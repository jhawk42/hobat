import json
import asyncio
from dataclasses import dataclass
from typing import Any

import websockets


DEFAULT_MATTER_WS_URI = "ws://localhost:5580/ws"


@dataclass
class FetchAllResult:
    """Container for websocket frames and extracted node list."""

    uri: str
    messages: list[dict[str, Any]]
    nodes: list[dict[str, Any]]


class MatterWSClient:
    """Small reusable Matter websocket client."""

    def __init__(
        self,
        uri: str = DEFAULT_MATTER_WS_URI,
        *,
        connect_timeout: float = 10.0,
        recv_timeout: float = 5.0,
    ) -> None:
        self.uri = uri
        self.connect_timeout = connect_timeout
        self.recv_timeout = recv_timeout
        self._websocket: Any | None = None
        self._message_id = 0

    async def __aenter__(self) -> "MatterWSClient":
        self._websocket = await asyncio.wait_for(
            websockets.connect(self.uri),
            timeout=self.connect_timeout,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._websocket is not None:
            await self._websocket.close()
            self._websocket = None

    def _next_message_id(self) -> str:
        self._message_id += 1
        return str(self._message_id)

    async def send_command(self, command: str, **extra_fields: Any) -> str:
        if self._websocket is None:
            raise RuntimeError("MatterWSClient is not connected")

        message_id = self._next_message_id()
        payload = {
            "message_id": message_id,
            "command": command,
        }
        payload.update(extra_fields)
        await self._websocket.send(json.dumps(payload))
        return message_id

    async def recv_json(self) -> dict[str, Any] | None:
        if self._websocket is None:
            raise RuntimeError("MatterWSClient is not connected")

        try:
            response = await asyncio.wait_for(
                self._websocket.recv(),
                timeout=self.recv_timeout,
            )
        except asyncio.TimeoutError:
            return None

        if not isinstance(response, str):
            return None

        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            return None

        return data if isinstance(data, dict) else None


def _extract_nodes_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for message in messages:
        result = message.get("result")
        if not isinstance(result, list):
            continue
        for entry in result:
            if isinstance(entry, dict):
                nodes.append(entry)
    return nodes


async def fetch_all_nodes(
    uri: str = DEFAULT_MATTER_WS_URI,
    *,
    idle_timeout: float = 2.0,
    recv_timeout: float = 5.0,
    max_messages: int = 500,
) -> FetchAllResult:
    """Fetch all available node frames from the Matter websocket endpoint.

    Protocol sequence:
    1. Send `start_listening`
    2. Send `get_nodes`
    3. Read messages until idle timeout (no new message) or max_messages
    """

    async with MatterWSClient(uri=uri, recv_timeout=recv_timeout) as client:
        await client.send_command("start_listening")
        await client.send_command("get_nodes")

        messages: list[dict[str, Any]] = []
        idle_deadline = asyncio.get_running_loop().time() + idle_timeout

        while len(messages) < max_messages:
            remaining = idle_deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break

            previous_timeout = client.recv_timeout
            client.recv_timeout = min(previous_timeout, remaining)
            msg = await client.recv_json()
            client.recv_timeout = previous_timeout

            if msg is None:
                break

            messages.append(msg)
            idle_deadline = asyncio.get_running_loop().time() + idle_timeout

    nodes = _extract_nodes_from_messages(messages)
    return FetchAllResult(uri=uri, messages=messages, nodes=nodes)

async def access_matter_server(uri: str = DEFAULT_MATTER_WS_URI) -> None:
    """Backward-compatible helper used by existing manual testing flow."""

    result = await fetch_all_nodes(uri=uri)
    for message in result.messages:
        print(f"Received from server: {json.dumps(message, indent=2)}")

if __name__ == "__main__":
    asyncio.run(access_matter_server())
