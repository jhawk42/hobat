"""Versioned health dataset manifest loading and validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


MANIFEST_PATH = Path(__file__).with_name("td-dataset-manifest.json")
SUPPORTED_SCHEMA_VERSION = 2
ALLOWED_MERGE_STRATEGIES = frozenset({"none", "by-identity", "by-rloc16"})
COVERAGE_PILLARS = (
    "availability",
    "connectivity",
    "delivery",
    "resilience",
    "externalRouting",
)
ALLOWED_COVERAGE_STATES = frozenset({"sufficient", "limited", "missing"})
ROSTER_FIELDS = (
    "extAddress", "omrIpv6Address", "rloc16", "deviceLabel", "eui64", "routerId",
    "ipv6Addresses", "type", "isBorderRouter", "isRouter", "isLeader",
    "isPrimaryBBR", "role", "state", "mode.device", "mode.rxOnWhenIdle",
    "mode.fullThreadDevice", "mode.fullNetworkData", "threadVersion",
    "threadStackVersion", "leaderData.partitionId", "leaderData.leaderRouterId",
    "vendorName", "vendorModel", "vendorSwVersion",
)


class HealthManifestError(ValueError):
    """Raised when the shared health manifest is invalid."""


@dataclass(frozen=True)
class HealthProfile:
    profile_id: str
    identity_file: str
    required_outcomes: tuple[str, ...]
    coverage: Mapping[str, str]
    topology_authority: bool
    border_router_authority: bool


@dataclass(frozen=True)
class HealthDataset:
    datasource_id: str
    dataset_id: str
    files: tuple[str, ...]
    merge_strategy: str
    row_extractor: str
    adaptor: str
    health_profile: HealthProfile


@dataclass(frozen=True)
class IneligibleHealthDataset:
    datasource_id: str
    dataset_id: str
    reason: str
    required_evidence: tuple[str, ...]


@dataclass(frozen=True)
class RosterPolicy:
    version: str
    digest: str
    alias_collision_window_seconds: int
    max_string_length: int
    max_addresses: int
    sources: Mapping[str, Mapping[str, int]]
    freshness_seconds: Mapping[str, int | None]


@dataclass(frozen=True)
class HealthManifest:
    schema_version: int
    datasets: Mapping[str, HealthDataset]
    ineligible_datasets: Mapping[str, IneligibleHealthDataset]
    roster_policy: RosterPolicy

    def dataset(self, dataset_id: str) -> HealthDataset:
        try:
            return self.datasets[dataset_id]
        except KeyError as exc:
            raise HealthManifestError(
                f"Dataset is not health eligible: {dataset_id}"
            ) from exc


def _safe_filename(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise HealthManifestError(f"{field} must be a path-safe filename")
    return value


def _roster_policy(raw: object, datasets: Mapping[str, HealthDataset]) -> RosterPolicy:
    if not isinstance(raw, dict) or not isinstance(raw.get("version"), str) or not raw["version"]:
        raise HealthManifestError("Manifest requires a versioned rosterPolicy")
    declared = {filename for dataset in datasets.values() for filename in dataset.files}
    excluded = {filename for filename in declared if filename.startswith("td-mdns-") or
                filename.startswith("td-static-") or ".outcome." in filename or ".partial." in filename}
    allowed = declared - excluded
    fields = raw.get("fields")
    if not isinstance(fields, dict) or set(fields) != set(ROSTER_FIELDS):
        raise HealthManifestError("rosterPolicy must define every approved field")
    limits = ("aliasCollisionWindowSeconds", "maxStringLength", "maxAddresses")
    if any(type(raw.get(key)) is not int or raw[key] <= 0 for key in limits):
        raise HealthManifestError("Invalid rosterPolicy limits")
    sources: dict[str, Mapping[str, int]] = {}
    freshness: dict[str, int | None] = {}
    for field, definition in fields.items():
        if not isinstance(definition, dict) or set(definition) != {"sources", "freshnessSeconds"}:
            raise HealthManifestError(f"Invalid rosterPolicy field: {field}")
        declared_sources = definition["sources"]
        if not isinstance(declared_sources, list) or not declared_sources:
            raise HealthManifestError(f"Missing roster sources for {field}")
        ranks: dict[str, int] = {}
        for source in declared_sources:
            if not isinstance(source, dict) or set(source) != {"filename", "rank"}:
                raise HealthManifestError(f"Invalid roster source for {field}")
            filename = _safe_filename(source["filename"], field=f"rosterPolicy.{field}")
            if filename not in allowed or filename in ranks or type(source["rank"]) is not int or source["rank"] <= 0:
                raise HealthManifestError(f"Duplicate or unapproved roster source for {field}: {filename}")
            ranks[filename] = source["rank"]
        age = definition["freshnessSeconds"]
        if age is not None and (type(age) is not int or age <= 0):
            raise HealthManifestError(f"Invalid roster freshness for {field}")
        sources[field] = MappingProxyType(ranks)
        freshness[field] = age
    encoded = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return RosterPolicy(raw["version"], hashlib.sha256(encoded).hexdigest(),
                        raw["aliasCollisionWindowSeconds"], raw["maxStringLength"],
                        raw["maxAddresses"], MappingProxyType(sources), MappingProxyType(freshness))


def load_health_manifest(path: Path = MANIFEST_PATH) -> HealthManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HealthManifestError(f"Cannot load health manifest: {exc}") from exc

    if not isinstance(raw, dict) or raw.get("schemaVersion") not in (1, SUPPORTED_SCHEMA_VERSION):
        raise HealthManifestError("Unsupported health manifest schemaVersion")
    if raw["schemaVersion"] == 2:
        from td_dataset_catalog import validate_dataset_catalog
        validate_dataset_catalog(raw)

    raw_profiles = raw.get("healthProfiles")
    raw_datasets = raw.get("datasets")
    raw_ineligible_datasets = raw.get("ineligibleDatasets", [])
    if not isinstance(raw_profiles, dict) or not isinstance(raw_datasets, list):
        raise HealthManifestError("Manifest requires healthProfiles and datasets")
    if not isinstance(raw_ineligible_datasets, list):
        raise HealthManifestError("ineligibleDatasets must be an array")

    profiles: dict[str, HealthProfile] = {}
    for profile_id, value in raw_profiles.items():
        if not isinstance(profile_id, str) or not isinstance(value, dict):
            raise HealthManifestError("Invalid health profile")
        outcomes = value.get("requiredOutcomes", [])
        if not isinstance(outcomes, list):
            raise HealthManifestError("requiredOutcomes must be an array")
        coverage = value.get("coverage")
        if not isinstance(coverage, dict) or set(coverage) != set(COVERAGE_PILLARS):
            raise HealthManifestError(
                f"{profile_id}.coverage must define the five health pillars"
            )
        if any(state not in ALLOWED_COVERAGE_STATES for state in coverage.values()):
            raise HealthManifestError(f"Invalid coverage state for {profile_id}")
        topology_authority = value.get("topologyAuthority")
        border_router_authority = value.get("borderRouterAuthority")
        if not isinstance(topology_authority, bool) or not isinstance(
            border_router_authority, bool
        ):
            raise HealthManifestError(f"Invalid authority flags for {profile_id}")
        profiles[profile_id] = HealthProfile(
            profile_id=profile_id,
            identity_file=_safe_filename(
                value.get("identityFile"), field=f"{profile_id}.identityFile"
            ),
            required_outcomes=tuple(
                _safe_filename(item, field=f"{profile_id}.requiredOutcomes")
                for item in outcomes
            ),
            coverage=MappingProxyType(dict(coverage)),
            topology_authority=topology_authority,
            border_router_authority=border_router_authority,
        )

    datasets: dict[str, HealthDataset] = {}
    seen_dataset_ids: set[str] = set()
    for value in raw_datasets:
        if not isinstance(value, dict):
            raise HealthManifestError("Invalid dataset entry")
        dataset_id = value.get("value")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise HealthManifestError("Dataset value must be a non-empty string")
        if dataset_id in seen_dataset_ids:
            raise HealthManifestError(f"Duplicate dataset value: {dataset_id}")
        seen_dataset_ids.add(dataset_id)
        if value.get("healthEligible") is not True:
            if raw["schemaVersion"] == 2 and value.get("healthEligible") is False:
                continue
            raise HealthManifestError("Health manifest contains an ineligible dataset")
        datasource_id = value.get("source")
        profile_id = value.get("healthProfile")
        files = value.get("files")
        merge_strategy = value.get("mergeStrategy")
        if not isinstance(datasource_id, str) or not datasource_id:
            raise HealthManifestError(f"Invalid source for {dataset_id}")
        if not isinstance(files, list) or not files:
            raise HealthManifestError(f"Dataset {dataset_id} requires files")
        if merge_strategy not in ALLOWED_MERGE_STRATEGIES:
            raise HealthManifestError(f"Invalid mergeStrategy for {dataset_id}")
        if profile_id not in profiles:
            raise HealthManifestError(f"Unknown healthProfile for {dataset_id}")
        row_extractor = value.get("rowExtractor")
        adaptor = value.get("adaptor")
        if not isinstance(row_extractor, str) or not isinstance(adaptor, str):
            raise HealthManifestError(f"Invalid processing fields for {dataset_id}")
        datasets[dataset_id] = HealthDataset(
            datasource_id=datasource_id,
            dataset_id=dataset_id,
            files=tuple(
                _safe_filename(item, field=f"{dataset_id}.files") for item in files
            ),
            merge_strategy=merge_strategy,
            row_extractor=row_extractor,
            adaptor=adaptor,
            health_profile=profiles[profile_id],
        )

    ineligible_datasets: dict[str, IneligibleHealthDataset] = {}
    for value in raw_ineligible_datasets:
        if not isinstance(value, dict):
            raise HealthManifestError("Invalid ineligible health dataset")
        dataset_id = value.get("value")
        datasource_id = value.get("source")
        reason = value.get("reason")
        required_evidence = value.get("requiredEvidence")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise HealthManifestError("Ineligible dataset value must be a non-empty string")
        if dataset_id in datasets or dataset_id in ineligible_datasets:
            raise HealthManifestError(f"Duplicate health dataset value: {dataset_id}")
        if not isinstance(datasource_id, str) or not datasource_id:
            raise HealthManifestError(f"Invalid source for {dataset_id}")
        if not isinstance(reason, str) or not reason:
            raise HealthManifestError(f"Invalid ineligibility reason for {dataset_id}")
        if not isinstance(required_evidence, list) or not required_evidence or any(
            not isinstance(item, str) or not item for item in required_evidence
        ):
            raise HealthManifestError(f"Invalid required evidence for {dataset_id}")
        ineligible_datasets[dataset_id] = IneligibleHealthDataset(
            datasource_id=datasource_id,
            dataset_id=dataset_id,
            reason=reason,
            required_evidence=tuple(required_evidence),
        )

    return HealthManifest(
        schema_version=raw["schemaVersion"],
        datasets=MappingProxyType(datasets),
        ineligible_datasets=MappingProxyType(ineligible_datasets),
        roster_policy=_roster_policy(raw.get("rosterPolicy"), datasets),
    )