from __future__ import annotations

import json
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from merge_dataset import build_merged_records, normalize_identifiers
from td_json_key_normalizer import convert_keys_to_camel_case


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "tests" / "fixtures" / "device_merge_contract.json"
NODE_RUNNER_PATH = REPO_ROOT / "tests" / "js" / "run-device-merge-contract.mjs"

AREAS = {
    "identity",
    "normalization",
    "scalar",
    "precedence",
    "route",
    "child",
    "neighbor",
    "mdns",
    "matter",
    "provenance",
    "conflict",
}
OPERATIONS = {"normalize", "merge"}
ENFORCEMENT_STATES = {"baseline", "contract"}
KNOWN_STRATEGIES = {"by-identity", "by-rloc16"}
CASE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
UNORDERED_PATH_PATTERN = re.compile(
    r"^\$\[\*\](?:\.[A-Za-z_][A-Za-z0-9_]*)+(?:\[\*\])?$"
)


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    if not isinstance(contract.get("contractVersion"), str):
        errors.append("contractVersion must be a string")

    cases = contract.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a non-empty array")
        return errors

    case_ids: set[str] = set()
    for index, case in enumerate(cases):
        location = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{location} must be an object")
            continue

        case_id = case.get("id")
        if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
            errors.append(f"{location}.id must be unique kebab-case")
        elif case_id in case_ids:
            errors.append(f"{location}.id duplicates {case_id}")
        else:
            case_ids.add(case_id)

        if case.get("area") not in AREAS:
            errors.append(f"{case_id}.area is invalid")
        if case.get("operation") not in OPERATIONS:
            errors.append(f"{case_id}.operation is invalid")
        if case.get("enforcement") not in ENFORCEMENT_STATES:
            errors.append(f"{case_id}.enforcement is invalid")
        if not isinstance(case.get("description"), str) or not case["description"].strip():
            errors.append(f"{case_id}.description is required")
        if not isinstance(case.get("inputs"), dict):
            errors.append(f"{case_id}.inputs must be an object")

        expected = case.get("expected")
        if not isinstance(expected, dict) or "contract" not in expected:
            errors.append(f"{case_id}.expected.contract is required")
            continue

        if case.get("enforcement") == "baseline":
            current = expected.get("current")
            if not isinstance(current, dict):
                errors.append(f"{case_id}.expected.current is required for baseline")
            else:
                for runtime in ("python", "javascript"):
                    if runtime not in current:
                        errors.append(f"{case_id}.expected.current.{runtime} is required")
            if not isinstance(case.get("correctionOwner"), str):
                errors.append(f"{case_id}.correctionOwner is required for baseline")
        elif "current" in expected:
            errors.append(f"{case_id} contract cases must not define expected.current")

        inputs = case.get("inputs", {})
        if case.get("operation") == "merge":
            if inputs.get("strategy") not in KNOWN_STRATEGIES:
                errors.append(f"{case_id}.inputs.strategy is invalid")
            sources = inputs.get("sources")
            if not isinstance(sources, list) or not sources:
                errors.append(f"{case_id}.inputs.sources must be non-empty")
            else:
                for source_index, source in enumerate(sources):
                    if not isinstance(source, dict):
                        errors.append(f"{case_id}.sources[{source_index}] must be an object")
                        continue
                    if not isinstance(source.get("name"), str) or not source["name"]:
                        errors.append(f"{case_id}.sources[{source_index}].name is required")
                    if not isinstance(source.get("records"), list):
                        errors.append(f"{case_id}.sources[{source_index}].records must be an array")
        elif not isinstance(inputs.get("record"), dict):
            errors.append(f"{case_id}.inputs.record must be an object")

        comparison = case.get("comparison", {})
        unordered_paths = comparison.get("unorderedArrays", []) if isinstance(comparison, dict) else []
        if not isinstance(unordered_paths, list) or any(
            not isinstance(path, str) or not UNORDERED_PATH_PATTERN.fullmatch(path)
            for path in unordered_paths
        ):
            errors.append(f"{case_id}.comparison.unorderedArrays contains an invalid path")

    return errors


def project_result(value: Any) -> Any:
    if isinstance(value, list):
        return [project_result(item) for item in value]
    if isinstance(value, dict):
        return {
            key: project_result(child)
            for key, child in value.items()
            if key not in {"_row_key", "_merge_identity_keys"}
        }
    return value


def _identity_sort_key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    extaddr = str(record.get("extAddress") or record.get("extaddr") or "").lower()
    omr = str(
        record.get("omrIpv6Address")
        or record.get("omrIpv6Addr")
        or record.get("omr_ipv6_addr")
        or ""
    ).lower()
    rloc16 = str(record.get("rloc16") or "").lower()
    serialized = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return extaddr, omr, rloc16, serialized


def canonicalize_result(value: Any, unordered_paths: list[str] | None = None) -> Any:
    projected = project_result(deepcopy(value))
    paths = set(unordered_paths or [])

    def visit(child: Any, path: str) -> Any:
        if isinstance(child, dict):
            return {key: visit(item, f"{path}.{key}") for key, item in child.items()}
        if isinstance(child, list):
            result = [visit(item, f"{path}[*]") for item in child]
            if path in paths:
                return sorted(result, key=lambda item: json.dumps(item, sort_keys=True))
            return result
        return child

    canonical = visit(projected, "$[*]" if isinstance(projected, list) else "$")
    if isinstance(canonical, list) and all(isinstance(item, dict) for item in canonical):
        canonical.sort(key=_identity_sort_key)
    return canonical


def first_difference(expected: Any, actual: Any, path: str = "$") -> str | None:
    if type(expected) is not type(actual):
        return f"{path}: expected {type(expected).__name__}, got {type(actual).__name__}"
    if isinstance(expected, dict):
        expected_keys = set(expected)
        actual_keys = set(actual)
        if expected_keys != actual_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            return f"{path}: missing keys {missing}, extra keys {extra}"
        for key in expected:
            difference = first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}: expected length {len(expected)}, got {len(actual)}"
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            difference = first_difference(expected_item, actual_item, f"{path}[{index}]")
            if difference:
                return difference
        return None
    if expected != actual:
        return f"{path}: expected {expected!r}, got {actual!r}"
    return None


def run_python_case(case: dict[str, Any], work_dir: Path) -> Any:
    inputs = case["inputs"]
    if case["operation"] == "normalize":
        normalized = deepcopy(inputs["record"])
        for _ in range(inputs.get("repeat", 1)):
            normalized = normalize_identifiers(normalized, inputs.get("omrPrefix", ""))
        return project_result(convert_keys_to_camel_case(normalized))

    input_files: list[str] = []
    for index, source in enumerate(inputs["sources"]):
        filename = source["name"]
        if filename in input_files:
            filename = f"{index}-{filename}"
        (work_dir / filename).write_text(json.dumps(source["records"]), encoding="utf-8")
        input_files.append(filename)

    options = inputs.get("options", {})
    records, _report = build_merged_records(
        base_dir=work_dir,
        omr_prefix=options.get("omrPrefix", ""),
        input_files=input_files,
        device_label_map={},
        matter_identity_mode=options.get("matterIdentityMode", "strict-omr"),
    )
    return project_result(records)


def run_node_cases(case_ids: list[str] | None = None) -> dict[str, Any]:
    command = [
        "node",
        "--experimental-default-type=module",
        str(NODE_RUNNER_PATH),
        str(CONTRACT_PATH),
    ]
    command.extend(case_ids or [])
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def expected_for_runtime(case: dict[str, Any], runtime: str) -> Any:
    if case["enforcement"] == "contract":
        return case["expected"]["contract"]
    return case["expected"]["current"][runtime]


def deferred_case_summary(contract: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "id": case["id"],
            "area": case["area"],
            "correctionOwner": case["correctionOwner"],
        }
        for case in sorted(contract["cases"], key=lambda item: item["id"])
        if case["enforcement"] == "baseline"
    ]


def assert_case_result(case: dict[str, Any], runtime: str, actual: Any) -> None:
    paths = case.get("comparison", {}).get("unorderedArrays", [])
    expected = canonicalize_result(expected_for_runtime(case, runtime), paths)
    canonical_actual = canonicalize_result(actual, paths)
    difference = first_difference(expected, canonical_actual)
    assert difference is None, f"{case['id']} [{runtime}] {difference}"
