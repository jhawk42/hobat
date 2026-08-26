from __future__ import annotations

from pathlib import Path

import pytest

from merge_contract_support import (
    assert_case_result,
    load_contract,
    run_python_case,
    validate_contract,
)


CONTRACT = load_contract()
CASES = CONTRACT["cases"]


def test_device_merge_contract_schema() -> None:
    assert validate_contract(CONTRACT) == []


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_python_merge_contract_baseline(case: dict[str, object], tmp_path: Path) -> None:
    actual = run_python_case(case, tmp_path)
    assert_case_result(case, "python", actual)
