"""Original-evidence qualification and retained Unified health regressions."""

import hashlib
import json
import os
import sqlite3
from collections import Counter
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from td_health_manifest import load_health_manifest
from td_health_migration import inventory_health_history
from td_health_policy import load_health_policy
from td_health_processor import HealthProcessingError, build_processing_result, process_health
from td_health_read import TDHealthReadService
from td_health_sqlite import SQLiteHealthStore, _RetainedHistory
from td_unified_dataset import build_unified_dataset, read_original_evidence
from test_td_unified_dataset import (
    NETWORK, SOURCE_TIME, _entry, _save, _seed, _seed_ha, _seed_ha_controller,
)


IDS = ("otbr_cli_unified", "otbr_restapi_unified", "ha_matter_ws_unified", "multi_source_unified")


def seed(directory, dataset_id):
    if dataset_id == "multi_source_unified":
        for item in ("otbr_cli_unified", "otbr_restapi_unified", "ha_matter_ws_unified", "mdns_unified"):
            _seed(directory, item)
    else:
        _seed(directory, dataset_id)
    build_unified_dataset(directory, dataset_id)


def process(directory, dataset_id, store=None, **kwargs):
    return (process_health if store else build_processing_result)(
        data_dir=directory, dataset_id=dataset_id, policy=load_health_policy(),
        **({"store": store} if store else {}), **kwargs,
    )


@pytest.mark.parametrize("dataset_id", IDS)
@pytest.mark.parametrize("builder_contract", [
    "unified-assembly-v2", "unified-assembly-v3", "unified-assembly-v4",
    "unified-assembly-v5", "unified-assembly-v6", "unified-assembly-v7", "unified-assembly-v8",
    "unified-assembly-v9", "unified-assembly-v10",
])
def test_original_samples_are_scoped_stable_and_reopenable(
    tmp_path, dataset_id, builder_contract, monkeypatch,
):
    monkeypatch.setattr("td_unified_dataset.BUILDER_CONTRACT", builder_contract)
    seed(tmp_path, dataset_id)
    before = {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    first = process(tmp_path, dataset_id, store)
    second = process(tmp_path, dataset_id, store)
    assert first.observation.observation_id == second.observation.observation_id
    assert first.assessment.assessment_id == second.assessment.assessment_id
    assert second.observation_created is False
    assert first.assessment.sample_contract_version == "comparison-v1-unified"
    assert first.observation.observed_at == SOURCE_TIME
    assert first.observation.devices
    assert all("unified" not in name and not name.startswith("td-mdns")
               for device in first.observation.devices for name in device.source_files)
    assert all("unified" not in source.filename for source in first.observation.sources)
    assert first.assessment.reproduction_context["unifiedHealth"]["recipe"]
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.json")} == before
    reopened = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    with closing(reopened._connect()) as connection:
        endpoint = reopened._endpoint(connection, first.assessment.assessment_id)
    assert endpoint is not None
    assert endpoint[0] == first.observation
    inventory = inventory_health_history(
        SQLiteHealthStore(tmp_path / "hobat_v1.db", read_only=True),
        target_policy=load_health_policy(), dataset_ids=(dataset_id,),
    )
    assert inventory.items
    assert inventory.items[0].eligibility.value == "already-current", inventory.items[0].reason_codes


def test_unrecognized_assembly_contract_does_not_validate_retained_context(tmp_path):
    from td_health_manifest import HealthManifestError
    from td_health_unified import digest, plain, validate_context

    seed(tmp_path, "otbr_restapi_unified")
    result = process(tmp_path, "otbr_restapi_unified")
    context = plain(result.assessment.reproduction_context)
    dataset = load_health_manifest().dataset("otbr_restapi_unified")
    context["unifiedHealth"]["reportContractDigest"] = digest([
        "unified-v1", "unified-assembly-unsupported",
        dataset.unified_recipe["recipeDigest"], dataset.unified_recipe["authorityDigest"],
    ])
    with pytest.raises(HealthManifestError, match="Invalid retained unifiedHealth context"):
        validate_context(context, dataset, result.observation)


@pytest.mark.parametrize("dataset_id", IDS)
def test_qualification_profiles_and_no_ha_negative_authority(tmp_path, dataset_id):
    seed(tmp_path, dataset_id)
    result = process(tmp_path, dataset_id)
    profile = load_health_manifest().dataset(dataset_id).health_profile
    assert profile.input_mode == "unified"
    assert load_health_manifest().dataset(dataset_id).unified_recipe["version"] == "unified-v1"
    assert profile.evidence_report.endswith(".report.json")
    assert set(profile.coverage) == {"availability", "connectivity", "delivery", "resilience", "externalRouting"}
    context = result.assessment.reproduction_context["unifiedHealth"]
    if dataset_id == "ha_matter_ws_unified":
        assert context["absenceWitness"] is None
        assert result.observation.completeness.value == "degraded"
        assert not result.assessment.coverage["topologyAuthority"]
        assert not result.assessment.coverage["borderRouterAuthority"]
    else:
        assert context["absenceWitness"]["domain"] == (
            "otbr-restapi" if dataset_id == "otbr_restapi_unified" else "otbr-cli")


def test_typed_controller_health_is_complete_without_absence_authority(tmp_path):
    from td_health_unified import digest

    entry = _seed_ha_controller(tmp_path)
    report = build_unified_dataset(tmp_path, entry["value"])
    assert report["healthState"] == "complete"
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    first = process(tmp_path, "ha_matter_ws_unified", store)
    context = first.assessment.reproduction_context["unifiedHealth"]
    source_times = context["sourceTimeProvenance"]
    controller = [item for item in source_times
                  if item["sourceObservationKind"] == "controller-snapshot"]
    assert len(controller) == 5
    assert all(item["timeProvenance"] == "controller-snapshot" for item in controller)
    assert context["sourceTimeProvenanceDigest"] == digest(source_times)
    assert context["absenceWitness"] is None
    assert first.observation.completeness.value == "complete"
    assert first.assessment.evaluator_version == "snapshot-v18"
    assert not first.assessment.coverage["offlineEligible"]
    assert not first.assessment.coverage["topologyAuthority"]
    assert first.assessment.coverage["sourceObservationKinds"] == {
        item["filename"]: "controller-snapshot" for item in controller
    }
    controller_files = {item["filename"] for item in controller}
    assert not any(
        fact.source_file in controller_files and fact.value_class == "transient"
        for fact in first.roster_facts
    )
    assert any(
        fact.field_key == "extAddress" and fact.value_class == "identity"
        and fact.source_file == "td-ha-matter-ws-devices-fetch-all.json"
        for fact in first.roster_facts
    )

    second = process(tmp_path, "ha_matter_ws_unified", store)
    assert second.observation.observation_id == first.observation.observation_id
    assert second.assessment.assessment_id == first.assessment.assessment_id
    assert second.observation_created is False
    reopened = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    with closing(reopened._connect()) as connection:
        retained = reopened._endpoint(connection, first.assessment.assessment_id)
    assert retained[0] == first.observation
    assert retained[1].reproduction_context["unifiedHealth"]["sourceTimeProvenance"] == source_times


def test_typed_controller_metrics_have_no_measurement_interval(tmp_path):
    from td_health_comparison import derive_comparison, source_roles_for_dataset
    from td_health_observation_model import MetricSample

    entry = _seed_ha_controller(tmp_path)
    build_unified_dataset(tmp_path, entry["value"])
    result = process(tmp_path, "ha_matter_ws_unified")
    source_file = next(
        item["filename"] for item in result.assessment.reproduction_context[
            "unifiedHealth"
        ]["sourceTimeProvenance"]
        if item["sourceObservationKind"] == "controller-snapshot"
    )
    before_observation = replace(result.observation, metrics=(MetricSample(
        "extaddr:0011223344556677", "parentChanges", 8.0, "count", None, source_file,
    ),))
    after_time = "2026-01-02T00:00:00+00:00"
    after_observation = replace(
        before_observation, observation_id="observation:later-controller-read",
        observed_at=after_time, ingested_at=after_time,
        metrics=(MetricSample(
            "extaddr:0011223344556677", "parentChanges", 2.0, "count", None, source_file,
        ),),
    )
    before_assessment = replace(
        result.assessment, assessment_id="assessment:before-controller-read",
        observation_id=before_observation.observation_id,
    )
    after_assessment = replace(
        result.assessment, assessment_id="assessment:after-controller-read",
        observation_id=after_observation.observation_id, assessed_at=after_time,
    )
    interval, items = derive_comparison(
        (before_observation, before_assessment),
        (after_observation, after_assessment),
        source_roles=source_roles_for_dataset(
            load_health_manifest().dataset("ha_matter_ws_unified"),
        ),
    )
    counter = next(item for item in items if item.kind == "counter-delta")
    assert interval.elapsed_seconds is None
    assert not interval.compatibility.comparable
    assert counter.delta is None
    assert counter.change == "unknown"
    assert "reset-unknown" in counter.compatibility.reasons
    assert "reset-detected" not in counter.compatibility.reasons


def test_typed_controller_checkpoint_stays_partial_when_allowed(tmp_path):
    entry = _seed_ha_controller(tmp_path)
    build_unified_dataset(tmp_path, entry["value"])
    filename = "td-ha-matter-ws-devices-fetch-all.json"
    final = tmp_path / filename
    checkpoint = tmp_path / filename.replace(".json", ".partial.json")
    checkpoint.write_text("[]")
    newer = final.stat().st_mtime + 2
    os.utime(checkpoint, (newer, newer))

    result = process(tmp_path, "ha_matter_ws_unified", allow_partial=True)
    provenance = {
        item["filename"]: item
        for item in result.assessment.reproduction_context["unifiedHealth"][
            "sourceTimeProvenance"
        ]
    }
    assert result.observation.completeness.value == "partial"
    assert provenance[filename]["state"] == "provisional"
    assert provenance[filename]["sourceObservationKind"] == "controller-snapshot"


def test_missing_optional_controller_inputs_do_not_downgrade_complete_ha(tmp_path):
    entry = _seed_ha_controller(tmp_path)
    optional_controller_files = [
        item["file"] for item in entry["unified"]["inputs"]
        if not item["required"] and item["extractor"] in {
            "ha-inventory", "raw-array", "ha-projection",
        }
    ]
    assert optional_controller_files
    for filename in optional_controller_files:
        (tmp_path / filename).unlink()

    report = build_unified_dataset(tmp_path, entry["value"])
    assert report["healthState"] == "complete"
    result = process(tmp_path, "ha_matter_ws_unified")
    assert result.observation.completeness.value == "complete"
    assert result.assessment.reproduction_context["unifiedHealth"]["absenceWitness"] is None


def test_source_time_provenance_requires_v11_builder_context(tmp_path):
    from td_health_manifest import HealthManifestError
    from td_health_unified import digest, plain, validate_context

    entry = _seed_ha_controller(tmp_path)
    build_unified_dataset(tmp_path, entry["value"])
    result = process(tmp_path, "ha_matter_ws_unified")
    dataset = load_health_manifest().dataset("ha_matter_ws_unified")
    context = plain(result.assessment.reproduction_context)
    context["unifiedHealth"]["reportContractDigest"] = digest([
        "unified-v1", "unified-assembly-v10",
        dataset.unified_recipe["recipeDigest"], dataset.unified_recipe["authorityDigest"],
    ])
    with pytest.raises(HealthManifestError, match="Source-time provenance requires the v11"):
        validate_context(context, dataset, result.observation)


def test_malformed_typed_source_time_provenance_is_not_silently_downgraded(tmp_path):
    from td_health_manifest import HealthManifestError
    from td_health_unified import has_typed_ha_observation, plain

    entry = _seed_ha_controller(tmp_path)
    build_unified_dataset(tmp_path, entry["value"])
    result = process(tmp_path, "ha_matter_ws_unified")
    dataset = load_health_manifest().dataset("ha_matter_ws_unified")
    context = plain(result.assessment.reproduction_context)
    context["unifiedHealth"]["sourceTimeProvenance"][0]["timeProvenance"] = {}
    with pytest.raises(HealthManifestError, match="Invalid retained Unified source-time provenance"):
        has_typed_ha_observation(context, dataset)


@pytest.mark.parametrize(
    ("typed_controller", "forged_evaluator"),
    [(False, "snapshot-v18"), (True, "snapshot-v17")],
)
def test_retained_unified_evaluator_must_match_typed_provenance(
    tmp_path, typed_controller, forged_evaluator,
):
    from td_health_sqlite import ReassessmentBaselineUnavailable

    if typed_controller:
        _seed_ha_controller(tmp_path)
    else:
        _seed_ha(tmp_path)
    build_unified_dataset(tmp_path, "ha_matter_ws_unified")
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    result = process(tmp_path, "ha_matter_ws_unified", store)
    with closing(store._connect()) as connection, connection:
        row = connection.execute(
            "SELECT reproduction_context_json FROM assessments WHERE assessment_id=?",
            (result.assessment.assessment_id,),
        ).fetchone()
        context = json.loads(row["reproduction_context_json"])
        context["evaluatorVersion"] = forged_evaluator
        connection.execute(
            """UPDATE assessments SET evaluator_version=?, reproduction_context_json=?
               WHERE assessment_id=?""",
            (forged_evaluator, json.dumps(context), result.assessment.assessment_id),
        )
    with closing(store._connect()) as connection:
        with pytest.raises(
            ReassessmentBaselineUnavailable,
            match="refresh health from retained snapshots",
        ):
            store._reassessment_inputs(connection, result.assessment.assessment_id)


def test_multisource_controller_reread_does_not_advance_original_witness_or_sources(tmp_path):
    from td_health_comparison import derive_comparison, source_roles_for_dataset
    from td_health_observation_model import MetricSample

    seed(tmp_path, "multi_source_unified")
    _seed_ha_controller(tmp_path)
    build_unified_dataset(tmp_path, "multi_source_unified")
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    first = process(tmp_path, "multi_source_unified", store)
    first_context = first.assessment.reproduction_context["unifiedHealth"]
    first_witness = first_context["absenceWitness"]
    assert first_witness["domain"] in {"otbr-cli", "otbr-restapi"}
    first_sources = {
        item["filename"]: item for item in first_context["sourceTimeProvenance"]
    }
    first_cli_rest = {
        name: (item["digest"], item["sourceObservedAt"])
        for name, item in first_sources.items()
        if name.startswith(("td-otbr-cli-", "td-otbr-restapi-"))
    }

    later = "2026-02-01T00:00:00+00:00"
    controller_files = (
        "td-ha-matter-ws-devices-fetch-all.json",
        "td-ha-matter-ws-topology.json",
        "td-ha-matter-ws-diagnostics-fetch-all.json",
        "td-ha-matter-ws-mesh-diagnostics-fetch-all.json",
        "td-ha-matter-ws-dashboard.json",
    )

    def retime(value):
        if isinstance(value, dict):
            if value.get("sourceObservationKind") == "controller-snapshot":
                value["sourceObservedAt"] = later
            for child in value.values():
                retime(child)
        elif isinstance(value, list):
            for child in value:
                retime(child)

    bindings = {}
    for filename in controller_files:
        payload = json.loads((tmp_path / filename).read_text())
        retime(payload)
        path = _save(tmp_path, filename, payload)
        bindings[filename] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "recordCount": len(payload if isinstance(payload, list) else payload["devices"]),
            "sourceObservedAt": later,
            "sourceObservationKind": "controller-snapshot",
        }
    outcome_file = "td-ha-matter-ws-collection.outcome.json"
    outcome = json.loads((tmp_path / outcome_file).read_text())
    outcome["sourceObservedAt"] = later
    outcome["completedAt"] = later
    outcome["artifactObservations"] = bindings
    _save(tmp_path, outcome_file, outcome)
    build_unified_dataset(tmp_path, "multi_source_unified")
    second = process(tmp_path, "multi_source_unified", store)
    second_context = second.assessment.reproduction_context["unifiedHealth"]
    second_sources = {
        item["filename"]: item for item in second_context["sourceTimeProvenance"]
    }
    second_cli_rest = {
        name: (item["digest"], item["sourceObservedAt"])
        for name, item in second_sources.items()
        if name.startswith(("td-otbr-cli-", "td-otbr-restapi-"))
    }
    assert second.observation.observed_at > first.observation.observed_at
    assert second_cli_rest == first_cli_rest
    assert second_context["absenceWitness"] == first_witness
    assert second_context["absenceWitness"]["domain"] in {"otbr-cli", "otbr-restapi"}
    counter_file = "td-otbr-cli-networkdiag-fetch-all.json"
    assert any(source.filename == counter_file for source in first.observation.sources)
    before_observation = replace(first.observation, metrics=(MetricSample(
        "extaddr:0011223344556677", "parentChanges", 8.0, "count", None, counter_file,
    ),))
    after_observation = replace(second.observation, metrics=(MetricSample(
        "extaddr:0011223344556677", "parentChanges", 2.0, "count", None, counter_file,
    ),))
    interval, items = derive_comparison(
        (before_observation, first.assessment),
        (after_observation, second.assessment),
        source_roles=source_roles_for_dataset(
            load_health_manifest().dataset("multi_source_unified"),
        ),
    )
    counter = next(item for item in items if item.kind == "counter-delta")
    assert interval.elapsed_seconds is not None
    assert counter.delta is None
    assert counter.change == "unknown"
    assert counter.reset_evidence.state == "unknown"
    assert "source-not-newer" in counter.compatibility.reasons


@pytest.mark.parametrize("case", ["recovered", "missing-binding", "mesh-partial"])
def test_rest_unified_revalidates_recovery_and_preserves_other_gates(tmp_path, case):
    from test_td_restapi_diagnostic_recovery import _fixture
    from util_data import network_scope_path

    outcome, diagnostics = _fixture()
    _seed(tmp_path, "otbr_restapi_unified")
    diagnostic_file = "td-otbr-restapi-diagnostics-fetch-all.json"
    outcome_file = "td-otbr-restapi-diagnostics-fetch-all.outcome.json"
    _save(tmp_path, diagnostic_file, diagnostics)
    outcome_path = _save(tmp_path, outcome_file, outcome)
    if case == "missing-binding":
        network_scope_path(outcome_path).unlink()
    if case == "mesh-partial":
        _save(tmp_path, "td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json", {
            "deviceResults": [{"status": "completed"}],
            "partial": True,
            "completedAt": SOURCE_TIME,
        })
    originals = {name: (tmp_path / name).read_bytes() for name in (diagnostic_file, outcome_file)}

    built = build_unified_dataset(tmp_path, "otbr_restapi_unified")
    reasons = built["coverage"]["healthReasons"]
    assert (f"incomplete-outcome:{outcome_file}" in reasons) == (case == "missing-binding")
    mesh_reason = "incomplete-outcome:td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json"
    assert (mesh_reason in reasons) == (case == "mesh-partial")
    result = process(tmp_path, "otbr_restapi_unified")
    coverage = result.assessment.coverage["restDiagnostics"]
    assert coverage["summary"]["recoveredChildren"] == (case != "missing-binding")
    assert result.assessment.evaluator_version == "snapshot-v17"
    assert {name: (tmp_path / name).read_bytes() for name in originals} == originals


@pytest.mark.parametrize("child_table", [[], [{"childId": 42}]])
@pytest.mark.parametrize("builder_contract", ["unified-assembly-v10", "unified-assembly-v11"])
def test_rest_child_table_coverage_uses_only_independent_rest_absence_authority(
    tmp_path, child_table, builder_contract, monkeypatch,
):
    from test_td_unified_composition import _seed_rest_child_coverage

    monkeypatch.setattr("td_unified_dataset.BUILDER_CONTRACT", builder_contract)
    _seed_rest_child_coverage(tmp_path, child_table=child_table, completed=True)
    report = build_unified_dataset(tmp_path, "multi_source_unified")
    assert report["healthState"] == "complete"
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    missing_child = "extaddr:2222222222222222"
    store.upsert_expected_device(NETWORK, missing_child, "child", "expected")
    with closing(store._connect()) as connection, connection:
        connection.execute("UPDATE expected_devices SET expected_since='2025-12-01T00:00:00+00:00'")
    result = process(tmp_path, "multi_source_unified", store)
    context = result.assessment.reproduction_context["unifiedHealth"]
    assert result.assessment.coverage["restChildTableCoverage"] == report["coverage"]["restChildTableCoverage"]
    assert result.assessment.coverage["meshdiagTablesNotProvided"] == 1
    assert all(relationship.to_device_id != missing_child for relationship in result.observation.relationships)
    if child_table:
        assert context["absenceWitness"] is None
        assert result.observation.completeness.value == "degraded"
        assert not any(f.rule_id == "device.offline" and missing_child in f.device_ids
                       for f in result.assessment.findings)
    else:
        assert context["absenceWitness"]["domain"] == "otbr-restapi"
        assert result.observation.completeness.value == "complete"
    repeated = process(tmp_path, "multi_source_unified", store)
    assert not repeated.observation_created
    assert not repeated.assessment_created
    with closing(store._connect()) as connection:
        reopened = store._endpoint(connection, result.assessment.assessment_id)
    assert reopened[0] == result.observation


@pytest.mark.parametrize("case", ["matched", "ambiguous", "conflicting-child-rloc"])
def test_rest_child_table_relationship_requires_same_run_unique_identity(tmp_path, case):
    from test_td_unified_composition import _seed_rest_child_coverage

    table_child = {"childId": 42, "rloc16": "0x442a"}
    if case == "conflicting-child-rloc":
        table_child["rloc16"] = "0x442b"
    _seed_rest_child_coverage(tmp_path, child_table=[table_child], completed=True)
    _add_completed_rest_child(tmp_path, ambiguous=case == "ambiguous")
    report = build_unified_dataset(tmp_path, "multi_source_unified")
    [router] = report["coverage"]["restChildTableCoverage"]["routers"]
    assert router["childCount"] == 1
    assert router["resolvedChildCount"] == (case == "matched")
    result = process(tmp_path, "multi_source_unified")
    link = next((item for item in result.observation.relationships
                 if item.from_device_id == "extaddr:8899aabbccddeeff"
                 and item.to_device_id == "extaddr:2222222222222222"), None)
    assert (link is not None) == (case == "matched")
    witness = result.assessment.reproduction_context["unifiedHealth"]["absenceWitness"]
    assert (witness is not None and witness["domain"] == "otbr-restapi") == (case == "matched")


def _add_completed_rest_child(directory, *, ambiguous=False):
    from test_td_restapi_diagnostic_recovery import _action

    diagnostic_file = "td-otbr-restapi-diagnostics-fetch-all.json"
    outcome_file = "td-otbr-restapi-diagnostics-fetch-all.outcome.json"
    outcome = json.loads((directory / outcome_file).read_text())
    child = {"id": "child-diagnostic", "extAddress": "2222222222222222",
             "rloc16": "0x442a", "created": "2026-10-30T11:00:01+00:00"}
    outcome["items"].append(child)
    outcome["deviceResults"].append({
        "deviceId": child["extAddress"], "role": "child", "status": "completed",
        "diagnosticId": child["id"], "action": _action(child["id"]),
    })
    if ambiguous:
        duplicate = {**child, "id": "other-diagnostic", "extAddress": "3333333333333333"}
        outcome["items"].append(duplicate)
        outcome["deviceResults"].append({
            "deviceId": duplicate["extAddress"], "role": "child", "status": "completed",
            "diagnosticId": duplicate["id"], "action": _action(duplicate["id"]),
        })
    _save(directory, diagnostic_file, outcome["items"])
    _save(directory, outcome_file, outcome)
    diagnostic_time = datetime(2026, 10, 30, 11, 0, 1, tzinfo=timezone.utc).timestamp()
    os.utime(directory / diagnostic_file, (diagnostic_time, diagnostic_time))


@pytest.mark.parametrize("dataset_id", ["otbr_restapi_unified", "otbr_restapi_devices_diagnostics_fetch"])
@pytest.mark.parametrize("matched", [False, True])
@pytest.mark.usefixtures("archived_health_catalog")
def test_rest_health_child_table_needs_bound_identity_for_presence_and_absence(tmp_path, dataset_id, matched):
    from test_td_unified_composition import _seed_rest_child_coverage

    _seed_rest_child_coverage(tmp_path, child_table=[{"childId": 42, "rloc16": "0x442a"}], completed=True)
    if matched:
        _add_completed_rest_child(tmp_path)
    if dataset_id.endswith("_unified"):
        build_unified_dataset(tmp_path, dataset_id)
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    child_id = "extaddr:2222222222222222"
    store.upsert_expected_device(NETWORK, child_id, "child", "expected")
    with closing(store._connect()) as connection, connection:
        connection.execute("UPDATE expected_devices SET expected_since='2025-12-01T00:00:00+00:00'")
    result = process(tmp_path, dataset_id, store)
    link = next((item for item in result.observation.relationships if item.to_device_id == child_id), None)
    assert (link is not None) is matched
    assert result.observation.completeness.value == ("complete" if matched else "degraded")
    if not matched:
        assert not any(f.rule_id == "device.offline" and child_id in f.device_ids
                       for f in result.assessment.findings)
    if dataset_id.endswith("_unified"):
        witness = result.assessment.reproduction_context["unifiedHealth"]["absenceWitness"]
        assert (witness is not None) is matched


def test_ambiguous_rloc_aliases_do_not_create_cross_source_relationships():
    from td_health_processor import _normalize_samples

    filename = "td-otbr-cli-meshdiag-topology.json"
    dataset = replace(load_health_manifest().dataset("multi_source_unified"), files=(filename,))
    parent = {"extAddress": "1111111111111111", "children": [{"rloc16": "0x042a"}]}
    child = {"extAddress": "2222222222222222", "rloc16": "0x42a"}
    conflicting = {"extAddress": "3333333333333333", "rloc16": "0x042a"}
    _, links, _, _, _ = _normalize_samples(dataset, {filename: [parent, child]})
    assert len(links) == 1
    _, links, _, _, _ = _normalize_samples(dataset, {filename: [parent, child, conflicting]})
    assert links == ()


@pytest.mark.parametrize("case", ["projection", "tables", "reason", "cli-dependency"])
def test_rest_child_table_coverage_rejects_tampered_composition_report(tmp_path, case):
    from test_td_unified_composition import _seed_rest_child_coverage

    _seed_rest_child_coverage(tmp_path, completed=True)
    build_unified_dataset(tmp_path, "multi_source_unified")
    path = tmp_path / _entry("multi_source_unified")["unified"]["reportFile"]
    report = json.loads(path.read_text())
    coverage = report["coverage"]
    if case == "projection":
        coverage["restChildTableCoverage"]["routers"][0]["childCount"] += 1
    elif case == "tables":
        coverage["tablesNotProvided"].pop()
    elif case == "reason":
        coverage["healthReasons"].append("otbr-cli:uncovered-children:0x4400")
    else:
        coverage["sources"]["otbr-cli"]["coverage"]["healthReasons"].clear()
    path.write_text(json.dumps(report))
    with pytest.raises(HealthProcessingError, match="coverage|exemptions"):
        process(tmp_path, "multi_source_unified")


@pytest.mark.parametrize("domain", ["otbr-restapi", "ha-matter-ws"])
def test_rest_child_coverage_cannot_hide_other_dependency_reasons(tmp_path, domain):
    from test_td_unified_composition import _seed_rest_child_coverage

    _seed_rest_child_coverage(tmp_path, completed=True)
    if domain == "otbr-restapi":
        filename = "td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json"
        _save(tmp_path, filename, {"deviceResults": [{"status": "completed"}],
                                   "partial": True, "completedAt": SOURCE_TIME})
    else:
        filename = "td-ha-matter-ws-collection.outcome.json"
        payload = json.loads((tmp_path / filename).read_text())
        payload["normalizedNodeCount"] += 1
        _save(tmp_path, filename, payload)
    report = build_unified_dataset(tmp_path, "multi_source_unified")
    reason = next(reason for reason in report["coverage"]["healthReasons"]
                  if reason.startswith(f"{domain}:"))
    assert report["healthState"] == "degraded"
    path = tmp_path / _entry("multi_source_unified")["unified"]["reportFile"]
    report = json.loads(path.read_text())
    report["coverage"]["healthReasons"].remove(reason)
    path.write_text(json.dumps(report))
    with pytest.raises(HealthProcessingError, match="coverage reasons changed"):
        process(tmp_path, "multi_source_unified")


def test_rest_child_table_coverage_remains_partial_with_newer_checkpoint(tmp_path):
    from test_td_unified_composition import _seed_rest_child_coverage

    _seed_rest_child_coverage(tmp_path, completed=True)
    build_unified_dataset(tmp_path, "multi_source_unified")
    partial = tmp_path / "td-otbr-restapi-diagnostics-fetch-all.partial.json"
    partial.write_text("[]")
    result = process(tmp_path, "multi_source_unified", allow_partial=True)
    assert result.observation.completeness.value == "partial"
    assert result.assessment.reproduction_context["unifiedHealth"]["absenceWitness"] is None


def test_rest_child_table_retained_context_rejects_malformed_router_files(tmp_path):
    import sqlite3
    from test_td_unified_composition import _seed_rest_child_coverage

    _seed_rest_child_coverage(tmp_path, completed=True)
    build_unified_dataset(tmp_path, "multi_source_unified")
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    result = process(tmp_path, "multi_source_unified", store)
    with closing(store._connect()) as connection, connection:
        row = connection.execute(
            "SELECT reproduction_context_json FROM assessments WHERE assessment_id=?",
            (result.assessment.assessment_id,),
        ).fetchone()
        context = json.loads(row[0])
        context["unifiedHealth"]["restChildTableCoverage"]["routers"][0]["cliFiles"] = [{}]
        connection.execute(
            "UPDATE assessments SET reproduction_context_json=? WHERE assessment_id=?",
            (json.dumps(context), result.assessment.assessment_id),
        )
        with pytest.raises(sqlite3.DatabaseError):
            store._endpoint(connection, result.assessment.assessment_id)


def test_rest_child_coverage_history_never_joins_cli_absences(tmp_path):
    from test_td_unified_composition import _seed_rest_child_coverage

    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    absent = "extaddr:aaaaaaaaaaaaaaaa"
    store.upsert_expected_device(NETWORK, absent, "expected", "expected")
    with closing(store._connect()) as connection, connection:
        connection.execute("UPDATE expected_devices SET expected_since='2025-12-01T00:00:00+00:00'")
    for day in (1, 2):
        collection(tmp_path, "otbr_cli_unified", day)
        process(tmp_path, "otbr_cli_unified", store)
    _seed_rest_child_coverage(tmp_path, child_table=[], completed=True)
    build_unified_dataset(tmp_path, "multi_source_unified")
    result = process(tmp_path, "multi_source_unified", store)
    finding = next(f for f in result.assessment.findings
                   if absent in f.device_ids and f.rule_id in {"device.missing", "device.offline"})
    assert finding.rule_id == "device.missing"
    assert finding.evidence["consecutiveCompleteAbsences"] == 1
    assert result.assessment.reproduction_context["unifiedHealth"]["absenceWitness"]["domain"] == "otbr-restapi"
    for path in tmp_path.glob("*.json"):
        path.unlink()
    store.upsert_expected_device(NETWORK, absent, "renamed", "expected")
    with closing(store._connect()) as connection:
        row = connection.execute(
            "SELECT assessment_id FROM current_assessments WHERE dataset_id='multi_source_unified'"
        ).fetchone()
        _, reassessed = store._endpoint(connection, row["assessment_id"])
    assert reassessed.coverage["restChildTableCoverage"] == result.assessment.coverage["restChildTableCoverage"]
    assert reassessed.reproduction_context["unifiedHealth"]["absenceWitness"]["domain"] == "otbr-restapi"


@pytest.mark.parametrize("damage", ["changed", "deleted", "scope", "outcome"])
def test_unified_health_rejects_stale_evidence_even_allow_partial(tmp_path, damage):
    seed(tmp_path, "otbr_cli_unified")
    filename = "td-otbr-cli-networkdiag-fetch-all.json"
    if damage == "deleted":
        (tmp_path / filename).unlink()
    elif damage == "changed":
        (tmp_path / filename).write_text("[]")
    elif damage == "scope":
        (tmp_path / filename.replace(".json", ".network.json")).write_text("{}")
    else:
        (tmp_path / "td-otbr-cli-unified.outcome.json").write_text("{}")
    with pytest.raises(HealthProcessingError):
        process(tmp_path, "otbr_cli_unified", allow_partial=True)


def test_runtime_partial_and_rest_failed_outcomes_never_supply_negative_witness(tmp_path):
    _seed(tmp_path, "otbr_restapi_unified")
    _save(tmp_path, "td-otbr-restapi-diagnostics-fetch-all.outcome.json",
          {"deviceResults": [{"status": "failed"}], "completedAt": SOURCE_TIME})
    build_unified_dataset(tmp_path, "otbr_restapi_unified")
    result = process(tmp_path, "otbr_restapi_unified")
    assert result.assessment.reproduction_context["unifiedHealth"]["absenceWitness"] is None
    assert result.observation.completeness.value != "complete"


def test_roster_facts_have_original_field_authority_not_aggregate_rank(tmp_path):
    seed(tmp_path, "multi_source_unified")
    result = process(tmp_path, "multi_source_unified")
    assert result.roster_facts
    assert all("unified" not in fact.source_file and not fact.source_file.startswith("td-mdns")
               for fact in result.roster_facts)
    ranks = load_health_manifest().roster_policy.sources
    assert all(fact.source_rank == ranks[fact.field_key][fact.source_file]
               for fact in result.roster_facts)


def test_embedded_mdns_services_do_not_change_original_health_samples(tmp_path, monkeypatch):
    import td_unified_dataset as unified
    from test_td_unified_composition import OMR, _hap_service, _matter_service

    for dataset_id in ("otbr_cli_unified", "otbr_restapi_unified", "ha_matter_ws_unified", "mdns_unified"):
        _seed(tmp_path, dataset_id)
    _save(tmp_path, "td-otbr-cli-networkdiag-fetch-all.json", [{
        "extAddress": "0011223344556677", "omrIpv6Address": OMR, "sourceObservedAt": SOURCE_TIME,
    }])
    _save(tmp_path, "td-mdns-scopes-matter.json", [
        _matter_service(fabric) for fabric in ("1111222233334444", "9999222233334444")
    ])
    _save(tmp_path, "td-mdns-scopes-thread.json", [_hap_service()])
    _save(tmp_path, "td-ha-matter-ws-topology.json", [{
        "extAddress": "0011223344556677", "relationshipOnly": True,
        "sourceObservedAt": SOURCE_TIME,
    }])
    with monkeypatch.context() as legacy:
        legacy.setattr(unified, "BUILDER_CONTRACT", "unified-assembly-v3")
        legacy.setattr(unified, "_embed_mdns_services", lambda rows, *_: rows)
        build_unified_dataset(tmp_path, "multi_source_unified")
        before = process(tmp_path, "multi_source_unified")
    build_unified_dataset(tmp_path, "multi_source_unified")
    after = process(tmp_path, "multi_source_unified")
    assert before.observation.devices == after.observation.devices
    assert before.observation.relationships == after.observation.relationships
    assert before.observation.metrics == after.observation.metrics
    assert before.observation.sources == after.observation.sources
    assert before.assessment.coverage == after.assessment.coverage
    assert before.roster_facts == after.roster_facts


MISSING = "extaddr:8899aabbccddeeff"


def expected(store):
    store.upsert_expected_device(NETWORK, MISSING, "expected", "expected")
    with closing(store._connect()) as connection, connection:
        connection.execute("UPDATE expected_devices SET expected_since='2025-12-01T00:00:00+00:00'")


def roster_history_records(day, count):
    """Supported synthetic raw evidence for opt-in dense performance runs."""
    records = []
    for index in range(count):
        router = index < 32
        record = {
            "extAddress": f"{0x0200000000000000 + index:016x}",
            "rloc16": f"0x{((index if router else (index - 32) % 32) << 10) | (0 if router else index):04x}",
            "deviceLabel": f"Synthetic {index:03d}",
            "role": ("router" if day % 2 else "leader") if router else "child",
            "state": "attached",
            "leaderData": {"partitionId": 1234 + day % 2},
            "mleCounters": {
                "parentChanges": day % 4, "partitionIdChanges": day,
                "betterPartitionAttachAttempts": day + 1,
                "totalParentPartitionChangesCount": day * 2,
            },
            "timeStatistics": {"routerPct": 80.0 + day, "detachedDisabledPct": 0.0},
            "macCounters": {
                "ifTotalPkts": 1000 + day, "ifTotalErrorsTotalPktsRatio": 0.01,
                "ifTotalDiscardsTotalPktsRatio": 0.0,
            },
        }
        if router:
            record["routerId"] = index
            record["routerNeighbors"] = [{
                "extAddress": f"{0x0200000000000000 + (index + step) % 32:016x}",
                "linkQualityIn": step % 4, "linkQualityOut": 3,
                "averageRssi": -50 - step, "lastRssi": -51 - step,
            } for step in range(1, 9)]
            record["childTable"] = [{
                "extAddress": f"{0x0200000000000000 + child:016x}",
                "linkQualityIn": 0, "linkQualityOut": 3,
                "queuedMessageCount": day % 2,
            } for child in range(32 + index, count, 32)]
            record["route64"] = {"id_sequence": day, "route_data": [{
                "route_id": f"0x{(index + step) % 32:02x}", "route_cost": step,
            } for step in range(1, 5)]}
        records.append(record)
    return records


def collection(directory, dataset_id, day, *, positive=False, variant=False, devices=1):
    _seed(directory, dataset_id)
    time = f"2026-01-{day:02d}T00:00:00+00:00"
    epoch = int(datetime.fromisoformat(time).timestamp() * 1_000_000_000)
    for item in _entry(dataset_id)["unified"]["inputs"]:
        path = directory / item["file"]
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        if item["role"] == "records":
            if devices > 1 and dataset_id != "mdns_unified":
                rows = roster_history_records(day, devices)
                if "diagnostics-fetch-all" not in item["file"] and "networkdiag-fetch-all" not in item["file"]:
                    for record in rows:
                        for field in ("mleCounters", "timeStatistics", "macCounters"):
                            record.pop(field)
                payload = {"data": rows} if isinstance(payload, dict) and "data" in payload else rows
            records = payload["data"] if isinstance(payload, dict) and "data" in payload else payload
            for record in records:
                record["sourceObservedAt"] = time
            if positive and "meshdiag-topology" in item["file"]:
                records.append({"extAddress": MISSING.removeprefix("extaddr:"),
                                "sourceObservedAt": time})
            if variant and "networkdiag-fetch-all" in item["file"]:
                records[0]["deviceLabel"] = "different content"
        elif item["role"] == "outcome":
            payload["completedAt"] = time
        _save(directory, item["file"], payload)
        os.utime(path, ns=(epoch, epoch))
    build_unified_dataset(directory, dataset_id)


def missing_finding(result):
    return next(f for f in result.assessment.findings if MISSING in f.device_ids
                and f.rule_id in {"device.missing", "device.offline"})


def roster_history_seed(directory, *, days=3, datasets=None, devices=1):
    """Synthetic cross-source history shared by parity and operation-count checks."""
    datasets = datasets or (
        "ha_matter_ws_unified", "multi_source_otbr_topology_mdns",
        "multi_source_unified", "otbr_cli_diagnostics_fetch", "otbr_cli_topology",
        "otbr_cli_topology_mdns", "otbr_cli_unified",
        "otbr_restapi_devices_diagnostics_fetch", "otbr_restapi_topology",
        "otbr_restapi_topology_mdns", "otbr_restapi_unified",
    )
    store = SQLiteHealthStore(directory / "hobat_v1.db")
    expected(store)
    _save(directory, "td-static-extaddr-device-label.json", [])
    results = {}
    for day in range(1, days + 1):
        for source in ("otbr_cli_unified", "otbr_restapi_unified", "mdns_unified"):
            collection(directory, source, day, devices=devices)
        entry = _seed_ha(directory)
        time = f"2026-01-{day:02d}T00:00:00+00:00"
        for item in entry["unified"]["inputs"]:
            path = directory / item["file"]
            if path.exists():
                payload = path.read_text().replace(SOURCE_TIME, time).replace(
                    "1767225600000", str(int(datetime.fromisoformat(time).timestamp() * 1000)),
                )
                _save(directory, item["file"], json.loads(payload))
        build_unified_dataset(directory, "ha_matter_ws_unified")
        build_unified_dataset(directory, "multi_source_unified")
        for dataset_id in datasets:
            results[dataset_id] = process(directory, dataset_id, store)
    return store, results


def test_prepared_comparison_matches_full_items_and_raw_columns(tmp_path, monkeypatch):
    import td_health_comparison as comparison
    from td_health_sqlite import _encode_comparison_items

    store, _ = roster_history_seed(tmp_path, datasets=("otbr_cli_unified",), devices=2)
    with closing(store._connect()) as connection:
        pair = connection.execute(
            "SELECT before_assessment_id, after_assessment_id FROM comparisons "
            "ORDER BY after_observed_at DESC LIMIT 1",
        ).fetchone()
        endpoints = [store._endpoint(connection, assessment_id) for assessment_id in pair]
        reference = store._derive_pair(connection, *endpoints)
        history = _RetainedHistory(connection, NETWORK)
        cached = [store._endpoint(connection, assessment_id, history=history) for assessment_id in pair]

        def unexpected(*args, **kwargs):
            pytest.fail("A prepared hit repeated static comparison derivation")

        monkeypatch.setattr(comparison, "_derive_metric_comparison_items", unexpected)
        monkeypatch.setattr(comparison, "_derive_relationship_comparison_items", unexpected)
        actual = store._derive_pair(connection, *cached, history=history)
        assert actual == reference
        assert list(_encode_comparison_items(actual[0].comparison_id, actual[1])) == list(
            _encode_comparison_items(reference[0].comparison_id, reference[1])
        )
        assert history.preparation.stats["pair-hit"] == 1
        assert history.preparation.stats["observation-hit"] >= 2
        assert history.preparation.stats["assessment-validated"] >= 2


@pytest.mark.parametrize("damage", ["payload", "network", "native-metric", "native-fact", "context"])
def test_preparation_fails_closed_without_swallowing_corruption(tmp_path, damage):
    from td_health_preparation import PreparationCorruptionError

    store, results = roster_history_seed(tmp_path, days=1, datasets=("otbr_cli_unified",))
    result = results["otbr_cli_unified"]
    with closing(store._connect()) as connection, connection:
        if damage == "payload":
            connection.execute("UPDATE health_observation_preparation SET payload=x'00'")
        elif damage == "network":
            connection.execute("UPDATE health_observation_preparation SET network_id='wrong-network'")
        elif damage == "native-metric":
            connection.execute(
                """INSERT OR REPLACE INTO metric_samples
                   (observation_id, device_id, metric, value, unit, source_file)
                   VALUES (?,?,?,?,?,?)""",
                (result.observation.observation_id, result.observation.devices[0].device_id,
                 "parentChanges", 1.0, "count", result.observation.sources[0].filename),
            )
        elif damage == "native-fact":
            connection.execute("UPDATE device_fact_samples SET value_json='\"changed\"'")
        else:
            context = json.loads(connection.execute(
                "SELECT reproduction_context_json FROM assessments"
            ).fetchone()[0])
            context["unifiedHealth"]["originalEvidenceFingerprint"] = "invalid"
            connection.execute("UPDATE assessments SET reproduction_context_json=?", (json.dumps(context),))
        history = _RetainedHistory(connection, NETWORK)
        with pytest.raises(sqlite3.DatabaseError):
            store._endpoint(connection, result.assessment.assessment_id, history=history)
        if damage != "context":
            witness = result.assessment.reproduction_context["unifiedHealth"]["absenceWitness"]
            with pytest.raises(PreparationCorruptionError):
                store._unified_absences(
                    connection, network_id=NETWORK, witness=witness,
                    expected_records=(), history=_RetainedHistory(connection, NETWORK),
                )


@pytest.mark.parametrize("state", ["missing", "stale"])
def test_preparation_misses_are_query_only_and_explicit(tmp_path, state):
    store, results = roster_history_seed(tmp_path, days=1, datasets=("otbr_cli_unified",))
    with closing(store._connect()) as connection, connection:
        connection.execute(
            "DELETE FROM health_observation_preparation" if state == "missing"
            else "UPDATE health_observation_preparation SET preparation_version='obsolete'"
        )
    readonly = SQLiteHealthStore(store.path, read_only=True)
    with closing(readonly._connect()) as connection:
        before = connection.total_changes
        history = _RetainedHistory(connection, NETWORK)
        actual = store._endpoint(
            connection, results["otbr_cli_unified"].assessment.assessment_id, history=history,
        )
        assert actual[0] == results["otbr_cli_unified"].observation
        assert history.preparation.stats[f"observation-{state}"] == 1
        assert history.preparation.stats["observation-reconstructed"] == 1
        assert connection.total_changes == before


def test_preparation_backfill_is_bounded_resumable_and_read_only_in_preview(tmp_path):
    store, _ = roster_history_seed(tmp_path, days=3, datasets=("otbr_cli_unified",))
    with closing(store._connect()) as connection, connection:
        connection.execute("DELETE FROM health_observation_preparation")
        connection.execute("DELETE FROM health_pair_preparation")
        before = tuple(connection.iterdump())
    report = SQLiteHealthStore(store.path, read_only=True).prepare_history(
        network_id=NETWORK, limit=2, dry_run=True,
    )
    with closing(store._connect()) as connection:
        assert tuple(connection.iterdump()) == before
    assert report["dryRun"] and not report["counters"]
    cursor = None
    reports = []
    for _ in range(10):
        report = store.prepare_history(network_id=NETWORK, limit=2, max_pairs=1, cursor=cursor)
        assert report["counters"].get("observation-published", 0) <= 2
        assert report["counters"].get("pair-published", 0) <= 1
        assert report["counters"].get("observation-hit", 0) + report["counters"].get(
            "observation-reconstructed", 0
        ) <= 2
        reports.append(report)
        cursor = report["nextCursor"]
        if cursor is None:
            break
    assert cursor is None
    assert sum(report["counters"].get("observation-published", 0) for report in reports) == 3
    assert sum(report["counters"].get("pair-published", 0) for report in reports) == 2
    with pytest.raises(ValueError, match="limit at least 2"):
        cursor = None
        for _ in range(5):
            cursor = store.prepare_history(network_id=NETWORK, limit=1, cursor=cursor)["nextCursor"]
    report = store.prepare_history(network_id=NETWORK, limit=1)
    store.upsert_expected_device(NETWORK, MISSING, "changed", "retired")
    with pytest.raises(ValueError, match="stale preparation cursor"):
        store.prepare_history(network_id=NETWORK, limit=1, cursor=report["nextCursor"])
    with pytest.raises(ValueError, match="cursor"):
        store.prepare_history(network_id=NETWORK, cursor="not-a-cursor")


def test_preparation_purge_invalidates_samples_and_rolls_back_preview(tmp_path):
    store, results = roster_history_seed(tmp_path, datasets=("otbr_cli_unified",))
    device_id = results["otbr_cli_unified"].observation.devices[0].device_id
    with closing(store._connect()) as connection:
        before = tuple(connection.iterdump())
    store.purge_device(device_id, network_id=NETWORK, dry_run=True)
    with closing(store._connect()) as connection:
        assert tuple(connection.iterdump()) == before
    store.purge_device(device_id, network_id=NETWORK)
    with closing(store._connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM health_observation_preparation").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM health_pair_preparation").fetchone()[0] == 0
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_preparation_caps_and_observation_cascade(tmp_path, monkeypatch):
    import td_health_preparation as preparation

    store, _ = roster_history_seed(tmp_path, datasets=("otbr_cli_unified",))
    with closing(store._connect()) as connection, connection:
        monkeypatch.setattr(preparation, "MAX_RECORDS", 1)
        cache = preparation.Preparation(connection, NETWORK)
        cache.trim()
        assert connection.execute("SELECT COUNT(*) FROM health_observation_preparation").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM health_pair_preparation").fetchone()[0] == 1
        monkeypatch.setattr(preparation, "MAX_PAYLOAD_BYTES", 1)
        cache.trim()
        assert cache.stats["budget-eviction"] >= 2
        assert connection.execute("SELECT COUNT(*) FROM health_observation_preparation").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM health_pair_preparation").fetchone()[0] == 0
    monkeypatch.undo()
    store.prepare_history(network_id=NETWORK)
    with closing(store._connect()) as connection, connection:
        connection.execute("DELETE FROM observations")
        assert connection.execute("SELECT COUNT(*) FROM health_observation_preparation").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM health_pair_preparation").fetchone()[0] == 0


def test_prepared_roster_failure_after_item_prefix_rolls_back_every_write(tmp_path, monkeypatch):
    import td_health_sqlite

    store, _ = roster_history_seed(tmp_path, datasets=("otbr_cli_unified",), devices=2)
    with closing(store._connect()) as connection:
        before = tuple(connection.iterdump())
    encode = td_health_sqlite._encode_comparison_items

    def fail_after_prefix(comparison_id, items):
        iterator = encode(comparison_id, items)
        yield next(iterator)
        raise RuntimeError("injected after nonempty comparison prefix")

    monkeypatch.setattr(td_health_sqlite, "_encode_comparison_items", fail_after_prefix)
    with pytest.raises(RuntimeError, match="nonempty comparison prefix"):
        store.upsert_expected_device(NETWORK, MISSING, "retired", "retired")
    assert store.preparation_stats["pair-hit"] >= 1
    with closing(store._connect()) as connection:
        assert tuple(connection.iterdump()) == before
    monkeypatch.undo()
    store.upsert_expected_device(NETWORK, MISSING, "retired", "retired")
    assert store.preparation_stats["pair-hit"] >= 1


def test_preparation_skips_orphan_pairs_and_detects_changed_pair_inventory(tmp_path):
    store, _ = roster_history_seed(tmp_path, datasets=("otbr_cli_unified",))
    report = store.prepare_history(network_id=NETWORK, limit=1)
    with closing(store._connect()) as connection:
        ids = connection.execute(
            """SELECT a.assessment_id FROM assessments a JOIN observations o USING(observation_id)
               ORDER BY o.observed_at"""
        ).fetchall()
    assert store.compare_assessments(ids[0][0], ids[-1][0])[2]
    with pytest.raises(ValueError, match="stale preparation cursor"):
        store.prepare_history(network_id=NETWORK, cursor=report["nextCursor"])
    with closing(store._connect()) as connection, connection:
        connection.execute("DELETE FROM observations WHERE observed_at LIKE '2026-01-01%'")
    report = store.prepare_history(network_id=NETWORK)
    assert report["ineligiblePairs"] == 2
    assert report["nextCursor"] is None


@pytest.mark.usefixtures("archived_health_catalog")
def test_roster_reassessment_only_inserts_assessments_not_sample_history(tmp_path):
    store, results = roster_history_seed(tmp_path)
    with closing(store._connect()) as connection:
        before = {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in ("observations", "observation_sources", "device_samples",
                          "relationship_samples", "metric_samples")
        }
        assessments = connection.execute("SELECT COUNT(*) FROM assessments").fetchone()[0]
        comparisons = connection.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0]
    store.upsert_expected_device(NETWORK, MISSING, "changed", "expected")
    with closing(store._connect()) as connection:
        assert before == {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in before
        }
        assert connection.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == assessments + len(results)
        assert connection.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] > comparisons


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.usefixtures("archived_health_catalog")
def test_roster_reassessment_matches_full_evaluator_for_every_current_dataset(
    tmp_path, monkeypatch, reverse,
):
    import td_health_evaluator as evaluator

    datasets = (
        "ha_matter_ws_unified", "multi_source_otbr_topology_mdns",
        "multi_source_unified", "otbr_cli_diagnostics_fetch", "otbr_cli_topology",
        "otbr_cli_topology_mdns", "otbr_cli_unified",
        "otbr_restapi_devices_diagnostics_fetch", "otbr_restapi_topology",
        "otbr_restapi_topology_mdns", "otbr_restapi_unified",
    )
    store, _ = roster_history_seed(
        tmp_path, datasets=tuple(reversed(datasets)) if reverse else datasets,
    )
    evaluate = evaluator.evaluate_observation
    checked = []

    def oracle(observation, policy, **kwargs):
        retained = kwargs["retained_assessment"]
        full = evaluate(observation, policy, **{**kwargs, "retained_assessment": None})
        findings = tuple(sorted(
            list(retained.findings) + [
                finding for finding in full.findings
                if finding.rule_id in evaluator.ROSTER_REASSESSMENT_RULE_IDS
            ],
            key=lambda finding: (-int(finding.rank), finding.finding_id),
        ))
        status, confidence = evaluator.aggregate_assessment_state(
            findings, completeness=observation.completeness,
            device_count=len(observation.devices),
            observed_pillars=full.coverage["observedPillars"],
            evaluation_inputs=kwargs["evaluation_inputs"],
        )
        expected = replace(full, findings=findings, status=status, confidence=confidence)
        actual = evaluate(observation, policy, **kwargs)
        assert actual == expected
        checked.append(observation.dataset_id)
        return actual

    monkeypatch.setattr(evaluator, "evaluate_observation", oracle)
    for state in ("retired", "expected"):
        store.upsert_expected_device(NETWORK, MISSING, f"oracle-{state}", state)
    assert Counter(checked) == Counter({dataset_id: 2 for dataset_id in datasets})


def _shared_history_scan(statement):
    sql = " ".join(statement.lower().split())
    if not sql.startswith("select ") or "where o.network_id=" not in sql:
        return None
    if "and a.assessment_id=" in sql:
        return None
    if "from observations o join assessments a using(observation_id)" in sql:
        return "inventory"
    for table in ("observation_sources", "device_samples", "relationship_samples", "metric_samples"):
        if f"from {table} s join " in sql:
            return table
    return None


@contextmanager
def _history_trace(connection):
    counts = Counter()
    statements = []

    def trace(statement):
        statements.append(statement)
        kind = _shared_history_scan(statement)
        if kind:
            counts[kind] += 1

    connection.set_trace_callback(trace)
    try:
        yield counts, statements
    finally:
        connection.set_trace_callback(None)


def test_roster_history_trace_classifier():
    assert _shared_history_scan(
        "SELECT o.*, a.* FROM observations o JOIN assessments a USING(observation_id) WHERE o.network_id='n'"
    ) == "inventory"
    for table in ("observation_sources", "device_samples", "relationship_samples", "metric_samples"):
        assert _shared_history_scan(
            f"SELECT s.* FROM {table} s JOIN observations o USING(observation_id) WHERE o.network_id='n'"
        ) == table
    for sql in (
        "SELECT * FROM device_samples WHERE observation_id='o'",
        "SELECT o.*, a.* FROM observations o JOIN assessments a USING(observation_id) "
        "WHERE o.network_id='n' AND a.assessment_id='a'",
        "SELECT * FROM current_assessments WHERE network_id='n'",
        "UPDATE assessments SET status='good'",
    ):
        assert _shared_history_scan(sql) is None


def _retained_row(connection, assessment_id):
    return connection.execute(
        "SELECT o.*, a.* FROM observations o JOIN assessments a USING(observation_id) WHERE a.assessment_id=?",
        (assessment_id,),
    ).fetchone()


@pytest.mark.usefixtures("archived_health_catalog")
def test_roster_history_reuses_bodies_and_bounds_shared_queries(tmp_path, monkeypatch):
    store, results = roster_history_seed(tmp_path)
    store.upsert_expected_device(NETWORK, MISSING, "duplicate assessments", "expected")
    with closing(store._connect()) as connection, connection:
        connection.execute("DELETE FROM health_observation_preparation")
        connection.execute("DELETE FROM health_pair_preparation")
    builds, validations, owners = Counter(), Counter(), []
    reconstruct = store._reconstruct_retained_samples
    validate = store._validate_retained_assessment_context

    def build(connection, row, dataset, *, history=None):
        assert history is not None
        if not owners:
            owners.append(history)
        assert history is owners[0]
        builds[(row["observation_id"], row["sample_contract_version"], history.contract_slot(dataset))] += 1
        return reconstruct(connection, row, dataset, history=history)

    def check(row, dataset, context, observation, **kwargs):
        validations[row["assessment_id"]] += 1
        return validate(row, dataset, context, observation, **kwargs)

    monkeypatch.setattr(SQLiteHealthStore, "_reconstruct_retained_samples", staticmethod(build))
    monkeypatch.setattr(SQLiteHealthStore, "_validate_retained_assessment_context", staticmethod(check))
    with closing(store._connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE network_roster_revisions SET revision=revision+1 WHERE network_id=?", (NETWORK,),
        )
        with _history_trace(connection) as (counts, statements):
            revisions = store._reassess_network(connection, NETWORK)
        assert len(revisions) == len(results)
        assert set(builds.values()) == {1}
        assert len(builds) < sum(validations.values())
        assert set(validations) >= {item["assessmentId"] for item in revisions}
        assert counts == Counter({
            "inventory": 1, "observation_sources": 1, "device_samples": 1,
            "relationship_samples": 1, "metric_samples": 1,
        })
        registrations = [s for s in statements if "WHERE o.network_id=" in s and "AND a.assessment_id=" in s]
        assert len(registrations) == len(results) - 1  # HA's null witness is still lazy.


@pytest.mark.parametrize("file_first", [False, True])
@pytest.mark.parametrize("prepared_first", [False, True])
def test_roster_history_keeps_contract_admission_and_complete_identity_separate(
    tmp_path, monkeypatch, file_first, prepared_first,
):
    from td_health_manifest_history import ManifestHistoryResolver

    store, results = roster_history_seed(
        tmp_path, days=1, datasets=("otbr_cli_unified", "otbr_restapi_unified"),
    )
    result = results["otbr_cli_unified"]
    dataset = load_health_manifest().dataset("otbr_cli_unified")
    historical = replace(dataset, health_profile=replace(dataset.health_profile, topology_authority=False))
    matching = ManifestHistoryResolver.matching_candidates

    def candidates(resolver, *args):
        admitted = matching(resolver, *args)
        if args == (dataset.dataset_id, dataset.datasource_id, dataset.health_profile.profile_id,
                    "comparison-v1-unified"):
            return (*admitted, replace(admitted[0], dataset=historical))
        return admitted

    monkeypatch.setattr(ManifestHistoryResolver, "matching_candidates", candidates)
    with closing(store._connect()) as connection, connection:
        current = _retained_row(connection, result.assessment.assessment_id)
        context = json.loads(current["reproduction_context_json"])
        context["healthProfile"]["topologyAuthority"] = False
        sibling = replace(
            result.assessment, assessment_id="assessment:historical-sibling",
            policy_digest="synthetic-historical-policy", reproduction_context=context,
        )
        assert store._insert_assessment(connection, sibling)
        row = _retained_row(connection, sibling.assessment_id)
        history = _RetainedHistory(connection, NETWORK)
        if prepared_first:
            assert store._retained_observation(
                connection, current, source_dataset=dataset, history=history,
            ) == result.observation
            assert current["observation_id"] in history._released_samples["device_samples"]

        def admitted():
            return store._retained_observation(connection, row, history=history)

        def rejected():
            with pytest.raises(sqlite3.DatabaseError, match="recipe/profile"):
                store._retained_observation(connection, row, source_dataset=dataset, history=history)

        if file_first:
            rejected()
            admitted()
        else:
            admitted()
            rejected()
        assert store._retained_observation(
            connection, current, source_dataset=dataset, history=history,
        ) == result.observation
        assert history.contracts == ([dataset, historical] if prepared_first else [historical, dataset])
        assert len(history.bodies) == 2
        assert store._retained_observation(connection, row, history=history) == result.observation
        for dataset_id in ("otbr_cli_unified", "otbr_restapi_unified"):
            witness = results[dataset_id].assessment.reproduction_context["unifiedHealth"]["absenceWitness"]
            for file_mode in (True, False):
                args = dict(network_id=NETWORK, witness=witness, expected_records=(), file_mode=file_mode)
                assert store._unified_absences(connection, **args, history=history) == (
                    store._unified_absences(connection, **args)
                )


def test_roster_history_admissions_decode_once_and_prepare_once(tmp_path, monkeypatch):
    import td_health_unified

    store, results = roster_history_seed(tmp_path, days=2, datasets=("otbr_cli_unified",))
    dataset = load_health_manifest().dataset("otbr_cli_unified")
    loads, prepares = Counter(), []
    decode, prepare = json.loads, td_health_unified._prepare_contract

    def counted_decode(raw, *args, **kwargs):
        if isinstance(raw, str) and '"unifiedHealth"' in raw:
            loads[raw] += 1
        return decode(raw, *args, **kwargs)

    def counted_prepare(contract):
        prepares.append(contract)
        return prepare(contract)

    with closing(store._connect()) as connection:
        rows = connection.execute(
            "SELECT o.*, a.* FROM observations o JOIN assessments a USING(observation_id)",
        ).fetchall()
        history = _RetainedHistory(connection, NETWORK)
        monkeypatch.setattr(json, "loads", counted_decode)
        monkeypatch.setattr(td_health_unified, "_prepare_contract", counted_prepare)
        for _ in range(3):
            for row in rows:
                for selected in (None, dataset, replace(dataset)):
                    store._retained_observation(
                        connection, row, source_dataset=selected, history=history,
                    )
        witness = results["otbr_cli_unified"].assessment.reproduction_context["unifiedHealth"]["absenceWitness"]
        for domain in ("otbr-cli", "otbr-restapi"):
            for file_mode in (True, False):
                store._qualified_absence_groups(history, domain=domain, file_mode=file_mode)
        assert sum(loads.values()) == 2 * len(rows)
        assert prepares == [dataset]
        assert len(history.contracts) == len(history.prepared_contracts) == 1
        assert all(len(entries) == 2 for entries in history.admissions.values())
        assert all(isinstance(entry.context["unifiedHealth"]["positiveDeviceIds"], list)
                   for entries in history.admissions.values() for entry in entries)
        assert set(history.admissions) == {row["assessment_id"] for row in rows}


@pytest.mark.usefixtures("archived_health_catalog")
def test_roster_history_resolves_each_full_contract_once_per_invocation(tmp_path, monkeypatch):
    from td_health_manifest_history import ManifestHistoryResolver

    store, _ = roster_history_seed(
        tmp_path, days=2, datasets=("otbr_cli_diagnostics_fetch", "otbr_cli_unified"),
    )
    matching = ManifestHistoryResolver.matching_candidates
    calls = Counter()

    def counted(resolver, *args):
        calls[args] += 1
        return matching(resolver, *args)

    monkeypatch.setattr(ManifestHistoryResolver, "matching_candidates", counted)
    with closing(store._connect()) as connection:
        for invocation in (1, 2):
            history = _RetainedHistory(connection, NETWORK)
            for _ in range(2):
                for domain in ("otbr-cli", "otbr-restapi"):
                    for file_mode in (False, True):
                        store._qualified_absence_groups(history, domain=domain, file_mode=file_mode)
            assert calls and set(calls.values()) == {invocation}
            assert history.preparation.stats["assessment-validated"] >= len(history.rows)


def test_unified_prepared_contract_binding_and_mapping_protocol(tmp_path):
    from collections import UserDict
    from types import MappingProxyType
    from td_health_unified import _prepare_contract, digest, freeze, plain, validate_context

    store, results = roster_history_seed(tmp_path, days=1, datasets=("otbr_cli_unified",))
    result = results["otbr_cli_unified"]
    dataset = load_health_manifest().dataset("otbr_cli_unified")
    prepared = _prepare_contract(dataset)
    context = result.assessment.reproduction_context
    assert validate_context(context, dataset, result.observation, prepared=prepared) == (
        validate_context(context, dataset, result.observation)
    )
    different = replace(dataset, health_profile=replace(dataset.health_profile, topology_authority=False))
    with pytest.raises(ValueError, match="Prepared Unified contract"):
        validate_context(context, different, result.observation, prepared=prepared)
    value = {"outer": [{"inner": [False, 0, None, "escaped\ntext"]}]}
    for mapping in (value, MappingProxyType(value), UserDict(value), freeze(value)):
        assert plain(mapping) == value
        assert digest(mapping) == digest(value)
        assert plain(freeze(mapping)) == value


@pytest.mark.parametrize("field", ["recipe", "originalEvidenceFingerprint", "effectiveCoverage",
                                  "coverage", "restDiagnostics", "absenceWitness"])
def test_roster_history_does_not_hide_invalid_assessment_context(tmp_path, field):
    store, results = roster_history_seed(tmp_path, days=1, datasets=("otbr_restapi_unified",))
    result = results["otbr_restapi_unified"]
    with closing(store._connect()) as connection, connection:
        good = _retained_row(connection, result.assessment.assessment_id)
        context = json.loads(good["reproduction_context_json"])
        coverage = json.loads(good["coverage_json"])
        if field == "coverage":
            coverage["restChildTableCoverage"] = {"invalid": True}
        elif field == "restDiagnostics":
            context["restDiagnostics"] = {"invalid": True}
        else:
            context["unifiedHealth"][field] = {}
        sibling = replace(
            result.assessment, assessment_id="assessment:invalid-sibling",
            policy_digest="synthetic-sibling-policy",
            coverage=coverage, reproduction_context=context,
        )
        assert store._insert_assessment(connection, sibling)
        bad = _retained_row(connection, sibling.assessment_id)
        history = _RetainedHistory(connection, NETWORK)
        assert store._retained_observation(connection, good, history=history) == result.observation
        with pytest.raises((sqlite3.DatabaseError, ValueError)):
            store._retained_observation(connection, bad, history=history)
        assert sibling.assessment_id not in history.admissions
        assert all(key[0] != sibling.assessment_id for key in history.validated_rows)
        args = dict(network_id=NETWORK,
                    witness=result.assessment.reproduction_context["unifiedHealth"]["absenceWitness"],
                    expected_records=())
        assert store._unified_absences(connection, **args, history=history) == store._unified_absences(connection, **args)
        connection.execute(
            "UPDATE current_assessments SET assessment_id=? WHERE dataset_id='otbr_restapi_unified'",
            (sibling.assessment_id,),
        )
        with pytest.raises((sqlite3.DatabaseError, ValueError)):
            store._reassess_network(connection, NETWORK)


@pytest.mark.usefixtures("archived_health_catalog")
def test_roster_history_registers_before_nested_comparison_and_advances_each_group(tmp_path, monkeypatch):
    store, results = roster_history_seed(tmp_path, days=3)
    derive, compare = store._derive_pair, store._auto_compare
    nested, owners = [], []

    def assert_visible(connection, *, history):
        if not owners:
            owners.append(history)
        assert history is owners[0]
        for dataset_id in ("otbr_cli_unified", "otbr_restapi_unified"):
            witness = results[dataset_id].assessment.reproduction_context["unifiedHealth"]["absenceWitness"]
            for file_mode in (True, False):
                args = dict(network_id=NETWORK, witness=witness, expected_records=(), file_mode=file_mode)
                assert store._unified_absences(connection, **args, history=history) == (
                    store._unified_absences(connection, **args)
                )
                assert history.groups[(witness["domain"], file_mode)].offset == len(history.rows)

    def auto(connection, observation, assessment, *, history=None, **kwargs):
        assert history is not None
        assert_visible(connection, history=history)
        assert assessment.assessment_id in {row["assessment_id"] for row in history.rows}
        return compare(connection, observation, assessment, history=history, **kwargs)

    def pair(connection, before, after, *, history=None):
        assert history is not None
        assert_visible(connection, history=history)
        nested.append(after[1].assessment_id)
        return derive(connection, before, after, history=history)

    monkeypatch.setattr(SQLiteHealthStore, "_auto_compare", staticmethod(auto))
    monkeypatch.setattr(SQLiteHealthStore, "_derive_pair", staticmethod(pair))
    store.upsert_expected_device(NETWORK, MISSING, "new revision", "expected")
    assert nested
    assert len({row["assessment_id"] for row in owners[0].rows}) == len(owners[0].rows)


def test_roster_history_no_witness_is_lazy_and_query_only(tmp_path):
    store, results = roster_history_seed(tmp_path, days=1, datasets=("otbr_cli_unified",))
    with closing(SQLiteHealthStore(store.path, read_only=True)._connect()) as connection:
        history = _RetainedHistory(connection, NETWORK)
        with _history_trace(connection) as (counts, statements):
            assert store._unified_absences(
                connection, network_id=NETWORK, witness=None, expected_records=(), history=history,
            ) == ({}, False, frozenset())
        assert not statements and not counts
        witness = results["otbr_cli_unified"].assessment.reproduction_context["unifiedHealth"]["absenceWitness"]
        args = dict(network_id=NETWORK, witness=witness, expected_records=())
        assert store._unified_absences(connection, **args, history=history) == store._unified_absences(connection, **args)
        other = _RetainedHistory(connection, "extpan:ffffffffffffffff")
        assert not other.rows
        assert all(not other.samples(table, results["otbr_cli_unified"].observation.observation_id)
                   for table in ("observation_sources", "device_samples", "relationship_samples", "metric_samples"))


def test_roster_history_is_local_to_network_and_consecutive_cli_actions(tmp_path, monkeypatch):
    import test_td_unified_dataset as fixtures

    store, _ = roster_history_seed(tmp_path, days=1, datasets=("otbr_cli_unified",))
    other_network = "extpan:ffffffffffffffff"
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    save = fixtures._save

    def scoped_save(directory, filename, payload, **kwargs):
        return save(directory, filename, payload, scope=other_network)

    with monkeypatch.context() as scoped:
        scoped.setattr(fixtures, "NETWORK", other_network)
        scoped.setattr(fixtures, "_save", scoped_save)
        seed(other_dir, "otbr_cli_unified")
        other_result = process(other_dir, "otbr_cli_unified", store)
    assert other_result.observation.network_id == other_network

    def other_rows():
        with closing(store._connect()) as connection:
            result = {}
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                table = row["name"]
                columns = {item["name"] for item in connection.execute(f'PRAGMA table_info("{table}")')}
                column, value = (
                    ("network_id", other_network) if "network_id" in columns
                    else ("observation_id", other_result.observation.observation_id)
                )
                if column in columns:
                    result[table] = sorted(
                        (tuple(item) for item in connection.execute(
                            f'SELECT * FROM "{table}" WHERE {column}=?', (value,),
                        )), key=repr,
                    )
            return result

    before = other_rows()
    owners = []
    initialize = _RetainedHistory.__init__

    def capture(history, connection, network_id):
        initialize(history, connection, network_id)
        owners.append(history)

    monkeypatch.setattr(_RetainedHistory, "__init__", capture)
    store.upsert_expected_device(NETWORK, MISSING, "first changed action", "expected")
    store.upsert_expected_device(NETWORK, MISSING, "second changed action", "expected")
    assert len(owners) == 2 and owners[0] is not owners[1]
    assert owners[0].bodies is not owners[1].bodies
    assert all(row["network_id"] == NETWORK for owner in owners for row in owner.rows)
    assert other_rows() == before


@pytest.mark.usefixtures("archived_health_catalog")
def test_original_and_unified_same_collection_count_once_in_current_and_reassessment(tmp_path):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    for day in (1, 2, 3):
        collection(tmp_path, "otbr_cli_unified", day)
        process(tmp_path, "otbr_cli_topology", store)
        result = process(tmp_path, "otbr_cli_unified", store)
        finding = missing_finding(result)
        assert finding.evidence["consecutiveCompleteAbsences"] == day
        assert finding.rule_id == (
            "device.offline" if day >= load_health_policy().offline_consecutive_complete_observations
            else "device.missing"
        )
    # A roster-only reassessment uses retained witnesses, not the current cache.
    for path in tmp_path.glob("*.json"):
        path.unlink()
    store.upsert_expected_device(NETWORK, MISSING, "renamed", "expected")
    with closing(store._connect()) as connection:
        current = connection.execute(
            "SELECT assessment_id FROM current_assessments WHERE dataset_id='otbr_cli_unified'"
        ).fetchone()
        context = json.loads(connection.execute(
            "SELECT reproduction_context_json FROM assessments WHERE assessment_id=?",
            (current["assessment_id"],),
        ).fetchone()[0])
    assert context["priorCompleteAbsences"][MISSING] == 2
    assert context["unifiedHealth"]["absenceWitness"]["domain"] == "otbr-cli"


@pytest.mark.usefixtures("archived_health_catalog")
def test_same_witness_positive_projection_overrides_current_negative(tmp_path):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    for day in (1, 2):
        collection(tmp_path, "otbr_cli_unified", day)
        process(tmp_path, "otbr_cli_unified", store)
    collection(tmp_path, "otbr_cli_unified", 3, positive=True)
    process(tmp_path, "otbr_cli_topology", store)
    collection(tmp_path, "otbr_cli_unified", 3)
    result = process(tmp_path, "otbr_cli_unified", store)
    finding = missing_finding(result)
    assert finding.rule_id == "device.missing"
    assert finding.evidence["consecutiveCompleteAbsences"] == 0
    assert result.assessment.reproduction_context["unifiedHealth"]["positiveDeviceIds"] == [MISSING]


def test_different_witnesses_at_same_time_are_unavailable_not_consecutive(tmp_path):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    collection(tmp_path, "otbr_cli_unified", 1)
    process(tmp_path, "otbr_cli_unified", store)
    collection(tmp_path, "otbr_cli_unified", 1, variant=True)
    result = process(tmp_path, "otbr_cli_unified", store)
    assert result.assessment.reproduction_context["evaluationInputs"]["domains"]["absenceHistory"]["state"] == "unavailable"
    assert missing_finding(result).rule_id == "device.missing"


def test_never_stitch_cli_and_rest_absence_domains(tmp_path):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    for day in (1, 2):
        collection(tmp_path, "otbr_cli_unified", day)
        process(tmp_path, "otbr_cli_unified", store)
    collection(tmp_path, "otbr_restapi_unified", 3)
    result = process(tmp_path, "otbr_restapi_unified", store)
    assert missing_finding(result).evidence["consecutiveCompleteAbsences"] == 1


@pytest.mark.usefixtures("archived_health_catalog")
def test_file_mode_deduplicates_reclassified_collection_and_counts_later_one(tmp_path):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    collection(tmp_path, "otbr_cli_unified", 1)
    first = process(tmp_path, "otbr_cli_diagnostics_fetch", store)
    assert missing_finding(first).evidence["consecutiveCompleteAbsences"] == 1

    identity = tmp_path / "td-otbr-cli-thread-network-info.json"
    payload = json.loads(identity.read_text())
    payload["networkName"] = "renamed"
    _save(tmp_path, identity.name, payload)
    reclassified = process(tmp_path, "otbr_cli_diagnostics_fetch", store)
    assert reclassified.observation.observation_id != first.observation.observation_id
    assert missing_finding(reclassified).evidence["consecutiveCompleteAbsences"] == 1
    repeated = process(tmp_path, "otbr_cli_diagnostics_fetch", store)
    assert not repeated.observation_created
    assert not repeated.assessment_created
    assert repeated.assessment.assessment_id == reclassified.assessment.assessment_id

    collection(tmp_path, "otbr_cli_unified", 2)
    later = process(tmp_path, "otbr_cli_diagnostics_fetch", store)
    assert missing_finding(later).evidence["consecutiveCompleteAbsences"] == 2
    assert missing_finding(later).rule_id == "device.offline"


@pytest.mark.usefixtures("archived_health_catalog")
def test_file_mode_never_stitches_cli_and_rest_absence_domains(tmp_path):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    for day in (1, 2):
        collection(tmp_path, "otbr_cli_unified", day)
        process(tmp_path, "otbr_cli_diagnostics_fetch", store)
    collection(tmp_path, "otbr_restapi_unified", 3)
    result = process(tmp_path, "otbr_restapi_devices_diagnostics_fetch", store)
    assert missing_finding(result).evidence["consecutiveCompleteAbsences"] == 1


def test_unified_builder_upgrade_does_not_count_one_collection_twice(tmp_path, monkeypatch):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    collection(tmp_path, "otbr_cli_unified", 1)
    with monkeypatch.context() as legacy:
        legacy.setattr("td_unified_dataset.BUILDER_CONTRACT", "unified-assembly-v9")
        build_unified_dataset(tmp_path, "otbr_cli_unified")
        first = process(tmp_path, "otbr_cli_unified", store)
    build_unified_dataset(tmp_path, "otbr_cli_unified")
    upgraded = process(tmp_path, "otbr_cli_unified", store)
    assert first.observation.observation_id != upgraded.observation.observation_id
    assert missing_finding(upgraded).evidence["consecutiveCompleteAbsences"] == 1


@pytest.mark.usefixtures("archived_health_catalog")
def test_label_map_rows_are_not_presence_evidence_for_same_witness_absence(tmp_path):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    collection(tmp_path, "otbr_cli_unified", 1)
    for item in ("otbr_restapi_unified", "mdns_unified"):
        _seed(tmp_path, item)
    _save(tmp_path, "td-static-extaddr-device-label.json", [
        {"extAddress": MISSING.removeprefix("extaddr:"), "deviceLabel": "labelled only"},
    ])
    merged = process(tmp_path, "multi_source_otbr_topology_mdns", store)
    assert MISSING not in {device.device_id for device in merged.observation.devices}
    assert missing_finding(merged).rule_id == "device.missing"
    result = process(tmp_path, "otbr_cli_topology", store)
    domains = result.assessment.reproduction_context["evaluationInputs"]["domains"]
    assert domains["absenceHistory"]["state"] == "available"


@pytest.mark.usefixtures("archived_health_catalog")
def test_file_mode_roster_change_reassesses_when_absence_history_is_unavailable(tmp_path):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    collection(tmp_path, "otbr_cli_unified", 1)
    process(tmp_path, "otbr_cli_topology", store)
    collection(tmp_path, "otbr_cli_unified", 1, variant=True)
    result = process(tmp_path, "otbr_cli_topology", store)
    domains = result.assessment.reproduction_context["evaluationInputs"]["domains"]
    assert domains["absenceHistory"]["state"] == "unavailable"
    store.upsert_expected_device(NETWORK, MISSING, None, "intentionally-offline")
    with closing(store._connect()) as connection:
        row = connection.execute(
            """SELECT a.network_roster_revision, a.reproduction_context_json
               FROM current_assessments c JOIN assessments a USING (assessment_id)
               WHERE c.dataset_id='otbr_cli_topology'""",
        ).fetchone()
    assert row["network_roster_revision"] > result.assessment.network_roster_revision
    records = json.loads(row["reproduction_context_json"])["rosterContext"]["records"]
    assert {r["deviceId"]: r["rosterState"] for r in records}[MISSING] == "intentionally-offline"


def test_ha_roster_reassessment_keeps_absence_unknown(tmp_path):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    seed(tmp_path, "ha_matter_ws_unified")
    result = process(tmp_path, "ha_matter_ws_unified", store)
    store.upsert_expected_device(NETWORK, MISSING, "renamed", "expected")
    assert missing_finding(result).rule_id == "device.missing"


@pytest.mark.parametrize("dataset_id", IDS)
def test_backup_restore_preserves_retained_original_closure_without_raw_cache(tmp_path, dataset_id):
    from td_system_backups import create_backup, restore_backup, validate_backup
    data = tmp_path / "data"
    data.mkdir()
    seed(data, dataset_id)
    store = SQLiteHealthStore(data / "hobat_v1.db")
    result = process(data, dataset_id, store)
    # Retained assessment readers/replay need no current raw files.
    for path in data.glob("*.json"):
        path.unlink()
    backup = tmp_path / "backup"
    create_backup(data, backup)
    validate_backup(backup)
    restored = tmp_path / "restored"
    restore_backup(restored, backup)
    reopened = SQLiteHealthStore(restored / "hobat_v1.db")
    with closing(reopened._connect()) as connection:
        endpoint = reopened._endpoint(connection, result.assessment.assessment_id)
    assert endpoint[0] == result.observation


@pytest.mark.parametrize("measured", [False, True])
def test_native_thread_measurements_preserve_zero_without_inventing_qualitative_samples(tmp_path, measured):
    _seed_ha(tmp_path)
    filename = "td-ha-matter-ws-network-topology.json"
    payload = json.loads((tmp_path / filename).read_text())
    graph = payload["topology"]
    graph["nodes"][1] = {
        "id": "second-router", "kind": "matter", "network_type": "thread",
        "ext_address": "8899aabbccddeeff", "ext_pan_id": NETWORK[7:], "role": "router",
    }
    link = {"source": "native-router", "target": "second-router",
            "network": "thread", "strength": "strong"}
    if measured:
        link.update(source_to_target={"strength": "strong", "lqi": 0},
                    target_to_source={"strength": "medium", "lqi": 2, "rssi": -70})
    graph["connections"] = [link]
    _save(tmp_path, filename, payload)
    build_unified_dataset(tmp_path, "ha_matter_ws_unified")
    result = process(tmp_path, "ha_matter_ws_unified")
    native = [link for link in result.observation.relationships if filename in link.source_files]
    if measured:
        assert len(native) == 2
        forward = next(link for link in native if link.from_device_id == "extaddr:0011223344556677")
        assert (forward.link_quality_out, forward.link_quality_in, forward.last_rssi) == (0, 2, -70)
    else:
        assert native == []


@pytest.mark.parametrize("field", ["recipe", "originalEvidenceFingerprint", "effectiveCoverage", "absenceWitness"])
def test_retained_context_corruption_is_rejected_without_using_current_cache(tmp_path, field):
    seed(tmp_path, "otbr_cli_unified")
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    result = process(tmp_path, "otbr_cli_unified", store)
    with closing(store._connect()) as connection, connection:
        row = connection.execute(
            "SELECT reproduction_context_json FROM assessments WHERE assessment_id=?",
            (result.assessment.assessment_id,),
        ).fetchone()
        context = json.loads(row[0])
        context["unifiedHealth"][field] = {}
        connection.execute(
            "UPDATE assessments SET reproduction_context_json=? WHERE assessment_id=?",
            (json.dumps(context), result.assessment.assessment_id),
        )
        import sqlite3
        with pytest.raises((sqlite3.DatabaseError, ValueError)):
            store._endpoint(connection, result.assessment.assessment_id)


def test_optional_evidence_and_rebuilt_transport_timestamps_do_not_create_absence_witness(tmp_path):
    seed(tmp_path, "otbr_cli_unified")
    first = process(tmp_path, "otbr_cli_unified")
    _save(tmp_path, "td-otbr-cli-router-table.json", [{"extAddress": "0011223344556677",
                                                     "deviceLabel": "new optional evidence"}])
    build_unified_dataset(tmp_path, "otbr_cli_unified")
    second = process(tmp_path, "otbr_cli_unified")
    assert first.assessment.reproduction_context["unifiedHealth"]["absenceWitness"] == (
        second.assessment.reproduction_context["unifiedHealth"]["absenceWitness"])


def test_roster_allowlist_rejects_identity_service_and_aggregate_authority():
    from td_health_roster import extract_roster_facts
    dataset = load_health_manifest().dataset("multi_source_unified")
    for filename in ("td-merged-unified.json", "td-mdns-scopes-meshcop.json",
                     "td-otbr-cli-thread-network-info.json"):
        with pytest.raises(ValueError, match="allowlist"):
            extract_roster_facts(
                {"extAddress": "0011223344556677"}, filename=filename, dataset=dataset,
                policy=load_health_manifest().roster_policy, evidence_files=frozenset({filename}),
            )


def test_newer_checkpoint_requires_partial_opt_in_and_never_qualifies_absence(tmp_path):
    seed(tmp_path, "otbr_cli_unified")
    (tmp_path / "td-otbr-cli-networkdiag-fetch-all.partial.json").write_text("[]")
    with pytest.raises(HealthProcessingError, match="allow-partial"):
        process(tmp_path, "otbr_cli_unified")
    result = process(tmp_path, "otbr_cli_unified", allow_partial=True)
    assert result.observation.completeness.value == "partial"
    assert result.assessment.reproduction_context["unifiedHealth"]["absenceWitness"] is None


def test_failed_original_table_attempt_truthfully_reduces_runtime_health_coverage(tmp_path):
    _seed(tmp_path, "otbr_cli_unified")
    _save(tmp_path, "td-otbr-cli-meshdiag-router-childtables.json", [
        {"extAddress": "0011223344556677", "tableAttempt": {"status": "timeout"},
         "sourceObservedAt": SOURCE_TIME},
    ])
    build_unified_dataset(tmp_path, "otbr_cli_unified")
    result = process(tmp_path, "otbr_cli_unified")
    assert result.observation.completeness.value == "degraded"
    assert result.assessment.reproduction_context["unifiedHealth"]["absenceWitness"] is None
    assert not result.assessment.coverage["topologyAuthority"]
    assert all(value["state"] != "sufficient" for value in result.assessment.coverage["observedPillars"].values())


def test_ping_reachable_router_without_tables_is_expected_not_a_timeout(tmp_path):
    _seed(tmp_path, "otbr_cli_unified")
    silent = {"rloc16": "0x4400", "extAddress": "8899aabbccddeeff", "childTable": [],
              "childTableCount": 0, "error": {"type": "ResponseTimeout"},
              "tableAttempt": {"status": "timeout"}, "ping": {"status": "reply"},
              "targetIdentity": {"rloc16": "0x4400", "extAddress": "8899aabbccddeeff"},
              "sourceObservedAt": SOURCE_TIME}
    _save(tmp_path, "td-otbr-cli-meshdiag-router-childtables.json", [
        {"rloc16": "0x1000", "extAddress": "0011223344556677", "childTable": [],
         "tableAttempt": {"status": "success"}, "sourceObservedAt": SOURCE_TIME},
        silent,
    ])
    _save(tmp_path, "td-otbr-cli-networkdiag-fetch-all.json", [
        {"extAddress": "0011223344556677", "rloc16": "0x1000", "deviceLabel": "router",
         "sourceObservedAt": SOURCE_TIME},
        {"extAddress": "8899aabbccddeeff", "rloc16": "0x4400", "children": [],
         "networkDiagnosticStatus": "responded", "sourceObservedAt": SOURCE_TIME},
    ])
    report = build_unified_dataset(tmp_path, "otbr_cli_unified")
    assert report["healthState"] == "complete"
    result = process(tmp_path, "otbr_cli_unified")
    assert result.observation.completeness.value == "complete"
    assert result.assessment.reproduction_context["unifiedHealth"]["absenceWitness"] is not None
    assert result.assessment.coverage["meshdiagTablesNotProvided"] == 1
    assert result.assessment.coverage["diagnosticTimeoutDeviceCount"] == 0
    flags = {(metric.device_id, metric.metric) for metric in result.observation.metrics}
    assert ("extaddr:8899aabbccddeeff", "meshdiagTableNotProvided") in flags
    assert not any(metric == "diagnosticTimeout" for _, metric in flags)

    # Without a ping reply the same table gap stays a degraded timeout.
    _save(tmp_path, "td-otbr-cli-meshdiag-router-childtables.json", [
        {**silent, "ping": {"status": "no-reply"}},
    ])
    build_unified_dataset(tmp_path, "otbr_cli_unified")
    degraded = process(tmp_path, "otbr_cli_unified")
    assert degraded.observation.completeness.value == "degraded"
    assert degraded.assessment.coverage["meshdiagTablesNotProvided"] == 0
    assert degraded.assessment.coverage["diagnosticTimeoutDeviceCount"] == 1

    # Uncovered children reject the exemption, so the timeout finding remains.
    _save(tmp_path, "td-otbr-cli-meshdiag-router-childtables.json", [
        {"rloc16": "0x1000", "extAddress": "0011223344556677", "childTable": [],
         "tableAttempt": {"status": "success"}, "sourceObservedAt": SOURCE_TIME},
        silent,
    ])
    _save(tmp_path, "td-otbr-cli-networkdiag-fetch-all.json", [
        {"extAddress": "0011223344556677", "rloc16": "0x1000", "deviceLabel": "router",
         "sourceObservedAt": SOURCE_TIME},
        {"extAddress": "8899aabbccddeeff", "rloc16": "0x4400", "children": [],
         "networkDiagnosticStatus": "no-response", "sourceObservedAt": SOURCE_TIME},
    ])
    assert "uncovered-children:0x4400" in build_unified_dataset(
        tmp_path, "otbr_cli_unified")["coverage"]["healthReasons"]
    uncovered = process(tmp_path, "otbr_cli_unified")
    assert uncovered.assessment.coverage["meshdiagTablesNotProvided"] == 0
    assert uncovered.assessment.coverage["diagnosticTimeoutDeviceCount"] == 1


@pytest.mark.usefixtures("archived_health_catalog")
def test_non_unified_datasets_keep_meshdiag_timeouts():
    from td_health_processor import _normalize_samples
    dataset = load_health_manifest().dataset("otbr_cli_topology")
    filename = "td-otbr-cli-meshdiag-router-childtables.json"
    assert filename in dataset.files
    record = {"rloc16": "0x4400", "extAddress": "8899aabbccddeeff", "childTable": [],
              "error": {"type": "ResponseTimeout"}, "tableAttempt": {"status": "timeout"},
              "ping": {"status": "reply"},
              "targetIdentity": {"rloc16": "0x4400", "extAddress": "8899aabbccddeeff"}}
    _, _, metrics, _, _ = _normalize_samples(replace(dataset, files=(filename,)), {filename: [record]})
    assert {metric.metric for metric in metrics} == {"diagnosticTimeout"}


def test_assembly_contract_upgrade_creates_a_distinct_observation(tmp_path, monkeypatch):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    _seed(tmp_path, "otbr_cli_unified")
    monkeypatch.setattr("td_unified_dataset.BUILDER_CONTRACT", "unified-assembly-v8")
    build_unified_dataset(tmp_path, "otbr_cli_unified")
    before = process(tmp_path, "otbr_cli_unified", store)
    monkeypatch.undo()
    build_unified_dataset(tmp_path, "otbr_cli_unified")
    after = process(tmp_path, "otbr_cli_unified", store)
    assert after.observation.observation_id != before.observation.observation_id
    assert after.observation.source_set_digest == before.observation.source_set_digest
    with closing(store._connect()) as connection:
        for result in (before, after):
            observation, _ = store._endpoint(connection, result.assessment.assessment_id)
            assert observation.observation_id == result.observation.observation_id


def test_v17_unified_assessment_reassesses_from_retained_observation_after_upgrade(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr("td_unified_dataset.BUILDER_CONTRACT", "unified-assembly-v10")
    _seed(tmp_path, "otbr_cli_unified")
    build_unified_dataset(tmp_path, "otbr_cli_unified")
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    monkeypatch.setattr("td_health_evaluator.UNIFIED_EVALUATOR_VERSION", "snapshot-v17")
    legacy = process(tmp_path, "otbr_cli_unified", store)
    assert legacy.assessment.evaluator_version == "snapshot-v17"
    monkeypatch.setattr("td_health_evaluator.UNIFIED_EVALUATOR_VERSION", "snapshot-v18")
    monkeypatch.setattr("td_unified_dataset.BUILDER_CONTRACT", "unified-assembly-v11")

    for path in tmp_path.glob("*.json"):
        path.unlink()
    reopened = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    reopened.upsert_expected_device(
        NETWORK, "extaddr:2222222222222222", "retained", "expected",
    )
    with closing(reopened._connect()) as connection:
        row = connection.execute(
            """SELECT assessment_id FROM current_assessments
               WHERE dataset_id='otbr_cli_unified' AND network_id=?""",
            (NETWORK,),
        ).fetchone()
        retained = reopened._endpoint(connection, row["assessment_id"])
    assert retained[1].evaluator_version == "snapshot-v17"
    assert retained[1].reproduction_context["evaluatorVersion"] == "snapshot-v17"
    assert retained[1].reproduction_context["unifiedHealth"]["absenceWitness"] is not None


def test_unified_comparison_requires_matching_current_evaluator(tmp_path):
    from td_health_comparison import derive_comparison, source_roles_for_dataset
    collection(tmp_path, "otbr_cli_unified", 1, positive=True)
    before = process(tmp_path, "otbr_cli_unified")
    collection(tmp_path, "otbr_cli_unified", 2)
    after = process(tmp_path, "otbr_cli_unified")
    roles = source_roles_for_dataset(load_health_manifest().dataset("otbr_cli_unified"))
    assert after.assessment.evaluator_version == "snapshot-v17"
    for old_version, new_version, comparable in (
        ("snapshot-v15", "snapshot-v15", False),
        ("snapshot-v15", "snapshot-v17", False),
        ("snapshot-v16", "snapshot-v16", True),
        ("snapshot-v16", "snapshot-v17", False),
        ("snapshot-v17", "snapshot-v17", True),
        ("snapshot-v18", "snapshot-v18", True),
        ("snapshot-v17", "snapshot-v18", False),
    ):
        legacy = replace(before.assessment, evaluator_version=old_version)
        after_assessment = replace(after.assessment, evaluator_version=new_version)
        interval, _ = derive_comparison(
            (before.observation, legacy), (after.observation, after_assessment), source_roles=roles,
        )
        assert interval.compatibility.comparable is comparable


@pytest.mark.parametrize("dataset_id", ["otbr_cli_unified", "otbr_restapi_unified"])
def test_missing_required_original_needs_explicit_partial_build_and_processing(tmp_path, dataset_id):
    _seed(tmp_path, dataset_id)
    entry = _entry(dataset_id)
    missing = next(item["file"] for item in entry["unified"]["inputs"] if item["required"])
    (tmp_path / missing).unlink()
    build_unified_dataset(tmp_path, dataset_id, allow_partial=True)
    with pytest.raises(HealthProcessingError, match="allow-partial"):
        process(tmp_path, dataset_id)
    result = process(tmp_path, dataset_id, allow_partial=True)
    assert result.observation.completeness.value == "partial"
    assert result.assessment.reproduction_context["unifiedHealth"]["absenceWitness"] is None


def test_retained_comparison_has_distinct_unified_contract_and_qualified_absence(tmp_path):
    from td_health_comparison import derive_comparison, source_roles_for_dataset
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    collection(tmp_path, "otbr_cli_unified", 1, positive=True)
    before = process(tmp_path, "otbr_cli_unified", store)
    collection(tmp_path, "otbr_cli_unified", 2)
    after = process(tmp_path, "otbr_cli_unified", store)
    for path in tmp_path.glob("*.json"):
        path.unlink()
    with closing(store._connect()) as connection:
        endpoints = [
            store._endpoint(connection, result.assessment.assessment_id) for result in (before, after)
        ]
    roles = source_roles_for_dataset(load_health_manifest().dataset("otbr_cli_unified"))
    interval, items = derive_comparison(*endpoints, source_roles=roles)
    assert interval.compatibility.comparable
    presence = next(item for item in items if item.subject_id == MISSING and item.kind == "presence-transition")
    assert presence.compatibility.comparable
    assert presence.after_value is False
    assert "td-otbr-cli-networkdiag-fetch-all.json" in presence.source_files
    # A retained positive projection or unavailable ordering cannot prove removal.
    for change in ({"positiveDeviceIds": [MISSING]}, {"absenceOrderingAvailable": False},
                   {"absenceWitness": None}):
        context = dict(after.assessment.reproduction_context)
        context["unifiedHealth"] = {**context["unifiedHealth"], **change}
        modified = replace(after.assessment, reproduction_context=context)
        _, items = derive_comparison(
            (before.observation, before.assessment), (after.observation, modified), source_roles=roles,
        )
        item = next(item for item in items if item.subject_id == MISSING and item.kind == "presence-transition")
        assert not item.compatibility.comparable


@pytest.mark.parametrize("dataset_id", IDS)
def test_cli_and_health_api_expose_the_same_explicit_qualified_profiles(tmp_path, dataset_id):
    import asyncio
    import subprocess
    import sys
    from pathlib import Path
    import td_webserver
    from test_td_webserver_health import _request

    seed(tmp_path, dataset_id)
    before = {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}
    command = [
        sys.executable, "src/td_cli.py", "--datadir", str(tmp_path),
        "health", "process-dataset", "--dataset", dataset_id, "--dry-run", "--json",
    ]
    result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["datasetId"] == dataset_id
    assert document["evaluatorVersion"] == "snapshot-v17"
    assert not (tmp_path / "hobat_v1.db").exists()
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    persisted = process(tmp_path, dataset_id, store)
    capabilities = asyncio.run(td_webserver.handle_health_capabilities_api(_request(tmp_path)))
    declared = json.loads(capabilities.text)["datasets"]
    assert set(IDS) <= set(declared)
    assert "mdns_unified" not in declared
    response = asyncio.run(td_webserver.handle_health_summary_api(
        _request(tmp_path, query={"dataset": dataset_id, "network": NETWORK})))
    summary = json.loads(response.text)
    assert summary["assessmentId"] == persisted.assessment.assessment_id
    assert summary["profileId"] == document["profileId"]
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.json")} == before


def test_optional_newer_evidence_cannot_move_negative_witness_past_expected_since(tmp_path):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    with closing(store._connect()) as connection, connection:
        connection.execute("UPDATE expected_devices SET expected_since='2026-01-02T00:00:00+00:00'")
    collection(tmp_path, "otbr_cli_unified", 1)
    _save(tmp_path, "td-otbr-cli-router-table.json", [
        {"extAddress": "0011223344556677", "sourceObservedAt": "2026-01-03T00:00:00+00:00"},
    ])
    build_unified_dataset(tmp_path, "otbr_cli_unified")
    result = process(tmp_path, "otbr_cli_unified", store)
    assert result.observation.observed_at == "2026-01-03T00:00:00+00:00"
    assert MISSING not in result.assessment.reproduction_context["expectedDeviceIds"]


@pytest.mark.usefixtures("archived_health_catalog")
def test_unsupported_retained_original_contract_never_supplies_negative_opportunities(tmp_path):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    for day in (1, 2):
        collection(tmp_path, "otbr_cli_unified", day)
        process(tmp_path, "otbr_cli_topology", store)
    with closing(store._connect()) as connection, connection:
        connection.execute("UPDATE assessments SET sample_contract_version='unsupported-retained-contract'")
    collection(tmp_path, "otbr_cli_unified", 3)
    result = process(tmp_path, "otbr_cli_unified", store)
    assert missing_finding(result).evidence["consecutiveCompleteAbsences"] == 1


@pytest.mark.parametrize("history", ["file", "unified", "unsupported"])
@pytest.mark.usefixtures("archived_health_catalog")
def test_file_mode_history_does_not_require_manifest_archive(tmp_path, monkeypatch, history):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    collection(tmp_path, "otbr_cli_unified", 1)
    process(tmp_path, "otbr_cli_unified" if history == "unified" else "otbr_cli_topology", store)
    if history == "unsupported":
        with closing(store._connect()) as connection, connection:
            connection.execute("UPDATE assessments SET sample_contract_version='unsupported-retained-contract'")

    def reject_archive():
        raise AssertionError("Native file-mode health must not load the manifest archive")

    monkeypatch.setattr("td_health_manifest_history.load_manifest_history", reject_archive)
    collection(tmp_path, "otbr_cli_unified", 2)
    result = process(tmp_path, "otbr_cli_topology", store)
    assert missing_finding(result).evidence["consecutiveCompleteAbsences"] == (
        1 if history == "unsupported" else 2
    )


@pytest.mark.usefixtures("archived_health_catalog")
def test_retained_comparison_rechecks_late_same_witness_positive_projection(tmp_path):
    store = SQLiteHealthStore(tmp_path / "hobat_v1.db")
    expected(store)
    collection(tmp_path, "otbr_cli_unified", 1, positive=True)
    before = process(tmp_path, "otbr_cli_unified", store)
    collection(tmp_path, "otbr_cli_unified", 2)
    after = process(tmp_path, "otbr_cli_unified", store)
    assert after.assessment.reproduction_context["unifiedHealth"]["positiveDeviceIds"] == []
    collection(tmp_path, "otbr_cli_unified", 2, positive=True)
    process(tmp_path, "otbr_cli_topology", store)
    for path in tmp_path.glob("*.json"):
        path.unlink()
    with closing(store._connect()) as connection:
        endpoints = [
            store._endpoint(connection, result.assessment.assessment_id) for result in (before, after)
        ]
        _, items = store._derive_pair(connection, *endpoints)
    presence = next(item for item in items if item.subject_id == MISSING and item.kind == "presence-transition")
    assert not presence.compatibility.comparable
