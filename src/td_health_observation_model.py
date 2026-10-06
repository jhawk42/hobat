"""Persistence-neutral domain contracts for Thread health processing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any, Mapping

from td_network_identity import canonical_ext_pan_id, network_id_from_ext_pan_id


_EXT_PAN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


class Completeness(StrEnum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    PARTIAL = "partial"


class HealthStatus(StrEnum):
    STRONG = "strong"
    MODERATE = "moderate"
    POOR = "poor"
    UNKNOWN = "unknown"


class FindingScope(StrEnum):
    NETWORK = "network"
    DEVICE = "device"
    RELATIONSHIP = "relationship"
    EXTERNAL = "external"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvaluationInputState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not-applicable"


class HistoryMigrationEligibility(StrEnum):
    ALREADY_CURRENT = "already-current"
    REPLAYABLE = "replayable"
    REPLAYABLE_WITH_GAPS = "replayable-with-gaps"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


class FindingRank(IntEnum):
    INFO = 10
    MODERATE = 20
    POOR = 30


@dataclass(frozen=True)
class SourceEvidence:
    filename: str
    digest: str
    kind: str
    state: str
    source_observed_at: str | None = None


@dataclass(frozen=True)
class DeviceSample:
    device_id: str
    ext_address: str
    role: str | None
    state: str | None
    is_border_router: bool
    source_files: tuple[str, ...]


@dataclass(frozen=True)
class RelationshipSample:
    relationship_id: str
    relationship_type: str
    from_device_id: str
    to_device_id: str
    link_quality_in: int | None
    link_quality_out: int | None
    average_rssi: float | None
    last_rssi: float | None
    link_margin: float | None
    frame_error_rate: float | None
    message_error_rate: float | None
    reporter_device_id: str | None
    source_files: tuple[str, ...]
    queued_message_count: float | None = None


@dataclass(frozen=True)
class MetricSample:
    device_id: str
    metric: str
    value: float
    unit: str
    denominator: float | None
    source_file: str


@dataclass(frozen=True)
class Finding:
    finding_id: str
    rule_id: str
    status: HealthStatus
    scope: FindingScope
    rank: FindingRank
    title: str
    summary: str
    why_it_matters: str
    device_ids: tuple[str, ...]
    relationship_ids: tuple[str, ...]
    evidence: Mapping[str, Any]
    confidence: Confidence
    action: str
    verify: str
    action_key: str
    verification_key: str
    source_files: tuple[str, ...]


@dataclass(frozen=True)
class Observation:
    observation_id: str
    datasource_id: str
    dataset_id: str
    network_id: str
    network_name: str | None
    observed_at: str
    ingested_at: str
    completeness: Completeness
    source_set_digest: str
    sources: tuple[SourceEvidence, ...]
    devices: tuple[DeviceSample, ...]
    relationships: tuple[RelationshipSample, ...]
    metrics: tuple[MetricSample, ...] = ()
    duplicate_relationship_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Assessment:
    assessment_id: str
    observation_id: str
    policy_version: str
    policy_digest: str
    evaluator_version: str
    profile_id: str
    status: HealthStatus
    confidence: Confidence
    coverage: Mapping[str, Any]
    findings: tuple[Finding, ...]
    assessed_at: str
    sample_contract_version: str = "legacy-unknown"
    health_policy_digest: str | None = None
    roster_context_digest: str = "legacy-unknown"
    presence_input_digest: str = "legacy-unknown"
    network_roster_revision: int = 0
    reproduction_context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationInputDomain:
    state: EvaluationInputState
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.state is EvaluationInputState.UNAVAILABLE and not self.reason_codes:
            raise ValueError("Unavailable evaluation inputs require a reason")
        if self.state is not EvaluationInputState.UNAVAILABLE and self.reason_codes:
            raise ValueError("Only unavailable evaluation inputs may have reasons")


@dataclass(frozen=True)
class EvaluationInputs:
    roster: EvaluationInputDomain
    expected_device_ids: frozenset[str] | None
    absence_history: EvaluationInputDomain
    prior_complete_absences: Mapping[str, int] | None
    duplicate_relationships: EvaluationInputDomain
    duplicate_relationship_ids: tuple[str, ...] | None
    omr_prefix: EvaluationInputDomain
    omr_prefix_value: str | None
    omr_source: Mapping[str, str] | None
    device_ipv6_addresses: EvaluationInputDomain
    device_ipv6_address_values: Mapping[str, tuple[str, ...]] | None
    observed_device_ipv6_address_values: Mapping[str, tuple[str, ...]]
    roster_context: Mapping[str, Any] | None
    history_boundary: Mapping[str, Any] | None

    def __post_init__(self) -> None:
        values = (
            (self.roster, self.expected_device_ids, "roster"),
            (self.absence_history, self.prior_complete_absences, "absence history"),
            (self.duplicate_relationships, self.duplicate_relationship_ids, "duplicate relationships"),
            (self.device_ipv6_addresses, self.device_ipv6_address_values, "IPv6 addresses"),
        )
        for domain, value, name in values:
            if domain.state is EvaluationInputState.AVAILABLE and value is None:
                raise ValueError(f"Available {name} input requires a value")
            if domain.state is not EvaluationInputState.AVAILABLE and value is not None:
                raise ValueError(f"Unavailable {name} input cannot carry a value")
        if self.roster.state is not EvaluationInputState.AVAILABLE and self.roster_context is not None:
            raise ValueError("Unavailable roster input cannot carry a roster context")
        if self.roster.state is EvaluationInputState.AVAILABLE and self.roster_context is None:
            raise ValueError("Available roster input requires a roster context")
        if (
            self.omr_prefix.state is EvaluationInputState.AVAILABLE
            and self.omr_source is None
        ):
            raise ValueError("Available OMR input requires source provenance")
        if not isinstance(self.observed_device_ipv6_address_values, Mapping):
            raise ValueError("Observed IPv6 address evidence must be a mapping")

    @property
    def evaluation_context_complete(self) -> bool:
        return all(
            domain.state is not EvaluationInputState.UNAVAILABLE
            for domain in self.domains().values()
        )

    @property
    def verdict_context_complete(self) -> bool:
        return all(
            domain.state is not EvaluationInputState.UNAVAILABLE
            for domain in (
                self.roster,
                self.absence_history,
                self.omr_prefix,
                self.device_ipv6_addresses,
            )
        )

    def domains(self) -> Mapping[str, EvaluationInputDomain]:
        return {
            "roster": self.roster,
            "absenceHistory": self.absence_history,
            "duplicateRelationships": self.duplicate_relationships,
            "omrPrefix": self.omr_prefix,
            "deviceIpv6Addresses": self.device_ipv6_addresses,
        }


@dataclass(frozen=True)
class HistoryMigrationInventoryItem:
    network_id: str
    dataset_id: str
    observation_id: str
    source_assessment_id: str
    eligibility: HistoryMigrationEligibility
    reason_codes: tuple[str, ...]
    evaluator_version: str
    policy_digest: str | None
    sample_contract_version: str
    preferred_assessment_id: str | None = None
    target_assessment_id: str | None = None
    unavailable_domains: tuple[str, ...] = ()
    before_status: str | None = None
    after_status: str | None = None
    before_finding_count: int | None = None
    after_finding_count: int | None = None
    before_coverage: Mapping[str, Any] | None = None
    after_coverage: Mapping[str, Any] | None = None
    replay_input_digest: str | None = None


@dataclass(frozen=True)
class HistoryMigrationInventory:
    schema_version: int
    target_contract_digest: str
    source_inventory_digest: str
    items: tuple[HistoryMigrationInventoryItem, ...]
    dataset_ids: tuple[str, ...] = ()
    network_id: str | None = None


def device_id_from_ext_address(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("extAddress must be a string")
    canonical = value.strip().lower().replace(":", "").replace("-", "")
    if not _EXT_PAN_ID_PATTERN.fullmatch(canonical) or canonical == "0" * 16:
        raise ValueError("extAddress must contain 16 non-placeholder hexadecimal digits")
    return f"extaddr:{canonical}"


def relationship_id(from_device_id: str, to_device_id: str) -> str:
    if from_device_id == to_device_id:
        raise ValueError("A relationship requires two different devices")
    return f"link:{from_device_id}->{to_device_id}"