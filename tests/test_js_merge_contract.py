from __future__ import annotations

import shutil

import pytest

from merge_contract_support import assert_case_result, load_contract, run_node_cases


CONTRACT = load_contract()
CASES = CONTRACT["cases"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_javascript_merge_contract_baseline(case: dict[str, object]) -> None:
    actual = run_node_cases([str(case["id"])])[str(case["id"])]
    assert_case_result(case, "javascript", actual)
