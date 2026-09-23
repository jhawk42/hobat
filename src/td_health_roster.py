"""Source-attributed, validated Thread roster fact extraction."""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from td_device_fields import FIELD_DEFINITIONS, get_canonical_ext_address
from td_health_manifest import HealthDataset, RosterPolicy
from td_health_observation_model import device_id_from_ext_address


_ALIASES = {
    definition["path"]: (definition["path"], *definition["aliases"])
    for definition in FIELD_DEFINITIONS
}
_BOOLEAN_FIELDS = frozenset({
    "isBorderRouter", "isRouter", "isLeader", "isPrimaryBBR",
    "mode.rxOnWhenIdle", "mode.fullThreadDevice", "mode.fullNetworkData",
})
_INTEGER_FIELDS = frozenset({
    "routerId", "leaderData.partitionId", "leaderData.leaderRouterId",
})
_INVENTORY_FIELDS = frozenset({
    "threadVersion", "threadStackVersion", "vendorName", "vendorModel", "vendorSwVersion",
})
_PLACEHOLDERS = frozenset({"unknown", "n/a", "none", "null", "-", "--"})
_HEX64 = re.compile(r"^[0-9a-f]{16}$")


@dataclass(frozen=True)
class RosterFact:
    device_id: str
    field_key: str
    value_json: str
    value_class: str
    source_file: str
    source_rank: int
    confidence: str


def _raw_value(record: Mapping[str, Any], path: str) -> Any:
    current: Any = record
    for segment in path.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return None
        current = current[segment]
    return current


def _source_value(record: Mapping[str, Any], field: str) -> Any:
    aliases = ("eui", "eui64", "EUI64") if field == "eui64" else _ALIASES.get(field, (field,))
    for alias in aliases:
        value = _raw_value(record, alias)
        if value is not None:
            return value
    return None


def _validated(field: str, value: Any, policy: RosterPolicy) -> Any:
    if field in {"extAddress", "eui64"}:
        if not isinstance(value, str):
            return None
        canonical = value.strip().lower().replace(":", "").replace("-", "")
        if not _HEX64.fullmatch(canonical) or canonical == "0" * 16:
            return None
        return canonical
    if field == "omrIpv6Address":
        try:
            address = ipaddress.IPv6Address(value) if isinstance(value, str) else None
        except ipaddress.AddressValueError:
            return None
        return str(address) if address is not None and not address.is_multicast and not address.is_unspecified and not address.is_link_local else None
    if field == "ipv6Addresses":
        if not isinstance(value, list) or not value or len(value) > policy.max_addresses:
            return None
        try:
            parsed = [ipaddress.IPv6Address(item) for item in value if isinstance(item, str)]
        except ipaddress.AddressValueError:
            return None
        if len(parsed) != len(value) or any(address.is_unspecified or address.is_multicast for address in parsed):
            return None
        return sorted({str(address) for address in parsed})
    if field == "rloc16":
        if not isinstance(value, str) or not re.fullmatch(r"(?:0x)?[0-9a-fA-F]{4}", value):
            return None
        return f"0x{int(value.removeprefix('0x'), 16):04x}"
    if field in _INTEGER_FIELDS:
        if field == "leaderData.partitionId" and isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{1,8}", value):
            value = int(value, 16)
        if type(value) is not int:
            return None
        upper = 0xffffffff if field == "leaderData.partitionId" else 62
        return value if 0 <= value <= upper else None
    if field in _BOOLEAN_FIELDS:
        return value if type(value) is bool else None
    if isinstance(value, str):
        text = value.strip()
        return text if 0 < len(text) <= policy.max_string_length and text.lower() not in _PLACEHOLDERS else None
    return None


def extract_roster_facts(
    record: Mapping[str, Any], *, filename: str, dataset: HealthDataset,
    policy: RosterPolicy,
) -> tuple[RosterFact, ...]:
    """Never infer facts from identity context, relationships, or static labels."""
    if filename not in dataset.files:
        return ()
    try:
        device_id = device_id_from_ext_address(get_canonical_ext_address(record))
    except ValueError:
        return ()
    facts: list[RosterFact] = []
    for field, sources in policy.sources.items():
        rank = sources.get(filename)
        if rank is None:
            continue
        value = _validated(field, _source_value(record, field), policy)
        if value is None:
            continue
        value_class = "identity" if field == "extAddress" else "alias" if field == "eui64" else "address" if field in {"omrIpv6Address", "ipv6Addresses"} else "inventory" if field in _INVENTORY_FIELDS else "presentation" if field == "deviceLabel" else "transient"
        facts.append(RosterFact(device_id, field, json.dumps(value, sort_keys=True, separators=(",", ":")),
                                value_class, filename, rank, "high" if rank >= 3 else "medium"))
    return tuple(sorted(facts, key=lambda fact: (fact.device_id, fact.field_key)))