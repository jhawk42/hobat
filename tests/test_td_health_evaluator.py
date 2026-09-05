"""Pure evaluator tests for directional quality and materiality."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest

from td_health_evaluator import EVALUATOR_VERSION, evaluate_observation
from td_health_observation_model import (
    Completeness,
    DeviceSample,
    HealthStatus,
    MetricSample,
    Observation,
    RelationshipSample,
)
from td_health_policy import load_health_policy
from td_health_manifest import load_health_manifest
from td_health_rules import HealthRuleCatalogError


PROFILE = load_health_manifest().dataset(
    "otbr_cli_topology_mdns_health"
).health_profile


def _observation(relationship: RelationshipSample) -> Observation:
    devices = tuple(
        DeviceSample(device_id, device_id.removeprefix("extaddr:"), "router", None, False, ("source.json",))
        for device_id in (relationship.from_device_id, relationship.to_device_id)
    )
    return Observation(
        "observation:test",
        "otbr-cli",
        "otbr_cli_topology_mdns_health",
        "extpan:78b9775b001c1cbe",
        "test",
        "2026-09-01T00:00:00+00:00",
        "2026-09-01T00:00:00+00:00",
        Completeness.COMPLETE,
        "digest",
        (),
        devices,
        (relationship,),
    )


def _relationship(**overrides) -> RelationshipSample:
    values = {
        "relationship_id": "link:test",
        "relationship_type": "router-neighbor",
        "from_device_id": "extaddr:1111111111111111",
        "to_device_id": "extaddr:2222222222222222",
        "link_quality_in": 3,
        "link_quality_out": 3,
        "average_rssi": -50.0,
        "last_rssi": -50.0,
        "link_margin": 40.0,
        "frame_error_rate": 0.0,
        "message_error_rate": 0.0,
        "reporter_device_id": "extaddr:1111111111111111",
        "source_files": ("source.json",),
    }
    values.update(overrides)
    return RelationshipSample(**values)


def test_bidirectional_lq3_is_positive_evidence() -> None:
    assessment = evaluate_observation(
        _observation(_relationship()), load_health_policy(), profile=PROFILE
    )
    assert any(f.rule_id == "relationship.bidirectional-lq3" for f in assessment.findings)


def test_same_device_metric_from_multiple_sources_has_unique_finding_ids() -> None:
    observation = replace(
        _observation(_relationship()),
        metrics=(
            MetricSample(
                "extaddr:1111111111111111",
                "parentChanges",
                9.0,
                "count",
                None,
                "source-a.json",
            ),
            MetricSample(
                "extaddr:1111111111111111",
                "parentChanges",
                12.0,
                "count",
                None,
                "source-b.json",
            ),
        ),
    )

    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)
    metric_findings = [
        finding
        for finding in assessment.findings
        if finding.rule_id == "device.parentChanges"
    ]

    assert len(metric_findings) == 2
    assert len({finding.finding_id for finding in metric_findings}) == 2


def test_complete_topology_profile_reports_border_router_redundancy() -> None:
    observation = _observation(_relationship())
    source_files = (
        "td-otbr-cli-meshdiag-topology.json",
        "td-otbr-cli-networkdiag-fetch-all.json",
        "td-mdns-scopes-thread.json",
    )
    observation = replace(
        observation,
        devices=(
            DeviceSample(
                "extaddr:1111111111111111",
                "1111111111111111",
                "router",
                None,
                True,
                source_files,
            ),
            DeviceSample(
                "extaddr:2222222222222222",
                "2222222222222222",
                "router",
                None,
                False,
                source_files,
            ),
            DeviceSample(
                "extaddr:3333333333333333",
                "3333333333333333",
                "child",
                None,
                True,
                source_files,
            ),
        ),
    )

    assessment = evaluate_observation(
        observation, load_health_policy(), profile=PROFILE
    )
    border_router_finding = next(
        finding
        for finding in assessment.findings
        if finding.rule_id == "network.border-router-redundancy"
    )
    router_finding = next(
        finding
        for finding in assessment.findings
        if finding.rule_id == "network.router-redundancy"
    )

    assert PROFILE.border_router_authority is True
    assert EVALUATOR_VERSION == "snapshot-v10"
    assert border_router_finding.status is HealthStatus.STRONG
    assert border_router_finding.evidence["observedBorderRouterCount"] == 2
    assert border_router_finding.evidence["moreThanOne"] is True
    assert border_router_finding.device_ids == (
        "extaddr:1111111111111111",
        "extaddr:3333333333333333",
    )
    assert border_router_finding.source_files == tuple(sorted(source_files))
    assert router_finding.device_ids == (
        "extaddr:1111111111111111",
        "extaddr:2222222222222222",
    )


def test_partial_authoritative_profile_reports_provisional_border_router_redundancy() -> None:
    observation = replace(
        _observation(_relationship()),
        completeness=Completeness.PARTIAL,
        devices=(
            DeviceSample(
                "extaddr:1111111111111111",
                "1111111111111111",
                "router",
                None,
                True,
                ("source.json",),
            ),
            DeviceSample(
                "extaddr:2222222222222222",
                "2222222222222222",
                "router",
                None,
                True,
                ("source.json",),
            ),
        ),
    )

    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)
    finding = next(
        finding
        for finding in assessment.findings
        if finding.rule_id == "network.border-router-redundancy"
    )

    assert finding.status is HealthStatus.UNKNOWN
    assert finding.evidence["observedBorderRouterCount"] == 2
    assert "provisional" in finding.summary


def test_profile_capability_changes_assessment_identity() -> None:
    observation = _observation(_relationship())
    policy = load_health_policy()
    original = evaluate_observation(observation, policy, profile=PROFILE)
    changed_profile = replace(
        PROFILE,
        coverage=MappingProxyType({**PROFILE.coverage, "externalRouting": "missing"}),
    )
    changed = evaluate_observation(observation, policy, profile=changed_profile)

    assert changed.assessment_id != original.assessment_id


def test_border_router_address_in_omr_prefix_is_strong_external_routing() -> None:
    observation = _observation(_relationship())
    source_files = (
        "td-otbr-cli-meshdiag-topology.json",
        "td-otbr-cli-networkdiag-fetch-all.json",
        "td-mdns-scopes-thread.json",
    )
    observation = replace(
        observation,
        devices=(
            DeviceSample(
                "extaddr:1111111111111111",
                "1111111111111111",
                "router",
                None,
                True,
                source_files,
            ),
            DeviceSample(
                "extaddr:2222222222222222",
                "2222222222222222",
                "router",
                None,
                False,
                source_files,
            ),
        ),
    )

    assessment = evaluate_observation(
        observation,
        load_health_policy(),
        profile=PROFILE,
        omr_prefix="fd6b:32e0:d18:0",
        device_ipv6_addresses={
            "extaddr:1111111111111111": ("fd6b:32e0:d18:0:1234:5678:9abc:def0",),
        },
    )
    finding = next(
        finding for finding in assessment.findings if finding.rule_id == "network.external-routing"
    )

    assert finding.status is HealthStatus.STRONG
    assert finding.evidence["omrBorderRouterIds"] == ("extaddr:1111111111111111",)


def test_border_router_without_omr_address_is_moderate_external_routing() -> None:
    observation = _observation(_relationship())
    source_files = (
        "td-otbr-cli-meshdiag-topology.json",
        "td-otbr-cli-networkdiag-fetch-all.json",
        "td-mdns-scopes-thread.json",
    )
    observation = replace(
        observation,
        devices=(
            DeviceSample(
                "extaddr:1111111111111111",
                "1111111111111111",
                "router",
                None,
                True,
                source_files,
            ),
        ),
    )

    assessment = evaluate_observation(
        observation,
        load_health_policy(),
        profile=PROFILE,
        omr_prefix="fd6b:32e0:d18:0",
        device_ipv6_addresses={
            "extaddr:1111111111111111": ("fd3b:a255:4aa6:5483:0:ff:fe00:1",),
        },
    )
    finding = next(
        finding for finding in assessment.findings if finding.rule_id == "network.external-routing"
    )

    assert finding.status is HealthStatus.MODERATE
    assert finding.evidence["omrBorderRouterIds"] == ()


def test_missing_omr_prefix_omits_external_routing_finding() -> None:
    assessment = evaluate_observation(
        _observation(_relationship()), load_health_policy(), profile=PROFILE
    )
    assert not any(finding.rule_id == "network.external-routing" for finding in assessment.findings)


def test_critical_delivery_only_escalates_on_observed_sole_path() -> None:
    relationship = _relationship(frame_error_rate=0.35)
    assessment = evaluate_observation(
        _observation(relationship), load_health_policy(), profile=PROFILE
    )
    finding = next(f for f in assessment.findings if f.rule_id == "relationship.directional-quality")
    assert finding.status is HealthStatus.POOR
    assert finding.evidence["solePath"] is True


def test_critical_child_delivery_escalates_on_one_observed_parent() -> None:
    relationship = _relationship(
        relationship_type="parent-child",
        frame_error_rate=0.30,
    )
    observation = replace(
        _observation(relationship),
        devices=(
            DeviceSample("extaddr:1111111111111111", "1" * 16, "router", None, False, ("source.json",)),
            DeviceSample("extaddr:2222222222222222", "2" * 16, "child", None, False, ("source.json",)),
        ),
    )

    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)
    finding = next(
        finding
        for finding in assessment.findings
        if finding.rule_id == "relationship.directional-quality"
    )

    assert finding.status is HealthStatus.POOR
    assert finding.evidence["pathBasis"] == "sole-parent"
    assert finding.evidence["observedParentCount"] == 1


def test_critical_router_delivery_stays_moderate_with_alternate_path() -> None:
    devices = tuple(
        DeviceSample(
            f"extaddr:{value * 16}", value * 16, "router", None, False, ("source.json",)
        )
        for value in ("1", "2", "3")
    )
    relationships = (
        _relationship(frame_error_rate=0.35),
        _relationship(
            relationship_id="link:2-3",
            from_device_id=devices[1].device_id,
            to_device_id=devices[2].device_id,
        ),
        _relationship(
            relationship_id="link:3-1",
            from_device_id=devices[2].device_id,
            to_device_id=devices[0].device_id,
        ),
    )
    observation = replace(_observation(relationships[0]), devices=devices, relationships=relationships)

    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)
    finding = next(
        finding
        for finding in assessment.findings
        if finding.rule_id == "relationship.directional-quality"
        and finding.relationship_ids == ("link:test",)
    )

    assert finding.status is HealthStatus.MODERATE
    assert finding.evidence["pathBasis"] == "router-bridge"
    assert finding.evidence["bridge"] is False


def test_child_with_two_observed_parents_is_not_a_sole_path() -> None:
    child_id = "extaddr:3333333333333333"
    first = _relationship(
        relationship_id="link:parent-1",
        relationship_type="parent-child",
        to_device_id=child_id,
        frame_error_rate=0.30,
    )
    second = _relationship(
        relationship_id="link:parent-2",
        relationship_type="parent-child",
        from_device_id="extaddr:4444444444444444",
        to_device_id=child_id,
    )
    observation = replace(
        _observation(first),
        devices=(
            DeviceSample("extaddr:1111111111111111", "1" * 16, "router", None, False, ("source.json",)),
            DeviceSample("extaddr:4444444444444444", "4" * 16, "router", None, False, ("source.json",)),
            DeviceSample(child_id, "3" * 16, "child", None, False, ("source.json",)),
        ),
        relationships=(first, second),
    )

    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)
    finding = next(
        finding
        for finding in assessment.findings
        if finding.rule_id == "relationship.directional-quality"
    )

    assert finding.status is HealthStatus.MODERATE
    assert finding.evidence["pathBasis"] == "sole-parent"
    assert finding.evidence["observedParentCount"] == 2
    assert finding.evidence["solePath"] is False


def test_child_relationship_does_not_count_as_alternate_router_path() -> None:
    router_relationship = _relationship()
    child_relationship = _relationship(
        relationship_id="link:child",
        relationship_type="parent-child",
        to_device_id="extaddr:3333333333333333",
    )
    observation = _observation(router_relationship)
    observation = replace(
        observation,
        devices=observation.devices
        + (
            DeviceSample(
                "extaddr:3333333333333333",
                "3333333333333333",
                "child",
                None,
                False,
                ("source.json",),
            ),
        ),
        relationships=(router_relationship, child_relationship),
    )

    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)
    finding = next(
        finding
        for finding in assessment.findings
        if finding.rule_id == "network.current-path-redundancy"
    )

    assert finding.status is HealthStatus.MODERATE
    assert finding.evidence["bridgeRelationshipIds"] == ("link:test",)
    assert finding.evidence["articulationDeviceIds"] == ()
    assert finding.evidence["routerNeighborDegrees"] == {
        "extaddr:1111111111111111": 1,
        "extaddr:2222222222222222": 1,
    }
    assert "link:child" not in finding.evidence["bridgeRelationshipIds"]


def test_lifetime_counter_metrics_are_evidence_only_and_do_not_change_status() -> None:
    observation = _observation(_relationship())
    observation = Observation(
        **{
            **observation.__dict__,
            "metrics": (
                MetricSample(
                    "extaddr:1111111111111111", "parentChanges", 6, "count", None, "source.json"
                ),
                MetricSample(
                    "extaddr:1111111111111111", "routerRolePercent", 40.0, "percent", None, "source.json"
                ),
            ),
        }
    )
    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)
    parent_changes = next(f for f in assessment.findings if f.rule_id == "device.parentChanges")
    router_pct = next(f for f in assessment.findings if f.rule_id == "device.routerRolePercent")

    assert parent_changes.status is HealthStatus.UNKNOWN
    assert parent_changes.evidence["band"] == "high"
    assert router_pct.status is HealthStatus.UNKNOWN
    assert router_pct.evidence["band"] == "high"
    assert not any(
        finding.rule_id in {"device.parentChanges", "device.routerRolePercent"}
        and finding.status in {HealthStatus.MODERATE, HealthStatus.POOR}
        for finding in assessment.findings
    )


def test_role_specific_metric_is_omitted_for_unknown_role() -> None:
    observation = replace(
        _observation(_relationship()),
        devices=tuple(replace(device, role=None) for device in _observation(_relationship()).devices),
        metrics=(
            MetricSample(
                "extaddr:1111111111111111",
                "parentChanges",
                9,
                "count",
                None,
                "source.json",
            ),
        ),
    )

    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)

    assert not any(
        finding.rule_id == "device.parentChanges" for finding in assessment.findings
    )


def test_source_required_metric_rejects_missing_source_attribution() -> None:
    observation = replace(
        _observation(_relationship()),
        metrics=(
            MetricSample(
                "extaddr:1111111111111111",
                "parentChanges",
                9,
                "count",
                None,
                "",
            ),
        ),
    )

    with pytest.raises(HealthRuleCatalogError, match="requires source evidence"):
        evaluate_observation(observation, load_health_policy(), profile=PROFILE)


def test_diagnostic_timeout_produces_evidence_only_finding_and_coverage() -> None:
    observation = _observation(_relationship())
    observation = Observation(
        **{
            **observation.__dict__,
            "metrics": (
                MetricSample(
                    "extaddr:1111111111111111", "diagnosticTimeout", 1.0, "flag", None, "source.json"
                ),
            ),
        }
    )
    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)
    finding = next(f for f in assessment.findings if f.rule_id == "device.diagnostic-timeout")

    assert finding.status is HealthStatus.UNKNOWN
    assert finding.device_ids == ("extaddr:1111111111111111",)
    assert assessment.coverage["diagnosticTimeoutDeviceCount"] == 1
    assert assessment.coverage["diagnosticTimeoutRatio"] == 0.5


def test_mac_discard_ratio_escalates_to_poor_only_with_attachment_failure() -> None:
    observation = _observation(_relationship())
    observation = replace(
        observation,
        devices=tuple(
            replace(device, state="detached") if device.device_id == "extaddr:1111111111111111" else device
            for device in observation.devices
        ),
        metrics=(
            MetricSample(
                "extaddr:1111111111111111", "totalMacDiscardRatio", 1.5, "ratio", 100, "source.json"
            ),
        ),
    )
    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)
    finding = next(f for f in assessment.findings if f.rule_id == "device.totalMacDiscardRatio")

    assert finding.status is HealthStatus.POOR
    assert finding.evidence["severityTier"] == "critical"
    assert finding.evidence["escalatedByAttachmentFailure"] is True


def test_mac_discard_ratio_stays_moderate_without_attachment_failure() -> None:
    observation = _observation(_relationship())
    observation = replace(
        observation,
        metrics=(
            MetricSample(
                "extaddr:1111111111111111", "totalMacDiscardRatio", 1.5, "ratio", 100, "source.json"
            ),
        ),
    )
    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)
    finding = next(f for f in assessment.findings if f.rule_id == "device.totalMacDiscardRatio")

    assert finding.status is HealthStatus.MODERATE
    assert finding.evidence["severityTier"] == "critical"
    assert finding.evidence["escalatedByAttachmentFailure"] is False


def test_error_uncorrelated_with_rss_is_tagged_on_relationship_finding() -> None:
    relationship = _relationship(frame_error_rate=0.20, last_rssi=-50.0, link_margin=40.0)
    assessment = evaluate_observation(
        _observation(relationship), load_health_policy(), profile=PROFILE
    )
    finding = next(f for f in assessment.findings if f.rule_id == "relationship.directional-quality")

    assert finding.evidence["errorUncorrelatedWithRss"] is True
    assert finding.title == "High Delivery Errors Despite Acceptable Signal"
    assert finding.evidence["evidenceKind"] == "snapshot"
    assert finding.evidence["materiality"] == "relationship"


def test_multiple_reporters_high_error_aggregates_across_relationships() -> None:
    observation = _observation(_relationship())
    observation = replace(
        observation,
        devices=observation.devices
        + (DeviceSample("extaddr:3333333333333333", "3333333333333333", "router", None, False, ("source.json",)),),
        relationships=(
            _relationship(frame_error_rate=0.20),
            _relationship(
                relationship_id="link:test-2",
                from_device_id="extaddr:3333333333333333",
                frame_error_rate=0.20,
            ),
        ),
    )
    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)
    finding = next(
        f for f in assessment.findings if f.rule_id == "device.multiple-reporters-high-error"
    )

    assert finding.device_ids == ("extaddr:2222222222222222",)
    assert len(finding.relationship_ids) == 2
    assert finding.confidence.value == "high"


def test_queued_messages_are_evidence_only() -> None:
    relationship = _relationship(
        relationship_type="parent-child", queued_message_count=3
    )
    assessment = evaluate_observation(
        _observation(relationship), load_health_policy(), profile=PROFILE
    )
    finding = next(f for f in assessment.findings if f.rule_id == "relationship.queued-messages")

    assert finding.status is HealthStatus.UNKNOWN
    assert finding.evidence["queuedMessageCount"] == 3


def test_router_neighbor_queue_depth_is_not_applicable() -> None:
    assessment = evaluate_observation(
        _observation(_relationship(queued_message_count=3)),
        load_health_policy(),
        profile=PROFILE,
    )

    assert not any(
        finding.rule_id == "relationship.queued-messages"
        for finding in assessment.findings
    )


def test_device_offline_is_independent_of_network_impact_ratio() -> None:
    observation = _observation(_relationship())
    absent_id = "extaddr:3333333333333333"
    expected_ids = frozenset(
        {
            *(device.device_id for device in observation.devices),
            absent_id,
            *(f"extaddr:{value:016x}" for value in range(4, 11)),
        }
    )

    assessment = evaluate_observation(
        observation,
        load_health_policy(),
        profile=PROFILE,
        expected_device_ids=expected_ids,
        prior_complete_absences={absent_id: 1},
    )

    offline = next(
        finding
        for finding in assessment.findings
        if finding.rule_id == "device.offline"
    )
    assert offline.device_ids == (absent_id,)
    assert offline.status is HealthStatus.POOR
    assert not any(
        finding.rule_id == "network.offline-impact"
        for finding in assessment.findings
    )
    assert assessment.status is not HealthStatus.POOR


def test_one_device_roster_offline_emits_device_and_network_findings() -> None:
    absent_id = "extaddr:3333333333333333"
    observation = replace(_observation(_relationship()), devices=(), relationships=())

    assessment = evaluate_observation(
        observation,
        load_health_policy(),
        profile=PROFILE,
        expected_device_ids=frozenset({absent_id}),
        prior_complete_absences={absent_id: 1},
    )

    assert {finding.rule_id for finding in assessment.findings} >= {
        "device.offline",
        "network.offline-impact",
    }


def test_offline_ratio_at_policy_boundary_does_not_emit_network_impact() -> None:
    policy = replace(load_health_policy(), offline_poor_device_ratio_threshold=1 / 3)
    observation = _observation(_relationship())
    absent_id = "extaddr:3333333333333333"

    assessment = evaluate_observation(
        observation,
        policy,
        profile=PROFILE,
        expected_device_ids=frozenset(
            {*(device.device_id for device in observation.devices), absent_id}
        ),
        prior_complete_absences={absent_id: 1},
    )

    assert any(finding.rule_id == "device.offline" for finding in assessment.findings)
    assert not any(
        finding.rule_id == "network.offline-impact" for finding in assessment.findings
    )


def test_recovered_expected_device_is_not_missing_or_offline() -> None:
    observation = _observation(_relationship())
    recovered_id = observation.devices[0].device_id

    assessment = evaluate_observation(
        observation,
        load_health_policy(),
        profile=PROFILE,
        expected_device_ids=frozenset({recovered_id}),
        prior_complete_absences={recovered_id: 12},
    )

    assert not any(
        finding.rule_id in {"device.missing", "device.offline"}
        for finding in assessment.findings
    )


def test_offline_ratio_emits_separate_network_impact() -> None:
    observation = _observation(_relationship())
    absent_id = "extaddr:3333333333333333"

    assessment = evaluate_observation(
        observation,
        load_health_policy(),
        profile=PROFILE,
        expected_device_ids=frozenset(
            {*(device.device_id for device in observation.devices), absent_id}
        ),
        prior_complete_absences={absent_id: 1},
    )

    impact = next(
        finding
        for finding in assessment.findings
        if finding.rule_id == "network.offline-impact"
    )
    assert impact.status is HealthStatus.POOR
    assert impact.evidence["offlineDeviceIds"] == (absent_id,)
    assert assessment.status is HealthStatus.POOR


def test_partial_observation_cannot_establish_offline() -> None:
    observation = replace(
        _observation(_relationship()), completeness=Completeness.PARTIAL
    )
    absent_id = "extaddr:3333333333333333"

    assessment = evaluate_observation(
        observation,
        load_health_policy(),
        profile=PROFILE,
        expected_device_ids=frozenset({absent_id}),
        prior_complete_absences={absent_id: 10},
    )

    assert any(
        finding.rule_id == "device.missing" for finding in assessment.findings
    )
    assert not any(
        finding.rule_id in {"device.offline", "network.offline-impact"}
        for finding in assessment.findings
    )


def test_observed_coverage_is_distinct_from_profile_capability() -> None:
    assessment = evaluate_observation(
        replace(_observation(_relationship()), completeness=Completeness.PARTIAL),
        load_health_policy(),
        profile=PROFILE,
    )

    assert assessment.coverage["pillars"] == dict(PROFILE.coverage)
    assert assessment.coverage["observedPillars"]["connectivity"]["state"] == "limited"
    assert (
        assessment.coverage["observedPillars"]["connectivity"]["evidenceCounts"][
            "routerNeighborRelationships"
        ]
        == 1
    )


def test_duplicate_relationship_ids_produce_network_scope_finding() -> None:
    observation = _observation(_relationship())
    observation = replace(observation, duplicate_relationship_ids=("link:test",))
    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)
    finding = next(
        f for f in assessment.findings if f.rule_id == "observation.duplicate-source-entry"
    )

    assert finding.status is HealthStatus.UNKNOWN
    assert finding.relationship_ids == ("link:test",)


def test_mac_ratio_requires_denominator_backed_metric_and_lq_excludes_unknown() -> None:
    observation = _observation(_relationship())
    observation = Observation(
        **{
            **observation.__dict__,
            "metrics": (
                MetricSample(
                    "extaddr:1111111111111111",
                    "totalMacDiscardRatio",
                    0.09,
                    "ratio",
                    1000,
                    "source.json",
                ),
                MetricSample("extaddr:1111111111111111", "observedLinkQuality1Count", 4, "count", None, "source.json"),
                MetricSample("extaddr:1111111111111111", "observedLinkQuality2Count", 2, "count", None, "source.json"),
                MetricSample("extaddr:1111111111111111", "observedLinkQuality3Count", 6, "count", None, "source.json"),
            ),
        }
    )
    assessment = evaluate_observation(
        observation, load_health_policy(), profile=PROFILE
    )
    assert any(f.rule_id == "device.totalMacDiscardRatio" for f in assessment.findings)
    lq = next(f for f in assessment.findings if f.rule_id == "network.observed-link-quality-ratios")
    assert lq.status is HealthStatus.MODERATE
    assert lq.evidence["observedCount"] == 12
    assert lq.evidence["lq2Ratio"] == 1 / 6
    assert lq.summary == "LQ3 is 50.0%; LQ2 is 16.7%; LQ1 is 33.3% of observed links."


def test_mac_ratio_without_positive_denominator_emits_no_finding() -> None:
    observation = replace(
        _observation(_relationship()),
        metrics=(
            MetricSample(
                "extaddr:1111111111111111",
                "totalMacErrorRatio",
                0.5,
                "ratio",
                None,
                "source.json",
            ),
        ),
    )

    assessment = evaluate_observation(observation, load_health_policy(), profile=PROFILE)

    assert not any(
        finding.rule_id == "device.totalMacErrorRatio"
        for finding in assessment.findings
    )
    assert (
        assessment.coverage["observedPillars"]["delivery"]["evidenceCounts"][
            "validMacRatios"
        ]
        == 0
    )


def test_complete_full_evidence_observation_has_sufficient_observed_coverage() -> None:
    relationships = (
        _relationship(),
        _relationship(
            relationship_id="link:2-3",
            from_device_id="extaddr:2222222222222222",
            to_device_id="extaddr:3333333333333333",
        ),
        _relationship(
            relationship_id="link:3-1",
            from_device_id="extaddr:3333333333333333",
            to_device_id="extaddr:1111111111111111",
        ),
    )
    devices = (
        DeviceSample("extaddr:1111111111111111", "1" * 16, "router", None, True, ("source.json",)),
        DeviceSample("extaddr:2222222222222222", "2" * 16, "router", None, False, ("source.json",)),
        DeviceSample("extaddr:3333333333333333", "3" * 16, "router", None, False, ("source.json",)),
    )
    observation = replace(
        _observation(relationships[0]),
        devices=devices,
        relationships=relationships,
        metrics=(
            MetricSample(devices[0].device_id, "totalMacErrorRatio", 0, "ratio", 100, "source.json"),
        ),
    )

    assessment = evaluate_observation(
        observation,
        load_health_policy(),
        profile=PROFILE,
        expected_device_ids=frozenset(device.device_id for device in devices),
        omr_prefix="fd00:1",
        device_ipv6_addresses={devices[0].device_id: ("fd00:1::1",)},
    )

    assert all(
        pillar["state"] == PROFILE.coverage[pillar_name]
        for pillar_name, pillar in assessment.coverage["observedPillars"].items()
    )
    assert assessment.coverage["observedPillars"]["resilience"]["evidenceCounts"][
        "topologyAuthority"
    ] == 1
    assert assessment.coverage["observedPillars"]["resilience"]["evidenceCounts"][
        "borderRouterAuthority"
    ] == 1


def test_missing_capability_omits_inapplicable_external_routing_rule() -> None:
    profile = replace(
        PROFILE,
        coverage=MappingProxyType({**PROFILE.coverage, "externalRouting": "missing"}),
    )
    observation = replace(
        _observation(_relationship()),
        devices=tuple(
            replace(device, is_border_router=True)
            for device in _observation(_relationship()).devices
        ),
    )

    assessment = evaluate_observation(
        observation,
        load_health_policy(),
        profile=profile,
        omr_prefix="fd00:1",
        device_ipv6_addresses={observation.devices[0].device_id: ("fd00:1::1",)},
    )

    assert not any(
        finding.rule_id == "network.external-routing"
        for finding in assessment.findings
    )