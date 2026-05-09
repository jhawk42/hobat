from __future__ import annotations

import argparse
import json
import sys
import logging

from pathlib import Path
from typing import Any, Sequence
from util_data import resolve_data_file_path, resolve_data_dir
from const import TD_DATA_DIR_ARG_HELP

from otbr_restapi_client import (
    DEFAULT_ACCEPT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    OTBRClientError,
    OTBRConnectionError,
    OTBRHTTPError,
    OTBRInvalidResponseError,
    OTBRRestApiClient,
    OTBRUsageError,
    build_fields_mapping,
    error_to_dict,
)

EXIT_SUCCESS = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_CONNECTION = 3
EXIT_HTTP = 4
EXIT_INVALID_RESPONSE = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CLI wrapper for the OpenThread Border Router REST API.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help="OTBR REST API host")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="OTBR REST API port"
    )
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    parser.add_argument(
        "--base-url", help="Override host/port with a full base URL")
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds"
    )
    parser.add_argument(
        "--accept",
        default=DEFAULT_ACCEPT,
        choices=["application/vnd.api+json", "application/json", "text/plain"],
        help="Default Accept header",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Return raw API envelopes instead of flattened output",
    )
    parser.add_argument("--output", help="Write the command result to a file")

    subparsers = parser.add_subparsers(dest="resource", required=True)
    _add_node_commands(subparsers)
    _add_devices_commands(subparsers)
    _add_diagnostics_commands(subparsers)
    _add_actions_commands(subparsers)
    return parser


def _add_node_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    node_parser = subparsers.add_parser(
        "node", help="Read or mutate local OTBR node data"
    )
    node_subparsers = node_parser.add_subparsers(
        dest="node_command", required=True)

    node_get = node_subparsers.add_parser(
        "get", help="Get the OTBR node record from /api/node"
    )
    _add_fields_argument(node_get)

    state_parser = node_subparsers.add_parser(
        "state", help="Get or set Thread state")
    state_subparsers = state_parser.add_subparsers(
        dest="state_command", required=True)
    state_subparsers.add_parser("get", help="Get current Thread state")
    state_set = state_subparsers.add_parser(
        "set", help="Enable or disable Thread")
    state_set.add_argument("--value", required=True,
                           choices=["enable", "disable"])

    dataset_parser = node_subparsers.add_parser(
        "dataset", help="Operate on node datasets"
    )
    dataset_subparsers = dataset_parser.add_subparsers(
        dest="dataset_kind", required=True
    )
    active_parser = dataset_subparsers.add_parser(
        "active", help="Operate on active dataset"
    )
    active_subparsers = active_parser.add_subparsers(
        dest="dataset_command", required=True
    )
    active_get = active_subparsers.add_parser("get", help="Get active dataset")
    active_get.add_argument(
        "--text", action="store_true", help="Request text/plain TLV dataset"
    )

    active_set = active_subparsers.add_parser(
        "set", help="Create or update active dataset"
    )
    group = active_set.add_mutually_exclusive_group(required=True)
    group.add_argument("--json", help="Inline JSON payload for dataset")
    group.add_argument(
        "--json-file", help="Path to a JSON file containing the dataset")
    group.add_argument("--text", help="Inline TLV dataset string")
    group.add_argument(
        "--text-file", help="Path to a text file containing the TLV dataset"
    )


def _add_devices_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    devices_parser = subparsers.add_parser("devices", help="Read OTBR devices")
    devices_subparsers = devices_parser.add_subparsers(
        dest="devices_command", required=True
    )

    devices_list = devices_subparsers.add_parser("list", help="List devices")
    _add_fields_argument(devices_list)
    devices_list.add_argument(
        "--with-meta",
        action="store_true",
        help="Include collection meta with flattened items",
    )

    devices_get = devices_subparsers.add_parser(
        "get", help="Get a device by device ID")
    devices_get.add_argument("--device-id", required=True)
    _add_fields_argument(devices_get)


def _add_diagnostics_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    diagnostics_parser = subparsers.add_parser(
        "diagnostics", help="Read OTBR diagnostics"
    )
    diagnostics_subparsers = diagnostics_parser.add_subparsers(
        dest="diagnostics_command", required=True
    )

    diagnostics_list = diagnostics_subparsers.add_parser(
        "list", help="List diagnostics"
    )
    _add_fields_argument(diagnostics_list)
    diagnostics_list.add_argument(
        "--with-meta",
        action="store_true",
        help="Include collection meta with flattened items",
    )

    diagnostics_get = diagnostics_subparsers.add_parser(
        "get", help="Get a diagnostic by diagnostics ID"
    )
    diagnostics_get.add_argument("--diagnostics-id", required=True)


def _add_actions_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    actions_parser = subparsers.add_parser(
        "actions", help="Read or enqueue OTBR actions"
    )
    actions_subparsers = actions_parser.add_subparsers(
        dest="actions_command", required=True
    )

    actions_list = actions_subparsers.add_parser("list", help="List actions")
    _add_fields_argument(actions_list)
    actions_list.add_argument(
        "--with-meta",
        action="store_true",
        help="Include collection meta with flattened items",
    )

    actions_get = actions_subparsers.add_parser(
        "get", help="Get an action by action ID"
    )
    actions_get.add_argument("--action-id", required=True)

    enqueue_parser = actions_subparsers.add_parser(
        "enqueue", help="Enqueue a new OTBR task"
    )
    enqueue_subparsers = enqueue_parser.add_subparsers(
        dest="enqueue_type", required=True
    )

    add_thread_device = enqueue_subparsers.add_parser(
        "add-thread-device", help="Enqueue addThreadDeviceTask"
    )
    add_thread_device.add_argument("--pskd", required=True)
    identity_group = add_thread_device.add_mutually_exclusive_group(
        required=True)
    identity_group.add_argument("--eui")
    identity_group.add_argument("--discerner")
    identity_group.add_argument("--joiner-id")
    add_thread_device.add_argument("--timeout", type=int)

    get_network_diag = enqueue_subparsers.add_parser(
        "get-network-diagnostic", help="Enqueue getNetworkDiagnosticTask"
    )
    get_network_diag.add_argument("--destination", required=True)
    get_network_diag.add_argument(
        "--types", nargs="+", required=True, help="Diagnostic TLVs by name or integer"
    )
    get_network_diag.add_argument("--timeout", type=int)
    get_network_diag.add_argument("--destination-type")

    reset_network_diag = enqueue_subparsers.add_parser(
        "reset-network-diag-counter", help="Enqueue resetNetworkDiagCounterTask"
    )
    reset_network_diag.add_argument(
        "--types", nargs="+", required=True, help="Counter TLVs by name or integer"
    )
    reset_network_diag.add_argument("--destination")
    reset_network_diag.add_argument("--timeout", type=int)
    reset_network_diag.add_argument("--destination-type")

    energy_scan = enqueue_subparsers.add_parser(
        "get-energy-scan", help="Enqueue getEnergyScanTask"
    )
    energy_scan.add_argument("--destination", required=True)
    energy_scan.add_argument(
        "--channel-mask", nargs="+", required=True, type=int)
    energy_scan.add_argument("--count", required=True, type=int)
    energy_scan.add_argument("--period", required=True, type=int)
    energy_scan.add_argument("--scan-duration", required=True, type=int)
    energy_scan.add_argument("--timeout", required=True, type=int)
    energy_scan.add_argument("--destination-type")

    update_devices = enqueue_subparsers.add_parser(
        "update-device-collection", help="Enqueue updateDeviceCollectionTask"
    )
    update_devices.add_argument("--max-age", required=True, type=int)
    update_devices.add_argument("--max-retries", required=True, type=int)
    update_devices.add_argument("--device-count", required=True, type=int)
    update_devices.add_argument("--timeout", required=True, type=int)


def _add_fields_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fields",
        action="append",
        help="Repeatable sparse-field selector such as 'threadDevice=hostname,role' or 'threadDevice'",
    )


def build_client(args: argparse.Namespace) -> OTBRRestApiClient:
    return OTBRRestApiClient(
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
            return client.get_node(fields=fields, raw=args.raw)
        if args.node_command == "state":
            if args.state_command == "get":
                return client.get_node_state()
            if args.state_command == "set":
                return client.set_node_state(args.value)
        if args.node_command == "dataset" and args.dataset_kind == "active":
            if args.dataset_command == "get":
                return client.get_active_dataset(plain_text=args.text, raw=args.raw)
            if args.dataset_command == "set":
                dataset = _parse_dataset_input(args)
                return client.set_active_dataset(dataset)

    if args.resource == "devices":
        if args.devices_command == "list":
            return client.list_devices(
                fields=fields, raw=args.raw, with_meta=args.with_meta
            )
        if args.devices_command == "get":
            return client.get_device(args.device_id, fields=fields, raw=args.raw)

    if args.resource == "diagnostics":
        if args.diagnostics_command == "list":
            return client.list_diagnostics(
                fields=fields, raw=args.raw, with_meta=args.with_meta
            )
        if args.diagnostics_command == "get":
            return client.get_diagnostic(args.diagnostics_id, raw=args.raw)

    if args.resource == "actions":
        if args.actions_command == "list":
            return client.list_actions(
                fields=fields, raw=args.raw, with_meta=args.with_meta
            )
        if args.actions_command == "get":
            return client.get_action(args.action_id, raw=args.raw)
        if args.actions_command == "enqueue":
            if args.enqueue_type == "add-thread-device":
                return client.enqueue_add_thread_device_task(
                    pskd=args.pskd,
                    eui=args.eui,
                    discerner=args.discerner,
                    joiner_id=args.joiner_id,
                    timeout=args.timeout,
                    raw=args.raw,
                )
            if args.enqueue_type == "get-network-diagnostic":
                return client.enqueue_get_network_diagnostic_task(
                    destination=args.destination,
                    types=_parse_typed_values(args.types),
                    timeout=args.timeout,
                    destination_type=args.destination_type,
                    raw=args.raw,
                )
            if args.enqueue_type == "reset-network-diag-counter":
                return client.enqueue_reset_network_diag_counter_task(
                    destination=args.destination,
                    types=_parse_typed_values(args.types),
                    timeout=args.timeout,
                    destination_type=args.destination_type,
                    raw=args.raw,
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
                    raw=args.raw,
                )
            if args.enqueue_type == "update-device-collection":
                return client.enqueue_update_device_collection_task(
                    max_age=args.max_age,
                    max_retries=args.max_retries,
                    device_count=args.device_count,
                    timeout=args.timeout,
                    raw=args.raw,
                )

    raise ValueError("Unsupported CLI command")


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


def _parse_typed_values(values: Sequence[str]) -> list[str | int]:
    parsed: list[str | int] = []
    for value in values:
        try:
            parsed.append(int(value))
        except ValueError:
            parsed.append(value)
    return parsed


def emit_output(result: Any, output_path: str | None) -> None:
    if result is None:
        rendered = ""
    elif isinstance(result, str):
        rendered = result
    else:
        rendered = json.dumps(result, indent=4, sort_keys=True)

    if output_path:
        suffix = "\n" if rendered and not rendered.endswith("\n") else ""
        Path(output_path).write_text(rendered + suffix, encoding="utf-8")

    if rendered:
        logging.info("Output:\n%s", rendered)


def emit_error(exc: Exception) -> None:
    payload = error_to_dict(exc)
    logging.error("Error occurred:\n%s", json.dumps(
        payload, indent=4, sort_keys=True))


def exit_code_for_exception(exc: Exception) -> int:
    if isinstance(exc, OTBRUsageError):
        return EXIT_USAGE
    if isinstance(exc, OTBRConnectionError):
        return EXIT_CONNECTION
    if isinstance(exc, OTBRHTTPError):
        return EXIT_HTTP
    if isinstance(exc, OTBRInvalidResponseError):
        return EXIT_INVALID_RESPONSE
    if isinstance(exc, OTBRClientError):
        return EXIT_UNEXPECTED
    return EXIT_UNEXPECTED


def main(argv: Sequence[str] | None = None) -> int:
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
    except OTBRClientError as exc:
        emit_error(exc)
        return exit_code_for_exception(exc)


if __name__ == "__main__":
    sys.exit(main())
