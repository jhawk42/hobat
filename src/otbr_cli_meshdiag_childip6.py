import json
import logging
import os
import re
from pathlib import Path
from typing import Sequence

from extaddr_device_label_map import load_extaddr_device_label_map
from td_const import OTBR_CLI_MESHDIAG_ROUTER_CHILDIP6_FILENAME
from td_json_key_normalizer import convert_keys_to_camel_case
from otbr_cli_router_table import fetch_and_parse_router_table
from otbr_cli_util import (
    build_timeout_error_record,
    collect_per_router,
    is_response_timeout_error,
    load_extaddr_map_or_empty,
    resolve_collector_runtime,
)
from util_ot_ctl import exec_ot_ctl
from util_data import create_checkpoint_filename, parse_datadir_from_argv, save_json_atomic


def _write_checkpoint_best_effort(payload, checkpoint_path: Path) -> None:
    try:
        save_json_atomic(convert_keys_to_camel_case(payload), checkpoint_path)
        logging.info(
            "event=checkpoint_write command=otbr-cli meshdiag childip6 checkpoint_file=%s records=%d stage=router",
            checkpoint_path,
            len(payload) if isinstance(payload, list) else 0,
        )
    except (OSError, ValueError, TypeError) as exc:
        logging.warning(
            "event=checkpoint_write_failed command=otbr-cli meshdiag childip6 checkpoint_file=%s error_type=%s error=%s action=continue_best_effort",
            checkpoint_path,
            type(exc).__name__,
            exc,
        )


def fetch_meshdiag_child_ip6_for_device(parent_rloc16, router=None, extaddr_map=None):
    """Collect and parse `meshdiag childip6` output for one parent router."""

    output = exec_ot_ctl(f"meshdiag childip6 {parent_rloc16}")
    logging.debug(
        f"[DEBUG] Output of 'meshdiag childip6 {parent_rloc16}':\n{output}\n")

    if is_response_timeout_error(output):
        device_label = (
            extaddr_map.get(router.get("extaddr"), "Unknown")
            if router and extaddr_map
            else "Unknown"
        )
        return build_timeout_error_record(
            rloc16=parent_rloc16,
            device_label=device_label,
            result_table_key="router_child_ip6_table",
            rloc_key="rloc16",
        )

    router_child_ip6 = {
        "rloc16": parent_rloc16,
        "device_label": extaddr_map.get(router.get("extaddr"), "Unknown")
        if router and extaddr_map
        else "Unknown",
    }

    router_child_ip6_data = []
    current_child = None

    for line in output.splitlines():
        stripped = line.strip()

        if not stripped or stripped == "Done":
            continue

        child_rloc16_match = re.match(
            r"child-rloc16:\s*(0x[0-9a-fA-F]+)", stripped)
        if child_rloc16_match:
            if current_child and current_child.get("child_rloc16"):
                current_child["ip6_addr_count"] = len(
                    current_child.get("ip6_addrs", [])
                )
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
        current_child["ip6_addr_count"] = len(
            current_child.get("ip6_addrs", []))
        router_child_ip6_data.append(current_child)

    router_child_ip6["router_child_ip6_table"] = router_child_ip6_data
    router_child_ip6["router_child_ip6_table_count"] = len(
        router_child_ip6_data)

    return router_child_ip6


def fetch_all_meshdiag_child_ip6_tables(extaddr_map, on_result=None):
    """Collect child IPv6 tables for all active routers in the router table."""

    router_table_data = fetch_and_parse_router_table(extaddr_map)
    
    return collect_per_router(
        router_table_data=router_table_data,
        collect_fn=fetch_meshdiag_child_ip6_for_device,
        extaddr_map=extaddr_map,
        collection_name="meshdiag childip6",
        on_result=on_result,
    )


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )
    
    # Resolve runtime paths using shared utility
    runtime = resolve_collector_runtime(
        datadir_arg=parse_datadir_from_argv(argv),
        default_output_filename=OTBR_CLI_MESHDIAG_ROUTER_CHILDIP6_FILENAME,
    )
    
    # Load extaddr map with unified helper
    extaddr_map = load_extaddr_map_or_empty(runtime.extaddr_map_path)

    try:
        checkpoint_path = runtime.td_data_dir / create_checkpoint_filename(
            runtime.output_path.name
        )

        def _on_result(results, _rloc16, _router) -> None:
            _write_checkpoint_best_effort(results, checkpoint_path)

        router_child_ip6_tables = fetch_all_meshdiag_child_ip6_tables(
            extaddr_map,
            on_result=_on_result,
        )

        save_json_atomic(
            convert_keys_to_camel_case(router_child_ip6_tables),
            runtime.output_path,
        )

        logging.debug("Saved meshdiag router childip6 data into %s as JSON:\n%s",
                      runtime.output_path, json.dumps(router_child_ip6_tables, indent=4))
        logging.info(f"Saved meshdiag router childip6 tables with {len(router_child_ip6_tables)} entries into {runtime.output_path}.")
        return 0
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logging.error(f"Invalid payload while collecting meshdiag-childip6: {exc}")
        return 5
    except Exception as exc:
        logging.error(f"Runtime failure while collecting meshdiag-childip6: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
