"""Tests for unified system backup commands."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

import td_cli
import td_system_cli
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
