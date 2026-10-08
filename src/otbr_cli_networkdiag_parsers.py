"""Parser functions for Thread network diagnostic output.

Each function receives the raw text output from ot-ctl networkdiagnostic get
and extracts a specific TLV field, returning a structured dict or value.
"""
import ipaddress
import logging
import re
import uuid
from collections.abc import Mapping
from copy import deepcopy

from otbr_cli_networkdiag_util import (
    DIAGNOSTIC_TLV_CONTROL_TYPES,
    device_type_from_mode,
)
from util_network import decode_short_thread_version
from util_mac_counters import derive_mac_counter_metrics, enrich_mac_counters


RAW_MAC_COUNTER_FIELDS: Mapping[str, str] = {
    "IfInUnknownProtos": "ifinunknownprotos",
    "IfInErrors": "ifinerrors",
    "IfOutErrors": "ifouterrors",
    "IfInUcastPkts": "ifinucastpkts",
    "IfInBroadcastPkts": "ifinbroadcastpkts",
    "IfInDiscards": "ifindiscards",
    "IfOutUcastPkts": "ifoutucastpkts",
    "IfOutBroadcastPkts": "ifoutbroadcastpkts",
    "IfOutDiscards": "ifoutdiscards",
}

FORMATTED_DIAGNOSTIC_TLV_TYPES = frozenset({2, 4, 5, 6, 9, 16, 34})
RAW_DIAGNOSTIC_TLV_TYPES = frozenset({0, 1, 8, 23, 24, 25, 26, 27, 28, 32, 33})
SINGLE_VALUE_DIAGNOSTIC_TLV_TYPES = frozenset({
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 14, 15, 16, 17, 18, 19,
    23, 24, 25, 26, 27, 28, 32, 33, 34,
})
DIAGNOSTIC_STRING_TLV_MAX_LENGTHS = {25: 32, 26: 32, 27: 16, 28: 64}
DIAGNOSTIC_RESPONSE_PREFIX = "DIAG_GET.rsp/ans from "


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


def parse_mode_flags(output):
    """Extracts top-level TLV 2 Mode flags from diagnostic output."""
    mode = {}
    lines = output.split("\n")
    in_mode_section = False

    for line in lines:
        stripped = line.strip()

        # Top-level "Mode:" line (child mode blocks are indented)
        if stripped == "Mode:" and not line.startswith(" "):
            in_mode_section = True
            continue

        if not in_mode_section:
            continue

        # End mode section at next top-level field
        if stripped and not line.startswith(" "):
            break

        if "RxOnWhenIdle:" in line:
            val_match = re.search(r"RxOnWhenIdle:\s*(\d+)", line)
            if val_match:
                mode["rx_on_when_idle"] = int(val_match.group(1))
        elif "DeviceType:" in line:
            val_match = re.search(r"DeviceType:\s*(\d+)", line)
            if val_match:
                mode["device_type"] = int(val_match.group(1))
        elif "NetworkData:" in line:
            val_match = re.search(r"NetworkData:\s*(\d+)", line)
            if val_match:
                mode["network_data"] = int(val_match.group(1))

        # Determine device type based on mode flags
        mode["device"] = device_type_from_mode(mode)

    return mode


def parse_child_table(output, parent_rloc16):
    """Extracts detailed Child Table information from diagnostic output."""
    children = []
    lines = output.split("\n")
    in_child_section = False
    current_child = None

    # Get parent prefix for child rloc16s
    try:
        parent_rloc16_int = int(
            parent_rloc16, 0
        )  # Auto-detect base (handles both 0xNNNN and decimal)
    except (TypeError, ValueError):
        return children

    for i, line in enumerate(lines):
        if "Child Table:" in line:
            in_child_section = True
            continue

        if not in_child_section:
            continue

        # Detect end of Child Table section
        if line.strip() and not line.startswith(" ") and "ChildId" not in line:
            if current_child:
                current_child["mode"]["device"] = device_type_from_mode(
                    current_child["mode"]
                )
                children.append(current_child)
                current_child = None  # Prevent duplicate append after loop
            break

        # Match ChildId
        if "ChildId:" in line:
            if current_child:
                current_child["mode"]["device"] = device_type_from_mode(
                    current_child["mode"]
                )
                children.append(current_child)
            child_id_match = re.search(
                r"ChildId:\s*(0x[0-9a-fA-F]+|\d+)", line)
            child_id = child_id_match.group(1) if child_id_match else "Unknown"

            # Child Rloc16: The 16-bit space is broken down exactly as follows:
            # Bits 15–10 (6 bits): 
            #   Router ID (The identifier of the parent router)
            # Bits 9–0 (10 bits): 
            #   Child ID (The unique index of the child under that parent)
            #
            # Parent Router ID is derived from parent RLOC16 by shifting right 10 bits (dividing by 1024)
            # Child RLOC16 is derived from parent RouterID with: 
            #   Child RLOC16 = (Parent Router ID * 1024) + Child ID

            try:
                parent_router_id = parent_rloc16_int >> 10  # Get parent router ID (top 6 bits)
                child_id_int = int(
                    child_id, 0
                )  # Auto-detect base (handles both 0xNNNN and decimal)
                child_rloc16_int = (parent_router_id << 10) + child_id_int
                child_rloc16 = f"0x{child_rloc16_int:04x}"
            except ValueError:
                child_rloc16 = f"Unknown-{child_id}"

            current_child = {
                "id": child_id,
                "rloc16": child_rloc16,
                "timeout": None,
                "link_quality": None,
                "mode": {},
            }
        elif current_child:
            # Parse Timeout
            if "Timeout:" in line:
                timeout_match = re.search(r"Timeout:\s*(\d+)", line)
                if timeout_match:
                    current_child["timeout"] = int(timeout_match.group(1))
            # Parse Link Quality
            elif "Link Quality:" in line:
                lq_match = re.search(r"Link Quality:\s*(\d+)", line)
                if lq_match:
                    current_child["link_quality"] = int(lq_match.group(1))
            # Parse Mode fields
            elif "RxOnWhenIdle:" in line:
                val_match = re.search(r"RxOnWhenIdle:\s*(\d+)", line)
                if val_match:
                    current_child["mode"]["rx_on_when_idle"] = int(
                        val_match.group(1))
            elif "DeviceType:" in line:
                val_match = re.search(r"DeviceType:\s*(\d+)", line)
                if val_match:
                    current_child["mode"]["device_type"] = int(
                        val_match.group(1))
            elif "NetworkData:" in line:
                val_match = re.search(r"NetworkData:\s*(\d+)", line)
                if val_match:
                    current_child["mode"]["network_data"] = int(
                        val_match.group(1))

    if current_child:
        current_child["mode"]["device"] = device_type_from_mode(
            current_child["mode"]
        )
        children.append(current_child)

    return children


def parse_mac_counter_tokens(output: str) -> dict[str, int]:
    """Extract accepted raw integer values from the MAC Counters section."""
    counters: dict[str, int] = {}
    in_mac_section = False

    for line in output.splitlines():
        if "MAC Counters:" in line:
            in_mac_section = True
            continue
        if not in_mac_section:
            continue

        # End of MAC Counters section
        if line.strip() and not line.startswith(" ") and ":" not in line.split()[0]:
            break
        if line.strip() and not line.startswith(" ") and line.strip() != "":
            if any(x in line for x in ["Counters:", "Errors", "Pkts", "Discards"]):
                break

        if ":" in line and line.startswith(" "):
            parts = line.strip().split(":", 1)
            if len(parts) == 2:
                key = RAW_MAC_COUNTER_FIELDS.get(parts[0].strip())
                if key is None:
                    continue
                try:
                    counters[key] = int(parts[1].strip())
                except ValueError:
                    pass
    return counters

def parse_mac_counters(output: str) -> dict[str, int | float]:
    """Extract raw MAC counters and add derived metrics."""
    counters = parse_mac_counter_tokens(output)
    return enrich_mac_counters(counters) if counters else {}


def parse_mle_counters(output):
    """Extracts MLE Counters from diagnostic output.

    Thread Network MLE Counters

    MLE (Mesh Link Establishment) counters provide insights into the stability and performance of the Thread mesh network.
    High counts of MLE errors or failed attempts can indicate issues with network connectivity, such as interference,
    weak signal strength, or misconfigured devices.

    Common causes include devices:
    - being too far apart, outdated firmware,
    - excessive network congestion.

    Troubleshooting steps involve
    - improving device placement to ensure better signal strength,
    - updating firmware to fix known issues, and
    - rebooting devices to clear any temporary network glitches.

    Example MLE Counters:
        "mle_counters": {
        "disabledrole": 0,
        "detachedrole": 5,
        "childrole": 5,
        "routerrole": 0,
        "leaderrole": 0,
        "attachattempts": 11,
        "partitionidchanges": 1,
        "betterpartitionattachattempts": 0,
        "parentchanges": 4

    """

    counters = {}
    lines = output.split("\n")
    in_mle_section = False

    for line in lines:
        if "MLE Counters:" in line:
            in_mle_section = True
            continue
        if not in_mle_section:
            continue

        # End of MLE Counters section
        if (
            line.strip()
            and not line.startswith(" ")
            and not any(x in line for x in ["Role", "Attempts", "Changes"])
        ):
            if "Counters" not in line and "Time" not in line:
                break

        # Parse counter lines
        if ":" in line and line.startswith(" "):
            parts = line.strip().split(":")
            if len(parts) == 2:
                key = parts[0].strip().lower().replace(" ", "_")
                try:
                    value = int(parts[1].strip())
                    counters[key] = value
                except ValueError:
                    pass

    # Enrich MLE counters with totals
    if counters:
        counters["totalparentpartitionchanges"] = (
            counters.get("parentchanges", 0)
            + counters.get("betterpartitionattachattempts", 0)
            + counters.get("partitionidchanges", 0)
        )

    return counters


def parse_time_statistics(output):
    """Extracts time statistics from diagnostic output."""
    time_stats = {}
    lines = output.split("\n")

    for line in lines:
        if "TrackedTime:" in line:
            match = re.search(r"TrackedTime:\s*(\d+)", line)
            if match:
                time_stats["tracked_time"] = int(match.group(1))
        elif "DisabledTime:" in line:
            match = re.search(r"DisabledTime:\s*(\d+)", line)
            if match:
                time_stats["disabled_time"] = int(match.group(1))
        elif "DetachedTime:" in line:
            match = re.search(r"DetachedTime:\s*(\d+)", line)
            if match:
                time_stats["detached_time"] = int(match.group(1))
        elif "ChildTime:" in line:
            match = re.search(r"ChildTime:\s*(\d+)", line)
            if match:
                time_stats["child_time"] = int(match.group(1))
        elif "RouterTime:" in line:
            match = re.search(r"RouterTime:\s*(\d+)", line)
            if match:
                time_stats["router_time"] = int(match.group(1))
        elif "LeaderTime:" in line:
            match = re.search(r"LeaderTime:\s*(\d+)", line)
            if match:
                time_stats["leader_time"] = int(match.group(1))

    if time_stats:
        tracked_time = time_stats.get("tracked_time", 0)
        if tracked_time > 0:
            # Combine detached and disabled time for overall "non-connected" time
            detached_disabled_time = time_stats.get("detached_time", 0) + time_stats.get("disabled_time", 0)
            time_stats["detached_disabled_time"] = detached_disabled_time

            detached_disabled_time_pct = round((detached_disabled_time / tracked_time) * 100, 1)
            time_stats["detached_disabled_pct"] = detached_disabled_time_pct

            # Calculate percentages for each role time relative to tracked time
            # format the percentages to 1 decimal place when printing
            time_stats["router_pct"] = round(
                (time_stats.get("router_time", 0) / tracked_time) * 100, 1
            )
            time_stats["child_pct"] = round(
                (time_stats.get("child_time", 0) / tracked_time) * 100, 1
            )
            time_stats["leader_pct"] = round(
                (time_stats.get("leader_time", 0) / tracked_time) * 100, 1
            )
            time_stats["disabled_pct"] = round(
                (time_stats.get("disabled_time", 0) / tracked_time) * 100, 1
            )
            time_stats["detached_pct"] = round(
                (time_stats.get("detached_time", 0) / tracked_time) * 100, 1
            )
            time_stats["detached_disabled_pct"] = round(
                (time_stats.get("detached_disabled_time", 0) / tracked_time) * 100, 1
            )

    return time_stats


def parse_eui64(output):
    """Extracts EUI64 hardware address from diagnostic output (TLV 23).
    
    Args:
        output: Raw diagnostic output string
    
    Returns:
        String with 16-char hex EUI64 (e.g., "f434f0fffe1e1774") or None if not found
    """
    match = re.search(r"EUI64:\s*([0-9a-fA-F]{16})", output)
    return match.group(1).lower() if match else None


def parse_connectivity(output):
    """Extracts Connectivity metrics from diagnostic output (TLV 4).
    
    Thread connectivity metrics provide physical state, link quality, parent metrics,
    and routing costs for a device. These values help assess the device's position
    and connectivity quality within the mesh network.
    
    Args:
        output: Raw diagnostic output string
    
    Returns:
        Dictionary with connectivity fields, or empty dict {} if not found:
        {
            "parent_priority": int,
            "link_quality_3": int,
            "link_quality_2": int,
            "link_quality_1": int,
            "leader_cost": int,
            "id_sequence": int,
            "active_routers": int,
            "sed_buffer_size": int,
            "sed_datagram_count": int
        }
    """
    connectivity = {}
    lines = output.split("\n")
    in_connectivity_section = False
    
    for line in lines:
        stripped = line.strip()
        
        # Start of Connectivity section
        if stripped == "Connectivity:":
            in_connectivity_section = True
            continue
        
        if not in_connectivity_section:
            continue
        
        # End connectivity section at next top-level field
        if stripped and not line.startswith(" "):
            break
        
        # Parse connectivity fields
        if "ParentPriority:" in line:
            match = re.search(r"ParentPriority:\s*(\d+)", line)
            if match:
                connectivity["parent_priority"] = int(match.group(1))
        elif "LinkQuality3:" in line:
            match = re.search(r"LinkQuality3:\s*(\d+)", line)
            if match:
                connectivity["link_quality_3"] = int(match.group(1))
        elif "LinkQuality2:" in line:
            match = re.search(r"LinkQuality2:\s*(\d+)", line)
            if match:
                connectivity["link_quality_2"] = int(match.group(1))
        elif "LinkQuality1:" in line:
            match = re.search(r"LinkQuality1:\s*(\d+)", line)
            if match:
                connectivity["link_quality_1"] = int(match.group(1))
        elif "LeaderCost:" in line:
            match = re.search(r"LeaderCost:\s*(\d+)", line)
            if match:
                connectivity["leader_cost"] = int(match.group(1))
        elif "IdSequence:" in line:
            match = re.search(r"IdSequence:\s*(\d+)", line)
            if match:
                connectivity["id_sequence"] = int(match.group(1))
        elif "ActiveRouters:" in line:
            match = re.search(r"ActiveRouters:\s*(\d+)", line)
            if match:
                connectivity["active_routers"] = int(match.group(1))
        elif "SedBufferSize:" in line:
            match = re.search(r"SedBufferSize:\s*(\d+)", line)
            if match:
                connectivity["sed_buffer_size"] = int(match.group(1))
        elif "SedDatagramCount:" in line:
            match = re.search(r"SedDatagramCount:\s*(\d+)", line)
            if match:
                connectivity["sed_datagram_count"] = int(match.group(1))
    
    return connectivity


def parse_leader_data(output):
    """Extracts Leader Data from diagnostic output (TLV 6).
    
    Leader data contains partition and network version information that helps
    identify the network partition and track network data changes.
    
    Args:
        output: Raw diagnostic output string
    
    Returns:
        Dictionary with leader data fields, or empty dict {} if not found:
        {
            "partition_id": str,          # hex string with 0x prefix
            "weighting": int,
            "data_version": int,
            "stable_data_version": int,
            "leader_router_id": str       # hex string with 0x prefix
        }
    """
    leader_data = {}
    lines = output.split("\n")
    in_leader_section = False
    
    for line in lines:
        stripped = line.strip()
        
        # Start of Leader Data section
        if stripped == "Leader Data:":
            in_leader_section = True
            continue
        
        if not in_leader_section:
            continue
        
        # End leader data section at next top-level field
        if stripped and not line.startswith(" "):
            break
        
        # Parse leader data fields
        if "PartitionId:" in line:
            match = re.search(r"PartitionId:\s*(0x[0-9a-fA-F]+)", line)
            if match:
                leader_data["partition_id"] = match.group(1)
        elif "Weighting:" in line:
            match = re.search(r"Weighting:\s*(\d+)", line)
            if match:
                leader_data["weighting"] = int(match.group(1))
        elif "StableDataVersion:" in line:
            match = re.search(r"StableDataVersion:\s*(\d+)", line)
            if match:
                leader_data["stable_data_version"] = int(match.group(1))
        elif "DataVersion:" in line:
            match = re.search(r"DataVersion:\s*(\d+)", line)
            if match:
                leader_data["data_version"] = int(match.group(1))
        elif "LeaderRouterId:" in line:
            match = re.search(r"LeaderRouterId:\s*(0x[0-9a-fA-F]+)", line)
            if match:
                leader_data["leader_router_id"] = match.group(1)
    
    return leader_data


def parse_vendor_name(output):
    """Extracts Vendor Name from diagnostic output (TLV 25).
    
    Args:
        output: Raw diagnostic output string
    
    Returns:
        String with vendor name (e.g., "Apple") or None if empty/missing
    """
    match = re.search(r"Vendor Name:[ \t]*([^\r\n]*)$", output, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None


def parse_vendor_model(output):
    """Extracts Vendor Model from diagnostic output (TLV 26).
    
    Args:
        output: Raw diagnostic output string
    
    Returns:
        String with vendor model (e.g., "Default") or None if empty/missing
    """
    match = re.search(r"Vendor Model:[ \t]*([^\r\n]*)$", output, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None


def parse_vendor_sw_version(output):
    """Extracts Vendor SW Version from diagnostic output (TLV 27).
    
    Args:
        output: Raw diagnostic output string
    
    Returns:
        String with vendor software version (e.g., "Default") or None if empty/missing
    """
    match = re.search(r"Vendor SW Version:[ \t]*([^\r\n]*)$", output, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None


def parse_route_data(output):
    """Extracts Route data from diagnostic output (TLV 5).
    
    Route data contains the routing table with ID sequence tracking and routing costs
    to all Router IDs in the network. This helps understand the routing topology and
    path costs between routers.
    
    Args:
        output: Raw diagnostic output string
    
    Returns:
        Dictionary with route data, or empty dict {} if not found:
        {
            "id_sequence": int,
            "route_data": [
                {
                    "route_id": str,          # hex string with 0x prefix
                    "link_quality_out": int,
                    "link_quality_in": int,
                    "route_cost": int
                },
                ...
            ]
        }
    """
    route = {}
    lines = output.split("\n")
    in_route_section = False
    in_route_data_array = False
    current_route_entry = None
    route_data_list = []
    
    for line in lines:
        stripped = line.strip()
        
        # Start of Route section
        if stripped == "Route:":
            in_route_section = True
            continue
        
        if not in_route_section:
            continue
        
        # End route section at next top-level field (not indented)
        if stripped and not line.startswith(" "):
            # Save any pending route entry
            if current_route_entry:
                route_data_list.append(current_route_entry)
                current_route_entry = None
            break
        
        # Parse IdSequence (top-level field under Route:)
        if "IdSequence:" in line and not in_route_data_array:
            match = re.search(r"IdSequence:\s*(\d+)", line)
            if match:
                route["id_sequence"] = int(match.group(1))
        
        # Start of RouteData array
        elif stripped == "RouteData:":
            in_route_data_array = True
            continue
        
        # Parse RouteData entries
        elif in_route_data_array:
            # New route entry starts with "- RouteId:"
            if "- RouteId:" in line or "RouteId:" in line:
                # Save previous entry if exists
                if current_route_entry:
                    route_data_list.append(current_route_entry)
                
                # Start new entry
                match = re.search(r"RouteId:\s*(0x[0-9a-fA-F]+)", line)
                if match:
                    current_route_entry = {
                        "route_id": match.group(1),
                        "link_quality_out": None,
                        "link_quality_in": None,
                        "route_cost": None
                    }
            
            # Parse fields of current route entry
            elif current_route_entry:
                if "LinkQualityOut:" in line:
                    match = re.search(r"LinkQualityOut:\s*(\d+)", line)
                    if match:
                        current_route_entry["link_quality_out"] = int(match.group(1))
                elif "LinkQualityIn:" in line:
                    match = re.search(r"LinkQualityIn:\s*(\d+)", line)
                    if match:
                        current_route_entry["link_quality_in"] = int(match.group(1))
                elif "RouteCost:" in line:
                    match = re.search(r"RouteCost:\s*(\d+)", line)
                    if match:
                        current_route_entry["route_cost"] = int(match.group(1))
    
    # Save any pending route entry at end of output
    if current_route_entry:
        route_data_list.append(current_route_entry)
    
    # Add route_data array to result if we collected any entries
    if route_data_list:
        route["route_data"] = route_data_list
    
    return route


def parse_diagnostic_tlv_payload(payload_hex: str) -> dict:
    """Parse and validate a complete Network Diagnostic TLV byte stream."""
    if not isinstance(payload_hex, str) or len(payload_hex) % 2 or not re.fullmatch(
        r"[0-9a-fA-F]*", payload_hex
    ):
        return {
            "status": "malformed",
            "error": "malformed-hex",
            "tlvs": [],
            "received_type_ids": [],
        }

    payload = bytes.fromhex(payload_hex)
    tlvs = []
    offset = 0
    while offset < len(payload):
        if len(payload) - offset < 2:
            return {
                "status": "malformed",
                "error": "truncated-header",
                "tlvs": [],
                "received_type_ids": [],
            }

        tlv_type, length = payload[offset], payload[offset + 1]
        offset += 2
        if length == 0xFF:
            if len(payload) - offset < 2:
                return {
                    "status": "malformed",
                    "error": "truncated-extended-length",
                    "tlvs": [],
                    "received_type_ids": [],
                }
            length = int.from_bytes(payload[offset:offset + 2], "big")
            offset += 2

        end = offset + length
        if end > len(payload):
            return {
                "status": "malformed",
                "error": "truncated-value",
                "tlvs": [],
                "received_type_ids": [],
            }

        tlvs.append({"type": tlv_type, "value": payload[offset:end]})
        offset = end

    return {
        "status": "valid",
        "error": None,
        "tlvs": tlvs,
        "received_type_ids": [tlv["type"] for tlv in tlvs],
    }


def decode_diagnostic_tlvs(parsed: dict) -> dict:
    """Validate known TLV value shapes and decode approved scalar values."""
    result = {
        "values": {},
        "malformed_type_ids": [],
        "undecoded_type_ids": [],
        "query_id": None,
        "answer_index": None,
        "is_final_answer": None,
    }
    if parsed.get("status") != "valid":
        return result

    tlvs = parsed.get("tlvs", [])
    counts = {}
    for tlv in tlvs:
        counts[tlv["type"]] = counts.get(tlv["type"], 0) + 1

    for tlv in tlvs:
        tlv_type = tlv["type"]
        value = tlv["value"]
        if tlv_type in SINGLE_VALUE_DIAGNOSTIC_TLV_TYPES and counts[tlv_type] != 1:
            if tlv_type not in result["malformed_type_ids"]:
                result["malformed_type_ids"].append(tlv_type)
            continue

        error = _diagnostic_tlv_value_error(tlv_type, value)
        if error is not None:
            if tlv_type not in result["malformed_type_ids"]:
                result["malformed_type_ids"].append(tlv_type)
            continue

        if tlv_type not in RAW_DIAGNOSTIC_TLV_TYPES:
            if tlv_type not in FORMATTED_DIAGNOSTIC_TLV_TYPES and tlv_type not in result["undecoded_type_ids"]:
                result["undecoded_type_ids"].append(tlv_type)
            continue

        if tlv_type == 0:
            result["values"]["extaddr"] = value.hex()
        elif tlv_type == 1:
            result["values"]["rloc16"] = f"0x{int.from_bytes(value, 'big'):04x}"
        elif tlv_type == 8:
            result["values"]["ipv6_addrs"] = [
                str(ipaddress.IPv6Address(value[offset:offset + 16]))
                for offset in range(0, len(value), 16)
            ]
        elif tlv_type == 23:
            result["values"]["eui64"] = value.hex()
        elif tlv_type == 24:
            version = int.from_bytes(value, "big")
            result["values"]["thread_version_decimal"] = version
            result["values"]["thread_version"] = decode_short_thread_version(version)
        elif tlv_type in DIAGNOSTIC_STRING_TLV_MAX_LENGTHS:
            key = {
                25: "vendor_name",
                26: "vendor_model",
                27: "vendor_sw_version",
                28: "thread_stack_version",
            }[tlv_type]
            try:
                result["values"][key] = value.decode("utf-8")
            except UnicodeDecodeError:
                if tlv_type not in result["malformed_type_ids"]:
                    result["malformed_type_ids"].append(tlv_type)
        elif tlv_type == 32:
            answer = int.from_bytes(value, "big")
            result["answer_index"] = answer & 0x7FFF
            result["is_final_answer"] = bool(answer & 0x8000)
        elif tlv_type == 33:
            result["query_id"] = int.from_bytes(value, "big")

    return result


def _diagnostic_tlv_value_error(tlv_type: int, value: bytes) -> str | None:
    exact_lengths = {
        0: {8},
        1: {2},
        2: {1},
        3: {4},
        6: {8},
        9: {36},
        14: {1},
        15: {2},
        19: {4},
        23: {8},
        24: {2},
        32: {2},
        33: {2},
        34: {66},
    }
    if tlv_type in exact_lengths and len(value) not in exact_lengths[tlv_type]:
        return "invalid-value-length"
    if tlv_type == 4 and len(value) not in (7, 10):
        return "invalid-connectivity-length"
    if tlv_type == 5:
        if len(value) < 9:
            return "truncated-route64"
        allocated_router_count = sum(byte.bit_count() for byte in value[1:9])
        standard_length = 9 + allocated_router_count
        long_routes_length = 9 + (allocated_router_count * 3 + 1) // 2
        if len(value) not in (standard_length, long_routes_length):
            return "invalid-route64-entry-count"
    if tlv_type == 8 and len(value) % 16:
        return "invalid-ipv6-address-list-length"
    if tlv_type == 16 and len(value) % 3:
        return "invalid-child-table-length"
    if tlv_type in DIAGNOSTIC_STRING_TLV_MAX_LENGTHS:
        if len(value) > DIAGNOSTIC_STRING_TLV_MAX_LENGTHS[tlv_type]:
            return "string-too-long"
        try:
            value.decode("utf-8")
        except UnicodeDecodeError:
            return "invalid-utf8"
    return None


def parse_network_diagnostic_response_frames(output: str) -> list[dict]:
    """Split CLI response envelopes in output order without parsing TLV textually."""
    if not isinstance(output, str):
        return []

    frames = []
    current = None

    def finish_frame() -> None:
        if current is not None:
            current["text"] = "\n".join(current.pop("lines"))
            frames.append(current.copy())

    for line in output.splitlines():
        if line.startswith(DIAGNOSTIC_RESPONSE_PREFIX):
            finish_frame()
            header = line[len(DIAGNOSTIC_RESPONSE_PREFIX):]
            match = re.match(r"^(.+):(?:\s+(.*))?$", header)
            current = {
                "response_index": len(frames),
                "responder_ipv6": match.group(1).strip() if match else None,
                "payload_hex": (
                    match.group(2).strip()
                    if match and match.group(2) else None
                ),
                "lines": [line],
            }
        elif current is not None:
            current["lines"].append(line)

    finish_frame()
    return frames


def create_diagnostic_collection_context() -> dict:
    """Create response-correlation state scoped to one collector invocation."""
    return {
        "collection_id": uuid.uuid4().hex,
        "request_attempts": [],
        "sent_request_ids": [],
        "query_origins": {},
        "observations": [],
        "parsed_records": [],
        "response_group_records": {},
    }


def register_diagnostic_request(
    collection_context: dict | None,
    capture_stage: str,
    capture_target: str,
    attempt_index: int,
    requested_tlv_values: str,
    query_target_rloc16: str | None = None,
) -> dict | None:
    if collection_context is None:
        return None
    requested_type_ids = []
    for token in requested_tlv_values.split():
        try:
            requested_type_ids.append(int(token, 10))
        except ValueError:
            return None
    request = {
        "request_id": f"{capture_stage}:{capture_target}:{attempt_index}:{len(collection_context['request_attempts'])}",
        "capture_stage": capture_stage,
        "capture_target": capture_target,
        "attempt_index": attempt_index,
        "requested_type_ids": requested_type_ids,
        "query_target_rloc16": query_target_rloc16,
    }
    collection_context["request_attempts"].append(request)
    return request


def mark_diagnostic_request_sent(
    collection_context: dict | None,
    request: dict | None,
) -> None:
    if collection_context is None or request is None:
        return
    request_id = request.get("request_id")
    if request_id is None:
        return
    sent_request_ids = collection_context.setdefault("sent_request_ids", [])
    if request_id not in sent_request_ids:
        sent_request_ids.append(request_id)


def _attribute_response_observation(
    observation: dict,
    request: dict | None,
    association: str,
) -> None:
    observation["request_association"] = association
    observation["attributed_request_attempt_index"] = (
        request.get("attempt_index") if request else None
    )
    observation["attributed_request"] = (
        {
            "capture_stage": request["capture_stage"],
            "capture_target": request["capture_target"],
            "attempt_index": request["attempt_index"],
            "query_target_rloc16": request.get("query_target_rloc16"),
        }
        if request else None
    )
    requested_types = list(request["requested_type_ids"]) if request else None
    received_types = set(observation.get("received_type_ids", []))
    application_types = received_types - DIAGNOSTIC_TLV_CONTROL_TYPES
    observation["requested_type_ids"] = requested_types
    observation["omitted_type_ids"] = (
        sorted(set(requested_types) - received_types)
        if requested_types is not None else None
    )
    observation["unrequested_type_ids"] = (
        sorted(application_types - set(requested_types))
        if requested_types is not None else None
    )


def build_tlv_response_observation(
    frame: dict | None,
    parsed: dict,
    decoded: dict,
    collection_context: dict,
    request_context: dict | None,
    capture_stage: str,
    capture_target: str,
    capture_attempt_index: int,
    response_index: int | None,
    *,
    no_response: bool = False,
) -> dict:
    responder = frame.get("responder_ipv6") if frame else None
    query_id = decoded.get("query_id")
    attributed_request = None
    association = "uncorrelated"

    if no_response and request_context is not None:
        attributed_request = request_context
        association = "no-response"
    elif (
        query_id is None
        and request_context is not None
        and request_context.get("query_target_rloc16") is not None
        and _request_target_matches_responder(request_context, responder)
    ):
        attributed_request = request_context
        association = "responder-target"
    elif query_id is not None:
        origin_id = collection_context["query_origins"].get(query_id)
        if origin_id is not None:
            attributed_request = next(
                (request for request in collection_context["request_attempts"] if request["request_id"] == origin_id),
                None,
            )
            association = "query-id" if attributed_request else "unknown"
        else:
            received_application_types = set(parsed.get("received_type_ids", [])) - DIAGNOSTIC_TLV_CONTROL_TYPES
            compatible_requests = [
                request
                for request in collection_context["request_attempts"]
                if request["capture_stage"] == capture_stage
                and request["capture_target"] == capture_target
                and request.get("query_target_rloc16") is None
                and request["attempt_index"] <= capture_attempt_index
                and _request_target_matches_responder(request, responder)
                and received_application_types.issubset(set(request["requested_type_ids"]))
            ]
            uniquely_identifying_requests = []
            for request in compatible_requests:
                other_requested = set().union(*(
                    set(other["requested_type_ids"])
                    for other in collection_context["request_attempts"]
                    if other is not request
                    and other["capture_stage"] == capture_stage
                    and other["capture_target"] == capture_target
                )) if len(collection_context["request_attempts"]) > 1 else set()
                if received_application_types & (set(request["requested_type_ids"]) - other_requested):
                    uniquely_identifying_requests.append(request)
            if len(uniquely_identifying_requests) == 1:
                attributed_request = uniquely_identifying_requests[0]
                collection_context["query_origins"][query_id] = attributed_request["request_id"]
                association = "request-set"
            else:
                association = "ambiguous" if compatible_requests else "unknown"
    elif parsed.get("status") == "valid" and 33 in parsed.get("received_type_ids", []):
        association = "unknown"

    received_type_ids = list(parsed.get("received_type_ids", []))
    parse_status = parsed.get("status", "raw-unavailable")
    if parse_status == "valid" and decoded.get("malformed_type_ids"):
        parse_status = "valid-with-malformed-tlvs"
    observation_id = (
        f"{collection_context['collection_id']}:{capture_stage}:{capture_target}:"
        f"{capture_attempt_index}:{response_index if response_index is not None else 'none'}"
    )
    group_id = (
        f"{responder}|query:{query_id:04x}"
        if responder and query_id is not None
        else observation_id
    )
    if query_id is not None and attributed_request is not None:
        for prior_observation in collection_context["observations"]:
            if (
                prior_observation.get("query_id") == query_id
                and prior_observation.get("request_association") in ("unknown", "ambiguous", "uncorrelated")
            ):
                _attribute_response_observation(
                    prior_observation, attributed_request, "query-id"
                )
    observation = {
        "observation_id": observation_id,
        "collection_id": collection_context["collection_id"],
        "capture_sequence": len(collection_context["observations"]),
        "capture_stage": capture_stage,
        "capture_target": capture_target,
        "capture_attempt_index": capture_attempt_index,
        "query_target_rloc16": (
            request_context.get("query_target_rloc16") if request_context else None
        ),
        "response_index": response_index,
        "response_group_id": group_id,
        "responder_ipv6": responder,
        "query_id": query_id,
        "answer_index": decoded.get("answer_index"),
        "final_answer": decoded.get("is_final_answer"),
        "request_association": association,
        "attributed_request_attempt_index": None,
        "attributed_request": None,
        "requested_type_ids": None,
        "received_type_ids": received_type_ids,
        "omitted_type_ids": None,
        "unrequested_type_ids": None,
        "malformed_type_ids": list(decoded.get("malformed_type_ids", [])),
        "undecoded_type_ids": list(decoded.get("undecoded_type_ids", [])),
        "parse_status": "no-response" if no_response else parse_status,
    }
    _attribute_response_observation(observation, attributed_request, association)
    collection_context["observations"].append(observation)
    logging.debug(
        "Network diagnostic response stage=%s target=%s captureAttempt=%s response=%s "
        "requestTypes=%s receivedTypes=%s parseStatus=%s undecodedTypes=%s association=%s",
        capture_stage,
        capture_target,
        capture_attempt_index,
        response_index,
        observation["requested_type_ids"],
        received_type_ids,
        observation["parse_status"],
        observation["undecoded_type_ids"],
        association,
    )
    return observation


def _request_target_matches_responder(request: dict, responder: str | None) -> bool:
    if not responder:
        return False
    try:
        target = ipaddress.IPv6Address(request["capture_target"])
        response_address = ipaddress.IPv6Address(responder)
    except (ipaddress.AddressValueError, TypeError):
        return False
    return target.is_multicast or target == response_address


def _same_ipv6_address(left: object, right: object) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    try:
        return ipaddress.IPv6Address(left) == ipaddress.IPv6Address(right)
    except ipaddress.AddressValueError:
        return False


def _diagnostic_response_group_key(
    responder: str | None,
    query_id: int | None,
) -> str | None:
    if not responder or query_id is None:
        return None
    try:
        canonical_responder = ipaddress.IPv6Address(responder).compressed
    except ipaddress.AddressValueError:
        return None
    return f"{canonical_responder}|{query_id:04x}"


def build_unframed_tlv_response_observation(
    output: str,
    collection_context: dict,
    request_context: dict,
    capture_stage: str,
    capture_target: str,
    capture_attempt_index: int,
) -> dict:
    no_response = (
        not output.strip()
        or output.strip().lower() in {"done", "done."}
        or bool(re.match(r"\s*(?:Error\b|ResponseTimeout\b)", output, re.IGNORECASE))
    )
    empty_parse = {"status": "raw-unavailable", "received_type_ids": []}
    return build_tlv_response_observation(
        None,
        empty_parse,
        {},
        collection_context,
        request_context,
        capture_stage,
        capture_target,
        capture_attempt_index,
        None,
        no_response=no_response,
    )


def _parse_thread_version_tlv(payload_hex: str) -> int | None:
    parsed = parse_diagnostic_tlv_payload(payload_hex)
    if parsed["status"] != "valid":
        return None
    return decode_diagnostic_tlvs(parsed)["values"].get("thread_version_decimal")


def _values_match_raw_and_formatted(field: str, formatted: object, raw: object) -> bool:
    if field in {"extaddr", "eui64"} and isinstance(formatted, str) and isinstance(raw, str):
        return formatted.lower() == raw.lower()
    if field == "rloc16" and isinstance(formatted, str) and isinstance(raw, str):
        return formatted.lower() == raw.lower()
    if field == "ipv6_addrs" and isinstance(formatted, list) and isinstance(raw, list):
        try:
            return [str(ipaddress.IPv6Address(item)) for item in formatted] == [
                str(ipaddress.IPv6Address(item)) for item in raw
            ]
        except ValueError:
            return formatted == raw
    if field in {"thread_stack_version", "vendor_name", "vendor_model", "vendor_sw_version"}:
        return str(formatted).strip() == str(raw).strip()
    return formatted == raw


def _raw_or_formatted_value(
    field: str,
    formatted: object,
    raw_values: dict,
    *,
    formatted_present: bool,
) -> object:
    if field not in raw_values:
        return formatted
    raw = raw_values[field]
    if formatted_present:
        if not _values_match_raw_and_formatted(field, formatted, raw):
            logging.debug(
                "Network diagnostic raw/formatted mismatch field=%s formatted=%r raw=%r; retaining formatted value",
                field,
                formatted,
                raw,
            )
        return formatted
    return raw


def _merge_response_histories(existing: object, incoming: object) -> list:
    histories = []
    positions = {}
    for source in (existing, incoming):
        if not isinstance(source, list):
            continue
        for observation in source:
            if not isinstance(observation, dict):
                continue
            identity = observation.get("observation_id", observation.get("observationId"))
            if identity is not None:
                if identity in positions:
                    histories[positions[identity]] = observation
                    continue
                positions[identity] = len(histories)
            histories.append(observation)
    if histories and all(
        isinstance(item.get("capture_sequence"), int)
        for item in histories
    ):
        histories.sort(key=lambda item: item["capture_sequence"])
    return histories


def parse_multicast_diag_output(
    output: str,
    extaddr_map: dict | None = None,
    *,
    collection_context: dict | None = None,
    request_context: dict | None = None,
    capture_stage: str = "multicast",
    capture_target: str | None = None,
    capture_attempt_index: int | None = None,
) -> dict:
    """
    Parses multicast network diagnostic output containing responses from multiple devices.

    Multicast commands (ot-ctl networkdiagnostic get ff03::1/ff02::1 ...) return a single
    combined output with multiple device responses. Each response begins with:
        DIAG_GET.rsp/ans from <responder-ipv6>: <hex-data>
    Followed by parsed fields (Ext Address, Rloc16, Mode, IP6 Address List, etc.).

    This function splits the output into per-device blocks and parses each using existing
    parse functions (parse_mode_flags, parse_ipv6_address_list, parse_child_table, etc.).

    Args:
        output: Raw multicast diagnostic output string
        extaddr_map: Optional dict mapping extended addresses to device labels

    Returns:
        Dict keyed by extaddr (16-char hex string), with device records as values.
        Each record contains:
        {
            "extaddr": str,               # from TLV 0, used as dict key
            "rloc16": str,                # from TLV 1, e.g. "0x2000"
            "device_label": str,          # from extaddr_map or f"found-{rloc16}"
            "eui64": str,                 # from TLV 23, factory-assigned global ID
            "thread_version_decimal": int,
            "thread_version": str,
            "thread_stack_version": str,  # from TLV 28 or "Unknown"
            "mode": dict,                 # from TLV 2, parse_mode_flags()
            "ipv6_addrs": list,           # from TLV 8, parse_ipv6_address_list()
            "connectivity": dict,         # from TLV 4, link quality and routing metrics
            "leader_data": dict,          # from TLV 6, partition and leader info
            "vendor_name": str,           # from TLV 25, hardware creator name
            "vendor_model": str,          # from TLV 26, product SKU identification
            "vendor_sw_version": str,     # from TLV 27, firmware version
            "route": dict,           # from TLV 5, routing table with costs
            "responder_ipv6": str,        # IPv6 from DIAG_GET.rsp header
            "children": list,             # from TLV 16, parse_child_table()
            "total_children": int,        # count of children
            "mac_counters": dict,         # from TLV 9, parse_mac_counters()
            "mle_counters": dict,         # from TLV 34, parse_mle_counters()
            "time_statistics": dict,      # from parse_time_statistics()
        }
    """
    if extaddr_map is None:
        extaddr_map = {}

    result = {}
    response_groups = {}
    frames = parse_network_diagnostic_response_frames(output)

    for frame in frames:
        block = frame["text"]
        raw_parse = (
            parse_diagnostic_tlv_payload(frame["payload_hex"])
            if frame["payload_hex"] is not None
            else {"status": "raw-unavailable", "error": None, "tlvs": [], "received_type_ids": []}
        )
        decoded = decode_diagnostic_tlvs(raw_parse)
        raw_values = decoded["values"]
        responder = frame.get("responder_ipv6")
        query_id = decoded.get("query_id")
        response_group_key = _diagnostic_response_group_key(responder, query_id)
        prior_group_record = (
            collection_context.get("response_group_records", {}).get(response_group_key)
            if collection_context is not None and response_group_key is not None
            else None
        )
        if prior_group_record is None and response_group_key is not None:
            prior_group_record = response_groups.get(response_group_key)
        observation = None
        if collection_context is not None and request_context is not None:
            observation = build_tlv_response_observation(
                frame,
                raw_parse,
                decoded,
                collection_context,
                request_context,
                capture_stage,
                capture_target or request_context["capture_target"],
                capture_attempt_index if capture_attempt_index is not None else request_context["attempt_index"],
                frame["response_index"],
            )

        extaddr_match = re.search(r"Ext Address:\s*([0-9a-fA-F]{16})", block)
        formatted_extaddr = extaddr_match.group(1).lower() if extaddr_match else None
        extaddr = _raw_or_formatted_value(
            "extaddr", formatted_extaddr, raw_values,
            formatted_present=formatted_extaddr is not None,
        )
        if extaddr is None and isinstance(prior_group_record, dict):
            extaddr = prior_group_record.get("extaddr")
        if not isinstance(extaddr, str) or not re.fullmatch(r"[0-9a-f]{16}", extaddr):
            continuation_candidates = []
            responder = frame.get("responder_ipv6")
            query_id = decoded.get("query_id")
            if responder and query_id is not None:
                for prior_extaddr, prior_record in result.items():
                    if not _values_match_raw_and_formatted(
                        "responder_ipv6",
                        prior_record.get("responder_ipv6"),
                        responder,
                    ):
                        continue
                    prior_history = prior_record.get("tlv_response_history", [])
                    if any(
                        isinstance(item, dict) and item.get("query_id") == query_id
                        for item in prior_history
                    ):
                        continuation_candidates.append(prior_extaddr)
            if len(continuation_candidates) == 1:
                extaddr = continuation_candidates[0]
        if not isinstance(extaddr, str) or not re.fullmatch(r"[0-9a-f]{16}", extaddr):
            logging.warning("Malformed multicast response block without a usable Ext Address")
            continue

        rloc16_match = re.search(r"Rloc16:\s*(0x[0-9a-fA-F]{4})", block)
        formatted_rloc16 = rloc16_match.group(1).lower() if rloc16_match else None
        rloc16 = _raw_or_formatted_value(
            "rloc16", formatted_rloc16, raw_values,
            formatted_present=formatted_rloc16 is not None,
        ) or "Unknown"
        if rloc16 == "Unknown" and isinstance(prior_group_record, dict):
            rloc16 = prior_group_record.get("rloc16", "Unknown")

        stack_match = re.search(r"Thread Stack Version:\s*([^\r\n]*)", block)
        formatted_stack = stack_match.group(1).strip() if stack_match else None
        thread_stack_version = _raw_or_formatted_value(
            "thread_stack_version", formatted_stack, raw_values,
            formatted_present=formatted_stack is not None,
        )
        if thread_stack_version is None:
            thread_stack_version = "Unknown"

        device_label = extaddr_map.get(extaddr, f"found-{rloc16}")
        mode = parse_mode_flags(block)
        ipv6_addrs = parse_ipv6_address_list(block)
        eui64 = parse_eui64(block)
        connectivity = parse_connectivity(block)
        leader_data = parse_leader_data(block)
        vendor_name = parse_vendor_name(block)
        vendor_model = parse_vendor_model(block)
        vendor_sw_version = parse_vendor_sw_version(block)
        route = parse_route_data(block)
        children = parse_child_table(block, rloc16)
        mac_counters = parse_mac_counters(block)
        mle_counters = parse_mle_counters(block)
        time_statistics = parse_time_statistics(block)

        ipv6_addrs = _raw_or_formatted_value(
            "ipv6_addrs", ipv6_addrs, raw_values,
            formatted_present="IP6 Address List:" in block,
        )
        eui64 = _raw_or_formatted_value(
            "eui64", eui64, raw_values, formatted_present=eui64 is not None,
        )
        vendor_name = _raw_or_formatted_value(
            "vendor_name", vendor_name, raw_values,
            formatted_present=vendor_name is not None,
        )
        vendor_model = _raw_or_formatted_value(
            "vendor_model", vendor_model, raw_values,
            formatted_present=vendor_model is not None,
        )
        vendor_sw_version = _raw_or_formatted_value(
            "vendor_sw_version", vendor_sw_version, raw_values,
            formatted_present=vendor_sw_version is not None,
        )

        device_record = {
            "extaddr": extaddr,
            "rloc16": rloc16,
            "device_label": device_label,
            "eui64": eui64,
            "thread_stack_version": thread_stack_version,
            "mode": mode,
            "ipv6_addrs": ipv6_addrs,
            "connectivity": connectivity,
            "leader_data": leader_data,
            "vendor_name": vendor_name,
            "vendor_model": vendor_model,
            "vendor_sw_version": vendor_sw_version,
            "route": route,
            "responder_ipv6": frame["responder_ipv6"] or "",
            "children": children,
            "total_children": len(children),
            "mac_counters": mac_counters,
            "mle_counters": mle_counters,
            "time_statistics": time_statistics,
        }
        if "thread_version_decimal" in raw_values:
            device_record["thread_version_decimal"] = raw_values["thread_version_decimal"]
            device_record["thread_version"] = raw_values["thread_version"]
        if observation is not None:
            device_record["tlv_response_history"] = [observation]

        previous = result.get(extaddr)
        if not isinstance(previous, dict) and isinstance(prior_group_record, dict):
            previous = prior_group_record
        if isinstance(previous, dict):
            from otbr_cli_networkdiag_util import reconcile_device_record

            merged_record = reconcile_device_record(
                deepcopy(previous), device_record
            )
            current_responder_history = (
                [
                    item
                    for item in collection_context.get("observations", [])
                    if isinstance(item, dict)
                    and _same_ipv6_address(item.get("responder_ipv6"), responder)
                ]
                if collection_context is not None
                else device_record.get("tlv_response_history", [])
            )
            histories = _merge_response_histories(
                merged_record.get("tlv_response_history"),
                current_responder_history,
            )
            if histories:
                merged_record["tlv_response_history"] = histories
            result[extaddr] = merged_record
        else:
            result[extaddr] = device_record
        if collection_context is not None and response_group_key is not None:
            collection_context.setdefault("response_group_records", {})[
                response_group_key
            ] = deepcopy(result[extaddr])
        if response_group_key is not None:
            response_groups[response_group_key] = deepcopy(result[extaddr])

    logging.info(f"Parsed {len(result)} unique devices from output")
    return result

