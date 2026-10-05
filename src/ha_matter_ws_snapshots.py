"""Pure snapshot builders for normalized Home Assistant Matter records."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from ha_matter_ws_roles import (
    ROLE_FIELDS,
    ROLE_INPUT_FIELDS,
    normalize_ha_matter_roles,
)
from td_device_fields import normalize_input_record


class MatterSnapshotSecurityError(ValueError):
    """A normalized snapshot contains credential material."""


SENSITIVE_KEYS = frozenset(
    {
        "accesscontrol",
        "acl",
        "activedataset",
        "certificate",
        "certificates",
        "daccertificate",
        "nocs",
        "networkkey",
        "operationaldataset",
        "trustedrootcertificates",
        "rootpublickey",
        "groupkeymap",
        "groupkeyset",
        "groupepochkey",
        "operationalcredentials",
        "paicertificate",
        "pendingdataset",
        "pskc",
        "threadcredentials",
    }
)


def assert_snapshot_safe(value: Any) -> None:
    """Reject credential-bearing fields before a normalized snapshot is returned."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = "".join(character for character in str(key).lower() if character.isalnum())
            if normalized_key in SENSITIVE_KEYS:
                raise MatterSnapshotSecurityError(
                    f"Normalized Matter snapshot contains forbidden field {key!r}"
                )
            assert_snapshot_safe(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            assert_snapshot_safe(child)


def build_device_snapshot(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Build a stable, credential-free device snapshot."""

    snapshot: list[dict[str, Any]] = []
    for record in records:
        matter = record.get("matter")
        if not isinstance(matter, Mapping):
            continue
        thread = record.get("thread")
        thread_record = thread if isinstance(thread, Mapping) else None
        matter_id = matter.get("matterId")
        matter_details = {
            **matter,
            "endpoints": record.get("endpoints", []),
            "deviceTypes": record.get("deviceTypes", []),
            "serverClusters": record.get("serverClusters", []),
        }
        device = {
            **record,
            "id": f"matter:{matter_id}" if matter_id else None,
            "type": "threadDevice" if thread_record is not None else "matterDevice",
            "deviceLabel": matter.get("deviceLabel"),
            "vendorName": matter.get("vendorName"),
            "vendorModel": matter.get("vendorModel"),
            "vendorSwVersion": matter.get("vendorSwVersion"),
            "available": matter.get("available"),
            "isBridge": matter.get("isBridge"),
            "extAddress": thread_record.get("extAddress") if thread_record else None,
            "rloc16": thread_record.get("rloc16") if thread_record else None,
            "ipv6Addresses": thread_record.get("ipv6Addresses", []) if thread_record else [],
            "role": thread_record.get("routingRole") if thread_record else None,
            "matter": matter_details,
        }
        role_source = {**(thread_record or {}), **device}
        resolved_roles = normalize_ha_matter_roles(
            role_source,
            thread_role=thread_record.get("routingRole") if thread_record else None,
            is_thread=thread_record is not None,
        )
        for field in ROLE_INPUT_FIELDS:
            if field in resolved_roles:
                device[field] = resolved_roles[field]
            else:
                device.pop(field, None)
        if "_merge_conflicts" in resolved_roles:
            device["_merge_conflicts"] = resolved_roles["_merge_conflicts"]
        normalized = normalize_input_record(device, source="ha-matter-ws")
        normalized_roles = normalize_ha_matter_roles(
            normalized,
            thread_role=thread_record.get("routingRole") if thread_record else None,
            is_thread=thread_record is not None,
        )
        for field in ROLE_FIELDS:
            if field in normalized_roles:
                normalized[field] = normalized_roles[field]
            else:
                normalized.pop(field, None)
        if "_merge_conflicts" in normalized_roles:
            normalized["_merge_conflicts"] = normalized_roles["_merge_conflicts"]
        snapshot.append(normalized)
    snapshot.sort(key=lambda record: record.get("matter", {}).get("nodeId", -1))
    assert_snapshot_safe(snapshot)
    return snapshot


def build_diagnostic_snapshot(
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build canonical scalar/table diagnostics without topology derivation."""

    snapshot: list[dict[str, Any]] = []
    for record in records:
        matter = record.get("matter")
        thread = record.get("thread")
        if not isinstance(matter, Mapping) or not isinstance(thread, Mapping):
            continue
        role = thread.get("routingRole")
        standard = thread.get("diagnosticsDetail", {}).get(
            "threadNetworkDiagnostics", {}
        )
        diagnostic = {
            "nodeId": matter.get("nodeId"),
            "matterId": matter.get("matterId"),
            "fabricId": matter.get("fabricId"),
            "compressedFabricId": matter.get("compressedFabricId"),
            "fabricIndex": matter.get("fabricIndex"),
            "deviceLabel": matter.get("deviceLabel"),
            "vendorName": matter.get("vendorName"),
            "vendorModel": matter.get("vendorModel"),
            "vendorSwVersion": matter.get("vendorSwVersion"),
            "available": matter.get("available"),
            "extAddress": thread.get("extAddress"),
            "rloc16": thread.get("rloc16"),
            "ipv6Addresses": thread.get("ipv6Addresses", []),
            "channel": thread.get("channel"),
            "networkName": thread.get("networkName"),
            "extPanId": thread.get("extendedPanId"),
            "meshLocalPrefix": thread.get("meshLocalPrefix"),
            "role": role,
            "leaderData": {
                key: standard[key]
                for key in (
                    "partitionId",
                    "weighting",
                    "dataVersion",
                    "stableDataVersion",
                    "leaderRouterId",
                )
                if key in standard
            },
            "macCounters": thread.get("macCounters", {}),
            "mleCounters": thread.get("mleCounters", {}),
            "networkInterfaces": record.get("networkInterfaces", []),
            "neighborTable": thread.get("neighborTable", []),
            "routeTable": thread.get("routeTable", []),
            "diagnosticsDetail": thread.get("diagnosticsDetail", {}),
            "diagnosticCoverage": record.get("diagnosticCoverage", {}),
        }
        role_source = {**thread, **record, **diagnostic}
        normalized_roles = normalize_ha_matter_roles(
            role_source, thread_role=role, is_thread=True
        )
        for field in ROLE_FIELDS:
            if field in normalized_roles:
                diagnostic[field] = normalized_roles[field]
        if "_merge_conflicts" in normalized_roles:
            diagnostic["_merge_conflicts"] = normalized_roles["_merge_conflicts"]
        snapshot.append(normalize_input_record(diagnostic, source="ha-matter-ws"))
    snapshot.sort(key=lambda record: record.get("nodeId", -1))
    assert_snapshot_safe(snapshot)
    return snapshot