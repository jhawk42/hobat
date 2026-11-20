"""Tests for unified system backup commands."""

from __future__ import annotations

import io
import json
import sqlite3
from urllib.error import HTTPError, URLError
from contextlib import closing, redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

pytestmark = pytest.mark.usefixtures("archived_health_catalog")

import td_cli
import td_system_cli
import td_system_ping


def test_restore_apply_confirmation_alias():
    parser = td_system_cli.build_parser()
    argv = ["backups", "restore", "--input", "backup"]
    assert parser.parse_args([*argv, "--apply"]) == parser.parse_args([*argv, "--yes"])


def _remote_response(document, status=200):
    response = Mock(status=status)
    response.read.return_value = json.dumps(document).encode()
    context = Mock()
    context.__enter__ = Mock(return_value=response)
    context.__exit__ = Mock(return_value=False)
    return context


@pytest.mark.parametrize(
    ("action", "options", "responses", "requests", "expected"),
    [
        ("status", [], [{"enabled": True, "last_run": None}], [("GET", "/api/scheduler", None)], {"enabled": True, "last_run": None}),
        ("list", [], [{"jobs": [{"kind": "scheduler", "jobId": "a"}, {"task": "scheduler-nightly", "jobId": "b"}, {"kind": "health"}]}], [("GET", "/api/jobs", None)], {"jobs": [{"kind": "scheduler", "jobId": "a"}, {"task": "scheduler-nightly", "jobId": "b"}]}),
        ("pause", [], [{"paused": True}], [("PATCH", "/api/scheduler", {"paused": True})], {"paused": True}),
        ("resume", [], [{"paused": False}], [("PATCH", "/api/scheduler", {"paused": False})], {"paused": False}),
        ("run-now", ["--apply"], [{"job_id": "j1", "status": "running", "mode": "full"}], [("POST", "/api/scheduler/run", {})], {"job_id": "j1", "status": "running", "mode": "full"}),
        ("run-now", ["--apply", "--quick"], [{"job_id": "j2", "status": "running", "mode": "quick"}], [("POST", "/api/scheduler/run", {"quick": True})], {"job_id": "j2", "status": "running", "mode": "quick"}),
        ("cancel", ["j1"], [{"task": "scheduler-nightly"}, {"job_id": "j1", "status": "cancelling"}], [("GET", "/api/job/j1", None), ("DELETE", "/api/job/j1", None)], {"job_id": "j1", "status": "cancelling"}),
    ],
)
def test_remote_scheduler_commands(action, options, responses, requests, expected, capsys):
    with patch.object(td_system_cli, "urlopen", side_effect=[_remote_response(item) for item in responses]) as send, patch.object(td_system_cli, "resolve_data_dir") as resolve:
        assert td_cli.main(["system", "scheduler", action, *options, "--server-url", "https://hobat.test/ingress/", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == expected
    assert ("live collection and purge" in captured.err) == (action == "run-now")
    resolve.assert_not_called()
    assert len(send.call_args_list) == len(requests)
    for call, (method, path, payload) in zip(send.call_args_list, requests):
        request = call.args[0]
        assert request.full_url == "https://hobat.test/ingress" + path
        assert request.method == method
        assert (json.loads(request.data) if request.data else None) == payload
        assert call.kwargs["timeout"] == 10


@pytest.mark.parametrize("argv", [
    ["--datadir", "", "system", "scheduler", "status"],
    ["--datadir", "local", "system", "scheduler", "status"],
    ["system", "scheduler", "--datadir", "local", "status"],
    ["system", "scheduler", "status", "--datadir", "local"],
])
def test_scheduler_rejects_explicit_datadir(argv, capsys):
    with patch.object(td_system_cli, "urlopen") as send, patch.object(td_system_cli, "resolve_data_dir") as resolve:
        assert td_cli.main([*argv, "--server-url", "http://hobat.test"]) != 0
    assert "server owns the directory" in capsys.readouterr().err
    send.assert_not_called()
    resolve.assert_not_called()


@pytest.mark.parametrize("action", ["status", "list", "pause", "resume", "cancel"])
def test_scheduler_quick_is_rejected_except_run_now(action):
    options = ["job1"] if action == "cancel" else []
    with patch.object(td_system_cli, "urlopen") as send, pytest.raises(SystemExit) as exc:
        td_cli.main(["system", "scheduler", action, *options, "--server-url", "http://hobat.test", "--quick"])
    assert exc.value.code == 2
    send.assert_not_called()


def test_scheduler_run_now_requires_apply():
    with patch.object(td_system_cli, "urlopen") as send, pytest.raises(SystemExit) as exc:
        td_cli.main(["system", "scheduler", "run-now", "--server-url", "http://hobat.test"])
    assert exc.value.code == 2
    send.assert_not_called()


@pytest.mark.parametrize("argv", [
    ["status"],
    ["run-now", "--apply", "--quick", "false", "--server-url", "http://hobat.test"],
    ["run-now", "--apply", "--quick=false", "--server-url", "http://hobat.test"],
])
def test_scheduler_rejects_missing_url_and_quick_values(argv):
    with patch.object(td_system_cli, "urlopen") as send, pytest.raises(SystemExit) as exc:
        td_cli.main(["system", "scheduler", *argv])
    assert exc.value.code == 2
    send.assert_not_called()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://user:secret@hobat.test", "http://hobat.test/?query=1", "http://hobat.test/#fragment", "http://hobat.test:invalid", "http://hobat.test/\x00"])
def test_scheduler_rejects_invalid_server_urls(url, capsys):
    with patch.object(td_system_cli, "urlopen") as send:
        assert td_system_cli.main(["scheduler", "status", "--server-url", url]) == 1
    assert "server-url" in capsys.readouterr().err
    send.assert_not_called()


@pytest.mark.parametrize("failure", [
    URLError("unreachable"),
    TimeoutError(),
    HTTPError("http://hobat.test", 409, "conflict", {}, None),
    _remote_response(["invalid"]),
    _remote_response({"jobs": "invalid"}),
])
def test_scheduler_transport_and_response_errors(failure, capsys):
    with patch.object(td_system_cli, "urlopen", side_effect=[failure]):
        assert td_system_cli.main(["scheduler", "list", "--server-url", "http://hobat.test"]) == 1
    assert "Error:" in capsys.readouterr().err


def test_scheduler_non_json_and_oversized_response(capsys):
    for body in (b"not json", b"x" * (1024 * 1024 + 1)):
        response = _remote_response({})
        response.__enter__.return_value.read.return_value = body
        with patch.object(td_system_cli, "urlopen", return_value=response):
            assert td_system_cli.main(["scheduler", "status", "--server-url", "http://hobat.test"]) == 1
        assert "Error:" in capsys.readouterr().err


def test_scheduler_run_now_requires_job_id(capsys):
    with patch.object(td_system_cli, "urlopen", return_value=_remote_response({"status": "running"})):
        assert td_system_cli.main(["scheduler", "run-now", "--apply", "--server-url", "http://hobat.test"]) == 1
    assert "invalid job acceptance" in capsys.readouterr().err


@pytest.mark.parametrize(("job_id", "job"), [("../other", None), ("job1", {"kind": "health"}), ("job1", {})])
def test_cancel_only_scheduler_jobs(job_id, job, capsys):
    with patch.object(td_system_cli, "urlopen", return_value=_remote_response(job or {})) as send:
        assert td_system_cli.main(["scheduler", "cancel", job_id, "--server-url", "http://hobat.test"]) == 1
    assert "Error:" in capsys.readouterr().err
    assert send.call_count == (0 if job is None else 1)


def test_cancel_expired_job_never_deletes(capsys):
    with patch.object(td_system_cli, "urlopen", side_effect=HTTPError("http://hobat.test", 404, "not found", {}, None)) as send:
        assert td_system_cli.main(["scheduler", "cancel", "job1", "--server-url", "http://hobat.test"]) == 1
    assert "HTTP 404" in capsys.readouterr().err
    assert send.call_count == 1
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


def test_top_level_database_repack_uses_selected_datadir(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _seed(data_dir)
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    output = io.StringIO()

    with redirect_stdout(output):
        assert td_cli.main([
            "--datadir", str(data_dir), "system", "database", "repack",
        ]) == 0

    assert output.getvalue().splitlines()[-1] == (
        f"Repacked Hobat database at {database_path}"
    )
    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone() == (1,)


def test_top_level_database_repack_missing_db_does_not_create_it(tmp_path, capsys) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database_path = data_dir / HOBAT_DATABASE_FILENAME

    assert td_cli.main([
        "--datadir", str(data_dir), "system", "database", "repack",
    ]) == 1

    assert "not available" in capsys.readouterr().err
    assert not database_path.exists()


def test_top_level_database_repack_reports_insufficient_disk_space(
    tmp_path, monkeypatch, capsys,
) -> None:
    data_dir = tmp_path / "data"
    _seed(data_dir)
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    required = database_path.stat().st_size
    monkeypatch.setattr("shutil.disk_usage", lambda path: SimpleNamespace(free=0))

    assert td_cli.main([
        "--datadir", str(data_dir), "system", "database", "repack",
    ]) == 1

    output = capsys.readouterr()
    assert "Not enough free disk space" in output.err
    assert f"requires at least {required} bytes" in output.err
    assert "0 bytes available" in output.err
    assert "Repacked Hobat database" not in output.out


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
