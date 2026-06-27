import argparse
import os
import re
import json
import sys
import time
import logging

from copy import deepcopy
from typing import Sequence
from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME, TD_DATA_DIR_ARG_HELP, TD_THREAD_MULTICAST_ADDRESSES_LINK_LOCAL_ALL_FTDS_AND_MEDS, TD_THREAD_MULTICAST_ADDRESSES_MESH_LOCAL_ALL_FTDS_AND_MEDS
import util_ot_ctl
import util_network
from td_json_key_normalizer import convert_keys_to_camel_case
from otbr_cli_router_table import fetch_and_parse_router_table
from extaddr_device_label_map import load_extaddr_device_label_map
from util_data import data_file_path, resolve_data_dir, save_json_atomic, create_checkpoint_filename

from otbr_cli_networkdiag_util import (
    TLV_VALUES_DETAILED,
    TLV_VALUES_MEDIUM,
    TLV_VALUES_BASIC,
    TLV_VALUES_CHILD_DETAILED,
    TLV_VALUES_CHILD_MEDIUM_TV_MAC,
    TLV_VALUES_CHILD_MEDIUM_MAC,
    TLV_VALUES_CHILD_BASIC,
    fetch_ipv6_addresses,
    device_type_from_mode,
    merge_device_record,
    get_tlv_values_for_detail_level,
)
from otbr_cli_networkdiag_parsers import (
    parse_ipv6_address_list,
    parse_mode_flags,
    parse_child_table,
    parse_mac_counters,
    parse_mle_counters,
    parse_time_statistics,
    parse_eui64,
    parse_connectivity,
    parse_leader_data,
    parse_vendor_name,
    parse_vendor_model,
    parse_vendor_sw_version,
    parse_route_data,
    parse_multicast_diag_output,
)

from otbr_cli_meshdiag_topology import (
    get_meshdiag_topology
)


NETWORKDIAG_MULTICAST_NETWORK_FILENAME = "td-otbr-cli-networkdiag-multicast-network.json"
NETWORKDIAG_MULTICAST_NEIGHBORS_FILENAME = "td-otbr-cli-networkdiag-multicast-neighbors.json"
NETWORKDIAG_FETCH_ALL_FILENAME = "td-otbr-cli-networkdiag-fetch-all.json"


def fetch_network_diag_for_device(
    rloc16, rloc_prefix, extaddr_map=None, router_table_by_router_id=None, ipv6_addresses=None, tlv_detail_level=6
):
    """
    Queries and parses network diagnostic data for a single router.

    Args:
        rloc16: RLOC16 value for the router (e.g., "0x0400")
        rloc_prefix: IPv6 prefix for building RLOC IPv6 address
        extaddr_map: Dictionary mapping extended addresses to node names
        ipv6_addresses: Dictionary of IPv6 addresses by RLOC

    Returns:
        Dictionary containing parsed diagnostic data for the router, or None if extaddr is not found
    """
    if extaddr_map is None:
        extaddr_map = {}
    if ipv6_addresses is None:
        ipv6_addresses = {}

    rloc_hex = util_network.strip_rloc16_hex_prefix(rloc16)
    ipv6_rloc_addr = util_network.build_rloc16_ipv6_address(
        rloc_prefix, rloc_hex
    )

    # Get TLV values for the requested detail level
    tlv_values = get_tlv_values_for_detail_level(tlv_detail_level)

    # Query router for diagnostic TLVs:
    # TLV 0: Ext Address, TLV 1: RLOC16, TLV 2: Mode, TLV 23: EUI64
    # TLV 8: IPv6 Address List, TLV 4: Connectivity, TLV 6: Leader Data
    # TLV 24: Thread Version, TLV 25: Vendor Name, TLV 26: Vendor Model
    # TLV 27: Vendor SW Version, TLV 28: Vendor App URL (Thread Stack Version)
    # TLV 5: Route64, TLV 16: Child Table, TLV 9: MAC Counters
    # TLV 34: MLE Counters, Time Statistics
    output = util_ot_ctl.exec_ot_ctl(
        f"networkdiagnostic get {ipv6_rloc_addr} {tlv_values}"
    )
    logging.debug(
        f"Diagnostic for RLOC {rloc16} (IPv6: {ipv6_rloc_addr}):\n{output}\n")

    # Extract Ext Address (TLV 0)
    extaddr_match = re.search(r"Ext Address: ([0-9a-fA-F]{16})", output)

    # If extaddr is not found, return None (caller will handle with default values)
    if not extaddr_match:
        return None

    # Try resolve device_label from extaddr_map, if not found use "Unknown-{rloc16}"
    device_label = extaddr_map.get(extaddr_match.group(1))
    if not device_label:
        device_label = f"Unknown-{rloc16}"

    # Extract Rloc16 (TLV 1)
    rloc16_match = re.search(r"Rloc16: (0x[0-9a-fA-F]{4})", output)

    # Extract Thread Stack Version (TLV 28)
    thread_version = re.search(r"Thread Stack Version: (.+?)(?:\n|$)", output)

    # Parse detailed structures
    mode_flags = parse_mode_flags(output)
    ipv6_list = parse_ipv6_address_list(output)
    eui64 = parse_eui64(output)
    connectivity = parse_connectivity(output)
    leader_data = parse_leader_data(output)
    vendor_name = parse_vendor_name(output)
    vendor_model = parse_vendor_model(output)
    vendor_sw_version = parse_vendor_sw_version(output)
    route = parse_route_data(output)
    children = parse_child_table(output, rloc16)
    mac_counters = parse_mac_counters(output)
    mle_counters = parse_mle_counters(output)
    time_stats = parse_time_statistics(output)

    network_topology_node = {
        "extaddr": extaddr_match.group(1) if extaddr_match else "Unknown",
        "rloc16": rloc16_match.group(1) if rloc16_match else rloc16,
        "device_label": device_label,
        "eui64": eui64,
        "tlv_values": tlv_values,
        "thread_stack_version": thread_version.group(1).strip()
        if thread_version
        else "Unknown",
        "mode": mode_flags,
        "ipv6_addrs": ipv6_list if ipv6_list else ipv6_addresses.get(rloc16, []),
        "connectivity": connectivity,
        "leader_data": leader_data,
        "vendor_name": vendor_name,
        "vendor_model": vendor_model,
        "vendor_sw_version": vendor_sw_version,
        "route": route,
        "children": children,
        "mac_counters": mac_counters,
        "mle_counters": mle_counters,
        "time_statistics": time_stats,
    }

   # Enrich device_record routes with router rloc
    _enrich_device_route_data_with_router_info(
        network_topology_node, router_table_by_router_id
    )

    return network_topology_node


def fetch_network_diag_multicast(
    multicast_addr: str,
    extaddr_map: dict | None = None,
    thread_network_info: dict | None = None,
    router_table_by_router_id: dict | None = None,
) -> dict:
    """
    Queries network diagnostic data via multicast with retry and merge strategy.

    Sends networkdiagnostic queries to all devices on a multicast address (ff03::1 for
    all mesh devices or ff02::1 for immediate neighbors). Retries with progressively
    simpler TLV sets to maximize device responses, merging results to get the most
    complete information across all retries.

    Args:
        multicast_addr: Multicast address to target ("ff03::1" or "ff02::1")
        extaddr_map: Optional dict mapping extended addresses to device labels
        thread_network_info: Optional dict with network info (contains OMR prefix)

    Returns:
        Dict keyed by rloc16, with device records as values (same format as
        fetch_network_diag_topology output). Each record includes consolidated
        data from all retry attempts.
    """
    if extaddr_map is None:
        extaddr_map = {}

    # Get OMR prefix from thread_network_info
    omr_ipv6addr_prefix = (
        thread_network_info["prefix_omr_ipv6addr_prefix"]
        if thread_network_info and "prefix_omr_ipv6addr_prefix" in thread_network_info
        else None
    )

    # Get meshlocal prefix from thread_network_info
    meshlocal_prefix = (
        thread_network_info["prefix_meshlocal_ipv6addr_prefix"]
        if thread_network_info and "prefix_meshlocal_ipv6addr_prefix" in thread_network_info
        else None
    )

    # Multiple attempts gives {DETAILED, MEDIUM, SIMPLE} as some devices may not respond to the more detailed TLVs
    attempts_max = 2
    delay_start = 0.1  # between retries 0.10 0.20 0.50 1.0 1.5 1.75 2.0 seconds
    tlv_detail_level = 8
    consolidated = {}  # Keyed by extaddr during collection

    # Retry loop with progressively simpler TLV sets
    for attempt_idx in range(attempts_max):

        match attempt_idx:
            case 0:
                tlv_detail_level = 10  # DETAILED
            case 1:
                tlv_detail_level = 8  # BASIC
            case 2:
                tlv_detail_level = 9  # MEDIUM
            case _:
                tlv_detail_level = 8  # BASIC

        # Get TLV values for current detail level
        tlv_values = get_tlv_values_for_detail_level(tlv_detail_level)

        logging.info(
            f"Multicast attempt {attempt_idx + 1}/{attempts_max} to {multicast_addr} "
            f"(TLV level {tlv_detail_level}): {tlv_values}"
        )

        # Execute multicast query
        output = util_ot_ctl.exec_ot_ctl(
            f"networkdiagnostic get {multicast_addr} {tlv_values}"
        )
        logging.debug(
            f"[DEBUG] Multicast output (attempt {attempt_idx + 1}):\n{output}\n")

        # Parse multicast output
        parsed = parse_multicast_diag_output(output, extaddr_map)

        # Merge results into consolidated dict (keyed by extaddr)
        for device_record in parsed.values():
            extaddr = device_record["extaddr"]

            # Enrich device record with role classification and prefix-based flags
            _enrich_device_role_and_prefix_flags(
                device_record, meshlocal_prefix, omr_ipv6addr_prefix
            )

            # Enrich device_record routes with router rloc
            _enrich_device_route_data_with_router_info(
                device_record, router_table_by_router_id
            )
            # Add TLV set info to record
            device_record["tlv_values"] = tlv_values
            if extaddr in consolidated:
                merge_device_record(consolidated[extaddr], device_record)
            else:
                consolidated[extaddr] = device_record

        logging.info(
            f"Multicast attempt {attempt_idx + 1}: {len(parsed)} responses, "
            f"{len(consolidated)} unique devices so far"
        )

        # Sleep before next retry (but not after the last retry)
        if attempt_idx < attempts_max - 1:
            # tlv_detail_level = max(1, tlv_detail_level - 1)  # Floor at 1

            r_delay = delay_start
            time.sleep(r_delay)

    # Finalize the consolidated dict

    # Re-key by rloc16 and add type/omr_ipv6_addr fields
    result = {}
    for record in consolidated.values():
        rloc16 = record.get("rloc16", "Unknown")

        # Add OMR IPv6 address if prefix available
        if omr_ipv6addr_prefix:
            record["omr_ipv6_addr"] = util_network.find_omr_address_in_list(
                record.get("ipv6_addrs", []), omr_ipv6addr_prefix
            )
        else:
            record["omr_ipv6_addr"] = None

        # Store in result, keyed by rloc16
        result[rloc16] = record

    logging.info(
        f"Multicast consolidation complete: {len(result)} devices (keyed by rloc16)"
    )
    return result


def fetch_network_diag_topology_multicast_network(
    extaddr_map: dict | None = None,
    thread_network_info: dict | None = None,
    router_table_by_router_id: dict | None = None
) -> dict:
    """
    Queries network diagnostic data via multicast to all Thread devices in the mesh (ff03::1).

    This is a thin wrapper around fetch_network_diag_multicast() that targets the
    all-thread-devices multicast address, allowing discovery of the entire mesh network.

    Args:
        extaddr_map: Optional dict mapping extended addresses to device labels
        thread_network_info: Optional dict with network info (contains OMR prefix)

    Returns:
        Dict keyed by rloc16 with device records from all mesh devices
    """
    return fetch_network_diag_multicast(
        multicast_addr=TD_THREAD_MULTICAST_ADDRESSES_MESH_LOCAL_ALL_FTDS_AND_MEDS,  # "ff03::1"
        extaddr_map=extaddr_map,
        thread_network_info=thread_network_info,
        router_table_by_router_id=router_table_by_router_id
    )


def fetch_network_diag_topology_multicast_neighbors(
    extaddr_map: dict | None = None,
    thread_network_info: dict | None = None,
    router_table_by_router_id: dict | None = None
) -> dict:
    """
    Queries network diagnostic data via multicast to immediate one-hop neighbors (ff02::1).

    This is a thin wrapper around fetch_network_diag_multicast() that targets the
    link-local multicast address, allowing discovery of only immediate neighbors
    reachable in one hop from the querying device.

    Args:
        extaddr_map: Optional dict mapping extended addresses to device labels
        thread_network_info: Optional dict with network info (contains OMR prefix)
        router_table_by_router_id: Optional dict mapping router IDs to router table entries
    Returns:
        Dict keyed by rloc16 with device records from immediate one-hop neighbors
    """
    return fetch_network_diag_multicast(
        multicast_addr=TD_THREAD_MULTICAST_ADDRESSES_LINK_LOCAL_ALL_FTDS_AND_MEDS,  # "ff02::1"
        extaddr_map=extaddr_map,
        thread_network_info=thread_network_info,
        router_table_by_router_id=router_table_by_router_id
    )


# ---------------------------------------------------------------------------
# Internal Helper Functions
# ---------------------------------------------------------------------------

def _build_unknown_device_record(
    rloc16: str,
    role: str,
    ipv6_addresses: dict,
    omr_ipv6addr_prefix: str | None,
    meshlocal_prefix: str | None,
) -> dict:
    """
    Constructs a fallback device record for unresponsive nodes.

    Used when a device fails to respond to network diagnostic queries after retry
    attempts. Provides a minimal record with placeholder values and available IPv6
    information to maintain topology completeness.

    Args:
        rloc16: RLOC16 of the unresponsive device (e.g., "0x5000")
        role: Device role ("router" or "child") to determine record structure
        ipv6_addresses: Dict mapping rloc16 to list of IPv6 addresses
        omr_ipv6addr_prefix: OMR prefix for finding off-mesh-routable addresses (optional)
        meshlocal_prefix: Mesh-local prefix for detecting border routers (optional)

    Returns:
        Dictionary with fallback device record structure. For routers, includes
        border router detection. For children, includes empty counters.
    """
    ipv6_addrs = ipv6_addresses.get(rloc16, [])

    # Find OMR address if prefix available
    omr_ipv6_addr = (
        util_network.find_omr_address_in_list(ipv6_addrs, omr_ipv6addr_prefix)
        if omr_ipv6addr_prefix
        else None
    )

    # Base record structure (common to both routers and children)
    record = {
        "extaddr": f"Unknown-{rloc16}",
        "rloc16": rloc16,
        "device_label": f"Unknown-{rloc16}",
        "mode": {},
        "ipv6_addrs": ipv6_addrs,
        "omr_ipv6_addr": omr_ipv6_addr,
    }

    if role == "router":
        # Router-specific fields: type/br based on IPv6 addresses
        record["is_router"] = True
        record["type"] = "router"
        record["role"] = "router"

        if meshlocal_prefix:
            is_border_router = util_network.is_border_router_from_ipv6_addrs(
                ipv6_addrs, meshlocal_prefix
            )
            if is_border_router:
                record["is_border_router"] = is_border_router
                record["type"] = "border router"
                record["role"] = "border router"
                record["br"] = is_border_router

        record["children"] = []
        record["mac_counters"] = {}
        record["mle_counters"] = {}
        record["time_statistics"] = {}

    elif role == "child":
        # Child-specific fields: type fixed, no br detection, empty counters
        record["type"] = "child"
        record["role"] = "child"
        record["mac_counters"] = {}
        record["mle_counters"] = {}
        record["time_statistics"] = {}

    return record


def _enrich_device_role_and_prefix_flags(
    record: dict,
    meshlocal_prefix: str | None,
    omr_ipv6addr_prefix: str | None,
) -> None:
    """
    Enriches a device record with role classification and prefix-based flags.

    Analyzes IPv6 addresses to determine device type (Router or Border Router)
    and adds OMR IPv6 address field if available. Mutates the record in place.

    Args:
        record: Device record dict to enrich (mutated in place)
        meshlocal_prefix: Mesh-local prefix for detecting border routers (optional)
        omr_ipv6addr_prefix: OMR prefix for finding off-mesh-routable addresses (optional)

    Side Effects:
        Adds/updates the following fields in record:
        - "type": "border router" or "router"
        - "br": True/False/None (border router flag)
        - "omr_ipv6_addr": OMR address string or None
    """

    # Add OMR IPv6 address if prefix available
    if omr_ipv6addr_prefix:
        ipv6_addrs = record.get("ipv6_addrs", [])
        # Ensure ipv6_addrs is a list
        if not isinstance(ipv6_addrs, list):
            logging.warning(
                f"ipv6_addrs for device {record.get('rloc16', 'Unknown')} is not a list: {type(ipv6_addrs)}. Converting to list.")
            ipv6_addrs = [ipv6_addrs] if ipv6_addrs else []
            record["ipv6_addrs"] = ipv6_addrs

        record["omr_ipv6_addr"] = util_network.find_omr_address_in_list(
            ipv6_addrs, omr_ipv6addr_prefix
        )
    else:
        record["omr_ipv6_addr"] = None

    # Check if router or child based on rloc16
    is_router = util_network.is_router(record.get("rloc16", "Unknown"))
    if not is_router:
        record["type"] = "child"
        record["role"] = "child"
        return

    # If router
    if is_router:
        record["is_router"] = True
        record["type"] = "router"
        record["role"] = "router"

    # Check if device is a border router based on mesh-local prefix
    if meshlocal_prefix:
        ipv6_addrs = record.get("ipv6_addrs", [])
        # Ensure ipv6_addrs is a list
        if not isinstance(ipv6_addrs, list):
            logging.warning(
                f"ipv6_addrs for device {record.get('rloc16', 'Unknown')} is not a list when checking border router: {type(ipv6_addrs)}. Converting to list.")
            ipv6_addrs = [ipv6_addrs] if ipv6_addrs else []
            record["ipv6_addrs"] = ipv6_addrs

        is_border_router = util_network.is_border_router_from_ipv6_addrs(
            ipv6_addrs, meshlocal_prefix
        )
        if is_border_router:
            record["is_border_router"] = True
            record["br"] = is_border_router
            record["type"] = "border router"
            record["role"] = "border router"


def _enrich_device_route_data_with_router_info(
    record: dict,
    router_table_by_router_id: dict | None,
) -> None:
    """
    Enrich device record route [] of routes, enriching the items in the array by looking up their router_id in the router_table_data and adding the corresponding rloc16 to each route entry. 
    This way we can have more complete information about the routes in the topology map, including the rloc16 of the next hops for each route, which can be useful for understanding the network topology and routing paths. 

    Enriches the route data in a device record with router information from the router table.

    For each route entry in the device's route_data, looks up the corresponding router_id
    in the router_table_data to find the rloc16 and adds it to the route entry. Mutates
    the record in place.

    Args:
        record: Device record dict containing "route" field to enrich (mutated in place)
        router_table_by_router_id: Optional dict of router entries keyed by "router_id", 
                                    each containing "rloc16". If None, no enrichment is performed.

    Side Effects:
        Updates each route entry in record["route"]["route_data"] by adding an "rloc16" field 
        based on matching "router_id" from router_table_by_router_id
    """
    # Early return if no router table provided
    if not router_table_by_router_id:
        return

    # route has structure: {"id_sequence": int, "route_data": [...]}
    route_dict = record.get("route")
    if not route_dict or not isinstance(route_dict, dict):
        return

    # Get the nested array of routes
    route_data_array = route_dict.get("route_data")
    if not route_data_array or not isinstance(route_data_array, list):
        return

    for route in route_data_array:
        route_id = route.get("route_id")
        if route_id is not None:
            # Look up rloc16 for this router_id in the router_table_by_router_id
            matching_router = router_table_by_router_id.get(route_id)
            if matching_router and isinstance(matching_router, dict) and matching_router.get("rloc16"):
                route["rloc16"] = matching_router["rloc16"]
            else:
                route["rloc16"] = "Unknown"


def _upsert_device_record(
    records_by_rloc: dict,
    incoming_record: dict,
    extaddr_to_rloc: dict,
) -> None:
    """
    Adds or merges a device record into the topology map.

    Implements the "upsert" pattern: if a record already exists for this rloc16,
    merge the new data into it; otherwise, add the new record. This is commonly
    used when combining multicast and direct query results.

    Handles RLOC16 changes: if the same EXTADDR appears with a different RLOC16,
    removes the old entry and adds with the new RLOC16 key. This prevents
    duplicates when devices change roles during topology polling.

    Args:
        records_by_rloc: Dict keyed by rloc16 containing existing device records (mutated)
        incoming_record: New device record to add or merge
        extaddr_to_rloc: Dict mapping extaddr to current rloc16 for duplicate detection (mutated)

    Side Effects:
        Mutates records_by_rloc by either:
        - Adding incoming_record as a new entry, or
        - Merging incoming_record into an existing entry via merge_device_record()
        - Removing old rloc16 key and adding new one if extaddr matches but rloc16 changed
        Mutates extaddr_to_rloc to track current rloc16 for each extaddr
    """
    rloc16 = incoming_record.get("rloc16")
    extaddr = incoming_record.get("extaddr")

    if not rloc16:
        return

    # Skip unknown or placeholder extaddrs (they start with "Unknown-")
    if extaddr and not extaddr.startswith("Unknown-"):
        # Check if this extaddr already exists with a different rloc16
        existing_rloc16 = extaddr_to_rloc.get(extaddr)

        if existing_rloc16 and existing_rloc16 != rloc16:
            # Same device, different RLOC16 (role change during polling)
            # Remove old entry and merge data into new entry
            logging.info(
                f"Device {extaddr} changed RLOC16 from {existing_rloc16} to {rloc16} "
                f"(role change detected). Removing old entry and updating with new RLOC16."
            )
            old_record = records_by_rloc.pop(existing_rloc16, None)
            if old_record:
                # Merge old data into incoming record to preserve any data collected earlier
                merge_device_record(incoming_record, old_record)

            # Update extaddr mapping
            extaddr_to_rloc[extaddr] = rloc16
            records_by_rloc[rloc16] = incoming_record
            return

        # Track this extaddr -> rloc16 mapping
        extaddr_to_rloc[extaddr] = rloc16

    if rloc16 in records_by_rloc:
        # Merge new data into existing record
        merge_device_record(records_by_rloc[rloc16], incoming_record)
    else:
        # Add new record
        records_by_rloc[rloc16] = incoming_record


def fetch_network_diag_topology(
    extaddr_map=None, thread_network_info=None, expand_children=True, td_data_dir=None
):
    """Maps the full network topology and returns a Python dictionary."""

    # expand_children controls whether to perform additional queries for each router to get their child table data and include that in the topology map.
    # Set to True to also query and include child nodes in the topology map (will increase runtime significantly)
    # Set to False to only get parent nodes without expanding children

    # 1. Initialize topology map and extaddr tracking
    network_topology_map = {}

    # Create checkpoint filename for saving intermediate results during topology mapping.
    checkpoint_filename = create_checkpoint_filename(
        NETWORKDIAG_FETCH_ALL_FILENAME)
    checkpoint_filepath = data_file_path(checkpoint_filename, td_data_dir)
    logging.debug("Checkpoint filepath: %s", checkpoint_filepath)

    # Track extaddr -> rloc16 mapping to detect duplicate devices with changed RLOC16
    extaddr_to_rloc = {}

    # 2. Get OMR prefix
    omr_ipv6addr_prefix = (
        thread_network_info["prefix_omr_ipv6addr_prefix"]
        if thread_network_info and "prefix_omr_ipv6addr_prefix" in thread_network_info
        else None
    )

    # 3. Get meshlocal prefix / rloc prefix from thread_network_info for building RLOC IPv6 addresses
    meshlocal_prefix = (
        thread_network_info["prefix_meshlocal_ipv6addr_prefix"]
        if thread_network_info and "prefix_meshlocal_ipv6addr_prefix" in thread_network_info
        else None
    )

    # 4. Get all active routers (potential parents)
    router_table_data = fetch_and_parse_router_table(extaddr_map)
    if router_table_data is not None:
        network_topology_map_routers = {}

        logging.info(f"Router table has {len(router_table_data)} entries")

        # Build lookup lists
        # Extract RLOC16 values for all routers in the router table
        router_rlocs = []
        for router in router_table_data:
            if not isinstance(router, dict):
                logging.warning(
                    f"Router in router_table_data is not a dict: {type(router)}, value: {router}. Skipping.")
                continue
            rloc16 = router.get("rloc16")
            if rloc16:
                router_rlocs.append(rloc16)

        # Build a dict of router_table_data indexed by router_id
        router_table_by_router_id = {}
        for router in router_table_data:
            if not isinstance(router, dict):
                continue
            router_id = router.get("router_id")
            if router_id is not None:
                router_table_by_router_id[router_id] = router

        # Conform router table data into the topology record
        for router in router_table_data:
            extaddr = router.get("extaddr")
            rloc16 = router.get("rloc16")
            if extaddr or rloc16:
                network_topology_map_routers[rloc16] = {
                    "extaddr": extaddr,
                    "rloc16": rloc16,
                    "device_label": extaddr_map.get(router.get("extaddr"), f"Unknown-{rloc16}"),
                    "role": "router",
                    "is_router": True,
                    "router_id": router.get("router_id"),
                    "next_hop": router.get("next_hop"),
                    "path_cost": router.get("path_cost"),
                    "lq_in": router.get("lq_in"),
                    "lq_out": router.get("lq_out"),
                    "age": router.get("age"),
                    "link": router.get("link"),
                }

        # Merge router table data into the topology map, keyed by rloc16, with enriched fields for type/role based on router table data.
        for rloc16, device_record in network_topology_map_routers.items():
            device_record
            _upsert_device_record(network_topology_map,
                                  device_record, extaddr_to_rloc)

        logging.info(
            f"After merging router table data, topology map has {len(network_topology_map)} devices (keyed by rloc16)")

        # Checkpoint to file
        save_topology_to_json_file(network_topology_map, checkpoint_filepath)

    else:
        logging.warning("Router table is None. No routers found.")
        router_table_data = []

    # 5a. Get meshdiag topology data and merge into main topology map, keyed by rloc16.
    meshdiag_topology_data = get_meshdiag_topology(
        extaddr_map, thread_network_info
    )

    if meshdiag_topology_data is not None:
        network_topology_map_meshdiag_routers = {}

        # Conform meshdiag topology data into the topology record
        for router in meshdiag_topology_data:
            extaddr = router.get("extaddr")
            rloc16 = router.get("rloc16")
            if extaddr or rloc16:
                # Ensure ipv6_addrs is a list, not a string
                ipv6_addrs = router.get("ipv6_addrs", [])
                if not isinstance(ipv6_addrs, list):
                    logging.warning(
                        f"meshdiag ipv6_addrs for {rloc16} is not a list: {type(ipv6_addrs)}. Converting.")
                    ipv6_addrs = [ipv6_addrs] if ipv6_addrs else []

                # build record
                network_topology_map_meshdiag_routers[rloc16] = {
                    "extaddr": extaddr,
                    "rloc16": rloc16,
                    "device_label": extaddr_map.get(extaddr, f"Unknown-{rloc16}"),
                    "thread_version": router.get("thread_version"),
                    "ver": router.get("ver"),
                    "role": "router",
                    "is_router": True,
                    "is_border_router": router.get("is_border_router", False),
                    "br": router.get("br", False),
                    "omr_ipv6_addr": router.get("omr_ipv6_addr"),
                    "mode": router.get("mode"),
                    "ipv6_addrs": ipv6_addrs,
                    "route": router.get("route", {}),
                    "children": router.get("children", []),
                }

        for rloc16, device_record in network_topology_map_meshdiag_routers.items():
            _upsert_device_record(network_topology_map,
                                  device_record, extaddr_to_rloc)

        # Checkpoint to file
        save_topology_to_json_file(network_topology_map, checkpoint_filepath)
    else:
        logging.warning(
            "Meshdiag topology data is None. No meshdiag data to merge.")

    # 5b. Get IPv6 addresses for all routers
    # need this if nodes don't reponse to networkdiagnostic get with TLV 8 for IPv6 address list, then we can at least populate the topology map with known IPv6 addresses for each RLOC16 from this separate query. This way we can still have some reference to IPv6 addresses in the topology even if some nodes don't respond to the full diagnostic query.
    ipv6_addresses = {}
    if meshdiag_topology_data is not None:
        # Build a dict of IPv6 addresses by RLOC16 from meshdiag topology data
        for router in meshdiag_topology_data:
            rloc16 = router.get("rloc16")
            ipv6_addrs = router.get("ipv6_addrs", [])
            if rloc16:
                ipv6_addresses[rloc16] = ipv6_addrs
    else:
        logging.warning(
            "Meshdiag topology data is None. Cannot extract IPv6 addresses from meshdiag data.")
        ipv6_addresses = fetch_ipv6_addresses()
        ipv6_addresses = (
            ipv6_addresses if ipv6_addresses else {}
        )  # Ensure it's a dict even if empty

    # 6. Get the multicast topology data
    # This will give us a starting point with data from all devices that responded to the multicast query, which we can then enrich with additional direct queries for any missing data or child information as needed. The multicast query can help reduce the number of direct queries needed by providing data for many devices in one go, especially for those that respond with more detailed TLV sets in the initial retries.
    network_topology_map_multicast = fetch_network_diag_topology_multicast_network(
        extaddr_map, thread_network_info, router_table_by_router_id
    )

    if network_topology_map_multicast:
        logging.info(
            f"Multicast topology map has {len(network_topology_map_multicast)} devices (keyed by rloc16)")

        # Merge multicast topology data into main topology map, keyed by rloc16
        for rloc16, device_record in network_topology_map_multicast.items():
            _upsert_device_record(network_topology_map,
                                  device_record, extaddr_to_rloc)
        logging.info(
            f"After merging multicast data, topology map has {len(network_topology_map)} devices (keyed by rloc16)"
        )

        # Checkpoint thread device data to file after multicast collection before starting direct queries, so we have a record of what we got from multicast alone before we start enriching with direct queries. This can be useful for debugging and analysis to see the difference between what we get from multicast vs direct queries, and also to have a baseline record of the multicast responses in case some devices become unresponsive during the direct query phase.
        save_topology_to_json_file(network_topology_map, checkpoint_filepath)
    else:
        logging.warning("Multicast topology map is empty or None")

    # 7. Loop through each router RLOC16 and query for its diagnostic data, then add to topology map. We can also check if we already have data for this RLOC16 from the multicast query before doing the direct query, and if so we can skip the direct query and just use the existing data to populate the topology map for this node. This way we can avoid unnecessary queries for nodes that already responded to the multicast request, which can help reduce overall runtime and network load. If we don't have data for this RLOC16 from the multicast query, then we proceed with the direct query with retries to try to get the data for this node.
    # Inner child loop also handles children and build a more complete topology map with parent-child relationships instead of just a flat map of RLOC16 to data. This way we can represent the full tree structure of the network instead of just a list of nodes.

    for rloc16 in router_rlocs:
        try:
            # Attempt logic for networkdiagnostic get in case of transient errors or unresponsive nodes, retry N times with some delay before giving up and adding with default values
            # Multiple attempts may give {DETAILED, MEDIUM, SIMPLE}
            attempts = 2
            delay_start = 0.1  # seconds

            # Initialize
            network_topology_node = None

            # Check if we already have data for this RLOC16 from the multicast query, if so skip the direct query and use the existing data to populate the topology map. This way we can avoid unnecessary queries for nodes that already responded to the multicast request, which can help reduce overall runtime and network load. If we don't have data for this RLOC16 from the multicast query, then we proceed with the direct query with retries to try to get the data for this node.
            record_exists = False
            if rloc16 in network_topology_map:
                network_topology_node = network_topology_map[rloc16]
                # Validate that the existing record is a dict, not a string or other type
                if not isinstance(network_topology_node, dict):
                    logging.error(
                        f"RLOC16 {rloc16} has invalid data type in topology map: {type(network_topology_node)}. Expected dict, got {network_topology_node}. Will re-fetch.")
                    network_topology_node = None
                    record_exists = False
                else:
                    record_exists = True
                    # We already have data for this RLOC16 from the multicast query, we can skip the direct query
                    # and use the existing data to populate the topology map. This way we can avoid unnecessary queries
                    # for nodes that already responded to the multicast request, which can help reduce overall runtime
                    # and network load. If we don't have data for this RLOC16 from the multicast query, then we proceed
                    # with the direct query with retries to try to get the data for this node.
                    logging.info(
                        f"RLOC16 {rloc16} already has data from multicast query, skipping direct query."
                    )
        except Exception as e:
            logging.error(
                f"Error processing RLOC16 {rloc16} in initial check: {e}")
            logging.error(
                f"rloc16: {rloc16}, network_topology_map keys: {list(network_topology_map.keys())[:10]}")
            raise

        # If record does exist then SKIP direct call attempts but still check if we need to expand children for this node if expand_children is True, since the multicast query might not have included the child table data for this node if it was using a simpler TLV set. So we can still enrich the existing node data with child information if needed by doing a direct query just for the child table TLV, but we can skip the full diagnostic query with all TLVs since we already have that data from the multicast response.

        # If record does not exist in topology map the direct query with attempts
        if (not record_exists):
            # Start with ROUTER TLV_VALUES_DETAILED for first attempt
            tlv_detail_level = 10  # DETAILED

            for attempt_idx in range(attempts):
                # Routers
                match attempt_idx:
                    case 0:
                        tlv_detail_level = 10  # DETAILED
                    case 1:
                        tlv_detail_level = 9  # MEDIUM
                    case 2:
                        tlv_detail_level = 8  # BASIC
                    case _:
                        tlv_detail_level = 8  # BASIC

                # Get TLV values for current detail level
                tlv_values = get_tlv_values_for_detail_level(tlv_detail_level)

                # On retry attempts
                if attempt_idx > 0:
                    logging.info(
                        f"Router Node {rloc16} not found after {attempt_idx} attempts, trying with tlv_detail_level {tlv_detail_level} {get_tlv_values_for_detail_level(tlv_detail_level)} TLV set."
                    )

                network_topology_node = fetch_network_diag_for_device(
                    rloc16, meshlocal_prefix, extaddr_map, router_table_by_router_id, ipv6_addresses, child_tlv_detail_level
                )
                if network_topology_node is not None:
                    break
                logging.info(
                    f"Router Node {rloc16} not found, retrying in {delay_start} seconds..."
                )
                # if last iteration skip sleep to avoid unnecessary delay before giving up and adding with default values
                if attempt_idx < attempts - 1:
                    # Increase delay with each retry
                    l_delay = delay_start * (attempt_idx + 1)
                    logging.info(
                        f"Waiting for {l_delay} seconds before next retry...{attempt_idx + 1} of {attempts}")
                    time.sleep(l_delay)

        if network_topology_node is None:
            # extaddr not found, use default values
            network_topology_map[rloc16] = _build_unknown_device_record(
                rloc16, "router", ipv6_addresses, omr_ipv6addr_prefix, meshlocal_prefix
            )
        else:
            # router node found
            # Enrich device record with role classification and prefix-based flags
            try:
                _enrich_device_role_and_prefix_flags(
                    network_topology_node, meshlocal_prefix, omr_ipv6addr_prefix
                )
            except Exception as e:
                logging.error(f"Error enriching device role for {rloc16}: {e}")
                logging.error(
                    f"network_topology_node type: {type(network_topology_node)}, value: {network_topology_node}")
                raise

            # Merge with existing data in topology map if present (e.g. from multicast query) to enrich the node data with any missing fields that we couldn't get from the direct query due to unresponsive node or TLV issues, this way we can have the most complete data possible for each node by combining the results from both the multicast and direct queries, and we can also handle cases where some nodes might only respond to one of the query types but not the other.
            is_new_record = rloc16 not in network_topology_map
            _upsert_device_record(network_topology_map,
                                  network_topology_node, extaddr_to_rloc)

            if is_new_record:
                logging.info(
                    f"Added router node {rloc16} {network_topology_node.get('extaddr', 'Unknown')} {network_topology_node.get('device_label', 'Unknown')} to topology map. {attempt_idx+1}/{attempts} attempts.  TLV detail level: {child_tlv_detail_level} {get_tlv_values_for_detail_level(child_tlv_detail_level)}"
                )
                logging.info(
                    f"Found {len(network_topology_map)} unique devices so far"
                )
                # Checkpoint to file after each new record added to topology map
                # used in progressive loading in dashboard UI
                save_topology_to_json_file(
                    network_topology_map, checkpoint_filepath)

            if expand_children:
                # 8. Expand child nodes in topology:
                # - If expand_children is True, loop through child nodes from this router's child table
                # - Query each child's diagnostic data and add to topology map with parent-child relationships
                # - Tradeoff: More complete topology but significantly more queries/runtime (especially in large networks)
                # - Implement retry logic for child node queries similar to parent router logic
                # - Gather RLOC16 values from child table and perform direct queries for each
                # - Result: Topology map shows parent-child relationships instead of flat RLOC16-only map

                # Get children list and ensure it's valid
                children_list = network_topology_node.get("children", [])
                if not isinstance(children_list, list):
                    logging.warning(
                        f"Children for {rloc16} is not a list: {type(children_list)}. Converting to list.")
                    children_list = [children_list] if children_list else []

                # Filter out non-dict children and extract rloc16 values
                children_rlocs = []
                for child in children_list:
                    if not isinstance(child, dict):
                        logging.warning(
                            f"Child for {rloc16} is not a dict: {type(child)}, value: {child}. Skipping.")
                        continue
                    child_rloc = child.get("rloc16")
                    if child_rloc:
                        children_rlocs.append(child_rloc)

                # index child table by rloc16 for quick lookup
                child_table_by_rloc16 = {}
                for child in children_list:
                    if not isinstance(child, dict):
                        continue
                    child_rloc = child.get("rloc16")
                    if child_rloc:
                        child_table_by_rloc16[child_rloc] = child

                # consider: make temporary records in the network_topology_map for each child with default values and then enrich them with direct queries, this way we can have a record of the child in the topology map even if it does not respond to the diagnostic query, and we can still attempt to enrich its data with more detailed TLV attempts. This can help maintain topology completeness even in cases where some child nodes are unresponsive or sleeping (MTD).

                for child_rloc in children_rlocs:
                    # Check if child RLOC16 is already in topology map (e.g. from multicast query),
                    # if so skip the direct query and use the existing data to populate the topology map
                    # for this child node. This way we can avoid unnecessary queries for child nodes (FTD) that
                    # already responded to the multicast request, which can help reduce overall runtime and
                    # network load. If we don't have data for this child RLOC16 from the multicast query, then
                    # we proceed with the direct query with retries to try to get the data for this child node.

                    if child_rloc not in network_topology_map:
                        # If child_node returns none, attempt N times with some delay
                        # in case the child sleeping (5 seconds), is not fully attached or responsive yet,
                        # otherwise add with default values

                        # if True then only fetch BASIC TLV values for child nodes. This can help reduce runtime and network load when expanding children, especially in large networks with many child nodes. 
                        # If False then fetch DETAILED TLV values for child nodes, which can take longer and increase network load but will give us more complete data for each child node.
                        child_fetch_fast_mode = True  
                        child_attempts_min = 3  # min number of attempts before giving up and adding with default values
                        child_attempts_max = 5  # max number of attempts
                        
                        child_delay_max = 2.0  # max delay between retries
                        child_delay_start = 0.25  # seconds 0.25 0.5 1.0 2.0 seconds
                        # start with BASIC TLV for first attempt, then progressively increase detail level on retries to maximize response chances
                        child_tlv_detail_level = 1
                        child_detail_level_name = ""

                        # track last attempt index that responded, -1 means no response yet
                        child_last_attempt_reponded = -1
                        # track last attempt detail level that responded, -1 means no response yet
                        child_last_attempt_tlv_detail_level = -1

                        for child_attempt_idx in range(child_attempts_max):

                            # Start with BASIC TLV for first attempt, then progressively increase detail level on retries to maximize response chances
                            # When node stops responding or we have enough data for the node then we can stop retrying and move on to the next child node.

                            """
                            match child_attempt_idx:
                                case 0:
                                    child_tlv_detail_level = 1 
                                    child_detail_level_name = "BASIC"                 
                                case 1:
                                    child_tlv_detail_level = 1 
                                    child_detail_level_name = "BASIC"                                    
                                case 2:
                                    child_tlv_detail_level = 2 
                                    child_detail_level_name = "MEDIUM_MAC"
                                case 3: 
                                    child_tlv_detail_level = 3   
                                    child_detail_level_name = "MEDIUM_TV_MAC"                                    
                                case 4:
                                    child_tlv_detail_level = 4 
                                    child_detail_level_name = "DETAILED"
                                case _:
                                    child_tlv_detail_level = 1  
                                    child_detail_level_name = "BASIC"
                            """

                            match child_attempt_idx:
                                case 0:
                                    child_tlv_detail_level = 1
                                    child_detail_level_name = "BASIC"
                                case 1:
                                    child_tlv_detail_level = 1
                                    child_detail_level_name = "BASIC"
                                case 2:
                                    child_tlv_detail_level = 1
                                    child_detail_level_name = "BASIC"
                                case 3:
                                    child_tlv_detail_level = 1
                                    child_detail_level_name = "BASIC"
                                case 4:
                                    child_tlv_detail_level = 2
                                    child_detail_level_name = "BASIC"
                                case _:
                                    child_tlv_detail_level = 1
                                    child_detail_level_name = "BASIC"

                            # Get TLV values for current detail level
                            tlv_values = get_tlv_values_for_detail_level(
                                child_tlv_detail_level)

                            # On retry attempts
                            if child_attempt_idx > 0:
                                logging.info(
                                    f"Child node {child_rloc} last responded attempt: {child_last_attempt_reponded}, last responded detail level: {child_last_attempt_tlv_detail_level}")
                                logging.info(
                                    f"Child node {child_rloc} new attempt {child_attempt_idx+1}/{child_attempts_max} with tlv_detail_level {child_tlv_detail_level} {tlv_values} {child_detail_level_name} detail TLV set. ")

                            child_node = fetch_network_diag_for_device(
                                child_rloc,
                                meshlocal_prefix,
                                extaddr_map,
                                router_table_by_router_id,
                                ipv6_addresses,
                                child_tlv_detail_level
                            )

                            # If child_node is None, it means the child did not respond to the diagnostic query.
                            # If this is the first couple of attempts, it may be a sleeping child (MTD) that is not currently responsive.
                            # Retry a few times with increasing delay to give the child a chance to respond

                            if child_node is None:
                                logging.info(
                                    f"Child node {child_rloc} did not respond after {child_attempt_idx+1} attempts with tlv_detail_level {child_tlv_detail_level} {tlv_values} {child_detail_level_name}. Evaluating retry/exit conditions."
                                )

                                # If Nth call to fetch_network_diag_for_device returned None
                                # Add to topology map with default values and mark as unknown device. This way we can still have a record of the child in the topology map even if it did not respond to the diagnostic query, and we can still attempt to enrich its data with more detailed TLV sets on subsequent retries.
                                if child_attempt_idx == child_attempts_min - 1 or child_attempt_idx == child_attempts_max - 1:  # 1:
                                    # if child has not responded after 5 attempts with tlv_detail_level 1 (BASIC) then we will add it to the topology map with default values and mark it as an unknown device. This way we can still have a record of the child in the topology map even if it did not respond to the diagnostic query, and we can still attempt to enrich its data with more detailed TLV sets on subsequent retries.
                                    # if child has not responded after 5 attempts with tlv_detail_level 1 (BASIC) then we will add it to the topology map with default values and mark it as an unknown device. This way we can still have a record of the child in the topology map even if it did not respond to the diagnostic query, and we can still attempt to enrich its data with more detailed TLV sets on subsequent retries.
                                    if child_last_attempt_tlv_detail_level == -1 and child_last_attempt_reponded == -1:

                                        # Add with default values and mark as unknown device
                                        unknown_child = _build_unknown_device_record(
                                            child_rloc, "child", ipv6_addresses, omr_ipv6addr_prefix, meshlocal_prefix
                                        )
                                        _upsert_device_record(
                                            network_topology_map, unknown_child, extaddr_to_rloc)
                                        logging.info(
                                            f"Child node {child_rloc} did not respond after attempts: {child_attempt_idx+1}/{child_attempts_max} with tlv_detail_level {child_tlv_detail_level} {tlv_values} {child_detail_level_name}. Added to topology map under parent {rloc16} with default values and marked as unknown device."
                                        )

                                        logging.info(
                                            f"found {len(network_topology_map)} unique devices so far")

                                        # Checkpoint to file after each new record added to topology map
                                        # used in progressive loading in dashboard UI
                                        save_topology_to_json_file(
                                            network_topology_map, checkpoint_filepath)
                                        break

                                # If the previous call to fetch_network_diag_for_device returned None
                                # and the child_rloc has previous responded then break
                                if child_last_attempt_tlv_detail_level >= 0 and child_last_attempt_reponded >= 0:
                                    logging.info(
                                        f"Child node {child_rloc} last responded attempt: {child_last_attempt_reponded+1}, last responded detail level: {child_last_attempt_tlv_detail_level}. Skipping further attempts.")
                                    break

                            # Child responded, add to topology map
                            if child_node is not None:
                                child_last_attempt_reponded = child_attempt_idx
                                child_last_attempt_tlv_detail_level = child_tlv_detail_level

                                child_node["type"] = "Child"
                                # Add OMR IPv6 address to child record
                                if omr_ipv6addr_prefix:
                                    child_node["omr_ipv6_addr"] = util_network.find_omr_address_in_list(
                                        child_node.get(
                                            "ipv6_addrs", []), omr_ipv6addr_prefix
                                    )
                                else:
                                    child_node["omr_ipv6_addr"] = None

                                # Enrich device record with role classification and prefix-based flags
                                _enrich_device_role_and_prefix_flags(
                                    child_node, meshlocal_prefix, omr_ipv6addr_prefix
                                )

                                # Use _upsert_device_record to handle potential RLOC16 changes
                                _upsert_device_record(
                                    network_topology_map, child_node, extaddr_to_rloc)

                                logging.info(f"Child node {child_rloc} responded. attempts: {child_attempt_idx+1}/{child_attempts_max} Added child node {child_rloc} {child_node.get('extaddr', 'Unknown')} {child_node.get('device_label', 'Unknown')} under parent {rloc16} {network_topology_node.get('extaddr', 'Unknown')} {network_topology_node.get('device_label', 'Unknown')} to topology map.  attempts: {child_attempt_idx+1}/{child_attempts_max}. detail level: {child_tlv_detail_level} TLVs: {tlv_values}")
                                logging.info(
                                    f"found {len(network_topology_map)} unique devices so far")
                                # Checkpoint to file after each new record added to topology map
                                # used in progressive loading in dashboard UI
                                save_topology_to_json_file(
                                    network_topology_map, checkpoint_filepath)

                                # Exit fetch fast if child responded, no need to retry further attempts for this child node, since we already got a response and added it to the topology map. This can help reduce overall runtime and network load by avoiding unnecessary retries for child nodes that are responsive.
                                if child_fetch_fast_mode:
                                    if child_last_attempt_tlv_detail_level >= 0 and child_last_attempt_reponded >= 0:
                                        logging.info(
                                            f"Child node {child_rloc} responded. Fetch fast mode enabled. Skipping further attempts.  attempts: {child_attempt_idx+1}/{child_attempts_max}, last responded detail level: {child_last_attempt_tlv_detail_level}.")
                                        break

                            # Sleep - if last iteration skip sleep to avoid unnecessary delay before giving up and adding with default values
                            # SED MTD children may not respond to diagnostic queries if they are sleeping, so retry a few times with increasing delay to give them a chance to respond. If they still do not respond after the retries, add them to the topology map with default values and mark as unknown devices.
                            if child_attempt_idx < child_attempts_max - 1:
                                # Increase delay with each retry
                                c_delay = child_delay_start * \
                                    (child_attempt_idx + 1)
                                c_delay = min(c_delay, child_delay_max)

                                if child_node is not None:
                                    logging.info(
                                        f"Child node {child_rloc} responded. attempts: {child_attempt_idx+1}/{child_attempts_max}, attempting more data in {c_delay} seconds...")
                                else:
                                    logging.info(
                                        f"Child node {child_rloc} did not respond. attempts: {child_attempt_idx+1}/{child_attempts_max}. attempting in {c_delay} seconds...")

                                time.sleep(c_delay)

                        

    logging.info(
        f"Poll consolidation complete: {len(network_topology_map)} unique devices found in topology map."
    )

    return network_topology_map


def print_network_diag_topology(topology):
    """Prints the network topology to console in tree format."""
    logging.debug("\n--- Thread Network Topology ---\n")
    for rloc, data in topology.items():
        logging.debug(f"Parent [RLOC: {rloc}] (Ext: {data['extaddr']})")
        logging.debug(
            f"  Thread Stack Version: {data.get('thread_stack_version', 'Unknown')}"
        )

        if data.get("ipv6_addrs"):
            logging.debug(f"  IPv6 Addresses ({len(data['ipv6_addrs'])}):")
            for ipv6 in data["ipv6_addrs"]:
                logging.debug(f"    - {ipv6}")

        if data.get("omr_ipv6_addr"):
            logging.debug(f"  OMR IPv6 Address: {data['omr_ipv6_addr']}")

        if data.get("children"):
            logging.debug(f"  Children ({len(data['children'])}):")
            for child in data["children"]:
                # Validate child is a dict
                if not isinstance(child, dict):
                    logging.warning(
                        f"Child is not a dict: {type(child)}, value: {child}. Skipping.")
                    continue
                logging.debug(
                    f"    - ID: {child.get('id')}, Timeout: {child.get('timeout')}, Link Quality: {child.get('link_quality')}"
                )
                if child.get("mode"):
                    mode = child["mode"]
                    logging.debug(
                        f"      Mode: RxOnWhenIdle={mode.get('rx_on_when_idle')}, DeviceType={mode.get('device_type')}, NetworkData={mode.get('network_data')}"
                    )
            logging.debug(
                f"    Total Children: {data.get('total_children', 0)}")

        if data.get("mac_counters"):
            logging.debug("  MAC Counters:")
            for key, value in sorted(data["mac_counters"].items()):
                logging.debug(f"    {key}: {value}")

        if data.get("mle_counters"):
            logging.debug("  MLE Counters:")
            for key, value in sorted(data["mle_counters"].items()):
                logging.debug(f"    {key}: {value}")

        if data.get("time_statistics"):
            logging.debug("  Time Statistics:")
            time_stats = data["time_statistics"]
            if time_stats:
                total_time = time_stats.get("tracked_time", 0)
                router_pct = (
                    (time_stats.get("router_time", 0) / total_time * 100)
                    if total_time > 0
                    else 0
                )
                child_pct = (
                    (time_stats.get("child_time", 0) / total_time * 100)
                    if total_time > 0
                    else 0
                )
                logging.debug(
                    f"    Tracked: {time_stats.get('tracked_time')}, Router: {time_stats.get('router_time')} ({router_pct:.1f}%), Child: {time_stats.get('child_time')} ({child_pct:.1f}%)"
                )
                logging.debug(
                    f"    Disabled: {time_stats.get('disabled_time')}, Detached: {time_stats.get('detached_time')}, Leader: {time_stats.get('leader_time')}"
                )

        logging.debug("")


def save_topology_to_json_file(
    data, filename=NETWORKDIAG_FETCH_ALL_FILENAME
):
    """Converts dict format to list format and saves to JSON."""
    network_map = []

    for rloc, data in data.items():
        # Set the order of priority fields in the output JSON for better readability, with key fields like rloc16, extaddr, device_label at the top, and then the more detailed fields like mode, ipv6_addrs, children, counters grouped together below. This way when looking at the JSON output, it's easier to quickly identify the key information about each node before diving into the more detailed data.
        network_node = {
            "rloc16": rloc,
            "extaddr": data["extaddr"],
            "omr_ipv6_addr": data.get("omr_ipv6_addr"),
            "device_label": data.get("device_label", f"Unknown-{rloc}"),
            "tlv_values": data.get("tlv_values", []),
            "eui64": data.get("eui64"),
            "thread_stack_version": data.get("thread_stack_version", "Unknown"),
            "thread_version": data.get("thread_version", "Unknown"),
            "ver": data.get("ver", "Unknown"),
            "mode": data.get("mode", {}),
            "ipv6_addrs": data.get("ipv6_addrs", []),
            "type": data.get("type", "Unknown"),
            "role": data.get("role", "Unknown"),
            "br": data.get("br", None),
            "is_border_router": data.get("is_border_router", None),
            "is_router": data.get("is_router", None),
            "leader": data.get("leader", None),
            "connectivity": data.get("connectivity", {}),
            "leader_data": data.get("leader_data", {}),
            "vendor_name": data.get("vendor_name"),
            "vendor_model": data.get("vendor_model"),
            "vendor_sw_version": data.get("vendor_sw_version"),
            "route": data.get("route", {}),
            "children": data.get("children", []),
            "total_children": data.get("total_children", 0),
            "mac_counters": data.get("mac_counters", {}),
            "mle_counters": data.get("mle_counters", {}),
            "time_statistics": data.get("time_statistics", {}),
        }

        network_map.append(network_node)

    save_json_atomic(convert_keys_to_camel_case(network_map), filename)
    logging.info(
        f"Successfully exported {len(network_map)} records for topology to {filename}")
    logging.debug("Saved topology data into %s as JSON:\n%s",
                  filename, json.dumps(network_map, indent=4))


def main_multicast_network(argv: Sequence[str] | None = None) -> int:
    """Entry point for multicast-network subcommand (ff03::1)."""

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    logging.info(
        "Initiating Thread Network Topology Scan (Multicast Network)...\n")

    parser = argparse.ArgumentParser(
        description="Thread Network Diagnostic Topology – Multicast Network (ff03::1)"
    )
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    args = parser.parse_args(argv)
    td_data_dir = resolve_data_dir(data_dir=args.datadir)

    # Load extaddr to device label mapping from JSON file
    extaddr_json_filename = data_file_path(
        EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir
    )
    if os.path.exists(extaddr_json_filename):
        extaddr_map = load_extaddr_device_label_map(extaddr_json_filename)
    else:
        extaddr_map = {}

    thread_network_info = util_network.fetch_thread_network_info()

    # Get all active routers (potential parents)
    router_table_data = fetch_and_parse_router_table(extaddr_map)

    # Build a dict of router_table_data indexed by router_id
    router_table_by_router_id = {router.get(
        "router_id"): router for router in router_table_data if router.get("router_id") is not None}

    # Get the multicast topology data
    data = fetch_network_diag_topology_multicast_network(
        extaddr_map, thread_network_info, router_table_by_router_id
    )

    # Print the topology in tree format to console
    print_network_diag_topology(data)

    # Save the topology as JSON to file
    save_json_filename = data_file_path(
        NETWORKDIAG_MULTICAST_NETWORK_FILENAME, td_data_dir
    )
    save_topology_to_json_file(data, save_json_filename)

    # Print the raw topology dictionary as JSON to console for debugging
    logging.debug(json.dumps(data, indent=4))

    return 0


def main_multicast_neighbors(argv: Sequence[str] | None = None) -> int:
    """Entry point for multicast-neighbors subcommand (ff02::1)."""

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    logging.info(
        "Initiating Thread Network Topology Scan (Multicast Neighbors)...\n")

    parser = argparse.ArgumentParser(
        description="Thread Network Diagnostic Topology – Multicast Neighbors (ff02::1)"
    )
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    args = parser.parse_args(argv)
    td_data_dir = resolve_data_dir(data_dir=args.datadir)

    # Load extaddr to device label mapping from JSON file
    extaddr_json_filename = data_file_path(
        EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir
    )
    if os.path.exists(extaddr_json_filename):
        extaddr_map = load_extaddr_device_label_map(extaddr_json_filename)
    else:
        extaddr_map = {}

    thread_network_info = util_network.fetch_thread_network_info()

    # Get all active routers (potential parents)
    router_table_data = fetch_and_parse_router_table(extaddr_map)

    # Build a dict of router_table_data indexed by router_id
    router_table_by_router_id = {router.get(
        "router_id"): router for router in router_table_data if router.get("router_id") is not None}

    # Get the multicast topology data
    data = fetch_network_diag_topology_multicast_neighbors(
        extaddr_map, thread_network_info, router_table_by_router_id
    )

    # Print the topology in tree format to console
    logging.debug("Final multicast neighbors topology data structure:\n%s", json.dumps(
        data, indent=4))
    print_network_diag_topology(data)

    # Save the topology as JSON to file
    save_json_filename = data_file_path(
        NETWORKDIAG_MULTICAST_NEIGHBORS_FILENAME, td_data_dir
    )
    save_topology_to_json_file(data, save_json_filename)

    # Print the raw topology dictionary as JSON to console for debugging
    logging.debug("Raw multicast neighbors topology data as JSON:\n%s",
                  json.dumps(data, indent=4))

    return 0


def main_fetch_all(argv: Sequence[str] | None = None) -> int:
    """Main entry point with optional command-line arguments."""

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="Thread Network Diagnostic Topology")
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    children_group = parser.add_mutually_exclusive_group()
    children_group.add_argument(
        "-c",
        "--children",
        dest="expand_children",
        action="store_true",
        default=True,
        help="Expand and include child nodes in the topology map (default)",
    )
    children_group.add_argument(
        "-cno",
        "--children-no",
        dest="expand_children",
        action="store_false",
        help="Do not expand child nodes in the topology map",
    )
    args = parser.parse_args(argv)
    td_data_dir = resolve_data_dir(data_dir=args.datadir)

    # Load extaddr to nodename mapping from JSON file
    extaddr_json_filename = data_file_path(
        EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir
    )

    # Check if file exists before parsing
    if os.path.exists(extaddr_json_filename):
        extaddr_map = load_extaddr_device_label_map(extaddr_json_filename)
    else:
        extaddr_map = {}

    try:
        thread_network_info = util_network.fetch_thread_network_info()

        expand_children = args.expand_children
        logging.info(f"Expand children is set to {expand_children}")

        # Get the networkdiagnostic topology data
        networkdiagnostic_topology_data = fetch_network_diag_topology(
            extaddr_map, thread_network_info, expand_children=expand_children, td_data_dir=td_data_dir
        )

        # print the topology in tree format to console
        print_network_diag_topology(networkdiagnostic_topology_data)

        # save the topology as JSON to file
        save_json_filepath = data_file_path(
            NETWORKDIAG_FETCH_ALL_FILENAME, td_data_dir
        )
        save_topology_to_json_file(
            networkdiagnostic_topology_data, save_json_filepath
        )

        # Print the raw topology dictionary as JSON to console for debugging
        logging.debug("Raw topology data as JSON:\n%s", json.dumps(
            networkdiagnostic_topology_data, indent=4))
        return 0
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logging.error(
            f"Invalid payload while collecting networkdiag-topology: {exc}")
        return 5
    except Exception as exc:
        import traceback
        logging.error(
            f"Runtime failure while collecting networkdiag-topology: {exc}")
        logging.error(f"Traceback: {traceback.format_exc()}")
        return 3


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point with optional command-line arguments."""

    return main_fetch_all(argv)


if __name__ == "__main__":
    sys.exit(main())
