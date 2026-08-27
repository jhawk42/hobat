"""Shared derivation policy for Thread MAC counters."""

from __future__ import annotations

from collections.abc import Mapping


REST_MAC_COUNTER_FIELDS: Mapping[str, str] = {
    "ifinucastpkts": "ifInUcastPkts",
    "ifinbroadcastpkts": "ifInBroadcastPkts",
    "ifoutucastpkts": "ifOutUcastPkts",
    "ifoutbroadcastpkts": "ifOutBroadcastPkts",
    "ifinerrors": "ifInErrors",
    "ifouterrors": "ifOutErrors",
    "ifindiscards": "ifInDiscards",
    "ifoutdiscards": "ifOutDiscards",
}


def derive_mac_counter_metrics(
    counters: Mapping[str, int],
) -> dict[str, int | float]:
    """Return legacy snake_case metrics derived from raw MAC counters."""
    in_total_packets = counters.get("ifinucastpkts", 0) + counters.get(
        "ifinbroadcastpkts", 0
    )
    out_total_packets = counters.get("ifoutucastpkts", 0) + counters.get(
        "ifoutbroadcastpkts", 0
    )
    total_packets = in_total_packets + out_total_packets
    in_errors = counters.get("ifinerrors", 0)
    out_errors = counters.get("ifouterrors", 0)
    in_discards = counters.get("ifindiscards", 0)
    out_discards = counters.get("ifoutdiscards", 0)
    total_errors = in_errors + out_errors
    total_discards = in_discards + out_discards
    in_error_discards = in_errors + in_discards
    out_error_discards = out_errors + out_discards
    total_error_discards = total_errors + total_discards

    metrics: dict[str, int | float] = {
        "ifintotalpkts": in_total_packets,
        "ifouttotalpkts": out_total_packets,
        "iftotalpkts": total_packets,
        "iftotalerrors": total_errors,
        "iftotaldiscards": total_discards,
        "iftotal_inerrdiscs": in_error_discards,
        "iftotal_outerrdiscs": out_error_discards,
        "iftotal_errdiscs": total_error_discards,
    }

    if in_error_discards > 0:
        metrics["ifinerrors_totalinerrdiscs_ratio"] = round(
            in_errors / in_error_discards, 1
        )
        metrics["ifindiscards_totalinerrdiscs_ratio"] = round(
            in_discards / in_error_discards, 1
        )
    if out_error_discards > 0:
        metrics["ifouterrors_totalouterrdiscs_ratio"] = round(
            out_errors / out_error_discards, 1
        )
        metrics["ifoutdiscards_totalouterrdiscs_ratio"] = round(
            out_discards / out_error_discards, 1
        )
    if total_error_discards > 0:
        metrics["iftotalerrors_totalerrdiscs_ratio"] = round(
            total_errors / total_error_discards, 1
        )
        metrics["iftotaldiscards_totalerrdiscs_ratio"] = round(
            total_discards / total_error_discards, 1
        )

    if in_total_packets > 0:
        metrics["ifinerrors_intotalpkts_ratio"] = round(
            in_errors / in_total_packets, 1
        )
        metrics["ifindiscards_intotalpkts_ratio"] = round(
            in_discards / in_total_packets, 1
        )
    if out_total_packets > 0:
        metrics["ifouterrors_outtotalpkts_ratio"] = round(
            out_errors / out_total_packets, 1
        )
        metrics["ifoutdiscards_outtotalpkts_ratio"] = round(
            out_discards / out_total_packets, 1
        )
    if total_packets > 0:
        metrics["iftotalerrors_totalpkts_ratio"] = round(
            total_errors / total_packets, 1
        )
        metrics["iftotaldiscards_totalpkts_ratio"] = round(
            total_discards / total_packets, 1
        )

    metrics["ifinerrors_totalerrors_pct"] = (
        round((in_errors / total_errors) * 100, 1) if total_errors > 0 else 0
    )
    metrics["ifouterrors_totalerrors_pct"] = (
        round((out_errors / total_errors) * 100, 1) if total_errors > 0 else 0
    )
    metrics["ifindiscards_totaldiscards_pct"] = (
        round((in_discards / total_discards) * 100, 1) if total_discards > 0 else 0
    )
    metrics["ifoutdiscards_totaldiscards_pct"] = (
        round((out_discards / total_discards) * 100, 1) if total_discards > 0 else 0
    )
    return metrics


def enrich_mac_counters(
    counters: Mapping[str, int],
) -> dict[str, int | float]:
    """Return a new dictionary containing raw counters and derived metrics."""
    return {**counters, **derive_mac_counter_metrics(counters)}


def derive_rest_mac_counter_metrics(
    counters: Mapping[str, int],
) -> dict[str, int | float]:
    """Adapt equivalent REST camelCase counters to the shared metric policy."""
    raw_counters = {
        raw_key: counters.get(rest_key, 0)
        for raw_key, rest_key in REST_MAC_COUNTER_FIELDS.items()
    }
    return derive_mac_counter_metrics(raw_counters)