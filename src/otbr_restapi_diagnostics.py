from __future__ import annotations

import argparse
import logging
import sys
import time
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
)
from td_json_key_normalizer import convert_keys_to_camel_case
import util_network

_MEDIUM_DIAGNOSTIC_TLVS: list[str] = [
    t for t in RECOMMENDED_DIAGNOSTIC_TLVS if t not in {"threadStackVersion", "mleCounters"}
]


def enrich_mac_counters(mac: dict[str, Any]) -> None:
    in_ucast = mac.get("ifInUcastPkts", 0)
    in_bcast = mac.get("ifInBroadcastPkts", 0)
    out_ucast = mac.get("ifOutUcastPkts", 0)
    out_bcast = mac.get("ifOutBroadcastPkts", 0)
    in_errors = mac.get("ifInErrors", 0)
    out_errors = mac.get("ifOutErrors", 0)
    in_disc = mac.get("ifInDiscards", 0)
    out_disc = mac.get("ifOutDiscards", 0)

    ifintotalpkts = in_ucast + in_bcast
    ifouttotalpkts = out_ucast + out_bcast
    iftotalpkts = ifintotalpkts + ifouttotalpkts
    totalerrors = in_errors + out_errors
    totaldiscards = in_disc + out_disc

    mac["ifintotalpkts"] = ifintotalpkts
    mac["ifouttotalpkts"] = ifouttotalpkts
    mac["iftotalpkts"] = iftotalpkts
    mac["iftotalerrors"] = totalerrors
    mac["iftotaldiscards"] = totaldiscards

    iftotal_inerrdiscs = in_errors + in_disc
    iftotal_outerrdiscs = out_errors + out_disc
    iftotal_errdiscs = totalerrors + totaldiscards

    mac["iftotal_inerrdiscs"] = iftotal_inerrdiscs
    mac["iftotal_outerrdiscs"] = iftotal_outerrdiscs
    mac["iftotal_errdiscs"] = iftotal_errdiscs

    if iftotal_inerrdiscs > 0:
        mac["ifinerrors_totalinerrdiscs_ratio"] = round(in_errors / iftotal_inerrdiscs, 1)
        mac["ifindiscards_totalinerrdiscs_ratio"] = round(in_disc / iftotal_inerrdiscs, 1)
    if iftotal_outerrdiscs > 0:
        mac["ifouterrors_totalouterrdiscs_ratio"] = round(out_errors / iftotal_outerrdiscs, 1)
        mac["ifoutdiscards_totalouterrdiscs_ratio"] = round(out_disc / iftotal_outerrdiscs, 1)
    if iftotal_errdiscs > 0:
        mac["iftotalerrors_totalerrdiscs_ratio"] = round(totalerrors / iftotal_errdiscs, 1)
        mac["iftotaldiscards_totalerrdiscs_ratio"] = round(totaldiscards / iftotal_errdiscs, 1)

    if ifintotalpkts > 0:
        mac["ifinerrors_intotalpkts_ratio"] = round(in_errors / ifintotalpkts, 1)
        mac["ifindiscards_intotalpkts_ratio"] = round(in_disc / ifintotalpkts, 1)
    if ifouttotalpkts > 0:
        mac["ifouterrors_outtotalpkts_ratio"] = round(out_errors / ifouttotalpkts, 1)
        mac["ifoutdiscards_outtotalpkts_ratio"] = round(out_disc / ifouttotalpkts, 1)
    if iftotalpkts > 0:
        mac["iftotalerrors_totalpkts_ratio"] = round(totalerrors / iftotalpkts, 1)
        mac["iftotaldiscards_totalpkts_ratio"] = round(totaldiscards / iftotalpkts, 1)

    mac["ifinerrors_totalerrors_pct"] = round((in_errors / totalerrors) * 100, 1) if totalerrors > 0 else 0
    mac["ifouterrors_totalerrors_pct"] = round((out_errors / totalerrors) * 100, 1) if totalerrors > 0 else 0
    mac["ifindiscards_totaldiscards_pct"] = round((in_disc / totaldiscards) * 100, 1) if totaldiscards > 0 else 0
    mac["ifoutdiscards_totaldiscards_pct"] = round((out_disc / totaldiscards) * 100, 1) if totaldiscards > 0 else 0


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
    preset = getattr(args, "fallback_preset", "minimal")
    if preset == "medium":
        return list(_MEDIUM_DIAGNOSTIC_TLVS)
    if preset == "basic":
        return list(BASIC_DIAGNOSTIC_TLVS)
    return list(MINIMAL_DIAGNOSTIC_TLVS)


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
    return results


def dispatch_diagnostics(
    client: OTBRRestApiClient,
    args: argparse.Namespace,
    raw_arg: object,
    fields: dict[str, str] | None,
) -> Any:
    if args.diagnostics_command == "list":
        diagnostics = client.list_diagnostics(
            fields=fields,
            raw=raw_arg,
            with_meta=args.with_meta,
        )
        if raw_arg is True or getattr(args, "no_enrich_mac_counters", False):
            return diagnostics

        if args.with_meta and isinstance(diagnostics, dict):
            items = diagnostics.get("items")
            if isinstance(items, list):
                _apply_mac_enrichment(items)
                _apply_time_stats_enrichment(items)
                _apply_border_router_enrichment(items)
            return convert_keys_to_camel_case(diagnostics)

        if isinstance(diagnostics, list):
            _apply_mac_enrichment(diagnostics)
            _apply_time_stats_enrichment(diagnostics)
            _apply_border_router_enrichment(diagnostics)
        return convert_keys_to_camel_case(diagnostics)
    if args.diagnostics_command == "get":
        return client.get_diagnostic(args.diagnostics_id, raw=raw_arg)
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
        return convert_keys_to_camel_case(result)
    if args.diagnostics_command == "fetch-all":
        resolved_types = resolve_types(args)
        fallback_types = resolve_fallback_types(args)
        do_enrich = not getattr(args, "no_enrich_mac_counters", False)
        do_update = not getattr(args, "no_update_devices", False)

        if do_update:
            devices = client.fetch_device_collection(device_count=getattr(args, "device_count", 255))
        else:
            devices = client.list_devices(raw=False)

        device_ids = getattr(args, "device_ids", None) or [
            d["id"] for d in devices if isinstance(d, dict) and d.get("id")
        ]
        progress_fn = make_progress_fn(len(device_ids), not getattr(args, "no_progress", False))
        diagnostics = fetch_all_with_fallback(
            client,
            device_ids,
            resolved_types,
            fallback_types,
            destination_type=args.destination_type,
            task_timeout=args.task_timeout,
            poll_interval=args.poll_interval,
            poll_timeout=args.poll_timeout,
            raw=raw_arg,
            on_progress=progress_fn,
        )
        if do_enrich:
            _apply_mac_enrichment(diagnostics)
            _apply_time_stats_enrichment(diagnostics)
            _apply_border_router_enrichment(diagnostics)
        return convert_keys_to_camel_case(diagnostics)

    raise ValueError("Unsupported diagnostics command")
