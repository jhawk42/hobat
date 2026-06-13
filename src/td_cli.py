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
from td_const import TD_DATA_DIR_ARG, TD_DATA_DIR_ARG_HELP, TD_DATA_DIR_RESOLUTION_SUMMARY

# Note: The imports below are organized to reflect the different components of the project, such as OTBR CLI parsing, REST API interactions, dataset merging, and the web interface. This structure helps maintain clarity and separation of concerns within the codebase.
import util_network
import extaddr_device_label_map

import mdns_thread_scopes
import eve_process

import otbr_cli_thread_network_info
import otbr_cli_router_table
import otbr_cli_meshdiag_topology
import otbr_cli_meshdiag_childtable
import otbr_cli_meshdiag_childip6
import otbr_cli_meshdiag_routerneighbortable

import otbr_cli_networkdiag_topology

import otbr_restapi_download
import otbr_restapi_cli

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
#   td_cli.py otbr-cli all
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
    networkdiag_sub.add_parser(
        "multicast-network",
        help="Scan networkdiag topology via multicast to all Thread devices (ff03::1)",
    )
    networkdiag_sub.add_parser(
        "multicast-neighbors",
        help="Scan networkdiag topology via multicast to one-hop neighbors (ff02::1)",
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
    """Build the flattened process-eve command."""

    # Remaining args are captured as extras via parse_known_args and forwarded to eve_process.main().
    subparsers.add_parser(
        "process-eve",
        help="Parse and enhance an Eve Thread layout file",
        add_help=False,
    )


# type: ignore[type-arg]
def _add_merge_commands(subparsers: argparse._SubParsersAction) -> None:
    """Build the flattened merge commands."""

    # Remaining args are captured as extras via parse_known_args and forwarded to subordinate module main().
    subparsers.add_parser(
        "merge-dataset",
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
    _add_process_commands(subparsers)
    _add_merge_commands(subparsers)

    # --- hand-crafted "Commands usage:" epilog ---
    parser.epilog = """Commands usage:
    otbr-cli
        usage: td_cli otbr-cli [-h] {thread-network-info,router-table,meshdiag,networkdiag} ...

    otbr-restapi
        usage: td_cli otbr-restapi [-h] {download,node,devices,diagnostics,actions,mesh-diagnostics,topology} ...

    mdns
        usage: td_cli mdns [-h] [--browse-timeout SECONDS] [--haptcp] [--mattertcpsupported] [SCOPE]

    process-eve
        usage: td_cli process-eve [-h] ...

    merge-dataset
        usage: td_cli merge-dataset [-h] ...

    merge-extaddr
        usage: td_cli merge-extaddr [-h] ...

"""

    # Expose subparsers so dispatch() can print targeted help
    parser._subcommand_parsers = {  # type: ignore[attr-defined]
        "otbr-cli": subparsers._name_parser_map["otbr-cli"],
        "otbr-restapi": subparsers._name_parser_map["otbr-restapi"],
        "process-eve": subparsers._name_parser_map["process-eve"],
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
    default_filename = "threadstatic-extaddr.json"
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


def dispatch(
    args: argparse.Namespace, extra_args: list[str], parser: argparse.ArgumentParser
) -> int:
    """Dispatch parsed arguments to the appropriate module entry point.

    extra_args contains the unrecognised arguments returned by parse_known_args.
    For scan commands it should be empty.  For forwarding commands (web, process,
    merge) it is passed directly to the subordinate module's main().
    """
    sub_parsers = parser._subcommand_parsers  # type: ignore[attr-defined]

    def _forward_with_datadir(argv: list[str]) -> list[str]:
        if getattr(args, "datadir", None):
            return [TD_DATA_DIR_ARG, str(args.datadir)] + list(argv)
        return list(argv)

    def _normalize_module_rc(raw_rc: object, module_name: str) -> int:
        """Normalize subordinate module return values into a process exit code.

        Compatibility behavior:
        - None is treated as success (0), because some existing collectors do not
          return explicit values on success paths yet.
        - Non-int return values are treated as internal errors (1).
        """
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

    def _experimental_restapi_command_name(
        restapi_cmd: str | None, forwarded_args: list[str]
    ) -> str | None:
        if restapi_cmd == "node":
            if len(forwarded_args) >= 2 and forwarded_args[0] == "state" and forwarded_args[1] == "set":
                return "node state set"
            if (
                len(forwarded_args) >= 3
                and forwarded_args[0] == "dataset"
                and forwarded_args[1] == "active"
                and forwarded_args[2] == "set"
            ):
                return "node dataset active set"
        if restapi_cmd == "actions" and len(forwarded_args) >= 2 and forwarded_args[0] == "enqueue":
            if forwarded_args[1] == "add-thread-device":
                return "actions enqueue add-thread-device"
            if forwarded_args[1] == "reset-network-diag-counter":
                return "actions enqueue reset-network-diag-counter"
        return None

    # --- otbr-cli ---
    if args.command == "otbr-cli":
        cli_cmd = args.cli_command
        if not cli_cmd:
            sub_parsers["otbr-cli"].print_help()
            return 0

        if cli_cmd == "thread-network-info":
            return _normalize_module_rc(
                otbr_cli_thread_network_info.main(_forward_with_datadir(extra_args)),
                "otbr_cli_thread_network_info.main",
            )

        if cli_cmd == "router-table":
            return _normalize_module_rc(
                otbr_cli_router_table.main(_forward_with_datadir(extra_args)),
                "otbr_cli_router_table.main",
            )

        if cli_cmd == "meshdiag":
            meshdiag_cmd = args.meshdiag_command
            if not meshdiag_cmd:
                if not _print_child_subparser_help(sub_parsers["otbr-cli"], "meshdiag"):
                    sub_parsers["otbr-cli"].print_help()
                return 0
            if meshdiag_cmd == "topology":
                return _normalize_module_rc(
                    otbr_cli_meshdiag_topology.main(
                        _forward_with_datadir(extra_args)
                    ),
                    "otbr_cli_meshdiag_topology.main",
                )
            if meshdiag_cmd == "routerneighbortable":
                return _normalize_module_rc(
                    otbr_cli_meshdiag_routerneighbortable.main(
                        _forward_with_datadir(extra_args)
                    ),
                    "otbr_cli_meshdiag_routerneighbortable.main",
                )
            if meshdiag_cmd == "childtable":
                return _normalize_module_rc(
                    otbr_cli_meshdiag_childtable.main(_forward_with_datadir(extra_args)),
                    "otbr_cli_meshdiag_childtable.main",
                )
            if meshdiag_cmd == "childip6":
                return _normalize_module_rc(
                    otbr_cli_meshdiag_childip6.main(_forward_with_datadir(extra_args)),
                    "otbr_cli_meshdiag_childip6.main",
                )


        if cli_cmd == "networkdiag":
            if not args.networkdiag_command:
                if not _print_child_subparser_help(sub_parsers["otbr-cli"], "networkdiag"):
                    sub_parsers["otbr-cli"].print_help()
                return 0
            if args.networkdiag_command == "fetch-all":
                expand_children_argv = (
                    [] if getattr(args, "expand_children", True) else ["-cno"]
                )
                return _normalize_module_rc(
                    otbr_cli_networkdiag_topology.main(
                        _forward_with_datadir(expand_children_argv)
                    ),
                    "otbr_cli_networkdiag_topology.main",
                )
            if args.networkdiag_command == "multicast-network":
                return _normalize_module_rc(
                    otbr_cli_networkdiag_topology.main_multicast_network(
                        _forward_with_datadir([])
                    ),
                    "otbr_cli_networkdiag_topology.main_multicast_network",
                )
            if args.networkdiag_command == "multicast-neighbors":
                return _normalize_module_rc(
                    otbr_cli_networkdiag_topology.main_multicast_neighbors(
                        _forward_with_datadir([])
                    ),
                    "otbr_cli_networkdiag_topology.main_multicast_neighbors",
                )


    # --- mdns ---
    if args.command == "mdns":
        mdns_argv: list[str] = [getattr(args, "mdns_scope", "thread")]
        if getattr(args, "browse_timeout", None) is not None:
            mdns_argv += ["--browse-timeout", str(args.browse_timeout)]
        if getattr(args, "haptcp", False):
            mdns_argv.append("--haptcp")
        if getattr(args, "mattertcpsupported", False):
            mdns_argv.append("--mattertcpsupported")
        mdns_argv += list(extra_args)
        return _normalize_module_rc(
            mdns_thread_scopes.main(_forward_with_datadir(mdns_argv)),
            "mdns_thread_scopes.main",
        )

    # --- otbr-restapi ---
    if args.command == "otbr-restapi":
        restapi_cmd = args.restapi_command
        if not restapi_cmd:
            sub_parsers["otbr-restapi"].print_help()
            return 0

        if restapi_cmd == "download":
            return _normalize_module_rc(
                otbr_restapi_download.main(_forward_with_datadir(extra_args)),
                "otbr_restapi_download.main",
            )

        # Build the base global-option args that otbr_restapi_cli expects before the
        # resource subcommand.  --output and --datadir are td_cli globals consumed by
        # parse_known_args and handled separately; all other pass-through options are
        # collected here so they land before the resource name in forwarded argv.
        def _restapi_globals() -> list[str]:
            fwd: list[str] = []
            if getattr(args, "output", None):
                fwd += ["--output", args.output]
            if getattr(args, "host", None):
                fwd += ["--host", args.host]
            if getattr(args, "port", None) is not None:
                fwd += ["--port", str(args.port)]
            if getattr(args, "base_url", None):
                fwd += ["--base-url", args.base_url]
            if getattr(args, "timeout", None) is not None:
                fwd += ["--timeout", str(args.timeout)]
            if getattr(args, "accept", None):
                fwd += ["--accept", args.accept]
            if getattr(args, "raw", False):
                fwd += ["--raw"]
            if getattr(args, "poll-interval", None) is not None:
                fwd += ["--poll-interval", str(args.poll_interval)]
            if getattr(args, "poll-timeout", None) is not None:
                fwd += ["--poll-timeout", str(args.poll_timeout)]
            if getattr(args, "no-progress", False):
                fwd += ["--no-progress"]
            if getattr(args, "no-auto-output", False):
                fwd += ["--no-auto-output"]
            if getattr(args, "lab", False):
                fwd += ["--lab"]
            return fwd

        _RESTAPI_RESOURCE_CMDS = frozenset(
            {"node", "devices", "diagnostics", "actions", "mesh-diagnostics"}
        )

        if restapi_cmd in _RESTAPI_RESOURCE_CMDS:
            if not extra_args:
                if not _print_restapi_resource_help(restapi_cmd):
                    sub_parsers["otbr-restapi"].print_help()
                return 0
            experimental_cmd = _experimental_restapi_command_name(restapi_cmd, list(extra_args))
            if experimental_cmd and not getattr(args, "lab", False):
                print(
                    (
                        f"Command '{experimental_cmd}' is currently experimental and requires --lab. "
                        "Use only in controlled lab/test environments."
                    ),
                    file=sys.stderr,
                )
                return 2
            return _normalize_module_rc(
                otbr_restapi_cli.main(
                    _forward_with_datadir(
                        _restapi_globals() + [restapi_cmd] + extra_args
                    )
                ),
                "otbr_restapi_cli.main",
            )

        if restapi_cmd == "topology":
            return _normalize_module_rc(
                otbr_restapi_cli.main(
                    _forward_with_datadir(_restapi_globals() + ["topology"] + extra_args)
                ),
                "otbr_restapi_cli.main",
            )


    # --- process-eve ---
    if args.command == "process-eve":
        return _normalize_module_rc(
            eve_process.main(_forward_with_datadir(extra_args)),
            "eve_process.main",
        )

    # --- merge-dataset ---
    if args.command in ("merge-dataset", "merge-data"):
        return _normalize_module_rc(
            merge_dataset.main(_forward_with_datadir(extra_args)),
            "merge_dataset.main",
        )

    # --- merge-extaddr ---
    if args.command == "merge-extaddr":
        return _normalize_module_rc(
            merge_extaddr_device_label_map.main(_forward_with_datadir(extra_args)),
            "merge_extaddr_device_label_map.main",
        )

    # --- unhandled command ---
    raise ValueError(f"Unhandled command: {args.command}")


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

    # banner
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
    ):
        value = getattr(args, attr, None)
        if value:
            subcommand_parts.append(str(value))
    subcommand_text = " ".join(subcommand_parts) if subcommand_parts else ""

    # log command, sub-command path, and extras[]
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
