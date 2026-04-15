import json
import os
import re
import logging

from otbr_cli_router_table import get_router_table_data
from extaddr_device_label_map import extaddr_device_label_mapping_load
from util_ot_ctl import run_ot_ctl_stdio

def get_meshdiag_routerneighbortable_one(rloc16, router=None, extaddr_map=None):
    """ 
    Dumps the meshdiag routerneighbortable for each router in 
    the network and can be used to identify potential issues with specific nodes 
    such as high link error counts, etc
    """

    output = run_ot_ctl_stdio(f"meshdiag routerneighbortable {rloc16}")

    timeout_match = re.search(r"Error\s+(\d+):\s+ResponseTimeout", output)
    if timeout_match:
        return {
            "rloc16": rloc16,
            "device_label": extaddr_map.get(router.get("extaddr"), "Unknown") if router and extaddr_map else "Unknown",
            "router_neighbor_table": [],
            "_error": {
                "type": "ResponseTimeout"
                #"code": int(timeout_match.group(1)),
                #"rloc16": rloc16,
                #"message": "Diagnostic response timed out"
            }
        }

    # store router rloc16
    # lookup rloc16 in router_table_data to get extaddr and device label if available

    router_neighbor_table = {}
    # store router rloc16 and device_label in router_neighbor_table for reference
    router_neighbor_table["rloc16"] = rloc16
    router_neighbor_table["device_label"] = extaddr_map.get(router.get("extaddr"), "Unknown") if router and extaddr_map else "Unknown"    
    router_neighbor_table_data = []

    current_neighbor = None

    for line in output.splitlines():
        stripped = line.strip()

        if not stripped or stripped == "Done":
            continue

        if stripped.startswith("rloc16:"):
            
            # found start of a new neighbor entry, store previous one if exists and has rloc16 before moving on
            # if we were already processing a neighbor, store it before moving on to the next one
            if current_neighbor and current_neighbor.get("rloc16"):
                router_neighbor_table_data.append(current_neighbor)

            match = re.match(
                r"rloc16:(0x[0-9a-fA-F]+)\s+ext-addr:([0-9a-fA-F]+)\s+ver:(\d+)",
                stripped,
            )
            if not match:
                current_neighbor = None
                continue

            current_neighbor = {
                "rloc16": match.group(1),
                "extaddr": match.group(2).lower(),
                "device_label": extaddr_map.get(match.group(2).lower(), "Unknown") if extaddr_map else "Unknown",
                "ver": int(match.group(3)),
            }
            continue

        # if we are here, we should be processing a neighbor entry, if not, skip
        if current_neighbor is None:
            continue

        rss_match = re.match(
            r"rss\s+-\s+ave:(-?\d+)\s+last:(-?\d+)\s+margin:(-?\d+)",
            stripped,
        )
        if rss_match:
            current_neighbor["rss_ave"] = int(rss_match.group(1))
            current_neighbor["rss_last"] = int(rss_match.group(2))
            current_neighbor["rss_margin"] = int(rss_match.group(3))
            continue

        err_rate_match = re.match(
            r"err-rate\s+-\s+frame:([0-9]+(?:\.[0-9]+)?)%\s+msg:([0-9]+(?:\.[0-9]+)?)%",
            stripped,
        )
        if err_rate_match:
            current_neighbor["err_rate_frame_pct"] = float(err_rate_match.group(1))
            current_neighbor["err_rate_msg_pct"] = float(err_rate_match.group(2))
            continue

        conn_time_match = re.match(r"conn-time:(\S+)", stripped)
        if conn_time_match:
            current_neighbor["conn_time"] = conn_time_match.group(1)

    # add last neighbor if exists and has rloc16
    if current_neighbor and current_neighbor.get("rloc16"):
        router_neighbor_table_data.append(current_neighbor)

    router_neighbor_table["router_neighbor_table"] = router_neighbor_table_data
    # store count of neighbors in router_neighbor_table for easy reference
    router_neighbor_table["router_neighbor_table_count"] = len(router_neighbor_table_data) 

    return router_neighbor_table
    
def get_meshdiag_routerneighbortables(extaddr_map:None):

    # 1. Get all active routers (potential parents)
    router_table_data = get_router_table_data(extaddr_map)
    router_rlocs = [router.get('rloc16') for router in router_table_data if router.get('rloc16')]
   
    router_neighbor_tables = []
    
    for rloc16 in router_rlocs:
        router = next((r for r in router_table_data if r.get('rloc16') == rloc16), None)
        if router:
            extaddr = router.get('extaddr')
            device_label = extaddr_map.get(extaddr, "Unknown")
            logging.info(f"Getting meshdiag routerneighbortable for router rloc16 {rloc16} (Node: {device_label}, ExtAddr: {extaddr})...")
        else:
            logging.info(f"Getting meshdiag routerneighbortable for router rloc16 {rloc16} (Node: Unknown, ExtAddr: Unknown)...")

        router_neighbor_table = get_meshdiag_routerneighbortable_one(rloc16, router, extaddr_map)
        router_neighbor_tables.append(router_neighbor_table)

    return router_neighbor_tables

def main():
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

    # Load extaddr to nodename mapping from JSON file
    extaddr_json_filename = "td-static-extaddr-device-label.json"

    # Check if file exists before parsing
    if os.path.exists(extaddr_json_filename):
        extaddr_map = extaddr_device_label_mapping_load(extaddr_json_filename)
    else:
        extaddr_map = {}

    logging.info(f"Loading extended address to device label mapping from {extaddr_json_filename}...")
    extaddr_map = extaddr_device_label_mapping_load(extaddr_json_filename)
        
    router_neighbor_tables = get_meshdiag_routerneighbortables(extaddr_map)
    
    with open('td-otbr-cli-meshdiag-router-neighbortables.json', 'w') as f:
        json.dump(router_neighbor_tables, f, indent=4)
        logging.info("Meshdiag routerneighbortables data saved to td-otbr-cli-meshdiag-router-neighbortables.json")  
    
    print(json.dumps(router_neighbor_tables, indent=4))

if __name__ == "__main__":
    main()