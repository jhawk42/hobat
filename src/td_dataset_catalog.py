"""Validation and loading for the shared dashboard and merge catalog."""

import json
from pathlib import Path

from td_health_manifest import MANIFEST_PATH, HealthManifestError, load_health_manifest


def validate_dataset_catalog(raw: dict) -> None:
    if raw.get("schemaVersion") != 2:
        raise HealthManifestError("Dataset catalog requires schemaVersion 2")
    vocabulary = raw.get("vocabulary")
    if not isinstance(vocabulary, dict):
        raise HealthManifestError("Dataset catalog requires vocabulary")
    for name in ("knownFiles", "mergeStrategies", "rowExtractors", "adaptors", "physicsProfiles"):
        if not isinstance(vocabulary.get(name), list) or not vocabulary[name]:
            raise HealthManifestError(f"Dataset catalog requires vocabulary.{name}")
    prefixes = vocabulary.get("valuePrefixBySource")
    required_extractors = vocabulary.get("requiredExtractorByAdaptor")
    if not isinstance(prefixes, dict) or not isinstance(required_extractors, dict):
        raise HealthManifestError("Dataset catalog requires source and adaptor vocabulary")
    datasources = raw.get("datasources")
    if not isinstance(datasources, list) or not datasources:
        raise HealthManifestError("Dataset catalog requires datasources")
    sources = {entry.get("value") for entry in datasources if isinstance(entry, dict)}
    if len(sources) != len(datasources) or any(not isinstance(source, str) for source in sources):
        raise HealthManifestError("Dataset catalog has duplicate or invalid datasources")
    for entry in raw["datasets"]:
        label = entry["value"]
        source = entry.get("source")
        if source not in sources or not label.startswith(prefixes.get(source, "\0")):
            raise HealthManifestError(f"Invalid datasource prefix for {label}")
        files = entry.get("files")
        if not isinstance(files, list) or not files or any(
            not isinstance(file, str) or Path(file).name != file or file not in vocabulary["knownFiles"]
            for file in files
        ):
            raise HealthManifestError(f"Invalid catalog files for {label}")
        for key, name in (("mergeStrategy", "mergeStrategies"), ("rowExtractor", "rowExtractors"),
                          ("adaptor", "adaptors"), ("defaultPhysicsProfile", "physicsProfiles")):
            if entry.get(key) not in vocabulary[name]:
                raise HealthManifestError(f"Invalid {key} for {label}")
        extractors = entry.get("mergeRowExtractors")
        if extractors is not None and (not isinstance(extractors, list) or len(extractors) != len(files)
                                       or any(item not in vocabulary["rowExtractors"] for item in extractors)):
            raise HealthManifestError(f"Invalid mergeRowExtractors for {label}")
        if required_extractors.get(entry["adaptor"]) not in (None, entry["rowExtractor"]):
            raise HealthManifestError(f"Invalid adaptor/rowExtractor for {label}")
    if not isinstance(raw.get("mergeGroups"), dict) or not isinstance(raw.get("authority"), dict):
        raise HealthManifestError("Dataset catalog requires mergeGroups and authority")
    groups = raw["mergeGroups"]
    for name, definition in groups.items():
        if not isinstance(definition, dict):
            raise HealthManifestError(f"Invalid merge group: {name}")
        if "composedOf" in definition:
            if any(part not in groups or part == name for part in definition["composedOf"]):
                raise HealthManifestError(f"Invalid merge group composition: {name}")
        else:
            items = list(definition.get("files", []))
            for dataset in raw["datasets"]:
                if name in dataset.get("mergeGroups", []):
                    items.extend(dataset.get("mergeInputs", []))
            if len({item.get("order") for item in items if item.get("enabled", True)}) != sum(
                item.get("enabled", True) for item in items
            ):
                raise HealthManifestError(f"Invalid merge input order: {name}")
            for item in items:
                if not isinstance(item.get("file"), str) or Path(item["file"]).name != item["file"] or (
                    item.get("enabled") is False and not item.get("disabledReason")
                ):
                    raise HealthManifestError(f"Invalid merge input: {name}")
    defaults = raw["authority"].get("sourceDefaults")
    if not isinstance(defaults, dict) or any(
        not isinstance(file, str) or type(rank) is not int or rank <= 0
        for file, rank in defaults.items()
    ):
        raise HealthManifestError("Invalid source authority defaults")


def load_dataset_catalog(path: Path = MANIFEST_PATH) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    validate_dataset_catalog(raw)
    policy = load_health_manifest(path).roster_policy
    raw["authority"]["fieldOverrides"] = {field: dict(ranks) for field, ranks in policy.sources.items()}
    raw["authority"]["freshnessSeconds"] = dict(policy.freshness_seconds)
    return raw