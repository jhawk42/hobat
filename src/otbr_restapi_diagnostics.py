from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from otbr_restapi_util import (
    BASIC_DIAGNOSTIC_TLVS,
    FULL_DIAGNOSTIC_TLVS,
    MINIMAL_DIAGNOSTIC_TLVS,
    RECOMMENDED_DIAGNOSTIC_TLVS,
    OTBRActionFailedError,
    OTBRActionTimeoutError,
    OTBRInvalidResponseError,
    OTBRRestApiClient,
    emit_rest_command_output,
)
from td_json_key_normalizer import convert_keys_to_camel_case
from util_data import create_checkpoint_filename, save_json_atomic
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
    if is_border_router is not None:
        if is_border_router:
            record["isBorderRouter"] = True
            record["is_border_router"] = True
            record["role"] = "border router"
            record["br"] = True

    
def _apply_border_router_enrichment(diagnostics: list[Any]) -> list[Any]:
    """Apply enrich_border_router in-place to each diagnostic record."""
    for record in diagnostics:
        if not isinstance(record, dict):
            continue
        enrich_border_router(record)
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
) -> None:
    try:
        save_json_atomic(convert_keys_to_camel_case(payload), checkpoint_path)
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


def dispatch_diagnostics(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
    fields: dict[str, str] | None,
) -> Any:
    output_path = getattr(args, "resolved_output_path", None)

    def finish(result: Any) -> Any:
        return emit_rest_command_output(result, output_path, logger=logging.getLogger(__name__))

    if args.diagnostics_command == "list":
        diagnostics = client.list_diagnostics(
            fields=fields,
            raw=raw_arg,
            with_meta=args.with_meta,
        )
        if raw_arg is True or getattr(args, "no_enrich_mac_counters", False):
            return finish(diagnostics)

        if args.with_meta and isinstance(diagnostics, dict):
            items = diagnostics.get("items")
            if isinstance(items, list):
                _apply_mac_enrichment(items)
                _apply_time_stats_enrichment(items)
                _apply_border_router_enrichment(items)
            return finish(convert_keys_to_camel_case(diagnostics))

        if isinstance(diagnostics, list):
            _apply_mac_enrichment(diagnostics)
            _apply_time_stats_enrichment(diagnostics)
            _apply_border_router_enrichment(diagnostics)
        return finish(convert_keys_to_camel_case(diagnostics))
    if args.diagnostics_command == "get":
        return finish(client.get_diagnostic(args.diagnostics_id, raw=raw_arg))
    if args.diagnostics_command == "fetch":
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
        if not getattr(args, "no_enrich_mac_counters", False):
            _apply_mac_enrichment([result])
        return finish(convert_keys_to_camel_case(result))
    if args.diagnostics_command == "fetch-all":
        resolved_types = resolve_types(args)
        fallback_types = resolve_fallback_types(args)
        do_enrich = not getattr(args, "no_enrich_mac_counters", False)
        do_update = not getattr(args, "no_update_devices", False)

        if do_update:
            devices = client.fetch_device_collection(
                device_count=getattr(args, "device_count", 255),
                items_only=True,
            )
        else:
            devices = client.list_devices(raw=False)

        selected_devices = getattr(args, "device_ids", None) or devices

        checkpoint_path = None
        if output_path:
            output_file = Path(output_path)
            checkpoint_path = output_file.parent / create_checkpoint_filename(
                output_file.name
            )

        def _on_checkpoint(results, _idx, _total, _device_id, _status):
            if checkpoint_path is None:
                return
            _write_checkpoint_best_effort(
                results,
                checkpoint_path,
                "otbr-restapi diagnostics fetch-all",
                "device",
            )

        progress_fn = make_progress_fn(len(selected_devices), not getattr(args, "no_progress", False))
        outcome = client.fetch_all_devices_diagnostics(
            selected_devices,
            types=resolved_types,
            destination_type=args.destination_type,
            task_timeout=args.task_timeout,
            poll_interval=args.poll_interval,
            poll_timeout=args.poll_timeout,
            clear_diagnostics=not getattr(args, "preserve_diagnostics", False),
            fallback_types=fallback_types,
            progressive_fallback=use_progressive_fallback(args),
            raw=raw_arg,
            on_progress=progress_fn,
            on_checkpoint=_on_checkpoint,
        )
        diagnostics = outcome["items"]
        if do_enrich:
            _apply_mac_enrichment(diagnostics)
            _apply_time_stats_enrichment(diagnostics)
            _apply_border_router_enrichment(diagnostics)
        if getattr(args, "items_only", False):
            return finish(convert_keys_to_camel_case(diagnostics))
        return finish(convert_keys_to_camel_case(outcome))

    raise ValueError("Unsupported diagnostics command")
