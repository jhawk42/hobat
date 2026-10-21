from __future__ import annotations

import logging
import re
from collections import defaultdict
from copy import deepcopy
from typing import Any

from td_device_fields import normalize_identifier_text, is_placeholder_ext_address
from td_device_merge import MergeContext
from td_record_merge import (
    merge_unique_strings, value_is_empty, values_equivalent,
    append_merge_conflict, merge_lists,
)


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
    max_val = 2 ** bits
    half_max = max_val // 2
    
    diff = (seq_a - seq_b) % max_val
    return 0 < diff < half_max


def compare_sequences(seq_a: int | None, seq_b: int | None) -> str:
    """
    Compare two sequence numbers, handling None values.
    
    Returns: "a_newer", "b_newer", "equal", "unknown", or "ambiguous".
    """
    if seq_a is None and seq_b is None:
        return "unknown"
    if seq_a is None:
        return "b_newer"
    if seq_b is None:
        return "a_newer"
    
    if seq_a % 256 == seq_b % 256:
        return "equal"
    
    if is_sequence_newer(seq_a, seq_b):
        return "a_newer"
    if is_sequence_newer(seq_b, seq_a):
        return "b_newer"
    return "ambiguous"


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
    
    partition_id = record.get("partitionId", record.get("partition_id"))
    if isinstance(partition_id, int):
        return f"0x{partition_id:08x}"
    if isinstance(partition_id, str) and partition_id.strip():
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
    def eligible(route: Any) -> bool:
        entry_partition = get_partition_id(route) if isinstance(route, dict) else "unknown"
        return isinstance(route, dict) and (
            partition_id == "unknown" or entry_partition == "unknown"
            or partition_id == entry_partition
        )

    def filtered(container: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(container)
        if isinstance(result.get("routeData"), list):
            result["routeData"] = [route for route in result["routeData"] if eligible(route)]
        return result

    base = filtered(base_route_data)
    incoming = filtered(incoming_route_data)
    
    # Extract sequence numbers
    base_seq = base.get("idSequence")
    incoming_seq = incoming.get("idSequence")
    
    # Compare sequences
    seq_comparison = compare_sequences(base_seq, incoming_seq)
    
    # If incoming has higher sequence, replace entirely
    if seq_comparison == "b_newer":
        logging.debug(f"Route data: incoming sequence {incoming_seq} > base {base_seq}, using incoming")
        return incoming
    
    # If base has higher sequence, keep base
    if seq_comparison == "a_newer":
        logging.debug(f"Route data: base sequence {base_seq} > incoming {incoming_seq}, keeping base")
        return base
    
    # Sequences equal or both unknown - merge by route identity
    logging.debug(f"Route data: sequences equal ({base_seq}), merging by route identity")
    
    base_routes = base.get("routeData", [])
    incoming_routes = incoming.get("routeData", [])
    
    if not isinstance(base_routes, list):
        base_routes = []
    if not isinstance(incoming_routes, list):
        incoming_routes = []
    
    # Merge by composite identity: (owner_rloc16, dest_route_id)
    merged_routes: dict[str, dict[str, Any]] = {}

    def route_key(route: dict[str, Any]) -> str:
        route_id = route.get("routeId", route.get("id"))
        if type(route_id) is int and route_id >= 0:
            return f"id:{route_id}"
        if isinstance(route_id, str):
            text = route_id.strip().lower()
            if re.fullmatch(r"(?:0x[0-9a-f]+|\d+)", text):
                return f"id:{int(text, 16 if text.startswith('0x') else 10)}"
        source = normalize_identifier_text(route.get("sourceId"))
        target = normalize_identifier_text(route.get("targetId"))
        if source and target:
            return f"endpoints:{source}|{target}"
        extaddr = normalize_identifier_text(route.get("extAddress"))
        if extaddr and not is_placeholder_ext_address(extaddr):
            return f"extAddress:{extaddr}"
        rloc16 = normalize_identifier_text(route.get("rloc16"))
        return f"rloc16:{rloc16}" if rloc16 else ""

    for route in base_routes:
        if isinstance(route, dict):
            identity = route_key(route)
            if identity:
                merged_routes[identity] = deepcopy(route)
    for route in incoming_routes:
        if isinstance(route, dict):
            identity = route_key(route)
            if identity in merged_routes:
                _fill_relationship(merged_routes[identity], route, "", None)
            elif identity and seq_comparison != "ambiguous":
                merged_routes[identity] = deepcopy(route)
    
    # Reconstruct canonical route object
    result = deepcopy(base)
    _fill_relationship(result, {key: value for key, value in incoming.items()
                              if key not in {"routeData", "idSequence"}}, "", None)
    
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
    context: MergeContext | None = None,
) -> list[dict[str, Any]]:
    merged: dict[int | str, dict[str, Any]] = {}
    by_extaddr: dict[tuple[str | None, str], int] = {}
    by_rloc16: dict[tuple[str | None, str], set[int]] = defaultdict(set)
    next_id = 0

    for record in base_records + incoming_records:
        if not isinstance(record, dict):
            continue

        extaddr = normalize_identifier_text(record.get("extAddress"))
        if is_placeholder_ext_address(extaddr):
            extaddr = ""
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
            if is_placeholder_ext_address(candidate_extaddr):
                candidate_extaddr = ""
            if not extaddr or not candidate_extaddr or candidate_extaddr == extaddr:
                existing_id = candidate_id
            elif context and context.conflict_target is not None:
                append_merge_conflict(
                    context.conflict_target,
                    f"{context.field_path}[rloc16:{rloc16}].extAddress",
                    candidate_extaddr, extaddr, limit=context.conflict_limit,
                )

        if existing_id is None:
            existing_id = next_id
            next_id += 1
            merged[existing_id] = deepcopy(record)
        else:
            existing = merged[existing_id]
            identity = f"extAddress:{extaddr}" if extaddr else f"rloc16:{rloc16}"
            path = f"{context.field_path if context else 'relationship'}[{identity}]"
            _fill_relationship(existing, record, path, context)

        if extaddr:
            by_extaddr[extaddr_key] = existing_id
        if rloc16:
            by_rloc16[rloc16_key].add(existing_id)

    return list(merged.values())


def _fill_relationship(
    target: dict[str, Any], source: dict[str, Any], path: str,
    context: MergeContext | None,
) -> None:
    for key, value in source.items():
        current = target.get(key)
        if key not in target or value_is_empty(current) or (
            key == "extAddress" and is_placeholder_ext_address(current)
            and not is_placeholder_ext_address(value)
        ):
            target[key] = deepcopy(value)
        elif isinstance(current, dict) and isinstance(value, dict):
            _fill_relationship(current, value, f"{path}.{key}", context)
        elif isinstance(current, list) and isinstance(value, list):
            target[key] = merge_lists(current, value)
        elif not value_is_empty(value) and not values_equivalent(current, value):
            if context and context.conflict_target is not None:
                append_merge_conflict(
                    context.conflict_target, f"{path}.{key}", current, value,
                    limit=context.conflict_limit,
                )


def merge_children_array(
    parent_rloc16: str,
    base_children: list[Any],
    incoming_children: list[Any],
    context: MergeContext | None = None,
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
        context=context,
    )


def merge_router_neighbors(
    base_neighbors: list[Any],
    incoming_neighbors: list[Any],
    context: MergeContext | None = None,
) -> list[dict[str, Any]]:
    """
    Merge routerNeighbors arrays by identity (rloc16 or extaddr).
    
    Args:
        base_neighbors: Existing routerNeighbors array
        incoming_neighbors: New routerNeighbors array
    
    Returns:
        Merged routerNeighbors array
    """
    return _merge_relationship_records(base_neighbors, incoming_neighbors, context=context)


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
        current = {}
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
        context,
    )


def _merge_neighbor_field(
    current: Any, incoming: Any, context: MergeContext
) -> Any:
    if not isinstance(incoming, list):
        return deepcopy(current)
    return merge_router_neighbors(
        current if isinstance(current, list) else [],
        incoming,
        context,
    )


def _merge_address_field(
    current: Any, incoming: Any, _context: MergeContext
) -> Any:
    if not isinstance(incoming, list):
        return deepcopy(current)
    return merge_unique_strings(current if isinstance(current, list) else [], incoming)
