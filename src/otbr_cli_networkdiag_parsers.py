"""Parser functions for Thread network diagnostic output.

Each function receives the raw text output from ot-ctl networkdiagnostic get
and extracts a specific TLV field, returning a structured dict or value.
"""
import re
import logging
from collections.abc import Mapping

from otbr_cli_networkdiag_util import device_type_from_mode
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
    parent_rloc16_int = int(
        parent_rloc16, 0
    )  # Auto-detect base (handles both 0xNNNN and decimal)

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
        vendor_name = match.group(1).strip()
        return vendor_name if vendor_name else None
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
        vendor_model = match.group(1).strip()
        return vendor_model if vendor_model else None
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
        vendor_sw_version = match.group(1).strip()
        return vendor_sw_version if vendor_sw_version else None
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


def parse_multicast_diag_output(output: str, extaddr_map: dict | None = None) -> dict:
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
            "device_label": str,          # from extaddr_map or f"Unknown-{rloc16}"
            "eui64": str,                 # from TLV 23, factory-assigned global ID
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

    # Split output by response marker, discarding the first element (preamble)
    blocks = output.split("DIAG_GET.rsp/ans from ")
    blocks = blocks[1:]  # Discard preamble

    for block in blocks:
        if not block.strip():
            continue

        # Split on first newline to extract responder IPv6
        lines = block.split("\n", 1)
        if not lines:
            continue

        # Extract responder IPv6 from first line (format: "<ipv6>: <hex-data>")
        first_line = lines[0]
        responder_ipv6 = ""
        if ": " in first_line:
            responder_ipv6 = first_line.split(": ")[0].strip()

        # Extract Ext Address (TLV 0) - required field
        extaddr_match = re.search(r"Ext Address:\s*([0-9a-fA-F]{16})", block)
        if not extaddr_match:
            logging.warning(
                f"Malformed multicast response block (no Ext Address): {block[:100]}...")
            continue

        extaddr = extaddr_match.group(1).lower()

        # Extract Rloc16 (TLV 1)
        rloc16_match = re.search(r"Rloc16:\s*(0x[0-9a-fA-F]{4})", block)
        rloc16 = rloc16_match.group(1) if rloc16_match else "Unknown"

        # Extract Thread Stack Version (TLV 28)
        thread_version_match = re.search(
            r"Thread Stack Version:\s*(.+?)(?:\n|$)", block)
        thread_stack_version = thread_version_match.group(
            1).strip() if thread_version_match else "Unknown"

        # Resolve device label from extaddr_map
        device_label = extaddr_map.get(extaddr, f"Unknown-{rloc16}")

        # Parse mode flags and IPv6 addresses (always present in request)
        mode = parse_mode_flags(block)
        ipv6_addrs = parse_ipv6_address_list(block)

        # Parse optional TLV data (may be present depending on response)
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

        # Build device record
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
            "responder_ipv6": responder_ipv6,
            "children": children,
            "total_children": len(children),
            "mac_counters": mac_counters,
            "mle_counters": mle_counters,
            "time_statistics": time_statistics,
        }

        # Store in result dict, keyed by extaddr (last duplicate wins for now)
        result[extaddr] = device_record

    logging.info(f"Parsed {len(result)} unique devices from multicast output")
    return result


