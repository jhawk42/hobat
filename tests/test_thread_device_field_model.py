from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from td_device_fields import (
    FIELD_DEFINITIONS,
    get_device_identity_keys,
    is_placeholder_ext_address,
    normalize_input_record,
)


pytestmark = pytest.mark.requires_data_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / "tests" / "fixtures" / "thread_device_field_model.json"
MODEL = json.loads(MODEL_PATH.read_text(encoding="utf-8"))

CATEGORIES = {"device", "derived", "extension", "relationship", "metadata", "error"}
JSON_TYPES = {"null", "boolean", "number", "string", "array", "object"}
SOURCES = {"rest", "cli", "mdns", "eve"}
TRANSFORMS = {
    "identity",
    "identifier",
    "boolean",
    "number",
    "route",
    "relationship",
    "stringArray",
}
PATH_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
CASE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_model(model: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if model.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    if not isinstance(model.get("modelVersion"), str):
        errors.append("modelVersion must be a string")
    if not isinstance(model.get("snapshotFiles"), list) or not model["snapshotFiles"]:
        errors.append("snapshotFiles must be a non-empty array")

    fields = model.get("fields")
    if not isinstance(fields, list) or not fields:
        errors.append("fields must be a non-empty array")
        return errors

    paths: set[str] = set()
    aliases: dict[str, str] = {}
    for index, field in enumerate(fields):
        location = f"fields[{index}]"
        path = field.get("path")
        if not isinstance(path, str) or not PATH_PATTERN.fullmatch(path):
            errors.append(f"{location}.path is invalid")
            continue
        if path in paths:
            errors.append(f"duplicate preferred path {path}")
        paths.add(path)
        if field.get("category") not in CATEGORIES:
            errors.append(f"{path}.category is invalid")
        json_types = field.get("jsonTypes")
        if not isinstance(json_types, list) or not json_types or not set(json_types) <= JSON_TYPES:
            errors.append(f"{path}.jsonTypes is invalid")
        sources = field.get("sources")
        if not isinstance(sources, list) or not sources or not set(sources) <= SOURCES:
            errors.append(f"{path}.sources is invalid")
        if field.get("transform") not in TRANSFORMS:
            errors.append(f"{path}.transform is invalid")
        if not isinstance(field.get("mergePolicy"), str) or not field["mergePolicy"]:
            errors.append(f"{path}.mergePolicy is required")
        field_aliases = field.get("aliases")
        if not isinstance(field_aliases, list):
            errors.append(f"{path}.aliases must be an array")
            continue
        for alias in field_aliases:
            if not isinstance(alias, str) or not alias.strip():
                errors.append(f"{path} has invalid alias {alias!r}")
            elif alias in aliases and aliases[alias] != path:
                errors.append(f"alias {alias} maps to both {aliases[alias]} and {path}")
            elif alias in paths and alias != path:
                errors.append(f"alias {alias} is also a preferred path")
            else:
                aliases[alias] = path
        nested_identity = field.get("nestedIdentity")
        if nested_identity is not None and (
            field.get("category") != "relationship"
            or not isinstance(nested_identity, list)
            or not all(isinstance(item, str) for item in nested_identity)
        ):
            errors.append(f"{path}.nestedIdentity is invalid")

    ignored = model.get("ignoredTransportPaths")
    if not isinstance(ignored, list) or not all(isinstance(path, str) for path in ignored):
        errors.append("ignoredTransportPaths must be a string array")
    elif set(ignored) & paths:
        errors.append("transport paths must not be catalog fields")

    case_ids: set[str] = set()
    cases = model.get("normalizationCases")
    if not isinstance(cases, list) or not cases:
        errors.append("normalizationCases must be a non-empty array")
    else:
        for index, case in enumerate(cases):
            case_id = case.get("id") if isinstance(case, dict) else None
            if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
                errors.append(f"normalizationCases[{index}].id is invalid")
            elif case_id in case_ids:
                errors.append(f"duplicate normalization case {case_id}")
            else:
                case_ids.add(case_id)
            if not isinstance(case.get("input"), dict) or not isinstance(case.get("expected"), dict):
                errors.append(f"{case_id} requires input and expected objects")

    return errors


def test_thread_device_field_model_schema() -> None:
    assert validate_model(MODEL) == []


def test_python_runtime_metadata_matches_model() -> None:
    expected = {
        field["path"]: {
            "path": field["path"],
            "aliases": tuple(field["aliases"]),
            "transform": field["transform"],
        }
        for field in MODEL["fields"]
    }
    actual = {field["path"]: field for field in FIELD_DEFINITIONS}
    assert actual == expected


def test_snapshot_files_exist() -> None:
    missing = [name for name in MODEL["snapshotFiles"] if not (REPO_ROOT / "data" / name).is_file()]
    assert missing == []


def _extract_snapshot_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("data"), list):
        records = []
        for item in payload["data"]:
            if not isinstance(item, dict):
                continue
            record = dict(item)
            if isinstance(item.get("attributes"), dict):
                record.update(item["attributes"])
            records.append(record)
        return records
    return [item for item in payload.values() if isinstance(item, dict)]


def _iter_leaf_paths(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            if not prefix and key in MODEL["ignoredTransportPaths"]:
                continue
            child_path = f"{prefix}.{key}" if prefix else key
            yield from _iter_leaf_paths(child, child_path)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_leaf_paths(child, prefix)
    elif prefix:
        yield prefix


def test_maintained_snapshot_paths_are_classified() -> None:
    catalog_paths = {field["path"] for field in MODEL["fields"]}
    aliases = {
        alias: field["path"]
        for field in MODEL["fields"]
        for alias in field["aliases"]
    }
    observed: set[str] = set()
    for filename in MODEL["snapshotFiles"]:
        payload = json.loads((REPO_ROOT / "data" / filename).read_text(encoding="utf-8"))
        for record in _extract_snapshot_records(payload):
            observed.update(_iter_leaf_paths(record))

    def is_classified(path: str) -> bool:
        canonical = aliases.get(path, path)
        return any(
            canonical == catalog_path or canonical.startswith(f"{catalog_path}.")
            for catalog_path in catalog_paths
        )

    unclassified = sorted(path for path in observed if not is_classified(path))
    assert unclassified == []


def test_relationship_collections_are_distinct() -> None:
    relationship_paths = {
        field["path"]
        for field in MODEL["fields"]
        if field["category"] == "relationship"
    }
    assert {"children", "childTable", "childIpv6Addresses", "routerNeighbors"} <= relationship_paths
    alias_owners = {
        alias: field["path"]
        for field in MODEL["fields"]
        for alias in field["aliases"]
    }
    assert alias_owners.get("children", "children") == "children"
    assert alias_owners.get("childTable", "childTable") == "childTable"


@pytest.mark.parametrize(
    "case", MODEL["normalizationCases"], ids=lambda case: case["id"]
)
def test_python_field_model_normalization(case: dict[str, Any]) -> None:
    original = deepcopy(case["input"])
    actual = normalize_input_record(case["input"])
    assert actual == case["expected"]
    assert case["input"] == original
    assert normalize_input_record(actual) == actual
    for strategy, expected_keys in case.get("identityKeys", {}).items():
        assert get_device_identity_keys(actual, strategy) == expected_keys


def test_ext_address_placeholder_policy() -> None:
    assert is_placeholder_ext_address("")
    assert is_placeholder_ext_address("0000000000000000")
    assert not is_placeholder_ext_address("0011223344556677")
