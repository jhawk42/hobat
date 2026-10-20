from __future__ import annotations

import pytest

from otbr_role_evidence import normalize_otbr_role_record


@pytest.mark.parametrize(
    "record",
    [
        {"role": "child", "mode": {"device": "FTD"}},
        {"type": "child", "mode": {"device": "FTD"}},
        {
            "role": "router",
            "type": "child",
            "mode": {"device": "FTD"},
        },
    ],
)
def test_child_role_or_type_with_ftd_mode_is_reed(record):
    assert normalize_otbr_role_record(record)["isReed"] is True
    assert "isReed" not in record


@pytest.mark.parametrize(
    "record",
    [
        {"role": "router", "mode": {"device": "FTD"}},
        {"type": "router", "mode": {"device": "FTD"}},
        {"role": "child", "mode": {"device": "MTD"}},
        {"type": "child", "mode": {"device": "Unknown"}},
        {"role": "child"},
        {"mode": {"device": "FTD"}},
        {"role": "Child", "mode": {"device": "FTD"}},
    ],
)
def test_incomplete_or_nonmatching_evidence_does_not_add_reed(record):
    assert normalize_otbr_role_record(record) == record


@pytest.mark.parametrize("explicit", [True, False])
def test_explicit_boolean_is_authoritative(explicit):
    record = {
        "role": "child",
        "mode": {"device": "FTD"},
        "isReed": explicit,
    }

    normalized = normalize_otbr_role_record(record)

    assert normalized["isReed"] is explicit
    if explicit:
        assert "_merge_conflicts" not in normalized
    else:
        assert normalized["_merge_conflicts"] == [
            {"path": "isReed", "current": False, "incoming": True}
        ]
        assert normalize_otbr_role_record(normalized) == normalized


def test_false_conflict_is_bounded_and_deduplicated():
    record = {
        "role": "child",
        "mode": {"device": "FTD"},
        "isReed": False,
        "_merge_conflicts": [
            {"path": f"existing-{index}", "current": index, "incoming": index + 1}
            for index in range(20)
        ],
    }

    normalized = normalize_otbr_role_record(record)

    assert normalized["isReed"] is False
    assert len(normalized["_merge_conflicts"]) == 20
    assert normalized["_merge_conflicts"] == record["_merge_conflicts"]
