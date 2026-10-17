from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from typing import Any

from td_const import (
    OTBR_RESTAPI_DEVICES_FETCH_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
    OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
)
from otbr_restapi_diagnostics import (
    _apply_border_router_enrichment,
    _apply_mac_enrichment,
    _apply_time_stats_enrichment,
    _write_checkpoint_best_effort,
    make_progress_fn,
    resolve_child_collection_options,
    resolve_fallback_types,
    resolve_types,
    use_progressive_fallback,
)
from otbr_restapi_mesh_diagnostics import filter_router_device_ids
from otbr_restapi_util import DestinationType, MESH_DIAGNOSTIC_TLVS, OTBRRestApiClient, emit_rest_payload_output
from util_data import create_checkpoint_filename

CLI_TOPOLOGY_TASK_TIMEOUT_FALLBACK = 15
CLI_TOPOLOGY_POLL_INTERVAL_FALLBACK = 2.0
CLI_TOPOLOGY_POLL_TIMEOUT_FALLBACK = None


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
    child_options = resolve_child_collection_options(args)
    progress_enabled = not getattr(args, "no_progress", False)
    logging.info(
        "Topology child policy=%s, MTD fast=%s, MTD detail=%s, child retry=%s",
        child_options["policy"],
        child_options["fast"],
        child_options["detail"],
        child_options["retry_enabled"],
    )
    wall_start = time.monotonic()

    devices: list[Any] = []
    if not getattr(args, "skip_devices", False):
        logging.info("topology step 1: devices fetch ...")
        devices = client.fetch_device_collection(items_only=True)
        path = data_dir / OTBR_RESTAPI_DEVICES_FETCH_FILENAME
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
            diagnostic_roster = devices
        elif do_update:
            diag_devices = client.fetch_device_collection(items_only=True)
            diag_device_ids = [d["id"] for d in diag_devices if isinstance(d, dict) and d.get("id")]
            diagnostic_roster = diag_devices
        else:
            diag_device_ids = device_ids
            diagnostic_roster = devices

        progress_fn = make_progress_fn(len(diag_device_ids), progress_enabled)
        devices_by_id = {
            device.get("id"): device
            for device in diagnostic_roster
            if isinstance(device, dict) and device.get("id")
        }
        selected_devices = [devices_by_id.get(device_id, device_id) for device_id in diag_device_ids]
        diagnostic_path = data_dir / OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME
        checkpoint_path = diagnostic_path.parent / create_checkpoint_filename(
            diagnostic_path.name
        )

        def write_checkpoint(results, stage):
            if raw_arg is not True:
                _apply_border_router_enrichment(results)
            _write_checkpoint_best_effort(
                results,
                checkpoint_path,
                "otbr-restapi topology diagnostics",
                stage,
                raw=raw_arg is True,
            )

        def on_checkpoint(results, _idx, _total, _device_id, _status):
            write_checkpoint(results, "device")

        def on_pass_checkpoint(
            results, _idx, _total, _device_id, pass_name
        ):
            write_checkpoint(results, f"pass:{pass_name}")

        diagnostic_outcome = client.fetch_all_devices_diagnostics(
            selected_devices,
            types=primary_types,
            destination_type=getattr(args, "destination_type", DestinationType.EXTENDED),
            task_timeout=args.task_timeout,
            poll_interval=args.poll_interval,
            poll_timeout=args.poll_timeout,
            clear_diagnostics=not getattr(args, "preserve_diagnostics", False),
            fallback_types=fallback_types,
            progressive_fallback=use_progressive_fallback(args),
            child_collection_policy=child_options["policy"],
            children_fetch_fast=child_options["fast"],
            children_fetch_detail=child_options["detail"],
            child_retry_enabled=child_options["retry_enabled"],
            child_task_timeout=child_options["task_timeout"],
            child_poll_timeout=child_options["poll_timeout"],
            raw=raw_arg,
            on_progress=progress_fn,
            on_checkpoint=on_checkpoint,
            on_pass_checkpoint=on_pass_checkpoint,
        )
        diagnostics = diagnostic_outcome["items"]
        if do_enrich:
            _apply_mac_enrichment(diagnostics)
            _apply_time_stats_enrichment(diagnostics)
            _apply_border_router_enrichment(diagnostics)
        emit_rest_payload_output(diagnostics, diagnostic_path, logging.getLogger(__name__))
        outcome_path = data_dir / OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME
        emit_rest_payload_output(
            diagnostic_outcome,
            outcome_path,
            logging.getLogger(__name__),
        )
        elapsed = time.monotonic() - step_start
        logging.info(
            "topology step 2 done: %d device(s), %d diagnostic(s) in %.1fs → %s",
            len(diag_device_ids),
            len(diagnostics),
            elapsed,
            diagnostic_path,
        )
    else:
        logging.info("topology step 2 skipped (--skip-diagnostics)")

    if not getattr(args, "skip_mesh_diagnostics", False):
        logging.info("topology step 3: mesh-diagnostics fetch-all --routers-only ...")
        step_start = time.monotonic()
        router_ids = filter_router_device_ids(devices, device_ids)
        logging.info("topology step 3: %d router device(s) selected", len(router_ids))
        mesh_progress_fn = make_progress_fn(len(router_ids), progress_enabled)
        mesh_outcome = client.fetch_mesh_diagnostics_all_devices(
            router_ids,
            types=list(MESH_DIAGNOSTIC_TLVS),
            task_timeout=args.task_timeout,
            poll_interval=args.poll_interval,
            poll_timeout=args.poll_timeout,
            clear_diagnostics=False,
            progressive_fallback=not getattr(args, "no_fallback", False),
            on_progress=mesh_progress_fn,
        )
        mesh_results = mesh_outcome["items"]
        path = data_dir / OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME
        emit_rest_payload_output(mesh_results, path, logging.getLogger(__name__))
        mesh_outcome_path = data_dir / OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME
        emit_rest_payload_output(
            mesh_outcome,
            mesh_outcome_path,
            logging.getLogger(__name__),
        )
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
