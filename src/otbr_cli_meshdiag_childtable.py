import json
import os
import re
import logging
from typing import Sequence

from extaddr_device_label_map import load_extaddr_device_label_map
from otbr_cli_router_table import fetch_and_parse_router_table
from otbr_cli_util import (
    build_timeout_error_record,
    collect_per_router,
    is_response_timeout_error,
    load_extaddr_map_or_empty,
    parse_conn_time,
    parse_err_rate_metrics,
    parse_rss_metrics,
    resolve_collector_runtime,
)
import util_network
from util_ot_ctl import exec_ot_ctl
from util_data import parse_datadir_from_argv, save_json_atomic


def _parse_yes_no_to_bool(value):
    return value.lower() == "yes"


def fetch_meshdiag_child_table_for_device(parent_rloc16, router=None, extaddr_map=None):
    """Collect and parse `meshdiag childtable` output for one parent router."""

    output = exec_ot_ctl(f"meshdiag childtable {parent_rloc16}")
    logging.debug(
        f"[DEBUG] Output of 'meshdiag childtable {parent_rloc16}':\n{output}\n"
    )

    if is_response_timeout_error(output):
        device_label = (
            extaddr_map.get(router.get("extaddr"), "Unknown")
            if router and extaddr_map
            else "Unknown"
        )
        return build_timeout_error_record(
            rloc16=parent_rloc16,
            device_label=device_label,
            result_table_key="router_child_table",
            rloc_key="rloc16",
        )

    router_child_table = {
        "rloc16": parent_rloc16,
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

        # Parse RSS metrics
        rss_metrics = parse_rss_metrics(stripped)
        if rss_metrics:
            current_child.update(rss_metrics)
            continue

        # Parse error rate metrics
        err_rate_metrics = parse_err_rate_metrics(stripped)
        if err_rate_metrics:
            current_child.update(err_rate_metrics)
            continue

        # Parse connection time
        conn_time = parse_conn_time(stripped)
        if conn_time:
            current_child["conn_time"] = conn_time
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
    
    return collect_per_router(
        router_table_data=router_table_data,
        collect_fn=fetch_meshdiag_child_table_for_device,
        extaddr_map=extaddr_map,
        collection_name="meshdiag childtable",
    )


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )
    
    # Resolve runtime paths using shared utility
    runtime = resolve_collector_runtime(
        datadir_arg=parse_datadir_from_argv(argv),
        default_output_filename="td-otbr-cli-meshdiag-router-childtables.json",
    )
    
    # Load extaddr map with unified helper
    extaddr_map = load_extaddr_map_or_empty(runtime.extaddr_map_path)

    try:
        router_child_tables = fetch_all_meshdiag_child_tables(extaddr_map)

        save_json_atomic(router_child_tables, runtime.output_path)

        logging.debug("Saved meshdiag router childtables data into %s as JSON:\n%s",
                      runtime.output_path, json.dumps(router_child_tables, indent=4))
        logging.info(f"Saved meshdiag router childtables with {len(router_child_tables)} entries into {runtime.output_path}.")
        return 0
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logging.error(f"Invalid payload while collecting meshdiag-childtable: {exc}")
        return 5
    except Exception as exc:
        logging.error(f"Runtime failure while collecting meshdiag-childtable: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
