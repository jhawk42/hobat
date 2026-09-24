from __future__ import annotations

from typing import Any

from td_device_fields import (
    get_canonical_ext_address as get_canonical_extaddr,
    get_canonical_omr_address as get_canonical_omr,
    is_placeholder_ext_address as is_placeholder_extaddr,
    normalize_identifier_text,
    normalize_input_record,
)


def first_normalized_identifier(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = normalize_identifier_text(record.get(key))
        if value:
            return value
    return ""


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
