from __future__ import annotations

from pathlib import Path

import pytest

from merge_contract_support import assert_case_result, load_contract

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "tests" / "fixtures" / "device_merge_contract.json"
RUNNER = REPO_ROOT / "tests" / "js" / "run-device-merge-contract.mjs"
CONTRACT_CASES = {case["id"]: case for case in load_contract()["cases"]}


def _assert_route_case(node_json, case_id: str) -> None:
    actual = node_json(RUNNER, str(CONTRACT_PATH), case_id)[case_id]
    assert_case_result(CONTRACT_CASES[case_id], "javascript", actual)


@pytest.mark.frontend
def test_deep_merge_supports_routeData_array_merge(node_json) -> None:
    _assert_route_case(node_json, "route-known-partition-mismatch")


@pytest.mark.frontend
def test_deep_merge_reconciles_route_sequence_by_rfc1982(node_json) -> None:
    _assert_route_case(node_json, "route-sequence-wraparound-250-to-5")
