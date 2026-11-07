from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from typing import Any

from otbr_restapi_util import (
    OTBRRestApiClient, emit_rest_command_output, emit_rest_observed_output,
    rest_payload_record_count,
)
from td_logging import format_event, log_event
from otbr_role_evidence import normalize_otbr_role_record
from td_device_fields import normalize_input_record
from td_json_key_normalizer import convert_keys_to_camel_case
from util_data import (
    CollectionWriteOutcome,
    create_checkpoint_filename,
    save_checkpoint_json,
    save_json_atomic,
)


def _normalize_device_record(
    record: Any, *, include_otbr_role_evidence: bool = False
) -> Any:
    if not isinstance(record, dict):
        return record
    normalized = normalize_input_record(record, source="rest")
    if include_otbr_role_evidence:
        normalized = normalize_otbr_role_record(normalized)
    return record if normalized == record else normalized


def _normalize_device_payload(
    payload: Any, *, include_otbr_role_evidence: bool = False
) -> Any:
    if isinstance(payload, list):
        normalized = [
            _normalize_device_record(
                record,
                include_otbr_role_evidence=include_otbr_role_evidence,
            )
            for record in payload
        ]
        return payload if all(new is old for new, old in zip(normalized, payload)) else normalized
    if not isinstance(payload, dict):
        return payload
    if isinstance(payload.get("items"), list):
        items = _normalize_device_payload(
            payload["items"],
            include_otbr_role_evidence=include_otbr_role_evidence,
        )
        return payload if items is payload["items"] else {**payload, "items": items}
    return _normalize_device_record(
        payload,
        include_otbr_role_evidence=include_otbr_role_evidence,
    )


def _write_checkpoint_best_effort(
    payload: Any,
    checkpoint_path: Path,
    *,
    normalize: bool = True,
    include_otbr_role_evidence: bool = False,
) -> None:
    count = rest_payload_record_count(payload)
    try:
        records = payload.get("items", []) if isinstance(payload, dict) else payload
        payload_to_save = (
            _normalize_device_payload(
                payload,
                include_otbr_role_evidence=include_otbr_role_evidence,
            )
            if normalize else payload
        )
        written = save_checkpoint_json(
            convert_keys_to_camel_case(payload_to_save),
            checkpoint_path,
            CollectionWriteOutcome.partial(has_usable_data=bool(records)),
            writer=save_json_atomic,
        )
        log_event(
            "checkpoint", source="otbr-restapi", command="devices fetch",
            stage="final", output=str(checkpoint_path), records=count,
            disposition="written" if written else "skipped_unusable",
        )
    except (OSError, ValueError, TypeError) as exc:
        log_event(
            "checkpoint", source="otbr-restapi", command="devices fetch",
            stage="final", output=str(checkpoint_path), records=count,
            disposition="failed", error_type=type(exc).__name__, error=str(exc),
            action="continue_best_effort",
        )
        logging.warning(
            "%s action=continue_best_effort",
            format_event(
                "checkpoint_write_failed", source="otbr-restapi", command="devices fetch",
                stage="final", output=str(checkpoint_path), records=count,
                error_type=type(exc).__name__, error=str(exc),
            ),
        )


def dispatch_devices(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
    fields: dict[str, str] | None,
) -> Any:
    output_path = getattr(args, "resolved_output_path", None)
    command = f"devices {args.devices_command}"
    started = time.monotonic()
    result: Any = None
    returned = False

    try:
        if args.devices_command == "list":
            result = client.list_devices(fields=fields, raw=raw_arg, with_meta=args.with_meta)
        elif args.devices_command == "get":
            result = client.get_device(args.device_id, fields=fields, raw=raw_arg)
        elif args.devices_command == "fetch":
            result = client.fetch_device_collection(
                device_count=args.device_count, max_age=args.max_age,
                max_retries=args.max_retries, task_timeout=args.task_timeout,
                poll_interval=args.poll_interval, poll_timeout=args.poll_timeout,
                items_only=not getattr(args, "structured_outcome", False),
                whole_action_attempts=getattr(args, "whole_action_attempts", 1),
                raw=raw_arg,
            )
        else:
            raise ValueError("Unsupported devices command")
        returned = True
    finally:
        fetch_elapsed = time.monotonic() - started
        if not returned:
            log_event("collector_summary", source="otbr-restapi", command=command,
                      stage="collection", state="raised", elapsed_s=fetch_elapsed,
                      records="unavailable")

    if args.devices_command == "fetch":
        if output_path and isinstance(result, dict) and result.get("partial"):
            output_file = Path(output_path)
            checkpoint_path = output_file.parent / create_checkpoint_filename(
                output_file.name
            )
            _write_checkpoint_best_effort(
                result,
                checkpoint_path,
                normalize=raw_arg is not True,
                include_otbr_role_evidence=True,
            )

    started = time.monotonic()
    normalized = False
    try:
        if raw_arg is not True:
            result = _normalize_device_payload(
                result, include_otbr_role_evidence=args.devices_command != "get"
            )
        normalized = True
    finally:
        log_event(
            "collector_summary", source="otbr-restapi", command=command,
            stage="collection", state="returned" if normalized else "raised",
            elapsed_s=fetch_elapsed + time.monotonic() - started,
            records=rest_payload_record_count(result, single=args.devices_command == "get"),
        )
    return emit_rest_observed_output(
        result, output_path, command=command, stage="final",
        single=args.devices_command == "get", logger=logging.getLogger(__name__),
        emitter=emit_rest_command_output,
    )
