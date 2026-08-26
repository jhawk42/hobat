from __future__ import annotations

from td_record_merge import (
    append_merge_conflict,
    merge_lists,
    merge_unique_strings,
    value_is_empty,
    values_equivalent,
)


def test_empty_value_policy_is_exact() -> None:
    assert all(value_is_empty(value) for value in (None, "", [], {}))
    assert all(not value_is_empty(value) for value in (False, 0, " ", [0], {"x": 0}))


def test_value_equivalence_does_not_coerce_types() -> None:
    assert values_equivalent({"x": [1]}, {"x": [1]})
    assert not values_equivalent(1, True)
    assert not values_equivalent(1, 1.0)


def test_conflicts_are_raw_deduplicated_and_bounded() -> None:
    target: dict[str, object] = {}
    append_merge_conflict(target, "status", "online", "offline", limit=2)
    append_merge_conflict(target, "status", "online", "offline", limit=2)
    append_merge_conflict(target, "role", "router", "child", limit=2)
    append_merge_conflict(target, "type", "router", "border router", limit=2)
    assert target["_merge_conflicts"] == [
        {"path": "status", "current": "online", "incoming": "offline"},
        {"path": "role", "current": "router", "incoming": "child"},
    ]


def test_stable_unions_preserve_first_observation_order() -> None:
    assert merge_unique_strings(["alpha", " alpha "], ["beta", "alpha"]) == [
        "alpha",
        "beta",
    ]
    assert merge_lists([{"id": 1}], [{"id": 1}, {"id": 2}]) == [
        {"id": 1},
        {"id": 2},
    ]