"""Explicit OTBR CLI Primary Backbone Router collection."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import util_ot_ctl
from otbr_cli_router_table import fetch_and_parse_router_table
from otbr_cli_util import load_extaddr_map_or_empty, resolve_collector_runtime
from td_const import OTBR_CLI_BBR_FILENAME
from td_device_fields import get_canonical_rloc16, normalize_input_record
from util_data import CollectionWriteOutcome, parse_datadir_from_argv, save_final_json, save_json_atomic


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
    observation = collect_primary_bbr_observation()
    routers = [normalize_input_record(router, source="cli") for router in fetch_and_parse_router_table(extaddr_map or {})]
    server16 = observation.get("primary", {}).get("server16")
    if server16:
        for router in routers:
            if get_canonical_rloc16(router) == server16:
                router["isPrimaryBBR"] = True
                router["primaryBBREvidence"] = "otbr-cli-bbr-server16-match"
    return {"bbr": observation, "routers": routers}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect an OTBR BBR observation")
    parser.add_argument("--datadir", default=None)
    args = parser.parse_args(argv)
    runtime = resolve_collector_runtime(args.datadir or parse_datadir_from_argv(argv), OTBR_CLI_BBR_FILENAME)
    try:
        result = collect_primary_bbr(load_extaddr_map_or_empty(runtime.extaddr_map_path))
        save_final_json(result, runtime.output_path, CollectionWriteOutcome.complete(), writer=save_json_atomic)
        return 0
    except Exception as exc:
        logging.error("Unable to collect OTBR BBR observation: %s", exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())