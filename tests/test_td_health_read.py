"""Tests for bounded, grouped health read projections."""

from __future__ import annotations

import json
import os

from td_health_read import TDHealthReadService
from td_health_sqlite import SQLiteHealthStore
from test_td_health_sqlite import _result


def test_assessment_projection_groups_losslessly_and_resolves_labels(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "td-health.db")
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
            "device.mle-parent-changes",
            "device.other",
            "device.totalMacErrorRatio",
            "relationship.directional-quality",
            "relationship.bidirectional-lq3",
            "network.observed-link-quality-ratios",
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
        "device.observed",
        "device.missing",
        "device.offline",
        "network.observed-link-quality-ratios",
        "relationship.bidirectional-lq3",
        "relationship.directional-quality",
        "device.totalMacErrorRatio",
        "device.mle-parent-changes",
        "device.attachment-failure",
        "device.other",
    ]
    assert [group["title"] for group in groups[:5]] == [
        "Border Router Redundancy",
        "Router Redundancy",
        "Router path redundancy",
        "Observed Devices",
        "Missing from latest observation",
    ]


def test_observation_page_is_bounded(tmp_path) -> None:
    store = SQLiteHealthStore(tmp_path / "td-health.db")
    for suffix in ("1", "2", "3"):
        store.save_processing_result(*_result(suffix))

    page = TDHealthReadService(tmp_path).observations(
        network_id=None, limit=2, offset=1
    )
    assert page["limit"] == 2
    assert page["offset"] == 1
    assert len(page["items"]) == 2


def test_read_service_does_not_modify_or_initialize_store(tmp_path) -> None:
    database_path = tmp_path / "td-health.db"
    SQLiteHealthStore(database_path).save_processing_result(*_result())
    before = (database_path.read_bytes(), os.stat(database_path).st_mtime_ns)

    TDHealthReadService(tmp_path).capabilities()

    assert (database_path.read_bytes(), os.stat(database_path).st_mtime_ns) == before


def test_assessment_findings_are_filtered_and_bounded(tmp_path) -> None:
    SQLiteHealthStore(tmp_path / "td-health.db").save_processing_result(*_result())

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