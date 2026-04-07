import os
import subprocess
import re
import json
import sys
import time

from copy import deepcopy
import td_util_ot_ctl
import td_util_network
from td_get_otbr_cli_router_table import get_router_table_data
from td_parse_extaddr_data_map import parse_extaddr_nodename_mapping

# from td_util_network import (
#     get_prefix_meshlocal,
#     get_network_dataset_info,
#     format_prefix_meshlocal_into_ipv6adrr_prefix,
#     conform_rloc_hex_strip,
#     merge_ipv6_rloc_prefix_rloc_hex,
#     get_omr_addr_from_list
# )

def get_ipv6_addresses():
    """
    Queries Thread network for IPv6 addresses of all routers.
    Runs: ot-ctl meshdiag topology ip6-addrs
    Returns a dictionary mapping RLOC16 to IPv6 addresses.
    """
    output = td_util_ot_ctl.run_ot_ctl_stdio("meshdiag topology ip6-addrs")
    print(f"[DEBUG] Output of 'meshdiag topology ip6-addrs':\n{output}\n")

    ipv6_map = {}
    
    # Parse output to extract RLOC16 and IPv6 address pairs
    # Expected format: "RLOC:0x5000 => ffxx::0200:x:x:x" or similar
    lines = output.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Match patterns like "RLOC16: 0x5000" or "RLOC: 0x5000" followed by IPv6
        rloc_match = re.search(r'0x[0-9a-fA-F]{4}', line)
        
        # Match IPv6 addresses (simplified pattern)
        ipv6_match = re.search(r'([0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F]{0,4}', line)
        
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
    lines = output.split('\n')
    in_ipv6_section = False
    for line in lines:
        if 'IP6 Address List:' in line:
            in_ipv6_section = True
            continue
        if in_ipv6_section:
            if line.strip().startswith('- '):
                ipv6_addr = line.strip().lstrip('- ')
                ipv6_list.append(ipv6_addr)
            # Check for end of IPv6 section (next section header)
            elif line.strip() and (line.strip().startswith('ChildId:') or 
                                   line.strip().startswith('Child Table:') or
                                   line.strip().startswith('MAC Counters:') or
                                   line.strip().startswith('MLE Counters:') or
                                   ('Ext Address:' in line and 'Rloc16:' not in line)):
                # End of IP6 list section
                break
            elif not line.strip():
                # Empty line might also indicate section boundary
                continue
    return ipv6_list

## TLV 2: Mode TLV to get more detailed info about the node's capabilities and role (e.g., if it's a sleepy end device, router-eligible end device, or full router) which can help better understand the topology and identify potential issues with devices that are not behaving as expected. This will also help enrich the topology map with more detailed information about each node's role and capabilities in the network.

def determine_device_type_from_mode(mode):
    """Returns device classification from Thread mode flags."""
    if (
        mode.get('rx_on_when_idle') == 1
        and mode.get('device_type') == 1
        and mode.get('network_data') == 1
    ):
        return "FTD"
    if (
        mode.get('rx_on_when_idle') == 0
        and mode.get('device_type') == 0
        and mode.get('network_data') == 0
    ):
        return "MTD"
    return "Unknown"

def parse_mode_flags(output):
    """Extracts top-level TLV 2 Mode flags from diagnostic output."""
    mode = {}
    lines = output.split('\n')
    in_mode_section = False

    for line in lines:
        stripped = line.strip()

        # Top-level "Mode:" line (child mode blocks are indented)
        if stripped == 'Mode:' and not line.startswith(' '):
            in_mode_section = True
            continue

        if not in_mode_section:
            continue

        # End mode section at next top-level field
        if stripped and not line.startswith(' '):
            break

        if 'RxOnWhenIdle:' in line:
            val_match = re.search(r'RxOnWhenIdle:\s*(\d+)', line)
            if val_match:
                mode['rx_on_when_idle'] = int(val_match.group(1))
        elif 'DeviceType:' in line:
            val_match = re.search(r'DeviceType:\s*(\d+)', line)
            if val_match:
                mode['device_type'] = int(val_match.group(1))
        elif 'NetworkData:' in line:
            val_match = re.search(r'NetworkData:\s*(\d+)', line)
            if val_match:
                mode['network_data'] = int(val_match.group(1))

        # Determine device type based on mode flags
        mode["device"] = determine_device_type_from_mode(mode)

    return mode

def parse_child_table(output, parent_rloc16):
    """Extracts detailed Child Table information from diagnostic output."""
    children = []
    lines = output.split('\n')
    in_child_section = False
    current_child = None
    
    # Get parent prefix for child rloc16s    
    parent_rloc16_int = int(parent_rloc16, 0)  # Auto-detect base (handles both 0xNNNN and decimal)
    
    for i, line in enumerate(lines):
        if 'Child Table:' in line:
            in_child_section = True
            continue
        
        if not in_child_section:
            continue
            
        # Detect end of Child Table section
        if line.strip() and not line.startswith(' ') and 'ChildId' not in line:
            if current_child:
                current_child["mode"]["device"] = determine_device_type_from_mode(current_child["mode"])
                children.append(current_child)
            break
        
        # Match ChildId
        if 'ChildId:' in line:
            if current_child:
                current_child["mode"]["device"] = determine_device_type_from_mode(current_child["mode"])
                children.append(current_child)
            child_id_match = re.search(r'ChildId:\s*(0x[0-9a-fA-F]+|\d+)', line)
            child_id = child_id_match.group(1) if child_id_match else "Unknown"

            # Child RLOC16 is derived from parent RLOC16 by replacing the last byte with the ChildId (0-255)
            # For example, if parent RLOC16 is 0x0400 and ChildId is 0x0006, child RLOC16 would be 0x0406
            try:
                child_id_int = int(child_id, 0)  # Auto-detect base (handles both 0xNNNN and decimal)
                child_rloc16_int = (parent_rloc16_int & 0xFF00) | (child_id_int & 0x00FF)
                child_rloc16 = f"0x{child_rloc16_int:04x}"
            except ValueError:
                child_rloc16 = f"Unknown-{child_id}"
            
            current_child = {
                "id": child_id,
                "rloc16": child_rloc16,
                "timeout": None,
                "link_quality": None,
                "mode": {}
            }
        elif current_child:
            # Parse Timeout
            if 'Timeout:' in line:
                timeout_match = re.search(r'Timeout:\s*(\d+)', line)
                if timeout_match:
                    current_child["timeout"] = int(timeout_match.group(1))
            # Parse Link Quality
            elif 'Link Quality:' in line:
                lq_match = re.search(r'Link Quality:\s*(\d+)', line)
                if lq_match:
                    current_child["link_quality"] = int(lq_match.group(1))
            # Parse Mode fields
            elif 'RxOnWhenIdle:' in line:
                val_match = re.search(r'RxOnWhenIdle:\s*(\d+)', line)
                if val_match:
                    current_child["mode"]["rx_on_when_idle"] = int(val_match.group(1))
            elif 'DeviceType:' in line:
                val_match = re.search(r'DeviceType:\s*(\d+)', line)
                if val_match:
                    current_child["mode"]["device_type"] = int(val_match.group(1))
            elif 'NetworkData:' in line:
                val_match = re.search(r'NetworkData:\s*(\d+)', line)
                if val_match:
                    current_child["mode"]["network_data"] = int(val_match.group(1))
    
    if current_child:
        current_child["mode"]["device"] = determine_device_type_from_mode(current_child["mode"])
        children.append(current_child)
    
    return children

def parse_mac_counters(output):
    """Extracts MAC Counters from diagnostic output.

    Thread network MAC counters track packet-level performance, where high errors indicate radio 
    interference or weak signal strength, and high discards often signal network congestion or 
    inadequate buffer space. Common causes include improperly placed Border Routers, interference 
    with 2.4GHz Wi-Fi, or outdated firmware, requiring node reboots or improved mesh topology

    Troubleshooting Steps:
    -Improve Topology: Ensure Thread Border Routers are well-spaced and not directly next to Wi-Fi 
     routers to minimize interference.
    -Reboot Devices: Cycle power on unresponsive accessories (turn off/on) to clear hung buffers 
     and force reconnection.
    -Check Signal: If a device has high discard counts, it may be too far from its neighbors in 
     the mesh, requiring a repeater or closer proximity to a border router

    Example MAC Counters:
        "mac_counters": {
            "ifinunknownprotos": 0,
            "ifinerrors": 2654,
            "ifouterrors": 175,
            "ifinucastpkts": 1019,
            "ifinbroadcastpkts": 32654,
            "ifindiscards": 17,
            "ifoutucastpkts": 2235,
            "ifoutbroadcastpkts": 243,
            "ifoutdiscards": 0
        }

    """

    counters = {}
    lines = output.split('\n')
    in_mac_section = False
    
    for line in lines:
        if 'MAC Counters:' in line:
            in_mac_section = True
            continue
        if not in_mac_section:
            continue
        
        # End of MAC Counters section
        if line.strip() and not line.startswith(' ') and ':' not in line.split()[0]:
            break
        if line.strip() and not line.startswith(' ') and line.strip() != '':
            if any(x in line for x in ['Counters:', 'Errors', 'Pkts', 'Discards']):
                break
        
        # Parse counter lines like "IfInUnknownProtos: 0"
        if ':' in line and line.startswith(' '):
            parts = line.strip().split(':')
            if len(parts) == 2:
                key = parts[0].strip().lower().replace(' ', '_')
                try:
                    value = int(parts[1].strip())
                    counters[key] = value
                except ValueError:
                    pass
    
    ## Enhance MAC counters with totals
    if counters:
        counters["iftotalpkts"] = counters.get("ifinucastpkts", 0) + counters.get("ifinbroadcastpkts", 0) + counters.get("ifoutucastpkts", 0) + counters.get("ifoutbroadcastpkts", 0)
        counters["iftotalerrors"] = counters.get("ifinerrors", 0) + counters.get("ifouterrors", 0)
        counters["iftotaldiscards"] = counters.get("ifindiscards", 0) + counters.get("ifoutdiscards", 0)
        counters["iftotalpktserrorsdiscards"] =  counters["iftotalerrors"] + counters["iftotaldiscards"]

        # errors are from malformed packets, interference, or weak signal strength causing corruption during 
        # transmission, while discards typically indicate congestion or buffer overflows where packets are 
        # dropped due to lack of resources to process them. By calculating the total packets, errors, and 
        # discards, we can get a clearer picture of the overall health and performance of the network at 
        # the MAC layer. High error counts relative to total packets may indicate issues with signal quality 
        # or interference, while high discard counts may point to congestion or insufficient buffering 
        # capacity in the network.
        #
        # discards can also occur when a device is overwhelmed with more traffic than it can handle, which 
        # may be the case in a dense network or if a device has limited resources. By looking at the total 
        # packets in relation to errors and discards, we can better understand whether high error/discard 
        # counts are significant issues that need to be addressed or if they are just a small fraction of 
        # the overall traffic and may not be as concerning.

        # Calculate percentages for each counter relative to iftotalpkts
        # Help determine if high error/discard counts are significant relative to total traffic or just a small fraction.
        # format the perentages to 1 decimal place when printing
        total_pkts = counters.get("iftotalpkts", 0)
        if total_pkts > 0:
            counters["iftotalpktserrorsdiscards_pct"] = round((counters.get("iftotalpktserrorsdiscards", 0) / total_pkts) * 100, 1)
            counters["iftotalerrors_pct"] = round((counters.get("iftotalerrors", 0) / total_pkts) * 100, 1)
            counters["iftotaldiscards_pct"] = round((counters.get("iftotaldiscards", 0) / total_pkts) * 100, 1)
            counters["ifinerrors_pct"] = round((counters.get("ifinerrors", 0) / total_pkts) * 100, 1)
            counters["ifouterrors_pct"] = round((counters.get("ifouterrors", 0) / total_pkts) * 100, 1)
            counters["ifindiscards_pct"] = round((counters.get("ifindiscards", 0) / total_pkts) * 100, 1)
            counters["ifoutdiscards_pct"] = round((counters.get("ifoutdiscards", 0) / total_pkts) * 100, 1)
    
    return counters

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
    lines = output.split('\n')
    in_mle_section = False
    
    for line in lines:
        if 'MLE Counters:' in line:
            in_mle_section = True
            continue
        if not in_mle_section:
            continue
        
        # End of MLE Counters section
        if line.strip() and not line.startswith(' ') and not any(x in line for x in ['Role', 'Attempts', 'Changes']):
            if 'Counters' not in line and 'Time' not in line:
                break
        
        # Parse counter lines
        if ':' in line and line.startswith(' '):
            parts = line.strip().split(':')
            if len(parts) == 2:
                key = parts[0].strip().lower().replace(' ', '_')
                try:
                    value = int(parts[1].strip())
                    counters[key] = value
                except ValueError:
                    pass
    
    ## Enhance MLE counters with totals
    if counters:
        counters["totalparentpartitionchanges"] = counters.get("parentchanges", 0) + counters.get("betterpartitionattachattempts", 0) + counters.get("partitionidchanges", 0) 

    return counters

def parse_time_statistics(output):
    """Extracts time statistics from diagnostic output."""
    time_stats = {}
    lines = output.split('\n')
    
    for line in lines:
        if 'TrackedTime:' in line:
            match = re.search(r'TrackedTime:\s*(\d+)', line)
            if match:
                time_stats['tracked_time'] = int(match.group(1))
        elif 'DisabledTime:' in line:
            match = re.search(r'DisabledTime:\s*(\d+)', line)
            if match:
                time_stats['disabled_time'] = int(match.group(1))
        elif 'DetachedTime:' in line:
            match = re.search(r'DetachedTime:\s*(\d+)', line)
            if match:
                time_stats['detached_time'] = int(match.group(1))
        elif 'ChildTime:' in line:
            match = re.search(r'ChildTime:\s*(\d+)', line)
            if match:
                time_stats['child_time'] = int(match.group(1))
        elif 'RouterTime:' in line:
            match = re.search(r'RouterTime:\s*(\d+)', line)
            if match:
                time_stats['router_time'] = int(match.group(1))
        elif 'LeaderTime:' in line:
            match = re.search(r'LeaderTime:\s*(\d+)', line)
            if match:
                time_stats['leader_time'] = int(match.group(1))
    
    if time_stats:
        tracked_time = time_stats.get('tracked_time', 0)
        if tracked_time > 0:
            # Combine detached and disabled time for overall "non-connected" time
            time_stats['detached_disabled_time'] = time_stats.get('detached_time', 0) + time_stats.get('disabled_time', 0)

            # Calculate percentages for each role time relative to tracked time
            # format the perentages to 1 decimal place when printing
            time_stats['router_pct'] = round((time_stats.get('router_time', 0) / tracked_time) * 100, 1)
            time_stats['child_pct'] = round((time_stats.get('child_time', 0) / tracked_time) * 100, 1)
            time_stats['leader_pct'] = round((time_stats.get('leader_time', 0) / tracked_time) * 100, 1)
            time_stats['disabled_pct'] = round((time_stats.get('disabled_time', 0) / tracked_time) * 100, 1)
            time_stats['detached_pct'] = round((time_stats.get('detached_time', 0) / tracked_time) * 100, 1)
            time_stats['detached_disabled_pct'] = round((time_stats.get('detached_disabled_time', 0) / tracked_time) * 100, 1)

    return time_stats

def get_networkdiagnostic_one(rloc, ipv6_rloc_prefix, extaddr_map=None, ipv6_addresses=None, tlv_detail_level=3):
    """
    Queries and parses network diagnostic data for a single router.
    
    Args:
        rloc: RLOC16 value for the router (e.g., "0x0400")
        ipv6_rloc_prefix: IPv6 prefix for building RLOC IPv6 address
        extaddr_map: Dictionary mapping extended addresses to node names
        ipv6_addresses: Dictionary of IPv6 addresses by RLOC
        
    Returns:
        Dictionary containing parsed diagnostic data for the router, or None if extaddr is not found
    """
    if extaddr_map is None:
        extaddr_map = {}
    if ipv6_addresses is None:
        ipv6_addresses = {}
        
    rloc_hex = td_util_network.conform_rloc_hex_strip(rloc)
    ipv6_rloc_addr = td_util_network.merge_ipv6_rloc_prefix_rloc_hex(ipv6_rloc_prefix, rloc_hex)

    tlv_values_detailed = "0 1 2 28 8 16 9 34"
    tlv_values_medium = "0 1 2 8 16 9"
    tlv_values_simple = "0 1 2 8"

    #tlv_values = tlv_values_detailed if tlv_detail_level == 3 else tlv_values_medium if tlv_detail_level == 2 else tlv_values_simple
    match tlv_detail_level:
        case 3:
            tlv_values = tlv_values_detailed
        case 2:
            tlv_values = tlv_values_medium
        case 1:
            tlv_values = tlv_values_simple
        case _:
            tlv_values = tlv_values_detailed
    
    # Query each router for its TLV fields: Ext Addr, RLOC16, Thread Stack Version, 
    # IPv6 Address List, Child Table, MAC Counters, MLE Counters
    # TLV 0 = Ext Address, TLV 1 = RLOC16, 
    # TLV 28 = Thread Stack Version, 
    # TLV 8 = IPv6 Address List, 
    # TLV 16 = Child Table, 
    # TLV 9 = MAC Counters, TLV 34 = MLE Counters
    
    output = td_util_ot_ctl.run_ot_ctl_stdio(f"networkdiagnostic get {ipv6_rloc_addr} {tlv_values}")
    print(f"[DEBUG] Diagnostic for RLOC {rloc} (IPv6: {ipv6_rloc_addr}):\n{output}\n")

    # Extract Ext Address (TLV 0)
    extaddr_match = re.search(r"Ext Address: ([0-9a-fA-F]{16})", output)
    
    # If extaddr is not found, return None (caller will handle with default values)
    if not extaddr_match:
        return None
    
    # Try resolve device_label from extaddr_map, if not found use "Unknown-{rloc}"
    device_label = extaddr_map.get(extaddr_match.group(1))
    if not device_label:
        device_label = f"Unknown-{rloc}"
                                                              
    # Extract Rloc16 (TLV 1)
    rloc16 = re.search(r"Rloc16: (0x[0-9a-fA-F]{4})", output)
    
    # Extract Thread Stack Version (TLV 28)
    thread_version = re.search(r"Thread Stack Version: (.+?)(?:\n|$)", output)
    
    # Parse detailed structures
    mode_flags = parse_mode_flags(output)
    ipv6_list = parse_ipv6_address_list(output)
    children = parse_child_table(output, rloc)
    mac_counters = parse_mac_counters(output)
    mle_counters = parse_mle_counters(output)
    time_stats = parse_time_statistics(output)

    network_topology_node = {
        "extaddr": extaddr_match.group(1) if extaddr_match else "Unknown",
        "rloc16": rloc16.group(1) if rloc16 else rloc,
        "device_label": device_label,
        "thread_stack_version": thread_version.group(1).strip() if thread_version else "Unknown",
        "mode": mode_flags,
        "ipv6_addrs": ipv6_list if ipv6_list else ipv6_addresses.get(rloc, []),
        "children": children,
        "mac_counters": mac_counters,
        "mle_counters": mle_counters,
        "time_statistics": time_stats
    }
    
    return network_topology_node

def get_networkdiagnostic_topology_data(extaddr_map=None, network_dataset_info=None):
    """Maps the full network topology and returns a Python dictionary."""
    
    omr_ipv6addr_prefix = network_dataset_info["prefix_omr_ipv6addr_prefix"] if network_dataset_info and "prefix_omr_ipv6addr_prefix" in network_dataset_info else None 

    # Set to True to also query and include child nodes in the topology map (will increase runtime significantly)
    # Set to False to only get parent nodes without expanding children

    expand_children = True  
    #expand_children = False  

    # 1. Get mesh-local prefix
    meshlocal_prefix = td_util_network.get_prefix_meshlocal()
    ipv6_rloc_prefix = td_util_network.format_prefix_meshlocal_into_ipv6adrr_prefix(meshlocal_prefix)

    # 2. Get all active routers (potential parents)
    router_table_data = get_router_table_data(extaddr_map)
    router_rlocs = [router.get('rloc16') for router in router_table_data if router.get('rloc16')]
    
    # 3. Get IPv6 addresses for all routers
    ## need this if nodes don't reponse to networkdiagnostic get with TLV 8 for IPv6 address list, then we can at least populate the topology map with known IPv6 addresses for each RLOC16 from this separate query. This way we can still have some reference to IPv6 addresses in the topology even if some nodes don't respond to the full diagnostic query.
    ipv6_addresses = get_ipv6_addresses()
    ipv6_addresses = ipv6_addresses if ipv6_addresses else {}  # Ensure it's a dict even if empty
    ##ipv6_addresses = {}

    network_topology_map = {}

    ## TODO refactor to loop through router_table_data instead of just RLOC16s so we can get more info about each router in the first loop and then enrich with diagnostics data in the second loop. This way we can also handle cases where RLOC16 might be missing or unknown in diagnostics output but we have it from router table.
    ## Inner loop also handles children and build a more complete topology map with parent-child relationships instead of just a flat map of RLOC16 to data. This way we can represent the full tree structure of the network instead of just a list of nodes.
    ## TODO refactor inner for loop in a new function that takes a router entry from router_table_data and enriches it with diagnostics data, then adds it to the topology map. This way we can keep the main function cleaner and separate concerns better.    
    
    for rloc16 in router_rlocs:
        # add retry logic for networkdiagnostic get in case of transient errors or unresponsive nodes, retry N times with some delay before giving up and adding with default values
        retries = 3 # number of retries
        delay = 1  # seconds
        network_topology_node = None

        tlv_detail_level = 3
        for r in range(retries):
            # On last retries, try with simpler TLV set in case detailed one is causing issues
            if r == retries - 2:
                tlv_detail_level = 2
                print(f"[DEBUG] Router Node {rloc16} not found after {r} attempts, trying with medium detail TLV set.")   

            if r == retries - 1:
                tlv_detail_level = 1
                print(f"[DEBUG] Router Node {rloc16} not found after {r} attempts, trying with simple values.")

            network_topology_node = get_networkdiagnostic_one(rloc16, ipv6_rloc_prefix, extaddr_map, ipv6_addresses, tlv_detail_level)
            if network_topology_node is not None:
                break
            print (f"[DEBUG] Router Node {rloc16} not found, retrying in {delay} seconds...")
            time.sleep(delay)
        
        if network_topology_node is None:
            # extaddr not found, use default values
            network_topology_map[rloc16] = {
                "extaddr": f"Unknown-{rloc16}",
                "rloc16": rloc16,
                "device_label": f"Unknown-{rloc16}",
                "thread_stack_version": "Unknown",
                "mode": {},
                "ipv6_addrs": ipv6_addresses.get(rloc16, []),
                "omrIpv6Address": td_util_network.get_omr_addr_from_list(ipv6_addresses.get(rloc16, []), omr_ipv6addr_prefix) if omr_ipv6addr_prefix else None,
                "children": [],
                "type": "Unknown-Router",
                "mac_counters": {},
                "mle_counters": {},
                "time_statistics": {}
            }
        else:
            network_topology_node['type'] = 'Router'
            if omr_ipv6addr_prefix:
                network_topology_node["omrIpv6Address"] = td_util_network.get_omr_addr_from_list(network_topology_node.get("ipv6_addrs", []), omr_ipv6addr_prefix)
            network_topology_map[rloc16] = network_topology_node

            if expand_children:
                children_rlocs = [child.get('rloc16') for child in network_topology_node.get('children', []) if child.get('rloc16')]
                for child_rloc in children_rlocs:
                    if child_rloc not in network_topology_map:
                        # if child_node returns none, retry N times with some delay 
                        # in case the child sleeping (5 seconds), is not fully attached or responsive yet, 
                        # otherwise add with default values    
                        child_retries = 5 # number of retries
                        child_delay = 1.75  # seconds
                        child_tlv_detail_level = 3

                        for cr in range(child_retries):
                            # On last retries, try with simpler TLV set in case detailed one is causing issues
                            if cr == child_retries - 2:
                                child_tlv_detail_level = 2
                                print(f"[DEBUG] Child node {child_rloc} not found after {cr} attempts, trying with medium detail TLV set.")   

                            if cr == child_retries - 1:
                                child_tlv_detail_level = 1
                                print(f"[DEBUG] Child node {child_rloc} not found after {cr} attempts, trying with simple values.")

                            child_node = get_networkdiagnostic_one(child_rloc, ipv6_rloc_prefix, extaddr_map, ipv6_addresses, child_tlv_detail_level)
                            if child_node is not None:
                                child_node['type'] = 'Child'
                                break
                            print (f"[DEBUG] Child node {child_rloc} not found, retrying in {child_delay} seconds...")
                            time.sleep(child_delay)
                            
                        if child_node is None:
                            network_topology_map[child_rloc] = {
                            "extaddr": f"Unknown-{child_rloc}",
                            "rloc16": child_rloc,
                            "device_label": f"Unknown-{child_rloc}",
                            "thread_stack_version": "Unknown",
                            "mode": {},
                            "ipv6_addrs": ipv6_addresses.get(child_rloc, []),
                            "children": [],
                            "omrIpv6Address": td_util_network.get_omr_addr_from_list(ipv6_addresses.get(child_rloc, []), omr_ipv6addr_prefix) if omr_ipv6addr_prefix else None,
                            "type": "Unknown-Child",
                            "mac_counters": {},
                            "mle_counters": {},
                            "time_statistics": {}
                        }
                        
                        else:
                            child_node['omrIpv6Address'] = td_util_network.get_omr_addr_from_list(child_node.get("ipv6_addrs", []), omr_ipv6addr_prefix) if omr_ipv6addr_prefix else None
                            network_topology_map[child_rloc] = child_node
                    
    return network_topology_map

def print_networkdiagnostic_topology(topology):
    """Prints the network topology to console in tree format."""
    print("\n--- Thread Network Topology ---\n")
    for rloc, data in topology.items():
        print(f"Parent [RLOC: {rloc}] (Ext: {data['extaddr']})")
        print(f"  Thread Stack Version: {data.get('thread_stack_version', 'Unknown')}")
        
        if data.get('ipv6_addrs'):
            print(f"  IPv6 Addresses ({len(data['ipv6_addrs'])}):")
            for ipv6 in data['ipv6_addrs']:
                print(f"    - {ipv6}")
        
        if data.get('omrIpv6Address'):
            print(f"  OMR IPv6 Address: {data['omrIpv6Address']}")

        if data.get('children'):
            print(f"  Children ({len(data['children'])}):")
            for child in data['children']:
                print(f"    - ID: {child['id']}, Timeout: {child.get('timeout')}, Link Quality: {child.get('link_quality')}")
                if child.get('mode'):
                    mode = child['mode']
                    print(f"      Mode: RxOnWhenIdle={mode.get('rx_on_when_idle')}, DeviceType={mode.get('device_type')}, NetworkData={mode.get('network_data')}")
        
        if data.get('mac_counters'):
            print(f"  MAC Counters:")
            for key, value in sorted(data['mac_counters'].items()):
                print(f"    {key}: {value}")
        
        if data.get('mle_counters'):
            print(f"  MLE Counters:")
            for key, value in sorted(data['mle_counters'].items()):
                print(f"    {key}: {value}")
        
        if data.get('time_statistics'):
            print(f"  Time Statistics:")
            time_stats = data['time_statistics']
            if time_stats:
                total_time = time_stats.get('tracked_time', 0)
                router_pct = (time_stats.get('router_time', 0) / total_time * 100) if total_time > 0 else 0
                child_pct = (time_stats.get('child_time', 0) / total_time * 100) if total_time > 0 else 0
                print(f"    Tracked: {time_stats.get('tracked_time')}, Router: {time_stats.get('router_time')} ({router_pct:.1f}%), Child: {time_stats.get('child_time')} ({child_pct:.1f}%)")
                print(f"    Disabled: {time_stats.get('disabled_time')}, Detached: {time_stats.get('detached_time')}, Leader: {time_stats.get('leader_time')}")
        
        print()


def save_networkdiagnostic_topology_to_json_dict(data, filename="td-otbr-cli-networkdiag-topology.json"):
    """Serializes the dictionary to a pretty-printed JSON file."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    print(f"Successfully exported topology to {filename}")

def save_networkdiagnostic_topology_to_json_list(data, filename="thread-networkdiagnostic-topology-list.json"):
    """Converts dict format to list format and saves to JSON."""
    network_map = []
    
    ## TODO "type" find a way to filter to router-br, router, REED, FTD, MTD, child
   
    for rloc, data in data.items():
        ##backup nn = deepcopy(data)

        # set the order of fields in the output JSON for better readability, with key fields like rloc16, extaddr, device_label at the top, and then the more detailed fields like mode, ipv6_addrs, children, counters grouped together below. This way when looking at the JSON output, it's easier to quickly identify the key information about each node before diving into the more detailed data.
        network_node = {
            "rloc16": rloc,
            "extaddr": data['extaddr'],
            "device_label": data.get('device_label', f"Unknown-{rloc}"),
            "thread_stack_version": data.get('thread_stack_version', 'Unknown'),
            "mode": data.get('mode', {}),
            "ipv6_addrs": data.get('ipv6_addrs', []),
            "omrIpv6Address": data.get('omrIpv6Address'),
            "type": data.get('type', 'Unknown'),
            "children": data.get('children', []),
            "mac_counters": data.get('mac_counters', {}),
            "mle_counters": data.get('mle_counters', {}),
            "time_statistics": data.get('time_statistics', {})
        }
        network_map.append(network_node)
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(network_map, f, indent=4)
    print(f"Successfully exported topology to {filename}")

def main():
    """Main entry point with optional command-line arguments."""
    print("Initiating Thread Network Topology Scan...\n")
    
    ## TODO 
    ## arguments
    ## all (default)
    ## br only
    ## leader only
    ## router only
    ## children only
    ## multicast networkdiagnostic get ff03::1
    
    # Load extaddr to nodename mapping from JSON file
    extaddr_json_filename = "td-static-extaddr-device-label.json"

    # Check if file exists before parsing
    if os.path.exists(extaddr_json_filename):
        extaddr_map = parse_extaddr_nodename_mapping(extaddr_json_filename)
    else:
        extaddr_map = {}
  
    network_dataset_info = td_util_network.get_network_dataset_info()

    # Get the networkdiagnostic topology data
    networkdiagnostic_topology_data = get_networkdiagnostic_topology_data(extaddr_map, network_dataset_info)
    
    # print the topology in tree format to console 
    print_networkdiagnostic_topology(networkdiagnostic_topology_data)

    # save the topology as JSON to file
    save_json_filename = "td-otbr-cli-networkdiag-topology.json"
    save_networkdiagnostic_topology_to_json_list(networkdiagnostic_topology_data, save_json_filename)
    
    # Print the raw topology dictionary as JSON to console for debugging
    print(json.dumps(networkdiagnostic_topology_data, indent=4))

    # """
    # # Determine output format from command-line argument
    # output_format = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    # if output_format in ["console", "all"]:
    #     print_network_topology(topology)
    
    # if output_format in ["json-dict", "all"]:
    #     save_topology_to_json(topology, "thread_topology.json")
    
    # if output_format in ["json-list", "all"]:
    #     save_topology_as_list_json(topology, "thread_topology_list.json")
    
    # if output_format not in ["console", "json-dict", "json-list", "all"]:
    #     print(f"Unknown format '{output_format}'")
    #     print("Usage: python td_dump_thread_topology_3_merged.py [console|json-dict|json-list|all]")
    #     print("  console:  Print topology to console (tree format)")
    #     print("  json-dict: Save as JSON dict with rloc16 keys")
    #     print("  json-list: Save as JSON list with parent nodes")
    #     print("  all:      Print to console + save both JSON formats (default)")
    # """
        
if __name__ == "__main__":
    main()
