import json
import os
import re
import logging
from pathlib import Path
from typing import Sequence

from extaddr_device_label_map import load_extaddr_device_label_map
from td_json_key_normalizer import convert_keys_to_camel_case
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
from util_data import create_checkpoint_filename, parse_datadir_from_argv, save_json_atomic


def _write_checkpoint_best_effort(payload, checkpoint_path: Path) -> None:
    try:
        save_json_atomic(convert_keys_to_camel_case(payload), checkpoint_path)
        logging.info(
            "event=checkpoint_write command=otbr-cli meshdiag routerneighbortable checkpoint_file=%s records=%d stage=router",
            checkpoint_path,
            len(payload) if isinstance(payload, list) else 0,
        )
    except (OSError, ValueError, TypeError) as exc:
        logging.warning(
            "event=checkpoint_write_failed command=otbr-cli meshdiag routerneighbortable checkpoint_file=%s error_type=%s error=%s action=continue_best_effort",
            checkpoint_path,
            type(exc).__name__,
            exc,
        )


def fetch_meshdiag_router_neighbor_table_for_device(rloc16, router=None, extaddr_map=None):
    """
    Dumps the meshdiag routerneighbortable for each router in
    the network and can be used to identify potential issues with specific nodes
    such as high link error counts, etc
    """

    output = exec_ot_ctl(f"meshdiag routerneighbortable {rloc16}")
    logging.debug(
        f"[DEBUG] Output of 'meshdiag routerneighbortable {rloc16}':\n{output}\n"
    )

    if is_response_timeout_error(output):
        device_label = (
            extaddr_map.get(router.get("extaddr"), "Unknown")
            if router and extaddr_map
            else "Unknown"
        )
        return build_timeout_error_record(
            rloc16=rloc16,
            device_label=device_label,
            result_table_key="router_neighbor_table",
            rloc_key="rloc16",
        )

    # store router rloc16
    # lookup rloc16 in router_table_data to get extaddr and device label if available

    router_neighbor_table = {}
    # store router rloc16 and device_label in router_neighbor_table for reference
    router_neighbor_table["rloc16"] = rloc16
    router_neighbor_table["device_label"] = (
        extaddr_map.get(router.get("extaddr"), "Unknown")
        if router and extaddr_map
        else "Unknown"
    )
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
                logging.warning(
                    "meshdiag routerneighbortable: unexpected format, pattern did not match: %r",
                    stripped,
                )
                current_neighbor = None
                continue

            current_neighbor = {
                "rloc16": match.group(1),
                "extaddr": match.group(2).lower(),
                "device_label": extaddr_map.get(match.group(2).lower(), "Unknown")
                if extaddr_map
                else "Unknown",
                "ver": int(match.group(3)),
                "thread_version": util_network.decode_short_thread_version(
                    int(match.group(3))                )
                if match.group(3) else "Unknown",
            }
            continue

        # if we are here, we should be processing a neighbor entry, if not, skip
        if current_neighbor is None:
            continue

        # Parse RSS metrics
        rss_metrics = parse_rss_metrics(stripped)
        if rss_metrics:
            current_neighbor.update(rss_metrics)
            continue

        # Parse error rate metrics
        err_rate_metrics = parse_err_rate_metrics(stripped)
        if err_rate_metrics:
            current_neighbor.update(err_rate_metrics)
            continue

        # Parse connection time
        conn_time = parse_conn_time(stripped)
        if conn_time:
            current_neighbor["conn_time"] = conn_time

    # add last neighbor if exists and has rloc16
    if current_neighbor and current_neighbor.get("rloc16"):
        router_neighbor_table_data.append(current_neighbor)

    router_neighbor_table["router_neighbor_table"] = router_neighbor_table_data
    # store count of neighbors in router_neighbor_table for easy reference
    router_neighbor_table["router_neighbor_table_count"] = len(
        router_neighbor_table_data
    )

    return router_neighbor_table


def fetch_all_meshdiag_router_neighbor_tables(extaddr_map=None, on_result=None):

    # 1. Get all active routers (potential parents)
    router_table_data = fetch_and_parse_router_table(extaddr_map)
    
    return collect_per_router(
        router_table_data=router_table_data,
        collect_fn=fetch_meshdiag_router_neighbor_table_for_device,
        extaddr_map=extaddr_map,
        collection_name="meshdiag routerneighbortable",
        on_result=on_result,
    )


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )
    
    # Resolve runtime paths using shared utility
    runtime = resolve_collector_runtime(
        datadir_arg=parse_datadir_from_argv(argv),
        default_output_filename="td-otbr-cli-meshdiag-router-neighbortables.json",
    )
    
    # Load extaddr map with unified helper
    extaddr_map = load_extaddr_map_or_empty(runtime.extaddr_map_path)

    try:
        checkpoint_path = runtime.td_data_dir / create_checkpoint_filename(
            runtime.output_path.name
        )

        def _on_result(results, _rloc16, _router) -> None:
            _write_checkpoint_best_effort(results, checkpoint_path)

        router_neighbor_tables = fetch_all_meshdiag_router_neighbor_tables(
            extaddr_map,
            on_result=_on_result,
        )

        save_json_atomic(
            convert_keys_to_camel_case(router_neighbor_tables),
            runtime.output_path,
        )

        logging.debug("Saved meshdiag routerneighbortables data into %s as JSON:\n%s",
                      runtime.output_path, json.dumps(router_neighbor_tables, indent=4))

        logging.info(f"Saved meshdiag routerneighbortables with {len(router_neighbor_tables)} entries into {runtime.output_path}.")
        return 0
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logging.error(f"Invalid payload while collecting meshdiag-routerneighbortable: {exc}")
        return 5
    except Exception as exc:
        logging.error(f"Runtime failure while collecting meshdiag-routerneighbortable: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
