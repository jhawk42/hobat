from __future__ import annotations

from pathlib import Path

from otbr_cli_networkdiag_parsers import (
    derive_mac_counter_metrics,
    parse_mac_counter_tokens,
    parse_mac_counters,
)
from otbr_restapi_cli import enrich_mac_counters as enrich_camel_mac_counters
from otbr_restapi_diagnostics import enrich_mac_counters
from util_mac_counters import enrich_mac_counters as enrich_raw_mac_counters


LOGS_DIR = Path(__file__).parent / "logs"


def test_parse_mac_counter_tokens_isolates_raw_values() -> None:
    output = """MLE Counters:
    AttachAttempts: 99
MAC Counters:
    IfInErrors: 2
    IfOutErrors: malformed
    IfInUcastPkts: -3
    IfOutDiscards: 1
MLE Counters:
    RouterRole: 7
"""

    assert parse_mac_counter_tokens(output) == {
        "ifinerrors": 2,
        "ifinucastpkts": -3,
        "ifoutdiscards": 1,
    }


def test_parse_mac_counter_tokens_accepts_real_otbr_output() -> None:
    output = (LOGS_DIR / "test_tlvs_7c00.txt").read_text(encoding="utf-8")

    assert parse_mac_counter_tokens(output) == {
        "ifinunknownprotos": 0,
        "ifinerrors": 0,
        "ifouterrors": 1,
        "ifinucastpkts": 534,
        "ifinbroadcastpkts": 591,
        "ifindiscards": 7,
        "ifoutucastpkts": 120,
        "ifoutbroadcastpkts": 116,
        "ifoutdiscards": 1,
    }


def test_derive_mac_counter_metrics_preserves_partial_zero_contract() -> None:
    counters = {"ifinerrors": 2}

    assert derive_mac_counter_metrics(counters) == {
        "ifintotalpkts": 0,
        "ifouttotalpkts": 0,
        "iftotalpkts": 0,
        "iftotalerrors": 2,
        "iftotaldiscards": 0,
        "iftotal_inerrdiscs": 2,
        "iftotal_outerrdiscs": 0,
        "iftotal_errdiscs": 2,
        "ifinerrors_totalinerrdiscs_ratio": 1.0,
        "ifindiscards_totalinerrdiscs_ratio": 0.0,
        "iftotalerrors_totalerrdiscs_ratio": 1.0,
        "iftotaldiscards_totalerrdiscs_ratio": 0.0,
        "ifinerrors_totalerrors_pct": 100.0,
        "ifouterrors_totalerrors_pct": 0.0,
        "ifindiscards_totaldiscards_pct": 0,
        "ifoutdiscards_totaldiscards_pct": 0,
    }
    assert counters == {"ifinerrors": 2}


def test_derive_mac_counter_metrics_preserves_rounding_and_key_presence() -> None:
    counters = {
        "ifinucastpkts": 2,
        "ifinbroadcastpkts": 1,
        "ifoutucastpkts": 3,
        "ifoutbroadcastpkts": 1,
        "ifinerrors": 1,
        "ifouterrors": 2,
        "ifindiscards": 2,
        "ifoutdiscards": 1,
    }

    metrics = derive_mac_counter_metrics(counters)

    assert metrics["ifinerrors_intotalpkts_ratio"] == 0.3
    assert metrics["ifouterrors_outtotalpkts_ratio"] == 0.5
    assert metrics["iftotalerrors_totalpkts_ratio"] == 0.4
    assert metrics["ifindiscards_totaldiscards_pct"] == 66.7
    assert set(metrics) == {
        "ifintotalpkts", "ifouttotalpkts", "iftotalpkts",
        "iftotalerrors", "iftotaldiscards", "iftotal_inerrdiscs",
        "iftotal_outerrdiscs", "iftotal_errdiscs",
        "ifinerrors_totalinerrdiscs_ratio",
        "ifindiscards_totalinerrdiscs_ratio",
        "ifouterrors_totalouterrdiscs_ratio",
        "ifoutdiscards_totalouterrdiscs_ratio",
        "iftotalerrors_totalerrdiscs_ratio",
        "iftotaldiscards_totalerrdiscs_ratio",
        "ifinerrors_intotalpkts_ratio", "ifindiscards_intotalpkts_ratio",
        "ifouterrors_outtotalpkts_ratio", "ifoutdiscards_outtotalpkts_ratio",
        "iftotalerrors_totalpkts_ratio", "iftotaldiscards_totalpkts_ratio",
        "ifinerrors_totalerrors_pct", "ifouterrors_totalerrors_pct",
        "ifindiscards_totaldiscards_pct", "ifoutdiscards_totaldiscards_pct",
    }


def test_mac_discard_ratio_can_exceed_one_across_source_adapters() -> None:
    raw = {
        "ifinucastpkts": 2_930_670,
        "ifindiscards": 21_226_370,
    }
    expected_ratio = 7.2

    raw_enriched = enrich_raw_mac_counters(raw)
    assert raw_enriched["iftotalpkts"] == 2_930_670
    assert raw_enriched["iftotaldiscards_totalpkts_ratio"] == expected_ratio

    cli_enriched = parse_mac_counters(
        "MAC Counters:\n"
        "    IfInUcastPkts: 2930670\n"
        "    IfInDiscards: 21226370\n"
    )
    assert cli_enriched["iftotalpkts"] == 2_930_670
    assert cli_enriched["iftotaldiscards_totalpkts_ratio"] == expected_ratio

    rest_counters = {"ifInUcastPkts": 2_930_670, "ifInDiscards": 21_226_370}
    enrich_mac_counters(rest_counters)
    assert rest_counters["iftotalpkts"] == 2_930_670
    assert rest_counters["iftotaldiscards_totalpkts_ratio"] == expected_ratio

    camel_rest_counters = dict(rest_counters)
    enrich_camel_mac_counters(camel_rest_counters)
    assert camel_rest_counters["ifTotalPkts"] == 2_930_670
    assert camel_rest_counters["ifTotalDiscardsTotalPktsRatio"] == expected_ratio


def test_parse_mac_counters_composes_raw_and_derived_results() -> None:
    output = """MAC Counters:
    IfInUcastPkts: 2
    IfInErrors: 1
"""

    assert parse_mac_counters(output) == {
        "ifinucastpkts": 2,
        "ifinerrors": 1,
        **derive_mac_counter_metrics({"ifinucastpkts": 2, "ifinerrors": 1}),
    }
    assert parse_mac_counters("MLE Counters:\n    RouterRole: 1") == {}


def test_enrich_mac_counters_returns_a_new_dictionary() -> None:
    counters = {"ifinerrors": 1}

    enriched = enrich_raw_mac_counters(counters)

    assert enriched["ifinerrors"] == 1
    assert enriched["iftotalerrors"] == 1
    assert enriched is not counters
    assert counters == {"ifinerrors": 1}


def test_rest_enrichment_reuses_metrics_without_changing_key_contract() -> None:
    mac = {
        "ifInUcastPkts": 2,
        "ifInBroadcastPkts": 1,
        "ifOutUcastPkts": 3,
        "ifOutBroadcastPkts": 1,
        "ifInErrors": 1,
        "ifOutErrors": 2,
        "ifInDiscards": 2,
        "ifOutDiscards": 1,
    }

    enrich_mac_counters(mac)

    assert mac["ifintotalpkts"] == 3
    assert mac["iftotalerrors_totalpkts_ratio"] == 0.4
    assert mac["ifindiscards_totaldiscards_pct"] == 66.7
    assert "ifInTotalPkts" not in mac


def test_camel_rest_enrichment_reuses_metrics_without_changing_key_contract() -> None:
    mac = {
        "ifInUcastPkts": 2,
        "ifInBroadcastPkts": 1,
        "ifOutUcastPkts": 3,
        "ifOutBroadcastPkts": 1,
        "ifInErrors": 1,
        "ifOutErrors": 2,
        "ifInDiscards": 2,
        "ifOutDiscards": 1,
    }

    enrich_camel_mac_counters(mac)

    assert mac["ifInTotalPkts"] == 3
    assert mac["ifTotalErrorsTotalPktsRatio"] == 0.4
    assert mac["ifInDiscardsPercentage"] == 66.7
    assert "ifintotalpkts" not in mac