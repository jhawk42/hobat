from __future__ import annotations

import argparse
import json
import logging
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from otbr_restapi_diagnostics import make_progress_fn
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
    write_rest_collection_outcome,
)

CLI_MESH_TASK_TIMEOUT_DEFAULT = 15
ROUTER_RLOC16_MASK = 0x03FF
ROUTER_RLOC16_VALUE = 0


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


def _attach_responsiveness(client, outcome, devices, scope_before, tables, bindings, captured, output_path, destination_type):
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
    for record in outcome.get("deviceResults", []):
        if record.get("status") == "completed":
            continue
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


def _write_checkpoint_best_effort(payload: Any, checkpoint_path: Path) -> None:
    try:
        save_checkpoint_json(
            convert_keys_to_camel_case(payload),
            checkpoint_path,
            CollectionWriteOutcome.partial(has_usable_data=bool(payload)),
            writer=save_json_atomic,
        )
        logging.info(
            "event=checkpoint_write command=otbr-restapi mesh-diagnostics fetch-all checkpoint_file=%s records=%d stage=device",
            checkpoint_path,
            len(payload) if isinstance(payload, list) else 0,
        )
    except (OSError, ValueError, TypeError) as exc:
        logging.warning(
            "event=checkpoint_write_failed command=otbr-restapi mesh-diagnostics fetch-all checkpoint_file=%s error_type=%s error=%s action=continue_best_effort",
            checkpoint_path,
            type(exc).__name__,
            exc,
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
        return emit_rest_command_output(result, output_path, logger=logging.getLogger(__name__))

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

        progress_fn = make_progress_fn(len(device_ids), not getattr(args, "no_progress", False))
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
            on_checkpoint=_on_checkpoint,
            raw=raw_arg,
        )
        if response_fallback:
            _attach_responsiveness(
                client, outcome, devices, scope_before, tables, bindings, captured,
                output_path, dest_type,
            )
        if output_path is not None:
            write_rest_collection_outcome(
                outcome, collection_outcome_path(output_path),
                raw=raw_arg is True, command_name="otbr-restapi mesh-diagnostics fetch-all",
            )
        payload = outcome["items"] if getattr(args, "items_only", False) else outcome
        return finish(payload)

    raise ValueError("Unsupported mesh-diagnostics command")
