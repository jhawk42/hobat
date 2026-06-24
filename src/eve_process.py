import argparse
import json
import logging
from typing import Sequence

import util_network
from json_key_normalizer import convert_keys_to_camel_case
from util_convert import b64_to_extended_address
from util_data import (
    TDRequiredInputMissingError,
    data_file_path,
    parse_datadir_from_argv,
    require_existing_input_file,
    resolve_data_dir,
    save_json_atomic,
)

EVE_NATIVE_LAYOUT_FILENAME = "Eve Thread Network Layout.evethreadlayout"

def load_and_parse_eve_file(path, thread_network_info=None):
    """
    Parses Eve JSON file and preserves all node fields.

    Convert each node's rloc16 (eve json has decimal) in hex string format for consistent mapping.
    Converts base64 extended addresses to canonical extaddr hex strings for consistent mapping.

    Args:
        path: Path to thread JSON file
        thread_network_info: Network dataset information for reference

    Returns:
        Dictionary mapping rloc16 (hex format) to all node fields with extaddr_hex added
    """

    result = {}

    omr_ipv6addr_prefix = (
        thread_network_info["prefix_omr_ipv6addr_prefix"]
        if thread_network_info and "prefix_omr_ipv6addr_prefix" in thread_network_info
        else None
    )
    
    meshlocal_ipv6addr_prefix = (
        thread_network_info["prefix_meshlocal_ipv6addr_prefix"]
        if thread_network_info and "prefix_meshlocal_ipv6addr_prefix" in thread_network_info
        else None
    )

    # Load the Eve JSON file
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    logging.info(f"Eve native: {len(data.get('nodes', []))} records in eve file.")

    for node in data.get("nodes", []):
        node_id = node.get("id")
        
        # Conform rloc16 to hex string for consistent mapping
        rloc16_hex = None
        rloc16_decimal = node.get("rloc16")

        # Enrich node with hex rloc16 and short rloc for easier mapping
        if rloc16_decimal is not None:
            rloc16_hex = f"0x{rloc16_decimal:04x}"
            node["rloc16"] = (
                rloc16_hex  # Patch original rloc16 field to hex string for consistency in the node data structure
            )
            node["rloc16_hex"] = rloc16_hex  # Add hex rloc16 for reference
            node["rloc16_hexshort"] = util_network.strip_rloc16_hex_prefix(
                rloc16_hex
            )  # Add short rloc for reference
            node["rloc16_decimal"] = (
                rloc16_decimal  # Preserve original decimal rloc16 for reference
            )

        # Conform from 'ip_addresses' to "ipv6_addrs" for consistent naming and mapping
        ipv6_addrs = node.get("ip_addresses", [])
        node["ipv6_addrs"] = ipv6_addrs

        # Enrich with rloc16 in hex from rloc16 ipv6 addresses if rloc16 field is missing
        if rloc16_decimal is None:
            
            # Note: some eve nodes don't have a rloc16 field. For these nodes, attempt to extract rloc16 from 
            # their IPv6 addresses if available, since rloc16 may be encoded in the IPv6 addresses for Thread devices.
            # Call extract_rloc16_from_ipv6_addresses to extract the rloc16 as hex from the IPv6 addresses
            if ipv6_addrs and meshlocal_ipv6addr_prefix:
                rloc16_hex = util_network.extract_rloc16_from_ipv6_addresses_cached(
                    ipv6_addrs, meshlocal_ipv6addr_prefix
                )
                if rloc16_hex is not None:
                    node["rloc16"] = rloc16_hex  # Patch original rloc16 field to hex string for consistency in the node data structure
                    node["rloc16_hex"] = rloc16_hex  # Add hex rloc16 for reference
                    node["rloc16_hexshort"] = util_network.strip_rloc16_hex_prefix(
                        rloc16_hex
                    )  # Add short rloc for reference
                    rloc16_decimal = int(rloc16_hex, 16)  # Preserve original decimal rloc16 for reference
                    node["rloc16_decimal"] = rloc16_decimal
                    logging.debug(
                        f"Extracted rloc16 {rloc16_hex} from IPv6 addresses for node {node.get('name', 'Unknown')} (id: {node.get('id', 'Unknown')})."
                    )
                else:
                    logging.warning(
                        f"No valid RLOC16 found in IPv6 addresses for node {node.get('name', 'Unknown')} (id: {node.get('id', 'Unknown')}). Skipping rloc16 enrichment for this node."
                    )

        # Enrich node with OMR IPv6 address  using OMR prefix
        if omr_ipv6addr_prefix:
            node["omr_ipv6_addr"] = util_network.find_omr_address_in_list(
                ipv6_addrs, omr_ipv6addr_prefix
            )

        # Remove original 'ip_addresses' to avoid confusion since we have 'ipv6_addrs' now
        if "ip_addresses" in node:
            del node["ip_addresses"]

        # Preserve original node name from Eve for reference
        node["node_name_eve"] = node.get("name")

        # Preserve original node ID from Eve for reference
        node["node_id_eve"] = node.get("id")

        # Convert base64 extAddress to hex string for consistent mapping
        thread_networks = node.get("threadNetworks", [])
        if thread_networks:
            ext_addr_b64 = thread_networks[0].get("extAddress")
            if ext_addr_b64:
                # Convert base64 extAddress to hex string
                ext_addr_hex = b64_to_extended_address(ext_addr_b64)

                # store enriched hex extAddress for reference
                # Add hex extAddress to threadNetworks for reference
                thread_networks[0]["extAddress_hex"] = ext_addr_hex

                # Add extaddr in hex format for consistent mapping
                thread_networks[0]["extaddr"] = ext_addr_hex
          
        ## Index by rloc16. Preserve all fields from the node
        #if rloc16_hex is not None:
        #    result[rloc16_hex] = node
        result[node_id] = node  # Also index by node id for reference

    return result


def enrich_eve_nodes(eve_data):
    """
    Rebuild Eve nodes and enrich rloc16, route entries.

    - Preserves all fields from original nodes.
    - Keys output by each node's rloc16_hex.
        - Adds route field "to_name" by resolving each route["to"] to a node name
    using the original eve_data structure.
    """

    # var to be returned from function with nodes keyed by rloc16_hex and enriched route entries
    result = {}

    # Build lookup maps from original data for route destination resolution.
    # route "to" values may be node ids (UUID). We will attempt to resolve them to node names.
    id_to_name = {}
    id_to_rloc16_hex = {}
    key_to_name = {}
    rloc16_hex_to_id = {}

    # Build maps
    for original_key, original_node in eve_data.items():
        if not isinstance(original_node, dict):
            continue

        # Build map for rloc16 to node id
        rloc16_hex_build = original_node.get("rloc16_hex")
        if rloc16_hex_build is not None:
            rloc16_hex_to_id[rloc16_hex_build] = original_node.get("id")

        # Build map for resolving route "to" values to node names
        node_name = original_node.get("name")
        # rloc16 to name mapping for direct dataset key resolution
        key_to_name[original_key] = node_name

        node_id = original_node.get("id")
        if node_id:
            id_to_name[node_id] = node_name
            id_to_rloc16_hex[node_id] = original_node.get("rloc16_hex")

    # Occasionally the eve layout format has some fields missiing
    # Try to patch missing parent-child relationships based on rloc16 hierarchy for nodes that have rloc16 but are missing "children" field in their parent node. This is to enrich the data structure for better reference and mapping, since rloc16 hierarchy can indicate parent-child relationships in Thread networks.
    for original_key, original_node in eve_data.items():
        # If missing in the original Eve data
        # Check if need to patch parent-child relationships based on rloc16 hierarchy 
        rloc16_hex = original_node.get("rloc16_hex")
        if rloc16_hex is not None:
            if rloc16_hex.endswith("00"): # Skip if a router
                continue
            
            node_id = original_node.get("id")

            # Find potential parent rloc16 by replacing the last 2 characters of the rloc16 with 0x00, which 
            # is the parent node rloc16 in Thread networks. For example, if the rloc16 is 0x1234, the 
            # parent rloc16 would be 0x1200,
            parent_rloc16_hex = rloc16_hex[:4] + "00"
            parent_node_id = rloc16_hex_to_id.get(parent_rloc16_hex)
            parent_node = eve_data[parent_node_id] if parent_node_id else None

            if parent_node is not None and node_id is not None:
                # Check if parent_node.children already contains this node "id" field
                parent_node_id = parent_node.get("id")
                parent_node_children = parent_node.get("children")

                # Check if children array is present. 
                if parent_node_children is None:
                    logging.debug(
                        f"Parent node {parent_node.get('name', 'Unknown')} (id: {parent_node_id}) has no children array. Initializing children array and adding child node {original_node.get('name', 'Unknown')} (id: {node_id}) based on rloc16 relationship."
                    )
                    # If not present, initialize it as an empty array and add the child node id to it. 
                    parent_node_children = []
                    parent_node_children.append(node_id)  # Add child node id to the new children array
                   
                    # Patch original eve_data structure to add children array for parent node
                    eve_data[parent_node_id]["children"] = parent_node_children  
                    
                    logging.debug(
                        f"Adding child node {original_node.get('name', 'Unknown')} (id: {node_id}, rloc16:{rloc16_hex}) to parent node {parent_node.get('name', 'Unknown')} (id: {parent_node.get('id', 'Unknown')}, rloc16:{parent_rloc16_hex}) based on rloc16 relationship."
                    )

                    logging.debug(
                        f"Updated parent node {parent_node.get('name', 'Unknown')} (id: {parent_node_id}, rloc16:{parent_rloc16_hex}) with new child node {original_node.get('name', 'Unknown')} (id: {node_id}, rloc16:{rloc16_hex})."
                    )
                elif node_id not in parent_node_children:
                    logging.debug(
                        f"Adding child node {original_node.get('name', 'Unknown')} (id: {node_id}, rloc16:{rloc16_hex}) to parent node {parent_node.get('name', 'Unknown')} (id: {parent_node.get('id', 'Unknown')}, rloc16:{parent_rloc16_hex}) based on rloc16 relationship."
                    )
                    eve_data[parent_node_id]["children"].append(node_id)  # Patch original eve_data structure to add child node id to parent's children array   


    # Rebuild nodes keyed by rloc16_hex while preserving all original fields.
    for original_key, original_node in eve_data.items():
        if not isinstance(original_node, dict):
            continue

        rloc16_hex = original_node.get("rloc16_hex", original_key)

        # Enrich route entries with "to_name" by resolving route["to"] to node names using the original data maps
        routes = original_node.get("routes")
        if isinstance(routes, list):
            for route in routes:
                if not isinstance(route, dict):
                    continue
                destination = route.get("to")

                # Resolve by direct dataset key first, then by node id.
                route["to_name"] = id_to_name.get(destination)
                if route["to_name"] is None:
                    route["to_name"] = f"Unknown({destination})"
                route["to_rloc16"] = id_to_rloc16_hex.get(
                    destination, f"Unknown({destination})"
                )

        result[rloc16_hex] = original_node

    node_count = len(result)
    logging.info(
        f"Eve consolidation complete: {node_count} records in eve file."
    )

    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse and enhance an Eve Thread layout file."
    )
    parser.add_argument(
        "--datadir",
        metavar="DIR",
        default=None,
        help="Data directory for JSON reads/writes",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )
    td_data_dir = resolve_data_dir(
        data_dir=args.datadir or parse_datadir_from_argv(argv)
    )

    try:
        # Main execution:

        # Get thread network info for reference in parsing and enriching Eve data
        thread_network_info = util_network.fetch_thread_network_info()

        # Parse the Eve JSON file to build an enhanced data structure keyed by rloc16_hex with all node fields preserved and extAddress in hex format for easier mapping and reference.
        eve_json_file_path = data_file_path(EVE_NATIVE_LAYOUT_FILENAME, td_data_dir)
        require_existing_input_file(
            eve_json_file_path,
            command_path="process-eve",
            data_dir=td_data_dir,
            classification="required",
            action="fail code=4",
        )
        eve_data_raw = load_and_parse_eve_file(
            eve_json_file_path, thread_network_info
        )

        # Enrich the eve_data json data structure to add route destination node names for reference
        eve_data_enhanced = enrich_eve_nodes(eve_data_raw)

        # Save json data structures for reference
        file_path = data_file_path("td-eve-topology.json", td_data_dir)
        save_json_atomic(convert_keys_to_camel_case(eve_data_enhanced), file_path)

        logging.info("Saved eve topology data to %s", file_path)
        return 0
    except TDRequiredInputMissingError as exc:
        logging.error(str(exc))
        return 4
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logging.error(f"Invalid payload while processing Eve layout: {exc}")
        return 5
    except Exception as exc:
        logging.error(f"Runtime failure while processing Eve layout: {exc}")
        return 3

if __name__ == "__main__":
    raise SystemExit(main())
