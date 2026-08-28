from __future__ import annotations

import argparse
import json
import sys
import logging
import time
import io

from pathlib import Path
from typing import Any, Sequence
from contextlib import redirect_stderr
from util_data import resolve_data_file_path, resolve_data_dir
from td_const import (
    OTBR_RESTAPI_ACTIONS_LIST_FILENAME,
    OTBR_RESTAPI_DEVICES_FETCH_FILENAME,
    OTBR_RESTAPI_DEVICES_LIST_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_LIST_FILENAME,
    OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_FILENAME,
    TD_DATA_DIR_ARG_HELP,
)

from otbr_restapi_util import (
    add_common_rest_client_args,
    build_rest_client_from_args,
    emit_rest_payload_output,
    exit_code_for_rest_exception,
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
from otbr_restapi_node import dispatch_node
from otbr_restapi_devices import dispatch_devices
from otbr_restapi_actions import dispatch_actions
from otbr_restapi_diagnostics import dispatch_diagnostics
from otbr_restapi_mesh_diagnostics import dispatch_mesh_diagnostics
from otbr_restapi_topology import dispatch_topology
from util_mac_counters import derive_rest_mac_counter_metrics

# Reference: https://github.com/openthread/ot-br-posix/blob/main/src/rest/openapi.yaml

EXIT_SUCCESS = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_CONNECTION = 3
EXIT_HTTP = 4
EXIT_INVALID_RESPONSE = 5

# CLI default timing/task values
CLI_POLL_INTERVAL_DEFAULT = 2.0
CLI_POLL_TIMEOUT_DEFAULT = None
CLI_DEVICE_COUNT_DEFAULT = 255
CLI_MAX_AGE_DEFAULT = 60
CLI_MAX_RETRIES_DEFAULT = 2
CLI_DEVICE_TASK_TIMEOUT_DEFAULT = 30
CLI_DIAGNOSTICS_TASK_TIMEOUT_DEFAULT = 15
CLI_MESH_TASK_TIMEOUT_DEFAULT = 15
CLI_UPDATE_DEVICE_COLLECTION_TIMEOUT_DEFAULT = 30

# Router-only selection mask/value
ROUTER_RLOC16_MASK = 0x03FF
ROUTER_RLOC16_VALUE = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CLI wrapper for the OpenThread Border Router REST API.",
    )
    # Add standard REST API client arguments
    add_common_rest_client_args(parser)
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Return raw API envelopes instead of flattened output",
    )
    parser.add_argument("--output", help="Write the command result to a file")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=CLI_POLL_INTERVAL_DEFAULT,
        metavar="FLOAT",
        help=f"Seconds between action status polls (default: {CLI_POLL_INTERVAL_DEFAULT})",
    )
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=CLI_POLL_TIMEOUT_DEFAULT,
        metavar="FLOAT",
        help="Max wall-clock seconds to wait for an action (default: derived).",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        default=False,
        help="Suppress per-device progress output to stderr on fetch-all commands",
    )
    parser.add_argument(
        "--no-auto-output",
        action="store_true",
        default=False,
        help=(
            "Disable automatic output file naming. By default, fetch/fetch-all commands "
            "write results to <datadir>/td-otbr-restapi-<resource>-<command>.json"
        ),
    )
    parser.add_argument(
        "--lab",
        action="store_true",
        default=False,
        help=(
            "Allow experimental mutating commands: node state set, "
            "node dataset active set, actions enqueue add-thread-device, "
            "actions enqueue reset-network-diag-counter"
        ),
    )
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        default=False,
        help="Enable debug logging",
    )

    subparsers = parser.add_subparsers(dest="resource", required=False)
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
        dest="node_command", required=False)

    node_get = node_subparsers.add_parser(
        "get", help="Get the OTBR node record from /api/node"
    )
    _add_fields_argument(node_get)

    state_parser = node_subparsers.add_parser(
        "state", help="Get or set Thread state")
    state_subparsers = state_parser.add_subparsers(
        dest="state_command", required=False)
    state_subparsers.add_parser("get", help="Get current Thread state")
    state_set = state_subparsers.add_parser(
        "set",
        help="Enable or disable Thread [EXPERIMENTAL: requires --lab]",
    )
    state_set.add_argument("--value", required=True,
                           choices=["enable", "disable"])

    dataset_parser = node_subparsers.add_parser(
        "dataset", help="Operate on node datasets"
    )
    dataset_subparsers = dataset_parser.add_subparsers(
        dest="dataset_kind", required=False
    )
    active_parser = dataset_subparsers.add_parser(
        "active", help="Operate on active dataset"
    )
    active_subparsers = active_parser.add_subparsers(
        dest="dataset_command", required=False
    )
    active_get = active_subparsers.add_parser("get", help="Get active dataset")
    active_get.add_argument(
        "--text", action="store_true", help="Request text/plain TLV dataset"
    )

    active_set = active_subparsers.add_parser(
        "set", help="Create or update active dataset [EXPERIMENTAL: requires --lab]"
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
        dest="devices_command", required=False
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
        "--device-count", type=int, default=CLI_DEVICE_COUNT_DEFAULT,
        help=f"Max devices to discover (default: {CLI_DEVICE_COUNT_DEFAULT})"
    )
    devices_fetch.add_argument(
        "--task-timeout", type=int, default=CLI_DEVICE_TASK_TIMEOUT_DEFAULT,
        help=f"Server-side task timeout in seconds (default: {CLI_DEVICE_TASK_TIMEOUT_DEFAULT})",
    )
    devices_fetch.add_argument(
        "--max-age", type=int, default=CLI_MAX_AGE_DEFAULT,
        help=f"Max age of cached device entries in seconds (default: {CLI_MAX_AGE_DEFAULT})",
    )
    devices_fetch.add_argument(
        "--max-retries", type=int, default=CLI_MAX_RETRIES_DEFAULT,
        help=f"Max retries per device (default: {CLI_MAX_RETRIES_DEFAULT})",
    )
    devices_fetch.add_argument(
        "--whole-action-attempts",
        type=int,
        default=1,
        help="Whole discovery action attempts; retries only known terminal failures (default: 1)",
    )
    devices_fetch.add_argument(
        "--structured-outcome",
        action="store_true",
        help="Return workflow metadata instead of only the device array",
    )


def _add_diagnostics_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    diagnostics_parser = subparsers.add_parser(
        "diagnostics", help="Read OTBR diagnostics"
    )
    diagnostics_subparsers = diagnostics_parser.add_subparsers(
        dest="diagnostics_command", required=False
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
    diagnostics_list.add_argument(
        "--no-enrich-mac-counters",
        action="store_true",
        default=False,
        help="Return raw macCounters values without computed totals and ratios",
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
        "--task-timeout", type=int, default=CLI_DIAGNOSTICS_TASK_TIMEOUT_DEFAULT,
        help=f"Server-side task timeout in seconds (default: {CLI_DIAGNOSTICS_TASK_TIMEOUT_DEFAULT})",
    )
    diagnostics_fetch.add_argument(
        "--destination-type", default=DestinationType.EXTENDED,
        help=f"Destination addressing mode (default: {DestinationType.EXTENDED})",
    )
    diagnostics_fetch.add_argument(
        "--no-fallback",
        action="store_true",
        default=False,
        help="Disable per-device TLV fallback retry on failure",
    )
    diagnostics_fetch.add_argument(
        "--fallback-preset",
        choices=["medium", "minimal", "basic"],
        default="minimal",
        help="TLV preset to retry with on device failure (default: minimal)",
    )
    diagnostics_fetch.add_argument(
        "--no-enrich-mac-counters",
        action="store_true",
        default=False,
        help="Return raw macCounters values without computed totals and ratios",
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
        "--task-timeout", type=int, default=CLI_DIAGNOSTICS_TASK_TIMEOUT_DEFAULT,
        help=f"Server-side task timeout per device in seconds (default: {CLI_DIAGNOSTICS_TASK_TIMEOUT_DEFAULT})",
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
            "By default the device list is refreshed first"
        ),
    )
    diagnostics_fetch_all.add_argument(
        "--no-fallback",
        action="store_true",
        default=False,
        help="Disable per-device TLV fallback retry on failure",
    )
    diagnostics_fetch_all.add_argument(
        "--fallback-preset",
        choices=["medium", "minimal", "basic"],
        default=None,
        help="Opt in to one terminal-action retry with a smaller TLV preset",
    )
    diagnostics_fetch_all.add_argument(
        "--preserve-diagnostics",
        action="store_true",
        help="Do not clear the diagnostic collection before this full sweep",
    )
    diagnostics_fetch_all.add_argument(
        "--items-only",
        action="store_true",
        help="Return only diagnostic items instead of the structured sweep outcome",
    )
    diagnostics_fetch_all.add_argument(
        "--no-enrich-mac-counters",
        action="store_true",
        default=False,
        help="Return raw macCounters values without computed totals and ratios",
    )


def _add_actions_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    actions_parser = subparsers.add_parser(
        "actions", help="Read or enqueue OTBR actions"
    )
    actions_subparsers = actions_parser.add_subparsers(
        dest="actions_command", required=False
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
    _add_fields_argument(actions_get)

    enqueue_parser = actions_subparsers.add_parser(
        "enqueue", help="Enqueue a new OTBR task"
    )
    enqueue_subparsers = enqueue_parser.add_subparsers(
        dest="enqueue_type", required=False
    )

    add_thread_device = enqueue_subparsers.add_parser(
        "add-thread-device",
        help="Enqueue addThreadDeviceTask [EXPERIMENTAL: requires --lab]",
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
        "reset-network-diag-counter",
        help="Enqueue resetNetworkDiagCounterTask [EXPERIMENTAL: requires --lab]",
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
    energy_scan.add_argument("--count", type=int, default=None)
    energy_scan.add_argument("--period", type=int, default=None)
    energy_scan.add_argument("--scan-duration", type=int, default=None)
    energy_scan.add_argument("--timeout", type=int, default=None)
    energy_scan.add_argument("--destination-type")

    update_devices = enqueue_subparsers.add_parser(
        "update-device-collection", help="Enqueue updateDeviceCollectionTask"
    )
    update_devices.add_argument(
        "--max-age", type=int, default=CLI_MAX_AGE_DEFAULT,
        help=f"Maximum age (seconds) for cached device entries (default: {CLI_MAX_AGE_DEFAULT})"
    )
    update_devices.add_argument(
        "--max-retries", type=int, default=CLI_MAX_RETRIES_DEFAULT,
        help=f"Maximum retries per device (default: {CLI_MAX_RETRIES_DEFAULT})"
    )
    update_devices.add_argument(
        "--device-count", type=int, default=CLI_DEVICE_COUNT_DEFAULT,
        help=f"Maximum number of devices to discover (default: {CLI_DEVICE_COUNT_DEFAULT})"
    )
    update_devices.add_argument(
        "--timeout", type=int, default=CLI_UPDATE_DEVICE_COLLECTION_TIMEOUT_DEFAULT,
        help=f"Task timeout passed to the server in seconds (default: {CLI_UPDATE_DEVICE_COLLECTION_TIMEOUT_DEFAULT})"
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
        dest="mesh_diag_command", required=False
    )

    def _mesh_device_args(
        p: argparse.ArgumentParser,
        task_timeout: int = CLI_MESH_TASK_TIMEOUT_DEFAULT,
    ) -> None:
        p.add_argument("--device-id", required=True,
                       help="Device extAddress (16-char hex)")
        p.add_argument(
            "--task-timeout", type=int, default=task_timeout,
            help=f"Server-side task timeout in seconds (default: {task_timeout})",
        )
        p.add_argument(
            "--poll-timeout", type=float, default=argparse.SUPPRESS, metavar="FLOAT",
            help=(
                "Max wall-clock seconds to wait for the action (default: derived). "
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
        "--task-timeout", type=int, default=CLI_MESH_TASK_TIMEOUT_DEFAULT,
        help=f"Server-side task timeout per device in seconds (default: {CLI_MESH_TASK_TIMEOUT_DEFAULT})",
    )
    mesh_fetch_all_p.add_argument(
        "--poll-timeout", type=float, default=argparse.SUPPRESS, metavar="FLOAT",
        help="Max wall-clock seconds per device action (default: derived)",
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
            "By default the device list is refreshed first"
        ),
    )
    mesh_fetch_all_p.add_argument(
        "--routers-only",
        action="store_true",
        default=False,
        help=(
            "Restrict queries to router devices only (rloc16 lower-10-bits == 0). "
            "Avoids wasting task slots on child devices for mesh-diagnostic TLVs"
        ),
    )
    mesh_fetch_all_p.add_argument(
        "--preserve-diagnostics",
        action="store_true",
        help="Do not clear the diagnostic collection before this full sweep",
    )
    mesh_fetch_all_p.add_argument(
        "--items-only",
        action="store_true",
        help="Return only diagnostic items instead of the structured sweep outcome",
    )


def _add_topology_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Combined topology sweep: devices → diagnostics → mesh-diagnostics."""
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
        "--task-timeout",
        type=int,
        default=CLI_DIAGNOSTICS_TASK_TIMEOUT_DEFAULT,
        help=f"Server-side timeout for diagnostic actions (default: {CLI_DIAGNOSTICS_TASK_TIMEOUT_DEFAULT})",
    )
    topo_p.add_argument(
        "--no-progress",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Disable per-device progress output",
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
        help="Skip updateDeviceCollectionTask before diagnostics/mesh steps",
    )
    topo_p.add_argument(
        "--no-enrich-mac-counters",
        action="store_true",
        default=False,
        help="Disable MAC counter enrichment on the diagnostics result",
    )
    topo_p.add_argument(
        "--no-fallback",
        action="store_true",
        default=False,
        help="Disable per-device TLV fallback retry on failure",
    )
    topo_p.add_argument(
        "--fallback-preset",
        choices=["medium", "minimal", "basic"],
        default=None,
        help="Opt in to one terminal-action retry with a smaller TLV preset",
    )
    topo_p.add_argument(
        "--preserve-diagnostics",
        action="store_true",
        help="Do not clear diagnostics before the topology diagnostic sweep",
    )


# ---------------------------------------------------------------------------
# Medium TLV preset: RECOMMENDED minus threadStackVersion and mleCounters
# ---------------------------------------------------------------------------
_MEDIUM_DIAGNOSTIC_TLVS: list[str] = [
    t for t in RECOMMENDED_DIAGNOSTIC_TLVS
    if t not in {"threadStackVersion", "mleCounters"}
]

# ---------------------------------------------------------------------------
# MAC Counter Enrichment
# REST API macCounters keys are camelCase (ifInErrors, ifInUcastPkts, …).
# Derived fields are emitted in canonical camelCase.
# ---------------------------------------------------------------------------

def enrich_mac_counters(mac: dict[str, Any]) -> None:
    """Enrich a macCounters dict in-place with derived totals and ratios.

    Accepts the camelCase key format returned by the OTBR REST API and adds
    camelCase totals/ratios used by TDash filtering and rendering.
    """
    key_map = {
        "ifintotalpkts": "ifInTotalPkts",
        "ifouttotalpkts": "ifOutTotalPkts",
        "iftotalpkts": "ifTotalPkts",
        "iftotalerrors": "ifTotalErrors",
        "iftotaldiscards": "ifTotalDiscards",
        "iftotal_inerrdiscs": "ifTotalInErrDiscs",
        "iftotal_outerrdiscs": "ifTotalOutErrDiscs",
        "iftotal_errdiscs": "ifTotalErrDiscs",
        "ifinerrors_totalinerrdiscs_ratio": "ifInErrorsTotalInErrDiscsRatio",
        "ifindiscards_totalinerrdiscs_ratio": "ifInDiscardsTotalInErrDiscsRatio",
        "ifouterrors_totalouterrdiscs_ratio": "ifOutErrorsTotalOutErrDiscsRatio",
        "ifoutdiscards_totalouterrdiscs_ratio": "ifOutDiscardsTotalOutErrDiscsRatio",
        "iftotalerrors_totalerrdiscs_ratio": "ifTotalErrorsTotalErrDiscsRatio",
        "iftotaldiscards_totalerrdiscs_ratio": "ifTotalDiscardsTotalErrDiscsRatio",
        "ifinerrors_intotalpkts_ratio": "ifInErrorsInTotalPktsRatio",
        "ifindiscards_intotalpkts_ratio": "ifInDiscardsInTotalPktsRatio",
        "ifouterrors_outtotalpkts_ratio": "ifOutErrorsOutTotalPktsRatio",
        "ifoutdiscards_outtotalpkts_ratio": "ifOutDiscardsOutTotalPktsRatio",
        "iftotalerrors_totalpkts_ratio": "ifTotalErrorsTotalPktsRatio",
        "iftotaldiscards_totalpkts_ratio": "ifTotalDiscardsTotalPktsRatio",
        "ifinerrors_totalerrors_pct": "ifInErrorsPercentage",
        "ifouterrors_totalerrors_pct": "ifOutErrorsPercentage",
        "ifindiscards_totaldiscards_pct": "ifInDiscardsPercentage",
        "ifoutdiscards_totaldiscards_pct": "ifOutDiscardsPercentage",
    }
    metrics = derive_rest_mac_counter_metrics(mac)
    mac.update({key_map[key]: value for key, value in metrics.items()})


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
# Progress Reporting
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
# Auto-output naming
# ---------------------------------------------------------------------------

_AUTO_OUTPUT_NAMES: dict[tuple[str, str], str] = {
    ("devices", "list"):                OTBR_RESTAPI_DEVICES_LIST_FILENAME,
    ("devices", "fetch"):               OTBR_RESTAPI_DEVICES_FETCH_FILENAME,
    ("diagnostics", "list"):            OTBR_RESTAPI_DIAGNOSTICS_LIST_FILENAME,
    ("diagnostics", "fetch"):           OTBR_RESTAPI_DIAGNOSTICS_FETCH_FILENAME,
    ("diagnostics", "fetch-all"):       OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
    ("actions", "list"):                OTBR_RESTAPI_ACTIONS_LIST_FILENAME,
    ("mesh-diagnostics", "fetch"):      OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_FILENAME,
    ("mesh-diagnostics", "fetch-all"):  OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
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
# Router-only device filter
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
        if rloc16 is None or (rloc16 & ROUTER_RLOC16_MASK) == ROUTER_RLOC16_VALUE:
            result.append(dev_id)
    return result


# ---------------------------------------------------------------------------
# TLV fallback helpers
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
        except (OTBRActionFailedError, OTBRActionTimeoutError, OTBRInvalidResponseError) as exc:
            status = "skipped"
            logging.warning("Skipping device %s: %s", device_id, exc)
        elapsed = time.monotonic() - t_start
        if on_progress is not None:
            on_progress(idx, total, device_id, elapsed, status)
    return results


def build_client(args: argparse.Namespace) -> OTBRRestApiClient:
    """Construct OTBRRestApiClient from parsed CLI arguments."""
    return build_rest_client_from_args(args)


def _find_child_subparser(
    parser: argparse.ArgumentParser, subcommand: str
) -> argparse.ArgumentParser | None:
    """Return a named child subparser from parser, if present."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        child = action.choices.get(subcommand)
        if isinstance(child, argparse.ArgumentParser):
            return child
    return None


def _print_incomplete_command_help(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> bool:
    """Print contextual help for incomplete command chains.

    Returns True if help was printed and CLI should exit success.
    """
    resource = getattr(args, "resource", None)
    if not resource:
        parser.print_help()
        return True

    resource_parser = _find_child_subparser(parser, resource)
    if resource_parser is None:
        return False

    if resource == "node":
        node_cmd = getattr(args, "node_command", None)
        if not node_cmd:
            resource_parser.print_help()
            return True
        if node_cmd == "state":
            state_parser = _find_child_subparser(resource_parser, "state")
            if getattr(args, "state_command", None) is None and state_parser is not None:
                state_parser.print_help()
                return True
        if node_cmd == "dataset":
            dataset_parser = _find_child_subparser(resource_parser, "dataset")
            dataset_kind = getattr(args, "dataset_kind", None)
            if dataset_kind is None and dataset_parser is not None:
                dataset_parser.print_help()
                return True
            if dataset_kind == "active" and dataset_parser is not None:
                active_parser = _find_child_subparser(dataset_parser, "active")
                if getattr(args, "dataset_command", None) is None and active_parser is not None:
                    active_parser.print_help()
                    return True
        return False

    if resource == "devices" and getattr(args, "devices_command", None) is None:
        resource_parser.print_help()
        return True

    if resource == "diagnostics" and getattr(args, "diagnostics_command", None) is None:
        resource_parser.print_help()
        return True

    if resource == "actions":
        actions_cmd = getattr(args, "actions_command", None)
        if actions_cmd is None:
            resource_parser.print_help()
            return True
        if actions_cmd == "enqueue":
            enqueue_parser = _find_child_subparser(resource_parser, "enqueue")
            if getattr(args, "enqueue_type", None) is None and enqueue_parser is not None:
                enqueue_parser.print_help()
                return True
        return False

    if resource == "mesh-diagnostics" and getattr(args, "mesh_diag_command", None) is None:
        resource_parser.print_help()
        return True

    return False


def _subparsers_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _action_for_option(
    parser: argparse.ArgumentParser, option: str
) -> argparse.Action | None:
    for action in parser._actions:
        if option in action.option_strings:
            return action
    return None


def _option_consumes_value(action: argparse.Action) -> bool:
    if action.nargs == 0:
        return False
    if action.nargs in ("*", "+", argparse.REMAINDER):
        return False
    return True


def _print_help_for_typo_or_invalid_command(
    parser: argparse.ArgumentParser, argv: list[str]
) -> bool:
    """Print closest contextual help for typo/invalid command tokens.

    Returns True when help was printed and caller should exit success.
    """
    current = parser
    idx = 0
    while idx < len(argv):
        token = argv[idx]

        if token in ("-h", "--help"):
            return False

        if token.startswith("-"):
            action = _action_for_option(current, token)
            if action is None:
                return False
            idx += 1
            if _option_consumes_value(action) and idx < len(argv):
                idx += 1
            continue

        sub_action = _subparsers_action(current)
        if sub_action is None:
            return False

        child = sub_action.choices.get(token)
        if not isinstance(child, argparse.ArgumentParser):
            current.print_help()
            return True

        current = child
        idx += 1

    return False


def _experimental_command_name(args: argparse.Namespace) -> str | None:
    """Return the experimental command path when --lab gating applies."""
    if args.resource == "node":
        if getattr(args, "node_command", None) == "state" and getattr(args, "state_command", None) == "set":
            return "node state set"
        if (
            getattr(args, "node_command", None) == "dataset"
            and getattr(args, "dataset_kind", None) == "active"
            and getattr(args, "dataset_command", None) == "set"
        ):
            return "node dataset active set"
    if args.resource == "actions" and getattr(args, "actions_command", None) == "enqueue":
        enqueue_type = getattr(args, "enqueue_type", None)
        if enqueue_type == "add-thread-device":
            return "actions enqueue add-thread-device"
        if enqueue_type == "reset-network-diag-counter":
            return "actions enqueue reset-network-diag-counter"
    return None


def dispatch(client: OTBRRestApiClient, args: argparse.Namespace) -> Any:
    experimental_cmd = _experimental_command_name(args)
    if experimental_cmd and not getattr(args, "lab", False):
        raise OTBRUsageError(
            f"Command '{experimental_cmd}' is currently experimental and requires --lab. "
            "Use only in controlled lab/test environments."
        )

    raw_arg = True if args.raw else _RAW_UNSET
    effective_raw = client._resolve_raw(raw_arg)
    fields = build_fields_mapping(getattr(args, "fields", None))

    if args.resource == "node":
        return dispatch_node(client, args, raw_arg, fields)

    if args.resource == "devices":
        return dispatch_devices(client, args, raw_arg, fields)

    if args.resource == "diagnostics":
        return dispatch_diagnostics(client, args, raw_arg, fields)

    if args.resource == "actions":
        return dispatch_actions(client, args, raw_arg, fields, effective_raw)

    if args.resource == "mesh-diagnostics":
        return dispatch_mesh_diagnostics(client, args, raw_arg)

    if args.resource == "topology":
        return dispatch_topology(client, args, raw_arg)

    raise ValueError("Unsupported CLI command")


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

    if not output_path and rendered:
        print(rendered)


def emit_error(exc: Exception) -> None:
    payload = error_to_dict(exc)
    print(json.dumps(payload, indent=4, sort_keys=True), file=sys.stderr)


def exit_code_for_exception(exc: Exception) -> int:
    """Map exceptions to exit codes, with CLI-specific handling for OTBRUsageError."""
    if isinstance(exc, OTBRUsageError):
        return EXIT_USAGE
    # Delegate all REST API exceptions to shared helper
    return exit_code_for_rest_exception(exc)


def run_cli(
    build_parser_fn,
    dispatch_fn,
    build_client_fn,
    argv: Sequence[str] | None = None,
) -> int:
    """Standard CLI entry-point scaffold shared by client CLIs."""
    # Parse arguments first to check debug flag before setting up logging
    parser = build_parser_fn()
    argv_list = list(sys.argv[1:] if argv is None else argv)
    parse_err = io.StringIO()
    with redirect_stderr(parse_err):
        try:
            args = parser.parse_args(argv_list)
        except SystemExit as exc:
            if exc.code != 0 and _print_help_for_typo_or_invalid_command(parser, argv_list):
                return EXIT_SUCCESS
            err_text = parse_err.getvalue()
            if err_text:
                print(err_text, file=sys.stderr, end="")
            return exc.code if isinstance(exc.code, int) else EXIT_USAGE

    if _print_incomplete_command_help(parser, args):
        return EXIT_SUCCESS
    
    # Configure logging based on debug flag
    log_level = logging.DEBUG if getattr(args, "debug", False) else logging.INFO
    logging.basicConfig(
        level=log_level, format="[%(asctime)s] %(levelname)s: %(message)s"
    )
    
    args.td_data_dir = resolve_data_dir(data_dir=args.datadir)

    # Resolve output path: explicit --output > auto-naming > stdout
    output_path = getattr(args, "output", None)
    if output_path:
        output_path = str(resolve_data_file_path(output_path, args.td_data_dir))
    else:
        output_path = _auto_output_path(args, args.td_data_dir)
    args.resolved_output_path = output_path

    try:
        client = build_client_fn(args)
        result = dispatch_fn(client, args)
        emit_output(result, output_path)
        if isinstance(result, dict) and isinstance(result.get("items"), list):
            record_count = len(result["items"])
        elif result is not None and hasattr(result, "__len__"):
            record_count = len(result)
        else:
            record_count = 0
        print(f"Saved {record_count} records to {output_path}" if output_path else "Output written to stdout")

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
