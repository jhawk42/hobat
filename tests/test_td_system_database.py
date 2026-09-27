"""Tests for Hobat SQLite database maintenance."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

import td_system_database
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_system_database import DatabaseRepackError, repack_database


def _create_database(data_dir):
    data_dir.mkdir()
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.execute(
                "CREATE TABLE retained (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute("INSERT INTO retained VALUES (1, 'keep me')")
            connection.execute("CREATE TABLE discarded (payload BLOB NOT NULL)")
            connection.executemany(
                "INSERT INTO discarded VALUES (?)",
                [(b"x" * 8192,) for _ in range(64)],
            )
            connection.execute("DELETE FROM discarded")
    return database_path


def test_repack_preserves_data_and_schema_and_clears_free_pages(tmp_path) -> None:
    data_dir = tmp_path / "data"
    database_path = _create_database(data_dir)
    with closing(sqlite3.connect(database_path)) as connection:
        schema_before = connection.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        assert connection.execute("PRAGMA freelist_count").fetchone()[0] > 0

    assert repack_database(data_dir) == database_path

    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute(
            "SELECT id, value FROM retained ORDER BY id"
        ).fetchall() == [(1, "keep me")]
        assert connection.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall() == schema_before
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA freelist_count").fetchone() == (0,)


def test_repack_does_not_create_a_missing_database(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database_path = data_dir / HOBAT_DATABASE_FILENAME

    with pytest.raises(DatabaseRepackError, match="not available"):
        repack_database(data_dir)

    assert not database_path.exists()


def test_repack_reports_an_invalid_database(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    database_path.write_bytes(b"not a sqlite database")

    with pytest.raises(DatabaseRepackError, match="Could not repack"):
        repack_database(data_dir)


def test_repack_reports_a_busy_database(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    database_path = _create_database(data_dir)
    monkeypatch.setattr(td_system_database, "_SQLITE_BUSY_TIMEOUT_SECONDS", 0.01)

    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("BEGIN EXCLUSIVE")
        with pytest.raises(DatabaseRepackError, match="database is busy"):
            repack_database(data_dir)
        connection.rollback()