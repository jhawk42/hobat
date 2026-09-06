from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

from otbr_restapi_diagnostics import make_progress_fn
from td_json_key_normalizer import convert_keys_to_camel_case
from util_data import create_checkpoint_filename, save_json_atomic
from otbr_restapi_util import (
    DIAG_TLV_CHILDREN,
    DIAG_TLV_CHILD_IPV6_ADDRS,
    DIAG_TLV_ROUTER_NEIGHBORS,
    DestinationType,
    MESH_DIAGNOSTIC_TLVS,
    OTBRRestApiClient,
    OTBRUsageError,
    emit_rest_command_output,
)

CLI_MESH_TASK_TIMEOUT_DEFAULT = 15
ROUTER_RLOC16_MASK = 0x03FF
ROUTER_RLOC16_VALUE = 0


def _write_checkpoint_best_effort(payload: Any, checkpoint_path: Path) -> None:
    try:
        save_json_atomic(convert_keys_to_camel_case(payload), checkpoint_path)
        logging.info(
            "event=checkpoint_write command=otbr-restapi mesh-diagnostics fetch-all checkpoint_file=%s records=%d stage=device",
            checkpoint_path,
            len(payload) if isinstance(payload, list) else 0,
        )
    except (OSError, ValueError, TypeError) as exc:
        logging.warning(
            "event=checkpoint_write_failed command=otbr-restapi mesh-diagnostics fetch-all checkpoint_file=%s error_type=%s error=%s action=continue_best_effort",
            checkpoint_path,
            type(exc).__name__,
            exc,
        )


def filter_router_device_ids(devices: list[Any], device_ids: list[str]) -> list[str]:
    rloc16_by_id: dict[str, int] = {}
    for device in devices:
        if not isinstance(device, dict):
            continue
        dev_id = device.get("id")
        rloc16_raw = device.get("rloc16")
        if dev_id is None or rloc16_raw is None:
            continue
        try:
            rloc16_by_id[dev_id] = int(rloc16_raw, 16) if isinstance(rloc16_raw, str) else int(rloc16_raw)
        except (ValueError, TypeError):
            pass

    result: list[str] = []
    for dev_id in device_ids:
        rloc16 = rloc16_by_id.get(dev_id)
        if rloc16 is None or (rloc16 & ROUTER_RLOC16_MASK) == ROUTER_RLOC16_VALUE:
            result.append(dev_id)
    return result


def parse_mesh_diag_types(types: list[str]) -> list[str]:
    invalid = [value for value in types if value not in MESH_DIAGNOSTIC_TLVS]
    if invalid:
        raise OTBRUsageError(
            f"Invalid mesh-diagnostic TLV(s): {invalid!r}. Allowed: {sorted(MESH_DIAGNOSTIC_TLVS)!r}"
        )
    if not types:
        raise OTBRUsageError("At least one mesh-diagnostic TLV must be specified")
    return types


def dispatch_mesh_diagnostics(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
) -> Any:
    cmd = args.mesh_diag_command
    poll_timeout = args.poll_timeout
    poll_interval = args.poll_interval
    dest_type = args.destination_type
    task_timeout = args.task_timeout
    output_path = getattr(args, "resolved_output_path", None)

    def finish(result: Any) -> Any:
        return emit_rest_command_output(result, output_path, logger=logging.getLogger(__name__))

    if cmd == "children":
        return finish(client.fetch_mesh_diagnostics(
            args.device_id,
            types=[DIAG_TLV_CHILDREN],
            destination_type=dest_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raw=raw_arg,
        ))
    if cmd == "child-ipv6":
        return finish(client.fetch_mesh_diagnostics(
            args.device_id,
            types=[DIAG_TLV_CHILD_IPV6_ADDRS],
            destination_type=dest_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raw=raw_arg,
        ))
    if cmd == "router-neighbors":
        return finish(client.fetch_mesh_diagnostics(
            args.device_id,
            types=[DIAG_TLV_ROUTER_NEIGHBORS],
            destination_type=dest_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raw=raw_arg,
        ))
    if cmd == "fetch":
        types = parse_mesh_diag_types(args.types or list(MESH_DIAGNOSTIC_TLVS))
        return finish(client.fetch_mesh_diagnostics(
            args.device_id,
            types=types,
            destination_type=dest_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raw=raw_arg,
        ))
    if cmd == "fetch-all":
        types = parse_mesh_diag_types(args.types or list(MESH_DIAGNOSTIC_TLVS))
        do_update = not getattr(args, "no_update_devices", False)
        routers_only = getattr(args, "routers_only", False)

        if do_update:
            devices = client.fetch_device_collection(items_only=True)
        else:
            devices = client.list_devices(raw=False)

        device_ids = getattr(args, "device_ids", None) or [
            d["id"] for d in devices if isinstance(d, dict) and d.get("id")
        ]
        if routers_only:
            device_ids = filter_router_device_ids(devices, device_ids)
            logging.info(
                "--routers-only: %d router device(s) selected from device list",
                len(device_ids),
            )

        checkpoint_path = None
        if output_path:
            output_file = Path(output_path)
            checkpoint_path = output_file.parent / create_checkpoint_filename(
                output_file.name
            )

        def _on_checkpoint(results, _idx, _total, _device_id, _status):
            if checkpoint_path is None:
                return
            _write_checkpoint_best_effort(results, checkpoint_path)

        progress_fn = make_progress_fn(len(device_ids), not getattr(args, "no_progress", False))
        outcome = client.fetch_mesh_diagnostics_all_devices(
            device_ids,
            types=types,
            destination_type=dest_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            clear_diagnostics=not getattr(args, "preserve_diagnostics", False),
            progressive_fallback=not getattr(args, "no_fallback", False),
            on_progress=progress_fn,
            on_checkpoint=_on_checkpoint,
            raw=raw_arg,
        )
        if getattr(args, "items_only", False):
            return finish(outcome["items"])
        return finish(outcome)

    raise ValueError("Unsupported mesh-diagnostics command")
