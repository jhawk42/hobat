#!/usr/bin/env python3
"""Fetch all Matter nodes from websocket and write raw + extracted reports."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from pathlib import Path
from typing import Any

from util_data import resolve_data_file_path, resolve_data_dir, save_json_atomic

from matter_devices_extractor import extract_nodes_info
from matter_devices_ws_client import DEFAULT_MATTER_WS_URI, fetch_all_nodes


DEFAULT_RAW_OUTPUT = Path(__file__).resolve().parent / "td-matter-ws-devices-fetch-all.json"
DEFAULT_THREAD_OUTPUT = Path(__file__).resolve().parent / "td-matter-ws-devices-thread-fetch-all.json"


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def build_thread_diagnostics(extracted_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    nodes_with_core = 0
    nodes_with_neighbors = 0
    nodes_with_routes = 0
    nodes_with_children = 0
    nodes_with_ipv6 = 0
    nodes_with_rloc16 = 0
    nodes_with_thread_version = 0
    warnings: list[str] = []

    for node in extracted_nodes:
        matter = node.get("matter", {})
        thread = node.get("thread", {})
        node_id = matter.get("node_id")

        core = thread.get("core") if isinstance(thread.get("core"), dict) else {}
        neighbors = thread.get("neighbor_table") if isinstance(thread.get("neighbor_table"), list) else []
        routes = thread.get("route_table") if isinstance(thread.get("route_table"), list) else []
        children = thread.get("child_table") if isinstance(thread.get("child_table"), list) else []
        ipv6_addrs = thread.get("ipv6_addresses") if isinstance(thread.get("ipv6_addresses"), list) else []
        rloc16 = thread.get("rloc16")
        thread_version = thread.get("thread_version")

        if core:
            nodes_with_core += 1
        if neighbors:
            nodes_with_neighbors += 1
        if routes:
            nodes_with_routes += 1
        if children:
            nodes_with_children += 1
        if ipv6_addrs:
            nodes_with_ipv6 += 1
        if rloc16:
            nodes_with_rloc16 += 1
        if thread_version:
            nodes_with_thread_version += 1

        role = core.get("routing_role")
        if role in {"Router", "Leader"} and not routes:
            warnings.append(
                f"node {node_id}: routing_role={role} but route_table is empty"
            )

        if core and not thread_version:
            warnings.append(
                f"node {node_id}: thread core present but thread_version is missing"
            )

    return {
        "nodes_with_thread_core": nodes_with_core,
        "nodes_with_neighbor_table": nodes_with_neighbors,
        "nodes_with_route_table": nodes_with_routes,
        "nodes_with_child_table": nodes_with_children,
        "nodes_with_thread_ipv6": nodes_with_ipv6,
        "nodes_with_rloc16": nodes_with_rloc16,
        "nodes_with_thread_version": nodes_with_thread_version,
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def build_thread_only_payload(
    *,
    uri: str,
    message_count: int,
    node_count: int,
    extracted_nodes: list[dict[str, Any]],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for node in extracted_nodes:
        matter = node.get("matter", {}) if isinstance(node.get("matter"), dict) else {}
        rows.append(
            {
                "node_id": matter.get("node_id"),
                "device_name": matter.get("device_name"),
                "device_type": matter.get("device_type"),
                "thread": node.get("thread", {}),
            }
        )

    return {
        "uri": uri,
        "message_count": message_count,
        "node_count": node_count,
        "extracted_count": len(extracted_nodes),
        "thread_diagnostics": diagnostics,
        "nodes": rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch all Matter node data model payloads from websocket endpoint "
            "and generate raw + extracted Thread/Matter reports."
        )
    )
    parser.add_argument(
        "--uri",
        default=DEFAULT_MATTER_WS_URI,
        help=f"Matter websocket endpoint URI (default: {DEFAULT_MATTER_WS_URI}).",
    )
    parser.add_argument(
        "--raw-output",
        type=Path,
        default=DEFAULT_RAW_OUTPUT,
        help=f"Raw dump output file (default: {DEFAULT_RAW_OUTPUT}).",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=DEFAULT_THREAD_OUTPUT,
        help=f"Extracted summary output file (default: {DEFAULT_THREAD_OUTPUT}).",
    )
    parser.add_argument(
        "--thread-only-output",
        type=Path,
        default=None,
        help="Optional output file for thread-only condensed report.",
    )
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=2.0,
        help="Seconds to wait for new websocket frames before ending fetch.",
    )
    parser.add_argument(
        "--recv-timeout",
        type=float,
        default=5.0,
        help="Per-frame receive timeout in seconds.",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=500,
        help="Maximum websocket frames to collect before stopping.",
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print a concise summary to stdout after writing files.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.max_messages <= 0:
        parser.error("--max-messages must be > 0")

    if args.idle_timeout <= 0:
        parser.error("--idle-timeout must be > 0")

    if args.recv_timeout <= 0:
        parser.error("--recv-timeout must be > 0")

    try:
        fetch_result = asyncio.run(
            fetch_all_nodes(
                uri=args.uri,
                idle_timeout=args.idle_timeout,
                recv_timeout=args.recv_timeout,
                max_messages=args.max_messages,
            )
        )
    except Exception as exc:
        print(f"Error fetching websocket nodes: {exc}", file=sys.stderr)
        return 1

    raw_payload = {
        "uri": fetch_result.uri,
        "message_count": len(fetch_result.messages),
        "node_count": len(fetch_result.nodes),
        "messages": fetch_result.messages,
        "nodes": fetch_result.nodes,
    }

    try:
        extracted = extract_nodes_info(fetch_result.nodes)
        thread_diagnostics = build_thread_diagnostics(extracted)

        summary_payload = {
            "uri": fetch_result.uri,
            "message_count": len(fetch_result.messages),
            "node_count": len(fetch_result.nodes),
            "extracted_count": len(extracted),
            "thread_diagnostics": thread_diagnostics,
            "nodes": extracted,
        }

        thread_only_payload = build_thread_only_payload(
            uri=fetch_result.uri,
            message_count=len(fetch_result.messages),
            node_count=len(fetch_result.nodes),
            extracted_nodes=extracted,
            diagnostics=thread_diagnostics,
        )

        write_json(args.raw_output, raw_payload)
        write_json(args.summary_output, summary_payload)
        if args.thread_only_output is not None:
            write_json(args.thread_only_output, thread_only_payload)
    except Exception as exc:
        print(f"Error writing output files: {exc}", file=sys.stderr)
        return 1

    if args.print_summary:
        print(f"Fetched messages: {len(fetch_result.messages)}")
        print(f"Fetched nodes: {len(fetch_result.nodes)}")
        print(f"Extracted nodes: {len(extracted)}")
        print(f"Raw output: {args.raw_output}")
        print(f"Summary output: {args.summary_output}")
        if args.thread_only_output is not None:
            print(f"Thread-only output: {args.thread_only_output}")
        print(
            "Thread diagnostics: "
            f"core={thread_diagnostics['nodes_with_thread_core']}, "
            f"neighbors={thread_diagnostics['nodes_with_neighbor_table']}, "
            f"routes={thread_diagnostics['nodes_with_route_table']}, "
            f"children={thread_diagnostics['nodes_with_child_table']}, "
            f"warnings={thread_diagnostics['warning_count']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
