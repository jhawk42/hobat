from __future__ import annotations

import asyncio
import json

from pathlib import Path
from typing import Any

import pytest

import ha_matter_ws_client

from ha_matter_ws_client import (
    HaMatterWsClient,
    MatterWsRequestTimeoutError,
    MatterWsTransportError,
    fetch_node_snapshot,
)
from ha_matter_ws_contract import MatterWsContractError, MatterWsResponseCorrelationError
from ha_matter_ws_extractor import extract_nodes_info
from ha_matter_ws_fetch_all import collect_devices, save_collection


FIXTURE = Path(__file__).parent / "fixtures" / "ha_matter_ws_phase2_inventory.json"


class FakeWebSocket:
    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        for frame in frames:
            self.incoming.put_nowait(json.dumps(frame))
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self.on_send = None

    async def recv(self) -> str:
        return await self.incoming.get()

    async def send(self, payload: str) -> None:
        message = json.loads(payload)
        self.sent.append(message)
        if self.on_send is not None:
            await self.on_send(message)

    async def close(self) -> None:
        self.closed = True

    def queue(self, frame: dict[str, Any]) -> None:
        self.incoming.put_nowait(json.dumps(frame))


def _server_info() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["serverInfo"]


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

        snapshot = await fetch_node_snapshot(request_timeout=0.2, settle_timeout=0.01)

        assert [message["command"] for message in socket.sent] == ["start_listening"]
        assert [node["node_id"] for node in snapshot.nodes] == [1, 2]
        assert snapshot.nodes[0]["available"] is False
        assert snapshot.nodes[0]["attributes"]["0/40/5"] == "Living Room"
        assert snapshot.nodes[1]["available"] is True

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

        async def fake_fetch_node_snapshot(*args, **kwargs):
            return ha_matter_ws_client.NodeSnapshot(
                uri="ws://fixture/ws",
                server_info=fixture["serverInfo"],
                frames=(),
                events=(),
                nodes=tuple(fixture["nodes"]),
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

        assert json.loads(device_path.read_text(encoding="utf-8"))[0]["matter"]["nodeId"] == 1
        assert json.loads(server_path.read_text(encoding="utf-8"))["schema_version"] == 12

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