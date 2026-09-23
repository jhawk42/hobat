"""Focused transactional tests for the Crawl SQLite health store."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from td_health_observation_model import (
    Assessment,
    Completeness,
    Confidence,
    DeviceSample,
    HealthStatus,
    MetricSample,
    Observation,
    RelationshipSample,
    SourceEvidence,
)
from td_health_observation_store import HealthStoreFutureSchemaError
from td_health_read import TDHealthReadService
from td_health_roster import RosterFact
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_sqlite import SCHEMA_VERSION, SQLiteHealthStore, _SCHEMA


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
            ("a", "o", "p", "d", "strong", "high", "{}", "now"),
        )

    SQLiteHealthStore(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT evaluator_version, profile_id FROM assessments"
        ).fetchone() == ("legacy-unknown", "legacy-unknown")


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

    store.save_processing_result(expired_observation, expired_assessment)
    store.upsert_expected_device(
        expired_observation.network_id, expired_device.device_id, "Retained roster"
    )
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
    for suffix in ("1", "2", "3"):
        store.save_processing_result(*_result(suffix))
    store.upsert_expected_device(
        "extpan:78b9775b001c1cbe", "extaddr:8672766ae0578187", "Router"
    )
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
    store.save_processing_result(*_result())
    store.upsert_expected_device(
        "extpan:78b9775b001c1cbe", "extaddr:8672766ae0578187", "Router"
    )
    with sqlite3.connect(store.path) as connection:
        connection.execute("CREATE TABLE other_hobat_data(value TEXT)")
        connection.execute("INSERT INTO other_hobat_data VALUES ('keep')")

    preview = store.purge_all(dry_run=True)
    assert preview.deleted["observations"] == 1
    assert store.store_capabilities()["observationCount"] == 1

    result = store.purge_all()
    assert result.deleted["observations"] == 1
    assert result.deleted["expected_devices"] == 1
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT value FROM other_hobat_data").fetchone() == ("keep",)
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] > 0
    repeated = store.purge_all()
    assert all(count == 0 for count in repeated.deleted.values())


def test_purge_device_removes_identity_and_invalidates_affected_assessment(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "health.db")
    store.save_processing_result(*_result())
    store.upsert_expected_device(
        "extpan:78b9775b001c1cbe", "extaddr:8672766ae0578187", "Router"
    )

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
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone() == (4,)


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
        assert connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(2,), (3,), (4,)]
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
    store.save_processing_result(*endpoint("3", 65))
    effective = service.comparison(comparison_id=comparison_id, limit=25, offset=0)
    numeric = next(item for item in effective["items"] if item["metric"] == "routerRolePercent")
    assert effective["baselineState"] == "pruned"
    assert not numeric["comparable"] and numeric["change"] == "unknown"
    assert numeric["delta"] is None and numeric["direction"] is None
    assert "baseline-pruned" in numeric["reasons"]
    with sqlite3.connect(store.path) as connection:
        stored = connection.execute(
            "SELECT delta_json FROM comparison_items WHERE comparison_id=? AND metric='routerRolePercent'",
            (comparison_id,),
        ).fetchone()
        assert json.loads(stored[0]) == 10