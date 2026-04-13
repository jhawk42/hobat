import subprocess
import re
import json
import sys
import time

from extaddr_device_label_map import parse_extaddr_nodename_mapping
import util_network
import os

def main():

    print("TDash: Thread Network Topology Scanner")

    """Main entry point with optional command-line arguments."""
    print("Initiating Thread Network Topology Scan...\n")

    # Determine output format from command-line argument
    output_format = sys.argv[1] if len(sys.argv) > 1 else "all"

    # Load extaddr to nodename mapping from JSON file
    extaddr_json_filename = "threadstatic-extaddr.json"

    # Check if file exists before parsing
    if os.path.exists(extaddr_json_filename):
        extaddr_map = parse_extaddr_nodename_mapping(extaddr_json_filename)
    else:
        extaddr_map = {}

    if output_format in ["console", "all", "network-data"]:
        ##print_network_topology(topology)
        print("Network Data")
        network_data = util_network.get_network_dataset_info()
        print(json.dumps(network_data, indent=4))

    if output_format in ["json-dict", "all"]:
        ##save_topology_to_json(topology, "thread_topology.json")
        print("json-dictoutput not implemented yet")
        
    if output_format in ["json-list", "all"]:
        ##save_topology_as_list_json(topology, "thread_topology_list.json")
        print("json-list output not implemented yet")
        
    if output_format not in ["console", "json-dict", "json-list", "network-data", "all"]:
        print(f"Unknown format '{output_format}'")
        print("Usage: python td_dump_thread_topology_3_merged.py [console|json-dict|json-list|all]")
        print("  console:  Print topology to console (tree format)")
        print("  json-dict: Save as JSON dict with RLOC16 keys")
        print("  json-list: Save as JSON list with parent nodes")
        print("  all:      Print to console + save both JSON formats (default)")        

if __name__ == "__main__":
    main()