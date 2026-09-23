"""Pure comparison-v1 identity and compatibility contract."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Mapping

from td_health_manifest import HealthDataset
from td_health_observation_model import Assessment, Completeness, Observation


COMPARISON_VERSION = "comparison-v1"
ROUTE64_SAMPLE_CONTRACT_VERSION = "comparison-v1-route64"
REASON_ORDER = (
    "endpoint-missing", "endpoint-order-invalid", "network-mismatch",
    "dataset-mismatch", "profile-mismatch", "source-signature-mismatch",
    "sample-contract-mismatch", "evaluator-mismatch", "policy-mismatch",
    "endpoint-incomplete", "gap-exceeded", "subject-mismatch", "role-mismatch",
    "relationship-mismatch", "metric-missing", "unit-mismatch",
    "denominator-mismatch", "baseline-pruned", "reset-detected", "reset-unknown",
    "source-not-newer",
)


@dataclass(frozen=True)
class ComparisonPolicy:
    max_comparison_gap_seconds: int = 604800
    uptime_continuity_tolerance_seconds: int = 300

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (self.max_comparison_gap_seconds, self.uptime_continuity_tolerance_seconds)
        ):
            raise ValueError("Comparison policy limits must be non-negative integers")

    @property
    def digest(self) -> str:
        return _digest({
            "version": COMPARISON_VERSION,
            "maxComparisonGapSeconds": self.max_comparison_gap_seconds,
            "uptimeContinuityToleranceSeconds": self.uptime_continuity_tolerance_seconds,
        })


@dataclass(frozen=True)
class Compatibility:
    comparable: bool
    change: str
    delta: None
    primary_reason: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ComparisonInterval:
    comparison_id: str
    before_assessment_id: str
    after_assessment_id: str
    endpoint_policy_digest: str | None
    comparison_policy_digest: str
    source_signature: str | None
    elapsed_seconds: int | None
    gap_state: str | None
    compatibility: Compatibility
    baseline_assessment_id: str
    baseline_observation_id: str | None
    after_observation_id: str | None
    before_observed_at: str | None
    after_observed_at: str | None
    baseline_state: str


@dataclass(frozen=True)
class ResetEvidence:
    state: str
    witness: str | None
    before_value: float | str | None
    after_value: float | str | None


@dataclass(frozen=True)
class SupportingChange:
    field: str
    before: str
    after: str


@dataclass(frozen=True)
class ComparisonItem:
    item_id: str
    scope: str
    subject_id: str
    kind: str
    metric: str | None
    unit: str | None
    denominator_kind: str | None
    before_value: Any
    after_value: Any
    delta: float | None
    direction: str | None
    change: str
    sample_count: int
    compatibility: Compatibility
    source_files: tuple[str, ...]
    before_source_time: str | None
    after_source_time: str | None
    transition: str | None = None
    reset_evidence: ResetEvidence | None = None


def derive_numeric_item(
    interval: ComparisonInterval, *, scope: str, subject_id: str, kind: str,
    metric: str, unit: str, denominator_kind: str | None,
    before_value: float | None, after_value: float | None,
    before_denominator: float | None = None, after_denominator: float | None = None,
    before_source_time: str | None = None, after_source_time: str | None = None,
    source_files: tuple[str, ...] = (), reset_evidence: ResetEvidence | None = None,
    preference: str | None = None,
) -> ComparisonItem:
    if kind not in {"counter-delta", "gauge-change", "ratio-change"}:
        raise ValueError("Unsupported numeric comparison kind")
    if preference not in {None, "higher", "lower"}:
        raise ValueError("Invalid comparison preference")
    sample_count = sum(value is not None for value in (before_value, after_value))
    compatibility = compare_item_compatibility(
        interval, before_subject=subject_id, after_subject=subject_id,
        before_role=None, after_role=None, before_relationship=None, after_relationship=None,
        before_metric=metric if before_value is not None else None,
        after_metric=metric if after_value is not None else None,
        before_unit=unit, after_unit=unit,
        before_denominator_kind=denominator_kind, after_denominator_kind=denominator_kind,
        before_source_time=before_source_time, after_source_time=after_source_time,
        since_reset=kind == "counter-delta", reset_evidence=reset_evidence,
    )
    reasons = set(compatibility.reasons)
    if sample_count != 2 or not all(_finite_nonnegative(value) if kind != "gauge-change" else _finite(value)
                                        for value in (before_value, after_value)):
        reasons.add("metric-missing")
    if kind == "ratio-change" and not (
        _finite_nonnegative(before_denominator) and before_denominator > 0 and
        _finite_nonnegative(after_denominator) and after_denominator > 0
    ):
        reasons.add("denominator-mismatch")
    if kind == "counter-delta" and sample_count == 2 and _finite_nonnegative(before_value) and _finite_nonnegative(after_value) and after_value < before_value:
        reasons.add("reset-detected")
    compatibility = _compatibility(reasons)
    delta = None
    direction = None
    change = "unknown"
    if compatibility.comparable:
        delta = after_value - before_value
        if kind == "ratio-change":
            delta *= 100
        change = "unchanged" if delta == 0 else "changed"
        if delta and preference:
            direction = "improved" if (delta > 0) == (preference == "higher") else "worsened"
    sorted_files = tuple(sorted(set(source_files)))
    item_id = "item:" + _digest((scope, subject_id, kind, metric, unit, denominator_kind, sorted_files))[:24]
    return ComparisonItem(item_id, scope, subject_id, kind, metric, unit, denominator_kind,
                          before_value if _finite(before_value) else None,
                          after_value if _finite(after_value) else None, delta, direction, change, sample_count,
                          compatibility, sorted_files, before_source_time, after_source_time,
                          reset_evidence=reset_evidence)


def derive_discrete_item(
    interval: ComparisonInterval, *, kind: str, scope: str, subject_id: str,
    metric: str | None, before_value: str | bool | int | float | None,
    after_value: str | bool | int | float | None,
    before_source_time: str | None, after_source_time: str | None,
    source_files: tuple[str, ...] = (),
    before_source_file: str | None = None,
    after_coverage_source: str | None = None,
    after_coverage_time: str | None = None,
    relationship_type: str | None = None,
) -> ComparisonItem:
    if kind not in {"categorical-transition", "presence-transition", "relationship-change", "queue-persistence"}:
        raise ValueError("Unsupported discrete comparison kind")
    if kind in {"presence-transition", "relationship-change"}:
        valid = type(before_value) is bool and type(after_value) is bool
    elif kind == "queue-persistence":
        valid = all(_finite_nonnegative(value) for value in (before_value, after_value))
    else:
        valid = all((isinstance(value, str) and bool(value)) or (type(value) is int and value >= 0)
                    for value in (before_value, after_value))
    if kind == "relationship-change" and (not relationship_type or not subject_id.startswith("link:")):
        valid = False
    if kind == "queue-persistence":
        before_value = before_value if _finite_nonnegative(before_value) else None
        after_value = after_value if _finite_nonnegative(after_value) else None
    source_time = after_source_time
    if kind == "presence-transition" and after_value is False and not after_source_time:
        source_time = after_coverage_time if before_source_file and after_coverage_source == before_source_file else None
    compatibility = compare_item_compatibility(
        interval, item_kind={"categorical-transition": "categorical",
                             "presence-transition": "presence", "relationship-change": "relationship",
                             "queue-persistence": "queue"}[kind],
        before_subject=subject_id, after_subject=subject_id,
        before_role=None, after_role=None,
        before_relationship=(subject_id, relationship_type) if kind == "relationship-change" else None,
        after_relationship=(subject_id, relationship_type) if kind == "relationship-change" else None,
        before_metric=metric, after_metric=metric,
        before_unit=None, after_unit=None, before_denominator_kind=None, after_denominator_kind=None,
        before_source_time=before_source_time, after_source_time=source_time,
    )
    reasons = set(compatibility.reasons)
    if not valid:
        reasons.add("metric-missing")
    compatibility = _compatibility(reasons)
    change = "unknown"
    transition = None
    if compatibility.comparable:
        if kind == "presence-transition":
            transition = "recovered" if not before_value and after_value else "missing" if not after_value else "present"
        elif kind == "relationship-change":
            transition = "added" if not before_value and after_value else "removed" if before_value and not after_value else "retained" if before_value else "absent"
        elif kind == "queue-persistence":
            transition = "present-both" if before_value > 0 and after_value > 0 else "cleared" if before_value > 0 else "appeared" if after_value > 0 else "absent-both"
        change = "unchanged" if before_value == after_value else "changed"
    sorted_files = tuple(sorted(set(source_files)))
    item_id = "item:" + _digest((scope, subject_id, kind, metric, relationship_type, sorted_files))[:24]
    if kind in {"presence-transition", "relationship-change"}:
        sample_count = int(before_value is True) + int(after_value is True)
    elif kind == "queue-persistence":
        sample_count = sum(_finite_nonnegative(value) for value in (before_value, after_value))
    else:
        sample_count = sum((isinstance(value, str) and bool(value)) or (type(value) is int and value >= 0)
                           for value in (before_value, after_value))
    return ComparisonItem(item_id, scope, subject_id, kind, metric, None, None,
                          before_value, after_value, None, None, change, sample_count,
                          compatibility, sorted_files, before_source_time, source_time, transition)


def _finite(value: float | None) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


METRIC_CATALOG: Mapping[str, tuple[str, str, str | None, str | None]] = {
    "totalMacErrorRatio": ("ratio-change", "ratio", "totalMacFrames", "lower"),
    "totalMacDiscardRatio": ("ratio-change", "ratio", "totalMacFrames", "lower"),
    "parentChanges": ("counter-delta", "count", None, "lower"),
    "partitionIdChanges": ("counter-delta", "count", None, "lower"),
    "betterPartitionAttachAttempts": ("counter-delta", "count", None, "lower"),
    "totalParentPartitionChanges": ("counter-delta", "count", None, "lower"),
    "routerRolePercent": ("gauge-change", "percent", None, "higher"),
    "detachedDisabledPercent": ("gauge-change", "percent", None, "lower"),
}

RELATIONSHIP_CATALOG: Mapping[str, tuple[str, str | None]] = {
    "link_quality_in": ("quality", "higher"),
    "link_quality_out": ("quality", "higher"),
    "average_rssi": ("dBm", "higher"),
    "last_rssi": ("dBm", "higher"),
    "link_margin": ("dB", "higher"),
    "frame_error_rate": ("ratio", "lower"),
    "message_error_rate": ("ratio", "lower"),
}


def derive_comparison(
    before: tuple[Observation, Assessment], after: tuple[Observation, Assessment],
    *, source_roles: Mapping[str, str], policy: ComparisonPolicy = ComparisonPolicy(),
    roster_device_ids: frozenset[str] = frozenset(),
    endpoint_facts: Mapping[str, tuple[Mapping[str, object], ...]] | None = None,
) -> tuple[ComparisonInterval, tuple[ComparisonItem, ...]]:
    """Derive only endpoint evidence; roster IDs select candidates, never samples."""
    before_obs, before_assessment = before
    after_obs, after_assessment = after
    interval = compare_interval(
        before, after, before_assessment_id=before_assessment.assessment_id,
        after_assessment_id=after_assessment.assessment_id, source_roles=source_roles, policy=policy,
    )
    items: list[ComparisonItem] = []
    old_devices = {device.device_id: device for device in before_obs.devices}
    new_devices = {device.device_id: device for device in after_obs.devices}
    for device_id in sorted(old_devices.keys() | new_devices.keys() | roster_device_ids):
        old_device, new_device = old_devices.get(device_id), new_devices.get(device_id)
        source_files = tuple(sorted(set(old_device.source_files if old_device else ()) |
                                    set(new_device.source_files if new_device else ())))
        source_file = next((filename for filename in source_files if
                            (old_device is None or filename in old_device.source_files) and
                            (new_device is None or filename in new_device.source_files) and
                            (before_time := source_time_for_sample(before_obs, filename)) and
                            (after_time := source_time_for_sample(after_obs, filename)) and
                            _utc_timestamp(after_time) > _utc_timestamp(before_time)), None)
        old_time = source_time_for_sample(before_obs, source_file) if source_file else None
        new_time = source_time_for_sample(after_obs, source_file) if source_file else None
        if old_device or new_device:
            items.append(derive_discrete_item(
                interval, kind="presence-transition", scope="device", subject_id=device_id,
                metric=None, before_value=old_device is not None, after_value=new_device is not None,
                before_source_time=old_time, after_source_time=new_time if new_device else None,
                source_files=source_files, before_source_file=source_file,
                after_coverage_source=source_file if new_device is None else None,
                after_coverage_time=new_time if new_device is None else None,
            ))
        for field in ("role", "state"):
            if old_device and new_device and getattr(old_device, field) is not None and getattr(new_device, field) is not None:
                items.append(derive_discrete_item(
                    interval, kind="categorical-transition", scope="device", subject_id=device_id,
                    metric=field, before_value=getattr(old_device, field), after_value=getattr(new_device, field),
                    before_source_time=old_time, after_source_time=new_time, source_files=source_files,
                ))
        if endpoint_facts:
            for field, metric in (("leaderData.partitionId", "partition"), ("rloc16", "rloc16")):
                matches = [fact for fact in endpoint_facts.get(before_obs.observation_id, ())
                           if fact["device_id"] == device_id and fact["field_key"] == field
                           and fact["conflict_state"] == "none"]
                newer = [fact for fact in endpoint_facts.get(after_obs.observation_id, ())
                         if fact["device_id"] == device_id and fact["field_key"] == field
                         and fact["conflict_state"] == "none"]
                for old_fact in matches:
                    matching = [fact for fact in newer if fact["source_file"] == old_fact["source_file"]
                                and fact["roster_policy_digest"] == old_fact["roster_policy_digest"]]
                    if (len(matches) == len(newer) == len(matching) == 1
                            and old_fact["roster_policy_digest"]
                            and old_fact["source_observed_at"] == source_time_for_sample(before_obs, old_fact["source_file"])
                            and matching[0]["source_observed_at"] == source_time_for_sample(after_obs, matching[0]["source_file"])):
                        items.append(derive_discrete_item(
                            interval, kind="categorical-transition", scope="device", subject_id=device_id,
                            metric=metric, before_value=old_fact["value"], after_value=matching[0]["value"],
                            before_source_time=old_fact["source_observed_at"],
                            after_source_time=matching[0]["source_observed_at"],
                            source_files=(old_fact["source_file"],),
                        ))
        old_parents = [link for link in before_obs.relationships if link.relationship_type == "parent-child"
                       and link.to_device_id == device_id]
        new_parents = [link for link in after_obs.relationships if link.relationship_type == "parent-child"
                       and link.to_device_id == device_id]
        if len(old_parents) == len(new_parents) == 1:
            parent_files = tuple(sorted(set(old_parents[0].source_files) | set(new_parents[0].source_files)))
            common_file = next((filename for filename in parent_files if filename in old_parents[0].source_files
                                and filename in new_parents[0].source_files
                                and (before_time := source_time_for_sample(before_obs, filename))
                                and (after_time := source_time_for_sample(after_obs, filename))
                                and _utc_timestamp(after_time) > _utc_timestamp(before_time)), None)
            items.append(derive_discrete_item(
                interval, kind="categorical-transition", scope="device", subject_id=device_id,
                metric="parent", before_value=old_parents[0].from_device_id,
                after_value=new_parents[0].from_device_id,
                before_source_time=source_time_for_sample(before_obs, common_file) if common_file else None,
                after_source_time=source_time_for_sample(after_obs, common_file) if common_file else None,
                source_files=parent_files,
            ))
    old_metrics = {(item.device_id, item.metric, item.source_file): item for item in before_obs.metrics}
    new_metrics = {(item.device_id, item.metric, item.source_file): item for item in after_obs.metrics}
    for key in sorted(old_metrics.keys() | new_metrics.keys()):
        device_id, metric_name, filename = key
        if metric_name not in METRIC_CATALOG:
            continue
        kind, unit, denominator_kind, preference = METRIC_CATALOG[metric_name]
        old, new = old_metrics.get(key), new_metrics.get(key)
        reset = (classify_reset(elapsed_seconds=interval.elapsed_seconds,
                                before_counter=old.value if old else None,
                                after_counter=new.value if new else None, policy=policy)
                 if kind == "counter-delta" else None)
        items.append(derive_numeric_item(
            interval, scope="device", subject_id=device_id, kind=kind, metric=metric_name,
            unit=unit, denominator_kind=denominator_kind,
            before_value=old.value if old and old.unit == unit else None,
            after_value=new.value if new and new.unit == unit else None,
            before_denominator=old.denominator if old else None,
            after_denominator=new.denominator if new else None,
            before_source_time=source_time_for_sample(before_obs, filename),
            after_source_time=source_time_for_sample(after_obs, filename),
            source_files=(filename,), reset_evidence=reset, preference=preference,
        ))
    old_links = {item.relationship_id: item for item in before_obs.relationships}
    new_links = {item.relationship_id: item for item in after_obs.relationships}
    for link_id in sorted(old_links.keys() | new_links.keys()):
        old, new = old_links.get(link_id), new_links.get(link_id)
        source_files = tuple(sorted(set(old.source_files if old else ()) | set(new.source_files if new else ())))
        common = next((filename for filename in source_files if
                       (old is None or filename in old.source_files) and
                       (new is None or filename in new.source_files) and
                       (before_time := source_time_for_sample(before_obs, filename)) and
                       (after_time := source_time_for_sample(after_obs, filename)) and
                       _utc_timestamp(after_time) > _utc_timestamp(before_time)), None)
        old_time = source_time_for_sample(before_obs, common) if common else None
        new_time = source_time_for_sample(after_obs, common) if common else None
        relationship_type = old.relationship_type if old else new.relationship_type
        item = derive_discrete_item(
            interval, kind="relationship-change", scope="relationship", subject_id=link_id,
            relationship_type=relationship_type, metric=None,
            before_value=old is not None, after_value=new is not None,
            before_source_time=old_time, after_source_time=new_time, source_files=source_files,
        )
        if old and new and old.relationship_type != new.relationship_type:
            item = replace(item, compatibility=_compatibility(set(item.compatibility.reasons) | {"relationship-mismatch"}),
                           change="unknown", transition=None)
        if relationship_type == "router-route":
            reporter_id = (old or new).reporter_device_id
            if not common or not reporter_id or any(
                not any(metric.device_id == reporter_id and metric.source_file == common
                        and metric.metric == "route64Coverage" and metric.unit == "flag" and metric.value == 1.0
                        for metric in observation.metrics)
                for observation in (before_obs, after_obs)
            ):
                item = replace(item, compatibility=_compatibility(set(item.compatibility.reasons) | {"metric-missing"}),
                               change="unknown", transition=None)
        items.append(item)
        if (old and old.queued_message_count is not None) or (new and new.queued_message_count is not None):
            items.append(derive_discrete_item(
                interval, kind="queue-persistence", scope="relationship", subject_id=link_id,
            metric="queuedMessageCount", before_value=old.queued_message_count if old else None,
            after_value=new.queued_message_count if new else None, before_source_time=old_time,
                after_source_time=new_time, source_files=source_files,
            ))
        for field, (unit, preference) in RELATIONSHIP_CATALOG.items():
            old_value = getattr(old, field) if old else None
            new_value = getattr(new, field) if new else None
            if old_value is None and new_value is None:
                continue
            items.append(derive_numeric_item(
                interval, scope="relationship", subject_id=link_id,
                kind="gauge-change", metric=field, unit=unit, denominator_kind=None,
                before_value=old_value, after_value=new_value,
                before_source_time=old_time, after_source_time=new_time,
                source_files=source_files, preference=preference,
            ))
    return interval, tuple(sorted(items, key=lambda item: (item.scope, item.subject_id, item.kind, item.metric or "", item.item_id)))


SUPPORTING_FIELDS = frozenset({
    "rloc16", "parent", "partition", "firmware", "source", "sampleContractVersion",
})


def supporting_changes(before: Mapping[str, str], after: Mapping[str, str]) -> tuple[SupportingChange, ...]:
    """Record observed transient changes without turning missing facts into changes."""
    return tuple(
        SupportingChange(field, before[field], after[field])
        for field in sorted(SUPPORTING_FIELDS & before.keys() & after.keys())
        if before[field] != after[field]
    )


def _finite_nonnegative(value: float | None) -> bool:
    return _finite(value) and value >= 0


def classify_reset(
    *,
    elapsed_seconds: int | None,
    before_epoch: str | None = None,
    after_epoch: str | None = None,
    before_uptime: float | None = None,
    after_uptime: float | None = None,
    before_counter: float | None = None,
    after_counter: float | None = None,
    policy: ComparisonPolicy = ComparisonPolicy(),
) -> ResetEvidence:
    """Qualify a since-reset interval using audited epochs or a trusted uptime witness."""
    if elapsed_seconds is None or elapsed_seconds < 0:
        return ResetEvidence("unknown", None, None, None)
    counter_pair = _finite_nonnegative(before_counter) and _finite_nonnegative(after_counter)
    if counter_pair and after_counter < before_counter:
        return ResetEvidence("reset-detected", "counter-decrease", before_counter, after_counter)
    if (before_counter is not None or after_counter is not None) and not counter_pair:
        return ResetEvidence("unknown", None, None, None)
    epoch_pair = isinstance(before_epoch, str) and bool(before_epoch) and isinstance(after_epoch, str) and bool(after_epoch)
    uptime_pair = _finite_nonnegative(before_uptime) and _finite_nonnegative(after_uptime)
    if uptime_pair and after_uptime < before_uptime:
        return ResetEvidence("reset-detected", "uptime", before_uptime, after_uptime)
    if epoch_pair and before_epoch != after_epoch:
        if uptime_pair and abs((after_uptime - before_uptime) - elapsed_seconds) <= policy.uptime_continuity_tolerance_seconds:
            return ResetEvidence("unknown", None, None, None)
        return ResetEvidence("reset-detected", "audited-epoch", before_epoch, after_epoch)
    if (before_uptime is not None or after_uptime is not None) and not uptime_pair:
        return ResetEvidence("unknown", None, None, None)
    if uptime_pair and abs((after_uptime - before_uptime) - elapsed_seconds) > policy.uptime_continuity_tolerance_seconds:
        return ResetEvidence("unknown", "uptime", before_uptime, after_uptime)
    if epoch_pair:
        return ResetEvidence("same-epoch", "audited-epoch", before_epoch, after_epoch)
    if uptime_pair:
        return ResetEvidence("same-epoch", "uptime", before_uptime, after_uptime)
    return ResetEvidence("unknown", None, None, None)


def source_time_for_sample(observation: Observation, filename: str) -> str | None:
    sources = [source for source in observation.sources if source.filename == filename]
    if len(sources) != 1 or sources[0].kind != "final" or sources[0].state != "valid":
        return None
    timestamp = sources[0].source_observed_at
    if timestamp is None:
        return None
    try:
        parsed = _utc_timestamp(timestamp)
        if parsed > _utc_timestamp(observation.ingested_at):
            return None
    except ValueError:
        return None
    return timestamp


def project_baseline_availability(
    interval: ComparisonInterval, *, before_retained: bool, after_retained: bool,
) -> ComparisonInterval:
    """Project pruned endpoints without changing the derived comparison."""
    if interval.baseline_state == "missing" or (before_retained and after_retained):
        return interval
    reasons = set(interval.compatibility.reasons)
    reasons.add("baseline-pruned")
    return replace(interval, baseline_state="pruned", compatibility=_compatibility(reasons))


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def comparison_id(before_assessment_id: str, after_assessment_id: str, policy: ComparisonPolicy) -> str:
    if not before_assessment_id or not after_assessment_id:
        raise ValueError("Comparison requires two assessment IDs")
    return "comparison:" + _digest((
        COMPARISON_VERSION, policy.digest, before_assessment_id, after_assessment_id,
    ))[:24]


def ordered_reasons(reasons: set[str]) -> tuple[str, ...]:
    unknown = reasons.difference(REASON_ORDER)
    if unknown:
        raise ValueError(f"Unknown comparison reasons: {sorted(unknown)}")
    return tuple(reason for reason in REASON_ORDER if reason in reasons)


def _compatibility(reasons: set[str]) -> Compatibility:
    ordered = ordered_reasons(reasons)
    return Compatibility(not ordered, "unknown", None,
                         ordered[0] if ordered else None, ordered)


def source_signature(observation: Observation, source_roles: Mapping[str, str]) -> str:
    """Fingerprint source composition, not source content or observation state."""
    sources = []
    for source in observation.sources:
        if source.filename not in source_roles or source_roles[source.filename] not in {"required", "optional"}:
            raise ValueError(f"Missing source role for {source.filename}")
        if not source.filename or "/" in source.filename or "\\" in source.filename or source.filename in {".", ".."}:
            raise ValueError("Source filename must be path-safe")
        sources.append((source.filename, source.kind, source_roles[source.filename]))
    if len({row[0] for row in sources}) != len(sources):
        raise ValueError("Duplicate observation source")
    return _digest(sorted(sources))


def source_roles_for_dataset(dataset: HealthDataset) -> Mapping[str, str]:
    """Map the manifest's required inputs to their source-composition roles."""
    filenames = (*dataset.files, dataset.health_profile.identity_file,
                 *dataset.health_profile.required_outcomes)
    if len(filenames) != len(set(filenames)):
        raise ValueError("Duplicate manifest source filename")
    return {filename: "required" for filename in filenames}


def _utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("Comparison timestamps require a timezone")
    return parsed


def compare_interval(
    before: tuple[Observation, Assessment] | None,
    after: tuple[Observation, Assessment] | None,
    *,
    before_assessment_id: str,
    after_assessment_id: str,
    source_roles: Mapping[str, str],
    policy: ComparisonPolicy = ComparisonPolicy(),
) -> ComparisonInterval:
    reasons: set[str] = set()
    if before is None or after is None:
        reasons.add("endpoint-missing")
    elapsed: int | None = None
    gap_state: str | None = None
    signature: str | None = None
    endpoint_digest: str | None = None
    baseline_observation_id: str | None = None
    after_observation_id: str | None = None
    before_time: str | None = None
    after_time: str | None = None
    if before is not None and after is not None:
        before_obs, before_assessment = before
        after_obs, after_assessment = after
        baseline_observation_id = before_obs.observation_id
        after_observation_id = after_obs.observation_id
        before_time, after_time = before_obs.observed_at, after_obs.observed_at
        if (before_assessment.assessment_id != before_assessment_id or
            after_assessment.assessment_id != after_assessment_id or
            before_assessment.observation_id != before_obs.observation_id or
            after_assessment.observation_id != after_obs.observation_id):
            raise ValueError("Assessment and observation IDs must match the requested endpoints")
        start = _utc_timestamp(before_obs.observed_at)
        end = _utc_timestamp(after_obs.observed_at)
        if (before_assessment_id == after_assessment_id or
            before_obs.observation_id == after_obs.observation_id or start >= end):
            reasons.add("endpoint-order-invalid")
        else:
            elapsed = math.floor((end - start).total_seconds())
            gap_state = "exceeded" if (end - start).total_seconds() > policy.max_comparison_gap_seconds else "within-limit"
            if gap_state == "exceeded":
                reasons.add("gap-exceeded")
        if (before_obs.network_id != after_obs.network_id or
            not before_obs.network_id.startswith("extpan:") or
            len(before_obs.network_id) != 23 or
            any(char not in "0123456789abcdef" for char in before_obs.network_id[7:])):
            reasons.add("network-mismatch")
        if (before_obs.datasource_id, before_obs.dataset_id) != (after_obs.datasource_id, after_obs.dataset_id):
            reasons.add("dataset-mismatch")
        if before_assessment.profile_id != after_assessment.profile_id:
            reasons.add("profile-mismatch")
        signature = source_signature(before_obs, source_roles)
        if signature != source_signature(after_obs, source_roles):
            reasons.add("source-signature-mismatch")
        supported_contracts = {COMPARISON_VERSION}
        if before_obs.dataset_id == after_obs.dataset_id == "otbr_cli_networkdiag_fetch_all":
            supported_contracts.add(ROUTE64_SAMPLE_CONTRACT_VERSION)
        if (before_assessment.sample_contract_version != after_assessment.sample_contract_version or
            before_assessment.sample_contract_version not in supported_contracts):
            reasons.add("sample-contract-mismatch")
        if before_assessment.evaluator_version != after_assessment.evaluator_version:
            reasons.add("evaluator-mismatch")
        if (not before_assessment.health_policy_digest or
            before_assessment.health_policy_digest != after_assessment.health_policy_digest):
            reasons.add("policy-mismatch")
        else:
            endpoint_digest = before_assessment.health_policy_digest
        if before_obs.completeness is not Completeness.COMPLETE or after_obs.completeness is not Completeness.COMPLETE:
            reasons.add("endpoint-incomplete")
    return ComparisonInterval(
        comparison_id(before_assessment_id, after_assessment_id, policy),
        before_assessment_id, after_assessment_id, endpoint_digest, policy.digest,
        signature, elapsed, gap_state, _compatibility(reasons),
        before_assessment_id, baseline_observation_id, after_observation_id, before_time, after_time,
        "available" if before is not None else "missing",
    )


def compare_item_compatibility(
    interval: ComparisonInterval,
    *,
    item_kind: str = "metric",
    before_subject: str | None,
    after_subject: str | None,
    before_role: str | None,
    after_role: str | None,
    before_relationship: tuple[str, str] | None,
    after_relationship: tuple[str, str] | None,
    before_metric: str | None,
    after_metric: str | None,
    before_unit: str | None,
    after_unit: str | None,
    before_denominator_kind: str | None,
    after_denominator_kind: str | None,
    before_source_time: str | None,
    after_source_time: str | None,
    since_reset: bool = False,
    reset_evidence: ResetEvidence | None = None,
    before_source_file: str | None = None,
    after_coverage_source: str | None = None,
    after_coverage_time: str | None = None,
) -> Compatibility:
    reasons = set(interval.compatibility.reasons)
    if item_kind not in {"metric", "presence", "relationship", "categorical", "queue"}:
        raise ValueError("Invalid comparison item kind")
    if not before_subject or before_subject != after_subject:
        reasons.add("subject-mismatch")
    if before_role != after_role:
        reasons.add("role-mismatch")
    if before_relationship != after_relationship:
        reasons.add("relationship-mismatch")
    if item_kind == "metric" and (not before_metric or before_metric != after_metric):
        reasons.add("metric-missing")
    if before_unit != after_unit:
        reasons.add("unit-mismatch")
    if before_denominator_kind != after_denominator_kind:
        reasons.add("denominator-mismatch")
    reset_state = reset_evidence.state if since_reset and reset_evidence is not None else "unknown" if since_reset else "not-applicable"
    if reset_state == "reset-detected":
        reasons.add("reset-detected")
    elif reset_state == "unknown":
        reasons.add("reset-unknown")
    elif reset_state not in {"same-epoch", "not-applicable"}:
        raise ValueError("Invalid reset state")
    effective_after_time = after_source_time
    if (item_kind == "presence" and not after_source_time and
        before_source_file and after_coverage_source == before_source_file):
        effective_after_time = after_coverage_time
    if (not before_source_time or not effective_after_time or
        _utc_timestamp(effective_after_time) <= _utc_timestamp(before_source_time)):
        reasons.add("source-not-newer")
    return _compatibility(reasons)