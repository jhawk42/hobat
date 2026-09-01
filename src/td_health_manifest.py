"""Versioned health dataset manifest loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


MANIFEST_PATH = Path(__file__).with_name("td-dataset-manifest.json")
SUPPORTED_SCHEMA_VERSION = 1
ALLOWED_MERGE_STRATEGIES = frozenset({"none", "by-identity", "by-rloc16"})
COVERAGE_PILLARS = (
    "availability",
    "connectivity",
    "delivery",
    "resilience",
    "externalRouting",
)
ALLOWED_COVERAGE_STATES = frozenset({"sufficient", "limited", "missing"})


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
class HealthManifest:
    schema_version: int
    datasets: Mapping[str, HealthDataset]

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


def load_health_manifest(path: Path = MANIFEST_PATH) -> HealthManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HealthManifestError(f"Cannot load health manifest: {exc}") from exc

    if not isinstance(raw, dict) or raw.get("schemaVersion") != SUPPORTED_SCHEMA_VERSION:
        raise HealthManifestError("Unsupported health manifest schemaVersion")

    raw_profiles = raw.get("healthProfiles")
    raw_datasets = raw.get("datasets")
    if not isinstance(raw_profiles, dict) or not isinstance(raw_datasets, list):
        raise HealthManifestError("Manifest requires healthProfiles and datasets")

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
    for value in raw_datasets:
        if not isinstance(value, dict) or value.get("healthEligible") is not True:
            raise HealthManifestError("Health manifest contains an ineligible dataset")
        dataset_id = value.get("value")
        datasource_id = value.get("source")
        profile_id = value.get("healthProfile")
        files = value.get("files")
        merge_strategy = value.get("mergeStrategy")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise HealthManifestError("Dataset value must be a non-empty string")
        if dataset_id in datasets:
            raise HealthManifestError(f"Duplicate dataset value: {dataset_id}")
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

    return HealthManifest(
        schema_version=SUPPORTED_SCHEMA_VERSION,
        datasets=MappingProxyType(datasets),
    )