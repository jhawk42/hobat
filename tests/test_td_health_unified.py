"""Original-evidence qualification and retained Unified health regressions."""

import json
import os
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from td_health_manifest import load_health_manifest
from td_health_migration import inventory_health_history
from td_health_policy import load_health_policy
from td_health_processor import HealthProcessingError, build_processing_result, process_health
from td_health_read import TDHealthReadService
from td_health_sqlite import SQLiteHealthStore
from td_unified_dataset import build_unified_dataset, read_original_evidence
from test_td_unified_dataset import NETWORK, SOURCE_TIME, _entry, _save, _seed, _seed_ha


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
    "unified-assembly-v9",
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
def test_rest_child_table_coverage_uses_only_independent_rest_absence_authority(tmp_path, child_table):
    from test_td_unified_composition import _seed_rest_child_coverage

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


def collection(directory, dataset_id, day, *, positive=False, variant=False):
    _seed(directory, dataset_id)
    time = f"2026-01-{day:02d}T00:00:00+00:00"
    epoch = int(datetime.fromisoformat(time).timestamp() * 1_000_000_000)
    for item in _entry(dataset_id)["unified"]["inputs"]:
        path = directory / item["file"]
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        if item["role"] == "records":
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
