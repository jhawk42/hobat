from __future__ import annotations

import argparse
from typing import Any

from otbr_restapi_util import OTBRRestApiClient


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
        return client.fetch_device_collection(
            device_count=args.device_count,
            max_age=args.max_age,
            max_retries=args.max_retries,
            task_timeout=args.task_timeout,
            poll_interval=args.poll_interval,
            poll_timeout=args.poll_timeout,
            raw=raw_arg,
        )

    raise ValueError("Unsupported devices command")
