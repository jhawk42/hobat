"""Focused health process-dataset CLI tests."""

from __future__ import annotations

import io
import json
import hashlib
import os
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import td_cli
import td_health_cli
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_read import TDHealthReadService
from td_health_sqlite import SQLiteHealthStore
from td_health_migration import (
    inventory_health_history,
    migrate_health_history,
)
from td_health_policy import load_health_policy
from td_health_processor import process_health
from test_td_health_sqlite import _result
from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME


def _seed(data_dir) -> None:
    (data_dir / "td-otbr-cli-thread-network-info.json").write_text(
        json.dumps({"extPanId": "78b9775b001c1cbe", "networkName": "test"}),
        encoding="utf-8",
    )
    (data_dir / "td-otbr-cli-networkdiag-fetch-all.json").write_text(
        json.dumps([{"extAddress": "8672766ae0578187", "role": "router"}]),
        encoding="utf-8",
    )


def test_dry_run_json_does_not_create_database(tmp_path) -> None:
    _seed(tmp_path)
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_health_cli.main(
            ["--datadir", str(tmp_path), "process-dataset", "--dataset", "otbr_cli_networkdiag_fetch_all", "--dry-run", "--json"]
        ) == 0
    document = json.loads(output.getvalue())
    assert document["networkId"] == "extpan:78b9775b001c1cbe"
    assert document["assessmentCreated"] is None
    assert not (tmp_path / HOBAT_DATABASE_FILENAME).exists()


def test_explicit_compare_is_cache_only_dry_run_and_idempotent(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    store.save_processing_result(*_result("1"))
    store.save_processing_result(*_result("2"))
    output = io.StringIO()
    args = ["--datadir", str(tmp_path), "compare", "--before-assessment", "assessment-1",
            "--after-assessment", "assessment-2", "--json"]
    with redirect_stdout(output):
        assert td_health_cli.main([*args, "--dry-run"]) == 0
    document = json.loads(output.getvalue())
    assert document["dryRun"] and not document["created"]
    assert document["comparisonId"].startswith("comparison:")
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_health_cli.main(args) == 0
    assert not json.loads(output.getvalue())["created"]


def test_top_level_compare_forwards_to_health_cli(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    store.save_processing_result(*_result("1"))
    store.save_processing_result(*_result("2"))
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_cli.main([
            "--datadir", str(tmp_path), "health", "compare",
            "--before-assessment", "assessment-1",
            "--after-assessment", "assessment-2", "--dry-run", "--json",
        ]) == 0
    assert json.loads(output.getvalue())["dryRun"]


def test_cached_cli_counter_change_without_reset_witness_stays_unknown(tmp_path) -> None:
    _seed(tmp_path)
    identity = tmp_path / "td-otbr-cli-thread-network-info.json"
    snapshot = tmp_path / "td-otbr-cli-networkdiag-fetch-all.json"
    first_time = datetime.now(timezone.utc) - timedelta(days=2)
    os.utime(identity, (first_time.timestamp(), first_time.timestamp()))
    assessment_ids = []
    for index, count in enumerate((0, 1, 0)):
        snapshot.write_text(json.dumps([{
            "extAddress": "8672766ae0578187", "role": "router",
            "mleCounters": {"newParentCount": count},
            "timeStatistics": {"trackedTime": 100 + index * 86400},
        }]), encoding="utf-8")
        observed_at = first_time + timedelta(days=index)
        os.utime(snapshot, (observed_at.timestamp(), observed_at.timestamp()))
        output = io.StringIO()
        with redirect_stdout(output):
            assert td_cli.main(["--datadir", str(tmp_path), "health", "process-dataset",
                                "--dataset", "otbr_cli_networkdiag_fetch_all", "--json"]) == 0
        assessment_ids.append(json.loads(output.getvalue())["assessmentId"])

    output = io.StringIO()
    with redirect_stdout(output):
        assert td_cli.main(["--datadir", str(tmp_path), "health", "compare",
                            "--before-assessment", assessment_ids[0],
                            "--after-assessment", assessment_ids[1], "--dry-run", "--json"]) == 0
    comparison_id = json.loads(output.getvalue())["comparisonId"]
    service = TDHealthReadService(tmp_path)
    detail = service.comparison(comparison_id=comparison_id, limit=100, offset=0)
    counter = next(item for item in detail["items"] if item["metric"] == "parentChanges")
    assert (counter["beforeValue"], counter["afterValue"]) == (0, 1)
    assert counter["beforeSourceObservedAt"] < counter["afterSourceObservedAt"]
    assert counter["resetState"] == "unknown" and counter["resetWitness"]["witness"] is None
    assert counter["reasons"] == ["reset-unknown"]
    assert counter["change"] == "unknown" and counter["delta"] is None
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_cli.main(["--datadir", str(tmp_path), "health", "compare",
                            "--before-assessment", assessment_ids[1],
                            "--after-assessment", assessment_ids[2], "--dry-run", "--json"]) == 0
    detail = service.comparison(comparison_id=json.loads(output.getvalue())["comparisonId"],
                                limit=100, offset=0)
    decreased = next(item for item in detail["items"] if item["metric"] == "parentChanges")
    assert (decreased["beforeValue"], decreased["afterValue"]) == (1, 0)
    assert decreased["resetState"] == "reset-detected"
    assert decreased["reasons"] == ["reset-detected"]
    assert decreased["change"] == "unknown" and decreased["delta"] is None


def test_dry_run_uses_existing_roster_history_without_mutating_store(tmp_path) -> None:
    _seed(tmp_path)
    database_path = tmp_path / HOBAT_DATABASE_FILENAME
    store = SQLiteHealthStore(database_path)
    store.upsert_expected_device(
        "extpan:78b9775b001c1cbe", "extaddr:1111111111111111", "Missing"
    )
    with closing(store._connect()) as connection:
        connection.execute(
            "UPDATE expected_devices SET expected_since=? WHERE device_id=?",
            ("2020-01-01T00:00:00+00:00", "extaddr:1111111111111111"),
        )
        connection.commit()
    assert td_health_cli.main([
        "--datadir", str(tmp_path), "process-dataset",
        "--dataset", "otbr_cli_networkdiag_fetch_all",
    ]) == 0
    snapshot = tmp_path / "td-otbr-cli-networkdiag-fetch-all.json"
    snapshot.write_text(snapshot.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()

    output = io.StringIO()
    with redirect_stdout(output):
        assert td_health_cli.main([
            "--datadir", str(tmp_path), "process-dataset",
            "--dataset", "otbr_cli_networkdiag_fetch_all", "--dry-run", "--json",
        ]) == 0

    document = json.loads(output.getvalue())
    assert any(
        finding["rule_id"] == "device.offline"
        for finding in document["findings"]
    )
    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == before


def test_migrate_history_cli_dry_run_is_read_only_json(tmp_path) -> None:
    _seed(tmp_path)
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    assert td_health_cli.main([
        "--datadir", str(tmp_path), "process-dataset",
        "--dataset", "otbr_cli_networkdiag_fetch_all",
    ]) == 0
    with closing(store._connect()) as connection:
        connection.execute(
            """UPDATE assessments
               SET evaluator_version='snapshot-v10', reproduction_context_json='{}'"""
        )
        connection.commit()
    database_path = tmp_path / HOBAT_DATABASE_FILENAME
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_health_cli.main([
            "--datadir", str(tmp_path), "migrate-history",
            "--dataset", "otbr_cli_networkdiag_fetch_all",
            "--dry-run", "--json",
        ]) == 0
    report = json.loads(output.getvalue())
    assert report["outcome"] == "dry-run-ready"
    assert report["totals"]["replayableWithGaps"] == 1
    assert report["items"][0]["unavailableDomains"]
    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == before


def test_migrate_history_creates_verified_backup_and_revision(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _seed(data_dir)
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    store = SQLiteHealthStore(database_path)
    assert td_health_cli.main([
        "--datadir", str(data_dir), "process-dataset",
        "--dataset", "otbr_cli_networkdiag_fetch_all",
    ]) == 0
    with closing(store._connect()) as connection:
        source = connection.execute(
            "SELECT assessment_id, observation_id FROM assessments"
        ).fetchone()
        connection.execute(
            """UPDATE assessments
               SET evaluator_version='snapshot-v10', reproduction_context_json='{}'
               WHERE assessment_id=?""",
            (source["assessment_id"],),
        )
        connection.commit()
    policy = load_health_policy()
    inventory = inventory_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        target_policy=policy,
        dataset_ids=("otbr_cli_networkdiag_fetch_all",),
    )
    backup_path = tmp_path / "backup"

    report = migrate_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        data_dir=data_dir,
        target_policy=policy,
        inventory=inventory,
        backup_output=backup_path,
    )

    assert report["outcome"] == "complete"
    assert report["totals"]["created"] == 1, report["cohorts"]
    assert report["totals"]["preferencesChanged"] == 1
    assert (backup_path / "hobat-backup-manifest.json").is_file()
    with closing(store._connect()) as connection:
        target = connection.execute(
            """SELECT p.assessment_id, p.selection_basis_assessment_id,
                      p.origin, u.source_assessment_id
               FROM health_assessment_preferences p
               JOIN health_assessment_upgrades u
                 ON u.target_assessment_id=p.assessment_id
               WHERE p.observation_id=?""",
            (source["observation_id"],),
        ).fetchone()
        assert target["origin"] == "migration"
        assert target["source_assessment_id"] == source["assessment_id"]
        assert target["selection_basis_assessment_id"] == source["assessment_id"]
        assert target["assessment_id"] != source["assessment_id"]


def test_migrate_history_missing_datadir_does_not_create_it(tmp_path) -> None:
    missing = tmp_path / "missing"
    assert td_health_cli.main([
        "--datadir", str(missing), "migrate-history",
        "--dataset", "all", "--dry-run",
    ]) == 4
    assert not missing.exists()


def test_invalid_member_aborts_entire_history_cohort(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _seed(data_dir)
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    store = SQLiteHealthStore(database_path)
    policy = load_health_policy()
    first = process_health(
        data_dir=data_dir,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=policy,
        store=store,
    )
    snapshot = data_dir / "td-otbr-cli-networkdiag-fetch-all.json"
    snapshot.write_text(
        json.dumps([{"extAddress": "8672766ae0578187", "role": "child"}]),
        encoding="utf-8",
    )
    second = process_health(
        data_dir=data_dir,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=policy,
        store=store,
    )
    with closing(store._connect()) as connection:
        connection.execute(
            """UPDATE assessments
               SET evaluator_version='snapshot-v10', reproduction_context_json='{}'
               WHERE assessment_id=?""",
            (first.assessment.assessment_id,),
        )
        connection.execute(
            """UPDATE assessments
               SET reproduction_context_json='null'
               WHERE assessment_id=?""",
            (second.assessment.assessment_id,),
        )
        connection.commit()
    inventory = inventory_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        target_policy=policy,
        dataset_ids=("otbr_cli_networkdiag_fetch_all",),
    )
    backup_path = tmp_path / "backup"

    report = migrate_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        data_dir=data_dir,
        target_policy=policy,
        inventory=inventory,
        backup_output=backup_path,
    )

    assert report["outcome"] == "failed"
    assert report["totals"]["failed"] == 1
    assert report["totals"]["created"] == 0
    with closing(store._connect()) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM health_assessment_upgrades"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM health_history_migrations"
        ).fetchone()[0] == 0
        preference = connection.execute(
            """SELECT assessment_id, origin
               FROM health_assessment_preferences WHERE observation_id=?""",
            (first.observation.observation_id,),
        ).fetchone()
        assert preference["assessment_id"] == first.assessment.assessment_id
        assert preference["origin"] == "native"


def test_migrate_history_policy_reversion_restores_native_preference(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _seed(data_dir)
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    store = SQLiteHealthStore(database_path)
    policy_one = load_health_policy()
    native = process_health(
        data_dir=data_dir,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=policy_one,
        store=store,
    )
    policy_one = load_health_policy()
    from dataclasses import replace

    policy_two = replace(policy_one, digest="test-policy-p2")
    backup_one = tmp_path / "backup-p2"
    inventory = inventory_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        target_policy=policy_two,
        dataset_ids=("otbr_cli_networkdiag_fetch_all",),
    )
    migrated = migrate_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        data_dir=data_dir,
        target_policy=policy_two,
        inventory=inventory,
        backup_output=backup_one,
    )
    assert migrated["totals"]["created"] == 1
    store.save_processing_result(native.observation, native.assessment)
    with closing(store._connect()) as connection:
        preference = connection.execute(
            """SELECT assessment_id, origin
               FROM health_assessment_preferences WHERE observation_id=?""",
            (native.observation.observation_id,),
        ).fetchone()
        assert preference["assessment_id"] != native.assessment.assessment_id
        assert preference["origin"] == "migration"

    inventory = inventory_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        target_policy=policy_one,
        dataset_ids=("otbr_cli_networkdiag_fetch_all",),
    )
    reverted = migrate_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        data_dir=data_dir,
        target_policy=policy_one,
        inventory=inventory,
        backup_output=tmp_path / "backup-p1",
    )

    assert reverted["totals"]["created"] == 0
    assert reverted["totals"]["preferencesChanged"] == 1
    with closing(store._connect()) as connection:
        preference = connection.execute(
            """SELECT assessment_id, selection_basis_assessment_id,
                      origin, migration_id
               FROM health_assessment_preferences WHERE observation_id=?""",
            (native.observation.observation_id,),
        ).fetchone()
        assert preference["assessment_id"] == native.assessment.assessment_id
        assert preference["selection_basis_assessment_id"] == native.assessment.assessment_id
        assert preference["origin"] == "native"
        assert preference["migration_id"] is None
        assert connection.execute(
            "SELECT COUNT(*) FROM assessments WHERE observation_id=?",
            (native.observation.observation_id,),
        ).fetchone()[0] == 2

    inventory = inventory_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        target_policy=policy_two,
        dataset_ids=("otbr_cli_networkdiag_fetch_all",),
    )
    migrate_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        data_dir=data_dir,
        target_policy=policy_two,
        inventory=inventory,
        backup_output=tmp_path / "backup-p2-again",
    )
    newer_native_id = f"assessment:{'f' * 24}"
    newer_assessed_at = (
        datetime.now(timezone.utc) + timedelta(seconds=10)
    ).isoformat()
    with closing(store._connect()) as connection, connection:
        connection.execute(
            """INSERT INTO assessments
               (assessment_id, observation_id, policy_version, policy_digest,
                evaluator_version, profile_id, status, confidence, coverage_json,
                assessed_at, sample_contract_version, health_policy_digest,
                roster_context_digest, network_roster_revision,
                presence_input_digest, reproduction_context_json)
               SELECT ?, observation_id, policy_version, policy_digest,
                      evaluator_version, profile_id, status, confidence,
                      coverage_json, ?, sample_contract_version,
                      health_policy_digest, roster_context_digest || '-newer',
                      network_roster_revision + 1, presence_input_digest,
                      reproduction_context_json
               FROM assessments WHERE assessment_id=?""",
            (
                newer_native_id,
                newer_assessed_at,
                native.assessment.assessment_id,
            ),
        )
        SQLiteHealthStore.consider_native_preference(
            connection, newer_native_id
        )
        preference = connection.execute(
            """SELECT assessment_id, selection_basis_assessment_id, origin
               FROM health_assessment_preferences WHERE observation_id=?""",
            (native.observation.observation_id,),
        ).fetchone()
        assert preference["assessment_id"] == newer_native_id
        assert preference["selection_basis_assessment_id"] == newer_native_id
        assert preference["origin"] == "native"


def test_history_upgrade_identity_is_independent_of_dataset_scope(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _seed(data_dir)
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    store = SQLiteHealthStore(database_path)
    native = process_health(
        data_dir=data_dir,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        store=store,
    )
    policy = load_health_policy()
    from dataclasses import replace

    policy = replace(policy, digest="test-policy-scope")
    first_inventory = inventory_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        target_policy=policy,
        dataset_ids=("otbr_cli_networkdiag_fetch_all",),
    )
    first = migrate_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        data_dir=data_dir,
        target_policy=policy,
        inventory=first_inventory,
        backup_output=tmp_path / "backup-single",
    )
    all_inventory = inventory_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        target_policy=policy,
    )
    all_result = migrate_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        data_dir=data_dir,
        target_policy=policy,
        inventory=all_inventory,
        backup_output=tmp_path / "backup-all",
    )

    assert first["totals"]["created"] == 1
    assert all_result["outcome"] == "already-current"
    assert all_result["totals"]["failed"] == 0
    with closing(store._connect()) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM assessments WHERE observation_id=?",
            (native.observation.observation_id,),
        ).fetchone()[0] == 2


def test_migration_prefers_upgraded_endpoints_and_stores_comparison(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _seed(data_dir)
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    store = SQLiteHealthStore(database_path)
    policy_one = load_health_policy()
    snapshot = data_dir / "td-otbr-cli-networkdiag-fetch-all.json"
    identity = data_dir / "td-otbr-cli-thread-network-info.json"
    first_time = datetime.now(timezone.utc) - timedelta(days=2)
    os.utime(snapshot, (first_time.timestamp(), first_time.timestamp()))
    os.utime(identity, (first_time.timestamp(), first_time.timestamp()))
    first = process_health(
        data_dir=data_dir,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=policy_one,
        store=store,
    )
    from dataclasses import replace

    policy_two = replace(policy_one, digest="test-policy-comparison")
    snapshot.write_text(
        json.dumps([{
            "extAddress": "8672766ae0578187",
            "role": "router",
            "mleCounters": {"newParentCount": 1},
        }]),
        encoding="utf-8",
    )
    second_time = first_time + timedelta(days=1)
    os.utime(snapshot, (second_time.timestamp(), second_time.timestamp()))
    os.utime(identity, (second_time.timestamp(), second_time.timestamp()))
    second = process_health(
        data_dir=data_dir,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=policy_two,
        store=store,
    )
    with closing(store._connect()) as connection, connection:
        connection.execute(
            """UPDATE assessments
               SET evaluator_version=?, reproduction_context_json='{}'
               WHERE assessment_id=?""",
            ("snapshot-v10", first.assessment.assessment_id),
        )
        connection.execute("DELETE FROM comparisons")
        old_endpoint = store._endpoint(connection, second.assessment.assessment_id)
        assert old_endpoint is not None
        store._auto_compare(connection, *old_endpoint)

    network_id = "extpan:78b9775b001c1cbe"
    dataset_id = "otbr_cli_networkdiag_fetch_all"
    before_service = TDHealthReadService(data_dir)
    before_list = before_service.comparisons(
        network_id=network_id, dataset_id=dataset_id, limit=25, offset=0
    )
    pinned_before = next(
        item for item in before_list["items"]
        if item["beforeAssessmentId"] == first.assessment.assessment_id
        and item["afterAssessmentId"] == second.assessment.assessment_id
    )
    before_detail = before_service.comparison(
        comparison_id=pinned_before["comparisonId"], limit=25, offset=0
    )
    assert set(before_detail["persistedReasons"]) >= {
        "evaluator-mismatch", "policy-mismatch"
    }

    inventory = inventory_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        target_policy=policy_two,
        dataset_ids=("otbr_cli_networkdiag_fetch_all",),
    )

    report = migrate_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        data_dir=data_dir,
        target_policy=policy_two,
        inventory=inventory,
        backup_output=tmp_path / "backup",
    )

    assert report["totals"]["created"] == 1, report["cohorts"]
    assert report["totals"]["comparisonsStored"] == 1
    after_service = TDHealthReadService(data_dir)
    after_list = after_service.comparisons(
        network_id=network_id, dataset_id=dataset_id, limit=25, offset=0
    )
    target_ids = {
        item["observationId"]: item["targetAssessmentId"]
        for cohort in report["cohorts"] for item in cohort["items"]
    }
    target_ids[second.observation.observation_id] = second.assessment.assessment_id
    migrated_pair = next(
        item for item in after_list["items"]
        if item["beforeAssessmentId"]
        == target_ids[first.observation.observation_id]
        and item["afterAssessmentId"]
        == target_ids[second.observation.observation_id]
    )
    migrated_detail = after_service.comparison(
        comparison_id=migrated_pair["comparisonId"], limit=25, offset=0
    )
    assert migrated_detail["persistedReasons"] == []
    assert "evaluator-mismatch" not in migrated_detail["reasons"]
    assert "policy-mismatch" not in migrated_detail["reasons"]
    retained_pinned = after_service.comparison(
        comparison_id=pinned_before["comparisonId"], limit=25, offset=0
    )
    assert retained_pinned["persistedReasons"] == before_detail["persistedReasons"]
    latest = store.latest_assessment(
        network_id, dataset_id
    )
    assert latest["assessment_id"] == second.assessment.assessment_id
    assert store.assessment_record(
        assessment_id=first.assessment.assessment_id
    )["assessment_id"] == first.assessment.assessment_id
    endpoints = store.assessment_endpoint_page(
        network_id=network_id,
        dataset_id=dataset_id,
        side="after",
        limit=10,
        offset=0,
    )
    preferred_ids = {row["assessmentId"] for row in endpoints["items"]}
    assert first.assessment.assessment_id not in preferred_ids
    assert second.assessment.assessment_id in preferred_ids
    assert len(preferred_ids) == 2
    observation_rows = {
        row["observation_id"]: row["preferredAssessmentId"]
        for row in store.observation_records(limit=10)
    }
    for cohort in report["cohorts"]:
        for item in cohort["items"]:
            assert observation_rows[item["observationId"]] == item[
                "targetAssessmentId"
            ]
    with closing(store._connect()) as connection:
        comparisons = connection.execute(
            "SELECT before_assessment_id, after_assessment_id FROM comparisons"
        ).fetchall()
        assert any(
            comparison["before_assessment_id"] in preferred_ids
            and comparison["after_assessment_id"] in preferred_ids
            for comparison in comparisons
        )


def test_migration_reserves_newest_comparison_pairs_with_current_endpoint_before_retention_cap(
    tmp_path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _seed(data_dir)
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    store = SQLiteHealthStore(database_path)
    snapshot = data_dir / "td-otbr-cli-networkdiag-fetch-all.json"
    identity = data_dir / "td-otbr-cli-thread-network-info.json"
    first_time = datetime.now(timezone.utc) - timedelta(days=3)
    native_results = []
    for index in range(3):
        snapshot.write_text(
            json.dumps(
                [{
                    "extAddress": "8672766ae0578187",
                    "role": "router",
                    "mleCounters": {"newParentCount": index},
                }]
            ),
            encoding="utf-8",
        )
        observed_at = first_time + timedelta(days=index)
        os.utime(snapshot, (observed_at.timestamp(), observed_at.timestamp()))
        os.utime(identity, (observed_at.timestamp(), observed_at.timestamp()))
        native_results.append(
            process_health(
                data_dir=data_dir,
                dataset_id="otbr_cli_networkdiag_fetch_all",
                policy=load_health_policy(),
                store=store,
            )
        )
    with closing(store._connect()) as connection:
        connection.execute(
            """UPDATE assessments SET evaluator_version='snapshot-v10',
               reproduction_context_json='{}' WHERE assessment_id != ?""",
            (native_results[1].assessment.assessment_id,),
        )
        comparison = connection.execute(
            "SELECT * FROM comparisons LIMIT 1"
        ).fetchone()
        columns = [
            row["name"]
            for row in connection.execute("PRAGMA table_info(comparisons)")
        ]
        comparison_id_index = columns.index("comparison_id")
        template = list(comparison)
        existing_count = connection.execute(
            "SELECT COUNT(*) FROM comparisons"
        ).fetchone()[0]
        filler_count = 1999 - existing_count
        connection.executemany(
            f"INSERT INTO comparisons VALUES ({','.join('?' for _ in columns)})",
            [
                tuple(
                    f"filler-comparison:{index}" if offset == comparison_id_index else value
                    for offset, value in enumerate(template)
                )
                for index in range(filler_count)
            ],
        )
        connection.commit()
    assert len(native_results) == 3
    policy = load_health_policy()
    inventory = inventory_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        target_policy=policy,
        dataset_ids=("otbr_cli_networkdiag_fetch_all",),
    )
    assert any(
        item.observation_id == native_results[1].observation.observation_id
        and item.eligibility.value == "already-current"
        for item in inventory.items
    )

    report = migrate_health_history(
        SQLiteHealthStore(database_path, read_only=True),
        data_dir=data_dir,
        target_policy=policy,
        inventory=inventory,
        backup_output=tmp_path / "backup",
    )

    assert report["outcome"] == "complete"
    assert report["totals"]["comparisonsStored"] == 1
    assert report["totals"]["comparisonsDeferred"] == 1
    targets = {
        item["observationId"]: item["targetAssessmentId"]
        for cohort in report["cohorts"]
        for item in cohort["items"]
    }
    with closing(store._connect()) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM comparisons"
        ).fetchone()[0] == 2000
        target_before_id = (
            native_results[1].assessment.assessment_id
            if native_results[1].observation.observation_id
            not in targets
            else targets[native_results[1].observation.observation_id]
        )
        assert connection.execute(
            """SELECT COUNT(*) FROM comparisons
               WHERE before_assessment_id=? AND after_assessment_id=?""",
            (
                target_before_id,
                targets[native_results[2].observation.observation_id],
            ),
        ).fetchone()[0] == 1


def test_top_level_json_has_no_banner(tmp_path) -> None:
    _seed(tmp_path)
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_cli.main(
            ["--datadir", str(tmp_path), "health", "process-dataset", "--dataset", "otbr_cli_networkdiag_fetch_all", "--dry-run", "--json"]
        ) == 0
    assert json.loads(output.getvalue())["datasetId"] == "otbr_cli_networkdiag_fetch_all"


def test_top_level_age_purge_dry_run_is_json_and_does_not_mutate(tmp_path) -> None:
    _seed(tmp_path)
    assert td_health_cli.main([
        "--datadir", str(tmp_path), "process-dataset",
        "--dataset", "otbr_cli_networkdiag_fetch_all",
    ]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_cli.main([
            "--datadir", str(tmp_path), "health", "purge",
            "--keep-days", "0", "--dry-run", "--json",
        ]) == 0
    document = json.loads(output.getvalue())
    assert document["command"] == "purge"
    assert document["dryRun"] is True
    assert document["deleted"]["observations"] == 1


def test_age_purge_defaults_to_configured_retention() -> None:
    args = td_health_cli.build_parser().parse_args(["purge"])

    assert args.keep_days == td_health_cli.DEFAULT_HEALTH_PURGE_KEEP_DAYS == 30


def test_purge_by_device_requires_confirmation(tmp_path) -> None:
    output = io.StringIO()
    with patch("builtins.input", return_value="n"), redirect_stdout(output):
        assert td_health_cli.main([
            "--datadir", str(tmp_path), "purge-by-device",
            "--device", "8672766ae0578187",
        ]) == 0
    assert "cancelled" in output.getvalue().lower()
    assert not (tmp_path / HOBAT_DATABASE_FILENAME).exists()


def test_roster_upsert_state_change_and_list_are_cli_only(tmp_path) -> None:
    _seed(tmp_path)
    output = io.StringIO()
    with redirect_stdout(output):
        assert td_health_cli.main([
            "--datadir", str(tmp_path),
            "process-dataset",
            "--dataset", "otbr_cli_networkdiag_fetch_all",
            "--roster-device", "86:72:76:6A:E0:57:81:87",
            "--roster-label", "Office Router",
            "--roster-state", "intermittent",
            "--json",
        ]) == 0
    document = json.loads(output.getvalue())
    assert document["devices"][0]["device_id"] == "extaddr:8672766ae0578187"
    assert document["devices"][0]["roster_state"] == "intermittent"

    output = io.StringIO()
    with redirect_stdout(output):
        assert td_health_cli.main([
            "--datadir", str(tmp_path),
            "process-dataset",
            "--dataset", "otbr_cli_networkdiag_fetch_all",
            "--roster-list",
            "--json",
        ]) == 0
    assert json.loads(output.getvalue())["devices"][0]["label"] == "Office Router"


def test_label_map_import_is_additive_and_reports_existing_entries(tmp_path) -> None:
    _seed(tmp_path)
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    network_id = "extpan:78b9775b001c1cbe"
    store.upsert_expected_device(
        network_id, "extaddr:8672766ae0578187", "Operator label", "retired"
    )
    (tmp_path / EXTADDR_DEVICE_LABEL_MAP_FILENAME).write_text(
        json.dumps([
            {"extAddress": "8672766ae0578187", "deviceLabel": "Static overwrite"},
            {"extAddress": "1111111111111111", "deviceLabel": "New device"},
            {"extAddress": "invalid"},
        ]),
        encoding="utf-8",
    )

    def import_map():
        output = io.StringIO()
        with redirect_stdout(output):
            assert td_health_cli.main([
                "--datadir", str(tmp_path), "process-dataset",
                "--dataset", "otbr_cli_networkdiag_fetch_all",
                "--init-roster-from-label-map", "--json",
            ]) == 0
        return json.loads(output.getvalue())

    first = import_map()
    assert (first["imported"], first["alreadyPresent"], first["skipped"]) == (1, 1, 1)
    second = import_map()
    assert (second["imported"], second["alreadyPresent"], second["skipped"]) == (0, 2, 1)
    records = {row["device_id"]: row for row in store.expected_device_records(network_id)}
    assert records["extaddr:8672766ae0578187"]["label"] == "Operator label"
    assert records["extaddr:8672766ae0578187"]["roster_state"] == "retired"
    assert records["extaddr:1111111111111111"]["label"] == "New device"


def test_all_processes_every_eligible_dataset_in_sorted_order(tmp_path) -> None:
    processed = []

    def fake_build_processing_result(**kwargs):
        processed.append(kwargs["dataset_id"])
        return kwargs["dataset_id"]

    with (
        patch.object(td_health_cli, "build_processing_result", side_effect=fake_build_processing_result),
        patch.object(td_health_cli, "result_document", side_effect=lambda dataset_id: {"datasetId": dataset_id}),
    ):
        output = io.StringIO()
        with redirect_stdout(output):
            assert td_health_cli.main([
                "--datadir", str(tmp_path),
                "process-dataset", "--dataset", "all", "--dry-run", "--json",
            ]) == 0

    expected = sorted(td_health_cli.load_health_manifest().datasets)
    assert processed == expected
    assert [item["datasetId"] for item in json.loads(output.getvalue())] == expected