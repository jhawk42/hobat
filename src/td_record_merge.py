"""Language-neutral record merge primitives."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


CONFLICT_LIMIT = 20


def value_is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def merge_unique_strings(existing: list[Any], incoming: list[Any]) -> list[str]:
    merged: list[str] = []
    for value in [*existing, *incoming]:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def values_equivalent(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            values_equivalent(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            values_equivalent(a, b) for a, b in zip(left, right)
        )
    return left == right


def merge_conflicts(existing: Any, incoming: Any, limit: int = CONFLICT_LIMIT) -> list[Any]:
    result: list[Any] = []
    for entries in (existing, incoming):
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if len(result) >= limit:
                break
            if not any(values_equivalent(entry, item) for item in result):
                result.append(deepcopy(entry))
    return result


def append_merge_conflict(
    target: dict[str, Any],
    path: str,
    current: Any,
    incoming: Any,
    *,
    limit: int = CONFLICT_LIMIT,
) -> None:
    if not path:
        return
    conflicts = merge_conflicts(target.get("_merge_conflicts"), [], limit)
    target["_merge_conflicts"] = conflicts
    entry = {
        "path": path,
        "current": deepcopy(current),
        "incoming": deepcopy(incoming),
    }
    if not any(values_equivalent(entry, item) for item in conflicts) and len(conflicts) < limit:
        conflicts.append(entry)


def merge_lists(existing: list[Any], incoming: list[Any]) -> list[Any]:
    merged: list[Any] = []
    for value in [*existing, *incoming]:
        if not any(values_equivalent(value, item) for item in merged):
            merged.append(deepcopy(value))
    return merged