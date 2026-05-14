import copy
import json
import logging
import os
from typing import Sequence

import util_network
from util_convert import b64_to_extended_address
from util_data import data_file_path, parse_datadir_from_argv, resolve_data_dir, save_json_atomic


def load_and_parse_eve_file(path, network_dataset_info=None):
    """
    Parses Eve JSON file and preserves all node fields.

    Convert each node's rloc16 (eve json has decimal) in hex string format for consistent mapping.
    Converts base64 extended addresses to canonical extaddr hex strings for consistent mapping.

    Args:
        path: Path to thread JSON file
        network_dataset_info: Network dataset information for reference

    Returns:
        Dictionary mapping rloc16 (hex format) to all node fields with extaddr_hex added
    """

    result = {}

    omr_ipv6addr_prefix = (
        network_dataset_info["prefix_omr_ipv6addr_prefix"]
        if network_dataset_info and "prefix_omr_ipv6addr_prefix" in network_dataset_info
        else None
    )

    # Load the Eve JSON file
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        logging.error(f"Failed to open Eve JSON file {path!r}: {e}")
        return result
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in Eve file {path!r}: {e}")
        return result

    for node in data.get("nodes", []):
        # Conform rloc16 to hex string for consistent mapping
        rloc16_decimal = node.get("rloc16")

        # Conform from 'ip_addresses' to "ipv6_addrs" for consistent naming and mapping
        ipv6_addrs = node.get("ip_addresses", [])
        node["ipv6_addrs"] = ipv6_addrs

        # Enhance node with OMR IPv6 address  using OMR prefix
        if omr_ipv6addr_prefix:
            node["omr_ipv6_addr"] = util_network.find_omr_address_in_list(
                ipv6_addrs, omr_ipv6addr_prefix
            )

        # Remove original 'ip_addresses' to avoid confusion since we have 'ipv6_addrs' now
        if "ip_addresses" in node:
            del node["ip_addresses"]

        # Enhance node with hex rloc16 and short rloc for easier mapping
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

        node["node_name_eve"] = node.get(
            "name"
        )  # Preserve original node name from Eve for reference
        node["node_id_eve"] = node.get(
            "id"
        )  # Preserve original node ID from Eve for reference

        # Convert base64 extAddress to hex string for consistent mapping
        thread_networks = node.get("threadNetworks", [])
        if thread_networks:
            ext_addr_b64 = thread_networks[0].get("extAddress")
            if ext_addr_b64:
                # Convert base64 extAddress to hex string
                ext_addr_hex = b64_to_extended_address(ext_addr_b64)

                # store enhanced hex extAddress for reference
                # Add hex extAddress to threadNetworks for reference
                thread_networks[0]["extAddress_hex"] = ext_addr_hex

                # Add extaddr in hex format for consistent mapping
                thread_networks[0]["extaddr"] = ext_addr_hex

        # Preserve all fields from the node
        if rloc16_decimal is not None:
            result[rloc16_hex] = node
    return result


def enhance_eve_routes(eve_data):
    """
    Rebuild Eve enhanced data keyed by rloc16_hex and enrich route entries.

    - Preserves all fields from original nodes.
    - Keys output by each node's rloc16_hex.
        - Adds route field "to_name" by resolving each route["to"] to a node name
    using the original eve_data structure.
    """

    # Build lookup maps from original data for route destination resolution.
    # route "to" values may be node ids (UUID). We will attempt to resolve them to node names.
    id_to_name = {}
    id_to_rloc16_hex = {}
    key_to_name = {}

    # TODO map off mesh ipaddr to node name
    # TODO map on mesh ipaddr to node name

    for original_key, original_node in eve_data.items():
        if not isinstance(original_node, dict):
            continue

        # build maps for resolving route "to" values to node names
        node_name = original_node.get("name")
        # rloc16 to name mapping for direct dataset key resolution
        key_to_name[original_key] = node_name

        node_id = original_node.get("id")
        if node_id:
            id_to_name[node_id] = node_name
            id_to_rloc16_hex[node_id] = original_node.get("rloc16_hex")
    result = {}

    # Rebuild nodes keyed by rloc16_hex while preserving all original fields.
    for original_key, original_node in eve_data.items():
        if not isinstance(original_node, dict):
            continue

        node_copy = copy.deepcopy(original_node)
        rloc16_hex = node_copy.get("rloc16_hex", original_key)

        # Enhance route entries with "to_name" by resolving route["to"] to node names using the original data maps
        routes = node_copy.get("routes")
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

        result[rloc16_hex] = node_copy

    node_count = len(result)
    logging.info(
        f"Eve consolidation complete: {node_count} records in eve file."
    )

    return result


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )
    td_data_dir = resolve_data_dir(
        data_dir=parse_datadir_from_argv(argv))

    # Main execution:

    # Get network dataset info for reference in parsing and enriching Eve data
    network_dataset_info = util_network.fetch_network_dataset_info()

    # Parse the Eve JSON file to build an enhanced data structure keyed by rloc16_hex with all node fields preserved and extAddress in hex format for easier mapping and reference.
    eve_json_file_path = data_file_path("thread-eve-layout.json", td_data_dir)
    eve_data_raw = load_and_parse_eve_file(
        eve_json_file_path, network_dataset_info
    )

    # Enhance the eve_data json data structure to add route destination node names for reference
    eve_data_enhanced = enhance_eve_routes(eve_data_raw)

    # Save json data structures for reference
    file_path = data_file_path("td-eve-topology.json", td_data_dir)
    save_json_atomic(eve_data_enhanced, file_path)

    # Print the parsed data structure with route names
    logging.debug("Raw eve data as JSON:\n%s",
                  json.dumps(eve_data_enhanced, indent=4))


if __name__ == "__main__":
    raise SystemExit(main())
