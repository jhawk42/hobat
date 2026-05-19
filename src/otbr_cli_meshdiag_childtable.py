import json
import os
import re
import logging
from typing import Sequence

from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
from otbr_cli_router_table import fetch_and_parse_router_table
from extaddr_device_label_map import load_extaddr_device_label_map
import util_network
from util_ot_ctl import exec_ot_ctl
from util_data import data_file_path, parse_datadir_from_argv, resolve_data_dir, save_json_atomic


def _parse_yes_no_to_bool(value):
    return value.lower() == "yes"


def fetch_meshdiag_child_table_for_device(parent_rloc16, router=None, extaddr_map=None):
    """Collect and parse `meshdiag childtable` output for one parent router."""

    output = exec_ot_ctl(f"meshdiag childtable {parent_rloc16}")
    logging.debug(
        f"[DEBUG] Output of 'meshdiag childtable {parent_rloc16}':\n{output}\n"
    )

    timeout_match = re.search(r"Error\s+(\d+):\s+ResponseTimeout", output)
    if timeout_match:
        return {
            "parent_rloc16": parent_rloc16,
            "device_label": extaddr_map.get(router.get("extaddr"), "Unknown")
            if router and extaddr_map
            else "Unknown",
            "router_child_table": [],
            "router_child_table_count": 0,
            "_error": {"type": "ResponseTimeout"},
        }

    router_child_table = {
        "parent_rloc16": parent_rloc16,
        "device_label": extaddr_map.get(router.get("extaddr"), "Unknown")
        if router and extaddr_map
        else "Unknown",
    }
    router_child_table_data = []
    current_child = None

    for line in output.splitlines():
        stripped = line.strip()

        if not stripped or stripped == "Done":
            continue

        if stripped.startswith("rloc16:"):
            if current_child and current_child.get("rloc16"):
                router_child_table_data.append(current_child)

            match = re.match(
                r"rloc16:(0x[0-9a-fA-F]+)\s+ext-addr:([0-9a-fA-F]+)\s+ver:(\d+)",
                stripped,
            )
            if not match:
                logging.warning(
                    "meshdiag childtable: unexpected format, pattern did not match: %r",
                    stripped,
                )
                current_child = None
                continue

            child_extaddr = match.group(2).lower()
            current_child = {
                "rloc16": match.group(1),
                "extaddr": child_extaddr,
                "device_label": extaddr_map.get(child_extaddr, "Unknown")
                if extaddr_map
                else "Unknown",
                "ver": int(match.group(3)),
                "thread_version": util_network.decode_short_thread_version(
                    int(match.group(3))                )
                if match.group(3) else "Unknown",
            }
            continue

        if current_child is None:
            continue

        timeout_age_match = re.match(
            r"timeout:(\d+)\s+age:(\d+)\s+supvn:(\d+)\s+q-msg:(\d+)",
            stripped,
        )
        if timeout_age_match:
            current_child["timeout"] = int(timeout_age_match.group(1))
            current_child["age"] = int(timeout_age_match.group(2))
            current_child["supvn"] = int(timeout_age_match.group(3))
            current_child["q_msg"] = int(timeout_age_match.group(4))
            continue

        rx_type_match = re.match(
            r"rx-on:(yes|no)\s+type:(\S+)\s+full-net:(yes|no)",
            stripped,
        )
        if rx_type_match:
            current_child["rx_on"] = _parse_yes_no_to_bool(
                rx_type_match.group(1))
            current_child["type"] = rx_type_match.group(2)
            current_child["full_net"] = _parse_yes_no_to_bool(
                rx_type_match.group(3))
            continue

        rss_match = re.match(
            r"rss\s+-\s+ave:(-?\d+)\s+last:(-?\d+)\s+margin:(-?\d+)",
            stripped,
        )
        if rss_match:
            current_child["rss_ave"] = int(rss_match.group(1))
            current_child["rss_last"] = int(rss_match.group(2))
            current_child["rss_margin"] = int(rss_match.group(3))
            continue

        err_rate_match = re.match(
            r"err-rate\s+-\s+frame:([0-9]+(?:\.[0-9]+)?)%\s+msg:([0-9]+(?:\.[0-9]+)?)%",
            stripped,
        )
        if err_rate_match:
            current_child["err_rate_frame_pct"] = float(
                err_rate_match.group(1))
            current_child["err_rate_msg_pct"] = float(err_rate_match.group(2))
            continue

        conn_time_match = re.match(r"conn-time:(\S+)", stripped)
        if conn_time_match:
            current_child["conn_time"] = conn_time_match.group(1)
            continue

        csl_match = re.match(
            r"csl\s+-\s+sync:(yes|no)\s+period:(\d+)\s+timeout:(\d+)\s+channel:(\d+)",
            stripped,
        )
        if csl_match:
            current_child["csl_sync"] = _parse_yes_no_to_bool(
                csl_match.group(1))
            current_child["csl_period"] = int(csl_match.group(2))
            current_child["csl_timeout"] = int(csl_match.group(3))
            current_child["csl_channel"] = int(csl_match.group(4))

    if current_child and current_child.get("rloc16"):
        router_child_table_data.append(current_child)

    router_child_table["router_child_table"] = router_child_table_data
    router_child_table["router_child_table_count"] = len(
        router_child_table_data)

    return router_child_table


def fetch_all_meshdiag_child_tables(extaddr_map):
    """Collect child tables for all active routers in the router table."""

    router_table_data = fetch_and_parse_router_table(extaddr_map)
    router_rlocs = [
        router.get("rloc16") for router in router_table_data if router.get("rloc16")
    ]

    router_child_tables = []

    for parent_rloc16 in router_rlocs:
        router = next(
            (r for r in router_table_data if r.get(
                "rloc16") == parent_rloc16), None
        )
        if router:
            extaddr = router.get("extaddr")
            device_label = (
                extaddr_map.get(
                    extaddr, "Unknown") if extaddr_map else "Unknown"
            )
            logging.info(
                f"Getting meshdiag childtable for router rloc16 {parent_rloc16} "
                f"(Node: {device_label}, ExtAddr: {extaddr})..."
            )
        else:
            logging.info(
                f"Getting meshdiag childtable for router rloc16 {parent_rloc16} "
                "(Node: Unknown, ExtAddr: Unknown)..."
            )

        router_child_table = fetch_meshdiag_child_table_for_device(
            parent_rloc16, router, extaddr_map
        )
        router_child_tables.append(router_child_table)

    return router_child_tables


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )
    td_data_dir = resolve_data_dir(
        data_dir=parse_datadir_from_argv(argv))

    extaddr_json_filename = data_file_path(
        EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir
    )

    if os.path.exists(extaddr_json_filename):
        logging.info(
            f"Loading extended address to device label mapping from {extaddr_json_filename}..."
        )
        extaddr_map = load_extaddr_device_label_map(extaddr_json_filename)
    else:
        logging.warning(
            f"extended address mapping file not found: {extaddr_json_filename}. Continuing with Unknown labels."
        )
        extaddr_map = {}

    router_child_tables = fetch_all_meshdiag_child_tables(extaddr_map)

    output_filename = data_file_path(
        "td-otbr-cli-meshdiag-router-childtables.json", td_data_dir
    )
    save_json_atomic(router_child_tables, output_filename)

    logging.info(
        f"Meshdiag router childtables data saved to {output_filename}")
    logging.debug("Raw meshdiag router childtables data as JSON:\n%s",
                  json.dumps(router_child_tables, indent=4))


if __name__ == "__main__":
    raise SystemExit(main())
