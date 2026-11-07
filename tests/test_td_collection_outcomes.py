from dataclasses import FrozenInstanceError, replace

import pytest

from td_collection_outcomes import (
    REASON_LABELS,
    STATUSES,
    CollectionAttempt,
    CollectionOutcome,
    CollectionSummary,
    normalize_reason,
    normalize_status,
    log_outcome_summary,
    summarize_outcomes,
)


def outcome(**changes):
    return CollectionOutcome(
        source=changes.pop("source", "otbr-restapi"),
        command=changes.pop("command", "diagnostics"),
        stage=changes.pop("stage", "initial"),
        target=changes.pop("target", "target-A"),
        initial_status=changes.pop("initial_status", "failed"),
        effective_status=changes.pop("effective_status", "failed"),
        **changes,
    )


@pytest.mark.parametrize("status", STATUSES)
def test_statuses_and_diagnostics(status):
    view = outcome(initial_status=status, effective_status=status)
    assert normalize_status(status) == status
    assert view.initial_status == view.effective_status == status
    assert view.diagnostics == (
        ("initial_status_other", "effective_status_other") if status == "other" else ()
    )


@pytest.mark.parametrize("status", [None, "", "success", "invalid_response", "completed "])
def test_unrecognized_status_is_diagnostic_and_preserves_input(status):
    view = outcome(initial_status=status, effective_status=status)
    assert view.initial_status == view.effective_status == "other"
    assert view.original_status == view.original_effective_status == status
    assert view.diagnostics == ("initial_status_other", "effective_status_other")
    assert normalize_status(status) == "other"


@pytest.mark.parametrize(
    ("name", "values"),
    [
        ("coverage", ("complete", "partial", "absent", "unknown")),
        ("table_class", ("answered", "not_provided", "unanswered", "legacy", "unavailable")),
        ("response", ("observed", "not_observed", "unknown")),
        ("response_evidence", ("direct", "ping", "qualified_diagnostic", "unknown")),
        ("recovery_state", ("none", "attempted", "recovered", "unknown")),
        ("recovery_kind", ("none", "same_set_retry", "request_fallback", "child_rloc", "child_detail", "unknown")),
    ],
)
def test_bounded_fields_accept_every_value_and_reject_unknown(name, values):
    for value in values:
        assert getattr(outcome(**{name: value}), name) == value
    with pytest.raises(ValueError):
        outcome(**{name: "unrecognized"})


@pytest.mark.parametrize("kind", ["initial", "same_set_retry", "request_fallback", "child_rloc", "child_detail", "unknown"])
def test_attempt_kinds_and_statuses(kind):
    for status in (*STATUSES, None, "unexpected"):
        attempt = CollectionAttempt(kind, status, evidence_ref="receipt-1")
        assert attempt.status == normalize_status(status)
        assert attempt.original_status == status
        assert attempt.diagnostics == (("status_other",) if attempt.status == "other" else ())
    with pytest.raises(ValueError):
        CollectionAttempt("bad", "failed")


@pytest.mark.parametrize("version", [0, 2, -1, "1", True, None])
def test_unsupported_version_rejected(version):
    with pytest.raises(ValueError, match="Unsupported"):
        outcome(version=version)
    with pytest.raises(ValueError, match="Unsupported"):
        summarize_outcomes([], version=version)


@pytest.mark.parametrize("name", ["source", "command", "stage", "target"])
def test_scope_is_explicit(name):
    with pytest.raises(ValueError):
        outcome(**{name: ""})


def test_raw_values_and_independent_fields():
    view = outcome(
        initial_status="failed", effective_status="completed",
        original_status="timeout", original_effective_status="success",
        original_reason_code="future-code", coverage="partial",
        table_class="unavailable", response="not_observed", response_evidence="direct",
        recovery_state="recovered", recovery_kind="request_fallback",
    )
    assert (view.initial_status, view.effective_status, view.coverage) == ("failed", "completed", "partial")
    assert (view.original_status, view.original_effective_status) == ("timeout", "success")
    assert (view.original_reason_code, view.reason_code, view.reason_label) == ("future-code", "unknown", "Unknown reason")
    assert view.response == "not_observed"
    assert view.display_label == "Request completed"
    assert view.recovery_summary == "Recovered by alternate request"


def test_all_reason_keys_have_labels_and_unknown_is_bounded():
    for code, label in REASON_LABELS.items():
        view = outcome(original_reason_code=code)
        assert normalize_reason(code) == code
        assert (view.reason_code, view.reason_label) == (code, label)
        assert label and isinstance(label, str)
    for code in (None, "", "exception with secret text", "UNRESOLVED_MESH_LOCAL_IID"):
        view = outcome(original_reason_code=code)
        assert view.reason_code == "unknown"
        assert view.original_reason_code == code
    with pytest.raises(TypeError):
        REASON_LABELS["new"] = "New"


def test_reason_inventory_from_source_owners():
    expected = {
        "unresolved_mesh_local_iid", "already_collected", "conflicting_evidence",
        "conflicting_child_mode", "conflicting_parent_identity", "parent_unavailable",
        "parent_evidence_unavailable", "parent_child_table_missing", "invalid_parent_rloc16",
        "parent_rloc16_not_router", "parent_router_id_out_of_range", "malformed_child_table",
        "invalid_child_entry", "identity_missing", "identity_changed", "identity_conflict",
        "rloc16_mismatch", "unresolved_prior_action", "child_passes_disabled",
        "malformed-outcome", "malformed-target", "incomplete-target",
        "malformed-expansion-target", "incomplete-expansion-target", "expansion-issue",
        "malformed-expansion-issue", "unverified-recovery-evidence",
        "unsupported-destination-type", "missing-target-identity", "partial-table-returned",
        "ineligible-failure", "ambiguous-target", "target-identity-changed",
        "witness-missing", "witness-stale", "children-uncovered",
        "diagnostic-no-response", "diagnostic-invalid-evidence", "diagnostic-result-missing",
        "diagnostic-result-reused", "diagnostic-identity-mismatch", "diagnostic-response-stale",
        "unsupported-contract", "scope-changed", "scope-unavailable",
        "witness-binding-mismatch", "witness-identity-mismatch", "answered",
        "not-provided-qualified", "ambiguous_target",
        "disabled", "skip_devices", "skip_diagnostics", "skip_mesh_diagnostics",
        "not_requested", "petition_rejected", "dtls_failed",
        "border_router_unreachable", "no_credentials", "no_source", "rest_unreachable",
        "rest_protocol", "timeout", "in_progress", "meshcop_no_responses_yet",
        "rest_no_responses_yet",
    }
    assert set(REASON_LABELS) == expected | {"unknown"}


def test_immutable_copy_safe_attempt_evidence_and_summary():
    attempts = [CollectionAttempt("initial", "failed", "first")]
    view = outcome(attempts=attempts)
    attempts.append(CollectionAttempt("same_set_retry", "completed", "second"))
    assert len(view.attempts) == 1
    with pytest.raises(FrozenInstanceError):
        view.attempts[0].status = "completed"
    with pytest.raises(FrozenInstanceError):
        view.coverage = "complete"
    with pytest.raises(TypeError):
        outcome(attempts=[{"status": "failed"}])
    summary = summarize_outcomes([view])
    with pytest.raises(TypeError):
        summary.terminal_statuses["failed"] = 0
    with pytest.raises(TypeError):
        summary.reasons["unknown"] = 0
    counts = {"failed": 1}
    direct_summary = CollectionSummary(1, counts, counts, 0)
    counts["failed"] = 2
    assert direct_summary.terminal_statuses["failed"] == direct_summary.reasons["failed"] == 1


@pytest.mark.parametrize(
    ("status", "label"),
    [("completed", "Request completed"), ("skipped", "Request skipped"),
     ("partial", "Request partial"), ("failed", "Request failed"),
     ("other", "Request outcome unknown")],
)
def test_request_labels(status, label):
    assert outcome(effective_status=status).display_label == label
    assert outcome(effective_status=status, table_class="not_provided").display_label == "Not provided"


@pytest.mark.parametrize(
    ("kind", "path"),
    [("none", None), ("unknown", None), ("same_set_retry", "retry"),
     ("request_fallback", "alternate request"), ("child_rloc", "child RLOC"),
     ("child_detail", "child detail")],
)
@pytest.mark.parametrize("state", ["none", "unknown", "attempted", "recovered"])
def test_recovery_summary_is_based_only_on_supplied_facts(state, kind, path):
    summary = outcome(recovery_state=state, recovery_kind=kind).recovery_summary
    if state in ("none", "unknown"):
        assert summary == {"none": "No recovery", "unknown": "Recovery unknown"}[state]
    else:
        verb = "Recovery attempted" if state == "attempted" else "Recovered"
        assert summary == (f"{verb} by {path}" if path else verb)


def test_plan_examples_and_attempts_are_not_devices():
    normal = outcome(initial_status="completed", effective_status="completed", coverage="complete",
                     table_class="answered", recovery_state="none", recovery_kind="none")
    not_provided = outcome(source="otbr-cli", table_class="not_provided", coverage="absent",
                           response="observed", response_evidence="ping",
                           recovery_state="none", recovery_kind="none")
    child = outcome(initial_status="skipped", effective_status="completed",
                    original_reason_code="unresolved_mesh_local_iid", coverage="unknown",
                    recovery_state="recovered", recovery_kind="child_rloc")
    fallback = outcome(initial_status="failed", effective_status="completed", coverage="partial",
                       recovery_state="recovered", recovery_kind="request_fallback",
                       attempts=[CollectionAttempt("initial", "failed"),
                                 CollectionAttempt("request_fallback", "completed")])
    retry = outcome(coverage="absent", response="not_observed", recovery_state="attempted",
                    recovery_kind="same_set_retry", attempts=[CollectionAttempt("initial", "failed"),
                                                             CollectionAttempt("same_set_retry", "failed")])
    legacy = outcome(initial_status=None, effective_status=None, table_class="legacy")

    assert (normal.display_label, normal.coverage, normal.recovery_summary) == ("Request completed", "complete", "No recovery")
    assert (not_provided.display_label, not_provided.initial_status, not_provided.effective_status) == ("Not provided", "failed", "failed")
    assert (not_provided.response, not_provided.response_evidence, not_provided.recovery_state) == ("observed", "ping", "none")
    assert (child.initial_status, child.effective_status, child.coverage, child.reason_code) == ("skipped", "completed", "unknown", "unresolved_mesh_local_iid")
    assert child.reason_label == "Address could not be resolved"
    assert (fallback.effective_status, fallback.coverage, fallback.recovery_summary) == ("completed", "partial", "Recovered by alternate request")
    assert (retry.effective_status, retry.response, retry.recovery_summary) == ("failed", "not_observed", "Recovery attempted by retry")
    assert (legacy.initial_status, legacy.effective_status, legacy.table_class, legacy.coverage) == ("other", "other", "legacy", "unknown")
    assert legacy.diagnostics == ("initial_status_other", "effective_status_other")

    summary = summarize_outcomes(iter([normal, not_provided, child, fallback, retry, legacy]))
    assert summary.population == 6
    assert dict(summary.terminal_statuses) == {"completed": 3, "skipped": 0, "partial": 0, "failed": 2, "other": 1}
    assert sum(summary.reasons.values()) == 6
    assert summary.reasons["unresolved_mesh_local_iid"] == 1
    assert summary.reasons["unknown"] == 5
    assert summary.verified_attempts == 4
    assert summarize_outcomes([retry]).population == 1
    assert summarize_outcomes([retry]).verified_attempts == 2


def test_missing_history_never_inferred_and_scopes_not_merged():
    recovered = outcome(effective_status="completed", recovery_state="recovered",
                        recovery_kind="request_fallback")
    assert recovered.attempts == ()
    assert recovered.initial_status == "failed"
    assert recovered.coverage == "unknown"
    same_target_other_source = replace(recovered, source="otbr-cli")
    summary = summarize_outcomes([recovered, same_target_other_source, recovered])
    assert summary.population == 3
    assert summary.terminal_statuses["completed"] == 3
    assert summary.verified_attempts == 0


def test_empty_summary_and_invalid_population():
    summary = summarize_outcomes([])
    assert summary.population == summary.verified_attempts == 0
    assert sum(summary.terminal_statuses.values()) == sum(summary.reasons.values()) == 0
    with pytest.raises(TypeError):
        summarize_outcomes([{}])


def test_event_fields_include_independent_facts_without_scope_kwargs():
    view = outcome(
        initial_status="failed", effective_status="completed",
        coverage="partial", table_class="not_provided",
        response="observed", response_evidence="ping",
        recovery_state="recovered", recovery_kind="request_fallback",
        original_status="timeout", original_effective_status="success",
        original_reason_code="future-code",
        attempts=[CollectionAttempt("initial", "failed", "first", "timeout"),
                  CollectionAttempt("request_fallback", "unexpected", "second")],
    )
    fields = view.event_fields()
    assert fields == {
        "target": "target-A",
        "initial_status": "failed", "effective_status": "completed",
        "coverage": "partial", "table_class": "not_provided",
        "response": "observed", "response_evidence": "ping",
        "recovery_state": "recovered", "recovery_kind": "request_fallback",
        "reason_code": "unknown", "reason_label": "Unknown reason",
        "display_label": "Not provided", "recovery_summary": "Recovered by alternate request",
        "original_status": "timeout", "original_effective_status": "success",
        "original_reason_code": "future-code", "version": 1, "diagnostics": [],
        "attempts": [
            {"kind": "initial", "status": "failed", "original_status": "timeout",
             "evidence_ref": "first", "diagnostics": []},
            {"kind": "request_fallback", "status": "other", "original_status": "unexpected",
             "evidence_ref": "second", "diagnostics": ["status_other"]},
        ],
    }
    assert not ({"source", "command", "stage"} & fields.keys())

    fields["attempts"][0]["diagnostics"].append("changed")
    fields["attempts"].append({"kind": "invented"})
    fields["diagnostics"].append("changed")
    assert len(view.event_fields()["attempts"]) == 2
    assert view.event_fields()["attempts"][0]["diagnostics"] == []
    assert view.event_fields()["diagnostics"] == []


def test_event_fields_keep_unknown_status_and_empty_history():
    view = outcome(initial_status=None, effective_status="future", recovery_state="recovered")
    fields = view.event_fields()
    assert fields["initial_status"] == fields["effective_status"] == "other"
    assert fields["original_status"] is None
    assert fields["original_effective_status"] == "future"
    assert fields["diagnostics"] == ["initial_status_other", "effective_status_other"]
    assert fields["attempts"] == []


def test_event_fields_can_be_passed_to_existing_formatter():
    from td_logging import format_event

    view = outcome(attempts=[CollectionAttempt("initial", "failed", "receipt")])
    rendered = format_event(
        "target_result", source=view.source, command=view.command, stage=view.stage,
        **view.event_fields(),
    )
    assert 'target="target-A"' in rendered
    assert 'attempts=[{"kind":"initial","status":"failed"' in rendered


def test_initial_and_effective_histograms_are_separate():
    values = [
        outcome(initial_status="skipped", effective_status="completed",
                attempts=[CollectionAttempt("child_rloc", "completed")]),
        outcome(initial_status="failed", effective_status="completed"),
        outcome(initial_status="failed", effective_status="failed"),
    ]
    initial = summarize_outcomes(values, status_phase="initial")
    effective = summarize_outcomes(values, status_phase="effective")
    assert initial.terminal_statuses == {
        "completed": 0, "skipped": 1, "partial": 0, "failed": 2, "other": 0,
    }
    assert effective.terminal_statuses == {
        "completed": 2, "skipped": 0, "partial": 0, "failed": 1, "other": 0,
    }
    assert summarize_outcomes(values) == effective
    assert initial.population == effective.population == 3
    assert initial.verified_attempts == effective.verified_attempts == 1
    assert initial.reasons == effective.reasons
    assert values[0].effective_status == "completed"


@pytest.mark.parametrize("phase", ["", "other", "INITIAL", None, 1])
def test_unknown_status_phase_fails_even_for_empty_population(phase):
    with pytest.raises(ValueError, match="status_phase"):
        summarize_outcomes([], status_phase=phase)


def test_summary_log_fields_separate_verified_attempt_kinds_from_targets():
    view = outcome(
        attempts=(
            CollectionAttempt("initial", "failed"),
            CollectionAttempt("same_set_retry", "failed"),
            CollectionAttempt("request_fallback", "completed"),
        ),
    )
    summary = summarize_outcomes([view])
    fields = summary.event_fields()
    assert fields["population"] == 1
    assert fields["verified_attempts"] == 3
    assert fields["verified_attempt_kinds"] == {
        "initial": 1, "same_set_retry": 1, "request_fallback": 1,
    }
    assert fields["reasons"] == {"unknown": 1}
    assert sum(fields["terminal_statuses"].values()) == 1
    assert sum(fields["reasons"].values()) == 1
    fields["verified_attempt_kinds"]["initial"] = 99
    assert summary.verified_attempt_kinds["initial"] == 1


@pytest.mark.parametrize("values,available", [(None, False), ([], True)])
def test_summary_logs_distinguish_unknown_and_known_empty(caplog, values, available):
    import logging

    with caplog.at_level(logging.INFO):
        log_outcome_summary(values, source="test", command="test", stage="initial")
    line = caplog.records[-1].message
    assert f'availability="{"available" if available else "unavailable"}"' in line
    if available:
        assert "population=0" in line
        assert 'reasons={}' in line
    else:
        assert "population=" not in line
        assert "terminal_statuses=" not in line
