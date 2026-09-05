"""Pure snapshot-v1 health evaluation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Mapping

from td_health_observation_model import (
    Assessment,
    Completeness,
    Confidence,
    Finding,
    FindingRank,
    FindingScope,
    HealthStatus,
    Observation,
)
from td_health_policy import HealthPolicy
from td_health_manifest import HealthProfile


EVALUATOR_VERSION = "snapshot-v7"

_LIFETIME_EVIDENCE_METRICS = frozenset(
    {
        "parentChanges",
        "partitionIdChanges",
        "betterPartitionAttachAttempts",
        "totalParentPartitionChanges",
        "routerRolePercent",
        "detachedDisabledPercent",
    }
)

_HISTORICAL_METRIC_PRESENTATION = {
    "parentChanges": (
        "Parent Changes Since Counter Reset",
        "The cumulative parent-change count crossed its threshold. It may indicate earlier attachment "
        "instability, but a later comparable observation is required to establish current churn.",
    ),
    "partitionIdChanges": (
        "Partition ID Changes Since Counter Reset",
        "The cumulative partition-ID-change count crossed its threshold. Compare its change over time "
        "before concluding that partition instability is current.",
    ),
    "betterPartitionAttachAttempts": (
        "Better-Partition Attach Attempts Since Counter Reset",
        "The cumulative number of attempts to attach to a better partition crossed its threshold. "
        "A future delta is needed to determine whether attempts are continuing.",
    ),
    "totalParentPartitionChanges": (
        "Parent and Partition Changes Since Counter Reset",
        "The cumulative combined parent and partition change count crossed its threshold. "
        "It is historical evidence, not proof of current instability.",
    ),
    "routerRolePercent": (
        "Low Router-Role Time Since Reset",
        "The device has spent less than the configured proportion of its recorded uptime in the Router "
        "role. Interpret this against its intended role and compare future observations.",
    ),
    "detachedDisabledPercent": (
        "Detached or Disabled Time Since Reset",
        "The proportion of recorded uptime spent detached or disabled crossed its threshold. "
        "It does not establish that the device is currently detached.",
    ),
}


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _profile_digest(profile: HealthProfile) -> str:
    payload = {
        "evaluatorVersion": EVALUATOR_VERSION,
        "profileId": profile.profile_id,
        "coverage": dict(profile.coverage),
        "topologyAuthority": profile.topology_authority,
        "borderRouterAuthority": profile.border_router_authority,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _assessment_input_digest(policy: HealthPolicy, profile: HealthProfile) -> str:
    return hashlib.sha256(
        f"{policy.digest}\0{_profile_digest(profile)}".encode("utf-8")
    ).hexdigest()


def _finding(
    observation: Observation,
    *,
    rule_id: str,
    status: HealthStatus,
    scope: FindingScope,
    rank: FindingRank,
    title: str,
    summary: str,
    why: str,
    evidence: Mapping[str, object],
    action: str,
    verify: str,
    device_ids: tuple[str, ...] = (),
    relationship_ids: tuple[str, ...] = (),
    target_parts: tuple[str, ...] = (),
    source_files: tuple[str, ...] = (),
    confidence: Confidence = Confidence.HIGH,
) -> Finding:
    target = ",".join((*device_ids, *relationship_ids, *target_parts)) or observation.network_id
    return Finding(
        finding_id=_stable_id("finding", observation.observation_id, rule_id, target),
        rule_id=rule_id,
        status=status,
        scope=scope,
        rank=rank,
        title=title,
        summary=summary,
        why_it_matters=why,
        device_ids=device_ids,
        relationship_ids=relationship_ids,
        evidence=evidence,
        confidence=confidence,
        action=action,
        verify=verify,
        source_files=source_files,
    )


def evaluate_observation(
    observation: Observation,
    policy: HealthPolicy,
    *,
    profile: HealthProfile,
    expected_device_ids: frozenset[str] = frozenset(),
    prior_complete_absences: Mapping[str, int] | None = None,
    assessed_at: str | None = None,
    omr_prefix: str | None = None,
    device_ipv6_addresses: Mapping[str, tuple[str, ...]] | None = None,
) -> Assessment:
    absences = prior_complete_absences or {}
    findings: list[Finding] = []
    observed_ids = frozenset(device.device_id for device in observation.devices)
    complete = observation.completeness is Completeness.COMPLETE
    attachment_failed_device_ids: set[str] = set()

    for device in observation.devices:
        findings.append(
            _finding(
                observation,
                rule_id="device.observed",
                status=HealthStatus.STRONG,
                scope=FindingScope.DEVICE,
                rank=FindingRank.INFO,
                title="Observed Devices",
                summary="Device is present in this observation.",
                why="Device is present in this cached observation. Presence does not prove application "
                "reachability or continued availability.",
                evidence={"present": True, "completeness": observation.completeness.value},
                action="No action required.",
                verify="Process another complete cached observation to confirm continued presence.",
                device_ids=(device.device_id,),
                source_files=device.source_files,
            )
        )
        attachment = (device.state or device.role or "").lower()
        if attachment in {"detached", "disabled", "orphaned"}:
            attachment_failed_device_ids.add(device.device_id)
            findings.append(
                _finding(
                    observation,
                    rule_id="device.attachment-failure",
                    status=HealthStatus.POOR,
                    scope=FindingScope.DEVICE,
                    rank=FindingRank.POOR,
                    title="Device Not Attached to Mesh",
                    summary=f"Device reports current state {attachment}.",
                    why="The device currently reports a detached, disabled, or orphaned state and is "
                    "therefore not attached to the Thread mesh.",
                    evidence={"attachment": attachment},
                    action="Inspect the device and its parent or commissioning state.",
                    verify="Collect and process a new complete observation after remediation.",
                    device_ids=(device.device_id,),
                    source_files=device.source_files,
                )
            )

    missing_expected_ids = tuple(sorted(expected_device_ids - observed_ids))
    offline_candidate_ids = frozenset(
        device_id
        for device_id in missing_expected_ids
        if complete
        and absences.get(device_id, 0) + 1 >= policy.offline_consecutive_complete_observations
    )
    offline_device_ratio = (
        len(offline_candidate_ids) / len(expected_device_ids)
        if expected_device_ids
        else 0.0
    )
    offline_poor_threshold_met = (
        offline_device_ratio > policy.offline_poor_device_ratio_threshold
    )

    for device_id in missing_expected_ids:
        prior = absences.get(device_id, 0)
        is_offline = device_id in offline_candidate_ids and offline_poor_threshold_met
        findings.append(
            _finding(
                observation,
                rule_id="device.offline" if is_offline else "device.missing",
                status=HealthStatus.POOR if is_offline else HealthStatus.UNKNOWN,
                scope=FindingScope.DEVICE,
                rank=FindingRank.POOR if is_offline else FindingRank.INFO,
                title="Offline Devices" if is_offline else "Expected Device Missing",
                summary=(
                    f"Expected device is absent from {prior + 1} consecutive complete observations."
                    if is_offline
                    else "Expected device is not present, but Offline is not established."
                ),
                why=(
                    "An expected device has been absent for the required consecutive complete observations, "
                    "and the policy's missing-roster threshold has also been exceeded."
                    if is_offline
                    else "An expected device is absent from the latest observation but has not met the history "
                    "and completeness requirements for Offline status."
                ),
                evidence={
                    "present": False,
                    "completeObservation": complete,
                    "consecutiveCompleteAbsences": prior + 1 if complete else prior,
                    "required": policy.offline_consecutive_complete_observations,
                    "offlineCandidateCount": len(offline_candidate_ids),
                    "expectedRosterCount": len(expected_device_ids),
                    "offlineDeviceRatio": offline_device_ratio,
                    "offlinePoorDeviceRatioThreshold": policy.offline_poor_device_ratio_threshold,
                    "offlinePoorThresholdMet": offline_poor_threshold_met,
                },
                action="Check collection completeness, then inspect the expected device if absence persists.",
                verify="Process another complete observation and confirm whether the device returns.",
                device_ids=(device_id,),
                confidence=Confidence.HIGH if is_offline else Confidence.LOW,
            )
        )

    router_ids = tuple(sorted(
        device.device_id
        for device in observation.devices
        if (device.role or "").lower() in {"router", "leader"}
    ))
    border_router_ids = tuple(sorted(
        device.device_id for device in observation.devices if device.is_border_router
    ))
    router_count = len(router_ids)
    border_router_count = len(border_router_ids)
    if profile.coverage["resilience"] == "sufficient":
        findings.append(_finding(
            observation,
            rule_id="network.router-redundancy",
            status=(
                HealthStatus.UNKNOWN if router_count == 0
                else HealthStatus.MODERATE if router_count == 1
                else HealthStatus.STRONG
            ),
            scope=FindingScope.NETWORK,
            rank=FindingRank.MODERATE if router_count == 1 else FindingRank.INFO,
            title="Router Redundancy",
            summary=f"Observed {router_count} Router{'s' if router_count != 1 else ''}.",
            why="One observed routing device leaves mesh routing dependent on a single active Router; "
            "no observed Routers leaves redundancy Unknown.",
            evidence={"observedRouterCount": router_count, "moreThanOne": router_count > 1},
            action=(
                "Collect Router-bearing evidence." if router_count == 0
                else "Add or restore Router-capable devices if resilience is required."
            ),
            verify="Process a complete topology observation and compare the Router count.",
            device_ids=router_ids,
            source_files=tuple(sorted({source for device in observation.devices for source in device.source_files})),
            confidence=Confidence.HIGH if router_count else Confidence.LOW,
        ))
    if profile.border_router_authority:
        border_router_summary = f"Observed {border_router_count} Border Router{'s' if border_router_count != 1 else ''}."
        if not complete:
            border_router_summary += f" Source completeness is {observation.completeness.value}, so redundancy is provisional."
        findings.append(_finding(
            observation,
            rule_id="network.border-router-redundancy",
            status=(
                HealthStatus.UNKNOWN if not complete or border_router_count == 0
                else HealthStatus.MODERATE if border_router_count == 1
                else HealthStatus.STRONG
            ),
            scope=FindingScope.NETWORK,
            rank=FindingRank.MODERATE if complete and border_router_count == 1 else FindingRank.INFO,
            title="Border Router Redundancy",
            summary=border_router_summary,
            why="One observed Border Router provides no Border Router failover; an incomplete observation "
            "or no authoritative count leaves redundancy Unknown.",
            evidence={"observedBorderRouterCount": border_router_count, "moreThanOne": border_router_count > 1},
            action=(
                "Collect complete Border-Router-bearing evidence." if not complete or border_router_count == 0
                else "Add or restore a second Border Router if resilience is required."
            ),
            verify="Process a complete Border-Router-bearing observation.",
            device_ids=border_router_ids,
            source_files=tuple(sorted({
                source
                for device in observation.devices
                if device.is_border_router
                for source in device.source_files
            })),
            confidence=Confidence.HIGH if complete and border_router_count else Confidence.LOW,
        ))

    if profile.border_router_authority and complete and omr_prefix:
        addresses = device_ipv6_addresses or {}
        omr_border_router_ids = tuple(sorted(
            device_id for device_id in border_router_ids
            if any(addr.startswith(omr_prefix) for addr in addresses.get(device_id, ()))
        ))
        findings.append(_finding(
            observation,
            rule_id="network.external-routing",
            status=(
                HealthStatus.STRONG if omr_border_router_ids
                else HealthStatus.MODERATE if border_router_ids
                else HealthStatus.UNKNOWN
            ),
            scope=FindingScope.EXTERNAL,
            rank=(
                FindingRank.INFO if omr_border_router_ids
                else FindingRank.MODERATE if border_router_ids
                else FindingRank.INFO
            ),
            title="Border Router OMR Addressing",
            summary=(
                f"{len(omr_border_router_ids)} Border Router{'s' if len(omr_border_router_ids) != 1 else ''} "
                "advertise an address in the OMR prefix."
                if omr_border_router_ids
                else "No Border Router has an observed address within the OMR prefix."
            ),
            why="An OMR-prefixed address supports Border Router OMR configuration but does not verify "
            "backbone, default-route, or Internet reachability.",
            evidence={
                "omrPrefix": omr_prefix,
                "borderRouterCount": len(border_router_ids),
                "omrBorderRouterIds": omr_border_router_ids,
            },
            action=(
                "No action required." if omr_border_router_ids
                else "Inspect Border Router backbone connectivity and OMR prefix advertisement."
            ),
            verify="Process a complete observation and confirm a Border Router address remains in the OMR prefix.",
            device_ids=omr_border_router_ids or border_router_ids,
            confidence=(
                Confidence.HIGH if omr_border_router_ids
                else Confidence.MEDIUM if border_router_ids
                else Confidence.LOW
            ),
        ))

    adjacency: dict[str, set[str]] = {device.device_id: set() for device in observation.devices}
    router_adjacency: dict[str, set[str]] = {device_id: set() for device_id in router_ids}
    for relationship in observation.relationships:
        adjacency.setdefault(relationship.from_device_id, set()).add(relationship.to_device_id)
        adjacency.setdefault(relationship.to_device_id, set()).add(relationship.from_device_id)
        if relationship.relationship_type == "router-neighbor":
            router_adjacency.setdefault(relationship.from_device_id, set()).add(
                relationship.to_device_id
            )
            router_adjacency.setdefault(relationship.to_device_id, set()).add(
                relationship.from_device_id
            )
    sole_path_router_ids = tuple(sorted(
        device_id for device_id in router_ids if len(router_adjacency.get(device_id, set())) == 1
    ))
    alternate_path_router_ids = tuple(sorted(
        device_id for device_id in router_ids if len(router_adjacency.get(device_id, set())) > 1
    ))
    if observation.relationships and profile.topology_authority:
        findings.append(
            _finding(
                observation,
                rule_id="network.current-path-redundancy",
                status=HealthStatus.MODERATE if sole_path_router_ids else HealthStatus.STRONG,
                scope=FindingScope.NETWORK,
                rank=FindingRank.MODERATE if sole_path_router_ids else FindingRank.INFO,
                title="Router Path Redundancy",
                summary=(
                    f"Observed {len(sole_path_router_ids)} Router(s) with one current relationship."
                    if sole_path_router_ids
                    else f"Observed alternate relationships for {len(alternate_path_router_ids)} Router(s)."
                ),
                why="A Router with only one observed router-neighbor relationship may be a current single "
                "point of failure; child relationships do not establish alternate router paths.",
                evidence={
                    "solePathRouterIds": sole_path_router_ids,
                    "alternatePathRouterIds": alternate_path_router_ids,
                },
                action="Inspect sole-path Routers and preserve an alternate usable relationship.",
                verify="Process another complete topology observation and compare current relationships.",
                device_ids=sole_path_router_ids,
            )
        )

    metric_sources: dict[str, set[str]] = {}
    lq_counts = {1: 0.0, 2: 0.0, 3: 0.0}
    diagnostic_timeout_device_ids: set[str] = set()
    for metric in observation.metrics:
        metric_sources.setdefault(metric.metric, set()).add(metric.source_file)
        if metric.metric.startswith("observedLinkQuality"):
            quality = int(metric.metric.removeprefix("observedLinkQuality").removesuffix("Count"))
            lq_counts[quality] += metric.value
            continue
        if metric.metric == "diagnosticTimeout":
            diagnostic_timeout_device_ids.add(metric.device_id)
            continue
        threshold = policy.thresholds.get(metric.metric)
        if threshold is None:
            continue
        if metric.metric in _LIFETIME_EVIDENCE_METRICS:
            metric_title, metric_description = _HISTORICAL_METRIC_PRESENTATION[metric.metric]
            lower_is_worse = "unstableBelow" in threshold
            crossed = (
                metric.value < threshold["unstableBelow"] if lower_is_worse
                else metric.value >= threshold["unstable"]
            )
            if not crossed:
                continue
            high_key = "highBelow" if lower_is_worse else "high"
            band = (
                "high"
                if high_key in threshold and (
                    metric.value < threshold[high_key] if lower_is_worse
                    else metric.value >= threshold[high_key]
                )
                else "moderate"
            )
            findings.append(
                _finding(
                    observation,
                    rule_id=f"device.{metric.metric}",
                    status=HealthStatus.UNKNOWN,
                    scope=FindingScope.DEVICE,
                    rank=FindingRank.INFO,
                    title=metric_title,
                    summary=f"{metric.metric} is {metric.value:g} ({band} band); lifetime/since-reset evidence only.",
                    why=metric_description,
                    evidence={
                        "metric": metric.metric,
                        "value": metric.value,
                        "unit": metric.unit,
                        "band": band,
                        "thresholds": dict(threshold),
                    },
                    action="Compare against a future observation before treating this as a current failure.",
                    verify="Process another complete observation and compare the delta or trend.",
                    device_ids=(metric.device_id,),
                    target_parts=(metric.source_file,),
                    source_files=(metric.source_file,),
                    confidence=Confidence.LOW,
                )
            )
            continue
        if metric.value < threshold["unstable"]:
            continue
        critical = threshold.get("critical")
        escalate_poor = (
            critical is not None
            and metric.value >= critical
            and metric.device_id in attachment_failed_device_ids
        )
        severity_tier = (
            "critical" if critical is not None and metric.value >= critical
            else "high" if metric.value >= threshold["high"]
            else "moderate"
        )
        findings.append(
            _finding(
                observation,
                rule_id=f"device.{metric.metric}",
                status=HealthStatus.POOR if escalate_poor else HealthStatus.MODERATE,
                scope=FindingScope.DEVICE,
                rank=FindingRank.POOR if escalate_poor else FindingRank.MODERATE,
                title=(
                    "High Device MAC Error Ratio"
                    if metric.metric == "totalMacErrorRatio"
                    else "High Device MAC Discard Ratio"
                ),
                summary=f"Current ratio is {metric.value:.1%} ({severity_tier} band).",
                why=(
                    "The current device-wide MAC error ratio crossed a policy threshold using a valid packet "
                    "denominator, indicating degraded delivery in this observation."
                    if metric.metric == "totalMacErrorRatio"
                    else "The current device-wide MAC discard ratio crossed a policy threshold using a valid "
                    "packet denominator, indicating packet loss before successful delivery."
                ),
                evidence={
                    "metric": metric.metric,
                    "value": metric.value,
                    "unit": metric.unit,
                    "denominator": metric.denominator,
                    "unstableThreshold": threshold["unstable"],
                    "highThreshold": threshold["high"],
                    "criticalThreshold": critical,
                    "severityTier": severity_tier,
                    "escalatedByAttachmentFailure": escalate_poor,
                },
                action="Inspect link conditions and packet counters for this device.",
                verify="Process another complete observation with a valid packet denominator.",
                device_ids=(metric.device_id,),
                target_parts=(metric.source_file,),
                source_files=(metric.source_file,),
            )
        )

    for device_id in sorted(diagnostic_timeout_device_ids):
        findings.append(
            _finding(
                observation,
                rule_id="device.diagnostic-timeout",
                status=HealthStatus.UNKNOWN,
                scope=FindingScope.DEVICE,
                rank=FindingRank.INFO,
                title="Mesh Diagnostic Query Timed Out",
                summary="The device did not respond to a mesh diagnostic query in this observation.",
                why="A timeout reduces evidence coverage and may reflect sleep behavior, congestion, overload, "
                "or loss of connectivity.",
                evidence={"responseTimeout": True},
                action="Investigate load, sleep behavior, or connectivity if this persists across observations.",
                verify="Process another complete observation and confirm whether the device responds.",
                device_ids=(device_id,),
                confidence=Confidence.LOW,
            )
        )

    if observation.duplicate_relationship_ids:
        findings.append(
            _finding(
                observation,
                rule_id="observation.duplicate-source-entry",
                status=HealthStatus.UNKNOWN,
                scope=FindingScope.NETWORK,
                rank=FindingRank.INFO,
                title="Duplicate Relationships in Source Data",
                summary=(
                    f"{len(observation.duplicate_relationship_ids)} relationship(s) appeared more than "
                    "once within one source file."
                ),
                why="The duplicate is treated as a collection artifact, not as a separate relationship.",
                evidence={"relationshipIds": observation.duplicate_relationship_ids},
                action="No action required unless duplicates recur across many observations.",
                verify="Confirm the relationship count is unaffected in the next complete observation.",
                relationship_ids=observation.duplicate_relationship_ids,
                confidence=Confidence.LOW,
            )
        )

    observed_lq_total = sum(lq_counts.values())
    if observed_lq_total > 0:
        lq3_ratio = lq_counts[3] / observed_lq_total
        lq2_ratio = lq_counts[2] / observed_lq_total
        lq1_ratio = lq_counts[1] / observed_lq_total
        lq3_bad = lq3_ratio < policy.thresholds["observedLq3Ratio"]["unstableBelow"]
        lq1_bad = lq1_ratio >= policy.thresholds["observedLq1Ratio"]["unstable"]
        findings.append(
            _finding(
                observation,
                rule_id="network.observed-link-quality-ratios",
                status=HealthStatus.MODERATE if lq3_bad or lq1_bad else HealthStatus.STRONG,
                scope=FindingScope.NETWORK,
                rank=FindingRank.MODERATE if lq3_bad or lq1_bad else FindingRank.INFO,
                title="Network Link Quality Distribution",
                summary=(
                    f"LQ3 is {lq3_ratio:.1%}; LQ2 is {lq2_ratio:.1%}; "
                    f"LQ1 is {lq1_ratio:.1%} of observed links."
                ),
                why="Missing and unknown quality reports are excluded rather than treated as healthy.",
                evidence={
                    "observedCount": observed_lq_total,
                    "lq3Ratio": lq3_ratio,
                    "lq2Ratio": lq2_ratio,
                    "lq1Ratio": lq1_ratio,
                    "lq3UnstableBelow": policy.thresholds["observedLq3Ratio"]["unstableBelow"],
                    "lq1UnstableAtOrAbove": policy.thresholds["observedLq1Ratio"]["unstable"],
                },
                action="Inspect weak relationships and preserve strong alternate paths.",
                verify="Process another complete topology observation and compare the distribution.",
                source_files=tuple(sorted(
                    metric_sources.get("observedLinkQuality1Count", set())
                    | metric_sources.get("observedLinkQuality2Count", set())
                    | metric_sources.get("observedLinkQuality3Count", set())
                )),
            )
        )

    neighbor_high_error_relationships: dict[str, set[str]] = {}
    for relationship in observation.relationships:
        child_relationship = relationship.relationship_type == "parent-child"
        frame_threshold = policy.thresholds[
            "childFrameErrorRate" if child_relationship else "routerNeighborFrameErrorRate"
        ]
        message_threshold = policy.thresholds[
            "childMessageErrorRate" if child_relationship else "routerNeighborMessageErrorRate"
        ]
        quality_values = tuple(
            value
            for value in (relationship.link_quality_in, relationship.link_quality_out)
            if value is not None and value > 0
        )
        asymmetric = (
            relationship.link_quality_in is not None
            and relationship.link_quality_out is not None
            and relationship.link_quality_in != relationship.link_quality_out
        )
        weak = bool(quality_values) and min(quality_values) <= 2
        frame_bad = (
            relationship.frame_error_rate is not None
            and relationship.frame_error_rate >= frame_threshold["unstable"]
        )
        message_bad = (
            relationship.message_error_rate is not None
            and relationship.message_error_rate >= message_threshold["unstable"]
        )
        rssi_bad = (
            relationship.last_rssi is not None
            and relationship.last_rssi < policy.thresholds["rssi"]["unstableBelow"]
        )
        margin_bad = (
            relationship.link_margin is not None
            and relationship.link_margin < policy.thresholds["childLinkMargin"]["unstableBelow"]
        )
        lq3_agreement = (
            relationship.link_quality_in == 3 and relationship.link_quality_out == 3
        )
        critical_delivery = (
            (relationship.frame_error_rate is not None
             and relationship.frame_error_rate >= frame_threshold.get("critical", float("inf")))
            or (relationship.message_error_rate is not None
                and relationship.message_error_rate >= message_threshold.get("critical", float("inf")))
        )
        sole_path = (
            len(adjacency.get(relationship.from_device_id, set())) <= 1
            or len(adjacency.get(relationship.to_device_id, set())) <= 1
        )
        if relationship.queued_message_count is not None and relationship.queued_message_count > 0:
            findings.append(
                _finding(
                    observation,
                    rule_id="relationship.queued-messages",
                    status=HealthStatus.UNKNOWN,
                    scope=FindingScope.RELATIONSHIP,
                    rank=FindingRank.INFO,
                    title="Indirect Messages Queued for Child",
                    summary=f"{relationship.queued_message_count:g} indirect message(s) queued for delivery.",
                    why="Queued indirect messages can be normal for a sleepy child; persistence or growth "
                    "across observations is more significant than one current queue depth.",
                    evidence={"queuedMessageCount": relationship.queued_message_count},
                    action="Compare against a future observation before treating this as a current failure.",
                    verify="Process another complete observation and confirm the queue clears.",
                    device_ids=(relationship.from_device_id, relationship.to_device_id),
                    relationship_ids=(relationship.relationship_id,),
                    source_files=relationship.source_files,
                    confidence=Confidence.LOW,
                )
            )
        if frame_bad or message_bad:
            neighbor_high_error_relationships.setdefault(relationship.to_device_id, set()).add(
                relationship.relationship_id
            )
        error_uncorrelated_with_rss = (
            (frame_bad or message_bad)
            and not rssi_bad
            and not margin_bad
            and (relationship.last_rssi is not None or relationship.link_margin is not None)
        )
        if weak or asymmetric or frame_bad or message_bad or rssi_bad or margin_bad:
            finding_status = (
                HealthStatus.POOR if critical_delivery and sole_path
                else HealthStatus.MODERATE
            )
            findings.append(
                _finding(
                    observation,
                    rule_id="relationship.directional-quality",
                    status=finding_status,
                    scope=FindingScope.RELATIONSHIP,
                    rank=(
                        FindingRank.POOR
                        if finding_status is HealthStatus.POOR
                        else FindingRank.MODERATE
                    ),
                    title=(
                        "High Delivery Errors Despite Acceptable Signal"
                        if error_uncorrelated_with_rss
                        else "Link Quality or Delivery Degradation"
                    ),
                    summary=(
                        "Frame or message errors are elevated despite adequate RSS/margin evidence; "
                        "suspect interference or firmware rather than distance."
                        if error_uncorrelated_with_rss
                        else "Current directional quality, delivery, or RF evidence crossed a snapshot threshold."
                    ),
                    why=(
                        "Frame or message errors are elevated even though observed RSS or link margin is not "
                        "weak. Investigate interference, congestion, or implementation issues before assuming "
                        "distance is the cause."
                        if error_uncorrelated_with_rss
                        else "Directional LQ, asymmetry, delivery errors, RSS, or link margin crossed a "
                        "current-snapshot threshold. Critical delivery errors become Poor only when an endpoint "
                        "has no observed alternate relationship."
                    ),
                    evidence={
                        "linkQualityIn": relationship.link_quality_in,
                        "linkQualityOut": relationship.link_quality_out,
                        "asymmetric": asymmetric,
                        "frameErrorRate": relationship.frame_error_rate,
                        "messageErrorRate": relationship.message_error_rate,
                        "lastRssi": relationship.last_rssi,
                        "linkMargin": relationship.link_margin,
                        "relationshipType": relationship.relationship_type,
                        "solePath": sole_path,
                        "errorUncorrelatedWithRss": error_uncorrelated_with_rss,
                    },
                    action=(
                        "Investigate interference or firmware for this device before relocating it."
                        if error_uncorrelated_with_rss
                        else "Inspect both endpoints and nearby RF conditions; preserve alternate paths."
                    ),
                    verify="Collect another complete observation and compare both directions.",
                    device_ids=(relationship.from_device_id, relationship.to_device_id),
                    relationship_ids=(relationship.relationship_id,),
                    source_files=relationship.source_files,
                )
            )
        elif lq3_agreement:
            findings.append(
                _finding(
                    observation,
                    rule_id="relationship.bidirectional-lq3",
                    status=HealthStatus.STRONG,
                    scope=FindingScope.RELATIONSHIP,
                    rank=FindingRank.INFO,
                    title="Strong Bidirectional Link (LQ3)",
                    summary="Both observed directions report LQ3.",
                    why="Both observed directions report LQ3, providing current evidence of a strong usable "
                    "relationship.",
                    evidence={"linkQualityIn": 3, "linkQualityOut": 3},
                    action="No action required.",
                    verify="Compare both directions in the next complete observation.",
                    device_ids=(relationship.from_device_id, relationship.to_device_id),
                    relationship_ids=(relationship.relationship_id,),
                    source_files=relationship.source_files,
                )
            )

    for device_id, relationship_ids in sorted(neighbor_high_error_relationships.items()):
        if len(relationship_ids) < 2:
            continue
        findings.append(
            _finding(
                observation,
                rule_id="device.multiple-reporters-high-error",
                status=HealthStatus.MODERATE,
                scope=FindingScope.DEVICE,
                rank=FindingRank.MODERATE,
                title="High Link Errors Reported by Multiple Neighbors",
                summary=f"{len(relationship_ids)} distinct reporters recorded high frame or message error rates.",
                why="Two or more observed relationships report elevated frame or message error rates toward "
                "this device, providing stronger evidence than one reporter alone.",
                evidence={"reporterRelationshipIds": tuple(sorted(relationship_ids))},
                action="Investigate interference or firmware for this device rather than one specific link.",
                verify="Process another complete observation and confirm whether multiple reporters still agree.",
                device_ids=(device_id,),
                relationship_ids=tuple(sorted(relationship_ids)),
                confidence=Confidence.HIGH,
            )
        )

    material = [
        finding
        for finding in findings
        if finding.status in {HealthStatus.MODERATE, HealthStatus.POOR}
    ]
    if any(finding.status is HealthStatus.POOR for finding in material):
        status = HealthStatus.POOR
    elif any(finding.status is HealthStatus.MODERATE for finding in material):
        status = HealthStatus.MODERATE
    elif (
        complete
        and observation.devices
        and all(state == "sufficient" for state in profile.coverage.values())
    ):
        status = HealthStatus.STRONG
    else:
        status = HealthStatus.UNKNOWN
    sufficient_pillars = sum(
        state == "sufficient" for state in profile.coverage.values()
    )
    if not complete:
        confidence = (
            Confidence.MEDIUM
            if observation.completeness is Completeness.DEGRADED
            else Confidence.LOW
        )
    elif sufficient_pillars >= 4:
        confidence = Confidence.HIGH
    elif sufficient_pillars >= 2:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW
    coverage = {
        "completeness": observation.completeness.value,
        "pillars": dict(profile.coverage),
        "confidenceReasons": [
            f"{sufficient_pillars} of {len(profile.coverage)} pillars sufficient",
            f"source completeness is {observation.completeness.value}",
        ],
        "topologyAuthority": profile.topology_authority,
        "borderRouterAuthority": profile.border_router_authority,
        "deviceCount": len(observation.devices),
        "relationshipCount": len(observation.relationships),
        "expectedRosterCount": len(expected_device_ids),
        "offlineEligible": complete and bool(expected_device_ids),
        "diagnosticTimeoutDeviceCount": len(diagnostic_timeout_device_ids),
        "diagnosticTimeoutRatio": (
            len(diagnostic_timeout_device_ids) / len(observation.devices)
            if observation.devices
            else 0.0
        ),
    }
    assessment_time = assessed_at or datetime.now(timezone.utc).isoformat()
    assessment_input_digest = _assessment_input_digest(policy, profile)
    assessment_id = _stable_id(
        "assessment", observation.observation_id, assessment_input_digest
    )
    return Assessment(
        assessment_id=assessment_id,
        observation_id=observation.observation_id,
        policy_version=policy.version,
        policy_digest=assessment_input_digest,
        status=status,
        confidence=confidence,
        coverage=coverage,
        findings=tuple(sorted(findings, key=lambda item: (-int(item.rank), item.finding_id))),
        assessed_at=assessment_time,
    )