"""Immutable, cache-only manifest history and retained replay contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from td_health_manifest import (
    ALLOWED_COVERAGE_STATES,
    ALLOWED_MERGE_STRATEGIES,
    COVERAGE_PILLARS,
    MANIFEST_PATH,
    ROSTER_FIELDS,
    HealthDataset,
    HealthManifestError,
    HealthProfile,
    load_health_manifest,
)


HISTORY_PATH = Path(__file__).with_name("td-dataset-manifest-history.json")
PROJECTION_VERSION = "health-manifest-v1"
REPLAY_CONTRACT_VERSION = "retained-replay-v1"
TARGET_CONTRACT_VERSION = "health-target-v2"
ADAPTER_ID = "retained-equivalent-v1"
_DATASET_FIELDS = (
    "source", "value", "files", "mergeStrategy", "rowExtractor", "adaptor", "healthProfile",
)
_PROFILE_FIELDS = frozenset({
    "identityFile", "requiredOutcomes", "coverage", "topologyAuthority", "borderRouterAuthority",
})
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_OLD_POLICYLESS = frozenset({
    "894ddf08935e76d50e1dea396d098fafc2fd187cfae187b099e91119e5f4fe26",
    "1d1829d4c4195c8401ad653062374e3f669b903c603c952dc6ed566681e7bbdf",
    "098425c1750a3e2f07aeaee36dae0b477cda5937094006eda259fe08d7b2f8d6",
    "4df64fa0175b516c93ce397a45629896f69d9d91d7ad5fe0345f0451ef745e35",
    "aa4a7fc9f796b35724a92e2540801f412bf3d54afbd3d1dddf86f8dc50dda7de",
})
_ROSTER_V1 = frozenset({
    "0c7160769a97af622b0c6de44bc2597cc9f39d98595a9ced01bc32dc30aab126",
    "942167cc426ff3415f8c7394ac4920cc82559571a81ce731f0ebd69ab6bf6ad1",
})
_ORIGINAL_SAMPLE_SUPPORT = MappingProxyType({
    "otbr_cli_networkdiag_fetch_all": "comparison-v1-route64",
    "otbr_cli_topology_health": "comparison-v1",
    "otbr_cli_topology_mdns_health": "comparison-v1",
    "otbr_restapi_devices_fetch_diagnostics_fetch_all": "comparison-v1",
    "otbr_restapi_devices_fetch_diagnostics_fetch_all_mesh_diagnostics_fetch_all": "comparison-v1",
    "otbr_restapi_topology_mdns_health": "comparison-v1",
    "merged_otbr_topology_mdns_health": "comparison-v1",
})
_CURRENT_SAMPLE_SUPPORT = MappingProxyType({
    "otbr_cli_diagnostics_fetch": "comparison-v1-route64",
    "otbr_cli_topology": "comparison-v1",
    "otbr_cli_topology_mdns": "comparison-v1",
    "otbr_restapi_devices_diagnostics_fetch": "comparison-v1",
    "otbr_restapi_topology": "comparison-v1",
    "otbr_restapi_topology_mdns": "comparison-v1",
    "multi_source_otbr_topology_mdns": "comparison-v1",
    "otbr_cli_unified": "comparison-v1-unified",
    "otbr_restapi_unified": "comparison-v1-unified",
    "ha_matter_ws_unified": "comparison-v1-unified",
    "multi_source_unified": "comparison-v1-unified",
})
# Reviewed schema-4 producers only; a structurally equivalent recipe is not proof.
PRODUCER_SAMPLE_SUPPORT = MappingProxyType({
    **{digest: _ORIGINAL_SAMPLE_SUPPORT for digest in _ROSTER_V1},
    "50b5a9f2e71c734a9fe5b8615d0fe7ee3e2a22f3965bd616af6bf1a2c3e05598": _ORIGINAL_SAMPLE_SUPPORT,
    "9ec1668fbd091746f82c6783b219e6e447e29a2ee81b6817f8e3c2aa8c2c9e28": _CURRENT_SAMPLE_SUPPORT,
    "5a981ad569a13253c809d36cf0c3a0668a127a9f4b20b0d8d82b8f54e2ce6752": _CURRENT_SAMPLE_SUPPORT,
    "73e911ff0385d0de5f06bbb870dccb50467e78f64cec906bab18527125046b3e": _CURRENT_SAMPLE_SUPPORT,
    "88ac93a9e81380ad7c02542c23e8cfe58f469cb180c589df89acc7f61b19349e": MappingProxyType({
        key: value for key, value in _CURRENT_SAMPLE_SUPPORT.items()
        if value != "comparison-v1-unified"
    }),
    "d369ccc7cca9e30cd2016ac33213039343ef94d9d224ea73d2ffd2dbcb548dd6": _CURRENT_SAMPLE_SUPPORT,
    "c74eca00bf7ba2175c2ae1df84e485e025a2fa27cb1c220a505d4bc484bb6011": _CURRENT_SAMPLE_SUPPORT,
})


class ManifestHistoryError(HealthManifestError):
    """An invalid archive, stale snapshot, or explicitly unsupported identity."""

    def __init__(self, message: str, *, reason: str = "invalid-manifest-history"):
        super().__init__(message)
        self.reason = reason


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def canonical_json(value: object) -> bytes:
    """Serialize H's input, preserving arrays and rejecting non-finite values."""
    try:
        return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise ManifestHistoryError(f"Invalid canonical JSON: {exc}") from exc


def canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ManifestHistoryError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ManifestHistoryError(f"Non-finite JSON constant: {value}")


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ManifestHistoryError(f"Non-finite JSON number: {value}")
    return result


def parse_json(data: bytes | str) -> object:
    try:
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant,
                          parse_float=_float)
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, ManifestHistoryError):
            raise
        raise ManifestHistoryError(f"Invalid manifest JSON: {exc}") from exc


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestHistoryError(f"{field} must be a nonempty string")
    return value


def _filename(value: object) -> str:
    value = _text(value, "filename")
    if value in {".", ".."} or "/" in value or "\\" in value or ":" in value or "\0" in value:
        raise ManifestHistoryError(f"Not a path-safe filename: {value!r}")
    return value


def _filenames(value: object, field: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or (required and not value):
        raise ManifestHistoryError(f"{field} must be an array of filenames")
    names = tuple(_filename(item) for item in value)
    if len(set(names)) != len(names):
        raise ManifestHistoryError(f"Duplicate filenames in {field}")
    return names


def health_projection(manifest: Mapping) -> dict:
    """The exact whole-manifest health-manifest-v1 projection."""
    try:
        datasets = [
            {key: _plain(entry[key]) for key in _DATASET_FIELDS}
            for entry in manifest["datasets"] if entry.get("healthEligible") is True
        ]
        datasets.sort(key=lambda entry: entry["value"])
        entries = {entry["value"]: entry for entry in manifest["datasets"]}
        for entry in datasets:
            if "unifiedRecipe" in entries[entry["value"]]:
                entry["unifiedRecipe"] = _plain(entries[entry["value"]]["unifiedRecipe"])
        profiles = {entry["healthProfile"]: _plain(manifest["healthProfiles"][entry["healthProfile"]])
                    for entry in datasets}
        authority = manifest.get("authority")
        return {
            "projectionVersion": PROJECTION_VERSION,
            "datasets": datasets,
            "healthProfiles": profiles,
            "rosterPolicy": _plain(manifest.get("rosterPolicy")),
            "sourceDefaults": _plain(authority.get("sourceDefaults")) if authority is not None else None,
        }
    except (KeyError, TypeError, AttributeError) as exc:
        raise ManifestHistoryError(f"Invalid health projection: {exc}") from exc


def dataset_declaration(dataset: HealthDataset) -> dict:
    result = {
        "source": dataset.datasource_id, "value": dataset.dataset_id,
        "files": list(dataset.files), "mergeStrategy": dataset.merge_strategy,
        "rowExtractor": dataset.row_extractor, "adaptor": dataset.adaptor,
        "healthProfile": dataset.health_profile.profile_id,
    }
    if dataset.unified_recipe is not None:
        result["unifiedRecipe"] = _plain(dataset.unified_recipe)
    return result


def profile_declaration(profile: HealthProfile) -> dict:
    result = {
        "identityFile": profile.identity_file,
        "requiredOutcomes": list(profile.required_outcomes),
        "coverage": dict(profile.coverage),
        "topologyAuthority": profile.topology_authority,
        "borderRouterAuthority": profile.border_router_authority,
    }
    if profile.input_mode != "files":
        result.update(inputMode=profile.input_mode, evidenceReport=profile.evidence_report)
    return result


def _profile(profile_id: str, raw: object) -> HealthProfile:
    _text(profile_id, "profile ID")
    if not isinstance(raw, Mapping) or set(raw) not in (
        _PROFILE_FIELDS, _PROFILE_FIELDS | {"inputMode"},
        _PROFILE_FIELDS | {"inputMode", "evidenceReport"}
    ):
        raise ManifestHistoryError(f"Invalid profile declaration: {profile_id}")
    coverage = raw["coverage"]
    if not isinstance(coverage, Mapping) or set(coverage) != set(COVERAGE_PILLARS):
        raise ManifestHistoryError(f"Invalid coverage pillars: {profile_id}")
    if any(not isinstance(state, str) or state not in ALLOWED_COVERAGE_STATES
           for state in coverage.values()):
        raise ManifestHistoryError(f"Invalid coverage state: {profile_id}")
    if any(type(raw[key]) is not bool for key in ("topologyAuthority", "borderRouterAuthority")):
        raise ManifestHistoryError(f"Invalid authority flags: {profile_id}")
    result = HealthProfile(profile_id, _filename(raw["identityFile"]),
                         _filenames(raw["requiredOutcomes"], "requiredOutcomes"),
                         MappingProxyType(dict(coverage)), raw["topologyAuthority"],
                         raw["borderRouterAuthority"], raw.get("inputMode", "files"),
                         raw.get("evidenceReport"))
    from td_health_unified import validate_profile
    validate_profile(result)
    return result


def _dataset(raw: Mapping, profiles: Mapping[str, HealthProfile]) -> HealthDataset:
    for key in _DATASET_FIELDS:
        if key not in raw:
            raise ManifestHistoryError(f"Missing dataset field: {key}")
    dataset_id = _text(raw["value"], "dataset ID")
    profile_id = _text(raw["healthProfile"], "healthProfile")
    if profile_id not in profiles:
        raise ManifestHistoryError(f"Unknown healthProfile: {profile_id}")
    strategy = _text(raw["mergeStrategy"], "mergeStrategy")
    if strategy not in ALLOWED_MERGE_STRATEGIES:
        raise ManifestHistoryError(f"Invalid mergeStrategy: {strategy}")
    from td_health_unified import validate_recipe
    return HealthDataset(_text(raw["source"], "datasource"), dataset_id,
                         _filenames(raw["files"], "files", required=True), strategy,
                         _text(raw["rowExtractor"], "rowExtractor"),
                         _text(raw["adaptor"], "adaptor"), profiles[profile_id],
                         validate_recipe(raw.get("unifiedRecipe"))
                         if profiles[profile_id].input_mode == "unified" else None)


def retained_replay_contract(dataset: HealthDataset, sample_contract_version: str) -> dict:
    """Validate every required field before constructing a replay fingerprint."""
    if not isinstance(dataset, HealthDataset) or not isinstance(dataset.health_profile, HealthProfile):
        raise ManifestHistoryError("Replay contract requires a HealthDataset and profile")
    try:
        declaration = dataset_declaration(dataset)
        profile = profile_declaration(dataset.health_profile)
    except (TypeError, AttributeError) as exc:
        raise ManifestHistoryError("Replay contract requires complete dataset/profile fields") from exc
    _dataset(declaration, {dataset.health_profile.profile_id:
                          _profile(dataset.health_profile.profile_id, profile)})
    return {
        "contractVersion": REPLAY_CONTRACT_VERSION,
        "dataset": declaration, "profile": profile,
        "sampleContractVersion": _text(sample_contract_version, "sampleContractVersion"),
    }


def retained_replay_digest(dataset: HealthDataset, sample_contract_version: str) -> str:
    return canonical_digest(retained_replay_contract(dataset, sample_contract_version))


def target_contract(dataset: HealthDataset, sample_contract_version: str, *,
                    evaluator_version: str, policy_version: str, policy_digest: str) -> dict:
    return {
        "contractVersion": TARGET_CONTRACT_VERSION,
        "replayContract": retained_replay_contract(dataset, sample_contract_version),
        "evaluatorVersion": _text(evaluator_version, "evaluatorVersion"),
        "policyVersion": _text(policy_version, "policyVersion"),
        "policyDigest": _text(policy_digest, "policyDigest"),
        "inputAvailabilityVersion": "evaluation-inputs-v2",
        "adapterId": ADAPTER_ID,
    }


def target_contract_digest(dataset: HealthDataset, sample_contract_version: str, *,
                           evaluator_version: str, policy_version: str, policy_digest: str) -> str:
    return canonical_digest(target_contract(
        dataset, sample_contract_version, evaluator_version=evaluator_version,
        policy_version=policy_version, policy_digest=policy_digest))


def _validate_policy(raw: object, datasets: Mapping[str, HealthDataset], digest: str,
                     *, current: bool) -> None:
    if raw is None:
        if not current and digest in _OLD_POLICYLESS:
            return
        raise ManifestHistoryError("Missing historical rosterPolicy")
    fields = set(ROSTER_FIELDS)
    version = "roster-v2"
    if not current and digest in _ROSTER_V1:
        fields = (fields - {"eui"}) | {"eui64"}
        version = "roster-v1"
    if not isinstance(raw, Mapping) or raw.get("version") != version:
        raise ManifestHistoryError("Invalid historical rosterPolicy version")
    if set(raw) != {"version", "aliasCollisionWindowSeconds", "maxStringLength", "maxAddresses", "fields"}:
        raise ManifestHistoryError("Invalid rosterPolicy structure")
    if any(type(raw[key]) is not int or raw[key] <= 0 for key in (
        "aliasCollisionWindowSeconds", "maxStringLength", "maxAddresses",
    )):
        raise ManifestHistoryError("Invalid rosterPolicy limits")
    if not isinstance(raw["fields"], Mapping) or set(raw["fields"]) != fields:
        raise ManifestHistoryError("Invalid historical rosterPolicy fields")
    allowed = {name for dataset in datasets.values() if dataset.unified_recipe is None for name in dataset.files
               if not name.startswith(("td-mdns-", "td-static-"))
               and ".outcome." not in name and ".partial." not in name}
    from td_health_unified import sample_sources
    allowed.update(name for dataset in datasets.values() if dataset.unified_recipe is not None
                   for name in sample_sources(dataset)
                   if not name.startswith("td-mdns-") and ".outcome." not in name
                   and not name.endswith(("thread-network-info.json", "dataset-active.json")))
    for definition in raw["fields"].values():
        if not isinstance(definition, Mapping) or set(definition) != {"sources", "freshnessSeconds"}:
            raise ManifestHistoryError("Invalid rosterPolicy field definition")
        sources = definition["sources"]
        if not isinstance(sources, list) or not sources:
            raise ManifestHistoryError("Missing rosterPolicy sources")
        seen: set[str] = set()
        for source in sources:
            if not isinstance(source, Mapping) or set(source) != {"filename", "rank"}:
                raise ManifestHistoryError("Invalid rosterPolicy source")
            name = _filename(source["filename"])
            if name not in allowed or name in seen or type(source["rank"]) is not int or source["rank"] <= 0:
                raise ManifestHistoryError("Duplicate or unapproved rosterPolicy source")
            seen.add(name)
        age = definition["freshnessSeconds"]
        if age is not None and (type(age) is not int or age <= 0):
            raise ManifestHistoryError("Invalid rosterPolicy freshness")


def _parse_datasets(raw: object, digest: str, *, current: bool) -> Mapping[str, HealthDataset]:
    if not isinstance(raw, dict) or type(raw.get("schemaVersion")) is not int or raw["schemaVersion"] not in (1, 2):
        raise ManifestHistoryError("Unsupported historical manifest schemaVersion")
    if not isinstance(raw.get("healthProfiles"), dict) or not isinstance(raw.get("datasets"), list):
        raise ManifestHistoryError("Manifest requires healthProfiles and datasets")
    profiles = {name: _profile(name, value) for name, value in raw["healthProfiles"].items()}
    datasets: dict[str, HealthDataset] = {}
    seen: set[str] = set()
    for entry in raw["datasets"]:
        if not isinstance(entry, dict):
            raise ManifestHistoryError("Invalid historical dataset")
        dataset_id = _text(entry.get("value"), "dataset ID")
        if dataset_id in seen:
            raise ManifestHistoryError(f"Duplicate dataset ID: {dataset_id}")
        seen.add(dataset_id)
        if type(entry.get("healthEligible")) is not bool:
            raise ManifestHistoryError("healthEligible must be a boolean")
        if not entry["healthEligible"]:
            if raw["schemaVersion"] != 2:
                raise ManifestHistoryError("Schema-1 health dataset must be eligible")
            _filenames(entry.get("files"), "files", required=True)
            continue
        datasets[dataset_id] = _dataset(entry, profiles)
    ineligible = raw.get("ineligibleDatasets", [])
    if not isinstance(ineligible, list):
        raise ManifestHistoryError("ineligibleDatasets must be an array")
    ineligible_seen: set[str] = set()
    for entry in ineligible:
        if not isinstance(entry, dict):
            raise ManifestHistoryError("Invalid ineligible dataset")
        dataset_id = _text(entry.get("value"), "ineligible dataset ID")
        if dataset_id in datasets or dataset_id in ineligible_seen:
            raise ManifestHistoryError(f"Conflicting ineligible dataset: {dataset_id}")
        ineligible_seen.add(dataset_id)
        _text(entry.get("source"), "ineligible source")
        _text(entry.get("reason"), "ineligibility reason")
        evidence = entry.get("requiredEvidence")
        if not isinstance(evidence, list) or not evidence:
            raise ManifestHistoryError("Missing requiredEvidence")
        for value in evidence:
            _text(value, "requiredEvidence")
    if raw["schemaVersion"] == 2:
        from td_dataset_catalog import validate_dataset_catalog
        try:
            validate_dataset_catalog(raw, historical=not current)
        except (KeyError, TypeError, AttributeError, HealthManifestError) as exc:
            raise ManifestHistoryError(f"Invalid historical catalog: {exc}") from exc
        for filename in raw["authority"]["sourceDefaults"]:
            _filename(filename)
    _validate_policy(raw.get("rosterPolicy"), datasets, digest, current=current)
    return MappingProxyType(datasets)


@dataclass(frozen=True)
class ManifestRevision:
    revision_id: str
    manifest_digest: str
    health_contract_digest: str
    manifest: Mapping
    datasets: Mapping[str, HealthDataset]
    commit: str | None = None
    committed_at: str | None = None
    manifest_path: str = "src/td-dataset-manifest.json"
    is_current: bool = False
    capture_kind: str | None = None
    captured_at: str | None = None


@dataclass(frozen=True)
class ContractCandidate:
    revision: ManifestRevision
    dataset: HealthDataset
    sample_contract_version: str
    replay_contract_digest: str

    @property
    def revision_id(self) -> str:
        return self.revision.revision_id

    @property
    def replay_contract(self) -> Mapping:
        return _freeze(retained_replay_contract(self.dataset, self.sample_contract_version))


@dataclass(frozen=True)
class SourceContractResolution:
    status: str
    candidates: tuple[ContractCandidate, ...]
    source_contract_digest: str | None
    source_revision_ids: tuple[str, ...]
    dataset: HealthDataset | None
    reason: str | None = None


@dataclass(frozen=True)
class TargetContractResolution:
    dataset: HealthDataset | None
    adapter_id: str | None
    reason: str | None


@dataclass(frozen=True)
class ManifestHistoryResolver:
    current: ManifestRevision
    revisions: tuple[ManifestRevision, ...]
    manifest_path: Path
    history_path: Path
    snapshot_digest: str
    _manifest_bytes: bytes
    _history_bytes: bytes

    @property
    def resolver_snapshot_digest(self) -> str:
        return self.snapshot_digest

    @property
    def declared_dataset_ids(self) -> frozenset[str]:
        return frozenset(name for revision in (self.current, *self.revisions)
                         for name in revision.datasets)

    def verify_snapshot(self) -> None:
        if (_read(self.manifest_path) != self._manifest_bytes or
                _read(self.history_path) != self._history_bytes):
            raise ManifestHistoryError("Manifest/history snapshot changed", reason="stale-resolver-snapshot")

    def current_target(self, dataset_id: str) -> HealthDataset | None:
        return self.current.datasets.get(dataset_id)

    def matching_candidates(self, dataset_id: str, datasource_id: str, profile_id: str,
                            sample_contract_version: str, *,
                            revision_id: str | None = None) -> tuple[ContractCandidate, ...]:
        result: list[ContractCandidate] = []
        revisions = (self.current, *self.revisions)
        if revision_id is not None:
            revisions = tuple(revision for revision in revisions if revision.revision_id == revision_id)
            if not revisions:
                raise ManifestHistoryError("Unknown explicit manifest revision", reason="unknown-manifest-revision")
        for revision in revisions:
            dataset = revision.datasets.get(dataset_id)
            if dataset is None or (dataset.datasource_id, dataset.health_profile.profile_id) != (datasource_id, profile_id):
                if revision_id is not None:
                    raise ManifestHistoryError("Explicit revision contradicts dataset/source/profile",
                                               reason="conflicting-manifest-revision")
                continue
            support = (_CURRENT_SAMPLE_SUPPORT if revision.is_current else
                       PRODUCER_SAMPLE_SUPPORT.get(revision.manifest_digest, {}))
            if support.get(dataset_id) != sample_contract_version:
                if revision_id is not None:
                    raise ManifestHistoryError("Explicit revision cannot produce this sample contract",
                                               reason="unsupported-sample-contract")
                continue
            result.append(ContractCandidate(
                revision, dataset, sample_contract_version,
                retained_replay_digest(dataset, sample_contract_version)))
        return tuple(result)

    def resolve_source(self, dataset_id: str, datasource_id: str, profile_id: str,
                       sample_contract_version: str, *, revision_id: str | None = None,
                       source_profile: HealthProfile | Mapping | None = None) -> SourceContractResolution:
        candidates = self.matching_candidates(
            dataset_id, datasource_id, profile_id, sample_contract_version, revision_id=revision_id)
        if source_profile is not None:
            if isinstance(source_profile, Mapping):
                source_profile = _profile(profile_id, source_profile)
            candidates = tuple(item for item in candidates if item.dataset.health_profile == source_profile)
        digests = {item.replay_contract_digest for item in candidates}
        ids = tuple(sorted({item.revision_id for item in candidates}))
        if not candidates:
            reason = ("unsupported-sample-contract" if sample_contract_version not in
                      {"comparison-v1", "comparison-v1-route64", "comparison-v1-unified"} else "unsupported-profile")
            return SourceContractResolution("unresolved", (), None, (), None, reason)
        if len(digests) != 1:
            return SourceContractResolution("ambiguous", candidates, None, ids, None,
                                            "ambiguous-historical-contract")
        status = ("equivalent-contracts" if len(ids) > 1 else
                  "current-contract" if candidates[0].revision.is_current else "historical-contract")
        return SourceContractResolution(status, candidates, next(iter(digests)), ids, candidates[0].dataset)

    def resolve_target(self, source: SourceContractResolution,
                       sample_contract_version: str) -> TargetContractResolution:
        if source.dataset is None or source.source_contract_digest is None:
            return TargetContractResolution(None, None, source.reason or "unsupported-profile")
        target = self.current_target(source.dataset.dataset_id)
        if target is None:
            return TargetContractResolution(None, None, "no-current-health-target")
        if (_CURRENT_SAMPLE_SUPPORT.get(target.dataset_id) != sample_contract_version or
                retained_replay_digest(target, sample_contract_version) != source.source_contract_digest):
            return TargetContractResolution(target, None, "unsupported-contract-transition")
        return TargetContractResolution(target, ADAPTER_ID, None)


def _read(path: Path) -> bytes:
    try:
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ManifestHistoryError("Manifest/history changed during read",
                                       reason="stale-resolver-snapshot")
        return data
    except OSError as exc:
        raise ManifestHistoryError(f"Cannot read required manifest/history {path}: {exc}") from exc


def _revision(entry: object) -> ManifestRevision:
    fields = {"revisionId", "commit", "committedAt", "manifestPath", "manifestDigest",
              "healthContractDigest", "manifest"}
    worktree_fields = fields | {"captureKind", "capturedAt"}
    if not isinstance(entry, dict) or set(entry) not in (fields, worktree_fields):
        raise ManifestHistoryError("Unsupported archive revision fields")
    digest = entry["manifestDigest"]
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise ManifestHistoryError("Invalid manifestDigest")
    if entry["revisionId"] != f"manifest-sha256:{digest}":
        raise ManifestHistoryError("Revision ID does not match manifestDigest")
    worktree = set(entry) == worktree_fields
    if worktree:
        if entry["captureKind"] != "worktree" or entry["commit"] is not None or entry["committedAt"] is not None:
            raise ManifestHistoryError("Invalid worktree capture provenance")
    elif not isinstance(entry["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", entry["commit"]):
        raise ManifestHistoryError("Invalid revision commit")
    try:
        timestamp = datetime.fromisoformat(entry["capturedAt"] if worktree else entry["committedAt"])
        if timestamp.tzinfo is None:
            raise ValueError("Timestamp requires an offset")
    except (ValueError, TypeError) as exc:
        field = "capturedAt" if worktree else "committedAt"
        raise ManifestHistoryError(f"Invalid revision {field}") from exc
    if entry["manifestPath"] != "src/td-dataset-manifest.json":
        raise ManifestHistoryError("Unsupported historical manifestPath")
    if canonical_digest(entry["manifest"]) != digest:
        raise ManifestHistoryError("Historical manifest digest mismatch")
    datasets = _parse_datasets(entry["manifest"], digest, current=False)
    projection_digest = canonical_digest(health_projection(entry["manifest"]))
    if entry["healthContractDigest"] != projection_digest:
        raise ManifestHistoryError("Historical health projection digest mismatch")
    return ManifestRevision(entry["revisionId"], digest, projection_digest,
                            _freeze(entry["manifest"]), datasets, entry["commit"],
                            entry["committedAt"], entry["manifestPath"],
                            capture_kind=entry.get("captureKind"), captured_at=entry.get("capturedAt"))


def load_manifest_history(manifest_path: Path = MANIFEST_PATH,
                          history_path: Path = HISTORY_PATH) -> ManifestHistoryResolver:
    """Load both required files once; retain exact bytes for locked revalidation."""
    manifest_path, history_path = Path(manifest_path), Path(history_path)
    manifest_bytes, history_bytes = _read(manifest_path), _read(history_path)
    raw = parse_json(manifest_bytes)
    archive = parse_json(history_bytes)
    if (not isinstance(archive, dict) or set(archive) != {"schemaVersion", "projectionVersion", "revisions"}
            or type(archive["schemaVersion"]) is not int or archive["schemaVersion"] != 1
            or archive["projectionVersion"] != PROJECTION_VERSION
            or not isinstance(archive["revisions"], list)):
        raise ManifestHistoryError("Unsupported manifest history wrapper")
    digest = canonical_digest(raw)
    datasets = _parse_datasets(raw, digest, current=True)
    # The native loader remains authoritative, including its current catalog checks.
    load_health_manifest(manifest_path)
    current = ManifestRevision(f"manifest-sha256:{digest}", digest,
                               canonical_digest(health_projection(raw)), _freeze(raw),
                               datasets, is_current=True)
    revisions = tuple(_revision(entry) for entry in archive["revisions"])
    ids = [revision.revision_id for revision in revisions]
    commits = [revision.commit for revision in revisions if revision.commit is not None]
    if len(set(ids)) != len(ids) or len(set(commits)) != len(commits):
        raise ManifestHistoryError("Duplicate revision ID or conflicting commit declaration")
    if current.revision_id in ids:
        raise ManifestHistoryError("Current manifest must not be duplicated in the archive")
    snapshot_digest = canonical_digest({
        "snapshotVersion": "manifest-history-files-v1",
        "manifestBytesDigest": hashlib.sha256(manifest_bytes).hexdigest(),
        "historyBytesDigest": hashlib.sha256(history_bytes).hexdigest(),
    })
    resolver = ManifestHistoryResolver(current, revisions, manifest_path, history_path,
                                       snapshot_digest, manifest_bytes, history_bytes)
    resolver.verify_snapshot()
    return resolver
