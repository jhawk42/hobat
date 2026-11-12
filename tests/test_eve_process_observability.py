from __future__ import annotations

import json
import logging
import pytest

import eve_process
import util_data


@pytest.mark.parametrize("legacy_only", [False, True])
def test_eve_omr_enrichment_requires_full_observed_cidr(tmp_path, monkeypatch, legacy_only):
    address = "fda5:494c:9a12::1234"
    source = tmp_path / "eve.json"
    source.write_text(json.dumps({"nodes": [{"id": "one", "rloc16": 7, "ip_addresses": [address]}]}))
    info = {"prefix_omr_ipv6addr_prefix": "fda5:494c:9a12:0"}
    if not legacy_only:
        info["prefix_omr"] = "fda5:494c:9a12:0::/64"
    monkeypatch.setattr(eve_process.util_network, "fetch_omr_prefix", lambda: pytest.fail("unexpected network query"))
    result = eve_process.load_and_parse_eve_file(source, info)
    assert result["one"].get("omrIpv6Address") == (None if legacy_only else address)
    assert info["prefix_omr_ipv6addr_prefix"] == "fda5:494c:9a12:0"


def test_eve_enrichment_counts_each_decision_branch_exclusively(
    monkeypatch, tmp_path, caplog
) -> None:
    source = tmp_path / "eve.json"
    source.write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "existing", "rloc16": 7},
                    {"id": "both-missing"},
                    {"id": "missing-addresses", "ip_addresses": []},
                    {"id": "no-match", "ip_addresses": ["fd00::2"]},
                    {"id": "extracted", "ip_addresses": ["fd00::3"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    extracted_rlocs = iter((None, "0x1234"))
    monkeypatch.setattr(
        eve_process.util_network,
        "extract_rloc16_from_ipv6_addresses_cached",
        lambda addresses, prefix: next(extracted_rlocs),
    )
    observed = {}

    parsed = eve_process.load_and_parse_eve_file(
        source,
        {
            "prefix_omr_ipv6addr_prefix": None,
            "prefix_meshlocal_ipv6addr_prefix": "fd00::/64",
        },
        enrichment_summary_callback=observed.update,
    )

    assert set(parsed) == {
        "existing",
        "both-missing",
        "missing-addresses",
        "no-match",
        "extracted",
    }
    assert observed == {
        "nodes": 5,
        "existing_rloc": 1,
        "extracted_rloc": 1,
        "missing_prefix": 0,
        "missing_addresses": 2,
        "no_matching_rloc": 1,
    }
    assert "No valid RLOC16 found" in caplog.text


def test_missing_prefix_takes_priority_when_addresses_are_also_missing(
    monkeypatch, tmp_path
) -> None:
    source = tmp_path / "eve.json"
    source.write_text(json.dumps({"nodes": [{"id": "both-missing"}]}), encoding="utf-8")
    observed = {}

    eve_process.load_and_parse_eve_file(
        source,
        {"prefix_meshlocal_ipv6addr_prefix": None},
        enrichment_summary_callback=observed.update,
    )

    assert observed["missing_prefix"] == 1
    assert observed["missing_addresses"] == 0
    assert observed["no_matching_rloc"] == 0


def test_scope_companion_failure_is_reported_after_topology_snapshot_write(
    monkeypatch, tmp_path
) -> None:
    input_path = eve_process.data_file_path(
        eve_process.EVE_NATIVE_LAYOUT_FILENAME, tmp_path
    )
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps({"nodes": [{"id": "one"}]}), encoding="utf-8")
    events = []
    monkeypatch.setattr(
        eve_process.util_network,
        "fetch_thread_network_info",
        lambda: {"prefix_meshlocal_ipv6addr_prefix": None},
    )
    def fail_scope_write(*args, **kwargs):
        raise OSError("companion failed")

    monkeypatch.setattr(util_data, "write_network_scope", fail_scope_write)
    monkeypatch.setattr(
        eve_process,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    assert eve_process.main(["--datadir", str(tmp_path)]) == 3

    output_path = eve_process.data_file_path(eve_process.EVE_TOPOLOGY_FILENAME, tmp_path)
    assert output_path.exists()
    summary = next(fields for event, fields in events if event == "collector_summary")
    assert summary["rloc_skipped"] == 1
    assert summary["missing_prefix"] == 1
    assert summary["records"] == 1
    writes = [fields for event, fields in events if event == "write"]
    assert len(writes) == 1
    assert writes[0]["disposition"] == "failed"


def test_retained_topology_result_is_not_logged_as_saved(monkeypatch, tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO)
    input_path = eve_process.data_file_path(
        eve_process.EVE_NATIVE_LAYOUT_FILENAME, tmp_path
    )
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps({"nodes": [{"id": "one"}]}), encoding="utf-8")
    events = []
    monkeypatch.setattr(
        eve_process.util_network,
        "fetch_thread_network_info",
        lambda: {"prefix_meshlocal_ipv6addr_prefix": None},
    )
    monkeypatch.setattr(eve_process, "save_final_json", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        eve_process,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    assert eve_process.main(["--datadir", str(tmp_path)]) == 0

    writes = [fields for event, fields in events if event == "write"]
    assert writes[0]["disposition"] == "retained_previous"
    assert "Retained previous eve topology data" in caplog.text
    assert "Saved eve topology data" not in caplog.text
