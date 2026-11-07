from __future__ import annotations

import json
import logging
import re
from types import SimpleNamespace

import pytest
import otbr_cli_bbr as bbr
import td_network_identity
import util_data


def _events(caplog, name=None):
    results = []
    for record in caplog.records:
        if record.levelno != logging.INFO:
            continue
        fields = {}
        for key, value in re.findall(
            r'([A-Za-z0-9_]+)=("(?:\\.|[^"\\])*"|\S+)',
            record.getMessage(),
        ):
            try:
                fields[key] = json.loads(value)
            except json.JSONDecodeError:
                continue
        if "event" in fields and (name is None or fields["event"] == name):
            results.append(fields)
    return results


def test_parse_bbr_primary_block_normalizes_server16_and_metadata() -> None:
    parsed = bbr.parse_bbr_output("""BBR Primary:
  server16: 8C00
  seqno: 4
  delay: 300
  timeout: 1200
Done
""")
    assert parsed == {"primary": {"server16": "0x8c00", "seqno": 4, "delay": 300, "timeout": 1200}}


def test_parse_bbr_primary_block_accepts_unindented_ot_ctl_fields() -> None:
    parsed = bbr.parse_bbr_output("""BBR Primary:
server16: 0x8C00
seqno:    26
delay:    5 secs
timeout:  3600 secs
Done
""")
    assert parsed["primary"]["server16"] == "0x8c00"


def test_bbr_marks_only_same_snapshot_router_with_matching_server16(monkeypatch) -> None:
    monkeypatch.setattr(bbr.util_ot_ctl, "exec_ot_ctl", lambda _command: "BBR Primary:\n  server16: 0x8c00\n")
    monkeypatch.setattr(bbr, "fetch_and_parse_router_table", lambda _labels: [
        {"rloc16": "0x8c00", "router_id": "35"},
        {"rloc16": "0x9000", "router_id": "36"},
    ])
    result = bbr.collect_primary_bbr()
    assert result["routers"][0]["isPrimaryBBR"] is True
    assert result["routers"][0]["primaryBBREvidence"] == "otbr-cli-bbr-server16-match"
    assert "isPrimaryBBR" not in result["routers"][1]


def test_bbr_malformed_or_unmatched_server16_does_not_infer_primary(monkeypatch) -> None:
    monkeypatch.setattr(bbr, "fetch_and_parse_router_table", lambda _labels: [{"rloc16": "0x9000"}])
    monkeypatch.setattr(bbr.util_ot_ctl, "exec_ot_ctl", lambda _command: "BBR Primary:\n  server16: broken\n")
    assert bbr.collect_primary_bbr()["routers"] == [{"rloc16": "0x9000"}]


def test_bbr_summary_reports_primary_evidence_without_changing_envelope(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    routers = [{"rloc16": "0x8c00"}]
    monkeypatch.setattr(
        bbr.util_ot_ctl,
        "exec_ot_ctl",
        lambda _command: "BBR Primary:\n  server16: 0x8c00\n",
    )
    monkeypatch.setattr(bbr, "fetch_and_parse_router_table", lambda _labels: routers)

    result = bbr.collect_primary_bbr()

    assert list(result) == ["bbr", "routers"]
    assert result["routers"][0]["isPrimaryBBR"] is True
    summary, = _events(caplog, "collector_summary")
    assert summary["command"] == "bbr"
    assert summary["stage"] == "bulk"
    assert summary["router_records"] == 1
    assert summary["primary_bbr_present"] is True
    assert summary["state"] == "returned"


def test_bbr_nested_router_failure_is_summarized_without_returning_payload(
    monkeypatch, caplog
) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(
        bbr.util_ot_ctl,
        "exec_ot_ctl",
        lambda _command: "BBR Primary:\n  server16: 0x8c00\n",
    )
    monkeypatch.setattr(
        bbr,
        "fetch_and_parse_router_table",
        lambda _labels: (_ for _ in ()).throw(RuntimeError("router table failed")),
    )

    with pytest.raises(RuntimeError, match="router table failed"):
        bbr.collect_primary_bbr()

    summaries = _events(caplog, "collector_summary")
    assert len(summaries) == 1
    assert summaries[0]["command"] == "bbr"
    assert summaries[0]["router_records"] is None
    assert summaries[0]["primary_bbr_present"] is True
    assert summaries[0]["state"] == "failed"


def test_bbr_main_logs_false_writer_without_changing_exit(monkeypatch, caplog, tmp_path) -> None:
    caplog.set_level(logging.INFO)
    output = tmp_path / "nested" / "bbr.json"
    result = {"bbr": {}, "routers": []}
    monkeypatch.setattr(
        bbr,
        "resolve_collector_runtime",
        lambda *_args: SimpleNamespace(
            extaddr_map_path=tmp_path / "labels.json",
            output_path=output,
        ),
    )
    monkeypatch.setattr(bbr, "load_extaddr_map_or_empty", lambda _path: {})
    monkeypatch.setattr(bbr, "collect_primary_bbr", lambda _labels: result)
    monkeypatch.setattr(bbr, "save_final_json", lambda *_args, **_kwargs: False)

    assert bbr.main([]) == 0

    write, = _events(caplog, "write")
    assert write["command"] == "bbr"
    assert write["output"] == str(output)
    assert write["router_records"] == 0
    assert write["primary_bbr_present"] is False
    assert write["disposition"] == "retained_previous"


def test_bbr_main_logs_write_failure_and_preserves_error_exit(monkeypatch, caplog, tmp_path) -> None:
    caplog.set_level(logging.INFO)
    output = tmp_path / "nested" / "td-otbr-cli-bbr.json"
    output.parent.mkdir()
    result = {"bbr": {}, "routers": []}
    monkeypatch.setattr(
        bbr,
        "resolve_collector_runtime",
        lambda *_args: SimpleNamespace(
            extaddr_map_path=tmp_path / "labels.json",
            output_path=output,
        ),
    )
    monkeypatch.setattr(bbr, "load_extaddr_map_or_empty", lambda _path: {})
    monkeypatch.setattr(bbr, "collect_primary_bbr", lambda _labels: result)
    monkeypatch.setattr(
        bbr,
        "save_final_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError("serialization failed")),
    )

    assert bbr.main([]) == 3

    write, = _events(caplog, "write")
    assert write["disposition"] == "failed"
    assert write["error_type"] == "TypeError"


def test_bbr_main_logs_companion_failure_and_preserves_error_exit(
    monkeypatch, caplog, tmp_path
) -> None:
    caplog.set_level(logging.INFO)
    output = tmp_path / "nested" / "td-otbr-cli-bbr.json"
    output.parent.mkdir()
    result = {"bbr": {}, "routers": []}
    monkeypatch.setattr(
        bbr,
        "resolve_collector_runtime",
        lambda *_args: SimpleNamespace(
            extaddr_map_path=tmp_path / "labels.json",
            output_path=output,
        ),
    )
    monkeypatch.setattr(bbr, "load_extaddr_map_or_empty", lambda _path: {})
    monkeypatch.setattr(bbr, "collect_primary_bbr", lambda _labels: result)
    monkeypatch.setattr(td_network_identity, "resolve_network_scope", lambda *_args: None)
    monkeypatch.setattr(
        util_data,
        "write_network_scope",
        lambda *_args: (_ for _ in ()).throw(OSError("companion failed")),
    )

    assert bbr.main([]) == 3

    write, = _events(caplog, "write")
    assert write["disposition"] == "failed"
    assert write["error_type"] == "OSError"
    assert output.exists()