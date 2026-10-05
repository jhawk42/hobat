from __future__ import annotations

import pytest

from ha_matter_ws_roles import normalize_ha_matter_roles


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("Leader", {"isRouter": True, "isLeader": True, "isReed": False}),
        ("Router", {"isRouter": True, "isLeader": False, "isReed": False}),
        ("Reed", {"isRouter": False, "isLeader": False, "isReed": True}),
        ("EndDevice", {"isRouter": False, "isLeader": False, "isReed": False}),
        (
            "SleepyEndDevice",
            {"isRouter": False, "isLeader": False, "isReed": False},
        ),
    ],
)
def test_commissioned_thread_role_truth_table(role, expected) -> None:
    result = normalize_ha_matter_roles({}, thread_role=role, is_thread=True)

    assert {key: result[key] for key in expected} == expected
    assert "isBorderRouter" not in result


@pytest.mark.parametrize(
    ("record", "kwargs", "expected"),
    [
        ({"role": "leader"}, {"is_thread": False}, {}),
        (
            {"role": "ap"},
            {"thread_role": "Leader", "is_thread": False},
            {},
        ),
        (
            {"role": "router"},
            {"thread_role": "unknown", "is_thread": True},
            {},
        ),
        (
            {},
            {"border_router": True},
            {"isBorderRouter": True, "isRouter": True},
        ),
        (
            {},
            {"inventory_router": True},
            {"isBorderRouter": True, "isRouter": True},
        ),
    ],
)
def test_context_and_positive_inventory_gates(record, kwargs, expected) -> None:
    result = normalize_ha_matter_roles(record, **kwargs)

    assert {key: result[key] for key in expected} == expected
    assert all(key not in result for key in ("isLeader", "isReed") if key not in expected)


def test_canonical_false_wins_and_records_role_conflict() -> None:
    result = normalize_ha_matter_roles(
        {"isRouter": False},
        thread_role="Router",
        is_thread=True,
    )

    assert result["isRouter"] is False
    assert result["_merge_conflicts"] == [
        {"path": "isRouter", "current": False, "incoming": True}
    ]


def test_border_router_kind_wins_derived_router_conflict_not_explicit_fact() -> None:
    result = normalize_ha_matter_roles(
        {},
        thread_role="Reed",
        is_thread=True,
        border_router=True,
    )

    assert result["isRouter"] is True
    assert result["isReed"] is True
    assert result["_merge_conflicts"] == [
        {"path": "isRouter", "current": True, "incoming": False}
    ]


def test_border_router_alias_precedence_and_explicit_false_conflicts() -> None:
    result = normalize_ha_matter_roles(
        {
            "isBorderRouter": False,
            "is_border_router": True,
            "br": True,
            "leader": False,
            "isReed": None,
        },
        thread_role="Leader",
        is_thread=True,
        border_router=True,
    )

    assert result["isBorderRouter"] is False
    assert result["isRouter"] is True
    assert result["isLeader"] is False
    assert result["isReed"] is False
    assert result["_merge_conflicts"] == [
        {"path": "isBorderRouter", "current": False, "incoming": True},
        {"path": "isLeader", "current": False, "incoming": True},
    ]


def test_unrecognized_boolean_values_are_omitted_and_normalization_is_idempotent() -> None:
    initial = {
        "isRouter": "true",
        "isLeader": None,
        "isReed": "yes",
        "_merge_conflicts": [],
    }
    once = normalize_ha_matter_roles(initial, thread_role="unassigned", is_thread=True)
    twice = normalize_ha_matter_roles(once, thread_role="unassigned", is_thread=True)

    assert once == twice == {"_merge_conflicts": []}


def test_router_id_leader_match_is_not_role_evidence() -> None:
    result = normalize_ha_matter_roles(
        {
            "isLeader": True,
            "leaderEvidence": "leader-router-id-match",
            "routerId": 1,
            "leaderData": {"leaderRouterId": 1},
        }
    )

    assert "isLeader" not in result
    assert "leaderEvidence" not in result
