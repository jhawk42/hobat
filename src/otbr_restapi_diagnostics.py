from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from td_const import (
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
)
from otbr_restapi_util import (
    ActionTimingPolicy,
    BASIC_DIAGNOSTIC_TLVS,
    CHILD_DIAGNOSTIC_TIMING_POLICY,
    DIAGNOSTICS_DEFAULT_POLL_INTERVAL,
    DIAGNOSTICS_DEFAULT_TASK_TIMEOUT,
    FULL_DIAGNOSTIC_TLVS,
    MINIMAL_DIAGNOSTIC_TLVS,
    RECOMMENDED_DIAGNOSTIC_TLVS,
    OTBRActionFailedError,
    OTBRActionTimeoutError,
    OTBRInvalidResponseError,
    OTBRRestApiClient,
    OTBRUsageError,
    emit_rest_command_output,
)
from td_json_key_normalizer import convert_keys_to_camel_case
from td_device_fields import normalize_input_record
from otbr_role_evidence import normalize_otbr_role_record
from td_record_merge import append_merge_conflict
from util_data import (
    CollectionWriteOutcome,
    create_checkpoint_filename,
    save_checkpoint_json,
    save_json_atomic,
)
from util_mac_counters import derive_rest_mac_counter_metrics
import util_network

_MEDIUM_DIAGNOSTIC_TLVS: list[str] = [
    t for t in RECOMMENDED_DIAGNOSTIC_TLVS if t not in {"threadStackVersion", "mleCounters"}
]


def enrich_mac_counters(mac: dict[str, Any]) -> None:
    mac.update(derive_rest_mac_counter_metrics(mac))


def _apply_mac_enrichment(diagnostics: list[Any]) -> list[Any]:
    for record in diagnostics:
        if not isinstance(record, dict):
            continue
        mac = record.get("macCounters")
        if isinstance(mac, dict):
            enrich_mac_counters(mac)
    return diagnostics


def enrich_time_statistics(record: dict[str, Any]) -> None:
    """Enrich a diagnostic record with normalized time_statistics metrics.

    OTBR REST diagnostics expose role-time counters under mleCounters. This
    function derives the same time_statistics fields used by
    parse_time_statistics() for cross-tool consistency.
    """
    stats = record.get("time_statistics")
    if isinstance(stats, dict):
        tracked_time = stats.get("tracked_time", 0)
        disabled_time = stats.get("disabled_time", 0)
        detached_time = stats.get("detached_time", 0)
        child_time = stats.get("child_time", 0)
        router_time = stats.get("router_time", 0)
        leader_time = stats.get("leader_time", 0)
    else:
        time_stats = record.get("timeStatistics")
        if isinstance(time_stats, dict):
            tracked_time = time_stats.get("trackedTime", 0)
            disabled_time = time_stats.get("disabledTime", 0)
            detached_time = time_stats.get("detachedTime", 0)
            child_time = time_stats.get("childTime", 0)
            router_time = time_stats.get("routerTime", 0)
            leader_time = time_stats.get("leaderTime", 0)
        else:
            mle = record.get("mleCounters")
            if not isinstance(mle, dict):
                return
            tracked_time = mle.get("totalTrackingTime", 0)
            disabled_time = mle.get("radioDisabledTime", 0)
            detached_time = mle.get("detachedRoleTime", 0)
            child_time = mle.get("childRoleTime", 0)
            router_time = mle.get("routerRoleTime", 0)
            leader_time = mle.get("leaderRoleTime", 0)

        stats = {
            "tracked_time": tracked_time,
            "disabled_time": disabled_time,
            "detached_time": detached_time,
            "child_time": child_time,
            "router_time": router_time,
            "leader_time": leader_time,
        }
        record["time_statistics"] = stats

    if not isinstance(tracked_time, (int, float)) or tracked_time <= 0:
        return

    detached_disabled_time = detached_time + disabled_time
    stats["detached_disabled_time"] = detached_disabled_time
    stats["detached_disabled_pct"] = round((detached_disabled_time / tracked_time) * 100, 1)
    stats["router_pct"] = round((router_time / tracked_time) * 100, 1)
    stats["child_pct"] = round((child_time / tracked_time) * 100, 1)
    stats["leader_pct"] = round((leader_time / tracked_time) * 100, 1)
    stats["disabled_pct"] = round((disabled_time / tracked_time) * 100, 1)
    stats["detached_pct"] = round((detached_time / tracked_time) * 100, 1)


def _apply_time_stats_enrichment(diagnostics: list[Any]) -> list[Any]:
    """Apply enrich_time_statistics in-place to each diagnostic record."""
    for record in diagnostics:
        if not isinstance(record, dict):
            continue
        enrich_time_statistics(record)
    return diagnostics


def enrich_border_router(record: dict[str, Any]) -> None:
    normalized = normalize_input_record(record, source="rest")
    record.clear()
    record.update(normalized)

    # isRouter 
    rloc16 = record.get("rloc16")
    if isinstance(rloc16, str):
        # check last two bytes of rloc16 for "00" which is a common indicator of routers (including border routers)
        rloc16 = rloc16.lower()
        if rloc16.endswith("00"):
            record["isRouter"] = True
            record["is_router"] = True
            record["role"] = "router"

    addrs = record.get("ipv6Addresses")
    if not isinstance(addrs, list):
        return

    # isBorderRouter - check for presence of border router indicators in IPv6 addresses (e.g., "br" or "border-router" in address labels or types)
    is_border_router = util_network.is_border_router_from_ipv6_addrs(addrs)
    if is_border_router is True:
        if record.get("isBorderRouter") is False:
            append_merge_conflict(record, "isBorderRouter", False, True)
        record["isBorderRouter"] = True
        record["role"] = "border router"

    
def _apply_border_router_enrichment(diagnostics: list[Any]) -> list[Any]:
    """Apply enrich_border_router in-place to each diagnostic record."""
    for record in diagnostics:
        if not isinstance(record, dict):
            continue
        enrich_border_router(record)
    return diagnostics


def _apply_role_evidence_normalization(
    diagnostics: list[Any], *, include_otbr_reed: bool = False
) -> list[Any]:
    for index, record in enumerate(diagnostics):
        if isinstance(record, dict):
            normalized = normalize_input_record(record, source="rest")
            diagnostics[index] = (
                normalize_otbr_role_record(normalized)
                if include_otbr_reed else normalized
            )
    return diagnostics

def make_progress_fn(total: int, enabled: bool):
    if not enabled or total == 0:
        return None

    def _cb(count: int, total_: int, device_id: str, elapsed: float, status: str) -> None:
        print(f"[{count}/{total_}] {device_id} → {status} ({elapsed:.1f}s)", file=sys.stderr)

    return _cb


def _parse_typed_values(values: Sequence[str]) -> list[str | int]:
    parsed: list[str | int] = []
    for value in values:
        try:
            parsed.append(int(value))
        except ValueError:
            parsed.append(value)
    return parsed


def resolve_types(args: argparse.Namespace) -> list[str | int]:
    preset = getattr(args, "preset", None)
    if preset == "recommended":
        return list(RECOMMENDED_DIAGNOSTIC_TLVS)
    if preset == "full":
        return list(FULL_DIAGNOSTIC_TLVS)
    if preset == "minimal":
        return list(MINIMAL_DIAGNOSTIC_TLVS)
    if preset == "basic":
        return list(BASIC_DIAGNOSTIC_TLVS)
    types_raw = getattr(args, "types", None)
    if types_raw:
        return _parse_typed_values(types_raw)
    return list(RECOMMENDED_DIAGNOSTIC_TLVS)


def resolve_fallback_types(args: argparse.Namespace) -> list[str | int] | None:
    if getattr(args, "no_fallback", False):
        return None
    preset = getattr(args, "fallback_preset", None)
    if preset is None:
        return None
    if preset == "medium":
        return list(_MEDIUM_DIAGNOSTIC_TLVS)
    if preset == "basic":
        return list(BASIC_DIAGNOSTIC_TLVS)
    return list(MINIMAL_DIAGNOSTIC_TLVS)


def use_progressive_fallback(args: argparse.Namespace) -> bool:
    return (
        not getattr(args, "no_fallback", False)
        and getattr(args, "fallback_preset", None) is None
        and getattr(args, "types", None) is None
        and getattr(args, "preset", None) in (None, "recommended")
    )


def resolve_child_collection_options(args: argparse.Namespace) -> dict[str, Any]:
    fast_setting = getattr(args, "children_fetch_fast", None)
    detail_setting = getattr(args, "children_fetch_detail", None)
    custom_policy = (
        getattr(args, "types", None) is not None
        or getattr(args, "preset", None) not in (None, "recommended")
        or getattr(args, "fallback_preset", None) is not None
    )
    if (fast_setting is not None or detail_setting is not None) and custom_policy:
        raise OTBRUsageError(
            "Child pass controls apply only to the default/recommended diagnostic policy; "
            "do not combine them with --types, a non-recommended --preset, or --fallback-preset"
        )
    if getattr(args, "no_basic_fallback", False) and custom_policy:
        raise OTBRUsageError(
            "--no-basic-fallback applies only to the default/recommended diagnostic policy"
        )

    task_timeout = getattr(
        args, "task_timeout", DIAGNOSTICS_DEFAULT_TASK_TIMEOUT
    )
    poll_interval = getattr(
        args, "poll_interval", DIAGNOSTICS_DEFAULT_POLL_INTERVAL
    )
    poll_timeout = getattr(args, "poll_timeout", None)
    ActionTimingPolicy.resolve(
        task_timeout=task_timeout,
        poll_interval=poll_interval,
        poll_timeout=poll_timeout,
    )
    child_task_timeout = getattr(
        args,
        "child_task_timeout",
        CHILD_DIAGNOSTIC_TIMING_POLICY.task_timeout,
    )
    child_timing = ActionTimingPolicy.resolve(
        task_timeout=child_task_timeout,
        poll_interval=poll_interval,
        poll_timeout=getattr(args, "child_poll_timeout", None),
    )
    return {
        "policy": "legacy" if custom_policy else "mode-aware",
        "fast": True if fast_setting is None else fast_setting,
        "detail": False if detail_setting is None else detail_setting,
        "retry_enabled": not getattr(args, "no_fallback", False),
        "task_timeout": child_task_timeout,
        "poll_timeout": child_timing.poll_timeout,
    }


def fetch_device_with_fallback(
    client: OTBRRestApiClient,
    device_id: str,
    primary_types: list[str | int],
    fallback_types: list[str | int] | None,
    *,
    destination_type: str,
    task_timeout: int,
    poll_interval: float,
    poll_timeout: float,
    raw: object,
) -> Any:
    try:
        return client.fetch_device_diagnostics(
            device_id,
            types=primary_types,
            destination_type=destination_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raw=raw,
        )
    except (OTBRActionFailedError, OTBRActionTimeoutError):
        if not fallback_types:
            raise
        logging.warning(
            "Device %s failed with primary TLVs; retrying with fallback preset",
            device_id,
        )
        return client.fetch_device_diagnostics(
            device_id,
            types=fallback_types,
            destination_type=destination_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raw=raw,
        )


def fetch_all_with_fallback(
    client: OTBRRestApiClient,
    device_ids: list[str],
    primary_types: list[str | int],
    fallback_types: list[str | int] | None,
    *,
    destination_type: str,
    task_timeout: int,
    poll_interval: float,
    poll_timeout: float,
    raw: object,
    on_progress=None,
    on_checkpoint=None,
) -> list[Any]:
    results: list[Any] = []
    total = len(device_ids)
    for idx, device_id in enumerate(device_ids, start=1):
        t_start = time.monotonic()
        status = "completed"
        try:
            diag = fetch_device_with_fallback(
                client,
                device_id,
                primary_types,
                fallback_types,
                destination_type=destination_type,
                task_timeout=task_timeout,
                poll_interval=poll_interval,
                poll_timeout=poll_timeout,
                raw=raw,
            )
            results.append(diag)
        except (OTBRActionFailedError, OTBRActionTimeoutError, OTBRInvalidResponseError) as exc:
            status = "skipped"
            logging.warning("Skipping device %s: %s", device_id, exc)
        elapsed = time.monotonic() - t_start
        if on_progress is not None:
            on_progress(idx, total, device_id, elapsed, status)
        if on_checkpoint is not None:
            on_checkpoint(results, idx, total, device_id, status)
    return results


def _write_checkpoint_best_effort(
    payload: Any,
    checkpoint_path: Path,
    command_name: str,
    stage: str,
    *,
    raw: bool = False,
) -> None:
    try:
        if raw:
            payload_to_save = payload
        elif isinstance(payload, list):
            payload_to_save = [
                normalize_input_record(record, source="rest")
                if isinstance(record, dict) else record
                for record in payload
            ]
        elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
            payload_to_save = {
                **payload,
                "items": [
                    normalize_input_record(record, source="rest")
                    if isinstance(record, dict) else record
                    for record in payload["items"]
                ],
            }
        else:
            payload_to_save = payload
        save_checkpoint_json(
            payload_to_save if raw else convert_keys_to_camel_case(payload_to_save),
            checkpoint_path,
            CollectionWriteOutcome.partial(has_usable_data=bool(payload)),
            writer=save_json_atomic,
        )
        logging.info(
            "event=checkpoint_write command=%s checkpoint_file=%s records=%d stage=%s",
            command_name,
            checkpoint_path,
            len(payload) if isinstance(payload, list) else 0,
            stage,
        )
    except (OSError, ValueError, TypeError) as exc:
        logging.warning(
            "event=checkpoint_write_failed command=%s checkpoint_file=%s error_type=%s error=%s action=continue_best_effort",
            command_name,
            checkpoint_path,
            type(exc).__name__,
            exc,
        )


def _has_unresolved_iid_skip(outcome: dict[str, Any]) -> bool:
    return any(
        isinstance(result, dict)
        and result.get("skipReasonCode") == "unresolved_mesh_local_iid"
        for result in outcome.get("deviceResults", [])
    )


def _diagnostic_outcome_path(output_path: str | Path) -> Path:
    output_file = Path(output_path)
    if output_file.name == OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME:
        return output_file.with_name(OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME)
    suffix = output_file.suffix
    stem = output_file.name[: -len(suffix)] if suffix else output_file.name
    return output_file.with_name(f"{stem}.outcome{suffix}")


def _write_guard_affected_outcome(
    outcome: dict[str, Any],
    output_path: str | Path,
    *,
    raw: bool,
    command_name: str,
) -> None:
    outcome_file = Path(output_path)
    payload = outcome if raw else convert_keys_to_camel_case(outcome)
    try:
        save_json_atomic(payload, outcome_file)
    except (OSError, TypeError, ValueError) as exc:
        logging.error(
            "event=diagnostic_outcome_write_failed command=%s outcome_file=%s error_type=%s error=%s",
            command_name,
            outcome_file,
            type(exc).__name__,
            exc,
        )
        raise
    logging.info(
        "event=diagnostic_outcome_write command=%s outcome_file=%s",
        command_name,
        outcome_file,
    )


def _dispatch_diagnostics_list(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
    fields: dict[str, str] | None,
    finish: Callable[[Any], Any],
) -> Any:
    diagnostics = client.list_diagnostics(
        fields=fields,
        raw=raw_arg,
        with_meta=args.with_meta,
    )
    if raw_arg is True:
        return finish(diagnostics)

    no_enrich = getattr(args, "no_enrich_mac_counters", False)
    if args.with_meta and isinstance(diagnostics, dict):
        items = diagnostics.get("items")
        if isinstance(items, list):
            if not no_enrich:
                _apply_mac_enrichment(items)
                _apply_time_stats_enrichment(items)
            _apply_border_router_enrichment(items)
            _apply_role_evidence_normalization(items)
        return finish(convert_keys_to_camel_case(diagnostics))

    if isinstance(diagnostics, list):
        if not no_enrich:
            _apply_mac_enrichment(diagnostics)
            _apply_time_stats_enrichment(diagnostics)
        _apply_border_router_enrichment(diagnostics)
        _apply_role_evidence_normalization(diagnostics)
    return finish(convert_keys_to_camel_case(diagnostics))


def _dispatch_diagnostics_get(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
    finish: Callable[[Any], Any],
) -> Any:
    result = client.get_diagnostic(args.diagnostics_id, raw=raw_arg)
    if raw_arg is True or not isinstance(result, dict):
        return finish(result)
    result = normalize_input_record(result, source="rest")
    _apply_border_router_enrichment([result])
    return finish(convert_keys_to_camel_case(result))


def _dispatch_diagnostics_fetch(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
    finish: Callable[[Any], Any],
) -> Any:
    primary_types = resolve_types(args)
    fallback_types = resolve_fallback_types(args)
    result = fetch_device_with_fallback(
        client,
        args.device_id,
        primary_types,
        fallback_types,
        destination_type=args.destination_type,
        task_timeout=args.task_timeout,
        poll_interval=args.poll_interval,
        poll_timeout=args.poll_timeout,
        raw=raw_arg,
    )
    if raw_arg is True:
        return finish(result)
    if not getattr(args, "no_enrich_mac_counters", False):
        _apply_mac_enrichment([result])
    if isinstance(result, dict):
        _apply_border_router_enrichment([result])
        result = normalize_input_record(result, source="rest")
    return finish(convert_keys_to_camel_case(result))


def _dispatch_diagnostics_fetch_all(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
    finish: Callable[..., Any],
    output_path: str | Path | None,
) -> Any:
    resolved_types = resolve_types(args)
    fallback_types = resolve_fallback_types(args)
    progressive_fallback = use_progressive_fallback(args)
    no_basic_fallback = getattr(args, "no_basic_fallback", False)
    child_options = resolve_child_collection_options(args)
    do_enrich = not getattr(args, "no_enrich_mac_counters", False)
    do_update = not getattr(args, "no_update_devices", False)
    logging.info(
        "Diagnostic child policy=%s, MTD fast=%s, MTD detail=%s, child retry=%s",
        child_options["policy"],
        child_options["fast"],
        child_options["detail"],
        child_options["retry_enabled"],
    )

    if do_update:
        devices = client.fetch_device_collection(
            device_count=getattr(args, "device_count", 255),
            items_only=True,
        )
    else:
        devices = client.list_devices(raw=False)

    requested_device_ids = getattr(args, "device_ids", None)
    if requested_device_ids:
        devices_by_id = {
            device["id"].lower(): device
            for device in devices
            if isinstance(device, dict)
            and isinstance(device.get("id"), str)
        }
        selected_devices = [
            devices_by_id.get(device_id.lower(), device_id)
            if isinstance(device_id, str)
            else device_id
            for device_id in requested_device_ids
        ]
    else:
        selected_devices = devices

    checkpoint_path = None
    if output_path:
        output_file = Path(output_path)
        checkpoint_path = output_file.parent / create_checkpoint_filename(
            output_file.name
        )

    def _write_checkpoint(results, stage):
        if checkpoint_path is None:
            return
        if raw_arg is not True:
            _apply_role_evidence_normalization(
                results, include_otbr_reed=True
            )
            _apply_border_router_enrichment(results)
        _write_checkpoint_best_effort(
            results,
            checkpoint_path,
            "otbr-restapi diagnostics fetch-all",
            stage,
            raw=raw_arg is True,
        )

    def _on_checkpoint(results, _idx, _total, _device_id, _status):
        _write_checkpoint(results, "device")

    def _on_pass_checkpoint(
        results, _idx, _total, _device_id, pass_name
    ):
        _write_checkpoint(results, f"pass:{pass_name}")

    progress_fn = make_progress_fn(
        len(selected_devices), not getattr(args, "no_progress", False)
    )
    outcome = client.fetch_all_devices_diagnostics(
        selected_devices,
        types=resolved_types,
        destination_type=args.destination_type,
        task_timeout=args.task_timeout,
        poll_interval=args.poll_interval,
        poll_timeout=args.poll_timeout,
        clear_diagnostics=not getattr(args, "preserve_diagnostics", False),
        fallback_types=fallback_types,
        progressive_fallback=progressive_fallback,
        include_basic_fallback=not no_basic_fallback,
        child_collection_policy=child_options["policy"],
        children_fetch_fast=child_options["fast"],
        children_fetch_detail=child_options["detail"],
        child_retry_enabled=child_options["retry_enabled"],
        child_task_timeout=child_options["task_timeout"],
        child_poll_timeout=child_options["poll_timeout"],
        raw=raw_arg,
        on_progress=progress_fn,
        on_checkpoint=_on_checkpoint,
        on_pass_checkpoint=_on_pass_checkpoint,
    )
    guard_affected = _has_unresolved_iid_skip(outcome)
    if guard_affected and output_path is not None:
        _write_guard_affected_outcome(
            outcome,
            _diagnostic_outcome_path(output_path),
            raw=raw_arg is True,
            command_name="otbr-restapi diagnostics fetch-all",
        )
    diagnostics = outcome["items"]
    if raw_arg is not True:
        if do_enrich:
            _apply_mac_enrichment(diagnostics)
            _apply_time_stats_enrichment(diagnostics)
        _apply_role_evidence_normalization(
            diagnostics, include_otbr_reed=True
        )
        _apply_border_router_enrichment(diagnostics)
    if raw_arg is True:
        if getattr(args, "items_only", False):
            payload = diagnostics
        else:
            payload = outcome
    else:
        if getattr(args, "items_only", False):
            payload = convert_keys_to_camel_case(diagnostics)
        else:
            payload = convert_keys_to_camel_case(outcome)
    preserve_prior_dataset = guard_affected and not diagnostics
    if preserve_prior_dataset:
        logging.warning(
            "OTBR REST diagnostics fetch-all produced no diagnostics for an "
            "unresolved-IID skip; retaining the prior dataset at %s",
            output_path if output_path is not None else "(no output path resolved)",
        )
    return finish(payload, write=not preserve_prior_dataset)


def dispatch_diagnostics(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
    fields: dict[str, str] | None,
) -> Any:
    output_path = getattr(args, "resolved_output_path", None)

    def finish(result: Any, *, write: bool = True) -> Any:
        if not write:
            return result
        if raw_arg is True:
            return emit_rest_command_output(
                result, output_path, logger=logging.getLogger(__name__), raw=True
            )
        return emit_rest_command_output(
            result, output_path, logger=logging.getLogger(__name__)
        )

    if args.diagnostics_command == "list":
        return _dispatch_diagnostics_list(client, args, raw_arg, fields, finish)
    if args.diagnostics_command == "get":
        return _dispatch_diagnostics_get(client, args, raw_arg, finish)
    if args.diagnostics_command == "fetch":
        return _dispatch_diagnostics_fetch(client, args, raw_arg, finish)
    if args.diagnostics_command == "fetch-all":
        return _dispatch_diagnostics_fetch_all(
            client, args, raw_arg, finish, output_path
        )

    raise ValueError("Unsupported diagnostics command")
