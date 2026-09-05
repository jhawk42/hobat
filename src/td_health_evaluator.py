"""Pure snapshot-v1 health evaluation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

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
from td_health_graph import GraphEdge, analyze_undirected_graph
from td_health_rules import HEALTH_RULE_CATALOG, HealthRuleCatalogError


EVALUATOR_VERSION = "snapshot-v9"

EVALUATOR_THRESHOLD_OWNERS = {
    "offlineConsecutiveCompleteObservations": frozenset({"device.offline", "device.missing"}),
    "offlinePoorDeviceRatioThreshold": frozenset({"network.offline-impact"}),
    "thresholds.totalMacErrorRatio": frozenset({"device.totalMacErrorRatio"}),
    "thresholds.totalMacDiscardRatio": frozenset({"device.totalMacDiscardRatio"}),
    "thresholds.routerNeighborFrameErrorRate": frozenset({"relationship.directional-quality"}),
    "thresholds.routerNeighborMessageErrorRate": frozenset({"relationship.directional-quality"}),
    "thresholds.childFrameErrorRate": frozenset({"relationship.directional-quality"}),
    "thresholds.childMessageErrorRate": frozenset({"relationship.directional-quality"}),
    "thresholds.observedLq3Ratio": frozenset({"network.observed-link-quality-ratios"}),
    "thresholds.observedLq1Ratio": frozenset({"network.observed-link-quality-ratios"}),
    "thresholds.childLinkQuality": frozenset({"relationship.directional-quality"}),
    "thresholds.routerLinkQuality": frozenset({"relationship.directional-quality"}),
    "thresholds.rssi": frozenset({"relationship.directional-quality"}),
    "thresholds.childLinkMargin": frozenset({"relationship.directional-quality"}),
    "thresholds.multipleReporterCount": frozenset({"device.multiple-reporters-high-error"}),
    "thresholds.borderRouterCount": frozenset({"network.border-router-redundancy"}),
    "thresholds.routerCount": frozenset({"network.router-redundancy"}),
    "thresholds.parentChanges": frozenset({"device.parentChanges"}),
    "thresholds.partitionIdChanges": frozenset({"device.partitionIdChanges"}),
    "thresholds.betterPartitionAttachAttempts": frozenset({"device.betterPartitionAttachAttempts"}),
    "thresholds.totalParentPartitionChanges": frozenset({"device.totalParentPartitionChanges"}),
    "thresholds.routerRolePercent": frozenset({"device.routerRolePercent"}),
    "thresholds.detachedDisabledPercent": frozenset({"device.detachedDisabledPercent"}),
}

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


def _policy_value(policy: HealthPolicy, rule_id: str, key: str) -> Any:
    if rule_id not in EVALUATOR_THRESHOLD_OWNERS.get(key, ()):
        raise HealthRuleCatalogError(
            f"Rule {rule_id} does not own policy key {key}"
        )
    if key not in HEALTH_RULE_CATALOG.rule(rule_id).threshold_keys:
        raise HealthRuleCatalogError(
            f"Rule {rule_id} does not declare policy key {key}"
        )
    if key == "offlineConsecutiveCompleteObservations":
        return policy.offline_consecutive_complete_observations
    if key == "offlinePoorDeviceRatioThreshold":
        return policy.offline_poor_device_ratio_threshold
    return policy.thresholds[key.removeprefix("thresholds.")]


def _device_role_tags(observation: Observation) -> dict[str, frozenset[str]]:
    return {
        device.device_id: frozenset({
            *((device.role or "").lower(),),
            *({"border-router"} if device.is_border_router else set()),
        } - {""})
        for device in observation.devices
    }


def _profile_supports_rule(profile: HealthProfile, rule_id: str) -> bool:
    capability = HEALTH_RULE_CATALOG.rule(rule_id).required_capability
    return capability is None or profile.coverage[capability] != "missing"


def _validate_finding_applicability(
    finding: Finding, observation: Observation, profile: HealthProfile
) -> None:
    rule = HEALTH_RULE_CATALOG.rule(finding.rule_id)
    if (
        rule.required_capability is not None
        and profile.coverage[rule.required_capability] == "missing"
    ):
        raise HealthRuleCatalogError(
            f"Rule {rule.rule_id} requires missing capability {rule.required_capability}"
        )
    relationship_types = {
        relationship.relationship_id: relationship.relationship_type
        for relationship in observation.relationships
    }
    if rule.relationship_types:
        for relationship_id in finding.relationship_ids:
            relationship_type = relationship_types.get(relationship_id)
            if relationship_type not in rule.relationship_types:
                raise HealthRuleCatalogError(
                    f"Rule {rule.rule_id} does not apply to relationship {relationship_type!r}"
                )
    role_tags = _device_role_tags(observation)
    if rule.roles:
        for device_id in finding.device_ids:
            if device_id in role_tags and not role_tags[device_id] & rule.roles:
                raise HealthRuleCatalogError(
                    f"Rule {rule.rule_id} does not apply to roles {sorted(role_tags[device_id])}"
                )


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
    source_requirement: str | None = None,
    confidence: Confidence = Confidence.HIGH,
) -> Finding:
    rule = HEALTH_RULE_CATALOG.rule(rule_id)
    if scope.value not in rule.scopes:
        raise HealthRuleCatalogError(
            f"Rule {rule_id} does not support scope {scope.value}"
        )
    matching_variants = tuple(
        variant for variant, variant_title in rule.variants.items()
        if variant_title == title
    )
    if title == rule.title:
        presentation_variant = None
    elif len(matching_variants) == 1:
        presentation_variant = matching_variants[0]
    else:
        raise HealthRuleCatalogError(
            f"Title {title!r} is not cataloged for {rule_id}"
        )
    catalog_evidence = dict(evidence)
    if rule.source_requirements:
        if source_requirement not in rule.source_requirements or not any(source_files):
            raise HealthRuleCatalogError(
                f"Rule {rule_id} requires source evidence from {sorted(rule.source_requirements)}"
            )
        catalog_evidence["sourceRequirement"] = source_requirement
    if rule.requires_denominator:
        denominator = catalog_evidence.get("denominator")
        if not isinstance(denominator, (int, float)) or denominator <= 0:
            raise HealthRuleCatalogError(
                f"Rule {rule_id} requires a positive denominator"
            )
    catalog_evidence["evidenceKind"] = rule.evidence_kind
    catalog_evidence["materiality"] = rule.materiality
    if presentation_variant is not None:
        catalog_evidence["presentationVariant"] = presentation_variant
    target = ",".join((*device_ids, *relationship_ids, *target_parts)) or observation.network_id
    return Finding(
        finding_id=_stable_id("finding", observation.observation_id, rule_id, target),
        rule_id=rule_id,
        status=status,
        scope=scope,
        rank=rank,
        title=rule.title_for(presentation_variant),
        summary=summary,
        why_it_matters=rule.description,
        device_ids=device_ids,
        relationship_ids=relationship_ids,
        evidence=catalog_evidence,
        confidence=confidence,
        action=rule.action,
        verify=rule.verify,
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
    offline_required = _policy_value(
        policy, "device.offline", "offlineConsecutiveCompleteObservations"
    )
    offline_candidate_ids = frozenset(
        device_id
        for device_id in missing_expected_ids
        if complete
        and absences.get(device_id, 0) + 1 >= offline_required
    )
    offline_device_ratio = (
        len(offline_candidate_ids) / len(expected_device_ids)
        if expected_device_ids
        else 0.0
    )
    offline_ratio_threshold = _policy_value(
        policy, "network.offline-impact", "offlinePoorDeviceRatioThreshold"
    )
    offline_poor_threshold_met = offline_device_ratio > offline_ratio_threshold

    for device_id in missing_expected_ids:
        prior = absences.get(device_id, 0)
        is_offline = device_id in offline_candidate_ids
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
                    "An expected device has been absent for the required consecutive complete observations. "
                    "Network impact is assessed separately."
                    if is_offline
                    else "An expected device is absent from the latest observation but has not met the history "
                    "and completeness requirements for Offline status."
                ),
                evidence={
                    "present": False,
                    "completeObservation": complete,
                    "consecutiveCompleteAbsences": prior + 1 if complete else prior,
                    "required": offline_required,
                    "offlineCandidateCount": len(offline_candidate_ids),
                    "expectedRosterCount": len(expected_device_ids),
                    "offlineDeviceRatio": offline_device_ratio,
                    "offlinePoorDeviceRatioThreshold": offline_ratio_threshold,
                    "offlinePoorThresholdMet": offline_poor_threshold_met,
                },
                action="Check collection completeness, then inspect the expected device if absence persists.",
                verify="Process another complete observation and confirm whether the device returns.",
                device_ids=(device_id,),
                confidence=Confidence.HIGH if is_offline else Confidence.LOW,
            )
        )

    if offline_candidate_ids and offline_poor_threshold_met:
        findings.append(
            _finding(
                observation,
                rule_id="network.offline-impact",
                status=HealthStatus.POOR,
                scope=FindingScope.NETWORK,
                rank=FindingRank.POOR,
                title="Offline Device Network Impact",
                summary=(
                    f"{len(offline_candidate_ids)} of {len(expected_device_ids)} expected devices "
                    f"are Offline ({offline_device_ratio:.1%})."
                ),
                why="The Offline share of the configured roster exceeds policy. Device role, operator "
                "criticality, attached descendants, and required-service impact are not yet available.",
                evidence={
                    "offlineDeviceIds": tuple(sorted(offline_candidate_ids)),
                    "offlineDeviceCount": len(offline_candidate_ids),
                    "expectedRosterCount": len(expected_device_ids),
                    "offlineDeviceRatio": offline_device_ratio,
                    "threshold": offline_ratio_threshold,
                    "availableMaterialityInputs": ("configuredRosterRatio",),
                    "unavailableMaterialityInputs": (
                        "deviceRole",
                        "operatorCriticality",
                        "attachedDescendants",
                        "requiredServiceImpact",
                    ),
                },
                action="Restore Offline devices or revise the expected roster after confirming their operational role.",
                verify="Process another complete observation and confirm the Offline ratio falls below policy.",
                device_ids=tuple(sorted(offline_candidate_ids)),
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
        router_count_threshold = _policy_value(
            policy, "network.router-redundancy", "thresholds.routerCount"
        )["unstableAtOrBelow"]
        findings.append(_finding(
            observation,
            rule_id="network.router-redundancy",
            status=(
                HealthStatus.UNKNOWN if router_count == 0
                else HealthStatus.MODERATE if router_count <= router_count_threshold
                else HealthStatus.STRONG
            ),
            scope=FindingScope.NETWORK,
            rank=FindingRank.MODERATE if 0 < router_count <= router_count_threshold else FindingRank.INFO,
            title="Router Redundancy",
            summary=f"Observed {router_count} Router{'s' if router_count != 1 else ''}.",
            why="One observed routing device leaves mesh routing dependent on a single active Router; "
            "no observed Routers leaves redundancy Unknown.",
            evidence={
                "observedRouterCount": router_count,
                "unstableAtOrBelow": router_count_threshold,
                "meetsPolicy": router_count > router_count_threshold,
                "moreThanOne": router_count > 1,
            },
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
        border_router_count_threshold = _policy_value(
            policy,
            "network.border-router-redundancy",
            "thresholds.borderRouterCount",
        )["unstableAtOrBelow"]
        border_router_summary = f"Observed {border_router_count} Border Router{'s' if border_router_count != 1 else ''}."
        if not complete:
            border_router_summary += f" Source completeness is {observation.completeness.value}, so redundancy is provisional."
        findings.append(_finding(
            observation,
            rule_id="network.border-router-redundancy",
            status=(
                HealthStatus.UNKNOWN if not complete or border_router_count == 0
                else HealthStatus.MODERATE if border_router_count <= border_router_count_threshold
                else HealthStatus.STRONG
            ),
            scope=FindingScope.NETWORK,
            rank=(
                FindingRank.MODERATE
                if complete and 0 < border_router_count <= border_router_count_threshold
                else FindingRank.INFO
            ),
            title="Border Router Redundancy",
            summary=border_router_summary,
            why="One observed Border Router provides no Border Router failover; an incomplete observation "
            "or no authoritative count leaves redundancy Unknown.",
            evidence={
                "observedBorderRouterCount": border_router_count,
                "unstableAtOrBelow": border_router_count_threshold,
                "meetsPolicy": border_router_count > border_router_count_threshold,
                "moreThanOne": border_router_count > 1,
            },
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

    omr_border_router_ids: tuple[str, ...] = ()
    if (
        profile.border_router_authority
        and complete
        and omr_prefix
        and _profile_supports_rule(profile, "network.external-routing")
    ):
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

    router_id_set = frozenset(router_ids)
    router_relationships = tuple(
        relationship
        for relationship in observation.relationships
        if relationship.relationship_type == "router-neighbor"
        and relationship.from_device_id in router_id_set
        and relationship.to_device_id in router_id_set
    )
    graph_analysis = analyze_undirected_graph(
        router_ids,
        (
            GraphEdge(
                relationship.relationship_id,
                relationship.from_device_id,
                relationship.to_device_id,
            )
            for relationship in router_relationships
        ),
    )
    bridge_relationship_ids = frozenset(graph_analysis.bridge_relationship_ids)
    bridge_device_ids = tuple(sorted({
        device_id
        for relationship in router_relationships
        if relationship.relationship_id in bridge_relationship_ids
        for device_id in (
            relationship.from_device_id,
            relationship.to_device_id,
        )
    }))
    affected_router_ids = tuple(sorted({
        *bridge_device_ids,
        *graph_analysis.articulation_device_ids,
    }))
    router_neighbor_degrees = {
        device_id: len({
            endpoint
            for relationship in router_relationships
            for endpoint in (
                relationship.to_device_id
                if relationship.from_device_id == device_id
                else relationship.from_device_id
                if relationship.to_device_id == device_id
                else None,
            )
            if endpoint is not None
        })
        for device_id in router_ids
    }
    if profile.topology_authority:
        path_status = (
            HealthStatus.UNKNOWN
            if router_count < 2 or graph_analysis.edge_count == 0
            else HealthStatus.MODERATE
            if graph_analysis.bridge_relationship_ids or graph_analysis.articulation_device_ids
            else HealthStatus.STRONG
        )
        findings.append(
            _finding(
                observation,
                rule_id="network.current-path-redundancy",
                status=path_status,
                scope=FindingScope.NETWORK,
                rank=FindingRank.MODERATE if path_status is HealthStatus.MODERATE else FindingRank.INFO,
                title="Router Path Redundancy",
                summary=(
                    f"Observed {len(graph_analysis.bridge_relationship_ids)} bridge relationship(s) and "
                    f"{len(graph_analysis.articulation_device_ids)} articulation Router(s)."
                    if path_status is not HealthStatus.UNKNOWN
                    else "Current router path redundancy is not established by this observation."
                ),
                why="Router-neighbor bridges and articulation Routers are current single points of failure; "
                "child relationships do not establish alternate router paths.",
                evidence={
                    "routerCount": router_count,
                    "routerNeighborEdgeCount": graph_analysis.edge_count,
                    "routerNeighborDegrees": router_neighbor_degrees,
                    "bridgeRelationshipIds": graph_analysis.bridge_relationship_ids,
                    "bridgeDeviceIds": bridge_device_ids,
                    "bridgeComponents": graph_analysis.bridge_components,
                    "articulationDeviceIds": graph_analysis.articulation_device_ids,
                    "articulationComponents": graph_analysis.articulation_components,
                },
                action="Inspect single points of failure and preserve alternate usable router paths.",
                verify="Process another complete topology observation and compare bridges and articulation Routers.",
                device_ids=affected_router_ids,
                relationship_ids=graph_analysis.bridge_relationship_ids,
                confidence=Confidence.LOW if path_status is HealthStatus.UNKNOWN else Confidence.HIGH,
            )
        )

    metric_sources: dict[str, set[str]] = {}
    device_roles = {
        device.device_id: (device.role or "").lower() for device in observation.devices
    }
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
        metric_rule_id = f"device.{metric.metric}"
        if metric_rule_id not in HEALTH_RULE_CATALOG.rule_ids:
            continue
        metric_rule = HEALTH_RULE_CATALOG.rule(metric_rule_id)
        if not _profile_supports_rule(profile, metric_rule_id):
            continue
        if metric_rule.roles and device_roles.get(metric.device_id) not in metric_rule.roles:
            continue
        if metric_rule.requires_denominator and (
            metric.denominator is None or metric.denominator <= 0
        ):
            continue
        threshold_key = f"thresholds.{metric.metric}"
        if threshold_key not in metric_rule.threshold_keys:
            continue
        threshold = _policy_value(policy, metric_rule_id, threshold_key)
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
                    source_requirement=(
                        "timeStatistics"
                        if metric.metric in {"routerRolePercent", "detachedDisabledPercent"}
                        else "mleCounters"
                    ),
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
                source_requirement="macCounters",
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
    if observed_lq_total > 0 and _profile_supports_rule(
        profile, "network.observed-link-quality-ratios"
    ):
        lq3_ratio = lq_counts[3] / observed_lq_total
        lq2_ratio = lq_counts[2] / observed_lq_total
        lq1_ratio = lq_counts[1] / observed_lq_total
        lq3_threshold = _policy_value(
            policy,
            "network.observed-link-quality-ratios",
            "thresholds.observedLq3Ratio",
        )
        lq1_threshold = _policy_value(
            policy,
            "network.observed-link-quality-ratios",
            "thresholds.observedLq1Ratio",
        )
        lq3_bad = lq3_ratio < lq3_threshold["unstableBelow"]
        lq1_bad = lq1_ratio >= lq1_threshold["unstable"]
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
                    "lq3UnstableBelow": lq3_threshold["unstableBelow"],
                    "lq1UnstableAtOrAbove": lq1_threshold["unstable"],
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
    child_parent_counts: dict[str, int] = {}
    for relationship in observation.relationships:
        if relationship.relationship_type != "parent-child":
            continue
        child_id = (
            relationship.from_device_id
            if device_roles.get(relationship.from_device_id) == "child"
            else relationship.to_device_id
        )
        child_parent_counts[child_id] = child_parent_counts.get(child_id, 0) + 1
    for relationship in observation.relationships:
        child_relationship = relationship.relationship_type == "parent-child"
        router_relationship = relationship.relationship_type == "router-neighbor"
        if not child_relationship and not router_relationship:
            continue
        frame_key = "childFrameErrorRate" if child_relationship else "routerNeighborFrameErrorRate"
        message_key = "childMessageErrorRate" if child_relationship else "routerNeighborMessageErrorRate"
        frame_threshold = _policy_value(
            policy, "relationship.directional-quality", f"thresholds.{frame_key}"
        )
        message_threshold = _policy_value(
            policy, "relationship.directional-quality", f"thresholds.{message_key}"
        )
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
        link_quality_key = "childLinkQuality" if child_relationship else "routerLinkQuality"
        link_quality_threshold = _policy_value(
            policy, "relationship.directional-quality", f"thresholds.{link_quality_key}"
        )
        rssi_threshold = _policy_value(
            policy, "relationship.directional-quality", "thresholds.rssi"
        )
        margin_threshold = _policy_value(
            policy, "relationship.directional-quality", "thresholds.childLinkMargin"
        )
        weak = bool(quality_values) and min(quality_values) <= link_quality_threshold[
            "unstableAtOrBelow"
        ]
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
            and relationship.last_rssi < rssi_threshold["unstableBelow"]
        )
        margin_bad = (
            child_relationship
            and
            relationship.link_margin is not None
            and relationship.link_margin < margin_threshold["unstableBelow"]
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
        child_id = (
            relationship.from_device_id
            if device_roles.get(relationship.from_device_id) == "child"
            else relationship.to_device_id
        )
        sole_path = (
            child_parent_counts.get(child_id, 0) == 1
            if child_relationship
            else relationship.relationship_id in bridge_relationship_ids
        )
        path_basis = "sole-parent" if child_relationship else "router-bridge"
        if (
            child_relationship
            and relationship.queued_message_count is not None
            and relationship.queued_message_count > 0
            and _profile_supports_rule(profile, "relationship.queued-messages")
        ):
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
        if (
            weak or asymmetric or frame_bad or message_bad or rssi_bad or margin_bad
        ) and _profile_supports_rule(profile, "relationship.directional-quality"):
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
                        "pathBasis": path_basis,
                        "observedParentCount": (
                            child_parent_counts.get(child_id, 0) if child_relationship else None
                        ),
                        "bridge": (
                            relationship.relationship_id in bridge_relationship_ids
                            if router_relationship
                            else None
                        ),
                        "affectedComponents": (
                            graph_analysis.bridge_components.get(relationship.relationship_id, ())
                            if router_relationship
                            else ()
                        ),
                        "errorUncorrelatedWithRss": error_uncorrelated_with_rss,
                        "presentationVariant": (
                            "delivery-errors-adequate-signal"
                            if error_uncorrelated_with_rss
                            else None
                        ),
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
        elif lq3_agreement and _profile_supports_rule(
            profile, "relationship.bidirectional-lq3"
        ):
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
        if not _profile_supports_rule(
            profile, "device.multiple-reporters-high-error"
        ):
            continue
        multiple_reporter_threshold = _policy_value(
            policy,
            "device.multiple-reporters-high-error",
            "thresholds.multipleReporterCount",
        )["unstableAtOrAbove"]
        if len(relationship_ids) < multiple_reporter_threshold:
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

    for finding in findings:
        _validate_finding_applicability(finding, observation, profile)

    material = [
        finding
        for finding in findings
        if finding.status in {HealthStatus.MODERATE, HealthStatus.POOR}
        and HEALTH_RULE_CATALOG.rule(finding.rule_id).materiality
        in {"network", "relationship"}
    ]
    if any(finding.status is HealthStatus.POOR for finding in material):
        status = HealthStatus.POOR
    elif any(finding.status is HealthStatus.MODERATE for finding in material):
        status = HealthStatus.MODERATE
    valid_mac_metrics = sum(
        metric.metric in {"totalMacErrorRatio", "totalMacDiscardRatio"}
        and metric.denominator is not None
        and metric.denominator > 0
        for metric in observation.metrics
    )
    complete_lq_pairs = sum(
        relationship.link_quality_in is not None
        and relationship.link_quality_out is not None
        for relationship in observation.relationships
    )
    observed_counts = {
        "availability": {
            "observedDevices": len(observation.devices),
            "expectedRosterEntries": len(expected_device_ids),
            "expectedDevicesPresent": len(expected_device_ids & observed_ids),
            "attachmentStates": sum(bool(device.state or device.role) for device in observation.devices),
            "offlineEligible": int(complete and bool(expected_device_ids)),
        },
        "connectivity": {
            "relationships": len(observation.relationships),
            "parentChildRelationships": sum(
                relationship.relationship_type == "parent-child"
                for relationship in observation.relationships
            ),
            "routerNeighborRelationships": len(router_relationships),
            "completeDirectionalLqPairs": complete_lq_pairs,
        },
        "delivery": {
            "validMacRatios": valid_mac_metrics,
            "relationshipRates": sum(
                relationship.frame_error_rate is not None
                or relationship.message_error_rate is not None
                for relationship in observation.relationships
            ),
            "queueDepths": sum(
                relationship.queued_message_count is not None
                for relationship in observation.relationships
            ),
            "diagnosticTimeouts": len(diagnostic_timeout_device_ids),
        },
        "resilience": {
            "routers": router_count,
            "borderRouters": border_router_count,
            "routerNeighborEdges": graph_analysis.edge_count,
            "bridges": len(graph_analysis.bridge_relationship_ids),
            "articulationPoints": len(graph_analysis.articulation_device_ids),
            "topologyAuthority": int(profile.topology_authority),
            "borderRouterAuthority": int(profile.border_router_authority),
        },
        "externalRouting": {
            "omrPrefixAvailable": int(bool(omr_prefix)),
            "borderRouters": border_router_count,
            "borderRoutersWithOmrAddress": len(omr_border_router_ids) if profile.border_router_authority and complete and omr_prefix else 0,
        },
    }
    observed_pillars: dict[str, dict[str, object]] = {}
    for pillar, static_state in profile.coverage.items():
        counts = observed_counts[pillar]
        evidence_present = any(value > 0 for value in counts.values())
        reasons: list[str] = []
        if static_state == "missing":
            observed_state = "missing"
            reasons.append("dataset profile does not support this pillar")
        elif not evidence_present:
            observed_state = "missing"
            reasons.append("no usable evidence in this observation")
        elif static_state == "limited" or not complete:
            observed_state = "limited"
            if static_state == "limited":
                reasons.append("dataset profile capability is limited")
            if not complete:
                reasons.append(f"source completeness is {observation.completeness.value}")
        else:
            observed_state = "sufficient"
            reasons.append("supported evidence is present in a complete observation")
        observed_pillars[pillar] = {
            "state": observed_state,
            "evidenceCounts": counts,
            "reasons": reasons,
        }
    if not material and complete and observation.devices and all(
        pillar["state"] == "sufficient" for pillar in observed_pillars.values()
    ):
        status = HealthStatus.STRONG
    elif not material:
        status = HealthStatus.UNKNOWN
    sufficient_pillars = sum(
        pillar["state"] == "sufficient" for pillar in observed_pillars.values()
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
        "observedPillars": observed_pillars,
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
        evaluator_version=EVALUATOR_VERSION,
        profile_id=profile.profile_id,
        status=status,
        confidence=confidence,
        coverage=coverage,
        findings=tuple(sorted(findings, key=lambda item: (-int(item.rank), item.finding_id))),
        assessed_at=assessment_time,
    )