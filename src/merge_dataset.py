#!/usr/bin/env python3
"""Merge multiple Thread topology JSON files into one detailed cache file."""

from __future__ import annotations

import argparse
import json
import logging

from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any, Sequence

from extaddr_device_label_map import (
    EXTADDR_FIELD_ALIASES,
    load_extaddr_device_label_map_flexible,
)
from json_key_normalizer import convert_keys_to_camel_case
from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME, TD_DATA_DIR_ARG_HELP
from util_data import (
    load_optional_input,
    require_existing_input_file,
    resolve_data_dir,
    save_json_atomic,
)
from util_data import TDRequiredInputMissingError


PRIORITY_FIELDS = [
    # === TIER 1: Primary Identity (Essential P0) ===
    # Ordered by stability: extaddr (immutable) > OMR IPv6 (stable) > rloc16 (changes rapidly)
    "extaddr",
    "extAddress",              # REST API alias
    "device_label",
    "name",
    "omr_ipv6_addr",           # More stable than rloc16
    "omrIpv6Address",          # REST API alias
    "omrIpv6Addr",             # Phase 1 canonical camelCase
    "rloc16",                  # May change rapidly, partition-scoped
    "routerId",                # REST API
    "router_id",               # CLI snake_case
    "eui64",                   # Alternative to extaddr
    "id",                      # REST API UUID
    "ID",                      # Alias
    
    # === TIER 2: Secondary Identity (Important P1) ===
    "mlEidIid",                # ML-EID Interface ID
    "room",
    "Extended MAC",            # Eve format
    "Next Hop",                # Eve format
    "Path Cost",               # Eve format
    "LQ In",                   # Eve format
    "LQ Out",                  # Eve format
    "Age",                     # Eve format / Child age
    
    # === TIER 3: Device Role & Status (Important P1) ===
    "type",
    "role",
    "Role",                    # Eve format
    "is_router",               # CLI - is router
    "isRouter",                # REST API alias
    "is_border_router",         # CLI - is border router
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
    "thread_version",
    "thread_stack_version",
    "threadStackVersion",      # REST API alias
    
    # === TIER 4: Topology & Connectivity (Important P1) ===
    "total_children",
    "has_children",
    "total_links",
    "total_link_3",
    "total_link_2",
    "total_link_1",
    "router_neighbor_table_count",
    "router_child_table_count",
    
    # Partition and Leader Data (Essential P0 for routing)
    "leader_data.partition_id",
    "leaderData.partitionId",  # REST API alias
    "leader_data.leader_router_id",
    "leaderData.leaderRouterId",  # REST API alias
    "leader_data.data_version",
    "leaderData.dataVersion",  # REST API alias
    "leader_data.stable_data_version",
    "leaderData.stableDataVersion",  # REST API alias
    "leader_data.weighting",
    "leaderData.weighting",    # REST API alias
    
    # Connectivity Fields (Important P1)
    "connectivity.id_sequence",
    "connectivity.idSequence",  # REST API alias
    "connectivity.activeRouters",
    "connectivity.active_routers",
    "connectivity.linkQuality3",
    "connectivity.link_quality_3",
    "connectivity.linkQuality2",
    "connectivity.link_quality_2",
    "connectivity.linkQuality1",
    "connectivity.link_quality_1",
    "connectivity.leaderCost",
    "connectivity.leader_cost",
    "connectivity.parentPriority",
    "connectivity.parent_priority",
    "connectivity.sedBufferSize",
    "connectivity.sed_buffer_size",
    "connectivity.sedDatagramCount",
    "connectivity.sed_datagram_count",
    
    # Route Data Fields (Essential P0 for routing)
    "route_data.id_sequence",
    "route.idSequence",        # REST API alias (note: different parent name)
    "route_data",              # CLI parent object
    "route",                   # REST API parent object
    
    # === TIER 5: Advanced/Diagnostic (Optional P2) ===
    "icon",
    "scope",                   # mDNS scope
    
    # Vendor Information
    "vendor_name",
    "vendorName",
    "vendor_model",
    "vendorModel",
    "vendor_sw_version",
    "vendorSwVersion",
    "tlv_values",              # CLI TLV values
    
    # MAC Counters (CLI only)
    "mac_counters.ifinerrors_pct",
    "mac_counters.ifouterrors_pct",
    "mac_counters.ifindiscards_pct",
    "mac_counters.ifoutdiscards_pct",
    "mac_counters.iftotalerrors_totalpkts_ratio",
    "mac_counters.iftotaldiscards_totalpkts_ratio",
    
    # MLE Counters (CLI only)
    "mle_counters.partitionidchanges",
    "mle_counters.betterpartitionattachattempts",
    "mle_counters.totalparentpartitionchanges",
    "mle_counters.parentchanges",
    
    # Time Statistics (CLI only)
    "time_statistics.router_pct",
    "time_statistics.detached_disabled_pct",
    "time_statistics",         # Parent object
    
    # mDNS Fields
    "record_key",              # mDNS unique key
    "event",                   # mDNS event type
    "captured_at_epoch",       # mDNS timestamp
    "captured_at_iso",         # mDNS ISO timestamp
    
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
    "extaddr_aliases": ("extAddress", "Extended MAC"),
    "omr_ipv6_addr_aliases": ("omrIpv6Address", "omrIpv6Addr"),
    "rloc16": "rloc16",
}

# Phase 3: Source Precedence Rules (Priority: Higher = Wins)
# Used to resolve conflicts when multiple sources provide same field
SOURCE_PRECEDENCE = {
    "td-static-extaddr-device-label.json": 101, # Highest priority

    "td-otbr-cli-networkdiag-fetch-all.json": 100, # Highest priority (most detailed)
    "td-otbr-cli-networkdiag-multicast-network.json": 99,
    "td-otbr-cli-meshdiag-topology.json": 98,
    "td-otbr-cli-meshdiag-router-neighbortables.json": 97,
    "td-otbr-cli-meshdiag-router-childtables.json": 96,
    "td-otbr-cli-router-table.json": 95,

    "td-otbr-restapi-diagnostics-fetch-all.json": 90, 
    "td-otbr-restapi-mesh-diagnostics-fetch-all.json": 89,
    "td-otbr-restapi-diagnostics-list.json": 88,
    "td-otbr-restapi-diagnostics.json": 87,      
    "td-otbr-restapi-devices-fetch.json": 86,
    "td-otbr-restapi-devices-list.json": 85,
    "td-otbr-restapi-devices.json": 84,

    "td-eve-topology.json": 60,

    "td-mdns-scopes-thread.json": 50,
    "td-mdns-scopes-br.json": 49,                # mDNS scopes (service discovery)
    "td-mdns-scopes-hap.json": 48,
    "td-mdns-scopes-matter.json": 47,
}

DEFAULT_INPUT_FILES = [
    ##"td-static-extaddr-device-label.json",
    "td-otbr-cli-router-table.json",
    "td-otbr-cli-meshdiag-topology.json",
    "td-otbr-cli-networkdiag-fetch-all.json",
    "td-otbr-cli-networkdiag-multicast-network.json",
    "td-otbr-cli-meshdiag-router-neighbortables.json",
    "td-otbr-cli-meshdiag-router-childtables.json",
    "td-otbr-restapi-diagnostics-fetch-all.json",
    "td-otbr-restapi-mesh-diagnostics-fetch-all.json",
    "td-otbr-restapi-diagnostics-list.json",
    "td-otbr-restapi-diagnostics.json",
    "td-otbr-restapi-devices-fetch.json",
    "td-otbr-restapi-devices-list.json",
    "td-otbr-restapi-devices.json",   
    "td-mdns-scopes-thread.json",                # Phase 3: mDNS Thread devices
    "td-mdns-scopes-br.json",                    # Phase 3: mDNS Border Router discovery
    "td-mdns-scopes-hap.json",                   # Phase 3: mDNS HomeKit devices
    "td-mdns-scopes-matter.json",                # Phase 3: mDNS Matter devices
    "td-eve-topology.json",
]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_identifier_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def first_normalized_identifier(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = normalize_identifier_text(record.get(key))
        if value:
            return value
    return ""


def get_canonical_extaddr(record: dict[str, Any]) -> str:
    return first_normalized_identifier(record, MERGE_IDENTITY_FIELDS["extaddr_aliases"])


def get_canonical_omr(record: dict[str, Any]) -> str:
    return first_normalized_identifier(record, MERGE_IDENTITY_FIELDS["omr_ipv6_addr_aliases"])


def is_placeholder_extaddr(value: Any) -> bool:
    """Return True for known non-identity extaddr placeholder values."""
    if not isinstance(value, str):
        return False
    normalized = normalize_identifier_text(value)
    return normalized in {"", "0000000000000000"}


def normalize_record_aliases(record: dict[str, Any]) -> dict[str, Any]:
    extaddr = get_canonical_extaddr(record)
    omr_addr = get_canonical_omr(record)

    if extaddr:
        record["extAddress"] = extaddr
    if omr_addr:
        record["omrIpv6Addr"] = omr_addr

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
    normalize_record_aliases(record)

    rloc16 = record.get("rloc16")
    if isinstance(rloc16, str):
        record["rloc16"] = rloc16.lower()

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
        record["omrIpv6Addr"] = omr_addr

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
    if value is None:
        return True
    if value == "":
        return True
    if value == [] or value == {}:
        return True
    return False


def merge_unique_strings(existing: list[Any], incoming: list[Any]) -> list[str]:
    merged: list[str] = []
    for value in existing + incoming:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def values_equivalent(left: Any, right: Any) -> bool:
    if left == right:
        return True
    try:
        return json.dumps(left, sort_keys=True, ensure_ascii=True) == json.dumps(
            right, sort_keys=True, ensure_ascii=True
        )
    except TypeError:
        return False


def append_merge_conflict(
    base: dict[str, Any], path: str, cur_val: Any, new_value: Any
) -> None:
    if not path:
        return

    conflicts = base.setdefault("_merge_conflicts", [])
    if not isinstance(conflicts, list):
        conflicts = []
        base["_merge_conflicts"] = conflicts

    if len(conflicts) >= 20:
        return

    current_text = json.dumps(
        cur_val, sort_keys=True, ensure_ascii=True, default=str
    )
    incoming_text = json.dumps(
        new_value, sort_keys=True, ensure_ascii=True, default=str
    )

    for entry in conflicts:
        if not isinstance(entry, dict):
            continue
        if (
            entry.get("path") == path
            and entry.get("current") == current_text
            and entry.get("incoming") == incoming_text
        ):
            return

    conflicts.append(
        {
            "path": path,
            "current": current_text,
            "incoming": incoming_text,
        }
    )


def merge_lists(left: list[Any], right: list[Any]) -> list[Any]:
    seen: set[str] = set()
    merged: list[Any] = []

    for item in left + right:
        key = json.dumps(item, sort_keys=True, ensure_ascii=True)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)

    return merged


# ============================================================================
# Phase 2: Field Normalization Functions
# ============================================================================

# Field alias mapping for normalization (camelCase ↔ snake_case)
FIELD_ALIASES_BIDIRECTIONAL = {
    # Identity fields
    "extaddr": ["extAddress", "Extended MAC"],
    "omr_ipv6_addr": ["omrIpv6Address", "omrIpv6Addr"],
    "router_id": ["routerId"],
    "device_label": ["name", "hostName"],
    "eui64": ["EUI64"],
    
    # Parent object names (CRITICAL: different names for same data!)
    "route_data": ["route"],
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
        if not child_extaddr:
            # No extaddr - can't create composite identity
            # Add as-is (might be duplicate, but can't determine)
            temp_key = json.dumps(child, sort_keys=True)
            merged[temp_key] = child
            continue
        
        # Normalize extaddr
        child_extaddr = normalize_identifier_text(child_extaddr)
        
        # Composite identity
        identity = (parent_rloc16, child_extaddr)
        
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
            identity = ("extaddr", normalize_identifier_text(extaddr))
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
    base_timestamp = base.get("captured_at_epoch")
    incoming_timestamp = incoming.get("captured_at_epoch")
    
    # Compare timestamps
    if base_timestamp is not None and incoming_timestamp is not None:
        if incoming_timestamp > base_timestamp:
            # Incoming is newer, use it as base
            result = deepcopy(incoming)
            # Merge service_info specially
            if "service_info" in base and "service_info" in incoming:
                result["service_info"] = merge_mdns_service_info(
                    base["service_info"],
                    incoming["service_info"],
                    base_timestamp,
                    incoming_timestamp,
                )
            return result
        elif incoming_timestamp < base_timestamp:
            # Base is newer, keep it
            result = deepcopy(base)
            # Still merge any missing fields from incoming
            for key, value in incoming.items():
                if key not in result or value_is_empty(result.get(key)):
                    result[key] = deepcopy(value)
            return result
        else:
            # Timestamps equal, use event priority
            base_event = base.get("event", "")
            incoming_event = incoming.get("event", "")
            base_priority = get_mdns_event_priority(base_event)
            incoming_priority = get_mdns_event_priority(incoming_event)
            
            if incoming_priority > base_priority:
                result = deepcopy(incoming)
                # Merge any missing fields from base (but incoming wins)
                for key, value in base.items():
                    if key == "service_info":
                        continue  # Handle separately
                    if key not in result or value_is_empty(result.get(key)):
                        result[key] = deepcopy(value)
                # Merge service_info - incoming as base since it has higher priority
                if "service_info" in incoming:
                    result["service_info"] = deepcopy(incoming["service_info"])
                    if "service_info" in base:
                        # Merge missing fields from base
                        for key, value in base["service_info"].items():
                            if key not in result["service_info"] or value_is_empty(result["service_info"].get(key)):
                                result["service_info"][key] = deepcopy(value)
            else:
                result = deepcopy(base)
                # Merge any missing fields from incoming
                for key, value in incoming.items():
                    if key == "service_info":
                        continue  # Handle separately
                    if key not in result or value_is_empty(result.get(key)):
                        result[key] = deepcopy(value)
                # Merge service_info - base as primary since it has higher/equal priority
                if "service_info" in incoming:
                    for key, value in incoming["service_info"].items():
                        if key not in result.get("service_info", {}) or value_is_empty(result.get("service_info", {}).get(key)):
                            result.setdefault("service_info", {})[key] = deepcopy(value)
            
            return result
    
    # No timestamp comparison, merge deeply
    result = deepcopy(base)
    for key, value in incoming.items():
        if key == "service_info" and "service_info" in base:
            result["service_info"] = merge_mdns_service_info(
                base["service_info"],
                value,
                base_timestamp,
                incoming_timestamp,
            )
        elif key not in result or value_is_empty(result.get(key)):
            result[key] = deepcopy(value)
    
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
    service_info = record.get("service_info")
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
        service_info = record.get("service_info")
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
        "record_key",
        "event",
        "captured_at_epoch",
        "captured_at_iso",
        "scope",
        "name",
        "extaddr",
        "omr_ipv6_addr",
        "is_border_router",
        "role",
        "service_info",
        "server",
        "server_key",
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
        "record_key",
        "event",
        "captured_at_epoch",
        "captured_at_iso",
        "scope",
        "name",
        "extaddr",
        "omr_ipv6_addr",
        "is_border_router",
        "role",
        "service_info",
        "server",
        "server_key",
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


def deep_merge(
    base: dict[str, Any],
    incoming: dict[str, Any],
    path_prefix: str = "",
    conflict_target: dict[str, Any] | None = None,
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
    owner_rloc16 = normalize_identifier_text(conflict_target.get("rloc16"))

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
        
        # Phase 3: canonical route merge on camelCase key only.
        if key == "route" and isinstance(value, dict):
            if "route" in base and isinstance(base["route"], dict):
                base["route"] = merge_route_data(
                    owner_rloc16,
                    base["route"],
                    value,
                    partition_id,
                )
            else:
                base["route"] = deepcopy(value)
            continue
        
        # Phase 2: Special handling for children array (composite identity merge)
        if key == "children" and isinstance(value, list):
            base_children = base.get("children", [])
            if isinstance(base_children, list):
                base["children"] = merge_children_array(
                    owner_rloc16,
                    base_children,
                    value,
                )
            else:
                base["children"] = deepcopy(value)
            continue
        
        # Phase 2: Special handling for childTable array (composite identity merge)
        if key == "childTable" and isinstance(value, list):
            base_children = base.get("childTable", [])
            if isinstance(base_children, list):
                base["childTable"] = merge_children_array(
                    owner_rloc16,
                    base_children,
                    value,
                )
            else:
                base["childTable"] = deepcopy(value)
            continue
        
        # Phase 2: Special handling for routerNeighbors array (identity merge)
        if key == "routerNeighbors" and isinstance(value, list):
            base_neighbors = base.get("routerNeighbors", [])
            if isinstance(base_neighbors, list):
                base["routerNeighbors"] = merge_router_neighbors(
                    base_neighbors,
                    value,
                )
            else:
                base["routerNeighbors"] = deepcopy(value)
            continue
        
        if key not in base:
            base[key] = deepcopy(value)
            continue

        cur = base[key]
        if isinstance(cur, dict) and isinstance(value, dict):
            deep_merge(cur, value, current_path, conflict_target)
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
            append_merge_conflict(conflict_target, current_path, cur, value)
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
        identities["extaddr"] = extaddr

    omr = get_canonical_omr(record)
    if omr:
        identities["omr_ipv6_addr"] = omr

    rloc16 = normalize_identifier_text(
        record.get(MERGE_IDENTITY_FIELDS["rloc16"]))
    if rloc16:
        identities["rloc16"] = rloc16

    if is_matter_operational_mdns_record(record):
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
    extaddr = identity_values.get("extaddr")
    omr = identity_values.get("omr_ipv6_addr")
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
    extaddr = identity_values.get("extaddr")
    omr = identity_values.get("omr_ipv6_addr")
    matter_id = identity_values.get("matter_fabric_node")

    if isinstance(extaddr, str):
        node["extAddress"] = extaddr
        add_identifier(by_extaddr, extaddr, node_id)
    if isinstance(omr, str):
        node["omrIpv6Addr"] = omr
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
    if not is_matter_operational_mdns_record(incoming_record):
        return candidate_ids

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
    deep_merge(target, source)

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

    for filename in input_files:
        data = load_json(base_dir / filename)
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
            extaddr = identity_values.get("extaddr")
            omr = identity_values.get("omr_ipv6_addr")

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
                                "extaddr": extaddr,
                                "omrIpv6Addr": omr,
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
                deep_merge(nodes[node_id], record)
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
            active_extaddr = active_identity_values.get("extaddr")
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
        if iv.get("extaddr"):
            identity_key_parts.append(f"extAddress:{iv['extaddr']}")
        if iv.get("rloc16"):
            identity_key_parts.append(f"rloc16:{iv['rloc16']}")
        if iv.get("omr_ipv6_addr"):
            identity_key_parts.append(f"omrIpv6Addr:{iv['omr_ipv6_addr']}")
        if identity_key_parts:
            node["_merge_identity_keys"] = identity_key_parts

        ordered: dict[str, Any] = {}

        for key in PRIORITY_FIELDS:
            if "." in key:
                value = nested_get(node, key)
                if value is not None:
                    ordered[key] = value
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
        "input_files": input_files,
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


def resolve_input_files(
    default_files: list[str],
    include_files: list[str],
    exclude_files: list[str],
) -> list[str]:
    resolved: list[str] = list(default_files)

    for filename in include_files:
        if filename not in resolved:
            resolved.append(filename)

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
        default="td-otbr-cli-thread-network-info.json",
        help="File that contains prefix_omr_ipv6addr_prefix.",
    )
    parser.add_argument(
        "--output",
        default="td-merged-topology-all.json",
        help="Output merged JSON file path.",
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


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    args = parse_args(argv)
    td_data_dir = resolve_data_dir(data_dir=args.datadir)
    base_dir = td_data_dir if args.base_dir == "." else Path(args.base_dir)
    include_files = parse_file_list_args(args.include_files)
    exclude_files = parse_file_list_args(args.exclude_files)

    try:
        input_files = resolve_input_files(
            DEFAULT_INPUT_FILES, include_files, exclude_files)

        extaddr_map_path = base_dir / args.extaddr_map_file
        extaddr_map_result = load_optional_input(
            extaddr_map_path,
            loader=lambda path: load_extaddr_device_label_map_flexible(
                str(path),
                extaddr_aliases=EXTADDR_FIELD_ALIASES,
            ),
            default_value={},
            command_path="merge-dataset",
            data_dir=base_dir,
            logger=logging.getLogger(__name__),
            classification="optional",
            fallback_action="continue fallback=empty-map",
        )
        device_label_map = extaddr_map_result.value

        dataset_path = base_dir / args.dataset_file
        dataset_result = load_optional_input(
            dataset_path,
            loader=lambda path: load_json(path),
            default_value={},
            command_path="merge-dataset",
            data_dir=base_dir,
            logger=logging.getLogger(__name__),
            classification="optional",
            fallback_action="continue fallback=empty-dataset",
        )
        dataset = dataset_result.value
        omr_prefix = ""
        if isinstance(dataset, dict):
            omr_prefix_value = dataset.get("prefixOmrIpv6AddrPrefix", "")
            if isinstance(omr_prefix_value, str):
                omr_prefix = omr_prefix_value

        available_input_files: list[str] = []
        skipped_input_files: list[dict[str, str]] = []

        include_file_set = set(include_files)
        for filename in input_files:
            source_path = base_dir / filename
            if source_path.exists():
                available_input_files.append(filename)
                continue

            # Explicitly included files are treated as required.
            if filename in include_file_set:
                raise TDRequiredInputMissingError(
                    command_path="merge-dataset",
                    data_dir=base_dir,
                    missing_file=source_path,
                    classification="required",
                    action="fail code=4",
                )

            warning = (
                f"merge-dataset: skipping missing optional input file {source_path}"
            )
            logging.warning(warning)
            skipped_input_files.append(
                {
                    "file": filename,
                    "reason": "missing",
                }
            )

        if not available_input_files:
            raise TDRequiredInputMissingError(
                command_path="merge-dataset",
                data_dir=base_dir,
                missing_file=base_dir / "<all-input-files>",
                classification="required-seed",
                action="fail code=4",
            )

        merged_records, report = build_merged_records(
            base_dir,
            omr_prefix,
            available_input_files,
            device_label_map,
            matter_identity_mode=args.matter_identity_mode,
        )
        report["input_files"] = input_files
        report["loaded_input_files"] = available_input_files
        report["skipped_input_files"] = skipped_input_files
        report["reference_extaddr_map_file"] = args.extaddr_map_file
        report["reference_extaddr_map_entries"] = len(device_label_map)
        report["optional_reference_files"] = [
            {
                "file": args.extaddr_map_file,
                "loaded": not extaddr_map_result.used_fallback,
                "fallback": extaddr_map_result.used_fallback,
            },
            {
                "file": args.dataset_file,
                "loaded": not dataset_result.used_fallback,
                "fallback": dataset_result.used_fallback,
            }
        ]

        identity_seed_record_count = 0
        for node in merged_records:
            if not isinstance(node, dict):
                continue
            extaddr = get_canonical_extaddr(node)
            rloc16 = normalize_identifier_text(node.get("rloc16"))
            omr_addr = get_canonical_omr(node)
            if (extaddr and not is_placeholder_extaddr(extaddr)) or rloc16 or omr_addr:
                identity_seed_record_count += 1

        required_seed_status = {
            "dataset_file": args.dataset_file,
            "loaded_input_file_count": len(available_input_files),
            "identity_seed_record_count": identity_seed_record_count,
            "viable": identity_seed_record_count > 0,
        }
        report["required_seed_status"] = required_seed_status

        if args.merge_strategy == "none":
            # Pass-through: collect all records without identity matching.
            passthrough_records: list[dict[str, Any]] = []
            for filename in available_input_files:
                data = load_json(base_dir / filename)
                records = extract_records(filename, data)
                for raw_record in records:
                    record = normalize_identifiers(raw_record, omr_prefix)
                    record.setdefault("_source_files", [filename])
                    passthrough_records.append(record)
            merged_records = passthrough_records
            report["merge_strategy"] = "none"
            report["passthrough_record_count"] = len(passthrough_records)
            logging.info(
                f"merge-strategy=none: collected {len(passthrough_records)} "
                "records without merging."
            )
        else:
            report["merge_strategy"] = "merge"

        output_path = base_dir / args.output
        merged_records_camel = convert_keys_to_camel_case(merged_records)
        save_json_atomic(
            merged_records_camel,
            output_path,
            indent=2,
            add_trailing_newline=True,
        )
        logging.debug("Saved merged records into %s as JSON:\n%s",
            output_path, json.dumps(merged_records_camel, indent=2))
        if args.report_file:
            report_path = base_dir / args.report_file
            save_json_atomic(report, report_path, indent=2, add_trailing_newline=True)
            logging.info(f"Wrote merge report to {report_path}")

        logging.info(
            f"Wrote {len(merged_records_camel)} merged records to {output_path}")
        logging.info(
            "Validation summary: "
            f"multi_source_nodes={report['multi_source_nodes_total']}, "
            f"single_source_nodes={report['single_source_nodes_total']}, "
            f"identity_collisions={report['identity_collision_count']}"
        )

        if not required_seed_status["viable"]:
            logging.error(
                "merge-dataset: no viable seed identities found in loaded input files"
            )
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
