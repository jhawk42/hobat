import os
import subprocess
import re
import json
import sys
import time
import logging
import argparse
from typing import Sequence

# Note: The imports below are organized to reflect the different components of the project, such as OTBR CLI parsing, REST API interactions, dataset merging, and the web interface. This structure helps maintain clarity and separation of concerns within the codebase. 
import util_network
import extaddr_device_label_map

import mdns_thread_scopes
import eve_parse

import otbr_cli_network_dataset_info
import otbr_cli_router_table
import otbr_cli_meshdiag_topology
import otbr_cli_meshdiag_childtable
import otbr_cli_meshdiag_routerneighbortable
# TODO_otbr_cli_meshdiag_childip6_add_parsing.py

import otbr_cli_networkdiag_topology

import otbr_restapi_download
import otbr_restapi_client_cli
import otbr_restapi_raw_client_cli

import dataset_merge
import tdash_web_server


## Command hierarchy:
#   tdash.py {common-options} {command} {sub-command} {command-options} {command-arguments}
#
# Common options:
#   --help / -h
#   --verbose / -v
#   --debug / -d
#   --output / -o <file>
#
# Top-level commands:
#   scan        – run an OpenThread CLI scan
#   web         – OTBR REST API commands
#   process     – process raw data files
#   merge       – merge datasets
#   web-server  – start the web dashboard server
#
# scan otbr-cli examples:
#   tdash.py scan otbr-cli network-dataset-info
#   tdash.py scan otbr-cli router-table
#   tdash.py scan otbr-cli meshdiag topology
#   tdash.py scan otbr-cli meshdiag routerneighbortable
#   tdash.py scan otbr-cli meshdiag childtable
#   tdash.py scan otbr-cli meshdiag childip6
#   tdash.py scan otbr-cli meshdiag all
#   tdash.py scan otbr-cli networkdiag topology
#   tdash.py scan otbr-cli all
#
# scan mdns examples:
#   tdash.py scan mdns
#   tdash.py scan mdns all
#   tdash.py scan mdns br
#   tdash.py scan mdns hap
#   tdash.py scan mdns matter
#   tdash.py scan mdns all --browse-timeout 60
#
# web otbr-restapi examples:
#   tdash.py web otbr-restapi download --url http://localhost:8080/api/v1/diagnostics --output td-otbr-restapi-diagnostics.json
#   tdash.py web otbr-restapi client diagnostics list
#   tdash.py web otbr-restapi client diagnostics get --diagnostics-id 123456789
#   tdash.py web otbr-restapi client actions list
#   tdash.py web otbr-restapi client actions get --action-id 123456789
#   tdash.py web otbr-restapi client actions enqueue add-thread-device --pskd 12345678 --eui 123456789 --discerner 123
#   tdash.py web otbr-restapi client actions enqueue get-network-diagnostic --destination 123456789 --types 1,2,3 --timeout 60 --destination-type extaddr
#   tdash.py web otbr-restapi client actions enqueue reset-network-diag-counter --destination 123456789 --types 1,2,3 --timeout 60 --destination-type extaddr
#   tdash.py web otbr-restapi client actions enqueue get-energy-scan --destination 123456789 --channel-mask 0x1FFF800 --count 5 --period
#   tdash.py web otbr-restapi rawclient diagnostics list
#   tdash.py web otbr-restapi rawclient diagnostics get --diagnostics-id 123456789
#   tdash.py web otbr-restapi rawclient actions list
#   tdash.py web otbr-restapi rawclient actions get --action-id 123456789
#   tdash.py web otbr-restapi rawclient actions enqueue add-thread-device --pskd 12345678 --eui 123456789 --discerner 123
#   tdash.py web otbr-restapi rawclient actions enqueue get-network-diagnostic --destination 123456789 --types 1,2,3 --timeout 60 --destination-type
#
# process examples:
#   tdash.py process eve --input eve_data.json --output td-eve-topology.json
#   tdash.py process eve --input 'Eve Thread Network Layout.evethreadlayout' --output td-eve-topology.json
#
# merge examples:
#   tdash.py merge dataset --input1 dataset1.json --input2 dataset2.json --output merged_dataset.json
#
# web-server examples:
#   tdash.py web-server --host localhost --port 8087


def _add_scan_commands(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """ build the 'scan' subcommand tree."""

    # scan otbr-cli
    otbr_cli_p = subparsers.add_parser("otbr-cli", help="Scan otbr-cli commands")
    otbr_cli_sub = otbr_cli_p.add_subparsers(dest="cli_command", required=False)

    otbr_cli_sub.add_parser("network-dataset-info", help="Scan and save network dataset info")
    otbr_cli_sub.add_parser("router-table", help="Scan and save router table")

    meshdiag_p = otbr_cli_sub.add_parser("meshdiag", help="Mesh diagnostic scans")
    meshdiag_sub = meshdiag_p.add_subparsers(dest="meshdiag_command", required=True)
    meshdiag_sub.add_parser("topology",            help="Scan meshdiag topology")
    meshdiag_sub.add_parser("routerneighbortable", help="Scan meshdiag router-neighbour table")
    meshdiag_sub.add_parser("childtable",          help="Scan meshdiag child table")
    meshdiag_sub.add_parser("childip6",            help="Scan meshdiag child IPv6 addresses (TODO)")
    meshdiag_sub.add_parser("all",                 help="Run all meshdiag scans")

    networkdiag_p = otbr_cli_sub.add_parser("networkdiag", help="Network diagnostic scans")
    networkdiag_sub = networkdiag_p.add_subparsers(dest="networkdiag_command", required=True)
    networkdiag_topology_p = networkdiag_sub.add_parser("topology", help="Scan networkdiag topology")
    networkdiag_children_group = networkdiag_topology_p.add_mutually_exclusive_group()
    networkdiag_children_group.add_argument("-c", "--children", dest="expand_children", action="store_true", default=True,
                                            help="Expand and include child nodes in the topology map (default)")
    networkdiag_children_group.add_argument("-cno", "--children-no", dest="expand_children", action="store_false",
                                            help="Do not expand child nodes in the topology map")

    otbr_cli_sub.add_parser("all", help="Run all otbr-cli scans")

    # scan mdns
    mdns_p = subparsers.add_parser("mdns", help="Scan Thread-related mDNS scopes")
    mdns_p.add_argument(
        "mdns_scope",
        nargs="?",
        choices=["all", "br", "hap", "matter"],
        default="all",
        metavar="SCOPE",
        help="Scope filter: all | br | hap | matter  (default: all)",
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
             "Applies when scope is 'all' or 'hap'. Off by default.",
    )
    mdns_p.add_argument(
        "--mattertcpsupported",
        action="store_true",
        default=False,
        help="Include _matter._tcp records where T=1 (TCP supported). "
             "By default those records are excluded.",
    )


def _add_web_commands(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """ build the 'web' subcommand tree."""

    # web otbr-restapi
    restapi_p = subparsers.add_parser("otbr-restapi", help="otbr-restapi sub commands")
    restapi_sub = restapi_p.add_subparsers(dest="restapi_command", required=False)

    # web otbr-restapi download  — remaining args forwarded to otbr_restapi_download.main()
    restapi_sub.add_parser("download", help="Download OTBR REST API endpoints to JSON files")

    # web otbr-restapi client  — remaining args forwarded to otbr_restapi_client_cli.main()
    restapi_sub.add_parser("client", help="Call OTBR REST API client commands (flattened output)")

    # web otbr-restapi rawclient  — remaining args forwarded to otbr_restapi_raw_client_cli.main()
    restapi_sub.add_parser("rawclient", help="Call OTBR REST API client commands (raw envelopes)")


def _add_process_commands(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """ build the 'process' subcommand tree."""

    # Remaining args are captured as extras via parse_known_args and forwarded to eve_parse.main().
    subparsers.add_parser("eve", help="Parse and enhance an Eve Thread layout file")


def _add_merge_commands(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """ build the 'merge' subcommand tree."""

    # Remaining args are captured as extras via parse_known_args and forwarded to dataset_merge.main().
    subparsers.add_parser("dataset", aliases=["data"], help="Merge Thread (otbr-cli, otbr-restapi, eve, mdns) sources into one cache file")


def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""

    parser = argparse.ArgumentParser(
        prog="tdash",
        description="Thread Network Topology Dashboard CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # --- common options ---
    parser._optionals.title = "Options"
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose (INFO) logging")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug logging")
    parser.add_argument("--output", "-o", metavar="FILE", help="Write command output to FILE")

    # --- top-level subcommands ---
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="These are the high level commands",
    )

    # scan -
    scan_p = subparsers.add_parser("scan", help="Scan (otbr-cli or mdns) for thread device details")
    scan_sub = scan_p.add_subparsers(dest="scan_type", required=False)
    _add_scan_commands(scan_sub)

    # web -
    web_p = subparsers.add_parser("web", help="Web call to OTBR REST API for thread device details")
    web_sub = web_p.add_subparsers(dest="web_type", required=False)
    _add_web_commands(web_sub)

    # process
    proc_p = subparsers.add_parser("process", help="Process (eve) raw data files")
    proc_sub = proc_p.add_subparsers(dest="process_type", required=False)
    _add_process_commands(proc_sub)

    # merge
    merge_p = subparsers.add_parser("merge", help="Merge datasets (otbr-cli, otbr-restapi, eve, mdns)")
    merge_sub = merge_p.add_subparsers(dest="merge_type", required=False)
    _add_merge_commands(merge_sub)

    # web-server — remaining args forwarded to tdash_web_server.main()
    ws_p = subparsers.add_parser("web-server", help="Start the web dashboard server")
    ws_p.add_argument("--host", default="localhost", help="Host to bind to (default: localhost)")
    ws_p.add_argument("--port", type=int, default=8087, help="Port to listen on (default: 8087)")

    # --- hand-crafted "Commands usage:" epilog ---
    parser.epilog = """\
Commands usage:
  scan
    usage: tdash scan [-h] {otbr-cli,mdns} ...
    scan otbr-cli       Scan otbr-cli commands
    scan mdns           Scan Thread-related mDNS scopes

  web
    usage: tdash web [-h] {otbr-restapi} ...
    web otbr-restapi    otbr-restapi sub commands

  process
    usage: tdash process [-h] {eve} ...
    process eve         Parse and enhance an Eve Thread layout file

  merge
    usage: tdash merge [-h] {dataset,data} ...
    dataset             Merge Thread (otbr-cli, otbr-restapi, eve, mdns) sources into one cache file

  web-server
    usage: tdash web-server [-h] [--host HOST] [--port PORT]
    options:
        --host HOST  Host to bind to (default: localhost)
        --port PORT  Port to listen on (default: 8087)
"""

    # Expose subparsers so dispatch() can print targeted help
    parser._subcommand_parsers = {  # type: ignore[attr-defined]
        "scan": scan_p,
        "scan:otbr-cli": scan_sub._name_parser_map["otbr-cli"],
        "web": web_p,
        "web:otbr-restapi": web_sub._name_parser_map["otbr-restapi"],
        "process": proc_p,
        "merge": merge_p,
        "web-server": ws_p,
    }

    return parser


def _load_extaddr_map() -> dict:
    """ lazily load the extaddr-to-device-label map for scan commands."""
    EXTADDR_JSON_FILENAME_DEFAULT = "threadstatic-extaddr.json"
    if os.path.exists(EXTADDR_JSON_FILENAME_DEFAULT):
        return extaddr_device_label_map.extaddr_device_label_mapping_load(EXTADDR_JSON_FILENAME_DEFAULT)
    logging.debug(f"Extaddr JSON file '{EXTADDR_JSON_FILENAME_DEFAULT}' not found; using empty mapping.")
    return {}


def dispatch(args: argparse.Namespace, sub_argv: list[str], parser: argparse.ArgumentParser) -> int:
    """Dispatch parsed arguments to the appropriate module entry point.

    sub_argv contains the unrecognised arguments returned by parse_known_args.
    For scan commands it should be empty.  For forwarding commands (web, process,
    merge) it is passed directly to the subordinate module's main().
    """
    _sub = parser._subcommand_parsers  # type: ignore[attr-defined]

    # --- scan ---
    if args.command == "scan":
        if not args.scan_type:
            _sub["scan"].print_help()
            return 0
        if args.scan_type == "otbr-cli":
            cli_cmd = args.cli_command
            if not cli_cmd:
                _sub["scan:otbr-cli"].print_help()
                return 0

            if cli_cmd == "network-dataset-info":
                return otbr_cli_network_dataset_info.main() or 0

            if cli_cmd == "router-table":
                return otbr_cli_router_table.main() or 0

            if cli_cmd == "meshdiag":
                meshdiag_cmd = args.meshdiag_command
                if meshdiag_cmd == "topology":
                    return otbr_cli_meshdiag_topology.main() or 0
                if meshdiag_cmd == "routerneighbortable":
                    return otbr_cli_meshdiag_routerneighbortable.main() or 0
                if meshdiag_cmd == "childtable":
                    return otbr_cli_meshdiag_childtable.main() or 0
                if meshdiag_cmd == "childip6":
                    raise NotImplementedError("scan otbr-cli meshdiag childip6 is not yet implemented")
                if meshdiag_cmd == "all":
                    rc = otbr_cli_meshdiag_topology.main() or 0
                    rc = rc or otbr_cli_meshdiag_routerneighbortable.main() or 0
                    rc = rc or otbr_cli_meshdiag_childtable.main() or 0
                    return rc

            if cli_cmd == "networkdiag":
                if args.networkdiag_command == "topology":
                    expand_children_argv = [] if getattr(args, 'expand_children', True) else ["-cno"]
                    return otbr_cli_networkdiag_topology.main(expand_children_argv) or 0

            if cli_cmd == "all":
                rc = otbr_cli_network_dataset_info.main() or 0
                rc = rc or otbr_cli_router_table.main() or 0
                rc = rc or otbr_cli_meshdiag_topology.main() or 0
                rc = rc or otbr_cli_meshdiag_routerneighbortable.main() or 0
                rc = rc or otbr_cli_meshdiag_childtable.main() or 0
                rc = rc or otbr_cli_networkdiag_topology.main([]) or 0
                return rc

        if args.scan_type == "mdns":
            mdns_argv = (
                [args.mdns_scope]
                + (["--browse-timeout", str(args.browse_timeout)] if args.browse_timeout is not None else [])
                + (["--haptcp"] if args.haptcp else [])
                + (["--mattertcpsupported"] if args.mattertcpsupported else [])
                + sub_argv
            )
            return mdns_thread_scopes.main(mdns_argv) or 0

    # --- web ---
    if args.command == "web":
        if not args.web_type:
            _sub["web"].print_help()
            return 0
        if args.web_type == "otbr-restapi":
            restapi_cmd = args.restapi_command
            if not restapi_cmd:
                _sub["web:otbr-restapi"].print_help()
                return 0

            if restapi_cmd == "download":
                return otbr_restapi_download.main(sub_argv)
            if restapi_cmd == "client":
                return otbr_restapi_client_cli.main(sub_argv)
            if restapi_cmd == "rawclient":
                return otbr_restapi_raw_client_cli.main(sub_argv)

    # --- process ---
    if args.command == "process":
        if not args.process_type:
            _sub["process"].print_help()
            return 0
        if args.process_type == "eve":
            # sub_argv forwarded for future use; eve_parse currently ignores argv
            return eve_parse.main(sub_argv) or 0

    # --- merge ---
    if args.command == "merge":
        if not args.merge_type:
            _sub["merge"].print_help()
            return 0
        if args.merge_type in ("dataset", "data"):
            # sub_argv forwarded for future use; dataset_merge currently ignores argv
            return dataset_merge.main(sub_argv) or 0

    # --- web-server ---
    if args.command == "web-server":
        return tdash_web_server.main(["--host", args.host, "--port", str(args.port)])

    raise ValueError(f"Unhandled command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point with optional command-line arguments."""

    # Default logging configuration; level may be raised to DEBUG after arg parsing
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

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