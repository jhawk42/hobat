"""Shared utility constants and helpers for Thread network diagnostics.

Provides TLV value sets, fetch utilities, device-type classification,
device record merging, and TLV detail-level mapping used by
otbr_cli_networkdiag_topology.py and otbr_cli_networkdiag_parsers.py.
"""
import re
import logging

import util_ot_ctl


# Thread TLV (Type-Length-Value)
# TLV value sets used for different detail levels by networkdiag functions to request Thread diagnostic information from devices.
# Some devices fail to return any TLV data when the list contains certain TLVs e.g. 28 Thread Stack Version TLV.
# So multiple detail levels allow retries with progressively simpler TLV sets.
# Note: Some Thread device implementations may not respond with all requested TLVs.

# TLV 0 = Ext Address (MAC Extended Address)
# TLV 1 = RLOC16 (Address16)
# TLV 2 = Mode (Capabilities)
# TLV 4 = Connectivity (Physical state, link quality, parent metrics, routing costs)
# TLV 5 = Route64 (ID sequence tracking paths and routing costs to all Router IDs)
# TLV 6 = Leader Data (Partition ID, Weighting, Leader node address)
# TLV 8 = IPv6 Address List
# TLV 9 = MAC Counters
# TLV 16 = Child Table
# TLV 23 = EUI64 (Factory-assigned 8-byte global identifier)
# TLV 24 = Thread Version (Protocol runtime version)
# TLV 25 = Vendor Name (Hardware creator name)
# TLV 26 = Vendor Model (Product SKU hardware identification)
# TLV 27 = Vendor SW Version (Running firmware version)
# TLV 28 = Vendor App URL (Developer/device-specific support URL, labeled as Thread Stack Version)
# TLV 34 = MLE Counters

# ROUTER TLVs - includes childtable
TLV_VALUES_DETAILED = "0 1 2 23 8 4 6 24 25 26 27 28 5 16 9 34"
TLV_VALUES_MEDIUM = "0 1 2 8 16 9"
TLV_VALUES_BASIC = "0 1 2 8"

# CHILD TLVs (excludes TLV 16 Child Table and TLV 6 Leader Data)
TLV_VALUES_CHILD_DETAILED = "0 1 2 8 9 24 34" ##  "0 1 2 8 24 9 34" ##"0 1 2 23 8 4 24 25 26 27 28 5 9 34"
TLV_VALUES_CHILD_MEDIUM_TV_MAC  = "0 1 2 8 9 34" ## "0 1 2 8 24 9"
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
            return TLV_VALUES_CHILD_MEDIUM_TV_MAC        
        case 2:
            return TLV_VALUES_CHILD_MEDIUM_MAC
        case 1:
            return TLV_VALUES_CHILD_BASIC
        case _:
            return TLV_VALUES_BASIC


def fetch_ipv6_addresses():
    """
    Queries Thread network for IPv6 addresses of all routers.
    Runs: ot-ctl meshdiag topology ip6-addrs
    Returns a dictionary mapping RLOC16 to IPv6 addresses.
    """
    output = util_ot_ctl.exec_ot_ctl("meshdiag topology ip6-addrs")
    logging.debug(
        f"[DEBUG] Output of 'meshdiag topology ip6-addrs':\n{output}\n")

    ipv6_map = {}

    # Parse output to extract RLOC16 and IPv6 address pairs
    # Expected format: "RLOC:0x5000 => ffxx::0200:x:x:x" or similar
    lines = output.split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Match patterns like "RLOC16: 0x5000" or "RLOC: 0x5000" followed by IPv6
        rloc_match = re.search(r"0x[0-9a-fA-F]{4}", line)

        # Match IPv6 addresses (simplified pattern)
        ipv6_match = re.search(
            r"([0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F]{0,4}", line)

        if rloc_match and ipv6_match:
            rloc = rloc_match.group(0)
            ipv6 = ipv6_match.group(0)

            if rloc not in ipv6_map:
                ipv6_map[rloc] = []
            ipv6_map[rloc].append(ipv6)

    return ipv6_map


def parse_ipv6_address_list(output):
    """Extracts IPv6 Address List from diagnostic output."""
    ipv6_list = []
    # Match IPv6 addresses in the IP6 Address List section
    lines = output.split("\n")
    in_ipv6_section = False
    for line in lines:
        if "IP6 Address List:" in line:
            in_ipv6_section = True
            continue
        if in_ipv6_section:
            if line.strip().startswith("- "):
                ipv6_addr = line.strip().lstrip("- ")
                ipv6_list.append(ipv6_addr)
            # Check for end of IPv6 section (next section header)
            elif line.strip() and (
                line.strip().startswith("ChildId:")
                or line.strip().startswith("Child Table:")
                or line.strip().startswith("MAC Counters:")
                or line.strip().startswith("MLE Counters:")
                or line.strip().startswith("Connectivity:")
                or line.strip().startswith("Leader Data:")
                or line.strip().startswith("Vendor Name:")
                or line.strip().startswith("Vendor Model:")
                or line.strip().startswith("Vendor SW Version:")
                or line.strip().startswith("Route:")
                or line.strip().startswith("Thread Stack Version:")
                or line.strip().startswith("EUI64:")
                or ("Ext Address:" in line and "Rloc16:" not in line)
            ):
                # End of IP6 list section
                break
            elif not line.strip():
                # Empty line might also indicate section boundary
                continue
    return ipv6_list


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
        - device_label: Keep existing if not starting with "Unknown-", else take new
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
    # extaddr: keep existing (it's the key, should be identical)
    # (no update needed)

    # rloc16: keep existing if not "Unknown", else take new
    if existing.get("rloc16") == "Unknown" and new.get("rloc16") != "Unknown":
        existing["rloc16"] = new["rloc16"]

    # device_label: keep existing if not starting with "Unknown-", else take new
    if existing.get("device_label", "").startswith("Unknown-") and not new.get("device_label", "").startswith("Unknown-"):
        existing["device_label"] = new["device_label"]

    # tlv_values: take new if new is non-empty dict and existing is not empty and len new > len existing, else keep existing
    if new.get("tlv_values") and (not existing.get("tlv_values") or len(new.get("tlv_values", {})) > len(existing.get("tlv_values", {}))):
        existing["tlv_values"] = new["tlv_values"]

    # tlv_values: take new if new is non-empty dict and existing is empty, else keep existing
    if not existing.get("tlv_values") and new.get("tlv_values"):
        existing["tlv_values"] = new["tlv_values"]

    # thread_stack_version: take new if existing is not present or if len new > len existing, else keep existing
    if new.get("thread_stack_version") and (not existing.get("thread_stack_version") or len(new.get("thread_stack_version", "")) > len(existing.get("thread_stack_version", ""))):
        existing["thread_stack_version"] = new["thread_stack_version"]

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

    # mode: take new if new mode is non-empty dict and existing is empty, else keep existing
    if not existing.get("mode") and new.get("mode"):
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

    # is_border_router: take new if new if True and existing is None or False of "Unknown", else keep existing
    if new.get("is_border_router") and (not existing.get("is_border_router") or existing.get("is_border_router") is None) or (existing.get("is_border_router") == "Unknown"):
        existing["is_border_router"] = new["is_border_router"]
        existing["type"] = "border router"

    # is_border_router: take new if new is True and existing is not True, else keep existing
    if new.get("is_border_router") and not existing.get("is_border_router"):
        existing["is_border_router"] = new["is_border_router"]

    # "br": take new if new is non-empty dict and existing is empty, else keep existing
    if not existing.get("br") and new.get("br"):
        existing["br"] = new["br"]

    # "type": (take new if new is non-empty and existing is empty) or (take new if new is "border router" and existing is "router", else keep existing)
    if (not existing.get("type") and new.get("type")) or (existing.get("type") == "router" and new.get("type") == "border router"):
        existing["type"] = new["type"]

    # "role": (take new if new is non-empty and existing is empty) or (take new if new is "border router" and existing is "router", else keep existing)
    if (not existing.get("role") and new.get("role")) or (existing.get("role") == "router" and new.get("role") == "border router"):
        existing["role"] = new["role"]
    
    # "leader": take new if new is non-empty and existing is empty, else keep existing
    if not existing.get("leader") and new.get("leader"):
        existing["leader"] = new["leader"]

    # route: take new if new is non-empty dict even if existing is not empty, else keep existing
    if new.get("route"):
        existing["route"] = new["route"]

    # route_data: take new if new is non-empty dict and existing is empty
    if not existing.get("route") and new.get("route"):
        existing["route"] = new["route"]

    # children: take new if new is non-empty list even if existing is not empty, else keep existing
    if new.get("children"):
        existing["children"] = new["children"]
        existing["total_children"] = len(existing["children"])

    # children: take new if new is non-empty list and existing is empty list
    if not existing.get("children") and new.get("children"):
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

