from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

import ha_matter_ws_client

from ha_matter_ws_client import (
    HaMatterWsClient,
    MatterWsRequestTimeoutError,
    MatterWsTransportError,
    fetch_node_snapshot,
)
from ha_matter_ws_contract import (
    MatterWsCommandUnsupportedError,
    MatterWsContractError,
    MatterWsResponseCorrelationError,
)
from ha_matter_ws_extractor import extract_nodes_info
from ha_matter_ws_fetch_all import collect_devices, save_collection


FIXTURE = Path(__file__).parent / "fixtures" / "ha_matter_ws_phase2_inventory.json"
DIAGNOSTIC_FIXTURE = (
    Path(__file__).parent / "fixtures" / "ha_matter_ws_phase3_diagnostics.json"
)


class FakeWebSocket:
    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self.incoming: asyncio.Queue[str | bytes] = asyncio.Queue()
        for frame in frames:
            self.incoming.put_nowait(json.dumps(frame))
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self.close_count = 0
        self.on_send = None

    async def recv(self) -> str | bytes:
        return await self.incoming.get()

    async def send(self, payload: str) -> None:
        message = json.loads(payload)
        self.sent.append(message)
        if self.on_send is not None:
            await self.on_send(message)

    async def close(self) -> None:
        self.closed = True
        self.close_count += 1

    def queue(self, frame: dict[str, Any]) -> None:
        self.incoming.put_nowait(json.dumps(frame))


def _server_info() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["serverInfo"]


def _server_info_with_schema(schema_version: int) -> dict[str, Any]:
    return dict(_server_info(), schema_version=schema_version)


@pytest.mark.parametrize(("frame", "error_type"), [
    ("not-json", MatterWsTransportError),
    (b"{}", MatterWsTransportError),
    ("[]", MatterWsTransportError),
    ("{}", MatterWsContractError),
])
def test_failed_handshake_closes_once_without_installing_reader(monkeypatch, frame, error_type):
    async def scenario():
        socket = FakeWebSocket([])
        socket.incoming.put_nowait(frame)
        monkeypatch.setattr(ha_matter_ws_client.websockets, "connect", lambda *a, **k: socket)
        client = HaMatterWsClient(connect_timeout=0.1)
        with pytest.raises(error_type):
            await client.__aenter__()
        assert socket.close_count == 1
        assert client._reader_task is None
        assert client._pending == {}
        assert client._server_info is None
        assert client._websocket is None
        await client.close()
        assert socket.close_count == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("error_type", [MatterWsTransportError, MatterWsContractError])
def test_failed_handshake_preserves_original_local_error_instance(monkeypatch, error_type):
    async def scenario():
        socket = FakeWebSocket([])
        monkeypatch.setattr(ha_matter_ws_client.websockets, "connect", lambda *a, **k: socket)
        client = HaMatterWsClient()
        error = error_type("original")
        monkeypatch.setattr(client, "_receive_frame", AsyncMock(side_effect=error))
        with pytest.raises(error_type) as raised:
            await client.__aenter__()
        assert raised.value is error
        assert socket.close_count == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["os", "websocket", "timeout", "programming"])
def test_failed_entry_cleanup_is_bounded_and_reports_known_failures(monkeypatch, caplog, failure):
    async def scenario():
        socket = FakeWebSocket([])
        monkeypatch.setattr(ha_matter_ws_client.websockets, "connect", lambda *a, **k: socket)
        client = HaMatterWsClient(connect_timeout=0.01)
        error = MatterWsTransportError("original handshake")
        monkeypatch.setattr(client, "_receive_frame", AsyncMock(side_effect=error))
        close_finished = asyncio.Event()
        original_close = socket.close

        async def close():
            await original_close()
            try:
                if failure == "timeout":
                    await asyncio.Event().wait()
                if failure == "programming":
                    raise RuntimeError("programming error")
                if failure == "websocket":
                    raise ha_matter_ws_client.websockets.WebSocketException("PRIVATE-CLOSE")
                raise OSError("PRIVATE-CLOSE")
            finally:
                close_finished.set()

        monkeypatch.setattr(socket, "close", close)
        with pytest.raises(RuntimeError if failure == "programming" else MatterWsTransportError) as raised:
            await asyncio.wait_for(client.__aenter__(), timeout=1)
        if failure == "programming":
            assert type(raised.value) is RuntimeError
        else:
            assert raised.value is error
            assert "cleanup incomplete" in caplog.text
            assert "PRIVATE-CLOSE" not in caplog.text
        assert close_finished.is_set()
        assert client._reader_task is None
        assert client._websocket is None
        await client.close()
        assert socket.close_count == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_cleanup", [False, True])
def test_handshake_cancellation_closes_once_and_second_cancellation_propagates(monkeypatch, cancel_cleanup):
    async def scenario():
        socket = FakeWebSocket([])
        monkeypatch.setattr(ha_matter_ws_client.websockets, "connect", lambda *a, **k: socket)
        client = HaMatterWsClient(connect_timeout=0.2)
        receiving = asyncio.Event()
        closing = asyncio.Event()
        close_finished = asyncio.Event()
        original_recv, original_close = socket.recv, socket.close

        async def recv():
            receiving.set()
            return await original_recv()

        async def close():
            await original_close()
            closing.set()
            try:
                if cancel_cleanup:
                    await asyncio.Event().wait()
            finally:
                close_finished.set()

        monkeypatch.setattr(socket, "recv", recv)
        monkeypatch.setattr(socket, "close", close)
        task = asyncio.create_task(client.__aenter__())
        await asyncio.wait_for(receiving.wait(), timeout=1)
        task.cancel()
        if cancel_cleanup:
            await asyncio.wait_for(closing.wait(), timeout=1)
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert close_finished.is_set()
        assert client._reader_task is None
        assert client._pending == {}
        await client.close()
        assert socket.close_count == 1
    asyncio.run(scenario())


def test_client_correlates_out_of_order_responses_and_routes_events(monkeypatch) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])

        async def on_send(message: dict[str, Any]) -> None:
            if len(socket.sent) == 2:
                socket.queue({"event": "node_updated", "data": {"node_id": 9}})
                first, second = socket.sent
                socket.queue({"message_id": second["message_id"], "result": "second"})
                socket.queue({"message_id": first["message_id"], "result": "first"})

        socket.on_send = on_send
        monkeypatch.setattr(ha_matter_ws_client.websockets, "connect", lambda *args, **kwargs: socket)

        async with HaMatterWsClient(request_timeout=0.2) as client:
            first = asyncio.create_task(client.request("first"))
            second = asyncio.create_task(client.request("second"))
            assert await asyncio.gather(first, second) == ["first", "second"]
            assert client.server_info == _server_info()
            assert [event["event"] for event in client.events] == ["node_updated"]

        assert socket.closed is True
        assert [message["message_id"] for message in socket.sent] == ["1", "2"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("server_schema", "required_schema", "supported"),
    [(11, 12, False), (12, 12, True), (12, 13, False), (13, 13, True)],
)
def test_client_gates_commands_by_server_schema_before_send(
    monkeypatch, server_schema, required_schema, supported
) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info_with_schema(server_schema)])

        async def on_send(message: dict[str, Any]) -> None:
            socket.queue({"message_id": message["message_id"], "result": "ok"})

        socket.on_send = on_send
        monkeypatch.setattr(
            ha_matter_ws_client.websockets,
            "connect",
            lambda *args, **kwargs: socket,
        )

        async with HaMatterWsClient(request_timeout=0.2) as client:
            if supported:
                assert await client.request(
                    "schema_gated", require_schema=required_schema
                ) == "ok"
                assert client._message_id == 1
                assert len(socket.sent) == 1
            else:
                with pytest.raises(MatterWsCommandUnsupportedError) as exc_info:
                    await client.request("schema_gated", require_schema=required_schema)
                assert exc_info.value.command == "schema_gated"
                assert exc_info.value.required_schema == required_schema
                assert exc_info.value.server_schema == server_schema
                assert client._message_id == 0
                assert socket.sent == []

    asyncio.run(scenario())


def test_network_topology_is_rejected_on_schema_12_before_send(monkeypatch) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info_with_schema(12)])
        monkeypatch.setattr(
            ha_matter_ws_client.websockets,
            "connect",
            lambda *args, **kwargs: socket,
        )

        async with HaMatterWsClient(request_timeout=0.2) as client:
            with pytest.raises(MatterWsCommandUnsupportedError) as exc_info:
                await client.request(
                    "get_network_topology",
                    args={"refresh": False},
                    require_schema=13,
                )
            assert exc_info.value.command == "get_network_topology"
            assert client._message_id == 0
            assert socket.sent == []

    asyncio.run(scenario())


def test_client_cursor_retains_event_arriving_before_command_response(monkeypatch) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info_with_schema(13)])

        async def on_send(message: dict[str, Any]) -> None:
            socket.queue({"event": "thread_diagnostics_updated", "data": {"id": 7}})
            socket.queue({"message_id": message["message_id"], "result": []})

        socket.on_send = on_send
        monkeypatch.setattr(
            ha_matter_ws_client.websockets,
            "connect",
            lambda *args, **kwargs: socket,
        )

        async with HaMatterWsClient(request_timeout=0.2) as client:
            cursor = client.event_cursor
            assert await client.request("opt_in", require_schema=12) == []
            sequence, event = await client.next_event(
                after=cursor,
                predicate=lambda frame: frame.get("event")
                == "thread_diagnostics_updated",
                timeout=0.2,
            )
            assert sequence == 1
            assert event["data"] == {"id": 7}
            assert client.event_cursor == 1

    asyncio.run(scenario())


def test_client_next_event_ignores_but_retains_unrelated_events(monkeypatch) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])
        monkeypatch.setattr(
            ha_matter_ws_client.websockets,
            "connect",
            lambda *args, **kwargs: socket,
        )

        async with HaMatterWsClient(request_timeout=0.2) as client:
            cursor = client.event_cursor
            waiter = asyncio.create_task(
                client.next_event(
                    after=cursor,
                    predicate=lambda frame: frame.get("event") == "matching",
                    timeout=0.2,
                )
            )
            socket.queue({"event": "unrelated", "data": {}})
            await asyncio.sleep(0)
            assert waiter.done() is False
            socket.queue({"event": "matching", "data": {}})
            sequence, _ = await waiter
            assert sequence == 2
            assert [event["event"] for event in client.events] == [
                "unrelated",
                "matching",
            ]

    asyncio.run(scenario())


def test_client_next_event_timeout_and_cancellation_do_not_consume_events(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])
        monkeypatch.setattr(
            ha_matter_ws_client.websockets,
            "connect",
            lambda *args, **kwargs: socket,
        )

        async with HaMatterWsClient(request_timeout=0.2) as client:
            with pytest.raises(asyncio.TimeoutError):
                await client.next_event(
                    after=client.event_cursor,
                    predicate=lambda frame: True,
                    timeout=0.01,
                )
            waiter = asyncio.create_task(
                client.next_event(
                    after=client.event_cursor,
                    predicate=lambda frame: True,
                )
            )
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            socket.queue({"event": "retained", "data": {}})
            _, event = await client.next_event(
                after=0, predicate=lambda frame: True, timeout=0.2
            )
            assert event["event"] == "retained"

    asyncio.run(scenario())


def test_client_reader_failure_wakes_all_event_waiters(monkeypatch) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])
        monkeypatch.setattr(
            ha_matter_ws_client.websockets,
            "connect",
            lambda *args, **kwargs: socket,
        )

        async with HaMatterWsClient(request_timeout=0.2) as client:
            waiters = [
                asyncio.create_task(
                    client.next_event(after=0, predicate=lambda frame: True)
                )
                for _ in range(2)
            ]
            socket.queue({})
            results = await asyncio.gather(*waiters, return_exceptions=True)
            assert all(isinstance(result, MatterWsContractError) for result in results)
            with pytest.raises(MatterWsContractError, match="Unrecognized"):
                client.raise_if_reader_failed()

    asyncio.run(scenario())


def test_client_normal_close_wakes_event_waiter_without_reader_error(monkeypatch) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])
        monkeypatch.setattr(
            ha_matter_ws_client.websockets,
            "connect",
            lambda *args, **kwargs: socket,
        )

        client = await HaMatterWsClient(request_timeout=0.2).__aenter__()
        waiter = asyncio.create_task(
            client.next_event(after=0, predicate=lambda frame: True)
        )
        await client.close()
        with pytest.raises(MatterWsTransportError, match="reader stopped"):
            await waiter
        client.raise_if_reader_failed()

    asyncio.run(scenario())


def test_client_cancellation_cleans_pending_request(monkeypatch) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])
        monkeypatch.setattr(ha_matter_ws_client.websockets, "connect", lambda *args, **kwargs: socket)

        async with HaMatterWsClient(request_timeout=1) as client:
            request = asyncio.create_task(client.request("never_completes"))
            while not socket.sent:
                await asyncio.sleep(0)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert client._pending == {}

    asyncio.run(scenario())


def test_client_ping_node_sends_one_request_and_returns_address_results(monkeypatch) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])

        async def on_send(message: dict[str, Any]) -> None:
            socket.queue(
                {
                    "message_id": message["message_id"],
                    "result": {"192.0.2.10": True, "2001:db8::10": False},
                }
            )

        socket.on_send = on_send
        monkeypatch.setattr(
            ha_matter_ws_client.websockets,
            "connect",
            lambda *args, **kwargs: socket,
        )

        async with HaMatterWsClient(request_timeout=0.2) as client:
            assert await client.ping_node(7, attempts=2) == {
                "192.0.2.10": True,
                "2001:db8::10": False,
            }

        assert [message["command"] for message in socket.sent] == ["ping_node"]
        assert socket.sent[0]["args"] == {"node_id": 7, "attempts": 2}

    asyncio.run(scenario())


@pytest.mark.parametrize("result", [[], {"192.0.2.10": 1}, {"": True}])
def test_client_ping_node_rejects_malformed_results(monkeypatch, result) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])

        async def on_send(message: dict[str, Any]) -> None:
            socket.queue({"message_id": message["message_id"], "result": result})

        socket.on_send = on_send
        monkeypatch.setattr(
            ha_matter_ws_client.websockets,
            "connect",
            lambda *args, **kwargs: socket,
        )

        async with HaMatterWsClient(request_timeout=0.2) as client:
            with pytest.raises(MatterWsContractError, match="ping_node result"):
                await client.ping_node(7)

    asyncio.run(scenario())


def test_client_ping_node_rejects_oversized_address_maps(monkeypatch) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])

        async def on_send(message: dict[str, Any]) -> None:
            socket.queue(
                {
                    "message_id": message["message_id"],
                    "result": {f"192.0.2.{index}": True for index in range(257)},
                }
            )

        socket.on_send = on_send
        monkeypatch.setattr(
            ha_matter_ws_client.websockets,
            "connect",
            lambda *args, **kwargs: socket,
        )

        async with HaMatterWsClient(request_timeout=0.2) as client:
            with pytest.raises(MatterWsContractError, match="exceeds"):
                await client.ping_node(7)

    asyncio.run(scenario())


def test_client_ignores_late_timeout_response_without_disrupting_request(monkeypatch) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])

        async def on_send(message: dict[str, Any]) -> None:
            if message["command"] == "second":
                socket.queue({"message_id": "1", "result": "late"})
                socket.queue({"message_id": message["message_id"], "result": "second"})

        socket.on_send = on_send
        monkeypatch.setattr(ha_matter_ws_client.websockets, "connect", lambda *args, **kwargs: socket)

        async with HaMatterWsClient(request_timeout=0.01) as client:
            with pytest.raises(MatterWsRequestTimeoutError):
                await client.request("first")
            assert await client.request("second") == "second"
            assert client._reader_task is not None
            assert client._reader_task.done() is False
            assert client._late_response_ids == {}

    asyncio.run(scenario())


def test_client_rejects_response_for_never_issued_message_id(monkeypatch) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])

        async def on_send(message: dict[str, Any]) -> None:
            socket.queue({"message_id": "never-issued", "result": "invalid"})

        socket.on_send = on_send
        monkeypatch.setattr(ha_matter_ws_client.websockets, "connect", lambda *args, **kwargs: socket)

        async with HaMatterWsClient(request_timeout=0.2) as client:
            with pytest.raises(MatterWsResponseCorrelationError, match="never-issued"):
                await client.request("first")

    asyncio.run(scenario())


def test_client_fails_pending_request_at_frame_limit(monkeypatch) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])

        async def on_send(message: dict[str, Any]) -> None:
            socket.queue({"message_id": message["message_id"], "result": []})

        socket.on_send = on_send
        monkeypatch.setattr(ha_matter_ws_client.websockets, "connect", lambda *args, **kwargs: socket)

        async with HaMatterWsClient(request_timeout=0.2, max_frames=1) as client:
            with pytest.raises(MatterWsTransportError, match="exceeded 1 frames"):
                await client.request("start_listening")

    asyncio.run(scenario())


def test_fetch_snapshot_uses_one_inventory_request_and_applies_events(monkeypatch) -> None:
    async def scenario() -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        socket = FakeWebSocket([fixture["serverInfo"]])
        observed_at = datetime(2026, 11, 4, 22, 0, tzinfo=timezone.utc)
        clock_calls = []
        milestones = []
        reconcile = ha_matter_ws_client.reconcile_nodes

        def track_reconciliation(initial_nodes, events):
            result = reconcile(initial_nodes, events)
            milestones.append("reconciled")
            return result

        def frozen_clock():
            clock_calls.append(observed_at)
            milestones.append("clock")
            return observed_at

        async def on_send(message: dict[str, Any]) -> None:
            socket.queue(
                {
                    "event": "node_updated",
                    "data": {"node_id": 2, "available": True, "attributes": {}},
                }
            )
            socket.queue({"message_id": message["message_id"], "result": fixture["nodes"]})
            socket.queue(
                {
                    "event": "node_updated",
                    "data": {"node_id": 1, "available": False},
                }
            )

        socket.on_send = on_send
        monkeypatch.setattr(ha_matter_ws_client.websockets, "connect", lambda *args, **kwargs: socket)
        monkeypatch.setattr(
            ha_matter_ws_client, "reconcile_nodes", track_reconciliation
        )

        snapshot = await fetch_node_snapshot(
            request_timeout=0.2,
            settle_timeout=0.01,
            clock=frozen_clock,
        )

        assert [message["command"] for message in socket.sent] == ["start_listening"]
        assert [node["node_id"] for node in snapshot.nodes] == [1, 2]
        assert snapshot.nodes[0]["available"] is False
        assert snapshot.nodes[0]["attributes"]["0/40/5"] == "Living Room"
        assert snapshot.nodes[1]["available"] is True
        assert snapshot.source_observed_at == observed_at.isoformat()
        assert clock_calls == [observed_at]
        assert milestones == ["reconciled", "clock"]

    asyncio.run(scenario())


def test_failed_inventory_response_does_not_capture_observation_time(monkeypatch) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])
        clock_calls = []

        async def on_send(message: dict[str, Any]) -> None:
            socket.queue({"message_id": message["message_id"], "result": {}})

        socket.on_send = on_send
        monkeypatch.setattr(
            ha_matter_ws_client.websockets,
            "connect",
            lambda *args, **kwargs: socket,
        )

        with pytest.raises(MatterWsContractError, match="node array"):
            await fetch_node_snapshot(
                request_timeout=0.2,
                clock=lambda: clock_calls.append(True)
                or datetime(2026, 11, 4, tzinfo=timezone.utc),
            )
        assert clock_calls == []

    asyncio.run(scenario())


@pytest.mark.parametrize("observed_at", [
    datetime(1970, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1),
])
def test_invalid_controller_clock_rejects_observation(monkeypatch, observed_at) -> None:
    async def scenario() -> None:
        socket = FakeWebSocket([_server_info()])

        async def on_send(message: dict[str, Any]) -> None:
            socket.queue({"message_id": message["message_id"], "result": []})

        socket.on_send = on_send
        monkeypatch.setattr(ha_matter_ws_client.websockets, "connect", lambda *args, **kwargs: socket)
        with pytest.raises(MatterWsContractError, match="positive timezone-aware"):
            await fetch_node_snapshot(
                request_timeout=0.2, settle_timeout=0, clock=lambda: observed_at,
            )

    asyncio.run(scenario())


def test_reader_failure_after_reconciliation_does_not_capture_observation_time(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        socket = FakeWebSocket([fixture["serverInfo"]])
        milestones = []
        clock_calls = []
        reconcile = ha_matter_ws_client.reconcile_nodes

        async def on_send(message: dict[str, Any]) -> None:
            socket.queue({"message_id": message["message_id"], "result": fixture["nodes"]})

        def track_reconciliation(initial_nodes, events):
            nodes = reconcile(initial_nodes, events)
            milestones.append("reconciled")
            return nodes

        def fail_reader(self):
            milestones.append("reader-check")
            raise MatterWsTransportError("reader failed during settle")

        socket.on_send = on_send
        monkeypatch.setattr(
            ha_matter_ws_client.websockets,
            "connect",
            lambda *args, **kwargs: socket,
        )
        monkeypatch.setattr(
            ha_matter_ws_client, "reconcile_nodes", track_reconciliation
        )
        monkeypatch.setattr(
            HaMatterWsClient, "raise_if_reader_failed", fail_reader
        )

        with pytest.raises(MatterWsTransportError, match="reader failed"):
            await fetch_node_snapshot(
                request_timeout=0.2,
                settle_timeout=0,
                clock=lambda: clock_calls.append(True)
                or datetime(2026, 11, 4, tzinfo=timezone.utc),
            )
        assert milestones == ["reconciled", "reader-check"]
        assert clock_calls == []

    asyncio.run(scenario())


def test_device_inventory_decodes_endpoints_identity_and_optional_fields() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    records = extract_nodes_info(fixture["nodes"], server_info=fixture["serverInfo"])

    bridge, unavailable = records
    assert bridge["matter"]["matterId"] == "2D8B8A670D8BA10C-0000000000000001"
    assert bridge["matter"]["fabricId"] == 4660
    assert bridge["matter"]["isBridge"] is True
    assert bridge["matter"]["deviceLabel"] == "Living Room"
    assert bridge["matter"]["vendorName"] == "Acme"
    assert bridge["matter"]["vendorModel"] == "Bridge 2000"
    assert bridge["matter"]["vendorHwVersion"] == "rev-D"
    assert bridge["matter"]["vendorSwVersion"] == "1.2.3"
    assert bridge["matter"]["serialNumber"] == "SN-REDACTED-001"
    assert bridge["matter"]["matterVersion"] == "1.4.1"
    assert bridge["matter"]["lastInterview"] == "2026-08-02T10:30:00Z"
    assert bridge["matter"]["interviewVersion"] == 6
    assert bridge["matter"]["dataModelRevision"] == 6
    assert bridge["matter"]["specificationVersion"] == 65536
    assert bridge["matter"]["location"] == "US"
    assert bridge["matter"]["manufacturingDate"] == "20240115"
    assert bridge["matter"]["partNumber"] == "BR-2000-BOARD"
    assert bridge["matter"]["productUrl"] == "https://example.test/bridge-2000"
    assert bridge["matter"]["localConfigDisabled"] is False
    assert bridge["matter"]["reachable"] is True
    assert bridge["matter"]["uniqueId"] == "bridge-unique-id"
    assert bridge["matter"]["configurationVersion"] == 7
    assert [endpoint["endpointId"] for endpoint in bridge["endpoints"]] == [0, 1, 2]
    assert bridge["endpoints"][1]["deviceTypes"] == [{"deviceType": 256, "revision": 2}]
    assert bridge["endpoints"][2]["serverClusters"] == [6, 29, 1026]
    assert unavailable["matter"]["available"] is False
    assert unavailable["matter"]["deviceLabel"] is None
    assert unavailable["matter"]["serialNumber"] is None
    assert unavailable["matter"]["matterVersion"] is None
    assert unavailable["matter"]["lastInterview"] is None
    assert unavailable["endpoints"] == []


def test_collection_atomically_writes_devices_and_server_info(monkeypatch, tmp_path) -> None:
    async def scenario() -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        observed_at = "2026-11-04T22:00:00+00:00"

        async def fake_fetch_node_snapshot(*args, **kwargs):
            return ha_matter_ws_client.NodeSnapshot(
                uri="ws://fixture/ws",
                server_info=fixture["serverInfo"],
                frames=(),
                events=(),
                nodes=tuple(fixture["nodes"]),
                source_observed_at=observed_at,
            )

        monkeypatch.setattr("ha_matter_ws_fetch_all.fetch_node_snapshot", fake_fetch_node_snapshot)
        collection = await collect_devices()
        device_path = tmp_path / "devices.json"
        server_path = tmp_path / "server.json"

        assert collection.devices[0]["id"] == "matter:2D8B8A670D8BA10C-0000000000000001"
        assert collection.devices[0]["type"] == "matterDevice"
        assert collection.devices[0]["deviceLabel"] == "Living Room"
        assert collection.devices[0]["matter"]["endpoints"][1]["endpointId"] == 1

        save_collection(collection, device_output=device_path, server_info_output=server_path)

        saved_devices = json.loads(device_path.read_text(encoding="utf-8"))
        assert saved_devices[0]["matter"]["nodeId"] == 1
        assert saved_devices[0]["sourceObservedAt"] == observed_at
        assert saved_devices[0]["sourceObservationKind"] == "controller-snapshot"
        assert json.loads(server_path.read_text(encoding="utf-8"))["schema_version"] == 12
        assert not (tmp_path / "td-ha-matter-ws-collection.outcome.json").exists()

    asyncio.run(scenario())


def test_collection_reports_incremental_normalization_progress(monkeypatch) -> None:
    async def scenario() -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

        async def fake_fetch_node_snapshot(*args, **kwargs):
            return ha_matter_ws_client.NodeSnapshot(
                uri="ws://fixture/ws",
                server_info=fixture["serverInfo"],
                frames=(),
                events=(),
                nodes=tuple(fixture["nodes"]),
            )

        progress = []
        monkeypatch.setattr(
            "ha_matter_ws_fetch_all.fetch_node_snapshot", fake_fetch_node_snapshot
        )
        collection = await collect_devices(
            progress_callback=lambda completed, total, partial: progress.append(
                (completed, total, len(partial.devices))
            )
        )

        assert progress == [(1, 2, 1), (2, 2, 2)]
        assert collection.node_count == 2

    asyncio.run(scenario())


def test_collector_output_preserves_controller_observation_time(monkeypatch) -> None:
    async def scenario() -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        nodes = json.loads(DIAGNOSTIC_FIXTURE.read_text(encoding="utf-8"))["nodes"]
        observed_at = "2026-11-04T22:00:00+00:00"

        async def fake_fetch_node_snapshot(*args, **kwargs):
            return SimpleNamespace(
                uri="ws://fixture/ws",
                server_info=fixture["serverInfo"],
                frames=(),
                events=(),
                nodes=tuple(nodes),
                source_observed_at=observed_at,
            )

        monkeypatch.setattr(
            "ha_matter_ws_fetch_all.fetch_node_snapshot", fake_fetch_node_snapshot
        )
        collection = await collect_devices()

        assert collection.source_observed_at == observed_at
        for product in (
            collection.devices,
            collection.diagnostics,
            collection.mesh_diagnostics,
            collection.topology,
        ):
            assert product
            assert all(
                record["sourceObservedAt"] == observed_at
                and record["sourceObservationKind"] == "controller-snapshot"
                for record in product
                if not record.get("relationshipOnly")
            )

    asyncio.run(scenario())