import os
import subprocess
import re
import json
import logging
from typing import Sequence

from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
import util_ot_ctl
import util_network
from td_json_key_normalizer import convert_keys_to_camel_case
from extaddr_device_label_map import load_extaddr_device_label_map
from util_data import data_file_path, parse_datadir_from_argv, resolve_data_dir, save_json_atomic


def fetch_meshdiag_topology():
    """Retrieves the meshdiag topology IP6 addresses and children data from the network.
    Runs: ot-ctl meshdiag topology ip6-addrs children
    Returns: Raw output string from the command
    """
    try:
        # Executes the command: ot-ctl meshdiag topology ip6-addrs children
        # This command provides IPv6 addresses and children info for all routers
        output = util_ot_ctl.exec_ot_ctl(
            "meshdiag topology ip6-addrs children")
        logging.debug(
            f"[DEBUG] Output of 'meshdiag topology ip6-addrs children':\n{output}\n")

        return output
    except subprocess.CalledProcessError as e:
        logging.error(f"Error running ot-ctl: {e}")
        return None


def parse_meshdiag_topology_output(
    output, extaddr_map=None
):
    """
    Parses the meshdiag topology ip6-addrs children output into a list of router dictionaries.

    Extracts: id, rloc16, extaddr, ver, br flag, 3_links, 2_links, 1_links, ipv6_addrs, children

    Args:
        output: meshdiag topology ip6-addrs children text
        extaddr_map: Optional dictionary mapping extended MAC to node name
    """
    routers = []
    if extaddr_map is None:
        extaddr_map = {}

    # Split by 'id:' to get each router block (skip the first empty element)
    router_blocks = re.split(r"id:", output)[1:]

    for block in router_blocks:
        # Split block into lines
        lines = block.split("\n")
        first_line = lines[0].strip()

        # Extract router info from first line
        # Format: "08 rloc16:0x2000 ext-addr:1a7fbf0434e4f043 ver:5 - me - br"
        # Format: "25 rloc16:0x6400 ext-addr:8672766ae0578187" (without ver)
        # Note: "id:" prefix is already removed by the split() on "id:"
        match = re.match(
            r"(\d+)\s+rloc16:(0x[0-9a-fA-F]+)\s+ext-addr:([0-9a-fA-F]+)(?:\s+ver:(\d+))?",
            first_line,
        )

        if match:
            router = {}
            router["id"] = match.group(1)
            router["rloc16"] = match.group(2)
            router["extaddr"] = match.group(3)
            router["ver"] = match.group(4) if match.group(4) else None
            router["thread_version"] = util_network.decode_short_thread_version(
                int(router["ver"])) if router["ver"] else "Unknown"

            # Check for BR (border router) flag
            router["br"] = "- br" in first_line or "br -" in first_line

            # Check for leader flag
            router["leader"] = "- leader" in first_line or "leader -" in first_line

            # Enrich with device label from extaddr_map if available
            # Add device_label from extaddr_map if available
            extaddr_lower = router["extaddr"].lower()
            if extaddr_lower in extaddr_map:
                router["device_label"] = extaddr_map[extaddr_lower]

            # Initialize link counters and children
            router["3_links"] = []
            router["2_links"] = []
            router["1_links"] = []
            router["ipv6_addrs"] = []
            router["children"] = []

            # Parse the rest of the block
            current_section = None

            for line in lines[1:]:
                stripped = line.strip()

                # Check for link sections
                if "3-links:" in line:
                    # Extract linked routers: "3-links:{ 01 02 09 10 13 14 22 26 30 43 47 49 59 62 }"
                    link_match = re.search(r"3-links:\{\s*(.*?)\s*\}", line)
                    if link_match:
                        links = link_match.group(1).split()
                        router["3_links"] = links
                    current_section = None

                elif "2-links:" in line:
                    link_match = re.search(r"2-links:\{\s*(.*?)\s*\}", line)
                    if link_match:
                        links = link_match.group(1).split()
                        router["2_links"] = links
                    current_section = None

                elif "1-links:" in line:
                    link_match = re.search(r"1-links:\{\s*(.*?)\s*\}", line)
                    if link_match:
                        links = link_match.group(1).split()
                        router["1_links"] = links
                    current_section = None

                elif "ip6-addrs:" in line:
                    current_section = "ip6-addrs"
                    continue

                elif "children:" in line:
                    current_section = "children"
                    if "none" in line:
                        current_section = None
                    continue

                # Handle indented content based on current section
                if line.startswith("    ") and stripped:
                    if current_section == "ip6-addrs":
                        # IPv6 address line
                        if ":" in stripped and stripped.count(":") >= 2:
                            router["ipv6_addrs"].append(stripped)

                    elif current_section == "children":
                        # Child line: "rloc16:0x5002 lq:3, mode:-"
                        if "rloc16:" in stripped:
                            child = {}
                            rloc_match = re.search(
                                r"rloc16:(0x[0-9a-fA-F]+)", stripped)
                            lq_match = re.search(r"lq:(\d+)", stripped)
                            mode_match = re.search(r"mode:([^\s,]+)", stripped)

                            if rloc_match:
                                child["rloc16"] = rloc_match.group(1)
                            if lq_match:
                                child["lq"] = lq_match.group(1)
                            if mode_match:
                                child["mode"] = mode_match.group(1)

                            if child:
                                router["children"].append(child)

                elif not line.startswith("    ") and stripped and current_section:
                    # End of current section
                    current_section = None

            routers.append(router)
        else:
            logging.warning(
                "meshdiag topology: unexpected format, pattern did not match: %r",
                first_line,
            )

    return routers


def enrich_topology_routers(
    topology_data, thread_network_info=None
):
    """
    Enriches thread topology IP6 addresses and children data with additional processing.

    Args:
        topology_data: List of router dictionaries from get_thread_topology_ip6addrs_children_data()

    Returns:
        Enriched topology data with additional fields/calculations
    """

    omr_ipv6addr_prefix = (
        thread_network_info["prefix_omr_ipv6addr_prefix"]
        if thread_network_info and "prefix_omr_ipv6addr_prefix" in thread_network_info
        else None
    )

    topology_data_enhanced = []
    for router in topology_data:
        enhanced_router = router.copy()

        # Enrich: mode
        # "mode": "rdn"
        if router.get("mode") == "rdn":
            enhanced_router["mode"] = {
                "rx_on_when_idle": 1,
                "device": "FTD",
                "device_type": 1,
                "network_data": 1,
            }
        # "mode": "-"
        if router.get("mode") == "-":
            enhanced_router["mode"] = {
                "rx_on_when_idle": 0,
                "device": "MTD",
                "device_type": 0,
                "network_data": 0,
            }

        # Enrich: OMR IPv6 address
        if omr_ipv6addr_prefix:
            enhanced_router["omr_ipv6_addr"] = util_network.find_omr_address_in_list(
                router.get("ipv6_addrs", []), omr_ipv6addr_prefix
            )

        # Enrich: Border Router role base on BR flag
        if router.get("br", False):
            enhanced_router["is_border_router"] = router.get("br", False)
            enhanced_router["type"] = "border router"
            enhanced_router["role"] = "border router"
        else:
            enhanced_router["is_router"] = True
            enhanced_router["type"] = "router"
            enhanced_router["role"] = "router"

        # Enrich: Count total children
        enhanced_router["total_children"] = len(router.get("children", []))

        # Enrich: Count total links
        enhanced_router["total_links"] = (
            len(router.get("3_links", []))
            + len(router.get("2_links", []))
            + len(router.get("1_links", []))
        )
        enhanced_router["total_link_3"] = len(router.get("3_links", []))
        enhanced_router["total_link_2"] = len(router.get("2_links", []))
        enhanced_router["total_link_1"] = len(router.get("1_links", []))

        # Helper function to decode link ids to objects with id and device_label
        def decode_links_to_objects(link_ids, topology_data):
            """Decode link ids to objects with id and device_label"""
            link_objects = []
            for link_id in link_ids:
                for linked_router in topology_data:
                    if linked_router.get("id") == link_id:
                        device_label = linked_router.get(
                            "device_label", "Unknown")
                        link_rloc16 = linked_router.get("rloc16", "Unknown")
                        link_objects.append(
                            {
                                "id": link_id,
                                "rloc16": link_rloc16,
                                "device_label": device_label,
                            }
                        )
                        break
            return link_objects

        # Decode all link types and replace the original arrays with objects
        for link_type in ["3_links", "2_links", "1_links"]:
            link_ids = router.get(link_type, [])
            enhanced_router[link_type] = decode_links_to_objects(
                link_ids, topology_data
            )

        # route_data
        # Enrich: add route_data for each router based on its 3_links, 2_links, and 1_links
        inner_route_data = []
        for link_type in ["3_links", "2_links", "1_links"]:
            # set link_quality based on link_type
            link_quality = {"3_links": 3, "2_links": 2, "1_links": 1}[link_type]
            for link in enhanced_router.get(link_type, []):
                inner_route_data.append(
                    {
                        # add 0x prefix to route_id
                        "route_id": "0x" + link.get("id"),
                        "device_label": link.get("device_label"),
                        "link_quality_out": link_quality,
                        "link_quality_in": link_quality,  
                        "rloc16": link.get("rloc16"),
                        "link_type": link_type,
                    }
                )
        # wrap route_data [] in a object with a route_data fields
        outer_route_data = {"route_data": inner_route_data}
        enhanced_router["route_data"] = outer_route_data

        # children
        # Enrich: add children data for each router based on its children list
        # Each child will have rloc16, lq, mode
        enriched_children = enhanced_router.get("children", [])
        for child in enriched_children:
            child_rloc16 = child.get("rloc16")
            if child.get("device_label"):
                child["device_label"] = child.get("device_label")
            else:
                child["device_label"] = f"Unknown-{child_rloc16}"  # default label if not found in extaddr_map
           
            child["link_quality"] = child.get("lq", 0)  # default lq if not found

            # Enrich: mode
            # "mode": "rdn"
            if child.get("mode") == "rdn":
                child["mode"] = {
                    "rx_on_when_idle": 1,
                    "device": "FTD",
                    "device_type": 1,
                    "network_data": 1,
                }
            # "mode": "-"
            elif child.get("mode") == "-":
                child["mode"] = {
                    "rx_on_when_idle": 0,
                    "device": "MTD",
                    "device_type": 0,
                    "network_data": 0,
                }
            else:
                child["mode"] = {
                    "rx_on_when_idle": 0,
                    "device": "Unknown",
                    "device_type": 0,
                    "network_data": 0,
                }
        # Patch the enriched children back to the router
        enhanced_router["children"] = enriched_children
   
        topology_data_enhanced.append(enhanced_router)

    return topology_data_enhanced


def get_meshdiag_topology(
    extaddr_map=None, thread_network_info=None
):
    """
    Retrieves, parses, and enhances the thread topology IP6 addresses and children data.

    Args:
        extaddr_map: Optional dictionary mapping extended MAC to node name.
        thread_network_info: Optional dictionary containing thread network information.
    Returns:
        Enriched topology data with decoded link IDs and additional fields
    """

    topology_data_enhanced = []

    output = fetch_meshdiag_topology()
    if output:
        topology_data_enhanced = (
            parse_meshdiag_topology_output(
                output, extaddr_map
            )
        )

    # enhance links by decoding link IDs to objects with id and device_label
    enhanced_links = (
        enrich_topology_routers(
            topology_data_enhanced, thread_network_info
        )
    )

    # routers counted by unique rloc16 values in the final enhanced topology data with links
    routers_count = len(enhanced_links)
    children_count = sum(router.get("total_children", 0)
                         for router in enhanced_links)
    total_devices_count = len(enhanced_links) + children_count

    logging.info(
        f"Meshdiag consolidation complete: {routers_count} unique routers, {children_count} unique children, and {total_devices_count} total devices found in topology map."
    )

    return enhanced_links


def main(argv: Sequence[str] | None = None) -> int:

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )
    td_data_dir = resolve_data_dir(
        data_dir=parse_datadir_from_argv(argv))

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

        meshdiag_topology_data = get_meshdiag_topology(
            extaddr_map, thread_network_info
        )
        save_path = data_file_path(
            "td-otbr-cli-meshdiag-topology.json", td_data_dir)

        logging.info("Saving %d entries of meshdiag topology data into %s as JSON...", len(meshdiag_topology_data), save_path)
        converted = convert_keys_to_camel_case(meshdiag_topology_data)
        logging.info("Saved %d entries after converting keys to camel case for meshdiag topology data.", len(converted))
        save_json_atomic(converted, save_path)

        logging.debug("Saved meshdiag topology data into %s as JSON:\n%s",
                      save_path, json.dumps(converted, indent=4))
        logging.info(f"Saved meshdiag topology with {len(converted)} entries into {save_path}.")
        return 0
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logging.error(f"Invalid payload while collecting meshdiag-topology: {exc}")
        return 5
    except Exception as exc:
        logging.error(f"Runtime failure while collecting meshdiag-topology: {exc}")
        return 3

if __name__ == "__main__":
    raise SystemExit(main())
