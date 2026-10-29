from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import otbr_restapi_cli as cli_module
from otbr_restapi_diagnostics import use_progressive_fallback
from otbr_restapi_util import (
    ActionStatus,
    BASIC_DIAGNOSTIC_TLVS,
    CHILD_DETAILED_DIAGNOSTIC_TLVS,
    CHILD_MEDIUM_DIAGNOSTIC_TLVS,
    OTBRActionFailedError,
    OTBRActionTimeoutError,
    OTBRHTTPError,
    OTBRIndeterminateEnqueueError,
    OTBRInvalidResponseError,
    OTBRRestApiClient,
    OTBRUsageError,
    RECOMMENDED_DIAGNOSTIC_TLVS,
    ROUTER_MEDIUM_DIAGNOSTIC_TLVS,
)


def completed_action(action_id: str = "action-1", diagnostic_id: str | None = None):
    action = {"id": action_id, "status": ActionStatus.COMPLETED}
    if diagnostic_id is not None:
        action["relationships"] = {
            "result": {"data": {"type": "diagnostics", "id": diagnostic_id}}
        }
    return action


def test_completed_discovery_returns_structured_outcome(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    monkeypatch.setattr(
        client,
        "trigger_and_wait_device_collection",
        lambda **kwargs: completed_action(),
    )
    monkeypatch.setattr(
        client,
        "list_devices",
        lambda **kwargs: [{"id": "96518e5497d5b9f3", "role": "router"}],
    )

    outcome = client.fetch_device_collection()

    assert outcome["partial"] is False
    assert outcome["status"] == "completed"
    assert outcome["action"]["id"] == "action-1"
    assert outcome["attempts"] == 1
    assert outcome["deviceCountTarget"] == 255
    assert outcome["freshness"]["stalePossible"] is False
    assert outcome["elapsed"] >= 0


def test_discovery_retries_only_known_terminal_failure(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    actions = iter(
        [
            {"id": "action-1", "status": ActionStatus.STOPPED},
            {"id": "action-2", "status": ActionStatus.COMPLETED},
        ]
    )
    trigger = MagicMock(side_effect=lambda **kwargs: next(actions))
    monkeypatch.setattr(client, "trigger_and_wait_device_collection", trigger)
    monkeypatch.setattr(client, "list_devices", lambda **kwargs: [])

    outcome = client.fetch_device_collection(whole_action_attempts=2)

    assert outcome["partial"] is False
    assert outcome["attempts"] == 2
    assert trigger.call_count == 2


def test_discovery_timeout_is_not_retried(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    timeout = OTBRActionTimeoutError(
        "timed out",
        action_id="action-1",
        status="active",
        action={"id": "action-1", "status": "active"},
    )
    trigger = MagicMock(side_effect=timeout)
    monkeypatch.setattr(client, "trigger_and_wait_device_collection", trigger)
    monkeypatch.setattr(client, "list_devices", lambda **kwargs: [{"id": "cached"}])

    outcome = client.fetch_device_collection(whole_action_attempts=3)

    assert outcome["partial"] is True
    assert outcome["status"] == "active"
    assert outcome["error"]["type"] == "OTBRActionTimeoutError"
    assert outcome["freshness"]["stalePossible"] is True
    assert trigger.call_count == 1


def test_indeterminate_enqueue_returns_partial_without_retry(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    cause = OTBRHTTPError(
        500,
        "Internal Server Error",
        "http://example.test/api/actions",
    )
    trigger = MagicMock(
        side_effect=OTBRIndeterminateEnqueueError("indeterminate", cause)
    )
    monkeypatch.setattr(client, "trigger_and_wait_device_collection", trigger)
    monkeypatch.setattr(
        client,
        "list_devices",
        lambda **kwargs: [{"id": "cached-device"}],
    )

    outcome = client.fetch_device_collection(whole_action_attempts=3)

    assert outcome["partial"] is True
    assert outcome["status"] == "indeterminate_enqueue"
    assert outcome["error"]["type"] == "OTBRIndeterminateEnqueueError"
    assert outcome["items"] == [{"id": "cached-device"}]
    assert trigger.call_count == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"device_count": 0},
        {"device_count": 256},
        {"max_age": -1},
        {"max_retries": -1},
        {"max_retries": 256},
        {"whole_action_attempts": 0},
    ],
)
def test_discovery_rejects_invalid_numeric_inputs(kwargs) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")

    with pytest.raises(OTBRUsageError):
        client.fetch_device_collection(**kwargs)


def test_single_device_diagnostic_uses_exact_action_result_uuid(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    monkeypatch.setattr(
        client,
        "run_action",
        lambda *args, **kwargs: completed_action("action-1", "diagnostic-7"),
    )
    get_diagnostic = MagicMock(
        return_value={"id": "diagnostic-7", "created": "2026-07-25T12:00:00Z"}
    )
    monkeypatch.setattr(client, "get_diagnostic", get_diagnostic)
    delete_all = MagicMock()
    monkeypatch.setattr(client, "delete_all_diagnostics", delete_all)

    context = client.fetch_device_diagnostics(
        "96518e5497d5b9f3", return_context=True
    )

    assert context["diagnosticId"] == "diagnostic-7"
    assert context["action"]["id"] == "action-1"
    get_diagnostic.assert_called_once_with("diagnostic-7", raw=False)
    delete_all.assert_not_called()


def test_diagnostic_sweep_records_roles_duplicates_malformed_and_failures(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    delete_all = MagicMock()
    monkeypatch.setattr(client, "delete_all_diagnostics", delete_all)
    calls: list[tuple[str, dict]] = []

    def fetch(device_id: str, **kwargs):
        calls.append((device_id, kwargs))
        if device_id == "2222222222222222":
            raise OTBRActionTimeoutError(
                "child timed out",
                action_id="child-action",
                status="active",
                action={"id": "child-action", "status": "active"},
            )
        diagnostic_id = f"diag-{device_id[:2]}"
        return {
            "item": {
                "id": diagnostic_id,
                "created": "2026-07-25T12:00:00Z",
            },
            "action": completed_action(f"action-{device_id[:2]}", diagnostic_id),
            "diagnosticId": diagnostic_id,
        }

    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)
    devices = [
        {"id": "1111111111111111", "role": "router"},
        {"id": "2222222222222222", "role": "child"},
        {"id": "3333333333333333", "role": "reed"},
        {"id": "1111111111111111", "role": "router"},
        {"id": "not-hex", "role": "child"},
    ]

    outcome = client.fetch_all_devices_diagnostics(
        devices,
        clear_diagnostics=True,
    )

    assert [item["id"] for item in outcome["items"]] == ["diag-11", "diag-33"]
    assert outcome["partial"] is True
    assert outcome["clearedDiagnostics"] is True
    assert outcome["inputCount"] == 5
    assert outcome["queriedCount"] == 3
    assert outcome["attemptedCount"] == 3
    assert [record["status"] for record in outcome["deviceResults"]] == [
        "skipped",
        "malformed",
        "completed",
        "failed",
        "completed",
    ]
    router_call = next(kwargs for device_id, kwargs in calls if device_id.startswith("11"))
    child_call = next(kwargs for device_id, kwargs in calls if device_id.startswith("22"))
    reed_call = next(kwargs for device_id, kwargs in calls if device_id.startswith("33"))
    assert router_call["task_timeout"] == 15
    assert child_call["task_timeout"] == 30
    assert reed_call["task_timeout"] == 15
    delete_all.assert_called_once_with()


@pytest.mark.parametrize("policy", ["legacy", "mode-aware"])
@pytest.mark.parametrize("clear_diagnostics", [True, False])
def test_zero_iid_extended_sweep_skips_before_actions_and_preserves_callbacks(
    monkeypatch, policy, clear_diagnostics, caplog
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    fetch = MagicMock()
    mode_aware_fetch = MagicMock()
    delete_all = MagicMock()
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)
    monkeypatch.setattr(
        client, "_fetch_mode_aware_diagnostic_attempts", mode_aware_fetch
    )
    monkeypatch.setattr(client, "delete_all_diagnostics", delete_all)
    progress = []
    checkpoints = []
    pass_checkpoints = []
    devices = [
        {
            "id": "1111111111111111",
            "role": "child",
            "mode": {"fullThreadDevice": False},
            "mlEidIid": "0000000000000000",
        },
        {
            "id": "1111111111111111",
            "role": "router",
            "mlEidIid": "1234567890abcdef",
        },
        {
            "id": "2222222222222222",
            "role": "router",
            "mode": {"device": "FTD"},
            "mlEidIid": "0000000000000000",
        },
        {
            "id": "3333333333333333",
            "role": "reed",
            "mlEidIid": "0000000000000000",
        },
        {
            "id": "4444444444444444",
            "mlEidIid": "0000000000000000",
        },
        {
            "id": "5555555555555555",
            "role": "child",
            "mode": {"fullThreadDevice": False, "device": "FTD"},
            "mlEidIid": "0000000000000000",
        },
        {"id": "malformed"},
    ]
    original_devices = [dict(device) for device in devices]

    outcome = client.fetch_all_devices_diagnostics(
        devices,
        child_collection_policy=policy,
        clear_diagnostics=clear_diagnostics,
        skip_on_failure=False,
        on_progress=lambda *args: progress.append(args),
        on_checkpoint=lambda *args: checkpoints.append(args),
        on_pass_checkpoint=lambda *args: pass_checkpoints.append(args),
    )

    fetch.assert_not_called()
    mode_aware_fetch.assert_not_called()
    delete_all.assert_not_called()
    assert devices == original_devices
    assert outcome["items"] == []
    assert outcome["partial"] is True
    assert outcome["clearedDiagnostics"] is False
    assert outcome["inputCount"] == 7
    assert outcome["queriedCount"] == 5
    assert outcome["attemptedCount"] == 0
    assert [item["status"] for item in outcome["deviceResults"]] == [
        "skipped",
        "malformed",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
    ]
    skipped = outcome["deviceResults"][-5:]
    assert [item["skipReasonCode"] for item in skipped] == [
        "unresolved_mesh_local_iid"
    ] * 5
    assert skipped[0]["deviceMode"] == {"fullThreadDevice": False}
    assert skipped[0]["attempts"] == 0
    assert skipped[0]["attemptedTypes"] == []
    assert skipped[0]["passes"] == []
    assert all(item["elapsed"] >= 0 for item in skipped)
    assert [event[2] for event in progress] == [
        "1111111111111111",
        "2222222222222222",
        "3333333333333333",
        "4444444444444444",
        "5555555555555555",
    ]
    assert [event[4] for event in progress] == ["skipped"] * 5
    assert [event[4] for event in checkpoints] == ["skipped"] * 5
    assert pass_checkpoints == []
    assert "unresolved_mesh_local_iid" in caplog.text


@pytest.mark.parametrize(
    ("iid", "destination_type"),
    [
        ("0000000000000000", "mleid"),
        ("0000000000000000", "rloc"),
        ("0000000000000001", "extended"),
        (None, "extended"),
        ("NULL", "extended"),
        ("ID_ONLY", "extended"),
        ("", "extended"),
        ("000000000000000", "extended"),
        (0, "extended"),
    ],
)
def test_zero_iid_guard_only_blocks_canonical_extended_targets(
    monkeypatch, iid, destination_type
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    fetch = MagicMock(
        return_value={
            "item": {"id": "diag-1"},
            "action": completed_action("action-1", "diag-1"),
            "diagnosticId": "diag-1",
        }
    )
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)
    device_record: dict[str, object] = {
        "id": "1111111111111111",
        "role": "router",
    }
    if iid == "ID_ONLY":
        device: dict[str, object] | str = "1111111111111111"
    elif iid == "NULL":
        device_record["mlEidIid"] = None
        device = device_record
    else:
        if iid is not None:
            device_record["mlEidIid"] = iid
        device = device_record

    outcome = client.fetch_all_devices_diagnostics(
        [device],
        destination_type=destination_type,
    )

    fetch.assert_called_once()
    assert outcome["deviceResults"][0]["status"] == "completed"
    assert "skipReasonCode" not in outcome["deviceResults"][0]
    assert outcome["attemptedCount"] == 1


def test_mixed_zero_and_addressable_targets_clear_and_count_real_attempts(
    monkeypatch,
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    fetch = MagicMock(
        return_value={
            "item": {"id": "diag-2"},
            "action": completed_action("action-2", "diag-2"),
            "diagnosticId": "diag-2",
        }
    )
    delete_all = MagicMock()
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)
    monkeypatch.setattr(client, "delete_all_diagnostics", delete_all)

    outcome = client.fetch_all_devices_diagnostics(
        [
            {
                "id": "1111111111111111",
                "mlEidIid": "0000000000000000",
            },
            {
                "id": "2222222222222222",
                "mlEidIid": "1234567890abcdef",
            },
        ],
        clear_diagnostics=True,
    )

    delete_all.assert_called_once_with()
    fetch.assert_called_once()
    assert outcome["partial"] is True
    assert outcome["clearedDiagnostics"] is True
    assert outcome["queriedCount"] == 2
    assert outcome["attemptedCount"] == 1
    assert [item["status"] for item in outcome["deviceResults"]] == [
        "skipped",
        "completed",
    ]


def test_terminal_diagnostic_failure_retries_only_with_explicit_fallback(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    failure = OTBRActionFailedError(
        "failed",
        action_id="action-1",
        status="failed",
        action={"id": "action-1", "status": "failed"},
    )
    fetch = MagicMock(
        side_effect=[
            failure,
            {
                "item": {"id": "diag-1"},
                "action": completed_action("action-2", "diag-1"),
                "diagnosticId": "diag-1",
            },
        ]
    )
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_all_devices_diagnostics(
        ["1111111111111111"],
        fallback_types=["extAddress"],
    )

    assert outcome["partial"] is True
    assert outcome["deviceResults"][0]["status"] == "partial"
    assert outcome["deviceResults"][0]["attempts"] == 2
    assert fetch.call_count == 2


def test_completed_diagnostic_without_result_retries_with_explicit_fallback(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    fetch = MagicMock(
        side_effect=[
            OTBRInvalidResponseError("Completed action action-1 has no result relationship"),
            {
                "item": {"id": "diag-1"},
                "action": completed_action("action-2", "diag-1"),
                "diagnosticId": "diag-1",
            },
        ]
    )
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_all_devices_diagnostics(
        ["1111111111111111"],
        fallback_types=["extAddress"],
    )

    assert outcome["partial"] is True
    assert outcome["deviceResults"][0]["status"] == "partial"
    assert outcome["deviceResults"][0]["attempts"] == 2
    assert fetch.call_count == 2
    assert fetch.call_args_list[1].kwargs["types"] == ["extAddress"]


@pytest.mark.parametrize(
    ("role", "expected_type_sets"),
    [
        (
            "router",
            [
                RECOMMENDED_DIAGNOSTIC_TLVS,
                ROUTER_MEDIUM_DIAGNOSTIC_TLVS,
                BASIC_DIAGNOSTIC_TLVS,
            ],
        ),
        (
            "child",
            [
                CHILD_DETAILED_DIAGNOSTIC_TLVS,
                CHILD_MEDIUM_DIAGNOSTIC_TLVS,
                BASIC_DIAGNOSTIC_TLVS,
            ],
        ),
    ],
)
def test_progressive_diagnostic_fallback_recovers_with_role_specific_basic_tlvs(
    monkeypatch, role, expected_type_sets
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    fetch = MagicMock(
        side_effect=[
            OTBRInvalidResponseError("first set returned no result"),
            OTBRActionFailedError(
                "second set failed", action_id="action-medium", status="failed"
            ),
            {
                "item": {"id": "diag-basic"},
                "action": completed_action("action-basic", "diag-basic"),
                "diagnosticId": "diag-basic",
            },
        ]
    )
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_all_devices_diagnostics(
        [{"id": "1111111111111111", "role": role}],
        progressive_fallback=True,
    )

    result = outcome["deviceResults"][0]
    assert outcome["partial"] is True
    assert result["status"] == "partial"
    assert result["attempts"] == 3
    assert result["attemptedTypes"] == expected_type_sets
    assert result["successfulTypes"] == BASIC_DIAGNOSTIC_TLVS
    assert result["fallbackRecovered"] is True
    assert [call.kwargs["types"] for call in fetch.call_args_list] == expected_type_sets


@pytest.mark.parametrize(
    ("role", "expected_type_sets"),
    [
        (
            "router",
            [RECOMMENDED_DIAGNOSTIC_TLVS, ROUTER_MEDIUM_DIAGNOSTIC_TLVS],
        ),
        (
            "child",
            [CHILD_DETAILED_DIAGNOSTIC_TLVS, CHILD_MEDIUM_DIAGNOSTIC_TLVS],
        ),
    ],
)
def test_progressive_diagnostic_can_skip_basic_fallback(
    monkeypatch, role, expected_type_sets
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    errors = [
        OTBRInvalidResponseError("initial TLVs returned no result"),
        OTBRActionFailedError(
            "medium TLVs failed", action_id="action-medium", status="failed"
        ),
    ]
    fetch = MagicMock(side_effect=errors)
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_all_devices_diagnostics(
        [{"id": "1111111111111111", "role": role}],
        progressive_fallback=True,
        include_basic_fallback=False,
    )

    result = outcome["deviceResults"][0]
    assert outcome["partial"] is True
    assert result["status"] == "failed"
    assert result["attempts"] == 2
    assert result["attemptedTypes"] == expected_type_sets
    assert [call.kwargs["types"] for call in fetch.call_args_list] == expected_type_sets


def test_mode_aware_policy_selects_exact_mtd_and_ftd_tlv_sets(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    calls = []

    def fetch(device_id, **kwargs):
        calls.append((device_id, kwargs))
        diagnostic_id = f"diag-{device_id[-1]}"
        return {
            "item": {"id": diagnostic_id},
            "action": completed_action(f"action-{device_id[-1]}", diagnostic_id),
            "diagnosticId": diagnostic_id,
        }

    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)
    devices = [
        {
            "id": "1111111111111111",
            "role": "child",
            "mode": {
                "fullThreadDevice": False,
                "device": "MTD",
                "rxOnWhenIdle": False,
            },
        },
        {
            "id": "2222222222222222",
            "role": "child",
            "mode": {"fullThreadDevice": True, "device": "FTD"},
        },
    ]

    outcome = client.fetch_all_devices_diagnostics(
        devices,
        child_collection_policy="mode-aware",
        children_fetch_detail=True,
    )

    assert [kwargs["types"] for _device_id, kwargs in calls] == [
        BASIC_DIAGNOSTIC_TLVS,
        CHILD_MEDIUM_DIAGNOSTIC_TLVS,
        CHILD_MEDIUM_DIAGNOSTIC_TLVS,
    ]
    assert [kwargs["task_timeout"] for _device_id, kwargs in calls] == [30, 30, 30]
    assert [record["modeClassification"] for record in outcome["deviceResults"]] == [
        "mtd",
        "ftd",
    ]
    assert [record["selectedPass"] for record in outcome["deviceResults"]] == [
        "detail",
        "medium",
    ]
    assert calls[-1][0] == "2222222222222222"
    assert all(record["status"] == "completed" for record in outcome["deviceResults"])
    assert outcome["childCollectionPolicy"] == "mode-aware"


def test_mtd_fast_checkpoint_precedes_detail_and_detail_becomes_final_item(
    monkeypatch,
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    events = []

    def fetch(device_id, **kwargs):
        pass_name = "fast" if len(events) == 0 else "detail"
        events.append(("fetch", pass_name, list(kwargs["types"])))
        diagnostic_id = f"diag-{pass_name}"
        return {
            "item": {"id": diagnostic_id},
            "action": completed_action(f"action-{pass_name}", diagnostic_id),
            "diagnosticId": diagnostic_id,
        }

    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    def checkpoint(results, _index, _total, _device_id, pass_name):
        events.append(("checkpoint", pass_name, [item["id"] for item in results]))

    outcome = client.fetch_all_devices_diagnostics(
        [
            {
                "id": "1111111111111111",
                "role": "child",
                "mode": {"device": "MTD"},
            }
        ],
        child_collection_policy="mode-aware",
        children_fetch_detail=True,
        on_pass_checkpoint=checkpoint,
    )

    assert events == [
        ("fetch", "fast", BASIC_DIAGNOSTIC_TLVS),
        ("checkpoint", "fast", ["diag-fast"]),
        ("fetch", "detail", CHILD_MEDIUM_DIAGNOSTIC_TLVS),
    ]
    assert outcome["items"] == [{"id": "diag-detail"}]
    assert outcome["deviceResults"][0]["selectedPass"] == "detail"
    assert len(outcome["items"]) == 1


def test_mode_aware_same_set_recovery_is_completed_not_fallback(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    fetch = MagicMock(
        side_effect=[
            OTBRInvalidResponseError("completed action has no result"),
            {
                "item": {"id": "diag-fast"},
                "action": completed_action("action-fast", "diag-fast"),
                "diagnosticId": "diag-fast",
            },
        ]
    )
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_all_devices_diagnostics(
        [
            {
                "id": "1111111111111111",
                "role": "child",
                "mode": {"fullThreadDevice": False},
            }
        ],
        child_collection_policy="mode-aware",
    )

    record = outcome["deviceResults"][0]
    assert outcome["partial"] is False
    assert record["status"] == "completed"
    assert record["retryRecovered"] is True
    assert record["fallbackRecovered"] is False
    assert record["passes"][0]["attempts"] == 2
    assert fetch.call_args_list[0].kwargs["types"] == BASIC_DIAGNOSTIC_TLVS
    assert fetch.call_args_list[1].kwargs["types"] == BASIC_DIAGNOSTIC_TLVS


def test_requested_mtd_detail_failure_retains_fast_result_as_partial(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    fast_context = {
        "item": {"id": "diag-fast"},
        "action": completed_action("action-fast", "diag-fast"),
        "diagnosticId": "diag-fast",
    }
    detail_failure = OTBRActionFailedError(
        "detail returned no result", action_id="detail-2", status="failed"
    )
    fetch = MagicMock(side_effect=[fast_context, detail_failure, detail_failure])
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_all_devices_diagnostics(
        [
            {
                "id": "1111111111111111",
                "role": "child",
                "mode": {"device": "MTD"},
            }
        ],
        child_collection_policy="mode-aware",
        children_fetch_detail=True,
    )

    record = outcome["deviceResults"][0]
    assert outcome["items"] == [fast_context["item"]]
    assert outcome["partial"] is True
    assert record["status"] == "partial"
    assert record["selectedPass"] == "fast"
    assert record["passes"][1]["status"] == "failed"
    assert record["passes"][1]["requestedTypes"] == CHILD_MEDIUM_DIAGNOSTIC_TLVS


def test_unsafe_mtd_fast_outcome_stops_before_detail(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    timeout = OTBRActionTimeoutError(
        "timed out", action_id="action-fast", status="active"
    )
    fetch = MagicMock(side_effect=timeout)
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_all_devices_diagnostics(
        [
            {
                "id": "1111111111111111",
                "role": "child",
                "mode": {"device": "MTD"},
            }
        ],
        child_collection_policy="mode-aware",
        children_fetch_detail=True,
    )

    assert outcome["deviceResults"][0]["status"] == "failed"
    assert outcome["deviceResults"][0]["passes"][0]["attempts"] == 1
    assert fetch.call_count == 1


def test_both_mtd_passes_disabled_is_an_explicit_skip(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    fetch = MagicMock()
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_all_devices_diagnostics(
        [
            {
                "id": "1111111111111111",
                "role": "child",
                "mode": {"device": "MTD"},
            }
        ],
        child_collection_policy="mode-aware",
        children_fetch_fast=False,
        children_fetch_detail=False,
    )

    assert outcome["partial"] is True
    assert outcome["items"] == []
    assert outcome["deviceResults"][0]["status"] == "skipped"
    assert outcome["deviceResults"][0]["skipReason"]
    fetch.assert_not_called()


def test_ftd_medium_pass_is_independent_of_disabled_mtd_passes(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    calls = []

    def fetch(device_id, **kwargs):
        calls.append((device_id, kwargs["types"]))
        return {
            "item": {"id": "diag-ftd"},
            "action": completed_action("action-ftd", "diag-ftd"),
            "diagnosticId": "diag-ftd",
        }

    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)
    outcome = client.fetch_all_devices_diagnostics(
        [
            {
                "id": "1111111111111111",
                "role": "child",
                "mode": {"fullThreadDevice": False},
            },
            {
                "id": "2222222222222222",
                "role": "child",
                "mode": {"fullThreadDevice": True},
            },
        ],
        child_collection_policy="mode-aware",
        children_fetch_fast=False,
        children_fetch_detail=False,
    )

    assert calls == [("2222222222222222", CHILD_MEDIUM_DIAGNOSTIC_TLVS)]
    assert [record["status"] for record in outcome["deviceResults"]] == [
        "skipped",
        "completed",
    ]


def test_no_fallback_keeps_both_enabled_passes_but_does_not_repeat(
    monkeypatch,
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    fast_failure = OTBRInvalidResponseError("fast result missing")
    detail_context = {
        "item": {"id": "diag-detail"},
        "action": completed_action("action-detail", "diag-detail"),
        "diagnosticId": "diag-detail",
    }
    fetch = MagicMock(side_effect=[fast_failure, detail_context])
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_all_devices_diagnostics(
        [
            {
                "id": "1111111111111111",
                "role": "child",
                "mode": {"device": "MTD"},
            }
        ],
        child_collection_policy="mode-aware",
        children_fetch_detail=True,
        child_retry_enabled=False,
    )

    record = outcome["deviceResults"][0]
    assert [call.kwargs["types"] for call in fetch.call_args_list] == [
        BASIC_DIAGNOSTIC_TLVS,
        CHILD_MEDIUM_DIAGNOSTIC_TLVS,
    ]
    assert [item["attempts"] for item in record["passes"]] == [1, 1]
    assert record["status"] == "partial"
    assert record["selectedPass"] == "detail"


def test_raw_mesh_reuse_does_not_select_mode_aware_child_fast_pass(
    monkeypatch,
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    fetch = MagicMock(
        return_value={
            "item": {"data": {"id": "raw-diagnostic"}},
            "action": completed_action("action-raw", "raw-diagnostic"),
            "diagnosticId": "raw-diagnostic",
        }
    )
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_mesh_diagnostics_all_devices(
        [
            {
                "id": "1111111111111111",
                "role": "child",
                "mode": {"fullThreadDevice": False, "device": "MTD"},
            }
        ],
        raw=True,
    )

    assert outcome["items"] == [{"data": {"id": "raw-diagnostic"}}]
    assert fetch.call_count == 1
    assert fetch.call_args.kwargs["types"] == (
        "children",
        "childIpv6Addresses",
        "routerNeighbors",
    )


def test_network_diagnostics_wrapper_forwards_selected_child_policy(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    devices = [
        {
            "id": "1111111111111111",
            "role": "child",
            "mode": {"device": "MTD"},
        }
    ]
    monkeypatch.setattr(
        client,
        "fetch_device_collection",
        lambda **_kwargs: {"items": devices, "partial": False},
    )
    batch_fetch = MagicMock(
        return_value={"items": [], "deviceResults": [], "partial": False}
    )
    monkeypatch.setattr(client, "fetch_all_devices_diagnostics", batch_fetch)

    client.fetch_network_diagnostics_all_devices(
        child_collection_policy="mode-aware",
        children_fetch_fast=False,
        children_fetch_detail=True,
        child_retry_enabled=False,
    )

    options = batch_fetch.call_args.kwargs
    assert options["child_collection_policy"] == "mode-aware"
    assert options["children_fetch_fast"] is False
    assert options["children_fetch_detail"] is True
    assert options["child_retry_enabled"] is False


@pytest.mark.parametrize(
    ("mode", "expected_warning"),
    [
        (None, "missing"),
        ({"fullThreadDevice": False, "device": "FTD"}, "conflicting"),
        ({"fullThreadDevice": "false", "device": "MTD"}, "malformed"),
        ("MTD", "malformed"),
    ],
)
def test_unknown_child_mode_warns_and_keeps_legacy_progression(
    monkeypatch, caplog, mode, expected_warning
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    fetch = MagicMock(
        side_effect=[
            OTBRInvalidResponseError("no result"),
            {
                "item": {"id": "diag-medium"},
                "action": completed_action("action-medium", "diag-medium"),
                "diagnosticId": "diag-medium",
            },
        ]
    )
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)
    device = {"id": "1111111111111111", "role": "child"}
    if mode is not None:
        device["mode"] = mode

    outcome = client.fetch_all_devices_diagnostics(
        [device],
        child_collection_policy="mode-aware",
        progressive_fallback=True,
    )

    record = outcome["deviceResults"][0]
    assert record["policy"] == "legacy-unknown-mode"
    assert record["modeClassification"] == "unknown"
    assert record["modeWarning"] == expected_warning
    assert record["status"] == "partial"
    assert fetch.call_args_list[0].kwargs["types"] == CHILD_DETAILED_DIAGNOSTIC_TLVS
    assert fetch.call_args_list[1].kwargs["types"] == CHILD_MEDIUM_DIAGNOSTIC_TLVS
    assert "legacy child diagnostic policy" in caplog.text


def test_invalid_child_poll_budget_fails_before_diagnostic_clear_or_action(
    monkeypatch,
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    clear = MagicMock()
    fetch = MagicMock()
    monkeypatch.setattr(client, "delete_all_diagnostics", clear)
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    with pytest.raises(OTBRUsageError, match="poll_timeout must be at least"):
        client.fetch_all_devices_diagnostics(
            ["1111111111111111"],
            child_task_timeout=30,
            child_poll_timeout=30,
            clear_diagnostics=True,
        )

    clear.assert_not_called()
    fetch.assert_not_called()


def test_child_pass_cli_options_keep_defaults_and_record_explicit_toggles() -> None:
    defaults = cli_module.build_parser().parse_args(
        ["diagnostics", "fetch-all"]
    )
    assert defaults.children_fetch_fast is None
    assert defaults.children_fetch_detail is None
    assert defaults.child_task_timeout == 30
    assert defaults.child_poll_timeout is None

    configured = cli_module.build_parser().parse_args(
        [
            "diagnostics",
            "fetch-all",
            "--children-fetch-fast-no",
            "--children-fetch-detail",
            "--child-task-timeout",
            "25",
            "--child-poll-timeout",
            "30",
        ]
    )
    assert configured.children_fetch_fast is False
    assert configured.children_fetch_detail is True
    assert configured.child_task_timeout == 25
    assert configured.child_poll_timeout == 30


def test_diagnostic_timeout_never_starts_fallback_action(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    timeout = OTBRActionTimeoutError(
        "timed out",
        action_id="action-1",
        status="active",
        action={"id": "action-1", "status": "active"},
    )
    fetch = MagicMock(side_effect=timeout)
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_all_devices_diagnostics(
        ["1111111111111111"],
        fallback_types=["extAddress"],
    )

    assert outcome["partial"] is True
    assert outcome["deviceResults"][0]["attempts"] == 1
    assert fetch.call_count == 1


def test_mesh_sweep_uses_structured_serialized_core(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    mesh_item = {
        "id": "diag-mesh",
        "children": [],
        "childIpv6Addresses": [],
        "routerNeighbors": [],
    }
    fetch = MagicMock(
        return_value={
            "item": mesh_item,
            "action": completed_action("action-mesh", "diag-mesh"),
            "diagnosticId": "diag-mesh",
        }
    )
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)
    delete_all = MagicMock()
    monkeypatch.setattr(client, "delete_all_diagnostics", delete_all)

    outcome = client.fetch_mesh_diagnostics_all_devices(
        [{"id": "1111111111111111", "role": "router"}],
        clear_diagnostics=True,
    )

    assert outcome["items"] == [mesh_item]
    assert outcome["partial"] is False
    assert outcome["clearedDiagnostics"] is True
    assert outcome["deviceResults"][0]["status"] == "completed"
    assert outcome["deviceResults"][0]["meshCoverage"] == [
        "children",
        "childIpv6Addresses",
        "routerNeighbors",
    ]
    assert fetch.call_count == 1
    assert fetch.call_args.kwargs["types"] == [
        "children",
        "childIpv6Addresses",
        "routerNeighbors",
    ]
    delete_all.assert_called_once()


def test_mesh_no_fallback_marks_identity_only_result_as_partial(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    fetch = MagicMock(
        return_value={
            "item": {"id": "diag-identity", "extAddress": "1111111111111111"},
            "action": completed_action("action-identity", "diag-identity"),
            "diagnosticId": "diag-identity",
        }
    )
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_mesh_diagnostics_all_devices(
        ["1111111111111111"], progressive_fallback=False
    )

    result = outcome["deviceResults"][0]
    assert outcome["items"] == []
    assert outcome["partial"] is True
    assert result["status"] == "partial"
    assert result["responsive"] is True
    assert result["meshCoverage"] == []
    assert result["attempts"] == 1
    assert result["fallbackRecovered"] is False
    assert fetch.call_count == 1
    assert fetch.call_args.kwargs["types"] == [
        "children",
        "childIpv6Addresses",
        "routerNeighbors",
    ]


def test_mesh_preserve_diagnostics_does_not_clear_collection(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    mesh_context = {
        "item": {
            "id": "diag-mesh",
            "children": [],
            "childIpv6Addresses": [],
            "routerNeighbors": [],
        },
        "action": completed_action("action-mesh", "diag-mesh"),
        "diagnosticId": "diag-mesh",
    }
    fetch = MagicMock(return_value=mesh_context)
    delete_all = MagicMock()
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)
    monkeypatch.setattr(client, "delete_all_diagnostics", delete_all)

    outcome = client.fetch_mesh_diagnostics_all_devices(
        ["1111111111111111"],
        clear_diagnostics=False,
        progressive_fallback=True,
    )

    assert outcome["clearedDiagnostics"] is False
    delete_all.assert_not_called()


def test_mesh_progressive_fallback_merges_split_tlvs(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    fetch = MagicMock(
        side_effect=[
            OTBRInvalidResponseError("combined request returned no result"),
            {
                "item": {"id": "diag-children", "children": [{"rloc16": "0x0401"}]},
                "action": completed_action("action-children", "diag-children"),
                "diagnosticId": "diag-children",
            },
            OTBRInvalidResponseError("child addresses returned no result"),
            {
                "item": {"id": "diag-neighbors", "routerNeighbors": [{"rloc16": "0x0800"}]},
                "action": completed_action("action-neighbors", "diag-neighbors"),
                "diagnosticId": "diag-neighbors",
            },
        ]
    )
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_mesh_diagnostics_all_devices(
        ["1111111111111111"], progressive_fallback=True
    )

    result = outcome["deviceResults"][0]
    assert outcome["partial"] is True
    assert result["status"] == "partial"
    assert result["responsive"] is True
    assert result["basicResponsive"] is False
    assert result["meshCoverage"] == ["children", "routerNeighbors"]
    assert outcome["items"] == [
        {
            "id": "diag-children",
            "children": [{"rloc16": "0x0401"}],
            "routerNeighbors": [{"rloc16": "0x0800"}],
        }
    ]


def test_mesh_progressive_fallback_records_basic_only_responsiveness(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    failures = [
        OTBRInvalidResponseError("no mesh result") for _ in range(4)
    ]
    basic_context = {
        "item": {"id": "diag-basic", "extAddress": "1111111111111111"},
        "action": completed_action("action-basic", "diag-basic"),
        "diagnosticId": "diag-basic",
    }
    fetch = MagicMock(side_effect=[*failures, basic_context])
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_mesh_diagnostics_all_devices(
        ["1111111111111111"], progressive_fallback=True
    )

    result = outcome["deviceResults"][0]
    assert outcome["items"] == []
    assert outcome["partial"] is True
    assert result["status"] == "partial"
    assert result["meshCoverage"] == []
    assert result["responsive"] is True
    assert result["basicResponsive"] is True
    assert fetch.call_args_list[-1].kwargs["types"] == BASIC_DIAGNOSTIC_TLVS


def test_mesh_items_only_skips_basic_probe_after_mesh_fallback_fails(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    mesh_failures = [
        OTBRInvalidResponseError("no mesh result") for _ in range(4)
    ]
    basic_context = {
        "item": {"id": "diag-basic", "extAddress": "1111111111111111"},
        "action": completed_action("action-basic", "diag-basic"),
        "diagnosticId": "diag-basic",
    }
    fetch = MagicMock(side_effect=[*mesh_failures, basic_context])
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    items = client.fetch_mesh_diagnostics_all_devices(
        ["1111111111111111"],
        progressive_fallback=True,
        items_only=True,
    )

    assert items == []
    assert [call.kwargs["types"] for call in fetch.call_args_list] == [
        ["children", "childIpv6Addresses", "routerNeighbors"],
        ["children"],
        ["childIpv6Addresses"],
        ["routerNeighbors"],
    ]


def test_mesh_items_only_preserves_mesh_item_shape(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    mesh_item = {
        "id": "diag-mesh",
        "children": [{"rloc16": "0x0401"}],
        "childIpv6Addresses": [{"rloc16": "0x0401", "addresses": []}],
        "routerNeighbors": [{"rloc16": "0x0800"}],
    }
    fetch = MagicMock(
        return_value={
            "item": mesh_item,
            "action": completed_action("action-mesh", "diag-mesh"),
            "diagnosticId": "diag-mesh",
        }
    )
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    items = client.fetch_mesh_diagnostics_all_devices(
        ["1111111111111111"],
        progressive_fallback=True,
        items_only=True,
    )

    assert items == [mesh_item]
    assert fetch.call_count == 1


def test_mesh_timeout_does_not_start_split_or_basic_fallback(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    timeout = OTBRActionTimeoutError(
        "timed out",
        action_id="action-mesh",
        status="active",
        action={"id": "action-mesh", "status": "active"},
    )
    fetch = MagicMock(side_effect=timeout)
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    outcome = client.fetch_mesh_diagnostics_all_devices(
        ["1111111111111111"], progressive_fallback=True
    )

    result = outcome["deviceResults"][0]
    assert result["status"] == "failed"
    assert result["attempts"] == 1
    assert result["responsive"] is False
    assert fetch.call_count == 1


@pytest.mark.parametrize(
    ("preset", "types", "fallback_preset", "no_fallback", "expected"),
    [
        (None, None, None, False, True),
        ("recommended", None, None, False, True),
        ("full", None, None, False, False),
        (None, ["extAddress"], None, False, False),
        ("recommended", None, "basic", False, False),
        ("recommended", None, None, True, False),
    ],
)
def test_progressive_fallback_only_applies_to_default_recommended_sweeps(
    preset, types, fallback_preset, no_fallback, expected
) -> None:
    args = type(
        "Args",
        (),
        {
            "preset": preset,
            "types": types,
            "fallback_preset": fallback_preset,
            "no_fallback": no_fallback,
        },
    )()

    assert use_progressive_fallback(args) is expected


def test_cli_discovery_forwards_safe_attempts_and_structured_mode() -> None:
    args = cli_module.build_parser().parse_args(
        [
            "devices",
            "fetch",
            "--whole-action-attempts",
            "2",
            "--structured-outcome",
        ]
    )
    args.resolved_output_path = None
    client = MagicMock()
    client._resolve_raw.return_value = False
    client.fetch_device_collection.return_value = {
        "items": [],
        "partial": False,
        "status": "completed",
    }

    result = cli_module.dispatch(client, args)

    assert result["partial"] is False
    kwargs = client.fetch_device_collection.call_args.kwargs
    assert kwargs["whole_action_attempts"] == 2
    assert kwargs["items_only"] is False


# ---------------------------------------------------------------------------
# S3-03A: --children-expand-by-rloc
# ---------------------------------------------------------------------------

import copy

from otbr_restapi_util import (
    CHILD_DETAILED_DIAGNOSTIC_TLVS as _CHILD_DETAILED,
    DestinationType,
    RLOC_EXPANSION_PROGRESS_PREFIX,
    _child_rloc_destination,
    _derive_child_rloc_targets,
    _parse_child_id,
    _parse_router_rloc16,
)

PARENT_EXT = "9af0b8a484b741ab"
OTHER_ROUTER_EXT = "1234567812345678"
MTD_MODE = {"rxOnWhenIdle": False, "fullThreadDevice": False, "device": "MTD"}
FTD_MODE = {"rxOnWhenIdle": True, "fullThreadDevice": True, "device": "FTD"}


def _parent_item(ext=PARENT_EXT, rloc16="0x3800", child_table=None):
    item = {"id": f"diag-{ext}", "extAddress": ext, "rloc16": rloc16}
    if child_table is not None:
        item["childTable"] = child_table
    return item


def _child_item(ext, rloc16):
    return {"id": f"diag-{ext}", "extAddress": ext, "rloc16": rloc16}


def _rloc_fetch(responses, calls):
    """Return a fake fetch_device_diagnostics keyed by (destination, destinationType)."""

    def fetch(destination, **kwargs):
        calls.append((destination, kwargs))
        value = responses[(destination, kwargs["destination_type"])]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, BaseException):
            raise value
        diagnostic_id = f"diag-{destination}-{len(calls)}"
        return {
            "item": copy.deepcopy(value),
            "action": completed_action(f"action-{len(calls)}", diagnostic_id),
            "diagnosticId": diagnostic_id,
        }

    return fetch


@pytest.mark.parametrize(
    ("parent_rloc16", "child_id", "child_rloc16", "destination"),
    [
        (0x9400, 53, 0x9435, "009435"),
        (0x9400, 14, 0x940E, "00940e"),
        (0x3800, 42, 0x382A, "00382a"),
    ],
)
def test_child_rloc_destination_matches_plan_examples(
    parent_rloc16, child_id, child_rloc16, destination
) -> None:
    assert _child_rloc_destination(parent_rloc16, child_id) == (
        child_rloc16,
        destination,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0x3800, (0x3800, None)),
        ("0x3800", (0x3800, None)),
        ("0x0", (0x0000, None)),
        (0xF800, (0xF800, None)),
        (0x3801, (None, "parent_rloc16_not_router")),
        ("0x382a", (None, "parent_rloc16_not_router")),
        (0xFC00, (None, "parent_router_id_out_of_range")),
        (True, (None, "invalid_parent_rloc16")),
        (14336.0, (None, "invalid_parent_rloc16")),
        ("3800", (None, "invalid_parent_rloc16")),
        ("0X3800", (None, "invalid_parent_rloc16")),
        ("0x10000", (None, "invalid_parent_rloc16")),
        (0x10000, (None, "invalid_parent_rloc16")),
        (-1024, (None, "invalid_parent_rloc16")),
        (None, (None, "invalid_parent_rloc16")),
    ],
)
def test_parent_rloc16_parsing_rejects_without_coercion(value, expected) -> None:
    assert _parse_router_rloc16(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, 1),
        (511, 511),
        (0, None),
        (512, None),
        (1023, None),
        (1024, None),
        (-1, None),
        (True, None),
        ("42", None),
        (42.0, None),
        (None, None),
    ],
)
def test_child_id_parsing_accepts_only_real_thread_child_ids(value, expected) -> None:
    assert _parse_child_id(value) == expected


def test_target_derivation_dedupes_classifies_and_does_not_mutate_inputs() -> None:
    items = [
        _parent_item(
            child_table=[
                {"childId": 42, "mode": MTD_MODE},
                {"childId": 42, "mode": dict(MTD_MODE)},
                {"childId": 7, "mode": FTD_MODE},
                {"childId": 7, "mode": MTD_MODE},
                {"childId": 0},
                {"childId": 512},
                {"childId": True},
                "not-an-entry",
                {"childId": 9, "mode": MTD_MODE},
            ]
        ),
        _parent_item(ext=OTHER_ROUTER_EXT, rloc16="0x9400", child_table=[]),
        _child_item("abababababababab", "0x3809"),
    ]
    snapshot = copy.deepcopy(items)

    targets, issues, parent_count = _derive_child_rloc_targets(items, [])

    assert items == snapshot
    assert parent_count == 2
    assert [(t.destination, t.status) for t in targets] == [
        ("00382a", None),
        ("003807", "conflict"),
        ("003809", "covered"),
    ]
    assert targets[1].conflicts == [
        {"code": "conflicting_child_mode", "childMode": MTD_MODE}
    ]
    assert targets[2].covered_ext_address == "abababababababab"
    assert [issue["code"] for issue in issues] == ["invalid_child_entry"] * 4
    assert all(issue["parentExtAddress"] == PARENT_EXT for issue in issues)
    assert [issue["entryIndex"] for issue in issues] == [4, 5, 6, 7]


def test_target_derivation_records_parent_coverage_limitations() -> None:
    items = [
        _parent_item(ext=PARENT_EXT, rloc16="0x3800"),
        _parent_item(ext=OTHER_ROUTER_EXT, rloc16="0x3801", child_table=[]),
        _parent_item(ext="5555555555555555", rloc16="0x9400", child_table="bad"),
        {"id": "no-identity"},
        _parent_item(ext="6666666666666666", rloc16="0x0400", child_table=[{"childId": 1}]),
        _parent_item(ext="7777777777777777", rloc16="0x0400", child_table=[{"childId": 2}]),
    ]
    device_results = [
        {"deviceId": "8888888888888888", "role": "router", "status": "failed"},
        {
            "deviceId": "9999999999999999",
            "role": "router",
            "status": "skipped",
            "skipReasonCode": "unresolved_mesh_local_iid",
        },
        {"deviceId": "aaaaaaaaaaaaaaaa", "role": "child", "status": "failed"},
    ]

    targets, issues, parent_count = _derive_child_rloc_targets(items, device_results)

    assert parent_count == 0
    assert [(t.destination, t.status) for t in targets] == [
        ("000401", "conflict"),
        ("000402", "conflict"),
    ]
    assert [issue["code"] for issue in issues] == [
        "parent_unavailable",
        "parent_unavailable",
        "parent_child_table_missing",
        "parent_rloc16_not_router",
        "malformed_child_table",
        "parent_evidence_unavailable",
        "conflicting_parent_identity",
    ]


def test_expansion_disabled_keeps_requested_types_and_omits_outcome(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    calls = []
    monkeypatch.setattr(
        client,
        "fetch_device_diagnostics",
        _rloc_fetch(
            {(PARENT_EXT, "extended"): _parent_item(child_table=[{"childId": 42}])},
            calls,
        ),
    )

    outcome = client.fetch_all_devices_diagnostics(
        [{"id": PARENT_EXT, "role": "router"}],
        types=["extAddress", "rloc16"],
        fallback_types=["extAddress"],
    )

    assert [kwargs["types"] for _dest, kwargs in calls] == [["extAddress", "rloc16"]]
    assert "childrenExpansion" not in outcome
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("types", "expected"),
    [
        (["extAddress", "rloc16"], ["extAddress", "rloc16", "childTable"]),
        ([0, 1, 16], [0, 1, 16]),
        (["childTable", "rloc16"], ["childTable", "rloc16"]),
    ],
)
def test_expansion_augments_parent_primary_and_fallback_types_only(
    monkeypatch, types, expected
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    calls = []
    monkeypatch.setattr(
        client,
        "fetch_device_diagnostics",
        _rloc_fetch(
            {
                (PARENT_EXT, "extended"): [
                    OTBRActionFailedError("failed", action_id="a", status="failed"),
                    _parent_item(child_table=[]),
                ],
                ("1111111111111111", "extended"): _child_item(
                    "1111111111111111", "0x3801"
                ),
            },
            calls,
        ),
    )
    original_recommended = list(RECOMMENDED_DIAGNOSTIC_TLVS)

    outcome = client.fetch_all_devices_diagnostics(
        [
            {"id": PARENT_EXT, "role": "router"},
            {"id": "1111111111111111", "role": "child"},
        ],
        types=types,
        fallback_types=["extAddress"],
        children_expand_by_rloc=True,
    )

    assert [kwargs["types"] for _dest, kwargs in calls] == [
        expected,
        ["extAddress", "childTable"],
        types,
    ]
    assert RECOMMENDED_DIAGNOSTIC_TLVS == original_recommended
    assert outcome["childrenExpansion"]["targetCount"] == 0
    assert outcome["childrenExpansion"]["partial"] is False


def test_expansion_queries_uncovered_children_by_rloc_with_mode_policies(
    monkeypatch,
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    calls = []
    zero_iid_child = "2222222222222222"
    responses = {
        (PARENT_EXT, "extended"): _parent_item(
            child_table=[
                {"childId": 42, "mode": MTD_MODE, "linkQuality": 3},
                {"childId": 7, "mode": FTD_MODE},
                {"childId": 9},
                {"childId": 1, "mode": MTD_MODE},
            ]
        ),
        ("1111111111111111", "extended"): _child_item("1111111111111111", "0x3801"),
        ("00382a", "rloc"): _child_item(zero_iid_child, "0x382a"),
        ("003807", "rloc"): _child_item("3333333333333333", "0x3807"),
        ("003809", "rloc"): _child_item("4444444444444444", "0x3809"),
    }
    monkeypatch.setattr(client, "fetch_device_diagnostics", _rloc_fetch(responses, calls))
    clear = MagicMock()
    monkeypatch.setattr(client, "delete_all_diagnostics", clear)
    progress = []

    outcome = client.fetch_all_devices_diagnostics(
        [
            {"id": PARENT_EXT, "role": "leader"},
            {"id": "1111111111111111", "role": "child", "mode": MTD_MODE},
            {
                "id": zero_iid_child,
                "role": "child",
                "mode": MTD_MODE,
                "mlEidIid": "0000000000000000",
            },
        ],
        clear_diagnostics=True,
        progressive_fallback=True,
        child_collection_policy="mode-aware",
        children_expand_by_rloc=True,
        on_progress=lambda *args: progress.append(args[:3] + args[4:]),
    )

    clear.assert_called_once()
    rloc_calls = [
        (dest, kwargs["destination_type"], kwargs["types"], kwargs["task_timeout"])
        for dest, kwargs in calls
        if kwargs["destination_type"] == DestinationType.RLOC
    ]
    assert rloc_calls == [
        ("00382a", "rloc", BASIC_DIAGNOSTIC_TLVS, 30),
        ("003807", "rloc", CHILD_MEDIUM_DIAGNOSTIC_TLVS, 30),
        ("003809", "rloc", _CHILD_DETAILED, 30),
    ]
    assert len(calls) == 5
    assert [item["extAddress"] for item in outcome["items"]] == [
        PARENT_EXT,
        "1111111111111111",
        zero_iid_child,
        "3333333333333333",
        "4444444444444444",
    ]
    assert outcome["deviceResults"][2]["skipReasonCode"] == "unresolved_mesh_local_iid"
    assert outcome["attemptedCount"] == 2
    assert outcome["queriedCount"] == 3
    expansion = outcome["childrenExpansion"]
    assert {
        key: expansion[key]
        for key in (
            "enabled",
            "partial",
            "parentCount",
            "targetCount",
            "attemptedCount",
            "completedCount",
            "coveredCount",
        )
    } == {
        "enabled": True,
        "partial": False,
        "parentCount": 1,
        "targetCount": 4,
        "attemptedCount": 3,
        "completedCount": 3,
        "coveredCount": 1,
    }
    assert outcome["partial"] is True
    records = {record["destination"]: record for record in expansion["results"]}
    assert records["00382a"]["extAddress"] == zero_iid_child
    assert records["00382a"]["parentExtAddress"] == PARENT_EXT
    assert records["00382a"]["parentRloc16"] == "0x3800"
    assert records["00382a"]["childMode"] == MTD_MODE
    assert records["00382a"]["selectedPass"] == "fast"
    assert records["003809"]["policy"] == "legacy-unknown-mode"
    assert records["003801"]["status"] == "covered"
    assert all("deviceId" not in record for record in expansion["results"])
    assert progress[-3:] == [
        (1, 3, f"{RLOC_EXPANSION_PROGRESS_PREFIX}00382a", "completed"),
        (2, 3, f"{RLOC_EXPANSION_PROGRESS_PREFIX}003807", "completed"),
        (3, 3, f"{RLOC_EXPANSION_PROGRESS_PREFIX}003809", "completed"),
    ]


def test_expansion_does_not_recurse_into_child_tables(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    calls = []
    child_with_table = _child_item("3333333333333333", "0x382a")
    child_with_table["childTable"] = [{"childId": 5}]
    responses = {
        (PARENT_EXT, "extended"): _parent_item(child_table=[{"childId": 42, "mode": FTD_MODE}]),
        ("00382a", "rloc"): child_with_table,
    }
    monkeypatch.setattr(client, "fetch_device_diagnostics", _rloc_fetch(responses, calls))

    outcome = client.fetch_all_devices_diagnostics(
        [PARENT_EXT],
        child_collection_policy="mode-aware",
        children_expand_by_rloc=True,
    )

    assert [dest for dest, _kwargs in calls] == [PARENT_EXT, "00382a"]
    assert outcome["childrenExpansion"]["targetCount"] == 1


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (_child_item("3333333333333333", "0x3829"), "rloc16_mismatch"),
        ({"id": "x", "rloc16": "0x382a"}, "identity_missing"),
        (_child_item("0000000000000000", "0x382a"), "identity_missing"),
        (_child_item(PARENT_EXT, "0x382a"), "identity_conflict"),
    ],
)
def test_expansion_identity_validation_blocks_publication(
    monkeypatch, response, reason
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    calls = []
    responses = {
        (PARENT_EXT, "extended"): _parent_item(child_table=[{"childId": 42, "mode": MTD_MODE}]),
        ("00382a", "rloc"): response,
    }
    monkeypatch.setattr(client, "fetch_device_diagnostics", _rloc_fetch(responses, calls))
    checkpoints = []

    outcome = client.fetch_all_devices_diagnostics(
        [PARENT_EXT],
        child_collection_policy="mode-aware",
        children_expand_by_rloc=True,
        on_pass_checkpoint=lambda results, *_args: checkpoints.append(list(results)),
    )

    record = outcome["childrenExpansion"]["results"][0]
    assert record["status"] == "invalid_response"
    assert record["reasonCode"] == reason
    assert record["attempts"] == 1
    assert "extAddress" not in record
    assert outcome["items"] == [_parent_item(child_table=[{"childId": 42, "mode": MTD_MODE}])]
    assert checkpoints == []
    assert outcome["partial"] is True
    assert len(calls) == 2


def test_expansion_detail_failure_or_identity_change_keeps_validated_fast(
    monkeypatch,
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    calls = []
    fast = _child_item("3333333333333333", "0x382a")
    responses = {
        (PARENT_EXT, "extended"): _parent_item(child_table=[{"childId": 42, "mode": MTD_MODE}]),
        ("00382a", "rloc"): [fast, _child_item("4444444444444444", "0x382a")],
    }
    monkeypatch.setattr(client, "fetch_device_diagnostics", _rloc_fetch(responses, calls))
    checkpoints = []

    outcome = client.fetch_all_devices_diagnostics(
        [PARENT_EXT],
        child_collection_policy="mode-aware",
        children_fetch_detail=True,
        children_expand_by_rloc=True,
        on_pass_checkpoint=lambda results, _i, _t, label, pass_name: checkpoints.append(
            (label, pass_name, [item["extAddress"] for item in results])
        ),
    )

    record = outcome["childrenExpansion"]["results"][0]
    assert record["status"] == "partial"
    assert record["selectedPass"] == "fast"
    assert record["reasonCode"] == "identity_changed"
    assert record["extAddress"] == "3333333333333333"
    assert outcome["items"][-1] == fast
    assert checkpoints == [
        (f"{RLOC_EXPANSION_PROGRESS_PREFIX}00382a", "fast", [PARENT_EXT, "3333333333333333"])
    ]
    assert [kwargs["types"] for _dest, kwargs in calls[1:]] == [
        BASIC_DIAGNOSTIC_TLVS,
        CHILD_MEDIUM_DIAGNOSTIC_TLVS,
    ]
    assert outcome["childrenExpansion"]["partial"] is True


def test_expansion_unresolved_action_stops_later_children(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    calls = []
    responses = {
        (PARENT_EXT, "extended"): _parent_item(
            child_table=[
                {"childId": 42, "mode": FTD_MODE},
                {"childId": 43, "mode": FTD_MODE},
            ]
        ),
        ("00382a", "rloc"): OTBRActionTimeoutError(
            "timed out", action_id="a", status="active"
        ),
        ("00382b", "rloc"): _child_item("3333333333333333", "0x382b"),
    }
    monkeypatch.setattr(client, "fetch_device_diagnostics", _rloc_fetch(responses, calls))
    progress = []

    outcome = client.fetch_all_devices_diagnostics(
        [PARENT_EXT],
        child_collection_policy="mode-aware",
        children_expand_by_rloc=True,
        on_progress=lambda idx, total, label, _elapsed, status: progress.append(
            (idx, total, label, status)
        ),
    )

    assert [dest for dest, _kwargs in calls] == [PARENT_EXT, "00382a"]
    results = outcome["childrenExpansion"]["results"]
    assert [(r["status"], r.get("reasonCode")) for r in results] == [
        ("failed", None),
        ("not_attempted", "unresolved_prior_action"),
    ]
    assert results[0]["attempts"] == 1
    assert progress[-1] == (
        2,
        2,
        f"{RLOC_EXPANSION_PROGRESS_PREFIX}00382b",
        "not_attempted",
    )


def test_unresolved_base_action_prevents_any_expansion_action(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    calls = []
    responses = {
        (PARENT_EXT, "extended"): _parent_item(child_table=[{"childId": 42, "mode": FTD_MODE}]),
        (OTHER_ROUTER_EXT, "extended"): OTBRIndeterminateEnqueueError(
            "indeterminate",
            OTBRHTTPError(500, "Internal Server Error", "http://example.test/api/actions"),
        ),
    }
    monkeypatch.setattr(client, "fetch_device_diagnostics", _rloc_fetch(responses, calls))

    outcome = client.fetch_all_devices_diagnostics(
        [
            {"id": PARENT_EXT, "role": "router"},
            {"id": OTHER_ROUTER_EXT, "role": "router"},
        ],
        children_expand_by_rloc=True,
    )

    assert [dest for dest, _kwargs in calls] == [PARENT_EXT, OTHER_ROUTER_EXT]
    expansion = outcome["childrenExpansion"]
    assert expansion["attemptedCount"] == 0
    assert expansion["results"][0]["status"] == "not_attempted"
    assert {issue["code"] for issue in expansion["issues"]} == {
        "parent_unavailable",
        "unresolved_prior_action",
    }
    assert expansion["partial"] is True


def test_expansion_known_terminal_failure_advances_and_fail_fast_raises(
    monkeypatch,
) -> None:
    def build(skip_on_failure):
        client = OTBRRestApiClient(base_url="http://example.test")
        calls = []
        responses = {
            (PARENT_EXT, "extended"): _parent_item(
                child_table=[
                    {"childId": 42, "mode": FTD_MODE},
                    {"childId": 43, "mode": FTD_MODE},
                ]
            ),
            ("00382a", "rloc"): OTBRActionFailedError(
                "failed", action_id="a", status="failed"
            ),
            ("00382b", "rloc"): _child_item("3333333333333333", "0x382b"),
        }
        monkeypatch.setattr(client, "fetch_device_diagnostics", _rloc_fetch(responses, calls))
        return client, calls

    client, calls = build(True)
    outcome = client.fetch_all_devices_diagnostics(
        [PARENT_EXT],
        child_collection_policy="mode-aware",
        children_expand_by_rloc=True,
    )
    assert [dest for dest, _kwargs in calls] == [PARENT_EXT, "00382a", "00382a", "00382b"]
    assert [r["status"] for r in outcome["childrenExpansion"]["results"]] == [
        "failed",
        "completed",
    ]

    client, calls = build(False)
    with pytest.raises(OTBRActionFailedError):
        client.fetch_all_devices_diagnostics(
            [PARENT_EXT],
            child_collection_policy="mode-aware",
            children_expand_by_rloc=True,
            skip_on_failure=False,
        )
    assert [dest for dest, _kwargs in calls] == [PARENT_EXT, "00382a", "00382a"]


def test_expansion_disabled_passes_no_retry_and_custom_policy(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    calls = []
    failure = OTBRActionFailedError("failed", action_id="a", status="failed")
    responses = {
        (PARENT_EXT, "extended"): _parent_item(
            child_table=[
                {"childId": 42, "mode": MTD_MODE},
                {"childId": 43, "mode": FTD_MODE},
            ]
        ),
        ("00382b", "rloc"): failure,
    }
    monkeypatch.setattr(client, "fetch_device_diagnostics", _rloc_fetch(responses, calls))

    outcome = client.fetch_all_devices_diagnostics(
        [PARENT_EXT],
        child_collection_policy="mode-aware",
        children_fetch_fast=False,
        children_fetch_detail=False,
        child_retry_enabled=False,
        children_expand_by_rloc=True,
    )

    results = outcome["childrenExpansion"]["results"]
    assert [(r["status"], r.get("reasonCode")) for r in results] == [
        ("skipped", "child_passes_disabled"),
        ("failed", None),
    ]
    assert [dest for dest, _kwargs in calls] == [PARENT_EXT, "00382b"]
    assert outcome["childrenExpansion"]["partial"] is True

    custom_calls = []
    responses = {
        (PARENT_EXT, "extended"): _parent_item(child_table=[{"childId": 42, "mode": MTD_MODE}]),
        ("00382a", "rloc"): [failure, _child_item("3333333333333333", "0x382a")],
    }
    monkeypatch.setattr(
        client, "fetch_device_diagnostics", _rloc_fetch(responses, custom_calls)
    )
    outcome = client.fetch_all_devices_diagnostics(
        [PARENT_EXT],
        types=["extAddress", "rloc16", "mode"],
        fallback_types=["extAddress", "rloc16"],
        child_task_timeout=40,
        children_expand_by_rloc=True,
    )
    assert [
        (dest, kwargs["types"], kwargs["task_timeout"])
        for dest, kwargs in custom_calls[1:]
    ] == [
        ("00382a", ["extAddress", "rloc16", "mode"], 40),
        ("00382a", ["extAddress", "rloc16"], 40),
    ]
    record = outcome["childrenExpansion"]["results"][0]
    assert record["policy"] == "legacy"
    assert record["status"] == "partial"
    assert record["fallbackRecovered"] is True


def test_zero_child_expansion_is_complete_without_actions(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    calls = []
    responses = {(PARENT_EXT, "extended"): _parent_item(child_table=[])}
    monkeypatch.setattr(client, "fetch_device_diagnostics", _rloc_fetch(responses, calls))

    outcome = client.fetch_all_devices_diagnostics(
        [PARENT_EXT], children_expand_by_rloc=True
    )

    assert len(calls) == 1
    assert outcome["partial"] is False
    assert outcome["childrenExpansion"] == {
        "enabled": True,
        "partial": False,
        "parentCount": 1,
        "targetCount": 0,
        "attemptedCount": 0,
        "completedCount": 0,
        "coveredCount": 0,
        "results": [],
        "issues": [],
    }


def test_expansion_reads_raw_envelope_identity_without_rewriting(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    calls = []

    def envelope(attributes):
        return {"data": {"id": "d", "type": "networkDiagnostics", "attributes": attributes}}

    child = envelope(_child_item("3333333333333333", "0x382a"))
    responses = {
        (PARENT_EXT, "extended"): envelope(_parent_item(child_table=[{"childId": 42, "mode": FTD_MODE}])),
        ("00382a", "rloc"): child,
    }
    monkeypatch.setattr(client, "fetch_device_diagnostics", _rloc_fetch(responses, calls))

    outcome = client.fetch_all_devices_diagnostics(
        [PARENT_EXT],
        child_collection_policy="mode-aware",
        children_expand_by_rloc=True,
        raw=True,
    )

    assert outcome["items"][-1] == child
    assert outcome["childrenExpansion"]["completedCount"] == 1


def test_expansion_requires_extended_base_destination_before_side_effects(
    monkeypatch,
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    clear = MagicMock()
    fetch = MagicMock()
    monkeypatch.setattr(client, "delete_all_diagnostics", clear)
    monkeypatch.setattr(client, "fetch_device_diagnostics", fetch)

    with pytest.raises(OTBRUsageError, match="extended"):
        client.fetch_all_devices_diagnostics(
            [PARENT_EXT],
            destination_type=DestinationType.RLOC,
            clear_diagnostics=True,
            children_expand_by_rloc=True,
        )
    clear.assert_not_called()
    fetch.assert_not_called()


def test_rloc_missing_result_message_does_not_blame_fixed_upstream_bug(
    monkeypatch,
) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    monkeypatch.setattr(
        client, "run_action", lambda *_args, **_kwargs: completed_action("action-9")
    )

    with pytest.raises(OTBRInvalidResponseError) as excinfo:
        client.fetch_device_diagnostics("00382a", destination_type=DestinationType.RLOC)

    message = str(excinfo.value)
    assert "has no result relationship" in message
    assert "destinationType='rloc'" in message
    assert "Older OTBR builds may not" in message
    assert "server bug" not in message
