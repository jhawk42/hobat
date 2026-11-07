from copy import deepcopy

import pytest

from otbr_restapi_outcomes import (
    diagnostic_outcome_views, mesh_outcome_views, responsiveness_outcome_views,
)
from td_collection_outcomes import summarize_outcomes
from td_restapi_diagnostic_recovery import REST_DIAGNOSTIC_RECOVERY_VERSION, reconcile_rest_diagnostics
from td_restapi_mesh_evidence import QUALIFICATION_VERSION, RESPONSIVENESS_VERSION


A = "1111111111111111"
B = "2222222222222222"


def action(diagnostic_id):
    return {"status": "completed", "relationships": {"result": {"data": {"id": diagnostic_id}}}}


def recovered(kind="child-rloc", *, original="skipped", fields=None):
    detail = {
        "extAddress": A, "diagnosticId": "diag-A", "recoveryKind": kind,
        "fields": fields if fields is not None else {
            "mode": {"availability": "present"},
            "childTable": {"availability": "not-provided"},
            "mleCounters": {"availability": "not-requested"},
        },
    }
    return {
        "deviceResults": [{
            "deviceId": A, "originalStatus": original, "status": "completed",
            "skipReasonCode": "unresolved_mesh_local_iid",
            "attemptedTypes": [[key for key, value in detail["fields"].items()
                                if isinstance(value, dict) and value.get("availability") != "not-requested"]],
            "recovery": {"contractVersion": REST_DIAGNOSTIC_RECOVERY_VERSION, "kind": kind,
                         "extAddress": A, "diagnosticId": "diag-A"},
        }],
        "childrenExpansion": {"results": [{"destination": "00382a", "status": "completed"}]},
        "diagnosticRecovery": {"contractVersion": REST_DIAGNOSTIC_RECOVERY_VERSION, "devices": [detail]},
    }


@pytest.mark.parametrize("kind,normalized", [
    ("child-rloc", "child_rloc"), ("child-detail", "child_detail"),
    ("router-fallback", "request_fallback"),
])
def test_reconciled_recovery_and_separate_populations(kind, normalized):
    data = recovered(kind, original="partial" if kind != "child-rloc" else "skipped")
    original = deepcopy(data)
    views = diagnostic_outcome_views(data, command="topology", stage_prefix="diagnostics.")
    assert data == original
    assert {key: len(value) for key, value in views.items()} == {"initial": 1, "expansion": 1, "effective": 1}
    effective = views["effective"][0]
    assert effective.stage == "diagnostics.effective"
    assert effective.command == "topology"
    assert effective.initial_status == data["deviceResults"][0]["originalStatus"]
    assert effective.effective_status == "completed"
    assert (effective.recovery_state, effective.recovery_kind) == ("recovered", normalized)
    assert effective.coverage == "partial"
    assert effective.original_reason_code == "unresolved_mesh_local_iid"
    assert effective.attempts == ()
    assert views["initial"][0].coverage == "unknown"
    assert views["expansion"][0].target == "00382a"


@pytest.mark.parametrize("fields,expected", [
    ({"mode": {"availability": "present"}, "x": {"availability": "not-requested"}}, "complete"),
    ({"mode": {"availability": "not-provided"}}, "absent"),
    ({"mode": {"availability": "unavailable"}}, "unknown"),
    ({"mode": {"availability": "present"}, "x": {"availability": "unavailable"}}, "partial"),
    ({"mode": {"availability": "not-requested"}}, "unknown"),
    ({}, "unknown"),
    ({"mode": {"availability": "future"}}, "unknown"),
    ({"mode": None}, "unknown"),
])
def test_coverage_from_qualified_fields_only(fields, expected):
    data = recovered(fields=fields)
    assert diagnostic_outcome_views(data)["effective"][0].coverage == expected


@pytest.mark.parametrize("case", ["duplicate_base", "duplicate_detail", "mismatched_detail", "unusable_base", "unusable_detail"])
def test_effective_population_requires_unique_identity_and_detail(case):
    data = recovered()
    if case == "duplicate_base":
        data["deviceResults"].append({"deviceId": A.upper(), "status": "failed"})
    elif case == "duplicate_detail":
        data["diagnosticRecovery"]["devices"].append(deepcopy(data["diagnosticRecovery"]["devices"][0]))
    elif case == "mismatched_detail":
        data["diagnosticRecovery"]["devices"][0]["extAddress"] = B
    elif case == "unusable_base":
        data["deviceResults"][0]["deviceId"] = "0000000000000000"
    else:
        data["diagnosticRecovery"]["devices"][0]["extAddress"] = "bad"
    assert diagnostic_outcome_views(data)["effective"] == ()


@pytest.mark.parametrize("change", ["contract", "kind", "diagnostic", "address"])
def test_inconsistent_recovery_is_never_claimed(change):
    data = recovered()
    rec = data["deviceResults"][0]["recovery"]
    if change == "contract":
        rec["contractVersion"] = "future"
    elif change == "kind":
        rec["kind"] = "router-fallback"
    elif change == "diagnostic":
        rec["diagnosticId"] = "other"
    else:
        rec["extAddress"] = B
    view = diagnostic_outcome_views(data)["effective"][0]
    assert (view.recovery_state, view.recovery_kind) == ("unknown", "unknown")


def test_unvalidated_details_cannot_supply_coverage_or_recovery():
    data = recovered()
    data["diagnosticRecovery"]["contractVersion"] = "unknown"
    view = diagnostic_outcome_views(data)["effective"][0]
    assert (view.coverage, view.recovery_state) == ("unknown", "unknown")


def test_coverage_requires_explicit_requested_set_not_success_flags():
    data = recovered(fields={"mode": {"availability": "present"}})
    record = data["deviceResults"][0]
    record.pop("attemptedTypes")
    record["successfulTypes"] = ["mode"]
    record["fallbackRecovered"] = True
    assert diagnostic_outcome_views(data)["effective"][0].coverage == "unknown"
    record["attemptedTypes"] = [["mode", "unknown-field"]]
    assert diagnostic_outcome_views(data)["effective"][0].coverage == "unknown"
    record["attemptedTypes"] = [["mode"]]
    assert diagnostic_outcome_views(data)["effective"][0].coverage == "complete"


@pytest.mark.parametrize("detail_availability,expected", [
    ("unavailable", "partial"), ("not-provided", "partial"), ("present", "complete"),
    ("not-requested", "unknown"),
])
def test_mode_aware_coverage_unions_pass_requested_fields(detail_availability, expected):
    data = recovered(fields={"mode": {"availability": "present"},
                             "macCounters": {"availability": detail_availability}})
    record = data["deviceResults"][0]
    record["attemptedTypes"] = [["mode"], ["mode", "macCounters"]]
    record["passes"] = [
        {"name": "fast", "requestedTypes": ["mode"]},
        {"name": "detail", "requestedTypes": ["mode", "macCounters"]},
    ]
    assert diagnostic_outcome_views(data)["effective"][0].coverage == expected


def test_generic_fallback_coverage_uses_primary_not_reduced_set():
    data = recovered(fields={"mode": {"availability": "present"},
                             "macCounters": {"availability": "not-provided"}})
    record = data["deviceResults"][0]
    record["attemptedTypes"] = [["mode", "macCounters"], ["mode"]]
    record["successfulTypes"] = ["mode"]
    assert diagnostic_outcome_views(data)["effective"][0].coverage == "partial"


def test_malformed_pass_requested_set_does_not_claim_coverage():
    data = recovered(fields={"mode": {"availability": "present"}})
    data["deviceResults"][0]["passes"] = [
        {"name": "fast", "requestedTypes": ["mode"]},
        {"name": "detail", "requestedTypes": None},
    ]
    assert diagnostic_outcome_views(data)["effective"][0].coverage == "unknown"


def test_real_reconciliation_child_rloc_evidence_is_consumed_without_mutation():
    parent = {"id": "p", "extAddress": A, "rloc16": "0x3800",
              "childTable": [{"childId": 42, "mode": {"device": "MTD"}}]}
    child = {"id": "c", "extAddress": B, "rloc16": "0x382a", "mode": {"device": "MTD"}}
    data = {
        "items": [parent, child], "partial": True,
        "deviceResults": [
            {"deviceId": A, "role": "router", "status": "completed", "diagnosticId": "p",
             "action": action("p"), "attemptedTypes": [["extAddress", "childTable"]]},
            {"deviceId": B, "role": "child", "status": "skipped",
             "skipReasonCode": "unresolved_mesh_local_iid", "attempts": 0},
        ],
        "childrenExpansion": {"partial": False, "issues": [], "results": [{
            "destination": "00382a", "destinationType": "rloc", "rloc16": "0x382a",
            "parentExtAddress": A, "parentRloc16": "0x3800", "childId": 42,
            "status": "completed", "attempts": 1, "extAddress": B, "diagnosticId": "c",
            "action": action("c"), "attemptedTypes": [["extAddress", "mode"]],
        }]},
    }
    reconciled = reconcile_rest_diagnostics(data)
    original = deepcopy(reconciled)
    views = diagnostic_outcome_views(reconciled)
    child_view = next(view for view in views["effective"] if view.target == B)
    assert (child_view.initial_status, child_view.effective_status) == ("skipped", "completed")
    assert (child_view.recovery_state, child_view.recovery_kind) == ("recovered", "child_rloc")
    assert child_view.coverage == "unknown"
    assert reconciled == original


def test_malformed_and_unknown_statuses_are_explicit_and_never_raise():
    data = {"deviceResults": [None, {"deviceId": [], "status": []},
                              {"deviceId": A, "status": "future", "originalStatus": 12}],
            "childrenExpansion": {"results": [None, {"status": {}}]}}
    views = diagnostic_outcome_views(data)
    assert [v.initial_status for v in views["initial"]] == ["other"] * 3
    assert [v.effective_status for v in views["expansion"]] == ["other"] * 2
    assert views["initial"][0].target == "unavailable-1"
    assert views["initial"][0].diagnostics
    assert views["initial"][2].original_effective_status == "future"
    assert diagnostic_outcome_views(None) == {"initial": (), "expansion": (), "effective": ()}


def test_verified_two_failures_and_one_fallback_success():
    data = {"deviceResults": [{
        "deviceId": A, "originalStatus": "failed", "status": "completed",
        "attempts": 3, "attemptedTypes": [["a", "b"], ["a", "b"], ["a"]],
        "attemptErrors": [{"type": "Error", "actionId": "a1"}, {"type": "Error", "actionId": "a2"}],
        "diagnosticId": "d3", "action": action("d3"),
    }]}
    view = diagnostic_outcome_views(data)["initial"][0]
    assert [(a.kind, a.status, a.evidence_ref) for a in view.attempts] == [
        ("initial", "failed", "a1"), ("same_set_retry", "failed", "a2"),
        ("request_fallback", "completed", "d3"),
    ]
    assert summarize_outcomes([view]).population == 1
    assert summarize_outcomes([view]).verified_attempts == 3
    assert (view.recovery_state, view.recovery_kind) == ("recovered", "request_fallback")


@pytest.mark.parametrize("sets,errors,status,expected", [
    ([["a"], ["b"]], [{"type": "Error"}, {"type": "Error"}], "failed", ("attempted", "request_fallback")),
    ([["a"], ["a"]], [{"type": "Error"}, {"type": "Error"}], "failed", ("attempted", "same_set_retry")),
    ([["a"], ["a"]], [{"type": "Error"}], "completed", ("recovered", "same_set_retry")),
    ([["a"], ["b"]], [{"type": "Error"}], "completed", ("recovered", "request_fallback")),
])
def test_terminal_retry_or_fallback_status_controls_recovery(sets, errors, status, expected):
    record = {"deviceId": A, "status": status, "attempts": len(sets),
              "attemptedTypes": sets, "attemptErrors": errors}
    if status == "completed":
        record.update(diagnosticId="d", action=action("d"))
    view = diagnostic_outcome_views({"deviceResults": [record]})["initial"][0]
    assert (view.recovery_state, view.recovery_kind) == expected


def test_verified_pass_retry_and_detail_history():
    data = {"deviceResults": [{
        "deviceId": A, "status": "completed",
        "passes": [
            {"name": "fast", "requestedTypes": ["mode"], "status": "completed",
             "attempts": 2, "attemptErrors": [{"type": "Error"}],
             "diagnosticId": "fast-id", "action": action("fast-id")},
            {"name": "detail", "requestedTypes": ["mode", "counter"], "status": "failed",
             "attempts": 1, "attemptErrors": [{"type": "Error"}]},
        ],
    }]}
    view = diagnostic_outcome_views(data)["initial"][0]
    assert [(a.kind, a.status) for a in view.attempts] == [
        ("initial", "failed"), ("same_set_retry", "completed"), ("child_detail", "failed"),
    ]
    assert (view.recovery_state, view.recovery_kind) == ("unknown", "unknown")


def test_successful_retry_followed_by_unproved_different_pass_is_not_recovered():
    passes = [
        {"name": "fast", "requestedTypes": ["mode"], "status": "completed",
         "attempts": 2, "attemptErrors": [{"type": "Error"}],
         "diagnosticId": "fast", "action": action("fast")},
        {"name": "other", "requestedTypes": ["counter"], "status": "failed",
         "attempts": 1, "attemptErrors": [{"type": "Error"}]},
    ]
    view = diagnostic_outcome_views({"deviceResults": [{"deviceId": A, "status": "partial", "passes": passes}]})["initial"][0]
    assert view.attempts[-1].kind == "unknown"
    assert (view.recovery_state, view.recovery_kind) == ("unknown", "unknown")


@pytest.mark.parametrize("detail_types", [["counter"], ["mode"]])
def test_intentional_fast_then_detail_completion_is_not_recovery(detail_types):
    passes = [
        {"name": "fast", "requestedTypes": ["mode"], "status": "completed",
         "attempts": 1, "attemptErrors": [], "diagnosticId": "fast", "action": action("fast")},
        {"name": "detail", "requestedTypes": detail_types, "status": "completed",
         "attempts": 1, "attemptErrors": [], "diagnosticId": "detail", "action": action("detail")},
    ]
    view = diagnostic_outcome_views({"deviceResults": [{"deviceId": A, "status": "completed", "passes": passes}]})["initial"][0]
    assert view.attempts[-1].kind == "child_detail"
    assert (view.recovery_state, view.recovery_kind) == ("unknown", "unknown")


@pytest.mark.parametrize("change", ["count", "errors", "action", "flag_only", "passes"])
def test_incomplete_or_inconsistent_history_never_invents_attempts(change):
    data = {"deviceResults": [{
        "deviceId": A, "status": "completed", "attempts": 2,
        "attemptedTypes": [["a"], ["b"]], "attemptErrors": [{"type": "Error"}],
        "diagnosticId": "d", "action": action("d"), "fallbackRecovered": True,
        "successfulTypes": ["b"],
    }]}
    record = data["deviceResults"][0]
    if change == "count":
        record["attempts"] = 3
    elif change == "errors":
        record["attemptErrors"] = [{}]
    elif change == "action":
        record["action"] = action("other")
    elif change == "flag_only":
        for key in ("attempts", "attemptedTypes", "attemptErrors", "action", "diagnosticId"):
            record.pop(key)
    else:
        record["passes"] = [{"name": "fast", "status": "completed"}]
    view = diagnostic_outcome_views(data)["initial"][0]
    assert view.attempts == ()
    assert view.coverage == "unknown"
    assert view.recovery_state == "unknown"


def test_mesh_qualification_must_be_supplied_and_uniquely_match():
    data = {"deviceResults": [{"deviceId": A, "status": "failed", "responsive": True}]}
    target = {"deviceId": A, "extAddress": A, "rawStatus": "failed",
              "classification": "not-provided", "reasonCode": "not-provided-qualified",
              "checkStatus": "response"}
    qualification = {"contractVersion": QUALIFICATION_VERSION, "targets": [target]}
    original = deepcopy((data, qualification))
    unavailable = mesh_outcome_views(data)[0]
    assert (unavailable.table_class, unavailable.response) == ("unavailable", "unknown")
    view = mesh_outcome_views(data, qualification=qualification)[0]
    assert (view.initial_status, view.effective_status, view.table_class, view.coverage) == (
        "failed", "failed", "not_provided", "absent",
    )
    assert (view.response, view.response_evidence) == ("observed", "qualified_diagnostic")
    assert view.display_label == "Not provided"
    assert (data, qualification) == original
    qualification["targets"].append(deepcopy(target))
    assert mesh_outcome_views(data, qualification=qualification)[0].table_class == "unavailable"


@pytest.mark.parametrize("change", [
    "bad_contract", "mismatched_id", "mismatched_status", "duplicate_base",
    "bad_class", "missing_qualification_reason", "no_qualified_response",
])
def test_mesh_qualification_cannot_broaden_evidence(change):
    data = {"deviceResults": [{"deviceId": A, "status": "failed"}]}
    qualification = {"contractVersion": QUALIFICATION_VERSION, "targets": [{
        "deviceId": A, "extAddress": A, "rawStatus": "failed",
        "classification": "not-provided", "checkStatus": "response",
        "reasonCode": "not-provided-qualified",
    }]}
    if change == "bad_contract":
        qualification["contractVersion"] = "future"
    elif change == "mismatched_id":
        qualification["targets"][0]["extAddress"] = B
    elif change == "mismatched_status":
        qualification["targets"][0]["rawStatus"] = "completed"
    elif change == "duplicate_base":
        data["deviceResults"].append(deepcopy(data["deviceResults"][0]))
    elif change == "bad_class":
        qualification["targets"][0]["classification"] = []
    elif change == "missing_qualification_reason":
        qualification["targets"][0].pop("reasonCode")
    else:
        qualification["targets"][0]["checkStatus"] = "no-response"
    assert all(v.table_class == "unavailable" and v.response == "unknown"
               for v in mesh_outcome_views(data, qualification=qualification))


def test_mesh_malformed_records_are_explicit():
    values = mesh_outcome_views({"deviceResults": [None, {"deviceId": A, "status": []}]})
    assert len(values) == 2
    assert all(v.initial_status == "other" and v.diagnostics for v in values)


def test_mesh_qualified_answered_proves_coverage_and_direct_response():
    data = {"deviceResults": [{"deviceId": A, "status": "completed"}]}
    qualified = {"contractVersion": QUALIFICATION_VERSION, "targets": [{
        "deviceId": A, "extAddress": A, "rawStatus": "completed",
        "classification": "answered", "reasonCode": "answered",
    }]}
    view = mesh_outcome_views(data, qualification=qualified)[0]
    assert (view.table_class, view.coverage, view.response, view.response_evidence) == (
        "answered", "complete", "observed", "direct",
    )
    assert mesh_outcome_views(data)[0].coverage == "unknown"
    qualified["targets"][0]["reasonCode"] = "other"
    assert mesh_outcome_views(data, qualification=qualified)[0].table_class == "unavailable"


@pytest.mark.parametrize("case", ["missing_item", "wrong_identity", "duplicate_item", "missing_binding", "duplicate_target", "flag_only"])
def test_diagnostic_response_needs_matched_action_diagnostic_and_identity(case):
    record = {"deviceId": A, "status": "completed", "diagnosticId": "diag",
              "action": action("diag"), "successfulTypes": ["mode"]}
    data = {"deviceResults": [record], "items": [{"id": "diag", "extAddress": A}]}
    if case == "missing_item":
        data["items"] = []
    elif case == "wrong_identity":
        data["items"][0]["extAddress"] = B
    elif case == "duplicate_item":
        data["items"].append(deepcopy(data["items"][0]))
    elif case == "missing_binding":
        record["action"].pop("relationships")
    elif case == "duplicate_target":
        data["deviceResults"].append(deepcopy(record))
    else:
        record.pop("action")
    assert diagnostic_outcome_views(data)["initial"][0].response == "unknown"


def test_diagnostic_response_can_be_observed_without_inferring_coverage():
    data = {"deviceResults": [{"deviceId": A, "status": "failed", "diagnosticId": "diag",
                               "action": action("diag")}],
            "items": [{"data": {"id": "diag", "attributes": {"extAddress": A}}}]}
    before = deepcopy(data)
    view = diagnostic_outcome_views(data)["initial"][0]
    assert (view.effective_status, view.response, view.response_evidence, view.coverage) == (
        "failed", "observed", "direct", "unknown",
    )
    assert data == before


def responsiveness_target(status, reason=None):
    check = {"status": status, "reasonCode": reason}
    if status != "not-attempted":
        check["request"] = {"types": ["mode"]}
    if status == "response":
        check.update(action=action("diag"), diagnostic={"id": "diag", "extAddress": A})
    return {"identity": {"deviceId": A, "extAddress": A}, "check": check}


@pytest.mark.parametrize("status,expected_status,response,attempts", [
    ("not-attempted", "skipped", "unknown", 0),
    ("response", "completed", "observed", 1),
    ("no-response", "failed", "not_observed", 1),
    ("invalid-response", "failed", "unknown", 1),
    ("future", "other", "unknown", 0),
])
def test_responsiveness_views_preserve_independent_facts(status, expected_status, response, attempts):
    data = {"meshResponsiveness": {"contractVersion": RESPONSIVENESS_VERSION,
                                   "targets": [responsiveness_target(status, "scope-changed")]}}
    original = deepcopy(data)
    view = responsiveness_outcome_views(data, command="topology", stage="mesh.response")[0]
    assert (view.command, view.stage, view.target) == ("topology", "mesh.response", A)
    assert (view.initial_status, view.effective_status, view.original_status) == (
        expected_status, expected_status, status,
    )
    assert (view.response, len(view.attempts), view.original_reason_code) == (response, attempts, "scope-changed")
    assert (view.table_class, view.coverage) == ("unavailable", "unknown")
    assert data == original


@pytest.mark.parametrize("case", ["missing_binding", "wrong_identity", "no_action", "no_diagnostic"])
def test_unverified_responsiveness_response_is_not_claimed(case):
    target = responsiveness_target("response")
    check = target["check"]
    if case == "missing_binding":
        check["action"].pop("relationships")
    elif case == "wrong_identity":
        check["diagnostic"]["extAddress"] = B
    elif case == "no_action":
        check.pop("action")
    else:
        check.pop("diagnostic")
    data = {"meshResponsiveness": {"contractVersion": RESPONSIVENESS_VERSION, "targets": [target]}}
    view = responsiveness_outcome_views(data)[0]
    assert (view.response, view.effective_status) == ("unknown", "other")
    assert view.table_class == "unavailable"


def test_responsiveness_bad_version_and_malformed_targets():
    assert responsiveness_outcome_views({"meshResponsiveness": {"contractVersion": "future", "targets": [None]}}) == ()
    data = {"meshResponsiveness": {"contractVersion": RESPONSIVENESS_VERSION, "targets": [None]}}
    view = responsiveness_outcome_views(data)[0]
    assert (view.effective_status, view.response, view.attempts) == ("other", "unknown", ())
