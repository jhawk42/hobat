"""Cache-only, digest-bound source-primary dataset materialization."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import ipaddress
import json
import logging
import math
import os
import re
import shutil
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ha_matter_ws_snapshots import MatterSnapshotSecurityError, assert_snapshot_safe
from ha_matter_ws_contract import MatterWsContractError
from merge_dataset import extract_records, merge_cached_records
from merge_policy_identity import identities_compatible
from merge_policy_mdns import is_matter_operational_mdns_record, merge_mdns_records, observed_service_network
from td_const import (
    HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME, HA_MATTER_WS_SERVER_INFO_FILENAME,
    HA_MATTER_WS_THREAD_DIAGNOSTICS_FILENAME,
    OTBR_CLI_BBR_FILENAME, OTBR_RESTAPI_ACTIONS_LIST_FILENAME,
    TD_DATA_DIR_ARG_HELP, UNIFIED_FILENAMES,
)
from td_dataset_catalog import (
    load_dataset_catalog, resolve_dataset, unique_json_object, validate_dataset_catalog,
)
from td_device_fields import get_canonical_omr_address, get_device_identity_keys
from td_network_identity import canonical_ext_pan_id
from td_record_merge import values_equivalent
from util_data import network_scope_path, resolve_data_dir


CONTRACT_VERSION = "unified-v1"
BUILDER_CONTRACT = "unified-assembly-v5"
_NETWORK = re.compile(r"extpan:[0-9a-f]{16}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class UnifiedDatasetError(ValueError):
    """A missing, invalid, changing, stale, or uncommitted cached generation."""


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True,
                       allow_nan=False) + "\n").encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fingerprint(value: Any) -> str:
    return _digest(_json_bytes(value))


def _reject_constant(value: str) -> None:
    raise UnifiedDatasetError(f"Non-finite JSON value: {value}")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        _reject_constant(value)
    return result


def _parse(data: bytes, filename: str) -> Any:
    try:
        return json.loads(data, object_pairs_hook=unique_json_object,
                          parse_constant=_reject_constant, parse_float=_finite_float)
    except (ValueError, UnicodeError) as exc:
        raise UnifiedDatasetError(f"Invalid cached JSON: {filename}: {exc}") from exc


@dataclass(frozen=True)
class CachedInput:
    filename: str
    content: bytes | None
    mtime_ns: int | None

    @property
    def digest(self) -> str | None:
        return None if self.content is None else _digest(self.content)


def _read_stable(data_dir: Path, filename: str) -> CachedInput:
    path = data_dir / filename
    try:
        stream = path.open("rb")
    except FileNotFoundError:
        return CachedInput(filename, None, None)
    try:
        with stream:
            before = os.fstat(stream.fileno())
            content = stream.read()
            after = os.fstat(stream.fileno())
        current = path.stat()
    except FileNotFoundError:
        raise UnifiedDatasetError(f"Changing cached input: {filename}")
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ) or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
            current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns
    ):
        raise UnifiedDatasetError(f"Changing cached input: {filename}")
    return CachedInput(filename, content, before.st_mtime_ns)


def _recheck(data_dir: Path, captured: Sequence[CachedInput]) -> None:
    for original in captured:
        current = _read_stable(data_dir, original.filename)
        if current.digest != original.digest or current.mtime_ns != original.mtime_ns:
            raise UnifiedDatasetError(f"Cached input changed during build: {original.filename}")


def _source_time(payload: Any, item: CachedInput, now: datetime, *,
                 extractor: str | None = None) -> tuple[str | None, str]:
    if extractor in {"ha-border-routers", "ha-native-topology"}:
        from ha_matter_ws_unified import native_observation_epoch
        if not (extractor == "ha-border-routers" and isinstance(payload, dict)
                and payload.get("borderRouters") == []):
            payload = {"sourceObservedAt": native_observation_epoch(extractor, payload)}
    candidates = []
    records = payload if isinstance(payload, list) else [payload]
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in ("sourceObservedAt", "observedAt", "capturedAt", "completedAt", "capturedAtEpoch",
                    "captured_at_epoch"):
            if key not in record:
                continue
            value = record[key]
            try:
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if not math.isfinite(value):
                        raise ValueError("Non-finite source time")
                    parsed = datetime.fromtimestamp(value, timezone.utc)
                elif isinstance(value, str):
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        raise ValueError("Source time lacks timezone")
                    parsed = parsed.astimezone(timezone.utc)
                else:
                    raise ValueError("Invalid source time")
                if parsed > now or parsed.timestamp() <= 0:
                    raise ValueError("Unavailable source time")
                candidates.append(parsed)
            except (ValueError, OverflowError, OSError):
                return None, "invalid-source-time"
            break
    if candidates:
        return max(candidates).isoformat(), "embedded"
    if item.mtime_ns is not None:
        parsed = datetime.fromtimestamp(item.mtime_ns / 1_000_000_000, timezone.utc)
        if 0 < parsed.timestamp() <= now.timestamp():
            return parsed.isoformat(), "raw-file-mtime"
    return None, "unavailable-source-time"


def _observed_id(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return canonical_ext_pan_id(value)
    except ValueError as exc:
        raise UnifiedDatasetError(f"Invalid observed Extended PAN ID: {exc}") from exc


def _scope(sidecar: CachedInput, snapshot: CachedInput) -> tuple[str | None, str]:
    if sidecar.content is None:
        return None, "missing-sidecar"
    value = _parse(sidecar.content, sidecar.filename)
    if not isinstance(value, dict) or value.get("snapshotSha256") != snapshot.digest:
        raise UnifiedDatasetError(f"Invalid scope binding: {sidecar.filename}")
    if value.get("provenance") not in {"observed", "operator", "unknown"}:
        raise UnifiedDatasetError(f"Invalid scope provenance: {sidecar.filename}")
    ext_pan_id = _observed_id(value.get("extPanId"))
    if (value["provenance"] == "unknown") != (ext_pan_id is None):
        raise UnifiedDatasetError(f"Invalid scope identity: {sidecar.filename}")
    if value["provenance"] != "observed":
        return None, "unobserved-sidecar"
    return ext_pan_id, "observed"


def _record_scope(record: dict, file_scope: str | None) -> str | None:
    value = record.get("extPanId")
    if value is not None:
        observed = _observed_id(value)
        if file_scope is not None and observed != file_scope:
            raise UnifiedDatasetError("Record identity contradicts its observed scope")
        return observed
    return file_scope


def _extract(item: dict, payload: Any) -> list[dict]:
    filename = item["file"]
    extractor = item["extractor"]
    if extractor == "json-api":
        if isinstance(payload, dict) and "data" in payload:
            data = payload["data"]
            if isinstance(data, dict):
                payload = {"data": [data]}
            elif not isinstance(data, list):
                raise UnifiedDatasetError(f"Invalid JSON:API records: {filename}")
            else:
                payload = {"data": data}
        elif not isinstance(payload, list):
            raise UnifiedDatasetError(f"Expected JSON:API records: {filename}")
        records = payload["data"] if isinstance(payload, dict) else payload
        if any(not isinstance(record, dict) or (
            "attributes" in record and not isinstance(record["attributes"], dict)
        ) for record in records):
            raise UnifiedDatasetError(f"Invalid JSON:API record: {filename}")
    elif extractor in {"ha-inventory", "ha-border-routers", "ha-native-topology", "ha-projection"}:
        from ha_matter_ws_contract import MatterWsContractError
        from ha_matter_ws_unified import normalize_cached_ha_records
        try:
            payload = normalize_cached_ha_records(extractor, payload)
        except (MatterWsContractError, MatterSnapshotSecurityError) as exc:
            raise UnifiedDatasetError(f"Invalid cached HA product: {filename}: {exc}") from exc
    elif extractor == "raw-array":
        if filename == OTBR_CLI_BBR_FILENAME:
            from otbr_cli_bbr import extract_cached_bbr_records
            payload = extract_cached_bbr_records(payload)
        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
            raise UnifiedDatasetError(f"Expected an array of records: {filename}")
    else:
        raise UnifiedDatasetError(f"Source converter is not enabled: {extractor}")
    rows = extract_records(filename, payload)
    try:
        assert_snapshot_safe(rows)
    except MatterSnapshotSecurityError as exc:
        raise UnifiedDatasetError(f"Unsafe cached records: {filename}: {exc}") from exc
    if filename.startswith("td-mdns-scopes-"):
        if any(not isinstance(row.get("scope"), str) or not any((
            row.get("name"),
            row.get("serviceInfo", {}).get("name") if isinstance(row.get("serviceInfo"), dict) else None,
            row.get("serviceInfo", {}).get("key") if isinstance(row.get("serviceInfo"), dict) else None,
        )) for row in rows):
            raise UnifiedDatasetError(f"Invalid service identity: {filename}")
        for row in rows:
            try:
                network = observed_service_network(row)
            except ValueError as exc:
                raise UnifiedDatasetError(f"Invalid service network: {filename}: {exc}") from exc
            if network is not None:
                if row.get("extPanId") is not None and _observed_id(row["extPanId"]) != network:
                    raise UnifiedDatasetError(f"Contradictory service network: {filename}")
                row["extPanId"] = network
    elif rows and not any(get_device_identity_keys(row) or (
        isinstance(row.get("id"), (str, int)) and not isinstance(row.get("id"), bool) and row["id"] != ""
    ) for row in rows):
        raise UnifiedDatasetError(f"No usable record identities: {filename}")
    return rows


def _validate_outcome(payload: Any, filename: str, *, source: str | None = None) -> bool:
    if source == "ha-matter-ws":
        from ha_matter_ws_contract import MatterWsContractError
        from ha_matter_ws_unified import validate_cached_outcome
        try:
            return validate_cached_outcome(filename, payload)
        except (MatterWsContractError, MatterSnapshotSecurityError) as exc:
            raise UnifiedDatasetError(f"Invalid cached HA outcome: {filename}: {exc}") from exc
    if (not isinstance(payload, dict) or not isinstance(payload.get("deviceResults"), list)
            or any(not isinstance(item, dict) or not isinstance(item.get("status"), str)
                   for item in payload["deviceResults"])
            or ("partial" in payload and type(payload["partial"]) is not bool)):
        raise UnifiedDatasetError(f"Invalid collection outcome: {filename}")
    from td_health_processor import _outcome_state
    return _outcome_state(payload).value == "complete"


def _field_paths(value: dict, prefix: str = "") -> dict[str, Any]:
    fields = {}
    for key, child in value.items():
        if key.startswith("_"):
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict) and child:
            fields.update(_field_paths(child, path))
        else:
            fields[path] = child
            if isinstance(child, list):
                for item in child:
                    if not isinstance(item, dict):
                        continue
                    identity = {
                        key: item[key] for key in (
                            "extAddress", "rloc16", "routerId", "childId", "endpointId",
                            "nativeSourceId", "nativeTargetId", "networkType",
                        ) if key in item
                    }
                    if key == "mdnsRecords" and "_unifiedRecordId" in item:
                        identity = {"_unifiedRecordId": item["_unifiedRecordId"]}
                    item_path = f"{path}[{_fingerprint(identity or item)}]"
                    fields.update(_field_paths(item, item_path))
    return fields


def _record_id(record: dict, network: str | None, occurrence: int = 0) -> str:
    identities = get_device_identity_keys(record)
    identity = sorted(identities) if identities else ["content:" + _fingerprint(record)]
    return _fingerprint({"network": network, "identity": identity, "occurrence": occurrence})


def _embed_mdns_services(rows: list[dict], record_sources: dict, field_sources: dict) -> list[dict]:
    from ha_matter_ws_unified import is_thread_record

    def address_key(record: dict) -> str | None:
        value = get_canonical_omr_address(record)
        if not value:
            return None
        try:
            address = ipaddress.IPv6Address(value)
        except ipaddress.AddressValueError:
            logging.warning("Invalid OMR address retained without mDNS association: %r", value)
            return None
        if address.is_unspecified or address.is_multicast or address.is_link_local or address.is_loopback:
            return None
        return str(address)

    devices: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("type") == "service" or row.get("relationshipOnly") or not is_thread_record(row):
            continue
        address = address_key(row)
        if address is not None:
            devices.setdefault(address, []).append(row)
    embedded = set()
    for service in rows:
        scope = service.get("scope")
        is_hap_udp = isinstance(scope, str) and scope.strip().lower() == "_hap._udp.local."
        if service.get("type") != "service" or not (
            is_matter_operational_mdns_record(service) or is_hap_udp
        ):
            continue
        address = address_key(service)
        if address is None:
            continue
        candidates = [
            row for row in devices.get(address, []) if (
                service["_networkInstance"] is None
                or service["_networkInstance"] == row["_networkInstance"]
            )
        ]
        if len(candidates) != 1 or not identities_compatible(candidates[0], service, "strict-omr"):
            continue
        device = candidates[0]
        device_id, service_id = device["_unifiedRecordId"], service["_unifiedRecordId"]
        device.setdefault("mdnsRecords", []).append(service)
        device["_source_files"] = list(dict.fromkeys([
            *device["_source_files"], *service["_source_files"],
        ]))
        origins = record_sources.pop(service_id)
        record_sources[device_id].extend(origins)
        fields = field_sources[device_id]
        fields.setdefault("mdnsRecords", []).extend(origins)
        prefix = f"mdnsRecords[{_fingerprint({'_unifiedRecordId': service_id})}]"
        for path, sources in field_sources.pop(service_id).items():
            fields[f"{prefix}.{path}"] = sources
        embedded.add(service_id)
    return [row for row in rows if row["_unifiedRecordId"] not in embedded]


def _assemble(
    sources: list[tuple[str | None, str, list[dict]]],
) -> tuple[list[dict], dict, dict]:
    rows: list[dict] = []
    record_sources: dict = {}
    field_sources: dict = {}
    scopes = dict.fromkeys(scope for scope, _, _ in sources)
    for scope in scopes:
        grouped = [(name, records) for source_scope, name, records in sources if source_scope == scope]
        # Service identity is not a Thread-node identity, even when it carries an XPAN.
        service_rows: dict[str, tuple[dict, list[tuple[str, dict]]]] = {}
        device_inputs = []
        for filename, records in grouped:
            if filename.startswith("td-mdns-scopes-"):
                for record in records:
                    service = record.get("serviceInfo", record.get("service_info", {}))
                    if not isinstance(service, dict):
                        raise UnifiedDatasetError(f"Invalid serviceInfo: {filename}")
                    key = _fingerprint({"scope": record.get("scope"),
                                        "name": record.get("name", service.get("name")),
                                        "key": service.get("key"), "server": service.get("server")})
                    if not any((record.get("name"), service.get("name"), service.get("key"))):
                        key = _fingerprint(record)
                    if key in service_rows:
                        previous, origins = service_rows[key]
                        service_rows[key] = (merge_mdns_records(previous, record), origins + [(filename, record)])
                    else:
                        service_rows[key] = (deepcopy(record), [(filename, record)])
            else:
                device_inputs.append((filename, records))
        merged, origins = merge_cached_records(device_inputs, scope)
        for record, contributors in service_rows.values():
            record["type"] = "service"
            record["_source_files"] = list(dict.fromkeys(name for name, _ in contributors))
            origins[len(merged)] = contributors
            merged.append(record)
        occurrences: dict[str, int] = {}
        source_occurrences: dict[tuple[str, str], int] = {}
        for index, record in enumerate(merged):
            base_id = _record_id(record, scope)
            occurrence = occurrences.get(base_id, 0)
            occurrences[base_id] = occurrence + 1
            record_id = _record_id(record, scope, occurrence)
            record["_unifiedRecordId"] = record_id
            record["_networkInstance"] = f"extpan:{scope}" if scope else None
            contributors = []
            for name, original in origins[index]:
                source_key = (name, _record_id(original, scope))
                source_occurrence = source_occurrences.get(source_key, 0)
                source_occurrences[source_key] = source_occurrence + 1
                contributors.append({
                    "filename": name, "recordId": _record_id(original, scope, source_occurrence),
                    "fields": _field_paths(original),
                })
            record_sources[record_id] = [
                {key: value for key, value in origin.items() if key != "fields"}
                for origin in contributors
            ]
            field_sources[record_id] = {}
            for path, value in _field_paths(record).items():
                matches = [origin for origin in contributors
                           if path in origin["fields"] and values_equivalent(value, origin["fields"][path])]
                if not matches and isinstance(value, list):
                    matches = [origin for origin in contributors if path in origin["fields"]]
                field_sources[record_id][path] = [
                    {"filename": origin["filename"], "recordId": origin["recordId"]}
                    for origin in matches
                ]
            rows.append(record)
    return _embed_mdns_services(rows, record_sources, field_sources), record_sources, field_sources


def _artifact_names(entry: dict) -> list[str]:
    row_file = entry["files"][0]
    recipe = entry["unified"]
    return [row_file, network_scope_path(row_file).name,
            *[recipe[key] for key in ("identityFile", "outcomeFile") if recipe[key] is not None]]


def _link_count(rows: list[dict]) -> int:
    count = 0
    for row in rows:
        for field in ("children", "childTable", "routerNeighbors", "links1", "links2", "links3",
                      "nativeRelationships"):
            if isinstance(row.get(field), list):
                count += len(row[field])
        route = row.get("route")
        if isinstance(route, dict) and isinstance(route.get("routeData"), list):
            count += len(route["routeData"])
    return count


def _dependencies(catalog: dict, entry: dict) -> list[dict]:
    by_file = {item["files"][0]: item for item in catalog["datasets"] if "unified" in item}
    return [by_file[item["file"]] for item in entry["unified"]["inputs"]]


def _composition_inputs(data_dir: Path, entry: dict, catalog: dict, *,
                        allow_partial: bool, network: str | None, now: datetime) -> dict:
    captured, inputs, sources, identities, missing, health_reasons = [], [], [], [], [], []
    raw_inputs, dependency_states, dependency_reports = [], {}, {}
    for dependency in _dependencies(catalog, entry):
        filename = dependency["files"][0]
        requested_network = None if dependency["source"] == "mdns" else network
        failure = None
        state = "complete"
        try:
            _build_locked(data_dir, dependency, catalog, allow_partial=allow_partial,
                          network=requested_network, now=now)
            report = read_generation(data_dir, dependency, verify_inputs=True)
        except UnifiedDatasetError as exc:
            message = str(exc)
            if not (message.startswith(("No usable cached record inputs",
                                        "Missing required cached inputs:",
                                        "Selected network has not been observed:"))):
                raise
            failure = message
            state = "excluded" if message.startswith("Selected network") else "missing"
            missing.append(filename)
            health_reasons.append(f"{state}-source:{dependency['source']}:{message}")
        cached = _read_stable(data_dir, filename)
        sidecar = _read_stable(data_dir, network_scope_path(filename).name)
        captured.extend((cached, sidecar))
        metadata = {
            "filename": filename, "role": "records", "sha256": cached.digest,
            "size": len(cached.content) if cached.content is not None else 0,
            "scopeSha256": sidecar.digest,
            "status": ("excluded" if cached.content is not None else "missing") if failure else "selected",
        }
        inputs.append(metadata)
        if failure:
            dependency_states[dependency["source"]] = {"status": state, "reason": failure}
            # Bind absent/failed dependency evidence too; a later cache arrival is not a no-op.
            for item in dependency["unified"]["inputs"]:
                raw = _read_stable(data_dir, item["file"])
                scope = _read_stable(data_dir, network_scope_path(item["file"]).name)
                captured.extend((raw, scope))
                raw_inputs.append({"filename": item["file"], "role": item["role"],
                                   "sha256": raw.digest, "scopeSha256": scope.digest,
                                   "status": "excluded" if raw.content is not None else "missing"})
            continue
        state = report["materializationState"]
        if state == "partial":
            missing.append(filename)
        dependency_marker = _read_stable(data_dir, dependency["unified"]["reportFile"])
        if dependency_marker.content is None or _parse(
            dependency_marker.content, dependency_marker.filename
        ) != report:
            raise UnifiedDatasetError("Dependency report changed during composition")
        metadata.update({
            "sourceObservedAt": max((item["sourceObservedAt"] for item in report["inputs"]
                                     if item.get("sourceObservedAt")), default=None),
            "timeProvenance": "original-evidence",
            "dependencyGenerationId": report["generationId"],
            "dependencyReportSha256": dependency_marker.digest,
        })
        dependency_reports[filename] = report
        dependency_states[dependency["source"]] = {
            "status": state, "observedAt": metadata["sourceObservedAt"], "coverage": report["coverage"],
        }
        health_reasons.extend(f"{dependency['source']}:{reason}"
                              for reason in report["coverage"]["healthReasons"]
                              if dependency["source"] != "mdns")
        for name in [*_artifact_names(dependency), dependency["unified"]["reportFile"]]:
            artifact = _read_stable(data_dir, name)
            expected = (dependency_marker.digest if name == dependency_marker.filename
                        else report["artifactDigests"][name])
            if artifact.digest != expected:
                raise UnifiedDatasetError(f"Dependency artifact changed during composition: {name}")
            captured.append(artifact)
        metadata["selectedRecordCount"] = 0
        metadata["excludedRecordCount"] = 0
        if report["networkInstance"] is not None:
            identities.append((report["networkInstance"][7:], None, metadata))
        declared = {item["file"]: item for item in dependency["unified"]["inputs"]}
        for original in report["inputs"]:
            raw_inputs.append(deepcopy(original))
            raw = _read_stable(data_dir, original["filename"])
            scope = _read_stable(data_dir, network_scope_path(original["filename"]).name)
            captured.extend((raw, scope))
            if (raw.digest != original["sha256"] or scope.digest != original["scopeSha256"]
                    or (original.get("timeProvenance") == "raw-file-mtime"
                        and raw.mtime_ns != original.get("rawMtimeNs"))):
                raise UnifiedDatasetError(f"Changing dependency evidence: {raw.filename}")
            if original["status"] != "selected" or original["role"] not in {"records", "projection"}:
                continue
            payload = _parse(raw.content, raw.filename)
            records = _extract(declared[raw.filename], payload)
            file_scope, _ = _scope(scope, raw)
            from ha_matter_ws_unified import is_thread_record
            grouped: dict[str | None, list[dict]] = {}
            for record in records:
                inherited_scope = (None if dependency["source"] == "mdns"
                                   and record.get("extPanId") is None else file_scope)
                record_scope = (_record_scope(record, inherited_scope)
                                if dependency["source"] != "ha-matter-ws" or is_thread_record(record)
                                else None)
                if network is not None and record_scope is not None and record_scope != network[7:]:
                    metadata["excludedRecordCount"] += 1
                    continue
                metadata["selectedRecordCount"] += 1
                grouped.setdefault(record_scope, []).append(record)
            if not records:
                grouped[file_scope] = []
            sources.extend((record_scope, raw.filename, records)
                           for record_scope, records in grouped.items())
        if metadata["excludedRecordCount"] and not metadata["selectedRecordCount"]:
            metadata["status"] = "excluded"
            dependency_reports.pop(filename)
            missing.append(filename)
            dependency_states[dependency["source"]] = {
                "status": "excluded", "reason": "all-records-outside-selected-network",
                "observedAt": metadata["sourceObservedAt"],
            }
    return {
        "captured": captured, "inputs": inputs, "sources": sources, "identities": identities,
        "missing": missing, "health_reasons": list(dict.fromkeys(health_reasons)),
        "raw_inputs": raw_inputs, "dependency_states": dependency_states,
        "dependency_reports": dependency_reports,
    }


def read_generation(data_dir: Path, entry: dict, *, verify_inputs: bool = False,
                    catalog: dict | None = None) -> dict:
    """Verify one committed generation without repairing or refreshing anything."""
    recipe = entry["unified"]
    marker = _read_stable(data_dir, recipe["reportFile"])
    if marker.content is None:
        raise UnifiedDatasetError(f"Missing Unified report: {recipe['reportFile']}")
    report = _parse(marker.content, marker.filename)
    if (not isinstance(report, dict) or report.get("contractVersion") != CONTRACT_VERSION
            or report.get("datasetId") != entry["value"] or report.get("source") != entry["source"]
            or not isinstance(report.get("generationId"), str)
            or not _DIGEST.fullmatch(report["generationId"])
            or report.get("materializationState") not in {"complete", "partial"}
            or report.get("healthState") not in {"complete", "partial", "degraded", "unavailable", "ineligible"}
            or type(report.get("rowCount")) is not int or report["rowCount"] < 0
            or type(report.get("linkCount")) is not int or report["linkCount"] < 0
            or not isinstance(report.get("coverage"), dict)
            or not isinstance(report.get("artifactDigests"), dict)
            or set(report["artifactDigests"]) != set(_artifact_names(entry))):
        raise UnifiedDatasetError(f"Invalid Unified report: {marker.filename}")
    inputs = report.get("inputs")
    if (not isinstance(inputs, list) or len(inputs) != len(recipe["inputs"])
            or any(not isinstance(item, dict) for item in inputs)):
        raise UnifiedDatasetError("Invalid Unified evidence closure")
    for item, declared in zip(inputs, recipe["inputs"], strict=True):
        if (item.get("filename") != declared["file"] or item.get("role") != declared["role"]
                or item.get("status") not in {"selected", "missing", "excluded"}
                or (item["status"] == "missing" and item.get("sha256") is not None)
                or (item["status"] != "missing" and (
                    not isinstance(item.get("sha256"), str) or not _DIGEST.fullmatch(item["sha256"])))):
            raise UnifiedDatasetError("Invalid Unified input metadata")
    selected = report.get("networkInstance")
    if selected is not None and (not isinstance(selected, str) or not _NETWORK.fullmatch(selected)):
        raise UnifiedDatasetError("Invalid Unified network instance")
    if report.get("recipeDigest") != _fingerprint(recipe):
        raise UnifiedDatasetError("Unified recipe changed; rebuild the cached generation")
    generation_contract = {
        "contractVersion": CONTRACT_VERSION, "datasetId": entry["value"], "source": entry["source"],
        "inputs": inputs, "recipeDigest": report["recipeDigest"],
        "authorityDigest": report.get("authorityDigest"),
        "networkInstance": selected[7:] if selected else None,
    }
    if "builderContract" in report:
        if report["builderContract"] not in {
            "unified-assembly-v2", "unified-assembly-v3", "unified-assembly-v4", BUILDER_CONTRACT,
        }:
            raise UnifiedDatasetError("Unsupported Unified assembly contract")
        generation_contract["builderContract"] = report["builderContract"]
    if entry["source"] == "multi-source":
        generation_contract["rawInputsDigest"] = report.get("rawInputsDigest")
    expected_generation = _fingerprint(generation_contract)
    if report["generationId"] != expected_generation:
        raise UnifiedDatasetError("Unified generation fingerprint mismatch")
    artifacts = {}
    for filename, digest in report["artifactDigests"].items():
        captured = _read_stable(data_dir, filename)
        if captured.content is None or captured.digest != digest:
            raise UnifiedDatasetError(f"Mixed or incomplete Unified generation: {filename}")
        artifacts[filename] = captured
    rows = _parse(artifacts[entry["files"][0]].content, entry["files"][0])
    if (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
            or len(rows) != report["rowCount"]
            or _link_count(rows) != report["linkCount"]
            or report.get("snapshotSha256") != artifacts[entry["files"][0]].digest):
        raise UnifiedDatasetError("Invalid Unified rows")
    try:
        assert_snapshot_safe(rows)
    except MatterSnapshotSecurityError as exc:
        raise UnifiedDatasetError(f"Unsafe Unified generation: {exc}") from exc
    record_ids = [row.get("_unifiedRecordId") for row in rows]
    if (any(not isinstance(record_id, str) or not _DIGEST.fullmatch(record_id) for record_id in record_ids)
            or len(set(record_ids)) != len(record_ids)
            or not isinstance(report.get("recordSources"), dict)
            or not isinstance(report.get("fieldSources"), dict)
            or set(report["recordSources"]) != set(record_ids)
            or set(report["fieldSources"]) != set(record_ids)):
        raise UnifiedDatasetError("Invalid Unified record lineage")
    for key in ("identityFile", "outcomeFile"):
        filename = recipe[key]
        if filename is not None:
            companion = _parse(artifacts[filename].content, filename)
            if (not isinstance(companion, dict)
                    or companion.get("generationId") != report["generationId"]
                    or companion.get("snapshotSha256") != report["snapshotSha256"]):
                raise UnifiedDatasetError(f"Invalid Unified companion: {filename}")
    scope_file = network_scope_path(entry["files"][0]).name
    scope = _parse(artifacts[scope_file].content, scope_file)
    if (not isinstance(scope, dict) or scope.get("snapshotSha256") != report["snapshotSha256"]
            or scope.get("generationId") != report["generationId"]):
        raise UnifiedDatasetError("Invalid Unified network sidecar")
    evidence_captures = []
    if verify_inputs:
        declared = {item["file"] for item in recipe["inputs"]}
        for item in inputs:
            filename = item["filename"]
            if filename not in declared:
                raise UnifiedDatasetError("Undeclared Unified evidence")
            current = _read_stable(data_dir, filename)
            evidence_captures.append(current)
            if current.digest != item.get("sha256"):
                raise UnifiedDatasetError(f"Stale Unified evidence: {filename}")
            if item.get("timeProvenance") == "raw-file-mtime" and current.mtime_ns != item.get("rawMtimeNs"):
                raise UnifiedDatasetError(f"Stale Unified evidence time: {filename}")
            sidecar = _read_stable(data_dir, network_scope_path(filename).name)
            evidence_captures.append(sidecar)
            if sidecar.digest != item.get("scopeSha256"):
                raise UnifiedDatasetError(f"Stale Unified evidence scope: {filename}")
    if entry["source"] == "multi-source":
        catalog = load_dataset_catalog() if catalog is None else catalog
        raw_inputs = report.get("rawInputs")
        dependencies = _dependencies(catalog, entry)
        declared_raw = {item["file"]: item for dependency in dependencies
                        for item in dependency["unified"]["inputs"]}
        allowed = set(declared_raw)
        if (not isinstance(raw_inputs, list) or len(raw_inputs) != len(allowed)
                or any(not isinstance(item, dict) for item in raw_inputs)
                or {item.get("filename") for item in raw_inputs} != allowed):
            raise UnifiedDatasetError("Invalid transitive Unified evidence closure")
        if any(item.get("role") != declared_raw[item["filename"]]["role"]
               or item.get("status") not in {"selected", "missing", "excluded"}
               or (item.get("sha256") is not None
                   and (not isinstance(item["sha256"], str) or not _DIGEST.fullmatch(item["sha256"])))
               for item in raw_inputs):
            raise UnifiedDatasetError("Invalid transitive Unified evidence metadata")
        if report.get("rawInputsDigest") != _fingerprint(raw_inputs):
            raise UnifiedDatasetError("Invalid transitive Unified evidence fingerprint")
        if verify_inputs:
            for dependency, metadata in zip(dependencies, inputs, strict=True):
                if metadata["status"] != "selected":
                    continue
                dependency_report = read_generation(data_dir, dependency, verify_inputs=True, catalog=catalog)
                marker_input = _read_stable(data_dir, dependency["unified"]["reportFile"])
                if (dependency_report["generationId"] != metadata.get("dependencyGenerationId")
                        or marker_input.digest != metadata.get("dependencyReportSha256")):
                    raise UnifiedDatasetError("Stale Unified dependency generation")
                if any(original not in raw_inputs for original in dependency_report["inputs"]):
                    raise UnifiedDatasetError("Unified transitive evidence differs from its dependency")
            for item in raw_inputs:
                raw = _read_stable(data_dir, item["filename"])
                scope = _read_stable(data_dir, network_scope_path(item["filename"]).name)
                evidence_captures.extend((raw, scope))
                if (raw.digest != item.get("sha256") or scope.digest != item.get("scopeSha256")
                        or (item.get("timeProvenance") == "raw-file-mtime"
                            and raw.mtime_ns != item.get("rawMtimeNs"))):
                    raise UnifiedDatasetError(f"Stale transitive Unified evidence: {item['filename']}")
    admitted = {item["filename"] for item in report.get("rawInputs", inputs)
                if item["role"] in {"records", "projection"} and item["status"] == "selected"}
    for record_id in record_ids:
        origins = report["recordSources"][record_id]
        fields = report["fieldSources"][record_id]
        if (not isinstance(origins, list) or not origins or not isinstance(fields, dict)
                or any(not isinstance(origin, dict) or set(origin) != {"filename", "recordId"}
                       or origin["filename"] not in admitted
                       or not isinstance(origin["recordId"], str)
                       or not _DIGEST.fullmatch(origin["recordId"]) for origin in origins)
                or any(not isinstance(path, str) or not isinstance(lineage, list)
                       or any(origin not in origins for origin in lineage)
                       for path, lineage in fields.items())):
            raise UnifiedDatasetError("Invalid original-evidence Unified lineage")
    _recheck(data_dir, [marker, *artifacts.values(), *evidence_captures])
    return report


def read_original_evidence(data_dir: Path, entry: dict, *, catalog: dict | None = None) -> dict:
    """Return scoped originals, never aggregate rows, after one verified stable read."""
    catalog = load_dataset_catalog() if catalog is None else catalog
    report = read_generation(data_dir, entry, verify_inputs=True, catalog=catalog)
    dependencies = _dependencies(catalog, entry) if entry["source"] == "multi-source" else [entry]
    declarations = {
        item["file"]: {**item, "source": dependency["source"]}
        for dependency in dependencies for item in dependency["unified"]["inputs"]
    }
    metadata = report.get("rawInputs", report["inputs"])
    captures = [_read_stable(data_dir, entry["unified"]["reportFile"])]
    if _parse(captures[0].content, captures[0].filename) != report:
        raise UnifiedDatasetError("Unified report changed before evidence extraction")
    payloads, rows = {}, {}
    selected = report["networkInstance"]
    if selected is None or report["healthState"] == "unavailable":
        raise UnifiedDatasetError("One valid observed network is required for health")
    from ha_matter_ws_unified import is_thread_record
    for item in metadata:
        declaration = declarations[item["filename"]]
        raw = _read_stable(data_dir, item["filename"])
        scope = _read_stable(data_dir, network_scope_path(item["filename"]).name)
        captures.extend((raw, scope))
        if (raw.digest != item.get("sha256") or scope.digest != item.get("scopeSha256")
                or (item.get("timeProvenance") == "raw-file-mtime"
                    and raw.mtime_ns != item.get("rawMtimeNs"))):
            raise UnifiedDatasetError(f"Stale original evidence: {raw.filename}")
        if item["status"] != "selected" or raw.content is None:
            continue
        payload = _parse(raw.content, raw.filename)
        payloads[raw.filename] = payload
        if declaration["source"] == "mdns" or item["role"] != "records":
            continue
        file_scope, _ = _scope(scope, raw)
        records = []
        for record in _extract(declaration, payload):
            if declaration["source"] == "ha-matter-ws" and not is_thread_record(record):
                continue
            if _record_scope(record, file_scope) != selected[7:]:
                continue
            records.append(record)
        rows[raw.filename] = records
    _recheck(data_dir, captures)
    read_generation(data_dir, entry, verify_inputs=True, catalog=catalog)
    return {"report": report, "metadata": metadata, "declarations": declarations,
            "payloads": payloads, "rows": rows}


def read_generation_artifact(data_dir: Path, entry: dict, filename: str) -> tuple[CachedInput, dict]:
    report = read_generation(data_dir, entry)
    marker = _read_stable(data_dir, entry["unified"]["reportFile"])
    if marker.content is None or _parse(marker.content, marker.filename) != report:
        raise UnifiedDatasetError("Unified report changed during read")
    artifact = _read_stable(data_dir, filename)
    expected = marker.digest if filename == marker.filename else report["artifactDigests"].get(filename)
    if artifact.content is None or artifact.digest != expected:
        raise UnifiedDatasetError(f"Unified artifact changed during read: {filename}")
    _recheck(data_dir, [marker, artifact])
    return artifact, report


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write(path: Path, content: bytes) -> None:
    with path.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _clear_recovery(recovery: Path, names: list[str]) -> None:
    for name in [*names, "commit.json", "commit.pending.json", *[name + ".restore" for name in names]]:
        (recovery / name).unlink(missing_ok=True)
    recovery.rmdir()


def _recover(data_dir: Path, entry: dict) -> None:
    recovery = data_dir / f".td-unified-{entry['value']}.recovery"
    if not recovery.exists():
        return
    names = [*_artifact_names(entry), entry["unified"]["reportFile"]]
    marker = recovery / "commit.json"
    if not marker.exists():
        _clear_recovery(recovery, names)
        return
    state = _parse(marker.read_bytes(), marker.name)
    if (not isinstance(state, dict) or set(state) != {"present", "generationId", "previousGenerationId"}
            or not isinstance(state["present"], list)
            or any(name not in names for name in state["present"])
            or len(set(state["present"])) != len(state["present"])
            or not isinstance(state["generationId"], str)
            or not _DIGEST.fullmatch(state["generationId"])
            or (state["previousGenerationId"] is not None
                and (not isinstance(state["previousGenerationId"], str)
                     or not _DIGEST.fullmatch(state["previousGenerationId"])))):
        raise UnifiedDatasetError(f"Invalid recovery record: {recovery.name}")
    try:
        current = read_generation(data_dir, entry)
    except UnifiedDatasetError:
        current = None
    if current is None or current["generationId"] != state["generationId"]:
        for filename in names:
            if filename in state["present"]:
                backup = recovery / filename
                if not backup.is_file():
                    raise UnifiedDatasetError(f"Missing recovery artifact: {filename}")
                restore = recovery / (filename + ".restore")
                shutil.copy2(backup, restore)
                os.replace(restore, data_dir / filename)
            else:
                (data_dir / filename).unlink(missing_ok=True)
        _sync_directory(data_dir)
        if state["previousGenerationId"] is not None:
            restored = read_generation(data_dir, entry)
            if restored["generationId"] != state["previousGenerationId"]:
                raise UnifiedDatasetError("Restored generation does not match recovery record")
    _clear_recovery(recovery, names)
    _sync_directory(data_dir)


def _publish(data_dir: Path, entry: dict, artifacts: dict[str, bytes],
             captured: list[CachedInput], generation: str, previous_generation: str | None) -> None:
    names = [*_artifact_names(entry), entry["unified"]["reportFile"]]
    recovery = data_dir / f".td-unified-{entry['value']}.recovery"
    with tempfile.TemporaryDirectory(prefix=f".td-unified-{entry['value']}-", dir=data_dir) as directory:
        stage = Path(directory)
        for filename in names:
            _write(stage / filename, artifacts[filename])
        _sync_directory(stage)
        _recheck(data_dir, captured)
        recovery.mkdir()
        present = []
        for filename in names:
            old = data_dir / filename
            if old.exists():
                shutil.copy2(old, recovery / filename)
                with (recovery / filename).open("rb") as stream:
                    os.fsync(stream.fileno())
                present.append(filename)
        _write(recovery / "commit.pending.json", _json_bytes({
            "present": present, "generationId": generation, "previousGenerationId": previous_generation,
        }))
        os.link(recovery / "commit.pending.json", recovery / "commit.json")
        _sync_directory(recovery)
        (recovery / "commit.pending.json").unlink()
        _sync_directory(data_dir)
        _recheck(data_dir, captured)
        for filename in names:
            os.replace(stage / filename, data_dir / filename)
            _sync_directory(data_dir)
        read_generation(data_dir, entry)
        _clear_recovery(recovery, names)
        _sync_directory(data_dir)


def _summary(entry: dict, report: dict, *, no_op: bool) -> dict:
    return {
        "datasetId": entry["value"], "source": entry["source"],
        "materializationState": report["materializationState"],
        "healthState": report["healthState"], "generationId": report["generationId"],
        "artifacts": [*_artifact_names(entry), entry["unified"]["reportFile"]],
        "rowCount": report["rowCount"], "linkCount": report["linkCount"],
        "coverage": report["coverage"], "noOp": no_op,
    }


def _build_locked(data_dir: Path, entry: dict, catalog: dict, *, allow_partial: bool,
                  network: str | None, now: datetime) -> dict:
    _recover(data_dir, entry)
    recipe = entry["unified"]
    captured: list[CachedInput] = []
    inputs: list[dict] = []
    sources = []
    identities = []
    missing = []
    missing_optional = []
    health_reasons = []
    ha_source = entry["source"] == "ha-matter-ws"
    composition = None
    if entry["source"] == "multi-source":
        composition = _composition_inputs(data_dir, entry, catalog, allow_partial=allow_partial,
                                          network=network, now=now)
        captured = composition["captured"]
        inputs = composition["inputs"]
        sources = composition["sources"]
        identities = composition["identities"]
        missing = composition["missing"]
        health_reasons = composition["health_reasons"]
    ha_payloads: dict[str, Any] = {}
    if ha_source:
        from ha_matter_ws_unified import is_thread_record, validate_canonical_rows
    unresolved_native = []
    usable = len(composition["dependency_reports"]) if composition else 0
    for item in ([] if composition else recipe["inputs"]):
        filename = item["file"]
        cached = _read_stable(data_dir, filename)
        sidecar = _read_stable(data_dir, network_scope_path(filename).name)
        captured.extend((cached, sidecar))
        metadata = {"filename": filename, "role": item["role"], "sha256": cached.digest,
                    "size": len(cached.content) if cached.content is not None else 0,
                    "scopeSha256": sidecar.digest, "status": "missing"}
        inputs.append(metadata)
        if cached.content is None:
            (missing if item["required"] else missing_optional).append(filename)
            if item["role"] in {"identity", "outcome"}:
                health_reasons.append(f"missing-{item['role']}:{filename}")
            continue
        payload = _parse(cached.content, filename)
        observed_at, time_provenance = _source_time(payload, cached, now, extractor=item["extractor"])
        file_scope, scope_state = _scope(sidecar, cached)
        metadata.update({"status": "selected", "sourceObservedAt": observed_at,
                         "timeProvenance": time_provenance, "scopeState": scope_state})
        if ha_source:
            ha_payloads[filename] = payload
            metadata["observedNetwork"] = file_scope
        if time_provenance == "raw-file-mtime":
            metadata["rawMtimeNs"] = cached.mtime_ns
        if observed_at is None:
            health_reasons.append(f"unavailable-source-time:{filename}")
        if ha_source and item["role"] == "records" and file_scope is not None:
            identities.append((file_scope, None, metadata))
        if ha_source and time_provenance == "raw-file-mtime":
            health_reasons.append(f"raw-file-mtime-only:{filename}")
        if item["role"] == "identity":
            if not isinstance(payload, dict):
                raise UnifiedDatasetError(f"Invalid identity context: {filename}")
            ext_pan_id = _observed_id(payload.get("extPanId"))
            if file_scope is not None and ext_pan_id != file_scope:
                raise UnifiedDatasetError(f"Identity context contradicts its scope: {filename}")
            if ext_pan_id is not None:
                identities.append((ext_pan_id, payload.get("networkName"), metadata))
            else:
                health_reasons.append(f"unknown-identity:{filename}")
            continue
        if item["role"] == "outcome":
            if not _validate_outcome(payload, filename, source=entry["source"]):
                health_reasons.append(f"incomplete-outcome:{filename}")
            continue
        rows = _extract(item, payload)
        if ha_source:
            validate_canonical_rows(rows)
        if any(isinstance(row.get("tableAttempt"), dict)
               and row["tableAttempt"].get("status") != "success" for row in rows):
            health_reasons.append(f"incomplete-table-evidence:{filename}")
        by_scope: dict[str | None, list[dict]] = {}
        for record in rows:
            if ha_source:
                thread_record = is_thread_record(record)
                record_scope = _record_scope(record, file_scope) if thread_record else None
                if (thread_record and record_scope is not None and item["role"] == "records"
                        and record.get("extPanId") is not None):
                    identities.append((record_scope, record.get("networkName"), metadata))
            else:
                record_scope = _record_scope(
                    record, None if entry["source"] == "mdns" and record.get("extPanId") is None
                    else file_scope,
                )
            by_scope.setdefault(record_scope, []).append(record)
        if file_scope is not None and not rows:
            by_scope[file_scope] = []
        selected_scopes = 0
        excluded_count = 0
        for record_scope, records in by_scope.items():
            if network is not None and record_scope is not None and record_scope != network[7:]:
                excluded_count += len(records)
                continue
            selected_scopes += 1
            sources.append((record_scope, filename, records))
            if records or item["required"]:
                usable += 1
        if not rows and file_scope is None and item["required"]:
            sources.append((None, filename, []))
            usable += 1
            selected_scopes += 1
        metadata["selectedRecordCount"] = sum(len(records) for scope, records in by_scope.items()
                                             if network is None or scope is None or scope == network[7:])
        metadata["excludedRecordCount"] = excluded_count
        if not selected_scopes and by_scope:
            metadata["status"] = "excluded"
            if item["required"]:
                missing.append(filename)
        unknown_thread_scope = (any(is_thread_record(row) for row in by_scope.get(None, []))
                                if ha_source else None in by_scope)
        if rows and unknown_thread_scope and not filename.startswith("td-mdns-scopes-"):
            health_reasons.append(f"unknown-record-scope:{filename}")
    if ha_source:
        from ha_matter_ws_unified import assess_cached_outcomes
        health_reasons.extend(assess_cached_outcomes(ha_payloads, inputs))
    observed_networks = {scope for scope, _, _ in sources if scope is not None}
    observed_networks.update(identity for identity, _, _ in identities)
    if network is not None and network[7:] not in observed_networks:
        raise UnifiedDatasetError(f"Selected network has not been observed: {network}")
    if missing and not allow_partial:
        raise UnifiedDatasetError(f"Missing required cached inputs: {', '.join(missing)}")
    if not usable:
        raise UnifiedDatasetError("No usable cached record inputs")
    health_reasons = list(dict.fromkeys(health_reasons))
    selected = network[7:] if network is not None else (
        next(iter(observed_networks)) if len(observed_networks) == 1 else None
    )
    if selected is None:
        health_reasons.append("missing-or-ambiguous-observed-identity")
    identity_usable = selected is not None and any(
        identity == selected and metadata["sourceObservedAt"] is not None
        for identity, _, metadata in identities
    )
    if not identity_usable and entry["value"] != "mdns_unified":
        health_reasons.append("no-matching-observed-identity-context")
    materialization = "partial" if missing else "complete"
    if entry["value"] == "mdns_unified":
        selected = None
    rows, record_sources, field_sources = _assemble(sources)
    if ha_source or composition:
        from ha_matter_ws_unified import bind_native_relationships
        rows, unresolved_native = bind_native_relationships(rows)
        if unresolved_native:
            health_reasons.append("unresolved-native-relationships")
        if any(conflict.get("path") in {"nativeNodeIds.ambiguousIdentity", "_merge_identity_ambiguity"}
               for row in rows for conflict in row.get("_merge_conflicts", [])):
            health_reasons.append("ambiguous-native-or-merged-identity")
    health_state = "ineligible" if entry["value"] == "mdns_unified" else (
        "unavailable" if not identity_usable else "partial" if missing else
        "degraded" if health_reasons else "complete"
    )
    assert_snapshot_safe(rows)
    recipe_digest = _fingerprint(recipe)
    authority_digest = _fingerprint(catalog["authority"])
    generation_contract = {"contractVersion": CONTRACT_VERSION, "datasetId": entry["value"],
                           "source": entry["source"], "inputs": inputs,
                           "recipeDigest": recipe_digest, "authorityDigest": authority_digest,
                           "networkInstance": selected, "builderContract": BUILDER_CONTRACT}
    if composition:
        generation_contract["rawInputsDigest"] = _fingerprint(composition["raw_inputs"])
    generation = _fingerprint(generation_contract)
    marker = data_dir / recipe["reportFile"]
    previous_generation = None
    if marker.exists():
        try:
            previous = read_generation(data_dir, entry, catalog=catalog)
        except UnifiedDatasetError as exc:
            logging.warning("Explicitly rebuilding invalid Unified generation: %s", exc)
        else:
            previous_generation = previous["generationId"]
            if previous_generation == generation:
                _recheck(data_dir, captured)
                return _summary(entry, previous, no_op=True)
    row_content = _json_bytes(rows)
    row_digest = _digest(row_content)
    health_inputs = [item for item in (composition["raw_inputs"] if composition else inputs)
                     if not item["filename"].startswith("td-mdns-")
                     and item["status"] == "selected"]
    source_set_digest = _fingerprint(health_inputs)
    observed_at = max((item["sourceObservedAt"] for item in health_inputs
                       if item["role"] in {"records", "projection"} and item.get("sourceObservedAt")),
                      default=None)
    scope = {"extPanId": selected, "networkName": next(
        (name for identity, name, _ in identities if identity == selected and isinstance(name, str)), None),
        "provenance": "observed" if selected else "unknown",
        "reason": None if selected else "missing-or-ambiguous-observed-identity",
        "observedAt": observed_at, "sources": [item["filename"] for item in inputs if item["status"] == "selected"],
        "snapshotSha256": row_digest, "generationId": generation}
    artifacts = {entry["files"][0]: row_content,
                 network_scope_path(entry["files"][0]).name: _json_bytes(scope)}
    if recipe["identityFile"] is not None:
        artifacts[recipe["identityFile"]] = _json_bytes({
            **{key: value for key, value in scope.items() if key != "reason"},
            "extPanId": selected if identity_usable else None,
            "provenance": "observed" if identity_usable else "unknown",
        })
    if recipe["outcomeFile"] is not None:
        artifacts[recipe["outcomeFile"]] = _json_bytes({
            "contractVersion": CONTRACT_VERSION, "datasetId": entry["value"],
            "generationId": generation, "snapshotSha256": row_digest,
            "status": "degraded" if health_state == "unavailable" else health_state,
            "sourceSetDigest": source_set_digest, "observedAt": observed_at,
            "inputs": [{"filename": item["filename"], "status": item["status"]}
                       for item in inputs], "reasons": health_reasons,
        })
    report = {
        "contractVersion": CONTRACT_VERSION, "datasetId": entry["value"], "source": entry["source"],
        "builderContract": BUILDER_CONTRACT,
        "generationId": generation, "snapshotSha256": row_digest,
        "materializationState": materialization, "healthState": health_state,
        "networkInstance": f"extpan:{selected}" if selected else None, "inputs": inputs,
        "recipeDigest": recipe_digest, "authorityDigest": authority_digest,
        "sourceSetDigest": source_set_digest, "observedAt": observed_at,
        "fieldSources": field_sources, "recordSources": record_sources,
        "coverage": {"missingRequired": missing, "missingOptional": missing_optional,
                     "healthReasons": health_reasons},
        "excluded": ([OTBR_RESTAPI_ACTIONS_LIST_FILENAME] if entry["source"] == "otbr-restapi" else
                     [HA_MATTER_WS_THREAD_DIAGNOSTICS_FILENAME, HA_MATTER_WS_SERVER_INFO_FILENAME]
                     if ha_source else []),
        "generatedAt": now.isoformat(), "rowCount": len(rows),
        "linkCount": _link_count(rows),
        "artifactDigests": {name: _digest(content) for name, content in artifacts.items()},
    }
    if composition:
        report["rawInputs"] = composition["raw_inputs"]
        report["rawInputsDigest"] = generation_contract["rawInputsDigest"]
        report["coverage"]["sources"] = composition["dependency_states"]
        report["coverage"]["unresolvedNativeRelationships"] = unresolved_native
    if ha_source:
        inventory = next(item for item in inputs if item["filename"] == HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME)
        report["coverage"]["commissionedInventory"] = {
            "status": inventory["status"],
            "selectedRecordCount": inventory.get("selectedRecordCount", 0),
            "excludedRecordCount": inventory.get("excludedRecordCount", 0),
        }
        report["coverage"]["unresolvedNativeRelationships"] = unresolved_native
    assert_snapshot_safe(report)
    artifacts[recipe["reportFile"]] = _json_bytes(report)
    _publish(data_dir, entry, artifacts, captured, generation, previous_generation)
    return _summary(entry, report, no_op=False)


def inspect_unified_cache(data_dir: Path, entry: dict, *, catalog: dict | None = None,
                          inspections: dict[str, dict] | None = None) -> dict:
    """Report local committed/buildable state, without collectors or file writes."""
    inspections = {} if inspections is None else inspections
    dataset_id = entry["value"]
    if dataset_id not in inspections:
        inspections[dataset_id] = _inspect_unified_cache(data_dir, entry, catalog, inspections)
    return inspections[dataset_id]


def _inspect_unified_cache(data_dir: Path, entry: dict, catalog: dict | None,
                           inspections: dict[str, dict]) -> dict:
    reasons = []
    try:
        read_generation(data_dir, entry, catalog=catalog)
        committed = True
    except (OSError, UnifiedDatasetError) as exc:
        committed = False
        reasons.append(str(exc))
    if entry["source"] == "multi-source":
        catalog = load_dataset_catalog() if catalog is None else catalog
        dependencies = [(dependency, inspect_unified_cache(
                            data_dir, dependency, catalog=catalog, inspections=inspections))
                        for dependency in _dependencies(catalog, entry)]
        return {
            "cached": committed,
            "buildableFromCache": any(state["buildableFromCache"] for _, state in dependencies)
                and not any(state["cacheInputState"] == "invalid" for _, state in dependencies),
            "cacheInputState": "invalid" if any(
                state["cacheInputState"] == "invalid" for _, state in dependencies
            ) else "usable" if any(state["buildableFromCache"] for _, state in dependencies) else "missing",
            "cacheReasons": reasons + [
                f"{dependency['source']}:{reason}" for dependency, state in dependencies
                for reason in state["cacheReasons"]
            ],
        }
    usable = False
    invalid = False
    for item in entry["unified"]["inputs"]:
        try:
            cached = _read_stable(data_dir, item["file"])
            if cached.content is None:
                if item["required"]:
                    reasons.append(f"missing-required:{item['file']}")
                continue
            payload = _parse(cached.content, item["file"])
            sidecar = _read_stable(data_dir, network_scope_path(item["file"]).name)
            _scope(sidecar, cached)
            if item["role"] in {"records", "projection"}:
                rows = _extract(item, payload)
                usable = usable or bool(rows) or item["required"]
            elif item["role"] == "identity":
                if not isinstance(payload, dict):
                    raise UnifiedDatasetError(f"Invalid identity context: {item['file']}")
                _observed_id(payload.get("extPanId"))
            else:
                _validate_outcome(payload, item["file"], source=entry["source"])
        except (OSError, ValueError) as exc:
            invalid = True
            reasons.append(str(exc))
    return {"cached": committed, "buildableFromCache": usable and not invalid,
            "cacheInputState": "invalid" if invalid else "usable" if usable else "missing",
            "cacheReasons": reasons}


def build_unified_dataset(
    data_dir: Path, dataset_id: str, *, allow_partial: bool = False,
    network: str | None = None, catalog: dict | None = None,
) -> dict:
    if dataset_id not in UNIFIED_FILENAMES:
        raise UnifiedDatasetError(f"Unsupported Unified dataset: {dataset_id}")
    if network is not None and (
        not _NETWORK.fullmatch(network) or canonical_ext_pan_id(network[7:]) != network[7:]
    ):
        raise UnifiedDatasetError("Network must be extpan:<16-lowercase-hex>, nonzero")
    catalog = load_dataset_catalog() if catalog is None else catalog
    validate_dataset_catalog(catalog)
    entry = resolve_dataset(catalog, dataset_id)
    if "unified" not in entry:
        raise UnifiedDatasetError(f"No Unified recipe: {dataset_id}")
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / ".td-unified.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return _build_locked(data_dir, entry, catalog, allow_partial=allow_partial,
                                 network=network, now=datetime.now(timezone.utc))
        except MatterWsContractError as exc:
            raise UnifiedDatasetError(f"Invalid cached HA evidence: {exc}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize a Unified dataset from cached files only")
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    parser.add_argument("--dataset", required=True, choices=("all", *UNIFIED_FILENAMES),
                        help="Unified dataset ID, or 'all' to build all five datasets")
    parser.add_argument("--network", default=None)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.network is not None and (not _NETWORK.fullmatch(args.network)
                                     or args.network == "extpan:0000000000000000"):
        parser.error("--network must be extpan:<16-lowercase-hex>, nonzero")
    dataset_ids = tuple(UNIFIED_FILENAMES) if args.dataset == "all" else (args.dataset,)
    summaries = []
    try:
        data_dir = resolve_data_dir(data_dir=args.datadir)
        for dataset_id in dataset_ids:
            network = (None if args.dataset == "all" and dataset_id == "mdns_unified"
                       else args.network)
            summaries.append(build_unified_dataset(
                data_dir, dataset_id, allow_partial=args.allow_partial, network=network,
            ))
    except (OSError, ValueError) as exc:
        logging.error("Unified materialization failed: %s", exc)
        return 1
    if args.json:
        print(json.dumps(summaries if args.dataset == "all" else summaries[0],
                         sort_keys=True, allow_nan=False))
    else:
        for summary in summaries:
            print(f"{summary['datasetId']}: {summary['materializationState']}; "
                  f"{summary['rowCount']} rows; generation {summary['generationId']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
