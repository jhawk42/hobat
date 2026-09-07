"""Focused health process-dataset CLI tests."""

from __future__ import annotations

import io
import json
import hashlib
from contextlib import redirect_stdout
from unittest.mock import patch

import td_cli
import td_health_cli
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_sqlite import SQLiteHealthStore


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
            ["--datadir", str(tmp_path), "process-dataset", "--dataset", "otbr_cli_networkdiag_fetch_all", "--dry-run", "--json"]
        ) == 0
    document = json.loads(output.getvalue())
    assert document["networkId"] == "extpan:78b9775b001c1cbe"
    assert document["assessmentCreated"] is None
    assert not (tmp_path / HOBAT_DATABASE_FILENAME).exists()


def test_dry_run_uses_existing_roster_history_without_mutating_store(tmp_path) -> None:
    _seed(tmp_path)
    database_path = tmp_path / HOBAT_DATABASE_FILENAME
    store = SQLiteHealthStore(database_path)
    store.upsert_expected_device(
        "extpan:78b9775b001c1cbe", "extaddr:1111111111111111", "Missing"
    )
    assert td_health_cli.main([
        "--datadir", str(tmp_path), "process-dataset",
        "--dataset", "otbr_cli_networkdiag_fetch_all",
    ]) == 0
    snapshot = tmp_path / "td-otbr-cli-networkdiag-fetch-all.json"
    snapshot.write_text(snapshot.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()

    output = io.StringIO()
    with redirect_stdout(output):
        assert td_health_cli.main([
            "--datadir", str(tmp_path), "process-dataset",
            "--dataset", "otbr_cli_networkdiag_fetch_all", "--dry-run", "--json",
        ]) == 0

    document = json.loads(output.getvalue())
    assert any(
        finding["rule_id"] == "device.offline"
        for finding in document["findings"]
    )
    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == before


def test_top_level_json_has_no_banner(tmp_path) -> None:
    _seed(tmp_path)
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_cli.main(
            ["--datadir", str(tmp_path), "health", "process-dataset", "--dataset", "otbr_cli_networkdiag_fetch_all", "--dry-run", "--json"]
        ) == 0
    assert json.loads(output.getvalue())["datasetId"] == "otbr_cli_networkdiag_fetch_all"


def test_top_level_age_purge_dry_run_is_json_and_does_not_mutate(tmp_path) -> None:
    _seed(tmp_path)
    assert td_health_cli.main([
        "--datadir", str(tmp_path), "process-dataset",
        "--dataset", "otbr_cli_networkdiag_fetch_all",
    ]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_cli.main([
            "--datadir", str(tmp_path), "health", "purge",
            "--keep-days", "0", "--dry-run", "--json",
        ]) == 0
    document = json.loads(output.getvalue())
    assert document["command"] == "purge"
    assert document["dryRun"] is True
    assert document["deleted"]["observations"] == 1


def test_age_purge_defaults_to_configured_retention() -> None:
    args = td_health_cli.build_parser().parse_args(["purge"])

    assert args.keep_days == td_health_cli.DEFAULT_HEALTH_PURGE_KEEP_DAYS == 30


def test_purge_by_device_requires_confirmation(tmp_path) -> None:
    output = io.StringIO()
    with patch("builtins.input", return_value="n"), redirect_stdout(output):
        assert td_health_cli.main([
            "--datadir", str(tmp_path), "purge-by-device",
            "--device", "8672766ae0578187",
        ]) == 0
    assert "cancelled" in output.getvalue().lower()
    assert not (tmp_path / HOBAT_DATABASE_FILENAME).exists()


def test_roster_upsert_state_change_and_list_are_cli_only(tmp_path) -> None:
    _seed(tmp_path)
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_health_cli.main([
            "--datadir", str(tmp_path),
            "process-dataset",
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
            "process-dataset",
            "--dataset", "otbr_cli_networkdiag_fetch_all",
            "--roster-list",
            "--json",
        ]) == 0
    assert json.loads(output.getvalue())["devices"][0]["label"] == "Office Router"


def test_all_processes_every_eligible_dataset_in_sorted_order(tmp_path) -> None:
    processed = []

    def fake_build_processing_result(**kwargs):
        processed.append(kwargs["dataset_id"])
        return kwargs["dataset_id"]

    with (
        patch.object(td_health_cli, "build_processing_result", side_effect=fake_build_processing_result),
        patch.object(td_health_cli, "result_document", side_effect=lambda dataset_id: {"datasetId": dataset_id}),
    ):
        output = io.StringIO()
        with redirect_stdout(output):
            assert td_health_cli.main([
                "--datadir", str(tmp_path),
                "process-dataset", "--dataset", "all", "--dry-run", "--json",
            ]) == 0

    expected = sorted(td_health_cli.load_health_manifest().datasets)
    assert processed == expected
    assert [item["datasetId"] for item in json.loads(output.getvalue())] == expected