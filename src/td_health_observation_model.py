"""Persistence-neutral domain contracts for Thread health processing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any, Mapping


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


def canonical_ext_pan_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("extPanId must be a string")
    canonical = value.strip().lower().replace(":", "").replace("-", "")
    if not _EXT_PAN_ID_PATTERN.fullmatch(canonical):
        raise ValueError("extPanId must contain exactly 16 hexadecimal digits")
    return canonical


def network_id_from_ext_pan_id(value: object) -> str:
    return f"extpan:{canonical_ext_pan_id(value)}"


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