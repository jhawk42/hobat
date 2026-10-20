"""Source-specific role evidence normalization for OTBR records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from td_record_merge import append_merge_conflict


def has_otbr_reed_evidence(record: Mapping[str, Any]) -> bool:
    mode = record.get("mode")
    return (
        (record.get("role") == "child" or record.get("type") == "child")
        and isinstance(mode, Mapping)
        and mode.get("device") == "FTD"
    )


def normalize_otbr_role_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return an OTBR record with only positively evidenced REED state added."""
    result = dict(record)
    if not has_otbr_reed_evidence(result):
        return result

    existing = result.get("isReed")
    if type(existing) is bool:
        if existing is False:
            append_merge_conflict(result, "isReed", False, True)
        return result

    result["isReed"] = True
    return result
