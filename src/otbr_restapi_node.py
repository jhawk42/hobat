from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from otbr_restapi_util import (
    OTBRRestApiClient,
    OTBRUsageError,
    SENSITIVE_VALUE_REDACTION,
    emit_rest_command_output,
    emit_rest_observed_output,
    redact_sensitive_payload,
)
from td_logging import log_event
from util_data import resolve_data_file_path


def _parse_dataset_input(args: argparse.Namespace) -> dict[str, Any] | str:
    td_data_dir = getattr(args, "td_data_dir", None)

    def _resolve(path_value: str) -> Path:
        if td_data_dir is None:
            return Path(path_value)
        return resolve_data_file_path(path_value, td_data_dir)

    try:
        if args.json is not None:
            return json.loads(args.json)
        if args.json_file is not None:
            return json.loads(_resolve(args.json_file).read_text(encoding="utf-8"))
        if args.text is not None:
            return args.text
        if args.text_file is not None:
            return _resolve(args.text_file).read_text(encoding="utf-8").strip()
    except json.JSONDecodeError as exc:
        raise OTBRUsageError(f"Invalid dataset JSON: {exc}") from exc
    except OSError as exc:
        raise OTBRUsageError(f"Failed to read dataset input: {exc}") from exc

    raise OTBRUsageError("No dataset input provided")


def dispatch_node(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
    fields: dict[str, str] | None,
) -> Any:
    output_path = getattr(args, "resolved_output_path", None)
    logger = logging.getLogger(__name__)
    command = f"node {args.node_command}"
    if args.node_command == "state":
        command += f" {args.state_command}"
    elif args.node_command == "dataset":
        command += f" {args.dataset_kind} {args.dataset_command}"

    def operation(call: Callable[[], Any]) -> Any:
        started = time.monotonic()
        returned = False
        try:
            result = call()
            returned = True
            return result
        finally:
            log_event("operation_end", source="otbr-restapi", command=command,
                      stage="operation", state="returned" if returned else "raised",
                      elapsed_s=time.monotonic() - started)

    def finish(result: Any, *, plain_text: bool = False) -> Any:
        return emit_rest_observed_output(
            result, output_path, command=command, stage="final", single=True,
            plain_text=plain_text, logger=logger, emitter=emit_rest_command_output,
        )

    if args.node_command == "get":
        return finish(operation(lambda: client.get_node(fields=fields, raw=raw_arg)))
    if args.node_command == "state":
        if args.state_command == "get":
            return finish(operation(client.get_node_state))
        if args.state_command == "set":
            return finish(operation(lambda: client.set_node_state(args.value)))
    if args.node_command == "dataset" and args.dataset_kind == "active":
        if args.dataset_command == "get":
            result = operation(lambda: client.get_active_dataset(plain_text=args.text, raw=raw_arg))
            result = (
                SENSITIVE_VALUE_REDACTION
                if args.text or isinstance(result, str)
                else redact_sensitive_payload(result)
            )
            return finish(result, plain_text=args.text)
        if args.dataset_command == "set":
            dataset = _parse_dataset_input(args)
            return finish(operation(lambda: client.set_active_dataset(dataset)))

    raise ValueError("Unsupported node command")
