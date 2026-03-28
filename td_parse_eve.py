from td_util_convert import convert_from_base64_to_ext_address_hexnumber
from td_util_network import conform_rloc_hex_strip

import copy
import json

def parse_eve_process_id_mappings(path):
    """
    Parses Eve JSON file and preserves all node fields.

    Convert each node's rloc16 (eve json has decimal) in hex string format for consistent mapping.
    Converts base64 extended addresses to canonical extaddr hex strings for consistent mapping.

    Args:
        path: Path to thread JSON file

    Returns:
        Dictionary mapping rloc16 (hex format) to all node fields with extaddr_hex added
    """
    
    rloc16_missing_start = 65535  # Default rloc16 value when missing (0xffff)

    with open(path) as f:
        j = json.load(f)
    out = {}

    for node in j.get("nodes", []):
        # Conform rloc16 to hex string for consistent mapping
        rloc16_decimal = node.get("rloc16")
        if rloc16_decimal is None:
            rloc16_decimal = rloc16_missing_start  # Default to 0xffff if rloc16 is missing
            rloc16_missing_start -= 1  # Decrement for next missing rloc16

        # Conform from 'ip_addresses' to "ipv6_addrs" for consistent naming and mapping
        ipv6_addrs = node.get("ip_addresses", [])
        node["ipv6_addrs"] = ipv6_addrs
        # remove original 'ip_addresses' to avoid confusion since we have 'ipv6_addrs' now
        if "ip_addresses" in node:
            del node["ip_addresses"]

        # Enrich node with hex rloc16 and short rloc for easier mapping
        rloc16_hex = f"0x{rloc16_decimal:04x}"
        node["rloc16"] = rloc16_hex  # Patch original rloc16 field to hex string for consistency in the node data structure
        node["rloc16_hex"] = rloc16_hex  # Add hex rloc16 for reference
        node["rloc16_hexshort"] = conform_rloc_hex_strip(rloc16_hex)  # Add short rloc for reference
        node["rloc16_decimal"] = rloc16_decimal  # Preserve original decimal rloc16 for reference

        node["node_name_eve"] = node.get("name")  # Preserve original node name from Eve for reference  
        node["node_id_eve"] = node.get("id")  # Preserve original node ID from Eve for reference

        # Convert base64 extAddress to hex string for consistent mapping
        threadNetworks = node.get("threadNetworks", [])
        if threadNetworks:
            extAddress_b64 = threadNetworks[0].get("extAddress")
            if extAddress_b64:
                # Convert base64 extAddress to hex string
                extAddress_hex = convert_from_base64_to_ext_address_hexnumber(extAddress_b64)
                
                # store enhanced hex extAddress for reference
                # Add hex extAddress to threadNetworks for reference
                threadNetworks[0]["extAddress_hex"] = extAddress_hex  
                
                # Add extaddr in hex format for consistent mapping
                threadNetworks[0]["extaddr"] = extAddress_hex  

        # Preserve all fields from the node
        out[rloc16_hex] = node
    return out

def parse_eve_process_route_mappings(eve_network_enhanced_data):
    """
    Rebuild Eve enhanced data keyed by rloc16_hex and enrich route entries.

    - Preserves all fields from original nodes.
    - Keys output by each node's rloc16_hex.
        - Adds route field "to_name" by resolving each route["to"] to a node name
      using the original eve_network_enhanced_data structure.
    """
    
    # Build lookup maps from original data for route destination resolution.
    # route "to" values may be node ids (UUID). We will attempt to resolve them to node names.
    id_to_name = {}
    id_to_rloc16_hex = {}
    key_to_name = {}

    # TODO map off mesh ipaddr to node name
    # TODO map on mesh ipaddr to node name

    for original_key, original_node in eve_network_enhanced_data.items():
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
    output = {}

    # Rebuild nodes keyed by rloc16_hex while preserving all original fields.
    for original_key, original_node in eve_network_enhanced_data.items():
        if not isinstance(original_node, dict):
            continue

        node_copy = copy.deepcopy(original_node)
        rloc16_hex = node_copy.get("rloc16_hex", original_key)

        # Enrich route entries with "to_name" by resolving route["to"] to node names using the original data maps
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
                route["to_rloc16"] = id_to_rloc16_hex.get(destination, f"Unknown({destination})")
        
        output[rloc16_hex] = node_copy

    return output


if __name__ == "__main__":
    ## Main execution: 

    # Parse the Eve JSON file to build an enhanced data structure keyed by rloc16_hex with all node fields preserved and extAddress in hex format for easier mapping and reference. 
    eve_json_file_path = "thread-eve-layout.json"
    eve_data_parse_1 = parse_eve_process_id_mappings(eve_json_file_path)

    ## Reparse and enrich the eve_data json data structure to add route destination node names for reference
    eve_data_parse_2 = parse_eve_process_route_mappings(eve_data_parse_1)  
    
    ## Save json data structures for reference
    save_json_filename = "thread-eve-topology.json"
    with open(save_json_filename, 'w') as f:
        json.dump(eve_data_parse_2, f, indent=4)

    ## Print the parsed data structure with route names
    print(json.dumps(eve_data_parse_2, indent=4))