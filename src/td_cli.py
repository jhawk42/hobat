import os
import subprocess
import re
import json
import sys
import time
import logging
import argparse
import io
from typing import Sequence
from contextlib import redirect_stderr
from td_const import (
    LEGACY_THREADSTATIC_EXTADDR_FILENAME,
    TD_DATA_DIR_ARG,
    TD_DATA_DIR_ARG_HELP,
    TD_DATA_DIR_RESOLUTION_SUMMARY,
)

# Note: The imports below are organized to reflect the different components of the project, such as OTBR CLI parsing, REST API interactions, dataset merging, and the web interface. This structure helps maintain clarity and separation of concerns within the codebase.
import util_network
import extaddr_device_label_map

import mdns_thread_scopes
import eve_process
import td_health_cli
import td_system_cli

import otbr_cli_thread_network_info
import otbr_cli_router_table
import otbr_cli_meshdiag_topology
import otbr_cli_meshdiag_childtable
import otbr_cli_meshdiag_childip6
import otbr_cli_meshdiag_routerneighbortable

import otbr_cli_networkdiag_topology

import otbr_restapi_download
import otbr_restapi_cli

import ha_matter_ws_cli

import merge_dataset
import merge_extaddr_device_label_map

class TDHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Formatter with a wider help column for long command names."""

    def __init__(self, prog: str):
        super().__init__(prog, max_help_position=32)


# Command hierarchy:
#   td_cli.py {common-options} {command} {sub-command} {command-options} {command-arguments}
#
# Common options:
#   --help / -h
#   --verbose / -v
#   --debug / -d
#   --output / -o <file>
#
# Top-level commands:
#   otbr-cli      – run OpenThread CLI scans
#   otbr-restapi  – OTBR REST API commands
#   mdns          – query Thread-related mDNS scopes
#   process-eve   – process Eve raw data files
#   merge-dataset – merge datasets
#
# otbr-cli examples:
#   td_cli.py otbr-cli thread-network-info
#   td_cli.py otbr-cli router-table
#   td_cli.py otbr-cli meshdiag topology
#   td_cli.py otbr-cli meshdiag routerneighbortable
#   td_cli.py otbr-cli meshdiag childtable
#   td_cli.py otbr-cli meshdiag childip6
#   td_cli.py otbr-cli meshdiag all
#   td_cli.py otbr-cli networkdiag fetch-all
#   td_cli.py otbr-cli networkdiag multicast-network
#   td_cli.py otbr-cli networkdiag multicast-neighbors
#   td_cli.py otbr-cli topology
#
# mdns examples:
#   td_cli.py mdns
#   td_cli.py mdns thread
#   td_cli.py mdns br
#   td_cli.py mdns hap
#   td_cli.py mdns matter
#   td_cli.py mdns thread --browse-timeout 10
#   td_cli.py mdns thread --haptcp
#   td_cli.py mdns thread --mattertcpsupported
#
# otbr-restapi examples:
#   td_cli.py otbr-restapi download --url http://localhost:8080/api/v1/diagnostics --output td-otbr-restapi-diagnostics.json
#   td_cli.py otbr-restapi devices list
#   td_cli.py otbr-restapi diagnostics list
#   td_cli.py otbr-restapi diagnostics get --diagnostics-id 123456789
#   td_cli.py otbr-restapi actions list
#   td_cli.py otbr-restapi actions get --action-id 123456789
#   td_cli.py otbr-restapi actions enqueue add-thread-device --pskd 12345678 --eui 123456789 --discerner 123
#   td_cli.py otbr-restapi actions enqueue get-network-diagnostic --destination 123456789 --types 1,2,3 --timeout 60 --destination-type extaddr
#   td_cli.py otbr-restapi actions enqueue reset-network-diag-counter --destination 123456789 --types 1,2,3 --timeout 60 --destination-type extaddr
#   td_cli.py otbr-restapi actions enqueue get-energy-scan --destination 123456789 --channel-mask 0x1FFF800 --count 5 --period
#   td_cli.py otbr-restapi node get
#   td_cli.py otbr-restapi mesh-diagnostics fetch-all --routers-only
#   td_cli.py otbr-restapi --raw  diagnostics list
#   td_cli.py otbr-restapi --raw  diagnostics get --diagnostics-id 123456789
#   td_cli.py otbr-restapi --raw  actions list
#   td_cli.py otbr-restapi --raw  actions get --action-id 123456789
#   td_cli.py otbr-restapi --raw  actions enqueue add-thread-device --pskd 12345678 --eui 123456789 --discerner 123
#   td_cli.py otbr-restapi --raw  actions enqueue get-network-diagnostic --destination 123456789 --types 1,2,3 --timeout 60 --destination-type
#
# process-eve examples:
#   td_cli.py process-eve --input eve_data.json --output td-eve-topology.json
#   td_cli.py process-eve --input 'Eve Thread Network Layout.evethreadlayout' --output td-eve-topology.json
#
# merge-dataset examples:
#   td_cli.py merge-dataset --input1 dataset1.json --input2 dataset2.json --output merged_dataset.json
#


# type: ignore[type-arg]
def _add_otbr_cli_commands(subparsers: argparse._SubParsersAction) -> None:
    """Build the flattened otbr-cli and mdns command trees."""

    # otbr-cli
    otbr_cli_p = subparsers.add_parser(
        "otbr-cli",
        help="Scan otbr-cli commands",
        formatter_class=TDHelpFormatter,
    )
    otbr_cli_sub = otbr_cli_p.add_subparsers(
        dest="cli_command", required=False)

    otbr_cli_sub.add_parser(
        "thread-network-info", help="Scan and save thread network info"
    )
    otbr_cli_sub.add_parser("router-table", help="Scan and save router table")

    meshdiag_p = otbr_cli_sub.add_parser(
        "meshdiag",
        help="Scan and save mesh diagnostic data",
        formatter_class=TDHelpFormatter,
    )
    meshdiag_sub = meshdiag_p.add_subparsers(
        dest="meshdiag_command", required=False)
    meshdiag_sub.add_parser("topology", help="Scan and save meshdiag topology")
    meshdiag_sub.add_parser(
        "routerneighbortable", help="Scan and save meshdiag router-neighbour table"
    )
    meshdiag_sub.add_parser(
        "childtable", help="Scan and save meshdiag child table")
    meshdiag_sub.add_parser(
        "childip6", help="Scan and save meshdiag child IPv6 addresses"
    )

    networkdiag_p = otbr_cli_sub.add_parser(
        "networkdiag",
        help="Scan and save network diagnostic data",
        formatter_class=TDHelpFormatter,
    )
    networkdiag_sub = networkdiag_p.add_subparsers(
        dest="networkdiag_command", required=False
    )
    networkdiag_topology_p = networkdiag_sub.add_parser(
        "fetch-all", help="Scan and poll networkdiag topology (unicast, router-by-router)"
    )
    networkdiag_children_group = networkdiag_topology_p.add_mutually_exclusive_group()
    networkdiag_children_group.add_argument(
        "-c",
        "--children",
        dest="expand_children",
        action="store_true",
        default=True,
        help="Expand and include child nodes in the topology map (default)",
    )
    networkdiag_children_group.add_argument(
        "-cno",
        "--children-no",
        dest="expand_children",
        action="store_false",
        help="Do not expand child nodes in the topology map",
    )

    networkdiag_child_fast_group = networkdiag_topology_p.add_mutually_exclusive_group()
    networkdiag_child_fast_group.add_argument(
        "-cff",
        "--children-fetch-fast",
        dest="child_fetch_fast_mode_default",
        action="store_true",
        default=True,
        help="Enable fast child fetching with basic TLVs (default)",
    )
    networkdiag_child_fast_group.add_argument(
        "-cffno",
        "--children-fetch-fast-no",
        dest="child_fetch_fast_mode_default",
        action="store_false",
        help="Disable fast child fetching with basic TLVs",
    )

    networkdiag_child_detail_group = networkdiag_topology_p.add_mutually_exclusive_group()
    networkdiag_child_detail_group.add_argument(
        "-cfd",
        "--children-fetch-detail",
        dest="child_fetch_detail_mode_default",
        action="store_true",
        default=False,
        help="Enable detailed child fetching with higher TLV coverage",
    )
    networkdiag_child_detail_group.add_argument(
        "-cfdno",
        "--children-fetch-detail-no",
        dest="child_fetch_detail_mode_default",
        action="store_false",
        help="Disable detailed child fetching",
    )

    networkdiag_sub.add_parser(
        "multicast-network",
        help="Scan networkdiag topology via multicast to all Thread devices (ff03::1)",
    )
    networkdiag_sub.add_parser(
        "multicast-neighbors",
        help="Scan networkdiag topology via multicast to one-hop neighbors (ff02::1)",
    )
    otbr_cli_sub.add_parser(
        "topology",
        help=(
            "Run full otbr-cli topology sweep: thread-network-info, "
            "router-table, meshdiag topology, networkdiag multicast-network, "
            "networkdiag fetch-all, meshdiag routerneighbortable, meshdiag childtable"
        ),
    )

    # mdns
    mdns_p = subparsers.add_parser(
        "mdns",
        help="Scan Thread-related mDNS scopes",
    )
    mdns_p.add_argument(
        "mdns_scope",
        nargs="?",
        default="thread",
        choices=["thread", "br", "hap", "matter"],
        help="mDNS scope to query (default: thread)",
    )
    mdns_p.add_argument(
        "--browse-timeout",
        type=float,
        default=None,
        dest="browse_timeout",
        help="Browse timeout in seconds forwarded to mdns_thread_scopes",
    )
    mdns_p.add_argument(
        "--haptcp",
        action="store_true",
        default=False,
        help="Include _hap._tcp service scope",
    )
    mdns_p.add_argument(
        "--mattertcpsupported",
        action="store_true",
        default=False,
        help="Include _matterc._udp scope",
    )


# type: ignore[type-arg]
def _add_otbr_restapi_commands(subparsers: argparse._SubParsersAction) -> None:
    """Build the flattened otbr-restapi command tree."""

    # otbr-restapi
    restapi_p = subparsers.add_parser(
        "otbr-restapi", help="Query otbr-restapi sub commands"
    )

    # Pass-through global options forwarded to otbr_restapi_cli before the resource name
    restapi_p.add_argument("--host", default=None, metavar="HOST",
        help="OTBR REST API host (forwarded to otbr_restapi_cli)")
    restapi_p.add_argument("--port", type=int, default=None, metavar="PORT",
        help="OTBR REST API port (forwarded to otbr_restapi_cli)")
    restapi_p.add_argument("--base-url", default=None, metavar="URL",
        help="Override host/port with a full base URL (forwarded)")
    restapi_p.add_argument("--timeout", type=int, default=None, metavar="SECS",
        help="HTTP request timeout in seconds (forwarded)")
    restapi_p.add_argument("--accept", default=None, metavar="MIME",
        help="Default Accept header (forwarded)")
    restapi_p.add_argument("--output", "-o", default=argparse.SUPPRESS, metavar="FILE",
        help="Write command output to FILE (forwarded)")
    restapi_p.add_argument("--datadir", default=argparse.SUPPRESS, metavar="DIR",
        help=TD_DATA_DIR_ARG_HELP)
    restapi_p.add_argument("--raw", action="store_true", default=False,
        help="Return raw API envelopes instead of flattened output (forwarded)")
    restapi_p.add_argument("--poll-interval", type=float, default=None, metavar="FLOAT",
        help="Seconds between action status polls (forwarded)")
    restapi_p.add_argument("--poll-timeout", type=float, default=None, metavar="FLOAT",
        help="Max seconds to wait for an action to complete (forwarded)")
    restapi_p.add_argument("--no-progress", action="store_true", default=False,
        help="Suppress per-device progress output (forwarded)")
    restapi_p.add_argument("--no-auto-output", action="store_true", default=False,
        help="Disable automatic output file naming (forwarded)")
    restapi_p.add_argument("--debug", "-d", action="store_true", default=argparse.SUPPRESS,
        help="Enable OTBR REST API debug logging (forwarded)")
    restapi_p.add_argument(
        "--lab",
        action="store_true",
        default=False,
        help=(
            "Allow experimental otbr-restapi mutating commands "
            "(node state set, node dataset active set, "
            "actions enqueue add-thread-device, "
            "actions enqueue reset-network-diag-counter)"
        ),
    )

    restapi_sub = restapi_p.add_subparsers(
        dest="restapi_command", required=False)

    # otbr-restapi download  — remaining args forwarded to otbr_restapi_download.main()
    restapi_sub.add_parser(
        "download", help="Download OTBR REST API endpoints to JSON files"
    )

    # Promoted resource sub-commands — name-only stubs; all resource-level args
    # captured as extra_args via parse_known_args and forwarded to otbr_restapi_cli.main()
    restapi_sub.add_parser("node",
        help="Read or mutate local OTBR node data", add_help=False)
    restapi_sub.add_parser("devices",
        help="Read OTBR devices", add_help=False)
    restapi_sub.add_parser("diagnostics",
        help="Read OTBR network diagnostics", add_help=False)
    restapi_sub.add_parser("actions",
        help="Read or enqueue OTBR task actions", add_help=False)
    restapi_sub.add_parser("mesh-diagnostics",
        help="Fetch mesh-diagnostic TLVs (children, childIpv6, routerNeighbors)", add_help=False)

    # otbr-restapi topology  — shortcut for otbr_restapi_cli.main(["topology", ...])
    restapi_sub.add_parser(
        "topology",
        help="Full topology sweep: devices fetch + diagnostics fetch-all + mesh-diagnostics fetch-all",
        add_help=False,
    )


# type: ignore[type-arg]
def _add_process_commands(subparsers: argparse._SubParsersAction) -> None:
    """Build routing-only processing commands."""

    # Remaining args are captured as extras via parse_known_args and forwarded to eve_process.main().
    subparsers.add_parser(
        "process-eve",
        help="Parse and enhance an Eve Thread layout file",
        add_help=False,
    )
    health = subparsers.add_parser(
        "health",
        help="Thread network health commands",
    )
    health_commands = health.add_subparsers(dest="health_command", required=True)
    health_commands.add_parser(
        "process-dataset",
        help="Assess approved cached Thread datasets",
        add_help=False,
    )
    health_commands.add_parser("purge", help="Delete old health records", add_help=False)
    health_commands.add_parser("purge-all", help="Delete all health records", add_help=False)
    health_commands.add_parser(
        "purge-by-device", help="Delete one device's health records", add_help=False
    )


# type: ignore[type-arg]
def _add_system_commands(subparsers: argparse._SubParsersAction) -> None:
    """Build routing-only system administration commands."""
    system = subparsers.add_parser("system", help="Hobat system administration")
    system_commands = system.add_subparsers(dest="system_command", required=True)
    backups = system_commands.add_parser("backups", help="Create or restore backups")
    backup_actions = backups.add_subparsers(dest="backup_action", required=True)
    backup_actions.add_parser("create", help="Create a data-directory backup", add_help=False)
    backup_actions.add_parser("restore", help="Restore a data-directory backup", add_help=False)


# type: ignore[type-arg]
def _add_ha_matter_ws_commands(subparsers: argparse._SubParsersAction) -> None:
    """Build the routing-only Home Assistant Matter command tree."""
    matter = subparsers.add_parser(
        "ha-matter-ws",
        help="Collect snapshots from Home Assistant Matter Server",
        description="Collect snapshots from Home Assistant Matter Server",
    )
    matter.add_argument("--uri", default=None)
    matter.add_argument("--connect-timeout", type=float, default=None)
    matter.add_argument("--request-timeout", type=float, default=None)
    matter.add_argument("--settle-timeout", type=float, default=None)
    matter.add_argument("--datadir", default=argparse.SUPPRESS, metavar="DIR")
    matter.add_argument("--output", "-o", default=argparse.SUPPRESS, metavar="FILE")
    matter.add_argument("--no-progress", action="store_true", default=False)
    matter.add_argument("--debug", "-d", action="store_true", default=argparse.SUPPRESS)

    commands = matter.add_subparsers(dest="ha_matter_command", required=False)
    commands.add_parser("server-info")

    devices = commands.add_parser("devices")
    device_commands = devices.add_subparsers(dest="ha_matter_devices_command")
    device_commands.add_parser("list")
    device_get = device_commands.add_parser("get")
    device_get.add_argument("--node-id", required=True)
    device_commands.add_parser("fetch-all")

    diagnostics = commands.add_parser("diagnostics")
    diagnostic_commands = diagnostics.add_subparsers(
        dest="ha_matter_diagnostics_command"
    )
    diagnostic_get = diagnostic_commands.add_parser("get")
    diagnostic_get.add_argument("--node-id", required=True)
    diagnostic_commands.add_parser("fetch-all")

    mesh = commands.add_parser("mesh-diagnostics")
    mesh_commands = mesh.add_subparsers(dest="ha_matter_mesh_diagnostics_command")
    mesh_get = mesh_commands.add_parser("get")
    mesh_get.add_argument("--node-id", required=True)
    mesh_commands.add_parser("fetch-all")

    commands.add_parser("topology")
    commands.add_parser("all")


# type: ignore[type-arg]
def _add_merge_commands(subparsers: argparse._SubParsersAction) -> None:
    """Build the flattened merge commands."""

    # Remaining args are captured as extras via parse_known_args and forwarded to subordinate module main().
    subparsers.add_parser(
        "merge-dataset",
        aliases=["merge-data"],
        help="Merge Thread (otbr-cli, otbr-restapi, eve, mdns) sources into one cache file",
        add_help=False,
    )
    subparsers.add_parser(
        "merge-extaddr",
        help="Merge missing extaddr entries from a topology or mdns input file into the static extaddr map",
        add_help=False,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""

    parser = argparse.ArgumentParser(
        prog="td_cli",
        description="Thread Network Topology Dashboard CLI",
        formatter_class=TDHelpFormatter,
    )

    # --- common options ---
    parser._optionals.title = "Options"
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose (INFO) logging"
    )
    parser.add_argument(
        "--debug", "-d", action="store_true", help="Enable debug logging"
    )
    parser.add_argument(
        "--output", "-o", metavar="FILE", help="Write command output to FILE"
    )
    parser.add_argument(
        "--datadir",
        metavar="DIR",
        default=None,
        help=TD_DATA_DIR_ARG_HELP,
    )

    # --- top-level subcommands ---
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="These are the common commands",
    )

    _add_otbr_cli_commands(subparsers)
    _add_otbr_restapi_commands(subparsers)
    _add_ha_matter_ws_commands(subparsers)
    _add_process_commands(subparsers)
    _add_system_commands(subparsers)
    _add_merge_commands(subparsers)

    # --- hand-crafted "Commands usage:" epilog ---
    parser.epilog = """Commands usage:
    otbr-cli
        usage: td_cli otbr-cli [-h] {thread-network-info,router-table,meshdiag,networkdiag,topology} ...

    otbr-restapi
        usage: td_cli otbr-restapi [-h] {node,devices,diagnostics,actions,mesh-diagnostics,topology,download} ...

    ha-matter-ws
        usage: td_cli ha-matter-ws [-h] {server-info,devices,diagnostics,mesh-diagnostics,topology,all} ...

    mdns
        usage: td_cli mdns [-h] [--browse-timeout SECONDS] [--haptcp] [--mattertcpsupported] [SCOPE]

    process-eve
        usage: td_cli process-eve [-h] ...

    health
        usage: td_cli health [-h] {process-dataset,purge,purge-all,purge-by-device} ...

    system
        usage: td_cli system [-h] backups {create,restore} ...

    merge-dataset
        usage: td_cli merge-dataset [-h] ...

    merge-extaddr
        usage: td_cli merge-extaddr [-h] ...

"""

    # Expose subparsers so dispatch() can print targeted help
    parser._subcommand_parsers = {  # type: ignore[attr-defined]
        "otbr-cli": subparsers._name_parser_map["otbr-cli"],
        "otbr-restapi": subparsers._name_parser_map["otbr-restapi"],
        "ha-matter-ws": subparsers._name_parser_map["ha-matter-ws"],
        "process-eve": subparsers._name_parser_map["process-eve"],
        "health": subparsers._name_parser_map["health"],
        "system": subparsers._name_parser_map["system"],
        "merge-dataset": subparsers._name_parser_map["merge-dataset"],
        "merge-extaddr": subparsers._name_parser_map["merge-extaddr"]
    }

    return parser


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


def _load_extaddr_device_label_map() -> dict:
    """lazily load the extaddr-to-device-label map for scan commands."""
    default_filename = LEGACY_THREADSTATIC_EXTADDR_FILENAME
    if os.path.exists(default_filename):
        return extaddr_device_label_map.load_extaddr_device_label_map(
            default_filename
        )
    logging.debug(
        f"Extaddr JSON file '{default_filename}' not found; using empty mapping."
    )
    return {}


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


def _print_child_subparser_help(
    parser: argparse.ArgumentParser, subcommand: str
) -> bool:
    """Print help for a named child subparser. Returns True when printed."""
    child = _find_child_subparser(parser, subcommand)
    if child is None:
        return False
    child.print_help()
    return True


def _print_restapi_resource_help(resource: str) -> bool:
    """Print otbr_restapi_cli help for a resource command and return success."""
    rest_parser = otbr_restapi_cli.build_parser()
    child = _find_child_subparser(rest_parser, resource)
    if child is None:
        return False
    child.print_help()
    return True


def _forward_with_datadir(args: argparse.Namespace, argv: list[str]) -> list[str]:
    if getattr(args, "datadir", None):
        return [TD_DATA_DIR_ARG, str(args.datadir)] + list(argv)
    return list(argv)


def _normalize_module_rc(raw_rc: object, module_name: str) -> int:
    """Normalize subordinate module return values into a process exit code."""
    if raw_rc is None:
        logging.debug(
            "%s returned None; treating as rc=0 for compatibility.", module_name
        )
        return 0
    if isinstance(raw_rc, int):
        return raw_rc
    logging.error(
        "%s returned non-int exit code (%s); treating as rc=1.",
        module_name,
        type(raw_rc).__name__,
    )
    return 1


_EXPERIMENTAL_RESTAPI_COMMANDS = frozenset(
    {
        ("node", "state", "set"),
        ("node", "dataset", "active", "set"),
        ("actions", "enqueue", "add-thread-device"),
        ("actions", "enqueue", "reset-network-diag-counter"),
    }
)
_RESTAPI_RESOURCE_COMMANDS = frozenset(
    {"node", "devices", "diagnostics", "actions", "mesh-diagnostics"}
)


def _experimental_restapi_command_name(
    restapi_command: str, forwarded_args: list[str]
) -> str | None:
    command_path = (restapi_command, *forwarded_args)
    for experimental_path in _EXPERIMENTAL_RESTAPI_COMMANDS:
        if command_path[:len(experimental_path)] == experimental_path:
            return " ".join(experimental_path)
    return None


def _restapi_globals(args: argparse.Namespace) -> list[str]:
    forwarded: list[str] = []
    if getattr(args, "output", None):
        forwarded += ["--output", args.output]
    if getattr(args, "host", None):
        forwarded += ["--host", args.host]
    if getattr(args, "port", None) is not None:
        forwarded += ["--port", str(args.port)]
    if getattr(args, "base_url", None):
        forwarded += ["--base-url", args.base_url]
    if getattr(args, "timeout", None) is not None:
        forwarded += ["--timeout", str(args.timeout)]
    if getattr(args, "accept", None):
        forwarded += ["--accept", args.accept]
    for attribute, option in (
        ("raw", "--raw"),
        ("poll_interval", "--poll-interval"),
        ("poll_timeout", "--poll-timeout"),
        ("no_progress", "--no-progress"),
        ("no_auto_output", "--no-auto-output"),
        ("debug", "--debug"),
        ("lab", "--lab"),
    ):
        value = getattr(args, attribute, None)
        if attribute in ("poll_interval", "poll_timeout") and value is not None:
            forwarded += [option, str(value)]
        elif value:
            forwarded.append(option)
    return forwarded


def _dispatch_otbr_cli(
    args: argparse.Namespace, extra_args: list[str], parser: argparse.ArgumentParser
) -> int:
    sub_parser = parser._subcommand_parsers["otbr-cli"]  # type: ignore[attr-defined]
    cli_command = args.cli_command
    if not cli_command:
        sub_parser.print_help()
        return 0

    direct_commands = {
        "thread-network-info": (
            otbr_cli_thread_network_info.main,
            "otbr_cli_thread_network_info.main",
        ),
        "router-table": (otbr_cli_router_table.main, "otbr_cli_router_table.main"),
    }
    if cli_command in direct_commands:
        command_main, module_name = direct_commands[cli_command]
        return _normalize_module_rc(
            command_main(_forward_with_datadir(args, extra_args)), module_name
        )

    if cli_command == "topology":
        step_calls = [
            ("otbr_cli_thread_network_info.main", otbr_cli_thread_network_info.main, None),
            ("otbr_cli_router_table.main", otbr_cli_router_table.main, None),
            ("otbr_cli_meshdiag_topology.main", otbr_cli_meshdiag_topology.main, None),
            ("otbr_cli_networkdiag_topology.main", otbr_cli_networkdiag_topology.main, ["multicast-network"]),
            ("otbr_cli_networkdiag_topology.main", otbr_cli_networkdiag_topology.main, ["fetch-all"]),
            ("otbr_cli_meshdiag_routerneighbortable.main", otbr_cli_meshdiag_routerneighbortable.main, None),
            ("otbr_cli_meshdiag_childtable.main", otbr_cli_meshdiag_childtable.main, None),
        ]
        first_nonzero_rc = 0
        for module_name, step_main, step_argv in step_calls:
            try:
                forwarded_argv = list(step_argv) if step_argv is not None else list(extra_args)
                raw_rc = step_main(_forward_with_datadir(args, forwarded_argv))
            except Exception:
                logging.exception("topology step raised an exception: %s", module_name)
                raw_rc = 1
            normalized_rc = _normalize_module_rc(raw_rc, module_name)
            if first_nonzero_rc == 0 and normalized_rc != 0:
                first_nonzero_rc = normalized_rc
                logging.error("topology step failed: %s rc=%s", module_name, normalized_rc)
        return first_nonzero_rc

    if cli_command == "meshdiag":
        meshdiag_command = args.meshdiag_command
        if not meshdiag_command:
            if not _print_child_subparser_help(sub_parser, "meshdiag"):
                sub_parser.print_help()
            return 0
        meshdiag_commands = {
            "topology": (otbr_cli_meshdiag_topology.main, "otbr_cli_meshdiag_topology.main"),
            "routerneighbortable": (
                otbr_cli_meshdiag_routerneighbortable.main,
                "otbr_cli_meshdiag_routerneighbortable.main",
            ),
            "childtable": (otbr_cli_meshdiag_childtable.main, "otbr_cli_meshdiag_childtable.main"),
            "childip6": (otbr_cli_meshdiag_childip6.main, "otbr_cli_meshdiag_childip6.main"),
        }
        command_main, module_name = meshdiag_commands[meshdiag_command]
        return _normalize_module_rc(
            command_main(_forward_with_datadir(args, extra_args)), module_name
        )

    if cli_command == "networkdiag":
        networkdiag_command = args.networkdiag_command
        if not networkdiag_command:
            if not _print_child_subparser_help(sub_parser, "networkdiag"):
                sub_parser.print_help()
            return 0
        networkdiag_argv = [networkdiag_command]
        if networkdiag_command == "fetch-all":
            if not getattr(args, "expand_children", True):
                networkdiag_argv.append("-cno")
            networkdiag_argv.append(
                "--children-fetch-fast"
                if getattr(args, "child_fetch_fast_mode_default", True)
                else "--children-fetch-fast-no"
            )
            networkdiag_argv.append(
                "--children-fetch-detail"
                if getattr(args, "child_fetch_detail_mode_default", False)
                else "--children-fetch-detail-no"
            )
        return _normalize_module_rc(
            otbr_cli_networkdiag_topology.main(
                _forward_with_datadir(args, networkdiag_argv)
            ),
            "otbr_cli_networkdiag_topology.main",
        )

    raise ValueError(f"Unhandled otbr-cli command: {cli_command}")


def _dispatch_mdns(
    args: argparse.Namespace, extra_args: list[str], parser: argparse.ArgumentParser
) -> int:
    del parser
    mdns_argv: list[str] = [getattr(args, "mdns_scope", "thread")]
    if getattr(args, "browse_timeout", None) is not None:
        mdns_argv += ["--browse-timeout", str(args.browse_timeout)]
    if getattr(args, "haptcp", False):
        mdns_argv.append("--haptcp")
    if getattr(args, "mattertcpsupported", False):
        mdns_argv.append("--mattertcpsupported")
    mdns_argv += list(extra_args)
    return _normalize_module_rc(
        mdns_thread_scopes.main(_forward_with_datadir(args, mdns_argv)),
        "mdns_thread_scopes.main",
    )


def _dispatch_otbr_restapi(
    args: argparse.Namespace, extra_args: list[str], parser: argparse.ArgumentParser
) -> int:
    sub_parser = parser._subcommand_parsers["otbr-restapi"]  # type: ignore[attr-defined]
    restapi_command = args.restapi_command
    if not restapi_command:
        sub_parser.print_help()
        return 0
    if restapi_command == "download":
        return _normalize_module_rc(
            otbr_restapi_download.main(_forward_with_datadir(args, extra_args)),
            "otbr_restapi_download.main",
        )
    if restapi_command in _RESTAPI_RESOURCE_COMMANDS:
        if not extra_args:
            if not _print_restapi_resource_help(restapi_command):
                sub_parser.print_help()
            return 0
        experimental_command = _experimental_restapi_command_name(
            restapi_command, extra_args
        )
        if experimental_command and not getattr(args, "lab", False):
            print(
                f"Command '{experimental_command}' is currently experimental and requires --lab. "
                "Use only in controlled lab/test environments.",
                file=sys.stderr,
            )
            return 2
    elif restapi_command != "topology":
        raise ValueError(f"Unhandled otbr-restapi command: {restapi_command}")

    forwarded_argv = _restapi_globals(args) + [restapi_command] + extra_args
    return _normalize_module_rc(
        otbr_restapi_cli.main(_forward_with_datadir(args, forwarded_argv)),
        "otbr_restapi_cli.main",
    )


def _dispatch_process_eve(
    args: argparse.Namespace, extra_args: list[str], parser: argparse.ArgumentParser
) -> int:
    del parser
    return _normalize_module_rc(
        eve_process.main(_forward_with_datadir(args, extra_args)),
        "eve_process.main",
    )


def _dispatch_health(
    args: argparse.Namespace, extra_args: list[str], parser: argparse.ArgumentParser
) -> int:
    del parser
    return _normalize_module_rc(
        td_health_cli.main(
            _forward_with_datadir(args, [args.health_command] + extra_args)
        ),
        "td_health_cli.main",
    )


def _dispatch_system(
    args: argparse.Namespace, extra_args: list[str], parser: argparse.ArgumentParser
) -> int:
    del parser
    return _normalize_module_rc(
        td_system_cli.main(
            _forward_with_datadir(
                args, [args.system_command, args.backup_action] + extra_args
            )
        ),
        "td_system_cli.main",
    )


def _dispatch_ha_matter_ws(
    args: argparse.Namespace, extra_args: list[str], parser: argparse.ArgumentParser
) -> int:
    sub_parser = parser._subcommand_parsers["ha-matter-ws"]  # type: ignore[attr-defined]
    command = getattr(args, "ha_matter_command", None)
    if not command:
        sub_parser.print_help()
        return 0

    nested_attribute = f"ha_matter_{command.replace('-', '_')}_command"
    nested = getattr(args, nested_attribute, None)
    if command in {"devices", "diagnostics", "mesh-diagnostics"} and not nested:
        return _normalize_module_rc(
            ha_matter_ws_cli.main([command, "--help"]),
            "ha_matter_ws_cli.main",
        )

    forwarded: list[str] = []
    if getattr(args, "datadir", None):
        forwarded += ["--datadir", str(args.datadir)]
    for attribute, option in (
        ("uri", "--uri"),
        ("connect_timeout", "--connect-timeout"),
        ("request_timeout", "--request-timeout"),
        ("settle_timeout", "--settle-timeout"),
        ("output", "--output"),
    ):
        value = getattr(args, attribute, None)
        if value is not None:
            forwarded += [option, str(value)]
    if getattr(args, "no_progress", False):
        forwarded.append("--no-progress")
    if getattr(args, "debug", False):
        forwarded.append("--debug")

    forwarded.append(command)
    if nested:
        forwarded.append(nested)
    node_id = getattr(args, "node_id", None)
    if node_id is not None:
        forwarded += ["--node-id", str(node_id)]
    forwarded += extra_args
    return _normalize_module_rc(
        ha_matter_ws_cli.main(forwarded), "ha_matter_ws_cli.main"
    )


def _dispatch_merge(
    args: argparse.Namespace, extra_args: list[str], parser: argparse.ArgumentParser
) -> int:
    del parser
    if args.command in ("merge-dataset", "merge-data"):
        command_main = merge_dataset.main
        module_name = "merge_dataset.main"
    else:
        command_main = merge_extaddr_device_label_map.main
        module_name = "merge_extaddr_device_label_map.main"
    return _normalize_module_rc(
        command_main(_forward_with_datadir(args, extra_args)), module_name
    )


_FAMILY_DISPATCHERS = {
    "otbr-cli": _dispatch_otbr_cli,
    "mdns": _dispatch_mdns,
    "otbr-restapi": _dispatch_otbr_restapi,
    "ha-matter-ws": _dispatch_ha_matter_ws,
    "process-eve": _dispatch_process_eve,
    "health": _dispatch_health,
    "system": _dispatch_system,
    "merge-dataset": _dispatch_merge,
    "merge-data": _dispatch_merge,
    "merge-extaddr": _dispatch_merge,
}


def dispatch(
    args: argparse.Namespace, extra_args: list[str], parser: argparse.ArgumentParser
) -> int:
    """Dispatch parsed arguments to the owning command-family handler."""
    handler = _FAMILY_DISPATCHERS.get(args.command)
    if handler is None:
        raise ValueError(f"Unhandled command: {args.command}")
    return handler(args, extra_args, parser)


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point with optional command-line arguments."""

    # Default logging configuration; level may be raised to DEBUG after arg parsing
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    argv_list: list[str] = list(sys.argv[1:] if argv is None else argv)

    parser = build_parser()

    if not argv_list:
        parser.print_help()
        return 0

    # parse_known_args lets option-style args for subordinate modules (--host, --input, etc.)
    # pass through as extras instead of being rejected by the routing-only subparsers.
    parse_err = io.StringIO()
    with redirect_stderr(parse_err):
        try:
            args, extras = parser.parse_known_args(argv_list)
        except SystemExit as exc:
            if exc.code != 0 and _print_help_for_typo_or_invalid_command(parser, argv_list):
                return 0
            err_text = parse_err.getvalue()
            if err_text:
                print(err_text, file=sys.stderr, end="")
            return exc.code if isinstance(exc.code, int) else 2

    # Apply verbosity / debug flags
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    single_record_json_output = (
        args.command == "merge-extaddr"
        and any(option in extras for option in ("--read-extaddr", "--update-extaddr"))
    ) or (args.command in {"health", "system"} and "--json" in extras)

    if not single_record_json_output:
        print("Thread Network Topology CLI")
        print("")
    # log args at debug level
    logging.debug("Parsed arguments: %s", args)
    # Build a flattened sub-command string from parsed namespace fields so
    # nested commands (for example: networkdiag multicast-network) are visible.
    subcommand_parts: list[str] = []
    for attr in (
        "cli_command",
        "meshdiag_command",
        "networkdiag_command",
        "restapi_command",
        "ha_matter_command",
        "ha_matter_devices_command",
        "ha_matter_diagnostics_command",
        "ha_matter_mesh_diagnostics_command",
        "health_command",
        "system_command",
        "backup_action",
    ):
        value = getattr(args, attr, None)
        if value:
            subcommand_parts.append(str(value))
    subcommand_text = " ".join(subcommand_parts) if subcommand_parts else ""

    # log command, sub-command path, and extras[]
    if not single_record_json_output:
        print(
            f"Command: {getattr(args, 'command', None)}, sub-command: {subcommand_text}"
        )
    # dispatch command
    try:
        rc = dispatch(args, extras, parser)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        logging.exception("Unhandled exception during command dispatch")
        return 1

    # log complete message
    logging.info("complete.")

    return rc


if __name__ == "__main__":
    sys.exit(main())
