"""Validation and loading for the shared dashboard and merge catalog."""

import json
import re
from pathlib import Path

from td_health_manifest import MANIFEST_PATH, HealthManifestError, load_health_manifest
from td_const import (
    EXTADDR_DEVICE_LABEL_MAP_FILENAME,
    HA_MATTER_WS_SERVER_INFO_FILENAME,
    HA_MATTER_WS_THREAD_DIAGNOSTICS_FILENAME,
    OTBR_RESTAPI_ACTIONS_LIST_FILENAME,
    UNIFIED_FILENAMES,
)


RETIRED_HEALTH_DATASET_IDS = frozenset({
    "otbr_cli_networkdiag_fetch_all",
    "otbr_cli_topology_health",
    "otbr_cli_topology_mdns_health",
    "otbr_restapi_devices_fetch_diagnostics_fetch_all",
    "otbr_restapi_devices_fetch_diagnostics_fetch_all_mesh_diagnostics_fetch_all",
    "otbr_restapi_topology_mdns_health",
    "merged_otbr_topology_mdns_health",
})


def unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise HealthManifestError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def resolve_dataset(catalog: dict, dataset_id: str, source: str | None = None) -> dict:
    """Resolve current non-health aliases without changing a recipe or health ID."""
    canonical = catalog.get("datasetAliases", {}).get(dataset_id, dataset_id)
    entry = next((item for item in catalog["datasets"] if item["value"] == canonical), None)
    if entry is None:
        raise HealthManifestError(f"Unsupported dataset: {dataset_id}")
    if source is not None:
        source_alias = catalog.get("sourceAliases", {}).get(source)
        if source_alias is not None and (
            dataset_id not in catalog.get("datasetAliases", {}) or entry.get("healthEligible") is True
        ):
            raise HealthManifestError(f"Unsupported source/dataset pair: {source}/{dataset_id}")
        if (source_alias or source) != entry["source"]:
            raise HealthManifestError(f"Mismatched source/dataset pair: {source}/{dataset_id}")
    return entry


def validate_unified_recipes(raw: dict) -> None:
    known_files = set(raw["vocabulary"]["knownFiles"])
    extractors = {"raw-array", "json-api", "identity", "outcome",
                  "ha-inventory", "ha-border-routers", "ha-native-topology",
                  "ha-projection", "unified"}
    dependencies: dict[str, list[str]] = {}
    source_prefixes = {
        "otbr-cli": "td-otbr-cli-", "otbr-restapi": "td-otbr-restapi-",
        "ha-matter-ws": "td-ha-matter-ws-", "mdns": "td-mdns-scopes-",
    }
    for entry in raw["datasets"]:
        recipe = entry.get("unified")
        if recipe is None:
            if entry["value"] in UNIFIED_FILENAMES:
                raise HealthManifestError(f"Unified dataset requires a recipe: {entry['value']}")
            continue
        dataset_id = entry["value"]
        row_file = UNIFIED_FILENAMES.get(dataset_id)
        if (row_file is None or entry["files"] != [row_file]
                or entry["mergeStrategy"] != "none" or entry["rowExtractor"] != "raw-array"
                or entry["adaptor"] != "unified" or not isinstance(recipe, dict)
                or set(recipe) != {"version", "reportFile", "outcomeFile", "identityFile", "inputs"}
                or recipe["version"] != "unified-v1"):
            raise HealthManifestError(f"Invalid Unified recipe: {dataset_id}")
        stem = row_file.removesuffix(".json")
        expected = {"reportFile": f"{stem}.report.json",
                    "outcomeFile": None if dataset_id == "mdns_unified" else f"{stem}.outcome.json",
                    "identityFile": None if dataset_id == "mdns_unified" else f"{stem}-thread-network-info.json"}
        if dataset_id == "ha_matter_ws_unified":
            expected["identityFile"] = "td-ha-matter-ws-thread-network-info.json"
        for key, filename in expected.items():
            if recipe[key] != filename or (filename is not None and filename not in known_files):
                raise HealthManifestError(f"Invalid Unified {key}: {dataset_id}")
        inputs = recipe["inputs"]
        if not isinstance(inputs, list) or not inputs:
            raise HealthManifestError(f"Missing Unified inputs: {dataset_id}")
        seen: set[str] = set()
        dependencies[row_file] = []
        outputs = {row_file, *[name for name in expected.values() if name is not None],
                   f"{stem}.network.json"}
        for item in inputs:
            if (not isinstance(item, dict) or set(item) != {"file", "role", "required", "extractor"}
                    or not isinstance(item["file"], str) or item["file"] not in known_files
                    or "/" in item["file"] or "\\" in item["file"]
                    or item["file"] in seen or item["file"] in outputs
                    or item["role"] not in {"records", "identity", "outcome", "projection"}
                    or type(item["required"]) is not bool or item["extractor"] not in extractors
                    or (item["role"] in {"identity", "outcome"}
                        and item["extractor"] != item["role"])
                    or (item["role"] in {"records", "projection"}
                        and item["extractor"] in {"identity", "outcome"})):
                raise HealthManifestError(f"Invalid Unified input: {dataset_id}")
            filename = item["file"]
            prefix = source_prefixes.get(entry["source"])
            forbidden = {
                OTBR_RESTAPI_ACTIONS_LIST_FILENAME, HA_MATTER_WS_SERVER_INFO_FILENAME,
                HA_MATTER_WS_THREAD_DIAGNOSTICS_FILENAME,
            }
            if (filename in forbidden or ".partial." in filename
                    or (prefix is not None and not filename.startswith(prefix))
                    or (item["role"] in {"records", "projection"}
                        and (filename.endswith((".outcome.json", ".report.json", ".network.json"))
                             or filename in UNIFIED_FILENAMES.values()) and entry["source"] != "multi-source")
                    or (entry["source"] == "multi-source" and filename not in {
                        *UNIFIED_FILENAMES.values(), EXTADDR_DEVICE_LABEL_MAP_FILENAME})):
                raise HealthManifestError(f"Excluded Unified input: {filename}")
            seen.add(item["file"])
            dependencies[row_file].append(item["file"])
        if not any(item["role"] == "records" and item["required"] for item in inputs):
            raise HealthManifestError(f"Unified recipe needs required records: {dataset_id}")
        if entry["source"] == "multi-source":
            dependencies_by_file = {
                dataset["files"][0]: dataset for dataset in raw["datasets"]
                if "unified" in dataset and dataset["source"] != "multi-source"
            }
            if (len(inputs) != 4 or any(
                item["file"] not in dependencies_by_file or item["role"] != "records"
                or not item["required"] or item["extractor"] != "unified" for item in inputs
            ) or {dependencies_by_file[item["file"]]["source"] for item in inputs}
                    != set(source_prefixes)):
                raise HealthManifestError("Multi-source Unified requires exactly four source primaries")
    def visit(filename: str, visiting: set[str]) -> None:
        if filename in visiting:
            raise HealthManifestError("Cyclic Unified inputs")
        for dependency in dependencies.get(filename, []):
            visit(dependency, visiting | {filename})
    for filename in dependencies:
        visit(filename, set())


def validate_dataset_catalog(raw: dict, *, historical: bool = False) -> None:
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
    datasets = raw.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise HealthManifestError("Dataset catalog requires datasets")
    values: dict[str, dict] = {}
    for entry in datasets:
        if not isinstance(entry, dict):
            raise HealthManifestError("Invalid dataset declaration")
        label = entry.get("value")
        pattern = r"[a-z][a-z0-9_]*" if historical else r"[a-z][a-z0-9_]{0,39}"
        if not isinstance(label, str) or not re.fullmatch(pattern, label):
            raise HealthManifestError(f"Invalid dataset identifier: {label}")
        if not historical and label in RETIRED_HEALTH_DATASET_IDS:
            raise HealthManifestError(f"Unsupported retired health dataset: {label}")
        if label in values:
            raise HealthManifestError(f"Duplicate dataset value: {label}")
        values[label] = entry
        if "selectable" in entry and type(entry["selectable"]) is not bool:
            raise HealthManifestError(f"Invalid selectable for {label}")
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
    aliases = raw.get("datasetAliases", {})
    if not isinstance(aliases, dict):
        raise HealthManifestError("Invalid datasetAliases")
    for alias, target in aliases.items():
        if (not isinstance(alias, str) or not alias or alias in values
                or alias in RETIRED_HEALTH_DATASET_IDS or not isinstance(target, str)
                or target not in values or target in aliases
                or values[target].get("healthEligible") is True):
            raise HealthManifestError(f"Invalid dataset alias: {alias}")
    source_aliases = raw.get("sourceAliases", {})
    if not isinstance(source_aliases, dict) or any(
        alias != "merged" or target != "multi-source" or alias in sources or target not in sources
        for alias, target in source_aliases.items()
    ):
        raise HealthManifestError("Invalid sourceAliases")
    validate_unified_recipes(raw)
    for source in datasources:
        for key in ("default_dataset_value", "primary_dataset_value"):
            if key not in source:
                continue
            dataset = values.get(source[key]) if isinstance(source[key], str) else None
            if dataset is None or dataset["source"] != source["value"] or not dataset.get("selectable", True):
                raise HealthManifestError(f"Invalid {key} for {source['value']}")
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
    raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_json_object)
    validate_dataset_catalog(raw)
    policy = load_health_manifest(path).roster_policy
    raw["authority"]["fieldOverrides"] = {field: dict(ranks) for field, ranks in policy.sources.items()}
    raw["authority"]["freshnessSeconds"] = dict(policy.freshness_seconds)
    return raw