from __future__ import annotations

import otbr_cli_bbr as bbr


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