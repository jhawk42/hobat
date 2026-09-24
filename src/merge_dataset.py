#!/usr/bin/env python3
"""Merge multiple Thread topology JSON files into one detailed cache file."""

from __future__ import annotations

import argparse
import json
import logging

from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from extaddr_device_label_map import (
    EXTADDR_FIELD_ALIASES,
    load_extaddr_device_label_map_flexible,
)
from otbr_restapi_util import RECOMMENDED_DIAGNOSTIC_TLVS
from td_json_key_normalizer import convert_keys_to_camel_case
from td_device_fields import (
    EXT_ADDRESS_ALIASES,
    OMR_ADDRESS_ALIASES,
    get_canonical_ext_address as get_canonical_extaddr,
    get_canonical_omr_address as get_canonical_omr,
    is_placeholder_ext_address as is_placeholder_extaddr,
    is_placeholder_device_label,
    is_placeholder_omr_address,
    normalize_identifier_text,
    normalize_input_record,
)
from td_device_merge import MergeContext, create_merge_context, sort_sources_by_priority
from td_record_merge import (
    append_merge_conflict,
    merge_lists,
    merge_unique_strings,
    value_is_empty,
    values_equivalent,
)
from td_const import (
    EVE_TOPOLOGY_FILENAME,
    EXTADDR_DEVICE_LABEL_MAP_FILENAME,
    HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME,
    HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_TOPOLOGY_FILENAME,
    MDNS_SCOPES_BR_FILENAME,
    MDNS_SCOPES_HAP_FILENAME,
    MDNS_SCOPES_MATTER_FILENAME,
    MDNS_SCOPES_THREAD_FILENAME,
    MERGED_TOPOLOGY_ALL_FILENAME,
    OTBR_CLI_MESHDIAG_ROUTER_CHILDTABLES_FILENAME,
    OTBR_CLI_MESHDIAG_ROUTER_NEIGHBORTABLES_FILENAME,
    OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME,
    OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
    OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME,
    OTBR_CLI_ROUTER_TABLE_FILENAME,
    OTBR_CLI_THREAD_NETWORK_INFO_FILENAME,
    OTBR_RESTAPI_DEVICES_FETCH_FILENAME,
    OTBR_RESTAPI_DEVICES_FILENAME,
    OTBR_RESTAPI_DEVICES_LIST_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_LIST_FILENAME,
    OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    TD_DATA_DIR_ARG_HELP,
)
from util_data import (
    load_optional_input,
    read_network_scope,
    resolve_data_dir,
    save_json_atomic,
    write_network_scope,
)
from util_data import TDRequiredInputMissingError


from merge_report import (
    MergeCommandInputs,
    MergeSupportingData,
    MergeCommandResult,
    evaluate_merge_viability,
    write_merge_outputs,
)

from merge_policy_mdns import (
    merge_mdns_service_info,
    get_mdns_event_priority,
    merge_mdns_records,
    is_mdns_record,
    is_matter_operational_mdns_record,
    _normalize_alias_text,
    _append_unique_alias,
    _extract_service_info_property_decoded,
    get_matter_fabric_node_identity,
    update_mdns_aliases,
    extract_mdns_merge_view,
    apply_mdns_merge_view,
    merge_mdns_record_into_node,
)

from merge_policy_relationship import (
    get_partition_id,
    merge_route_data,
    _merge_relationship_records,
    merge_children_array,
    merge_router_neighbors,
    _merge_route_field,
    _merge_relationship_field,
    _merge_neighbor_field,
    _merge_address_field,
    is_sequence_newer,
    compare_sequences,
)

from merge_policy_identity import (
    first_normalized_identifier,
    normalize_record_aliases,
    derive_mode_device,
    normalize_identifiers,
    find_candidate_node_ids,
    add_identifier,
    filter_candidate_ids_for_extaddr_consistency,
)

PRIORITY_FIELDS = [
    # === TIER 1: Primary Identity (Essential P0) ===
    # Ordered by stability: extaddr (immutable) > OMR IPv6 (stable) > rloc16 (changes rapidly)
    "extAddress",              # REST API alias
    "extaddr",
    "deviceLabel",
    "name",
    "omrIpv6Address",          # More stable than rloc16
    "rloc16",                  # May change rapidly, partition-scoped
    "routerId",                # REST API
    "eui64",                   # Alternative to extaddr
    "id",                      # REST API UUID
    "ID",                      # Alias
    
    # === TIER 2: Secondary Identity (Important P1) ===
    "mlEidIid",                # ML-EID Interface ID
    "room",
    "Extended MAC",            # Eve format
    "nextHop",                # Eve format
    "pathCost",               # Eve format
    "linkQualityIn",                   # Eve format
    "linkQualityOut",                  # Eve format
    "age",                     # Eve format / Child age
    
    # === TIER 3: Device Role & Status (Important P1) ===
    "type",
    "role",
    "Role",                    # Eve format
    "isRouter",                # REST API alias
    "isBorderRouter",          # REST API alias
    "br",                      # CLI - is border router
    "leader",                  # Leader status
    "isLeader",                # REST API alias
    "isPrimaryBBR",            # Is primary backbone router
    "status",
    "mode.device",
    "mode.deviceTypeFTD",      # FTD vs MTD indicator
    "ver",
    "version",
    "threadVersion",
    "threadStackVersion",      # REST API alias
    
    # === TIER 4: Topology & Connectivity (Important P1) ===
    "totalChildren",
    "hasChildren",
    "totalLinks",
    "totalLink3",
    "totalLink2",
    "totalLink1",
    "routerNeighborsCount",
    "childTableCount",
    
    # Partition and Leader Data (Essential P0 for routing)
    "leaderData.partitionId",  # REST API alias
    "leaderData.leaderRouterId",  # REST API alias
    "leaderData.dataVersion",  # REST API alias
    "leaderData.stableDataVersion",  # REST API alias
    "leaderData.weighting",    # REST API alias
    
    # Connectivity Fields (Important P1)
    "connectivity.idSequence",  # REST API alias
    "connectivity.activeRouters",
    "connectivity.linkQuality3",
    "connectivity.linkQuality2",
    "connectivity.linkQuality1",
    "connectivity.leaderCost",
    "connectivity.parentPriority",
    "connectivity.sedBufferSize",
    "connectivity.sedDatagramCount",
    
    # Route Data Fields (Essential P0 for routing)
    "route.idSequence",        # REST API alias (note: different parent name)
    "route",                   # REST API parent object
    
    # === TIER 5: Advanced/Diagnostic (Optional P2) ===
    "icon",
    "scope",                   # mDNS scope
    
    # Vendor Information
    "vendorName",
    "vendorModel",
    "vendorSwVersion",
    "tlvValues",              # CLI TLV values
    
    # MAC Counters (CLI only)
    "macCounters.ifInErrorsPct",
    "macCounters.ifOutErrorsPct",
    "macCounters.ifInDiscardsPct",
    "macCounters.ifOutDiscardsPct",
    "macCounters.ifTotalErrorsTotalPktsRatio",
    "macCounters.ifTotalDiscardsTotalPktsRatio",
    
    # MLE Counters (CLI only)
    "mleCounters.partitionIdChanges",
    "mleCounters.betterPartitionAttachAttempts",
    "mleCounters.totalParentPartitionChanges",
    "mleCounters.parentChanges",
    
    # Time Statistics (CLI only)
    "timeStatistics.routerPct",
    "timeStatistics.detachedDisabledPct",
    "timeStatistics",         # Parent object
    
    # mDNS Fields
    "recordKey",              # mDNS unique key
    "event",                   # mDNS event type
    "capturedAtEpoch",       # mDNS timestamp
    "capturedAtIso",         # mDNS ISO timestamp
    
    # REST API specific
    "created",                 # REST API creation timestamp
    "hostsService",            # Hosts service flag
    
    # Child/Neighbor details
    "children",                # Child array
    "childTable",              # REST API child array
    "childIpv6Addresses",      # REST API child IPv6 addresses
    "routerNeighbors",         # REST API router neighbors
]

# Canonical merge identity model used by merge/index matching logic.
MERGE_STRATEGIES = {
    "by_identity": "by-identity",
}

MATTER_IDENTITY_MERGE_MODES = {
    "strict_omr": "strict-omr",
    "composite_guard": "composite-guard",
}

MERGE_IDENTITY_FIELDS = {
    "extaddr_aliases": EXT_ADDRESS_ALIASES,
    "omr_ipv6_addr_aliases": OMR_ADDRESS_ALIASES,
    "rloc16": "rloc16",
}

from td_source_authority import AUTHORITY, source_rank

SOURCE_PRECEDENCE = AUTHORITY.source_defaults


def load_merge_groups(manifest: dict) -> dict[str, list[str]]:
    declared = manifest["mergeGroups"]
    groups: dict[str, list[str]] = {}
    for name, definition in declared.items():
        if "composedOf" in definition:
            groups[name] = [file for part in definition["composedOf"] for file in groups[part]]
            continue
        ordered = [(item["order"], item["file"]) for item in definition.get("files", [])
                   if item.get("enabled", True)]
        for dataset in manifest["datasets"]:
            if name not in dataset.get("mergeGroups", []):
                continue
            ordered.extend((item["order"], item["file"])
                           for item in dataset.get("mergeInputs", []) if item.get("enabled", True))
        ordered.sort(key=lambda pair: pair[0])
        if len({order for order, _ in ordered}) != len(ordered):
            raise ValueError(f"Duplicate merge input order in group {name}")
        groups[name] = [file for _, file in ordered]
    return groups


from td_dataset_catalog import load_dataset_catalog

GROUP_TO_INPUT_FILES: dict[str, list[str]] = load_merge_groups(load_dataset_catalog())
SYSTEM_INPUT_FILES = GROUP_TO_INPUT_FILES["system"]
OTBR_CLI_INPUT_FILES = GROUP_TO_INPUT_FILES["otbr-cli"]
OTBR_RESTAPI_INPUT_FILES = GROUP_TO_INPUT_FILES["otbr-restapi"]
HA_MATTER_WS_INPUT_FILES = GROUP_TO_INPUT_FILES["ha-matter-ws"]
MDNS_INPUT_FILES = GROUP_TO_INPUT_FILES["mdns"]
EVE_INPUT_FILES = GROUP_TO_INPUT_FILES["eve"]
DEFAULT_FULL_INPUT_FILES = GROUP_TO_INPUT_FILES["full"]

def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def extract_records(filename: str, data: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                records.append(normalize_record_aliases(deepcopy(item)))
        return records

    if not isinstance(data, dict):
        return records

    if "data" in data and isinstance(data["data"], list):
        for item in data["data"]:
            if not isinstance(item, dict):
                continue
            merged_item = deepcopy(item)
            attrs = merged_item.get("attributes")
            if isinstance(attrs, dict):
                for k, v in attrs.items():
                    if k not in merged_item:
                        merged_item[k] = deepcopy(v)
            records.append(normalize_record_aliases(merged_item))
        return records

    # Eve topology is a dict keyed by rloc16-like strings.
    for map_key, item in data.items():
        if not isinstance(item, dict):
            continue
        copied = deepcopy(item)
        copied.setdefault("_map_key", map_key)
        records.append(normalize_record_aliases(copied))

    return records



MERGE_FIELD_HANDLERS = {
    "route": _merge_route_field,
    "children": _merge_relationship_field,
    "childTable": _merge_relationship_field,
    "childIpv6Addresses": _merge_address_field,
    "routerNeighbors": _merge_neighbor_field,
}


def deep_merge(
    base: dict[str, Any],
    incoming: dict[str, Any],
    path_prefix: str = "",
    conflict_target: dict[str, Any] | None = None,
    context: MergeContext | None = None,
) -> dict[str, Any]:
    """
    Deep merge with Phase 2 enhancements:
    - Route data merge by composite identity
    - Children array merge by composite identity
    - Router neighbors merge by identity
    - Partition-aware constraints
    - Sequence number precedence
    """
    if conflict_target is None:
        conflict_target = base

    # Phase 2: Extract partition and RLOC16 for context-aware merges
    partition_id = get_partition_id(conflict_target)
    incoming_partition_id = get_partition_id(incoming)
    owner_rloc16 = normalize_identifier_text(conflict_target.get("rloc16"))
    if context is None:
        context = MergeContext(
            owner_rloc16=owner_rloc16,
            partition_id=partition_id,
            incoming_partition_id=incoming_partition_id,
            conflict_target=conflict_target,
        )

    for key, value in incoming.items():
        if key == "_merge_conflicts":
            existing_conflicts = conflict_target.setdefault(
                "_merge_conflicts", [])
            if isinstance(existing_conflicts, list) and isinstance(value, list):
                for conflict in value:
                    if len(existing_conflicts) >= 20:
                        break
                    if conflict not in existing_conflicts:
                        existing_conflicts.append(deepcopy(conflict))
            continue

        if key == "_source_files":
            existing_sources = (
                base.get("_source_files")
                if isinstance(base.get("_source_files"), list)
                else []
            )
            incoming_sources = value if isinstance(value, list) else []
            base["_source_files"] = merge_unique_strings(
                existing_sources, incoming_sources
            )
            continue

        current_path = f"{path_prefix}.{key}" if path_prefix else key
        handler = MERGE_FIELD_HANDLERS.get(key)
        if handler is not None:
            base[key] = handler(base.get(key), value, context.for_field(key))
            continue
        
        if key not in base:
            base[key] = deepcopy(value)
            continue

        cur = base[key]
        if isinstance(cur, dict) and isinstance(value, dict):
            deep_merge(cur, value, current_path, conflict_target, context.for_field(key))
        elif isinstance(cur, list) and isinstance(value, list):
            base[key] = merge_lists(cur, value)
        elif value_is_empty(cur) and not value_is_empty(value):
            base[key] = deepcopy(value)
        elif key == "extAddress" and is_placeholder_extaddr(cur) and not is_placeholder_extaddr(value):
            # Prefer a concrete extaddr over known placeholder values.
            base[key] = deepcopy(value)
        elif key == "deviceLabel" and is_placeholder_device_label(cur) and not is_placeholder_device_label(value) and not value_is_empty(value):
            base[key] = deepcopy(value)
        elif (
            not value_is_empty(cur)
            and not value_is_empty(value)
            and not values_equivalent(cur, value)
        ):
            append_merge_conflict(
                conflict_target,
                current_path,
                cur,
                value,
                limit=context.conflict_limit,
            )
    return base


def nested_get(record: dict[str, Any], dotted_key: str) -> Any:
    parts = dotted_key.split(".")
    cur: Any = record
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def collect_merge_identity_values(record: dict[str, Any]) -> dict[str, str]:
    identities: dict[str, str] = {}

    extaddr = get_canonical_extaddr(record)
    if extaddr:
        identities["extAddress"] = extaddr

    omr = get_canonical_omr(record)
    if omr and not is_placeholder_omr_address(omr):
        identities["omrIpv6Address"] = omr

    rloc16 = normalize_identifier_text(
        record.get(MERGE_IDENTITY_FIELDS["rloc16"]))
    if rloc16:
        identities["rloc16"] = rloc16

    matter_id = get_matter_fabric_node_identity(record)
    if matter_id:
        identities["matter_fabric_node"] = matter_id

    return identities




def index_node_identity_values(
    node: dict[str, Any],
    node_id: int,
    by_rloc16: dict[str, int],
    by_extaddr: dict[str, int],
    by_omr: dict[str, int],
    by_matter_fabric_node: dict[str, int],
) -> dict[str, str]:
    identity_values = collect_merge_identity_values(node)

    rloc16 = identity_values.get("rloc16")
    extaddr = identity_values.get("extAddress")
    omr = identity_values.get("omrIpv6Address")
    matter_id = identity_values.get("matter_fabric_node")

    if isinstance(extaddr, str):
        node["extAddress"] = extaddr
        add_identifier(by_extaddr, extaddr, node_id)
    if isinstance(omr, str):
        node["omrIpv6Address"] = omr
        add_identifier(by_omr, omr, node_id)
    if isinstance(rloc16, str):
        node["rloc16"] = rloc16
        add_identifier(by_rloc16, rloc16, node_id)
    if isinstance(matter_id, str):
        add_identifier(by_matter_fabric_node, matter_id, node_id)

    return identity_values


def filter_candidate_ids_for_matter_identity_consistency(
    candidate_ids: set[int],
    incoming_record: dict[str, Any],
    nodes: dict[int, dict[str, Any]],
) -> set[int]:
    """For Matter operational mDNS records, avoid OMR-only false merges.

    Rules:
    - If incoming record has no Fabric+Node composite identity, keep all candidates.
    - If candidate has concrete extaddr matching incoming extaddr, keep (strong identity).
    - Else if candidate has Matter composite identity, keep only exact match.
    - Else keep only when rloc16 also matches; otherwise drop (OMR-only weak match).
    """
    incoming_matter_id = get_matter_fabric_node_identity(incoming_record)
    if not incoming_matter_id:
        return candidate_ids

    incoming_extaddr = get_canonical_extaddr(incoming_record)
    incoming_rloc16 = normalize_identifier_text(incoming_record.get("rloc16"))

    filtered: set[int] = set()
    for node_id in candidate_ids:
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            continue

        node_extaddr = get_canonical_extaddr(node)
        if (
            incoming_extaddr
            and node_extaddr
            and not is_placeholder_extaddr(node_extaddr)
            and node_extaddr == incoming_extaddr
        ):
            filtered.add(node_id)
            continue

        node_matter_id = get_matter_fabric_node_identity(node)
        if node_matter_id:
            if node_matter_id == incoming_matter_id:
                filtered.add(node_id)
            continue

        node_rloc16 = normalize_identifier_text(node.get("rloc16"))
        if incoming_rloc16 and node_rloc16 and incoming_rloc16 == node_rloc16:
            filtered.add(node_id)

    return filtered






def merge_nodes(
    target_id: int,
    source_id: int,
    nodes: dict[int, dict[str, Any]],
    by_rloc16: dict[str, int],
    by_extaddr: dict[str, int],
    by_omr: dict[str, int],
    by_matter_fabric_node: dict[str, int],
) -> int:
    if target_id == source_id:
        return target_id

    target = nodes[target_id]
    source = nodes[source_id]
    merge_mdns_record_into_node(target, source)
    existing_source = next(iter(target.get("_source_files", [])), "")
    incoming_source = next(iter(source.get("_source_files", [])), "")
    deep_merge(
        target,
        source,
        context=create_merge_context(
            existing_source,
            incoming_source,
            SOURCE_PRECEDENCE,
            owner_rloc16=normalize_identifier_text(target.get("rloc16")),
            partition_id=get_partition_id(target),
            incoming_partition_id=get_partition_id(source),
            conflict_target=target,
        ),
    )

    for lookup in (by_rloc16, by_extaddr, by_omr, by_matter_fabric_node):
        for key, value in list(lookup.items()):
            if value == source_id:
                lookup[key] = target_id

    del nodes[source_id]
    return target_id


def build_merged_records(
    base_dir: Path,
    omr_prefix: str,
    input_files: list[str],
    device_label_map: dict[str, str],
    matter_identity_mode: str = MATTER_IDENTITY_MERGE_MODES["strict_omr"],
    *,
    input_data: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    nodes: dict[int, dict[str, Any]] = {}
    by_rloc16: dict[str, int] = {}
    by_extaddr: dict[str, int] = {}
    by_omr: dict[str, int] = {}
    by_matter_fabric_node: dict[str, int] = {}
    next_id = 1

    records_read_by_source: dict[str, int] = {}
    new_nodes_by_source: dict[str, int] = defaultdict(int)
    matched_existing_by_source: dict[str, int] = defaultdict(int)
    identity_collision_count = 0
    identity_collision_examples: list[dict[str, Any]] = []

    ordered_input_files = sort_sources_by_priority(input_files, SOURCE_PRECEDENCE)
    loaded: dict[str, tuple[Any, list[dict[str, Any]]]] = {}
    scopes: dict[str, dict[str, Any] | None] = {}
    errors: dict[str, str | None] = {}
    for filename in ordered_input_files:
        data = input_data[filename] if input_data is not None else load_json(base_dir / filename)
        records = extract_records(filename, data)
        loaded[filename] = (data, records)
        scopes[filename], errors[filename] = read_network_scope(base_dir / filename) if (base_dir / filename).exists() else (None, "missing-sidecar")

    chosen = next((scopes[name] for provenance in ("observed", "operator")
                   for name in ordered_input_files if scopes[name] is not None
                   and scopes[name].get("provenance") == provenance
                   and scopes[name].get("extPanId")), None)
    output_id = chosen["extPanId"] if chosen else None
    excluded: list[dict[str, Any]] = []
    for filename in ordered_input_files:
        data, records = loaded[filename]
        scope = scopes[filename]
        mismatch = scope is not None and scope.get("extPanId") and output_id and scope["extPanId"] != output_id
        conflicted = scope is not None and str(scope.get("reason") or "").startswith("multiple-instances-in-scope")
        if errors[filename] not in (None, "missing-sidecar") or mismatch or conflicted:
            excluded.append({
                "filename": filename,
                "extPanId": scope.get("extPanId") if scope else None,
                "recordCount": len(records),
                "reason": "multiple-instances-in-scope" if conflicted else "cross-instance" if mismatch else errors[filename],
            })
            records_read_by_source[filename] = len(records)
            continue
        records_read_by_source[filename] = len(records)
        for raw_record in records:
            record = normalize_identifiers(raw_record, omr_prefix)

            record_extaddr = record.get("extAddress")
            if isinstance(record_extaddr, str):
                mapped_label = device_label_map.get(
                    record_extaddr.lower())
                if mapped_label and value_is_empty(record.get("deviceLabel")):
                    record["deviceLabel"] = mapped_label

            record.setdefault("_source_files", [])
            if filename not in record["_source_files"]:
                record["_source_files"].append(filename)

            identity_values = collect_merge_identity_values(record)
            rloc16 = identity_values.get("rloc16")
            extaddr = identity_values.get("extAddress")
            omr = identity_values.get("omrIpv6Address")

            candidate_ids = find_candidate_node_ids(
                identity_values,
                by_rloc16,
                by_extaddr,
                by_omr,
                by_matter_fabric_node,
            )

            # Guard against collapsing distinct devices that only share weak identities
            # (e.g. reused rloc16/OMR) but have conflicting concrete extaddr values.
            if isinstance(extaddr, str) and not is_placeholder_extaddr(extaddr):
                candidate_ids = filter_candidate_ids_for_extaddr_consistency(
                    candidate_ids,
                    extaddr,
                    nodes,
                )

            if matter_identity_mode == MATTER_IDENTITY_MERGE_MODES["composite_guard"]:
                candidate_ids = filter_candidate_ids_for_matter_identity_consistency(
                    candidate_ids,
                    record,
                    nodes,
                )

            if not candidate_ids:
                node_id = next_id
                next_id += 1
                nodes[node_id] = deepcopy(record)
                if is_mdns_record(record):
                    update_mdns_aliases(nodes[node_id], record)
                new_nodes_by_source[filename] += 1
            else:
                matched_existing_by_source[filename] += 1
                if len(candidate_ids) > 1:
                    identity_collision_count += 1
                    if len(identity_collision_examples) < 10:
                        identity_collision_examples.append(
                            {
                                "source_file": filename,
                                "candidate_node_ids": sorted(candidate_ids),
                                "rloc16": rloc16,
                                "extAddress": extaddr,
                                "omrIpv6Address": omr,
                            }
                        )
                node_id = min(candidate_ids)
                for other_id in sorted(candidate_ids):
                    node_id = merge_nodes(
                        node_id,
                        other_id,
                        nodes,
                        by_rloc16,
                        by_extaddr,
                        by_omr,
                        by_matter_fabric_node,
                    )
                merge_mdns_record_into_node(nodes[node_id], record)
                existing_source = next(
                    iter(nodes[node_id].get("_source_files", [])), ""
                )
                deep_merge(
                    nodes[node_id],
                    record,
                    context=create_merge_context(
                        existing_source,
                        filename,
                        SOURCE_PRECEDENCE,
                        owner_rloc16=normalize_identifier_text(
                            nodes[node_id].get("rloc16")
                        ),
                        partition_id=get_partition_id(nodes[node_id]),
                        incoming_partition_id=get_partition_id(record),
                        network_scope=f"extpan:{output_id or 'unknown'}",
                        incoming_network_scope=f"extpan:{output_id or 'unknown'}",
                        conflict_target=nodes[node_id],
                        matter_identity_mode=matter_identity_mode,
                    ),
                )
                existing_sources = nodes[node_id].setdefault(
                    "_source_files", [])
                if filename not in existing_sources:
                    existing_sources.append(filename)

            # Re-read after merges in case node id changed.
            active = nodes[node_id]
            active_identity_values = index_node_identity_values(
                active,
                node_id,
                by_rloc16,
                by_extaddr,
                by_omr,
                by_matter_fabric_node,
            )
            active_extaddr = active_identity_values.get("extAddress")
            if isinstance(active_extaddr, str):
                mapped_label = device_label_map.get(active_extaddr)
                if mapped_label and value_is_empty(active.get("deviceLabel")):
                    active["deviceLabel"] = mapped_label

    merged_records: list[dict[str, Any]] = []
    for _, node in sorted(
        nodes.items(), key=lambda x: (x[1].get("rloc16") or "", x[0])
    ):
        source_files = node.get("_source_files")

        # Build _merge_identity_keys (mirrors JS mergeRowsByStrategy output).
        identity_key_parts: list[str] = []
        iv = collect_merge_identity_values(node)
        if iv.get("extAddress"):
            identity_key_parts.append(f"extAddress:{iv['extAddress']}")
        if iv.get("rloc16"):
            identity_key_parts.append(f"rloc16:{iv['rloc16']}")
        if iv.get("omrIpv6Address"):
            identity_key_parts.append(f"omrIpv6Address:{iv['omrIpv6Address']}")
        if identity_key_parts:
            node["_merge_identity_keys"] = identity_key_parts

        ordered: dict[str, Any] = {}

        for key in PRIORITY_FIELDS:
            if "." in key:
                continue
            elif key in node:
                ordered[key] = node[key]

        for key, value in node.items():
            if key not in ordered:
                ordered[key] = value

        merged_records.append(ordered)

    merged_nodes_by_source: dict[str, int] = defaultdict(int)
    single_source_nodes_by_source: dict[str, int] = defaultdict(int)
    multi_source_nodes = 0

    for node in nodes.values():
        source_files = node.get("_source_files") or []
        if not isinstance(source_files, list):
            continue

        unique_sources = sorted(
            {s for s in source_files if isinstance(s, str)})
        if len(unique_sources) > 1:
            multi_source_nodes += 1
        if len(unique_sources) == 1:
            single_source_nodes_by_source[unique_sources[0]] += 1
        for src in unique_sources:
            merged_nodes_by_source[src] += 1

    report = {
        "networkInstance": {
            "extPanId": output_id,
            "networkName": chosen.get("networkName") if chosen else None,
            "provenance": chosen["provenance"] if chosen else "unknown",
            "sources": chosen.get("sources", []) if chosen else [],
            "excluded": excluded,
        },
        "input_files": ordered_input_files,
        "matter_identity_mode": matter_identity_mode,
        "records_read_by_source": records_read_by_source,
        "new_nodes_by_source": dict(sorted(new_nodes_by_source.items())),
        "matched_existing_by_source": dict(sorted(matched_existing_by_source.items())),
        "merged_nodes_by_source": dict(sorted(merged_nodes_by_source.items())),
        "single_source_nodes_by_source": dict(
            sorted(single_source_nodes_by_source.items())
        ),
        "single_source_nodes_total": sum(single_source_nodes_by_source.values()),
        "multi_source_nodes_total": multi_source_nodes,
        "identity_collision_count": identity_collision_count,
        "identity_collision_examples": identity_collision_examples,
        "total_merged_nodes": len(merged_records),
    }

    # Phase 3 cleanup: merged records are now canonical camelCase.
    merged_records_camel = convert_keys_to_camel_case(merged_records)
    return merged_records_camel, report


def parse_file_list_args(values: list[str] | None) -> list[str]:
    if not values:
        return []

    result: list[str] = []
    for value in values:
        for token in value.split(","):
            candidate = token.strip()
            if candidate:
                result.append(candidate)
    return result


def resolve_input_groups(group_names: list[str]) -> list[str]:
    resolved: list[str] = []
    unknown = [name for name in group_names if name not in GROUP_TO_INPUT_FILES]
    if unknown:
        raise ValueError(f"Unknown input group(s): {', '.join(unknown)}")

    for group_name in group_names:
        resolved.extend(GROUP_TO_INPUT_FILES[group_name])
    return resolved


def resolve_input_files(
    default_files: list[str],
    include_files: list[str],
    exclude_files: list[str],
) -> list[str]:
    resolved = list(dict.fromkeys([*default_files, *include_files]))

    excluded = set(exclude_files)
    resolved = [filename for filename in resolved if filename not in excluded]

    if not resolved:
        raise ValueError(
            "No input files selected after applying include/exclude options."
        )

    return resolved


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge Thread topology JSON sources into one detailed cache file.",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Directory containing input JSON files (default: current directory).",
    )
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    parser.add_argument(
        "--dataset-file",
        default=OTBR_CLI_THREAD_NETWORK_INFO_FILENAME,
        help="File that contains prefix_omr_ipv6addr_prefix.",
    )
    parser.add_argument(
        "--output",
        default=MERGED_TOPOLOGY_ALL_FILENAME,
        help="Output merged JSON file path.",
    )
    # add --include-groups 
    parser.add_argument(
        "--include-groups",
        nargs="*",
        default="full",
        help=(
            "Extra JSON source groups to include. "
            "Supports space-separated and/or comma-separated group names. "
            "Available groups: " + ", ".join(GROUP_TO_INPUT_FILES.keys())
        ),
    )

    parser.add_argument(
        "--include-files",
        nargs="*",
        default=[],
        help=(
            "Extra JSON source files to include. "
            "Supports space-separated and/or comma-separated file names."
        ),
    )
    parser.add_argument(
        "--exclude-files",
        nargs="*",
        default=[],
        help=(
            "JSON source files to exclude from defaults. "
            "Supports space-separated and/or comma-separated file names."
        ),
    )
    parser.add_argument(
        "--report-file",
        default="",
        help="Optional path to write merge validation report JSON.",
    )
    parser.add_argument(
        "--extaddr-map-file",
        default=EXTADDR_DEVICE_LABEL_MAP_FILENAME,
        help="Reference file used only for extaddr to device_label lookup.",
    )
    parser.add_argument(
        "--merge-strategy",
        default="merge",
        choices=["merge", "none"],
        help=(
            "merge (default): identify-and-merge records from all sources. "
            "none: pass-through mode — all records from all sources are "
            "collected as-is without identity matching or deduplication."
        ),
    )
    parser.add_argument(
        "--matter-identity-mode",
        default=MATTER_IDENTITY_MERGE_MODES["strict_omr"],
        choices=[
            MATTER_IDENTITY_MERGE_MODES["strict_omr"],
            MATTER_IDENTITY_MERGE_MODES["composite_guard"],
        ],
        help=(
            "strict-omr (default): collapse Matter mDNS records by shared OMR identity and "
            "preserve per-fabric/per-node distinctions in _mdns_aliases. "
            "composite-guard: prevent OMR-only merges when FabricID_compressed+NodeID differ."
        ),
    )
    return parser.parse_args(argv)








def resolve_merge_command_inputs(
    args: argparse.Namespace,
    data_dir: Path,
) -> MergeCommandInputs:
    base_dir = data_dir if args.base_dir == "." else Path(args.base_dir)
    raw_groups = args.include_groups
    group_values = [raw_groups] if isinstance(raw_groups, str) else raw_groups
    group_names = parse_file_list_args(group_values)
    default_files = resolve_input_groups(group_names) if group_names else []
    include_files = parse_file_list_args(args.include_files)
    exclude_files = parse_file_list_args(args.exclude_files)
    input_files = resolve_input_files(default_files, include_files, exclude_files)

    required_files = frozenset(include_files).intersection(input_files)
    loaded_input_files: list[str] = []
    skipped_files: list[dict[str, str]] = []
    for filename in input_files:
        source_path = base_dir / filename
        if source_path.is_file():
            loaded_input_files.append(filename)
        elif filename in required_files:
            raise TDRequiredInputMissingError(
                command_path="merge-dataset",
                data_dir=base_dir,
                missing_file=source_path,
                classification="required",
                action="fail code=4",
            )
        else:
            logging.warning(
                "merge-dataset: skipping missing optional input file %s",
                source_path,
            )
            skipped_files.append({"file": filename, "reason": "missing"})

    if not loaded_input_files:
        raise TDRequiredInputMissingError(
            command_path="merge-dataset",
            data_dir=base_dir,
            missing_file=base_dir / "<all-input-files>",
            classification="required-seed",
            action="fail code=4",
        )

    return MergeCommandInputs(
        data_dir=base_dir,
        input_files=tuple(input_files),
        required_files=required_files,
        loaded_input_files=tuple(loaded_input_files),
        skipped_files=tuple(skipped_files),
        dataset_path=base_dir / args.dataset_file,
        extaddr_map_path=base_dir / args.extaddr_map_file,
        output_path=base_dir / args.output,
        report_path=base_dir / args.report_file if args.report_file else None,
        dataset_file=args.dataset_file,
        extaddr_map_file=args.extaddr_map_file,
        merge_strategy=args.merge_strategy,
        matter_identity_mode=args.matter_identity_mode,
    )


def load_merge_supporting_data(
    command_inputs: MergeCommandInputs,
) -> MergeSupportingData:
    logger = logging.getLogger(__name__)
    extaddr_map_result = load_optional_input(
        command_inputs.extaddr_map_path,
        loader=lambda path: load_extaddr_device_label_map_flexible(
            str(path),
            extaddr_aliases=EXTADDR_FIELD_ALIASES,
        ),
        default_value={},
        command_path="merge-dataset",
        data_dir=command_inputs.data_dir,
        logger=logger,
        classification="optional",
        fallback_action="continue fallback=empty-map",
    )
    dataset_result = load_optional_input(
        command_inputs.dataset_path,
        loader=load_json,
        default_value={},
        command_path="merge-dataset",
        data_dir=command_inputs.data_dir,
        logger=logger,
        classification="optional",
        fallback_action="continue fallback=empty-dataset",
    )

    network_info = dataset_result.value if isinstance(dataset_result.value, dict) else {}
    omr_prefix_value = network_info.get("prefixOmrIpv6AddrPrefix", "")
    omr_prefix = omr_prefix_value if isinstance(omr_prefix_value, str) else ""
    device_label_map = (
        extaddr_map_result.value
        if isinstance(extaddr_map_result.value, dict)
        else {}
    )
    reference_files = (
        {
            "file": command_inputs.extaddr_map_file,
            "loaded": not extaddr_map_result.used_fallback,
            "fallback": extaddr_map_result.used_fallback,
        },
        {
            "file": command_inputs.dataset_file,
            "loaded": not dataset_result.used_fallback,
            "fallback": dataset_result.used_fallback,
        },
    )
    return MergeSupportingData(
        device_label_map=device_label_map,
        network_info=network_info,
        omr_prefix=omr_prefix,
        reference_files=reference_files,
    )




def build_merge_output(
    command_inputs: MergeCommandInputs,
    supporting_data: MergeSupportingData,
) -> MergeCommandResult:
    input_data = {
        filename: load_json(command_inputs.data_dir / filename)
        for filename in command_inputs.loaded_input_files
    }
    merged_records, report = build_merged_records(
        command_inputs.data_dir,
        supporting_data.omr_prefix,
        list(command_inputs.loaded_input_files),
        supporting_data.device_label_map,
        matter_identity_mode=command_inputs.matter_identity_mode,
        input_data=input_data,
    )
    report["input_files"] = list(command_inputs.input_files)
    report["loaded_input_files"] = list(command_inputs.loaded_input_files)
    report["skipped_input_files"] = list(command_inputs.skipped_files)
    report["reference_extaddr_map_file"] = command_inputs.extaddr_map_file
    report["reference_extaddr_map_entries"] = len(supporting_data.device_label_map)
    report["optional_reference_files"] = list(supporting_data.reference_files)

    viable, identity_seed_record_count, viability_reason = evaluate_merge_viability(
        merged_records
    )
    report["required_seed_status"] = {
        "dataset_file": command_inputs.dataset_file,
        "loaded_input_file_count": len(command_inputs.loaded_input_files),
        "identity_seed_record_count": identity_seed_record_count,
        "viable": viable,
    }

    output_records = merged_records
    if command_inputs.merge_strategy == "none":
        passthrough_records: list[dict[str, Any]] = []
        excluded_files = {item["filename"] for item in report["networkInstance"]["excluded"]}
        for filename in command_inputs.loaded_input_files:
            if filename in excluded_files:
                continue
            records = extract_records(filename, input_data[filename])
            for raw_record in records:
                record = normalize_identifiers(raw_record, supporting_data.omr_prefix)
                record.setdefault("_source_files", [filename])
                passthrough_records.append(record)
        output_records = passthrough_records
        report["merge_strategy"] = "none"
        report["passthrough_record_count"] = len(passthrough_records)
        logging.info(
            "merge-strategy=none: collected %s records without merging.",
            len(passthrough_records),
        )
    else:
        report["merge_strategy"] = "merge"

    return MergeCommandResult(
        records=convert_keys_to_camel_case(output_records),
        report=report,
        viable=viable,
        viability_reason=viability_reason,
    )




def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    args = parse_args(argv)
    td_data_dir = resolve_data_dir(data_dir=args.datadir)

    try:
        command_inputs = resolve_merge_command_inputs(args, td_data_dir)
        supporting_data = load_merge_supporting_data(command_inputs)
        result = build_merge_output(command_inputs, supporting_data)
        if not result.viable:
            logging.error("merge-dataset: %s", result.viability_reason)
            save_json_atomic(
                result.records,
                command_inputs.output_path,
                indent=2,
                add_trailing_newline=True,
            )
            if command_inputs.report_path is not None:
                save_json_atomic(
                    result.report,
                    command_inputs.report_path,
                    indent=2,
                    add_trailing_newline=True,
                )
            logging.info("Wrote merge report to %s", command_inputs.report_path)
            logging.info(
                "Wrote %s merged records to %s",
                len(result.records),
                command_inputs.output_path,
            )
            return 3
        write_merge_outputs(
            result,
            command_inputs.output_path,
            command_inputs.report_path,
        )

        if command_inputs.report_path is not None:
            logging.info("Wrote merge report to %s", command_inputs.report_path)
        logging.info(
            "Wrote %s merged records to %s",
            len(result.records),
            command_inputs.output_path,
        )
        logging.info(
            "Validation summary: "
            f"multi_source_nodes={result.report['multi_source_nodes_total']}, "
            f"single_source_nodes={result.report['single_source_nodes_total']}, "
            f"identity_collisions={result.report['identity_collision_count']}"
        )

        return 0
    except TDRequiredInputMissingError as exc:
        logging.error(str(exc))
        return 4
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logging.error(f"merge-dataset invalid payload: {exc}")
        return 5
    except Exception as exc:
        logging.error(f"merge-dataset runtime failure: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
