"""Pure conversion of cached HA Matter inventory and native topology products."""

from __future__ import annotations

import hashlib
import ipaddress
import json
from copy import deepcopy
from datetime import datetime
from typing import Any

from ha_matter_ws_contract import MatterWsContractError
from ha_matter_ws_native_topology import MAX_SAFE_JSON_INTEGER, validate_native_topology
from ha_matter_ws_roles import ROLE_FIELDS, ROLE_INPUT_FIELDS, normalize_ha_matter_roles
from ha_matter_ws_snapshots import (
    DASHBOARD_SCHEMA_VERSION,
    NATIVE_SNAPSHOT_SCHEMA_VERSION,
    assert_snapshot_safe,
    build_device_snapshot,
)
from ha_matter_ws_thread import validate_border_router_entries
from ha_matter_ws_topology import _topology_id
from td_device_fields import (
    get_canonical_ext_address,
    is_placeholder_ext_address,
    normalize_input_record,
)
from td_const import (
    HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME,
    HA_MATTER_WS_DASHBOARD_FILENAME,
    HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME,
    HA_MATTER_WS_NETWORK_TOPOLOGY_FILENAME,
    HA_MATTER_WS_NETWORK_TOPOLOGY_OUTCOME_FILENAME,
    HA_MATTER_WS_THREAD_BORDER_ROUTERS_FILENAME,
    HA_MATTER_WS_THREAD_BORDER_ROUTERS_OUTCOME_FILENAME,
)
from td_network_identity import canonical_ext_pan_id
from td_record_merge import append_merge_conflict


def _wrapper(payload: Any, source: str, field: str) -> Any:
    if (not isinstance(payload, dict)
            or payload.get("schemaVersion") != NATIVE_SNAPSHOT_SCHEMA_VERSION
            or payload.get("source") != source or field not in payload):
        raise MatterWsContractError(f"Invalid cached {source} envelope")
    assert_snapshot_safe(payload)
    return payload[field]


def _without_role_conflicts(record: Any) -> Any:
    if not isinstance(record, dict):
        return record
    result = deepcopy(record)
    conflicts = result.pop("_merge_conflicts", [])
    if not isinstance(conflicts, list) or any(
        not isinstance(item, dict) or set(item) != {"path", "current", "incoming"}
        or item["path"] not in ROLE_FIELDS
        or type(item["current"]) is not bool or type(item["incoming"]) is not bool
        for item in conflicts
    ):
        raise MatterWsContractError("Invalid cached native role conflicts")
    return result


def _roles(record: dict, original: dict, *, is_thread: bool,
           border_router: bool = False) -> dict:
    if "_merge_conflicts" in original:
        record["_merge_conflicts"] = deepcopy(original["_merge_conflicts"])
    return normalize_ha_matter_roles(
        record, thread_role=record.get("role"), is_thread=is_thread,
        border_router=border_router,
    )


def _native_id(record: dict, native_id: str) -> str:
    address = get_canonical_ext_address(record)
    if record.get("extPanId") and not is_placeholder_ext_address(address):
        return _topology_id(record)
    return f"ha-native:{native_id}"


def _ext_pan_id(value: Any) -> str:
    try:
        return canonical_ext_pan_id(value)
    except ValueError as exc:
        raise MatterWsContractError(f"Invalid native Thread identity: {exc}") from exc


def normalize_inventory(payload: Any) -> list[dict]:
    """Preserve every commissioned device and its complete safe snapshot fields."""
    if not isinstance(payload, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("matter"), dict)
        or not isinstance(row["matter"].get("matterId"), str)
        or not row["matter"]["matterId"]
        for row in payload
    ):
        raise MatterWsContractError("Expected commissioned Matter device snapshots")
    assert_snapshot_safe(payload)
    records = deepcopy(payload)
    rows = []
    for record in records:
        matter = record["matter"]
        for field in ("endpoints", "deviceTypes", "serverClusters"):
            record.setdefault(field, deepcopy(matter.get(field, [])))
        thread = record.get("thread")
        if isinstance(thread, dict) and thread.get("extendedPanId") is not None:
            observed = _ext_pan_id(thread["extendedPanId"])
            if record.get("extPanId") is not None and _ext_pan_id(record["extPanId"]) != observed:
                raise MatterWsContractError("Inventory Thread identity contradicts its device")
            record["extPanId"] = observed
        normalized = normalize_input_record(record, source="ha-matter-ws")
        derived = build_device_snapshot([normalized])[0]
        row = {**derived, **normalized,
               "matter": {**derived["matter"], **normalized["matter"]}}
        if "_merge_conflicts" in derived:
            row["_merge_conflicts"] = derived["_merge_conflicts"]
        rows.append(row)
    return rows


def normalize_border_routers(payload: Any) -> list[dict]:
    """Map validated native Border Routers without promoting IPv4 to IPv6."""
    entries = _wrapper(payload, "ha-matter-ws-thread-border-routers", "borderRouters")
    if not isinstance(entries, list):
        raise MatterWsContractError("Expected native Border Router entries")
    validated = validate_border_router_entries([_without_role_conflicts(row) for row in entries])
    rows = []
    mapping = {
        "extAddressHex": "extAddress", "extendedPanIdHex": "extPanId",
        "networkName": "networkName", "vendorName": "vendorName",
        "modelName": "vendorModel", "swVersion": "vendorSwVersion",
        "threadVersion": "threadVersion",
    }
    for native, original in zip(validated, entries, strict=True):
        row = {canonical: native[key] for key, canonical in mapping.items() if key in native}
        if "extPanId" in row:
            row["extPanId"] = _ext_pan_id(row["extPanId"])
        row["type"] = "threadDevice"
        row["ipv6Addresses"] = list(dict.fromkeys(
            str(ipaddress.IPv6Address(address)) for address in native["addresses"]
            if ipaddress.ip_address(address).version == 6
        ))
        row["diagnosticsDetail"] = {"nativeBorderRouter": deepcopy(native)}
        for field in ROLE_INPUT_FIELDS:
            if field in native:
                row[field] = native[field]
        row = _roles(row, original, is_thread=True, border_router=True)
        row = normalize_input_record(row, source="ha-matter-ws")
        row["topologyId"] = _native_id(row, f"br:{get_canonical_ext_address(row)}")
        row["id"] = row["topologyId"]
        rows.append(row)
    assert_snapshot_safe(rows)
    return rows


def normalize_native_topology(payload: Any) -> list[dict]:
    """Retain typed native links, including unresolved endpoints, without OTBR tables."""
    graph = _wrapper(payload, "ha-matter-ws-network-topology", "topology")
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        raise MatterWsContractError("Expected native topology graph")
    clean = {**graph, "nodes": [_without_role_conflicts(node) for node in graph["nodes"]]}
    validated = validate_native_topology(clean, allow_dangling_connections=True)
    rows: list[dict] = []
    by_native_id: dict[str, dict] = {}
    mapping = {
        "ext_address": "extAddress", "ext_pan_id": "extPanId",
        "network_name": "networkName", "vendor_name": "vendorName",
        "model_name": "vendorModel", "available": "available", "is_bridge": "isBridge",
    }
    for native, original in zip(validated["nodes"], graph["nodes"], strict=True):
        is_thread = native["network_type"] == "thread"
        row = {canonical: native[key] for key, canonical in mapping.items() if key in native}
        if "extPanId" in row:
            row["extPanId"] = _ext_pan_id(row["extPanId"])
        if "rloc16" in native:
            row["rloc16"] = f"0x{native['rloc16']:04x}"
        if is_thread and "role" in native:
            row["role"] = native["role"]
        for field in ROLE_INPUT_FIELDS:
            if field in native:
                row[field] = native[field]
        row["type"] = "threadDevice" if is_thread else (
            "matterDevice" if native["kind"] == "matter" else "nativeDevice"
        )
        row["nativeNodeIds"] = [native["id"]]
        row["diagnosticsDetail"] = {"nativeTopology": {
            "node": deepcopy(native), "collectedAt": validated["collected_at"],
        }}
        row = _roles(row, original, is_thread=is_thread,
                     border_router=is_thread and native["kind"] == "border_router")
        row = normalize_input_record(row, source="ha-matter-ws")
        row["topologyId"] = _native_id(row, native["id"])
        row["id"] = row["topologyId"]
        row["nativeRelationships"] = []
        rows.append(row)
        by_native_id[native["id"]] = row
    by_canonical_id: dict[str, list[dict]] = {}
    for row in rows:
        by_canonical_id.setdefault(row["topologyId"], []).append(row)
    for candidates in by_canonical_id.values():
        if len(candidates) > 1:
            for row in candidates:
                append_merge_conflict(row, "nativeNodeIds.ambiguousIdentity",
                                      row["topologyId"], row["nativeNodeIds"])
                row["topologyId"] = f"ha-native:{row['nativeNodeIds'][0]}"
                row["id"] = row["topologyId"]
    seen = set()
    for connection in validated["connections"]:
        fingerprint = json.dumps(connection, sort_keys=True, separators=(",", ":"))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        source = by_native_id.get(connection["source"])
        target = by_native_id.get(connection["target"])
        link = {
            "sourceId": source["topologyId"] if source else f"ha-native:{connection['source']}",
            "targetId": target["topologyId"] if target else f"ha-native:{connection['target']}",
            "networkType": connection["network"],
            "nativeSourceId": connection["source"], "nativeTargetId": connection["target"],
            "strength": connection["strength"],
            "observations": [{"source": "nativeTopology", "collectedAt": validated["collected_at"]}],
        }
        for key, canonical in (
            ("source_to_target", "sourceToTarget"), ("target_to_source", "targetToSource"),
            ("via_route_table", "viaRouteTable"), ("path_cost", "pathCost"),
            ("extensions", "extensions"),
        ):
            if key in connection:
                link[canonical] = deepcopy(connection[key])
        unresolved = [connection[key] for key in ("source", "target")
                      if connection[key] not in by_native_id]
        owner = source if source is not None else target
        if owner is None:
            identity = "ha-native-link:" + hashlib.sha256(fingerprint.encode()).hexdigest()
            owner = {"id": identity, "topologyId": identity, "type": "nativeRelationship",
                     "relationshipOnly": True, "nativeNodeIds": [], "nativeRelationships": []}
            rows.append(owner)
        if unresolved:
            link["unresolvedEndpoints"] = unresolved
            append_merge_conflict(owner, "nativeRelationships.unresolvedEndpoints", None, unresolved)
        owner["nativeRelationships"].append(link)
    assert_snapshot_safe(rows)
    return rows


def is_thread_record(record: dict) -> bool:
    if record.get("type") == "threadDevice":
        return True
    if record.get("type") in {"matterDevice", "nativeDevice", "nativeRelationship"}:
        return False
    return bool(record.get("extAddress") or record.get("rloc16") or record.get("extPanId"))


def native_observation_epoch(extractor: str, payload: Any) -> float | None:
    """Use upstream graph/discovery time, never wrapper read time, for native rows."""
    if not isinstance(payload, dict):
        return None
    if extractor == "ha-native-topology":
        graph = payload.get("topology")
        values = [graph.get("collected_at")] if isinstance(graph, dict) else []
    else:
        entries = payload.get("borderRouters")
        if not isinstance(entries, list):
            return None
        if not entries:
            return None
        values = [entry.get("lastSeen") if isinstance(entry, dict) else None for entry in entries]
    if not values or any(type(value) is not int or not 0 < value <= MAX_SAFE_JSON_INTEGER
                         for value in values):
        return None
    return min(values) / 1000


def validate_cached_outcome(filename: str, payload: Any) -> bool:
    """Validate original HA outcomes independently of display materialization."""
    if not isinstance(payload, dict) or payload.get("source") != "ha-matter-ws":
        raise MatterWsContractError("Invalid cached HA collection outcome")
    assert_snapshot_safe(payload)
    if filename == HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME:
        statuses = {"success", "success-with-node-errors", "failed", "cancelled", "partial"}
        files = payload.get("finalFiles")
        errors = payload.get("nodeErrors")
        if (payload.get("status") not in statuses or not isinstance(files, list)
                or any(not isinstance(name, str) for name in files)
                or len(files) != len(set(files)) or not isinstance(errors, list)
                or any(not isinstance(error, dict) for error in errors)
                or any(type(payload.get(key)) is not int or payload[key] < 0
                       for key in ("nodeCount", "normalizedNodeCount"))):
            raise MatterWsContractError("Invalid cached HA inventory outcome")
        return (payload["status"] == "success" and not errors
                and payload["nodeCount"] == payload["normalizedNodeCount"]
                and HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME in files)
    native = {
        HA_MATTER_WS_THREAD_BORDER_ROUTERS_OUTCOME_FILENAME:
            ("get_thread_border_routers", HA_MATTER_WS_THREAD_BORDER_ROUTERS_FILENAME, "itemCount"),
        HA_MATTER_WS_NETWORK_TOPOLOGY_OUTCOME_FILENAME:
            ("get_network_topology", HA_MATTER_WS_NETWORK_TOPOLOGY_FILENAME, "nodeCount"),
    }
    expected = native.get(filename)
    if expected is None:
        raise MatterWsContractError("Unsupported cached HA outcome")
    command, final_file, count = expected
    if (payload.get("status") not in {"complete", "failed", "cancelled", "partial"}
            or payload.get("command") != command or not isinstance(payload.get("finalFile"), str)
            or type(payload.get(count)) is not int or payload[count] < 0
            or any(key in payload and (type(payload[key]) is not int or payload[key] < 0)
                   for key in ("itemCount", "nodeCount", "connectionCount", "responseCount", "eventCount"))):
        raise MatterWsContractError("Invalid cached HA native outcome")
    return payload["status"] == "complete" and payload["finalFile"] == final_file


def assess_cached_outcomes(payloads: dict[str, Any], inputs: list[dict]) -> list[str]:
    """Check outcome association without treating file mtimes as collection proof."""
    metadata = {item["filename"]: item for item in inputs}
    reasons = []
    collection = payloads.get(HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME)
    inventory = payloads.get(HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME)
    if collection is not None and inventory is not None:
        if collection["normalizedNodeCount"] != len(inventory):
            reasons.append("outcome-count-mismatch:" + HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME)
    native = (
        (HA_MATTER_WS_THREAD_BORDER_ROUTERS_OUTCOME_FILENAME,
         HA_MATTER_WS_THREAD_BORDER_ROUTERS_FILENAME, "borderRouters", "itemCount"),
        (HA_MATTER_WS_NETWORK_TOPOLOGY_OUTCOME_FILENAME,
         HA_MATTER_WS_NETWORK_TOPOLOGY_FILENAME, "topology", "nodeCount"),
    )
    for outcome_file, data_file, field, count in native:
        outcome = payloads.get(outcome_file)
        snapshot = payloads.get(data_file)
        if outcome is None or snapshot is None or outcome["status"] != "complete":
            continue
        native_data = snapshot[field]
        expected_count = len(native_data["nodes"]) if field == "topology" else len(native_data)
        if outcome[count] != expected_count or (field == "topology" and
                outcome.get("connectionCount") != len(native_data["connections"])):
            reasons.append("outcome-count-mismatch:" + outcome_file)
        try:
            times = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in
                     (outcome["startedAt"], snapshot["observedAt"], outcome["completedAt"])]
            if any(value.tzinfo is None for value in times) or not times[0] <= times[1] <= times[2]:
                raise ValueError("Unbound native capture time")
        except (KeyError, AttributeError, ValueError, TypeError):
            reasons.append("unbound-outcome-capture:" + outcome_file)
        outcome_scope = metadata[outcome_file].get("observedNetwork")
        snapshot_scope = metadata[data_file].get("observedNetwork")
        if outcome_scope is not None and snapshot_scope is not None and outcome_scope != snapshot_scope:
            reasons.append("outcome-scope-mismatch:" + outcome_file)
    return reasons


def normalize_projection(payload: Any) -> list[dict]:
    """Deduplicate dashboard projections without making them an inventory substitute."""
    if not isinstance(payload, dict) or payload.get("schemaVersion") != DASHBOARD_SCHEMA_VERSION:
        raise MatterWsContractError("Invalid cached HA dashboard projection")
    assert_snapshot_safe(payload)
    rows = normalize_inventory(payload.get("devices"))
    for field in ("diagnostics", "meshDiagnostics", "topology"):
        records = payload.get(field)
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            raise MatterWsContractError(f"Invalid cached HA dashboard {field}")
        rows.extend(normalize_input_record(record, source="ha-matter-ws") for record in records)
    from merge_dataset import merge_cached_records
    grouped: dict[str | None, list[dict]] = {}
    for row in rows:
        network = _ext_pan_id(row["extPanId"]) if row.get("extPanId") is not None else None
        if network is not None:
            row["extPanId"] = network
        grouped.setdefault(network, []).append(row)
    result = []
    for network, records in grouped.items():
        merged, _ = merge_cached_records(
            [(HA_MATTER_WS_DASHBOARD_FILENAME, records)], network,
            preserve_same_file_duplicates=False,
        )
        result.extend(merged)
    return result


def bind_native_relationships(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Bind native endpoints to committed row IDs, never a possibly colliding address."""
    result = deepcopy(rows)
    by_record_id = {row["_unifiedRecordId"]: row for row in result}
    by_native_id: dict[str, list[str]] = {}
    for row in result:
        for native_id in row.get("nativeNodeIds", []):
            by_native_id.setdefault(native_id, []).append(row["_unifiedRecordId"])
    unresolved = []
    for row in result:
        for link in row.get("nativeRelationships", []):
            missing = []
            for endpoint in ("source", "target"):
                native_id = link[f"native{endpoint.title()}Id"]
                candidates = by_native_id.get(native_id, [])
                if len(candidates) == 1:
                    link[f"{endpoint}Id"] = candidates[0]
                else:
                    link[f"{endpoint}Id"] = f"ha-native:{native_id}"
                    missing.append(native_id)
            if not missing and link["networkType"] == "thread":
                source_scope = by_record_id[link["sourceId"]].get("_networkInstance")
                target_scope = by_record_id[link["targetId"]].get("_networkInstance")
                if source_scope is not None and target_scope is not None and source_scope != target_scope:
                    native_id = link["nativeTargetId"]
                    link["targetId"] = f"ha-native:{native_id}"
                    missing.append(native_id)
                    append_merge_conflict(row, "nativeRelationships.networkMismatch",
                                          source_scope, target_scope)
            if missing:
                link["unresolvedEndpoints"] = missing
                append_merge_conflict(row, "nativeRelationships.unresolvedEndpoints", None, missing)
                unresolved.append({key: link[key] for key in
                                   ("sourceId", "targetId", "unresolvedEndpoints")})
            else:
                link.pop("unresolvedEndpoints", None)
    return result, unresolved


def validate_canonical_rows(rows: list[dict]) -> None:
    for row in rows:
        conflicts = row.get("_merge_conflicts", [])
        if not isinstance(conflicts, list) or any(
            not isinstance(conflict, dict) or not isinstance(conflict.get("path"), str)
            or not {"current", "incoming"} <= conflict.keys() for conflict in conflicts
        ):
            raise MatterWsContractError("Invalid cached HA merge conflicts")
        node_ids = row.get("nativeNodeIds", [])
        if not isinstance(node_ids, list) or any(not isinstance(node_id, str) or not node_id
                                                for node_id in node_ids):
            raise MatterWsContractError("Invalid cached HA native node IDs")
        links = row.get("nativeRelationships", [])
        if not isinstance(links, list) or any(
            not isinstance(link, dict) or any(
                not isinstance(link.get(key), str) or not link[key]
                for key in ("sourceId", "targetId", "nativeSourceId", "nativeTargetId", "networkType")
            ) for link in links
        ):
            raise MatterWsContractError("Invalid cached HA native relationships")


def normalize_cached_ha_records(extractor: str, payload: Any) -> list[dict]:
    """Dispatch only explicit source-owned cached converters, never live collection."""
    converters = {
        "ha-inventory": normalize_inventory,
        "ha-border-routers": normalize_border_routers,
        "ha-native-topology": normalize_native_topology,
        "ha-projection": normalize_projection,
    }
    if extractor not in converters:
        raise MatterWsContractError(f"Unsupported cached HA converter: {extractor}")
    return converters[extractor](payload)
