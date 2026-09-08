"""Tests for versioned whole-data-directory backup and restore."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

import td_system_backups
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_sqlite import SQLiteHealthStore
from td_system_backups import (
    BACKUP_MANIFEST_FILENAME,
    BackupError,
    create_backup,
    restore_backup,
)
from test_td_health_sqlite import _result


def _data_dir(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    SQLiteHealthStore(data_dir / HOBAT_DATABASE_FILENAME).save_processing_result(*_result())
    (data_dir / "snapshot.json").write_text('{"value": 1}\n', encoding="utf-8")
    (data_dir / "config").mkdir()
    (data_dir / "config" / "policy.json").write_text("{}\n", encoding="utf-8")
    return data_dir


def test_backup_and_restore_round_trip_complete_data_directory(tmp_path) -> None:
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    manifest = create_backup(
        data_dir,
        backup_dir,
        created_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )

    assert manifest["createdAt"] == "2026-09-03T00:00:00+00:00"
    assert HOBAT_DATABASE_FILENAME in manifest["files"]
    assert "snapshot.json" in manifest["files"]
    assert (backup_dir / BACKUP_MANIFEST_FILENAME).is_file()
    assert not list(backup_dir.glob("*-wal"))
    assert not list(backup_dir.glob("*-shm"))

    (data_dir / "snapshot.json").write_text('{"value": 2}\n', encoding="utf-8")
    (data_dir / "new.json").write_text("{}\n", encoding="utf-8")
    restored = restore_backup(data_dir, backup_dir)

    assert restored == manifest
    assert (data_dir / "snapshot.json").read_text(encoding="utf-8") == '{"value": 1}\n'
    assert not (data_dir / "new.json").exists()
    assert not (data_dir / BACKUP_MANIFEST_FILENAME).exists()
    with sqlite3.connect(data_dir / HOBAT_DATABASE_FILENAME) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1


def test_backup_rejects_output_inside_data_directory(tmp_path) -> None:
    data_dir = _data_dir(tmp_path)
    with pytest.raises(BackupError, match="outside"):
        create_backup(data_dir, data_dir / "backup")


def test_restore_rejects_checksum_mismatch_without_changing_data(tmp_path) -> None:
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    original = (data_dir / "snapshot.json").read_bytes()
    (backup_dir / "snapshot.json").write_text("corrupt", encoding="utf-8")

    with pytest.raises(BackupError, match="checksum"):
        restore_backup(data_dir, backup_dir)
    assert (data_dir / "snapshot.json").read_bytes() == original


def test_restore_refuses_busy_database(tmp_path) -> None:
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    connection = sqlite3.connect(data_dir / HOBAT_DATABASE_FILENAME)
    connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(BackupError, match="busy"):
            restore_backup(data_dir, backup_dir)
    finally:
        connection.rollback()
        connection.close()


def test_restore_rejects_unsafe_manifest_path(tmp_path) -> None:
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    manifest_path = backup_dir / BACKUP_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["../outside"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupError, match="Unsafe"):
        restore_backup(data_dir, backup_dir)


def test_interrupted_restore_reinstates_original_data_directory(
    tmp_path, monkeypatch
) -> None:
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    (data_dir / "snapshot.json").write_text("current\n", encoding="utf-8")
    real_replace = os.replace

    def fail_activation(source, destination):
        if ".restore-" in str(source):
            raise OSError("injected activation failure")
        real_replace(source, destination)

    monkeypatch.setattr(td_system_backups.os, "replace", fail_activation)
    with pytest.raises(OSError, match="injected activation failure"):
        restore_backup(data_dir, backup_dir)
    assert (data_dir / "snapshot.json").read_text(encoding="utf-8") == "current\n"


def test_restore_mount_root_replaces_contents_without_replacing_root(
    tmp_path, monkeypatch
) -> None:
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    (data_dir / "snapshot.json").write_text("current\n", encoding="utf-8")
    (data_dir / "stale").mkdir()
    (data_dir / "stale" / "value.txt").write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr(td_system_backups.os.path, "ismount", lambda path: path == data_dir)

    restore_backup(data_dir, backup_dir)

    assert data_dir.is_dir()
    assert (data_dir / "snapshot.json").read_text(encoding="utf-8") == '{"value": 1}\n'
    assert (data_dir / "config" / "policy.json").read_text(encoding="utf-8") == "{}\n"
    assert not (data_dir / "stale").exists()


def test_restore_mount_root_reinstates_contents_after_activation_failure(
    tmp_path, monkeypatch
) -> None:
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    (data_dir / "snapshot.json").write_text("current\n", encoding="utf-8")
    (data_dir / "current").mkdir()
    (data_dir / "current" / "value.txt").write_text("current\n", encoding="utf-8")
    real_replace = os.replace

    def fail_snapshot_activation(source, destination):
        if ".restore-" in str(source) and Path(source).name == "snapshot.json":
            raise OSError("injected mount activation failure")
        real_replace(source, destination)

    monkeypatch.setattr(td_system_backups.os.path, "ismount", lambda path: path == data_dir)
    monkeypatch.setattr(td_system_backups.os, "replace", fail_snapshot_activation)

    with pytest.raises(OSError, match="injected mount activation failure"):
        restore_backup(data_dir, backup_dir)
    assert data_dir.is_dir()
    assert (data_dir / "snapshot.json").read_text(encoding="utf-8") == "current\n"
    assert (data_dir / "current" / "value.txt").read_text(encoding="utf-8") == "current\n"
