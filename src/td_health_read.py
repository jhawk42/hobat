"""Bounded public read projections for stored health assessments."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from extaddr_device_label_map import load_extaddr_device_label_map
from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
from td_health_manifest import load_health_manifest
from td_health_observation_store import HEALTH_DATABASE_FILENAME
from td_health_sqlite import SQLiteHealthStore


MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
FINDING_GROUP_PRESENTATION = {
    "network.border-router-redundancy": (0, "Border Router Redundancy"),
    "network.router-redundancy": (1, "Router Redundancy"),
    "network.external-routing": (2, "External Routing"),
    "network.current-path-redundancy": (3, "Router path redundancy"),
    "device.observed": (4, "Observed Devices"),
    "device.missing": (5, "Missing from latest observation"),
    "device.offline": (6, "Offline Devices"),
    "network.observed-link-quality-ratios": (7, "Observed link quality distribution"),
    "relationship.bidirectional-lq3": (8, "Strong bidirectional link"),
    "relationship.directional-quality": (9, "Directional link quality needs attention"),
    "device.attachment-failure": (12, "Attachment failure"),
}


def _finding_group_presentation(rule_id: str, title: str) -> tuple[int, str]:
    return FINDING_GROUP_PRESENTATION.get(
        rule_id,
        (10 if "mac" in rule_id.lower() else 11 if "mle" in rule_id.lower() else 13, title),
    )


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
        database_path = data_dir / HEALTH_DATABASE_FILENAME
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

    def _finding(self, row: dict, labels: dict[str, str]) -> dict[str, Any]:
        device_ids = _decode_json(row["device_ids_json"], field="device IDs")
        relationship_ids = _decode_json(
            row["relationship_ids_json"], field="relationship IDs"
        )
        evidence = _decode_json(row["evidence_json"], field="evidence")
        router_ids = ()
        if row["rule_id"] == "network.current-path-redundancy":
            router_ids = tuple(sorted({
                *evidence.get("solePathRouterIds", ()),
                *evidence.get("alternatePathRouterIds", ()),
            }))
        return {
            "findingId": row["finding_id"],
            "ruleId": row["rule_id"],
            "status": row["status"],
            "scope": row["scope"],
            "rank": row["rank"],
            "title": row["title"],
            "summary": row["summary"],
            "whyItMatters": row["why_it_matters"],
            "evidence": evidence,
            "confidence": row["confidence"],
            "action": row["action"],
            "verify": row["verify"],
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
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for finding in findings:
            key = (finding["ruleId"], finding["status"], finding["scope"])
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
            _, title = _finding_group_presentation(key[0], children[0]["title"])
            result.append(
                {
                    "groupId": f"finding-group:{digest}",
                    "ruleId": key[0],
                    "status": key[1],
                    "scope": key[2],
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
                _finding_group_presentation(group["ruleId"], group["title"])[0],
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
            self._finding(item, labels)
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
            "schemaVersion": 1,
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
        return {
            "schemaVersion": 1,
            "readOnly": True,
            "history": True,
            "rosterMutation": "cli-only",
            "datasets": sorted(load_health_manifest().datasets),
            **self.store.store_capabilities(),
        }