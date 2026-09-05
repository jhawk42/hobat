"""Tests for bounded, grouped health read projections."""

from __future__ import annotations

import json
import os
import sqlite3

from td_health_observation_store import HOBAT_DATABASE_FILENAME
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