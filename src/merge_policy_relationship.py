from __future__ import annotations

import logging
from collections import defaultdict
from copy import deepcopy
from typing import Any

from td_device_fields import normalize_identifier_text
from td_device_merge import MergeContext
from td_record_merge import merge_unique_strings, value_is_empty


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
            if route_id is not None:
                identity = (owner_rloc16, str(route_id))
                merged_routes[identity] = deepcopy(route)
    
    for route in incoming_routes:
        if isinstance(route, dict):
            route_id = route.get("routeId")
            if route_id is not None:
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


def _merge_relationship_records(
    base_records: list[Any],
    incoming_records: list[Any],
    *,
    parent_rloc16: str | None = None,
    prefer_incoming_values: bool = False,
) -> list[dict[str, Any]]:
    merged: dict[int | str, dict[str, Any]] = {}
    by_extaddr: dict[tuple[str | None, str], int] = {}
    by_rloc16: dict[tuple[str | None, str], set[int]] = defaultdict(set)
    next_id = 0

    for record in base_records + incoming_records:
        if not isinstance(record, dict):
            continue

        extaddr = normalize_identifier_text(record.get("extAddress"))
        rloc16 = normalize_identifier_text(record.get("rloc16"))
        if not extaddr and not rloc16:
            merged[next_id] = deepcopy(record)
            next_id += 1
            continue

        extaddr_key = (parent_rloc16, extaddr)
        rloc16_key = (parent_rloc16, rloc16)
        existing_id = by_extaddr.get(extaddr_key) if extaddr else None
        rloc_candidates = by_rloc16[rloc16_key] if rloc16 else set()
        if existing_id is None and len(rloc_candidates) == 1:
            candidate_id = next(iter(rloc_candidates))
            candidate_extaddr = normalize_identifier_text(
                merged[candidate_id].get("extAddress"))
            if not extaddr or not candidate_extaddr or candidate_extaddr == extaddr:
                existing_id = candidate_id

        if existing_id is None:
            existing_id = next_id
            next_id += 1
            merged[existing_id] = deepcopy(record)
        else:
            existing = merged[existing_id]
            for key, value in record.items():
                if key not in existing or value_is_empty(existing.get(key)):
                    existing[key] = value
                elif (
                    prefer_incoming_values
                    and not value_is_empty(value)
                    and existing.get(key) != value
                ):
                    existing[key] = value

        if extaddr:
            by_extaddr[extaddr_key] = existing_id
        if rloc16:
            by_rloc16[rloc16_key].add(existing_id)

    return list(merged.values())


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
    return _merge_relationship_records(
        base_children,
        incoming_children,
        parent_rloc16=normalize_identifier_text(parent_rloc16),
        prefer_incoming_values=True,
    )


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
    return _merge_relationship_records(base_neighbors, incoming_neighbors)


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
