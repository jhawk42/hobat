"""Source-specific Thread role evidence for Home Assistant Matter snapshots."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from td_device_fields import FIELD_DEFINITIONS
from td_record_merge import append_merge_conflict


ROLE_FIELDS = ("isBorderRouter", "isRouter", "isLeader", "isReed")
_ROLE_ALIASES = {
    definition["path"]: definition["aliases"]
    for definition in FIELD_DEFINITIONS
    if definition["path"] in ROLE_FIELDS
}
ROLE_INPUT_FIELDS = tuple(
    dict.fromkeys(
        field
        for role_field in ROLE_FIELDS
        for field in (role_field, *_ROLE_ALIASES.get(role_field, ()))
    )
)
_THREAD_ROLES = {
    "leader": (True, True, False),
    "router": (True, False, False),
    "reed": (False, False, True),
    "end_device": (False, False, False),
    "sleepy_end_device": (False, False, False),
}
_THREAD_ROLE_SPELLINGS = {
    "Leader": "leader",
    "Router": "router",
    "Reed": "reed",
    "EndDevice": "end_device",
    "SleepyEndDevice": "sleepy_end_device",
}


def normalize_ha_matter_roles(
    record: Mapping[str, Any],
    *,
    thread_role: Any = None,
    is_thread: bool = False,
    border_router: bool = False,
    inventory_router: bool = False,
) -> dict[str, Any]:
    """Return a copy with explicit HA Matter role facts ahead of role evidence."""

    result = deepcopy(dict(record))
    if result.get("leaderEvidence") == "leader-router-id-match":
        result.pop("isLeader", None)
        result.pop("leaderEvidence", None)
    explicit: dict[str, bool] = {}
    conflicts: dict[str, list[tuple[bool, bool]]] = {
        field: [] for field in ROLE_FIELDS
    }

    for field in ROLE_FIELDS:
        candidates = (field, *_ROLE_ALIASES.get(field, ()))
        values = [
            result[key]
            for key in candidates
            if key in result and type(result[key]) is bool
        ]
        if values:
            explicit[field] = values[0]
            conflicts[field].extend(
                (values[0], value) for value in values[1:] if value is not values[0]
            )
        for key in candidates:
            if key in result and type(result[key]) is not bool:
                result.pop(key)

    normalized_role = thread_role
    if isinstance(normalized_role, str):
        normalized_role = _THREAD_ROLE_SPELLINGS.get(
            normalized_role, normalized_role.lower()
        )
    role_facts = (
        _THREAD_ROLES.get(normalized_role)
        if is_thread and isinstance(normalized_role, str)
        else None
    )
    derived: dict[str, bool] = {}
    if border_router or inventory_router:
        derived["isBorderRouter"] = True
        derived["isRouter"] = True
    if role_facts is not None:
        role_router, role_leader, role_reed = role_facts
        if "isRouter" in derived and derived["isRouter"] is not role_router:
            conflicts["isRouter"].append((derived["isRouter"], role_router))
        else:
            derived["isRouter"] = role_router
        derived["isLeader"] = role_leader
        derived["isReed"] = role_reed

    for field in ROLE_FIELDS:
        derived_value = derived.get(field)
        explicit_value = explicit.get(field)
        if (
            explicit_value is not None
            and derived_value is not None
            and explicit_value is not derived_value
        ):
            conflicts[field].append((explicit_value, derived_value))
        value = explicit_value if explicit_value is not None else derived_value
        if value is None:
            result.pop(field, None)
        else:
            result[field] = value

    for field in ROLE_FIELDS:
        for current, incoming in conflicts[field]:
            append_merge_conflict(result, field, current, incoming)
    return result
