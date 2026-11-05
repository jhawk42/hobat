"""Pure evidence rules for extended-address REST mesh responsiveness."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from td_network_identity import canonical_ext_pan_id


RESPONSIVENESS_VERSION = "rest-mesh-responsiveness-v1"
QUALIFICATION_VERSION = "rest-mesh-qualification-v1"
ORIGIN = "otbr-restapi-network-diagnostics"
POLICY = {
    "types": ["extAddress", "rloc16", "mode", "ipv6Addresses"],
    "destinationType": "extended", "maxRequestsPerTarget": 1,
    "taskTimeoutSeconds": 15, "pollIntervalSeconds": 2,
    "pollTimeoutSeconds": 20, "timestampPrecisionSeconds": 1,
    "witnessMaxAgeSeconds": 7200,
}
MESH_TYPES = frozenset({"children", "childIpv6Addresses", "routerNeighbors"})


def identity_view(value: object) -> dict:
    if not isinstance(value, Mapping):
        return {}
    if isinstance(value.get("data"), Mapping):
        return identity_view(value["data"])
    attributes = value.get("attributes")
    return {**attributes, **{key: value[key] for key in ("id", "type", "relationships") if key in value}} if isinstance(attributes, Mapping) else dict(value)


def extended_address(value: object) -> str | None:
    return value.lower() if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{16}", value) and int(value, 16) else None


def timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def scope_identity(value: object) -> str | None:
    view = identity_view(value)
    observed = [view[key] for key in ("extPanId", "extendedPanId", "ExtendedPanId") if key in view]
    try:
        identities = {canonical_ext_pan_id(item) for item in observed}
    except (ValueError, TypeError):
        return None
    return next(iter(identities)) if len(identities) == 1 else None


def classify_mesh_probe_eligibility(record: object, destination_type: str = "extended") -> str | None:
    if destination_type != "extended":
        return "unsupported-destination-type"
    if not isinstance(record, Mapping) or extended_address(record.get("deviceId")) is None:
        return "missing-target-identity"
    if record.get("meshCoverage") or record.get("diagnosticIds") or record.get("successfulTypes"):
        return "partial-table-returned"
    errors = record.get("attemptErrors")
    if record.get("status") != "failed" or not isinstance(errors, list) or not errors:
        return "ineligible-failure"
    for error in errors:
        if not isinstance(error, Mapping) or not isinstance(error.get("actionId"), str) or not error["actionId"]:
            return "ineligible-failure"
        if error.get("type") == "OTBRActionTimeoutError":
            continue
        if error.get("type") != "OTBRActionFailedError" or error.get("actionStatus") not in ("stopped", "failed"):
            return "ineligible-failure"
    return None


def select_router_identity(device_id: str, roster: Sequence[object]) -> tuple[dict | None, str | None]:
    rows = [identity_view(item) for item in roster]
    matches = [row for row in rows if row.get("id") == device_id]
    if len(matches) != 1:
        return None, "ambiguous-target"
    row = matches[0]
    address = extended_address(row.get("extAddress"))
    if address is None or address != extended_address(device_id):
        return None, "missing-target-identity"
    if sum(extended_address(item.get("extAddress")) == address for item in rows) != 1:
        return None, "ambiguous-target"
    if row.get("role") != "router":
        return None, "target-identity-changed"
    return {"deviceId": device_id, "extAddress": address, "destination": device_id, "destinationType": "extended", "role": "router"}, None


def select_child_witness(address: str, tables: Sequence[dict], started_at: str) -> tuple[dict | None, str | None]:
    matches = [table for table in tables if extended_address(table.get("extAddress")) == address]
    if len(matches) != 1:
        return None, "witness-missing" if not matches else "ambiguous-target"
    table = matches[0]
    created, started = timestamp(table.get("created")), timestamp(started_at)
    if created is None or started is None or not 0 <= (started - created).total_seconds() <= POLICY["witnessMaxAgeSeconds"]:
        return None, "witness-stale"
    children, resolved = table.get("childTable"), table.get("resolvedChildren")
    if not isinstance(children, list) or not isinstance(resolved, list) or len(children) != len(resolved):
        return None, "children-uncovered"
    return {"diagnosticId": table["diagnosticId"], "created": table["created"], "extAddress": address}, None


def action_result_id(action: object) -> str | None:
    relationships = identity_view(action).get("relationships")
    result = relationships.get("result") if isinstance(relationships, Mapping) else None
    data = result.get("data") if isinstance(result, Mapping) else None
    return data.get("id") if isinstance(data, Mapping) and isinstance(data.get("id"), str) else None


def witness_identifiers(value: object) -> list[str]:
    identifiers = set()
    def visit(item):
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if key in ("id", "diagnosticId", "actionId") and isinstance(nested, str) and nested:
                    identifiers.add(nested)
                if key == "diagnosticIds" and isinstance(nested, list):
                    identifiers.update(identifier for identifier in nested if isinstance(identifier, str) and identifier)
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
    visit(value)
    return sorted(identifiers)


def validate_diagnostic_response(check: object, identity: Mapping, used_ids: Sequence[str] = ()) -> str | None:
    if not isinstance(identity, Mapping) or not isinstance(identity.get("destination"), str) or extended_address(identity.get("extAddress")) is None:
        return "missing-target-identity"
    if not isinstance(check, Mapping) or check.get("status") != "response":
        return "diagnostic-no-response"
    request = check.get("request")
    expected = {"destination": identity["destination"], "destinationType": "extended", "types": POLICY["types"], "timeout": 15}
    if request != expected:
        return "diagnostic-invalid-evidence"
    started, completed = timestamp(check.get("startedAt")), timestamp(check.get("completedAt"))
    duration = check.get("elapsedSeconds")
    if started is None or completed is None or completed < started or type(duration) not in {float, int} or not math.isfinite(duration) or duration < 0:
        return "diagnostic-invalid-evidence"
    action, diagnostic = identity_view(check.get("action")), identity_view(check.get("diagnostic"))
    action_id, diagnostic_id = action.get("id"), diagnostic.get("id")
    if action.get("status") != "completed" or not isinstance(action_id, str) or not action_id:
        return "diagnostic-invalid-evidence"
    if not isinstance(diagnostic_id, str) or not diagnostic_id or action_result_id(action) != diagnostic_id:
        return "diagnostic-result-missing"
    if action_id == diagnostic_id or action_id in used_ids or diagnostic_id in used_ids:
        return "diagnostic-result-reused"
    if action.get("type") not in (None, "getNetworkDiagnosticTask") or any(key in action and action[key] != value for key, value in expected.items()):
        return "diagnostic-invalid-evidence"
    if diagnostic.get("type") != "networkDiagnostics" or extended_address(diagnostic.get("extAddress")) != identity["extAddress"]:
        return "diagnostic-identity-mismatch"
    created = timestamp(diagnostic.get("created"))
    if created is None or not started - timedelta(seconds=1) <= created <= completed + timedelta(seconds=1):
        return "diagnostic-response-stale"
    return None


def sanitize_context(context: object) -> tuple[dict, dict]:
    value = context if isinstance(context, Mapping) else {}
    action, diagnostic = identity_view(value.get("action")), identity_view(value.get("item"))
    action_fields = ("id", "type", "status", "destination", "destinationType", "types", "timeout")
    retained = {key: deepcopy(action[key]) for key in action_fields if key in action}
    result_id = action_result_id(action)
    if result_id:
        retained["relationships"] = {"result": {"data": {"type": "diagnostics", "id": result_id}}}
    return retained, {key: deepcopy(diagnostic[key]) for key in ("id", "type", "created", "extAddress", "rloc16", "mode", "ipv6Addresses") if key in diagnostic}


def qualify_rest_mesh_outcome(outcome: Mapping, final_items: Sequence[object], tables: Sequence[dict], bindings: Mapping, network: str | None, witness_ids: Sequence[str] = ()) -> dict:
    evidence = outcome.get("meshResponsiveness")
    raw_results = outcome.get("deviceResults")
    results_ok = isinstance(raw_results, list) and bool(raw_results) and all(isinstance(record, Mapping) for record in raw_results)
    results = [record if isinstance(record, Mapping) else {} for record in raw_results] if isinstance(raw_results, list) else []
    evidence = evidence if isinstance(evidence, Mapping) else {}
    targets = evidence.get("targets", [])
    targets = targets if isinstance(targets, list) else []
    target_shape_ok = all(isinstance(target, Mapping) and isinstance(target.get("identity"), Mapping) and isinstance(target.get("check"), Mapping) for target in targets)
    targets = [target for target in targets if isinstance(target, Mapping) and isinstance(target.get("identity"), Mapping) and isinstance(target.get("check"), Mapping)]
    target_ids = [target["identity"].get("deviceId") for target in targets]
    target_shape_ok = target_shape_ok and all(isinstance(identifier, str) for identifier in target_ids) and len(set(identifier for identifier in target_ids if isinstance(identifier, str))) == len(target_ids)
    target_shape_ok = target_shape_ok and all(any(record.get("deviceId") == identifier and record.get("status") != "completed" for record in results) for identifier in target_ids)
    before, after = evidence.get("scopeBefore"), evidence.get("scopeAfter")
    scope = scope_identity(before)
    scope_ok = scope is not None and scope == scope_identity(after) and network in {scope, "extpan:" + scope.removeprefix("0x")}
    policy = evidence.get("policy")
    policy_ok = isinstance(policy, Mapping) and policy == POLICY and all(type(policy[key]) is type(value) for key, value in POLICY.items())
    contract_ok = evidence.get("contractVersion") == RESPONSIVENESS_VERSION and evidence.get("enabled") is True and evidence.get("origin") == ORIGIN and policy_ok and target_shape_ok
    bindings_ok = evidence.get("witnessBindings") == bindings and bool(bindings) and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in bindings.values())
    used_ids = list(witness_ids)
    for item in final_items:
        used_ids.append(identity_view(item).get("id"))
    for table in tables:
        used_ids.append(table.get("diagnosticId"))
    for record in results:
        identifiers, errors = record.get("diagnosticIds"), record.get("attemptErrors")
        used_ids.extend(identifiers if isinstance(identifiers, list) else [])
        used_ids.extend(error.get("actionId") for error in (errors if isinstance(errors, list) else []) if isinstance(error, Mapping))
    checks = [target.get("check", {}) for target in targets if isinstance(target, Mapping)]
    new_ids = Counter(identifier for check in checks for identifier in (identity_view(check.get("action")).get("id"), identity_view(check.get("diagnostic")).get("id")) if isinstance(identifier, str) and identifier)
    used_ids.extend(identifier for identifier, count in new_ids.items() if count > 1)
    result_counts = Counter(extended_address(record.get("deviceId")) for record in results)
    item_rows = [identity_view(item) for item in final_items]
    item_counts = Counter(row["id"] for row in item_rows if isinstance(row.get("id"), str))
    items_by_id = {row["id"]: row for row in item_rows if isinstance(row.get("id"), str) and item_counts[row["id"]] == 1}
    qualified = []
    for record in results:
        device_id = record.get("deviceId")
        classification, reason = "unanswered", "ineligible-failure"
        matching = [target for target in targets if isinstance(target, Mapping) and target.get("identity", {}).get("deviceId") == device_id]
        target = matching[0] if len(matching) == 1 else {}
        identity, check = target.get("identity", {}), target.get("check", {})
        attempts, identifiers = record.get("attemptedTypes"), record.get("diagnosticIds")
        requested = attempts[0] if isinstance(attempts, list) and attempts and isinstance(attempts[0], list) else []
        requested_ok = bool(requested) and all(isinstance(field, str) and field in MESH_TYPES for field in requested)
        ids_ok = isinstance(identifiers, list) and bool(identifiers) and all(isinstance(identifier, str) and identifier in items_by_id for identifier in identifiers)
        rows = [items_by_id[identifier] for identifier in identifiers] if ids_ok else []
        answered = (record.get("status") == "completed" and requested_ok and ids_ok
                    and all(extended_address(row.get("extAddress")) == extended_address(device_id) for row in rows)
                    and all(any(isinstance(row.get(field), list) and all(isinstance(entry, Mapping) for entry in row[field]) for row in rows) for field in requested))
        if not results_ok or extended_address(device_id) is None or result_counts[extended_address(device_id)] != 1:
            reason = "ambiguous-target"
        elif answered:
            classification, reason = "answered", "answered"
        else:
            reason = classify_mesh_probe_eligibility(record)
            if reason is None and not contract_ok:
                reason = "unsupported-contract"
            if reason is None and not scope_ok:
                reason = "scope-changed" if scope else "scope-unavailable"
            if reason is None and not bindings_ok:
                reason = "witness-binding-mismatch"
            if reason is None and (identity.get("destinationType") != "extended" or identity.get("destination") != device_id or identity.get("extAddress") != extended_address(device_id) or identity.get("role") != "router"):
                reason = "missing-target-identity"
            if reason is None:
                reason = validate_diagnostic_response(check, identity, used_ids)
            if reason is None:
                witness, reason = select_child_witness(identity["extAddress"], tables, check["startedAt"])
                if witness != target.get("witness"):
                    reason = reason or "witness-identity-mismatch"
            if reason is None:
                mesh_end = timestamp(outcome.get("completedAt"))
                check_start, check_end = timestamp(check.get("startedAt")), timestamp(check.get("completedAt"))
                scope_start, scope_end = timestamp(identity_view(before).get("receivedAt")), timestamp(identity_view(after).get("requestedAt"))
                mesh_start = timestamp(outcome.get("startedAt"))
                before_start, after_end = timestamp(identity_view(before).get("requestedAt")), timestamp(identity_view(after).get("receivedAt"))
                if None in (before_start, scope_start, mesh_start, mesh_end, check_start, check_end, scope_end, after_end) or not before_start <= scope_start <= mesh_start <= mesh_end <= check_start <= check_end <= scope_end <= after_end:
                    reason = "diagnostic-invalid-evidence"
            if reason is None:
                classification, reason = "not-provided", "not-provided-qualified"
        qualified.append({"deviceId": device_id, "extAddress": extended_address(device_id), "destination": identity.get("destination", device_id), "destinationType": identity.get("destinationType", "extended"), "rawStatus": record.get("status"), "classification": classification, "reasonCode": reason, "checkStatus": check.get("status", "not-attempted"), "childCoverage": "qualified" if classification == "not-provided" else "not-required" if classification == "answered" else "unavailable", "witness": deepcopy(target.get("witness")) if classification == "not-provided" else None})
    counts = {"selected": len(results), "answered": sum(item["classification"] == "answered" for item in qualified), "notProvided": sum(item["classification"] == "not-provided" for item in qualified), "unanswered": sum(item["classification"] == "unanswered" for item in qualified), "probed": sum(check.get("status") != "not-attempted" for check in checks)}
    complete = (counts["selected"] > 0 and counts["answered"] > 0 and counts["unanswered"] == 0
                and outcome.get("queriedCount") == counts["selected"]
                and (outcome.get("partial") is False or counts["notProvided"] > 0))
    return {"contractVersion": QUALIFICATION_VERSION, "counts": counts, "targets": qualified, "complete": complete, "provenance": {"witnessBindings": dict(bindings), "responsivenessContract": evidence.get("contractVersion"), "networkInstance": network, "policy": deepcopy(policy)}}