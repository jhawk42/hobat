"""Pure snapshot construction for the Thread Watch devices inventory."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from td_snapshot_security import contains_sensitive_field


class ThreadWatchSnapshotSecurityError(ValueError):
    """A Thread Watch inventory contains credential-bearing field names."""


_SENSITIVE_SUBSTRINGS = (
    "password",
    "passphrase",
    "secret",
    "token",
    "credential",
    "privatekey",
    "apikey",
    "networkkey",
    "pskc",
    "pskd",
)
_HEX_ADDRESS_LENGTH = 16
_HEX_RLOC_LENGTH = 4


@dataclass(frozen=True)
class ThreadWatchProjectionWarning:
    row_index: int
    field: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "row_index": self.row_index,
            "field": self.field,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ThreadWatchSnapshot:
    rows: list[dict[str, Any]]
    warnings: tuple[ThreadWatchProjectionWarning, ...]


def _matches_extra_sensitive_rule(normalized_key: str) -> bool:
    return any(fragment in normalized_key for fragment in _SENSITIVE_SUBSTRINGS)


def assert_thread_watch_safe(value: Any) -> None:
    if contains_sensitive_field(value, extra_match=_matches_extra_sensitive_rule):
        raise ThreadWatchSnapshotSecurityError(
            "Thread Watch response contains a forbidden credential field"
        )


def _hex_address(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or len(value) != _HEX_ADDRESS_LENGTH
        or any(character not in "0123456789abcdefABCDEF" for character in value)
        or value == "0" * _HEX_ADDRESS_LENGTH
    ):
        return None
    return value.lower()


def _rloc16(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    digits = value[2:] if value.lower().startswith("0x") else value
    if len(digits) != _HEX_RLOC_LENGTH or any(
        character not in "0123456789abcdefABCDEF" for character in digits
    ):
        return None
    return f"0x{digits.lower()}"


def _warn(
    warnings: list[ThreadWatchProjectionWarning],
    row_index: int,
    field: str,
    reason: str,
) -> None:
    warnings.append(ThreadWatchProjectionWarning(row_index, field, reason))


def _project_optional_string(
    source: Mapping[str, Any],
    source_field: str,
    target_field: str,
    target: dict[str, Any],
    warnings: list[ThreadWatchProjectionWarning],
    row_index: int,
) -> None:
    if source_field not in source:
        return
    value = source[source_field]
    if value is None or isinstance(value, str):
        target[target_field] = value
        return
    _warn(warnings, row_index, source_field, "invalid-value-type")


def _project_identity(
    source: Mapping[str, Any],
    source_field: str,
    target_field: str,
    target: dict[str, Any],
    warnings: list[ThreadWatchProjectionWarning],
    row_index: int,
    *,
    parent: bool = False,
) -> str | None:
    if source_field not in source:
        if not parent:
            _warn(warnings, row_index, source_field, "missing")
        return None
    value = source[source_field]
    if value is None:
        if parent:
            target[target_field] = None
        else:
            _warn(warnings, row_index, source_field, "null")
        return None
    normalized = _hex_address(value)
    if normalized is None:
        _warn(
            warnings,
            row_index,
            source_field,
            "zero" if value == "0" * _HEX_ADDRESS_LENGTH else "invalid",
        )
        return None
    target[target_field] = normalized
    return normalized


def _project_role(
    source: Mapping[str, Any],
    target: dict[str, Any],
    warnings: list[ThreadWatchProjectionWarning],
    row_index: int,
) -> str | None:
    if "role" not in source:
        return None
    role = source["role"]
    if role is None:
        target["role"] = None
        return None
    if role in ("router", "child"):
        target["role"] = role
        return role
    _warn(warnings, row_index, "role", "unsupported-value")
    return None


def _project_router_id(
    source: Mapping[str, Any],
    target: dict[str, Any],
    warnings: list[ThreadWatchProjectionWarning],
    row_index: int,
    role: str | None,
    rloc16: str | None,
) -> None:
    if role not in ("router", "child") or "router_id" not in source:
        return
    value = source["router_id"]
    if isinstance(value, bool) or not isinstance(value, int):
        _warn(warnings, row_index, "router_id", "invalid-value-type")
        return
    if not 0 <= value <= 62:
        _warn(warnings, row_index, "router_id", "out-of-range")
        return
    if rloc16 is None:
        _warn(warnings, row_index, "router_id", "rloc-required")
        return
    if int(rloc16[2:], 16) >> 10 != value:
        _warn(warnings, row_index, "router_id", "rloc-mismatch")
        return
    target["routerId" if role == "router" else "parentRouterId"] = value


def _router_rloc16(child_rloc16: str) -> str:
    return f"0x{int(child_rloc16[2:], 16) & 0xFC00:04x}"


def _child_relationship_record(row: Mapping[str, Any]) -> dict[str, Any]:
    child_rloc16 = row["rloc16"]
    child: dict[str, Any] = {
        "id": f"0x{int(child_rloc16[2:], 16) & 0x03FF:04x}",
        "rloc16": child_rloc16,
        "role": "child",
    }
    for field in ("extAddress", "deviceLabel"):
        if field in row:
            child[field] = row[field]
    return child


def _is_child_rloc16(value: object) -> bool:
    return (
        isinstance(value, str)
        and (normalized := _rloc16(value)) is not None
        and (int(normalized[2:], 16) & 0x03FF) != 0
    )


def _add_parent_children(rows: list[dict[str, Any]]) -> None:
    routers_by_address: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        if (
            row.get("role") != "router"
            or row.get("isRouter") is not True
            or not isinstance(row.get("extAddress"), str)
            or not isinstance(row.get("rloc16"), str)
        ):
            continue
        routers_by_address.setdefault(row["extAddress"], []).append(index)

    children: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        if (
            row.get("role") != "child"
            or not isinstance(row.get("parentExtAddress"), str)
            or not _is_child_rloc16(row.get("rloc16"))
        ):
            continue
        parent_indexes = routers_by_address.get(row["parentExtAddress"], ())
        if len(parent_indexes) != 1:
            continue
        parent_index = parent_indexes[0]
        if rows[parent_index]["rloc16"] != _router_rloc16(row["rloc16"]):
            continue
        children.setdefault(parent_index, []).append(
            _child_relationship_record(row)
        )

    for index, row in enumerate(rows):
        records = children.get(index)
        if not records:
            continue
        row["children"] = records
        row["totalChildren"] = len(records)


def build_device_snapshot(records: Iterable[Mapping[str, Any]]) -> ThreadWatchSnapshot:
    """Build one lossless root row for every accepted Thread Watch device."""

    rows: list[dict[str, Any]] = []
    warnings: list[ThreadWatchProjectionWarning] = []
    for row_index, original in enumerate(records):
        if not isinstance(original, Mapping):
            raise TypeError("Thread Watch device rows must be mappings")
        source = deepcopy(dict(original))
        assert_thread_watch_safe(source)
        target: dict[str, Any] = {
            "type": "threadDevice",
            "threadWatch": source,
        }

        _project_identity(
            source, "addr", "extAddress", target, warnings, row_index
        )
        rloc16 = None
        if "rloc16" in source:
            if source["rloc16"] is None:
                target["rloc16"] = None
            else:
                rloc16 = _rloc16(source["rloc16"])
                if rloc16 is None:
                    _warn(warnings, row_index, "rloc16", "invalid")
                else:
                    target["rloc16"] = rloc16
        _project_optional_string(
            source, "name", "deviceLabel", target, warnings, row_index
        )
        _project_identity(
            source,
            "parent_addr",
            "parentExtAddress",
            target,
            warnings,
            row_index,
            parent=True,
        )
        _project_optional_string(
            source,
            "parent",
            "parentDeviceLabel",
            target,
            warnings,
            row_index,
        )
        role = _project_role(source, target, warnings, row_index)

        if "border_router" in source and source["border_router"] is not None:
            target["isBorderRouter"] = True
        if role == "router":
            target["isRouter"] = True
        if "leader" in source:
            leader = source["leader"]
            if leader is True:
                target["isLeader"] = True
                if role == "child":
                    _warn(warnings, row_index, "leader", "child-leader-conflict")
            elif leader is not None and not isinstance(leader, bool):
                _warn(warnings, row_index, "leader", "invalid-value-type")

        _project_router_id(source, target, warnings, row_index, role, rloc16)
        rows.append(target)
    _add_parent_children(rows)
    return ThreadWatchSnapshot(rows=rows, warnings=tuple(warnings))
