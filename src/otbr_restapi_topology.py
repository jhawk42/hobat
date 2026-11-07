from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import logging
import time
from pathlib import Path
from typing import Any, Iterator

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
    _has_unresolved_iid_skip,
    _log_diagnostic_facts,
    _write_event,
    _write_guard_affected_outcome,
    _write_checkpoint_best_effort,
    make_batch_progress_fns,
    resolve_child_collection_options,
    resolve_fallback_types,
    resolve_types,
    use_progressive_fallback,
)
from otbr_restapi_mesh_diagnostics import filter_router_device_ids
from otbr_restapi_util import (
    DestinationType, MESH_DIAGNOSTIC_TLVS, OTBRRestApiClient,
    RLOC_EXPANSION_PROGRESS_PREFIX, emit_rest_payload_output,
)
from td_logging import log_event
from otbr_restapi_outcomes import mesh_outcome_views
from td_collection_outcomes import log_outcome_summary
from util_data import create_checkpoint_filename

CLI_TOPOLOGY_TASK_TIMEOUT_FALLBACK = 15
CLI_TOPOLOGY_POLL_INTERVAL_FALLBACK = 2.0
CLI_TOPOLOGY_POLL_TIMEOUT_FALLBACK = None


def _write_topology_output(
    payload: Any, path: Path, stage: str, records: int, *,
    guarded_outcome: bool = False, raw: bool = False,
) -> None:
    written: bool | None = None
    returned = False

    def on_write(value: bool) -> None:
        nonlocal written
        written = value

    try:
        if guarded_outcome:
            _write_guard_affected_outcome(
                payload, path, raw=raw,
                command_name="otbr-restapi topology diagnostics",
            )
            written = True
        else:
            emit_rest_payload_output(
                payload, path, logging.getLogger(__name__), on_write=on_write,
            )
        if written is None:
            raise RuntimeError("Topology output writer did not report its disposition")
        returned = True
    finally:
        _write_event(
            "topology", stage, path, records,
            ("saved" if written else "retained_previous") if returned else "failed",
        )


@contextmanager
def _topology_step(
    stage: str, current: int, counts: dict[str, int],
) -> Iterator[None]:
    started = time.monotonic()
    returned = False
    counts["executed"] += 1
    log_event("step_start", source="otbr-restapi", command="topology",
              stage=stage, current=current, total=3)
    try:
        yield
        returned = True
    finally:
        if not returned:
            counts["failed"] += 1
        log_event(
            "step_end", source="otbr-restapi", command="topology", stage=stage,
            current=current, total=3, state="returned" if returned else "raised",
            elapsed_s=round(time.monotonic() - started, 3),
        )


def dispatch_topology(
    client: OTBRRestApiClient, args: argparse.Namespace, raw_arg: object,
) -> None:
    started = time.monotonic()
    counts = {"executed": 0, "skipped": 0, "failed": 0}
    returned = False
    try:
        with ExitStack() as steps:
            _dispatch_topology(client, args, raw_arg, counts, steps)
        returned = True
    finally:
        log_event(
            "workflow_summary", source="otbr-restapi", command="topology",
            stage="workflow", **counts, state="returned" if returned else "raised",
            elapsed_s=round(time.monotonic() - started, 3),
        )


def _dispatch_topology(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
    counts: dict[str, int],
    steps: ExitStack,
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
        with _topology_step("devices.fetch", 1, counts):
            devices = client.fetch_device_collection(items_only=True)
            path = data_dir / OTBR_RESTAPI_DEVICES_FETCH_FILENAME
            _write_topology_output(devices, path, "devices.final", len(devices))
        logging.info("topology step 1 done: %d device(s) → %s", len(devices), path)
    else:
        logging.info("topology step 1 skipped (--skip-devices); fetching device list quietly")
        counts["skipped"] += 1
        log_event("step_skip", source="otbr-restapi", command="topology",
                  stage="devices.fetch", reason="skip_devices", current=1, total=3)
        started = time.monotonic()
        returned = False
        try:
            devices = client.list_devices(raw=False)
            returned = True
        finally:
            log_event(
                "operation_end", source="otbr-restapi", command="topology",
                stage="devices.list", state="returned" if returned else "raised",
                elapsed_s=round(time.monotonic() - started, 3),
            )

    device_ids = [d["id"] for d in devices if isinstance(d, dict) and d.get("id")]

    if not getattr(args, "skip_diagnostics", False):
        steps.enter_context(_topology_step("diagnostics", 2, counts))
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

        progress_fn, rejected_progress_fn = make_batch_progress_fns(
            len(diag_device_ids), progress_enabled, command="topology",
            stage="diagnostics.initial", expansion_stage="diagnostics.expansion",
        )
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
                "topology",
                f"diagnostics.{stage}",
                raw=raw_arg is True,
            )

        def on_checkpoint(results, _idx, _total, device_id, _status):
            expanded = isinstance(device_id, str) and device_id.startswith(RLOC_EXPANSION_PROGRESS_PREFIX)
            write_checkpoint(results, "expansion" if expanded else "device")

        def on_pass_checkpoint(
            results, _idx, _total, device_id, pass_name
        ):
            expanded = isinstance(device_id, str) and device_id.startswith(RLOC_EXPANSION_PROGRESS_PREFIX)
            write_checkpoint(results, f"{'expansion.' if expanded else ''}pass:{pass_name}")

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
            on_rejected_progress=rejected_progress_fn,
            on_checkpoint=on_checkpoint,
            on_pass_checkpoint=on_pass_checkpoint,
        )
        _log_diagnostic_facts(
            diagnostic_outcome, command="topology", stage_prefix="diagnostics.",
        )
        diagnostics = diagnostic_outcome["items"]
        if do_enrich:
            _apply_mac_enrichment(diagnostics)
            _apply_time_stats_enrichment(diagnostics)
            _apply_border_router_enrichment(diagnostics)
        outcome_path = data_dir / OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME
        guard_affected = _has_unresolved_iid_skip(diagnostic_outcome)
        unresolved_iid_skips = sum(
            isinstance(result, dict)
            and result.get("skipReasonCode") == "unresolved_mesh_local_iid"
            and result.get("status") != "completed"
            for result in diagnostic_outcome.get("deviceResults", [])
        )
        preserve_prior_dataset = guard_affected and not diagnostics
        if preserve_prior_dataset:
            logging.warning(
                "Topology diagnostics produced no new records after %d "
                "unresolved-IID skip(s); retaining the prior dataset at %s",
                unresolved_iid_skips,
                diagnostic_path,
            )
            _write_event("topology", "diagnostics.final", diagnostic_path,
                         len(diagnostics), "retained_previous")
        else:
            _write_topology_output(
                diagnostics, diagnostic_path, "diagnostics.final", len(diagnostics),
            )
        _write_topology_output(
            diagnostic_outcome, outcome_path, "diagnostics.outcome",
            len(diagnostics), guarded_outcome=guard_affected, raw=raw_arg is True,
        )
        elapsed = time.monotonic() - step_start
        if guard_affected:
            logging.info(
                "topology step 2 done: %d device(s), %d diagnostic(s), "
                "%d unresolved-IID skip(s)%s in %.1fs → %s",
                len(diag_device_ids),
                len(diagnostics),
                unresolved_iid_skips,
                ", no new diagnostic data" if preserve_prior_dataset else "",
                elapsed,
                diagnostic_path,
            )
        else:
            logging.info(
                "topology step 2 done: %d device(s), %d diagnostic(s) in %.1fs → %s",
                len(diag_device_ids),
                len(diagnostics),
                elapsed,
                diagnostic_path,
            )
        steps.close()
    else:
        logging.info("topology step 2 skipped (--skip-diagnostics)")
        counts["skipped"] += 1
        log_event("step_skip", source="otbr-restapi", command="topology",
                  stage="diagnostics", reason="skip_diagnostics", current=2, total=3)

    if not getattr(args, "skip_mesh_diagnostics", False):
        steps.enter_context(_topology_step("mesh", 3, counts))
        logging.info("topology step 3: mesh-diagnostics fetch-all --routers-only ...")
        step_start = time.monotonic()
        router_ids = filter_router_device_ids(devices, device_ids)
        logging.info("topology step 3: %d router device(s) selected", len(router_ids))
        mesh_progress_fn, mesh_rejected_fn = make_batch_progress_fns(
            len(router_ids), progress_enabled, command="topology", stage="mesh.initial",
        )
        mesh_outcome = client.fetch_mesh_diagnostics_all_devices(
            router_ids,
            types=list(MESH_DIAGNOSTIC_TLVS),
            task_timeout=args.task_timeout,
            poll_interval=args.poll_interval,
            poll_timeout=args.poll_timeout,
            clear_diagnostics=False,
            progressive_fallback=not getattr(args, "no_fallback", False),
            on_progress=mesh_progress_fn,
            on_rejected_progress=mesh_rejected_fn,
        )
        mesh_results = mesh_outcome["items"]
        views = mesh_outcome_views(
            mesh_outcome, command="topology", stage="mesh.initial",
        )
        for view in views:
            log_event(
                "target_outcome", source=view.source, command=view.command,
                stage=view.stage, **view.event_fields(),
            )
        log_outcome_summary(
            views if isinstance(mesh_outcome.get("deviceResults"), list) else None,
            source="otbr-restapi", command="topology", stage="mesh.initial",
        )
        path = data_dir / OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME
        log_event(
            "collector_summary", source="otbr-restapi", command="topology",
            stage="mesh.initial", records=len(mesh_results),
            input=mesh_outcome.get("inputCount", "unavailable"),
            normalized=mesh_outcome.get("queriedCount", "unavailable"),
            terminal_results=(
                len(mesh_outcome["deviceResults"])
                if isinstance(mesh_outcome.get("deviceResults"), list) else "unavailable"
            ),
        )
        _write_topology_output(mesh_results, path, "mesh.final", len(mesh_results))
        mesh_outcome_path = data_dir / OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME
        _write_topology_output(
            mesh_outcome, mesh_outcome_path, "mesh.outcome", len(mesh_results),
        )
        log_event("coverage", source="otbr-restapi", command="topology",
                  stage="mesh.qualification", availability="unavailable",
                  reason="not_requested")
        log_outcome_summary(
            None, source="otbr-restapi", command="topology", stage="mesh.qualification",
        )
        elapsed = time.monotonic() - step_start
        logging.info(
            "topology step 3 done: %d mesh diagnostic(s) in %.1fs → %s",
            len(mesh_results),
            elapsed,
            path,
        )
        steps.close()
    else:
        logging.info("topology step 3 skipped (--skip-mesh-diagnostics)")
        counts["skipped"] += 1
        log_event("step_skip", source="otbr-restapi", command="topology",
                  stage="mesh", reason="skip_mesh_diagnostics", current=3, total=3)

    total_elapsed = time.monotonic() - wall_start
    logging.info("Topology sweep complete in %.1fs", total_elapsed)
    return None
