"""Safety tests for cache-only health processing and evaluation."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from td_health_observation_model import Completeness, HealthStatus
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_policy import load_health_policy
from td_health_processor import HealthProcessingError, build_processing_result, process_health
from td_health_sqlite import SQLiteHealthStore


def _write_seed(data_dir, devices, *, extpan="78b9775b001c1cbe"):
    (data_dir / "td-otbr-cli-thread-network-info.json").write_text(
        json.dumps({"extPanId": extpan, "networkName": "mutable-name"}),
        encoding="utf-8",
    )
    (data_dir / "td-otbr-cli-networkdiag-fetch-all.json").write_text(
        json.dumps(devices), encoding="utf-8"
    )


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