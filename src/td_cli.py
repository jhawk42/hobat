import os
import subprocess
import re
import json
import sys
import time
import logging
import argparse
from typing import Sequence
from const import TD_DATA_DIR_ARG, TD_DATA_DIR_ARG_HELP, TD_DATA_DIR_RESOLUTION_SUMMARY

# Note: The imports below are organized to reflect the different components of the project, such as OTBR CLI parsing, REST API interactions, dataset merging, and the web interface. This structure helps maintain clarity and separation of concerns within the codebase.
import util_network
import extaddr_device_label_map

import mdns_thread_scopes
import eve_parse

import otbr_cli_network_dataset_info
import otbr_cli_router_table
import otbr_cli_meshdiag_topology
import otbr_cli_meshdiag_childtable
import otbr_cli_meshdiag_childip6
import otbr_cli_meshdiag_routerneighbortable

import otbr_cli_networkdiag_topology

import otbr_restapi_download
import otbr_restapi_client_cli
import otbr_restapi_raw_client_cli

import dataset_merge
import web_server


class TDHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Formatter with a wider help column for long command names."""

    def __init__(self, prog: str):
        super().__init__(prog, max_help_position=32)


## Command hierarchy:
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
#   web-server  – start the web dashboard server
#
# otbr-cli examples:
#   td_cli.py otbr-cli network-dataset-info
#   td_cli.py otbr-cli router-table
#   td_cli.py otbr-cli meshdiag topology
#   td_cli.py otbr-cli meshdiag routerneighbortable
#   td_cli.py otbr-cli meshdiag childtable
#   td_cli.py otbr-cli meshdiag childip6
#   td_cli.py otbr-cli meshdiag all
#   td_cli.py otbr-cli networkdiag topology
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
#   td_cli.py otbr-restapi client diagnostics list
#   td_cli.py otbr-restapi client diagnostics get --diagnostics-id 123456789
#   td_cli.py otbr-restapi client actions list
#   td_cli.py otbr-restapi client actions get --action-id 123456789
#   td_cli.py otbr-restapi client actions enqueue add-thread-device --pskd 12345678 --eui 123456789 --discerner 123
#   td_cli.py otbr-restapi client actions enqueue get-network-diagnostic --destination 123456789 --types 1,2,3 --timeout 60 --destination-type extaddr
#   td_cli.py otbr-restapi client actions enqueue reset-network-diag-counter --destination 123456789 --types 1,2,3 --timeout 60 --destination-type extaddr
#   td_cli.py otbr-restapi client actions enqueue get-energy-scan --destination 123456789 --channel-mask 0x1FFF800 --count 5 --period
#   td_cli.py otbr-restapi rawclient diagnostics list
#   td_cli.py otbr-restapi rawclient diagnostics get --diagnostics-id 123456789
#   td_cli.py otbr-restapi rawclient actions list
#   td_cli.py otbr-restapi rawclient actions get --action-id 123456789
#   td_cli.py otbr-restapi rawclient actions enqueue add-thread-device --pskd 12345678 --eui 123456789 --discerner 123
#   td_cli.py otbr-restapi rawclient actions enqueue get-network-diagnostic --destination 123456789 --types 1,2,3 --timeout 60 --destination-type
#
# process-eve examples:
#   td_cli.py process-eve --input eve_data.json --output td-eve-topology.json
#   td_cli.py process-eve --input 'Eve Thread Network Layout.evethreadlayout' --output td-eve-topology.json
#
# merge-dataset examples:
#   td_cli.py merge-dataset --input1 dataset1.json --input2 dataset2.json --output merged_dataset.json
#
# web-server examples:
#   td_cli.py web-server --host localhost --port 8087


def _add_scan_commands(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Build the flattened otbr-cli and mdns command trees."""

    # otbr-cli
    otbr_cli_p = subparsers.add_parser(
        "otbr-cli",
        help="Scan otbr-cli commands",
        formatter_class=TDHelpFormatter,
    )
    otbr_cli_sub = otbr_cli_p.add_subparsers(dest="cli_command", required=False)

    otbr_cli_sub.add_parser(
        "network-dataset-info", help="Scan and save network dataset info"
    )
    otbr_cli_sub.add_parser("router-table", help="Scan and save router table")

    meshdiag_p = otbr_cli_sub.add_parser(
        "meshdiag",
        help="Scan and save mesh diagnostic data",
        formatter_class=TDHelpFormatter,
    )
    meshdiag_sub = meshdiag_p.add_subparsers(dest="meshdiag_command", required=True)
    meshdiag_sub.add_parser("topology", help="Scan and save meshdiag topology")
    meshdiag_sub.add_parser(
        "routerneighbortable", help="Scan and save meshdiag router-neighbour table"
    )
    meshdiag_sub.add_parser("childtable", help="Scan and save meshdiag child table")
    meshdiag_sub.add_parser(
        "childip6", help="Scan and save meshdiag child IPv6 addresses"
    )
    meshdiag_sub.add_parser("all", help="Run all meshdiag scans")

    networkdiag_p = otbr_cli_sub.add_parser(
        "networkdiag",
        help="Scan and save network diagnostic data",
        formatter_class=TDHelpFormatter,
    )
    networkdiag_sub = networkdiag_p.add_subparsers(
        dest="networkdiag_command", required=True
    )
    networkdiag_topology_p = networkdiag_sub.add_parser(
        "topology", help="Scan and save networkdiag topology"
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

    otbr_cli_sub.add_parser("all", help="Run all otbr-cli scans")

    # mdns
    mdns_p = subparsers.add_parser("mdns", help="Scan Thread-related mDNS scopes")
    mdns_p.add_argument(
        "mdns_scope",
        nargs="?",
        choices=["thread", "br", "hap", "matter"],
        default="thread",
        metavar="SCOPE",
        help="Scope filter: thread | br | hap | matter  (default: thread)",
    )
    mdns_p.add_argument(
        "--browse-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Seconds of idle time before auto-exit (default: 10, or TD_MDNS_BROWSE_TIMEOUT env var)",
    )
    mdns_p.add_argument(
        "--haptcp",
        action="store_true",
        default=False,
        help="Also browse _hap._tcp.local. (Wi-Fi HomeKit accessories). "
        "Applies when scope is 'thread' or 'hap'. Off by default.",
    )
    mdns_p.add_argument(
        "--mattertcpsupported",
        action="store_true",
        default=False,
        help="Include _matter._tcp records where T=1 (TCP supported). "
        "By default those records are excluded.",
    )


def _add_web_commands(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Build the flattened otbr-restapi command tree."""

    # otbr-restapi
    restapi_p = subparsers.add_parser(
        "otbr-restapi", help="Query otbr-restapi sub commands"
    )
    restapi_sub = restapi_p.add_subparsers(dest="restapi_command", required=False)

    # otbr-restapi download  — remaining args forwarded to otbr_restapi_download.main()
    restapi_sub.add_parser(
        "download", help="Download OTBR REST API endpoints to JSON files"
    )

    # otbr-restapi client  — remaining args forwarded to otbr_restapi_client_cli.main()
    restapi_sub.add_parser(
        "client", help="Call OTBR REST API client commands (flattened output)"
    )

    # otbr-restapi rawclient  — remaining args forwarded to otbr_restapi_raw_client_cli.main()
    restapi_sub.add_parser(
        "rawclient", help="Call OTBR REST API client commands (raw envelopes)"
    )


def _add_process_commands(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Build the flattened process-eve command."""

    # Remaining args are captured as extras via parse_known_args and forwarded to eve_parse.main().
    subparsers.add_parser(
        "process-eve", help="Parse and enhance an Eve Thread layout file"
    )


def _add_merge_commands(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Build the flattened merge-dataset command."""

    # Remaining args are captured as extras via parse_known_args and forwarded to dataset_merge.main().
    subparsers.add_parser(
        "merge-dataset",
        help="Merge Thread (otbr-cli, otbr-restapi, eve, mdns) sources into one cache file",
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

    _add_scan_commands(subparsers)
    _add_web_commands(subparsers)
    _add_process_commands(subparsers)
    _add_merge_commands(subparsers)

    # web-server — remaining args forwarded to web_server.main()
    ws_p = subparsers.add_parser("web-server", help="Start the web dashboard server")
    ws_p.add_argument(
        "--host", default="localhost", help="Host to bind to (default: localhost)"
    )
    ws_p.add_argument(
        "--port", type=int, default=8087, help="Port to listen on (default: 8087)"
    )

    # --- hand-crafted "Commands usage:" epilog ---
    parser.epilog = """Commands usage:
    otbr-cli
        usage: td_cli otbr-cli [-h] {network-dataset-info,router-table,meshdiag,networkdiag,all} ...

    otbr-restapi
        usage: td_cli otbr-restapi [-h] {download,client,rawclient} ...

    mdns
        usage: td_cli mdns [-h] [--browse-timeout SECONDS] [--haptcp] [--mattertcpsupported] [SCOPE]

    process-eve
        usage: td_cli process-eve [-h] ...

    merge-dataset
        usage: td_cli merge-dataset [-h] ...

    web-server
        usage: td_cli web-server [-h] [--host HOST] [--port PORT]
        options:
                --host HOST  Host to bind to (default: localhost)
                --port PORT  Port to listen on (default: 8087)

"""

    # Expose subparsers so dispatch() can print targeted help
    parser._subcommand_parsers = {  # type: ignore[attr-defined]
        "otbr-cli": subparsers._name_parser_map["otbr-cli"],
        "otbr-restapi": subparsers._name_parser_map["otbr-restapi"],
        "process-eve": subparsers._name_parser_map["process-eve"],
        "merge-dataset": subparsers._name_parser_map["merge-dataset"],
        "web-server": ws_p,
    }

    return parser


def _load_extaddr_map() -> dict:
    """lazily load the extaddr-to-device-label map for scan commands."""
    EXTADDR_JSON_FILENAME_DEFAULT = "threadstatic-extaddr.json"
    if os.path.exists(EXTADDR_JSON_FILENAME_DEFAULT):
        return extaddr_device_label_map.extaddr_device_label_mapping_load(
            EXTADDR_JSON_FILENAME_DEFAULT
        )
    logging.debug(
        f"Extaddr JSON file '{EXTADDR_JSON_FILENAME_DEFAULT}' not found; using empty mapping."
    )
    return {}


def dispatch(
    args: argparse.Namespace, sub_argv: list[str], parser: argparse.ArgumentParser
) -> int:
    """Dispatch parsed arguments to the appropriate module entry point.

    sub_argv contains the unrecognised arguments returned by parse_known_args.
    For scan commands it should be empty.  For forwarding commands (web, process,
    merge) it is passed directly to the subordinate module's main().
    """
    _sub = parser._subcommand_parsers  # type: ignore[attr-defined]

    def _forward_with_datadir(argv: list[str]) -> list[str]:
        if getattr(args, "datadir", None):
            return [TD_DATA_DIR_ARG, str(args.datadir)] + list(argv)
        return list(argv)

    # --- otbr-cli ---
    if args.command == "otbr-cli":
        cli_cmd = args.cli_command
        if not cli_cmd:
            _sub["otbr-cli"].print_help()
            return 0

        if cli_cmd == "network-dataset-info":
            return (
                otbr_cli_network_dataset_info.main(_forward_with_datadir(sub_argv)) or 0
            )

        if cli_cmd == "router-table":
            return otbr_cli_router_table.main(_forward_with_datadir(sub_argv)) or 0

        if cli_cmd == "meshdiag":
            meshdiag_cmd = args.meshdiag_command
            if meshdiag_cmd == "topology":
                return (
                    otbr_cli_meshdiag_topology.main(_forward_with_datadir(sub_argv))
                    or 0
                )
            if meshdiag_cmd == "routerneighbortable":
                return (
                    otbr_cli_meshdiag_routerneighbortable.main(
                        _forward_with_datadir(sub_argv)
                    )
                    or 0
                )
            if meshdiag_cmd == "childtable":
                return (
                    otbr_cli_meshdiag_childtable.main(_forward_with_datadir(sub_argv))
                    or 0
                )
            if meshdiag_cmd == "childip6":
                return (
                    otbr_cli_meshdiag_childip6.main(_forward_with_datadir(sub_argv))
                    or 0
                )
            if meshdiag_cmd == "all":
                forwarded = _forward_with_datadir(sub_argv)
                rc = otbr_cli_meshdiag_topology.main(forwarded) or 0
                rc = rc or otbr_cli_meshdiag_routerneighbortable.main(forwarded) or 0
                rc = rc or otbr_cli_meshdiag_childtable.main(forwarded) or 0
                rc = rc or otbr_cli_meshdiag_childip6.main(forwarded) or 0
                return rc

        if cli_cmd == "networkdiag":
            if args.networkdiag_command == "topology":
                expand_children_argv = (
                    [] if getattr(args, "expand_children", True) else ["-cno"]
                )
                return (
                    otbr_cli_networkdiag_topology.main(
                        _forward_with_datadir(expand_children_argv)
                    )
                    or 0
                )

        if cli_cmd == "all":
            forwarded = _forward_with_datadir(sub_argv)
            rc = otbr_cli_network_dataset_info.main(forwarded) or 0
            rc = rc or otbr_cli_router_table.main(forwarded) or 0
            rc = rc or otbr_cli_meshdiag_topology.main(forwarded) or 0
            rc = rc or otbr_cli_meshdiag_routerneighbortable.main(forwarded) or 0
            rc = rc or otbr_cli_meshdiag_childtable.main(forwarded) or 0
            rc = rc or otbr_cli_meshdiag_childip6.main(forwarded) or 0
            rc = rc or otbr_cli_networkdiag_topology.main(forwarded) or 0
            return rc

    # --- mdns ---
    if args.command == "mdns":
        mdns_argv = (
            [args.mdns_scope]
            + (
                ["--browse-timeout", str(args.browse_timeout)]
                if args.browse_timeout is not None
                else []
            )
            + (["--haptcp"] if args.haptcp else [])
            + (["--mattertcpsupported"] if args.mattertcpsupported else [])
            + sub_argv
        )
        return mdns_thread_scopes.main(_forward_with_datadir(mdns_argv)) or 0

    # --- otbr-restapi ---
    if args.command == "otbr-restapi":
        restapi_cmd = args.restapi_command
        if not restapi_cmd:
            _sub["otbr-restapi"].print_help()
            return 0

        if restapi_cmd == "download":
            return otbr_restapi_download.main(_forward_with_datadir(sub_argv)) or 0
        if restapi_cmd == "client":
            return otbr_restapi_client_cli.main(_forward_with_datadir(sub_argv)) or 0
        if restapi_cmd == "rawclient":
            return (
                otbr_restapi_raw_client_cli.main(_forward_with_datadir(sub_argv)) or 0
            )

    # --- process-eve ---
    if args.command == "process-eve":
        return eve_parse.main(_forward_with_datadir(sub_argv)) or 0

    # --- merge-dataset ---
    if args.command in ("merge-dataset", "merge-data"):
        return dataset_merge.main(_forward_with_datadir(sub_argv)) or 0

    # --- web-server ---
    if args.command == "web-server":
        web_argv = ["--host", args.host, "--port", str(args.port)]
        return web_server.main(_forward_with_datadir(web_argv))

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
    args, extras = parser.parse_known_args(argv_list)

    # Apply verbosity / debug flags
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # banner
    logging.info("Thread Network Topology Scanner")
    logging.info("Initiating Thread Network Topology Scan...\n")

    return dispatch(args, extras, parser)


if __name__ == "__main__":
    sys.exit(main())
