"""Tests for versioned whole-data-directory backup and restore."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("archived_health_catalog")

import td_system_backups
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_sqlite import SQLiteHealthStore
from td_system_backups import (
    BACKUP_MANIFEST_FILENAME,
    BackupError,
    create_backup,
    restore_backup,
)
from td_scheduler_lock import (
    SCHEDULER_LOCK_FILENAME,
    SCHEDULER_STATE_FILENAME,
    SchedulerLockError,
    acquire_scheduler_lock,
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
    with closing(sqlite3.connect(data_dir / HOBAT_DATABASE_FILENAME)) as connection, connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1


def test_backup_excludes_migration_recovery_and_restore_preserves_it(tmp_path) -> None:
    data_dir = _data_dir(tmp_path)
    recovery_dir = data_dir / ".migration-backups"
    recovery_dir.mkdir()
    recovery_copy = recovery_dir / "hobat_v1-schema-v3-to-v8-verified.sqlite"
    recovery_copy.write_bytes(b"verified recovery copy")
    recovery_metadata = recovery_copy.with_suffix(".json")
    recovery_metadata.write_text('{"sourceSchemaVersion":3}\n', encoding="utf-8")
    backup_dir = tmp_path / "backup"

    manifest = create_backup(data_dir, backup_dir)

    assert not any(name.startswith(".migration-backups/") for name in manifest["files"])
    assert not (backup_dir / ".migration-backups").exists()
    restore_backup(data_dir, backup_dir)

    assert recovery_copy.read_bytes() == b"verified recovery copy"
    assert recovery_metadata.read_text(encoding="utf-8") == '{"sourceSchemaVersion":3}\n'


def test_restore_refuses_to_overwrite_same_named_migration_recovery_copy(tmp_path) -> None:
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    restored_recovery_dir = backup_dir / ".migration-backups"
    restored_recovery_dir.mkdir()
    duplicate_name = "recovery.sqlite"
    (restored_recovery_dir / duplicate_name).write_bytes(b"backup copy")
    manifest_path = backup_dir / BACKUP_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][".migration-backups/recovery.sqlite"] = td_system_backups._sha256(
        restored_recovery_dir / duplicate_name
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (data_dir / ".migration-backups").mkdir()
    (data_dir / ".migration-backups" / duplicate_name).write_bytes(b"operator copy")

    with pytest.raises(BackupError, match="must not contain migration-recovery"):
        restore_backup(data_dir, backup_dir)
    staging_dir = tmp_path / "staging"
    collision_dir = staging_dir / ".migration-backups"
    collision_dir.mkdir(parents=True)
    (collision_dir / duplicate_name).write_bytes(b"backup copy")
    with pytest.raises(BackupError, match="overwrite"):
        td_system_backups._preserve_migration_recovery_files(data_dir, staging_dir)
    assert (
        data_dir / ".migration-backups" / duplicate_name
    ).read_bytes() == b"operator copy"


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
        if Path(source).parent.name == "incoming" and Path(source).name == "snapshot.json":
            raise OSError("injected mount activation failure")
        real_replace(source, destination)

    monkeypatch.setattr(td_system_backups.os.path, "ismount", lambda path: path == data_dir)
    monkeypatch.setattr(td_system_backups.os, "replace", fail_snapshot_activation)

    with pytest.raises(OSError, match="injected mount activation failure"):
        restore_backup(data_dir, backup_dir)
    assert data_dir.is_dir()
    assert (data_dir / "snapshot.json").read_text(encoding="utf-8") == "current\n"
    assert (data_dir / "current" / "value.txt").read_text(encoding="utf-8") == "current\n"


def test_mounted_restore_uses_only_target_filesystem_moves(tmp_path, monkeypatch):
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    root_identity = (data_dir.stat().st_dev, data_dir.stat().st_ino)
    recovery = data_dir / ".migration-backups"
    recovery.mkdir()
    (recovery / "copy.sqlite").write_bytes(b"recovery")
    real_replace = os.replace

    def same_filesystem_replace(source, destination):
        assert Path(source).is_relative_to(data_dir)
        assert Path(destination).is_relative_to(data_dir)
        real_replace(source, destination)

    monkeypatch.setattr(td_system_backups.os.path, "ismount", lambda path: path == data_dir)
    monkeypatch.setattr(td_system_backups.os, "replace", same_filesystem_replace)
    restore_backup(data_dir, backup_dir)
    assert (data_dir.stat().st_dev, data_dir.stat().st_ino) == root_identity
    assert (recovery / "copy.sqlite").read_bytes() == b"recovery"
    assert not list(data_dir.glob(".hobat-restore-*"))


def test_restore_on_real_second_filesystem(tmp_path, monkeypatch):
    root = Path("/dev/shm")
    if not root.is_dir() or root.stat().st_dev == tmp_path.stat().st_dev or not os.access(root, os.W_OK):
        pytest.skip("No writable second filesystem available")
    source = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    manifest = create_backup(source, backup_dir)
    with tempfile.TemporaryDirectory(prefix="hobat-restore-test-", dir=root) as name:
        data_dir = _data_dir(Path(name))
        identity = data_dir.stat().st_ino
        real_replace = os.replace

        def guarded_replace(source, destination):
            assert Path(source).parent.stat().st_dev == Path(destination).parent.stat().st_dev
            real_replace(source, destination)

        monkeypatch.setattr(td_system_backups.os.path, "ismount", lambda path: path == data_dir)
        monkeypatch.setattr(td_system_backups.os, "replace", guarded_replace)
        assert restore_backup(data_dir, backup_dir) == manifest
        assert data_dir.stat().st_ino == identity
        actual = td_system_backups._manifest_files(data_dir)
        actual.pop(SCHEDULER_LOCK_FILENAME)
        assert actual == manifest["files"]
        assert not list(data_dir.glob(".hobat-restore-*"))


@pytest.mark.parametrize("stage", ["evacuation", "activation"])
def test_mounted_restore_rolls_back_partial_moves(tmp_path, monkeypatch, stage):
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    (data_dir / "snapshot.json").write_text("current")
    (data_dir / "dangling").symlink_to("missing-target")
    td_system_backups._assert_database_available_for_restore(data_dir)
    before = td_system_backups._manifest_files(data_dir)
    real_replace = os.replace
    moved = 0

    def fail_after_one_move(source, destination):
        nonlocal moved
        selected = (
            Path(destination).parent.name == "previous"
            if stage == "evacuation" else Path(source).parent.name == "incoming"
        )
        if selected:
            moved += 1
            if moved == 2:
                raise OSError("injected partial move failure")
        real_replace(source, destination)

    monkeypatch.setattr(td_system_backups.os.path, "ismount", lambda path: path == data_dir)
    monkeypatch.setattr(td_system_backups.os, "replace", fail_after_one_move)
    with pytest.raises(OSError, match="partial move"):
        restore_backup(data_dir, backup_dir)
    after = td_system_backups._manifest_files(data_dir)
    after.pop(SCHEDULER_LOCK_FILENAME)
    assert after == before
    assert (data_dir / "dangling").is_symlink()
    assert os.readlink(data_dir / "dangling") == "missing-target"
    assert not list(data_dir.glob(".hobat-restore-*"))


@pytest.mark.parametrize("failure", ["rollback", "cleanup"])
def test_mounted_restore_retains_unresolved_recovery(tmp_path, monkeypatch, failure):
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    (data_dir / "snapshot.json").write_text("current")
    real_replace = os.replace
    real_remove = td_system_backups.shutil.rmtree

    def fail_moves(source, destination):
        parent = Path(source).parent.name
        if failure == "rollback" and (
            (parent == "incoming" and Path(source).name == "snapshot.json")
            or (parent == "previous" and Path(source).name == "snapshot.json")
        ):
            raise OSError("injected move failure")
        real_replace(source, destination)

    def fail_cleanup(path, *args, **kwargs):
        if failure == "cleanup" and Path(path).name.startswith(".hobat-restore-"):
            raise OSError("injected cleanup failure")
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(td_system_backups.os.path, "ismount", lambda path: path == data_dir)
    monkeypatch.setattr(td_system_backups.os, "replace", fail_moves)
    monkeypatch.setattr(td_system_backups.shutil, "rmtree", fail_cleanup)
    with pytest.raises(BackupError, match="recovery.*at") as error:
        restore_backup(data_dir, backup_dir)
    workspace, = data_dir.glob(".hobat-restore-*")
    assert str(workspace) in str(error.value)
    assert (workspace / "previous" / "snapshot.json").read_text() == "current"
    if failure == "cleanup":
        assert (data_dir / "snapshot.json").read_text() == '{"value": 1}\n'
    with pytest.raises(BackupError, match="Unfinished restore workspace"):
        restore_backup(data_dir, backup_dir)
    with pytest.raises(BackupError, match="Unfinished restore workspace"):
        create_backup(data_dir, tmp_path / "another-backup")


@pytest.mark.parametrize("mounted", [False, True])
def test_backup_excludes_scheduler_runtime_files(tmp_path, monkeypatch, mounted):
    data_dir = _data_dir(tmp_path)
    monkeypatch.setattr(td_system_backups.td_scheduler_lock, "is_mount_root", lambda _: mounted)
    (data_dir / SCHEDULER_STATE_FILENAME).write_text("local claim")
    (data_dir / SCHEDULER_LOCK_FILENAME).write_text("runtime lock")
    backup_dir = tmp_path / "backup"

    manifest = create_backup(data_dir, backup_dir)

    assert SCHEDULER_STATE_FILENAME not in manifest["files"]
    assert SCHEDULER_LOCK_FILENAME not in manifest["files"]
    assert not (backup_dir / SCHEDULER_STATE_FILENAME).exists()
    assert not (backup_dir / SCHEDULER_LOCK_FILENAME).exists()


def _add_legacy_scheduler_files(backup_dir):
    manifest_path = backup_dir / BACKUP_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text())
    for name in (SCHEDULER_STATE_FILENAME, SCHEDULER_LOCK_FILENAME):
        path = backup_dir / name
        path.write_text("legacy runtime")
        manifest["files"][name] = td_system_backups._sha256(path)
    manifest_path.write_text(json.dumps(manifest))


@pytest.mark.parametrize("mounted", [False, True])
@pytest.mark.parametrize("local_state", [None, "local claim"])
def test_restore_ignores_legacy_runtime_and_preserves_local_state(
    tmp_path, monkeypatch, mounted, local_state
):
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    _add_legacy_scheduler_files(backup_dir)
    state = data_dir / SCHEDULER_STATE_FILENAME
    if local_state is not None:
        state.write_text(local_state)
    monkeypatch.setattr(td_system_backups.td_scheduler_lock, "is_mount_root", lambda _: mounted)

    restore_backup(data_dir, backup_dir)

    if local_state is None:
        assert not state.exists()
    else:
        assert state.read_text() == local_state
    if mounted:
        assert (data_dir / SCHEDULER_LOCK_FILENAME).read_text() == ""
    else:
        assert not (data_dir / SCHEDULER_LOCK_FILENAME).exists()


@pytest.mark.parametrize("mounted", [False, True])
def test_restore_rejects_scheduler_owner_and_releases_lock_afterwards(
    tmp_path, monkeypatch, mounted
):
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    monkeypatch.setattr(td_system_backups.td_scheduler_lock, "is_mount_root", lambda _: mounted)
    with acquire_scheduler_lock(data_dir):
        with pytest.raises(BackupError, match="stop the scheduler-enabled server"):
            restore_backup(data_dir, backup_dir)
    restore_backup(data_dir, backup_dir)
    with acquire_scheduler_lock(data_dir):
        pass


def test_legacy_scheduler_state_is_validated_before_discard(tmp_path):
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    _add_legacy_scheduler_files(backup_dir)
    (backup_dir / SCHEDULER_STATE_FILENAME).write_text("corrupted")
    (data_dir / SCHEDULER_STATE_FILENAME).write_text("local claim")

    with pytest.raises(BackupError, match="checksum"):
        restore_backup(data_dir, backup_dir)
    assert (data_dir / SCHEDULER_STATE_FILENAME).read_text() == "local claim"


def test_scheduler_lock_is_shared_across_processes(tmp_path):
    data_dir = _data_dir(tmp_path)
    code = (
        "import sys; from pathlib import Path; "
        "from td_scheduler_lock import acquire_scheduler_lock; "
        "lock = acquire_scheduler_lock(Path(sys.argv[1])); lock.__enter__()"
    )
    env = dict(os.environ, PYTHONPATH=str(Path("src").resolve()), PYTHONDONTWRITEBYTECODE="1")
    with acquire_scheduler_lock(data_dir):
        result = subprocess.run(
            [sys.executable, "-c", code, str(data_dir)],
            capture_output=True, text=True, env=env, check=False,
        )
    assert result.returncode != 0
    assert "SchedulerLockError" in result.stderr
    assert "stop the scheduler-enabled server" in result.stderr
    result = subprocess.run(
        [sys.executable, "-c", code, str(data_dir)],
        capture_output=True, text=True, env=env, check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mounted", [False, True])
def test_restore_holds_owner_lock_during_activation_and_rollback(
    tmp_path, monkeypatch, mounted
):
    data_dir = _data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_backup(data_dir, backup_dir)
    state = data_dir / SCHEDULER_STATE_FILENAME
    state.write_text("local claim")
    monkeypatch.setattr(td_system_backups.td_scheduler_lock, "is_mount_root", lambda _: mounted)
    real_replace = os.replace
    checked = []

    def fail_activation(source, destination):
        is_activation = (
            Path(source).parent.name == "incoming"
            if mounted else ".restore-" in Path(source).name
        )
        if is_activation:
            with pytest.raises(SchedulerLockError, match="stop the scheduler-enabled server"):
                with acquire_scheduler_lock(data_dir):
                    pass
            checked.append(True)
            raise OSError("injected activation failure")
        if checked:
            with pytest.raises(SchedulerLockError):
                with acquire_scheduler_lock(data_dir):
                    pass
        return real_replace(source, destination)

    monkeypatch.setattr(td_system_backups.os, "replace", fail_activation)
    with pytest.raises(OSError, match="injected activation failure"):
        restore_backup(data_dir, backup_dir)
    assert checked
    assert state.read_text() == "local claim"
    with acquire_scheduler_lock(data_dir):
        pass
