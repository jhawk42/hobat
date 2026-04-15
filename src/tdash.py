import subprocess
import re
import json
import sys
import time
import logging

from extaddr_device_label_map import extaddr_device_label_mapping_load
import util_network
import os

def main():
    """Main entry point with optional command-line arguments."""

    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

    logging.info("Thread Network Topology Scanner")
    logging.info("Initiating Thread Network Topology Scan...\n")

    # Determine output format from command-line argument
    output_format = sys.argv[1] if len(sys.argv) > 1 else "all"

    # Load extaddr to nodename mapping from JSON file
    extaddr_json_filename = "threadstatic-extaddr.json"

    # Check if file exists before parsing
    if os.path.exists(extaddr_json_filename):
        extaddr_map = extaddr_device_label_mapping_load(extaddr_json_filename)
    else:
        extaddr_map = {}

    # args processing and validation can be added here if needed
    if output_format in ["console", "all", "network-data"]:
        ##print_network_topology(topology)
        logging.info("Network Data")
        network_data = util_network.get_network_dataset_info()
        logging.info(json.dumps(network_data, indent=4))

    if output_format in ["json-dict", "all"]:
        ##save_topology_to_json(topology, "thread_topology.json")
        logging.info("json-dict output not implemented yet")
        
    if output_format in ["json-list", "all"]:
        ##save_topology_as_list_json(topology, "thread_topology_list.json")
        logging.info("json-list output not implemented yet")
        
    if output_format not in ["console", "json-dict", "json-list", "network-data", "all"]:
        logging.info(f"Unknown format '{output_format}'")
        logging.info("Usage: python td_dump_thread_topology_3_merged.py [console|json-dict|json-list|all]")
        logging.info("  console:  Print topology to console (tree format)")
        logging.info("  json-dict: Save as JSON dict with RLOC16 keys")
        logging.info("  json-list: Save as JSON list with parent nodes")
        logging.info("  all:      Print to console + save both JSON formats (default)")

if __name__ == "__main__":
    main()