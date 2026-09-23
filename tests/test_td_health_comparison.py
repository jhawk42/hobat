"""Comparison-v1 identity and compatibility fixtures."""

from __future__ import annotations

from dataclasses import replace

import pytest

from td_health_comparison import (
    COMPARISON_VERSION,
    ComparisonPolicy,
    classify_reset,
    compare_interval,
    compare_item_compatibility,
    derive_comparison,
    derive_numeric_item,
    derive_discrete_item,
    project_baseline_availability,
    source_roles_for_dataset,
    source_signature,
    source_time_for_sample,
    supporting_changes,
)
from td_health_manifest import load_health_manifest
from td_health_observation_model import (
    Assessment,
    Completeness,
    Confidence,
    DeviceSample,
    HealthStatus,
    MetricSample,
    Observation,
    RelationshipSample,
    SourceEvidence,
)


ROLES = {"devices.json": "required", "outcome.json": "optional"}


def _endpoints() -> tuple[tuple[Observation, Assessment], tuple[Observation, Assessment]]:
    def endpoint(suffix: str, time: str) -> tuple[Observation, Assessment]:
        observation = Observation(
            observation_id=f"observation-{suffix}", datasource_id="otbr-cli",
            dataset_id="networkdiag", network_id="extpan:78b9775b001c1cbe",
            network_name="mesh", observed_at=time, ingested_at=time,
            completeness=Completeness.COMPLETE, source_set_digest=f"content-{suffix}",
            sources=(
                SourceEvidence("devices.json", f"digest-{suffix}", "final", "complete"),
                SourceEvidence("outcome.json", suffix, "outcome", "complete"),
            ),
            devices=(), relationships=(),
        )
        assessment = Assessment(
            assessment_id=f"assessment-{suffix}", observation_id=observation.observation_id,
            policy_version="snapshot-v1", policy_digest="health-policy",
            evaluator_version="snapshot-v10", profile_id="networkdiag-v1",
            status=HealthStatus.STRONG, confidence=Confidence.HIGH,
            coverage={}, findings=(), assessed_at=time,
            sample_contract_version=COMPARISON_VERSION,
            health_policy_digest="health-policy",
        )
        return observation, assessment

    return endpoint("before", "2026-09-01T00:00:00+00:00"), endpoint("after", "2026-09-02T00:00:00+00:00")


def _compare(before=None, after=None, **kwargs):
    default_before, default_after = _endpoints()
    return compare_interval(
        before if before is not None else default_before,
        after if after is not None else default_after,
        before_assessment_id="assessment-before", after_assessment_id="assessment-after",
        source_roles=ROLES, **kwargs,
    )


def test_same_composition_with_changed_content_is_compatible_and_idempotent() -> None:
    before, after = _endpoints()
    assert before[0].source_set_digest != after[0].source_set_digest
    assert source_signature(before[0], ROLES) == source_signature(after[0], ROLES)
    comparison = _compare()
    assert comparison == _compare()
    assert comparison.compatibility.comparable
    assert comparison.compatibility.change == "unknown"
    assert comparison.compatibility.reasons == ()
    assert comparison.elapsed_seconds == 86400
    assert comparison.gap_state == "within-limit"
    assert comparison.endpoint_policy_digest == "health-policy"
    assert comparison.comparison_policy_digest == ComparisonPolicy().digest


@pytest.mark.parametrize(
    ("observation_changes", "assessment_changes", "reason"),
    [
        ({"network_id": "extpan:1111111111111111"}, {}, "network-mismatch"),
        ({"datasource_id": "otbr-restapi"}, {}, "dataset-mismatch"),
        ({"dataset_id": "other"}, {}, "dataset-mismatch"),
        ({"sources": (SourceEvidence("devices.json", "new", "final", "complete"),)}, {}, "source-signature-mismatch"),
        ({"completeness": Completeness.DEGRADED}, {}, "endpoint-incomplete"),
        ({"completeness": Completeness.PARTIAL}, {}, "endpoint-incomplete"),
        ({"observed_at": "2026-09-01T00:00:00+00:00"}, {}, "endpoint-order-invalid"),
        ({"observed_at": "2026-08-31T00:00:00+00:00"}, {}, "endpoint-order-invalid"),
        ({}, {"profile_id": "other"}, "profile-mismatch"),
        ({}, {"sample_contract_version": "legacy-unknown"}, "sample-contract-mismatch"),
        ({}, {"evaluator_version": "snapshot-v9"}, "evaluator-mismatch"),
        ({}, {"health_policy_digest": "changed"}, "policy-mismatch"),
        ({}, {"health_policy_digest": None}, "policy-mismatch"),
    ],
)
def test_interval_gate_fails_closed(observation_changes, assessment_changes, reason) -> None:
    before, (observation, assessment) = _endpoints()
    after = replace(observation, **observation_changes), replace(assessment, **assessment_changes)
    compatibility = _compare(before, after).compatibility
    assert not compatibility.comparable
    assert compatibility.change == "unknown"
    assert compatibility.delta is None
    assert reason in compatibility.reasons


def test_route64_sample_contract_requires_matching_qualified_endpoints() -> None:
    before, after = _endpoints()
    before = replace(before[0], dataset_id="otbr_cli_networkdiag_fetch_all"), replace(
        before[1], sample_contract_version="comparison-v1-route64")
    after = replace(after[0], dataset_id="otbr_cli_networkdiag_fetch_all"), replace(
        after[1], sample_contract_version="comparison-v1-route64")
    assert _compare(before, after).compatibility.comparable
    old = before[0], replace(before[1], sample_contract_version=COMPARISON_VERSION)
    assert _compare(old, after).compatibility.reasons == ("sample-contract-mismatch",)


def test_gap_and_policy_changes_do_not_reuse_comparison_identity() -> None:
    before, (observation, assessment) = _endpoints()
    after = replace(observation, observed_at="2026-09-09T00:00:01+00:00"), assessment
    comparison = _compare(before, after)
    assert comparison.elapsed_seconds == 691201
    assert comparison.gap_state == "exceeded"
    assert comparison.compatibility.primary_reason == "gap-exceeded"
    adjusted = _compare(before, after, policy=ComparisonPolicy(max_comparison_gap_seconds=691201))
    assert adjusted.compatibility.comparable
    assert comparison.comparison_id != adjusted.comparison_id


def test_reason_precedence_and_missing_endpoint() -> None:
    before, (observation, assessment) = _endpoints()
    after = replace(observation, network_id="extpan:1111111111111111", completeness=Completeness.PARTIAL), replace(assessment, health_policy_digest="other")
    result = _compare(before, after)
    assert result.compatibility.reasons == (
        "network-mismatch", "policy-mismatch", "endpoint-incomplete",
    )
    assert result.compatibility.primary_reason == "network-mismatch"
    missing = compare_interval(None, after, before_assessment_id="assessment-before",
                               after_assessment_id="assessment-after", source_roles=ROLES)
    assert missing.compatibility.reasons == ("endpoint-missing",)


def _item(interval=None, **changes):
    fields = dict(
        before_subject="extaddr:8672766ae0578187", after_subject="extaddr:8672766ae0578187",
        before_role="router", after_role="router", before_relationship=("link:a->b", "router-neighbor"),
        after_relationship=("link:a->b", "router-neighbor"), before_metric="totalMacErrorRatio",
        after_metric="totalMacErrorRatio", before_unit="ratio", after_unit="ratio",
        before_denominator_kind="totalMacFrames", after_denominator_kind="totalMacFrames",
        before_source_time="2026-09-01T00:00:00+00:00",
        after_source_time="2026-09-02T00:00:00+00:00", since_reset=True,
        reset_evidence=classify_reset(elapsed_seconds=86400, before_epoch="epoch-1", after_epoch="epoch-1"),
    )
    fields.update(changes)
    return compare_item_compatibility(interval or _compare(), **fields)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"after_subject": "extaddr:1111111111111111"}, "subject-mismatch"),
        ({"after_role": "child"}, "role-mismatch"),
        ({"after_relationship": ("link:b->a", "router-neighbor")}, "relationship-mismatch"),
        ({"after_metric": None}, "metric-missing"),
        ({"after_unit": "percent"}, "unit-mismatch"),
        ({"after_denominator_kind": "other"}, "denominator-mismatch"),
        ({"reset_evidence": classify_reset(elapsed_seconds=86400, before_epoch="epoch-1", after_epoch="epoch-2")}, "reset-detected"),
        ({"reset_evidence": None}, "reset-unknown"),
        ({"after_source_time": "2026-09-01T00:00:00+00:00"}, "source-not-newer"),
        ({"after_source_time": None}, "source-not-newer"),
    ],
)
def test_item_incompatibility_is_local(changes, reason) -> None:
    result = _item(**changes)
    assert not result.comparable
    assert result.change == "unknown"
    assert result.delta is None
    assert result.primary_reason == reason
    assert _item().comparable


def test_source_roles_and_endpoint_provenance_must_be_explicit() -> None:
    before, after = _endpoints()
    with pytest.raises(ValueError, match="Missing source role"):
        source_signature(before[0], {"devices.json": "required"})
    with pytest.raises(ValueError, match="Assessment and observation IDs"):
        _compare(before, (after[0], replace(after[1], observation_id="other")))
    with pytest.raises(ValueError, match="non-negative"):
        ComparisonPolicy(max_comparison_gap_seconds=-1)


def test_roster_only_digest_change_does_not_invalidate_metric_interval() -> None:
    before, (observation, assessment) = _endpoints()
    assert _compare(before, (observation, replace(assessment, policy_digest="roster-changed"))).compatibility.comparable


def test_source_roles_are_derived_from_approved_dataset() -> None:
    dataset = next(iter(load_health_manifest().datasets.values()))
    roles = source_roles_for_dataset(dataset)
    assert set(roles) == set(dataset.files) | {dataset.health_profile.identity_file} | set(dataset.health_profile.required_outcomes)
    assert set(roles.values()) == {"required"}


def test_missing_presence_requires_newer_complete_authoritative_source() -> None:
    fields = dict(item_kind="presence", before_metric=None, after_metric=None,
                  after_source_time=None, before_source_file="devices.json",
                  after_coverage_source="devices.json",
                  after_coverage_time="2026-09-02T00:00:00+00:00")
    assert _item(**fields).comparable
    assert _item(**{**fields, "after_coverage_source": "outcome.json"}).reasons == ("source-not-newer",)
    assert _item(**{**fields, "after_coverage_time": "2026-09-01T00:00:00+00:00"}).reasons == ("source-not-newer",)
    before, (observation, assessment) = _endpoints()
    partial = _compare(before, (replace(observation, completeness=Completeness.PARTIAL), assessment))
    assert _item(partial, **fields).reasons == ("endpoint-incomplete",)


def test_pruned_read_projection_preserves_immutable_interval() -> None:
    stored = _compare()
    effective = project_baseline_availability(stored, before_retained=False, after_retained=True)
    assert stored.compatibility.comparable and stored.baseline_state == "available"
    assert effective.baseline_state == "pruned"
    assert effective.compatibility.reasons == ("baseline-pruned",)
    assert effective.compatibility.delta is None
    assert effective.baseline_observation_id == stored.baseline_observation_id
    assert effective.after_observation_id == stored.after_observation_id
    assert effective.before_observed_at == stored.before_observed_at
    assert _item(effective).reasons == ("baseline-pruned",)
    _before, after = _endpoints()
    missing = compare_interval(None, after, before_assessment_id="assessment-before",
                               after_assessment_id="assessment-after", source_roles=ROLES)
    assert missing.baseline_state == "missing"
    assert project_baseline_availability(missing, before_retained=False, after_retained=True) is missing


@pytest.mark.parametrize(
    ("inputs", "state", "witness"),
    [
        ({"before_epoch": "first", "after_epoch": "first"}, "same-epoch", "audited-epoch"),
        ({"before_epoch": "first", "after_epoch": "second"}, "reset-detected", "audited-epoch"),
        ({"before_uptime": 100.0, "after_uptime": 86500.0}, "same-epoch", "uptime"),
        ({"before_uptime": 100.0, "after_uptime": 86800.0}, "same-epoch", "uptime"),
        ({"before_uptime": 100.0, "after_uptime": 86801.0}, "unknown", "uptime"),
        ({"before_uptime": 100.0, "after_uptime": 50.0}, "reset-detected", "uptime"),
        ({"before_counter": 200.0, "after_counter": 50.0}, "reset-detected", "counter-decrease"),
        ({"before_counter": 200.0, "after_counter": 250.0}, "unknown", None),
        ({"before_uptime": float("nan"), "after_uptime": 86400.0}, "unknown", None),
        ({"before_epoch": "first", "after_epoch": "first", "before_uptime": 0.0, "after_uptime": 50.0}, "unknown", "uptime"),
        ({"before_epoch": "first", "after_epoch": "second", "before_uptime": 0.0, "after_uptime": 86400.0}, "unknown", None),
        ({}, "unknown", None),
    ],
)
def test_reset_witness_matrix(inputs, state, witness) -> None:
    evidence = classify_reset(elapsed_seconds=86400, **inputs)
    assert (evidence.state, evidence.witness) == (state, witness)
    if state == "reset-detected":
        assert _item(reset_evidence=evidence).reasons == ("reset-detected",)
    elif state == "unknown":
        assert _item(reset_evidence=evidence).reasons == ("reset-unknown",)


def test_source_times_require_valid_final_file_provenance() -> None:
    observation, _assessment = _endpoints()[0]
    assert source_time_for_sample(observation, "devices.json") is None
    timestamp = "2026-08-31T23:00:00+00:00"
    sources = (
        replace(observation.sources[0], source_observed_at=timestamp, state="valid"),
        replace(observation.sources[1], source_observed_at="2026-09-01T01:00:00+00:00"),
    )
    attributed = replace(observation, sources=sources)
    assert source_time_for_sample(attributed, "devices.json") == timestamp
    assert source_time_for_sample(attributed, "outcome.json") is None
    assert source_time_for_sample(replace(attributed, sources=(replace(sources[0], state="invalid"),)), "devices.json") is None
    assert source_time_for_sample(replace(attributed, sources=(replace(sources[0], source_observed_at="2026-09-02T00:00:00+00:00"),)), "devices.json") is None


def test_transient_supporting_facts_are_sorted_and_do_not_infer_absence() -> None:
    before = {"rloc16": "0x1234", "parent": "extaddr:aaaaaaaaaaaaaaaa",
              "partition": "1", "firmware": "v1", "source": "devices.json",
              "sampleContractVersion": "comparison-v1"}
    after = {"rloc16": "0x5678", "parent": "extaddr:bbbbbbbbbbbbbbbb",
             "partition": "1", "firmware": "v2", "sampleContractVersion": "comparison-v2"}
    changes = supporting_changes(before, after)
    assert [(change.field, change.before, change.after) for change in changes] == [
        ("firmware", "v1", "v2"),
        ("parent", "extaddr:aaaaaaaaaaaaaaaa", "extaddr:bbbbbbbbbbbbbbbb"),
        ("rloc16", "0x1234", "0x5678"),
        ("sampleContractVersion", "comparison-v1", "comparison-v2"),
    ]
    assert "source" not in {change.field for change in changes}


def _numeric(**overrides):
    values = dict(scope="device", subject_id="extaddr:8672766ae0578187",
                  kind="gauge-change", metric="rssi", unit="dBm", denominator_kind=None,
                  before_value=-65.0, after_value=-70.0,
                  before_source_time="2026-09-01T00:00:00+00:00",
                  after_source_time="2026-09-02T00:00:00+00:00",
                  source_files=("devices.json",), preference="higher")
    values.update(overrides)
    return derive_numeric_item(_compare(), **values)


def test_gauge_and_ratio_changes_are_discrete_and_catalog_directed() -> None:
    gauge = _numeric()
    assert (gauge.before_value, gauge.after_value, gauge.delta, gauge.direction, gauge.change) == (
        -65.0, -70.0, -5.0, "worsened", "changed")
    assert gauge == _numeric()
    assert _numeric(after_value=-65.0).change == "unchanged"
    ratio = _numeric(kind="ratio-change", metric="totalMacErrorRatio", unit="ratio",
                     before_value=0.1, after_value=0.15, before_denominator=10,
                     after_denominator=20, denominator_kind="totalMacFrames", preference="lower")
    assert ratio.delta == pytest.approx(5.0)
    assert ratio.direction == "worsened"
    assert _numeric(preference=None).direction is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"before_value": None}, "metric-missing"),
        ({"before_value": float("nan")}, "metric-missing"),
        ({"after_value": float("inf")}, "metric-missing"),
        ({"kind": "ratio-change", "before_value": 0.1, "after_value": 0.2,
          "denominator_kind": "totalMacFrames", "before_denominator": 0, "after_denominator": 4}, "denominator-mismatch"),
        ({"kind": "counter-delta", "before_value": 10, "after_value": 9,
          "reset_evidence": classify_reset(elapsed_seconds=86400, before_epoch="a", after_epoch="a")}, "reset-detected"),
        ({"kind": "counter-delta", "before_value": 10, "after_value": 11}, "reset-unknown"),
        ({"after_source_time": "2026-09-01T00:00:00+00:00"}, "source-not-newer"),
    ],
)
def test_numeric_gates_leave_delta_unknown(overrides, reason) -> None:
    item = _numeric(**overrides)
    assert not item.compatibility.comparable
    assert reason in item.compatibility.reasons
    assert item.delta is None and item.direction is None and item.change == "unknown"


@pytest.mark.parametrize(
    ("kind", "before", "after", "transition", "change"),
    [
        ("categorical-transition", "router", "child", None, "changed"),
        ("presence-transition", True, False, "missing", "changed"),
        ("presence-transition", False, True, "recovered", "changed"),
        ("presence-transition", True, True, "present", "unchanged"),
        ("relationship-change", False, True, "added", "changed"),
        ("relationship-change", True, False, "removed", "changed"),
        ("relationship-change", True, True, "retained", "unchanged"),
        ("queue-persistence", 2, 1, "present-both", "changed"),
        ("queue-persistence", 2, 0, "cleared", "changed"),
        ("queue-persistence", 0, 3, "appeared", "changed"),
        ("queue-persistence", 0, 0, "absent-both", "unchanged"),
    ],
)
def test_discrete_item_kinds(kind, before, after, transition, change) -> None:
    item = derive_discrete_item(
        _compare(), kind=kind, scope="relationship" if kind == "relationship-change" else "device",
        subject_id="link:extaddr:aaaaaaaaaaaaaaaa->extaddr:bbbbbbbbbbbbbbbb" if kind == "relationship-change" else "extaddr:aaaaaaaaaaaaaaaa",
        relationship_type="router-neighbor" if kind == "relationship-change" else None,
        metric="role" if kind == "categorical-transition" else None,
        before_value=before, after_value=after,
        before_source_time="2026-09-01T00:00:00+00:00",
        after_source_time="2026-09-02T00:00:00+00:00",
        source_files=("devices.json",),
    )
    assert item.compatibility.comparable
    assert (item.change, item.transition, item.delta) == (change, transition, None)


def test_missing_presence_needs_same_source_coverage_and_no_roster_fallback() -> None:
    fields = dict(kind="presence-transition", scope="device", subject_id="extaddr:aaaaaaaaaaaaaaaa",
                  metric=None, before_value=True, after_value=False,
                  before_source_time="2026-09-01T00:00:00+00:00", after_source_time=None,
                  source_files=("devices.json",), before_source_file="devices.json",
                  after_coverage_source="devices.json", after_coverage_time="2026-09-02T00:00:00+00:00")
    assert derive_discrete_item(_compare(), **fields).transition == "missing"
    assert derive_discrete_item(_compare(), **{**fields, "after_coverage_source": "outcome.json"}).change == "unknown"
    assert derive_discrete_item(_compare(), **{**fields, "after_coverage_time": None}).change == "unknown"
    one_queue = derive_discrete_item(
        _compare(), kind="queue-persistence", scope="relationship", subject_id="link:a->b",
        metric="queuedMessageCount", before_value=2, after_value=None,
        before_source_time="2026-09-01T00:00:00+00:00", after_source_time=None,
    )
    assert one_queue.sample_count == 1 and one_queue.change == "unknown"
    nonfinite = derive_discrete_item(
        _compare(), kind="queue-persistence", scope="relationship", subject_id="link:a->b",
        metric="queuedMessageCount", before_value=2, after_value=float("inf"),
        before_source_time="2026-09-01T00:00:00+00:00",
        after_source_time="2026-09-02T00:00:00+00:00",
    )
    assert nonfinite.after_value is None and nonfinite.change == "unknown"


def test_endpoint_derivation_uses_source_times_and_directional_relationships() -> None:
    before, after = _endpoints()
    link_id = "link:extaddr:aaaaaaaaaaaaaaaa->extaddr:bbbbbbbbbbbbbbbb"

    def relation(quality, queue):
        return RelationshipSample(link_id, "router-neighbor", "extaddr:aaaaaaaaaaaaaaaa",
                                  "extaddr:bbbbbbbbbbbbbbbb", quality, None, None, None,
                                  None, None, None, None, ("devices.json",), queue)

    first = replace(
        before[0], sources=(replace(before[0].sources[0], state="valid",
                                   source_observed_at=before[0].observed_at), before[0].sources[1]),
        relationships=(relation(2, 4),),
        metrics=(MetricSample("extaddr:aaaaaaaaaaaaaaaa", "parentChanges", 8, "count", None, "devices.json"),),
    )
    second = replace(
        after[0], sources=(replace(after[0].sources[0], state="valid",
                                  source_observed_at=after[0].observed_at), after[0].sources[1]),
        relationships=(relation(3, 0),),
        metrics=(MetricSample("extaddr:aaaaaaaaaaaaaaaa", "parentChanges", 9, "count", None, "devices.json"),),
    )
    interval, items = derive_comparison((first, before[1]), (second, after[1]), source_roles=ROLES)
    assert interval.compatibility.comparable
    assert [(item.kind, item.metric) for item in items] == [
        ("counter-delta", "parentChanges"), ("gauge-change", "link_quality_in"),
        ("queue-persistence", "queuedMessageCount"), ("relationship-change", None),
    ]
    gauge = next(item for item in items if item.metric == "link_quality_in")
    assert gauge.delta == 1 and gauge.direction == "improved"
    assert next(item for item in items if item.kind == "queue-persistence").transition == "cleared"
    counter = next(item for item in items if item.kind == "counter-delta")
    assert counter.compatibility.reasons == ("reset-unknown",)
    assert counter.reset_evidence.state == "unknown" and counter.delta is None
    repeated = replace(second, sources=(replace(second.sources[0], source_observed_at=first.observed_at), second.sources[1]))
    _, reused = derive_comparison((first, before[1]), (repeated, after[1]), source_roles=ROLES)
    assert all(item.change == "unknown" for item in reused)


def test_relationship_add_remove_requires_newer_authoritative_source() -> None:
    before, after = _endpoints()
    link_id = "link:extaddr:aaaaaaaaaaaaaaaa->extaddr:bbbbbbbbbbbbbbbb"
    link = RelationshipSample(link_id, "router-neighbor", "extaddr:aaaaaaaaaaaaaaaa",
                              "extaddr:bbbbbbbbbbbbbbbb", None, None, None, None,
                              None, None, None, None, ("devices.json",))

    def endpoint(pair, links, source_time):
        observation, assessment = pair
        source = replace(observation.sources[0], state="valid", source_observed_at=source_time)
        return replace(observation, sources=(source, observation.sources[1]), relationships=links), assessment

    first = endpoint(before, (), before[0].observed_at)
    second = endpoint(after, (link,), after[0].observed_at)
    _, added = derive_comparison(first, second, source_roles=ROLES)
    assert next(item for item in added if item.kind == "relationship-change").transition == "added"
    _, removed = derive_comparison(endpoint(before, (link,), before[0].observed_at),
                                   endpoint(after, (), after[0].observed_at), source_roles=ROLES)
    assert next(item for item in removed if item.kind == "relationship-change").transition == "removed"
    repeated = endpoint(after, (link,), before[0].observed_at)
    _, unknown = derive_comparison(first, repeated, source_roles=ROLES)
    assert next(item for item in unknown if item.kind == "relationship-change").change == "unknown"


def test_route_change_requires_reporter_coverage_at_both_endpoints() -> None:
    before, after = _endpoints()
    reporter = "extaddr:aaaaaaaaaaaaaaaa"
    target = "extaddr:bbbbbbbbbbbbbbbb"
    route_id = f"link:route:{reporter}->{target}"
    route = RelationshipSample(route_id, "router-route", reporter, target,
                               None, None, None, None, None, None, None, reporter,
                               ("devices.json",))

    def endpoint(pair, links, covered=True):
        observation, assessment = pair
        source = replace(observation.sources[0], state="valid", source_observed_at=observation.observed_at)
        metrics = (MetricSample(reporter, "route64Coverage", 1.0, "flag", None, "devices.json"),) if covered else ()
        return replace(observation, sources=(source, observation.sources[1]),
                       relationships=links, metrics=metrics), assessment

    first = endpoint(before, (route,))
    second = endpoint(after, ())
    _, items = derive_comparison(first, second, source_roles=ROLES)
    assert next(item for item in items if item.subject_id == route_id).transition == "removed"
    _, items = derive_comparison(first, endpoint(after, (), False), source_roles=ROLES)
    route_item = next(item for item in items if item.subject_id == route_id)
    assert route_item.change == "unknown" and route_item.transition is None
    assert route_item.compatibility.reasons == ("metric-missing",)
    _, items = derive_comparison(endpoint(before, (), False), endpoint(after, (route,)), source_roles=ROLES)
    assert next(item for item in items if item.subject_id == route_id).change == "unknown"


def test_relationship_uses_qualified_shared_source_when_first_is_unqualified() -> None:
    before, after = _endpoints()
    link_id = "link:extaddr:aaaaaaaaaaaaaaaa->extaddr:bbbbbbbbbbbbbbbb"
    link = RelationshipSample(link_id, "router-neighbor", "extaddr:aaaaaaaaaaaaaaaa",
                              "extaddr:bbbbbbbbbbbbbbbb", None, None, None, None,
                              None, None, None, None, ("a.json", "devices.json"))

    def endpoint(pair):
        observation, assessment = pair
        sources = (SourceEvidence("a.json", "bad", "final", "complete"),
                   replace(observation.sources[0], state="valid", source_observed_at=observation.observed_at),
                   observation.sources[1])
        return replace(observation, sources=sources, relationships=(link,)), assessment

    _, items = derive_comparison(endpoint(before), endpoint(after),
                                 source_roles={**ROLES, "a.json": "optional"})
    relationship = next(item for item in items if item.kind == "relationship-change")
    assert relationship.change == "unchanged"
    assert relationship.before_source_time == before[0].observed_at
    assert relationship.after_source_time == after[0].observed_at


def test_device_and_parent_use_qualified_shared_source() -> None:
    before, after = _endpoints()
    child_id = "extaddr:bbbbbbbbbbbbbbbb"
    device = DeviceSample(child_id, "bbbbbbbbbbbbbbbb", "child", "attached", False,
                          ("a.json", "devices.json"))
    parent_id = "extaddr:aaaaaaaaaaaaaaaa"
    link = RelationshipSample(f"link:{parent_id}->{child_id}", "parent-child", parent_id,
                              child_id, None, None, None, None, None, None, None, None,
                              ("a.json", "devices.json"))

    def endpoint(pair):
        observation, assessment = pair
        sources = (SourceEvidence("a.json", "bad", "final", "complete"),
                   replace(observation.sources[0], state="valid", source_observed_at=observation.observed_at),
                   observation.sources[1])
        return replace(observation, sources=sources, devices=(device,), relationships=(link,)), assessment

    _, items = derive_comparison(endpoint(before), endpoint(after),
                                 source_roles={**ROLES, "a.json": "optional"})
    for metric in (None, "role", "state", "parent"):
        device_item = next(item for item in items if item.scope == "device" and item.metric == metric)
        assert device_item.change == "unchanged"
        assert device_item.before_source_time == before[0].observed_at
        assert device_item.after_source_time == after[0].observed_at


def test_parent_transition_requires_one_attributed_parent_per_endpoint() -> None:
    before, after = _endpoints()
    child_id = "extaddr:bbbbbbbbbbbbbbbb"
    child = DeviceSample(child_id, "bbbbbbbbbbbbbbbb", "child", None, False, ("devices.json",))

    def endpoint(pair, parent_ids):
        observation, assessment = pair
        relationships = tuple(
            RelationshipSample(f"link:{parent_id}->{child_id}", "parent-child", parent_id,
                               child_id, None, None, None, None, None, None, None, None,
                               ("devices.json",))
            for parent_id in parent_ids
        )
        source = replace(observation.sources[0], state="valid", source_observed_at=observation.observed_at)
        return (replace(observation, devices=(child,), relationships=relationships,
                        sources=(source, observation.sources[1])), assessment)

    first = endpoint(before, ("extaddr:aaaaaaaaaaaaaaaa",))
    second = endpoint(after, ("extaddr:cccccccccccccccc",))
    _, items = derive_comparison(first, second, source_roles=ROLES)
    parent = next(item for item in items if item.metric == "parent")
    assert (parent.before_value, parent.after_value, parent.change) == (
        "extaddr:aaaaaaaaaaaaaaaa", "extaddr:cccccccccccccccc", "changed")
    ambiguous = endpoint(after, ("extaddr:cccccccccccccccc", "extaddr:dddddddddddddddd"))
    _, items = derive_comparison(first, ambiguous, source_roles=ROLES)
    assert not any(item.metric == "parent" for item in items)
    old_time = replace(second[0], sources=(replace(second[0].sources[0], source_observed_at=first[0].observed_at), second[0].sources[1]))
    _, items = derive_comparison(first, (old_time, second[1]), source_roles=ROLES)
    assert next(item for item in items if item.metric == "parent").change == "unknown"


def test_partition_and_rloc_transitions_require_matching_immutable_source_facts() -> None:
    before, after = _endpoints()
    device_id = "extaddr:aaaaaaaaaaaaaaaa"
    device = DeviceSample(device_id, "aaaaaaaaaaaaaaaa", "router", None, False, ("devices.json",))

    def endpoint(pair):
        observation, assessment = pair
        source = replace(observation.sources[0], state="valid", source_observed_at=observation.observed_at)
        return replace(observation, devices=(device,), sources=(source, observation.sources[1])), assessment

    first, second = endpoint(before), endpoint(after)

    def fact(field, value, time):
        return {"device_id": device_id, "field_key": field, "source_file": "devices.json",
                "source_observed_at": time, "roster_policy_digest": "roster-v1",
                "conflict_state": "none", "value": value}

    old = (fact("leaderData.partitionId", 10, first[0].observed_at),
           fact("rloc16", "0x1234", first[0].observed_at))
    new = (fact("leaderData.partitionId", 20, second[0].observed_at),
           fact("rloc16", "0x5678", second[0].observed_at))
    facts = {first[0].observation_id: old, second[0].observation_id: new}
    _, items = derive_comparison(first, second, source_roles=ROLES, endpoint_facts=facts)
    transitions = {item.metric: item for item in items if item.metric in {"partition", "rloc16"}}
    assert {metric: (item.before_value, item.after_value, item.change) for metric, item in transitions.items()} == {
        "partition": (10, 20, "changed"), "rloc16": ("0x1234", "0x5678", "changed")}
    repeated = replace(second[0], sources=(replace(second[0].sources[0], source_observed_at=first[0].observed_at), second[0].sources[1]))
    _, items = derive_comparison(first, (repeated, second[1]), source_roles=ROLES, endpoint_facts=facts)
    assert not any(item.metric in {"partition", "rloc16"} for item in items)
    conflicting = {**facts, second[0].observation_id: ({**new[0], "conflict_state": "cross-source"}, new[1])}
    _, items = derive_comparison(first, second, source_roles=ROLES, endpoint_facts=conflicting)
    assert not any(item.metric == "partition" for item in items)