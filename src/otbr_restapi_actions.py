from __future__ import annotations

import argparse
import logging
import time
from typing import Any, Callable, Sequence

from otbr_restapi_diagnostics import resolve_types
from otbr_restapi_util import (
    DIAGNOSTICS_DEFAULT_TASK_TIMEOUT,
    OTBRRestApiClient,
    OTBRUsageError,
    emit_rest_command_output,
    emit_rest_observed_output,
    extract_action_result_id,
)
from td_logging import log_event


def _parse_typed_values(values: Sequence[str]) -> list[str | int]:
    parsed: list[str | int] = []
    for value in values:
        try:
            parsed.append(int(value))
        except ValueError:
            parsed.append(value)
    return parsed


def dispatch_actions(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
    fields: dict[str, str] | None,
    effective_raw: bool,
) -> Any:
    output_path = getattr(args, "resolved_output_path", None)
    command = f"actions {args.actions_command}"
    if args.actions_command == "enqueue":
        command += f" {args.enqueue_type}"
    started = time.monotonic()
    operation_returned = False

    def finish(result: Any, *, action: Any = None) -> Any:
        nonlocal operation_returned
        operation_returned = True
        facts: dict[str, Any] = {}
        evidence = result if action is None else action
        if isinstance(evidence, dict):
            if isinstance(evidence.get("data"), dict):
                evidence = evidence["data"]
            if isinstance(evidence.get("attributes"), dict):
                evidence = evidence["attributes"]
            action_state = evidence.get("status", evidence.get("state"))
            if action_state in ("queued", "pending", "active", "running", "completed",
                                "stopped", "failed", "undiscovered", "attempted"):
                facts["action_state"] = action_state
            for key in ("accepted", "acceptedForTransmission"):
                if isinstance(evidence.get(key), bool):
                    facts["accepted"] = evidence[key]
                    break
        log_event("operation_end", source="otbr-restapi", command=command,
                  stage="operation", state="returned",
                  elapsed_s=time.monotonic() - started, **facts)
        return emit_rest_observed_output(
            result, output_path, command=command, stage="final",
            single=args.actions_command != "list", logger=logging.getLogger(__name__),
            emitter=emit_rest_command_output,
        )

    try:
        return _dispatch_actions(client, args, raw_arg, fields, effective_raw, finish)
    finally:
        if not operation_returned:
            log_event("operation_end", source="otbr-restapi", command=command,
                      stage="operation", state="raised",
                      elapsed_s=time.monotonic() - started)


def _dispatch_actions(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
    fields: dict[str, str] | None,
    effective_raw: bool,
    finish: Callable[..., Any],
) -> Any:
    if args.actions_command == "list":
        return finish(client.list_actions(fields=fields, raw=raw_arg, with_meta=args.with_meta))
    if args.actions_command == "get":
        return finish(client.get_action(args.action_id, fields=fields, raw=raw_arg))
    if args.actions_command == "enqueue":
        if args.enqueue_type == "add-thread-device":
            return finish(client.enqueue_add_thread_device_task(
                pskd=args.pskd,
                eui=args.eui,
                discerner=args.discerner,
                joiner_id=args.joiner_id,
                timeout=args.timeout,
                raw=raw_arg,
            ))
        if args.enqueue_type == "get-network-diagnostic":
            resolved_types = resolve_types(args)
            if not resolved_types:
                raise OTBRUsageError("Provide --types or --preset for get-network-diagnostic")
            if not getattr(args, "wait", False):
                return finish(client.enqueue_get_network_diagnostic_task(
                    destination=args.destination,
                    types=resolved_types,
                    timeout=args.timeout,
                    destination_type=args.destination_type,
                    raw=raw_arg,
                ))
            task_timeout = args.timeout or DIAGNOSTICS_DEFAULT_TASK_TIMEOUT
            action = client.run_action(
                lambda: client.enqueue_get_network_diagnostic_task(
                    destination=args.destination,
                    types=resolved_types,
                    timeout=task_timeout,
                    destination_type=args.destination_type,
                    raw=False,
                ),
                task_timeout=task_timeout,
                poll_interval=args.poll_interval,
                poll_timeout=args.poll_timeout,
                raise_on_stopped=True,
                raw=raw_arg,
            )
            result_id = extract_action_result_id(action)
            if result_id:
                return finish(client.get_diagnostic(result_id, raw=raw_arg), action=action)
            return finish(action)
        if args.enqueue_type == "reset-network-diag-counter":
            return finish(client.enqueue_reset_network_diag_counter_task(
                destination=args.destination,
                types=_parse_typed_values(args.types),
                timeout=args.timeout,
                destination_type=args.destination_type,
                raw=raw_arg,
            ))
        if args.enqueue_type == "get-energy-scan":
            return finish(client.enqueue_get_energy_scan_task(
                destination=args.destination,
                channel_mask=args.channel_mask,
                count=args.count,
                period=args.period,
                scan_duration=args.scan_duration,
                timeout=args.timeout,
                destination_type=args.destination_type,
                raw=raw_arg,
            ))
        if args.enqueue_type == "update-device-collection":
            return finish(client.enqueue_update_device_collection_task(
                max_age=args.max_age,
                max_retries=args.max_retries,
                device_count=args.device_count,
                timeout=args.timeout,
                raw=raw_arg,
            ))

    raise ValueError("Unsupported actions command")
