from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from td_device_merge import (
    FIELD_HANDLER_REGISTRY,
    create_merge_context,
    sort_sources_by_priority,
)


PRIORITIES = {"high.json": 10, "low.json": 1}


def test_source_order_is_descending_and_stable_for_unknowns() -> None:
    assert sort_sources_by_priority(
        ["unknown-a.json", "low.json", "unknown-b.json", "high.json"],
        PRIORITIES,
    ) == ["high.json", "low.json", "unknown-a.json", "unknown-b.json"]


def test_merge_context_records_sources_priorities_and_field_paths() -> None:
    context = create_merge_context(
        "high.json",
        "unknown.json",
        PRIORITIES,
        owner_rloc16="0x1000",
        partition_id="0x00000001",
    )
    assert context.existing_priority == 10
    assert context.incoming_priority == 0
    assert context.for_field("route").field_path == "route"
    with pytest.raises(FrozenInstanceError):
        context.existing_source = "changed.json"  # type: ignore[misc]


def test_handler_registry_owns_all_special_catalog_paths() -> None:
    assert set(FIELD_HANDLER_REGISTRY) == {
        "route",
        "children",
        "childTable",
        "childIpv6Addresses",
        "routerNeighbors",
        "_source_files",
        "_merge_conflicts",
    }