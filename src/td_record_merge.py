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
    return type(left) is type(right) and left == right


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
    conflicts = target.setdefault("_merge_conflicts", [])
    if not isinstance(conflicts, list):
        conflicts = []
        target["_merge_conflicts"] = conflicts
    entry = {
        "path": path,
        "current": deepcopy(current),
        "incoming": deepcopy(incoming),
    }
    if entry not in conflicts and len(conflicts) < limit:
        conflicts.append(entry)


def merge_lists(existing: list[Any], incoming: list[Any]) -> list[Any]:
    merged: list[Any] = []
    for value in [*existing, *incoming]:
        if not any(values_equivalent(value, item) for item in merged):
            merged.append(deepcopy(value))
    return merged