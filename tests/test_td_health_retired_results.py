"""Four-product cutover and scoped, transactional retirement tests."""

import json
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest

import td_cli
import td_health_manifest
import td_health_manifest_history
from td_health_manifest import RETIRED_HEALTH_RESULT_DATASET_IDS, load_health_manifest
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_read import HealthEndpointUnavailableError, TDHealthReadService
from td_health_sqlite import SQLiteHealthStore
from test_td_health_sqlite import _result


@pytest.fixture
def retired_store(tmp_path, monkeypatch, archived_health_catalog):
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    for index, (dataset_id, dataset) in enumerate(load_health_manifest().datasets.items()):
        observation, assessment = _result()
        observation = replace(
            observation, observation_id=f"observation-{index}", dataset_id=dataset_id,
            datasource_id=dataset.datasource_id,
        )
        assessment = replace(
            assessment, assessment_id=f"assessment-{index}",
            observation_id=observation.observation_id,
        )
        store.save_processing_result(observation, assessment)
        with closing(store._connect()) as connection, connection:
            values = {
                "comparison_id": f"comparison-{index}", "dataset_id": dataset_id,
                "network_id": observation.network_id, "datasource_id": dataset.datasource_id,
                "before_assessment_id": assessment.assessment_id,
                "after_assessment_id": assessment.assessment_id,
                "before_observation_id": observation.observation_id,
                "after_observation_id": observation.observation_id,
            }
            columns = connection.execute("PRAGMA table_info(comparisons)").fetchall()
            values = {row["name"]: values.get(row["name"], 0 if row["type"] == "INTEGER" else "test")
                      for row in columns}
            connection.execute(
                f"INSERT INTO comparisons ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
                tuple(values.values()),
            )
            columns = connection.execute("PRAGMA table_info(comparison_items)").fetchall()
            values = {row["name"]: (f"comparison-{index}" if row["name"] == "comparison_id"
                      else 0 if row["type"] == "INTEGER" else "test") for row in columns}
            connection.execute(
                f"INSERT INTO comparison_items ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
                tuple(values.values()),
            )
            connection.execute(
                """INSERT INTO findings
                   SELECT ?, 'finding', 'network.test', 'strong', 'network', 1,
                          'test', 'test', 'test', '[]', 'high', 'test', 'test',
                          '[]', '[]', '[]'""", (assessment.assessment_id,),
            )
    monkeypatch.setattr(td_health_manifest.load_health_manifest, "__defaults__",
                        (td_health_manifest.MANIFEST_PATH,))
    monkeypatch.setattr(td_health_manifest_history.load_manifest_history, "__defaults__",
                        (td_health_manifest.MANIFEST_PATH, td_health_manifest_history.HISTORY_PATH))
    return store


def _rows(store):
    with closing(store._connect()) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )]
        return {table: sorted(tuple(row) for row in connection.execute(f"SELECT * FROM {table}"))
                for table in tables}


def test_purge_exact_scope_dry_run_rerun_and_preserved_rows(retired_store):
    before = _rows(retired_store)
    preview = retired_store.purge_retired_results(dry_run=True)
    assert set(preview["datasetIds"]) == RETIRED_HEALTH_RESULT_DATASET_IDS
    assert all(counts == {"findings": 1, "comparisons": 1, "comparison_items": 1,
                          "current_assessments": 1} for counts in preview["deleted"].values())
    assert _rows(retired_store) == before
    committed = retired_store.purge_retired_results()
    assert committed["deleted"] == preview["deleted"]
    after = _rows(retired_store)
    for table in before:
        if table not in {"findings", "comparisons", "comparison_items", "current_assessments"}:
            assert after[table] == before[table], table
    assert all(len(after[table]) == 4 for table in (
        "findings", "comparisons", "comparison_items", "current_assessments",
    ))
    with closing(retired_store._connect()) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        for dataset_id in load_health_manifest().datasets:
            assessment_id = connection.execute(
                "SELECT assessment_id FROM current_assessments WHERE dataset_id=?", (dataset_id,),
            ).fetchone()[0]
            for table in ("findings",):
                assert [row for row in after[table] if row[0] == assessment_id] == [
                    row for row in before[table] if row[0] == assessment_id
                ]
    rerun = retired_store.purge_retired_results()
    assert all(not any(counts.values()) for counts in rerun["deleted"].values())
    assert _rows(retired_store) == after


def test_purge_rolls_back_on_delete_failure(retired_store):
    with closing(retired_store._connect()) as connection, connection:
        connection.execute(
            """CREATE TRIGGER reject_retirement BEFORE DELETE ON comparisons
               BEGIN SELECT RAISE(ABORT, 'test purge failure'); END"""
        )
    before = _rows(retired_store)
    with pytest.raises(sqlite3.DatabaseError, match="test purge failure"):
        retired_store.purge_retired_results()
    assert _rows(retired_store) == before


def test_retired_results_cannot_be_read_or_recreated(retired_store, tmp_path):
    service = TDHealthReadService(tmp_path)
    with closing(retired_store._connect()) as connection:
        row = connection.execute(
            """SELECT a.assessment_id FROM assessments a JOIN observations o USING(observation_id)
               WHERE o.dataset_id='otbr_cli_diagnostics_fetch'"""
        ).fetchone()
    for kwargs in ({"dataset_id": "otbr_cli_diagnostics_fetch"}, {"assessment_id": row[0]}):
        with pytest.raises(HealthEndpointUnavailableError, match="retired"):
            service.assessment(**kwargs)
    retired_store.purge_retired_results()
    with pytest.raises(HealthEndpointUnavailableError, match="purged history"):
        service.assessment(assessment_id=row[0])
    with pytest.raises(ValueError, match="retired"):
        retired_store.compare_assessments(row[0], row[0])
    observation, assessment = _result()
    with pytest.raises(ValueError, match="retired"):
        retired_store.save_processing_result(observation, assessment)
    with closing(retired_store._connect()) as connection, connection:
        retired_store._repair_current_assessments(connection)
        assert {row[0] for row in connection.execute(
            "SELECT dataset_id FROM current_assessments"
        )} == set(load_health_manifest().datasets)


def test_cli_requires_backup_and_reports_exact_counts(retired_store, tmp_path, capsys):
    args = ["--datadir", str(tmp_path), "health", "purge-retired-results", "--json"]
    before = _rows(retired_store)
    assert td_cli.main([*args, "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["dryRun"] is True
    assert _rows(retired_store) == before
    with pytest.raises(SystemExit):
        td_cli.main([*args, "--yes"])
    backup = tmp_path.parent / (tmp_path.name + "-retirement-backup")
    assert td_cli.main([*args, "--yes", "--backup-output", str(backup)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["backupOutput"] == str(backup)
    assert (backup / "hobat-backup-manifest.json").is_file()
    with sqlite3.connect(backup / HOBAT_DATABASE_FILENAME) as connection:
        assert connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 11
