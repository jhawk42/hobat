"""Focused process-health CLI tests."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import td_cli
import td_health_cli


def _seed(data_dir) -> None:
    (data_dir / "td-otbr-cli-thread-network-info.json").write_text(
        json.dumps({"extPanId": "78b9775b001c1cbe", "networkName": "test"}),
        encoding="utf-8",
    )
    (data_dir / "td-otbr-cli-networkdiag-fetch-all.json").write_text(
        json.dumps([{"extAddress": "8672766ae0578187", "role": "router"}]),
        encoding="utf-8",
    )


def test_dry_run_json_does_not_create_database(tmp_path) -> None:
    _seed(tmp_path)
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_health_cli.main(
            ["--datadir", str(tmp_path), "--dataset", "otbr_cli_networkdiag_fetch_all", "--dry-run", "--json"]
        ) == 0
    document = json.loads(output.getvalue())
    assert document["networkId"] == "extpan:78b9775b001c1cbe"
    assert document["assessmentCreated"] is None
    assert not (tmp_path / "td-health.db").exists()


def test_top_level_json_has_no_banner(tmp_path) -> None:
    _seed(tmp_path)
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_cli.main(
            ["--datadir", str(tmp_path), "process-health", "--dataset", "otbr_cli_networkdiag_fetch_all", "--dry-run", "--json"]
        ) == 0
    assert json.loads(output.getvalue())["datasetId"] == "otbr_cli_networkdiag_fetch_all"


def test_roster_upsert_state_change_and_list_are_cli_only(tmp_path) -> None:
    _seed(tmp_path)
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_health_cli.main([
            "--datadir", str(tmp_path),
            "--dataset", "otbr_cli_networkdiag_fetch_all",
            "--roster-device", "86:72:76:6A:E0:57:81:87",
            "--roster-label", "Office Router",
            "--roster-state", "intermittent",
            "--json",
        ]) == 0
    document = json.loads(output.getvalue())
    assert document["devices"][0]["device_id"] == "extaddr:8672766ae0578187"
    assert document["devices"][0]["roster_state"] == "intermittent"

    output = io.StringIO()
    with redirect_stdout(output):
        assert td_health_cli.main([
            "--datadir", str(tmp_path),
            "--dataset", "otbr_cli_networkdiag_fetch_all",
            "--roster-list",
            "--json",
        ]) == 0
    assert json.loads(output.getvalue())["devices"][0]["label"] == "Office Router"