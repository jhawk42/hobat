from __future__ import annotations

import argparse
from unittest.mock import MagicMock

import pytest

from otbr_restapi_actions import dispatch_actions
from otbr_restapi_util import (
    ActionTimingPolicy,
    CHILD_DIAGNOSTIC_TIMING_POLICY,
    DISCOVERY_TIMING_POLICY,
    OTBRActionDisappearedError,
    OTBRActionTimeoutError,
    OTBRHTTPError,
    OTBRInvalidResponseError,
    OTBRRestApiClient,
    OTBRUsageError,
    ROUTER_DIAGNOSTIC_TIMING_POLICY,
)


def test_timing_policy_derives_approved_deadlines() -> None:
    discovery = ActionTimingPolicy.resolve(
        task_timeout=30, poll_interval=2.0, poll_timeout=None
    )
    diagnostics = ActionTimingPolicy.resolve(
        task_timeout=15, poll_interval=0.5, poll_timeout=None
    )

    assert discovery.poll_timeout == 36.0
    assert diagnostics.poll_timeout == 20.0
    assert DISCOVERY_TIMING_POLICY.poll_timeout == 36.0
    assert ROUTER_DIAGNOSTIC_TIMING_POLICY.poll_timeout == 20.0
    assert CHILD_DIAGNOSTIC_TIMING_POLICY.poll_timeout == 36.0


@pytest.mark.parametrize(
    ("task_timeout", "poll_interval", "poll_timeout"),
    [
        (0, 2.0, None),
        (15, 0, None),
        (15, 2.0, 19.99),
    ],
)
def test_timing_policy_rejects_invalid_or_too_short_values(
    task_timeout: int,
    poll_interval: float,
    poll_timeout: float | None,
) -> None:
    with pytest.raises(OTBRUsageError):
        ActionTimingPolicy.resolve(
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
        )


@pytest.mark.parametrize(
    "enqueued",
    [
        [],
        [{"status": "pending"}],
        [{"id": ""}],
        [{"id": "one"}, {"id": "two"}],
        {"data": []},
    ],
)
def test_action_runner_validates_enqueue_response_before_polling(enqueued) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    client.wait_for_action = MagicMock()

    with pytest.raises(OTBRInvalidResponseError):
        client.run_action(
            lambda: enqueued,
            task_timeout=15,
            poll_interval=2.0,
            poll_timeout=20.0,
        )

    client.wait_for_action.assert_not_called()


def test_unknown_action_status_is_rejected_with_payload(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    action = {"id": "action-1", "status": "mystery", "timeout": 10}
    monkeypatch.setattr(
        client,
        "get_action",
        lambda action_id, raw=False, deadline=None: action,
    )

    with pytest.raises(OTBRInvalidResponseError) as error:
        client.wait_for_action("action-1", poll_interval=1, poll_timeout=20)

    assert "unknown status 'mystery'" in str(error.value)
    assert repr(action) in str(error.value)


def test_missing_action_is_classified_as_disappeared(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    missing = OTBRHTTPError(
        status_code=404,
        reason="Not Found",
        url="http://example.test/api/actions/action-1",
    )
    monkeypatch.setattr(
        client,
        "get_action",
        lambda action_id, raw=False, deadline=None: (_ for _ in ()).throw(missing),
    )

    with pytest.raises(OTBRActionDisappearedError) as error:
        client.wait_for_action("action-1", poll_interval=1, poll_timeout=20)

    assert error.value.action_id == "action-1"
    assert error.value.status == "unknown"


def test_runner_optionally_deletes_only_timed_out_action(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    timeout = OTBRActionTimeoutError(
        "timed out",
        action_id="action-1",
        status="active",
        action={"id": "action-1", "status": "active"},
    )
    monkeypatch.setattr(
        client,
        "wait_for_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(timeout),
    )
    delete_action = MagicMock()
    monkeypatch.setattr(client, "delete_action", delete_action)

    with pytest.raises(OTBRActionTimeoutError):
        client.run_action(
            lambda: [{"id": "action-1", "status": "pending"}],
            task_timeout=15,
            poll_interval=2.0,
            poll_timeout=20.0,
            cleanup_on_timeout=True,
        )

    delete_action.assert_called_once_with("action-1")


def test_discovery_uses_shared_runner_and_derived_deadline(monkeypatch) -> None:
    client = OTBRRestApiClient(base_url="http://example.test")
    run_action = MagicMock(return_value={"id": "action-1", "status": "completed"})
    monkeypatch.setattr(client, "run_action", run_action)

    result = client.trigger_and_wait_device_collection()

    assert result["status"] == "completed"
    kwargs = run_action.call_args.kwargs
    assert kwargs["task_timeout"] == 30
    assert kwargs["poll_interval"] == 2.0
    assert kwargs["poll_timeout"] is None


def test_cli_wait_uses_shared_runner() -> None:
    client = MagicMock()
    client.run_action.return_value = {
        "id": "action-1",
        "status": "completed",
    }
    args = argparse.Namespace(
        actions_command="enqueue",
        enqueue_type="get-network-diagnostic",
        destination="96518e5497d5b9f3",
        types=["extAddress"],
        preset=None,
        timeout=15,
        destination_type="extended",
        wait=True,
        poll_interval=0.5,
        poll_timeout=20.0,
    )

    result = dispatch_actions(client, args, False, None, False)

    assert result["status"] == "completed"
    kwargs = client.run_action.call_args.kwargs
    assert kwargs["task_timeout"] == 15
    assert kwargs["poll_interval"] == 0.5
    assert kwargs["poll_timeout"] == 20.0
