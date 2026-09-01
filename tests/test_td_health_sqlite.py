"""Focused transactional tests for the Crawl SQLite health store."""

from __future__ import annotations

import sqlite3

import pytest

from td_health_observation_model import (
    Assessment,
    Completeness,
    Confidence,
    DeviceSample,
    HealthStatus,
    Observation,
)
from td_health_observation_store import HealthStoreFutureSchemaError
from td_health_sqlite import SCHEMA_VERSION, SQLiteHealthStore


def _result(suffix: str = "1") -> tuple[Observation, Assessment]:
    observation = Observation(
        observation_id=f"observation-{suffix}",
        datasource_id="otbr-cli",
        dataset_id="otbr_cli_networkdiag_fetch_all",
        network_id="extpan:78b9775b001c1cbe",
        network_name="island",
        observed_at=f"2026-09-01T00:00:0{suffix}+00:00",
        ingested_at=f"2026-09-01T00:00:0{suffix}+00:00",
        completeness=Completeness.COMPLETE,
        source_set_digest=f"digest-{suffix}",
        sources=(),
        devices=(
            DeviceSample(
                "extaddr:8672766ae0578187",
                "8672766ae0578187",
                "router",
                None,
                False,
                ("snapshot.json",),
            ),
        ),
        relationships=(),
    )
    assessment = Assessment(
        assessment_id=f"assessment-{suffix}",
        observation_id=observation.observation_id,
        policy_version="snapshot-v1",
        policy_digest="policy-digest",
        status=HealthStatus.STRONG,
        confidence=Confidence.HIGH,
        coverage={"devices": True},
        findings=(),
        assessed_at=observation.ingested_at,
    )
    return observation, assessment


def test_atomic_save_is_idempotent_and_sets_sqlite_guards(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    observation, assessment = _result()

    assert store.save_processing_result(observation, assessment).observation_created
    repeated = store.save_processing_result(observation, assessment)
    assert not repeated.observation_created
    assert not repeated.assessment_created

    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1


def test_atomic_save_rolls_back_when_assessment_insert_fails(tmp_path, monkeypatch) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    observation, assessment = _result()

    def fail(*_args):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(store, "_insert_assessment", fail)
    with pytest.raises(RuntimeError, match="injected"):
        store.save_processing_result(observation, assessment)

    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0


def test_future_schema_is_rejected(tmp_path) -> None:
    path = tmp_path / "health.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES (?, CURRENT_TIMESTAMP)",
            (SCHEMA_VERSION + 1,),
        )

    with pytest.raises(HealthStoreFutureSchemaError, match="newer"):
        SQLiteHealthStore(path)


def test_status_vocabulary_migrates_from_schema_version_one(tmp_path) -> None:
    path = tmp_path / "health.db"
    store = SQLiteHealthStore(path)
    observation, assessment = _result()
    store.save_processing_result(observation, assessment)

    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE schema_migrations SET version=1 WHERE version=2")
        connection.execute("UPDATE assessments SET status='healthy'")
        connection.execute(
            "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                assessment.assessment_id,
                "legacy-finding",
                "legacy.rule",
                "unhealthy",
                "device",
                30,
                "Legacy finding",
                "Legacy summary",
                "Legacy reason",
                "{}",
                "high",
                "Legacy action",
                "Legacy verification",
                "[]",
                "[]",
                "[]",
            ),
        )

    SQLiteHealthStore(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT status FROM assessments").fetchone() == ("strong",)
        assert connection.execute("SELECT status FROM findings").fetchone() == ("poor",)


def test_observation_retention_is_bounded(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db", max_observations=2)
    for suffix in ("1", "2", "3"):
        store.save_processing_result(*_result(suffix))

    with sqlite3.connect(store.path) as connection:
        rows = connection.execute(
            "SELECT observation_id FROM observations ORDER BY observed_at"
        ).fetchall()
    assert rows == [("observation-2",), ("observation-3",)]