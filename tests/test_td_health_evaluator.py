"""Pure evaluator tests for directional quality and materiality."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

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
    assert EVALUATOR_VERSION == "snapshot-v6"
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
    assert finding.title == "Delivery errors uncorrelated with signal strength"


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
    relationship = _relationship(queued_message_count=3)
    assessment = evaluate_observation(
        _observation(relationship), load_health_policy(), profile=PROFILE
    )
    finding = next(f for f in assessment.findings if f.rule_id == "relationship.queued-messages")

    assert finding.status is HealthStatus.UNKNOWN
    assert finding.evidence["queuedMessageCount"] == 3


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