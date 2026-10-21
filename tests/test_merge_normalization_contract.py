from __future__ import annotations

from pathlib import Path

import pytest

from merge_dataset import build_merged_records
from merge_contract_support import (
    assert_case_result,
    canonicalize_result,
    first_difference,
    load_contract,
    run_python_case,
    validate_contract,
)


CONTRACT = load_contract()
CASES = CONTRACT["cases"]


def test_device_merge_contract_schema() -> None:
    assert validate_contract(CONTRACT) == []


def test_contract_comparator_preserves_order_metadata_and_recursive_types(tmp_path: Path) -> None:
    assert canonicalize_result([{"rloc16": "z"}, {"rloc16": "a"}]) == [
        {"rloc16": "z"}, {"rloc16": "a"}
    ]
    assert canonicalize_result({"_merge_identity_keys": ["b", "a"]}) == {
        "_merge_identity_keys": ["b", "a"]
    }
    assert first_difference({"a": [True]}, {"a": [1]}) is not None
    assert first_difference({"a": 1, "b": 2}, {"b": 2, "a": 1}) is None
    contract = load_contract()
    contract["cases"][0]["comparison"] = {"unorderedArrays": ["$[*]._merge_identity_keys"]}
    assert any("must remain ordered" in error for error in validate_contract(contract))
    with pytest.raises(ValueError, match="Unsupported Python contract strategy"):
        run_python_case({"operation": "merge", "inputs": {"strategy": "by-rloc16"}}, tmp_path)


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


def test_offline_merge_keeps_tlv_summaries_collection_scoped(tmp_path: Path) -> None:
    fetch_all = "td-otbr-cli-networkdiag-fetch-all.json"
    multicast = "td-otbr-cli-networkdiag-multicast-network.json"
    records, _report = build_merged_records(
        tmp_path,
        "",
        [fetch_all, multicast],
        {},
        input_data={
            fetch_all: [{
                "extaddr": "0011223344556677",
                "rloc16": "0x0400",
                "tlv_values": "0 1 2 8",
                "tlv_response_values": "0 1 2",
            }],
            multicast: [{
                "extaddr": "0011223344556677",
                "rloc16": "0x0400",
                "tlvRequestValues": "0 1 2 8 9",
                "tlvResponseValues": "0 1 2 8 9",
            }],
        },
    )

    [record] = records
    assert record["tlvRequestValues"] == "0 1 2 8"
    assert record["tlvResponseValues"] == "0 1 2"
    assert "tlvValues" not in record
    assert {
        conflict["path"]
        for conflict in record.get("_merge_conflicts", [])
    } >= {"tlvRequestValues", "tlvResponseValues"}
