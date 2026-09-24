"""Shared utility constants and helpers for Thread network diagnostics.

Provides TLV value sets, fetch utilities, device-type classification,
device record merging, and TLV detail-level mapping used by
otbr_cli_networkdiag_topology.py and otbr_cli_networkdiag_parsers.py.
"""
import ipaddress
import logging
import re

import util_ot_ctl


# Thread TLV (Type-Length-Value)
# TLV value sets used for different detail levels by networkdiag functions to request Thread diagnostic information from devices.
# Some devices fail to return any TLV data when the list contains certain TLVs e.g. 28 Thread Stack Version TLV.
# So multiple detail levels allow retries with progressively simpler TLV sets.
# Note: Some Thread device implementations may not respond with all requested TLVs.

# TLV 0 = Ext Address (MAC Extended Address)
# TLV 1 = RLOC16 (Address16)
# TLV 2 = Mode (Capabilities)
# TLV 3 = Timeout (Timeout value for sleepy end devices)
# TLV 4 = Connectivity (Physical state, link quality, parent metrics, routing costs)
# TLV 5 = Route64 (ID sequence tracking paths and routing costs to all Router IDs)
# TLV 6 = Leader Data (Partition ID, Weighting, Leader node address)
# TLV 7 = Network Data (Network configuration, service data, and routing information)
# TLV 8 = IPv6 Address List
# TLV 9 = MAC Counters
# TLV 14 = Battery Level
# TLV 15 = Supply Voltage
# TLV 16 = Child Table
# TLV 17 = Channel Pages
# TLV 19 = Max Child Timeout
# TLV 23 = EUI64 (Factory-assigned 8-byte global identifier)
# TLV 24 = Thread Version (Protocol runtime version)
# TLV 25 = Vendor Name (Hardware creator name)
# TLV 26 = Vendor Model (Product SKU hardware identification)
# TLV 27 = Vendor SW Version (Running firmware version)
# TLV 28 = Thread Stack Version
# TLV 34 = MLE Counters

# ROUTER TLVs - includes childtable
TLV_VALUES_DETAILED = "0 1 2 23 8 4 6 24 25 26 27 28 5 16 9 34"
TLV_VALUES_MEDIUM = "0 1 2 8 16 9"
TLV_VALUES_BASIC = "0 1 2 8"

# CHILD TLVs (excludes TLV 16 Child Table and TLV 6 Leader Data)
TLV_VALUES_CHILD_DETAILED = "0 1 2 8 9 28 34"
TLV_VALUES_CHILD_MEDIUM_MAC_MLE = "0 1 2 8 9 34"
TLV_VALUES_CHILD_MEDIUM_MAC = "0 1 2 8 9"
TLV_VALUES_CHILD_BASIC = "0 1 2 8"


def get_tlv_values_for_detail_level(tlv_detail_level: int) -> str:
    """
    Maps a detail level to the appropriate TLV values string for network diagnostics.

    Args:
        tlv_detail_level: Detail level (6=DETAILED, 5=MEDIUM, 4/3/2/1=SIMPLE, etc.)
                         Levels 10-6 are for routers, 5-1 are for child devices.

    Returns:
        TLV values string (space-separated TLV numbers)
    """
    match tlv_detail_level:
        # ROUTER TLV sets
        case 10:
            return TLV_VALUES_DETAILED
        case 9:
            return TLV_VALUES_MEDIUM
        case 8:
            return TLV_VALUES_BASIC

        # CHILD TLV sets
        case 4:
            return TLV_VALUES_CHILD_DETAILED
        case 3:
            return TLV_VALUES_CHILD_MEDIUM_MAC_MLE
        case 2:
            return TLV_VALUES_CHILD_MEDIUM_MAC
        case 1:
            return TLV_VALUES_CHILD_BASIC
        case _:
            return TLV_VALUES_BASIC


def _parse_meshdiag_ipv6_addresses(output: str) -> dict[str, list[str]]:
    ipv6_map = {}
    current_rloc16 = None

    for line in output.splitlines():
        rloc16_match = re.search(r"\brloc16:\s*(0x[0-9a-fA-F]{4})\b", line)
        if rloc16_match:
            current_rloc16 = rloc16_match.group(1).lower()
            ipv6_map.setdefault(current_rloc16, [])
            continue
        if line.lstrip().startswith("id:"):
            current_rloc16 = None
            continue
        if current_rloc16 is None:
            continue
        for candidate in re.findall(r"[0-9a-fA-F:]+", line):
            if ":" not in candidate:
                continue
            try:
                address = str(ipaddress.IPv6Address(candidate))
            except ValueError:
                continue
            if address not in ipv6_map[current_rloc16]:
                ipv6_map[current_rloc16].append(address)

    return ipv6_map


def fetch_ipv6_addresses():
    """
    Queries Thread network for IPv6 addresses of all routers.
    Runs: ot-ctl meshdiag topology ip6-addrs
    Returns a dictionary mapping RLOC16 to IPv6 addresses.
    """
    output = util_ot_ctl.exec_ot_ctl("meshdiag topology ip6-addrs")
    logging.debug(
        f"[DEBUG] Output of 'meshdiag topology ip6-addrs':\n{output}\n")

    if not isinstance(output, str) or output.lstrip().lower().startswith("error"):
        logging.warning("Could not fetch meshdiag IPv6 addresses: %s", output)
        return {}

    return _parse_meshdiag_ipv6_addresses(output)


# TLV 2: Mode TLV to get more detailed info about the node's capabilities and role (e.g., if it's a sleepy end device, router-eligible end device, or full router) which can help better understand the topology and identify potential issues with devices that are not behaving as expected. This will also help enrich the topology map with more detailed information about each node's role and capabilities in the network.

def device_type_from_mode(mode):
    """Returns device classification from Thread mode flags."""
    if (
        mode.get("rx_on_when_idle") == 1
        and mode.get("device_type") == 1
        and mode.get("network_data") == 1
    ):
        return "FTD"
    if (
        mode.get("rx_on_when_idle") == 0
        and mode.get("device_type") == 0
        and mode.get("network_data") == 0
    ):
        return "MTD"
    return "Unknown"


def reconcile_device_record(existing: dict, incoming: dict) -> dict:
    from td_device_fields import FIELD_DEFINITIONS, normalize_input_record
    from td_record_merge import append_merge_conflict, merge_lists, value_is_empty

    current = normalize_input_record(existing, source="cli")
    updated = normalize_input_record(incoming, source="cli")
    preferred_to_key = {
        definition["path"]: next(
            (key for key in (*definition["aliases"], definition["path"])
             if "." not in key and (key in existing or key in incoming)),
            definition["path"],
        )
        for definition in FIELD_DEFINITIONS if "." not in definition["path"]
    }

    def apply(field: str, value: object) -> None:
        key = preferred_to_key.get(field, field)
        existing[key] = value
        current[field] = value

    for field in ("extAddress", "deviceLabel"):
        old, new = current.get(field), updated.get(field)
        placeholder = isinstance(old, str) and old.startswith(("found-", "Unknown-", "Offline-"))
        new_is_real = isinstance(new, str) and new and not new.startswith(("found-", "Unknown-", "Offline-"))
        if new_is_real and (value_is_empty(old) or placeholder):
            apply(field, new)

    if existing.get("rloc16") == "Unknown" and updated.get("rloc16") not in (None, "Unknown", "unknown"):
        apply("rloc16", updated["rloc16"])

    for field in ("lastAttemptResponded", "lastAttemptTlvDetailLevel"):
        new = updated.get(field)
        old = current.get(field)
        if new is not None and (old is None or new > old):
            apply(field, new)

    for field, new in updated.items():
        if field in ("extAddress", "deviceLabel", "rloc16", "lastAttemptResponded", "lastAttemptTlvDetailLevel"):
            continue
        old = current.get(field)
        if field == "ipv6Addresses" and isinstance(new, list):
            if new:
                apply(field, merge_lists(old if isinstance(old, list) else [], new))
        elif field in ("mode", "route", "children"):
            if not value_is_empty(new):
                apply(field, incoming.get(preferred_to_key.get(field, field), new))
                if field == "children":
                    apply("totalChildren", len(new))
        elif field in ("isRouter", "isBorderRouter"):
            if new is True and old is not True:
                apply(field, new)
                if field == "isRouter":
                    apply("role", "router")
                else:
                    apply("type", "border router")
        elif field in ("type", "role"):
            if not value_is_empty(new) and (value_is_empty(old) or (old == "router" and new == "border router")):
                apply(field, new)
        elif field == "tlvValues" and isinstance(new, dict):
            if value_is_empty(old) or (isinstance(old, dict) and len(new) > len(old)):
                if new:
                    apply(field, new)
        elif field == "threadStackVersion":
            if not value_is_empty(new) and (value_is_empty(old) or old == "Unknown" or len(str(new)) > len(str(old))):
                apply(field, new)
        elif not value_is_empty(new):
            if value_is_empty(old) or old == "Unknown":
                apply(field, new)
            elif old != new and not isinstance(new, (dict, list)):
                append_merge_conflict(existing, field, old, new)
    for source in incoming.get("_source_files", []):
        sources = existing.setdefault("_source_files", [])
        if source not in sources:
            sources.append(source)
    return existing
