#!/usr/bin/env python3
"""
td_restapi_topology_driver.py

Python driver that mirrors the topology sweep from td_cli.py otbr-cli:

    td_cli.py otbr-cli networkdiag topology-poll
        → fetch_network_diagnostics_all_devices (RECOMMENDED preset)
          writes: td-otbr-restapi-diagnostics-fetch-all.json

    td_cli.py otbr-cli meshdiag topology
        → fetch_mesh_diagnostics_all_devices (all three otMeshDiag TLVs)
          writes: td-otbr-restapi-mesh-diagnostics-fetch-all.json

The driver calls OTBRRestApiClient directly (no subprocess) and writes both
result files under --datadir using save_json_atomic.

Exit codes:
    0  success
    2  usage / bad arguments
    3  connection error (server unreachable)
    4  HTTP or action error
    5  invalid response from server
    1  unexpected / unhandled error
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from pathlib import Path

from otbr_restapi_util import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DIAG_TLV_CHILDREN,
    DIAG_TLV_CHILD_IPV6_ADDRS,
    DIAG_TLV_ROUTER_NEIGHBORS,
    RECOMMENDED_DIAGNOSTIC_TLVS,
    OTBRActionError,
    OTBRConnectionError,
    OTBRHTTPError,
    OTBRInvalidResponseError,
    OTBRRestApiClient,
    OTBRUsageError,
)
from util_data import resolve_data_dir, save_json_atomic

# ---------------------------------------------------------------------------
# File-name convention (mirrors td-otbr-cli-* pattern)
# ---------------------------------------------------------------------------
DIAG_FILENAME = "td-otbr-restapi-diagnostics-fetch-all.json"
MESH_DIAG_FILENAME = "td-otbr-restapi-mesh-diagnostics-fetch-all.json"

# Exit codes
EXIT_SUCCESS = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_CONNECTION = 3
EXIT_HTTP = 4
EXIT_INVALID_RESPONSE = 5

ALL_MESH_TLVS: list[str] = [
    DIAG_TLV_CHILDREN,
    DIAG_TLV_CHILD_IPV6_ADDRS,
    DIAG_TLV_ROUTER_NEIGHBORS,
]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Topology driver: fetch network diagnostics and mesh diagnostics "
            "from the OTBR REST API and write results to files."
        ),
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"OTBR REST API host (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"OTBR REST API port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--datadir",
        default=None,
        help="Output directory for result files (default: ./data or /data)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    parser.add_argument(
        "--skip-diagnostics",
        action="store_true",
        help="Skip Step A (network diagnostics fetch-all)",
    )
    parser.add_argument(
        "--skip-mesh-diagnostics",
        action="store_true",
        help="Skip Step B (mesh diagnostics fetch-all)",
    )
    return parser


# ---------------------------------------------------------------------------
# Driver logic
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    data_dir: Path = resolve_data_dir(data_dir=args.datadir)

    client = OTBRRestApiClient(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
    )

    logging.info("OTBR endpoint : %s:%s", args.host, args.port)
    logging.info("Output dir    : %s", data_dir)

    wall_start = time.monotonic()

    # -----------------------------------------------------------------------
    # Step A — Network diagnostics (mirrors: networkdiag topology-poll)
    #
    # Refreshes the device list via updateDeviceCollectionTask, then fetches
    # the RECOMMENDED TLV preset for every device (extAddress, rloc16, mode,
    # ipv6Addresses, macCounters, mleCounters, childTable, threadStackVersion,
    # eui64, version, vendorName, vendorModel, vendorSwVersion, connectivity,
    # route, leaderData, channelPages).
    # -----------------------------------------------------------------------
    devices: list = []
    diagnostics: list = []

    if not args.skip_diagnostics:
        logging.info("Step A: diagnostics fetch-all --preset recommended ...")
        step_start = time.monotonic()

        devices, diagnostics = client.fetch_network_diagnostics_all_devices(
            types=list(RECOMMENDED_DIAGNOSTIC_TLVS),
        )

        elapsed = time.monotonic() - step_start
        diag_path = data_dir / DIAG_FILENAME
        save_json_atomic(diagnostics, diag_path)

        logging.info(
            "Step A done: %d device(s) discovered, %d diagnostic(s) returned "
            "in %.1fs → %s",
            len(devices),
            len(diagnostics),
            elapsed,
            diag_path,
        )
    else:
        logging.info("Step A skipped (--skip-diagnostics)")

    # -----------------------------------------------------------------------
    # Step B — Mesh diagnostics (mirrors: meshdiag topology)
    #
    # Fetches the three otMeshDiag TLVs for each known device:
    #   children (TLV 29), childIpv6Addresses (TLV 30), routerNeighbors (TLV 31)
    #
    # NOTE: --routers-only filtering (P2 improvement) is not yet available in
    #       the client.  Once implemented, pass a pre-filtered device_ids list
    #       containing only devices whose rloc16 & 0x1FF == 0 (router mask).
    # -----------------------------------------------------------------------
    if not args.skip_mesh_diagnostics:
        logging.info("Step B: mesh-diagnostics fetch-all (all TLVs) ...")
        step_start = time.monotonic()

        # Re-use the device list from Step A when available; otherwise refresh.
        if devices:
            device_ids = [
                d["id"] for d in devices if isinstance(d, dict) and d.get("id")
            ]
        else:
            logging.info(
                "Step A was skipped — fetching fresh device list for Step B"
            )
            device_ids = _get_device_ids(client)

        mesh_results = client.fetch_mesh_diagnostics_all_devices(
            device_ids,
            types=ALL_MESH_TLVS,
        )

        elapsed = time.monotonic() - step_start
        mesh_path = data_dir / MESH_DIAG_FILENAME
        save_json_atomic(mesh_results, mesh_path)

        logging.info(
            "Step B done: %d mesh diagnostic(s) returned in %.1fs → %s",
            len(mesh_results),
            elapsed,
            mesh_path,
        )
    else:
        logging.info("Step B skipped (--skip-mesh-diagnostics)")

    total_elapsed = time.monotonic() - wall_start
    logging.info("Topology sweep complete in %.1fs", total_elapsed)
    return EXIT_SUCCESS


def _get_device_ids(client: OTBRRestApiClient) -> list[str]:
    """Refresh device collection and return extAddress IDs."""
    devices = client.fetch_device_collection()
    return [d["id"] for d in devices if isinstance(d, dict) and d.get("id")]


# ---------------------------------------------------------------------------
# Error handling helpers
# ---------------------------------------------------------------------------

def _exit_code_for(exc: Exception) -> int:
    if isinstance(exc, OTBRUsageError):
        return EXIT_USAGE
    if isinstance(exc, OTBRConnectionError):
        return EXIT_CONNECTION
    if isinstance(exc, (OTBRHTTPError, OTBRActionError)):
        return EXIT_HTTP
    if isinstance(exc, OTBRInvalidResponseError):
        return EXIT_INVALID_RESPONSE
    return EXIT_UNEXPECTED


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        return run(args)
    except (OTBRConnectionError, OTBRHTTPError, OTBRActionError,
            OTBRInvalidResponseError, OTBRUsageError) as exc:
        logging.error("%s: %s", type(exc).__name__, exc)
        return _exit_code_for(exc)
    except Exception as exc:
        logging.exception("Unexpected error: %s", exc)
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    sys.exit(main())
