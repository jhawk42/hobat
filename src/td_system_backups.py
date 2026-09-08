"""Versioned backup and restore for the complete Hobat data directory."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_sqlite import SCHEMA_VERSION


BACKUP_FORMAT_VERSION = 1
BACKUP_MANIFEST_FILENAME = "hobat-backup-manifest.json"
_EXCLUDED_SUFFIXES = ("-wal", "-shm", "-journal", ".lock")


class BackupError(RuntimeError):
    """Raised when backup creation or restoration cannot complete safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _database_schema_version(path: Path) -> int:
    try:
        connection = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True
        )
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise BackupError("Backup database failed integrity verification")
            row = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()
            version = int(row[0] or 0)
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError("Backup database cannot be opened") from exc
    if version > SCHEMA_VERSION:
        raise BackupError(
            f"Backup database schema {version} is newer than supported {SCHEMA_VERSION}"
        )
    return version


def _copy_sqlite(source: Path, destination: Path) -> int:
    source_connection = sqlite3.connect(
        f"{source.resolve().as_uri()}?mode=ro", timeout=5.0, uri=True
    )
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.execute("PRAGMA busy_timeout=5000")
        source_connection.backup(destination_connection)
    except sqlite3.DatabaseError as exc:
        raise BackupError("Could not create SQLite backup") from exc
    finally:
        destination_connection.close()
        source_connection.close()
    return _database_schema_version(destination)


def _copy_data_files(data_dir: Path, destination: Path) -> None:
    for source in sorted(data_dir.rglob("*")):
        relative = source.relative_to(data_dir)
        if source.is_symlink():
            raise BackupError(f"Data directory contains unsupported symlink: {relative}")
        if source.is_dir():
            continue
        if relative == Path(HOBAT_DATABASE_FILENAME):
            continue
        if source.name.endswith(_EXCLUDED_SUFFIXES) or source.name.endswith(".tmp"):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _manifest_files(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): _sha256(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != BACKUP_MANIFEST_FILENAME
    }


def create_backup(
    data_dir: Path, output_dir: Path, *, created_at: datetime | None = None
) -> dict[str, Any]:
    data_dir = data_dir.resolve()
    output_dir = output_dir.resolve()
    if not data_dir.is_dir():
        raise BackupError(f"Data directory does not exist: {data_dir}")
    if _is_within(output_dir, data_dir):
        raise BackupError("Backup output must be outside the data directory")
    if output_dir.exists():
        raise BackupError(f"Backup output already exists: {output_dir}")
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    if not database_path.is_file():
        raise BackupError(f"Hobat database is not available: {database_path}")

    staging = output_dir.parent / f".{output_dir.name}.tmp-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    try:
        _copy_data_files(data_dir, staging)
        schema_version = _copy_sqlite(database_path, staging / HOBAT_DATABASE_FILENAME)
        timestamp = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        manifest = {
            "formatVersion": BACKUP_FORMAT_VERSION,
            "createdAt": timestamp.isoformat(),
            "databaseSchemaVersion": schema_version,
            "files": _manifest_files(staging),
        }
        (staging / BACKUP_MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(staging, output_dir)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _load_and_validate_backup(input_dir: Path) -> dict[str, Any]:
    manifest_path = input_dir / BACKUP_MANIFEST_FILENAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("Backup manifest is missing or invalid") from exc
    if manifest.get("formatVersion") != BACKUP_FORMAT_VERSION:
        raise BackupError("Unsupported backup format version")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise BackupError("Backup manifest has no files")
    for name, expected_digest in files.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name:
            raise BackupError(f"Unsafe backup path: {name}")
        path = input_dir / relative
        if path.is_symlink():
            raise BackupError(f"Backup contains unsupported symlink: {name}")
        if not path.is_file() or _sha256(path) != expected_digest:
            raise BackupError(f"Backup checksum mismatch: {name}")
    actual_files = _manifest_files(input_dir)
    if actual_files != files:
        raise BackupError("Backup contents do not match the manifest")
    database_path = input_dir / HOBAT_DATABASE_FILENAME
    schema_version = _database_schema_version(database_path)
    if schema_version != manifest.get("databaseSchemaVersion"):
        raise BackupError("Backup database schema does not match the manifest")
    return manifest


def _assert_database_available_for_restore(data_dir: Path) -> None:
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    if not database_path.exists():
        return
    connection = sqlite3.connect(database_path, timeout=0.1)
    try:
        connection.execute("PRAGMA busy_timeout=100")
        connection.execute("BEGIN EXCLUSIVE")
        connection.rollback()
    except sqlite3.OperationalError as exc:
        raise BackupError("Hobat database is busy; stop active writers before restore") from exc
    finally:
        connection.close()


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _restore_mount_contents(data_dir: Path, staging: Path, previous: Path) -> None:
    previous.mkdir()
    moved_previous: list[Path] = []
    activated: list[Path] = []
    try:
        for child in data_dir.iterdir():
            os.replace(child, previous / child.name)
            moved_previous.append(child)
        for child in staging.iterdir():
            target = data_dir / child.name
            os.replace(child, target)
            activated.append(target)
    except Exception:
        for child in activated:
            if child.exists():
                _remove_path(child)
        for child in moved_previous:
            previous_child = previous / child.name
            if previous_child.exists():
                os.replace(previous_child, child)
        raise


def restore_backup(data_dir: Path, input_dir: Path) -> dict[str, Any]:
    data_dir = data_dir.resolve()
    input_dir = input_dir.resolve()
    if not input_dir.is_dir():
        raise BackupError(f"Backup directory does not exist: {input_dir}")
    if _is_within(input_dir, data_dir):
        raise BackupError("Backup input must be outside the data directory")
    manifest = _load_and_validate_backup(input_dir)
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = data_dir.parent / f".{data_dir.name}.restore-{uuid.uuid4().hex}"
    previous = data_dir.parent / f".{data_dir.name}.previous-{uuid.uuid4().hex}"
    try:
        shutil.copytree(
            input_dir,
            staging,
            ignore=shutil.ignore_patterns(BACKUP_MANIFEST_FILENAME),
        )
        _database_schema_version(staging / HOBAT_DATABASE_FILENAME)
        _assert_database_available_for_restore(data_dir)
        had_existing = data_dir.exists()
        mounted_data_dir = had_existing and os.path.ismount(data_dir)
        if mounted_data_dir:
            _restore_mount_contents(data_dir, staging, previous)
        elif had_existing:
            os.replace(data_dir, previous)
        if not mounted_data_dir:
            try:
                os.replace(staging, data_dir)
            except Exception:
                if had_existing:
                    os.replace(previous, data_dir)
                raise
        if had_existing:
            shutil.rmtree(previous)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if not os.path.ismount(data_dir) and previous.exists() and not data_dir.exists():
            os.replace(previous, data_dir)
        raise
