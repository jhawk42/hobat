from __future__ import annotations

import json
import socket
import threading
from contextlib import contextmanager
from copy import deepcopy
from http.server import ThreadingHTTPServer

import pytest

from otbr_restapi_util import OTBRConnectionError, OTBRRestApiClient
from td_mock_otbr_restapi_server import MockOTBRStore, make_handler


@contextmanager
def running_mock(store: MockOTBRStore):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield OTBRRestApiClient(base_url=f"http://{host}:{port}", retries=1)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def queue_discovery(store: MockOTBRStore, *statuses: str) -> None:
    store.queued_action_sequences.append(
        [{"status": status} for status in statuses]
    )


def test_one_router_discovery_matrix() -> None:
    store = MockOTBRStore.build()
    store.devices = {store.node_item["id"]: store.node_item}
    queue_discovery(store, "active", "completed")

    with running_mock(store) as client:
        outcome = client.fetch_device_collection(poll_interval=0.01)

    assert outcome["partial"] is False
    assert outcome["status"] == "completed"
    assert [device["id"] for device in outcome["items"]] == [store.node_item["id"]]


def test_multi_router_discovery_matrix() -> None:
    store = MockOTBRStore.build()
    second_router = deepcopy(store.node_item)
    second_router["id"] = "1111111111111111"
    second_router["attributes"]["extAddress"] = second_router["id"]
    second_router["attributes"]["rloc16"] = "0x4000"
    second_router["attributes"]["role"] = "router"
    store.devices = {
        store.node_item["id"]: store.node_item,
        second_router["id"]: second_router,
    }
    queue_discovery(store, "completed")

    with running_mock(store) as client:
        outcome = client.fetch_device_collection(poll_interval=0.01)

    assert outcome["partial"] is False
    assert {device["id"] for device in outcome["items"]} == {
        store.node_item["id"],
        second_router["id"],
    }


def test_sleepy_child_diagnostic_matrix() -> None:
    store = MockOTBRStore.build()
    child = next(
        item
        for item in store.devices.values()
        if item["attributes"].get("role") == "child"
    )
    diagnostic_id = next(iter(store.diagnostics))
    store.diagnostics[diagnostic_id]["attributes"]["extAddress"] = child["id"]
    store.queued_action_sequences.append(
        [
            {"status": "active", "timeout": 29},
            {"status": "active", "timeout": 28},
            {"status": "completed"},
        ]
    )

    with running_mock(store) as client:
        outcome = client.fetch_all_devices_diagnostics(
            [{"id": child["id"], "role": "child"}],
            poll_interval=0.01,
            clear_diagnostics=False,
        )

    assert outcome["partial"] is False
    assert outcome["deviceResults"][0]["role"] == "child"
    assert outcome["deviceResults"][0]["diagnosticId"] == diagnostic_id
    assert outcome["items"][0]["extAddress"] == child["id"]


def test_unreachable_server_matrix() -> None:
    socket_handle = socket.socket()
    socket_handle.bind(("127.0.0.1", 0))
    port = socket_handle.getsockname()[1]
    socket_handle.close()
    client = OTBRRestApiClient(
        base_url=f"http://127.0.0.1:{port}",
        timeout=0.1,
        retries=1,
    )

    with pytest.raises(OTBRConnectionError):
        client.get_node()


def test_queue_full_matrix_returns_indeterminate_partial_without_storm() -> None:
    store = MockOTBRStore.build()
    initial_action_count = len(store.actions)
    store.enqueue_reject_statuses.append(503)

    with running_mock(store) as client:
        outcome = client.fetch_device_collection(whole_action_attempts=3)

    action_posts = [
        request
        for request in store.requests
        if request.method == "POST" and request.path == "/api/actions"
    ]
    assert outcome["partial"] is True
    assert outcome["status"] == "indeterminate_enqueue"
    assert len(action_posts) == 1
    assert len(store.actions) == initial_action_count


def test_slow_action_sequence_completes_with_one_enqueue() -> None:
    store = MockOTBRStore.build()
    queue_discovery(store, "pending", "active", "active", "active", "completed")

    with running_mock(store) as client:
        outcome = client.fetch_device_collection(poll_interval=0.01)

    action_posts = [
        request
        for request in store.requests
        if request.method == "POST" and request.path == "/api/actions"
    ]
    action_polls = [
        request
        for request in store.requests
        if request.method == "GET" and request.path.startswith("/api/actions/")
    ]
    assert outcome["partial"] is False
    assert len(action_posts) == 1
    assert len(action_polls) == 5


def test_python_discovery_request_matches_ui_contract_except_approved_policy() -> None:
    store = MockOTBRStore.build()

    with running_mock(store) as client:
        client.enqueue_update_device_collection_task(
            max_age=30,
            max_retries=5,
            device_count=255,
            timeout=30,
        )

    request = next(
        request
        for request in store.requests
        if request.method == "POST" and request.path == "/api/actions"
    )
    python_task = json.loads(request.body)["data"][0]
    upstream_ui_task = {
        "type": "updateDeviceCollectionTask",
        "attributes": {
            "maxAge": 30,
            "maxRetries": 5,
            "deviceCount": 16,
            "timeout": 15,
        },
    }

    assert request.headers["content-type"] == "application/vnd.api+json"
    assert request.headers["accept"] == "application/vnd.api+json"
    assert python_task["type"] == upstream_ui_task["type"]
    shared_keys = {"maxAge", "maxRetries"}
    assert {
        key: python_task["attributes"][key] for key in shared_keys
    } == {
        key: upstream_ui_task["attributes"][key] for key in shared_keys
    }
    assert {
        "deviceCount": (
            upstream_ui_task["attributes"]["deviceCount"],
            python_task["attributes"]["deviceCount"],
        ),
        "timeout": (
            upstream_ui_task["attributes"]["timeout"],
            python_task["attributes"]["timeout"],
        ),
    } == {
        "deviceCount": (16, 255),
        "timeout": (15, 30),
    }
