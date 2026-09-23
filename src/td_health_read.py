"""Bounded public read projections for stored health assessments."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from extaddr_device_label_map import load_extaddr_device_label_map
from td_health_comparison import ordered_reasons
from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
from td_health_manifest import ROSTER_FIELDS, load_health_manifest
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_observation_model import device_id_from_ext_address, network_id_from_ext_pan_id
from td_health_sqlite import SQLiteHealthStore
from td_health_rules import HEALTH_RULE_CATALOG, HealthRuleCatalogError


MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
# Scope-namespaced order bases leave room to insert new rule_ids without renumbering neighbors.
NETWORK_ORDER_BASE = 1000
DEVICE_ORDER_BASE = 2000
RELATIONSHIP_ORDER_BASE = 3000
UNKNOWN_ORDER_BASE = 9000
_SCOPE_ORDER_BASE = {
    "network": NETWORK_ORDER_BASE,
    "observation": NETWORK_ORDER_BASE,
    "device": DEVICE_ORDER_BASE,
    "relationship": RELATIONSHIP_ORDER_BASE,
}

_NORMALIZED_EVIDENCE_KINDS = frozenset(
    {"snapshot", "since-reset", "historical", "expected-state", "active-probe"}
)
_LEGACY_EVIDENCE_KIND_MAP = {
    "current": "snapshot",
    "cumulative": "since-reset",
    "lifetime": "since-reset",
}


def _uses_catalog_contract(evaluator_version: object) -> bool:
    if not isinstance(evaluator_version, str) or not evaluator_version.startswith("snapshot-v"):
        return False
    try:
        return int(evaluator_version.removeprefix("snapshot-v")) >= 10
    except ValueError:
        return False


def _finding_group_presentation(
    rule_id: str, title: str, variant: str | None = None
) -> tuple[int, str]:
    try:
        rule = HEALTH_RULE_CATALOG.rule(rule_id)
        return (rule.order, rule.title_for(variant))
    except HealthRuleCatalogError:
        pass
    base = _SCOPE_ORDER_BASE.get(rule_id.split(".", 1)[0], UNKNOWN_ORDER_BASE)
    return (base + 950, title)


class HealthReadError(RuntimeError):
    pass


class HealthUnavailableError(HealthReadError):
    pass


class HealthBusyError(HealthReadError):
    pass


class HealthCorruptStoreError(HealthReadError):
    pass


def _decode_json(value: object, *, field: str) -> Any:
    if not isinstance(value, str):
        raise HealthCorruptStoreError(f"Invalid stored {field}")
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise HealthCorruptStoreError(f"Invalid stored {field}") from exc


class TDHealthReadService:
    def __init__(self, data_dir: Path):
        database_path = data_dir / HOBAT_DATABASE_FILENAME
        if not database_path.is_file():
            raise HealthUnavailableError("Health store is not available")
        self.data_dir = data_dir
        try:
            self.store = SQLiteHealthStore(database_path, read_only=True)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise HealthBusyError("Health store is busy") from exc
            raise HealthCorruptStoreError("Health store cannot be opened") from exc
        except (sqlite3.DatabaseError, ValueError) as exc:
            raise HealthCorruptStoreError("Health store cannot be opened") from exc

    def _labels(self) -> dict[str, str]:
        path = self.data_dir / EXTADDR_DEVICE_LABEL_MAP_FILENAME
        try:
            labels = load_extaddr_device_label_map(path)
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            return {}
        return {
            str(ext_address).lower(): str(label)
            for ext_address, label in labels.items()
            if isinstance(ext_address, str) and isinstance(label, str)
        }

    @staticmethod
    def _display_name(device_id: str, labels: dict[str, str]) -> str:
        ext_address = device_id.removeprefix("extaddr:").lower()
        return labels.get(ext_address) or f"…{ext_address[-8:]}"

    def _roster_projection(self, data: dict, *, now: datetime, labels: dict[str, str],
                           detailed: bool) -> dict[str, Any]:
        policy = load_health_manifest().roster_policy
        device_id = data["deviceId"]
        fields: dict[str, dict] = {}
        for row in data["fields"]:
            field = row["field_key"]
            if field not in ROSTER_FIELDS:
                continue
            time = row["source_observed_at"]
            age = (now - datetime.fromisoformat(time)).total_seconds() if time else None
            if age is not None and age < 0:
                raise HealthCorruptStoreError("Invalid future roster source time")
            expiry = policy.freshness_seconds[field] if row["roster_policy_digest"] == policy.digest else None
            freshness = ("unknown" if age is None or row["roster_policy_digest"] != policy.digest
                         else "stale" if expiry is not None and age > expiry else "fresh")
            fields[field] = {
                "value": _decode_json(row["value_json"], field="roster value"),
                "valueClass": row["value_class"], "sourceObservedAt": time,
                "ageSeconds": int(age) if age is not None else None,
                "freshness": freshness, "confidence": row["confidence"],
                "sourceFile": row["source_file"] if row["source_file"] != "legacy-unknown" else None,
                "observationId": row["observation_id"], "conflictState": row["conflict_state"],
            }
        for conflict in data["conflicts"]:
            field = conflict["field_key"]
            item = fields.get(field)
            if not item or item["freshness"] != "fresh" or item["value"] != _decode_json(conflict["value_json"], field="alias value"):
                continue
            other_age = (now - datetime.fromisoformat(conflict["other_source_observed_at"])).total_seconds()
            own_age = item["ageSeconds"]
            if (other_age < 0 or other_age > policy.alias_collision_window_seconds or
                    (own_age is not None and own_age > policy.alias_collision_window_seconds)):
                continue
            expiry = policy.freshness_seconds[field]
            if expiry is not None and other_age > expiry:
                continue
            item["conflictState"] = "alias-collision"
            item["otherDeviceId"] = conflict["other_device_id"]
        ext_address = device_id.removeprefix("extaddr:")
        static_label = labels.get(ext_address)
        observed = fields.get("deviceLabel")
        if data["expectedLabel"]:
            label, origin = data["expectedLabel"], "expected"
        elif static_label:
            label, origin = static_label, "static"
        elif observed and observed["freshness"] == "fresh" and observed["conflictState"] == "none":
            label, origin = observed["value"], "observed"
        else:
            suffix = " (stale label)" if observed and observed["freshness"] == "stale" else ""
            label, origin = f"…{ext_address[-8:]}{suffix}", "fallback"
        counts = {state: sum(item["freshness"] == state for item in fields.values())
                  for state in ("fresh", "stale")}
        counts["conflicted"] = sum(item["conflictState"] != "none" for item in fields.values())
        times = [item["sourceObservedAt"] for item in fields.values() if item["sourceObservedAt"]]
        result = {"deviceId": device_id, "displayLabel": label, "labelOrigin": origin,
                  "labelAmbiguity": "stale label" if origin == "fallback" and observed and observed["freshness"] == "stale" else "none",
                  "lastObservedAt": max(times, default=None),
                  "lastEndpointPresenceAt": data["lastEndpointPresenceAt"],
                  "confidence": fields.get("extAddress", {}).get("confidence", "unknown"),
                  "ageSeconds": min((item["ageSeconds"] for item in fields.values()
                                     if item["ageSeconds"] is not None), default=None),
                  "fieldCounts": counts}
        if detailed:
            result["fields"] = {field: fields.get(field, {"value": None, "freshness": "absent",
                                                  "conflictState": "none"}) for field in ROSTER_FIELDS}
        return result

    def _disambiguate_roster_labels(self, devices: list[dict], *, network_id: str,
                                    now: datetime, labels: dict[str, str]) -> None:
        for label in {device["displayLabel"] for device in devices if device["labelOrigin"] != "fallback"}:
            targets = {device["deviceId"] for device in devices if device["displayLabel"] == label}
            collision = len(targets) > 1
            if not collision:
                static_ids = (f"extaddr:{address}" for address, value in labels.items() if value == label)
                for device_id in static_ids:
                    if device_id in targets:
                        continue
                    row = self.store.roster_device_row(network_id=network_id, device_id=device_id)
                    if row and self._roster_projection(row, now=now, labels=labels, detailed=False)["displayLabel"] == label:
                        collision = True
                        break
            offset = 0
            while not collision:
                candidates = self.store.roster_label_candidates(
                    network_id=network_id, label=label, limit=100, offset=offset,
                )
                for row in candidates:
                    if row["deviceId"] not in targets and row["fields"] and self._roster_projection(
                        row, now=now, labels=labels, detailed=False,
                    )["displayLabel"] == label:
                        collision = True
                        break
                if len(candidates) < 100:
                    break
                offset += len(candidates)
            if collision:
                for device in devices:
                    if device["displayLabel"] == label:
                        device["displayLabel"] = f"{label} · {device['deviceId'][-8:]} (duplicate label)"
                        device["labelAmbiguity"] = "duplicate label"

    def roster(self, *, network_id: str, limit: int = DEFAULT_PAGE_SIZE,
               offset: int = 0, read_time: datetime | None = None) -> dict[str, Any]:
        if (not network_id.startswith("extpan:") or
            network_id_from_ext_pan_id(network_id.removeprefix("extpan:")) != network_id or
            not 1 <= limit <= MAX_PAGE_SIZE or offset < 0):
            raise ValueError("Invalid roster page or network")
        self._require_roster_schema()
        now = read_time or datetime.now(timezone.utc)
        rows, total = self.store.roster_rows(network_id=network_id, limit=limit, offset=offset)
        labels = self._labels()
        devices = [self._roster_projection(row, now=now, labels=labels, detailed=False) for row in rows]
        self._disambiguate_roster_labels(devices, network_id=network_id, now=now, labels=labels)
        return {"schemaVersion": 1, "total": total, "limit": limit, "offset": offset,
            "devices": devices}

    def roster_device(self, *, network_id: str, device_id: str,
                      read_time: datetime | None = None) -> dict[str, Any] | None:
        if (not network_id.startswith("extpan:") or
            network_id_from_ext_pan_id(network_id.removeprefix("extpan:")) != network_id or
            not device_id.startswith("extaddr:") or
            device_id_from_ext_address(device_id.removeprefix("extaddr:")) != device_id):
            raise ValueError("Invalid roster network or device identity")
        self._require_roster_schema()
        row = self.store.roster_device_row(network_id=network_id, device_id=device_id)
        if not row:
            return None
        now = read_time or datetime.now(timezone.utc)
        labels = self._labels()
        device = self._roster_projection(row, now=now, labels=labels, detailed=True)
        self._disambiguate_roster_labels([device], network_id=network_id, now=now, labels=labels)
        return device

    def _require_roster_schema(self) -> None:
        with self.store._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_last_known'"
            ).fetchone() is None:
                raise HealthUnavailableError("Roster requires a processed schema-v4 health store")

    def _finding(
        self, row: dict, labels: dict[str, str], *, evaluator_version: str
    ) -> dict[str, Any]:
        device_ids = _decode_json(row["device_ids_json"], field="device IDs")
        relationship_ids = _decode_json(
            row["relationship_ids_json"], field="relationship IDs"
        )
        evidence = _decode_json(row["evidence_json"], field="evidence")
        if not isinstance(evidence, dict):
            raise HealthCorruptStoreError("Invalid stored evidence")
        evidence = dict(evidence)
        legacy = not _uses_catalog_contract(evaluator_version)
        try:
            rule = HEALTH_RULE_CATALOG.rule(row["rule_id"])
        except HealthRuleCatalogError:
            rule = None

        variant = evidence.get("presentationVariant")
        if variant is not None and not isinstance(variant, str):
            if not legacy:
                raise HealthCorruptStoreError("Invalid stored presentation variant")
            variant = None
        if rule is not None and variant is None and legacy:
            variant = next(
                (
                    name
                    for name, title in rule.variants.items()
                    if title == row["title"]
                ),
                None,
            )
        if rule is not None:
            try:
                title = rule.title_for(variant)
            except HealthRuleCatalogError as exc:
                if not legacy:
                    raise HealthCorruptStoreError(
                        "Invalid stored presentation variant"
                    ) from exc
                variant = None
                title = rule.title
            why_it_matters = rule.description
            action = rule.action
            verify = rule.verify
            evidence_kind = rule.evidence_kind
            materiality = rule.materiality
            action_key = rule.action_key
            verification_key = rule.verification_key
        else:
            title = row["title"]
            why_it_matters = row["why_it_matters"]
            action = row["action"]
            verify = row["verify"]
            stored_kind = evidence.get("evidenceKind")
            evidence_kind = _LEGACY_EVIDENCE_KIND_MAP.get(stored_kind, stored_kind)
            if evidence_kind not in _NORMALIZED_EVIDENCE_KINDS:
                evidence_kind = "historical"
            stored_materiality = evidence.get("materiality")
            materiality = (
                stored_materiality
                if stored_materiality in {"informational", "device", "relationship", "network"}
                else "informational"
            )
            action_key = f"health.{row['rule_id']}.action"
            verification_key = f"health.{row['rule_id']}.verify"

        evidence["evidenceKind"] = evidence_kind
        evidence["materiality"] = materiality
        if variant is not None:
            evidence["presentationVariant"] = variant
        router_ids = ()
        if row["rule_id"] == "network.current-path-redundancy":
            router_ids = tuple(sorted({
                *evidence.get("bridgeDeviceIds", ()),
                *evidence.get("articulationDeviceIds", ()),
                *evidence.get("solePathRouterIds", ()),
                *evidence.get("alternatePathRouterIds", ()),
            }))
        return {
            "findingId": row["finding_id"],
            "ruleId": row["rule_id"],
            "status": row["status"],
            "scope": row["scope"],
            "rank": row["rank"],
            "title": title,
            "summary": row["summary"],
            "whyItMatters": why_it_matters,
            "evidence": evidence,
            "presentationVariant": variant,
            "evidenceKind": evidence_kind,
            "materiality": materiality,
            "confidence": row["confidence"],
            "action": action,
            "verify": verify,
            "actionKey": action_key,
            "verificationKey": verification_key,
            "sourceFiles": _decode_json(row["source_files_json"], field="source files"),
            "deviceIds": device_ids,
            "relationshipIds": relationship_ids,
            "endpoints": [
                {"deviceId": device_id, "displayName": self._display_name(device_id, labels)}
                for device_id in device_ids
            ],
            "routerEndpoints": [
                {"deviceId": device_id, "displayName": self._display_name(device_id, labels)}
                for device_id in router_ids
            ],
        }

    @staticmethod
    def _group_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        for finding in findings:
            key = (
                finding["ruleId"],
                finding["status"],
                finding["scope"],
                finding.get("presentationVariant") or "",
            )
            grouped.setdefault(key, []).append(finding)
        result: list[dict[str, Any]] = []
        for key, children in grouped.items():
            device_ids = sorted({item for child in children for item in child["deviceIds"]})
            relationship_ids = sorted(
                {item for child in children for item in child["relationshipIds"]}
            )
            endpoints_by_id = {
                endpoint["deviceId"]: endpoint
                for child in children
                for endpoint in child["endpoints"]
            }
            digest = hashlib.sha256("\0".join(key).encode("utf-8")).hexdigest()[:20]
            variant = key[3] or None
            _, title = _finding_group_presentation(
                key[0], children[0]["title"], variant
            )
            result.append(
                {
                    "groupId": f"finding-group:{digest}",
                    "ruleId": key[0],
                    "status": key[1],
                    "scope": key[2],
                    "presentationVariant": variant,
                    "title": title,
                    "summary": children[0]["summary"],
                    "confidence": min(
                        (child["confidence"] for child in children),
                        key=lambda value: CONFIDENCE_ORDER.get(value, -1),
                    ),
                    "count": len(children),
                    "deviceIds": device_ids,
                    "relationshipIds": relationship_ids,
                    "endpoints": [endpoints_by_id[device_id] for device_id in device_ids],
                    "findings": children,
                }
            )
        return sorted(
            result,
            key=lambda group: (
                _finding_group_presentation(
                    group["ruleId"],
                    group["title"],
                    group.get("presentationVariant"),
                )[0],
                -max(child["rank"] for child in group["findings"]),
                group["groupId"],
            ),
        )

    def assessment(
        self,
        *,
        dataset_id: str | None = None,
        network_id: str | None = None,
        assessment_id: str | None = None,
        grouped: bool = True,
        status: str | None = None,
        scope: str | None = None,
        device_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any] | None:
        if dataset_id is not None:
            load_health_manifest().dataset(dataset_id)
        row = self.store.assessment_record(
            dataset_id=dataset_id,
            network_id=network_id,
            assessment_id=assessment_id,
        )
        if row is None:
            return None
        labels = self._labels()
        findings = [
            self._finding(
                item, labels, evaluator_version=row["evaluator_version"]
            )
            for item in self.store.finding_records(
                row["assessment_id"],
                status=status,
                scope=scope,
                device_id=device_id,
                limit=limit,
                offset=offset,
            )
        ]
        finding_count = self.store.finding_count(
            row["assessment_id"], status=status, scope=scope, device_id=device_id
        )
        return {
            "schemaVersion": 2,
            "assessmentId": row["assessment_id"],
            "observationId": row["observation_id"],
            "datasourceId": row["datasource_id"],
            "datasetId": row["dataset_id"],
            "networkId": row["network_id"],
            "networkName": row["network_name"],
            "status": row["status"],
            "confidence": row["confidence"],
            "completeness": row["completeness"],
            "observedAt": row["observed_at"],
            "assessedAt": row["assessed_at"],
            "policyVersion": row["policy_version"],
            "policyDigest": row["policy_digest"],
            "evaluatorVersion": row["evaluator_version"],
            "profileId": row["profile_id"],
            "coverage": _decode_json(row["coverage_json"], field="coverage"),
            "findingCount": finding_count,
            "limit": limit,
            "offset": offset,
            "findingGroups": self._group_findings(findings) if grouped else [],
            "findings": findings if not grouped else [],
        }

    def observations(
        self, *, network_id: str | None, limit: int, offset: int
    ) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "items": self.store.observation_records(
                network_id=network_id, limit=limit, offset=offset
            ),
            "limit": limit,
            "offset": offset,
        }

    @staticmethod
    def _comparison_header(row: dict[str, Any]) -> dict[str, Any]:
        pruned = not row["before_retained"] or not row["after_retained"]
        persisted_reasons = _decode_json(row["reasons_json"], field="comparison reasons")
        if not isinstance(persisted_reasons, list) or any(
            not isinstance(reason, str) for reason in persisted_reasons
        ):
            raise HealthCorruptStoreError("Invalid comparison reasons")
        try:
            reasons = list(ordered_reasons(set(persisted_reasons) | ({"baseline-pruned"} if pruned else set())))
        except ValueError as exc:
            raise HealthCorruptStoreError("Invalid comparison reasons") from exc
        return {
            "schemaVersion": 1, "comparisonId": row["comparison_id"],
            "comparisonVersion": row["comparison_version"],
            "beforeAssessmentId": row["before_assessment_id"],
            "afterAssessmentId": row["after_assessment_id"],
            "beforeObservationId": row["before_observation_id"],
            "afterObservationId": row["after_observation_id"],
            "baselineAssessmentId": row["before_assessment_id"],
            "baselineObservationId": row["before_observation_id"],
            "beforeObservedAt": row["before_observed_at"], "afterObservedAt": row["after_observed_at"],
            "observationCount": 2, "elapsedSeconds": row["elapsed_seconds"],
            "networkId": row["network_id"], "datasourceId": row["datasource_id"],
            "datasetId": row["dataset_id"], "profileId": row["profile_id"],
            "sourceSignature": row["source_signature"],
            "sampleContractVersion": row["sample_contract_version"],
            "evaluatorVersion": row["evaluator_version"],
            "beforeAssessmentDigest": row["before_assessment_digest"],
            "afterAssessmentDigest": row["after_assessment_digest"],
            "endpointPolicyDigest": row["endpoint_policy_digest"],
            "comparisonPolicyDigest": row["comparison_policy_digest"],
            "gapState": row["gap_state"], "resetState": row["reset_state"],
            "resetWitness": _decode_json(row["reset_witness_json"], field="reset witness"),
            "baselineState": "pruned" if pruned else row["baseline_state"],
            "persistedComparable": bool(row["comparable"]),
            "persistedReasons": persisted_reasons,
            "comparable": bool(row["comparable"]) and not pruned,
            "primaryReason": reasons[0] if reasons else None,
            "reasons": reasons, "itemCount": row["item_count"],
            "createdAt": row["created_at"],
        }

    def comparisons(self, *, network_id: str, dataset_id: str, limit: int,
                    offset: int) -> dict[str, Any]:
        if not network_id.startswith("extpan:"):
            raise ValueError("network must be a canonical network ID")
        load_health_manifest().dataset(dataset_id)
        rows, total = self.store.comparison_rows(
            network_id=network_id, dataset_id=dataset_id, limit=limit, offset=offset,
        )
        return {"schemaVersion": 1, "total": total, "limit": limit, "offset": offset,
                "items": [self._comparison_header(row) for row in rows]}

    def comparison(self, *, comparison_id: str, limit: int, offset: int) -> dict[str, Any] | None:
        record = self.store.comparison_row(comparison_id, limit=limit, offset=offset)
        if record is None:
            return None
        row, item_rows = record
        header = self._comparison_header(row)
        pruned = header["baselineState"] == "pruned"
        items = []
        for item in item_rows:
            persisted_reasons = _decode_json(item["reasons_json"], field="item reasons")
            if not isinstance(persisted_reasons, list) or any(
                not isinstance(reason, str) for reason in persisted_reasons
            ):
                raise HealthCorruptStoreError("Invalid item reasons")
            try:
                reasons = list(ordered_reasons(set(persisted_reasons) | ({"baseline-pruned"} if pruned else set())))
            except ValueError as exc:
                raise HealthCorruptStoreError("Invalid item reasons") from exc
            items.append({
                "itemId": item["item_id"], "scope": item["scope"],
                "subjectId": item["subject_id"], "itemKind": item["item_kind"],
                "metric": item["metric"], "unit": item["unit"],
                "denominatorKind": item["denominator_kind"],
                "beforeValue": _decode_json(item["before_json"], field="before value"),
                "afterValue": _decode_json(item["after_json"], field="after value"),
                "delta": None if pruned else _decode_json(item["delta_json"], field="delta"),
                "direction": None if pruned else item["direction"],
                "change": "unknown" if pruned else item["change"],
                "transition": None if pruned else item["transition_state"],
                "sampleCount": item["sample_count"],
                "sourceFiles": _decode_json(item["source_files_json"], field="source files"),
                "beforeSourceObservedAt": item["before_source_time"],
                "afterSourceObservedAt": item["after_source_time"],
                "resetState": item["reset_state"],
                "resetWitness": _decode_json(item["reset_witness_json"], field="item reset witness"),
                "beforeDeviceId": item["before_device_id"],
                "afterDeviceId": item["after_device_id"],
                "beforeRelationshipId": item["before_relationship_id"],
                "afterRelationshipId": item["after_relationship_id"],
                "persistedComparable": bool(item["comparable"]),
                "persistedReasons": persisted_reasons,
                "comparable": bool(item["comparable"]) and not pruned,
                "primaryReason": reasons[0] if reasons else None, "reasons": reasons,
            })
        return {**header, "limit": limit, "offset": offset, "items": items}

    def device(self, *, assessment_id: str, device_id: str) -> dict | None:
        row = self.store.device_record(
            assessment_id=assessment_id, device_id=device_id
        )
        if row is None:
            return None
        labels = self._labels()
        result = {
            "deviceId": row["device_id"],
            "role": row["role"],
            "isBorderRouter": bool(row["is_border_router"]),
            "sourceFiles": _decode_json(
            row.pop("source_files_json"), field="source files"
            ),
            "displayName": self._display_name(device_id, labels),
        }
        findings = self.assessment(assessment_id=assessment_id, grouped=False)
        result["findings"] = [
            finding
            for finding in (findings or {}).get("findings", [])
            if device_id in finding["deviceIds"]
        ]
        return result

    def capabilities(self) -> dict[str, Any]:
        capabilities = self.store.store_capabilities()
        return {
            "schemaVersion": 1,
            "readOnly": True,
            "history": True,
            **({"comparisonReadModel": 1} if capabilities["schemaVersion"] >= 4 else {}),
            "rosterMutation": "cli-only",
            "datasets": sorted(load_health_manifest().datasets),
            **capabilities,
        }