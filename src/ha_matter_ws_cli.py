"""Public CLI owner for Home Assistant Matter WebSocket snapshots."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ha_matter_ws_client import MatterWsTransportError
from ha_matter_ws_contract import (
    HA_MATTER_WS_HOST_DEFAULT,
    HA_MATTER_WS_HOST_ENV,
    HA_MATTER_WS_PORT_DEFAULT,
    HA_MATTER_WS_PORT_ENV,
    MatterWsContractError,
    build_ha_matter_ws_uri,
    resolve_default_ha_matter_ws_host,
    resolve_default_ha_matter_ws_port,
)
from ha_matter_ws_extractor import MatterExtractionError
from ha_matter_ws_fetch_all import MatterCollection, collect_devices
from ha_matter_ws_snapshots import MatterSnapshotSecurityError
from td_const import (
    HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME,
    HA_MATTER_WS_DASHBOARD_FILENAME,
    HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME,
    HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_SERVER_INFO_FILENAME,
    HA_MATTER_WS_TOPOLOGY_FILENAME,
    TD_DATA_DIR_ARG_HELP,
)
from util_data import (
    create_checkpoint_filename,
    ensure_data_dir_exists,
    resolve_data_dir,
    resolve_data_file_path,
    save_json_atomic,
)


EXIT_OK = 0
EXIT_ARGUMENT = 2
EXIT_CONNECTION = 3
EXIT_PROTOCOL = 4
EXIT_PARTIAL = 5
EXIT_EXTRACTION = 6
EXIT_PERSISTENCE = 7
EXIT_CANCELLED = 130
DASHBOARD_SCHEMA_VERSION = "1.0.0"


class MatterPartialCollectionError(RuntimeError):
    """The controller inventory lost nodes during normalization."""


class MatterArgumentError(ValueError):
    """A command argument is semantically invalid."""


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    default_host = resolve_default_ha_matter_ws_host()
    default_port = resolve_default_ha_matter_ws_port()
    parser = argparse.ArgumentParser(
        prog="td_cli ha-matter-ws",
        description="Collect normalized snapshots from Home Assistant Matter Server",
    )
    parser.add_argument(
        "--host",
        default=default_host,
        help=(
            f"Matter WebSocket host (default: {default_host}; falls back to "
            f"{HA_MATTER_WS_HOST_DEFAULT} when {HA_MATTER_WS_HOST_ENV} is unset)"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help=(
            f"Matter WebSocket port (default: {default_port}; falls back to "
            f"{HA_MATTER_WS_PORT_DEFAULT} when {HA_MATTER_WS_PORT_ENV} is unset/invalid)"
        ),
    )
    parser.add_argument(
        "--uri",
        default=None,
        help="Override host and port with a full Matter WebSocket URI",
    )
    parser.add_argument("--connect-timeout", type=_positive_float, default=10.0)
    parser.add_argument("--request-timeout", type=_positive_float, default=5.0)
    parser.add_argument("--settle-timeout", type=_positive_float, default=0.25)
    parser.add_argument("--datadir", help=TD_DATA_DIR_ARG_HELP)
    parser.add_argument("--output", "-o", metavar="FILE")
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--debug", "-d", action="store_true")

    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("server-info", help="Fetch compatible server metadata")

    devices = commands.add_parser("devices", help="Read normalized Matter devices")
    device_commands = devices.add_subparsers(dest="devices_command", required=True)
    device_commands.add_parser("list", help="Print concise node inventory")
    device_get = device_commands.add_parser("get", help="Print one normalized node")
    device_get.add_argument("--node-id", required=True)
    device_commands.add_parser("fetch-all", help="Save all normalized nodes")

    diagnostics = commands.add_parser("diagnostics", help="Read Thread diagnostics")
    diagnostic_commands = diagnostics.add_subparsers(
        dest="diagnostics_command", required=True
    )
    diagnostic_get = diagnostic_commands.add_parser("get", help="Print one diagnostic")
    diagnostic_get.add_argument("--node-id", required=True)
    diagnostic_commands.add_parser("fetch-all", help="Save all diagnostics")

    mesh = commands.add_parser(
        "mesh-diagnostics", help="Read relationship-rich Thread diagnostics"
    )
    mesh_commands = mesh.add_subparsers(dest="mesh_diagnostics_command", required=True)
    mesh_get = mesh_commands.add_parser("get", help="Print one mesh diagnostic")
    mesh_get.add_argument("--node-id", required=True)
    mesh_commands.add_parser("fetch-all", help="Save all mesh diagnostics")

    commands.add_parser("topology", help="Save canonical Matter topology")
    commands.add_parser("dashboard", help="Save the dashboard data bundle")
    commands.add_parser("all", help="Collect once and save every Matter snapshot")
    return parser


def _command_path(args: argparse.Namespace) -> tuple[str, ...]:
    path = [args.command]
    nested = getattr(args, f"{args.command.replace('-', '_')}_command", None)
    if nested:
        path.append(nested)
    return tuple(path)


def _fixed_filename(path: tuple[str, ...]) -> str | None:
    return {
        ("server-info",): HA_MATTER_WS_SERVER_INFO_FILENAME,
        ("devices", "fetch-all"): HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME,
        ("diagnostics", "fetch-all"): HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME,
        ("mesh-diagnostics", "fetch-all"): HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
        ("topology",): HA_MATTER_WS_TOPOLOGY_FILENAME,
        ("dashboard",): HA_MATTER_WS_DASHBOARD_FILENAME,
    }.get(path)


def _node_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value, 0)
    except ValueError:
        return None


def _record_node_number(record: Mapping[str, Any]) -> int | None:
    direct = _node_number(record.get("nodeId"))
    if direct is not None:
        return direct
    matter = record.get("matter")
    if isinstance(matter, Mapping):
        nested = _node_number(matter.get("nodeId"))
        if nested is not None:
            return nested
    matter_id = record.get("matterId")
    if isinstance(matter_id, str) and ":" in matter_id:
        return _node_number(matter_id.rsplit(":", 1)[1])
    return None


def _select_node(records: Sequence[dict[str, Any]], node_id: str) -> dict[str, Any]:
    wanted = _node_number(node_id)
    if wanted is None:
        raise MatterArgumentError(f"invalid Matter node id: {node_id}")
    for record in records:
        if _record_node_number(record) == wanted:
            return record
    raise ValueError(f"Matter node not found: {node_id}")


def _device_inventory(devices: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    inventory = []
    for device in devices:
        matter = device.get("matter")
        node_id = matter.get("nodeId") if isinstance(matter, Mapping) else None
        inventory.append(
            {
                "nodeId": node_id,
                "deviceLabel": device.get("deviceLabel"),
                "available": device.get("available"),
                "isBridge": device.get("isBridge"),
            }
        )
    return inventory


def _payload(collection: MatterCollection, path: tuple[str, ...], node_id: str | None) -> Any:
    if path == ("server-info",):
        return collection.server_info
    if path == ("devices", "list"):
        return _device_inventory(collection.devices)
    if path == ("dashboard",):
        return build_dashboard_snapshot(collection)
    if path[0] == "devices":
        records = collection.devices
    elif path[0] == "diagnostics":
        records = collection.diagnostics
    elif path[0] == "mesh-diagnostics":
        records = collection.mesh_diagnostics
    elif path == ("topology",):
        records = collection.topology
    else:
        raise ValueError(f"unsupported command path: {' '.join(path)}")
    if path[-1] == "get":
        return _select_node(records, node_id or "")
    return list(records)


def build_dashboard_snapshot(collection: MatterCollection) -> dict[str, Any]:
    return {
        "schemaVersion": DASHBOARD_SCHEMA_VERSION,
        "devices": list(collection.devices),
        "diagnostics": list(collection.diagnostics),
        "meshDiagnostics": list(collection.mesh_diagnostics),
        "topology": list(collection.topology),
    }


def make_checkpoint_callback(
    output_paths: Mapping[str, Path], *, show_progress: bool
) -> Callable[[int, int, MatterCollection], None]:
    """Return a best-effort callback for incomplete per-node normalization."""

    def checkpoint(
        completed: int, total: int, collection: MatterCollection
    ) -> None:
        if show_progress:
            print(f"Matter nodes: {completed}/{total}", file=sys.stderr)
        if completed >= total:
            return
        for name, final_path in output_paths.items():
            partial_path = final_path.with_name(create_checkpoint_filename(final_path.name))
            if name == "dashboard":
                payload = {
                    "partial": True,
                    "completed": completed,
                    "total": total,
                    **build_dashboard_snapshot(collection),
                }
            else:
                payload = {
                    "partial": True,
                    "dataset": name,
                    "completed": completed,
                    "total": total,
                    "records": list(getattr(collection, name)),
                }
            try:
                save_json_atomic(
                    payload,
                    partial_path,
                    add_trailing_newline=True,
                )
            except (OSError, TypeError, ValueError):
                logging.warning("Unable to write Matter checkpoint %s", partial_path)

    return checkpoint


def _coverage_summary(diagnostics: Sequence[dict[str, Any]]) -> dict[str, Any]:
    states = (
        "populated",
        "null",
        "attributeUnsupported",
        "readError",
        "implementedEmpty",
        "clusterUnsupported",
    )
    cluster_counts = {state: 0 for state in states}
    attribute_counts = {state: 0 for state in states if state != "clusterUnsupported"}
    for diagnostic in diagnostics:
        coverage = diagnostic.get("diagnosticCoverage")
        if not isinstance(coverage, Mapping):
            continue
        for cluster in coverage.values():
            if not isinstance(cluster, Mapping):
                continue
            cluster_state = cluster.get("cluster")
            if cluster_state in cluster_counts:
                cluster_counts[str(cluster_state)] += 1
            attributes = cluster.get("attributes")
            if not isinstance(attributes, Mapping):
                continue
            for status in attributes.values():
                if status in attribute_counts:
                    attribute_counts[str(status)] += 1
    return {"clusters": cluster_counts, "attributes": attribute_counts}


def _outcome(
    collection: MatterCollection,
    *,
    started_at: str,
    final_paths: Sequence[Path],
) -> dict[str, Any]:
    warnings = []
    errors = []
    for diagnostic in collection.diagnostics:
        detail = diagnostic.get("diagnosticsDetail")
        read_errors = detail.get("readErrors") if isinstance(detail, Mapping) else None
        if isinstance(read_errors, Mapping) and read_errors:
            errors.append(
                {"nodeId": diagnostic.get("nodeId"), "readErrors": dict(read_errors)}
            )
    thread_count = sum(device.get("type") == "threadDevice" for device in collection.devices)
    return {
        "source": "ha-matter-ws",
        "uri": collection.uri,
        "startedAt": started_at,
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "status": "success" if not errors else "success-with-node-errors",
        "messageCount": collection.message_count,
        "nodeCount": collection.node_count,
        "normalizedNodeCount": len(collection.devices),
        "threadCapableCount": thread_count,
        "coverage": _coverage_summary(collection.diagnostics),
        "nodeErrors": errors,
        "warnings": warnings,
        "server": {
            key: collection.server_info.get(key)
            for key in (
                "schema_version",
                "min_supported_schema_version",
                "sdk_version",
            )
        },
        "finalFiles": [path.name for path in final_paths],
    }


def _collection_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "uri": args.uri or build_ha_matter_ws_uri(args.host, args.port),
        "connect_timeout": args.connect_timeout,
        "request_timeout": args.request_timeout,
        "settle_timeout": args.settle_timeout,
    }


def _run(args: argparse.Namespace) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    data_dir = ensure_data_dir_exists(resolve_data_dir(args.datadir))
    path = _command_path(args)
    if path == ("all",) and args.output:
        raise MatterArgumentError("--output is not supported by the all command")
    node_id = getattr(args, "node_id", None)
    if path[-1] == "get" and _node_number(node_id) is None:
        raise MatterArgumentError(f"invalid Matter node id: {node_id}")

    explicit_output: Path | None = None
    if args.output:
        try:
            explicit_output = resolve_data_file_path(args.output, data_dir)
        except ValueError as exc:
            raise MatterArgumentError(str(exc)) from exc

    checkpoint_outputs: dict[str, Path] = {}
    checkpoint_dataset = {
        ("devices", "fetch-all"): "devices",
        ("diagnostics", "fetch-all"): "diagnostics",
        ("mesh-diagnostics", "fetch-all"): "mesh_diagnostics",
        ("topology",): "topology",
        ("dashboard",): "dashboard",
    }.get(path)
    if checkpoint_dataset:
        filename = _fixed_filename(path)
        checkpoint_outputs[checkpoint_dataset] = (
            explicit_output
            if explicit_output is not None
            else resolve_data_file_path(filename or "", data_dir)
        )
    elif path == ("all",):
        checkpoint_outputs = {
            "devices": resolve_data_file_path(
                HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME, data_dir
            ),
            "diagnostics": resolve_data_file_path(
                HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME, data_dir
            ),
            "mesh_diagnostics": resolve_data_file_path(
                HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME, data_dir
            ),
            "topology": resolve_data_file_path(HA_MATTER_WS_TOPOLOGY_FILENAME, data_dir),
            "dashboard": resolve_data_file_path(
                HA_MATTER_WS_DASHBOARD_FILENAME, data_dir
            ),
        }
    progress_callback = (
        make_checkpoint_callback(
            checkpoint_outputs, show_progress=not args.no_progress
        )
        if checkpoint_outputs
        else None
    )
    collection = asyncio.run(
        collect_devices(
            **_collection_kwargs(args), progress_callback=progress_callback
        )
    )
    if len(collection.devices) != collection.node_count:
        raise MatterPartialCollectionError(
            f"normalized {len(collection.devices)} of {collection.node_count} controller nodes"
        )

    if path == ("all",):
        outputs = [
            (
                collection.server_info,
                resolve_data_file_path(HA_MATTER_WS_SERVER_INFO_FILENAME, data_dir),
            ),
            (list(collection.devices), checkpoint_outputs["devices"]),
            (list(collection.diagnostics), checkpoint_outputs["diagnostics"]),
            (
                list(collection.mesh_diagnostics),
                checkpoint_outputs["mesh_diagnostics"],
            ),
            (list(collection.topology), checkpoint_outputs["topology"]),
            (
                build_dashboard_snapshot(collection),
                checkpoint_outputs["dashboard"],
            ),
        ]
        for payload, output_path in outputs:
            save_json_atomic(payload, output_path, add_trailing_newline=True)
        outcome_path = resolve_data_file_path(
            HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME, data_dir
        )
        save_json_atomic(
            _outcome(
                collection,
                started_at=started_at,
                final_paths=[output_path for _, output_path in outputs],
            ),
            outcome_path,
            add_trailing_newline=True,
        )
        return EXIT_OK

    payload = _payload(collection, path, node_id)
    fixed_filename = _fixed_filename(path)
    if explicit_output is not None:
        output_path = explicit_output
    elif fixed_filename:
        output_path = resolve_data_file_path(fixed_filename, data_dir)
    else:
        print(json.dumps(payload, indent=2))
        return EXIT_OK
    save_json_atomic(payload, output_path, add_trailing_newline=True)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_ARGUMENT
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    try:
        return _run(args)
    except asyncio.CancelledError:
        logging.error("Matter collection cancelled")
        return EXIT_CANCELLED
    except MatterWsTransportError as exc:
        logging.error("Matter connection failed: %s", exc)
        return EXIT_CONNECTION
    except MatterWsContractError as exc:
        logging.error("Matter protocol is incompatible: %s", exc)
        return EXIT_PROTOCOL
    except MatterPartialCollectionError as exc:
        logging.error("Matter collection is partial: %s", exc)
        return EXIT_PARTIAL
    except MatterArgumentError as exc:
        logging.error("Invalid Matter command argument: %s", exc)
        return EXIT_ARGUMENT
    except (MatterExtractionError, MatterSnapshotSecurityError, ValueError) as exc:
        logging.error("Matter extraction failed: %s", exc)
        return EXIT_EXTRACTION
    except (OSError, TypeError) as exc:
        logging.error("Matter snapshot persistence failed: %s", exc)
        return EXIT_PERSISTENCE


if __name__ == "__main__":
    raise SystemExit(main())