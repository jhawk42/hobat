from __future__ import annotations

from pathlib import Path

import pytest

from merge_dataset import build_merged_records
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


def test_offline_merge_normalizes_legacy_cli_thread_fields(tmp_path: Path) -> None:
    filename = "td-otbr-cli-networkdiag-fetch-all.json"
    records, _report = build_merged_records(
        tmp_path,
        "",
        [filename],
        {},
        input_data={filename: [{
            "extaddr": "0011223344556677",
            "rloc16": "0x0400",
            "eui64": "8899aabbccddeeff",
            "ver": 4,
            "thread_version": "1.3",
        }]},
    )

    [record] = records
    assert record["eui"] == "8899aabbccddeeff"
    assert record["threadVersionDecimal"] == 4
    assert record["threadVersion"] == "1.3"
    assert "eui64" not in record
    assert "ver" not in record
    assert "version" not in record


def test_offline_merge_emits_canonical_border_router_with_alias_conflict(tmp_path: Path) -> None:
    filename = "td-otbr-cli-networkdiag-fetch-all.json"
    records, _report = build_merged_records(
        tmp_path,
        "",
        [filename],
        {},
        input_data={filename: [{
            "extaddr": "0011223344556677",
            "rloc16": "0x0400",
            "isBorderRouter": False,
            "is_border_router": True,
            "br": False,
        }]},
    )

    [record] = records
    assert record["isBorderRouter"] is False
    assert "is_border_router" not in record
    assert "br" not in record
    assert record["_merge_conflicts"] == [
        {"path": "isBorderRouter", "current": False, "incoming": True}
    ]
