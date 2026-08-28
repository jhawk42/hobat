import argparse
import os
import re
import json
import sys
import time
import logging

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal, Sequence

from td_const import (
    EXTADDR_DEVICE_LABEL_MAP_FILENAME,
    OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME,
    OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
    OTBR_CLI_NETWORKDIAG_MULTICAST_NEIGHBORS_FILENAME,
    OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME,
    OTBR_CLI_ROUTER_TABLE_FILENAME,
    TD_DATA_DIR_ARG_HELP,
    TD_THREAD_MULTICAST_ADDRESSES_LINK_LOCAL_ALL_FTDS_AND_MEDS,
    TD_THREAD_MULTICAST_ADDRESSES_MESH_LOCAL_ALL_FTDS_AND_MEDS,
)
import util_ot_ctl
import util_network
from util_data import data_file_path, resolve_data_dir, save_json_atomic, create_checkpoint_filename
from td_json_key_normalizer import convert_keys_to_camel_case
from td_device_fields import get_canonical_rloc16
from extaddr_device_label_map import load_extaddr_device_label_map
from otbr_cli_router_table import fetch_and_parse_router_table

from otbr_cli_networkdiag_util import (
    TLV_VALUES_DETAILED,
    TLV_VALUES_MEDIUM,
    TLV_VALUES_BASIC,
    TLV_VALUES_CHILD_DETAILED,
    TLV_VALUES_CHILD_MEDIUM_MAC_MLE,
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


def fetch_network_diag_for_device(
    rloc16, rloc_prefix, extaddr_map=None, router_table_by_router_id=None, ipv6_addresses=None, tlv_detail_level=6
):
    """
    Queries and parses network diagnostic data for a single router.

    Args:
        rloc16: RLOC16 value for the router (e.g., "0x0400")
        rloc_prefix: IPv6 prefix for building RLOC IPv6 address
        extaddr_map: Dictionary mapping extended addresses to node names
        router_table_by_router_id: Dictionary of router table entries by router ID
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
    checkpoint_filepath: str | None = None,
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
        router_table_by_router_id: Optional dict mapping router IDs to router info
        checkpoint_filepath: Optional path to checkpoint file for saving intermediate results (default: None)

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

            # Add OMR IPv6 address if prefix available
            if omr_ipv6addr_prefix:
                if device_record["omr_ipv6_addr"] == None:
                    device_record["omr_ipv6_addr"] = util_network.find_omr_address_in_list(
                        device_record.get(
                            "ipv6_addrs", []), omr_ipv6addr_prefix
                    )
            else:
                device_record["omr_ipv6_addr"] = None

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

        # Save checkpoint if filepath provided
        if checkpoint_filepath:
            # Re-key by rloc16
            checkpoint_result = {}
            for record in consolidated.values():
                rloc16 = record.get("rloc16", "Unknown")

                # Store in result, keyed by rloc16
                checkpoint_result[rloc16] = record
            save_topology_to_json_file(checkpoint_result, checkpoint_filepath)
            logging.info(
                "event=checkpoint_write command=otbr-cli networkdiag multicast checkpoint_file=%s records=%d stage=multicast",
                checkpoint_filepath,
                len(checkpoint_result) if isinstance(
                    checkpoint_result, dict) else 0,
            )

        # Sleep before next retry (but not after the last retry)
        if attempt_idx < attempts_max - 1:
            # tlv_detail_level = max(1, tlv_detail_level - 1)  # Floor at 1

            r_delay = delay_start
            time.sleep(r_delay)

    # Finalize the consolidated dict

    # Re-key by rloc16
    result = {}
    for record in consolidated.values():
        rloc16 = record.get("rloc16", "Unknown")

        # Store in result, keyed by rloc16
        result[rloc16] = record

    logging.info(
        f"Multicast consolidation complete: {len(result)} devices (keyed by rloc16)"
    )
    return result


def fetch_network_diag_topology_multicast_network(
    extaddr_map: dict | None = None,
    thread_network_info: dict | None = None,
    router_table_by_router_id: dict | None = None,
    checkpoint_filepath: str | None = None,
    final_output_path: str | None = None,
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
    result = fetch_network_diag_multicast(
        multicast_addr=TD_THREAD_MULTICAST_ADDRESSES_MESH_LOCAL_ALL_FTDS_AND_MEDS,  # "ff03::1"
        extaddr_map=extaddr_map,
        thread_network_info=thread_network_info,
        router_table_by_router_id=router_table_by_router_id,
        checkpoint_filepath=checkpoint_filepath
    )
    if checkpoint_filepath is not None:
        save_topology_to_json_file(result, checkpoint_filepath)
        logging.info(
            "event=checkpoint_write command=otbr-cli networkdiag multicast-network checkpoint_file=%s records=%d stage=final",
            checkpoint_filepath,
            len(result),
        )
    if final_output_path is not None:
        save_topology_to_json_file(result, final_output_path)
    return result


def fetch_network_diag_topology_multicast_neighbors(
    extaddr_map: dict | None = None,
    thread_network_info: dict | None = None,
    router_table_by_router_id: dict | None = None,
    checkpoint_filepath: str | None = None,
    final_output_path: str | None = None,
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
        checkpoint_filepath: Optional path to checkpoint file for saving intermediate results (default: None)
    Returns:
        Dict keyed by rloc16 with device records from immediate one-hop neighbors
    """
    result = fetch_network_diag_multicast(
        multicast_addr=TD_THREAD_MULTICAST_ADDRESSES_LINK_LOCAL_ALL_FTDS_AND_MEDS,  # "ff02::1"
        extaddr_map=extaddr_map,
        thread_network_info=thread_network_info,
        router_table_by_router_id=router_table_by_router_id,
        checkpoint_filepath=checkpoint_filepath
    )
    if checkpoint_filepath is not None:
        save_topology_to_json_file(result, checkpoint_filepath)
        logging.info(
            "event=checkpoint_write command=otbr-cli networkdiag multicast-neighbors checkpoint_file=%s records=%d stage=final",
            checkpoint_filepath,
            len(result),
        )
    if final_output_path is not None:
        save_topology_to_json_file(result, final_output_path)
    return result


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
        "extaddr": f"Offline-{rloc16}",
        "rloc16": rloc16,
        "device_label": f"Offline-{rloc16}",
        "mode": {},
        "ipv6_addrs": ipv6_addrs,
        "omr_ipv6_addr": omr_ipv6_addr,
    }

    # Defaults for last attempt response and TLV detail level
    record["last_attempt_responded"] = -1
    record["last_attempt_tlv_detail_level"] = -1

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


def fetch_network_diag_topology_router_table(
    extaddr_map: dict,
    network_topology_map: dict,
    extaddr_to_rloc: dict,
    checkpoint_filepath: str | None,
    final_output_path: str | os.PathLike | None = None,
) -> tuple[list, list, dict]:
    """Fetches router table data and merges router records into topology map.

    The nested router-table collector atomically persists its standalone result
    before this stage consumes and returns that collection when final_output_path
    is supplied.

    Returns:
        Tuple of (router_table_data, router_rlocs, router_table_by_router_id)
    """
    router_table_data = fetch_and_parse_router_table(
        extaddr_map,
        output_path=final_output_path,
    )
    if router_table_data is None:
        logging.warning("Router table is None. No routers found.")
        return [], [], {}

    network_topology_map_routers = {}

    logging.info(f"Router table has {len(router_table_data)} entries")

    # Extract RLOC16 values for all routers in the router table
    router_rlocs = []
    for router in router_table_data:
        if not isinstance(router, dict):
            logging.warning(
                f"Router in router_table_data is not a dict: {type(router)}, value: {router}. Skipping."
            )
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

    # Conform router table data into topology records
    for router in router_table_data:
        if not isinstance(router, dict):
            continue
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

    # Merge router table records into main topology map, keyed by rloc16
    for _, device_record in network_topology_map_routers.items():
        _upsert_device_record(network_topology_map,
                              device_record, extaddr_to_rloc)

    logging.info(
        f"After merging router table data, topology map has {len(network_topology_map)} devices (keyed by rloc16)"
    )

    # Checkpoint to file
    save_topology_to_json_file(network_topology_map, checkpoint_filepath)

    return router_table_data, router_rlocs, router_table_by_router_id


def fetch_network_diag_topology_meshdiag_topology(
    extaddr_map: dict,
    thread_network_info: dict | None,
    network_topology_map: dict,
    extaddr_to_rloc: dict,
    checkpoint_filepath: str | None,
    final_output_path: str | os.PathLike | None = None,
) -> list | None:
    """Fetches, atomically persists, and merges meshdiag topology data.

    Persistence is enabled only when final_output_path is supplied.
    """

    meshdiag_topology_data = get_meshdiag_topology(
        extaddr_map,
        thread_network_info,
        output_path=final_output_path,
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
                        f"meshdiag ipv6_addrs for {rloc16} is not a list: {type(ipv6_addrs)}. Converting."
                    )
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

        for _, device_record in network_topology_map_meshdiag_routers.items():
            _upsert_device_record(network_topology_map,
                                  device_record, extaddr_to_rloc)

        # Checkpoint to file
        save_topology_to_json_file(network_topology_map, checkpoint_filepath)
    else:
        logging.warning(
            "Meshdiag topology data is None. No meshdiag data to merge.")

    return meshdiag_topology_data


def fetch_network_diag_topology_ipv6_addresses(
    meshdiag_topology_data: list | None,
) -> dict:
    """Builds IPv6 address map keyed by rloc16 for topology enrichment."""
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
            "Meshdiag topology data is None. Cannot extract IPv6 addresses from meshdiag data."
        )
        ipv6_addresses = fetch_ipv6_addresses()
        ipv6_addresses = ipv6_addresses if ipv6_addresses else {}

    return ipv6_addresses


def fetch_network_diag_topology_multicast(
    extaddr_map: dict,
    thread_network_info: dict | None,
    router_table_by_router_id: dict,
    network_topology_map: dict,
    extaddr_to_rloc: dict,
    checkpoint_filepath: str | None,
    final_output_path: str | os.PathLike | None = None,
) -> dict:
    """Fetches, atomically persists, and merges multicast topology data.

    Persistence is enabled only when final_output_path is supplied.
    """
    
    network_topology_map_multicast = fetch_network_diag_topology_multicast_network(
        extaddr_map,
        thread_network_info,
        router_table_by_router_id,
        final_output_path=final_output_path,
    )

    if network_topology_map_multicast:
        logging.info(
            f"Multicast topology map has {len(network_topology_map_multicast)} devices (keyed by rloc16)"
        )

        # Merge multicast topology data into main topology map, keyed by rloc16
        for _, device_record in network_topology_map_multicast.items():
            _upsert_device_record(network_topology_map,
                                  device_record, extaddr_to_rloc)
        logging.info(
            f"After merging multicast data, topology map has {len(network_topology_map)} devices (keyed by rloc16)"
        )

        # Checkpoint thread device data to file after multicast collection before starting direct queries.
        save_topology_to_json_file(network_topology_map, checkpoint_filepath)
    else:
        logging.warning("Multicast topology map is empty or None")

    return network_topology_map_multicast


def fetch_network_diag_topology_detail_routers(
    router_rlocs: list,
    network_topology_map: dict,
    extaddr_map: dict,
    router_table_by_router_id: dict,
    ipv6_addresses: dict,
    omr_ipv6addr_prefix: str | None,
    meshlocal_prefix: str | None,
    extaddr_to_rloc: dict,
    checkpoint_filepath: str | None,
) -> None:
    """Fetches per-router diagnostics and merges results into the topology map."""
    for rloc16 in router_rlocs:
        try:
            # Attempt logic for networkdiagnostic get in case of transient errors or unresponsive nodes, 
            # Retry N times with some delay before giving up and adding with default values
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
                        f"RLOC16 {rloc16} has invalid data type in topology map: {type(network_topology_node)}. Expected dict, got {network_topology_node}. Will re-fetch."
                    )
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
                f"rloc16: {rloc16}, network_topology_map keys: {list(network_topology_map.keys())[:10]}"
            )
            raise

        # If record does exist then SKIP direct call attempts but still check if we need to expand children for this node if expand_children is True, since the multicast query might not have included the child table data for this node if it was using a simpler TLV set. So we can still enrich the existing node data with child information if needed by doing a direct query just for the child table TLV, but we can skip the full diagnostic query with all TLVs since we already have that data from the multicast response.

        # If record does not exist in topology map the direct query with attempts
        if not record_exists:
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
                    rloc16,
                    meshlocal_prefix,
                    extaddr_map,
                    router_table_by_router_id,
                    ipv6_addresses,
                    tlv_detail_level,
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
                        f"Waiting for {l_delay} seconds before next retry...{attempt_idx + 1} of {attempts}"
                    )
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
                    f"network_topology_node type: {type(network_topology_node)}, value: {network_topology_node}"
                )
                raise

            # Merge with existing data in topology map if present (e.g. from multicast query) to enrich the node data with any missing fields that we couldn't get from the direct query due to unresponsive node or TLV issues, this way we can have the most complete data possible for each node by combining the results from both the multicast and direct queries, and we can also handle cases where some nodes might only respond to one of the query types but not the other.
            is_new_record = rloc16 not in network_topology_map
            _upsert_device_record(
                network_topology_map, network_topology_node, extaddr_to_rloc
            )

            if is_new_record:
                logging.info(
                    f"Added router node {rloc16} {network_topology_node.get('extaddr', 'Unknown')} {network_topology_node.get('device_label', 'Unknown')} to topology map. {attempt_idx+1}/{attempts} attempts.  TLV detail level: {tlv_detail_level} {get_tlv_values_for_detail_level(tlv_detail_level)}"
                )
                logging.info(
                    f"Found {len(network_topology_map)} unique devices so far"
                )
                # Checkpoint to file after each new record added to topology map
                # used in progressive loading in dashboard UI
                save_topology_to_json_file(
                    network_topology_map, checkpoint_filepath)


@dataclass(frozen=True)
class ChildFetchAttempt:
    index: int
    detail_level: int
    tlv_values: str
    delay_after_failure_s: float | None

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("Child fetch attempt index cannot be negative")
        if self.detail_level not in (1, 2, 3, 4):
            raise ValueError("Child fetch attempt has an invalid detail level")
        if self.tlv_values != get_tlv_values_for_detail_level(self.detail_level):
            raise ValueError("Child fetch attempt TLVs do not match its detail level")
        if self.delay_after_failure_s is not None and self.delay_after_failure_s < 0:
            raise ValueError("Child fetch attempt delay cannot be negative")


@dataclass(frozen=True)
class ChildFetchPolicy:
    mode: Literal["fast", "detail"]
    minimum_attempts: int
    attempts: tuple[ChildFetchAttempt, ...]
    stop_after_first_response: bool
    satisfied_detail_level: int = 4

    def __post_init__(self) -> None:
        if not self.attempts or not 1 <= self.minimum_attempts <= len(self.attempts):
            raise ValueError("Child fetch policy has an invalid attempt range")
        if tuple(attempt.index for attempt in self.attempts) != tuple(range(len(self.attempts))):
            raise ValueError("Child fetch attempt indexes must be contiguous")
        if self.attempts[-1].delay_after_failure_s is not None:
            raise ValueError("Final child fetch attempt cannot have a delay")


@dataclass(frozen=True)
class ChildFetchTarget:
    parent_rloc16: str
    child_rloc16: str
    child_record: dict[str, Any]


@dataclass(frozen=True)
class ChildFetchOutcome:
    target: ChildFetchTarget
    policy_mode: str
    observations: tuple[dict[str, Any], ...]
    attempted: tuple[ChildFetchAttempt, ...]
    terminal_reason: Literal[
        "responded", "exhausted", "already-satisfied", "retained-prior"
    ]


@dataclass(frozen=True)
class ChildMutation:
    changed: bool
    kind: Literal["added", "updated", "moved", "fallback", "unchanged"]
    rloc16: str


def build_child_fetch_policies(
    fast_enabled: bool,
    detail_enabled: bool,
    delay_start: float = 0.25,
    delay_max: float = 2.0,
) -> tuple[ChildFetchPolicy, ...]:
    policies = []
    schedules = (
        ("fast", 2, (1, 1), True),
        ("detail", 3, (1, 2, 3, 3, 4), False),
    )
    for mode, minimum_attempts, levels, stop_after_first in schedules:
        if (mode == "fast" and not fast_enabled) or (mode == "detail" and not detail_enabled):
            continue
        attempts = tuple(
            ChildFetchAttempt(
                index=index,
                detail_level=level,
                tlv_values=get_tlv_values_for_detail_level(level),
                delay_after_failure_s=(
                    min(delay_start * (index + 1), delay_max)
                    if index < len(levels) - 1 else None
                ),
            )
            for index, level in enumerate(levels)
        )
        policies.append(ChildFetchPolicy(mode, minimum_attempts, attempts, stop_after_first))
    return tuple(policies)


def collect_child_fetch_targets(
    router_rlocs: Sequence[str], topology_map: dict
) -> tuple[ChildFetchTarget, ...]:
    targets = []
    seen = set()
    for parent_rloc16 in router_rlocs:
        parent = topology_map.get(parent_rloc16)
        if not isinstance(parent, dict):
            logging.warning("Router node %s not found in topology map when attempting to expand children. Skipping child expansion for this node.", parent_rloc16)
            continue
        children = parent.get("children", [])
        if not isinstance(children, list):
            logging.warning("Children for %s is not a list: %s. Converting to list.", parent_rloc16, type(children))
            children = [children] if children else []
        for child in children:
            if not isinstance(child, dict):
                logging.warning("Child for %s is not a dict: %s, value: %s. Skipping.", parent_rloc16, type(child), child)
                continue
            child_rloc16 = get_canonical_rloc16(child)
            if not child_rloc16 or child_rloc16 in seen:
                continue
            seen.add(child_rloc16)
            targets.append(ChildFetchTarget(parent_rloc16, child_rloc16, deepcopy(child)))
    return tuple(targets)


def fetch_child_with_retries(
    target: ChildFetchTarget,
    policy: ChildFetchPolicy,
    prior_state: dict,
    fetch: Callable[[ChildFetchTarget, ChildFetchAttempt], dict | None],
    delay: Callable[[float], None],
) -> ChildFetchOutcome:
    if prior_state.get("last_attempt_tlv_detail_level", -1) >= policy.satisfied_detail_level:
        return ChildFetchOutcome(target, policy.mode, (), (), "already-satisfied")

    observations = []
    attempted = []
    for attempt in policy.attempts:
        attempted.append(attempt)
        observation = fetch(target, attempt)
        if observation is not None:
            copied = deepcopy(observation)
            copied["last_attempt_responded"] = attempt.index
            copied["last_attempt_tlv_detail_level"] = attempt.detail_level
            observations.append(copied)
            if policy.stop_after_first_response:
                return ChildFetchOutcome(target, policy.mode, tuple(observations), tuple(attempted), "responded")
            continue

        if observations or (
            prior_state.get("last_attempt_responded", -1) >= 0
            and prior_state.get("last_attempt_tlv_detail_level", -1) >= 0
        ):
            return ChildFetchOutcome(target, policy.mode, tuple(observations), tuple(attempted), "retained-prior")
        if attempt.index == policy.minimum_attempts - 1 or attempt.index == len(policy.attempts) - 1:
            return ChildFetchOutcome(target, policy.mode, tuple(observations), tuple(attempted), "exhausted")
        if attempt.delay_after_failure_s is not None:
            delay(attempt.delay_after_failure_s)

    return ChildFetchOutcome(target, policy.mode, tuple(observations), tuple(attempted), "responded")


def reconcile_child_fetch_outcome(
    outcome: ChildFetchOutcome,
    topology_map: dict,
    extaddr_to_rloc: dict,
    ipv6_addresses: dict,
    omr_ipv6addr_prefix: str | None,
    meshlocal_prefix: str | None,
) -> ChildMutation:
    before = deepcopy(topology_map)
    prior_extaddr_rlocs = dict(extaddr_to_rloc)
    mutation_kind: Literal["added", "updated", "moved", "fallback", "unchanged"] = "unchanged"

    for observation in outcome.observations:
        child_node = deepcopy(observation)
        child_node["type"] = "child"
        _enrich_device_role_and_prefix_flags(child_node, meshlocal_prefix, omr_ipv6addr_prefix)
        extaddr = child_node.get("extaddr")
        if extaddr and prior_extaddr_rlocs.get(extaddr) not in (None, child_node.get("rloc16")):
            mutation_kind = "moved"
        elif child_node.get("rloc16") not in topology_map and mutation_kind != "moved":
            mutation_kind = "added"
        elif mutation_kind not in ("moved", "added"):
            mutation_kind = "updated"
        _upsert_device_record(topology_map, child_node, extaddr_to_rloc)

    if not outcome.observations and outcome.terminal_reason == "exhausted":
        existing = topology_map.get(outcome.target.child_rloc16)
        known = (
            isinstance(existing, dict)
            and existing.get("extaddr")
            and not str(existing["extaddr"]).startswith(("Unknown-", "Offline-"))
        )
        if not known:
            fallback = _build_unknown_device_record(
                outcome.target.child_rloc16, "child", ipv6_addresses,
                omr_ipv6addr_prefix, meshlocal_prefix,
            )
            _upsert_device_record(topology_map, fallback, extaddr_to_rloc)
            mutation_kind = "fallback"

    changed = before != topology_map
    return ChildMutation(changed, mutation_kind if changed else "unchanged", outcome.target.child_rloc16)


def notify_child_checkpoint(
    mutation: ChildMutation,
    topology_map: dict,
    checkpoint_filepath: str | None,
    save: Callable[[dict, str | None], None] | None = None,
) -> None:
    if mutation.changed:
        (save or save_topology_to_json_file)(topology_map, checkpoint_filepath)


def fetch_network_diag_topology_expand_children(
    expand_children: bool,
    router_rlocs: list,
    network_topology_map: dict,
    extaddr_map: dict,
    router_table_by_router_id: dict,
    ipv6_addresses: dict,
    omr_ipv6addr_prefix: str | None,
    meshlocal_prefix: str | None,
    extaddr_to_rloc: dict,
    checkpoint_filepath: str | None,
    child_fetch_fast_mode_default: bool = True,
    child_fetch_detail_mode_default: bool = False,
) -> None:
    """Expands child-node diagnostics and merges child records into the topology map."""
    if not expand_children:
        return

    policies = build_child_fetch_policies(
        child_fetch_fast_mode_default, child_fetch_detail_mode_default
    )
    targets = collect_child_fetch_targets(router_rlocs, network_topology_map)

    for policy in policies:
        for target in targets:
            prior_state = network_topology_map.get(target.child_rloc16, {})
            if not isinstance(prior_state, dict):
                logging.warning("Child node %s in topology map is not a dict. Skipping.", target.child_rloc16)
                continue

            outcome = fetch_child_with_retries(
                target,
                policy,
                prior_state,
                lambda current_target, attempt: fetch_network_diag_for_device(
                    current_target.child_rloc16,
                    meshlocal_prefix,
                    extaddr_map,
                    router_table_by_router_id,
                    ipv6_addresses,
                    attempt.detail_level,
                ),
                time.sleep,
            )
            mutation = reconcile_child_fetch_outcome(
                outcome,
                network_topology_map,
                extaddr_to_rloc,
                ipv6_addresses,
                omr_ipv6addr_prefix,
                meshlocal_prefix,
            )
            notify_child_checkpoint(
                mutation, network_topology_map, checkpoint_filepath,
                save_topology_to_json_file,
            )


def fetch_network_diag_topology(
    extaddr_map=None,
    thread_network_info=None,
    expand_children=True,
    td_data_dir=None,
    child_fetch_fast_mode_default: bool = True,
    child_fetch_detail_mode_default: bool = False,
    checkpoint_filepath=None,
    final_output_path=None,
):
    """Maps the full network topology and returns a Python dictionary.

    When td_data_dir is supplied, collection stages atomically refresh their
    established standalone snapshots before their results return to this
    aggregate collector. Aggregate checkpoints and final output remain separate.
    """

    # expand_children controls whether to perform additional queries for each router to get their child table data and include that in the topology map.
    # Set to True to also query and include child nodes in the topology map (will increase runtime significantly)
    # Set to False to only get parent nodes without expanding children

    # 1. Initialize topology map and extaddr tracking
    network_topology_map = {}

    # Create checkpoint filename for saving intermediate results during topology mapping.
    if checkpoint_filepath is None and td_data_dir is not None:
        checkpoint_filename = create_checkpoint_filename(
            OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME
        )
        checkpoint_filepath = data_file_path(checkpoint_filename, td_data_dir)
    logging.debug("Checkpoint filepath: %s", checkpoint_filepath)

    router_table_output_path = None
    meshdiag_output_path = None
    multicast_output_path = None
    if td_data_dir is not None:
        router_table_output_path = data_file_path(
            OTBR_CLI_ROUTER_TABLE_FILENAME,
            td_data_dir,
        )
        meshdiag_output_path = data_file_path(
            OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME,
            td_data_dir,
        )
        multicast_output_path = data_file_path(
            OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME,
            td_data_dir,
        )

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
    (
        router_table_data,
        router_rlocs,
        router_table_by_router_id,
    ) = fetch_network_diag_topology_router_table(
        extaddr_map,
        network_topology_map,
        extaddr_to_rloc,
        checkpoint_filepath,
        final_output_path=router_table_output_path,
    )

    # 5. Query meshdiag topology and merge router records
    meshdiag_topology_data = fetch_network_diag_topology_meshdiag_topology(
        extaddr_map,
        thread_network_info,
        network_topology_map,
        extaddr_to_rloc,
        checkpoint_filepath,
        final_output_path=meshdiag_output_path,
    )

    # 6. Build IPv6 map for lookup by RLOC16
    ipv6_addresses = fetch_network_diag_topology_ipv6_addresses(
        meshdiag_topology_data)

    # 7. Query multicast networkdiag and merge discovered records
    fetch_network_diag_topology_multicast(
        extaddr_map,
        thread_network_info,
        router_table_by_router_id,
        network_topology_map,
        extaddr_to_rloc,
        checkpoint_filepath,
        final_output_path=multicast_output_path,
    )

    # 7b. Query per-router details and merge
    fetch_network_diag_topology_detail_routers(
        router_rlocs,
        network_topology_map,
        extaddr_map,
        router_table_by_router_id,
        ipv6_addresses,
        omr_ipv6addr_prefix,
        meshlocal_prefix,
        extaddr_to_rloc,
        checkpoint_filepath,
    )

    # 8. Expand child nodes from router child tables
    fetch_network_diag_topology_expand_children(
        expand_children,
        router_rlocs,
        network_topology_map,
        extaddr_map,
        router_table_by_router_id,
        ipv6_addresses,
        omr_ipv6addr_prefix,
        meshlocal_prefix,
        extaddr_to_rloc,
        checkpoint_filepath,
        child_fetch_fast_mode_default,
        child_fetch_detail_mode_default,
    )

    logging.info(
        f"Poll consolidation complete: {len(network_topology_map)} unique devices found in topology map."
    )

    if final_output_path is not None:
        save_topology_to_json_file(network_topology_map, final_output_path)

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
    data, filename=OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME
):
    """Converts dict format to list format and saves to JSON."""
    if filename is None:
        return

    network_map = []

    for rloc, data in data.items():
        # Set the order of priority fields in the output JSON for better readability, 
        # with key fields like rloc16, extaddr, device_label at the top, and then the 
        # more detailed fields like mode, ipv6_addrs, children, counters grouped together below. 
        # This way when looking at the JSON output, it's easier to quickly identify the key information 
        # about each node before diving into the more detailed data.
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

    checkpoint_filename = create_checkpoint_filename(
        OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME
    )
    checkpoint_filepath = data_file_path(checkpoint_filename, td_data_dir)

    # Get the multicast topology data
    save_json_filename = data_file_path(
        OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME, td_data_dir
    )
    data = fetch_network_diag_topology_multicast_network(
        extaddr_map,
        thread_network_info,
        router_table_by_router_id,
        checkpoint_filepath=checkpoint_filepath,
        final_output_path=save_json_filename,
    )

    # Print the topology in tree format to console
    print_network_diag_topology(data)

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

    checkpoint_filename = create_checkpoint_filename(
        OTBR_CLI_NETWORKDIAG_MULTICAST_NEIGHBORS_FILENAME
    )
    checkpoint_filepath = data_file_path(checkpoint_filename, td_data_dir)

    # Get the multicast topology data
    save_json_filename = data_file_path(
        OTBR_CLI_NETWORKDIAG_MULTICAST_NEIGHBORS_FILENAME, td_data_dir
    )
    data = fetch_network_diag_topology_multicast_neighbors(
        extaddr_map,
        thread_network_info,
        router_table_by_router_id,
        checkpoint_filepath=checkpoint_filepath,
        final_output_path=save_json_filename,
    )

    # Print the topology in tree format to console
    logging.debug("Final multicast neighbors topology data structure:\n%s", json.dumps(
        data, indent=4))
    print_network_diag_topology(data)

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

    child_fast_group = parser.add_mutually_exclusive_group()
    child_fast_group.add_argument(
        "-cff",
        "--children-fetch-fast",
        dest="child_fetch_fast_mode_default",
        action="store_true",
        default=True,
        help="Enable fast child fetching with basic TLVs (default)",
    )
    child_fast_group.add_argument(
        "-cffno",
        "--children-fetch-fast-no",
        dest="child_fetch_fast_mode_default",
        action="store_false",
        help="Disable fast child fetching with basic TLVs",
    )

    child_detail_group = parser.add_mutually_exclusive_group()
    child_detail_group.add_argument(
        "-cfd",
        "--children-fetch-detail",
        dest="child_fetch_detail_mode_default",
        action="store_true",
        default=False,
        help="Enable detailed child fetching with higher TLV coverage",
    )
    child_detail_group.add_argument(
        "-cfdno",
        "--children-fetch-detail-no",
        dest="child_fetch_detail_mode_default",
        action="store_false",
        help="Disable detailed child fetching",
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

        save_json_filepath = data_file_path(
            OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME, td_data_dir
        )
        checkpoint_filepath = data_file_path(
            create_checkpoint_filename(OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME),
            td_data_dir,
        )

        # Get the networkdiagnostic topology data
        networkdiagnostic_topology_data = fetch_network_diag_topology(
            extaddr_map,
            thread_network_info,
            expand_children=expand_children,
            td_data_dir=td_data_dir,
            child_fetch_fast_mode_default=args.child_fetch_fast_mode_default,
            child_fetch_detail_mode_default=args.child_fetch_detail_mode_default,
            checkpoint_filepath=checkpoint_filepath,
            final_output_path=save_json_filepath,
        )

        # print the topology in tree format to console
        print_network_diag_topology(networkdiagnostic_topology_data)

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
    """Dispatch a networkdiag subcommand to its collector entry point."""

    parser = argparse.ArgumentParser(
        description="Thread Network Diagnostic Topology"
    )
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    subparsers = parser.add_subparsers(dest="networkdiag_command")
    subparsers.add_parser(
        "fetch-all",
        help="Scan and poll networkdiag topology (unicast, router-by-router)",
        add_help=False,
    )
    subparsers.add_parser(
        "multicast-network",
        help="Scan networkdiag topology via multicast to all Thread devices (ff03::1)",
        add_help=False,
    )
    subparsers.add_parser(
        "multicast-neighbors",
        help="Scan networkdiag topology via multicast to one-hop neighbors (ff02::1)",
        add_help=False,
    )

    args, command_argv = parser.parse_known_args(argv)
    if args.datadir is not None:
        command_argv = ["--datadir", args.datadir] + command_argv
    if args.networkdiag_command == "fetch-all":
        return main_fetch_all(command_argv)
    if args.networkdiag_command == "multicast-network":
        return main_multicast_network(command_argv)
    if args.networkdiag_command == "multicast-neighbors":
        return main_multicast_neighbors(command_argv)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
