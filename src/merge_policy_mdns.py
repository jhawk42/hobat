from __future__ import annotations

from copy import deepcopy
from typing import Any

from td_record_merge import value_is_empty
from td_device_fields import get_matter_fabric_node_identity
from td_network_identity import canonical_ext_pan_id


def observed_service_network(record: dict[str, Any]) -> str | None:
    """Only this MeshCoP observation's XPAN is scope, not a sibling service's."""
    if record.get("scope") != "_meshcop._udp.local.":
        return None
    service = record.get("serviceInfo", record.get("service_info", {}))
    properties = service.get("properties", {}) if isinstance(service, dict) else {}
    xp = properties.get("xp") if isinstance(properties, dict) else None
    if xp is None:
        return None
    if not isinstance(xp, dict) or xp.get("hex") is None:
        raise ValueError("Invalid MeshCoP Extended PAN ID")
    return canonical_ext_pan_id(xp["hex"])


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
    incoming_first = (
        base_timestamp is not None and incoming_timestamp is not None
        and incoming_timestamp > base_timestamp
    )
    primary, secondary = (
        (incoming_service_info, base_service_info) if incoming_first
        else (base_service_info, incoming_service_info)
    )
    result = deepcopy(primary)
    for key, value in secondary.items():
        if key not in result or value_is_empty(result[key]):
            result[key] = deepcopy(value)
        elif isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_mdns_service_info(result[key], value, None, None)
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
    return event_priorities.get(event.strip().lower(), 0)


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
    record_key = record.get("recordKey", record.get("record_key"))
    if isinstance(record_key, str) and "|" in record_key:
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
    preferred_key = {"FabricID_compressed": "fabricIdCompressed", "NodeID": "nodeId"}.get(key, key)
    prop_obj = props.get(preferred_key, props.get(key))
    if not isinstance(prop_obj, dict):
        return ""
    decoded = prop_obj.get("decoded")
    if isinstance(decoded, str):
        return decoded.strip()
    return ""


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
    server_key_value = _normalize_alias_text(record.get("serverKey", record.get("server_key")), lower=True)

    service_info = record.get("serviceInfo", record.get("service_info"))
    if isinstance(service_info, dict):
        if not server_value:
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
        "omrIpv6Address",
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

    service_info = out.get("serviceInfo")
    if isinstance(service_info, dict):
        if "server" not in out and isinstance(service_info.get("server"), str):
            out["server"] = service_info.get("server")
        if "serverKey" not in out and isinstance(service_info.get("key"), str):
            out["serverKey"] = service_info.get("key")

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
        "omrIpv6Address",
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
