import json
import logging
import os
import re
from typing import Sequence

from const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
from extaddr_device_label_map import extaddr_device_label_mapping_load
from otbr_cli_router_table import get_router_table_data
from util_ot_ctl import run_ot_ctl_stdio
from util_data import data_file_path, extract_datadir_arg, resolve_td_data_dir


def get_meshdiag_childip6_one(parent_rloc16, router=None, extaddr_map=None):
    """Collect and parse `meshdiag childip6` output for one parent router."""

    output = run_ot_ctl_stdio(f"meshdiag childip6 {parent_rloc16}")
    logging.info(f"[DEBUG] Output of 'meshdiag childip6 {parent_rloc16}':\n{output}\n")

    timeout_match = re.search(r"Error\s+(\d+):\s+ResponseTimeout", output)
    if timeout_match:
        return {
            "parent_rloc16": parent_rloc16,
            "device_label": extaddr_map.get(router.get("extaddr"), "Unknown") if router and extaddr_map else "Unknown",
            "router_child_ip6_table": [],
            "router_child_ip6_table_count": 0,
            "_error": {
                "type": "ResponseTimeout",
            },
        }

    router_child_ip6 = {
        "parent_rloc16": parent_rloc16,
        "device_label": extaddr_map.get(router.get("extaddr"), "Unknown") if router and extaddr_map else "Unknown",
    }

    router_child_ip6_data = []
    current_child = None

    for line in output.splitlines():
        stripped = line.strip()

        if not stripped or stripped == "Done":
            continue

        child_rloc16_match = re.match(r"child-rloc16:\s*(0x[0-9a-fA-F]+)", stripped)
        if child_rloc16_match:
            if current_child and current_child.get("child_rloc16"):
                current_child["ip6_addr_count"] = len(current_child.get("ip6_addrs", []))
                router_child_ip6_data.append(current_child)

            current_child = {
                "child_rloc16": child_rloc16_match.group(1),
                "ip6_addrs": [],
            }
            continue

        if current_child is None:
            continue

        # Child IPv6 addresses are emitted as indented lines below each child-rloc16.
        if re.fullmatch(r"[0-9a-fA-F:]+", stripped) and ":" in stripped:
            current_child["ip6_addrs"].append(stripped.lower())

    if current_child and current_child.get("child_rloc16"):
        current_child["ip6_addr_count"] = len(current_child.get("ip6_addrs", []))
        router_child_ip6_data.append(current_child)

    router_child_ip6["router_child_ip6_table"] = router_child_ip6_data
    router_child_ip6["router_child_ip6_table_count"] = len(router_child_ip6_data)

    return router_child_ip6


def get_meshdiag_childip6_tables(extaddr_map):
    """Collect child IPv6 tables for all active routers in the router table."""

    router_table_data = get_router_table_data(extaddr_map)
    router_rlocs = [router.get("rloc16") for router in router_table_data if router.get("rloc16")]

    router_child_ip6_tables = []

    for parent_rloc16 in router_rlocs:
        router = next((r for r in router_table_data if r.get("rloc16") == parent_rloc16), None)
        if router:
            extaddr = router.get("extaddr")
            device_label = extaddr_map.get(extaddr, "Unknown") if extaddr_map else "Unknown"
            logging.info(
                f"Getting meshdiag childip6 for router rloc16 {parent_rloc16} "
                f"(Node: {device_label}, ExtAddr: {extaddr})..."
            )
        else:
            logging.info(
                f"Getting meshdiag childip6 for router rloc16 {parent_rloc16} "
                "(Node: Unknown, ExtAddr: Unknown)..."
            )

        router_child_ip6 = get_meshdiag_childip6_one(parent_rloc16, router, extaddr_map)
        router_child_ip6_tables.append(router_child_ip6)

    return router_child_ip6_tables


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
    td_data_dir = resolve_td_data_dir(datadir_arg=extract_datadir_arg(argv))

    extaddr_json_filename = data_file_path(EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir)

    if os.path.exists(extaddr_json_filename):
        logging.info(f"Loading extended address to device label mapping from {extaddr_json_filename}...")
        extaddr_map = extaddr_device_label_mapping_load(extaddr_json_filename)
    else:
        logging.warning(
            f"extended address mapping file not found: {extaddr_json_filename}. Continuing with Unknown labels."
        )
        extaddr_map = {}

    router_child_ip6_tables = get_meshdiag_childip6_tables(extaddr_map)

    output_filename = data_file_path("td-otbr-cli-meshdiag-router-childip6.json", td_data_dir)
    with open(output_filename, "w") as f:
        json.dump(router_child_ip6_tables, f, indent=4)

    logging.info(f"Meshdiag router childip6 data saved to {output_filename}")
    print(json.dumps(router_child_ip6_tables, indent=4))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
