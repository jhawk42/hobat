#!/usr/bin/env python3
"""Merge multiple Thread topology JSON files into one detailed cache file."""

from __future__ import annotations

import argparse
import json
import logging
import re

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
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
    get_canonical_ext_address,
    get_canonical_omr_address,
    is_placeholder_ext_address,
    normalize_identifier_text as normalize_device_identifier_text,
    normalize_input_record,
)
from td_device_merge import MergeContext, create_merge_context, sort_sources_by_priority
from td_record_merge import (
    append_merge_conflict as append_record_conflict,
    merge_lists as merge_record_lists,
    merge_unique_strings as merge_record_unique_strings,
    value_is_empty as record_value_is_empty,
    values_equivalent as record_values_equivalent,
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
    resolve_data_dir,
    save_json_atomic,
)
from util_data import TDRequiredInputMissingError


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

# Phase 3: Source Precedence Rules (Priority: Higher = Wins)
# Used to resolve conflicts when multiple sources provide same field
SOURCE_PRECEDENCE = {
    EXTADDR_DEVICE_LABEL_MAP_FILENAME: 101, # Highest priority

    OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME: 100, # Highest priority (most detailed)
    OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME: 99,
    OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME: 98,
    OTBR_CLI_MESHDIAG_ROUTER_NEIGHBORTABLES_FILENAME: 97,
    OTBR_CLI_MESHDIAG_ROUTER_CHILDTABLES_FILENAME: 96,
    OTBR_CLI_ROUTER_TABLE_FILENAME: 95,

    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME: 90,
    OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME: 89,
    OTBR_RESTAPI_DIAGNOSTICS_LIST_FILENAME: 88,
    OTBR_RESTAPI_DIAGNOSTICS_FILENAME: 87,
    OTBR_RESTAPI_DEVICES_FETCH_FILENAME: 86,
    OTBR_RESTAPI_DEVICES_LIST_FILENAME: 85,
    OTBR_RESTAPI_DEVICES_FILENAME: 84,

    HA_MATTER_WS_TOPOLOGY_FILENAME: 83,
    HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME: 82,
    HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME: 81,
    HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME: 80,

    EVE_TOPOLOGY_FILENAME: 60,

    MDNS_SCOPES_THREAD_FILENAME: 50,
    MDNS_SCOPES_BR_FILENAME: 49,                # mDNS scopes (service discovery)
    MDNS_SCOPES_HAP_FILENAME: 48,
    MDNS_SCOPES_MATTER_FILENAME: 47,
}


SYSTEM_INPUT_FILES: list[str] = [
    EXTADDR_DEVICE_LABEL_MAP_FILENAME,
]

OTBR_CLI_INPUT_FILES: list[str] = [
    OTBR_CLI_ROUTER_TABLE_FILENAME,
    OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME,
    OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
    OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME,
    OTBR_CLI_MESHDIAG_ROUTER_NEIGHBORTABLES_FILENAME,
    OTBR_CLI_MESHDIAG_ROUTER_CHILDTABLES_FILENAME,
]

OTBR_RESTAPI_INPUT_FILES: list[str] = [
    OTBR_RESTAPI_DEVICES_FETCH_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_DEVICES_LIST_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_LIST_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FILENAME,
    OTBR_RESTAPI_DEVICES_FILENAME,
]

HA_MATTER_WS_INPUT_FILES: list[str] = [
    HA_MATTER_WS_TOPOLOGY_FILENAME,
]

MDNS_INPUT_FILES: list[str] = [
    ##MDNS_SCOPES_THREAD_FILENAME,                 # mDNS Thread devices
    MDNS_SCOPES_BR_FILENAME,                       # mDNS Border Router discovery
    MDNS_SCOPES_HAP_FILENAME,                      # mDNS HomeKit devices
    ##MDNS_SCOPES_MATTER_FILENAME,                 # mDNS Matter devices
]

EVE_INPUT_FILES: list[str] = [
    EVE_TOPOLOGY_FILENAME,
]

DEFAULT_FULL_INPUT_FILES: list[str] = (
                                       ## SYSTEM_INPUT_FILES 
                                       OTBR_CLI_INPUT_FILES 
                                       + OTBR_RESTAPI_INPUT_FILES 
                                       + HA_MATTER_WS_INPUT_FILES
                                       + MDNS_INPUT_FILES 
                                       ##+ EVE_INPUT_FILES
                                       + [])

GROUP_TO_INPUT_FILES: dict[str, list[str]] = {
    "system": SYSTEM_INPUT_FILES,
    "otbr-cli": OTBR_CLI_INPUT_FILES,
    "otbr-restapi": OTBR_RESTAPI_INPUT_FILES,
    "ha-matter-ws": HA_MATTER_WS_INPUT_FILES,
    "mdns": MDNS_INPUT_FILES,
    "eve": EVE_INPUT_FILES,
    "full": DEFAULT_FULL_INPUT_FILES,
}

def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_identifier_text(value: Any) -> str:
    return normalize_device_identifier_text(value)


def first_normalized_identifier(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = normalize_identifier_text(record.get(key))
        if value:
            return value
    return ""


def get_canonical_extaddr(record: dict[str, Any]) -> str:
    return get_canonical_ext_address(record)


def get_canonical_omr(record: dict[str, Any]) -> str:
    return get_canonical_omr_address(record)


def is_placeholder_extaddr(value: Any) -> bool:
    """Return True for known non-identity extaddr placeholder values."""
    return is_placeholder_ext_address(value)


def normalize_record_aliases(record: dict[str, Any]) -> dict[str, Any]:
    extaddr = get_canonical_extaddr(record)
    omr_addr = get_canonical_omr(record)

    if extaddr:
        record["extAddress"] = extaddr
    if omr_addr:
        record["omrIpv6Address"] = omr_addr

    return record


def derive_mode_device(record: dict[str, Any]) -> str:
    mode_device_raw = record.get("mode.device")
    if isinstance(mode_device_raw, str) and mode_device_raw.strip():
        value = mode_device_raw.strip().upper()
        if value in {"FTD", "MTD"}:
            return value

    mode = record.get("mode")
    if isinstance(mode, dict):
        mode_device = mode.get("device")
        if isinstance(mode_device, str) and mode_device.strip():
            value = mode_device.strip().upper()
            if value in {"FTD", "MTD"}:
                return value

        device_type_ftd = mode.get("deviceTypeFTD")
        if isinstance(device_type_ftd, bool):
            return "FTD" if device_type_ftd else "MTD"

        device_type = mode.get("device_type")
        if isinstance(device_type, (int, float)):
            return "FTD" if int(device_type) != 0 else "MTD"

    role = record.get("role")
    if isinstance(role, str):
        role_text = role.strip().lower()
        if role_text in ("router", "border router"):
            return "FTD"
        if role_text == "child":
            return "MTD"

    node_type = record.get("type")
    if isinstance(node_type, str):
        type_text = node_type.strip().lower()
        if type_text in ("router", "border router"):
            return "FTD"
        if "child" in type_text:
            return "MTD"

    return ""


def normalize_identifiers(record: dict[str, Any], omr_prefix: str) -> dict[str, Any]:
    normalized = normalize_input_record(record)
    record.clear()
    record.update(normalized)

    omr_addr = get_canonical_omr(record)

    if not omr_addr:
        ipv6_values = record.get("ipv6Addresses")
        if isinstance(ipv6_values, list):
            prefix = omr_prefix.lower()
            for ip_value in ipv6_values:
                if isinstance(ip_value, str) and ip_value.lower().startswith(prefix):
                    omr_addr = ip_value.lower()
                    break

    if omr_addr:
        record["omrIpv6Address"] = omr_addr

    mode_device = derive_mode_device(record)
    if mode_device:
        record["mode.device"] = mode_device
        mode = record.get("mode")
        if isinstance(mode, dict) and (
            not isinstance(mode.get("device"), str)
            or not mode.get("device", "").strip()
        ):
            mode["device"] = mode_device

    return record


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


def value_is_empty(value: Any) -> bool:
    return record_value_is_empty(value)


def merge_unique_strings(existing: list[Any], incoming: list[Any]) -> list[str]:
    return merge_record_unique_strings(existing, incoming)


def values_equivalent(left: Any, right: Any) -> bool:
    return record_values_equivalent(left, right)


def append_merge_conflict(
    base: dict[str, Any], path: str, cur_val: Any, new_value: Any, limit: int = 20
) -> None:
    append_record_conflict(base, path, cur_val, new_value, limit=limit)


def merge_lists(left: list[Any], right: list[Any]) -> list[Any]:
    return merge_record_lists(left, right)


# ============================================================================
# Phase 2: Field Normalization Functions
# ============================================================================

# Field alias mapping for normalization (camelCase ↔ snake_case)
FIELD_ALIASES_BIDIRECTIONAL = {
    # Identity fields
    "extaddr": ["extAddress", "Extended MAC"],
    "omrIpv6Address": ["omrIpv6Address", "omrIpv6Addr"],
    "router_id": ["routerId"],
    "device_label": ["name", "hostName"],
    "eui64": ["EUI64"],
    
    "route": ["route"],
    "leader_data": ["leaderData"],
    
    # Route data fields
    "route_id": ["routeId"],
    "route_cost": ["routeCost"],
    "link_quality_in": ["linkQualityIn"],
    "link_quality_out": ["linkQualityOut"],
    "id_sequence": ["idSequence"],
    
    # Leader data fields
    "partition_id": ["partitionId"],
    "leader_router_id": ["leaderRouterId"],
    "data_version": ["dataVersion"],
    "stable_data_version": ["stableDataVersion"],
    "weighting": ["weighting"],
    
    # Connectivity fields
    "active_routers": ["activeRouters"],
    "leader_cost": ["leaderCost"],
    "parent_priority": ["parentPriority"],
    "link_quality_3": ["linkQuality3"],
    "link_quality_2": ["linkQuality2"],
    "link_quality_1": ["linkQuality1"],
    "sed_buffer_size": ["sedBufferSize"],
    "sed_datagram_count": ["sedDatagramCount"],
    
    # Border router flags
    "leader": ["isLeader"],
    "is_router": ["isRouter"],
    "is_border_router": ["isBorderRouter"],
    "br": ["isBorderRouter"],
    
    # Vendor fields
    "vendor_name": ["vendorName"],
    "vendor_model": ["vendorModel"],
    "vendor_sw_version": ["vendorSwVersion"],
    "thread_stack_version": ["threadStackVersion"],
    
    # Mode fields
    "rx_on_when_idle": ["rxOnWhenIdle"],
    "device_type": ["deviceTypeFTD"],
    "network_data": ["fullNetworkData"],
}


def get_canonical_field_name(field_name: str) -> str:
    """Get canonical (snake_case) field name from any alias."""
    # Already canonical
    for canonical, aliases in FIELD_ALIASES_BIDIRECTIONAL.items():
        if field_name == canonical:
            return canonical
        if field_name in aliases:
            return canonical
    # Not in mapping, return as-is
    return field_name


def normalize_field_names_in_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize top-level field names to canonical form while preserving aliases."""
    normalized = {}
    seen_canonical = set()
    
    for key, value in record.items():
        canonical = get_canonical_field_name(key)
        
        # Set canonical form
        if canonical not in seen_canonical:
            normalized[canonical] = value
            seen_canonical.add(canonical)
        
        # Preserve original key if different from canonical (for compatibility)
        if key != canonical:
            normalized[key] = value
    
    return normalized


# ============================================================================
# Phase 2: Sequence Number Comparison (RFC 1982)
# ============================================================================

def is_sequence_newer(seq_a: int, seq_b: int, bits: int = 8) -> bool:
    """
    Compare two sequence numbers with wraparound handling (RFC 1982).
    
    Returns True if seq_a is newer than seq_b.
    Uses serial number arithmetic for 8-bit counter (0-255).
    
    Examples:
        100 > 50:  True (no wraparound)
        5 > 250:   True (wraparound: 250→255→0→5)
        250 > 5:   False
        128 > 0:   False (ambiguous, exactly half-max)
    """
    if seq_a == seq_b:
        return False
    
    max_val = 2 ** bits
    half_max = max_val // 2
    
    diff = (seq_a - seq_b) % max_val
    return diff < half_max


def compare_sequences(seq_a: int | None, seq_b: int | None) -> str:
    """
    Compare two sequence numbers, handling None values.
    
    Returns: "a_newer", "b_newer", "equal", or "unknown"
    """
    if seq_a is None and seq_b is None:
        return "unknown"
    if seq_a is None:
        return "b_newer"
    if seq_b is None:
        return "a_newer"
    
    if seq_a == seq_b:
        return "equal"
    
    if is_sequence_newer(seq_a, seq_b):
        return "a_newer"
    else:
        return "b_newer"


# ============================================================================
# Phase 2: Partition Extraction
# ============================================================================

def get_partition_id(record: dict[str, Any]) -> str:
    """
    Extract partitionId from leaderData.
    
    Returns normalized partition_id string or "unknown" if not found.
    """
    # Canonical merged format
    leader_data = record.get("leaderData")
    if isinstance(leader_data, dict):
        partition_id = leader_data.get("partitionId")
        if partition_id is not None:
            # Normalize to string
            if isinstance(partition_id, int):
                return f"0x{partition_id:08x}"
            elif isinstance(partition_id, str):
                return partition_id.strip().lower()
    
    return "unknown"


# ============================================================================
# Phase 2: Route Data Merge (Composite Identity)
# ============================================================================

def merge_route_data(
    owner_rloc16: str,
    base_route_data: dict[str, Any],
    incoming_route_data: dict[str, Any],
    partition_id: str,
) -> dict[str, Any]:
    """
    Merge route data using composite identity: (owner_rloc16, destination_route_id).
    
    Uses sequence number precedence (highest wins).
    Only merges routes within same partition.
    
    Args:
        owner_rloc16: RLOC16 of the node that owns this routing table
        base_route_data: Existing route dict
        incoming_route_data: New route dict
        partition_id: Partition ID for validation
    
    Returns:
        Merged route dict
    """
    base = base_route_data
    incoming = incoming_route_data
    
    # Extract sequence numbers
    base_seq = base.get("idSequence")
    incoming_seq = incoming.get("idSequence")
    
    # Compare sequences
    seq_comparison = compare_sequences(base_seq, incoming_seq)
    
    # If incoming has higher sequence, replace entirely
    if seq_comparison == "b_newer":
        logging.debug(f"Route data: incoming sequence {incoming_seq} > base {base_seq}, using incoming")
        return deepcopy(incoming_route_data)
    
    # If base has higher sequence, keep base
    if seq_comparison == "a_newer":
        logging.debug(f"Route data: base sequence {base_seq} > incoming {incoming_seq}, keeping base")
        return deepcopy(base_route_data)
    
    # Sequences equal or both unknown - merge by route identity
    logging.debug(f"Route data: sequences equal ({base_seq}), merging by route identity")
    
    base_routes = base.get("routeData", [])
    incoming_routes = incoming.get("routeData", [])
    
    if not isinstance(base_routes, list):
        base_routes = []
    if not isinstance(incoming_routes, list):
        incoming_routes = []
    
    # Merge by composite identity: (owner_rloc16, dest_route_id)
    merged_routes = {}
    
    for route in base_routes:
        if isinstance(route, dict):
            route_id = route.get("routeId")
            if route_id:
                identity = (owner_rloc16, str(route_id))
                merged_routes[identity] = deepcopy(route)
    
    for route in incoming_routes:
        if isinstance(route, dict):
            route_id = route.get("routeId")
            if route_id:
                identity = (owner_rloc16, str(route_id))
                # If already exists, prefer non-zero link quality values
                if identity in merged_routes:
                    existing = merged_routes[identity]
                    # Merge additional fields
                    for key, value in route.items():
                        if key not in existing or value_is_empty(existing.get(key)):
                            existing[key] = value
                else:
                    merged_routes[identity] = deepcopy(route)
    
    # Reconstruct canonical route object
    result = deepcopy(base_route_data) if base_route_data else deepcopy(incoming_route_data)
    
    # Ensure result has proper structure
    if not isinstance(result, dict):
        result = {}
    
    # Set merged routes
    result["routeData"] = list(merged_routes.values())
    
    # Preserve sequence number
    if base_seq is not None:
        result["idSequence"] = base_seq
    elif incoming_seq is not None:
        result["idSequence"] = incoming_seq
    
    return result


# ============================================================================
# Phase 2: Children Array Merge (Composite Identity)
# ============================================================================

def merge_children_array(
    parent_rloc16: str,
    base_children: list[Any],
    incoming_children: list[Any],
) -> list[dict[str, Any]]:
    """
    Merge children arrays using composite identity: (parent_rloc16, child_extaddr).
    
    Critical: childId is parent-local only, NOT globally unique!
    
    Args:
        parent_rloc16: RLOC16 of the parent node
        base_children: Existing children array
        incoming_children: New children array
    
    Returns:
        Merged children array
    """
    merged = {}
    
    for child in base_children + incoming_children:
        if not isinstance(child, dict):
            continue
        
        # Get child extaddr (globally unique)
        child_extaddr = child.get("extAddress")
        child_rloc16 = child.get("rloc16")
        if not child_extaddr and not child_rloc16:
            # No extaddr - can't create composite identity
            # Add as-is (might be duplicate, but can't determine)
            temp_key = json.dumps(child, sort_keys=True)
            merged[temp_key] = child
            continue
        
        identity_kind = "extAddress" if child_extaddr else "rloc16"
        identity_value = normalize_identifier_text(child_extaddr or child_rloc16)
        identity = (parent_rloc16, identity_kind, identity_value)
        
        if identity not in merged:
            merged[identity] = deepcopy(child)
        else:
            # Merge additional fields (preserve more complete data)
            existing = merged[identity]
            for key, value in child.items():
                if key not in existing or value_is_empty(existing.get(key)):
                    existing[key] = value
                elif not value_is_empty(value) and existing.get(key) != value:
                    # Prefer newer data (e.g., updated age, RSSI)
                    existing[key] = value
    
    return list(merged.values())


# ============================================================================
# Phase 2: Router Neighbors Merge
# ============================================================================

def merge_router_neighbors(
    base_neighbors: list[Any],
    incoming_neighbors: list[Any],
) -> list[dict[str, Any]]:
    """
    Merge routerNeighbors arrays by identity (rloc16 or extaddr).
    
    Args:
        base_neighbors: Existing routerNeighbors array
        incoming_neighbors: New routerNeighbors array
    
    Returns:
        Merged routerNeighbors array
    """
    merged = {}
    
    for neighbor in base_neighbors + incoming_neighbors:
        if not isinstance(neighbor, dict):
            continue
        
        # Identity by extaddr (preferred) or rloc16
        extaddr = neighbor.get("extAddress")
        rloc16 = neighbor.get("rloc16")
        
        if extaddr:
            identity = ("extAddress", normalize_identifier_text(extaddr))
        elif rloc16:
            identity = ("rloc16", normalize_identifier_text(rloc16))
        else:
            # No identity - add as-is
            temp_key = json.dumps(neighbor, sort_keys=True)
            merged[temp_key] = neighbor
            continue
        
        if identity not in merged:
            merged[identity] = deepcopy(neighbor)
        else:
            # Merge additional fields
            existing = merged[identity]
            for key, value in neighbor.items():
                if key not in existing or value_is_empty(existing.get(key)):
                    existing[key] = value
    
    return list(merged.values())


# ============================================================================
# Phase 3: mDNS Service Info Merge
# ============================================================================

def merge_mdns_service_info(
    base_service_info: dict[str, Any],
    incoming_service_info: dict[str, Any],
    base_timestamp: float | None,
    incoming_timestamp: float | None,
) -> dict[str, Any]:
    """
    Merge mDNS service_info objects.
    
    Uses timestamp precedence (newer wins).
    Preserves most complete nested structure.
    
    Args:
        base_service_info: Existing service_info
        incoming_service_info: New service_info
        base_timestamp: Base captured_at_epoch
        incoming_timestamp: Incoming captured_at_epoch
    
    Returns:
        Merged service_info
    """
    # If timestamps available, prefer newer
    if base_timestamp is not None and incoming_timestamp is not None:
        if incoming_timestamp > base_timestamp:
            # Incoming is newer, use it as base
            result = deepcopy(incoming_service_info)
            # Merge any additional fields from base
            for key, value in base_service_info.items():
                if key not in result or value_is_empty(result.get(key)):
                    result[key] = deepcopy(value)
            return result
        else:
            # Base is newer or equal, keep it
            result = deepcopy(base_service_info)
            # Merge any additional fields from incoming
            for key, value in incoming_service_info.items():
                if key not in result or value_is_empty(result.get(key)):
                    result[key] = deepcopy(value)
            return result
    
    # No timestamp comparison possible, merge deeply
    result = deepcopy(base_service_info)
    for key, value in incoming_service_info.items():
        if key not in result:
            result[key] = deepcopy(value)
        elif isinstance(result[key], dict) and isinstance(value, dict):
            # Merge nested dicts
            for nested_key, nested_value in value.items():
                if nested_key not in result[key] or value_is_empty(result[key].get(nested_key)):
                    result[key][nested_key] = deepcopy(nested_value)
        elif value_is_empty(result[key]) and not value_is_empty(value):
            result[key] = deepcopy(value)
    
    return result


def get_mdns_event_priority(event: str) -> int:
    """
    Get priority for mDNS event types.
    
    Priority: add=3, update=2, remove=1
    Higher priority events take precedence.
    """
    event_priorities = {
        "add": 3,
        "update": 2,
        "remove": 1,
    }
    return event_priorities.get(event, 0)


def merge_mdns_records(
    base: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """
    Merge two mDNS records with timestamp and event precedence.
    
    Rules:
    - Newer timestamp wins (captured_at_epoch)
    - If timestamps equal, event priority: add > update > remove
    - service_info merged with timestamp precedence
    
    Args:
        base: Existing mDNS record
        incoming: New mDNS record
    
    Returns:
        Merged mDNS record
    """
    base_timestamp = base.get("capturedAtEpoch", base.get("captured_at_epoch"))
    incoming_timestamp = incoming.get(
        "capturedAtEpoch", incoming.get("captured_at_epoch")
    )
    incoming_is_primary = False
    if isinstance(base_timestamp, (int, float)) and isinstance(
        incoming_timestamp, (int, float)
    ):
        if incoming_timestamp > base_timestamp:
            incoming_is_primary = True
        elif incoming_timestamp == base_timestamp:
            incoming_is_primary = get_mdns_event_priority(
                str(incoming.get("event", ""))
            ) > get_mdns_event_priority(str(base.get("event", "")))

    primary, secondary = (
        (incoming, base) if incoming_is_primary else (base, incoming)
    )
    result = deepcopy(primary)
    for key, value in secondary.items():
        if key in {"serviceInfo", "service_info"}:
            continue
        if key not in result or value_is_empty(result.get(key)):
            result[key] = deepcopy(value)

    base_service = base.get("serviceInfo", base.get("service_info"))
    incoming_service = incoming.get("serviceInfo", incoming.get("service_info"))
    if isinstance(base_service, dict) or isinstance(incoming_service, dict):
        service_key = (
            "serviceInfo"
            if "serviceInfo" in base or "serviceInfo" in incoming
            else "service_info"
        )
        if base_timestamp == incoming_timestamp:
            primary_service = primary.get(service_key, {})
            secondary_service = secondary.get(service_key, {})
            result[service_key] = merge_mdns_service_info(
                primary_service if isinstance(primary_service, dict) else {},
                secondary_service if isinstance(secondary_service, dict) else {},
                None,
                None,
            )
        else:
            result[service_key] = merge_mdns_service_info(
                base_service if isinstance(base_service, dict) else {},
                incoming_service if isinstance(incoming_service, dict) else {},
                base_timestamp if isinstance(base_timestamp, (int, float)) else None,
                incoming_timestamp
                if isinstance(incoming_timestamp, (int, float))
                else None,
            )
        result.pop("service_info" if service_key == "serviceInfo" else "serviceInfo", None)
    return result


def is_mdns_record(record: dict[str, Any]) -> bool:
    """Return True when a record appears to be an mDNS capture row."""
    if not isinstance(record, dict):
        return False
    if isinstance(record.get("record_key"), str) and "|" in record["record_key"]:
        return True
    scope = record.get("scope")
    if isinstance(scope, str) and scope.startswith("_") and scope.endswith(".local."):
        return True
    return False


def is_matter_operational_mdns_record(record: dict[str, Any]) -> bool:
    """Return True for Matter operational mDNS records."""
    if not is_mdns_record(record):
        return False
    scope = record.get("scope")
    return isinstance(scope, str) and scope.strip().lower() == "_matter._tcp.local."


def _normalize_alias_text(value: Any, lower: bool = False) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    return text.lower() if lower else text


def _append_unique_alias(container: dict[str, Any], key: str, value: str) -> None:
    if not value:
        return
    existing = container.get(key)
    if not isinstance(existing, list):
        existing = []
    if value not in existing:
        existing.append(value)
    container[key] = existing


def _extract_service_info_property_decoded(record: dict[str, Any], key: str) -> str:
    service_info = record.get("serviceInfo", record.get("service_info"))
    if not isinstance(service_info, dict):
        return ""
    props = service_info.get("properties")
    if not isinstance(props, dict):
        return ""
    prop_obj = props.get(key)
    if not isinstance(prop_obj, dict):
        return ""
    decoded = prop_obj.get("decoded")
    if isinstance(decoded, str):
        return decoded.strip()
    return ""


def get_matter_fabric_node_identity(record: dict[str, Any]) -> str:
    """Return normalized Matter composite identity from FabricID_compressed + NodeID."""
    if not isinstance(record, dict):
        return ""

    matter = record.get("matter")
    matter_record = matter if isinstance(matter, dict) else record
    fabric_value = matter_record.get(
        "compressedFabricId", matter_record.get("fabricId")
    )
    node_value = matter_record.get("nodeId")

    def normalize_component(value: Any) -> str:
        if isinstance(value, bool):
            return ""
        if isinstance(value, int):
            return f"{value:016x}" if 0 <= value < 1 << 64 else ""
        if not isinstance(value, str):
            return ""
        text = value.strip().lower()
        if not text:
            return ""
        if re.fullmatch(r"(?:0x)?[0-9a-f]{1,16}", text):
            return f"{int(text, 16):016x}"
        return text

    fabric_id = normalize_component(fabric_value)
    node_id = normalize_component(node_value)
    if fabric_id and node_id:
        return f"{fabric_id}|{node_id}"

    fabric_id = _normalize_alias_text(
        _extract_service_info_property_decoded(record, "FabricID_compressed"),
        lower=True,
    )
    node_id = _normalize_alias_text(
        _extract_service_info_property_decoded(record, "NodeID"),
        lower=True,
    )

    if not fabric_id or not node_id:
        return ""
    return f"{fabric_id}|{node_id}"


def update_mdns_aliases(target: dict[str, Any], record: dict[str, Any]) -> None:
    """Collect stable alias values observed across mDNS records for one merged node."""
    if not isinstance(target, dict) or not isinstance(record, dict):
        return

    aliases = target.setdefault("_mdns_aliases", {})
    if not isinstance(aliases, dict):
        aliases = {}
        target["_mdns_aliases"] = aliases

    name_value = _normalize_alias_text(record.get("name"), lower=False)
    server_value = _normalize_alias_text(record.get("server"), lower=False)
    server_key_value = _normalize_alias_text(record.get("server_key"), lower=True)

    if not server_value:
        service_info = record.get("serviceInfo", record.get("service_info"))
        if isinstance(service_info, dict):
            server_value = _normalize_alias_text(service_info.get("server"), lower=False)
            if not server_key_value:
                server_key_value = _normalize_alias_text(service_info.get("key"), lower=True)

    fabric_id = _normalize_alias_text(
        _extract_service_info_property_decoded(record, "FabricID_compressed"),
        lower=False,
    )
    node_id = _normalize_alias_text(
        _extract_service_info_property_decoded(record, "NodeID"),
        lower=False,
    )

    _append_unique_alias(aliases, "name_aliases", name_value)
    _append_unique_alias(aliases, "server_aliases", server_value)
    _append_unique_alias(aliases, "server_key_aliases", server_key_value)
    _append_unique_alias(aliases, "fabric_id_compressed_aliases", fabric_id)
    _append_unique_alias(aliases, "node_id_aliases", node_id)

    matter_composite = get_matter_fabric_node_identity(record)
    if matter_composite:
        _append_unique_alias(aliases, "matter_fabric_node_aliases", matter_composite)


def extract_mdns_merge_view(record: dict[str, Any]) -> dict[str, Any]:
    """Extract an mDNS-focused view suitable for merge_mdns_records."""
    if not isinstance(record, dict):
        return {}

    mdns_fields = (
        "recordKey",
        "event",
        "capturedAtEpoch",
        "capturedAtIso",
        "scope",
        "name",
        "extAddress",
        "omrIpv6Addr",
        "isBorderRouter",
        "role",
        "serviceInfo",
        "server",
        "serverKey",
    )

    out: dict[str, Any] = {}
    for key in mdns_fields:
        if key in record:
            out[key] = deepcopy(record[key])

    service_info = out.get("service_info")
    if isinstance(service_info, dict):
        if "server" not in out and isinstance(service_info.get("server"), str):
            out["server"] = service_info.get("server")
        if "server_key" not in out and isinstance(service_info.get("key"), str):
            out["server_key"] = service_info.get("key")

    return out


def apply_mdns_merge_view(target: dict[str, Any], merged: dict[str, Any]) -> None:
    """Write merged mDNS fields back onto the merged node without touching non-mDNS fields."""
    if not isinstance(target, dict) or not isinstance(merged, dict):
        return

    for key in (
        "recordKey",
        "event",
        "capturedAtEpoch",
        "capturedAtIso",
        "scope",
        "name",
        "extAddress",
        "omrIpv6Addr",
        "isBorderRouter",
        "role",
        "serviceInfo",
        "server",
        "serverKey",
    ):
        if key in merged:
            target[key] = deepcopy(merged[key])


def merge_mdns_record_into_node(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    """Merge incoming mDNS row into a merged target node using mDNS-specific precedence."""
    if not is_mdns_record(incoming):
        return

    update_mdns_aliases(target, target)
    update_mdns_aliases(target, incoming)

    base_view = extract_mdns_merge_view(target)
    incoming_view = extract_mdns_merge_view(incoming)
    if not incoming_view:
        return

    merged_view = (
        merge_mdns_records(base_view, incoming_view)
        if base_view
        else deepcopy(incoming_view)
    )
    apply_mdns_merge_view(target, merged_view)


def _merge_route_field(
    current: Any, incoming: Any, context: MergeContext
) -> Any:
    if not isinstance(incoming, dict):
        return deepcopy(current)
    if (
        context.partition_id != "unknown"
        and context.incoming_partition_id != "unknown"
        and context.partition_id != context.incoming_partition_id
    ):
        return deepcopy(current)
    if not isinstance(current, dict):
        return deepcopy(incoming)
    return merge_route_data(
        context.owner_rloc16,
        current,
        incoming,
        context.partition_id,
    )


def _merge_relationship_field(
    current: Any, incoming: Any, context: MergeContext
) -> Any:
    if not isinstance(incoming, list):
        return deepcopy(current)
    return merge_children_array(
        context.owner_rloc16,
        current if isinstance(current, list) else [],
        incoming,
    )


def _merge_neighbor_field(
    current: Any, incoming: Any, _context: MergeContext
) -> Any:
    if not isinstance(incoming, list):
        return deepcopy(current)
    return merge_router_neighbors(
        current if isinstance(current, list) else [],
        incoming,
    )


def _merge_address_field(
    current: Any, incoming: Any, _context: MergeContext
) -> Any:
    if not isinstance(incoming, list):
        return deepcopy(current)
    return merge_unique_strings(current if isinstance(current, list) else [], incoming)


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
                context.conflict_limit,
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
    if omr:
        identities["omrIpv6Address"] = omr

    rloc16 = normalize_identifier_text(
        record.get(MERGE_IDENTITY_FIELDS["rloc16"]))
    if rloc16:
        identities["rloc16"] = rloc16

    matter_id = get_matter_fabric_node_identity(record)
    if matter_id:
        identities["matter_fabric_node"] = matter_id

    return identities


def find_candidate_node_ids(
    identity_values: dict[str, str],
    by_rloc16: dict[str, int],
    by_extaddr: dict[str, int],
    by_omr: dict[str, int],
    by_matter_fabric_node: dict[str, int],
) -> set[int]:
    candidate_ids: set[int] = set()

    rloc16 = identity_values.get("rloc16")
    extaddr = identity_values.get("extAddress")
    omr = identity_values.get("omrIpv6Address")
    matter_id = identity_values.get("matter_fabric_node")

    if isinstance(extaddr, str) and extaddr in by_extaddr:
        candidate_ids.add(by_extaddr[extaddr])
    if isinstance(omr, str) and omr in by_omr:
        candidate_ids.add(by_omr[omr])
    if isinstance(rloc16, str) and rloc16 in by_rloc16:
        candidate_ids.add(by_rloc16[rloc16])
    if isinstance(matter_id, str) and matter_id in by_matter_fabric_node:
        candidate_ids.add(by_matter_fabric_node[matter_id])

    return candidate_ids


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


def add_identifier(
    index: dict[str, int],
    key: str,
    node_id: int,
) -> None:
    if key:
        index[key] = node_id


def filter_candidate_ids_for_extaddr_consistency(
    candidate_ids: set[int],
    incoming_extaddr: str,
    nodes: dict[int, dict[str, Any]],
) -> set[int]:
    """Keep only candidate nodes that do not conflict with incoming concrete extaddr."""
    if not incoming_extaddr:
        return candidate_ids

    filtered: set[int] = set()
    for node_id in candidate_ids:
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            continue

        node_extaddr = get_canonical_extaddr(node)
        if not node_extaddr:
            filtered.add(node_id)
            continue

        if is_placeholder_extaddr(node_extaddr):
            filtered.add(node_id)
            continue

        if node_extaddr == incoming_extaddr:
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
    for filename in ordered_input_files:
        data = input_data[filename] if input_data is not None else load_json(base_dir / filename)
        records = extract_records(filename, data)
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


@dataclass(frozen=True)
class MergeCommandInputs:
    data_dir: Path
    input_files: tuple[str, ...]
    required_files: frozenset[str]
    loaded_input_files: tuple[str, ...]
    skipped_files: tuple[dict[str, str], ...]
    dataset_path: Path
    extaddr_map_path: Path
    output_path: Path
    report_path: Path | None
    dataset_file: str
    extaddr_map_file: str
    merge_strategy: str
    matter_identity_mode: str


@dataclass(frozen=True)
class MergeSupportingData:
    device_label_map: dict[str, Any]
    network_info: dict[str, Any]
    omr_prefix: str
    reference_files: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class MergeCommandResult:
    records: list[dict[str, Any]]
    report: dict[str, Any]
    viable: bool
    viability_reason: str | None


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


def evaluate_merge_viability(
    records: Sequence[dict[str, Any]],
) -> tuple[bool, int, str | None]:
    identity_seed_record_count = 0
    for node in records:
        extaddr = get_canonical_extaddr(node)
        rloc16 = normalize_identifier_text(node.get("rloc16"))
        omr_addr = get_canonical_omr(node)
        if (extaddr and not is_placeholder_extaddr(extaddr)) or rloc16 or omr_addr:
            identity_seed_record_count += 1

    viable = identity_seed_record_count > 0
    reason = None if viable else "no viable seed identities found in loaded input files"
    return viable, identity_seed_record_count, reason


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
        for filename in command_inputs.loaded_input_files:
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


def write_merge_outputs(
    result: MergeCommandResult,
    output_path: Path,
    report_path: Path | None = None,
) -> None:
    save_json_atomic(
        result.records,
        output_path,
        indent=2,
        add_trailing_newline=True,
    )
    if report_path is not None:
        save_json_atomic(
            result.report,
            report_path,
            indent=2,
            add_trailing_newline=True,
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

        if not result.viable:
            logging.error("merge-dataset: %s", result.viability_reason)
            return 3
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
