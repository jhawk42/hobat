from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import otbr_restapi_cli as cli_module
from otbr_restapi_util import (
    ActionStatus,
    OTBRActionFailedError,
    OTBRActionTimeoutError,
    OTBRHTTPError,
    OTBRIndeterminateEnqueueError,
    OTBRRestApiClient,
    OTBRUsageError,
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

    assert outcome["partial"] is False
    assert outcome["deviceResults"][0]["attempts"] == 2
    assert fetch.call_count == 2


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
