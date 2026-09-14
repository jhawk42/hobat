"""Canonical Thread device fields, normalization, and identity helpers."""

from __future__ import annotations

import ipaddress
from copy import deepcopy
from typing import Any, Mapping


FIELD_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"path": "extAddress", "aliases": ("extaddr", "extMacAddr", "extMacAddress", "extAddressHex", "ext_address", "Extended MAC"), "transform": "identifier"},
    {"path": "omrIpv6Address", "aliases": ("omrIpv6Addr", "omr_ipv6_addr"), "transform": "identifier"},
    {"path": "rloc16", "aliases": ("RLOC16",), "transform": "identifier"},
    {"path": "eui", "aliases": ("eui64", "EUI64"), "transform": "identifier"},
    {"path": "mode.fullThreadDevice", "aliases": ("mode.deviceType", "mode.deviceTypeFTD"), "transform": "boolean"},
    {"path": "mode.fullNetworkData", "aliases": ("mode.networkData",), "transform": "boolean"},
    {"path": "mode.rxOnWhenIdle", "aliases": ("mode.rxOn", "mode.rx_on_when_idle"), "transform": "boolean"},
    {"path": "mode.device", "aliases": (), "transform": "identity"},
    {"path": "isLeader", "aliases": ("leader",), "transform": "strictBoolean"},
    {"path": "isBorderRouter", "aliases": ("br", "is_border_router"), "transform": "boolean"},
    {"path": "isRouter", "aliases": ("is_router",), "transform": "boolean"},
    {"path": "isPrimaryBBR", "aliases": (), "transform": "strictBoolean"},
    {"path": "leaderEvidence", "aliases": (), "transform": "identity"},
    {"path": "primaryBBREvidence", "aliases": ("primaryBbrEvidence",), "transform": "identity"},
    {"path": "mleCounters.partIdChangesCount", "aliases": ("mleCounters.partitionIdChanges",), "transform": "number"},
    {"path": "mleCounters.newParentCount", "aliases": ("mleCounters.parentChanges",), "transform": "number"},
    {"path": "mleCounters.betterPartIdAttachAttemptsCount", "aliases": ("mleCounters.betterPartitionAttachAttempts",), "transform": "number"},
    {"path": "id", "aliases": (), "transform": "identity"},
    {"path": "routerId", "aliases": ("router_id",), "transform": "routerId"},
    {"path": "ipv6Addresses", "aliases": ("ipv6_addrs", "addresses"), "transform": "stringArray"},
    {"path": "role", "aliases": (), "transform": "identity"},
    {"path": "type", "aliases": (), "transform": "identity"},
    {"path": "threadVersion", "aliases": ("thread_version",), "transform": "identity"},
    {"path": "threadStackVersion", "aliases": ("thread_stack_version",), "transform": "identity"},
    {"path": "version", "aliases": ("ver",), "transform": "identity"},
    {"path": "vendorName", "aliases": ("vendor_name",), "transform": "identity"},
    {"path": "vendorModel", "aliases": ("vendor_model",), "transform": "identity"},
    {"path": "vendorSwVersion", "aliases": ("vendor_sw_version",), "transform": "identity"},
    {"path": "leaderData", "aliases": ("leader_data",), "transform": "identity"},
    {"path": "connectivity", "aliases": (), "transform": "identity"},
    {"path": "macCounters", "aliases": ("mac_counters",), "transform": "identity"},
    {"path": "mleCounters", "aliases": ("mle_counters",), "transform": "identity"},
    {"path": "timeStatistics", "aliases": ("time_statistics",), "transform": "identity"},
    {"path": "route", "aliases": ("route64", "route_data"), "transform": "route"},
    {"path": "children", "aliases": (), "transform": "relationship"},
    {"path": "childTable", "aliases": ("router_child_table",), "transform": "relationship"},
    {"path": "childIpv6Addresses", "aliases": ("child_ipv6_addresses",), "transform": "stringArray"},
    {"path": "routerNeighbors", "aliases": ("router_neighbor_table",), "transform": "relationship"},
    {"path": "rlocAddress", "aliases": (), "transform": "identifier"},
    {"path": "mlEidIid", "aliases": (), "transform": "identity"},
    {"path": "state", "aliases": (), "transform": "identity"},
    {"path": "updated", "aliases": (), "transform": "identity"},
    {"path": "created", "aliases": (), "transform": "identity"},
    {"path": "routerCount", "aliases": (), "transform": "number"},
    {"path": "hostsService", "aliases": (), "transform": "boolean"},
    {"path": "baId", "aliases": (), "transform": "identity"},
    {"path": "baState", "aliases": (), "transform": "identity"},
    {"path": "brCounters", "aliases": (), "transform": "identity"},
    {"path": "extPanId", "aliases": ("ext_pan_id",), "transform": "identifier"},
    {"path": "networkName", "aliases": ("network_name",), "transform": "identity"},
    {"path": "deviceLabel", "aliases": ("device_label", "hostName", "hostname"), "transform": "identity"},
    {"path": "nodeId", "aliases": ("node_id",), "transform": "identity"},
    {"path": "tlvValues", "aliases": ("tlv_values",), "transform": "identity"},
    {"path": "lastAttemptResponded", "aliases": ("last_attempt_responded",), "transform": "number"},
    {"path": "lastAttemptTlvDetailLevel", "aliases": ("last_attempt_tlv_detail_level",), "transform": "number"},
    {"path": "networkDiagnosticStatus", "aliases": ("network_diagnostic_status",), "transform": "identity"},
    {"path": "reachability", "aliases": (), "transform": "identity"},
    {"path": "ping", "aliases": (), "transform": "identity"},
    {"path": "totalChildren", "aliases": ("total_children",), "transform": "number"},
    {"path": "totalLinks", "aliases": ("total_links",), "transform": "number"},
    {"path": "totalLink1", "aliases": ("total_link_1",), "transform": "number"},
    {"path": "totalLink2", "aliases": ("total_link_2",), "transform": "number"},
    {"path": "totalLink3", "aliases": ("total_link_3",), "transform": "number"},
    {"path": "links1", "aliases": ("1_links",), "transform": "identity"},
    {"path": "links2", "aliases": ("2_links",), "transform": "identity"},
    {"path": "links3", "aliases": ("3_links",), "transform": "identity"},
    {"path": "error", "aliases": ("_error",), "transform": "identity"},
    {"path": "_source_files", "aliases": (), "transform": "identity"},
    {"path": "_merge_conflicts", "aliases": (), "transform": "identity"},
)

PREFERRED_FIELD_NAMES: dict[str, str] = {
    alias: definition["path"]
    for definition in FIELD_DEFINITIONS
    for alias in definition["aliases"]
}
for _definition in FIELD_DEFINITIONS:
    PREFERRED_FIELD_NAMES[_definition["path"]] = _definition["path"]

EXT_ADDRESS_ALIASES = ("extAddress", "extaddr", "extMacAddr", "extMacAddress", "extAddressHex", "ext_address", "Extended MAC")
OMR_ADDRESS_ALIASES = ("omrIpv6Address", "omrIpv6Addr", "omr_ipv6_addr")
RLOC16_ALIASES = ("rloc16", "RLOC16")
TRANSPORT_FIELDS = frozenset({"data", "attributes", "relationships", "meta", "links", "included"})
PLACEHOLDER_EXT_ADDRESSES = frozenset({"0000000000000000"})

_ROUTE_ALIASES = {
    "id_sequence": "idSequence",
    "route_data": "routeData",
    "route_id": "routeId",
    "route_cost": "routeCost",
    "link_quality_in": "linkQualityIn",
    "link_quality_out": "linkQualityOut",
}


def normalize_identifier_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def _first_identifier(record: Mapping[str, Any], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        value = normalize_identifier_text(record.get(alias))
        if value:
            return value
    return ""


def get_canonical_ext_address(record: Mapping[str, Any]) -> str:
    return _first_identifier(record, EXT_ADDRESS_ALIASES)


def get_canonical_omr_address(record: Mapping[str, Any]) -> str:
    return _first_identifier(record, OMR_ADDRESS_ALIASES)


def is_placeholder_omr_address(value: Any) -> bool:
    normalized = normalize_identifier_text(value)
    if not normalized:
        return False
    try:
        return ipaddress.IPv6Address(normalized).is_unspecified
    except ipaddress.AddressValueError:
        return False


def get_canonical_rloc16(record: Mapping[str, Any]) -> str:
    return _first_identifier(record, RLOC16_ALIASES)


def is_placeholder_ext_address(value: Any) -> bool:
    normalized = normalize_identifier_text(value)
    return (
        normalized in PLACEHOLDER_EXT_ADDRESSES
        or normalized == ""
        or normalized.startswith(("found-", "unknown-", "offline-"))
    )


def _get_path(record: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = record
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _set_path(record: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = record
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _delete_path(record: dict[str, Any], path: str) -> None:
    parts = path.split(".")
    current: Any = record
    parents: list[tuple[dict[str, Any], str]] = []
    for part in parts[:-1]:
        if not isinstance(current, dict) or not isinstance(current.get(part), dict):
            return
        parents.append((current, part))
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)
    for parent, part in reversed(parents):
        if parent.get(part) == {}:
            parent.pop(part)


def _to_boolean(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return value


def _to_number(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            number = float(text)
        except ValueError:
            return value
        return int(number) if number.is_integer() else number
    return value


def normalize_router_id(value: Any) -> int | None:
    """Return a valid Thread Router ID, or None when the value is malformed."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        router_id = value
    elif isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return None
        try:
            router_id = int(text, 16 if text.startswith("0x") else 10)
        except ValueError:
            return None
    else:
        return None
    return router_id if 0 <= router_id <= 62 else None


def _normalize_role_evidence(record: dict[str, Any], source: str | None = None) -> None:
    for role_field in ("isLeader", "isPrimaryBBR"):
        if role_field in record and not isinstance(record[role_field], bool):
            record.pop(role_field)

    if source == "rest" and record.get("isPrimaryBBR") is True:
        record["primaryBBREvidence"] = "explicit-rest"

    router_id = normalize_router_id(record.get("routerId"))
    if router_id is None:
        record.pop("routerId", None)
    else:
        record["routerId"] = router_id

    leader_data = record.get("leaderData")
    leader_router_id = (
        normalize_router_id(leader_data.get("leaderRouterId", leader_data.get("leader_router_id")))
        if isinstance(leader_data, dict)
        else None
    )
    if isinstance(leader_data, dict):
        leader_data.pop("leader_router_id", None)
        if leader_router_id is None:
            leader_data.pop("leaderRouterId", None)
        else:
            leader_data["leaderRouterId"] = leader_router_id

    derived_match = router_id is not None and router_id == leader_router_id
    explicit = record.get("isLeader") if isinstance(record.get("isLeader"), bool) else None
    if explicit is not None:
        if not (explicit and derived_match and record.get("leaderEvidence") == "leader-router-id-match"):
            record["leaderEvidence"] = "explicit"
        if derived_match and explicit is False:
            record["roleEvidenceConflicts"] = [{"role": "isLeader", "explicit": False, "derived": True}]
    elif derived_match:
        record["isLeader"] = True
        record["leaderEvidence"] = "leader-router-id-match"


def _normalize_route(value: Any) -> Any:
    if not isinstance(value, dict):
        return deepcopy(value)
    result: dict[str, Any] = {}
    for key, child in value.items():
        preferred = _ROUTE_ALIASES.get(key, key)
        if preferred == "routeData" and isinstance(child, list):
            result[preferred] = [_normalize_route(item) for item in child]
        else:
            result[preferred] = _normalize_route(child) if isinstance(child, dict) else deepcopy(child)
    return result


def _transform_value(transform: str, value: Any, source: str | None) -> Any:
    if transform == "identifier":
        normalized = normalize_identifier_text(value)
        return normalized if normalized else deepcopy(value)
    if transform == "boolean":
        return _to_boolean(value)
    if transform == "strictBoolean":
        return value if isinstance(value, bool) else None
    if transform == "number":
        return _to_number(value)
    if transform == "routerId":
        return normalize_router_id(value)
    if transform == "route":
        return _normalize_route(value)
    if transform == "relationship" and isinstance(value, list):
        return [
            normalize_input_record(item, source=source) if isinstance(item, dict) else deepcopy(item)
            for item in value
        ]
    if transform == "stringArray" and isinstance(value, list):
        return [normalize_identifier_text(item) if isinstance(item, str) else deepcopy(item) for item in value]
    return deepcopy(value)


def normalize_input_record(
    record: Mapping[str, Any],
    source: str | None = None,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an idempotently normalized copy of one device or relationship record."""
    del options
    result = deepcopy(dict(record))
    for key in TRANSPORT_FIELDS:
        result.pop(key, None)

    for definition in FIELD_DEFINITIONS:
        preferred = definition["path"]
        candidates = (preferred, *definition["aliases"])
        selected = next(
            ((candidate, value) for candidate in candidates if (found := _get_path(result, candidate))[0] for value in (found[1],)),
            None,
        )
        if selected is None:
            continue
        selected_path, value = selected
        transformed = _transform_value(definition["transform"], value, source)
        if definition["transform"] in {"routerId", "strictBoolean"} and transformed is None:
            for candidate in candidates:
                _delete_path(result, candidate)
            continue
        _set_path(result, preferred, transformed)
        for candidate in candidates:
            if candidate != preferred:
                _delete_path(result, candidate)

    mode = result.get("mode")
    if isinstance(mode, dict) and "device" not in mode and isinstance(mode.get("fullThreadDevice"), bool):
        mode["device"] = "FTD" if mode["fullThreadDevice"] else "MTD"
    _normalize_role_evidence(result, source)
    return result


def get_device_identity_keys(
    record: Mapping[str, Any],
    strategy: str = "by-identity",
    options: Mapping[str, Any] | None = None,
) -> list[str]:
    del options
    keys: list[str] = []
    if strategy == "by-identity":
        ext_address = get_canonical_ext_address(record)
        if ext_address and not is_placeholder_ext_address(ext_address):
            keys.append(f"extAddress:{ext_address}")
        omr_address = get_canonical_omr_address(record)
        if omr_address and not is_placeholder_omr_address(omr_address):
            keys.append(f"omrIpv6Address:{omr_address}")
    rloc16 = get_canonical_rloc16(record)
    if rloc16:
        keys.append(f"rloc16:{rloc16}")
    return list(dict.fromkeys(keys))
