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


def merge_device_record(existing: dict, new: dict) -> dict:
    """
    Merges a newer device record into an existing one, preserving the most complete information.

    Used when the same device responds to multiple multicast retries with different TLV data.
    This function applies field-by-field merge rules to combine responses intelligently.

    Args:
        existing: The existing device record to merge into (mutated in place)
        new: The new device record to merge from

    Returns:
        The updated existing dict (mutated and also returned)

    Merge rules (field by field):
        - extaddr: Keep existing (should be identical, it's the key)
        - rloc16: Keep existing if not "Unknown", else take new
        - device_label: Keep existing label, unless it is a discovered placeholder
        - tlv_values: Take new if new is non-empty dict and existing is empty, else keep existing
        - thread_stack_version: Keep existing if not "Unknown", else take new
        - mode: Take new if new mode is non-empty and existing is empty, else keep existing
        - ipv6_addrs: Union: merge lists, deduplicate preserving order
        - responder_ipv6: Keep existing (first responder wins)
        - children: Take new if new is non-empty list and existing is empty, else keep existing
        - mac_counters: Take new if new is non-empty dict and existing is empty, else keep existing
        - mle_counters: Take new if new is non-empty dict and existing is empty, else keep existing
        - time_statistics: Take new if new is non-empty dict and existing is empty, else keep existing
        - eui64: Keep existing if present, else take new
        - connectivity: Take new if new is non-empty dict and existing is empty, else keep existing
        - leader_data: Take new if new is non-empty dict and existing is empty, else keep existing
        - vendor_name: Keep existing if present, else take new
        - vendor_model: Keep existing if present, else take new
        - vendor_sw_version: Keep existing if present, else take new
        - route: Take new if new is non-empty dict and existing is empty, else keep existing
    """
    # Replace discovery placeholders when a later diagnostic returns a real identity.
    placeholder_prefixes = ("found-", "Unknown-", "Offline-")
    existing_extaddr = existing.get("extaddr", "")
    new_extaddr = new.get("extaddr", "")
    if (
        isinstance(existing_extaddr, str)
        and existing_extaddr.startswith(placeholder_prefixes)
        and isinstance(new_extaddr, str)
        and new_extaddr
        and not new_extaddr.startswith(placeholder_prefixes)
    ):
        existing["extaddr"] = new_extaddr

    # rloc16: keep existing if not "Unknown", else take new
    if existing.get("rloc16") == "Unknown" and new.get("rloc16") != "Unknown":
        existing["rloc16"] = new["rloc16"]

    # Retain support for legacy Unknown- and Offline- cached placeholders.
    existing_label = existing.get("device_label", "")
    new_label = new.get("device_label", "")
    existing_is_placeholder = existing_label.startswith(placeholder_prefixes)
    new_is_placeholder = new_label.startswith(placeholder_prefixes)
    if not existing_label and new_label:
        existing["device_label"] = new_label
    elif existing_is_placeholder and new_label and not new_is_placeholder:
        existing["device_label"] = new["device_label"]

    # Keep highest attempt/detail metadata, including 0 values from first-attempt success.
    new_last_attempt_responded = new.get("last_attempt_responded")
    existing_last_attempt_responded = existing.get("last_attempt_responded")
    if (
        new_last_attempt_responded is not None
        and (
            existing_last_attempt_responded is None
            or new_last_attempt_responded > existing_last_attempt_responded
        )
    ):
        existing["last_attempt_responded"] = new_last_attempt_responded

    new_last_attempt_tlv_detail_level = new.get(
        "last_attempt_tlv_detail_level")
    existing_last_attempt_tlv_detail_level = existing.get(
        "last_attempt_tlv_detail_level")
    if (
        new_last_attempt_tlv_detail_level is not None
        and (
            existing_last_attempt_tlv_detail_level is None
            or new_last_attempt_tlv_detail_level > existing_last_attempt_tlv_detail_level
        )
    ):
        existing["last_attempt_tlv_detail_level"] = new_last_attempt_tlv_detail_level

    # tlv_values: take new if new is non-empty dict and len new > len existing, else keep existing
    new_tlv_values = new.get("tlv_values", {})
    existing_tlv_values = existing.get("tlv_values", {})
    if new_tlv_values and existing_tlv_values and len(new_tlv_values) > len(existing_tlv_values):
        existing["tlv_values"] = new_tlv_values

    # tlv_values: take new if new is non-empty dict and existing is empty, else keep existing
    if not existing_tlv_values and new_tlv_values:
        existing["tlv_values"] = new_tlv_values

    # thread_stack_version: take new if len new > len existing, else keep existing
    new_thread_stack_version = new.get("thread_stack_version")
    existing_thread_stack_version = existing.get("thread_stack_version")
    if new_thread_stack_version and existing_thread_stack_version and len(new_thread_stack_version) > len(existing_thread_stack_version):
        existing["thread_stack_version"] = new_thread_stack_version

    # thread_stack_version: keep existing if not "Unknown", else take new
    if existing.get("thread_stack_version") == "Unknown" and new.get("thread_stack_version") != "Unknown":
        existing["thread_stack_version"] = new["thread_stack_version"]

    # thread_version: take new if existing is not present, else keep existing
    if not existing.get("thread_version") and new.get("thread_version"):
        existing["thread_version"] = new["thread_version"]

    # ver: take new if existing is not present", else keep existing
    if not existing.get("ver") and new.get("ver"):
        existing["ver"] = new["ver"]

    # mode: take new if new mode is non empty even if existing is not empty, else keep existing
    if new.get("mode"):
        existing["mode"] = new["mode"]

    # ipv6_addrs: union merge, deduplicate preserving order
    if existing.get("ipv6_addrs") and new.get("ipv6_addrs"):
        # Merge lists, deduplicate while preserving order
        seen = set(existing["ipv6_addrs"])
        for addr in new["ipv6_addrs"]:
            if addr not in seen:
                existing["ipv6_addrs"].append(addr)
                seen.add(addr)
    elif new.get("ipv6_addrs"):
        existing["ipv6_addrs"] = new["ipv6_addrs"]

    # omr_ipv6_addr: keep existing (first responder wins)
    if not existing.get("omr_ipv6_addr") and new.get("omr_ipv6_addr"):
        existing["omr_ipv6_addr"] = new["omr_ipv6_addr"]

    # is_router: take new if new is True and existing is not True, else keep existing
    if new.get("is_router") and not existing.get("is_router"):
        existing["is_router"] = new["is_router"]
        existing["role"] = "router"

    # is_border_router: take new if new if True and existing is None or False or "Unknown", else keep existing
    new_is_border_router = new.get("is_border_router")
    existing_is_border_router = existing.get("is_border_router")
    if new_is_border_router and (not existing_is_border_router or existing_is_border_router is None or existing_is_border_router == "Unknown"):
        existing["is_border_router"] = new_is_border_router
        existing["type"] = "border router"

    # "br": take new if new is non-empty dict and existing is empty, else keep existing
    if not existing.get("br") and new.get("br"):
        existing["br"] = new["br"]

    # "type": (take new if new is non-empty and existing is empty) or (take new if new is "border router" and existing is "router", else keep existing)
    new_type = new.get("type")
    existing_type = existing.get("type")
    if (not existing_type and new_type) or (existing_type == "router" and new_type == "border router"):
        existing["type"] = new_type

    # "role": (take new if new is non-empty and existing is empty) or (take new if new is "border router" and existing is "router", else keep existing)
    new_role = new.get("role")
    existing_role = existing.get("role")
    if (not existing_role and new_role) or (existing_role == "router" and new_role == "border router"):
        existing["role"] = new_role

    # "leader": take new if new is non-empty and existing is empty, else keep existing
    if not existing.get("leader") and new.get("leader"):
        existing["leader"] = new["leader"]

    # route: take new if new is non-empty dict even if existing is not empty, else keep existing
    if new.get("route"):
        existing["route"] = new["route"]

    # children: take new if new is non-empty list even if existing is not empty, else keep existing
    if new.get("children"):
        existing["children"] = new["children"]
        existing["total_children"] = len(existing["children"])

    # mac_counters: take new if new is non-empty dict and existing is empty
    if not existing.get("mac_counters") and new.get("mac_counters"):
        existing["mac_counters"] = new["mac_counters"]

    # mle_counters: take new if new is non-empty dict and existing is empty
    if not existing.get("mle_counters") and new.get("mle_counters"):
        existing["mle_counters"] = new["mle_counters"]

    # time_statistics: take new if new is non-empty dict and existing is empty
    if not existing.get("time_statistics") and new.get("time_statistics"):
        existing["time_statistics"] = new["time_statistics"]

    # eui64: keep existing if present, else take new
    if not existing.get("eui64") and new.get("eui64"):
        existing["eui64"] = new["eui64"]

    # connectivity: take new if new is non-empty dict and existing is empty
    if not existing.get("connectivity") and new.get("connectivity"):
        existing["connectivity"] = new["connectivity"]

    # leader_data: take new if new is non-empty dict and existing is empty
    if not existing.get("leader_data") and new.get("leader_data"):
        existing["leader_data"] = new["leader_data"]

    # vendor_name: keep existing if present, else take new
    if not existing.get("vendor_name") and new.get("vendor_name"):
        existing["vendor_name"] = new["vendor_name"]

    # vendor_model: keep existing if present, else take new
    if not existing.get("vendor_model") and new.get("vendor_model"):
        existing["vendor_model"] = new["vendor_model"]

    # vendor_sw_version: keep existing if present, else take new
    if not existing.get("vendor_sw_version") and new.get("vendor_sw_version"):
        existing["vendor_sw_version"] = new["vendor_sw_version"]

    return existing
