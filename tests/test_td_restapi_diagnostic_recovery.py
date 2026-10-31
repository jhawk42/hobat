from __future__ import annotations

from copy import deepcopy

import pytest

from td_restapi_diagnostic_recovery import (
    REST_DIAGNOSTIC_RECOVERY_VERSION,
    reconcile_bound_rest_diagnostics,
    reconcile_rest_diagnostics,
    valid_child_table,
)


PARENT = "1111111111111111"
CHILD = "2222222222222222"
FAST_TYPES = ["extAddress", "rloc16", "mode", "ipv6Addresses"]
DETAIL_TYPES = [*FAST_TYPES, "macCounters"]


def _action(diagnostic_id: str) -> dict:
    return {
        "status": "completed",
        "relationships": {"result": {"data": {"id": diagnostic_id}}},
    }


def _row(diagnostic_id: str, attributes: dict, raw: bool) -> dict:
    if raw:
        return {"data": {"id": diagnostic_id, "attributes": attributes}}
    return {"id": diagnostic_id, **attributes}


def _attributes(row: dict) -> dict:
    return row["data"]["attributes"] if "data" in row else row


def _fixture(raw: bool = False) -> tuple[dict, list]:
    parent = _row(
        "parent-diagnostic",
        {
            "extAddress": PARENT,
            "rloc16": "0x3800",
            "childTable": [{"childId": 42, "mode": {"device": "MTD"}}],
            "created": "2026-10-30T11:00:00+00:00",
        },
        raw,
    )
    child = _row(
        "child-diagnostic",
        {
            "extAddress": CHILD,
            "rloc16": "0x382a",
            "mode": {"device": "MTD", "rxOnWhenIdle": False},
            "ipv6Addresses": ["fd00::1"],
            "created": "2026-10-30T11:00:01+00:00",
        },
        raw,
    )
    parent_result = {
        "deviceId": PARENT,
        "role": "router",
        "status": "partial",
        "diagnosticId": "parent-diagnostic",
        "action": _action("parent-diagnostic"),
        "attempts": 2,
        "attemptedTypes": [
            ["extAddress", "rloc16", "childTable", "mleCounters"],
            ["extAddress", "rloc16", "childTable", "macCounters"],
        ],
        "successfulTypes": ["extAddress", "rloc16", "childTable", "macCounters"],
        "fallbackRecovered": True,
        "attemptErrors": [{"type": "OTBRActionFailedError", "message": "failed"}],
    }
    child_result = {
        "deviceId": CHILD,
        "role": "child",
        "status": "skipped",
        "skipReasonCode": "unresolved_mesh_local_iid",
        "attempts": 0,
    }
    target = {
        "destination": "00382a",
        "destinationType": "rloc",
        "rloc16": "0x382a",
        "parentExtAddress": PARENT,
        "parentRloc16": "0x3800",
        "childId": 42,
        "status": "completed",
        "attempts": 1,
        "extAddress": CHILD,
        "diagnosticId": "child-diagnostic",
        "selectedPass": "fast",
        "passes": [{
            "name": "fast",
            "requestedTypes": FAST_TYPES,
            "status": "completed",
            "diagnosticId": "child-diagnostic",
            "action": _action("child-diagnostic"),
            "attemptErrors": [],
        }],
        "attemptedTypes": [FAST_TYPES],
        "successfulTypes": FAST_TYPES,
        "attemptErrors": [],
    }
    outcome = {
        "items": [parent, child],
        "deviceResults": [parent_result, child_result],
        "partial": True,
        "startedAt": "2026-10-30T11:00:00.500000+00:00",
        "completedAt": "2026-10-30T11:01:00+00:00",
        "childrenExpansion": {
            "enabled": True,
            "partial": False,
            "targetCount": 1,
            "attemptedCount": 1,
            "completedCount": 1,
            "coveredCount": 0,
            "results": [target],
            "issues": [],
        },
    }
    return outcome, deepcopy(outcome["items"])


@pytest.mark.parametrize("raw", [False, True])
def test_recovery_uses_bound_rows_and_actual_field_values(raw: bool) -> None:
    outcome, final = _fixture(raw)
    original = deepcopy(outcome)

    effective = reconcile_rest_diagnostics(outcome, final, require_timestamps=True)

    assert outcome == original
    assert effective["partial"] is False
    assert [item["originalStatus"] for item in effective["deviceResults"]] == [
        "partial", "skipped"
    ]
    assert effective["deviceResults"][1]["skipReasonCode"] == "unresolved_mesh_local_iid"
    assert effective["childrenExpansion"]["completedCount"] == 1
    assert effective["childrenExpansion"]["recoveredCount"] == 1
    coverage = effective["diagnosticRecovery"]
    assert coverage["contractVersion"] == REST_DIAGNOSTIC_RECOVERY_VERSION
    assert coverage["summary"]["recoveredChildren"] == 1
    assert coverage["summary"]["recoveredRouters"] == 1
    devices = {item["extAddress"]: item for item in coverage["devices"]}
    assert devices[CHILD]["fields"]["mode"]["availability"] == "present"
    assert devices[CHILD]["fields"]["macCounters"]["availability"] == "not-requested"
    assert devices[PARENT]["fields"]["macCounters"]["availability"] == "not-provided"
    assert devices[PARENT]["fields"]["mleCounters"] == {
        "availability": "unavailable",
        "reason": "OTBRActionFailedError",
    }


@pytest.mark.parametrize(
    "case",
    [
        "missing-parent-table",
        "null-parent-table",
        "invalid-child-id",
        "conflicting-child-entries",
        "parent-identity",
        "target-identity",
        "target-rloc",
        "unattempted",
        "duplicate-target",
        "duplicate-base",
        "parent-issue",
        "missing-diagnostic",
        "mismatched-final",
        "duplicate-final",
        "out-of-run",
        "missing-time",
    ],
)
def test_unbound_or_conflicting_child_stays_incomplete(case: str) -> None:
    outcome, final = _fixture()
    parent = _attributes(outcome["items"][0])
    target = outcome["childrenExpansion"]["results"][0]
    if case == "missing-parent-table":
        parent.pop("childTable")
        _attributes(final[0]).pop("childTable")
    elif case == "null-parent-table":
        parent["childTable"] = _attributes(final[0])["childTable"] = None
    elif case == "invalid-child-id":
        parent["childTable"] = _attributes(final[0])["childTable"] = [{"childId": True}]
    elif case == "conflicting-child-entries":
        entries = [{"childId": 42, "mode": "first"}, {"childId": 42, "mode": "second"}]
        parent["childTable"] = _attributes(final[0])["childTable"] = entries
    elif case == "parent-identity":
        target["parentExtAddress"] = "3333333333333333"
    elif case == "target-identity":
        target["extAddress"] = "3333333333333333"
    elif case == "target-rloc":
        target["rloc16"] = "0x382b"
    elif case == "unattempted":
        target["status"] = "not_attempted"
        target["attempts"] = 0
    elif case == "duplicate-target":
        outcome["childrenExpansion"]["results"].append(deepcopy(target))
    elif case == "duplicate-base":
        outcome["deviceResults"].append(deepcopy(outcome["deviceResults"][1]))
    elif case == "parent-issue":
        outcome["childrenExpansion"]["issues"].append({
            "code": "invalid_child_entry", "parentExtAddress": PARENT
        })
    elif case == "missing-diagnostic":
        outcome["items"].pop()
    elif case == "mismatched-final":
        _attributes(final[1])["extAddress"] = "3333333333333333"
    elif case == "duplicate-final":
        final.append(deepcopy(final[1]))
    elif case == "out-of-run":
        _attributes(outcome["items"][1])["created"] = "2026-10-30T11:02:00+00:00"
        _attributes(final[1])["created"] = "2026-10-30T11:02:00+00:00"
    elif case == "missing-time":
        outcome["completedAt"] = None

    effective = reconcile_rest_diagnostics(outcome, final, require_timestamps=True)

    assert effective["partial"] is True
    assert effective["deviceResults"][1]["status"] == "skipped"


@pytest.mark.parametrize("failure", ["OTBRActionFailedError", "OTBRActionTimeoutError"])
def test_valid_fast_response_survives_failed_detail(failure: str) -> None:
    outcome, final = _fixture()
    target = outcome["childrenExpansion"]["results"][0]
    target["status"] = "partial"
    target["attempts"] = 2
    target["attemptedTypes"].append(DETAIL_TYPES)
    target["passes"].append({
        "name": "detail",
        "requestedTypes": DETAIL_TYPES,
        "status": "failed",
        "attemptErrors": [{"type": failure}],
    })
    outcome["childrenExpansion"]["partial"] = True
    outcome["childrenExpansion"]["completedCount"] = 0

    effective = reconcile_rest_diagnostics(outcome, final, require_timestamps=True)

    target = effective["childrenExpansion"]["results"][0]
    assert target["status"] == "partial"
    assert target["effectiveStatus"] == "completed"
    assert effective["childrenExpansion"]["originalPartial"] is True
    assert effective["childrenExpansion"]["completedCount"] == 0
    assert effective["childrenExpansion"]["recoveredCount"] == 1
    assert effective["partial"] is False
    child = next(item for item in effective["diagnosticRecovery"]["devices"] if item["extAddress"] == CHILD)
    assert child["fields"]["macCounters"] == {
        "availability": "unavailable", "reason": failure
    }


def test_changed_identity_in_later_detail_is_not_recovered() -> None:
    outcome, final = _fixture()
    target = outcome["childrenExpansion"]["results"][0]
    target["status"] = "partial"
    target["selectedPass"] = "fast"
    target["reasonCode"] = "identity_changed"
    target["passes"].append({
        "name": "detail",
        "requestedTypes": DETAIL_TYPES,
        "status": "failed",
        "attemptErrors": [{"type": "_RlocIdentityError"}],
    })
    outcome["childrenExpansion"]["partial"] = True

    effective = reconcile_rest_diagnostics(outcome, final, require_timestamps=True)

    assert effective["partial"] is True
    assert effective["deviceResults"][1]["status"] == "skipped"
    assert "effectiveStatus" not in effective["childrenExpansion"]["results"][0]


def test_persisted_recovery_metadata_is_not_its_own_proof() -> None:
    outcome, final = _fixture()
    recovered = reconcile_rest_diagnostics(outcome, final, require_timestamps=True)
    recovered["deviceResults"][1].pop("originalStatus")

    effective = reconcile_rest_diagnostics(
        recovered, final, require_timestamps=True, allow_recovery=False
    )

    assert effective["partial"] is True
    assert effective["deviceResults"][1]["status"] == "skipped"
    assert effective["deviceResults"][0]["status"] == "partial"
    assert effective["diagnosticRecovery"]["unresolved"]


@pytest.mark.parametrize(
    ("damage", "recovered"),
    [
        ("none", True),
        ("missing-sidecar", False),
        ("unobserved-sidecar", False),
        ("wrong-digest", False),
        ("different-network", False),
        ("wrong-expected-network", False),
        ("missing-scope-digest", False),
    ],
)
def test_cached_recovery_requires_matching_digest_bound_scopes(damage: str, recovered: bool) -> None:
    outcome, final = _fixture()
    outcome_digest, diagnostics_digest = "a" * 64, "b" * 64
    outcome_scope = {
        "extPanId": "1234567890abcdef",
        "provenance": "observed",
        "snapshotSha256": outcome_digest,
    }
    diagnostics_scope = {
        "extPanId": "1234567890abcdef",
        "provenance": "observed",
        "snapshotSha256": diagnostics_digest,
    }
    scope_digest = "c" * 64
    expected_network = "extpan:1234567890abcdef"
    if damage == "missing-sidecar":
        outcome_scope = None
    elif damage == "unobserved-sidecar":
        outcome_scope["provenance"] = "operator"
    elif damage == "wrong-digest":
        diagnostics_scope["snapshotSha256"] = "d" * 64
    elif damage == "different-network":
        diagnostics_scope["extPanId"] = "fedcba0987654321"
    elif damage == "wrong-expected-network":
        expected_network = "extpan:fedcba0987654321"
    elif damage == "missing-scope-digest":
        scope_digest = None

    effective = reconcile_bound_rest_diagnostics(
        outcome,
        final,
        outcome_digest=outcome_digest,
        diagnostics_digest=diagnostics_digest,
        outcome_scope=outcome_scope,
        diagnostics_scope=diagnostics_scope,
        outcome_scope_digest=scope_digest,
        diagnostics_scope_digest="e" * 64,
        expected_network=expected_network,
    )

    assert effective["partial"] is not recovered
    assert effective["diagnosticRecovery"]["provenance"]["bindingStatus"] == (
        "verified" if recovered else "unverified"
    )


def test_completed_baseline_does_not_require_new_recovery_proof() -> None:
    outcome = {
        "items": [],
        "deviceResults": [{"deviceId": "old-target", "status": "completed"}],
        "partial": False,
        "completedAt": "2026-10-30T11:01:00+00:00",
    }
    assert reconcile_rest_diagnostics(outcome, allow_recovery=False)["partial"] is False


@pytest.mark.parametrize("case", ["missing-results", "missing-issues", "unexplained-partial"])
def test_malformed_or_unexplained_expansion_stays_incomplete(case: str) -> None:
    outcome, final = _fixture()
    expansion = outcome["childrenExpansion"]
    if case == "missing-results":
        expansion.pop("results")
    elif case == "missing-issues":
        expansion.pop("issues")
    else:
        expansion["partial"] = True

    effective = reconcile_rest_diagnostics(outcome, final, require_timestamps=True)

    assert effective["partial"] is True
    assert effective["childrenExpansion"]["partial"] is True


@pytest.mark.parametrize(
    ("table", "valid"),
    [
        ([], True),
        ([{"childId": 42}, {"childId": 42}], True),
        ([{"childId": 42}, {"childId": 42, "mode": "different"}], False),
        ([{"childId": 0}], False),
        ([{"childId": 512}], False),
        ([{"childId": True}], False),
        (None, False),
        ({}, False),
    ],
)
def test_child_table_validation(table: object, valid: bool) -> None:
    assert valid_child_table(table) is valid
