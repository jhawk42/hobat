from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from otbr_restapi_util import OTBRRestApiClient, OTBRUsageError
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
    if args.node_command == "get":
        return client.get_node(fields=fields, raw=raw_arg)
    if args.node_command == "state":
        if args.state_command == "get":
            return client.get_node_state()
        if args.state_command == "set":
            return client.set_node_state(args.value)
    if args.node_command == "dataset" and args.dataset_kind == "active":
        if args.dataset_command == "get":
            return client.get_active_dataset(plain_text=args.text, raw=raw_arg)
        if args.dataset_command == "set":
            dataset = _parse_dataset_input(args)
            return client.set_active_dataset(dataset)

    raise ValueError("Unsupported node command")
