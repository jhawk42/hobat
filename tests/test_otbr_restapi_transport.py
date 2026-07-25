from __future__ import annotations

import io
import logging
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

import otbr_restapi_util as client_module


class FakeHeaders(dict):
    def get(self, key: str, default=None):
        for existing_key, value in self.items():
            if existing_key.lower() == key.lower():
                return value
        return default


class FakeResponse:
    def __init__(
        self,
        payload: bytes = b'{"data":{"id":"node-1","type":"threadBorderRouter","attributes":{"role":"router"}}}',
        content_type: str = "application/vnd.api+json",
    ) -> None:
        self.payload = payload
        self.headers = FakeHeaders({"Content-Type": content_type})
        self.status = 200

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


def make_http_error(
    status: int,
    *,
    detail: str = "temporarily unavailable",
    retry_after: str | None = None,
) -> HTTPError:
    headers = FakeHeaders({"Content-Type": "application/vnd.api+json"})
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    body = (
        '{"errors":[{"title":"Service Unavailable","status":%d,"detail":"%s"}]}'
        % (status, detail)
    ).encode()
    return HTTPError(
        url="http://example.test/api/node",
        code=status,
        msg="Service Unavailable",
        hdrs=headers,
        fp=io.BytesIO(body),
    )


def test_get_retries_transient_error_and_recovers(monkeypatch) -> None:
    client = client_module.OTBRRestApiClient(
        base_url="http://example.test", retries=3
    )
    sleeps: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", sleeps.append)

    with patch.object(
        client_module,
        "urlopen",
        side_effect=[make_http_error(503, retry_after="0"), FakeResponse()],
    ) as urlopen:
        node = client.get_node()

    assert node["id"] == "node-1"
    assert urlopen.call_count == 2
    assert sleeps == []


def test_post_does_not_retry_even_when_retries_are_configured(monkeypatch) -> None:
    client = client_module.OTBRRestApiClient(
        base_url="http://example.test", retries=3
    )
    sleep = patch.object(client_module.time, "sleep")

    with sleep as sleep_mock, patch.object(
        client_module,
        "urlopen",
        side_effect=make_http_error(503),
    ) as urlopen:
        with pytest.raises(client_module.OTBRHTTPError) as error:
            client.enqueue_update_device_collection_task(
                max_age=30, max_retries=2, device_count=255, timeout=30
            )

    assert error.value.status_code == 503
    assert urlopen.call_count == 1
    sleep_mock.assert_not_called()


def test_retry_after_and_backoff_are_capped(monkeypatch) -> None:
    client = client_module.OTBRRestApiClient(
        base_url="http://example.test",
        retries=2,
        retry_backoff_max=3.0,
    )
    sleeps: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", sleeps.append)

    with patch.object(
        client_module,
        "urlopen",
        side_effect=[make_http_error(503, retry_after="30"), FakeResponse()],
    ):
        client.get_node()

    assert sleeps == [3.0]


def test_optional_jitter_is_bounded_and_deterministic(monkeypatch) -> None:
    client = client_module.OTBRRestApiClient(
        base_url="http://example.test",
        retries=2,
        retry_backoff_max=2.0,
        retry_jitter=0.5,
    )
    sleeps: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", sleeps.append)
    monkeypatch.setattr(client_module.random, "uniform", lambda lower, upper: 0.25)

    with patch.object(
        client_module,
        "urlopen",
        side_effect=[make_http_error(503), FakeResponse()],
    ):
        client.get_node()

    assert sleeps == [1.25]


def test_action_get_timeout_is_bounded_by_workflow_deadline(monkeypatch) -> None:
    client = client_module.OTBRRestApiClient(
        base_url="http://example.test", timeout=10
    )
    monkeypatch.setattr(client_module.time, "monotonic", lambda: 100.0)

    with patch.object(client_module, "urlopen", return_value=FakeResponse()) as urlopen:
        client.get_action("action-1", deadline=103.0)

    assert urlopen.call_args.kwargs["timeout"] == 3.0


def test_expired_workflow_deadline_prevents_http_request(monkeypatch) -> None:
    client = client_module.OTBRRestApiClient(base_url="http://example.test")
    monkeypatch.setattr(client_module.time, "monotonic", lambda: 100.0)

    with patch.object(client_module, "urlopen") as urlopen:
        with pytest.raises(client_module.OTBRConnectionError, match="deadline expired"):
            client.get_action("action-1", deadline=100.0)

    urlopen.assert_not_called()


def test_action_request_expiring_at_deadline_remains_action_timeout(monkeypatch) -> None:
    client = client_module.OTBRRestApiClient(base_url="http://example.test")
    monotonic_values = iter([100.0, 101.0])
    monkeypatch.setattr(
        client_module.time, "monotonic", lambda: next(monotonic_values)
    )
    monkeypatch.setattr(
        client,
        "get_action",
        lambda action_id, raw=False, deadline=None: (_ for _ in ()).throw(
            client_module.OTBRConnectionError("request deadline expired")
        ),
    )

    with pytest.raises(client_module.OTBRActionTimeoutError) as error:
        client.wait_for_action("action-1", poll_timeout=1)

    assert error.value.status == "unknown"
    assert error.value.action is None


def test_sensitive_json_request_fields_are_redacted_from_debug_logs(caplog) -> None:
    client = client_module.OTBRRestApiClient(base_url="http://example.test")
    caplog.set_level(logging.DEBUG)

    with patch.object(
        client_module,
        "urlopen",
        return_value=FakeResponse(payload=b'{"data":[]}'),
    ):
        client.enqueue_add_thread_device_task(
            pskd="SUPER-SECRET-PSKD",
            eui="0011223344556677",
            timeout=30,
        )

    assert "SUPER-SECRET-PSKD" not in caplog.text
    assert '"pskd": "<redacted>"' in caplog.text
    assert "0011223344556677" in caplog.text


def test_text_request_body_is_fully_redacted() -> None:
    rendered = client_module.OTBRRestApiClient._redact_request_body(
        b"SENSITIVE-DATASET-TLV", "text/plain"
    )

    assert rendered == "<redacted text/plain body>"


def test_terminal_retry_error_preserves_last_parsed_details(monkeypatch) -> None:
    client = client_module.OTBRRestApiClient(
        base_url="http://example.test", retries=2
    )
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)

    with patch.object(
        client_module,
        "urlopen",
        side_effect=[
            make_http_error(503, detail="first failure"),
            make_http_error(503, detail="terminal failure"),
        ],
    ):
        with pytest.raises(client_module.OTBRHTTPError) as error:
            client.get_node()

    assert error.value.status_code == 503
    assert error.value.errors[0].detail == "terminal failure"
    assert error.value.payload["errors"][0]["detail"] == "terminal failure"
    assert "terminal failure" in error.value.body
