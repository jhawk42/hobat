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
    expected = {"items": [], "deviceResults": [], "partial": False}
    sweep = MagicMock(return_value=expected)
    monkeypatch.setattr(client, "fetch_all_devices_diagnostics", sweep)

    outcome = client.fetch_mesh_diagnostics_all_devices(
        [{"id": "1111111111111111", "role": "router"}],
        clear_diagnostics=True,
    )

    assert outcome is expected
    kwargs = sweep.call_args.kwargs
    assert kwargs["clear_diagnostics"] is True
    assert kwargs["items_only"] is False
    assert set(kwargs["types"]) == {
        "children",
        "childIpv6Addresses",
        "routerNeighbors",
    }


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
