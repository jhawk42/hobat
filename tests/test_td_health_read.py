"""Tests for bounded, grouped health read projections."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import replace

import pytest

from td_health_evaluator import evaluate_observation
from td_health_manifest import load_health_manifest
from td_health_observation_model import (
    Completeness,
    DeviceSample,
    FindingRank,
    HealthStatus,
    MetricSample,
    RelationshipSample,
    SourceEvidence,
)
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_policy import load_health_policy
from td_health_read import TDHealthReadService
from td_health_sqlite import SQLiteHealthStore
from test_td_health_sqlite import _result


def test_assessment_projection_groups_losslessly_and_resolves_labels(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    observation, assessment = _result()
    store.save_processing_result(observation, assessment)
    (tmp_path / "td-static-extaddr-device-label.json").write_text(
        json.dumps([
            {"extAddress": "8672766ae0578187", "deviceLabel": "Office Router"}
        ]),
        encoding="utf-8",
    )

    result = TDHealthReadService(tmp_path).assessment(
        dataset_id="otbr_cli_networkdiag_fetch_all", grouped=True
    )

    assert result is not None
    assert result["schemaVersion"] == 2
    assert result["evaluatorVersion"] == "snapshot-test"
    assert result["profileId"] == "profile-test"
    assert result["assessmentId"] == assessment.assessment_id
    assert result["findingCount"] == len(assessment.findings)
    assert sum(group["count"] for group in result["findingGroups"]) == len(
        assessment.findings
    )
    for group in result["findingGroups"]:
        assert len(group["endpoints"]) == len(group["deviceIds"])

    device = TDHealthReadService(tmp_path).device(
        assessment_id=assessment.assessment_id,
        device_id="extaddr:8672766ae0578187",
    )
    assert device is not None
    assert device["displayName"] == "Office Router"
    assert device["deviceId"] == "extaddr:8672766ae0578187"
    assert "device_id" not in device


def test_reprocessing_snapshot_counts_preserves_prior_assessment_and_projection(
    tmp_path,
) -> None:
    observation, _ = _result()
    metric = MetricSample(
        observation.devices[0].device_id,
        "parentChanges",
        6,
        "count",
        None,
        "snapshot.json",
    )
    second_device_id = "extaddr:1122334455667788"
    observation = replace(
        observation,
        devices=observation.devices + (
            DeviceSample(
                second_device_id,
                "1122334455667788",
                "router",
                None,
                False,
                ("snapshot.json",),
            ),
        ),
        relationships=(
            RelationshipSample(
                "link:child",
                "parent-child",
                observation.devices[0].device_id,
                second_device_id,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                observation.devices[0].device_id,
                ("snapshot.json",),
                5,
            ),
        ),
        metrics=(metric,),
    )
    profile = load_health_manifest().dataset(
        "otbr_cli_topology_mdns_health"
    ).health_profile
    current = evaluate_observation(
        observation, load_health_policy(), profile=profile
    )
    current_finding = next(
        finding
        for finding in current.findings
        if finding.rule_id == "device.parentChanges"
    )
    legacy_finding = replace(
        current_finding,
        status=HealthStatus.UNKNOWN,
        rank=FindingRank.INFO,
        summary="Legacy evidence-only counter finding.",
    )
    current_queue_finding = next(
        finding
        for finding in current.findings
        if finding.rule_id == "relationship.queued-messages"
    )
    legacy_queue_evidence = {
        key: value
        for key, value in current_queue_finding.evidence.items()
        if key not in {"band", "thresholds"}
    }
    legacy_queue_evidence["materiality"] = "informational"
    legacy_queue_finding = replace(
        current_queue_finding,
        status=HealthStatus.UNKNOWN,
        rank=FindingRank.INFO,
        summary="Legacy informational queue evidence.",
        evidence=legacy_queue_evidence,
    )
    legacy = replace(
        current,
        assessment_id="assessment:legacy-snapshot-v10",
        policy_digest="legacy-policy-digest",
        evaluator_version="snapshot-v10",
        status=HealthStatus.UNKNOWN,
        findings=tuple(
            legacy_finding if finding is current_finding
            else legacy_queue_finding if finding is current_queue_finding
            else finding
            for finding in current.findings
        ),
    )

    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    store.save_processing_result(observation, legacy)
    store.save_processing_result(observation, current)
    service = TDHealthReadService(tmp_path)
    old_projection = service.assessment(
        assessment_id=legacy.assessment_id, grouped=False
    )
    current_projection = service.assessment(
        assessment_id=current.assessment_id, grouped=False
    )
    current_groups = service.assessment(
        assessment_id=current.assessment_id, grouped=True
    )

    assert legacy.assessment_id != current.assessment_id
    assert old_projection is not None
    assert current_projection is not None
    assert old_projection["evaluatorVersion"] == "snapshot-v10"
    assert current_projection["evaluatorVersion"] == "snapshot-v11"
    assert next(
        finding for finding in old_projection["findings"]
        if finding["ruleId"] == "device.parentChanges"
    )["status"] == "unknown"
    old_queue_projection = next(
        finding for finding in old_projection["findings"]
        if finding["ruleId"] == "relationship.queued-messages"
    )
    assert old_queue_projection["status"] == "unknown"
    assert old_queue_projection["materiality"] == "informational"
    old_groups = service.assessment(
        assessment_id=legacy.assessment_id, grouped=True
    )
    old_queue_group = next(
        item for item in old_groups["findingGroups"]
        if item["ruleId"] == "relationship.queued-messages"
    )
    assert old_queue_group["status"] == "unknown"
    assert old_queue_group["findings"][0]["materiality"] == "informational"
    current_finding_projection = next(
        finding for finding in current_projection["findings"]
        if finding["ruleId"] == "device.parentChanges"
    )
    assert current_finding_projection["status"] == "moderate"
    assert current_finding_projection["evidence"]["band"] == "high"
    group = next(
        item for item in current_groups["findingGroups"]
        if item["ruleId"] == "device.parentChanges"
    )
    assert group["status"] == "moderate"
    assert group["findings"][0]["evidence"]["band"] == "high"
    current_queue_projection = next(
        finding for finding in current_projection["findings"]
        if finding["ruleId"] == "relationship.queued-messages"
    )
    assert current_queue_projection["status"] == "moderate"
    assert current_queue_projection["materiality"] == "relationship"
    assert current_queue_projection["evidence"]["band"] == "high"


def test_comparison_endpoint_pages_and_query_only_pair_projection(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    before, before_assessment = _result("1")
    after, after_assessment = _result("2")
    store.save_processing_result(before, before_assessment)
    store.save_processing_result(after, after_assessment)
    service = TDHealthReadService(tmp_path)

    after_page = service.comparison_endpoints(
        network_id=after.network_id, dataset_id=after.dataset_id,
        side="after", limit=1, offset=0,
    )
    assert after_page["items"][0]["assessmentId"] == after_assessment.assessment_id
    assert after_page["defaultAfter"]["assessmentId"] == after_assessment.assessment_id
    assert after_page["defaultBefore"]["assessmentId"] == before_assessment.assessment_id
    before_page = service.comparison_endpoints(
        network_id=after.network_id, dataset_id=after.dataset_id, side="before",
        after_assessment_id=after_assessment.assessment_id, limit=25, offset=0,
    )
    assert before_page["total"] == 1
    assert before_page["predecessor"]["assessmentId"] == before_assessment.assessment_id

    query = {
        "network_id": after.network_id,
        "dataset_id": after.dataset_id,
        "before_assessment_id": before_assessment.assessment_id,
        "after_assessment_id": after_assessment.assessment_id,
        "limit": 25,
        "offset": 0,
        "scope": "all",
        "result": "all",
    }
    stored = service.comparison_pair(**query)
    assert stored is not None and stored["origin"] == "stored"
    with sqlite3.connect(store.path) as connection:
        connection.execute("DELETE FROM comparison_items")
        connection.execute("DELETE FROM comparisons")
        connection.commit()
        before_counts = connection.execute(
            "SELECT (SELECT COUNT(*) FROM comparisons), "
            "(SELECT COUNT(*) FROM comparison_items)"
        ).fetchone()

    derived = service.comparison_pair(**query)
    assert derived is not None and derived["origin"] == "derived"
    assert derived["createdAt"] is None
    assert {
        key: value for key, value in stored.items() if key not in {"origin", "createdAt"}
    } == {
        key: value for key, value in derived.items() if key not in {"origin", "createdAt"}
    }
    with sqlite3.connect(store.path) as connection:
        after_counts = connection.execute(
            "SELECT (SELECT COUNT(*) FROM comparisons), "
            "(SELECT COUNT(*) FROM comparison_items)"
        ).fetchone()
    assert after_counts == before_counts == (0, 0)


def test_endpoint_inventory_orders_equivalent_utc_instants_and_rejects_same_time_before(
    tmp_path,
) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    first, first_assessment = _result("1")
    first = replace(first, observed_at="2026-09-01T00:00:02+02:00")
    first_assessment = replace(first_assessment, assessed_at="2026-09-01T00:00:02+02:00")
    same_time, same_time_assessment = _result("2")
    same_time = replace(same_time, observed_at="2026-08-31T22:00:02Z")
    same_time_assessment = replace(
        same_time_assessment, assessed_at="2026-08-31T22:00:02Z"
    )
    later, later_assessment = _result("3")
    later = replace(later, observed_at="2026-09-01T00:00:03+02:00")
    later_assessment = replace(later_assessment, assessed_at="2026-09-01T00:00:03+02:00")
    store.save_processing_result(first, first_assessment)
    store.save_processing_result(same_time, same_time_assessment)
    store.save_processing_result(later, later_assessment)

    service = TDHealthReadService(tmp_path)
    page = service.comparison_endpoints(
        network_id=later.network_id, dataset_id=later.dataset_id,
        side="after", limit=25, offset=0,
    )
    assert [item["assessmentId"] for item in page["items"]] == [
        later_assessment.assessment_id,
        same_time_assessment.assessment_id,
        first_assessment.assessment_id,
    ]
    before_page = service.comparison_endpoints(
        network_id=later.network_id, dataset_id=later.dataset_id,
        side="before", after_assessment_id=same_time_assessment.assessment_id,
        limit=25, offset=0,
    )
    assert before_page["items"] == []
    assert before_page["total"] == 0


def test_shortcut_candidates_use_full_retained_history_and_include_partials(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    latest = None
    for day in range(1, 32):
        observation, assessment = _result(str(day))
        timestamp = f"2026-01-{day:02d}T00:00:00Z"
        observation = replace(
            observation, observed_at=timestamp, ingested_at=timestamp,
            completeness=Completeness.PARTIAL if day == 1 else Completeness.COMPLETE,
        )
        assessment = replace(assessment, assessed_at=timestamp)
        store.save_processing_result(observation, assessment)
        if day == 31:
            latest = assessment
    assert latest is not None

    page = TDHealthReadService(tmp_path).comparison_endpoints(
        network_id="extpan:78b9775b001c1cbe",
        dataset_id="otbr_cli_networkdiag_fetch_all", side="after",
        limit=25, offset=0, selected_assessment_id=latest.assessment_id,
    )
    assert page["selectedAfter"]["assessmentId"] == latest.assessment_id
    assert len(page["items"]) == 25
    assert "assessment-1" not in {item["assessmentId"] for item in page["items"]}
    shortcuts = {item["interval"]: item for item in page["shortcuts"]}
    assert shortcuts["1d"]["candidate"]["assessmentId"] == "assessment-30"
    assert shortcuts["1m"]["candidate"]["assessmentId"] == "assessment-1"
    assert shortcuts["1m"]["candidate"]["completeness"] == "partial"


def test_derived_reset_witness_matches_stored_header(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    filename = "td-otbr-cli-networkdiag-fetch-all.json"
    before, before_assessment = _result("1")
    after, after_assessment = _result("2")
    before = replace(
        before,
        sources=(SourceEvidence(filename, "before", "final", "valid", before.observed_at),),
        metrics=(MetricSample(
            before.devices[0].device_id, "parentChanges", 9, "count", None, filename,
        ),),
    )
    after = replace(
        after,
        sources=(SourceEvidence(filename, "after", "final", "valid", after.observed_at),),
        metrics=(MetricSample(
            after.devices[0].device_id, "parentChanges", 2, "count", None, filename,
        ),),
    )
    store.save_processing_result(before, before_assessment)
    store.save_processing_result(after, after_assessment)
    service = TDHealthReadService(tmp_path)
    query = {
        "network_id": after.network_id,
        "dataset_id": after.dataset_id,
        "before_assessment_id": before_assessment.assessment_id,
        "after_assessment_id": after_assessment.assessment_id,
        "limit": 25,
        "offset": 0,
        "scope": "all",
        "result": "all",
    }
    stored = service.comparison_pair(**query)
    assert stored is not None
    assert stored["resetState"] == "reset-detected"
    assert stored["resetWitness"]
    with sqlite3.connect(store.path) as connection:
        connection.execute("DELETE FROM comparison_items")
        connection.execute("DELETE FROM comparisons")
        connection.commit()
    derived = service.comparison_pair(**query)
    assert derived is not None
    assert derived["resetState"] == stored["resetState"]
    assert derived["resetWitness"] == stored["resetWitness"]
    assert [
        (item["itemId"], item["resetState"], item["resetWitness"])
        for item in derived["items"]
    ] == [
        (item["itemId"], item["resetState"], item["resetWitness"])
        for item in stored["items"]
    ]


def test_derived_comparison_rejects_corrupt_source_timestamps(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    filename = "td-otbr-cli-networkdiag-fetch-all.json"
    before, before_assessment = _result("1")
    after, after_assessment = _result("2")
    before = replace(
        before,
        sources=(SourceEvidence(filename, "before", "final", "valid", before.observed_at),),
    )
    after = replace(
        after,
        sources=(SourceEvidence(filename, "after", "final", "valid", after.observed_at),),
    )
    store.save_processing_result(before, before_assessment)
    store.save_processing_result(after, after_assessment)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DELETE FROM comparison_items")
        connection.execute("DELETE FROM comparisons")
        connection.execute(
            "UPDATE observation_sources SET source_observed_at='broken' "
            "WHERE observation_id=?", (before.observation_id,),
        )
        connection.commit()

    with pytest.raises(sqlite3.DatabaseError, match="Invalid stored health timestamp"):
        TDHealthReadService(tmp_path).comparison_pair(
            network_id=after.network_id, dataset_id=after.dataset_id,
            before_assessment_id=before_assessment.assessment_id,
            after_assessment_id=after_assessment.assessment_id,
            limit=25, offset=0,
        )


def test_pinned_roster_includes_observed_without_facts_and_designation_only(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    observation, assessment = _result()
    store.save_processing_result(observation, assessment)
    expected_id = "extaddr:0000000000000001"
    store.upsert_expected_device(observation.network_id, expected_id, "Alpha")
    service = TDHealthReadService(tmp_path)

    observed = service.roster(network_id=observation.network_id,
                              assessment_id=assessment.assessment_id)
    assert observed["schemaVersion"] == 2
    assert observed["total"] == 2 and observed["filteredTotal"] == 1
    assert observed["activeExpectedTotal"] == 1
    assert observed["devices"][0]["presenceState"] == "observed"
    assert observed["devices"][0]["rosterState"] == "untracked"

    page = service.roster(network_id=observation.network_id,
                          assessment_id=assessment.assessment_id, presence="all",
                          sort="label", limit=1)
    assert page["filteredTotal"] == 2
    assert page["devices"][0]["deviceId"] == expected_id
    assert page["devices"][0]["presenceState"] == "not-assessed"
    assert service.roster_device(network_id=observation.network_id,
                                 device_id=expected_id)["fields"]["deviceLabel"]["freshness"] == "absent"
    second = service.roster(network_id=observation.network_id,
                            assessment_id=assessment.assessment_id, presence="all",
                            sort="label", limit=1, offset=1)
    assert second["devices"][0]["deviceId"] == observation.devices[0].device_id
    assert service.roster(network_id=observation.network_id,
                          assessment_id=assessment.assessment_id, presence="not-assessed")["filteredTotal"] == 1

    try:
        service.roster(network_id="extpan:0000000000000000",
                       assessment_id=assessment.assessment_id)
    except ValueError:
        pass
    else:
        raise AssertionError("Cross-network assessment was accepted")


def test_pinned_roster_sorts_and_filters_complete_population_before_paging(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    observation, assessment = _result()
    store.save_processing_result(observation, assessment)
    for index in range(30):
        store.upsert_expected_device(observation.network_id, f"extaddr:{index:016x}",
                                     "Same" if index in (0, 29) else f"Room {index:02d}")
    service = TDHealthReadService(tmp_path)
    page = service.roster(network_id=observation.network_id,
                          assessment_id=assessment.assessment_id, presence="all", limit=25)
    assert page["total"] == page["filteredTotal"] == 31
    assert page["devices"][0]["displayLabel"] == "Room 01"
    second = service.roster(network_id=observation.network_id,
                            assessment_id=assessment.assessment_id, presence="all", limit=25, offset=25)
    assert second["devices"][3]["displayLabel"] == "Same · 00000000 (duplicate label)"
    assert second["devices"][4]["displayLabel"] == "Same · 0000001d (duplicate label)"
    filtered = service.roster(network_id=observation.network_id,
                              assessment_id=assessment.assessment_id, presence="not-assessed",
                              roster_state="expected", q="room", limit=5, offset=5)
    assert filtered["filteredTotal"] == 28
    assert filtered["devices"][0]["displayLabel"] == "Room 06"
    for sort in ("label", "presence", "rosterState", "lastObserved", "quality"):
        for direction in ("ascending", "descending"):
            ordered = service.roster(network_id=observation.network_id,
                                     assessment_id=assessment.assessment_id,
                                     presence="all", sort=sort, direction=direction, limit=100)
            assert len({device["deviceId"] for device in ordered["devices"]}) == 31
            if sort == "lastObserved":
                assert ordered["devices"][0]["deviceId"] == observation.devices[0].device_id
            if sort == "quality":
                assert ordered["devices"][0]["deviceId"] == "extaddr:0000000000000000"


def test_finding_groups_follow_operator_presentation_order() -> None:
    findings = [
        {
            "ruleId": rule_id,
            "status": "moderate",
            "scope": "device",
            "rank": 1,
            "title": rule_id,
            "summary": "summary",
            "confidence": "high",
            "deviceIds": [],
            "relationshipIds": [],
            "endpoints": [],
        }
        for rule_id in (
            "device.attachment-failure",
            "device.parentChanges",
            "device.other",
            "device.totalMacErrorRatio",
            "relationship.queued-messages",
            "relationship.directional-quality",
            "relationship.bidirectional-lq3",
            "network.observed-link-quality-ratios",
            "observation.duplicate-source-entry",
            "device.diagnostic-timeout",
            "device.multiple-reporters-high-error",
            "device.offline",
            "device.missing",
            "device.observed",
            "network.current-path-redundancy",
            "network.router-redundancy",
            "network.border-router-redundancy",
        )
    ]

    groups = TDHealthReadService._group_findings(findings)

    assert [group["ruleId"] for group in groups] == [
        "network.border-router-redundancy",
        "network.router-redundancy",
        "network.current-path-redundancy",
        "network.observed-link-quality-ratios",
        "observation.duplicate-source-entry",
        "device.observed",
        "device.missing",
        "device.offline",
        "device.diagnostic-timeout",
        "device.multiple-reporters-high-error",
        "device.parentChanges",
        "device.totalMacErrorRatio",
        "device.attachment-failure",
        "device.other",
        "relationship.bidirectional-lq3",
        "relationship.directional-quality",
        "relationship.queued-messages",
    ]
    assert [group["title"] for group in groups[:5]] == [
        "Border Router Redundancy",
        "Router Redundancy",
        "Router Path Redundancy",
        "Network Link Quality Distribution",
        "Duplicate Relationships in Source Data",
    ]


def test_directional_quality_variants_form_distinct_groups() -> None:
    base = {
        "ruleId": "relationship.directional-quality",
        "status": "moderate",
        "scope": "relationship",
        "rank": 20,
        "title": "Link Quality or Delivery Degradation",
        "summary": "summary",
        "confidence": "high",
        "deviceIds": [],
        "relationshipIds": [],
        "endpoints": [],
    }

    groups = TDHealthReadService._group_findings(
        [
            {**base, "presentationVariant": None},
            {**base, "presentationVariant": "delivery-errors-adequate-signal"},
        ]
    )

    assert len(groups) == 2
    assert {group["title"] for group in groups} == {
        "Link Quality or Delivery Degradation",
        "High Delivery Errors Despite Acceptable Signal",
    }


def test_legacy_assessment_projects_catalog_metadata_and_unknown_fallback(tmp_path) -> None:
    database_path = tmp_path / HOBAT_DATABASE_FILENAME
    store = SQLiteHealthStore(database_path)
    store.save_processing_result(*_result())
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE assessments SET evaluator_version='legacy-unknown', profile_id='legacy-unknown'"
        )
        connection.executemany(
            "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    "assessment-1", "known-legacy", "relationship.directional-quality",
                    "moderate", "relationship", 20,
                    "High Delivery Errors Despite Acceptable Signal", "Legacy summary",
                    "Legacy description", '{"evidenceKind":"current"}', "medium",
                    "Legacy action", "Legacy verify", "[]", "[]", "[]",
                ),
                (
                    "assessment-1", "unknown-legacy", "legacy.rule", "unknown",
                    "device", 10, "Legacy title", "Legacy summary", "Legacy description",
                    "{}", "low", "Legacy action", "Legacy verify", "[]", "[]", "[]",
                ),
            ),
        )

    result = TDHealthReadService(tmp_path).assessment(
        assessment_id="assessment-1", grouped=False
    )

    assert result is not None
    assert result["evaluatorVersion"] == "legacy-unknown"
    findings = {finding["findingId"]: finding for finding in result["findings"]}
    known = findings["known-legacy"]
    assert known["presentationVariant"] == "delivery-errors-adequate-signal"
    assert known["title"] == "High Delivery Errors Despite Acceptable Signal"
    assert known["evidenceKind"] == known["evidence"]["evidenceKind"] == "snapshot"
    assert known["materiality"] == known["evidence"]["materiality"] == "relationship"
    assert known["actionKey"] == "health.relationship.directional-quality.action"
    assert known["verificationKey"] == "health.relationship.directional-quality.verify"
    assert known["whyItMatters"] != "Legacy description"

    unknown = findings["unknown-legacy"]
    assert unknown["title"] == "Legacy title"
    assert unknown["whyItMatters"] == "Legacy description"
    assert unknown["evidenceKind"] == "historical"
    assert unknown["materiality"] == "informational"
    assert unknown["actionKey"] == "health.legacy.rule.action"
    assert unknown["verificationKey"] == "health.legacy.rule.verify"


def test_observation_page_is_bounded(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME)
    for suffix in ("1", "2", "3"):
        store.save_processing_result(*_result(suffix))

    page = TDHealthReadService(tmp_path).observations(
        network_id=None, limit=2, offset=1
    )
    assert page["limit"] == 2
    assert page["offset"] == 1
    assert len(page["items"]) == 2


def test_read_service_does_not_modify_or_initialize_store(tmp_path) -> None:
    database_path = tmp_path / HOBAT_DATABASE_FILENAME
    SQLiteHealthStore(database_path).save_processing_result(*_result())
    before = (database_path.read_bytes(), os.stat(database_path).st_mtime_ns)

    TDHealthReadService(tmp_path).capabilities()

    assert (database_path.read_bytes(), os.stat(database_path).st_mtime_ns) == before


def test_assessment_findings_are_filtered_and_bounded(tmp_path) -> None:
    SQLiteHealthStore(tmp_path / HOBAT_DATABASE_FILENAME).save_processing_result(*_result())

    result = TDHealthReadService(tmp_path).assessment(
        assessment_id="assessment-1",
        grouped=False,
        scope="device",
        limit=1,
        offset=0,
    )

    assert result is not None
    assert len(result["findings"]) <= 1
    assert all(finding["scope"] == "device" for finding in result["findings"])