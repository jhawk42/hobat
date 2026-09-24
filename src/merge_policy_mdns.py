from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from td_record_merge import value_is_empty


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
