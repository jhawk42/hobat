"""Read-only views over already reconciled REST collector evidence."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import replace

from td_collection_outcomes import CollectionAttempt, CollectionOutcome
from td_restapi_diagnostic_recovery import REST_DIAGNOSTIC_RECOVERY_VERSION, diagnostic_items
from td_restapi_mesh_evidence import QUALIFICATION_VERSION, RESPONSIVENESS_VERSION, extended_address, identity_view


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _records(value: object) -> list:
    return value if isinstance(value, list) else []


def _target(record: Mapping, key: str, index: int) -> str:
    value = record.get(key)
    return value if isinstance(value, str) and value else f"unavailable-{index + 1}"


def _action_success(record: Mapping) -> bool:
    action, diagnostic_id = record.get("action"), record.get("diagnosticId")
    if not isinstance(action, Mapping) or action.get("status") != "completed":
        return False
    if not isinstance(diagnostic_id, str) or not diagnostic_id:
        return False
    relationships = action.get("relationships")
    if relationships is None:
        return True
    if not isinstance(relationships, Mapping):
        return False
    result = relationships.get("result")
    data = result.get("data") if isinstance(result, Mapping) else None
    return isinstance(data, Mapping) and data.get("id") == diagnostic_id


def _matched_action(record: Mapping) -> bool:
    if not _action_success(record):
        return False
    action = record["action"]
    relationships = action.get("relationships")
    result = relationships.get("result") if isinstance(relationships, Mapping) else None
    data = result.get("data") if isinstance(result, Mapping) else None
    return isinstance(data, Mapping) and data.get("id") == record["diagnosticId"]


def _attempts(record: Mapping) -> tuple[CollectionAttempt, ...]:
    """Translate only complete, ordered attempt evidence."""
    passes = record.get("passes")
    if isinstance(passes, list) and passes:
        groups = passes
        is_pass = True
    else:
        groups = [record]
        is_pass = False
    attempts: list[CollectionAttempt] = []
    previous_types: object = None
    for group in groups:
        if not isinstance(group, Mapping):
            return ()
        errors, count = group.get("attemptErrors"), group.get("attempts")
        if not isinstance(errors, list) or type(count) is not int or count < 1:
            return ()
        if any(not isinstance(error, Mapping) or not isinstance(error.get("type"), str) for error in errors):
            return ()
        raw_status = group.get("status")
        if raw_status == "failed":
            success = False
        elif raw_status in ("completed", "partial") and _action_success(group):
            success = True
        else:
            return ()
        if len(errors) + int(success) != count:
            return ()
        types = group.get("attemptedTypes")
        if not is_pass and (
            not isinstance(types, list) or len(types) != count
            or any(not isinstance(item, list) for item in types)
        ):
            return ()
        for index in range(count):
            if is_pass:
                current_types = group.get("requestedTypes")
                if not isinstance(current_types, list):
                    return ()
            else:
                current_types = types[index]
            if not attempts:
                kind = "initial"
            elif (not is_pass or index > 0) and current_types == previous_types:
                kind = "same_set_retry"
            elif is_pass and group.get("name") == "detail":
                kind = "child_detail"
            elif not is_pass:
                kind = "request_fallback"
            else:
                kind = "unknown"
            error = errors[index] if index < len(errors) else None
            ref = _text(error.get("actionId")) if error is not None else _text(group.get("diagnosticId"))
            attempts.append(CollectionAttempt(kind, "failed" if error is not None else "completed", ref))
            previous_types = current_types
    return tuple(attempts)


def _coverage(detail: Mapping, record: Mapping) -> str:
    fields = detail.get("fields")
    if not isinstance(fields, Mapping) or not fields:
        return "unknown"
    passes = record.get("passes")
    if isinstance(passes, list) and passes:
        if any(not isinstance(item, Mapping) or not isinstance(item.get("requestedTypes"), list)
               or not item["requestedTypes"] for item in passes):
            return "unknown"
        requested = [name for item in passes for name in item["requestedTypes"]]
    else:
        requested = record.get("attemptedTypes")
        requested = requested[0] if isinstance(requested, list) and requested else None
    if (not isinstance(requested, list) or not requested
            or any(not isinstance(name, str) or name not in fields for name in requested)):
        return "unknown"
    values = []
    for name in requested:
        item = fields[name]
        if not isinstance(item, Mapping):
            return "unknown"
        value = item.get("availability")
        if value not in ("present", "not-provided", "unavailable"):
            return "unknown"
        values.append(value)
    if not values:
        return "unknown"
    if all(value == "present" for value in values):
        return "complete"
    if "present" in values:
        return "partial"
    if all(value == "not-provided" for value in values):
        return "absent"
    return "unknown"


def _view(record: object, *, command: str, stage: str, target_key: str, index: int,
          detail: Mapping | None = None, detail_valid: bool = False) -> CollectionOutcome:
    row = record if isinstance(record, Mapping) else {}
    initial = _text(row.get("originalStatus", row.get("status")))
    effective = _text(row.get("effectiveStatus", row.get("status")))
    attempts = _attempts(row)
    state, kind = "unknown", "unknown"
    recovery = row.get("recovery")
    kinds = {"child-rloc": "child_rloc", "child-detail": "child_detail", "router-fallback": "request_fallback"}
    if (detail_valid and isinstance(recovery, Mapping)
            and recovery.get("contractVersion") == REST_DIAGNOSTIC_RECOVERY_VERSION
            and detail is not None
            and recovery.get("kind") == detail.get("recoveryKind")
            and isinstance(recovery.get("kind"), str) and recovery.get("kind") in kinds
            and extended_address(recovery.get("extAddress")) == extended_address(row.get("deviceId"))
            and isinstance(recovery.get("diagnosticId"), str)
            and recovery["diagnosticId"] == detail.get("diagnosticId")
            and effective == "completed"):
        state, kind = "recovered", kinds[recovery["kind"]]
    elif attempts and attempts[-1].kind in ("same_set_retry", "request_fallback"):
        kind = attempts[-1].kind
        state = "recovered" if attempts[-1].status == "completed" else "attempted"
    return CollectionOutcome(
        source="otbr-restapi", command=command, stage=stage,
        target=_target(row, target_key, index),
        initial_status=initial, effective_status=effective,
        original_reason_code=_text(row.get("skipReasonCode") or row.get("reasonCode")),
        coverage=_coverage(detail, row) if detail_valid and detail is not None else "unknown",
        recovery_state=state, recovery_kind=kind, attempts=attempts,
    )


def _observed_diagnostic(record: object, items: list, identity_key: str, counts: Counter) -> bool:
    if not isinstance(record, Mapping) or not _matched_action(record):
        return False
    address = extended_address(record.get(identity_key))
    if address is None or counts[address] != 1:
        return False
    diagnostic_id = record["diagnosticId"]
    matches = [identity_view(item) for item in items if identity_view(item).get("id") == diagnostic_id]
    return len(matches) == 1 and extended_address(matches[0].get("extAddress")) == address


def diagnostic_outcome_views(
    outcome: object, *, command: str = "diagnostics fetch-all", stage_prefix: str = "",
) -> dict[str, tuple[CollectionOutcome, ...]]:
    """Project base, expansion and uniquely correlated effective populations."""
    value = outcome if isinstance(outcome, Mapping) else {}
    base = _records(value.get("deviceResults"))
    expansion = value.get("childrenExpansion")
    expanded = _records(expansion.get("results")) if isinstance(expansion, Mapping) else []
    items = diagnostic_items(value.get("items"))
    expansion_counts = Counter(extended_address(item.get("extAddress")) for item in expanded if isinstance(item, Mapping))
    recovery = value.get("diagnosticRecovery")
    details = _records(recovery.get("devices")) if isinstance(recovery, Mapping) else []
    base_counts = Counter(extended_address(item.get("deviceId")) for item in base if isinstance(item, Mapping))
    detail_counts = Counter(extended_address(item.get("extAddress")) for item in details if isinstance(item, Mapping))
    unique_details = {
        extended_address(item.get("extAddress")): item for item in details
        if isinstance(item, Mapping) and extended_address(item.get("extAddress")) is not None
        and detail_counts[extended_address(item.get("extAddress"))] == 1
    }
    valid_contract = isinstance(recovery, Mapping) and recovery.get("contractVersion") == REST_DIAGNOSTIC_RECOVERY_VERSION
    def diagnostic_view(item: object, stage: str, target_key: str, index: int,
                        identity_key: str, counts: Counter, detail: Mapping | None = None) -> CollectionOutcome:
        view = _view(item, command=command, stage=stage, target_key=target_key, index=index,
                     detail=detail, detail_valid=valid_contract)
        if _observed_diagnostic(item, items, identity_key, counts):
            view = replace(view, response="observed", response_evidence="direct")
        return view

    initial = tuple(diagnostic_view(item, stage_prefix + "initial", "deviceId", index, "deviceId", base_counts)
                    for index, item in enumerate(base))
    expansion_views = tuple(diagnostic_view(item, stage_prefix + "expansion", "destination", index, "extAddress", expansion_counts)
                            for index, item in enumerate(expanded))
    effective = []
    for index, item in enumerate(base):
        if not isinstance(item, Mapping):
            continue
        address = extended_address(item.get("deviceId"))
        detail = unique_details.get(address)
        if address is None or base_counts[address] != 1 or detail is None:
            continue
        effective.append(diagnostic_view(item, stage_prefix + "effective", "deviceId", index,
                                         "deviceId", base_counts, detail))
    return {"initial": initial, "expansion": expansion_views, "effective": tuple(effective)}


def mesh_outcome_views(
    outcome: object, *, command: str = "mesh-diagnostics fetch-all", stage: str = "router",
    qualification: object = None,
) -> tuple[CollectionOutcome, ...]:
    """Project mesh records without independently qualifying table evidence."""
    value = outcome if isinstance(outcome, Mapping) else {}
    base = _records(value.get("deviceResults"))
    qualified = qualification if isinstance(qualification, Mapping) else {}
    targets = _records(qualified.get("targets")) if qualified.get("contractVersion") == QUALIFICATION_VERSION else []
    base_counts = Counter(extended_address(item.get("deviceId")) for item in base if isinstance(item, Mapping))
    target_counts = Counter(extended_address(item.get("deviceId")) for item in targets if isinstance(item, Mapping))
    by_address = {extended_address(item.get("deviceId")): item for item in targets if isinstance(item, Mapping)}
    views = []
    for index, item in enumerate(base):
        row = item if isinstance(item, Mapping) else {}
        address = extended_address(row.get("deviceId"))
        target = by_address.get(address)
        table_class = "unavailable"
        reason = _text(row.get("skipReasonCode") or row.get("reasonCode"))
        response, response_evidence, coverage = "unknown", "unknown", "unknown"
        if (address is not None and base_counts[address] == target_counts[address] == 1
                and isinstance(target, Mapping)
                and extended_address(target.get("extAddress")) == address
                and target.get("rawStatus") == row.get("status")):
            classes = {"answered": "answered", "not-provided": "not_provided", "unanswered": "unanswered"}
            classification = target.get("classification")
            table_class = classes.get(classification, "unavailable") if isinstance(classification, str) else "unavailable"
            if table_class == "not_provided" and (
                row.get("status") != "failed" or target.get("checkStatus") != "response"
                or target.get("reasonCode") != "not-provided-qualified"
            ):
                table_class = "unavailable"
            if table_class == "answered" and (
                row.get("status") != "completed" or target.get("reasonCode") != "answered"
            ):
                table_class = "unavailable"
            reason = _text(target.get("reasonCode")) or reason
            if table_class == "not_provided":
                coverage = "absent"
                response, response_evidence = "observed", "qualified_diagnostic"
            elif table_class == "answered":
                coverage = "complete"
                response, response_evidence = "observed", "direct"
        view = _view(item, command=command, stage=stage, target_key="deviceId", index=index)
        views.append(replace(view, table_class=table_class, coverage=coverage, response=response,
                             response_evidence=response_evidence, original_reason_code=reason))
    return tuple(views)


def responsiveness_outcome_views(
    outcome: object, *, command: str = "mesh-diagnostics fetch-all", stage: str = "responsiveness",
) -> tuple[CollectionOutcome, ...]:
    """Project existing responsiveness checks without granting table authority."""
    value = outcome if isinstance(outcome, Mapping) else {}
    evidence = value.get("meshResponsiveness")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    if evidence.get("contractVersion") != RESPONSIVENESS_VERSION:
        return ()
    views = []
    for index, item in enumerate(_records(evidence.get("targets"))):
        row = item if isinstance(item, Mapping) else {}
        identity = row.get("identity") if isinstance(row.get("identity"), Mapping) else {}
        check = row.get("check") if isinstance(row.get("check"), Mapping) else {}
        raw_status = _text(check.get("status"))
        diagnostic = check.get("diagnostic") if isinstance(check.get("diagnostic"), Mapping) else {}
        diagnostic_id = _text(diagnostic.get("id"))
        action_record = {"action": check.get("action"), "diagnosticId": diagnostic_id}
        address = extended_address(identity.get("extAddress"))
        observed = (
            raw_status == "response" and address is not None
            and extended_address(identity.get("deviceId")) == address
            and extended_address(diagnostic.get("extAddress")) == address
            and _matched_action(action_record)
        )
        status = {
            "not-attempted": "skipped", "no-response": "failed", "invalid-response": "failed",
        }.get(raw_status, "completed" if observed else "other")
        response = "observed" if observed else "not_observed" if raw_status == "no-response" else "unknown"
        attempts = ()
        if isinstance(check.get("request"), Mapping) and raw_status in ("response", "no-response", "invalid-response"):
            attempts = (CollectionAttempt("initial", status, diagnostic_id),)
        views.append(CollectionOutcome(
            source="otbr-restapi", command=command, stage=stage,
            target=_target(identity, "deviceId", index), initial_status=status, effective_status=status,
            original_status=raw_status, original_effective_status=raw_status,
            original_reason_code=_text(check.get("reasonCode")), response=response,
            response_evidence="qualified_diagnostic" if observed else "unknown",
            attempts=attempts,
        ))
    return tuple(views)
