"""Evidence-bound recovery of OTBR REST network-diagnostic outcomes."""

from __future__ import annotations

import ipaddress
import math
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from td_network_identity import canonical_ext_pan_id


REST_DIAGNOSTIC_RECOVERY_VERSION = "rest-diagnostic-recovery-v1"
_MAX_ROUTER_ID = 62
_MAX_CHILD_ID = 511
_RLOC16_CHILD_MASK = 0x03FF

_NETWORK_DIAGNOSTIC_TYPE_ALIASES = {"eui64": "eui", "version": "threadVersion"}
_NETWORK_DIAGNOSTIC_TYPE_IDS = {
    0: "extAddress",
    1: "rloc16",
    2: "mode",
    3: "timeout",
    4: "connectivity",
    5: "route",
    6: "leaderData",
    7: "networkData",
    8: "ipv6Addresses",
    9: "macCounters",
    14: "batteryLevel",
    15: "supplyVoltage",
    16: "childTable",
    17: "channelPages",
    19: "maxChildTimeout",
    20: "lDevIdSubject",
    21: "iDevIdCert",
    23: "eui",
    24: "threadVersion",
    25: "vendorName",
    26: "vendorModel",
    27: "vendorSwVersion",
    28: "threadStackVersion",
    29: "children",
    30: "childIpv6Addresses",
    31: "routerNeighbors",
    34: "mleCounters",
}
_KNOWN_FIELDS = frozenset(_NETWORK_DIAGNOSTIC_TYPE_IDS.values())
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _diagnostic_identity_view(item: object) -> Mapping[str, Any]:
    if not isinstance(item, Mapping):
        return {}
    data = item.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("attributes"), Mapping):
        return data["attributes"]
    return item


def _diagnostic_id(item: object) -> str | None:
    if not isinstance(item, Mapping):
        return None
    data = item.get("data")
    value = data.get("id") if isinstance(data, Mapping) else item.get("id")
    return value if isinstance(value, str) and value else None


def diagnostic_items(payload: object) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        return []
    if isinstance(payload.get("items"), list):
        return payload["items"]
    data = payload.get("data")
    if isinstance(data, list):
        return [{"data": item} for item in data]
    return [payload] if isinstance(data, Mapping) else []


def _parse_rloc16(value: object) -> int | None:
    if type(value) is int:
        return value if 0 <= value <= 0xFFFF else None
    if isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{1,4}", value):
        return int(value, 16)
    return None


def _parse_router_rloc16(value: object) -> tuple[int | None, str | None]:
    rloc16 = _parse_rloc16(value)
    if rloc16 is None:
        return None, "invalid_parent_rloc16"
    if rloc16 & _RLOC16_CHILD_MASK:
        return None, "parent_rloc16_not_router"
    if rloc16 >> 10 > _MAX_ROUTER_ID:
        return None, "parent_router_id_out_of_range"
    return rloc16, None


def _parse_child_id(value: object) -> int | None:
    if type(value) is int and 1 <= value <= _MAX_CHILD_ID:
        return value
    return None


def _usable_ext_address(value: object) -> str | None:
    if (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-fA-F]{16}", value)
        and value.strip("0")
    ):
        return value.lower()
    return None


def _child_rloc_destination(parent_rloc16: int, child_id: int) -> tuple[int, str]:
    child_rloc16 = (parent_rloc16 & 0xFC00) | child_id
    return child_rloc16, f"{child_rloc16:06x}"


def _format_rloc16(value: int) -> str:
    return f"0x{value:04x}"


def valid_child_table(value: object) -> bool:
    if not isinstance(value, list):
        return False
    entries: dict[int, Mapping[str, Any]] = {}
    for entry in value:
        if not isinstance(entry, Mapping):
            return False
        child_id = _parse_child_id(entry.get("childId"))
        if child_id is None:
            return False
        if child_id in entries and entries[child_id] != entry:
            return False
        entries[child_id] = entry
    return True


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None or result.utcoffset() is None:
        return None
    return result.astimezone(timezone.utc)


def _within_run(created: object, started: datetime, completed: datetime) -> bool:
    instant = _timestamp(created)
    if instant is None or not isinstance(created, str):
        return False
    match = re.search(r"T\d\d:\d\d:\d\d(?:\.(\d+))?", created)
    if match is None:
        return False
    digits = len(match.group(1) or "")
    precision = timedelta(microseconds=10 ** max(0, 6 - digits))
    return instant <= completed and instant + precision > started


def _contains(actual: object, expected: object) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and all(
            key in actual and _contains(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _contains(left, right) for left, right in zip(actual, expected)
        )
    return type(actual) is type(expected) and actual == expected


def _valid_field(name: str, value: object) -> bool:
    if name == "extAddress":
        return _usable_ext_address(value) is not None
    if name == "rloc16":
        return _parse_rloc16(value) is not None
    if name == "childTable":
        return valid_child_table(value)
    if name == "mode":
        if not isinstance(value, Mapping) or not value:
            return False
        for key in ("rxOnWhenIdle", "fullThreadDevice", "fullNetworkData"):
            if key in value and type(value[key]) is not bool:
                return False
        if "device" in value and "fullThreadDevice" in value:
            if (value["device"] == "FTD") != value["fullThreadDevice"]:
                return False
        return "device" not in value or (
            isinstance(value["device"], str) and value["device"] in {"MTD", "FTD"}
        )
    if name == "ipv6Addresses":
        if not isinstance(value, list):
            return False
        try:
            return all(isinstance(item, str) and ipaddress.IPv6Address(item) for item in value)
        except ipaddress.AddressValueError:
            return False
    if name in {"macCounters", "mleCounters"}:
        return isinstance(value, Mapping) and bool(value) and all(
            isinstance(number, (int, float))
            and not isinstance(number, bool)
            and math.isfinite(number)
            and number >= 0
            for number in value.values()
        )
    if name in {"connectivity", "route", "leaderData", "networkData"}:
        return isinstance(value, (Mapping, list)) and bool(value)
    if name in {"children", "childIpv6Addresses", "routerNeighbors", "channelPages"}:
        return isinstance(value, list)
    if name in {"timeout", "batteryLevel", "supplyVoltage", "maxChildTimeout"}:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
        )
    return isinstance(value, (str, int)) and not isinstance(value, bool) and value != ""


def _field_names(values: object) -> set[str]:
    if not isinstance(values, list):
        return set()
    names = set()
    for value in values:
        if type(value) is int:
            name = _NETWORK_DIAGNOSTIC_TYPE_IDS.get(value)
        elif isinstance(value, str):
            name = _NETWORK_DIAGNOSTIC_TYPE_ALIASES.get(value, value)
        else:
            name = None
        if name in _KNOWN_FIELDS:
            names.add(name)
    return names


def _action_matches(action: object, diagnostic_id: str) -> bool:
    if action is None:
        return True
    if not isinstance(action, Mapping) or action.get("status") != "completed":
        return False
    relationships = action.get("relationships")
    if relationships is None:
        return True
    if not isinstance(relationships, Mapping):
        return False
    result = relationships.get("result")
    data = result.get("data") if isinstance(result, Mapping) else None
    return isinstance(data, Mapping) and data.get("id") == diagnostic_id


def _failure_reason(record: Mapping[str, Any]) -> str:
    errors = record.get("attemptErrors")
    if isinstance(errors, list):
        for error in reversed(errors):
            if isinstance(error, Mapping):
                reason = error.get("type") or error.get("message")
                if isinstance(reason, str) and reason:
                    return reason
    error = record.get("error")
    if isinstance(error, Mapping):
        reason = error.get("type") or error.get("message")
        if isinstance(reason, str) and reason:
            return reason
    return "failed-pass"


def _field_availability(
    record: Mapping[str, Any], row: Mapping[str, Any], diagnostic_id: str
) -> dict[str, dict[str, str]]:
    successful: set[str] = set()
    failed: dict[str, str] = {}
    passes = record.get("passes")
    if isinstance(passes, list) and passes:
        for item in passes:
            if not isinstance(item, Mapping):
                continue
            names = _field_names(item.get("requestedTypes"))
            if (
                item.get("status") == "completed"
                and item.get("diagnosticId") == diagnostic_id
                and _action_matches(item.get("action"), diagnostic_id)
            ):
                successful.update(names)
            elif item.get("status") == "failed":
                for name in names:
                    failed[name] = _failure_reason(item)
    else:
        attempted = record.get("attemptedTypes")
        if isinstance(attempted, list):
            for values in attempted[:-1]:
                for name in _field_names(values):
                    failed[name] = _failure_reason(record)
            if attempted and _action_matches(record.get("action"), diagnostic_id):
                successful.update(_field_names(attempted[-1]))

    fields: dict[str, dict[str, str]] = {}
    for name in sorted(_KNOWN_FIELDS):
        if name in row:
            if _valid_field(name, row[name]):
                fields[name] = {"availability": "present"}
            else:
                fields[name] = {"availability": "unavailable", "reason": "invalid-value"}
        elif name in successful:
            fields[name] = {"availability": "not-provided"}
        elif name in failed:
            fields[name] = {"availability": "unavailable", "reason": failed[name]}
        else:
            fields[name] = {"availability": "not-requested"}
    return fields


def _original_status(record: Mapping[str, Any]) -> object:
    if "originalStatus" in record:
        return record["originalStatus"]
    status = record.get("status")
    if status == "completed":
        if record.get("skipReasonCode") == "unresolved_mesh_local_iid":
            return "skipped"
        if record.get("fallbackRecovered") is True:
            return "partial"
        passes = record.get("passes")
        if record.get("selectedPass") == "fast" and isinstance(passes, list) and any(
            isinstance(item, Mapping) and item.get("status") == "failed"
            for item in passes
        ):
            return "partial"
    return status


def _router_fallback(record: Mapping[str, Any]) -> bool:
    attempted = record.get("attemptedTypes")
    errors = record.get("attemptErrors")
    return (
        record.get("fallbackRecovered") is True
        and type(record.get("attempts")) is int
        and record["attempts"] >= 2
        and isinstance(attempted, list)
        and len(attempted) >= 2
        and isinstance(errors, list)
        and bool(errors)
        and all(
            isinstance(error, Mapping)
            and error.get("type") in {"OTBRActionFailedError", "OTBRInvalidResponseError"}
            for error in errors
        )
    )


def _detail_gap(record: Mapping[str, Any], diagnostic_id: str) -> bool:
    if record.get("reasonCode") in {
        "identity_missing", "identity_changed", "identity_conflict", "rloc16_mismatch"
    }:
        return False
    passes = record.get("passes")
    if not isinstance(passes, list) or record.get("selectedPass") != "fast":
        return False
    fast = [
        item for item in passes
        if isinstance(item, Mapping)
        and item.get("name") == "fast"
        and item.get("status") == "completed"
        and item.get("diagnosticId") == diagnostic_id
        and _action_matches(item.get("action"), diagnostic_id)
    ]
    failed = [
        item for item in passes
        if isinstance(item, Mapping) and item.get("status") == "failed"
    ]
    if len(fast) != 1 or not failed or len(fast) + len(failed) != len(passes):
        return False
    allowed = {"OTBRActionFailedError", "OTBRActionTimeoutError", "OTBRInvalidResponseError"}
    for item in failed:
        if item.get("name") != "detail":
            return False
        errors = item.get("attemptErrors")
        if not isinstance(errors, list) or not errors:
            return False
        if any(not isinstance(error, Mapping) or error.get("type") not in allowed for error in errors):
            return False
    return True


def reconcile_bound_rest_diagnostics(
    outcome: Mapping[str, Any],
    final_items: Sequence[Any],
    *,
    outcome_digest: str | None,
    diagnostics_digest: str | None,
    outcome_scope: object,
    diagnostics_scope: object,
    outcome_scope_digest: str | None,
    diagnostics_scope_digest: str | None,
    expected_network: str | None = None,
) -> dict[str, Any]:
    """Reconcile a cached run only when both original scope bindings agree."""
    digests = (outcome_digest, diagnostics_digest, outcome_scope_digest, diagnostics_scope_digest)
    verified = all(isinstance(value, str) and _SHA256.fullmatch(value) for value in digests)
    network = None
    if verified and isinstance(outcome_scope, Mapping) and isinstance(diagnostics_scope, Mapping):
        verified = (
            outcome_scope.get("provenance") == diagnostics_scope.get("provenance") == "observed"
            and outcome_scope.get("snapshotSha256") == outcome_digest
            and diagnostics_scope.get("snapshotSha256") == diagnostics_digest
        )
        if verified:
            try:
                network = canonical_ext_pan_id(outcome_scope.get("extPanId"))
                verified = network == canonical_ext_pan_id(diagnostics_scope.get("extPanId"))
                if expected_network is not None:
                    verified = verified and network == canonical_ext_pan_id(
                        expected_network.removeprefix("extpan:")
                    )
            except ValueError:
                verified = False
    else:
        verified = False
    provenance = {
        "bindingStatus": "verified" if verified else "unverified",
        "outcomeSha256": outcome_digest,
        "diagnosticsSha256": diagnostics_digest,
        "outcomeScopeSha256": outcome_scope_digest,
        "diagnosticsScopeSha256": diagnostics_scope_digest,
        "networkInstance": f"extpan:{network}" if verified and network else None,
    }
    effective = reconcile_rest_diagnostics(
        outcome,
        final_items,
        require_timestamps=True,
        allow_recovery=verified,
        provenance=provenance,
    )
    results = outcome.get("deviceResults")
    expansion = outcome.get("childrenExpansion")
    baseline_expansion = expansion is None or (
        isinstance(expansion, Mapping)
        and expansion.get("partial") is False
        and isinstance(expansion.get("issues"), list) and not expansion["issues"]
        and isinstance(expansion.get("results"), list)
        and all(
            isinstance(item, Mapping)
            and item.get("status") in {"completed", "covered"}
            and "effectiveStatus" not in item
            for item in expansion["results"]
        )
        and "originalPartial" not in expansion
    )
    if (
        "diagnosticRecovery" not in outcome
        and outcome.get("partial") is not True
        and isinstance(results, list)
        and bool(results)
        and all(
            isinstance(record, Mapping)
            and "originalStatus" not in record
            and _original_status(record) == "completed"
            for record in results
        )
        and isinstance(outcome.get("completedAt"), str)
        and baseline_expansion
    ):
        effective["partial"] = False
        effective["diagnosticRecovery"]["effectiveStatus"] = "completed"
    return effective


def validate_retained_recovery(
    recovery: object, *, sources: Sequence[Any], network_id: str,
) -> None:
    """Validate retained recovery provenance without consulting the current cache."""
    from td_const import (
        OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
        OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
    )

    if not isinstance(recovery, Mapping) or (
        recovery.get("contractVersion") != REST_DIAGNOSTIC_RECOVERY_VERSION
        or recovery.get("effectiveStatus") not in {"completed", "partial"}
        or not isinstance(recovery.get("summary"), Mapping)
        or not isinstance(recovery.get("devices"), list)
        or not isinstance(recovery.get("unresolved"), list)
        or not isinstance(recovery.get("provenance"), Mapping)
    ):
        raise ValueError("Invalid retained REST diagnostic recovery")
    summary, provenance = recovery["summary"], recovery["provenance"]
    keys = ("recoveredChildren", "recoveredRouters", "notProvidedDevices", "unavailableDevices")
    if any(type(summary.get(key)) is not int or summary[key] < 0 for key in keys):
        raise ValueError("Invalid retained REST diagnostic summary")
    by_name = {source.filename: source for source in sources}
    for filename, field in (
        (OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME, "diagnosticsSha256"),
        (OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME, "outcomeSha256"),
    ):
        if filename not in by_name or provenance.get(field) != by_name[filename].digest:
            raise ValueError("Retained REST recovery source digest mismatch")
    binding = provenance.get("bindingStatus")
    if binding not in {"verified", "unverified"}:
        raise ValueError("Invalid retained REST recovery binding")
    if binding == "verified":
        if provenance.get("networkInstance") != network_id or any(
            not isinstance(provenance.get(field), str)
            or not _SHA256.fullmatch(provenance[field])
            for field in ("outcomeScopeSha256", "diagnosticsScopeSha256")
        ):
            raise ValueError("Invalid retained REST recovery provenance")
    elif summary["recoveredChildren"] or summary["recoveredRouters"]:
        raise ValueError("Unverified REST evidence cannot establish recovery")


def _bound_diagnostic_lookup(
    items: Sequence[Any],
    results: Sequence[Any],
    expansion_results: Sequence[Any],
    saved: Sequence[Any],
    *,
    started: datetime | None,
    completed: datetime | None,
    require_timestamps: bool,
) -> Callable[[object], Mapping[str, Any] | None]:
    ids = Counter(_diagnostic_id(item) for item in items)
    saved_ids = Counter(_diagnostic_id(item) for item in saved)
    ext_counts = Counter(_usable_ext_address(_diagnostic_identity_view(item).get("extAddress")) for item in items)
    saved_ext_counts = Counter(_usable_ext_address(_diagnostic_identity_view(item).get("extAddress")) for item in saved)
    rloc_counts = Counter(_parse_rloc16(_diagnostic_identity_view(item).get("rloc16")) for item in items)
    saved_rloc_counts = Counter(_parse_rloc16(_diagnostic_identity_view(item).get("rloc16")) for item in saved)
    result_ids = Counter(
        record.get("diagnosticId")
        for record in [*results, *expansion_results]
        if isinstance(record, Mapping) and isinstance(record.get("diagnosticId"), str)
    )
    by_id = {_diagnostic_id(item): item for item in items}
    saved_by_id = {_diagnostic_id(item): item for item in saved}

    def bound_row(diagnostic_id: object) -> Mapping[str, Any] | None:
        if (
            not isinstance(diagnostic_id, str)
            or ids[diagnostic_id] != 1
            or saved_ids[diagnostic_id] != 1
            or result_ids[diagnostic_id] != 1
        ):
            return None
        row = _diagnostic_identity_view(by_id[diagnostic_id])
        final = _diagnostic_identity_view(saved_by_id[diagnostic_id])
        ext, rloc = _usable_ext_address(row.get("extAddress")), _parse_rloc16(row.get("rloc16"))
        if (
            ext is None or rloc is None
            or ext_counts[ext] != 1 or saved_ext_counts[ext] != 1
            or rloc_counts[rloc] != 1 or saved_rloc_counts[rloc] != 1
            or _usable_ext_address(final.get("extAddress")) != ext
            or _parse_rloc16(final.get("rloc16")) != rloc
        ):
            return None
        if any(name in row and (name not in final or not _contains(final[name], row[name])) for name in _KNOWN_FIELDS):
            return None
        if require_timestamps and (
            started is None or completed is None or completed < started
            or row.get("created") != final.get("created")
            or not _within_run(row.get("created"), started, completed)
        ):
            return None
        return row

    return bound_row


def qualified_router_tables(
    effective: Mapping[str, Any], final_items: Sequence[Any],
) -> list[dict[str, Any]]:
    """Return only same-run router tables backed by verified recovery evidence."""
    recovery = effective.get("diagnosticRecovery")
    provenance = recovery.get("provenance") if isinstance(recovery, Mapping) else None
    results, items = effective.get("deviceResults"), effective.get("items")
    expansion = effective.get("childrenExpansion")
    targets = expansion.get("results", []) if isinstance(expansion, Mapping) else []
    if (
        not isinstance(provenance, Mapping)
        or provenance.get("bindingStatus") != "verified"
        or not isinstance(results, list) or not isinstance(items, list)
        or not isinstance(targets, list)
    ):
        return []
    lookup = _bound_diagnostic_lookup(
        items, results, targets, final_items,
        started=_timestamp(effective.get("startedAt")),
        completed=_timestamp(effective.get("completedAt")),
        require_timestamps=True,
    )
    counts = Counter(
        _usable_ext_address(result.get("deviceId"))
        for result in results if isinstance(result, Mapping)
    )
    child_candidates: dict[int, set[str]] = {}
    child_records = [
        {
            "extAddress": result.get("deviceId"),
            "diagnosticId": result.get("diagnosticId"),
            "action": result.get("action"),
        }
        for result in results
        if isinstance(result, Mapping) and result.get("status") == "completed"
        and result.get("role") == "child"
    ]
    child_records.extend(
        detail for detail in recovery.get("devices", [])
        if isinstance(detail, Mapping) and detail.get("recoveryKind") in {"child-rloc", "child-detail"}
    )
    for child in child_records:
        ext, diagnostic_id = _usable_ext_address(child.get("extAddress")), child.get("diagnosticId")
        row = lookup(diagnostic_id)
        if ext is None or counts[ext] != 1 or row is None or not isinstance(diagnostic_id, str):
            continue
        rloc = _parse_rloc16(row.get("rloc16"))
        if (
            rloc is not None and rloc & _RLOC16_CHILD_MASK
            and _usable_ext_address(row.get("extAddress")) == ext
            and _action_matches(child.get("action"), diagnostic_id)
        ):
            child_candidates.setdefault(rloc, set()).add(ext)
    tables = []
    for result in results:
        if not isinstance(result, Mapping) or result.get("status") != "completed" or result.get("role") == "child":
            continue
        ext = _usable_ext_address(result.get("deviceId"))
        diagnostic_id = result.get("diagnosticId")
        row = lookup(diagnostic_id)
        if ext is None or counts[ext] != 1 or row is None or not isinstance(diagnostic_id, str):
            continue
        rloc, _ = _parse_router_rloc16(row.get("rloc16"))
        if (
            rloc is None
            or _usable_ext_address(row.get("extAddress")) != ext
            or ("rloc16" in result and _parse_rloc16(result["rloc16"]) != rloc)
            or not valid_child_table(row.get("childTable"))
            or not _action_matches(result.get("action"), diagnostic_id)
        ):
            continue
        if _original_status(result) != "completed" and not (
            isinstance(result.get("recovery"), Mapping)
            and result["recovery"].get("kind") == "router-fallback"
        ):
            continue
        resolved = {}
        for child in row["childTable"]:
            child_id = child["childId"]
            candidates = child_candidates.get(rloc | child_id, set())
            if (
                len(candidates) != 1
                or any(name in child and _usable_ext_address(child[name]) not in candidates
                       for name in ("extAddress", "extaddr"))
                or ("rloc16" in child and _parse_rloc16(child["rloc16"]) != rloc | child_id)
            ):
                continue
            resolved[child_id] = {
                "childId": child_id,
                "rloc16": _format_rloc16(rloc | child_id),
                "extAddress": next(iter(candidates)),
            }
        tables.append({
            "extAddress": ext,
            "rloc16": _format_rloc16(rloc),
            "diagnosticId": diagnostic_id,
            "created": row["created"],
            "childTable": deepcopy(row["childTable"]),
            "resolvedChildren": [resolved[child_id] for child_id in sorted(resolved)],
        })
    return sorted(tables, key=lambda item: (item["rloc16"], item["extAddress"]))


def unresolved_child_table_identities(effective: Mapping[str, Any] | None, final_items: Sequence[Any]) -> bool:
    """Do not treat an unidentified child-table entry as a named absence."""
    tables = qualified_router_tables(effective, final_items) if effective is not None else []
    resolved = {
        (table["extAddress"], child["childId"])
        for table in tables for child in table["resolvedChildren"]
    }
    for item in final_items:
        row = _diagnostic_identity_view(item)
        if "childTable" not in row:
            continue
        children = row.get("childTable")
        if not isinstance(children, list):
            return True
        if not children:
            continue
        parent = _usable_ext_address(row.get("extAddress"))
        if parent is None or not valid_child_table(children) or any(
            (parent, child["childId"]) not in resolved for child in children
        ):
            return True
    return False


def reconcile_rest_diagnostics(
    outcome: Mapping[str, Any],
    final_items: Sequence[Any] | None = None,
    *,
    require_timestamps: bool = False,
    allow_recovery: bool = True,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a new effective outcome; never rewrite or trust recovery metadata."""
    effective = deepcopy(dict(outcome))
    results = effective.get("deviceResults")
    items = effective.get("items")
    if not isinstance(results, list) or not isinstance(items, list):
        effective["partial"] = True
        effective["diagnosticRecovery"] = {
            "contractVersion": REST_DIAGNOSTIC_RECOVERY_VERSION,
            "effectiveStatus": "partial",
            "summary": {
                "recoveredChildren": 0,
                "recoveredRouters": 0,
                "notProvidedDevices": 0,
                "unavailableDevices": 0,
            },
            "devices": [],
            "unresolved": [{"reasonCode": "malformed-outcome"}],
            **({"provenance": dict(provenance)} if provenance is not None else {}),
        }
        return effective

    expansion = effective.get("childrenExpansion")
    expansion_results = expansion.get("results") if isinstance(expansion, dict) else []
    expansion_invalid = expansion is not None and not isinstance(expansion, dict)
    if not isinstance(expansion_results, list):
        expansion_results = []
        expansion_invalid = True
        allow_recovery = False

    for record in results:
        if isinstance(record, dict):
            record["status"] = _original_status(record)
            record.pop("originalStatus", None)
            record.pop("recovery", None)
    if isinstance(expansion, dict):
        for record in expansion_results:
            if isinstance(record, dict):
                record.pop("effectiveStatus", None)
        if "originalPartial" in expansion:
            expansion["partial"] = expansion.pop("originalPartial")
        expansion.pop("recoveredCount", None)

    started, completed = _timestamp(effective.get("startedAt")), _timestamp(effective.get("completedAt"))
    if require_timestamps and (started is None or completed is None or completed < started):
        allow_recovery = False
    saved = list(final_items) if final_items is not None else items
    bound_row = _bound_diagnostic_lookup(
        items, results, expansion_results, saved, started=started, completed=completed,
        require_timestamps=require_timestamps,
    )
    base_counts = Counter(_usable_ext_address(record.get("deviceId")) for record in results if isinstance(record, Mapping))
    target_counts = Counter(_parse_rloc16(record.get("rloc16")) for record in expansion_results if isinstance(record, Mapping))
    target_ext_counts = Counter(_usable_ext_address(record.get("extAddress")) for record in expansion_results if isinstance(record, Mapping))

    base_by_ext = {
        _usable_ext_address(record.get("deviceId")): record
        for record in results if isinstance(record, dict)
    }

    def parent_row(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
        parent_ext = _usable_ext_address(record.get("parentExtAddress"))
        parent_rloc, _ = _parse_router_rloc16(record.get("parentRloc16"))
        parent = base_by_ext.get(parent_ext)
        if parent_ext is None or parent_rloc is None or base_counts[parent_ext] != 1 or parent is None:
            return None
        if parent.get("role") == "child":
            return None
        parent_id = parent.get("diagnosticId")
        row = bound_row(parent_id)
        if (
            row is None or not isinstance(parent_id, str)
            or _usable_ext_address(row.get("extAddress")) != parent_ext
            or _parse_rloc16(row.get("rloc16")) != parent_rloc
            or not valid_child_table(row.get("childTable"))
            or not _action_matches(parent.get("action"), parent_id)
        ):
            return None
        status = _original_status(parent)
        if status != "completed" and not (status == "partial" and _router_fallback(parent)):
            return None
        return row

    def target_row(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
        rloc = _parse_rloc16(record.get("rloc16"))
        ext = _usable_ext_address(record.get("extAddress"))
        parent_rloc, _ = _parse_router_rloc16(record.get("parentRloc16"))
        child_id = _parse_child_id(record.get("childId"))
        diagnostic_id = record.get("diagnosticId")
        if (
            rloc is None or ext is None or parent_rloc is None or child_id is None
            or target_counts[rloc] != 1 or target_ext_counts[ext] != 1
            or _child_rloc_destination(parent_rloc, child_id) != (rloc, record.get("destination"))
            or record.get("destinationType") != "rloc"
            or type(record.get("attempts")) is not int or record["attempts"] < 1
        ):
            return None
        parent = parent_row(record)
        row = bound_row(diagnostic_id)
        if (
            parent is None or row is None or not isinstance(diagnostic_id, str)
            or not any(entry.get("childId") == child_id for entry in parent["childTable"])
            or _usable_ext_address(row.get("extAddress")) != ext
            or _parse_rloc16(row.get("rloc16")) != rloc
        ):
            return None
        issues = expansion.get("issues", []) if isinstance(expansion, dict) else []
        if not isinstance(issues, list):
            return None
        for issue in issues:
            if not isinstance(issue, Mapping):
                return None
            issue_ext = _usable_ext_address(issue.get("parentExtAddress"))
            issue_rloc = _parse_rloc16(issue.get("parentRloc16"))
            issue_target = _parse_rloc16(issue.get("rloc16"))
            if issue_ext == _usable_ext_address(record.get("parentExtAddress")) or issue_rloc == parent_rloc or issue_target == rloc:
                return None
            if issue_ext is None and issue_rloc is None and issue_target is None:
                return None
        return row

    recovered_expansion: set[int] = set()
    detail_rows: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, str]] = []

    def add_detail(record: Mapping[str, Any], row: Mapping[str, Any], kind: str, original: object) -> None:
        ext = _usable_ext_address(row.get("extAddress"))
        rloc = _parse_rloc16(row.get("rloc16"))
        diagnostic_id = record.get("diagnosticId")
        if ext is None or rloc is None or not isinstance(diagnostic_id, str):
            return
        detail = {
            "extAddress": ext,
            "rloc16": _format_rloc16(rloc),
            "role": record.get("role", "child"),
            "recoveryKind": kind,
            "diagnosticId": diagnostic_id,
            "originalStatus": original,
            "fields": _field_availability(record, row, diagnostic_id),
        }
        for key in ("parentExtAddress", "parentRloc16", "childId"):
            if key in record:
                detail[key] = record[key]
        detail_rows[ext] = detail

    if allow_recovery:
        for index, record in enumerate(expansion_results):
            if not isinstance(record, dict) or record.get("status") != "partial":
                continue
            row = target_row(record)
            diagnostic_id = record.get("diagnosticId")
            if row is not None and isinstance(diagnostic_id, str) and _detail_gap(record, diagnostic_id):
                record["effectiveStatus"] = "completed"
                recovered_expansion.add(index)
                add_detail(record, row, "child-detail", "partial")

        for record in results:
            if not isinstance(record, dict):
                continue
            status = record.get("status")
            ext = _usable_ext_address(record.get("deviceId"))
            if status == "completed" or ext is None or base_counts[ext] != 1:
                continue
            row = None
            recovery_record = record
            kind = None
            if record.get("role") == "child" and status == "skipped" and record.get("skipReasonCode") == "unresolved_mesh_local_iid":
                candidates = [
                    (index, target) for index, target in enumerate(expansion_results)
                    if isinstance(target, dict) and _usable_ext_address(target.get("extAddress")) == ext
                ]
                if len(candidates) == 1:
                    index, target = candidates[0]
                    target_status = target.get("effectiveStatus", target.get("status"))
                    if target_status == "completed":
                        row = target_row(target)
                        if row is not None:
                            recovered_expansion.add(index)
                            recovery_record = target
                            kind = "child-rloc"
            elif record.get("role") == "child" and status == "partial":
                diagnostic_id = record.get("diagnosticId")
                row = bound_row(diagnostic_id)
                if (
                    row is not None and isinstance(diagnostic_id, str)
                    and _usable_ext_address(row.get("extAddress")) == ext
                    and _parse_rloc16(row.get("rloc16")) & _RLOC16_CHILD_MASK
                    and _detail_gap(record, diagnostic_id)
                ):
                    kind = "child-detail"
            elif status == "partial" and _router_fallback(record):
                diagnostic_id = record.get("diagnosticId")
                row = bound_row(diagnostic_id)
                if (
                    row is not None and isinstance(diagnostic_id, str)
                    and _usable_ext_address(row.get("extAddress")) == ext
                    and _parse_router_rloc16(row.get("rloc16"))[0] is not None
                    and valid_child_table(row.get("childTable"))
                    and _action_matches(record.get("action"), diagnostic_id)
                ):
                    kind = "router-fallback"
            recovered_rloc = _parse_rloc16(row.get("rloc16")) if row is not None else None
            if kind is not None and row is not None and recovered_rloc is not None:
                record["originalStatus"] = status
                record["status"] = "completed"
                record["recovery"] = {
                    "contractVersion": REST_DIAGNOSTIC_RECOVERY_VERSION,
                    "kind": kind,
                    "diagnosticId": recovery_record["diagnosticId"],
                    "extAddress": ext,
                    "rloc16": _format_rloc16(recovered_rloc),
                    **{key: recovery_record[key] for key in ("parentExtAddress", "parentRloc16", "childId") if key in recovery_record},
                }
                add_detail(recovery_record, row, kind, status)

    for record in results:
        if not isinstance(record, dict):
            unresolved.append({"reasonCode": "malformed-target"})
            continue
        if record.get("status") != "completed":
            unresolved.append({
                "deviceId": str(record.get("deviceId") or ""),
                "reasonCode": str(record.get("skipReasonCode") or record.get("reasonCode") or "incomplete-target"),
            })
        if allow_recovery and _usable_ext_address(record.get("deviceId")) not in detail_rows:
            row = bound_row(record.get("diagnosticId"))
            ext = _usable_ext_address(record.get("deviceId"))
            if row is not None and ext is not None and base_counts[ext] == 1 and _usable_ext_address(row.get("extAddress")) == ext:
                add_detail(record, row, "none", _original_status(record))

    if isinstance(expansion, dict):
        for record in expansion_results:
            if not isinstance(record, Mapping):
                unresolved.append({"reasonCode": "malformed-expansion-target"})
                continue
            status = record.get("effectiveStatus", record.get("status"))
            if status not in {"completed", "covered"}:
                unresolved.append({
                    "deviceId": str(record.get("extAddress") or record.get("destination") or ""),
                    "reasonCode": str(record.get("reasonCode") or "incomplete-expansion-target"),
                })
            ext = _usable_ext_address(record.get("extAddress"))
            if allow_recovery and status == "completed" and ext not in detail_rows:
                row = target_row(record)
                if row is not None:
                    add_detail(record, row, "none", record.get("status"))
        original_partial = expansion.get("partial") is True
        issues = expansion.get("issues")
        if isinstance(issues, list):
            for issue in issues:
                unresolved.append({
                    "reasonCode": str(issue.get("code") or "expansion-issue")
                    if isinstance(issue, Mapping) else "malformed-expansion-issue",
                })
        original_target_partial = any(
            not isinstance(item, Mapping) or item.get("status") not in {"completed", "covered"}
            for item in expansion_results
        )
        expansion_partial = (
            expansion_invalid
            or type(expansion.get("partial")) is not bool
            or not isinstance(issues, list) or bool(issues)
            or (original_partial and not original_target_partial and not issues)
            or any(not isinstance(item, Mapping) or item.get("effectiveStatus", item.get("status")) not in {"completed", "covered"} for item in expansion_results)
        )
        if expansion_partial != original_partial:
            expansion["originalPartial"] = original_partial
        expansion["partial"] = expansion_partial
        expansion["recoveredCount"] = len(recovered_expansion)
    else:
        expansion_partial = expansion_invalid

    original_incomplete = any(
        not isinstance(item, Mapping) or _original_status(item) != "completed" for item in results
    ) or (isinstance(expansion, dict) and expansion.get("originalPartial", expansion.get("partial")) is True)
    unexplained_partial = effective.get("partial") is True and not original_incomplete
    effective["partial"] = (
        not results or unexplained_partial or expansion_partial
        or any(not isinstance(item, Mapping) or item.get("status") != "completed" for item in results)
    )
    details = sorted(detail_rows.values(), key=lambda item: (item["extAddress"], item["rloc16"]))
    recovered_children = sum(item["recoveryKind"] in {"child-rloc", "child-detail"} for item in details)
    recovered_routers = sum(item["recoveryKind"] == "router-fallback" for item in details)
    summary = {
        "recoveredChildren": recovered_children,
        "recoveredRouters": recovered_routers,
        "notProvidedDevices": sum(any(field["availability"] == "not-provided" for field in item["fields"].values()) for item in details),
        "unavailableDevices": sum(any(field["availability"] == "unavailable" for field in item["fields"].values()) for item in details),
    }
    if not allow_recovery:
        unresolved.append({"reasonCode": "unverified-recovery-evidence"})
    effective["diagnosticRecovery"] = {
        "contractVersion": REST_DIAGNOSTIC_RECOVERY_VERSION,
        "effectiveStatus": "partial" if effective["partial"] else "completed",
        "summary": summary,
        "devices": details,
        "unresolved": sorted(unresolved, key=lambda item: (item.get("deviceId", ""), item["reasonCode"])),
        **({"provenance": dict(provenance)} if provenance is not None else {}),
    }
    return effective
