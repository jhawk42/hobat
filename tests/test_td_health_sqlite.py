"""Focused transactional tests for the Crawl SQLite health store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from td_health_observation_model import (
    Assessment,
    Completeness,
    Confidence,
    DeviceSample,
    Finding,
    FindingRank,
    FindingScope,
    HealthStatus,
    MetricSample,
    Observation,
    RelationshipSample,
    SourceEvidence,
)
from td_health_observation_store import HealthStoreFutureSchemaError
from td_health_comparison import (
    COMPARISON_INTERVALS,
    ComparisonPolicy,
    comparison_id,
)
from td_health_read import TDHealthReadService
from td_health_roster import RosterFact
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_sqlite import SCHEMA_VERSION, SQLiteHealthStore, _SCHEMA
from td_health_sqlite import StaleRosterContextError


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
        evaluator_version="snapshot-test",
        profile_id="profile-test",
        status=HealthStatus.STRONG,
        confidence=Confidence.HIGH,
        coverage={"devices": True},
        findings=(),
        assessed_at=observation.ingested_at,
    )
    return observation, assessment


def _result_with_metric(
    metric: str,
    value: float,
    unit: str,
    denominator: float | None,
    *,
    suffix: str = "1",
) -> tuple[Observation, Assessment]:
    observation, assessment = _result(suffix)
    filename = "td-otbr-cli-networkdiag-fetch-all.json"
    source = SourceEvidence(
        filename, "source-digest", "final", "valid", observation.observed_at
    )
    observation = replace(
        observation,
        source_set_digest=hashlib.sha256(
            f"{filename}:source-digest".encode("utf-8")
        ).hexdigest(),
        sources=(source,),
        devices=tuple(
            replace(device, source_files=(filename,))
            for device in observation.devices
        ),
        metrics=(
            MetricSample(
                observation.devices[0].device_id,
                metric,
                value,
                unit,
                denominator,
                filename,
            ),
        ),
    )
    return observation, assessment


def _reconstruct_observation(
    store: SQLiteHealthStore, assessment_id: str
) -> Observation:
    with closing(store._connect()) as connection:
        row = connection.execute(
            """SELECT a.*, o.datasource_id, o.dataset_id, o.network_id,
                      o.network_name, o.observed_at, o.ingested_at, o.completeness,
                      o.source_set_digest
               FROM assessments a JOIN observations o USING (observation_id)
               WHERE a.assessment_id=?""",
            (assessment_id,),
        ).fetchone()
        assert row is not None
        return SQLiteHealthStore._retained_observation(connection, row)


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
        assert connection.execute(
            "SELECT evaluator_version, profile_id FROM assessments"
        ).fetchone() == ("snapshot-test", "profile-test")


def test_initialized_schema_matches_frozen_contract(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")

    with sqlite3.connect(store.path) as connection:
        schema_objects = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        max_migration = connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0]

    schema_objects_digest = hashlib.sha256(
        json.dumps(
            schema_objects,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert hashlib.sha256(_SCHEMA.encode("utf-8")).hexdigest() == (
        "309af9199b3f0c778a99407e89433d1f6da6f052604fcf6bdc8cbf51b72e9189"
    )
    assert schema_objects_digest == (
        "9cdea3a1c0665ab4f0a69904222cc8840cf00b891ecb398d4378b632b30b5fb4"
    )
    assert SCHEMA_VERSION == 8
    assert max_migration == 8


def test_roster_source_time_and_partial_observation_do_not_refresh_projection(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    filename = "td-otbr-cli-networkdiag-fetch-all.json"
    first_time = "2026-09-01T00:00:00+00:00"
    second_time = "2026-09-02T00:00:00+00:00"

    def save(suffix: str, value: str, source_time: str, completeness=Completeness.COMPLETE):
        observation, assessment = _result(suffix)
        observation = replace(observation, completeness=completeness,
                              sources=(SourceEvidence(filename, f"digest-{suffix}", "final", "valid", source_time),))
        fact = RosterFact(observation.devices[0].device_id, "role", json.dumps(value),
                          "transient", filename, 3, "high")
        store.save_processing_result(observation, assessment, roster_facts=(fact,))
        return observation

    first = save("1", "router", first_time)
    second = save("2", "child", first_time)
    save("3", "leader", second_time, Completeness.PARTIAL)
    with sqlite3.connect(store.path) as connection:
        current = connection.execute(
            "SELECT value_json, observation_id, source_observed_at FROM device_last_known WHERE field_key='role'"
        ).fetchone()
        assert current == ('"router"', first.observation_id, first_time)
        assert connection.execute(
            "SELECT COUNT(*) FROM device_fact_samples WHERE field_key='role'"
        ).fetchone()[0] == 3
        assert connection.execute(
            "SELECT value_json FROM device_fact_samples WHERE observation_id=? AND field_key='role'",
            (second.observation_id,),
        ).fetchone()[0] == '"child"'


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


def test_reconcile_current_assessments_removes_only_stale_pointers(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    active_observation, active_assessment = _result("1")
    stale_observation, stale_assessment = _result("2")
    stale_observation = replace(stale_observation, dataset_id="retired-dataset")
    store.save_processing_result(active_observation, active_assessment)
    store.save_processing_result(stale_observation, stale_assessment)

    assert store.reconcile_current_assessments(
        (active_observation.dataset_id,)
    ) == 1

    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT dataset_id FROM current_assessments"
        ).fetchall() == [(active_observation.dataset_id,)]
        assert connection.execute("SELECT COUNT(*) FROM assessments").fetchone() == (2,)


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


def test_schema_three_records_explicit_assessment_provenance(tmp_path) -> None:
    path = tmp_path / "health.db"
    store = SQLiteHealthStore(path)
    store.save_processing_result(*_result())

    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(assessments)")
        }
        versions = {
            row[0] for row in connection.execute("SELECT version FROM schema_migrations")
        }

    assert {"evaluator_version", "profile_id"} <= columns
    assert 3 in versions


def test_schema_two_assessments_migrate_with_unknown_legacy_provenance(tmp_path) -> None:
    path = tmp_path / "health.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES (2, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            """CREATE TABLE observations(
                observation_id TEXT PRIMARY KEY, datasource_id TEXT NOT NULL,
                dataset_id TEXT NOT NULL, network_id TEXT NOT NULL, network_name TEXT,
                observed_at TEXT NOT NULL, ingested_at TEXT NOT NULL,
                completeness TEXT NOT NULL, source_set_digest TEXT NOT NULL
            )"""
        )
        connection.execute(
            """INSERT INTO observations VALUES
               ('o', 'source', 'dataset', 'extpan:78b9775b001c1cbe', NULL,
                '2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00',
                'complete', 'digest')"""
        )
        connection.execute(
            """CREATE TABLE assessments (
                assessment_id TEXT PRIMARY KEY,
                observation_id TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                policy_digest TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence TEXT NOT NULL,
                coverage_json TEXT NOT NULL,
                assessed_at TEXT NOT NULL,
                UNIQUE (observation_id, policy_digest)
            )"""
        )
        connection.execute(
            "INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("a", "o", "p", "d", "strong", "high", "{}", "2026-09-01T00:00:00+00:00"),
        )

    SQLiteHealthStore(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT evaluator_version, profile_id FROM assessments"
        ).fetchone() == ("legacy-unknown", "legacy-unknown")
        assert connection.execute("SELECT assessment_id FROM assessments").fetchone() == ("a",)
        assert connection.execute(
            "SELECT roster_context_digest, presence_input_digest FROM assessments"
        ).fetchone() == ("legacy-unknown", "legacy-unknown")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_current_assessment_orders_offset_timestamps_by_utc_instant(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    first, first_assessment = _result("1")
    second, second_assessment = _result("2")
    first = replace(first, observed_at="2026-09-01T00:00:00+00:00")
    first_assessment = replace(first_assessment, assessed_at="2026-09-01T00:00:00+00:00")
    second = replace(second, observed_at="2026-09-01T01:00:00+02:00")
    second_assessment = replace(second_assessment, assessed_at="2026-09-01T01:00:00+02:00")
    store.save_processing_result(first, first_assessment)
    store.save_processing_result(second, second_assessment)

    current = store.latest_assessment(first.network_id, first.dataset_id)
    assert current["assessment_id"] == first_assessment.assessment_id


def test_observation_retention_is_bounded(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db", max_observations=2)
    for suffix in ("1", "2", "3"):
        store.save_processing_result(*_result(suffix))

    with sqlite3.connect(store.path) as connection:
        rows = connection.execute(
            "SELECT observation_id FROM observations ORDER BY observed_at"
        ).fetchall()
    assert rows == [("observation-2",), ("observation-3",)]


def test_observation_retention_prunes_orphaned_identities(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db", max_observations=1)
    expired_observation, expired_assessment = _result("1")
    expired_device = expired_observation.devices[0]
    orphaned_device = DeviceSample(
        "extaddr:8899aabbccddeeff",
        "8899aabbccddeeff",
        "child",
        None,
        False,
        ("snapshot.json",),
    )
    expired_observation = replace(
        expired_observation,
        devices=(expired_device, orphaned_device),
    )
    retained_device = DeviceSample(
        "extaddr:0011223344556677",
        "0011223344556677",
        "child",
        None,
        False,
        ("snapshot.json",),
    )
    retained_observation, retained_assessment = _result("2")
    retained_observation = replace(
        retained_observation,
        devices=(retained_device,),
        relationships=(
            RelationshipSample(
                "relationship-retained",
                "neighbor",
                retained_device.device_id,
                expired_device.device_id,
                3,
                3,
                None,
                None,
                None,
                None,
                None,
                retained_device.device_id,
                ("snapshot.json",),
            ),
        ),
    )

    store.upsert_expected_device(
        expired_observation.network_id, expired_device.device_id, "Retained roster"
    )
    store.save_processing_result(expired_observation, expired_assessment)
    store.save_processing_result(retained_observation, retained_assessment)

    with sqlite3.connect(store.path) as connection:
        device_ids = {
            row[0] for row in connection.execute("SELECT device_id FROM devices")
        }
        assert device_ids == {expired_device.device_id, retained_device.device_id}
        assert orphaned_device.device_id not in device_ids
        assert connection.execute(
            "SELECT relationship_id FROM relationships"
        ).fetchall() == [("relationship-retained",)]


def test_age_purge_is_exclusive_preserves_roster_and_supports_dry_run(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    store.upsert_expected_device(
        "extpan:78b9775b001c1cbe", "extaddr:8672766ae0578187", "Router"
    )
    for suffix in ("1", "2", "3"):
        store.save_processing_result(*_result(suffix))
    cutoff = datetime(2026, 9, 1, 0, 0, 3, tzinfo=timezone.utc)

    preview = store.purge_before(cutoff, dry_run=True)
    assert preview.deleted["observations"] == 2
    assert store.store_capabilities()["observationCount"] == 3

    result = store.purge_before(cutoff)
    assert result.cutoff == "2026-09-01T00:00:03+00:00"
    assert result.deleted["observations"] == 2
    assert result.deleted["expected_devices"] == 0
    assert store.store_capabilities()["observationCount"] == 1
    assert store.latest_assessment(
        "extpan:78b9775b001c1cbe", "otbr_cli_networkdiag_fetch_all"
    )["assessment_id"] == "assessment-3"


def test_purge_all_removes_health_records_but_preserves_other_tables(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    store.upsert_expected_device(
        "extpan:78b9775b001c1cbe", "extaddr:8672766ae0578187", "Router"
    )
    store.save_processing_result(*_result())
    with sqlite3.connect(store.path) as connection:
        connection.execute("CREATE TABLE other_hobat_data(value TEXT)")
        connection.execute("INSERT INTO other_hobat_data VALUES ('keep')")

    preview = store.purge_all(dry_run=True)
    assert preview.deleted["observations"] == 1
    assert store.store_capabilities()["observationCount"] == 1

    result = store.purge_all()
    assert result.deleted["observations"] == 1
    assert result.deleted["expected_devices"] == 1
    assert result.deleted["roster_lifecycle_events"] == 1
    assert result.deleted["network_roster_revisions"] == 1
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT value FROM other_hobat_data").fetchone() == ("keep",)
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] > 0
    repeated = store.purge_all()
    assert all(count == 0 for count in repeated.deleted.values())


def test_purge_device_removes_identity_and_invalidates_affected_assessment(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    store.upsert_expected_device(
        "extpan:78b9775b001c1cbe", "extaddr:8672766ae0578187", "Router"
    )
    store.save_processing_result(*_result())

    preview = store.purge_device("extaddr:8672766ae0578187", dry_run=True)
    assert preview.deleted["assessments"] == 1
    assert store.store_capabilities()["assessmentCount"] == 1

    result = store.purge_device("extaddr:8672766ae0578187")
    assert result.deleted["assessments"] == 1
    assert result.deleted["device_samples"] == 1
    assert result.deleted["expected_devices"] == 1
    assert store.store_capabilities()["observationCount"] == 1
    assert store.store_capabilities()["assessmentCount"] == 0
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM current_assessments").fetchone()[0] == 0


def test_purging_expected_device_invalidates_pending_processing_context(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    network_id = "extpan:78b9775b001c1cbe"
    device_id = "extaddr:8672766ae0578187"
    store.upsert_expected_device(network_id, device_id, "Router")
    observation, assessment = _result()
    assessment = replace(
        assessment, roster_context_digest="roster-context",
        network_roster_revision=1,
    )

    store.purge_device(device_id, network_id=network_id)

    with pytest.raises(StaleRosterContextError, match="Roster changed"):
        store.save_processing_result(observation, assessment)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT revision FROM network_roster_revisions WHERE network_id=?",
            (network_id,),
        ).fetchone() == (2,)
        assert connection.execute("SELECT COUNT(*) FROM assessments").fetchone() == (0,)


def test_device_purge_removes_noop_receipts_for_the_scoped_device(tmp_path) -> None:
    from td_health_roster_mutation import apply_browser_roster_action

    store = SQLiteHealthStore(tmp_path / "health.db")
    network_id = "extpan:78b9775b001c1cbe"
    device_id = "extaddr:8672766ae0578187"
    store.upsert_expected_device(network_id, device_id, "Router")
    action = {
        "network_id": network_id, "device_id": device_id,
        "action": "mark-offline", "expected_revision": 1,
        "context_assessment_id": None, "device_label": None, "reason": None,
    }
    apply_browser_roster_action(
        store, **action, request_id="63b4c344-c7f9-41ce-9f3e-a62d4eb7b116",
    )
    action["expected_revision"] = 2
    result, changed = apply_browser_roster_action(
        store, **action, request_id="73b4c344-c7f9-41ce-9f3e-a62d4eb7b116",
    )
    assert not changed
    assert result["eventId"] is None

    store.purge_device(device_id, network_id=network_id)

    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM roster_mutation_receipts WHERE device_id=?",
            (device_id,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT revision FROM network_roster_revisions WHERE network_id=?",
            (network_id,),
        ).fetchone() == (3,)


def test_schema_seven_adds_and_backfills_receipt_device_scope(tmp_path) -> None:
    from td_health_roster_mutation import apply_browser_roster_action

    path = tmp_path / "health.db"
    store = SQLiteHealthStore(path)
    network_id = "extpan:78b9775b001c1cbe"
    device_id = "extaddr:8672766ae0578187"
    store.upsert_expected_device(network_id, device_id, "Router")
    apply_browser_roster_action(
        store, network_id=network_id, device_id=device_id, action="mark-offline",
        request_id="63b4c344-c7f9-41ce-9f3e-a62d4eb7b116",
        expected_revision=1, context_assessment_id=None, device_label=None, reason=None,
    )
    apply_browser_roster_action(
        store, network_id=network_id, device_id=device_id, action="mark-offline",
        request_id="73b4c344-c7f9-41ce-9f3e-a62d4eb7b116",
        expected_revision=2, context_assessment_id=None, device_label=None, reason=None,
    )
    with sqlite3.connect(path) as connection:
        connection.execute("DROP INDEX idx_roster_receipts_network_device")
        connection.execute("ALTER TABLE roster_mutation_receipts DROP COLUMN device_id")
        connection.execute("DELETE FROM schema_migrations WHERE version=7")

    migrated = SQLiteHealthStore(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT DISTINCT device_id FROM roster_mutation_receipts"
        ).fetchall() == [(device_id,)]
        assert connection.execute(
            "SELECT version FROM schema_migrations WHERE version=7"
        ).fetchone() == (7,)
    result = migrated.purge_device(device_id, network_id=network_id)
    assert result.deleted["roster_mutation_receipts"] == 2


def test_legacy_assessment_endpoint_uses_zero_roster_revision(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    observation, assessment = _result()
    store.save_processing_result(observation, assessment)
    with sqlite3.connect(store.path) as connection:
        connection.execute("ALTER TABLE assessments DROP COLUMN network_roster_revision")

    page = store.assessment_endpoint_page(
        network_id=observation.network_id,
        dataset_id=observation.dataset_id,
        side="after", limit=10, offset=0,
    )

    assert page["items"][0]["assessmentId"] == assessment.assessment_id
    assert page["items"][0]["networkRosterRevision"] == 0


def test_schema_seven_endpoint_inventory_deduplicates_revisions(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    observation, assessment = _result()
    store.save_processing_result(observation, assessment)
    revised = replace(
        assessment,
        assessment_id="assessment-1-revision",
        assessed_at="2026-09-02T00:00:00+00:00",
        roster_context_digest="new-roster-context",
    )
    store.save_processing_result(observation, revised)
    with closing(store._connect()) as connection, connection:
        connection.execute("DELETE FROM schema_migrations WHERE version=8")

    page = store.assessment_endpoint_page(
        network_id=observation.network_id,
        dataset_id=observation.dataset_id,
        side="after",
        limit=10,
        offset=0,
    )
    pinned_page = store.assessment_endpoint_page(
        network_id=observation.network_id,
        dataset_id=observation.dataset_id,
        side="after",
        limit=10,
        offset=0,
        selected_assessment_id=assessment.assessment_id,
    )

    assert page["total"] == 1
    assert [row["assessmentId"] for row in page["items"]] == [
        revised.assessment_id
    ]
    assert pinned_page["total"] == 2
    assert {row["assessmentId"] for row in pinned_page["items"]} == {
        assessment.assessment_id,
        revised.assessment_id,
    }


def test_reprocessing_purged_assessment_restores_preference_but_missing_preference_is_corrupt(
    tmp_path,
) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    observation, assessment = _result()
    store.save_processing_result(observation, assessment)
    with closing(store._connect()) as connection, connection:
        connection.execute(
            "DELETE FROM assessments WHERE assessment_id=?",
            (assessment.assessment_id,),
        )

    restored = store.save_processing_result(observation, assessment)
    assert restored.assessment_created

    with closing(store._connect()) as connection, connection:
        connection.execute(
            "DELETE FROM health_assessment_preferences WHERE observation_id=?",
            (observation.observation_id,),
        )
    with pytest.raises(
        sqlite3.DatabaseError,
        match="Schema-8 assessment preference is missing",
    ):
        store.save_processing_result(observation, assessment)


def test_purge_device_preserves_other_network_fact_samples(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    first, first_assessment = _result("1")
    second, second_assessment = _result("2")
    second = replace(second, network_id="extpan:0011223344556677")
    store.save_processing_result(first, first_assessment)
    store.save_processing_result(second, second_assessment)
    with sqlite3.connect(store.path) as connection:
        connection.executemany(
            """INSERT INTO device_fact_samples
               (observation_id, device_id, field_key, source_file, value_json, value_class)
               VALUES (?, 'extaddr:8672766ae0578187', 'extAddress', 'legacy-unknown',
                       '"8672766ae0578187"', 'identity')""",
            ((first.observation_id,), (second.observation_id,)),
        )
    store.purge_device("extaddr:8672766ae0578187", network_id=first.network_id)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT observation_id FROM device_fact_samples"
        ).fetchall() == [(second.observation_id,)]


def test_purge_device_removes_relationship_but_preserves_other_endpoint(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    store.save_processing_result(*_result())
    with sqlite3.connect(store.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO devices VALUES (?, ?)",
            ("extaddr:0011223344556677", "0011223344556677"),
        )
        connection.execute(
            "INSERT INTO device_samples VALUES (?, ?, ?, ?, ?, ?)",
            ("observation-1", "extaddr:0011223344556677", "child", None, 0, "[]"),
        )
        connection.execute(
            "INSERT INTO relationships VALUES (?, ?, ?)",
            (
                "relationship-1",
                "extaddr:8672766ae0578187",
                "extaddr:0011223344556677",
            ),
        )
        connection.execute(
            "INSERT INTO relationship_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "observation-1", "relationship-1", "neighbor", 3, 3,
                None, None, None, None, None, "extaddr:8672766ae0578187", "[]", None,
            ),
        )

    result = store.purge_device("extaddr:8672766ae0578187")
    assert result.deleted["relationship_samples"] == 1
    assert result.deleted["relationships"] == 1
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT device_id FROM devices"
        ).fetchall() == [("extaddr:0011223344556677",)]


def test_purge_device_discovers_saved_context_and_finding_only_references(
    tmp_path,
) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    observation, assessment = _result()
    device_id = "extaddr:1111111111111111"
    other_device_id = "extaddr:2222222222222222"
    assessment = replace(
        assessment,
        reproduction_context={
            "expectedDeviceIds": [device_id],
            "priorCompleteAbsences": {device_id: 1},
            "rosterContext": {"records": [{"deviceId": device_id}]},
            "presenceInputs": {
                "observedDeviceIds": [device_id],
                "expectedDeviceIds": [],
            },
            "evaluationInputs": {
                "roster": {
                    "expectedDeviceIds": [],
                    "context": {"records": [{"deviceId": device_id}]},
                },
                "absenceHistory": {"priorCompleteAbsences": {}},
                "deviceIpv6Addresses": {
                    "complete": {},
                    "observed": {device_id: ["fe80::1"]},
                },
                "duplicateRelationshipIds": [
                    f"link:{device_id}->{other_device_id}"
                ],
            },
        },
        findings=(
            Finding(
                finding_id="finding-device-reference",
                rule_id="device.missing",
                status=HealthStatus.POOR,
                scope=FindingScope.DEVICE,
                rank=FindingRank.POOR,
                title="Device missing",
                summary="Device evidence",
                why_it_matters="Device evidence",
                device_ids=(device_id,),
                relationship_ids=(),
                evidence={},
                confidence=Confidence.HIGH,
                action="Inspect",
                verify="Recheck",
                action_key="inspect",
                verification_key="recheck",
                source_files=(),
            ),
        ),
    )
    store.save_processing_result(observation, assessment)

    result = store.purge_device(device_id)

    assert result.deleted["assessments"] == 1
    assert result.deleted["findings"] == 1
    assert result.deleted["health_assessment_preferences"] == 1
    assert result.deleted["health_assessment_upgrades"] == 0
    assert store.assessment_record(assessment_id=assessment.assessment_id) is None


def test_purge_rolls_back_completely_on_failure(tmp_path, monkeypatch) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    store.save_processing_result(*_result())

    def fail(_connection):
        raise RuntimeError("injected purge failure")

    monkeypatch.setattr(store, "_delete_orphans", fail)
    with pytest.raises(RuntimeError, match="injected purge failure"):
        store.purge_all()
    assert store.store_capabilities()["observationCount"] == 1
    assert store.store_capabilities()["assessmentCount"] == 1


def test_comparison_pair_is_atomic_idempotent_and_late_arrival_does_not_repoint(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    before, after = _result("1"), _result("3")
    store.save_processing_result(*before)
    store.save_processing_result(replace(after[0], completeness=Completeness.DEGRADED), after[1])
    interval, items, created = store.compare_assessments("assessment-1", "assessment-3", dry_run=True)
    assert not created and len(items) == 2
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] == 0
    assert store.compare_assessments("assessment-1", "assessment-3")[2] is True
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] == 1
    assert store.compare_assessments("assessment-1", "assessment-3")[2] is False
    store.save_processing_result(*_result("2"))
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT assessment_id FROM current_assessments").fetchone()[0] == "assessment-3"
        assert connection.execute(
            "SELECT before_assessment_id, after_assessment_id FROM comparisons ORDER BY after_observed_at"
        ).fetchall() == [("assessment-1", "assessment-2"), ("assessment-1", "assessment-3")]
    assert interval.comparison_id == store.compare_assessments("assessment-1", "assessment-3", dry_run=True)[0].comparison_id


def test_comparison_revision_reads_reject_cross_observation_preference(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    before = _result("1")
    after = _result("2")
    store.save_processing_result(*before)
    store.save_processing_result(*after)
    with closing(store._connect()) as connection:
        comparison_id = connection.execute(
            "SELECT comparison_id FROM comparisons"
        ).fetchone()["comparison_id"]
        connection.execute(
            """UPDATE health_assessment_preferences
               SET assessment_id=?, selection_basis_assessment_id=?
               WHERE observation_id=?""",
            (
                after[1].assessment_id,
                after[1].assessment_id,
                before[0].observation_id,
            ),
        )
        connection.commit()

    with pytest.raises(sqlite3.DatabaseError, match="crosses observations"):
        store.comparison_rows(
            network_id=before[0].network_id,
            dataset_id=before[0].dataset_id,
            limit=10,
            offset=0,
        )
    with pytest.raises(sqlite3.DatabaseError, match="crosses observations"):
        store.comparison_row(comparison_id, limit=10, offset=0)

    with closing(store._connect()) as connection:
        connection.execute(
            "DELETE FROM comparisons WHERE comparison_id=?", (comparison_id,)
        )
        connection.commit()
    with pytest.raises(sqlite3.DatabaseError, match="crosses observations"):
        store.compare_endpoint_pair(
            network_id=before[0].network_id,
            dataset_id=before[0].dataset_id,
            before_assessment_id=before[1].assessment_id,
            after_assessment_id=after[1].assessment_id,
            limit=10,
            offset=0,
            scope="all",
            result="all",
        )


def test_auto_comparison_suppresses_equivalent_observation_instants(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    first, first_assessment = _result("1")
    second, second_assessment = _result("2")
    first = replace(
        first, observed_at="2026-09-01T00:00:01Z", ingested_at="2026-09-01T00:00:01Z",
    )
    first_assessment = replace(first_assessment, assessed_at="2026-09-01T00:00:01Z")
    second = replace(
        second, observed_at="2026-09-01T02:00:01+02:00",
        ingested_at="2026-09-01T02:00:01+02:00",
    )
    second_assessment = replace(second_assessment, assessed_at="2026-09-01T02:00:01+02:00")
    store.save_processing_result(first, first_assessment)
    store.save_processing_result(second, second_assessment)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] == 0


def test_auto_comparison_persists_immutable_partition_and_rloc_changes(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    filename = "td-otbr-cli-networkdiag-fetch-all.json"
    for suffix, partition, rloc in (("1", 10, "0x1234"), ("2", 20, "0x5678")):
        observation, assessment = _result(suffix)
        observation = replace(observation, sources=(SourceEvidence(
            filename, f"digest-{suffix}", "final", "valid", observation.observed_at),))
        assessment = replace(assessment, sample_contract_version="comparison-v1",
                     health_policy_digest="policy-digest")
        facts = (RosterFact(observation.devices[0].device_id, "leaderData.partitionId",
                            json.dumps(partition), "transient", filename, 3, "high"),
                 RosterFact(observation.devices[0].device_id, "rloc16",
                            json.dumps(rloc), "transient", filename, 3, "high"))
        store.save_processing_result(observation, assessment, roster_facts=facts)
    with sqlite3.connect(store.path) as connection:
        rows = connection.execute(
            "SELECT metric, before_json, after_json, change FROM comparison_items "
            "WHERE metric IN ('partition', 'rloc16') ORDER BY metric"
        ).fetchall()
    assert [(metric, json.loads(before), json.loads(after), change) for metric, before, after, change in rows] == [
        ("partition", 10, 20, "changed"), ("rloc16", "0x1234", "0x5678", "changed")]


def test_auto_comparison_persists_unique_complete_interval_candidates_and_retries_idempotently(
    tmp_path, monkeypatch,
) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)

    def endpoint(suffix: str, timestamp: str):
        observation, assessment = _result(suffix)
        return (
            replace(observation, observed_at=timestamp, ingested_at=timestamp),
            replace(assessment, assessed_at=timestamp),
        )

    history = [
        ("1", "2026-01-01T00:00:00Z"),
        ("2", "2026-01-24T00:00:00Z"),
        ("3", "2026-01-28T00:00:00Z"),
        ("4", "2026-01-29T00:00:00Z"),
    ]
    for suffix, timestamp in history:
        store.save_processing_result(*endpoint(suffix, timestamp))
    partial, partial_assessment = endpoint("5", "2026-01-30T00:00:00Z")
    store.save_processing_result(
        replace(partial, completeness=Completeness.PARTIAL), partial_assessment,
    )
    after = endpoint("6", "2026-01-31T00:00:00Z")
    store.save_processing_result(*after)

    with sqlite3.connect(store.path) as connection:
        rows = connection.execute(
            "SELECT before_assessment_id, comparison_id FROM comparisons "
            "WHERE after_assessment_id=?",
            (after[1].assessment_id,),
        ).fetchall()
    expected_before = {
        "assessment-1", "assessment-2", "assessment-3", "assessment-4",
    }
    assert {before_id for before_id, _ in rows} == expected_before
    assert len(rows) == len(COMPARISON_INTERVALS) == 4
    assert len({comparison_id for _, comparison_id in rows}) == 4

    derived = []
    original_derive = store._derive_pair

    def count_derivations(*args):
        derived.append(args[1][1].assessment_id)
        return original_derive(*args)

    monkeypatch.setattr(store, "_derive_pair", count_derivations)
    store.save_processing_result(*after)
    assert derived == []


def test_auto_comparison_retry_adds_candidates_from_late_arriving_history(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)

    def endpoint(suffix: str, timestamp: str):
        observation, assessment = _result(suffix)
        return (
            replace(observation, observed_at=timestamp, ingested_at=timestamp),
            replace(assessment, assessed_at=timestamp),
        )

    after = endpoint("6", "2026-01-31T00:00:00Z")
    store.save_processing_result(*after)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM comparisons WHERE after_assessment_id=?",
            (after[1].assessment_id,),
        ).fetchone()[0] == 0

    for suffix, timestamp in (
        ("1", "2026-01-01T00:00:00Z"),
        ("2", "2026-01-24T00:00:00Z"),
        ("3", "2026-01-28T00:00:00Z"),
        ("4", "2026-01-29T00:00:00Z"),
    ):
        store.save_processing_result(*endpoint(suffix, timestamp))
    partial, partial_assessment = endpoint("5", "2026-01-30T00:00:00Z")
    store.save_processing_result(
        replace(partial, completeness=Completeness.PARTIAL), partial_assessment,
    )
    with sqlite3.connect(store.path) as connection:
        earlier_pairs = connection.execute(
            "SELECT comparison_id FROM comparisons ORDER BY comparison_id"
        ).fetchall()
    store.save_processing_result(*after)
    with sqlite3.connect(store.path) as connection:
        final_pairs = connection.execute(
            "SELECT before_assessment_id, comparison_id FROM comparisons "
            "WHERE after_assessment_id=?",
            (after[1].assessment_id,),
        ).fetchall()
        pairs_after_retry = connection.execute(
            "SELECT comparison_id FROM comparisons WHERE after_assessment_id<>? "
            "ORDER BY comparison_id",
            (after[1].assessment_id,),
        ).fetchall()
    assert {before_id for before_id, _ in final_pairs} == {
        "assessment-1", "assessment-2", "assessment-3", "assessment-4",
    }
    assert pairs_after_retry == earlier_pairs


def test_pruned_comparison_is_read_only_and_device_purge_removes_it(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME, max_observations=2)
    for suffix in ("1", "2", "3"):
        store.save_processing_result(*_result(suffix))
    service = TDHealthReadService(tmp_path)
    listing = service.comparisons(network_id="extpan:78b9775b001c1cbe",
                                  dataset_id="otbr_cli_networkdiag_fetch_all", limit=1, offset=1)
    assert listing["total"] == 2 and len(listing["items"]) == 1
    detail = service.comparison(comparison_id=listing["items"][0]["comparisonId"], limit=25, offset=0)
    assert detail["baselineState"] == "pruned"
    assert detail["reasons"][0] == "baseline-pruned" or "baseline-pruned" in detail["reasons"]
    assert not detail["comparable"] and detail["itemCount"] == len(detail["items"])
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] == 2
    dry = store.purge_device("extaddr:8672766ae0578187", dry_run=True)
    applied = store.purge_device("extaddr:8672766ae0578187")
    assert dry.deleted == applied.deleted
    assert applied.deleted["comparisons"] == 2
    assert service.comparison(comparison_id=detail["comparisonId"], limit=25, offset=0) is None


def test_real_v3_migration_backfills_only_lossless_device_facts(tmp_path) -> None:
    path = tmp_path / HOBAT_DATABASE_FILENAME
    with sqlite3.connect(path) as connection:
        connection.executescript(_SCHEMA)
        connection.execute("INSERT INTO schema_migrations VALUES (3, CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO devices VALUES (?, ?)", ("extaddr:8672766ae0578187", "8672766ae0578187"))
        connection.execute(
            """INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("observation-old", "otbr-cli", "otbr_cli_networkdiag_fetch_all",
             "extpan:78b9775b001c1cbe", None, "2026-09-01T00:00:00+00:00",
             "2026-09-01T00:00:00+00:00", "complete", "digest"),
        )
        connection.execute("INSERT INTO device_samples VALUES (?, ?, ?, ?, ?, ?)",
                           ("observation-old", "extaddr:8672766ae0578187", "router", "attached", 0, "[]"))
    SQLiteHealthStore(path)
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT field_key, value_json, source_file, source_observed_at, roster_policy_digest FROM device_fact_samples ORDER BY field_key"
        ).fetchall()
        assert rows == [
            ("extAddress", '"8672766ae0578187"', "legacy-unknown", None, None),
            ("role", '"router"', "legacy-unknown", None, None),
            ("state", '"attached"', "legacy-unknown", None, None),
        ]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone() == (
            SCHEMA_VERSION,
        )


def test_v3_upgrade_reopen_keeps_comparison_and_roster_provenance(tmp_path) -> None:
    path = tmp_path / HOBAT_DATABASE_FILENAME
    with sqlite3.connect(path) as connection:
        connection.executescript(_SCHEMA)
        connection.execute("INSERT INTO schema_migrations VALUES (3, CURRENT_TIMESTAMP)")
    store = SQLiteHealthStore(path)
    filename = "td-otbr-cli-networkdiag-fetch-all.json"
    for suffix in ("1", "2"):
        observation, assessment = _result(suffix)
        observation = replace(observation, sources=(SourceEvidence(
            filename, f"digest-{suffix}", "final", "valid", observation.observed_at,
        ),))
        fact = RosterFact(observation.devices[0].device_id, "role", json.dumps("router"),
                          "transient", filename, 3, "high")
        store.save_processing_result(observation, assessment, roster_facts=(fact,))

    SQLiteHealthStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [
            (version,) for version in range(2, SCHEMA_VERSION + 1)
        ]
        assert connection.execute("SELECT before_assessment_id, after_assessment_id FROM comparisons").fetchall() == [
            ("assessment-1", "assessment-2")]
        assert connection.execute(
            "SELECT observation_id, source_observed_at FROM device_fact_samples WHERE field_key='role' ORDER BY observation_id"
        ).fetchall() == [
            ("observation-1", "2026-09-01T00:00:01+00:00"),
            ("observation-2", "2026-09-01T00:00:02+00:00"),
        ]
        assert connection.execute("SELECT observation_id FROM device_last_known WHERE field_key='role'").fetchone() == (
            "observation-2",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_comparison_failure_rolls_back_observation_and_current_pointer(tmp_path, monkeypatch) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    store.save_processing_result(*_result("1"))

    def fail(*_args):
        raise RuntimeError("comparison failure")

    monkeypatch.setattr(store, "_store_comparison", fail)
    with pytest.raises(RuntimeError, match="comparison failure"):
        store.save_processing_result(*_result("2"))
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone() == (1,)
        assert connection.execute("SELECT assessment_id FROM current_assessments").fetchone() == ("assessment-1",)
        assert connection.execute("SELECT COUNT(*) FROM comparisons").fetchone() == (0,)


def test_schema_five_migration_adds_roster_lifecycle_columns_to_v4_rows(tmp_path) -> None:
    path = tmp_path / "health.db"
    network_id = "extpan:78b9775b001c1cbe"
    device_id = "extaddr:8672766ae0578187"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
            INSERT INTO schema_migrations VALUES (4, CURRENT_TIMESTAMP);
            CREATE TABLE expected_devices(
                network_id TEXT NOT NULL, device_id TEXT NOT NULL, label TEXT,
                roster_state TEXT NOT NULL DEFAULT 'expected',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(network_id, device_id)
            );
            INSERT INTO expected_devices(network_id, device_id, label, roster_state)
            VALUES ('extpan:78b9775b001c1cbe', 'extaddr:8672766ae0578187', 'Router', 'expected');
        """)

    SQLiteHealthStore(path)
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(expected_devices)")}
        assert {"revision", "reason", "expected_since", "change_source"} <= columns
        assert connection.execute(
            "SELECT label, roster_state, revision, expected_since, change_source "
            "FROM expected_devices WHERE network_id=? AND device_id=?",
            (network_id, device_id),
        ).fetchone() == ("Router", "expected", 0, None, "legacy")
        assert connection.execute(
            "SELECT revision FROM network_roster_revisions WHERE network_id=?",
            (network_id,),
        ).fetchone() == (0,)


def test_roster_cli_writes_are_audited_revisioned_and_label_only_is_nonreactivating(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    network_id = "extpan:78b9775b001c1cbe"
    device_id = "extaddr:8672766ae0578187"

    store.upsert_expected_device(network_id, device_id, "Desk", "intentionally-offline")
    store.upsert_expected_device(network_id, device_id, "Office")
    row = store.expected_device_records(network_id)[0]
    assert row["roster_state"] == "intentionally-offline"
    assert row["label"] == "Office"
    assert row["expected_since"] is None
    assert row["revision"] == 2

    store.upsert_expected_device(network_id, device_id, None)
    assert store.expected_device_records(network_id)[0]["revision"] == 2
    store.upsert_expected_device(network_id, device_id, None, "expected")
    reactivated = store.expected_device_records(network_id)[0]
    assert reactivated["roster_state"] == "expected"
    assert reactivated["expected_since"] is not None
    assert reactivated["revision"] == 3

    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT revision FROM network_roster_revisions WHERE network_id=?",
            (network_id,),
        ).fetchone() == (3,)
        events = connection.execute(
            """SELECT action, from_state, to_state, previous_label, new_label,
                      device_revision, network_revision
               FROM roster_lifecycle_events ORDER BY network_revision"""
        ).fetchall()
        assert events == [
            ("enroll", None, "intentionally-offline", None, "Desk", 1, 1),
            ("set-label", "intentionally-offline", "intentionally-offline", "Desk", "Office", 2, 2),
            ("set-state", "intentionally-offline", "expected", "Office", "Office", 3, 3),
        ]


def test_roster_import_is_additive_idempotent_and_purge_removes_its_audit(tmp_path) -> None:
    from td_health_roster_mutation import add_expected_devices_from_label_map

    store = SQLiteHealthStore(tmp_path / "health.db")
    network_id = "extpan:78b9775b001c1cbe"
    existing_id = "extaddr:8672766ae0578187"
    imported_id = "extaddr:1111111111111111"
    store.upsert_expected_device(network_id, existing_id, "Operator label", "retired")

    first = add_expected_devices_from_label_map(
        store,
        network_id=network_id,
        devices=((existing_id, "Static label"), (imported_id, "New device")),
    )
    assert (first.imported, first.already_present, first.skipped) == (1, 1, 0)
    rows = {row["device_id"]: row for row in store.expected_device_records(network_id)}
    assert rows[existing_id]["label"] == "Operator label"
    assert rows[existing_id]["roster_state"] == "retired"
    assert rows[imported_id]["roster_state"] == "expected"

    repeated = add_expected_devices_from_label_map(
        store,
        network_id=network_id,
        devices=((existing_id, "Changed label"), (imported_id, "Changed label")),
    )
    assert (repeated.imported, repeated.already_present) == (0, 2)
    assert rows[existing_id]["revision"] == 1
    assert rows[imported_id]["revision"] == 1

    result = store.purge_device(existing_id, network_id=network_id)
    assert result.deleted["expected_devices"] == 1
    assert result.deleted["roster_lifecycle_events"] == 1
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM roster_lifecycle_events").fetchone()[0] == 1


def test_idempotent_retry_recreates_missing_comparison(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    store.save_processing_result(*_result("1"))
    later = _result("2")
    store.save_processing_result(*later)
    with sqlite3.connect(store.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        comparison_id = connection.execute("SELECT comparison_id FROM comparisons").fetchone()[0]
        connection.execute("DELETE FROM comparisons")
    repeated = store.save_processing_result(*later)
    assert not repeated.observation_created and not repeated.assessment_created
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT comparison_id FROM comparisons").fetchone() == (comparison_id,)


@pytest.mark.parametrize(
    ("reserved", "expected"),
    [
        (True, (1, 0)),
        (False, (0, 1)),
    ],
)
def test_auto_comparison_filters_unavailable_endpoints_before_baseline_selection(
    tmp_path, reserved, expected
) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    first = _result("1")
    unsupported = _result("2")
    latest = _result("3")
    for endpoint in (first, unsupported, latest):
        store.save_processing_result(*endpoint)

    target_pair = comparison_id(
        first[1].assessment_id,
        latest[1].assessment_id,
        ComparisonPolicy(),
    )
    with closing(store._connect()) as connection, connection:
        connection.execute("DELETE FROM comparisons")
        result = store._auto_compare(
            connection,
            *latest,
            allowed_assessment_ids=frozenset(
                {first[1].assessment_id, latest[1].assessment_id}
            ),
            reserved_comparison_ids=(
                frozenset({target_pair}) if reserved else frozenset()
            ),
            enforce_retention=False,
        )
        assert result == expected
        stored = connection.execute(
            "SELECT before_assessment_id, after_assessment_id FROM comparisons"
        ).fetchall()
        if reserved:
            assert [(row[0], row[1]) for row in stored] == [
                (first[1].assessment_id, latest[1].assessment_id)
            ]
        else:
            assert stored == []


def test_route64_contract_cannot_upgrade_immutable_observation_samples(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    observation, assessment = _result()
    store.save_processing_result(observation, assessment)
    updated = replace(assessment, assessment_id="assessment-route64",
                      sample_contract_version="comparison-v1-route64")
    with pytest.raises(ValueError, match="sample contract"):
        store.save_processing_result(observation, updated)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT assessment_id FROM assessments").fetchall() == [(assessment.assessment_id,)]
    with closing(store._connect()) as connection, connection:
        connection.execute(
            "DELETE FROM assessments WHERE assessment_id=?",
            (assessment.assessment_id,),
        )
    assert store.save_processing_result(observation, updated).assessment_created


@pytest.mark.parametrize(
    ("metric", "value"),
    [
        (metric, value)
        for metric in ("totalMacErrorRatio", "totalMacDiscardRatio")
        for value in (0.0, 1.0, 1.5, 7.2)
    ],
)
def test_retained_mac_ratios_round_trip_without_rescaling(tmp_path, metric, value) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    observation, assessment = _result_with_metric(metric, value, "ratio", 100.0)
    store.save_processing_result(observation, assessment)

    retained = _reconstruct_observation(store, assessment.assessment_id)

    sample = next(item for item in retained.metrics if item.metric == metric)
    assert sample.value == value
    assert sample.denominator == 100.0


@pytest.mark.parametrize(
    ("metric", "value", "denominator"),
    [
        ("totalMacErrorRatio", -0.1, 100.0),
        ("totalMacDiscardRatio", -0.1, 100.0),
        ("totalMacErrorRatio", float("inf"), 100.0),
        ("totalMacDiscardRatio", float("inf"), 100.0),
        ("totalMacErrorRatio", 1.5, None),
        ("totalMacDiscardRatio", 1.5, None),
        ("totalMacErrorRatio", 1.5, 0.0),
        ("totalMacDiscardRatio", 1.5, 0.0),
        ("totalMacErrorRatio", 1.5, -1.0),
        ("totalMacDiscardRatio", 1.5, -1.0),
        ("totalMacErrorRatio", 1.5, float("inf")),
        ("totalMacDiscardRatio", 1.5, float("inf")),
    ],
)
def test_retained_mac_ratios_reject_invalid_values_and_denominators(
    tmp_path, metric, value, denominator
) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    observation, assessment = _result_with_metric(metric, value, "ratio", denominator)
    store.save_processing_result(observation, assessment)

    with pytest.raises(sqlite3.DatabaseError):
        _reconstruct_observation(store, assessment.assessment_id)


@pytest.mark.parametrize(
    ("metric", "unit", "value", "denominator", "valid"),
    [
        ("routerRolePercent", "percent", 100.0, None, True),
        ("routerRolePercent", "percent", 100.1, None, False),
        ("route64Coverage", "flag", 1.0, None, True),
        ("route64Coverage", "flag", 2.0, None, False),
        ("parentChanges", "count", 0.0, None, True),
        ("parentChanges", "count", -1.0, None, False),
    ],
)
def test_retained_non_mac_metric_bounds_remain_unchanged(
    tmp_path, metric, unit, value, denominator, valid
) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    observation, assessment = _result_with_metric(metric, value, unit, denominator)
    store.save_processing_result(observation, assessment)

    if valid:
        retained = _reconstruct_observation(store, assessment.assessment_id)
        assert retained.metrics[0].value == value
    else:
        with pytest.raises(sqlite3.DatabaseError):
            _reconstruct_observation(store, assessment.assessment_id)


def test_mac_ratio_comparison_read_preserves_values_units_and_delta(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    for suffix, value in (("1", 1.5), ("2", 7.2)):
        observation, assessment = _result_with_metric(
            "totalMacDiscardRatio", value, "ratio", 100.0, suffix=suffix
        )
        store.save_processing_result(
            observation,
            replace(
                assessment,
                sample_contract_version="comparison-v1",
                health_policy_digest="health-policy",
            ),
        )
    service = TDHealthReadService(tmp_path)
    listing = service.comparisons(
        network_id="extpan:78b9775b001c1cbe",
        dataset_id="otbr_cli_networkdiag_fetch_all",
        limit=25,
        offset=0,
    )

    assert listing["total"] == 1
    comparison = service.comparison(
        comparison_id=listing["items"][0]["comparisonId"],
        limit=25,
        offset=0,
    )
    item = next(
        item for item in comparison["items"]
        if item["metric"] == "totalMacDiscardRatio"
    )
    assert item["unit"] == "ratio"
    assert item["beforeValue"] == 1.5
    assert item["afterValue"] == 7.2
    assert item["delta"] == 570.0


def test_pruned_numeric_delta_is_suppressed_without_mutating_persisted_item(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME, max_observations=2)
    filename = "td-otbr-cli-networkdiag-fetch-all.json"

    def endpoint(suffix, value):
        observation, assessment = _result(suffix)
        observation = replace(
            observation,
            sources=(SourceEvidence(filename, suffix, "final", "valid", observation.observed_at),),
            metrics=(MetricSample(observation.devices[0].device_id, "routerRolePercent",
                                  value, "percent", None, filename),),
        )
        return observation, replace(assessment, sample_contract_version="comparison-v1",
                                    health_policy_digest="health-policy")

    for suffix, value in (("1", 50), ("2", 60)):
        store.save_processing_result(*endpoint(suffix, value))
    service = TDHealthReadService(tmp_path)
    listing = service.comparisons(network_id="extpan:78b9775b001c1cbe",
                                  dataset_id="otbr_cli_networkdiag_fetch_all", limit=25, offset=0)
    comparison_id = listing["items"][0]["comparisonId"]
    first = service.comparison(comparison_id=comparison_id, limit=25, offset=0)
    numeric = next(item for item in first["items"] if item["metric"] == "routerRolePercent")
    assert numeric["delta"] == 10 and numeric["change"] == "changed"
    assert first["filteredItemCount"] == first["itemCount"] == len(first["items"])
    store.save_processing_result(*endpoint("3", 65))
    effective = service.comparison(comparison_id=comparison_id, limit=25, offset=0)
    numeric = next(item for item in effective["items"] if item["metric"] == "routerRolePercent")
    assert effective["baselineState"] == "pruned"
    assert not numeric["comparable"] and numeric["change"] == "unknown"
    assert effective["filteredItemCount"] == effective["itemCount"]
    assert service.comparison(
        comparison_id=comparison_id, limit=25, offset=0, result="changed"
    )["filteredItemCount"] == 0
    assert service.comparison(
        comparison_id=comparison_id, limit=25, offset=0, result="unknown"
    )["filteredItemCount"] == effective["itemCount"]
    assert numeric["delta"] is None and numeric["direction"] is None
    assert "baseline-pruned" in numeric["reasons"]
    with sqlite3.connect(store.path) as connection:
        stored = connection.execute(
            "SELECT delta_json FROM comparison_items WHERE comparison_id=? AND metric='routerRolePercent'",
            (comparison_id,),
        ).fetchone()
        assert json.loads(stored[0]) == 10


def test_comparison_filters_count_and_page_the_effective_population(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    filename = "td-otbr-cli-networkdiag-fetch-all.json"

    def endpoint(suffix, value):
        observation, assessment = _result(suffix)
        observation = replace(
            observation,
            sources=(SourceEvidence(filename, suffix, "final", "valid", observation.observed_at),),
            metrics=(MetricSample(observation.devices[0].device_id, "routerRolePercent",
                                  value, "percent", None, filename),),
        )
        return observation, replace(assessment, sample_contract_version="comparison-v1",
                                    health_policy_digest="health-policy")

    store.save_processing_result(*endpoint("1", 50))
    store.save_processing_result(*endpoint("2", 60))
    service = TDHealthReadService(tmp_path)
    listing = service.comparisons(
        network_id="extpan:78b9775b001c1cbe",
        dataset_id="otbr_cli_networkdiag_fetch_all", limit=25, offset=0,
    )
    comparison_id = listing["items"][0]["comparisonId"]

    with sqlite3.connect(store.path) as connection:
        connection.row_factory = sqlite3.Row
        original = dict(connection.execute(
            "SELECT * FROM comparison_items WHERE comparison_id=?", (comparison_id,)
        ).fetchone())
        connection.execute("DELETE FROM comparison_items WHERE comparison_id=?", (comparison_id,))
        for index in range(30):
            item = {
                **original,
                "item_id": f"item:filter-test-{index:02d}",
                "scope": ("device", "network", "relationship")[index % 3],
                "subject_id": f"extaddr:{index:016x}",
                "change": "changed" if index < 12 or index >= 19 else "unchanged",
                "comparable": int(index < 19),
                "direction": "improved" if index % 2 else "worsened",
            }
            columns = tuple(item)
            connection.execute(
                f"INSERT INTO comparison_items ({','.join(columns)}) "
                f"VALUES ({','.join('?' for _ in columns)})",
                tuple(item[column] for column in columns),
            )
        connection.execute(
            "UPDATE comparisons SET item_count=30 WHERE comparison_id=?", (comparison_id,)
        )

    all_rows = service.comparison(comparison_id=comparison_id, limit=100, offset=0)
    assert all_rows["itemCount"] == all_rows["filteredItemCount"] == 30
    assert len(all_rows["items"]) == 30

    changed_first = service.comparison(
        comparison_id=comparison_id, limit=5, offset=0, result="changed",
    )
    changed_second = service.comparison(
        comparison_id=comparison_id, limit=5, offset=5, result="changed",
    )
    changed_all = service.comparison(
        comparison_id=comparison_id, limit=100, offset=0, result="changed",
    )
    assert changed_first["itemCount"] == 30
    assert changed_first["filteredItemCount"] == 12
    assert len(changed_first["items"]) == len(changed_second["items"]) == 5
    assert [item["itemId"] for item in changed_first["items"] + changed_second["items"]] == [
        item["itemId"] for item in changed_all["items"][:10]
    ]
    assert all(item["change"] == "changed" for item in changed_all["items"])

    unchanged = service.comparison(
        comparison_id=comparison_id, limit=100, offset=0, result="unchanged",
    )
    unknown = service.comparison(
        comparison_id=comparison_id, limit=100, offset=0, result="unknown",
    )
    scoped = service.comparison(
        comparison_id=comparison_id, limit=100, offset=0,
        scope="device", result="changed",
    )
    assert unchanged["filteredItemCount"] == 7
    assert all(item["change"] == "unchanged" for item in unchanged["items"])
    assert unknown["filteredItemCount"] == 11
    assert all(not item["comparable"] and item["change"] == "unknown" for item in unknown["items"])
    assert scoped["filteredItemCount"] == 4
    assert all(item["scope"] == "device" and item["change"] == "changed"
               for item in scoped["items"])