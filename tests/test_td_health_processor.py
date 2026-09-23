"""Safety tests for cache-only health processing and evaluation."""

from __future__ import annotations

import json
import hashlib
import os
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from td_health_observation_model import Completeness, HealthStatus
from td_health_comparison import source_time_for_sample
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_read import TDHealthReadService
from td_health_policy import load_health_policy
from td_health_processor import (
    HealthProcessingError,
    _normalize_samples,
    _omr_prefix_from_identity,
    build_processing_result,
    process_health,
)
from td_health_manifest import load_health_manifest
from td_health_roster import extract_roster_facts
from td_health_sqlite import SQLiteHealthStore


def _write_seed(data_dir, devices, *, extpan="78b9775b001c1cbe"):
    (data_dir / "td-otbr-cli-thread-network-info.json").write_text(
        json.dumps({"extPanId": extpan, "networkName": "mutable-name"}),
        encoding="utf-8",
    )
    (data_dir / "td-otbr-cli-networkdiag-fetch-all.json").write_text(
        json.dumps(devices), encoding="utf-8"
    )


def test_roster_extracts_only_explicit_valid_source_facts() -> None:
    manifest = load_health_manifest()
    dataset = manifest.dataset("otbr_restapi_devices_fetch_diagnostics_fetch_all")
    filename = "td-otbr-restapi-devices-fetch.json"
    facts = extract_roster_facts(
        {"extAddress": "86:72:76:6A:E0:57:81:87", "eui64": "11:22:33:44:55:66:77:88",
         "omrIpv6Address": "::", "deviceLabel": "", "isBorderRouter": False,
         "mode": {"rxOnWhenIdle": False, "fullThreadDevice": "false"},
         "ipv6Addresses": ["fd00::2", "fd00::1", "fd00::2"]},
        filename=filename, dataset=dataset, policy=manifest.roster_policy,
    )
    values = {fact.field_key: json.loads(fact.value_json) for fact in facts}
    assert values["extAddress"] == "8672766ae0578187"
    assert values["eui64"] == "1122334455667788"
    assert values["isBorderRouter"] is False
    assert values["mode.rxOnWhenIdle"] is False
    assert values["ipv6Addresses"] == ["fd00::1", "fd00::2"]
    assert "omrIpv6Address" not in values
    assert "deviceLabel" not in values
    assert "mode.fullThreadDevice" not in values
    observed_omr = extract_roster_facts(
        {"extAddress": "8672766ae0578187", "omrIpv6Address": "fd6b:32e0:d18::1"},
        filename=filename, dataset=dataset, policy=manifest.roster_policy,
    )
    assert next(fact for fact in observed_omr if fact.field_key == "omrIpv6Address").value_class == "address"
    invalid_set = extract_roster_facts(
        {"extAddress": "8672766ae0578187", "ipv6Addresses": ["fd00::1", "::"]},
        filename=filename, dataset=dataset, policy=manifest.roster_policy,
    )
    assert all(fact.field_key != "ipv6Addresses" for fact in invalid_set)
    assert not extract_roster_facts({"extAddress": "unknown", "role": "router"},
                                    filename=filename, dataset=dataset, policy=manifest.roster_policy)
    assert not extract_roster_facts({"extAddress": "8672766ae0578187"},
                                    filename="td-static-extaddr-device-label.json", dataset=dataset,
                                    policy=manifest.roster_policy)


@pytest.mark.parametrize(("value", "expected"), [
    ("0x1472c6c1", 0x1472c6c1), (0x1472c6c1, 0x1472c6c1),
    ("0x100000000", None), ("0xnothex", None), (True, None),
])
def test_roster_partition_accepts_explicit_cli_hex_and_rejects_invalid_values(value, expected) -> None:
    manifest = load_health_manifest()
    dataset = manifest.dataset("otbr_cli_networkdiag_fetch_all")
    facts = extract_roster_facts(
        {"extAddress": "8672766ae0578187", "leaderData": {"partitionId": value}},
        filename="td-otbr-cli-networkdiag-fetch-all.json", dataset=dataset,
        policy=manifest.roster_policy,
    )
    partition = next((json.loads(fact.value_json) for fact in facts
                      if fact.field_key == "leaderData.partitionId"), None)
    assert partition == expected


def test_otbr_cli_route64_requires_resolved_bounded_reporter_coverage() -> None:
    dataset = load_health_manifest().dataset("otbr_cli_networkdiag_fetch_all")
    filename = dataset.files[0]
    reporter = {"extaddr": "1111111111111111", "router_id": 1,
                "route64": {"id_sequence": 4, "route_data": [
                    {"route_id": "0x02", "route_cost": 2}]}}
    target = {"extaddr": "2222222222222222", "router_id": 2}
    devices, relationships, metrics, _, _ = _normalize_samples(dataset, {filename: [reporter, target]})
    assert len(devices) == 2
    assert [(link.relationship_type, link.from_device_id, link.to_device_id) for link in relationships] == [
        ("router-route", "extaddr:1111111111111111", "extaddr:2222222222222222")]
    assert [(metric.device_id, metric.metric, metric.value, metric.source_file) for metric in metrics] == [
        ("extaddr:1111111111111111", "route64Coverage", 1.0, filename)]
    empty = {**reporter, "route64": {"id_sequence": 5, "route_data": []}}
    _, links, coverage, _, _ = _normalize_samples(dataset, {filename: [empty, target]})
    assert links == () and len(coverage) == 1
    unresolved = {**reporter, "route64": {"id_sequence": 6, "route_data": [{"route_id": "0x03"}]}}
    _, links, coverage, _, _ = _normalize_samples(dataset, {filename: [unresolved, target]})
    assert links == () and coverage == ()
    for entries in ([{"route_id": "0x02"}, {"route_id": "0x02"}],
                    [{"route_id": "0x02"}] * 64, [{"route_id": "invalid"}]):
        invalid = {**reporter, "route64": {"id_sequence": 7, "route_data": entries}}
        _, links, coverage, _, _ = _normalize_samples(dataset, {filename: [invalid, target]})
        assert links == () and coverage == ()
    conflicting = {**target, "extaddr": "3333333333333333"}
    _, links, coverage, _, _ = _normalize_samples(dataset, {filename: [reporter, target, conflicting]})
    assert links == () and coverage == ()
    duplicate_reporter = {**reporter, "route64": {"id_sequence": 5, "route_data": []}}
    _, links, coverage, _, _ = _normalize_samples(dataset, {filename: [reporter, duplicate_reporter, target]})
    assert links == () and coverage == ()
    fallback = {"rloc16": "0x0400", "route64": reporter["route64"]}
    _, links, coverage, _, _ = _normalize_samples(dataset, {filename: [
        {**reporter, "rloc16": "0x0400", "route64": None}, fallback, target,
    ]})
    assert links == () and coverage == ()
    rest = load_health_manifest().dataset("otbr_restapi_devices_fetch_diagnostics_fetch_all")
    _, links, coverage, _, _ = _normalize_samples(rest, {
        name: [reporter, target] if name == rest.files[0] else [] for name in rest.files
    })
    assert links == () and coverage == ()


def test_route64_comparison_persists_covered_removal_and_unknown_gap(tmp_path) -> None:
    reporter = {"extaddr": "1111111111111111", "router_id": 1, "role": "router"}
    target = {"extaddr": "2222222222222222", "router_id": 2, "role": "router"}
    _write_seed(tmp_path, [])
    identity = tmp_path / "td-otbr-cli-thread-network-info.json"
    first_time = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()
    os.utime(identity, (first_time, first_time))
    snapshot = tmp_path / "td-otbr-cli-networkdiag-fetch-all.json"
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    link_id = "link:route:extaddr:1111111111111111->extaddr:2222222222222222"
    source_times = (datetime(2026, 9, day, tzinfo=timezone.utc) for day in (1, 2, 3, 4))
    for routes, source_time in zip(
        ([{"route_id": "0x02"}], [], [{"route_id": "0x02"}], [{"route_id": "0x03"}]), source_times,
    ):
        record = {**reporter, "route64": {"id_sequence": 4, "route_data": routes}}
        snapshot.write_text(json.dumps([record, target]), encoding="utf-8")
        os.utime(snapshot, (source_time.timestamp(), source_time.timestamp()))
        process_health(data_dir=tmp_path, dataset_id="otbr_cli_networkdiag_fetch_all",
                       policy=load_health_policy(), store=store,
                       processing_time=datetime(2026, 9, 5, tzinfo=timezone.utc))

    service = TDHealthReadService(tmp_path)
    listing = service.comparisons(network_id="extpan:78b9775b001c1cbe",
                                  dataset_id="otbr_cli_networkdiag_fetch_all", limit=25, offset=0)
    assert listing["total"] == 3
    newer = service.comparison(comparison_id=listing["items"][0]["comparisonId"], limit=25, offset=0)
    older = service.comparison(comparison_id=listing["items"][2]["comparisonId"], limit=25, offset=0)
    removed = next(item for item in older["items"] if item["subjectId"] == link_id)
    unknown = next(item for item in newer["items"] if item["subjectId"] == link_id)
    assert (removed["transition"], removed["change"], removed["sourceFiles"]) == (
        "removed", "changed", ["td-otbr-cli-networkdiag-fetch-all.json"])
    assert removed["beforeSourceObservedAt"] < removed["afterSourceObservedAt"]
    assert unknown["change"] == "unknown" and unknown["transition"] is None
    assert unknown["reasons"] == ["metric-missing"]
    removed_id = older["comparisonId"]
    dry = store.purge_device("extaddr:2222222222222222", dry_run=True)
    applied = store.purge_device("extaddr:2222222222222222")
    assert dry.deleted == applied.deleted
    assert applied.deleted["comparisons"] == 3
    assert service.comparison(comparison_id=removed_id, limit=25, offset=0) is None


def test_route64_reprocessing_creates_new_immutable_observation_identity(tmp_path) -> None:
    _write_seed(tmp_path, [{"extaddr": "1111111111111111", "router_id": 1,
                            "route64": {"id_sequence": 1, "route_data": []}}])
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    pending = build_processing_result(data_dir=tmp_path, dataset_id="otbr_cli_networkdiag_fetch_all",
                                      policy=load_health_policy())
    observation = pending.observation
    old_key = "\0".join((observation.datasource_id, observation.dataset_id,
                          observation.network_id, observation.observed_at, observation.source_set_digest))
    legacy_id = "observation:" + hashlib.sha256(old_key.encode("utf-8")).hexdigest()[:24]
    legacy_observation = replace(observation, observation_id=legacy_id, relationships=(), metrics=())
    legacy_assessment = replace(pending.assessment, assessment_id="assessment:legacy-route64",
                                observation_id=legacy_id, sample_contract_version="comparison-v1")
    store.save_processing_result(legacy_observation, legacy_assessment)
    result = process_health(data_dir=tmp_path, dataset_id="otbr_cli_networkdiag_fetch_all",
                            policy=load_health_policy(), store=store)
    observation = result.observation
    assert observation.observation_id != legacy_id
    assert result.observation_created
    assert result.assessment.sample_contract_version == "comparison-v1-route64"
    with closing(store._connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM metric_samples WHERE observation_id=?",
                                  (legacy_id,)).fetchone()[0] == 0
    repeated = process_health(data_dir=tmp_path, dataset_id="otbr_cli_networkdiag_fetch_all",
                              policy=load_health_policy(), store=store)
    assert repeated.observation.observation_id == observation.observation_id
    assert not repeated.observation_created


def test_roster_persists_attributed_facts_only_for_new_observations(tmp_path) -> None:
    _write_seed(tmp_path, [{"extaddr": "8672766ae0578187", "role": "router",
                            "mode": {"rxOnWhenIdle": False}, "deviceLabel": "entry"}])
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    first = process_health(data_dir=tmp_path, dataset_id="otbr_cli_networkdiag_fetch_all",
                           policy=load_health_policy(), store=store)
    assert first.observation_created
    again = process_health(data_dir=tmp_path, dataset_id="otbr_cli_networkdiag_fetch_all",
                           policy=load_health_policy(), store=store)
    assert not again.observation_created
    with closing(store._connect()) as connection:
        facts = connection.execute(
            "SELECT field_key, value_json, source_file, source_observed_at FROM device_fact_samples "
            "WHERE observation_id=? ORDER BY field_key", (first.observation.observation_id,),
        ).fetchall()
        assert all(row["source_file"] == "td-otbr-cli-networkdiag-fetch-all.json"
                   and row["source_observed_at"] for row in facts)
        assert {row["field_key"]: json.loads(row["value_json"]) for row in facts}["mode.rxOnWhenIdle"] is False
        assert connection.execute("SELECT COUNT(*) FROM device_fact_samples WHERE observation_id=?",
                                  (first.observation.observation_id,)).fetchone()[0] == len(facts)
        projected = connection.execute(
            "SELECT source_observed_at FROM device_last_known WHERE network_id=? AND device_id=? AND field_key='role'",
            (first.observation.network_id, "extaddr:8672766ae0578187"),
        ).fetchone()
        assert projected and projected["source_observed_at"]
    page = TDHealthReadService(tmp_path).roster(network_id=first.observation.network_id)
    assert page["schemaVersion"] == 1 and page["total"] == 1
    assert page["devices"][0]["deviceId"] == "extaddr:8672766ae0578187"
    detail = TDHealthReadService(tmp_path).roster_device(
        network_id=first.observation.network_id, device_id="extaddr:8672766ae0578187",
    )
    assert detail["fields"]["mode.rxOnWhenIdle"]["value"] is False
    assert detail["fields"]["omrIpv6Address"]["freshness"] == "absent"
    assert detail["displayLabel"] == "entry" and detail["labelOrigin"] == "observed"
    stale_time = datetime.fromisoformat(detail["fields"]["deviceLabel"]["sourceObservedAt"]) + timedelta(days=31)
    stale = TDHealthReadService(tmp_path).roster_device(
        network_id=first.observation.network_id, device_id="extaddr:8672766ae0578187",
        read_time=stale_time,
    )
    assert stale["displayLabel"] == "…e0578187 (stale label)"
    assert stale["labelOrigin"] == "fallback"
    assert stale["fields"]["deviceLabel"]["freshness"] == "stale"


def test_roster_disambiguates_labels_across_pages_and_priorities(tmp_path) -> None:
    first_id = "extaddr:8672766ae0578187"
    second_id = "extaddr:8672766ae0578188"
    _write_seed(tmp_path, [{"extaddr": first_id.removeprefix("extaddr:"), "deviceLabel": "Desk"},
                           {"extaddr": second_id.removeprefix("extaddr:"), "deviceLabel": "Desk"}])
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    result = process_health(data_dir=tmp_path, dataset_id="otbr_cli_networkdiag_fetch_all",
                            policy=load_health_policy(), store=store)
    network_id = result.observation.network_id
    service = TDHealthReadService(tmp_path)
    for offset, device_id in ((0, first_id), (1, second_id)):
        page = service.roster(network_id=network_id, limit=1, offset=offset)
        device = page["devices"][0]
        assert device["deviceId"] == device_id
        assert device["displayLabel"] == f"Desk · {device_id[-8:]} (duplicate label)"
        assert device["labelAmbiguity"] == "duplicate label"
        detail = service.roster_device(network_id=network_id, device_id=device_id)
        assert detail["fields"]["deviceLabel"]["value"] == "Desk"
    (tmp_path / "td-static-extaddr-device-label.json").write_text(json.dumps([
        {"extAddress": first_id.removeprefix("extaddr:"), "deviceLabel": "Desk"},
    ]), encoding="utf-8")
    assert service.roster_device(network_id=network_id, device_id=first_id)["labelOrigin"] == "static"
    store.upsert_expected_device(network_id, first_id, "Desk")
    assert service.roster_device(network_id=network_id, device_id=first_id)["labelOrigin"] == "expected"
    assert service.roster_device(network_id=network_id, device_id=second_id)["labelAmbiguity"] == "duplicate label"
    store.upsert_expected_device(network_id, first_id, "Office")
    assert service.roster_device(network_id=network_id, device_id=second_id)["labelAmbiguity"] == "none"


def test_roster_alias_collision_does_not_merge_device_ids(tmp_path) -> None:
    devices = [
        {"extAddress": "8672766ae0578187", "eui": "1122334455667788"},
        {"extAddress": "8672766ae0578188", "eui": "1122334455667788"},
    ]
    (tmp_path / "td-otbr-restapi-dataset-active.json").write_text(
        json.dumps({"extPanId": "78b9775b001c1cbe"}), encoding="utf-8")
    (tmp_path / "td-otbr-restapi-devices-fetch.json").write_text(json.dumps(devices), encoding="utf-8")
    (tmp_path / "td-otbr-restapi-diagnostics-fetch-all.json").write_text("[]", encoding="utf-8")
    (tmp_path / "td-otbr-restapi-diagnostics-fetch-all.outcome.json").write_text(
        json.dumps({"deviceResults": [{"status": "completed"}], "completedAt": "2026-09-01"}),
        encoding="utf-8")
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    process_health(data_dir=tmp_path, dataset_id="otbr_restapi_devices_fetch_diagnostics_fetch_all",
                   policy=load_health_policy(), store=store)
    network_id = "extpan:78b9775b001c1cbe"
    with closing(store._connect()) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM device_identity_conflicts WHERE network_id=? AND field_key='eui64'",
            (network_id,),
        ).fetchone()[0] == 2
    service = TDHealthReadService(tmp_path)
    assert service.roster(network_id=network_id)["total"] == 2
    first = service.roster_device(network_id=network_id, device_id="extaddr:8672766ae0578187")
    assert first["fields"]["eui64"]["conflictState"] == "alias-collision"
    store.purge_device("extaddr:8672766ae0578188", network_id=network_id)
    assert service.roster(network_id=network_id)["total"] == 1
    first = service.roster_device(network_id=network_id, device_id="extaddr:8672766ae0578187")
    assert first["fields"]["eui64"]["conflictState"] == "none"


def test_missing_final_is_rejected_without_allow_partial(tmp_path) -> None:
    (tmp_path / "td-otbr-cli-thread-network-info.json").write_text(
        json.dumps({"extPanId": "78b9775b001c1cbe"}), encoding="utf-8"
    )
    with pytest.raises(HealthProcessingError, match="missing or invalid"):
        build_processing_result(
            data_dir=tmp_path,
            dataset_id="otbr_cli_networkdiag_fetch_all",
            policy=load_health_policy(),
        )


def test_processor_uses_extpan_identity_and_normalizes_devices(tmp_path) -> None:
    _write_seed(
        tmp_path,
        [{"extaddr": "86:72:76:6A:E0:57:81:87", "role": "router"}],
    )
    result = build_processing_result(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        processing_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    assert result.observation.network_id == "extpan:78b9775b001c1cbe"
    assert result.observation.devices[0].device_id == "extaddr:8672766ae0578187"
    assert result.observation.completeness is Completeness.COMPLETE
    assert result.assessment.status is HealthStatus.UNKNOWN
    assert result.assessment.confidence.value == "low"
    assert (
        result.assessment.coverage["observedPillars"]["availability"]["state"]
        == "sufficient"
    )
    assert (
        result.assessment.coverage["observedPillars"]["connectivity"]["state"]
        == "missing"
    )
    assert result.assessment.coverage["pillars"]["resilience"] == "limited"
    assert not any(
        finding.rule_id == "network.current-path-redundancy"
        for finding in result.assessment.findings
    )
    assert any(
        finding.rule_id == "network.border-router-redundancy"
        for finding in result.assessment.findings
    )


def test_partial_observation_cannot_make_expected_device_offline(tmp_path) -> None:
    _write_seed(tmp_path, [])
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    network_id = "extpan:78b9775b001c1cbe"
    store.upsert_expected_device(network_id, "extaddr:8672766ae0578187", "expected")
    complete = process_health(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        store=store,
    )
    assert not any(f.rule_id == "device.offline" for f in complete.assessment.findings)

    (tmp_path / "td-otbr-cli-networkdiag-fetch-all.partial.json").write_text("[]", encoding="utf-8")
    partial_path = tmp_path / "td-otbr-cli-networkdiag-fetch-all.partial.json"
    partial_path.touch()
    partial = process_health(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        store=store,
        allow_partial=True,
    )
    assert partial.observation.completeness is Completeness.PARTIAL
    assert not any(f.rule_id == "device.offline" for f in partial.assessment.findings)


def test_second_complete_absence_establishes_offline(tmp_path) -> None:
    _write_seed(tmp_path, [])
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    device_id = "extaddr:8672766ae0578187"
    store.upsert_expected_device("extpan:78b9775b001c1cbe", device_id, "expected")
    first = process_health(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        store=store,
        processing_time=datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc),
    )
    assert not any(f.rule_id == "device.offline" for f in first.assessment.findings)

    snapshot = tmp_path / "td-otbr-cli-networkdiag-fetch-all.json"
    snapshot.write_text("[]\n", encoding="utf-8")
    second = process_health(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        store=store,
        processing_time=datetime(2026, 9, 1, 0, 1, tzinfo=timezone.utc),
    )
    assert any(f.rule_id == "device.offline" for f in second.assessment.findings)


def test_intentionally_offline_roster_state_replaces_stale_offline_assessment(tmp_path) -> None:
    _write_seed(tmp_path, [])
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    network_id = "extpan:78b9775b001c1cbe"
    device_id = "extaddr:8672766ae0578187"
    store.upsert_expected_device(network_id, device_id, "expected")
    process_health(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        store=store,
        processing_time=datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc),
    )
    snapshot = tmp_path / "td-otbr-cli-networkdiag-fetch-all.json"
    snapshot.write_text("[]\n", encoding="utf-8")
    offline = process_health(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        store=store,
        processing_time=datetime(2026, 9, 1, 0, 1, tzinfo=timezone.utc),
    )
    assert any(f.rule_id == "device.offline" for f in offline.assessment.findings)

    store.upsert_expected_device(
        network_id, device_id, "expected", "intentionally-offline"
    )
    updated = process_health(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        store=store,
        processing_time=datetime(2026, 9, 1, 0, 2, tzinfo=timezone.utc),
    )

    assert not updated.observation_created
    assert updated.assessment_created
    assert updated.assessment.assessment_id != offline.assessment.assessment_id
    assert not any(
        finding.rule_id == "device.offline" for finding in updated.assessment.findings
    )


def test_complete_absences_below_roster_ratio_are_offline_without_network_impact(tmp_path) -> None:
    device_ids = [f"extaddr:{index:016x}" for index in range(10)]
    missing_device_id = device_ids[0]
    observed_devices = [
        {"extaddr": device_id.removeprefix("extaddr:"), "role": "child"}
        for device_id in device_ids[1:]
    ]
    _write_seed(tmp_path, observed_devices)
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    network_id = "extpan:78b9775b001c1cbe"
    for device_id in device_ids:
        store.upsert_expected_device(network_id, device_id, "expected")

    first = process_health(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        store=store,
        processing_time=datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc),
    )
    assert not any(f.rule_id == "device.offline" for f in first.assessment.findings)

    snapshot = tmp_path / "td-otbr-cli-networkdiag-fetch-all.json"
    snapshot.write_text(json.dumps(observed_devices), encoding="utf-8")
    second = process_health(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        store=store,
        processing_time=datetime(2026, 9, 1, 0, 1, tzinfo=timezone.utc),
    )
    missing = next(
        finding for finding in second.assessment.findings
        if missing_device_id in finding.device_ids
    )

    assert missing.rule_id == "device.offline"
    assert missing.status is HealthStatus.POOR
    assert missing.evidence["offlineDeviceRatio"] == 0.1
    assert missing.evidence["offlinePoorThresholdMet"] is False
    assert not any(
        finding.rule_id == "network.offline-impact"
        for finding in second.assessment.findings
    )
    assert second.assessment.status is not HealthStatus.POOR


def _write_rest_seed(data_dir, outcome):
    (data_dir / "td-otbr-restapi-dataset-active.json").write_text(
        json.dumps(
            {
                "extPanId": "78b9775b001c1cbe",
                "networkName": "safe-label",
                "networkKey": "SECRET_NETWORK_KEY",
                "pskc": "SECRET_PSKC",
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "td-otbr-restapi-diagnostics-fetch-all.json").write_text(
        json.dumps([{"extAddress": "8672766ae0578187", "role": "child"}]),
        encoding="utf-8",
    )
    (data_dir / "td-otbr-restapi-devices-fetch.json").write_text(
        json.dumps([{"extAddress": "8672766ae0578187", "role": "child"}]),
        encoding="utf-8",
    )
    (data_dir / "td-otbr-restapi-diagnostics-fetch-all.outcome.json").write_text(
        json.dumps(outcome), encoding="utf-8"
    )


def test_newer_outcome_does_not_refresh_unchanged_device_source(tmp_path) -> None:
    _write_rest_seed(tmp_path, {
        "deviceResults": [{"deviceId": "8672766ae0578187", "status": "completed"}],
        "completedAt": "2026-09-01T00:00:00+00:00",
    })
    first_time = datetime(2026, 9, 1, tzinfo=timezone.utc)
    later_time = datetime(2026, 9, 2, tzinfo=timezone.utc)
    read_time = datetime(2026, 9, 3, tzinfo=timezone.utc)
    for path in tmp_path.iterdir():
        os.utime(path, (first_time.timestamp(), first_time.timestamp()))
    dataset_id = "otbr_restapi_devices_fetch_diagnostics_fetch_all"
    before = build_processing_result(data_dir=tmp_path, dataset_id=dataset_id,
                                     policy=load_health_policy(), processing_time=read_time)

    outcome = tmp_path / "td-otbr-restapi-diagnostics-fetch-all.outcome.json"
    os.utime(outcome, (later_time.timestamp(), later_time.timestamp()))
    after = build_processing_result(data_dir=tmp_path, dataset_id=dataset_id,
                                    policy=load_health_policy(), processing_time=read_time)
    device_file = "td-otbr-restapi-devices-fetch.json"
    before_time = source_time_for_sample(before.observation, device_file)
    assert before_time == first_time.isoformat()
    assert after.observation.observed_at == later_time.isoformat()
    assert source_time_for_sample(after.observation, device_file) == before_time
    assert source_time_for_sample(after.observation, outcome.name) is None

    device_path = tmp_path / device_file
    os.utime(device_path, (later_time.timestamp(), later_time.timestamp()))
    refreshed = build_processing_result(data_dir=tmp_path, dataset_id=dataset_id,
                                        policy=load_health_policy(), processing_time=read_time)
    assert source_time_for_sample(refreshed.observation, device_file) == later_time.isoformat()

    os.utime(device_path, (read_time.timestamp() + 1, read_time.timestamp() + 1))
    future = build_processing_result(data_dir=tmp_path, dataset_id=dataset_id,
                                     policy=load_health_policy(), processing_time=read_time)
    assert source_time_for_sample(future.observation, device_file) is None


def test_rest_outcome_completeness_contract_and_secret_exclusion(tmp_path) -> None:
    _write_rest_seed(
        tmp_path,
        {
            "items": [],
            "deviceResults": [{"deviceId": "8672766ae0578187", "status": "completed"}],
            "partial": False,
            "completedAt": "2026-09-01T00:00:00+00:00",
        },
    )
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    complete = process_health(
        data_dir=tmp_path,
        dataset_id="otbr_restapi_devices_fetch_diagnostics_fetch_all",
        policy=load_health_policy(),
        store=store,
    )
    assert complete.observation.completeness is Completeness.COMPLETE
    database_bytes = (tmp_path / HOBAT_DATABASE_FILENAME).read_bytes()
    assert b"SECRET_NETWORK_KEY" not in database_bytes
    assert b"SECRET_PSKC" not in database_bytes


def test_rest_legacy_outcome_is_degraded_and_explicit_failure_is_partial(tmp_path) -> None:
    _write_rest_seed(tmp_path, {"items": []})
    degraded = build_processing_result(
        data_dir=tmp_path,
        dataset_id="otbr_restapi_devices_fetch_diagnostics_fetch_all",
        policy=load_health_policy(),
    )
    assert degraded.observation.completeness is Completeness.DEGRADED

    _write_rest_seed(
        tmp_path,
        {
            "items": [],
            "deviceResults": [{"deviceId": "8672766ae0578187", "status": "failed"}],
            "partial": True,
            "completedAt": "2026-09-01T00:00:00+00:00",
        },
    )
    with pytest.raises(HealthProcessingError, match="partial"):
        build_processing_result(
            data_dir=tmp_path,
            dataset_id="otbr_restapi_devices_fetch_diagnostics_fetch_all",
            policy=load_health_policy(),
        )


def test_complete_rest_topology_mdns_profile_reports_border_router_redundancy(tmp_path) -> None:
    dataset_id = "otbr_restapi_topology_mdns_health"
    (tmp_path / "td-otbr-restapi-dataset-active.json").write_text(
        json.dumps({"extPanId": "78b9775b001c1cbe", "networkName": "test"}),
        encoding="utf-8",
    )
    border_routers = [
        {"extAddress": "1111111111111111", "isBorderRouter": True, "role": "router"},
        {"extAddress": "2222222222222222", "isBorderRouter": True, "role": "router"},
    ]
    for filename in (
        "td-otbr-restapi-devices-fetch.json",
        "td-otbr-restapi-diagnostics-fetch-all.json",
        "td-otbr-restapi-mesh-diagnostics-fetch-all.json",
        "td-mdns-scopes-thread.json",
    ):
        (tmp_path / filename).write_text(json.dumps(border_routers), encoding="utf-8")
    completed_outcome = {
        "deviceResults": [{"deviceId": "1111111111111111", "status": "completed"}],
        "partial": False,
        "completedAt": "2026-09-01T00:00:00+00:00",
    }
    for filename in (
        "td-otbr-restapi-diagnostics-fetch-all.outcome.json",
        "td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json",
    ):
        (tmp_path / filename).write_text(json.dumps(completed_outcome), encoding="utf-8")

    complete = build_processing_result(
        data_dir=tmp_path, dataset_id=dataset_id, policy=load_health_policy()
    )
    finding = next(
        finding
        for finding in complete.assessment.findings
        if finding.rule_id == "network.border-router-redundancy"
    )

    assert complete.observation.completeness is Completeness.COMPLETE
    assert finding.status is HealthStatus.STRONG
    assert finding.evidence["observedBorderRouterCount"] == 2

    completed_outcome["partial"] = True
    (tmp_path / "td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json").write_text(
        json.dumps(completed_outcome), encoding="utf-8"
    )
    partial = build_processing_result(
        data_dir=tmp_path,
        dataset_id=dataset_id,
        policy=load_health_policy(),
        allow_partial=True,
    )
    partial_finding = next(
        finding
        for finding in partial.assessment.findings
        if finding.rule_id == "network.border-router-redundancy"
    )

    assert partial.observation.completeness is Completeness.PARTIAL
    assert partial_finding.status is HealthStatus.UNKNOWN
    assert "provisional" in partial_finding.summary


def test_border_router_omr_address_reports_strong_external_routing(tmp_path) -> None:
    dataset_id = "otbr_cli_topology_mdns_health"
    (tmp_path / "td-otbr-cli-thread-network-info.json").write_text(
        json.dumps({
            "extPanId": "78b9775b001c1cbe",
            "networkName": "test",
            "prefixOmr": "fd6b:32e0:d18:0::/64",
            "prefixMeshLocal": "fd3b:a255:4aa6:5483::/64",
            "prefixOmrIpv6AddrPrefix": "fd6b:32e0:d18:0",
        }),
        encoding="utf-8",
    )
    devices = [
        {
            "extAddress": "1111111111111111",
            "isBorderRouter": True,
            "role": "router",
            "ipv6Addresses": ["fd6b:32e0:d18:0:1234:5678:9abc:def0"],
        },
        {"extAddress": "2222222222222222", "isBorderRouter": False, "role": "router"},
    ]
    for filename in (
        "td-otbr-cli-meshdiag-topology.json",
        "td-otbr-cli-networkdiag-fetch-all.json",
        "td-otbr-cli-meshdiag-router-neighbortables.json",
        "td-otbr-cli-meshdiag-router-childtables.json",
        "td-mdns-scopes-thread.json",
    ):
        (tmp_path / filename).write_text(json.dumps(devices), encoding="utf-8")

    result = build_processing_result(
        data_dir=tmp_path, dataset_id=dataset_id, policy=load_health_policy()
    )
    finding = next(
        finding
        for finding in result.assessment.findings
        if finding.rule_id == "network.external-routing"
    )

    assert finding.status is HealthStatus.STRONG
    assert finding.evidence["omrBorderRouterIds"] == ("extaddr:1111111111111111",)
    future_identity = build_processing_result(
        data_dir=tmp_path, dataset_id=dataset_id, policy=load_health_policy(),
        processing_time=datetime.now(timezone.utc) - timedelta(days=1),
    )
    assert not any(item.rule_id == "network.external-routing" for item in future_identity.assessment.findings)


@pytest.mark.parametrize("prefixes", [
    {},
    {"prefixOmr": "fd6b:32e0:d18::"},
    {"prefixOmr": "fd6b:32e0:d18::/64"},
    {"prefixOmr": "fd6b:32e0:d18::/64", "prefixMeshLocal": "not-a-prefix"},
    {"prefixOmr": "fd6b:32e0:d18::/64", "prefixMeshLocal": "fd6b:32e0:d18::/64"},
])
def test_unqualified_identity_prefix_is_not_omr_authority(prefixes) -> None:
    assert _omr_prefix_from_identity(prefixes) is None


@pytest.mark.parametrize(
    ("dataset_id", "identity_file", "final_files", "outcome_files"),
    [
        (
            "otbr_cli_topology_health",
            "td-otbr-cli-thread-network-info.json",
            (
                "td-otbr-cli-meshdiag-topology.json",
                "td-otbr-cli-networkdiag-fetch-all.json",
                "td-otbr-cli-meshdiag-router-neighbortables.json",
                "td-otbr-cli-meshdiag-router-childtables.json",
            ),
            (),
        ),
        (
            "merged_otbr_topology_mdns_health",
            "td-otbr-cli-thread-network-info.json",
            (
                "td-static-extaddr-device-label.json",
                "td-otbr-cli-meshdiag-topology.json",
                "td-otbr-cli-networkdiag-fetch-all.json",
                "td-otbr-cli-meshdiag-router-neighbortables.json",
                "td-otbr-cli-meshdiag-router-childtables.json",
                "td-otbr-restapi-devices-fetch.json",
                "td-otbr-restapi-diagnostics-fetch-all.json",
                "td-otbr-restapi-mesh-diagnostics-fetch-all.json",
                "td-mdns-scopes-thread.json",
            ),
            (
                "td-otbr-restapi-diagnostics-fetch-all.outcome.json",
                "td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json",
            ),
        ),
        (
            "otbr_restapi_devices_fetch_diagnostics_fetch_all",
            "td-otbr-restapi-dataset-active.json",
            (
                "td-otbr-restapi-devices-fetch.json",
                "td-otbr-restapi-diagnostics-fetch-all.json",
            ),
            ("td-otbr-restapi-diagnostics-fetch-all.outcome.json",),
        ),
        (
            "otbr_restapi_devices_fetch_diagnostics_fetch_all_mesh_diagnostics_fetch_all",
            "td-otbr-restapi-dataset-active.json",
            (
                "td-otbr-restapi-devices-fetch.json",
                "td-otbr-restapi-diagnostics-fetch-all.json",
                "td-otbr-restapi-mesh-diagnostics-fetch-all.json",
            ),
            (
                "td-otbr-restapi-diagnostics-fetch-all.outcome.json",
                "td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json",
            ),
        ),
    ],
)
def test_additional_health_datasets_use_source_identity(
    tmp_path, dataset_id, identity_file, final_files, outcome_files
) -> None:
    (tmp_path / identity_file).write_text(
        json.dumps({"extPanId": "78b9775b001c1cbe", "networkName": "shared-source-name"}),
        encoding="utf-8",
    )
    for filename in final_files:
        (tmp_path / filename).write_text(
            json.dumps([{"extAddress": "8672766ae0578187", "role": "router"}]),
            encoding="utf-8",
        )
    for filename in outcome_files:
        (tmp_path / filename).write_text(
            json.dumps(
                {
                    "deviceResults": [{"deviceId": "8672766ae0578187", "status": "completed"}],
                    "partial": False,
                    "completedAt": "2026-09-01T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

    result = build_processing_result(
        data_dir=tmp_path,
        dataset_id=dataset_id,
        policy=load_health_policy(),
    )

    assert result.observation.network_id == "extpan:78b9775b001c1cbe"
    assert result.observation.network_name == "shared-source-name"
    assert result.observation.completeness is Completeness.COMPLETE
    assert result.observation.devices[0].device_id == "extaddr:8672766ae0578187"


def test_mle_and_time_statistics_are_extracted_as_metric_samples(tmp_path) -> None:
    _write_seed(
        tmp_path,
        [
            {
                "extaddr": "86:72:76:6A:E0:57:81:87",
                "role": "router",
                "mleCounters": {
                    "parentChanges": 6,
                    "partitionIdChanges": 4,
                    "betterPartitionAttachAttempts": 1,
                    "totalParentPartitionChangesCount": 11,
                },
                "timeStatistics": {"routerPct": 40.0, "detachedDisabledPct": 3.0},
            }
        ],
    )
    result = build_processing_result(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        allow_partial=True,
    )
    metrics_by_name = {metric.metric: metric for metric in result.observation.metrics}
    assert metrics_by_name["parentChanges"].value == 6
    assert metrics_by_name["partitionIdChanges"].value == 4
    assert metrics_by_name["betterPartitionAttachAttempts"].value == 1
    assert metrics_by_name["totalParentPartitionChanges"].value == 11
    assert metrics_by_name["routerRolePercent"].value == 40.0
    assert metrics_by_name["detachedDisabledPercent"].value == 3.0


def test_mac_counter_ratios_remain_unit_ratios(tmp_path) -> None:
    _write_seed(
        tmp_path,
        [
            {
                "extaddr": "0000000000000001",
                "macCounters": {"ifTotalPkts": 10, "ifTotalErrorsTotalPktsRatio": 0.0},
            },
            {
                "extaddr": "0000000000000002",
                "macCounters": {"ifTotalPkts": 10, "ifTotalErrorsTotalPktsRatio": 0.1},
            },
            {
                "extaddr": "0000000000000003",
                "macCounters": {"ifTotalPkts": 10, "ifTotalErrorsTotalPktsRatio": 0.5},
            },
        ],
    )

    result = build_processing_result(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
    )

    metrics = {
        metric.device_id: metric.value
        for metric in result.observation.metrics
        if metric.metric == "totalMacErrorRatio"
    }
    assert metrics == {
        "extaddr:0000000000000001": 0.0,
        "extaddr:0000000000000002": 0.1,
        "extaddr:0000000000000003": 0.5,
    }


def test_merged_dataset_normalizes_relationship_error_rates_by_file_source() -> None:
    dataset = load_health_manifest().dataset("merged_otbr_topology_mdns_health")
    payloads = {filename: [] for filename in dataset.files}
    payloads["td-otbr-cli-meshdiag-router-neighbortables.json"] = [
        {
            "extAddress": "0000000000000001",
            "routerNeighbors": [
                {"extAddress": "0000000000000002", "frameErrorRate": 0.5}
            ],
        },
        {
            "extAddress": "0000000000000003",
            "routerNeighbors": [
                {"extAddress": "0000000000000004", "frameErrorRate": 15}
            ],
        },
    ]
    payloads["td-otbr-restapi-mesh-diagnostics-fetch-all.json"] = [
        {
            "extAddress": "0000000000000005",
            "routerNeighbors": [
                {"extAddress": "0000000000000006", "frameErrorRate": 0.5}
            ],
        }
    ]

    _, relationships, _, _, _ = _normalize_samples(dataset, payloads)

    rates = {
        relationship.from_device_id: relationship.frame_error_rate
        for relationship in relationships
    }
    assert rates == {
        "extaddr:0000000000000001": 0.005,
        "extaddr:0000000000000003": 0.15,
        "extaddr:0000000000000005": 0.5,
    }


def test_response_timeout_record_is_captured_without_ext_address(tmp_path) -> None:
    _write_seed(
        tmp_path,
        [
            {
                "extaddr": "86:72:76:6A:E0:57:81:87",
                "role": "router",
                "rloc16": "0x1000",
            },
            {
                "rloc16": "0x1000",
                "device_label": "Timed Out Router",
                "error": {"type": "ResponseTimeout"},
            },
        ],
    )
    result = build_processing_result(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        allow_partial=True,
    )
    timeout_metrics = [m for m in result.observation.metrics if m.metric == "diagnosticTimeout"]
    assert len(timeout_metrics) == 1
    assert timeout_metrics[0].device_id == "extaddr:8672766ae0578187"


def test_duplicate_child_table_entries_are_flagged(tmp_path) -> None:
    _write_seed(
        tmp_path,
        [
            {
                "extaddr": "86:72:76:6A:E0:57:81:87",
                "role": "router",
                "childTable": [
                    {"extAddress": "2222222222222222", "linkQuality": 3, "queuedMessageCount": 2},
                    {"extAddress": "2222222222222222", "linkQuality": 3, "queuedMessageCount": 2},
                ],
            }
        ],
    )
    result = build_processing_result(
        data_dir=tmp_path,
        dataset_id="otbr_cli_networkdiag_fetch_all",
        policy=load_health_policy(),
        allow_partial=True,
    )
    assert len(result.observation.duplicate_relationship_ids) == 1
    relationship = result.observation.relationships[0]
    assert relationship.queued_message_count == 2