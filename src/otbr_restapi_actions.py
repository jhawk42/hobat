from __future__ import annotations

import argparse
from typing import Any, Sequence

from otbr_restapi_diagnostics import resolve_types
from otbr_restapi_util import (
    OTBRRestApiClient,
    OTBRUsageError,
    extract_action_result_id,
)


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
    if args.actions_command == "list":
        return client.list_actions(fields=fields, raw=raw_arg, with_meta=args.with_meta)
    if args.actions_command == "get":
        return client.get_action(args.action_id, fields=fields, raw=raw_arg)
    if args.actions_command == "enqueue":
        if args.enqueue_type == "add-thread-device":
            return client.enqueue_add_thread_device_task(
                pskd=args.pskd,
                eui=args.eui,
                discerner=args.discerner,
                joiner_id=args.joiner_id,
                timeout=args.timeout,
                raw=raw_arg,
            )
        if args.enqueue_type == "get-network-diagnostic":
            resolved_types = resolve_types(args)
            if not resolved_types:
                raise OTBRUsageError("Provide --types or --preset for get-network-diagnostic")
            enqueued = client.enqueue_get_network_diagnostic_task(
                destination=args.destination,
                types=resolved_types,
                timeout=args.timeout,
                destination_type=args.destination_type,
                raw=raw_arg,
            )
            if not getattr(args, "wait", False):
                return enqueued
            action_id = enqueued["data"][0]["id"] if effective_raw else enqueued[0]["id"]
            action = client.wait_for_action(
                action_id,
                poll_interval=args.poll_interval,
                poll_timeout=args.poll_timeout,
                raise_on_stopped=True,
                raw=raw_arg,
            )
            result_id = extract_action_result_id(action)
            if result_id:
                return client.get_diagnostic(result_id, raw=raw_arg)
            return action
        if args.enqueue_type == "reset-network-diag-counter":
            return client.enqueue_reset_network_diag_counter_task(
                destination=args.destination,
                types=_parse_typed_values(args.types),
                timeout=args.timeout,
                destination_type=args.destination_type,
                raw=raw_arg,
            )
        if args.enqueue_type == "get-energy-scan":
            return client.enqueue_get_energy_scan_task(
                destination=args.destination,
                channel_mask=args.channel_mask,
                count=args.count,
                period=args.period,
                scan_duration=args.scan_duration,
                timeout=args.timeout,
                destination_type=args.destination_type,
                raw=raw_arg,
            )
        if args.enqueue_type == "update-device-collection":
            return client.enqueue_update_device_collection_task(
                max_age=args.max_age,
                max_retries=args.max_retries,
                device_count=args.device_count,
                timeout=args.timeout,
                raw=raw_arg,
            )

    raise ValueError("Unsupported actions command")
