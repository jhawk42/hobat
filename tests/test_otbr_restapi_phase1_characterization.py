from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import pytest

import otbr_restapi_cli as cli_module
import otbr_restapi_topology as topology_module
import otbr_restapi_util as client_module
from td_mock_otbr_restapi_server import JSON_API, MockOTBRStore, make_handler


@contextmanager
def running_mock(store: MockOTBRStore):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield client_module.OTBRRestApiClient(
            base_url=f"http://{host}:{port}", retries=1
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def action_count(store: MockOTBRStore) -> int:
    return sum(
        request.method == "POST" and request.path == "/api/actions"
        for request in store.requests
    )


def test_mock_captures_exact_read_contracts() -> None:
    store = MockOTBRStore.build()

    with running_mock(store) as client:
        client.get_node(raw=True)
        client.list_actions(raw=True)
        client.list_devices(raw=True)
        client.list_diagnostics(raw=True)

    assert [(request.method, request.path) for request in store.requests] == [
        ("GET", "/api/node"),
        ("GET", "/api/actions"),
        ("GET", "/api/devices"),
        ("GET", "/api/diagnostics"),
    ]
    assert all(request.headers["accept"] == JSON_API for request in store.requests)
    assert all(request.body == b"" for request in store.requests)


def test_mock_captures_exact_discovery_enqueue_contract() -> None:
    store = MockOTBRStore.build()

    with running_mock(store) as client:
        result = client.enqueue_update_device_collection_task(
            max_age=30,
            max_retries=5,
            device_count=255,
            timeout=30,
        )

    request = store.requests[-1]
    assert request.method == "POST"
    assert request.path == "/api/actions"
    assert request.headers["accept"] == JSON_API
    assert request.headers["content-type"] == JSON_API
    assert json.loads(request.body) == {
        "data": [
            {
                "type": "updateDeviceCollectionTask",
                "attributes": {
                    "maxAge": 30,
                    "maxRetries": 5,
                    "deviceCount": 255,
                    "timeout": 30,
                },
            }
        ]
    }
    assert result[0]["status"] == "pending"


def test_targeted_action_delete_removes_only_requested_action() -> None:
    store = MockOTBRStore.build()
    existing_id = next(iter(store.actions))
    store.actions["keep-action"] = {
        "id": "keep-action",
        "type": "updateDeviceCollectionTask",
        "attributes": {"status": "completed"},
    }

    with running_mock(store) as client:
        client.delete_action(existing_id)

    assert existing_id not in store.actions
    assert "keep-action" in store.actions
    assert store.requests[-1].method == "DELETE"
    assert store.requests[-1].path == f"/api/actions/{existing_id}"


def test_diagnostic_collection_delete_preserves_actions_and_devices() -> None:
    store = MockOTBRStore.build()
    action_ids = set(store.actions)
    device_ids = set(store.devices)

    with running_mock(store) as client:
        client.delete_all_diagnostics()

    assert store.diagnostics == {}
    assert set(store.actions) == action_ids
    assert set(store.devices) == device_ids
    assert store.requests[-1].path == "/api/diagnostics"


def test_programmable_action_sequence_reaches_completed() -> None:
    store = MockOTBRStore.build()
    store.queued_action_sequences.append(
        [
            {"status": "pending", "timeout": 14},
            {"status": "active", "timeout": 13},
            {"status": "completed"},
        ]
    )

    with running_mock(store) as client:
        enqueued = client.enqueue_update_device_collection_task(
            max_age=30, max_retries=2, device_count=255, timeout=15
        )
        action = client.wait_for_action(
            enqueued[0]["id"], poll_interval=0, poll_timeout=1
        )

    assert action["status"] == "completed"
    assert action_count(store) == 1
    assert sum(request.method == "GET" for request in store.requests) == 3


@pytest.mark.parametrize("terminal_status", ["stopped", "failed"])
def test_terminal_failure_states_remain_distinct(terminal_status: str) -> None:
    store = MockOTBRStore.build()
    store.queued_action_sequences.append([{"status": terminal_status}])

    with running_mock(store) as client:
        enqueued = client.enqueue_update_device_collection_task(
            max_age=30, max_retries=2, device_count=255, timeout=15
        )
        with pytest.raises(client_module.OTBRActionFailedError) as error:
            client.wait_for_action(
                enqueued[0]["id"], poll_interval=0, poll_timeout=1
            )

    assert error.value.status == terminal_status
    assert error.value.action["status"] == terminal_status


def test_poll_timeout_retains_last_action_and_status(monkeypatch) -> None:
    client = client_module.OTBRRestApiClient(base_url="http://example.test")
    action = {"id": "action-1", "status": "active", "timeout": 1}
    monkeypatch.setattr(
        client,
        "get_action",
        lambda action_id, raw=False, deadline=None: action,
    )
    monotonic_values = iter([10.0, 11.0, 11.0])
    monkeypatch.setattr(client_module.time, "monotonic", lambda: next(monotonic_values))

    with pytest.raises(client_module.OTBRActionTimeoutError) as error:
        client.wait_for_action("action-1", poll_interval=2, poll_timeout=1)

    assert error.value.action == action
    assert error.value.status == "active"


def test_stopped_discovery_returns_warning_backed_partial_collection(caplog) -> None:
    store = MockOTBRStore.build()
    store.queued_action_sequences.append([{"status": "stopped"}])

    with running_mock(store) as client:
        outcome = client.fetch_device_collection(
            task_timeout=15, poll_interval=0.25, poll_timeout=20
        )

    assert len(outcome["items"]) == 2
    assert outcome["partial"] is True
    assert outcome["status"] == "stopped"
    assert outcome["action"]["status"] == "stopped"
    assert outcome["freshness"]["maxAge"] == 60
    assert "returning partial device collection" in caplog.text
    assert [(request.method, request.path) for request in store.requests] == [
        ("POST", "/api/actions"),
        ("GET", next(request.path for request in store.requests if request.method == "GET" and request.path.startswith("/api/actions/"))),
        ("GET", "/api/devices"),
    ]


def test_malformed_action_without_status_is_rejected() -> None:
    store = MockOTBRStore.build()
    action_id = "malformed-action"
    store.actions[action_id] = {
        "id": action_id,
        "type": "updateDeviceCollectionTask",
        "attributes": {},
    }

    with running_mock(store) as client:
        with pytest.raises(client_module.OTBRInvalidResponseError, match="no 'status'"):
            client.wait_for_action(action_id, poll_interval=0, poll_timeout=1)


def test_queue_capacity_503_is_exposed_without_creating_an_action() -> None:
    store = MockOTBRStore.build()
    initial_ids = set(store.actions)
    store.enqueue_reject_statuses.append(503)

    with running_mock(store) as client:
        with pytest.raises(client_module.OTBRHTTPError) as error:
            client.enqueue_update_device_collection_task(
                max_age=30, max_retries=2, device_count=255, timeout=15
            )

    assert error.value.status_code == 503
    assert set(store.actions) == initial_ids
    assert action_count(store) == 1


def test_accepted_but_lost_post_response_does_not_duplicate_action(monkeypatch) -> None:
    store = MockOTBRStore.build()
    initial_count = len(store.actions)
    store.enqueue_response_statuses.extend([500, 200])
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)

    with running_mock(store) as client:
        client.retries = 2
        with pytest.raises(client_module.OTBRHTTPError) as error:
            client.enqueue_update_device_collection_task(
                max_age=30, max_retries=2, device_count=255, timeout=15
            )

    assert error.value.status_code == 500
    assert len(store.actions) == initial_count + 1
    assert action_count(store) == 1


def test_empty_enqueue_response_fails_with_invalid_response_error(monkeypatch) -> None:
    client = client_module.OTBRRestApiClient(base_url="http://example.test")
    monkeypatch.setattr(client, "enqueue_update_device_collection_task", lambda **kwargs: [])

    with pytest.raises(client_module.OTBRInvalidResponseError):
        client.trigger_and_wait_device_collection(
            device_count=255,
            max_age=30,
            max_retries=2,
            task_timeout=15,
            poll_interval=0.25,
            poll_timeout=20,
        )


@pytest.mark.parametrize(
    ("argv", "method_name"),
    [
        (
            [
                "--poll-interval", "0.25", "--poll-timeout", "44",
                "devices", "fetch", "--task-timeout", "33",
            ],
            "fetch_device_collection",
        ),
        (
            [
                "--poll-interval", "0.25", "--poll-timeout", "44",
                "diagnostics", "fetch", "--device-id", "96518e5497d5b9f3",
                "--task-timeout", "33", "--no-fallback",
            ],
            "fetch_device_diagnostics",
        ),
            (
            [
                "--poll-interval", "0.25", "--poll-timeout", "44",
                "mesh-diagnostics", "fetch", "--device-id", "96518e5497d5b9f3",
                "--task-timeout", "33",
            ],
                "fetch_mesh_diagnostics",
        ),
    ],
)
def test_cli_timing_overrides_reach_client_workflows(argv, method_name) -> None:
    args = cli_module.build_parser().parse_args(argv)
    args.resolved_output_path = None
    client = MagicMock()
    client._resolve_raw.return_value = False
    getattr(client, method_name).return_value = [] if method_name == "fetch_device_collection" else {}

    cli_module.dispatch(client, args)

    kwargs = getattr(client, method_name).call_args.kwargs
    assert kwargs["task_timeout"] == 33
    assert kwargs["poll_interval"] == 0.25
    assert kwargs["poll_timeout"] == 44


def test_topology_timing_overrides_reach_diagnostic_workflow(tmp_path) -> None:
    args = cli_module.build_parser().parse_args(
        [
            "--poll-interval", "0.25", "--poll-timeout", "44",
            "topology", "--task-timeout", "33", "--skip-mesh-diagnostics",
            "--no-enrich-mac-counters", "--no-progress",
        ]
    )
    args.td_data_dir = tmp_path
    client = MagicMock()
    client._resolve_raw.return_value = False
    client.fetch_device_collection.return_value = [
        {"id": "96518e5497d5b9f3", "rloc16": "0xf000"}
    ]
    client.fetch_all_devices_diagnostics.return_value = {
        "items": [],
        "deviceResults": [],
        "partial": False,
    }

    cli_module.dispatch(client, args)

    kwargs = client.fetch_all_devices_diagnostics.call_args.kwargs
    assert kwargs["task_timeout"] == 33
    assert kwargs["poll_interval"] == 0.25
    assert kwargs["poll_timeout"] == 44
