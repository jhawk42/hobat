"""Derive directional Thread relationships from Matter diagnostic reports."""

from __future__ import annotations

import json
import re

from copy import deepcopy
from typing import Any, Iterable, Mapping

from ha_matter_ws_snapshots import assert_snapshot_safe
from td_device_fields import normalize_input_record
from util_network import (
    extract_rloc16_from_ipv6_address,
    is_child_rloc16_of_parent,
    is_router,
)


class TopologyValidationError(ValueError):
    """A topology contains an ambiguous or unresolved relationship endpoint."""


def _ext_address(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace(":", "").replace("-", "")
    if not re.fullmatch(r"[0-9a-f]{16}", normalized):
        return None
    if normalized in {"0000000000000000", "ffffffffffffffff"}:
        return None
    return normalized


def _rloc16(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        number = int(value, 0)
    except ValueError:
        return None
    if number < 0 or number >= 0xFFFE:
        return None
    return f"0x{number:04x}"


def _network_key(record: Mapping[str, Any]) -> str:
    ext_pan_id = record.get("extPanId")
    if isinstance(ext_pan_id, str) and ext_pan_id.strip():
        return f"extpan:{ext_pan_id.strip().lower()}"
    mesh_prefix = record.get("meshLocalPrefix")
    if isinstance(mesh_prefix, str) and mesh_prefix.strip():
        return f"prefix:{mesh_prefix.strip().lower()}"
    network_name = record.get("networkName")
    leader_data = record.get("leaderData")
    partition_id = (
        leader_data.get("partitionId") if isinstance(leader_data, Mapping) else None
    )
    return f"name:{network_name!s}|partition:{partition_id!s}"


def _topology_id(record: Mapping[str, Any]) -> str:
    ext_address = _ext_address(record.get("extAddress"))
    if ext_address is not None:
        return f"thread:{_network_key(record)}:ext:{ext_address}"
    rloc16 = _rloc16(record.get("rloc16"))
    if rloc16 is not None:
        return f"thread:{_network_key(record)}:rloc:{rloc16}"
    matter_id = record.get("matterId")
    if isinstance(matter_id, str) and matter_id:
        return f"matter:{matter_id}"
    return f"node:{record.get('nodeId')!s}"


def _derive_rloc16(record: Mapping[str, Any]) -> tuple[str | None, str | None]:
    addresses = record.get("ipv6Addresses")
    if not isinstance(addresses, list):
        return None, None
    for value in addresses:
        rloc16 = extract_rloc16_from_ipv6_address(value)
        if rloc16 is not None:
            return rloc16, value
    return None, None


def _initialize_node(record: Mapping[str, Any]) -> dict[str, Any]:
    node = normalize_input_record(deepcopy(dict(record)), source="ha-matter-ws")
    ext_address = _ext_address(node.get("extAddress"))
    rloc16 = _rloc16(node.get("rloc16"))
    if rloc16 is None:
        rloc16, source_address = _derive_rloc16(node)
        if rloc16 is not None:
            node["rloc16Provenance"] = {
                "source": "threadInterfaceIpv6",
                "address": source_address,
            }
    if ext_address is not None:
        node["extAddress"] = ext_address
    else:
        node.pop("extAddress", None)
    if rloc16 is not None:
        node["rloc16"] = rloc16
        node["isRouter"] = is_router(rloc16)
    else:
        node.pop("rloc16", None)
    node["topologyId"] = _topology_id(node)
    node["routerNeighbors"] = []
    node["children"] = []
    node["route"] = {"routeData": []}
    return node


def _observation(
    reporter: Mapping[str, Any], target: Mapping[str, Any], source: str, entry: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "source": source,
        "reporterMatterId": reporter.get("matterId"),
        "sourceId": reporter["topologyId"],
        "targetId": target["topologyId"],
        "entry": deepcopy(dict(entry)),
    }


def _append_unique(items: list[dict[str, Any]], value: dict[str, Any]) -> None:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if all(
        json.dumps(item, sort_keys=True, separators=(",", ":")) != encoded
        for item in items
    ):
        items.append(value)


class _TopologyIndex:
    def __init__(self, nodes: list[dict[str, Any]]) -> None:
        self.nodes = nodes
        self.by_ext: dict[str, dict[str, Any]] = {}
        self.by_rloc: dict[tuple[str, str], dict[str, Any]] = {}
        for node in nodes:
            self._index(node)

    def _index(self, node: dict[str, Any]) -> None:
        ext_address = _ext_address(node.get("extAddress"))
        rloc16 = _rloc16(node.get("rloc16"))
        if ext_address is not None:
            existing = self.by_ext.get(ext_address)
            if existing is not None and existing is not node:
                raise TopologyValidationError(
                    f"Duplicate commissioned extAddress {ext_address}"
                )
            self.by_ext[ext_address] = node
        if rloc16 is not None:
            key = (_network_key(node), rloc16)
            existing = self.by_rloc.get(key)
            if existing is not None and existing is not node:
                raise TopologyValidationError(
                    f"Duplicate commissioned RLOC16 {rloc16} in {_network_key(node)}"
                )
            self.by_rloc[key] = node

    def resolve(
        self, reporter: Mapping[str, Any], entry: Mapping[str, Any]
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        ext_address = _ext_address(entry.get("extAddress"))
        rloc16 = _rloc16(entry.get("rloc16"))
        context = _network_key(reporter)
        ext_target = self.by_ext.get(ext_address) if ext_address is not None else None
        rloc_target = self.by_rloc.get((context, rloc16)) if rloc16 is not None else None
        conflicts: list[dict[str, Any]] = []
        if ext_target is not None:
            if rloc_target is not None and rloc_target is not ext_target:
                conflicts.append(
                    {
                        "field": "rloc16",
                        "reported": rloc16,
                        "resolved": rloc_target["topologyId"],
                    }
                )
            return ext_target, conflicts
        if rloc_target is not None:
            return rloc_target, conflicts
        if ext_address is None and rloc16 is None:
            return None, conflicts

        placeholder: dict[str, Any] = {
            "relationshipOnly": True,
            "networkName": reporter.get("networkName"),
            "extPanId": reporter.get("extPanId"),
            "meshLocalPrefix": reporter.get("meshLocalPrefix"),
            "role": "unknown",
            "routerNeighbors": [],
            "children": [],
            "route": {"routeData": []},
        }
        if ext_address is not None:
            placeholder["extAddress"] = ext_address
        if rloc16 is not None:
            placeholder["rloc16"] = rloc16
            placeholder["isRouter"] = is_router(rloc16)
        placeholder["topologyId"] = _topology_id(placeholder)
        self.nodes.append(placeholder)
        self._index(placeholder)
        return placeholder, conflicts


def _relationship(
    reporter: Mapping[str, Any],
    target: Mapping[str, Any],
    entry: Mapping[str, Any],
    source: str,
    conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    relationship = deepcopy(dict(entry))
    relationship.update(
        {
            "sourceId": reporter["topologyId"],
            "targetId": target["topologyId"],
            "direction": "outbound",
            "extAddress": target.get("extAddress"),
            "rloc16": target.get("rloc16"),
            "observations": [_observation(reporter, target, source, entry)],
        }
    )
    if conflicts:
        relationship["identityConflicts"] = conflicts
    return relationship


def _merge_relationship(
    relationships: list[dict[str, Any]], incoming: dict[str, Any]
) -> dict[str, Any]:
    existing = next(
        (
            relationship
            for relationship in relationships
            if relationship["targetId"] == incoming["targetId"]
        ),
        None,
    )
    if existing is None:
        relationships.append(incoming)
        return incoming
    for observation in incoming["observations"]:
        _append_unique(existing["observations"], observation)
    for conflict in incoming.get("identityConflicts", []):
        conflicts = existing.setdefault("identityConflicts", [])
        _append_unique(conflicts, conflict)
    return existing


def _derive_reporter_relationships(
    reporter: dict[str, Any], index: _TopologyIndex
) -> None:
    raw_neighbors = reporter.pop("neighborTable", [])
    if isinstance(raw_neighbors, list):
        for entry in raw_neighbors:
            if not isinstance(entry, Mapping):
                continue
            target, conflicts = index.resolve(reporter, entry)
            if target is None:
                continue
            relationships = (
                reporter["children"]
                if entry.get("isChild") is True
                else reporter["routerNeighbors"]
            )
            _merge_relationship(
                relationships,
                _relationship(
                    reporter,
                    target,
                    entry,
                    "ThreadNetworkDiagnostics.NeighborTable",
                    conflicts,
                ),
            )

    raw_routes = reporter.pop("routeTable", [])
    if isinstance(raw_routes, list):
        for entry in raw_routes:
            if not isinstance(entry, Mapping) or entry.get("allocated") is False:
                continue
            target, conflicts = index.resolve(reporter, entry)
            if target is None:
                continue
            _merge_relationship(
                reporter["route"]["routeData"],
                _relationship(
                    reporter,
                    target,
                    entry,
                    "ThreadNetworkDiagnostics.RouteTable",
                    conflicts,
                ),
            )


def _infer_rloc16_children(nodes: list[dict[str, Any]]) -> None:
    for parent in nodes:
        parent_rloc16 = parent.get("rloc16")
        if not is_router(parent_rloc16):
            continue
        for child in nodes:
            if (
                child is parent
                or child.get("relationshipOnly")
                or _network_key(child) != _network_key(parent)
            ):
                continue
            child_rloc16 = child.get("rloc16")
            if not is_child_rloc16_of_parent(child_rloc16, parent_rloc16):
                continue
            relationship = {
                "sourceId": parent["topologyId"],
                "targetId": child["topologyId"],
                "direction": "outbound",
                "extAddress": child.get("extAddress"),
                "rloc16": child_rloc16,
                "observations": [
                    {
                        "source": "Rloc16Hierarchy",
                        "reporterMatterId": parent.get("matterId"),
                        "sourceId": parent["topologyId"],
                        "targetId": child["topologyId"],
                        "entry": {
                            "parentRloc16": parent_rloc16,
                            "childRloc16": child_rloc16,
                        },
                    }
                ],
            }
            _merge_relationship(parent["children"], relationship)


def _set_totals(node: dict[str, Any]) -> None:
    node["totalLinks"] = len(node["routerNeighbors"])
    node["totalChildren"] = len(node["children"])
    node["totalRoutes"] = len(node["route"]["routeData"])
    for quality in (1, 2, 3):
        links = [
            relationship["targetId"]
            for relationship in node["routerNeighbors"]
            if relationship.get("lqi") == quality
        ]
        node[f"totalLink{quality}"] = len(links)
        node[f"links{quality}"] = links


def validate_topology(topology: Iterable[Mapping[str, Any]]) -> None:
    nodes = list(topology)
    topology_ids = [node.get("topologyId") for node in nodes]
    if any(not isinstance(topology_id, str) or not topology_id for topology_id in topology_ids):
        raise TopologyValidationError("Every topology node requires a topologyId")
    if len(topology_ids) != len(set(topology_ids)):
        raise TopologyValidationError("Topology node identifiers are not unique")
    valid_ids = set(topology_ids)
    for node in nodes:
        relationships = [
            *node.get("routerNeighbors", []),
            *node.get("children", []),
            *node.get("route", {}).get("routeData", []),
        ]
        for relationship in relationships:
            for endpoint in ("sourceId", "targetId"):
                if relationship.get(endpoint) not in valid_ids:
                    raise TopologyValidationError(
                        f"Relationship endpoint {relationship.get(endpoint)!r} does not resolve"
                    )


def build_topology_snapshot(
    diagnostics: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build canonical nodes and directional relationships from Matter reports."""

    nodes = [_initialize_node(record) for record in diagnostics]
    reporters = list(nodes)
    index = _TopologyIndex(nodes)
    for reporter in reporters:
        _derive_reporter_relationships(reporter, index)
    _infer_rloc16_children(nodes)
    for node in nodes:
        _set_totals(node)
    nodes.sort(
        key=lambda node: (
            bool(node.get("relationshipOnly")),
            node.get("nodeId") if isinstance(node.get("nodeId"), int) else 1 << 64,
            node["topologyId"],
        )
    )
    validate_topology(nodes)
    assert_snapshot_safe(nodes)
    return nodes


def build_mesh_diagnostic_snapshot(
    diagnostics: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return relationship-rich commissioned reporters without placeholders."""

    return [
        node
        for node in build_topology_snapshot(diagnostics)
        if not node.get("relationshipOnly")
    ]