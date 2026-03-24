import os
import subprocess
import re
import json

from td_parse_extaddr_data_map import parse_extaddr_nodename_mapping
import td_util_ot_ctl

def get_meshdiag_topology_ip6addrs_children():
    try:
        # Executes the command: ot-ctl meshdiag topology ip6-addrs children
        # This command provides IPv6 addresses and children info for all routers
        output = td_util_ot_ctl.run_ot_ctl("meshdiag topology ip6-addrs children")
        return output
    except subprocess.CalledProcessError as e:
        print(f"Error running ot-ctl: {e}")
        return None

def parse_meshdiag_topology_ip6addrs_children_output_and_enhance(output, extaddr_map=None):
    """
    Parses the meshdiag topology ip6-addrs children output into a list of router dictionaries.
    
    Extracts: id, rloc16, ext-addr, ver, br flag, 3-links, 2-links, 1-links, ip6-addrs, children
    
    Args:
        output: meshdiag topology ip6-addrs children text
        extaddr_map: Optional dictionary mapping extended MAC to node name
    """
    routers = []
    if extaddr_map is None:
        extaddr_map = {}
    
    # Split by 'id:' to get each router block (skip the first empty element)
    router_blocks = re.split(r'id:', output)[1:]
    
    for block in router_blocks:
        # Split block into lines
        lines = block.split('\n')
        first_line = lines[0]
        
        # Extract router info from first line
        # Format: "20 rloc16:0x5000 ext-addr:1a7fbf0434e4f043 ver:5 - me - br"
        match = re.match(r'(\d+)\s+rloc16:(0x[0-9a-fA-F]+)\s+ext-addr:([0-9a-fA-F]+)\s+ver:(\d+)', first_line)
        
        if match:
            router = {}
            router["id"] = match.group(1)
            router["rloc16"] = match.group(2)
            router["ext_addr"] = match.group(3)
            router["ver"] = match.group(4)
            
            # Check for BR (border router) flag
            router["br"] = "- br" in first_line or "br -" in first_line
            
            # Enhance with node name from extaddr_map if available
            # Add node_name from extaddr_map if available
            ext_addr_lower = router["ext_addr"].lower()
            if ext_addr_lower in extaddr_map:
                router['node_name'] = extaddr_map[ext_addr_lower]
            
            # Initialize link counters and children
            router["3-links"] = []
            router["2-links"] = []
            router["1-links"] = []
            router["ip6-addrs"] = []
            router["children"] = []
            
            # Parse the rest of the block
            current_section = None
            current_lq = None
            
            for line in lines[1:]:
                stripped = line.strip()
                
                # Check for link sections
                if '3-links:' in line:
                    # Extract linked routers: "3-links:{ 01 02 09 10 13 14 22 26 30 43 47 49 59 62 }"
                    link_match = re.search(r'3-links:\{\s*(.*?)\s*\}', line)
                    if link_match:
                        links = link_match.group(1).split()
                        router["3-links"] = links
                    current_section = None
                
                elif '2-links:' in line:
                    link_match = re.search(r'2-links:\{\s*(.*?)\s*\}', line)
                    if link_match:
                        links = link_match.group(1).split()
                        router["2-links"] = links
                    current_section = None
                
                elif '1-links:' in line:
                    link_match = re.search(r'1-links:\{\s*(.*?)\s*\}', line)
                    if link_match:
                        links = link_match.group(1).split()
                        router["1-links"] = links
                    current_section = None
                
                elif 'ip6-addrs:' in line:
                    current_section = 'ip6-addrs'
                    continue
                
                elif 'children:' in line:
                    current_section = 'children'
                    if 'none' in line:
                        current_section = None
                    continue
                
                # Handle indented content based on current section
                if line.startswith('    ') and stripped:
                    if current_section == 'ip6-addrs':
                        # IPv6 address line
                        if ':' in stripped and stripped.count(':') >= 2:
                            router["ip6-addrs"].append(stripped)
                    
                    elif current_section == 'children':
                        # Child line: "rloc16:0x5002 lq:3, mode:-"
                        if 'rloc16:' in stripped:
                            child = {}
                            rloc_match = re.search(r'rloc16:(0x[0-9a-fA-F]+)', stripped)
                            lq_match = re.search(r'lq:(\d+)', stripped)
                            mode_match = re.search(r'mode:([^\s,]+)', stripped)
                            
                            if rloc_match:
                                child['rloc16'] = rloc_match.group(1)
                            if lq_match:
                                child['lq'] = lq_match.group(1)
                            if mode_match:
                                child['mode'] = mode_match.group(1)
                            
                            if child:
                                router["children"].append(child)
                
                elif not line.startswith('    ') and stripped and current_section:
                    # End of current section
                    current_section = None
            
            routers.append(router)
    
    return routers

def meshdiag_topology_ip6addrs_children_data_enhance_links(topology_data):
    """
    Enhances thread topology IP6 addresses and children data with additional processing.
    
    Args:
        topology_data: List of router dictionaries from get_thread_topology_ip6addrs_children_data()
    
    Returns:
        Enhanced topology data with additional fields/calculations
    """
    pass
    topology_data_enhanced = []
    for router in topology_data:
        enhanced_router = router.copy()
        
        # Enhancement: Count total children
        enhanced_router["total_children"] = len(router.get("children", []))
        
        # Enhancement: Count total links
        enhanced_router["total_links"] = len(router.get("3-links", [])) + len(router.get("2-links", [])) + len(router.get("1-links", []))
        enhanced_router["total_link_3"] = len(router.get("3-links", []))
        enhanced_router["total_link_2"] = len(router.get("2-links", []))
        enhanced_router["total_link_1"] = len(router.get("1-links", []))

        # Helper function to decode link ids to objects with id and node_name
        def decode_links_to_objects(link_ids, topology_data):
            """Decode link ids to objects with id and node_name"""
            link_objects = []
            for link_id in link_ids:
                for linked_router in topology_data:
                    if linked_router.get("id") == link_id:
                        node_name = linked_router.get("node_name", "Unknown")
                        link_rloc16 = linked_router.get("rloc16", "Unknown")
                        link_objects.append({
                            "id": link_id,
                            "rloc16": link_rloc16,
                            "node_name": node_name
                        })
                        break
            return link_objects
        
        # Decode all link types and replace the original arrays with objects
        for link_type in ["3-links", "2-links", "1-links"]:
            link_ids = router.get(link_type, [])
            enhanced_router[link_type] = decode_links_to_objects(link_ids, topology_data)

        topology_data_enhanced.append(enhanced_router)

    return topology_data_enhanced

def get_meshdiag_topology_ip6addrs_children_data(extaddr_map=None):
    """
    Retrieves, parses, and enhances the thread topology IP6 addresses and children data.
    
    Args:
        extaddr_map: Optional dictionary mapping extended MAC to node name.
    
    Returns:
        Enhanced topology data with decoded link IDs and additional fields
    """
    
    output = get_meshdiag_topology_ip6addrs_children()
    if output:
        topology_data_enhanced = parse_meshdiag_topology_ip6addrs_children_output_and_enhance(output, extaddr_map)
    
    # enhance links by decoding link IDs to objects with id and node_name
    topology_data_enhanced_links = meshdiag_topology_ip6addrs_children_data_enhance_links(topology_data_enhanced) 
    
    return topology_data_enhanced_links

if __name__ == "__main__":

    # Load extaddr to nodename mapping from JSON file
    extaddr_json_filename = "threadstatic-extaddr.json"

    # Check if file exists before parsing
    if os.path.exists(extaddr_json_filename):
        extaddr_map = parse_extaddr_nodename_mapping(extaddr_json_filename)
    else:
        extaddr_map = {}
     
    meshdiag_topology_data = get_meshdiag_topology_ip6addrs_children_data(extaddr_map)
    save_path = "thread-meshdiag-topology.json"
    with open(save_path, 'w') as f:
        json.dump(meshdiag_topology_data, f, indent=4)

    print(json.dumps(meshdiag_topology_data, indent=4))
