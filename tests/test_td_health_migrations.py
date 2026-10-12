"""Historical SQLite schema fixtures for health-store migration coverage."""

from __future__ import annotations

import sqlite3
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

import td_health_sqlite
from td_health_observation_store import HealthStoreMigrationError
from td_health_sqlite import (
    SCHEMA_VERSION,
    SQLiteHealthStore,
    _SCHEMA,
    _SCHEMA_V2,
    _V4_TABLES,
)


def _create_schema_fixture(path, version: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.executescript(_SCHEMA_V2 if version <= 2 else _SCHEMA)

        if version < 3:
            assessment_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(assessments)")
            }
            for column in ("evaluator_version", "profile_id"):
                if column in assessment_columns:
                    connection.execute(f"ALTER TABLE assessments DROP COLUMN {column}")

        if version >= 4:
            for table, column, definition in (
                ("assessments", "sample_contract_version", "TEXT NOT NULL DEFAULT 'legacy-unknown'"),
                ("assessments", "health_policy_digest", "TEXT"),
                ("metric_samples", "metric_kind", "TEXT NOT NULL DEFAULT 'legacy-unknown'"),
                ("metric_samples", "denominator_kind", "TEXT NOT NULL DEFAULT 'legacy-unknown'"),
                ("observation_sources", "source_observed_at", "TEXT"),
                ("relationship_samples", "queued_message_count", "REAL"),
            ):
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            for statement in _V4_TABLES:
                connection.execute(statement)

        if version < 5:
            expected_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(expected_devices)")
            }
            for column in ("revision", "reason", "expected_since", "change_source"):
                if column in expected_columns:
                    connection.execute(f"ALTER TABLE expected_devices DROP COLUMN {column}")
            for table in (
                "network_roster_revisions",
                "roster_lifecycle_events",
                "roster_mutation_receipts",
            ):
                if connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone():
                    connection.execute(f"DROP TABLE {table}")

        if version < 6:
            assessment_columns = [
                (row[1], row[2], row[3], row[4], row[5])
                for row in connection.execute("PRAGMA table_info(assessments)")
                if row[1] not in {
                    "roster_context_digest",
                    "network_roster_revision",
                    "presence_input_digest",
                    "reproduction_context_json",
                }
            ]
            declarations = []
            for name, kind, not_null, default, primary_key in assessment_columns:
                parts = [name, kind]
                if not_null:
                    parts.append("NOT NULL")
                if default is not None:
                    parts.extend(("DEFAULT", str(default)))
                if primary_key:
                    parts.append("PRIMARY KEY")
                declarations.append(" ".join(parts))
            declarations.append(
                "UNIQUE (observation_id, policy_digest)"
            )
            connection.execute(
                "CREATE TABLE assessments_legacy ("
                + ", ".join(declarations)
                + ", FOREIGN KEY(observation_id) REFERENCES observations(observation_id) ON DELETE CASCADE)"
            )
            connection.execute("DROP TABLE assessments")
            connection.execute("ALTER TABLE assessments_legacy RENAME TO assessments")

        if 5 <= version < 7 and connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='roster_mutation_receipts'"
        ).fetchone():
            connection.execute("ALTER TABLE roster_mutation_receipts DROP COLUMN device_id")

        if version >= 7:
            connection.execute(
                "CREATE INDEX idx_roster_receipts_network_device "
                "ON roster_mutation_receipts(network_id, device_id)"
            )

        if version >= 8:
            SQLiteHealthStore._ensure_schema_v8(connection)
            connection.execute("DELETE FROM schema_migrations")

        if version >= 9:
            td_health_sqlite._migration_v9(connection)

        connection.execute("DELETE FROM schema_migrations")
        if version == 1:
            connection.execute(
                "INSERT INTO schema_migrations VALUES (1, CURRENT_TIMESTAMP)"
            )
        else:
            connection.executemany(
                "INSERT INTO schema_migrations VALUES (?, CURRENT_TIMESTAMP)",
                ((item,) for item in range(2, version + 1)),
            )

        assessment_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(assessments)")
        }
        values = {
            "assessment_id": "'assessment-fixture'",
            "observation_id": "'observation-fixture'",
            "policy_version": "'legacy'",
            "policy_digest": "'fixture-policy'",
            "status": "'healthy'" if version == 1 else "'strong'",
            "confidence": "'high'",
            "coverage_json": "'{}'",
            "assessed_at": "'2026-10-01T00:00:00+00:00'",
        }
        for column in (
            "evaluator_version",
            "profile_id",
            "sample_contract_version",
            "health_policy_digest",
            "roster_context_digest",
            "network_roster_revision",
            "presence_input_digest",
            "reproduction_context_json",
        ):
            if column in assessment_columns:
                values[column] = (
                    "0" if column == "network_roster_revision" else
                    "NULL" if column == "health_policy_digest" else
                    "'{}'" if column == "reproduction_context_json" else
                    "'legacy-unknown'"
                )
        names = ", ".join(values)
        literals = ", ".join(values.values())
        connection.execute(
            f"INSERT INTO assessments ({names}) VALUES ({literals})"
        )
        connection.execute(
            """INSERT INTO observations VALUES
               ('observation-fixture', 'source', 'dataset',
                'extpan:78b9775b001c1cbe', NULL, '2026-10-01T00:00:00+00:00',
                '2026-10-01T00:00:00+00:00', 'complete', 'fixture-digest')"""
        )
        if version >= 8:
            connection.execute(
                """INSERT INTO health_assessment_preferences
                   (observation_id, assessment_id, selection_basis_assessment_id,
                    origin, migration_id)
                   VALUES ('observation-fixture', 'assessment-fixture',
                           'assessment-fixture', 'native', NULL)"""
            )


def _schema_layout(connection: sqlite3.Connection) -> dict[str, tuple]:
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    layout = {}
    for table in tables:
        escaped_table = table.replace('"', '""')
        columns = tuple(
            sorted(
                tuple(row[index] for index in (1, 2, 3, 4, 5))
                for row in connection.execute(
                    f'PRAGMA table_info("{escaped_table}")'
                )
            )
        )
        foreign_keys = tuple(
            sorted(
                tuple(row[index] for index in (2, 3, 4, 5, 6, 7))
                for row in connection.execute(
                    f'PRAGMA foreign_key_list("{escaped_table}")'
                )
            )
        )
        indexes = []
        for index in connection.execute(f'PRAGMA index_list("{escaped_table}")'):
            escaped_index = index[1].replace('"', '""')
            index_columns = tuple(
                row[2]
                for row in connection.execute(
                    f'PRAGMA index_info("{escaped_index}")'
                )
            )
            indexes.append((index[1], bool(index[2]), index_columns))
        layout[table] = columns, foreign_keys, tuple(sorted(indexes))
    return layout


@pytest.mark.parametrize("version", range(1, SCHEMA_VERSION + 1))
def test_historical_schema_fixture_has_version_specific_layout(tmp_path, version) -> None:
    path = tmp_path / f"schema-v{version}.db"
    _create_schema_fixture(path, version)

    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(assessments)")
        }
        ledger = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert connection.execute(
            "SELECT assessment_id, status FROM assessments"
        ).fetchone() == (
            "assessment-fixture",
            "healthy" if version == 1 else "strong",
        )
        assert ("evaluator_version" in columns) is (version >= 3)
        assert ("sample_contract_version" in columns) is (version >= 4)
        assert ("roster_context_digest" in columns) is (version >= 6)
        assert {
            "device_fact_samples",
            "device_last_known",
            "device_identity_conflicts",
            "comparisons",
            "comparison_items",
        } <= tables if version >= 4 else not (
            tables & {
                "device_fact_samples",
                "device_last_known",
                "device_identity_conflicts",
                "comparisons",
                "comparison_items",
            }
        )
        expected_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(expected_devices)")
        }
        assert {
            "revision", "reason", "expected_since", "change_source"
        } <= expected_columns if version >= 5 else not (
            expected_columns & {"revision", "reason", "expected_since", "change_source"}
        )
        assert ("network_roster_revisions" in tables) is (version >= 5)
        assert ("health_assessment_preferences" in tables) is (version >= 8)
        comparison_columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(comparison_items)"
            )
        } if version >= 4 else set()
        assert ("relationship_type" in comparison_columns) is (version >= 9)
        assessment_unique_shapes = {
            tuple(
                row[2]
                for row in connection.execute(f"PRAGMA index_info('{index[1]}')")
            )
            for index in connection.execute("PRAGMA index_list(assessments)")
            if index[2]
        }
        assert (
            ("observation_id", "policy_digest", "roster_context_digest")
            in assessment_unique_shapes
        ) is (version >= 6)
        assert (
            ("observation_id", "policy_digest") in assessment_unique_shapes
        ) is (version < 6)
        receipt_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(roster_mutation_receipts)")
        } if version >= 5 else set()
        assert ("device_id" in receipt_columns) is (version >= 7)
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' "
                "AND name='idx_roster_receipts_network_device'"
            ).fetchone() is not None
        ) is (version >= 7)
        assert ledger == (
            [1] if version == 1 else list(range(2, version + 1))
        )


@pytest.mark.parametrize("version", range(1, SCHEMA_VERSION + 1))
def test_historical_schema_upgrades_to_current_with_rows_preserved(tmp_path, version) -> None:
    path = tmp_path / f"upgrade-v{version}.db"
    _create_schema_fixture(path, version)

    SQLiteHealthStore(path)

    with sqlite3.connect(path) as connection:
        expected_ledger = (
            list(range(1, SCHEMA_VERSION + 1))
            if version == 1
            else list(range(2, SCHEMA_VERSION + 1))
        )
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(item,) for item in expected_ledger]
        assert connection.execute(
            "SELECT assessment_id, status, evaluator_version FROM assessments"
        ).fetchone() == (
            "assessment-fixture",
            "strong",
            "legacy-unknown",
        )
        assert connection.execute(
            "SELECT observation_id, network_id FROM observations"
        ).fetchone() == (
            "observation-fixture",
            "extpan:78b9775b001c1cbe",
        )
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        if version == 1:
            fresh_path = tmp_path / "fresh-v8.db"
            SQLiteHealthStore(fresh_path)
            with sqlite3.connect(fresh_path) as fresh:
                assert _schema_layout(connection) == _schema_layout(fresh)


def test_schema_validation_quotes_database_index_names(tmp_path) -> None:
    path = tmp_path / "quoted-index.db"
    SQLiteHealthStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            'CREATE UNIQUE INDEX "odd; DROP TABLE assessments; --" '
            "ON assessments(status)"
        )
        assert ("status",) in td_health_sqlite._index_columns(
            connection, "assessments"
        )
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='assessments'"
        ).fetchone() is not None


def test_migration_failure_rolls_back_schema_data_and_ledger_then_retry_succeeds(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "retry.db"
    _create_schema_fixture(path, 3)
    with sqlite3.connect(path) as connection:
        before_objects = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        before_ledger = connection.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        before_assessments = connection.execute(
            "SELECT * FROM assessments"
        ).fetchall()

    original_registry = td_health_sqlite.SCHEMA_MIGRATIONS
    original_v4 = next(
        migration for migration in original_registry
        if migration.to_version == 4
    )

    def fail_after_v4(connection):
        original_v4.apply(connection)
        raise RuntimeError("injected after schema v4 DDL")

    monkeypatch.setattr(
        td_health_sqlite,
        "SCHEMA_MIGRATIONS",
        tuple(
            replace(migration, apply=fail_after_v4)
            if migration.to_version == 4
            else migration
            for migration in original_registry
        ),
    )
    with pytest.raises(HealthStoreMigrationError) as error:
        SQLiteHealthStore(path)
    assert error.value.category == "migration-failed"

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall() == before_objects
        assert connection.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall() == before_ledger
        assert connection.execute("SELECT * FROM assessments").fetchall() == before_assessments
    backups = list((tmp_path / ".migration-backups").glob("*.sqlite"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    monkeypatch.setattr(
        td_health_sqlite, "SCHEMA_MIGRATIONS", original_registry
    )
    SQLiteHealthStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone() == (SCHEMA_VERSION,)


def test_schema_v9_failure_rolls_back_column_and_ledger_then_retry_succeeds(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "retry-v9.db"
    _create_schema_fixture(path, 8)
    with sqlite3.connect(path) as connection:
        before_objects = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        before_ledger = connection.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()

    original_registry = td_health_sqlite.SCHEMA_MIGRATIONS
    original_v9 = next(
        migration for migration in original_registry
        if migration.to_version == 9
    )

    def fail_after_v9(connection):
        original_v9.apply(connection)
        raise RuntimeError("injected after schema v9 DDL")

    monkeypatch.setattr(
        td_health_sqlite,
        "SCHEMA_MIGRATIONS",
        tuple(
            replace(migration, apply=fail_after_v9)
            if migration.to_version == 9
            else migration
            for migration in original_registry
        ),
    )
    with pytest.raises(HealthStoreMigrationError) as error:
        SQLiteHealthStore(path)
    assert error.value.category == "migration-failed"
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall() == before_objects
        assert connection.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall() == before_ledger
        assert "relationship_type" not in {
            row[1] for row in connection.execute(
                "PRAGMA table_info(comparison_items)"
            )
        }
    monkeypatch.setattr(
        td_health_sqlite, "SCHEMA_MIGRATIONS", original_registry
    )
    SQLiteHealthStore(path)
    with sqlite3.connect(path) as connection:
        relationship_type = next(
            row for row in connection.execute(
                "PRAGMA table_info(comparison_items)"
            )
            if row[1] == "relationship_type"
        )
        assert relationship_type[2:5] == ("TEXT", 0, None)
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone() == (9,)


def test_backup_publication_failure_leaves_database_unchanged(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "backup-failure.db"
    _create_schema_fixture(path, 3)
    with sqlite3.connect(path) as connection:
        before_objects = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        before_ledger = connection.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
    def fail_link(*_args):
        raise OSError("injected publication failure")

    monkeypatch.setattr(td_health_sqlite.os, "link", fail_link)

    with pytest.raises(HealthStoreMigrationError) as error:
        SQLiteHealthStore(path)

    assert error.value.category == "backup-failed"
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall() == before_objects
        assert connection.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall() == before_ledger
    recovery_dir = tmp_path / ".migration-backups"
    assert not list(recovery_dir.glob("*.sqlite"))
    assert not list(recovery_dir.glob("*.partial"))


@pytest.mark.parametrize("versions", [(2, 4), (0,), (SCHEMA_VERSION + 1,)])
def test_invalid_ledgers_fail_closed(versions, tmp_path) -> None:
    path = tmp_path / "invalid-ledger.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES (?, CURRENT_TIMESTAMP)",
            ((version,) for version in versions),
        )

    if versions == (SCHEMA_VERSION + 1,):
        error = td_health_sqlite.HealthStoreFutureSchemaError
    else:
        error = HealthStoreMigrationError
    with pytest.raises(error):
        SQLiteHealthStore(path)


def _delayed_migration_process(path, marker, *, sleep_seconds: int = 2):
    script = """
import sys
import time
from dataclasses import replace
from pathlib import Path
import td_health_sqlite as health
registry = health.SCHEMA_MIGRATIONS
def delayed(connection):
    original.apply(connection)
    Path(sys.argv[2]).write_text("ready")
    time.sleep(int(sys.argv[3]))
original = next(item for item in registry if item.to_version == 4)
health.SCHEMA_MIGRATIONS = tuple(
    replace(item, apply=delayed) if item.to_version == 4 else item
    for item in registry
)
health.SQLiteHealthStore(Path(sys.argv[1]))
print("migrated", flush=True)
"""
    environment = os.environ.copy()
    source_path = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (source_path, environment.get("PYTHONPATH")))
    )
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(path),
            str(marker),
            str(sleep_seconds),
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_marker(process, marker: Path) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if marker.exists():
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(f"migration subprocess exited early: {stdout}\n{stderr}")
        time.sleep(0.05)
    process.terminate()
    process.wait(timeout=5)
    pytest.fail("migration subprocess did not reach its DDL marker")


def test_wal_reader_stays_available_during_locked_migration(tmp_path) -> None:
    path = tmp_path / "wal-reader.db"
    _create_schema_fixture(path, 3)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    reader = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    reader.execute("BEGIN")
    assert reader.execute("SELECT MAX(version) FROM schema_migrations").fetchone() == (3,)
    marker = tmp_path / "migration-ready"
    process = _delayed_migration_process(path, marker)
    try:
        _wait_for_marker(process, marker)
        assert reader.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone() == (3,)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        assert stdout.strip() == "migrated"
    finally:
        reader.close()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone() == (SCHEMA_VERSION,)


def test_competing_writer_gets_bounded_migration_busy_error(tmp_path) -> None:
    path = tmp_path / "busy.db"
    _create_schema_fixture(path, 3)
    writer = sqlite3.connect(path)
    writer.execute("BEGIN IMMEDIATE")
    try:
        script = (
            "from pathlib import Path; "
            "from td_health_sqlite import SQLiteHealthStore; "
            "from td_health_observation_store import HealthStoreMigrationError; "
            "import sys; "
            "\ntry: SQLiteHealthStore(Path(sys.argv[1]))"
            "\nexcept HealthStoreMigrationError as error: print(error.category)"
        )
        environment = os.environ.copy()
        source_path = str(Path(__file__).resolve().parents[1] / "src")
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (source_path, environment.get("PYTHONPATH")))
        )
        result = subprocess.run(
            [sys.executable, "-c", script, str(path)],
            capture_output=True,
            text=True,
            timeout=10,
            env=environment,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "migration-busy"
    finally:
        writer.rollback()
        writer.close()


def test_terminated_migration_rolls_back_and_retry_succeeds(tmp_path) -> None:
    path = tmp_path / "interrupted.db"
    _create_schema_fixture(path, 3)
    marker = tmp_path / "migration-ready"
    process = _delayed_migration_process(path, marker, sleep_seconds=30)
    _wait_for_marker(process, marker)
    process.terminate()
    process.wait(timeout=10)
    stdout, stderr = process.communicate()
    assert "Traceback" not in stderr
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(2,), (3,)]
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='device_fact_samples'"
        ).fetchone() is None
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert len(list((tmp_path / ".migration-backups").glob("*.sqlite"))) == 1

    SQLiteHealthStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone() == (SCHEMA_VERSION,)
    assert len(list((tmp_path / ".migration-backups").glob("*.sqlite"))) == 2
