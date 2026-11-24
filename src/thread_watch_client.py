"""Bounded read-only HTTP client for the Thread Watch review API."""

from __future__ import annotations

import asyncio
import json
import math
import os
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from thread_watch_snapshots import (
    ThreadWatchSnapshotSecurityError,
    assert_thread_watch_safe,
)


THREAD_WATCH_HOST_DEFAULT = "localhost"
THREAD_WATCH_PORT_DEFAULT = 9180
THREAD_WATCH_HOST_ENV = "TD_THREAD_WATCH_HOST"
THREAD_WATCH_PORT_ENV = "TD_THREAD_WATCH_PORT"
THREAD_WATCH_URI_ENV = "TD_THREAD_WATCH_URI"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_MEDIA_TYPE = "application/json"


class ThreadWatchError(RuntimeError):
    """Base Thread Watch collection error."""


class ThreadWatchArgumentError(ThreadWatchError, ValueError):
    """Invalid Thread Watch endpoint or timeout configuration."""


class ThreadWatchTransportError(ThreadWatchError):
    """Connection, timeout, redirect, or HTTP status failure."""


class ThreadWatchInvalidResponseError(ThreadWatchError):
    """The response is not an accepted Thread Watch devices inventory."""


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ThreadWatchArgumentError(f"{name} must be finite and greater than zero")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ThreadWatchArgumentError(
            f"{name} must be finite and greater than zero"
        ) from exc
    if not math.isfinite(result) or result <= 0:
        raise ThreadWatchArgumentError(f"{name} must be finite and greater than zero")
    return result


def _validate_host(host: object) -> str:
    if not isinstance(host, str):
        raise ThreadWatchArgumentError("Thread Watch host must be a nonempty string")
    value = host.strip()
    if (
        not value
        or any(character.isspace() for character in value)
        or "://" in value
        or "/" in value
        or "@" in value
        or "?" in value
        or "#" in value
    ):
        raise ThreadWatchArgumentError("Invalid Thread Watch host")
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1]
        if not inner or ":" not in inner:
            raise ThreadWatchArgumentError("Invalid bracketed Thread Watch host")
        return value
    if "[" in value or "]" in value:
        raise ThreadWatchArgumentError("Invalid bracketed Thread Watch host")
    return f"[{value}]" if ":" in value else value


def _validate_port(value: object) -> int:
    if isinstance(value, bool):
        raise ThreadWatchArgumentError(
            "Thread Watch port must be an integer between 1 and 65535"
        )
    text = str(value).strip()
    if (
        not text
        or len(text) > 5
        or not text.isascii()
        or not text.isdecimal()
        or not 1 <= int(text) <= 65535
    ):
        raise ThreadWatchArgumentError(
            "Thread Watch port must be an integer between 1 and 65535"
        )
    return int(text)


def validate_thread_watch_uri(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ThreadWatchArgumentError("Thread Watch URI must be a nonempty root URL")
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise ThreadWatchArgumentError("Invalid Thread Watch URI") from exc
    if (
        parsed.scheme not in ("http", "https")
        or parsed.hostname is None
        or any(character.isspace() for character in parsed.netloc)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or port is not None and not 1 <= port <= 65535
    ):
        raise ThreadWatchArgumentError(
            "Thread Watch URI must be an HTTP(S) root URL without credentials, query, or fragment"
        )
    netloc = parsed.netloc
    return urlunsplit((parsed.scheme, netloc, "", "", "")).rstrip("/")


def resolve_thread_watch_uri(
    *,
    uri: str | None = None,
    host: str | None = None,
    port: int | str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    env_map = os.environ if env is None else env
    if uri is not None:
        return validate_thread_watch_uri(uri)
    if host is None and port is None and THREAD_WATCH_URI_ENV in env_map:
        return validate_thread_watch_uri(env_map[THREAD_WATCH_URI_ENV])
    selected_host = host if host is not None else env_map.get(
        THREAD_WATCH_HOST_ENV, THREAD_WATCH_HOST_DEFAULT
    )
    selected_port = port if port is not None else env_map.get(
        THREAD_WATCH_PORT_ENV, THREAD_WATCH_PORT_DEFAULT
    )
    return f"http://{_validate_host(selected_host)}:{_validate_port(selected_port)}"


def _duplicate_checked_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ThreadWatchInvalidResponseError(
                "Thread Watch response contains duplicate JSON keys"
            )
        result[key] = value
    return result


def _parse_float(token: str) -> float:
    try:
        parsed = float(token)
        original = Decimal(token)
        rendered = Decimal(repr(parsed))
    except (ValueError, OverflowError, InvalidOperation) as exc:
        raise ThreadWatchInvalidResponseError(
            "Thread Watch response contains an unsupported JSON number"
        ) from exc
    if (
        not math.isfinite(parsed)
        or original != 0 and parsed == 0
        or original != rendered
    ):
        raise ThreadWatchInvalidResponseError(
            "Thread Watch response number does not round-trip exactly"
        )
    return parsed


def _reject_constant(_value: str) -> None:
    raise ThreadWatchInvalidResponseError(
        "Thread Watch response contains a non-finite JSON number"
    )


def parse_thread_watch_devices(
    payload: bytes,
    *,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> list[dict[str, Any]]:
    if len(payload) > max_bytes:
        raise ThreadWatchInvalidResponseError("Thread Watch response exceeds 16 MiB")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ThreadWatchInvalidResponseError(
            "Thread Watch response is not valid UTF-8 JSON"
        ) from exc
    try:
        envelope = json.loads(
            text,
            object_pairs_hook=_duplicate_checked_pairs,
            parse_float=_parse_float,
            parse_constant=_reject_constant,
        )
    except ThreadWatchInvalidResponseError:
        raise
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ThreadWatchInvalidResponseError(
            "Thread Watch response is not valid JSON"
        ) from exc
    if not isinstance(envelope, dict):
        raise ThreadWatchInvalidResponseError(
            "Thread Watch response must be a JSON object"
        )
    if envelope.get("error") is not None:
        raise ThreadWatchInvalidResponseError(
            "Thread Watch response reports an API error"
        )
    errors = envelope.get("errors")
    if errors not in (None, [], {}):
        raise ThreadWatchInvalidResponseError(
            "Thread Watch response reports API errors"
        )
    devices = envelope.get("devices")
    if not isinstance(devices, list) or any(
        not isinstance(device, dict) for device in devices
    ):
        raise ThreadWatchInvalidResponseError(
            "Thread Watch response devices must be an array of objects"
        )
    try:
        assert_thread_watch_safe(devices)
    except ThreadWatchSnapshotSecurityError as exc:
        raise ThreadWatchInvalidResponseError(str(exc)) from exc
    return devices


async def fetch_thread_watch_devices(
    uri: str | None = None,
    *,
    host: str | None = None,
    port: int | str | None = None,
    env: Mapping[str, str] | None = None,
    connect_timeout: float = 10.0,
    request_timeout: float = 30.0,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> tuple[list[dict[str, Any]], str]:
    root_uri = resolve_thread_watch_uri(uri=uri, host=host, port=port, env=env)
    connect = _positive_number(connect_timeout, "connect timeout")
    request = _positive_number(request_timeout, "request timeout")
    timeout = aiohttp.ClientTimeout(total=request, connect=connect, sock_connect=connect)
    endpoint = f"{root_uri}/api/devices"
    try:
        async with aiohttp.ClientSession(
            timeout=timeout, auto_decompress=True
        ) as session:
            # One collection attempt means no transparent retry on a stale keep-alive.
            session._retry_connection = False
            async with session.get(endpoint, allow_redirects=False) as response:
                if response.status != 200:
                    raise ThreadWatchTransportError(
                        f"Thread Watch request failed with HTTP {response.status}"
                    )
                content_type = response.headers.get("Content-Type", "")
                media_type, _, parameters = content_type.partition(";")
                if media_type.strip().lower() != _MEDIA_TYPE:
                    raise ThreadWatchInvalidResponseError(
                        "Thread Watch response must use application/json"
                    )
                if "charset=" in parameters.lower() and "charset=utf-8" not in (
                    parameters.lower().replace(" ", "")
                ):
                    raise ThreadWatchInvalidResponseError(
                        "Thread Watch response must use UTF-8 JSON"
                    )
                chunks = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    if len(chunks) + len(chunk) > max_bytes:
                        raise ThreadWatchInvalidResponseError(
                            "Thread Watch response exceeds 16 MiB"
                        )
                    chunks.extend(chunk)
    except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
        raise ThreadWatchTransportError("Thread Watch request failed") from exc
    return parse_thread_watch_devices(bytes(chunks), max_bytes=max_bytes), endpoint
