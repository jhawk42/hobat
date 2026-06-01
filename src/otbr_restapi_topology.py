from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from typing import Any

from otbr_restapi_diagnostics import (
    _apply_mac_enrichment,
    fetch_all_with_fallback,
    make_progress_fn,
    resolve_fallback_types,
    resolve_types,
)
from otbr_restapi_mesh_diagnostics import filter_router_device_ids
from otbr_restapi_util import DestinationType, MESH_DIAGNOSTIC_TLVS, OTBRRestApiClient, emit_rest_payload_output

CLI_TOPOLOGY_TASK_TIMEOUT_FALLBACK = 8
CLI_TOPOLOGY_POLL_INTERVAL_FALLBACK = 2.0
CLI_TOPOLOGY_POLL_TIMEOUT_FALLBACK = 8.0


def dispatch_topology(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
) -> None:
    data_dir: Path = args.td_data_dir
    do_update = not getattr(args, "no_update_devices", False)
    do_enrich = not getattr(args, "no_enrich_mac_counters", False)
    fallback_types = resolve_fallback_types(args)
    primary_types = resolve_types(args)
    progress_enabled = not getattr(args, "no_progress", False)
    wall_start = time.monotonic()

    devices: list[Any] = []
    if not getattr(args, "skip_devices", False):
        logging.info("topology step 1: devices fetch ...")
        devices = client.fetch_device_collection()
        path = data_dir / "td-otbr-restapi-devices-fetch.json"
        emit_rest_payload_output(devices, path, logging.getLogger(__name__))
        logging.info("topology step 1 done: %d device(s) → %s", len(devices), path)
    else:
        logging.info("topology step 1 skipped (--skip-devices); fetching device list quietly")
        devices = client.list_devices(raw=False)

    device_ids = [d["id"] for d in devices if isinstance(d, dict) and d.get("id")]

    if not getattr(args, "skip_diagnostics", False):
        logging.info("topology step 2: diagnostics fetch-all --preset %s ...", args.preset)
        step_start = time.monotonic()
        if do_update and not getattr(args, "skip_devices", False):
            diag_device_ids = device_ids
        elif do_update:
            diag_devices = client.fetch_device_collection()
            diag_device_ids = [d["id"] for d in diag_devices if isinstance(d, dict) and d.get("id")]
        else:
            diag_device_ids = device_ids

        progress_fn = make_progress_fn(len(diag_device_ids), progress_enabled)
        diagnostics = fetch_all_with_fallback(
            client,
            diag_device_ids,
            primary_types,
            fallback_types,
            destination_type=args.destination_type if hasattr(args, "destination-type") else DestinationType.EXTENDED,
            task_timeout=args.task_timeout if hasattr(args, "task-timeout") else CLI_TOPOLOGY_TASK_TIMEOUT_FALLBACK,
            poll_interval=args.poll_interval if hasattr(args, "poll-interval") else CLI_TOPOLOGY_POLL_INTERVAL_FALLBACK,
            poll_timeout=args.poll_timeout if hasattr(args, "poll-timeout") else CLI_TOPOLOGY_POLL_TIMEOUT_FALLBACK,
            raw=raw_arg,
            on_progress=progress_fn,
        )
        if do_enrich:
            _apply_mac_enrichment(diagnostics)
        path = data_dir / "td-otbr-restapi-diagnostics-fetch-all.json"
        emit_rest_payload_output(diagnostics, path, logging.getLogger(__name__))
        elapsed = time.monotonic() - step_start
        logging.info(
            "topology step 2 done: %d device(s), %d diagnostic(s) in %.1fs → %s",
            len(diag_device_ids),
            len(diagnostics),
            elapsed,
            path,
        )
    else:
        logging.info("topology step 2 skipped (--skip-diagnostics)")

    if not getattr(args, "skip_mesh_diagnostics", False):
        logging.info("topology step 3: mesh-diagnostics fetch-all --routers-only ...")
        step_start = time.monotonic()
        router_ids = filter_router_device_ids(devices, device_ids)
        logging.info("topology step 3: %d router device(s) selected", len(router_ids))
        mesh_progress_fn = make_progress_fn(len(router_ids), progress_enabled)
        mesh_results = client.fetch_mesh_diagnostics_all_devices(
            router_ids,
            types=list(MESH_DIAGNOSTIC_TLVS),
            on_progress=mesh_progress_fn,
        )
        path = data_dir / "td-otbr-restapi-mesh-diagnostics-fetch-all.json"
        emit_rest_payload_output(mesh_results, path, logging.getLogger(__name__))
        elapsed = time.monotonic() - step_start
        logging.info(
            "topology step 3 done: %d mesh diagnostic(s) in %.1fs → %s",
            len(mesh_results),
            elapsed,
            path,
        )
    else:
        logging.info("topology step 3 skipped (--skip-mesh-diagnostics)")

    total_elapsed = time.monotonic() - wall_start
    logging.info("Topology sweep complete in %.1fs", total_elapsed)
    return None
