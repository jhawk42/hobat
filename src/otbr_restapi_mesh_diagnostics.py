from __future__ import annotations

import argparse
import json
import logging
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from otbr_restapi_diagnostics import (
    make_progress_fn, make_batch_progress_fns, _safe_legacy_field, _write_event,
)
from td_logging import log_event
from otbr_restapi_outcomes import mesh_outcome_views, responsiveness_outcome_views
from td_collection_outcomes import log_outcome_summary
from td_restapi_mesh_evidence import (
    ORIGIN, POLICY, RESPONSIVENESS_VERSION, classify_mesh_probe_eligibility,
    sanitize_context, scope_identity, select_child_witness,
    select_router_identity, validate_diagnostic_response,
)
from td_json_key_normalizer import convert_keys_to_camel_case
from util_data import (
    CollectionWriteOutcome,
    create_checkpoint_filename,
    save_checkpoint_json,
    save_json_atomic,
)
from otbr_restapi_util import (
    DIAG_TLV_CHILDREN,
    DIAG_TLV_CHILD_IPV6_ADDRS,
    DIAG_TLV_ROUTER_NEIGHBORS,
    DestinationType,
    MESH_DIAGNOSTIC_TLVS,
    OTBRRestApiClient,
    OTBRClientError,
    OTBRUsageError,
    collection_outcome_path,
    emit_rest_command_output,
    emit_rest_observed_output,
    write_rest_collection_outcome,
)

CLI_MESH_TASK_TIMEOUT_DEFAULT = 15
ROUTER_RLOC16_MASK = 0x03FF
ROUTER_RLOC16_VALUE = 0
_COMMAND = "mesh-diagnostics fetch-all"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _observe_scope(client: OTBRRestApiClient) -> dict:
    requested = _utc_now()
    try:
        observed = scope_identity(client.get_active_dataset(raw=False))
        reason = None if observed else "scope-unavailable"
    except OTBRClientError:
        observed, reason = None, "scope-unavailable"
    return {"extPanId": observed, "requestedAt": requested, "receivedAt": _utc_now(), "reasonCode": reason}


def _capture_child_witness(output_path: object, scope: dict) -> tuple[list, dict, list]:
    if output_path is None or scope.get("extPanId") is None:
        return [], {}, []
    from td_const import OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME
    from td_restapi_diagnostic_recovery import diagnostic_items, qualified_router_tables
    from td_unified_dataset import UnifiedDatasetError, read_rest_diagnostic_recovery

    try:
        effective, captured = read_rest_diagnostic_recovery(
            Path(output_path).parent, expected_network="extpan:" + scope["extPanId"],
        )
        final = next(item for item in captured if item.filename == OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME)
        rows = diagnostic_items(json.loads(final.content)) if final.content else []
        bindings = {item.filename: item.digest for item in captured}
        if effective is None or any(value is None for value in bindings.values()):
            return [], {}, captured
        return qualified_router_tables(effective, rows), bindings, captured
    except (UnifiedDatasetError, OSError, ValueError, TypeError):
        return [], {}, []


def _attach_responsiveness(client, outcome, devices, scope_before, tables, bindings, captured, output_path, destination_type, *, progress_enabled=False):
    from td_restapi_mesh_evidence import witness_identifiers
    evidence = {
        "contractVersion": RESPONSIVENESS_VERSION, "enabled": True, "origin": ORIGIN,
        "policy": deepcopy(POLICY), "scopeBefore": scope_before,
        "witnessBindings": bindings, "targets": [],
    }
    used_ids = [table.get("diagnosticId") for table in tables]
    used_ids.extend(witness_identifiers([json.loads(item.content) for item in captured if item.content is not None]))
    for record in outcome.get("deviceResults", []):
        used_ids.extend(record.get("diagnosticIds", []))
        used_ids.extend(error.get("actionId") for error in record.get("attemptErrors", []))
    candidates = [
        record for record in outcome.get("deviceResults", [])
        if isinstance(record, dict) and record.get("status") != "completed"
    ]
    progress = make_progress_fn(len(candidates), progress_enabled,
                                command=_COMMAND, stage="responsiveness",
                                expansion_stage=None)
    for index, record in enumerate(candidates, 1):
        target_clock = time.monotonic()
        started = _utc_now()
        identity, identity_reason = select_router_identity(record["deviceId"], devices)
        reason = classify_mesh_probe_eligibility(record, destination_type) or identity_reason
        witness = None
        if reason is None and scope_before.get("extPanId") is None:
            reason = "scope-unavailable"
        if reason is None:
            witness, reason = select_child_witness(identity["extAddress"], tables, started)
        target = {
            "identity": identity or {"deviceId": record["deviceId"]}, "witness": witness,
            "check": {"status": "not-attempted", "reasonCode": reason},
        }
        evidence["targets"].append(target)
        if reason is not None:
            if progress:
                progress(index, len(candidates), record["deviceId"],
                         time.monotonic() - target_clock, "not-attempted")
            continue
        request = {"destination": record["deviceId"], "destinationType": "extended", "types": list(POLICY["types"]), "timeout": 15}
        check = {"status": "response", "request": request, "startedAt": started}
        target["check"] = check
        clock = time.monotonic()
        try:
            context = client.fetch_device_diagnostics(
                record["deviceId"], types=list(POLICY["types"]), destination_type="extended",
                task_timeout=15, poll_interval=2.0, poll_timeout=20.0,
                return_context=True, raw=False,
            )
            check["action"], check["diagnostic"] = sanitize_context(context)
        except OTBRClientError as exc:
            check.update({"status": "no-response", "reasonCode": "diagnostic-no-response", "error": {
                "type": type(exc).__name__, "actionId": getattr(exc, "action_id", None),
                "actionStatus": getattr(exc, "status", None),
            }})
        check.update({"completedAt": _utc_now(), "elapsedSeconds": time.monotonic() - clock})
        if check["status"] == "response":
            reason = validate_diagnostic_response(check, identity, used_ids)
            check["reasonCode"] = reason
            if reason:
                check["status"] = "invalid-response"
            used_ids.extend([check["action"].get("id"), check["diagnostic"].get("id")])
        if progress:
            progress(index, len(candidates), record["deviceId"],
                     time.monotonic() - target_clock, check["status"])
    evidence["scopeAfter"] = _observe_scope(client)
    if evidence["scopeAfter"].get("extPanId") != scope_before.get("extPanId"):
        reason = "scope-changed" if evidence["scopeAfter"].get("extPanId") and scope_before.get("extPanId") else "scope-unavailable"
        evidence["scopeAfter"]["reasonCode"] = reason
        for target in evidence["targets"]:
            target["check"]["reasonCode"] = reason
    if captured and output_path is not None:
        from td_unified_dataset import UnifiedDatasetError, _recheck
        try:
            _recheck(Path(output_path).parent, captured)
        except (UnifiedDatasetError, OSError):
            evidence["witnessBindings"] = {}
            for target in evidence["targets"]:
                target["check"]["reasonCode"] = "witness-binding-mismatch"
    outcome["meshResponsiveness"] = evidence
    log_event(
        "collector_summary", source="otbr-restapi", command=_COMMAND,
        stage="responsiveness", targets=len(candidates),
        checks=sum(target["check"]["status"] != "not-attempted" for target in evidence["targets"]),
    )
    views = responsiveness_outcome_views(outcome)
    for view in views:
        log_event(
            "target_outcome", source=view.source, command=view.command,
            stage=view.stage, **view.event_fields(),
        )
    log_outcome_summary(
        views, source="otbr-restapi", command=_COMMAND, stage="responsiveness",
    )


def _write_checkpoint_best_effort(payload: Any, checkpoint_path: Path) -> None:
    try:
        written = save_checkpoint_json(
            convert_keys_to_camel_case(payload),
            checkpoint_path,
            CollectionWriteOutcome.partial(has_usable_data=bool(payload)),
            writer=save_json_atomic,
        )
        if written:
            logging.info(
                "event=checkpoint_write command=otbr-restapi mesh-diagnostics fetch-all checkpoint_file=%s records=%d stage=device",
                _safe_legacy_field(checkpoint_path),
                len(payload) if isinstance(payload, list) else 0,
            )
        log_event("checkpoint", source="otbr-restapi", command=_COMMAND, stage="device",
                  output=str(checkpoint_path),
                  records=len(payload) if isinstance(payload, list) else 0,
                  disposition="written" if written else "skipped_unusable")
    except (OSError, ValueError, TypeError) as exc:
        log_event("checkpoint", source="otbr-restapi", command=_COMMAND, stage="device",
                  output=str(checkpoint_path),
                  records=len(payload) if isinstance(payload, list) else 0,
                  disposition="failed", error_type=type(exc).__name__)
        logging.warning(
            "event=checkpoint_write_failed command=otbr-restapi mesh-diagnostics fetch-all checkpoint_file=%s error_type=%s error=%s action=continue_best_effort",
            _safe_legacy_field(checkpoint_path),
            type(exc).__name__,
            _safe_legacy_field(exc),
        )


def _log_qualification(outcome, output_path, outcome_path, tables, bindings, captured):
    qualification = None
    from td_restapi_mesh_evidence import qualify_rest_mesh_outcome, witness_identifiers
    from td_unified_dataset import UnifiedDatasetError, _recheck
    from util_data import read_network_scope

    fields = {"availability": "unavailable"}
    try:
        _recheck(Path(output_path).parent, captured)
        final_scope, _ = read_network_scope(output_path)
        outcome_scope, _ = read_network_scope(outcome_path)
        network = scope_identity(final_scope)
        if network is not None and network == scope_identity(outcome_scope):
            qualification = qualify_rest_mesh_outcome(
                outcome, outcome["items"], tables, bindings, network,
                witness_identifiers([json.loads(item.content) for item in captured if item.content is not None]),
            )
            counts = qualification["counts"]
            fields = {
                "availability": "available", "answered": counts["answered"],
                "not_provided": counts["notProvided"], "unanswered": counts["unanswered"],
                "guard_passed": counts["answered"] > 0,
                "complete": qualification["complete"],
            }
    except (UnifiedDatasetError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        qualification = None
        fields = {
            "availability": "unavailable", "reason": "qualification_error",
            "error_type": type(exc).__name__,
        }
    log_event("coverage", source="otbr-restapi", command=_COMMAND,
              stage="qualification", **fields)
    views = mesh_outcome_views(
        outcome, stage="qualification", qualification=qualification,
    )
    for view in views:
        log_event(
            "target_outcome", source=view.source, command=view.command,
            stage=view.stage, **view.event_fields(),
        )
    log_outcome_summary(
        views if qualification is not None else None,
        source="otbr-restapi", command=_COMMAND, stage="qualification",
    )


def filter_router_device_ids(devices: list[Any], device_ids: list[str]) -> list[str]:
    devices_by_id: dict[str, dict[str, Any]] = {}
    for device in devices:
        if not isinstance(device, dict):
            continue
        device_id = device.get("id")
        if not isinstance(device_id, str) or not device_id:
            continue
        devices_by_id[device_id] = device

    result: list[str] = []
    for device_id in device_ids:
        device = devices_by_id.get(device_id)
        role_value = device.get("role") if device is not None else None
        if role_value is not None:
            if not isinstance(role_value, str):
                logging.warning(
                    "Skipping device %s for --routers-only: unrecognized role %r",
                    device_id,
                    role_value,
                )
                continue
            role = role_value.strip().lower()
            if role == "router":
                result.append(device_id)
                continue
            if role == "child":
                continue
            if role:
                logging.warning(
                    "Skipping device %s for --routers-only: unrecognized role %r",
                    device_id,
                    role_value,
                )
                continue

        rloc16_raw = device.get("rloc16") if device is not None else None
        try:
            if rloc16_raw is None:
                raise ValueError("RLOC16 is missing")
            rloc16 = (
                int(rloc16_raw, 16)
                if isinstance(rloc16_raw, str)
                else int(rloc16_raw)
            )
        except (ValueError, TypeError, OverflowError):
            logging.warning(
                "Skipping device %s for --routers-only: role and valid RLOC16 unavailable",
                device_id,
            )
            continue

        if (rloc16 & ROUTER_RLOC16_MASK) == ROUTER_RLOC16_VALUE:
            result.append(device_id)
    return result


def parse_mesh_diag_types(types: list[str]) -> list[str]:
    invalid = [value for value in types if value not in MESH_DIAGNOSTIC_TLVS]
    if invalid:
        raise OTBRUsageError(
            f"Invalid mesh-diagnostic TLV(s): {invalid!r}. Allowed: {sorted(MESH_DIAGNOSTIC_TLVS)!r}"
        )
    if not types:
        raise OTBRUsageError("At least one mesh-diagnostic TLV must be specified")
    return types


def dispatch_mesh_diagnostics(
    client: OTBRRestApiClient, args: argparse.Namespace, raw_arg: object,
) -> Any:
    if args.mesh_diag_command == "fetch-all":
        return _dispatch_mesh_diagnostics(client, args, raw_arg)
    started = time.monotonic()
    returned = False
    try:
        result = _dispatch_mesh_diagnostics(client, args, raw_arg)
        returned = True
        return result
    finally:
        log_event(
            "operation_end", source="otbr-restapi",
            command=f"mesh-diagnostics {args.mesh_diag_command}", stage="operation",
            state="returned" if returned else "raised",
            elapsed_s=time.monotonic() - started,
        )


def _dispatch_mesh_diagnostics(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
) -> Any:
    cmd = args.mesh_diag_command
    poll_timeout = args.poll_timeout
    poll_interval = args.poll_interval
    dest_type = args.destination_type
    task_timeout = args.task_timeout
    output_path = getattr(args, "resolved_output_path", None)

    def finish(result: Any) -> Any:
        return emit_rest_observed_output(
            result, output_path, command=f"mesh-diagnostics {cmd}", stage="final",
            single=True, logger=logging.getLogger(__name__),
            emitter=emit_rest_command_output,
        )

    if cmd == "children":
        return finish(client.fetch_mesh_diagnostics(
            args.device_id,
            types=[DIAG_TLV_CHILDREN],
            destination_type=dest_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raw=raw_arg,
        ))
    if cmd == "child-ipv6":
        return finish(client.fetch_mesh_diagnostics(
            args.device_id,
            types=[DIAG_TLV_CHILD_IPV6_ADDRS],
            destination_type=dest_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raw=raw_arg,
        ))
    if cmd == "router-neighbors":
        return finish(client.fetch_mesh_diagnostics(
            args.device_id,
            types=[DIAG_TLV_ROUTER_NEIGHBORS],
            destination_type=dest_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raw=raw_arg,
        ))
    if cmd == "fetch":
        types = parse_mesh_diag_types(args.types or list(MESH_DIAGNOSTIC_TLVS))
        return finish(client.fetch_mesh_diagnostics(
            args.device_id,
            types=types,
            destination_type=dest_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raw=raw_arg,
        ))
    if cmd == "fetch-all":
        types = parse_mesh_diag_types(args.types or list(MESH_DIAGNOSTIC_TLVS))
        do_update = not getattr(args, "no_update_devices", False)
        routers_only = getattr(args, "routers_only", True)
        if getattr(args, "diagnostic_response_fallback", False) and not routers_only:
            raise OTBRUsageError("--diagnostic-response-fallback requires --routers-only")
        response_fallback = getattr(args, "diagnostic_response_fallback", False)
        scope_before, tables, bindings, captured = None, [], {}, []
        if response_fallback:
            scope_before = _observe_scope(client)
            tables, bindings, captured = _capture_child_witness(output_path, scope_before)

        if do_update:
            devices = client.fetch_device_collection(items_only=True)
        else:
            devices = client.list_devices(raw=False)

        device_ids = getattr(args, "device_ids", None) or [
            d["id"] for d in devices if isinstance(d, dict) and d.get("id")
        ]
        if routers_only:
            device_ids = filter_router_device_ids(devices, device_ids)
            logging.info(
                "--routers-only: %d router device(s) selected from device list",
                len(device_ids),
            )

        checkpoint_path = None
        if output_path:
            output_file = Path(output_path)
            checkpoint_path = output_file.parent / create_checkpoint_filename(
                output_file.name
            )

        def _on_checkpoint(results, _idx, _total, _device_id, _status):
            if checkpoint_path is None:
                return
            _write_checkpoint_best_effort(results, checkpoint_path)

        progress_fn, rejected_progress_fn = make_batch_progress_fns(
            len(device_ids), not getattr(args, "no_progress", False),
            command=_COMMAND, stage="router" if routers_only else "device",
        )
        outcome = client.fetch_mesh_diagnostics_all_devices(
            device_ids,
            types=types,
            destination_type=dest_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            clear_diagnostics=not getattr(args, "preserve_diagnostics", False),
            items_only=False,
            progressive_fallback=not getattr(args, "no_fallback", False),
            on_progress=progress_fn,
            on_rejected_progress=rejected_progress_fn,
            on_checkpoint=_on_checkpoint,
            raw=raw_arg,
        )
        results = outcome.get("deviceResults")
        log_event(
            "collector_summary", source="otbr-restapi", command=_COMMAND,
            stage="router" if routers_only else "device",
            input=outcome.get("inputCount", "unavailable"),
            normalized=outcome.get("queriedCount", "unavailable"),
            attempted=(
                sum(isinstance(record, dict) and record.get("attempts", 0) > 0 for record in results)
                if isinstance(results, list) and all(
                    isinstance(record, dict) and "attempts" in record
                    for record in results
                ) else "unavailable"
            ),
            terminal_results=len(results) if isinstance(results, list) else "unavailable",
        )
        for record in results if isinstance(results, list) else []:
            if isinstance(record, dict):
                log_event(
                    "target_result", source="otbr-restapi", command=_COMMAND,
                    stage="router" if routers_only else "device",
                    target=record.get("deviceId"), status=record.get("status", "unavailable"),
                )
        if response_fallback:
            _attach_responsiveness(
                client, outcome, devices, scope_before, tables, bindings, captured,
                output_path, dest_type,
                progress_enabled=not getattr(args, "no_progress", False),
            )
        views = mesh_outcome_views(
            outcome, stage="router" if routers_only else "device",
        )
        for view in views:
            log_event(
                "target_outcome", source=view.source, command=view.command,
                stage=view.stage, **view.event_fields(),
            )
        log_outcome_summary(
            views if isinstance(results, list) else None,
            source="otbr-restapi", command=_COMMAND,
            stage="router" if routers_only else "device",
        )
        records = len(outcome["items"])
        outcome_records = len(results) if isinstance(results, list) else 0
        if output_path is not None:
            outcome_path = collection_outcome_path(output_path)
            try:
                write_rest_collection_outcome(
                    outcome, outcome_path,
                    raw=raw_arg is True, command_name="otbr-restapi mesh-diagnostics fetch-all",
                )
            except Exception as exc:
                _write_event(_COMMAND, "outcome", outcome_path, outcome_records, "failed",
                             error_type=type(exc).__name__)
                raise
            _write_event(_COMMAND, "outcome", outcome_path, outcome_records, "saved")
        else:
            _write_event(_COMMAND, "outcome", None, outcome_records, "not_requested")
        payload = outcome["items"] if getattr(args, "items_only", False) else outcome
        written = None

        def on_write(value):
            nonlocal written
            written = value
            _write_event(_COMMAND, "final", output_path, records,
                         "saved" if value else "retained_previous")

        try:
            if output_path is None:
                _write_event(_COMMAND, "final", None, records, "not_requested")
                result = payload
            else:
                result = emit_rest_command_output(
                    payload, output_path, logger=logging.getLogger(__name__),
                    on_write=on_write,
                )
        except Exception as exc:
            _write_event(_COMMAND, "final", output_path, records, "failed",
                         error_type=type(exc).__name__)
            raise

        if response_fallback and written is True and bindings and captured:
            _log_qualification(outcome, output_path, outcome_path, tables, bindings, captured)
        else:
            log_event("coverage", source="otbr-restapi", command=_COMMAND,
                      stage="qualification", availability="unavailable")
            log_outcome_summary(
                None, source="otbr-restapi", command=_COMMAND, stage="qualification",
            )
        return result

    raise ValueError("Unsupported mesh-diagnostics command")
