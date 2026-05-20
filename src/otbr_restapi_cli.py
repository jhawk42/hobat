from __future__ import annotations

import argparse
import json
import sys
import logging
import time

from pathlib import Path
from typing import Any, Sequence
from util_data import resolve_data_file_path, resolve_data_dir, save_json_atomic
from td_const import TD_DATA_DIR_ARG_HELP

from otbr_restapi_util import (
    
    DEFAULT_ACCEPT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DIAG_TLV_CHILDREN,
    DIAG_TLV_CHILD_IPV6_ADDRS,
    DIAG_TLV_ROUTER_NEIGHBORS,
    FULL_DIAGNOSTIC_TLVS,
    MESH_DIAGNOSTIC_TLVS,
    MINIMAL_DIAGNOSTIC_TLVS,
    BASIC_DIAGNOSTIC_TLVS,
    RECOMMENDED_DIAGNOSTIC_TLVS,
    DestinationType,
    OTBRActionError,
    OTBRActionFailedError,
    OTBRActionTimeoutError,
    OTBRClientError,
    OTBRConnectionError,
    OTBRHTTPError,
    OTBRInvalidResponseError,
    OTBRRestApiClient,
    OTBRUsageError,
    _RAW_UNSET,
    build_fields_mapping,
    error_to_dict,
    extract_action_result_id,
)

EXIT_SUCCESS = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_CONNECTION = 3
EXIT_HTTP = 4
EXIT_INVALID_RESPONSE = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CLI wrapper for the OpenThread Border Router REST API.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help="OTBR REST API host")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="OTBR REST API port"
    )
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    parser.add_argument(
        "--base-url", help="Override host/port with a full base URL")
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds"
    )
    parser.add_argument(
        "--accept",
        default=DEFAULT_ACCEPT,
        choices=["application/vnd.api+json", "application/json", "text/plain"],
        help="Default Accept header",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Return raw API envelopes instead of flattened output",
    )
    parser.add_argument("--output", help="Write the command result to a file")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        metavar="FLOAT",
        help="Seconds between action status polls (default: 2.0)",
    )
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=120.0,
        metavar="FLOAT",
        help="Max wall-clock seconds to wait for an action to complete (default: 120.0)",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        default=False,
        help="Suppress per-device progress output to stderr on fetch-all commands (P6)",
    )
    parser.add_argument(
        "--no-auto-output",
        action="store_true",
        default=False,
        help=(
            "Disable automatic output file naming. By default, fetch/fetch-all commands "
            "write results to <datadir>/td-otbr-restapi-<resource>-<command>.json (P5)"
        ),
    )

    subparsers = parser.add_subparsers(dest="resource", required=True)
    _add_node_commands(subparsers)
    _add_devices_commands(subparsers)
    _add_diagnostics_commands(subparsers)
    _add_actions_commands(subparsers)
    _add_mesh_diagnostics_commands(subparsers)
    _add_topology_commands(subparsers)
    return parser


def _add_node_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    node_parser = subparsers.add_parser(
        "node", help="Read or mutate local OTBR node data"
    )
    node_subparsers = node_parser.add_subparsers(
        dest="node_command", required=True)

    node_get = node_subparsers.add_parser(
        "get", help="Get the OTBR node record from /api/node"
    )
    _add_fields_argument(node_get)

    state_parser = node_subparsers.add_parser(
        "state", help="Get or set Thread state")
    state_subparsers = state_parser.add_subparsers(
        dest="state_command", required=True)
    state_subparsers.add_parser("get", help="Get current Thread state")
    state_set = state_subparsers.add_parser(
        "set", help="Enable or disable Thread")
    state_set.add_argument("--value", required=True,
                           choices=["enable", "disable"])

    dataset_parser = node_subparsers.add_parser(
        "dataset", help="Operate on node datasets"
    )
    dataset_subparsers = dataset_parser.add_subparsers(
        dest="dataset_kind", required=True
    )
    active_parser = dataset_subparsers.add_parser(
        "active", help="Operate on active dataset"
    )
    active_subparsers = active_parser.add_subparsers(
        dest="dataset_command", required=True
    )
    active_get = active_subparsers.add_parser("get", help="Get active dataset")
    active_get.add_argument(
        "--text", action="store_true", help="Request text/plain TLV dataset"
    )

    active_set = active_subparsers.add_parser(
        "set", help="Create or update active dataset"
    )
    group = active_set.add_mutually_exclusive_group(required=True)
    group.add_argument("--json", help="Inline JSON payload for dataset")
    group.add_argument(
        "--json-file", help="Path to a JSON file containing the dataset")
    group.add_argument("--text", help="Inline TLV dataset string")
    group.add_argument(
        "--text-file", help="Path to a text file containing the TLV dataset"
    )


def _add_devices_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    devices_parser = subparsers.add_parser("devices", help="Read OTBR devices")
    devices_subparsers = devices_parser.add_subparsers(
        dest="devices_command", required=True
    )

    devices_list = devices_subparsers.add_parser("list", help="List devices")
    _add_fields_argument(devices_list)
    devices_list.add_argument(
        "--with-meta",
        action="store_true",
        help="Include collection meta with flattened items",
    )

    devices_get = devices_subparsers.add_parser(
        "get", help="Get a device by device ID")
    devices_get.add_argument("--device-id", required=True)
    _add_fields_argument(devices_get)

    devices_fetch = devices_subparsers.add_parser(
        "fetch",
        help=(
            "Trigger updateDeviceCollectionTask, wait for it, and return "
            "the populated device list"
        ),
    )
    devices_fetch.add_argument(
        "--device-count", type=int, default=200, help="Max devices to discover (default: 200)"
    )
    devices_fetch.add_argument(
        "--task-timeout", type=int, default=600,
        help="Server-side task timeout in seconds (default: 600)",
    )
    devices_fetch.add_argument(
        "--max-age", type=int, default=60,
        help="Max age of cached device entries in seconds (default: 60)",
    )
    devices_fetch.add_argument(
        "--max-retries", type=int, default=5,
        help="Max retries per device (default: 5)",
    )


def _add_diagnostics_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    diagnostics_parser = subparsers.add_parser(
        "diagnostics", help="Read OTBR diagnostics"
    )
    diagnostics_subparsers = diagnostics_parser.add_subparsers(
        dest="diagnostics_command", required=True
    )

    diagnostics_list = diagnostics_subparsers.add_parser(
        "list", help="List diagnostics"
    )
    _add_fields_argument(diagnostics_list)
    diagnostics_list.add_argument(
        "--with-meta",
        action="store_true",
        help="Include collection meta with flattened items",
    )

    diagnostics_get = diagnostics_subparsers.add_parser(
        "get", help="Get a diagnostic by diagnostics ID"
    )
    diagnostics_get.add_argument("--diagnostics-id", required=True)

    diagnostics_fetch = diagnostics_subparsers.add_parser(
        "fetch",
        help=(
            "Enqueue getNetworkDiagnosticTask for a device, wait for completion, "
            "and return the diagnostic result"
        ),
    )
    diagnostics_fetch.add_argument("--device-id", required=True,
                                   help="Device extAddress (16-char hex)")
    diagnostics_fetch.add_argument(
        "--types", nargs="+", metavar="TLV",
        help="Diagnostic TLV names (default: RECOMMENDED_DIAGNOSTIC_TLVS)",
    )
    diagnostics_fetch.add_argument(
        "--preset", choices=["recommended", "full", "minimal", "basic"],
        help="Use a predefined TLV preset; overrides --types",
    )
    diagnostics_fetch.add_argument(
        "--task-timeout", type=int, default=600,
        help="Server-side task timeout in seconds (default: 600)",
    )
    diagnostics_fetch.add_argument(
        "--destination-type", default=DestinationType.EXTENDED,
        help=f"Destination addressing mode (default: {DestinationType.EXTENDED})",
    )
    diagnostics_fetch.add_argument(
        "--no-fallback",
        action="store_true",
        default=False,
        help="Disable per-device TLV fallback retry on failure (P1)",
    )
    diagnostics_fetch.add_argument(
        "--fallback-preset",
        choices=["medium", "minimal", "basic"],
        default="minimal",
        help="TLV preset to retry with on device failure (default: minimal) (P1)",
    )
    diagnostics_fetch.add_argument(
        "--no-enrich-mac-counters",
        action="store_true",
        default=False,
        help="Return raw macCounters values without computed totals and ratios (P3)",
    )

    diagnostics_fetch_all = diagnostics_subparsers.add_parser(
        "fetch-all",
        help=(
            "Fetch diagnostics for all known devices (or a given list), "
            "one device at a time"
        ),
    )
    diagnostics_fetch_all.add_argument(
        "--device-ids", nargs="+", metavar="ID",
        help="Device extAddress IDs to query (default: all devices from /api/devices)",
    )
    diagnostics_fetch_all.add_argument(
        "--types", nargs="+", metavar="TLV",
        help="Diagnostic TLV names (default: RECOMMENDED_DIAGNOSTIC_TLVS)",
    )
    diagnostics_fetch_all.add_argument(
        "--preset", choices=["recommended", "full", "minimal", "basic"],
        help="Use a predefined TLV preset; overrides --types",
    )
    diagnostics_fetch_all.add_argument(
        "--task-timeout", type=int, default=600,
        help="Server-side task timeout per device in seconds (default: 600)",
    )
    diagnostics_fetch_all.add_argument(
        "--destination-type", default=DestinationType.EXTENDED,
        help=f"Destination addressing mode (default: {DestinationType.EXTENDED})",
    )
    diagnostics_fetch_all.add_argument(
        "--no-update-devices",
        action="store_true",
        default=False,
        help=(
            "Skip updateDeviceCollectionTask before fetching diagnostics. "
            "By default the device list is refreshed first (P7)"
        ),
    )
    diagnostics_fetch_all.add_argument(
        "--no-fallback",
        action="store_true",
        default=False,
        help="Disable per-device TLV fallback retry on failure (P1)",
    )
    diagnostics_fetch_all.add_argument(
        "--fallback-preset",
        choices=["medium", "minimal", "basic"],
        default="minimal",
        help="TLV preset to retry with on device failure (default: minimal) (P1)",
    )
    diagnostics_fetch_all.add_argument(
        "--no-enrich-mac-counters",
        action="store_true",
        default=False,
        help="Return raw macCounters values without computed totals and ratios (P3)",
    )


def _add_actions_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    actions_parser = subparsers.add_parser(
        "actions", help="Read or enqueue OTBR actions"
    )
    actions_subparsers = actions_parser.add_subparsers(
        dest="actions_command", required=True
    )

    actions_list = actions_subparsers.add_parser("list", help="List actions")
    _add_fields_argument(actions_list)
    actions_list.add_argument(
        "--with-meta",
        action="store_true",
        help="Include collection meta with flattened items",
    )

    actions_get = actions_subparsers.add_parser(
        "get", help="Get an action by action ID"
    )
    actions_get.add_argument("--action-id", required=True)

    enqueue_parser = actions_subparsers.add_parser(
        "enqueue", help="Enqueue a new OTBR task"
    )
    enqueue_subparsers = enqueue_parser.add_subparsers(
        dest="enqueue_type", required=True
    )

    add_thread_device = enqueue_subparsers.add_parser(
        "add-thread-device", help="Enqueue addThreadDeviceTask"
    )
    add_thread_device.add_argument("--pskd", required=True)
    identity_group = add_thread_device.add_mutually_exclusive_group(
        required=True)
    identity_group.add_argument("--eui")
    identity_group.add_argument("--discerner")
    identity_group.add_argument("--joiner-id")
    add_thread_device.add_argument("--timeout", type=int)

    get_network_diag = enqueue_subparsers.add_parser(
        "get-network-diagnostic", help="Enqueue getNetworkDiagnosticTask"
    )
    get_network_diag.add_argument("--destination", required=True)
    get_network_diag.add_argument(
        "--types", nargs="+", metavar="TLV",
        help="Diagnostic TLVs by name or integer (required unless --preset is given)",
    )
    get_network_diag.add_argument(
        "--preset", choices=["recommended", "full", "minimal", "basic"],
        help="Use a predefined TLV preset; overrides --types",
    )
    get_network_diag.add_argument("--timeout", type=int,
                                  help="Server-side task timeout in seconds")
    get_network_diag.add_argument("--destination-type")
    get_network_diag.add_argument(
        "--wait", action="store_true", default=False,
        help=(
            "After enqueuing, poll until completion and return the diagnostic result. "
            "Uses --poll-interval and --poll-timeout. Exit code 4 on stopped/failed."
        ),
    )

    reset_network_diag = enqueue_subparsers.add_parser(
        "reset-network-diag-counter", help="Enqueue resetNetworkDiagCounterTask"
    )
    reset_network_diag.add_argument(
        "--types", nargs="+", required=True, help="Counter TLVs by name or integer"
    )
    reset_network_diag.add_argument("--destination")
    reset_network_diag.add_argument("--timeout", type=int)
    reset_network_diag.add_argument("--destination-type")

    energy_scan = enqueue_subparsers.add_parser(
        "get-energy-scan", help="Enqueue getEnergyScanTask"
    )
    energy_scan.add_argument("--destination", required=True)
    energy_scan.add_argument(
        "--channel-mask", nargs="+", required=True, type=int)
    energy_scan.add_argument("--count", required=True, type=int)
    energy_scan.add_argument("--period", required=True, type=int)
    energy_scan.add_argument("--scan-duration", required=True, type=int)
    energy_scan.add_argument("--timeout", required=True, type=int)
    energy_scan.add_argument("--destination-type")

    update_devices = enqueue_subparsers.add_parser(
        "update-device-collection", help="Enqueue updateDeviceCollectionTask"
    )
    update_devices.add_argument(
        "--max-age", type=int, default=30,
        help="Maximum age (seconds) for cached device entries (default: 30)"
    )
    update_devices.add_argument(
        "--max-retries", type=int, default=5,
        help="Maximum retries per device (default: 5)"
    )
    update_devices.add_argument(
        "--device-count", type=int, default=200,
        help="Maximum number of devices to discover (default: 200)"
    )
    update_devices.add_argument(
        "--timeout", type=int, default=300,
        help="Task timeout passed to the server in seconds (default: 300)"
    )


def _add_fields_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fields",
        action="append",
        help="Repeatable sparse-field selector such as 'threadDevice=hostname,role' or 'threadDevice'",
    )


def _add_mesh_diagnostics_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    mesh_parser = subparsers.add_parser(
        "mesh-diagnostics",
        help=(
            "Fetch mesh-diagnostic TLVs (children, childIpv6Addresses, routerNeighbors). "
            "These require an additional otMeshDiag round-trip on the server and have "
            "higher latency than standard diagnostic TLVs."
        ),
    )
    mesh_subparsers = mesh_parser.add_subparsers(
        dest="mesh_diag_command", required=True
    )

    def _mesh_device_args(p: argparse.ArgumentParser, task_timeout: int = 600) -> None:
        p.add_argument("--device-id", required=True,
                       help="Device extAddress (16-char hex)")
        p.add_argument(
            "--task-timeout", type=int, default=task_timeout,
            help=f"Server-side task timeout in seconds (default: {task_timeout})",
        )
        p.add_argument(
            "--poll-timeout", type=float, default=360.0, metavar="FLOAT",
            help=(
                "Max wall-clock seconds to wait for the action (default: 360.0). "
                "Mesh-diagnostic queries require an additional otMeshDiag round-trip."
            ),
        )
        p.add_argument(
            "--destination-type", default=DestinationType.EXTENDED,
            help=f"Destination addressing mode (default: {DestinationType.EXTENDED})",
        )

    children_p = mesh_subparsers.add_parser(
        "children",
        help=(
            "Fetch the child table for a device via otMeshDiag (TLV 29). "
            "Higher latency than standard diagnostic TLVs."
        ),
    )
    _mesh_device_args(children_p)

    child_ipv6_p = mesh_subparsers.add_parser(
        "child-ipv6",
        help=(
            "Fetch child IPv6 addresses for a device via otMeshDiag (TLV 30). "
            "Higher latency than standard diagnostic TLVs."
        ),
    )
    _mesh_device_args(child_ipv6_p)

    router_neighbors_p = mesh_subparsers.add_parser(
        "router-neighbors",
        help=(
            "Fetch router neighbor table for a device via otMeshDiag (TLV 31). "
            "Higher latency than standard diagnostic TLVs."
        ),
    )
    _mesh_device_args(router_neighbors_p)

    mesh_fetch_p = mesh_subparsers.add_parser(
        "fetch",
        help=(
            "Fetch a caller-specified subset of mesh-diagnostic TLVs for a single device. "
            "Allowed types: children, childIpv6Addresses, routerNeighbors."
        ),
    )
    _mesh_device_args(mesh_fetch_p)
    mesh_fetch_p.add_argument(
        "--types", nargs="+", metavar="TLV",
        default=None,
        help=(
            "Mesh-diagnostic TLV names to request. "
            "Allowed: children, childIpv6Addresses, routerNeighbors. "
            "Defaults to all three when omitted."
        ),
    )

    mesh_fetch_all_p = mesh_subparsers.add_parser(
        "fetch-all",
        help=(
            "Fetch mesh diagnostics for all known devices (or a given list), "
            "one device at a time."
        ),
    )
    mesh_fetch_all_p.add_argument(
        "--device-ids", nargs="+", metavar="ID",
        help="Device extAddress IDs to query (default: all devices from /api/devices)",
    )
    mesh_fetch_all_p.add_argument(
        "--types", nargs="+", metavar="TLV",
        default=None,
        help=(
            "Mesh-diagnostic TLV names. "
            "Allowed: children, childIpv6Addresses, routerNeighbors. "
            "Defaults to all three when omitted."
        ),
    )
    mesh_fetch_all_p.add_argument(
        "--task-timeout", type=int, default=600,
        help="Server-side task timeout per device in seconds (default: 600)",
    )
    mesh_fetch_all_p.add_argument(
        "--poll-timeout", type=float, default=360.0, metavar="FLOAT",
        help="Max wall-clock seconds per device action (default: 360.0)",
    )
    mesh_fetch_all_p.add_argument(
        "--destination-type", default=DestinationType.EXTENDED,
        help=f"Destination addressing mode (default: {DestinationType.EXTENDED})",
    )
    mesh_fetch_all_p.add_argument(
        "--no-update-devices",
        action="store_true",
        default=False,
        help=(
            "Skip updateDeviceCollectionTask before fetching mesh diagnostics. "
            "By default the device list is refreshed first (P7)"
        ),
    )
    mesh_fetch_all_p.add_argument(
        "--routers-only",
        action="store_true",
        default=False,
        help=(
            "Restrict queries to router devices only (rloc16 lower-10-bits == 0). "
            "Avoids wasting task slots on child devices for mesh-diagnostic TLVs (P2)"
        ),
    )


def _add_topology_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """P4 — Combined topology sweep: devices → diagnostics → mesh-diagnostics."""
    topo_p = subparsers.add_parser(
        "topology",
        help=(
            "Full topology sweep: (1) devices fetch, (2) diagnostics fetch-all "
            "--preset recommended, (3) mesh-diagnostics fetch-all --routers-only. "
            "All three output files are written under --datadir automatically."
        ),
    )
    topo_p.add_argument(
        "--preset",
        choices=["recommended", "full", "minimal", "basic"],
        default="recommended",
        help="TLV preset for the diagnostics step (default: recommended)",
    )
    topo_p.add_argument(
        "--skip-devices",
        action="store_true",
        help="Skip Step 1 (device refresh via updateDeviceCollectionTask)",
    )
    topo_p.add_argument(
        "--skip-diagnostics",
        action="store_true",
        help="Skip Step 2 (network diagnostics fetch-all)",
    )
    topo_p.add_argument(
        "--skip-mesh-diagnostics",
        action="store_true",
        help="Skip Step 3 (mesh diagnostics fetch-all)",
    )
    topo_p.add_argument(
        "--no-update-devices",
        action="store_true",
        default=False,
        help="Skip updateDeviceCollectionTask before diagnostics/mesh steps (P7)",
    )
    topo_p.add_argument(
        "--no-enrich-mac-counters",
        action="store_true",
        default=False,
        help="Disable MAC counter enrichment on the diagnostics result (P3)",
    )
    topo_p.add_argument(
        "--no-fallback",
        action="store_true",
        default=False,
        help="Disable per-device TLV fallback retry on failure (P1)",
    )
    topo_p.add_argument(
        "--fallback-preset",
        choices=["medium", "minimal", "basic"],
        default="minimal",
        help="TLV preset to retry with on per-device failure (default: minimal) (P1)",
    )


# ---------------------------------------------------------------------------
# Medium TLV preset: RECOMMENDED minus threadStackVersion and mleCounters (P1)
# ---------------------------------------------------------------------------
_MEDIUM_DIAGNOSTIC_TLVS: list[str] = [
    t for t in RECOMMENDED_DIAGNOSTIC_TLVS
    if t not in {"threadStackVersion", "mleCounters"}
]

# ---------------------------------------------------------------------------
# MAC Counter Enrichment (P3)
# REST API macCounters keys are camelCase (ifInErrors, ifInUcastPkts, …).
# Derived fields use the same lowercase names as parse_mac_counters() in
# otbr_cli_networkdiag_topology.py for cross-tool consistency.
# ---------------------------------------------------------------------------

def enrich_mac_counters(mac: dict[str, Any]) -> None:
    """Enrich a macCounters dict in-place with derived totals and ratios.

    Accepts the camelCase key format returned by the OTBR REST API and adds
    the same computed fields that parse_mac_counters() produces for ot-ctl
    text output.
    """
    in_ucast   = mac.get("ifInUcastPkts", 0)
    in_bcast   = mac.get("ifInBroadcastPkts", 0)
    out_ucast  = mac.get("ifOutUcastPkts", 0)
    out_bcast  = mac.get("ifOutBroadcastPkts", 0)
    in_errors  = mac.get("ifInErrors", 0)
    out_errors = mac.get("ifOutErrors", 0)
    in_disc    = mac.get("ifInDiscards", 0)
    out_disc   = mac.get("ifOutDiscards", 0)

    ifintotalpkts  = in_ucast  + in_bcast
    ifouttotalpkts = out_ucast + out_bcast
    iftotalpkts    = ifintotalpkts + ifouttotalpkts
    totalerrors    = in_errors + out_errors
    totaldiscards  = in_disc   + out_disc

    mac["ifintotalpkts"]  = ifintotalpkts
    mac["ifouttotalpkts"] = ifouttotalpkts
    mac["iftotalpkts"]    = iftotalpkts
    mac["iftotalerrors"]  = totalerrors
    mac["iftotaldiscards"] = totaldiscards

    iftotal_inerrdiscs  = in_errors  + in_disc
    iftotal_outerrdiscs = out_errors + out_disc
    iftotal_errdiscs    = totalerrors + totaldiscards

    mac["iftotal_inerrdiscs"]  = iftotal_inerrdiscs
    mac["iftotal_outerrdiscs"] = iftotal_outerrdiscs
    mac["iftotal_errdiscs"]    = iftotal_errdiscs

    if iftotal_inerrdiscs > 0:
        mac["ifinerrors_totalinerrdiscs_ratio"]   = round(in_errors / iftotal_inerrdiscs, 1)
        mac["ifindiscards_totalinerrdiscs_ratio"] = round(in_disc   / iftotal_inerrdiscs, 1)
    if iftotal_outerrdiscs > 0:
        mac["ifouterrors_totalouterrdiscs_ratio"]   = round(out_errors / iftotal_outerrdiscs, 1)
        mac["ifoutdiscards_totalouterrdiscs_ratio"] = round(out_disc   / iftotal_outerrdiscs, 1)
    if iftotal_errdiscs > 0:
        mac["iftotalerrors_totalerrdiscs_ratio"]   = round(totalerrors   / iftotal_errdiscs, 1)
        mac["iftotaldiscards_totalerrdiscs_ratio"] = round(totaldiscards / iftotal_errdiscs, 1)

    if ifintotalpkts > 0:
        mac["ifinerrors_intotalpkts_ratio"]   = round(in_errors / ifintotalpkts, 1)
        mac["ifindiscards_intotalpkts_ratio"] = round(in_disc   / ifintotalpkts, 1)
    if ifouttotalpkts > 0:
        mac["ifouterrors_outtotalpkts_ratio"]   = round(out_errors / ifouttotalpkts, 1)
        mac["ifoutdiscards_outtotalpkts_ratio"] = round(out_disc   / ifouttotalpkts, 1)
    if iftotalpkts > 0:
        mac["iftotalerrors_totalpkts_ratio"]   = round(totalerrors   / iftotalpkts, 1)
        mac["iftotaldiscards_totalpkts_ratio"] = round(totaldiscards / iftotalpkts, 1)

    mac["ifinerrors_totalerrors_pct"] = (
        round((in_errors  / totalerrors) * 100, 1) if totalerrors > 0 else 0
    )
    mac["ifouterrors_totalerrors_pct"] = (
        round((out_errors / totalerrors) * 100, 1) if totalerrors > 0 else 0
    )
    mac["ifindiscards_totaldiscards_pct"] = (
        round((in_disc  / totaldiscards) * 100, 1) if totaldiscards > 0 else 0
    )
    mac["ifoutdiscards_totaldiscards_pct"] = (
        round((out_disc / totaldiscards) * 100, 1) if totaldiscards > 0 else 0
    )


def _apply_mac_enrichment(diagnostics: list[Any]) -> list[Any]:
    """Apply enrich_mac_counters in-place to each diagnostic record's macCounters."""
    for record in diagnostics:
        if not isinstance(record, dict):
            continue
        mac = record.get("macCounters")
        if isinstance(mac, dict):
            enrich_mac_counters(mac)
    return diagnostics


# ---------------------------------------------------------------------------
# Progress Reporting (P6)
# ---------------------------------------------------------------------------

def _make_progress_fn(total: int, enabled: bool):
    """Return a progress callback for fetch_all_devices_* client methods.

    When enabled=True, prints one line per device to stderr:
        [3/12] aabbccddeeff0011 → completed (2.4s)
    When enabled=False or total==0, returns None.
    """
    if not enabled or total == 0:
        return None

    def _cb(count: int, total_: int, device_id: str, elapsed: float, status: str) -> None:
        print(
            f"[{count}/{total_}] {device_id} \u2192 {status} ({elapsed:.1f}s)",
            file=sys.stderr,
        )
    return _cb


# ---------------------------------------------------------------------------
# Auto-output naming (P5)
# ---------------------------------------------------------------------------

_AUTO_OUTPUT_NAMES: dict[tuple[str, str], str] = {
    ("devices", "list"):                "td-otbr-restapi-devices-list.json",
    ("devices", "fetch"):               "td-otbr-restapi-devices-fetch.json",
    ("diagnostics", "list"):             "td-otbr-restapi-diagnostics-list.json",
    ("diagnostics", "fetch"):           "td-otbr-restapi-diagnostics-fetch.json",
    ("diagnostics", "fetch-all"):       "td-otbr-restapi-diagnostics-fetch-all.json",
    ("actions", "list"):                 "td-otbr-restapi-actions-list.json",
    ("mesh-diagnostics", "fetch"):      "td-otbr-restapi-mesh-diagnostics-fetch.json",
    ("mesh-diagnostics", "fetch-all"):  "td-otbr-restapi-mesh-diagnostics-fetch-all.json",
}


def _auto_output_path(args: argparse.Namespace, data_dir: Path) -> str | None:
    """Return the auto-named output path when P5 auto-output is active.

    Returns None when --no-auto-output is set, --output was explicitly provided,
    or the resource/command pair has no auto-naming rule.
    """
    if getattr(args, "no_auto_output", False):
        return None
    if getattr(args, "output", None):
        return None  # explicit --output overrides auto-naming

    resource = getattr(args, "resource", None)
    if resource == "diagnostics":
        command = getattr(args, "diagnostics_command", None)
    elif resource == "mesh-diagnostics":
        command = getattr(args, "mesh_diag_command", None)
    elif resource == "devices":
        command = getattr(args, "devices_command", None)
    elif resource == "actions":
        command = getattr(args, "actions_command", None)
    else:
        return None

    filename = _AUTO_OUTPUT_NAMES.get((resource, command))
    if filename is None:
        return None
    return str(data_dir / filename)


# ---------------------------------------------------------------------------
# Router-only device filter (P2)
# ---------------------------------------------------------------------------

def _filter_router_device_ids(devices: list[Any], device_ids: list[str]) -> list[str]:
    """Return device IDs whose rloc16 lower-10-bits are zero (router devices).

    Devices whose rloc16 is missing or un-parseable are kept (safe default).
    """
    rloc16_by_id: dict[str, int] = {}
    for d in devices:
        if not isinstance(d, dict):
            continue
        dev_id = d.get("id")
        rloc16_raw = d.get("rloc16")
        if dev_id is None or rloc16_raw is None:
            continue
        try:
            rloc16_by_id[dev_id] = (
                int(rloc16_raw, 16) if isinstance(rloc16_raw, str) else int(rloc16_raw)
            )
        except (ValueError, TypeError):
            pass

    result = []
    for dev_id in device_ids:
        rloc16 = rloc16_by_id.get(dev_id)
        if rloc16 is None or (rloc16 & 0x03FF) == 0:
            result.append(dev_id)
    return result


# ---------------------------------------------------------------------------
# TLV fallback helpers (P1)
# ---------------------------------------------------------------------------

def _resolve_fallback_types(args: argparse.Namespace) -> list[str | int] | None:
    """Return the fallback TLV list, or None when --no-fallback is set."""
    if getattr(args, "no_fallback", False):
        return None
    preset = getattr(args, "fallback_preset", "minimal")
    if preset == "medium":
        return list(_MEDIUM_DIAGNOSTIC_TLVS)
    if preset == "basic":
        return list(BASIC_DIAGNOSTIC_TLVS)
    return list(MINIMAL_DIAGNOSTIC_TLVS)  # default: minimal


def _fetch_device_with_fallback(
    client: OTBRRestApiClient,
    device_id: str,
    primary_types: list[str | int],
    fallback_types: list[str | int] | None,
    *,
    destination_type: str,
    task_timeout: int,
    poll_interval: float,
    poll_timeout: float,
    raw: object,
) -> Any:
    """Fetch diagnostics for one device, retrying with fallback_types on failure."""
    try:
        return client.fetch_device_diagnostics(
            device_id,
            types=primary_types,
            destination_type=destination_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raw=raw,
        )
    except (OTBRActionFailedError, OTBRActionTimeoutError):
        if not fallback_types:
            raise
        logging.warning(
            "Device %s failed with primary TLVs; retrying with fallback preset",
            device_id,
        )
        return client.fetch_device_diagnostics(
            device_id,
            types=fallback_types,
            destination_type=destination_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raw=raw,
        )


def _fetch_all_with_fallback(
    client: OTBRRestApiClient,
    device_ids: list[str],
    primary_types: list[str | int],
    fallback_types: list[str | int] | None,
    *,
    destination_type: str,
    task_timeout: int,
    poll_interval: float,
    poll_timeout: float,
    raw: object,
    on_progress=None,
) -> list[Any]:
    """Fetch diagnostics for all devices with per-device TLV fallback and progress."""
    results: list[Any] = []
    total = len(device_ids)
    for idx, device_id in enumerate(device_ids, start=1):
        t_start = time.monotonic()
        status = "completed"
        try:
            diag = _fetch_device_with_fallback(
                client, device_id, primary_types, fallback_types,
                destination_type=destination_type,
                task_timeout=task_timeout,
                poll_interval=poll_interval,
                poll_timeout=poll_timeout,
                raw=raw,
            )
            results.append(diag)
        except (OTBRActionFailedError, OTBRActionTimeoutError) as exc:
            status = "skipped"
            logging.warning("Skipping device %s: %s", device_id, exc)
        elapsed = time.monotonic() - t_start
        if on_progress is not None:
            on_progress(idx, total, device_id, elapsed, status)
    return results


def build_client(args: argparse.Namespace) -> OTBRRestApiClient:
    return OTBRRestApiClient(
        host=args.host,
        port=args.port,
        base_url=args.base_url,
        timeout=args.timeout,
        accept=args.accept,
    )


def dispatch(client: OTBRRestApiClient, args: argparse.Namespace) -> Any:
    raw_arg = True if args.raw else _RAW_UNSET
    _eff_raw = client._resolve_raw(raw_arg)
    fields = build_fields_mapping(getattr(args, "fields", None))

    if args.resource == "node":
        if args.node_command == "get":
            return client.get_node(fields=fields, raw=raw_arg)
        if args.node_command == "state":
            if args.state_command == "get":
                return client.get_node_state()
            if args.state_command == "set":
                return client.set_node_state(args.value)
        if args.node_command == "dataset" and args.dataset_kind == "active":
            if args.dataset_command == "get":
                return client.get_active_dataset(plain_text=args.text, raw=raw_arg)
            if args.dataset_command == "set":
                dataset = _parse_dataset_input(args)
                return client.set_active_dataset(dataset)

    if args.resource == "devices":
        if args.devices_command == "list":
            return client.list_devices(
                fields=fields, raw=raw_arg, with_meta=args.with_meta
            )
        if args.devices_command == "get":
            return client.get_device(args.device_id, fields=fields, raw=raw_arg)
        if args.devices_command == "fetch":
            return client.fetch_device_collection(
                device_count=args.device_count,
                max_age=args.max_age,
                max_retries=args.max_retries,
                task_timeout=args.task_timeout,
                poll_interval=args.poll_interval,
                poll_timeout=args.poll_timeout,
                raw=raw_arg,
            )

    if args.resource == "diagnostics":
        if args.diagnostics_command == "list":
            return client.list_diagnostics(
                fields=fields, raw=raw_arg, with_meta=args.with_meta
            )
        if args.diagnostics_command == "get":
            return client.get_diagnostic(args.diagnostics_id, raw=raw_arg)
        if args.diagnostics_command == "fetch":
            primary_types = _resolve_types(args)
            fallback_types = _resolve_fallback_types(args)
            result = _fetch_device_with_fallback(
                client, args.device_id, primary_types, fallback_types,
                destination_type=args.destination_type,
                task_timeout=args.task_timeout,
                poll_interval=args.poll_interval,
                poll_timeout=args.poll_timeout,
                raw=raw_arg,
            )
            if not getattr(args, "no_enrich_mac_counters", False):
                _apply_mac_enrichment([result])
            return result
        if args.diagnostics_command == "fetch-all":
            resolved_types = _resolve_types(args)
            fallback_types = _resolve_fallback_types(args)
            do_enrich = not getattr(args, "no_enrich_mac_counters", False)
            do_update = not getattr(args, "no_update_devices", False)
            progress_fn = _make_progress_fn(
                0,  # total unknown until device list retrieved
                not getattr(args, "no_progress", False),
            )

            if do_update:
                devices = client.fetch_device_collection(
                    device_count=getattr(args, "device_count", 50),
                )
            else:
                devices = client.list_devices(raw=False)

            device_ids = (
                getattr(args, "device_ids", None)
                or [d["id"] for d in devices if isinstance(d, dict) and d.get("id")]
            )
            progress_fn = _make_progress_fn(
                len(device_ids),
                not getattr(args, "no_progress", False),
            )
            diagnostics = _fetch_all_with_fallback(
                client, device_ids, resolved_types, fallback_types,
                destination_type=args.destination_type,
                task_timeout=args.task_timeout,
                poll_interval=args.poll_interval,
                poll_timeout=args.poll_timeout,
                raw=raw_arg,
                on_progress=progress_fn,
            )
            if do_enrich:
                _apply_mac_enrichment(diagnostics)
            return diagnostics

    if args.resource == "actions":
        if args.actions_command == "list":
            return client.list_actions(
                fields=fields, raw=raw_arg, with_meta=args.with_meta
            )
        if args.actions_command == "get":
            return client.get_action(args.action_id, raw=raw_arg)
        if args.actions_command == "enqueue":
            if args.enqueue_type == "add-thread-device":
                return client.enqueue_add_thread_device_task(
                    pskd=args.pskd,
                    eui=args.eui,
                    discerner=args.discerner,
                    joiner_id=args.joiner_id,
                    timeout=args.timeout,
                    raw=raw_arg,
                )
            if args.enqueue_type == "get-network-diagnostic":
                resolved_types = _resolve_types(args)
                if not resolved_types:
                    raise OTBRUsageError(
                        "Provide --types or --preset for get-network-diagnostic"
                    )
                enqueued = client.enqueue_get_network_diagnostic_task(
                    destination=args.destination,
                    types=resolved_types,
                    timeout=args.timeout,
                    destination_type=args.destination_type,
                    raw=raw_arg,
                )
                if not getattr(args, "wait", False):
                    return enqueued
                # --wait: poll until terminal state, then return diagnostic result
                action_id = (
                    enqueued["data"][0]["id"] if _eff_raw else enqueued[0]["id"]
                )
                action = client.wait_for_action(
                    action_id,
                    poll_interval=args.poll_interval,
                    poll_timeout=args.poll_timeout,
                    raise_on_stopped=True,
                    raw=raw_arg,
                )
                result_id = extract_action_result_id(action)
                if result_id:
                    return client.get_diagnostic(result_id, raw=raw_arg)
                return action
            if args.enqueue_type == "reset-network-diag-counter":
                return client.enqueue_reset_network_diag_counter_task(
                    destination=args.destination,
                    types=_parse_typed_values(args.types),
                    timeout=args.timeout,
                    destination_type=args.destination_type,
                    raw=raw_arg,
                )
            if args.enqueue_type == "get-energy-scan":
                return client.enqueue_get_energy_scan_task(
                    destination=args.destination,
                    channel_mask=args.channel_mask,
                    count=args.count,
                    period=args.period,
                    scan_duration=args.scan_duration,
                    timeout=args.timeout,
                    destination_type=args.destination_type,
                    raw=raw_arg,
                )
            if args.enqueue_type == "update-device-collection":
                return client.enqueue_update_device_collection_task(
                    max_age=args.max_age,
                    max_retries=args.max_retries,
                    device_count=args.device_count,
                    timeout=args.timeout,
                    raw=raw_arg,
                )

    if args.resource == "mesh-diagnostics":
        cmd = args.mesh_diag_command
        poll_timeout = getattr(args, "poll_timeout", args.poll_timeout)
        poll_interval = args.poll_interval
        dest_type = getattr(args, "destination_type", DestinationType.EXTENDED)
        task_timeout = getattr(args, "task_timeout", 300)

        if cmd == "children":
            return client.fetch_mesh_diagnostics(
                args.device_id, types=[DIAG_TLV_CHILDREN],
                destination_type=dest_type, task_timeout=task_timeout,
                poll_interval=poll_interval, poll_timeout=poll_timeout,
                raw=raw_arg,
            )
        if cmd == "child-ipv6":
            return client.fetch_mesh_diagnostics(
                args.device_id, types=[DIAG_TLV_CHILD_IPV6_ADDRS],
                destination_type=dest_type, task_timeout=task_timeout,
                poll_interval=poll_interval, poll_timeout=poll_timeout,
                raw=raw_arg,
            )
        if cmd == "router-neighbors":
            return client.fetch_mesh_diagnostics(
                args.device_id, types=[DIAG_TLV_ROUTER_NEIGHBORS],
                destination_type=dest_type, task_timeout=task_timeout,
                poll_interval=poll_interval, poll_timeout=poll_timeout,
                raw=raw_arg,
            )
        if cmd == "fetch":
            types = _parse_mesh_diag_types(
                args.types or list(MESH_DIAGNOSTIC_TLVS))
            return client.fetch_mesh_diagnostics(
                args.device_id, types=types,
                destination_type=dest_type, task_timeout=task_timeout,
                poll_interval=poll_interval, poll_timeout=poll_timeout,
                raw=raw_arg,
            )
        if cmd == "fetch-all":
            types = _parse_mesh_diag_types(
                args.types or list(MESH_DIAGNOSTIC_TLVS))
            do_update = not getattr(args, "no_update_devices", False)
            routers_only = getattr(args, "routers_only", False)

            if do_update:
                devices = client.fetch_device_collection()
            else:
                devices = client.list_devices(raw=False)

            device_ids = getattr(args, "device_ids", None) or [
                d["id"] for d in devices if isinstance(d, dict) and d.get("id")
            ]
            if routers_only:
                device_ids = _filter_router_device_ids(devices, device_ids)
                logging.info(
                    "--routers-only: %d router device(s) selected from device list",
                    len(device_ids),
                )

            progress_fn = _make_progress_fn(
                len(device_ids),
                not getattr(args, "no_progress", False),
            )
            return client.fetch_mesh_diagnostics_all_devices(
                device_ids, types=types,
                destination_type=dest_type, task_timeout=task_timeout,
                poll_interval=poll_interval, poll_timeout=poll_timeout,
                on_progress=progress_fn,
                raw=raw_arg,
            )

    if args.resource == "topology":
        return _dispatch_topology(client, args, raw_arg)

    raise ValueError("Unsupported CLI command")


def _dispatch_topology(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
) -> None:
    """P4 — Execute the full topology sweep and write all three output files."""
    data_dir: Path = args.td_data_dir
    do_update = not getattr(args, "no_update_devices", False)
    do_enrich = not getattr(args, "no_enrich_mac_counters", False)
    fallback_types = _resolve_fallback_types(args)
    primary_types = _resolve_types(args)
    progress_enabled = not getattr(args, "no_progress", False)

    # ------------------------------------------------------------------
    # Step 1: Device refresh
    # ------------------------------------------------------------------
    devices: list[Any] = []
    if not getattr(args, "skip_devices", False):
        logging.info("topology step 1: devices fetch ...")
        devices = client.fetch_device_collection()
        path = data_dir / "td-otbr-restapi-devices-fetch.json"
        save_json_atomic(devices, path)
        logging.info("topology step 1 done: %d device(s) → %s", len(devices), path)
    else:
        logging.info("topology step 1 skipped (--skip-devices); fetching device list quietly")
        devices = client.list_devices(raw=False)

    device_ids = [d["id"] for d in devices if isinstance(d, dict) and d.get("id")]

    # ------------------------------------------------------------------
    # Step 2: Network diagnostics fetch-all
    # ------------------------------------------------------------------
    if not getattr(args, "skip_diagnostics", False):
        logging.info("topology step 2: diagnostics fetch-all --preset %s ...", args.preset)
        if do_update and not getattr(args, "skip_devices", False):
            # Device list already refreshed in step 1; avoid a second refresh
            diag_device_ids = device_ids
        elif do_update:
            diag_devices = client.fetch_device_collection()
            diag_device_ids = [
                d["id"] for d in diag_devices if isinstance(d, dict) and d.get("id")
            ]
        else:
            diag_device_ids = device_ids

        progress_fn = _make_progress_fn(len(diag_device_ids), progress_enabled)
        diagnostics = _fetch_all_with_fallback(
            client, diag_device_ids, primary_types, fallback_types,
            destination_type=args.destination_type if hasattr(args, "destination_type")
            else DestinationType.EXTENDED,
            task_timeout=args.task_timeout if hasattr(args, "task_timeout") else 93,
            poll_interval=args.poll_interval,
            poll_timeout=args.poll_timeout,
            raw=raw_arg,
            on_progress=progress_fn,
        )
        if do_enrich:
            _apply_mac_enrichment(diagnostics)
        path = data_dir / "td-otbr-restapi-diagnostics-fetch-all.json"
        save_json_atomic(diagnostics, path)
        logging.info(
            "topology step 2 done: %d diagnostic(s) → %s", len(diagnostics), path
        )
    else:
        logging.info("topology step 2 skipped (--skip-diagnostics)")

    # ------------------------------------------------------------------
    # Step 3: Mesh diagnostics fetch-all --routers-only
    # ------------------------------------------------------------------
    if not getattr(args, "skip_mesh_diagnostics", False):
        logging.info("topology step 3: mesh-diagnostics fetch-all --routers-only ...")
        router_ids = _filter_router_device_ids(devices, device_ids)
        logging.info(
            "topology step 3: %d router device(s) selected", len(router_ids)
        )
        mesh_progress_fn = _make_progress_fn(len(router_ids), progress_enabled)
        mesh_results = client.fetch_mesh_diagnostics_all_devices(
            router_ids,
            types=list(MESH_DIAGNOSTIC_TLVS),
            on_progress=mesh_progress_fn,
        )
        path = data_dir / "td-otbr-restapi-mesh-diagnostics-fetch-all.json"
        save_json_atomic(mesh_results, path)
        logging.info(
            "topology step 3 done: %d mesh diagnostic(s) → %s", len(mesh_results), path
        )
    else:
        logging.info("topology step 3 skipped (--skip-mesh-diagnostics)")

    return None  # emit_output handles None by writing nothing


def _resolve_types(args: argparse.Namespace) -> list[str | int]:
    """Resolve TLV type list from --preset or --types args. Returns RECOMMENDED_DIAGNOSTIC_TLVS if neither given."""
    preset = getattr(args, "preset", None)
    if preset == "recommended":
        return list(RECOMMENDED_DIAGNOSTIC_TLVS)
    if preset == "full":
        return list(FULL_DIAGNOSTIC_TLVS)
    if preset == "minimal":
        return list(MINIMAL_DIAGNOSTIC_TLVS)
    if preset == "basic":
        return list(BASIC_DIAGNOSTIC_TLVS)
    types_raw = getattr(args, "types", None)
    if types_raw:
        return _parse_typed_values(types_raw)
    return list(RECOMMENDED_DIAGNOSTIC_TLVS)


def _parse_mesh_diag_types(types: list[str]) -> list[str]:
    """Validate and return mesh-diagnostic TLV names, raising OTBRUsageError for unknown values."""
    invalid = [t for t in types if t not in MESH_DIAGNOSTIC_TLVS]
    if invalid:
        raise OTBRUsageError(
            f"Invalid mesh-diagnostic TLV(s): {invalid!r}. "
            f"Allowed: {sorted(MESH_DIAGNOSTIC_TLVS)!r}"
        )
    if not types:
        raise OTBRUsageError(
            "At least one mesh-diagnostic TLV must be specified")
    return types


def _get_all_device_ids(client: OTBRRestApiClient) -> list[str]:
    """Retrieve all device IDs from /api/devices."""
    devices = client.list_devices(raw=False)
    return [d["id"] for d in devices if isinstance(d, dict) and d.get("id")]


def _parse_dataset_input(args: argparse.Namespace) -> dict[str, Any] | str:
    td_data_dir = getattr(args, "td_data_dir", None)

    def _resolve(path_value: str) -> Path:
        if td_data_dir is None:
            return Path(path_value)
        return resolve_data_file_path(path_value, td_data_dir)

    try:
        if args.json is not None:
            return json.loads(args.json)
        if args.json_file is not None:
            return json.loads(_resolve(args.json_file).read_text(encoding="utf-8"))
        if args.text is not None:
            return args.text
        if args.text_file is not None:
            return _resolve(args.text_file).read_text(encoding="utf-8").strip()
    except json.JSONDecodeError as exc:
        raise OTBRUsageError(f"Invalid dataset JSON: {exc}") from exc
    except OSError as exc:
        raise OTBRUsageError(f"Failed to read dataset input: {exc}") from exc

    raise OTBRUsageError("No dataset input provided")


def _parse_typed_values(values: Sequence[str]) -> list[str | int]:
    parsed: list[str | int] = []
    for value in values:
        try:
            parsed.append(int(value))
        except ValueError:
            parsed.append(value)
    return parsed


def emit_output(result: Any, output_path: str | None) -> None:
    if result is None:
        rendered = ""
    elif isinstance(result, str):
        rendered = result
    else:
        rendered = json.dumps(result, indent=4, sort_keys=True)

    if output_path:
        suffix = "\n" if rendered and not rendered.endswith("\n") else ""
        Path(output_path).write_text(rendered + suffix, encoding="utf-8")

    if not output_path and rendered:
        print(rendered)


def emit_error(exc: Exception) -> None:
    payload = error_to_dict(exc)
    print(json.dumps(payload, indent=4, sort_keys=True), file=sys.stderr)


def exit_code_for_exception(exc: Exception) -> int:
    if isinstance(exc, OTBRUsageError):
        return EXIT_USAGE
    if isinstance(exc, OTBRConnectionError):
        return EXIT_CONNECTION
    if isinstance(exc, OTBRHTTPError):
        return EXIT_HTTP
    if isinstance(exc, OTBRActionError):
        return EXIT_HTTP
    if isinstance(exc, OTBRInvalidResponseError):
        return EXIT_INVALID_RESPONSE
    if isinstance(exc, OTBRClientError):
        return EXIT_UNEXPECTED
    return EXIT_UNEXPECTED


def run_cli(
    build_parser_fn,
    dispatch_fn,
    build_client_fn,
    argv: Sequence[str] | None = None,
) -> int:
    """Standard CLI entry-point scaffold shared by both client CLIs."""
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )
    parser = build_parser_fn()
    args = parser.parse_args(argv)
    args.td_data_dir = resolve_data_dir(data_dir=args.datadir)

    # P5 — resolve output path: explicit --output > auto-naming > stdout
    output_path = getattr(args, "output", None)
    if output_path:
        output_path = str(resolve_data_file_path(output_path, args.td_data_dir))
    else:
        output_path = _auto_output_path(args, args.td_data_dir)

    try:
        client = build_client_fn(args)
        result = dispatch_fn(client, args)
        emit_output(result, output_path)
        return EXIT_SUCCESS
    except OTBRClientError as exc:
        emit_error(exc)
        return exit_code_for_exception(exc)
    except Exception as exc:
        emit_error(exc)
        return EXIT_UNEXPECTED


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(build_parser, dispatch, build_client, argv)


if __name__ == "__main__":
    sys.exit(main())
