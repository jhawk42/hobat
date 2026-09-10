"""Correlated Home Assistant Matter WebSocket transport and node snapshots."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging

from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Mapping

import websockets

from ha_matter_ws_contract import (
    DEFAULT_HA_MATTER_WS_URI,
    MatterWsCommandError,
    MatterWsContractError,
    MatterWsResponseCorrelationError,
    classify_frame,
    resolve_default_ha_matter_ws_uri,
    validate_server_info,
)


DEFAULT_MATTER_WS_URI = DEFAULT_HA_MATTER_WS_URI
_MAX_LATE_RESPONSE_IDS = 100
_MAX_PING_ADDRESSES = 256


class MatterWsTransportError(RuntimeError):
    """The WebSocket connection or frame stream failed."""


class MatterWsRequestTimeoutError(MatterWsTransportError):
    """A correlated request did not complete before its deadline."""


@dataclass(frozen=True)
class NodeSnapshot:
    uri: str
    server_info: dict[str, Any]
    frames: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]
    nodes: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class FetchAllResult:
    uri: str
    messages: tuple[dict[str, Any], ...]
    nodes: tuple[dict[str, Any], ...]
    server_info: dict[str, Any]
    events: tuple[dict[str, Any], ...]


class HaMatterWsClient:
    """Route one bounded frame stream to correlated requests and events."""

    def __init__(
        self,
        uri: str | None = None,
        *,
        connect_timeout: float = 10.0,
        request_timeout: float = 5.0,
        max_frame_size: int = 4 * 1024 * 1024,
        max_frames: int = 500,
    ) -> None:
        if min(connect_timeout, request_timeout) <= 0:
            raise ValueError("Matter WebSocket timeouts must be greater than zero")
        if max_frame_size <= 0 or max_frames <= 0:
            raise ValueError("Matter WebSocket frame limits must be greater than zero")
        self.uri = resolve_default_ha_matter_ws_uri() if uri is None else uri
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout
        self.max_frame_size = max_frame_size
        self.max_frames = max_frames
        self._websocket: Any | None = None
        self._message_id = 0
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._late_response_ids: dict[str, None] = {}
        self._frames: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._event_received = asyncio.Event()
        self._server_info: dict[str, Any] | None = None
        self._closing = False

    @property
    def server_info(self) -> dict[str, Any]:
        if self._server_info is None:
            raise MatterWsTransportError("Matter WebSocket handshake is incomplete")
        return dict(self._server_info)

    @property
    def frames(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._frames)

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._events)

    async def __aenter__(self) -> "HaMatterWsClient":
        try:
            connection = websockets.connect(self.uri, max_size=self.max_frame_size)
            if inspect.isawaitable(connection):
                connection = await asyncio.wait_for(
                    connection, timeout=self.connect_timeout
                )
            self._websocket = connection
            server_info = await self._receive_frame(timeout=self.connect_timeout)
            validate_server_info(server_info)
            self._server_info = dict(server_info)
            self._frames.append(dict(server_info))
            self._reader_task = asyncio.create_task(self._reader_loop())
            return self
        except asyncio.CancelledError:
            await self.close()
            raise
        except MatterWsContractError:
            await self.close()
            raise
        except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as exc:
            await self.close()
            raise MatterWsTransportError(
                f"Unable to establish Matter WebSocket session: {exc}"
            ) from exc

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        self._closing = True
        if self._reader_task is not None:
            self._reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        self._fail_pending(MatterWsTransportError("Matter WebSocket session closed"))
        if self._websocket is not None:
            await self._websocket.close()
            self._websocket = None

    def _next_message_id(self) -> str:
        self._message_id += 1
        return str(self._message_id)

    async def request(
        self,
        command: str,
        *,
        args: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        if self._websocket is None or self._reader_task is None:
            raise MatterWsTransportError("Matter WebSocket client is not connected")
        message_id = self._next_message_id()
        future = asyncio.get_running_loop().create_future()
        self._pending[message_id] = future
        may_receive_late_response = False
        payload: dict[str, Any] = {"message_id": message_id, "command": command}
        if args is not None:
            payload["args"] = dict(args)
        try:
            await self._websocket.send(json.dumps(payload))
            return await asyncio.wait_for(
                asyncio.shield(future),
                timeout=self.request_timeout if timeout is None else timeout,
            )
        except asyncio.TimeoutError as exc:
            may_receive_late_response = True
            raise MatterWsRequestTimeoutError(
                f"Matter command {command!r} timed out (message_id={message_id!r})"
            ) from exc
        except asyncio.CancelledError:
            may_receive_late_response = True
            raise
        except websockets.WebSocketException as exc:
            raise MatterWsTransportError(
                f"Unable to send Matter command {command!r}: {exc}"
            ) from exc
        finally:
            pending = self._pending.pop(message_id, None)
            if pending is not None and not pending.done():
                pending.cancel()
            if may_receive_late_response:
                self._late_response_ids[message_id] = None
                while len(self._late_response_ids) > _MAX_LATE_RESPONSE_IDS:
                    self._late_response_ids.pop(next(iter(self._late_response_ids)))

    async def ping_node(self, node_id: int, attempts: int = 1) -> dict[str, bool]:
        """Ping one Matter node and validate its per-address response."""
        result = await self.request(
            "ping_node",
            args={"node_id": node_id, "attempts": attempts},
        )
        if not isinstance(result, dict):
            raise MatterWsContractError("ping_node result must be an address map")
        if len(result) > _MAX_PING_ADDRESSES:
            raise MatterWsContractError(
                f"ping_node result exceeds {_MAX_PING_ADDRESSES} addresses"
            )
        validated: dict[str, bool] = {}
        for address, success in result.items():
            if not isinstance(address, str) or not address:
                raise MatterWsContractError(
                    "ping_node result addresses must be non-empty strings"
                )
            if type(success) is not bool:
                raise MatterWsContractError(
                    "ping_node result values must be boolean"
                )
            validated[address] = success
        return validated

    async def wait_for_event_settle(self, settle_timeout: float) -> None:
        if settle_timeout < 0:
            raise ValueError("settle_timeout must not be negative")
        if settle_timeout == 0:
            return
        while True:
            self._event_received.clear()
            try:
                await asyncio.wait_for(
                    self._event_received.wait(), timeout=settle_timeout
                )
            except asyncio.TimeoutError:
                return

    async def _receive_frame(self, *, timeout: float | None = None) -> dict[str, Any]:
        if self._websocket is None:
            raise MatterWsTransportError("Matter WebSocket client is not connected")
        response = self._websocket.recv()
        if timeout is not None:
            response = await asyncio.wait_for(response, timeout=timeout)
        else:
            response = await response
        if not isinstance(response, str):
            raise MatterWsTransportError("Matter WebSocket returned a non-text frame")
        try:
            frame = json.loads(response)
        except json.JSONDecodeError as exc:
            raise MatterWsTransportError("Matter WebSocket returned invalid JSON") from exc
        if not isinstance(frame, dict):
            raise MatterWsTransportError("Matter WebSocket frame must be an object")
        return frame

    async def _reader_loop(self) -> None:
        try:
            while not self._closing:
                frame = await self._receive_frame()
                if len(self._frames) >= self.max_frames:
                    raise MatterWsTransportError(
                        f"Matter WebSocket exceeded {self.max_frames} frames"
                    )
                self._frames.append(frame)
                kind = classify_frame(frame)
                if kind == "server_info":
                    raise MatterWsContractError("Received duplicate server-info frame")
                if kind == "event":
                    self._events.append(frame)
                    self._event_received.set()
                    continue

                message_id = frame["message_id"]
                future = self._pending.get(message_id)
                if future is None:
                    if message_id in self._late_response_ids:
                        self._late_response_ids.pop(message_id)
                        logging.debug(
                            "Ignoring late Matter response for message_id %r", message_id
                        )
                        continue
                    raise MatterWsResponseCorrelationError(
                        f"Response for unknown message_id {message_id!r}"
                    )
                if kind == "error":
                    future.set_exception(
                        MatterWsCommandError(
                            message_id,
                            frame["error_code"],
                            frame.get("details")
                            if isinstance(frame.get("details"), str)
                            else None,
                        )
                    )
                else:
                    future.set_result(frame["result"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(exc)

    def _fail_pending(self, exc: BaseException) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)


MatterWSClient = HaMatterWsClient


def _node_id(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _merge_node(current: dict[str, Any] | None, update: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(current or {})
    merged.update(update)
    if current is not None and isinstance(current.get("attributes"), dict):
        updated_attributes = update.get("attributes")
        if isinstance(updated_attributes, dict):
            merged["attributes"] = {**current["attributes"], **updated_attributes}
        elif "attributes" not in update:
            merged["attributes"] = dict(current["attributes"])
    return merged


def reconcile_nodes(
    initial_nodes: list[Any], events: tuple[dict[str, Any], ...]
) -> tuple[dict[str, Any], ...]:
    """Apply node events over a deduplicated initial controller snapshot."""

    nodes: dict[int, dict[str, Any]] = {}
    for entry in initial_nodes:
        if isinstance(entry, dict) and (node_id := _node_id(entry.get("node_id"))) is not None:
            nodes[node_id] = dict(entry)

    for event in events:
        event_name = event.get("event")
        data = event.get("data")
        if event_name == "node_removed":
            node_id = _node_id(data.get("node_id")) if isinstance(data, dict) else _node_id(data)
            if node_id is not None:
                nodes.pop(node_id, None)
            continue
        if event_name not in {"node_added", "node_updated", "attribute_updated"}:
            continue
        if not isinstance(data, dict) or (node_id := _node_id(data.get("node_id"))) is None:
            continue
        nodes[node_id] = _merge_node(nodes.get(node_id), data)

    return tuple(nodes[node_id] for node_id in sorted(nodes))


async def fetch_node_snapshot(
    uri: str | None = None,
    *,
    connect_timeout: float = 10.0,
    request_timeout: float = 5.0,
    settle_timeout: float = 0.25,
    max_frame_size: int = 4 * 1024 * 1024,
    max_frames: int = 500,
) -> NodeSnapshot:
    """Fetch one bounded inventory and reconcile events without a second request."""

    async with HaMatterWsClient(
        uri,
        connect_timeout=connect_timeout,
        request_timeout=request_timeout,
        max_frame_size=max_frame_size,
        max_frames=max_frames,
    ) as client:
        result = await client.request("start_listening")
        if not isinstance(result, list):
            raise MatterWsContractError("start_listening result must be a node array")
        await client.wait_for_event_settle(settle_timeout)
        return NodeSnapshot(
            uri=client.uri,
            server_info=client.server_info,
            frames=client.frames,
            events=client.events,
            nodes=reconcile_nodes(result, client.events),
        )


async def fetch_all_nodes(
    uri: str | None = None,
    *,
    idle_timeout: float = 0.25,
    recv_timeout: float = 5.0,
    max_messages: int = 500,
) -> FetchAllResult:
    """Compatibility wrapper for the Phase 2 snapshot operation."""

    snapshot = await fetch_node_snapshot(
        uri,
        request_timeout=recv_timeout,
        settle_timeout=idle_timeout,
        max_frames=max_messages,
    )
    return FetchAllResult(
        uri=snapshot.uri,
        messages=snapshot.frames,
        nodes=snapshot.nodes,
        server_info=snapshot.server_info,
        events=snapshot.events,
    )


async def access_matter_server(uri: str | None = None) -> None:
    result = await fetch_all_nodes(uri=uri)
    for message in result.messages:
        print(f"Received from server: {json.dumps(message, indent=2)}")