from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from merge_contract_support import (
    canonicalize_result,
    deferred_case_summary,
    first_difference,
    load_contract,
    run_node_cases,
    run_python_case,
)


CONTRACT = load_contract()
CONTRACT_CASES = [
    case for case in CONTRACT["cases"] if case["enforcement"] == "contract"
]
BASELINE_CASES = [
    case for case in CONTRACT["cases"] if case["enforcement"] == "baseline"
]


def test_no_deferred_baseline_cases_remain() -> None:
    summary = deferred_case_summary(CONTRACT)
    assert BASELINE_CASES == []
    assert summary == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
@pytest.mark.parametrize("case", CONTRACT_CASES, ids=lambda case: case["id"])
def test_python_javascript_contract_parity(case: dict[str, object], tmp_path: Path) -> None:
    case_id = str(case["id"])
    python_result = run_python_case(case, tmp_path)
    javascript_result = run_node_cases([case_id])[case_id]
    unordered_paths = case.get("comparison", {}).get("unorderedArrays", [])
    canonical_python = canonicalize_result(python_result, unordered_paths)
    canonical_javascript = canonicalize_result(javascript_result, unordered_paths)
    difference = first_difference(canonical_python, canonical_javascript)
    assert difference is None, f"{case_id} parity {difference}"
