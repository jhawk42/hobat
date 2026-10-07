"""Pure snapshot health evaluation."""

from __future__ import annotations

import hashlib
import ipaddress
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from td_health_comparison import ROUTE64_SAMPLE_CONTRACT_VERSION
from td_health_observation_model import (
    Assessment,
    Completeness,
    Confidence,
    EvaluationInputDomain,
    EvaluationInputState,
    EvaluationInputs,
    Finding,
    FindingRank,
    FindingScope,
    HealthStatus,
    Observation,
)
from td_health_policy import HealthPolicy
from td_health_manifest import HealthProfile
from td_health_graph import GraphAnalysis, GraphEdge, analyze_undirected_graph
from td_health_rules import HEALTH_RULE_CATALOG, HealthRuleCatalogError


EVALUATOR_VERSION = "snapshot-v12"

_DIRECT_THRESHOLD_COUNT_METRICS = frozenset(
    {"parentChanges", "partitionIdChanges", "betterPartitionAttachAttempts"}
)

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
    "thresholds.queuedMessages": frozenset({"relationship.queued-messages"}),
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


@dataclass(frozen=True)
class AvailabilityFacts:
    observed_ids: frozenset[str]
    missing_expected_ids: tuple[str, ...]
    attachment_failed_device_ids: frozenset[str]
    offline_candidate_ids: frozenset[str]
    offline_device_ratio: float
    offline_poor_threshold_met: bool


@dataclass(frozen=True)
class TopologyFacts:
    router_ids: tuple[str, ...]
    border_router_ids: tuple[str, ...]
    router_relationships: tuple[Any, ...]
    graph_analysis: GraphAnalysis
    omr_border_router_ids: tuple[str, ...]

    @property
    def bridge_relationship_ids(self) -> frozenset[str]:
        return frozenset(self.graph_analysis.bridge_relationship_ids)


@dataclass(frozen=True)
class MetricFacts:
    metric_sources: Mapping[str, frozenset[str]]
    lq_counts: Mapping[int, float]
    diagnostic_timeout_device_ids: frozenset[str]
    device_roles: Mapping[str, str]


@dataclass(frozen=True)
class RelationshipFacts:
    child_parent_counts: Mapping[str, int]


def _evaluate_availability(
    observation: Observation,
    policy: HealthPolicy,
    inputs: EvaluationInputs,
    expected_device_ids: frozenset[str],
    absences: Mapping[str, int],
    complete: bool,
) -> tuple[list[Finding], AvailabilityFacts]:
    findings: list[Finding] = []
    observed_ids = frozenset(device.device_id for device in observation.devices)
    attachment_failed_device_ids: set[str] = set()
    for device in observation.devices:
        findings.append(
            _finding(
                observation,
                rule_id="device.observed",
                status=HealthStatus.STRONG,
                scope=FindingScope.DEVICE,
                rank=FindingRank.INFO,
                summary="Device is present in this observation.",
                evidence={"present": True, "completeness": observation.completeness.value},
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
                    summary=f"Device reports current state {attachment}.",
                    evidence={"attachment": attachment},
                    device_ids=(device.device_id,),
                    source_files=device.source_files,
                )
            )

    missing_expected_ids = tuple(sorted(expected_device_ids - observed_ids))
    offline_required = _policy_value(
        policy, "device.offline", "offlineConsecutiveCompleteObservations"
    )
    absence_history_available = (
        inputs.absence_history.state is EvaluationInputState.AVAILABLE
    )
    offline_candidate_ids = frozenset(
        device_id
        for device_id in missing_expected_ids
        if complete
        and absence_history_available
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
        prior = absences.get(device_id, 0) if absence_history_available else None
        is_offline = device_id in offline_candidate_ids
        findings.append(
            _finding(
                observation,
                rule_id="device.offline" if is_offline else "device.missing",
                status=HealthStatus.POOR if is_offline else HealthStatus.UNKNOWN,
                scope=FindingScope.DEVICE,
                rank=FindingRank.POOR if is_offline else FindingRank.INFO,
                summary=(
                    f"Expected device is absent from {prior + 1} consecutive complete observations."
                    if is_offline
                    else "Expected device is not present, but Offline is not established."
                ),
                evidence={
                    "present": False,
                    "completeObservation": complete,
                    "consecutiveCompleteAbsences": (
                        prior + 1 if complete and prior is not None else prior
                    ),
                    "required": offline_required,
                    "offlineCandidateCount": len(offline_candidate_ids),
                    "expectedRosterCount": len(expected_device_ids),
                    "offlineDeviceRatio": offline_device_ratio,
                    "offlinePoorDeviceRatioThreshold": offline_ratio_threshold,
                    "offlinePoorThresholdMet": offline_poor_threshold_met,
                },
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
                summary=(
                    f"{len(offline_candidate_ids)} of {len(expected_device_ids)} expected devices "
                    f"are Offline ({offline_device_ratio:.1%})."
                ),
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
                device_ids=tuple(sorted(offline_candidate_ids)),
            )
        )
    return findings, AvailabilityFacts(
        observed_ids=observed_ids,
        missing_expected_ids=missing_expected_ids,
        attachment_failed_device_ids=frozenset(attachment_failed_device_ids),
        offline_candidate_ids=offline_candidate_ids,
        offline_device_ratio=offline_device_ratio,
        offline_poor_threshold_met=offline_poor_threshold_met,
    )


def _evaluate_topology_resilience(
    observation: Observation,
    policy: HealthPolicy,
    profile: HealthProfile,
    inputs: EvaluationInputs,
    complete: bool,
    omr_prefix: str | None,
    device_ipv6_addresses: Mapping[str, tuple[str, ...]],
) -> tuple[list[Finding], TopologyFacts]:
    findings: list[Finding] = []
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
            summary=f"Observed {router_count} Router{'s' if router_count != 1 else ''}.",
            evidence={
                "observedRouterCount": router_count,
                "unstableAtOrBelow": router_count_threshold,
                "meetsPolicy": router_count > router_count_threshold,
                "moreThanOne": router_count > 1,
            },
            device_ids=router_ids,
            source_files=tuple(sorted({
                source for device in observation.devices for source in device.source_files
            })),
            confidence=Confidence.HIGH if router_count else Confidence.LOW,
        ))
    if profile.border_router_authority:
        border_router_count_threshold = _policy_value(
            policy,
            "network.border-router-redundancy",
            "thresholds.borderRouterCount",
        )["unstableAtOrBelow"]
        border_router_summary = (
            f"Observed {border_router_count} Border Router"
            f"{'s' if border_router_count != 1 else ''}."
        )
        if not complete:
            border_router_summary += (
                f" Source completeness is {observation.completeness.value}, "
                "so redundancy is provisional."
            )
        findings.append(_finding(
            observation,
            rule_id="network.border-router-redundancy",
            status=(
                HealthStatus.UNKNOWN if not complete or border_router_count == 0
                else HealthStatus.MODERATE
                if border_router_count <= border_router_count_threshold
                else HealthStatus.STRONG
            ),
            scope=FindingScope.NETWORK,
            rank=(
                FindingRank.MODERATE
                if complete and 0 < border_router_count <= border_router_count_threshold
                else FindingRank.INFO
            ),
            summary=border_router_summary,
            evidence={
                "observedBorderRouterCount": border_router_count,
                "unstableAtOrBelow": border_router_count_threshold,
                "meetsPolicy": border_router_count > border_router_count_threshold,
                "moreThanOne": border_router_count > 1,
            },
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
        and inputs.omr_prefix.state is EvaluationInputState.AVAILABLE
        and inputs.device_ipv6_addresses.state is EvaluationInputState.AVAILABLE
        and _profile_supports_rule(profile, "network.external-routing")
    ):
        addresses = device_ipv6_addresses or {}
        omr_network = ipaddress.IPv6Network(omr_prefix)

        def in_omr(address: str) -> bool:
            try:
                return ipaddress.IPv6Address(address) in omr_network
            except (ipaddress.AddressValueError, TypeError):
                return False

        omr_border_router_ids = tuple(sorted(
            device_id for device_id in border_router_ids
            if any(in_omr(addr) for addr in addresses.get(device_id, ()))
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
            summary=(
                f"{len(omr_border_router_ids)} Border Router"
                f"{'s' if len(omr_border_router_ids) != 1 else ''} "
                "advertise an address in the OMR prefix."
                if omr_border_router_ids
                else "No Border Router has an observed address within the OMR prefix."
            ),
            evidence={
                "omrPrefix": omr_prefix,
                "borderRouterCount": len(border_router_ids),
                "omrBorderRouterIds": omr_border_router_ids,
            },
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
                summary=(
                    f"Observed {len(graph_analysis.bridge_relationship_ids)} bridge relationship(s) and "
                    f"{len(graph_analysis.articulation_device_ids)} articulation Router(s)."
                    if path_status is not HealthStatus.UNKNOWN
                    else "Current router path redundancy is not established by this observation."
                ),
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
                device_ids=affected_router_ids,
                relationship_ids=graph_analysis.bridge_relationship_ids,
                confidence=Confidence.LOW if path_status is HealthStatus.UNKNOWN else Confidence.HIGH,
            )
        )
    return findings, TopologyFacts(
        router_ids=router_ids,
        border_router_ids=border_router_ids,
        router_relationships=router_relationships,
        graph_analysis=graph_analysis,
        omr_border_router_ids=omr_border_router_ids,
    )


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _assessment_input_digest(
    policy: HealthPolicy,
    profile: HealthProfile,
    sample_contract_version: str,
    evaluation_inputs: EvaluationInputs,
) -> str:
    payload = {
        "evaluatorVersion": EVALUATOR_VERSION,
        "healthPolicy": {
            "version": policy.version,
            "digest": policy.digest,
            "offlineConsecutiveCompleteObservations": (
                policy.offline_consecutive_complete_observations
            ),
            "offlinePoorDeviceRatioThreshold": policy.offline_poor_device_ratio_threshold,
            "thresholds": {
                metric: dict(bands) for metric, bands in policy.thresholds.items()
            },
        },
        "healthProfile": {
            "profileId": profile.profile_id,
            "identityFile": profile.identity_file,
            "requiredOutcomes": list(profile.required_outcomes),
            "coverage": dict(profile.coverage),
            "topologyAuthority": profile.topology_authority,
            "borderRouterAuthority": profile.border_router_authority,
        },
        "sampleContractVersion": sample_contract_version,
        "evaluationInputs": _evaluation_inputs_payload(evaluation_inputs),
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evaluation_inputs_payload(inputs: EvaluationInputs) -> dict[str, Any]:
    return {
        "domains": {
            name: {
                "state": domain.state.value,
                "reasonCodes": list(domain.reason_codes),
            }
            for name, domain in inputs.domains().items()
        },
        "roster": {
            "expectedDeviceIds": sorted(inputs.expected_device_ids or ()),
            "context": dict(inputs.roster_context or {}),
        },
        "absenceHistory": {
            "priorCompleteAbsences": dict(sorted(
                (inputs.prior_complete_absences or {}).items()
            )),
            "historyBoundary": (
                dict(inputs.history_boundary) if inputs.history_boundary else None
            ),
        },
        "duplicateRelationshipIds": list(inputs.duplicate_relationship_ids or ()),
        "omrPrefix": {
            "value": inputs.omr_prefix_value,
            "source": dict(inputs.omr_source or {}),
        },
        "deviceIpv6Addresses": {
            "complete": dict(sorted(
                (inputs.device_ipv6_address_values or {}).items()
            )),
            "observed": dict(sorted(inputs.observed_device_ipv6_address_values.items())),
        },
    }


def evaluation_inputs_from_payload(raw: object) -> EvaluationInputs:
    if not isinstance(raw, dict):
        raise ValueError("Evaluation inputs must be an object")
    domains = raw.get("domains")
    roster = raw.get("roster")
    absence = raw.get("absenceHistory")
    omr = raw.get("omrPrefix")
    addresses = raw.get("deviceIpv6Addresses")
    duplicates = raw.get("duplicateRelationshipIds")
    if not all(isinstance(value, dict) for value in (domains, roster, absence, omr, addresses)):
        raise ValueError("Evaluation input payload is missing a domain object")
    if not isinstance(duplicates, list) or not all(
        isinstance(value, str) for value in duplicates
    ):
        raise ValueError("Invalid duplicate relationship evidence")

    def domain(name: str) -> EvaluationInputDomain:
        value = domains.get(name)
        if not isinstance(value, dict):
            raise ValueError(f"Missing evaluation input domain {name}")
        try:
            state = EvaluationInputState(value["state"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"Invalid evaluation input state for {name}") from exc
        reasons = value.get("reasonCodes")
        if not isinstance(reasons, list) or not all(
            isinstance(reason, str) and reason for reason in reasons
        ):
            raise ValueError(f"Invalid evaluation input reasons for {name}")
        return EvaluationInputDomain(state, tuple(reasons))

    expected = roster.get("expectedDeviceIds")
    absence_values = absence.get("priorCompleteAbsences")
    source = omr.get("source")
    complete_addresses = addresses.get("complete")
    observed_addresses = addresses.get("observed")
    roster_context = roster.get("context")
    history_boundary = absence.get("historyBoundary")
    if not isinstance(expected, list) or not all(
        isinstance(value, str) for value in expected
    ):
        raise ValueError("Invalid saved expected device IDs")
    if not isinstance(absence_values, dict) or not all(
        isinstance(key, str) and type(value) is int and value >= 0
        for key, value in absence_values.items()
    ):
        raise ValueError("Invalid saved absence history")
    if source is not None and (
        not isinstance(source, dict)
        or not all(isinstance(key, str) and isinstance(value, str) for key, value in source.items())
    ):
        raise ValueError("Invalid saved OMR provenance")
    if not isinstance(roster_context, dict):
        raise ValueError("Invalid saved roster context")
    if history_boundary is not None and not isinstance(history_boundary, dict):
        raise ValueError("Invalid saved history boundary")

    def address_map(value: object, *, nullable: bool) -> Mapping[str, tuple[str, ...]] | None:
        if value is None and nullable:
            return None
        if not isinstance(value, dict):
            raise ValueError("Invalid saved device IPv6 address map")
        result: dict[str, tuple[str, ...]] = {}
        for device_id, values in value.items():
            if not isinstance(device_id, str) or not isinstance(values, list) or not all(
                isinstance(address, str) for address in values
            ):
                raise ValueError("Invalid saved device IPv6 address entry")
            result[device_id] = tuple(values)
        return result

    return EvaluationInputs(
        roster=domain("roster"),
        expected_device_ids=(
            frozenset(expected)
            if domain("roster").state is EvaluationInputState.AVAILABLE
            else None
        ),
        absence_history=domain("absenceHistory"),
        prior_complete_absences=(
            absence_values
            if domain("absenceHistory").state is EvaluationInputState.AVAILABLE
            else None
        ),
        duplicate_relationships=domain("duplicateRelationships"),
        duplicate_relationship_ids=(
            tuple(duplicates)
            if domain("duplicateRelationships").state is EvaluationInputState.AVAILABLE
            else None
        ),
        omr_prefix=domain("omrPrefix"),
        omr_prefix_value=(
            omr.get("value")
            if domain("omrPrefix").state is EvaluationInputState.AVAILABLE
            else None
        ),
        omr_source=source,
        device_ipv6_addresses=domain("deviceIpv6Addresses"),
        device_ipv6_address_values=(
            address_map(complete_addresses, nullable=False)
            if domain("deviceIpv6Addresses").state is EvaluationInputState.AVAILABLE
            else None
        ),
        observed_device_ipv6_address_values=(
            address_map(observed_addresses, nullable=False) or {}
        ),
        roster_context=(
            roster_context
            if domain("roster").state is EvaluationInputState.AVAILABLE
            else None
        ),
        history_boundary=history_boundary,
    )


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
    summary: str,
    evidence: Mapping[str, object],
    presentation_variant: str | None = None,
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
    rule.title_for(presentation_variant)
    catalog_evidence = dict(evidence)
    missing_evidence = [
        path for path in rule.required_evidence if path not in catalog_evidence
    ]
    if missing_evidence:
        raise HealthRuleCatalogError(
            f"Rule {rule_id} requires evidence {missing_evidence}"
        )
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
        action_key=rule.action_key,
        verification_key=rule.verification_key,
        source_files=source_files,
    )


def aggregate_assessment_state(
    findings: tuple[Finding, ...] | list[Finding],
    *,
    completeness: Completeness,
    device_count: int,
    observed_pillars: Mapping[str, Mapping[str, Any]],
    evaluation_inputs: EvaluationInputs,
) -> tuple[HealthStatus, Confidence]:
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
    elif (
        completeness is Completeness.COMPLETE
        and device_count
        and all(pillar["state"] == "sufficient" for pillar in observed_pillars.values())
    ):
        status = HealthStatus.STRONG
    else:
        status = HealthStatus.UNKNOWN
    verdict_context_complete = _verdict_context_complete(
        evaluation_inputs, completeness, findings
    )
    if status is HealthStatus.STRONG and not verdict_context_complete:
        status = HealthStatus.UNKNOWN
    sufficient_pillars = sum(
        pillar["state"] == "sufficient" for pillar in observed_pillars.values()
    )
    if completeness is not Completeness.COMPLETE:
        confidence = (
    Confidence.MEDIUM
    if completeness is Completeness.DEGRADED
    else Confidence.LOW
        )
    elif sufficient_pillars >= 4:
        confidence = Confidence.HIGH
    elif sufficient_pillars >= 2:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW
    if not verdict_context_complete and confidence is Confidence.HIGH:
        confidence = Confidence.MEDIUM
    return status, confidence


def _available_domain() -> EvaluationInputDomain:
    return EvaluationInputDomain(EvaluationInputState.AVAILABLE)


def _not_applicable_domain() -> EvaluationInputDomain:
    return EvaluationInputDomain(EvaluationInputState.NOT_APPLICABLE)


def _verdict_context_complete(
    inputs: EvaluationInputs,
    completeness: Completeness,
    findings: tuple[Finding, ...] | list[Finding],
) -> bool:
    return (
        inputs.roster.state is not EvaluationInputState.UNAVAILABLE
        and not (
            inputs.absence_history.state is EvaluationInputState.UNAVAILABLE
            and completeness is Completeness.COMPLETE
            and any(
                finding.rule_id in {"device.missing", "device.offline"}
                for finding in findings
            )
        )
        and all(
            domain.state is not EvaluationInputState.UNAVAILABLE
            for domain in (inputs.omr_prefix, inputs.device_ipv6_addresses)
        )
    )


def _legacy_evaluation_inputs(
    observation: Observation,
    *,
    expected_device_ids: frozenset[str],
    prior_complete_absences: Mapping[str, int],
    roster_context: Mapping[str, Any] | None,
    network_roster_revision: int,
    history_boundary: Mapping[str, Any] | None,
    omr_prefix: str | None,
    device_ipv6_addresses: Mapping[str, tuple[str, ...]] | None,
    profile: HealthProfile,
) -> EvaluationInputs:
    external_routing_applicable = (
        profile.border_router_authority
        and profile.coverage["externalRouting"] != "missing"
    )
    return EvaluationInputs(
        roster=_available_domain(),
        expected_device_ids=expected_device_ids,
        absence_history=_available_domain(),
        prior_complete_absences=dict(prior_complete_absences),
        duplicate_relationships=_available_domain(),
        duplicate_relationship_ids=observation.duplicate_relationship_ids,
        omr_prefix=(
            _available_domain() if external_routing_applicable
            else _not_applicable_domain()
        ),
        omr_prefix_value=omr_prefix if external_routing_applicable else None,
        omr_source=(
            {"kind": "explicit-evaluator-input"}
            if external_routing_applicable else None
        ),
        device_ipv6_addresses=(
            _available_domain() if external_routing_applicable
            else _not_applicable_domain()
        ),
        device_ipv6_address_values=(
            dict(device_ipv6_addresses or {})
            if external_routing_applicable else None
        ),
        observed_device_ipv6_address_values=(
            dict(device_ipv6_addresses or {})
            if external_routing_applicable else {}
        ),
        roster_context=dict(roster_context or {
            "schemaVersion": 1,
            "networkId": observation.network_id,
            "networkRosterRevision": network_roster_revision,
            "records": [],
            "expectedDeviceIds": sorted(expected_device_ids),
        }),
        history_boundary=dict(history_boundary) if history_boundary else None,
    )


def _evaluate_metrics(
    observation: Observation,
    policy: HealthPolicy,
    profile: HealthProfile,
    attachment_failed_device_ids: frozenset[str],
) -> tuple[list[Finding], MetricFacts]:
    findings: list[Finding] = []
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
                    status=(
                        HealthStatus.MODERATE
                        if metric.metric in _DIRECT_THRESHOLD_COUNT_METRICS
                        else HealthStatus.UNKNOWN
                    ),
                    scope=FindingScope.DEVICE,
                    rank=(
                        FindingRank.MODERATE
                        if metric.metric in _DIRECT_THRESHOLD_COUNT_METRICS
                        else FindingRank.INFO
                    ),
                    summary=(
                        f"{metric.metric} is {metric.value:g} ({band} evidence band); "
                        "this accumulated count alone does not establish current churn."
                        if metric.metric in _DIRECT_THRESHOLD_COUNT_METRICS
                        else f"{metric.metric} is {metric.value:g} ({band} band); lifetime/since-reset evidence only."
                    ),
                    evidence={
                        "metric": metric.metric,
                        "value": metric.value,
                        "unit": metric.unit,
                        "band": band,
                        "thresholds": dict(threshold),
                    },
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
                summary=f"Current ratio is {metric.value:.1%} ({severity_tier} band).",
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
                summary="The device did not respond to a mesh diagnostic query in this observation.",
                evidence={"responseTimeout": True},
                device_ids=(device_id,),
                confidence=Confidence.LOW,
            )
        )

    return findings, MetricFacts(
        metric_sources={key: frozenset(value) for key, value in metric_sources.items()},
        lq_counts=lq_counts,
        diagnostic_timeout_device_ids=frozenset(diagnostic_timeout_device_ids),
        device_roles=device_roles,
    )


def _evaluate_relationships(
    observation: Observation,
    policy: HealthPolicy,
    profile: HealthProfile,
    device_roles: Mapping[str, str],
    bridge_relationship_ids: frozenset[str],
    graph_analysis: GraphAnalysis,
) -> tuple[list[Finding], RelationshipFacts]:
    findings: list[Finding] = []
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
            and _profile_supports_rule(profile, "relationship.queued-messages")
        ):
            queue_threshold = _policy_value(
                policy,
                "relationship.queued-messages",
                "thresholds.queuedMessages",
            )
            if relationship.queued_message_count >= queue_threshold["unstable"]:
                band = (
                    "high"
                    if relationship.queued_message_count >= queue_threshold["high"]
                    else "moderate"
                )
                findings.append(
                    _finding(
                        observation,
                        rule_id="relationship.queued-messages",
                        status=HealthStatus.MODERATE,
                        scope=FindingScope.RELATIONSHIP,
                        rank=FindingRank.MODERATE,
                        summary=(
                            f"{relationship.queued_message_count:g} indirect message(s) are queued "
                            f"for delivery ({band} evidence band)."
                        ),
                        evidence={
                            "queuedMessageCount": relationship.queued_message_count,
                            "band": band,
                            "thresholds": dict(queue_threshold),
                        },
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
                    presentation_variant=(
                        "delivery-errors-adequate-signal"
                        if error_uncorrelated_with_rss
                        else None
                    ),
                    summary=(
                        "Frame or message errors are elevated despite adequate RSS/margin evidence; "
                        "suspect interference or firmware rather than distance."
                        if error_uncorrelated_with_rss
                        else "Current directional quality, delivery, or RF evidence crossed a snapshot threshold."
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
                    summary="Both observed directions report LQ3.",
                    evidence={"linkQualityIn": 3, "linkQualityOut": 3},
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
                summary=f"{len(relationship_ids)} distinct reporters recorded high frame or message error rates.",
                evidence={"reporterRelationshipIds": tuple(sorted(relationship_ids))},
                device_ids=(device_id,),
                relationship_ids=tuple(sorted(relationship_ids)),
                confidence=Confidence.HIGH,
            )
        )

    return findings, RelationshipFacts(
        child_parent_counts=child_parent_counts,
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
    roster_context: Mapping[str, Any] | None = None,
    network_roster_revision: int = 0,
    history_boundary: Mapping[str, Any] | None = None,
    evaluation_inputs: EvaluationInputs | None = None,
    sample_contract_version: str = "comparison-v1",
) -> Assessment:
    inputs = evaluation_inputs or _legacy_evaluation_inputs(
        observation,
        expected_device_ids=expected_device_ids,
        prior_complete_absences=prior_complete_absences or {},
        roster_context=roster_context,
        network_roster_revision=network_roster_revision,
        history_boundary=history_boundary,
        omr_prefix=omr_prefix,
        device_ipv6_addresses=device_ipv6_addresses,
        profile=profile,
    )
    expected_device_ids = (
        inputs.expected_device_ids or frozenset()
        if inputs.roster.state is EvaluationInputState.AVAILABLE
        else frozenset()
    )
    absences = (
        inputs.prior_complete_absences or {}
        if inputs.absence_history.state is EvaluationInputState.AVAILABLE
        else {}
    )
    omr_prefix = (
        inputs.omr_prefix_value
        if inputs.omr_prefix.state is EvaluationInputState.AVAILABLE
        else None
    )
    device_ipv6_addresses = (
        inputs.device_ipv6_address_values or {}
        if inputs.device_ipv6_addresses.state is EvaluationInputState.AVAILABLE
        else {}
    )
    findings: list[Finding] = []
    complete = observation.completeness is Completeness.COMPLETE
    availability_findings, availability_facts = _evaluate_availability(
        observation, policy, inputs, expected_device_ids, absences, complete
    )
    findings.extend(availability_findings)
    observed_ids = availability_facts.observed_ids
    missing_expected_ids = availability_facts.missing_expected_ids
    attachment_failed_device_ids = availability_facts.attachment_failed_device_ids

    topology_findings, topology_facts = _evaluate_topology_resilience(
        observation,
        policy,
        profile,
        inputs,
        complete,
        omr_prefix,
        device_ipv6_addresses,
    )
    findings.extend(topology_findings)
    router_ids = topology_facts.router_ids
    border_router_ids = topology_facts.border_router_ids
    router_relationships = topology_facts.router_relationships
    graph_analysis = topology_facts.graph_analysis
    bridge_relationship_ids = topology_facts.bridge_relationship_ids
    omr_border_router_ids = topology_facts.omr_border_router_ids
    router_count = len(router_ids)
    border_router_count = len(border_router_ids)

    metric_findings, metric_facts = _evaluate_metrics(
        observation, policy, profile, attachment_failed_device_ids
    )
    findings.extend(metric_findings)
    metric_sources = metric_facts.metric_sources
    lq_counts = metric_facts.lq_counts
    diagnostic_timeout_device_ids = metric_facts.diagnostic_timeout_device_ids
    device_roles = metric_facts.device_roles

    if (
        inputs.duplicate_relationships.state is EvaluationInputState.AVAILABLE
        and inputs.duplicate_relationship_ids
    ):
        findings.append(
            _finding(
                observation,
                rule_id="observation.duplicate-source-entry",
                status=HealthStatus.UNKNOWN,
                scope=FindingScope.NETWORK,
                rank=FindingRank.INFO,
                summary=(
                    f"{len(inputs.duplicate_relationship_ids)} relationship(s) appeared more than "
                    "once within one source file."
                ),
                evidence={"relationshipIds": inputs.duplicate_relationship_ids},
                relationship_ids=inputs.duplicate_relationship_ids,
                confidence=Confidence.LOW,
            )
        )

    unavailable_domains = [
        {
            "domain": name,
            "reasonCodes": list(domain.reason_codes),
            "affectedRuleIds": {
                "roster": ["device.missing", "device.offline", "network.offline-impact"],
                "absenceHistory": ["device.offline", "network.offline-impact"],
                "duplicateRelationships": ["observation.duplicate-source-entry"],
                "omrPrefix": ["network.external-routing"],
                "deviceIpv6Addresses": ["network.external-routing"],
            }[name],
        }
        for name, domain in inputs.domains().items()
        if domain.state is EvaluationInputState.UNAVAILABLE
    ]
    if unavailable_domains:
        findings.append(
            _finding(
                observation,
                rule_id="observation.evaluation-context-unavailable",
                status=HealthStatus.UNKNOWN,
                scope=FindingScope.NETWORK,
                rank=FindingRank.INFO,
                summary="One or more historical evaluation inputs are unavailable.",
                evidence={"unavailableDomains": unavailable_domains},
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
                summary=(
                    f"LQ3 is {lq3_ratio:.1%}; LQ2 is {lq2_ratio:.1%}; "
                    f"LQ1 is {lq1_ratio:.1%} of observed links."
                ),
                evidence={
                    "observedCount": observed_lq_total,
                    "lq3Ratio": lq3_ratio,
                    "lq2Ratio": lq2_ratio,
                    "lq1Ratio": lq1_ratio,
                    "lq3UnstableBelow": lq3_threshold["unstableBelow"],
                    "lq1UnstableAtOrAbove": lq1_threshold["unstable"],
                },
                source_files=tuple(sorted(
                    metric_sources.get("observedLinkQuality1Count", set())
                    | metric_sources.get("observedLinkQuality2Count", set())
                    | metric_sources.get("observedLinkQuality3Count", set())
                )),
            )
        )

    relationship_findings, relationship_facts = _evaluate_relationships(
        observation,
        policy,
        profile,
        device_roles,
        bridge_relationship_ids,
        graph_analysis,
    )
    findings.extend(relationship_findings)

    for finding in findings:
        _validate_finding_applicability(finding, observation, profile)

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
            "expectedRosterEntries": (
                len(expected_device_ids)
                if inputs.roster.state is EvaluationInputState.AVAILABLE else None
            ),
            "expectedDevicesPresent": (
                len(expected_device_ids & observed_ids)
                if inputs.roster.state is EvaluationInputState.AVAILABLE else None
            ),
            "attachmentStates": sum(bool(device.state or device.role) for device in observation.devices),
            "offlineEligible": int(complete and bool(expected_device_ids)),
        },
        "connectivity": {
            "relationships": len(observation.relationships),
            "parentChildRelationships": sum(relationship_facts.child_parent_counts.values()),
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
        evidence_present = any(
            isinstance(value, (int, float)) and value > 0
            for value in counts.values()
        )
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
    context_limited_pillars: dict[str, list[str]] = {}
    if inputs.roster.state is EvaluationInputState.UNAVAILABLE:
        context_limited_pillars.setdefault("availability", []).append("roster")
    if (
        inputs.absence_history.state is EvaluationInputState.UNAVAILABLE
        and complete
        and missing_expected_ids
    ):
        context_limited_pillars.setdefault("availability", []).append(
            "absenceHistory"
        )
    if (
        profile.border_router_authority
        and _profile_supports_rule(profile, "network.external-routing")
    ):
        unavailable_routing = [
            name
            for name, domain in (
                ("omrPrefix", inputs.omr_prefix),
                ("deviceIpv6Addresses", inputs.device_ipv6_addresses),
            )
            if domain.state is EvaluationInputState.UNAVAILABLE
        ]
        if unavailable_routing:
            context_limited_pillars["externalRouting"] = unavailable_routing
    for pillar_name, domains in context_limited_pillars.items():
        pillar = observed_pillars[pillar_name]
        if pillar["state"] == "sufficient":
            pillar["state"] = "limited"
        reasons = list(pillar["reasons"])
        reasons.append(
            "evaluation context unavailable: " + ", ".join(domains)
        )
        pillar["reasons"] = reasons
    status, confidence = aggregate_assessment_state(
        findings,
        completeness=observation.completeness,
        device_count=len(observation.devices),
        observed_pillars=observed_pillars,
        evaluation_inputs=inputs,
    )
    sufficient_pillars = sum(
        pillar["state"] == "sufficient" for pillar in observed_pillars.values()
    )
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
        "expectedRosterCount": (
            len(expected_device_ids)
            if inputs.roster.state is EvaluationInputState.AVAILABLE else None
        ),
        "offlineEligible": (
            complete
            and bool(expected_device_ids)
            and inputs.roster.state is EvaluationInputState.AVAILABLE
            and inputs.absence_history.state is EvaluationInputState.AVAILABLE
        ),
        "diagnosticTimeoutDeviceCount": len(diagnostic_timeout_device_ids),
        "diagnosticTimeoutRatio": (
            len(diagnostic_timeout_device_ids) / len(observation.devices)
            if observation.devices
            else 0.0
        ),
        "evaluationInputs": {
            name: {
                "state": domain.state.value,
                "reasonCodes": list(domain.reason_codes),
            }
            for name, domain in inputs.domains().items()
        },
        "evaluationContextComplete": inputs.evaluation_context_complete,
        "verdictContextComplete": _verdict_context_complete(
            inputs, observation.completeness, findings
        ),
        "unavailableEvaluationDomains": [
            name
            for name, domain in inputs.domains().items()
            if domain.state is EvaluationInputState.UNAVAILABLE
        ],
    }
    assessment_time = assessed_at or datetime.now(timezone.utc).isoformat()
    assessment_input_digest = _assessment_input_digest(
        policy, profile, sample_contract_version, inputs
    )
    if sample_contract_version not in {"comparison-v1", ROUTE64_SAMPLE_CONTRACT_VERSION}:
        raise ValueError(f"Unsupported sample contract: {sample_contract_version}")
    normalized_roster_context = dict(inputs.roster_context or {})
    presence_inputs = {
        "complete": complete,
        "observedDeviceIds": sorted(observed_ids),
        "sampleContractVersion": sample_contract_version,
        "roster": {
            "state": inputs.roster.state.value,
            "expectedDeviceIds": sorted(expected_device_ids),
            "reasonCodes": list(inputs.roster.reason_codes),
        },
        "absenceHistory": {
            "state": inputs.absence_history.state.value,
            "priorCompleteAbsences": dict(sorted(absences.items())),
            "reasonCodes": list(inputs.absence_history.reason_codes),
        },
    }
    roster_context_digest = hashlib.sha256(
        json.dumps(
            {
                "state": inputs.roster.state.value,
                "reasonCodes": list(inputs.roster.reason_codes),
                "context": normalized_roster_context,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    presence_input_digest = hashlib.sha256(
        json.dumps(
            presence_inputs,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assessment_id = _stable_id(
        "assessment", "v3", observation.observation_id, assessment_input_digest,
        roster_context_digest, presence_input_digest,
    )
    reproduction_context = {
        "schemaVersion": 2,
        "evaluatorVersion": EVALUATOR_VERSION,
        "healthPolicy": {
            "version": policy.version,
            "digest": policy.digest,
            "offlineConsecutiveCompleteObservations": (
                policy.offline_consecutive_complete_observations
            ),
            "offlinePoorDeviceRatioThreshold": policy.offline_poor_device_ratio_threshold,
            "thresholds": {
                metric: dict(bands) for metric, bands in policy.thresholds.items()
            },
        },
        "healthProfile": {
            "profileId": profile.profile_id,
            "identityFile": profile.identity_file,
            "requiredOutcomes": list(profile.required_outcomes),
            "coverage": dict(profile.coverage),
            "topologyAuthority": profile.topology_authority,
            "borderRouterAuthority": profile.border_router_authority,
        },
        "networkRosterRevision": network_roster_revision,
        "rosterContext": normalized_roster_context,
        "historyProvenance": "retained-complete-observations",
        "historyBoundary": dict(inputs.history_boundary) if inputs.history_boundary else None,
        "presenceInputs": presence_inputs,
        "expectedDeviceIds": sorted(expected_device_ids),
        "priorCompleteAbsences": dict(sorted(absences.items())),
        "evaluationInputs": _evaluation_inputs_payload(inputs),
        "endpointEligibility": {
            "complete": complete,
            "observedAt": observation.observed_at,
        },
    }
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
        sample_contract_version=sample_contract_version,
        health_policy_digest=policy.digest,
        roster_context_digest=roster_context_digest,
        presence_input_digest=presence_input_digest,
        network_roster_revision=network_roster_revision,
        reproduction_context=reproduction_context,
    )