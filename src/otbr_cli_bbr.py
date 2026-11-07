"""Explicit OTBR CLI Primary Backbone Router collection."""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Sequence

import util_ot_ctl
from td_logging import log_event
from otbr_cli_router_table import fetch_and_parse_router_table
from otbr_cli_util import load_extaddr_map_or_empty, resolve_collector_runtime
from td_const import OTBR_CLI_BBR_FILENAME
from td_device_fields import get_canonical_rloc16, normalize_input_record
from util_data import CollectionWriteOutcome, parse_datadir_from_argv, save_final_json, save_json_atomic


def extract_cached_bbr_records(payload: Any) -> list[dict[str, Any]]:
    if (not isinstance(payload, dict) or not isinstance(payload.get("routers"), list)
            or not isinstance(payload.get("bbr"), dict)
            or any(not isinstance(row, dict) for row in payload["routers"])):
        raise ValueError("Invalid cached BBR observation")
    return [{**deepcopy(record), "bbr": deepcopy(payload["bbr"])}
            for record in payload["routers"]]


def normalize_rloc16(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    return f"0x{text}" if re.fullmatch(r"[0-9a-f]{4}", text) else None


def parse_bbr_output(output: str) -> dict[str, Any]:
    """Parse only the BBR Primary block; its metadata is not device identity."""
    primary_match = re.search(
        r"^BBR Primary:\s*$([\s\S]*?)(?=^Done\s*$|\Z)",
        output,
        re.MULTILINE,
    )
    if not primary_match:
        return {}
    primary: dict[str, Any] = {}
    for line in primary_match.group(1).splitlines():
        match = re.match(r"\s*(server16|seqno|delay|timeout)\s*:\s*(\S+)\s*$", line, re.IGNORECASE)
        if not match:
            continue
        key = match.group(1).lower()
        value = match.group(2)
        if key == "server16":
            rloc16 = normalize_rloc16(value)
            if rloc16:
                primary["server16"] = rloc16
        elif value.isdigit():
            primary[key] = int(value)
    return {"primary": primary} if primary else {}


def collect_primary_bbr_observation() -> dict[str, Any]:
    return parse_bbr_output(util_ot_ctl.exec_ot_ctl("bbr"))


def collect_primary_bbr(extaddr_map: dict[str, str] | None = None) -> dict[str, Any]:
    started_at = time.monotonic()
    normal_return = False
    observation = None
    router_records = None
    try:
        observation = collect_primary_bbr_observation()
        routers = [normalize_input_record(router, source="cli") for router in fetch_and_parse_router_table(extaddr_map or {})]
        router_records = len(routers)
        server16 = observation.get("primary", {}).get("server16")
        if server16:
            for router in routers:
                if get_canonical_rloc16(router) == server16:
                    router["isPrimaryBBR"] = True
                    router["primaryBBREvidence"] = "otbr-cli-bbr-server16-match"
        result = {"bbr": observation, "routers": routers}
        normal_return = True
        return result
    finally:
        log_event(
            "collector_summary", source="otbr-cli", command="bbr", stage="bulk",
            router_records=router_records,
            primary_bbr_present=(
                bool(observation.get("primary")) if observation is not None else None
            ),
            elapsed_ms=max(0, round((time.monotonic() - started_at) * 1000)),
            state="returned" if normal_return else "failed",
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect an OTBR BBR observation")
    parser.add_argument("--datadir", default=None)
    args = parser.parse_args(argv)
    runtime = resolve_collector_runtime(args.datadir or parse_datadir_from_argv(argv), OTBR_CLI_BBR_FILENAME)
    try:
        result = collect_primary_bbr(load_extaddr_map_or_empty(runtime.extaddr_map_path))
        write_returned = False
        try:
            written = save_final_json(
                result, runtime.output_path, CollectionWriteOutcome.complete(),
                writer=save_json_atomic,
            )
            write_returned = True
        finally:
            if write_returned:
                log_event(
                    "write", source="otbr-cli", command="bbr", stage="final",
                    output=str(runtime.output_path),
                    router_records=len(result["routers"]),
                    primary_bbr_present=bool(result["bbr"].get("primary")),
                    disposition="saved" if written else "retained_previous",
                )
            else:
                error = sys.exc_info()[1]
                log_event(
                    "write", source="otbr-cli", command="bbr", stage="final",
                    output=str(runtime.output_path),
                    router_records=len(result["routers"]),
                    primary_bbr_present=bool(result["bbr"].get("primary")),
                    disposition="failed",
                    error_type=type(error).__name__ if error is not None else None,
                )
        return 0
    except Exception as exc:
        logging.error("Unable to collect OTBR BBR observation: %s", exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())