"""Thread-device merge context and source policy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class MergeContext:
    existing_source: str = ""
    incoming_source: str = ""
    existing_priority: int = 0
    incoming_priority: int = 0
    owner_rloc16: str = ""
    partition_id: str = "unknown"
    incoming_partition_id: str = "unknown"
    conflict_target: dict[str, Any] | None = None
    conflict_limit: int = 20
    matter_identity_mode: str = "strict-omr"
    field_path: str = ""

    def for_field(self, field_name: str) -> "MergeContext":
        path = f"{self.field_path}.{field_name}" if self.field_path else field_name
        return replace(self, field_path=path)


FIELD_HANDLER_REGISTRY = {
    "route": "route",
    "children": "relationship",
    "childTable": "relationship",
    "childIpv6Addresses": "address_union",
    "routerNeighbors": "relationship",
    "_source_files": "provenance",
    "_merge_conflicts": "conflict",
}


def source_priority(source_name: str, priorities: Mapping[str, int]) -> int:
    return priorities.get(source_name, 0)


def create_merge_context(
    existing_source: str,
    incoming_source: str,
    priorities: Mapping[str, int],
    **values: Any,
) -> MergeContext:
    return MergeContext(
        existing_source=existing_source,
        incoming_source=incoming_source,
        existing_priority=source_priority(existing_source, priorities),
        incoming_priority=source_priority(incoming_source, priorities),
        **values,
    )


def sort_sources_by_priority(
    source_names: Sequence[str], priorities: Mapping[str, int]
) -> list[str]:
    return sorted(
        source_names,
        key=lambda source_name: source_priority(source_name, priorities),
        reverse=True,
    )