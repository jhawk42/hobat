from __future__ import annotations

import argparse
import logging

from typing import Any, Sequence
from util_data import resolve_data_file_path, resolve_data_dir

from otbr_restapi_client_cli import (
    EXIT_SUCCESS,
    _parse_dataset_input,
    _parse_typed_values,
    build_parser as build_flattened_parser,
    emit_error,
    emit_output,
)
from otbr_restapi_raw_client import OTBRRawRestApiClient, build_fields_mapping


def build_parser() -> argparse.ArgumentParser:
    parser = build_flattened_parser()
    parser.description = "CLI wrapper for the OpenThread Border Router REST API returning raw server envelopes."
    return parser


def build_client(args: argparse.Namespace) -> OTBRRawRestApiClient:
    return OTBRRawRestApiClient(
        host=args.host,
        port=args.port,
        base_url=args.base_url,
        timeout=args.timeout,
        accept=args.accept,
    )


def dispatch(args: argparse.Namespace) -> Any:
    client = build_client(args)
    fields = build_fields_mapping(getattr(args, "fields", None))

    if args.resource == "node":
        if args.node_command == "get":
            return client.get_node(fields=fields)
        if args.node_command == "state":
            if args.state_command == "get":
                return client.get_node_state()
            if args.state_command == "set":
                return client.set_node_state(args.value)
        if args.node_command == "dataset" and args.dataset_kind == "active":
            if args.dataset_command == "get":
                return client.get_active_dataset(plain_text=args.text)
            if args.dataset_command == "set":
                dataset = _parse_dataset_input(args)
                return client.set_active_dataset(dataset)

    if args.resource == "devices":
        if args.devices_command == "list":
            return client.list_devices(fields=fields)
        if args.devices_command == "get":
            return client.get_device(args.device_id, fields=fields)

    if args.resource == "diagnostics":
        if args.diagnostics_command == "list":
            return client.list_diagnostics(fields=fields)
        if args.diagnostics_command == "get":
            return client.get_diagnostic(args.diagnostics_id)

    if args.resource == "actions":
        if args.actions_command == "list":
            return client.list_actions(fields=fields)
        if args.actions_command == "get":
            return client.get_action(args.action_id)
        if args.actions_command == "enqueue":
            if args.enqueue_type == "add-thread-device":
                return client.enqueue_add_thread_device_task(
                    pskd=args.pskd,
                    eui=args.eui,
                    discerner=args.discerner,
                    joiner_id=args.joiner_id,
                    timeout=args.timeout,
                )
            if args.enqueue_type == "get-network-diagnostic":
                return client.enqueue_get_network_diagnostic_task(
                    destination=args.destination,
                    types=_parse_typed_values(args.types),
                    timeout=args.timeout,
                    destination_type=args.destination_type,
                )
            if args.enqueue_type == "reset-network-diag-counter":
                return client.enqueue_reset_network_diag_counter_task(
                    destination=args.destination,
                    types=_parse_typed_values(args.types),
                    timeout=args.timeout,
                    destination_type=args.destination_type,
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
                )
            if args.enqueue_type == "update-device-collection":
                return client.enqueue_update_device_collection_task(
                    max_age=args.max_age,
                    max_retries=args.max_retries,
                    device_count=args.device_count,
                    timeout=args.timeout,
                )

    raise ValueError("Unsupported CLI command")


def main(argv: Sequence[str] | None = None) -> int:
    from otbr_restapi_client_cli import exit_code_for_exception

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    parser = build_parser()
    args = parser.parse_args(argv)
    args.td_data_dir = resolve_data_dir(datadir_arg=args.datadir)

    output_path = args.output
    if output_path:
        output_path = str(resolve_data_file_path(
            output_path, args.td_data_dir))

    try:
        result = dispatch(args)
        emit_output(result, output_path)
        return EXIT_SUCCESS
    except Exception as exc:
        emit_error(exc)
        return exit_code_for_exception(exc)


if __name__ == "__main__":
    raise SystemExit(main())
