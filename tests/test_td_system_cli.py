"""Tests for unified system backup commands."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import td_cli
import td_system_cli
import td_system_ping
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_sqlite import SQLiteHealthStore
from test_td_health_sqlite import _result


def _seed(data_dir) -> None:
    data_dir.mkdir()
    SQLiteHealthStore(data_dir / HOBAT_DATABASE_FILENAME).save_processing_result(*_result())
    (data_dir / "snapshot.json").write_text("before\n", encoding="utf-8")


def test_top_level_backup_create_and_restore_json(tmp_path) -> None:
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backup"
    _seed(data_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_cli.main([
            "--datadir", str(data_dir), "system", "backups", "create",
            "--output", str(backup_dir), "--json",
        ]) == 0
    created = json.loads(output.getvalue())
    assert created["action"] == "create"
    assert created["fileCount"] >= 2

    (data_dir / "snapshot.json").write_text("after\n", encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_cli.main([
            "--datadir", str(data_dir), "system", "backups", "restore",
            "--input", str(backup_dir), "--yes", "--json",
        ]) == 0
    restored = json.loads(output.getvalue())
    assert restored["action"] == "restore"
    assert (data_dir / "snapshot.json").read_text(encoding="utf-8") == "before\n"


def test_restore_can_be_cancelled_without_reading_backup(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _seed(data_dir)
    output = io.StringIO()
    with patch("builtins.input", return_value="n"), redirect_stdout(output):
        assert td_system_cli.main([
            "--datadir", str(data_dir), "backups", "restore",
            "--input", str(tmp_path / "missing"),
        ]) == 0
    assert "cancelled" in output.getvalue().lower()
    assert (data_dir / "snapshot.json").read_text(encoding="utf-8") == "before\n"


def test_system_ping_is_forwarded_without_resolving_datadir(tmp_path) -> None:
    with patch.object(td_system_cli, "run_ping", return_value=({"outcome": "success"}, 0)) as run, patch.object(td_system_cli, "resolve_data_dir") as resolve:
        assert td_cli.main(["--datadir", str(tmp_path / "missing"), "system", "device", "ping", "--address", "192.0.2.1"]) == 0
    run.assert_called_once_with("192.0.2.1", "auto", 1, 5.0, 30.0)
    resolve.assert_not_called()


def test_top_level_system_ping_emits_only_json() -> None:
    output = io.StringIO()
    with patch.object(td_system_cli, "run_ping", return_value=({"outcome": "invalid-address"}, 6)), redirect_stdout(output):
        assert td_cli.main(["system", "device", "ping", "--address", "not-an-ip"]) == 6
    assert json.loads(output.getvalue()) == {"outcome": "invalid-address"}


def test_ping_command_construction_is_platform_specific() -> None:
    assert td_system_ping.build_ping_command("Linux", "ping", "192.0.2.1", "ipv4", 1.2) == ["ping", "-4", "-c", "1", "-W", "2", "192.0.2.1"]
    assert td_system_ping.build_ping_command("Darwin", "ping", "2001:db8::1", "ipv6", 1.2) == ["ping", "-6", "-c", "1", "-W", "1200", "2001:db8::1"]
    assert td_system_ping.build_ping_command("Windows", "ping.exe", "192.0.2.1", "ipv4", 1.2) == ["ping.exe", "-4", "-n", "1", "-w", "1200", "192.0.2.1"]


def test_ping_validation_rejects_nonliteral_zone_and_family_mismatch() -> None:
    for address, family in [("host.example", "auto"), ("fe80::1%eth0", "auto"), ("fe80::1", "auto"), ("192.0.2.1", "ipv6")]:
        document, exit_code = td_system_ping.run_ping(address, family, 1, 1, 2)
        assert exit_code == td_system_ping.EXIT_INVALID_ADDRESS
        assert document["outcome"] == "invalid-address"


def test_ping_records_partial_and_timeout_cleanup() -> None:
    successful = Mock(returncode=0)
    failed = Mock(returncode=1)
    with patch.object(td_system_ping.platform, "system", return_value="Linux"), patch.object(td_system_ping.shutil, "which", return_value="/bin/ping"), patch.object(td_system_ping.subprocess, "Popen", side_effect=[successful, failed]):
        document, exit_code = td_system_ping.run_ping("192.0.2.1", "auto", 2, 1, 5)
    assert exit_code == td_system_ping.EXIT_PARTIAL
    assert document["outcome"] == "partial-success"

    timed_out = Mock()
    timed_out.wait.side_effect = [td_system_ping.subprocess.TimeoutExpired("ping", 1), None]
    with patch.object(td_system_ping.platform, "system", return_value="Linux"), patch.object(td_system_ping.shutil, "which", return_value="/bin/ping"), patch.object(td_system_ping.subprocess, "Popen", return_value=timed_out):
        document, exit_code = td_system_ping.run_ping("192.0.2.1", "auto", 1, 1, 5)
    assert exit_code == td_system_ping.EXIT_ATTEMPT_TIMEOUT
    assert document["attempts"][0]["outcome"] == "attempt-timeout"
    timed_out.terminate.assert_called_once()


def test_ping_classifies_missing_unsupported_and_process_failures() -> None:
    with patch.object(td_system_ping.platform, "system", return_value="Plan9"):
        document, exit_code = td_system_ping.run_ping("192.0.2.1", "auto", 1, 1, 5)
    assert (document["outcome"], exit_code) == ("unsupported-platform", td_system_ping.EXIT_UNSUPPORTED)

    with patch.object(td_system_ping.platform, "system", return_value="Linux"), patch.object(td_system_ping.shutil, "which", return_value=None):
        document, exit_code = td_system_ping.run_ping("192.0.2.1", "auto", 1, 1, 5)
    assert (document["outcome"], exit_code) == ("missing-executable", td_system_ping.EXIT_MISSING_EXECUTABLE)

    with patch.object(td_system_ping.platform, "system", return_value="Linux"), patch.object(td_system_ping.shutil, "which", return_value="/bin/ping"), patch.object(td_system_ping.subprocess, "Popen", side_effect=OSError("denied")):
        document, exit_code = td_system_ping.run_ping("192.0.2.1", "auto", 1, 1, 5)
    assert (document["outcome"], exit_code) == ("process-failure", td_system_ping.EXIT_PROCESS_FAILURE)


def test_ping_stops_before_starting_an_attempt_after_deadline() -> None:
    with patch.object(td_system_ping.time, "monotonic", side_effect=[0.0, 2.0, 2.1]), patch.object(td_system_ping.platform, "system", return_value="Linux"), patch.object(td_system_ping.shutil, "which", return_value="/bin/ping"), patch.object(td_system_ping.subprocess, "Popen") as popen:
        document, exit_code = td_system_ping.run_ping("192.0.2.1", "auto", 2, 1, 1)
    assert (document["outcome"], exit_code) == ("deadline-exceeded", td_system_ping.EXIT_DEADLINE)
    assert document["attemptsCompleted"] == 0
    popen.assert_not_called()


def test_ping_discards_child_output_and_reaps_on_cancellation() -> None:
    process = Mock(returncode=0)
    process.wait.side_effect = KeyboardInterrupt
    with patch.object(td_system_ping.platform, "system", return_value="Linux"), patch.object(td_system_ping.shutil, "which", return_value="/bin/ping"), patch.object(td_system_ping.subprocess, "Popen", return_value=process) as popen:
        try:
            td_system_ping.run_ping("192.0.2.1", "auto", 1, 1, 5)
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("expected cancellation")
    assert popen.call_args.kwargs["stdout"] is td_system_ping.subprocess.DEVNULL
    assert popen.call_args.kwargs["stderr"] is td_system_ping.subprocess.DEVNULL
    process.terminate.assert_called_once()
