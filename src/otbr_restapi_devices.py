from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

from otbr_restapi_util import OTBRRestApiClient
from td_json_key_normalizer import convert_keys_to_camel_case
from util_data import create_checkpoint_filename, save_json_atomic


def _write_checkpoint_best_effort(payload: Any, checkpoint_path: Path) -> None:
    try:
        save_json_atomic(convert_keys_to_camel_case(payload), checkpoint_path)
        logging.info(
            "event=checkpoint_write command=otbr-restapi devices fetch checkpoint_file=%s records=%d stage=final",
            checkpoint_path,
            len(payload) if isinstance(payload, list) else 0,
        )
    except (OSError, ValueError, TypeError) as exc:
        logging.warning(
            "event=checkpoint_write_failed command=otbr-restapi devices fetch checkpoint_file=%s error_type=%s error=%s action=continue_best_effort",
            checkpoint_path,
            type(exc).__name__,
            exc,
        )


def dispatch_devices(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
    fields: dict[str, str] | None,
) -> Any:
    if args.devices_command == "list":
        return client.list_devices(fields=fields, raw=raw_arg, with_meta=args.with_meta)
    if args.devices_command == "get":
        return client.get_device(args.device_id, fields=fields, raw=raw_arg)
    if args.devices_command == "fetch":
        result = client.fetch_device_collection(
            device_count=args.device_count,
            max_age=args.max_age,
            max_retries=args.max_retries,
            task_timeout=args.task_timeout,
            poll_interval=args.poll_interval,
            poll_timeout=args.poll_timeout,
            items_only=not getattr(args, "structured_outcome", False),
            whole_action_attempts=getattr(args, "whole_action_attempts", 1),
            raw=raw_arg,
        )
        output_path = getattr(args, "resolved_output_path", None)
        if output_path:
            output_file = Path(output_path)
            checkpoint_path = output_file.parent / create_checkpoint_filename(
                output_file.name
            )
            _write_checkpoint_best_effort(result, checkpoint_path)
        return result

    raise ValueError("Unsupported devices command")
