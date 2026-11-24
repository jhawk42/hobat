from __future__ import annotations

import asyncio
import copy
import gzip
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from thread_watch_client import (
    ThreadWatchArgumentError,
    ThreadWatchInvalidResponseError,
    ThreadWatchTransportError,
    fetch_thread_watch_devices,
    parse_thread_watch_devices,
    resolve_thread_watch_uri,
)
from thread_watch_snapshots import (
    ThreadWatchSnapshotSecurityError,
    build_device_snapshot,
)
import thread_watch_cli
from util_data import read_network_scope


def test_builder_preserves_rows_order_duplicates_and_nested_values() -> None:
    original = {
        "addr": "AABBCCDDEEFF0011",
        "rloc16": "9040",
        "name": "",
        "parent_addr": "FEDCBA9876543210",
        "parent": "FEDCBA9876543210",
        "role": "child",
        "router_id": 36,
        "border_router": "",
        "leader": False,
        "key_sequences": {"latest": 0, "nested": [False, None]},
        "future": {"threadWatch": "preserved", "__proto__": {"value": 1}},
    }
    duplicate = copy.deepcopy(original)
    before = copy.deepcopy([original, duplicate, {"unknown": 0}])

    snapshot = build_device_snapshot(before)

    assert len(snapshot.rows) == 3
    assert [row["threadWatch"] for row in snapshot.rows] == before
    for row in snapshot.rows[:2]:
        assert row["type"] == "threadDevice"
        assert row["extAddress"] == "aabbccddeeff0011"
        assert row["rloc16"] == "0x9040"
        assert row["deviceLabel"] == ""
        assert row["parentExtAddress"] == "fedcba9876543210"
        assert row["parentDeviceLabel"] == "FEDCBA9876543210"
        assert row["parentRouterId"] == 36
        assert row["isBorderRouter"] is True
        assert "isRouter" not in row
        assert "isLeader" not in row
    assert snapshot.rows[2]["threadWatch"] == {"unknown": 0}
    assert "extAddress" not in snapshot.rows[2]
    assert before == [original, duplicate, {"unknown": 0}]


@pytest.mark.parametrize(
    ("source", "expected", "absent"),
    [
        (
            {
                "addr": "0000000000000001",
                "rloc16": "0000",
                "name": None,
                "parent_addr": None,
                "parent": None,
                "role": "router",
                "router_id": 0,
                "border_router": None,
                "leader": True,
            },
            {
                "extAddress": "0000000000000001",
                "rloc16": "0x0000",
                "deviceLabel": None,
                "parentExtAddress": None,
                "parentDeviceLabel": None,
                "role": "router",
                "routerId": 0,
                "isRouter": True,
                "isLeader": True,
            },
            ("isBorderRouter", "parentRouterId"),
        ),
        (
            {
                "addr": "FFFFFFFFFFFFFFFF",
                "rloc16": "0xF800",
                "role": "router",
                "router_id": 62,
                "border_router": "router.local",
                "leader": False,
            },
            {
                "extAddress": "ffffffffffffffff",
                "rloc16": "0xf800",
                "role": "router",
                "routerId": 62,
                "isRouter": True,
                "isBorderRouter": True,
            },
            ("isLeader", "parentRouterId"),
        ),
    ],
)
def test_builder_projects_positive_markers_and_router_ids(
    source, expected, absent
) -> None:
    row = build_device_snapshot([source]).rows[0]

    assert expected.items() <= row.items()
    for field in absent:
        assert field not in row


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("rloc16", "12345", "invalid"),
        ("role", "reed", "unsupported-value"),
        ("name", 5, "invalid-value-type"),
        ("leader", 1, "invalid-value-type"),
        ("leader", "true", "invalid-value-type"),
        ("parent", [], "invalid-value-type"),
    ],
)
def test_builder_preserves_invalid_optional_values_and_warns(
    field, value, reason
) -> None:
    source = {"addr": "0000000000000001", field: value}

    snapshot = build_device_snapshot([source])

    assert snapshot.rows[0]["threadWatch"][field] == value
    assert any(
        warning.row_index == 0
        and warning.field == field
        and warning.reason == reason
        for warning in snapshot.warnings
    )


@pytest.mark.parametrize("addr", [None, "", "0000000000000000", "short", 1])
def test_builder_never_guesses_invalid_identity(addr) -> None:
    snapshot = build_device_snapshot([{"addr": addr, "name": "visible"}])

    assert "extAddress" not in snapshot.rows[0]
    assert snapshot.rows[0]["deviceLabel"] == "visible"
    assert any(warning.field == "addr" for warning in snapshot.warnings)


@pytest.mark.parametrize(
    ("role", "router_id", "rloc16", "warning"),
    [
        ("router", -1, "0x0000", "out-of-range"),
        ("router", 63, "0xfc00", "out-of-range"),
        ("router", True, "0x0400", "invalid-value-type"),
        ("router", 1.0, "0x0400", "invalid-value-type"),
        ("router", "1", "0x0400", "invalid-value-type"),
        ("router", 2, "0x0400", "rloc-mismatch"),
        ("child", 1, None, "rloc-required"),
        ("unknown", 1, "0x0400", None),
    ],
)
def test_builder_rejects_invalid_or_non_role_specific_router_ids(
    role, router_id, rloc16, warning
) -> None:
    source = {"addr": "0000000000000001", "role": role, "router_id": router_id}
    if rloc16 is not None:
        source["rloc16"] = rloc16

    snapshot = build_device_snapshot([source])
    row = snapshot.rows[0]

    assert "routerId" not in row
    assert "parentRouterId" not in row
    if warning is None:
        assert not any(item.field == "router_id" for item in snapshot.warnings)
    else:
        assert any(
            item.field == "router_id" and item.reason == warning
            for item in snapshot.warnings
        )


def test_builder_retains_child_leader_conflict_and_raw_values() -> None:
    snapshot = build_device_snapshot(
        [
            {
                "addr": "0000000000000001",
                "role": "child",
                "rloc16": "0x0401",
                "router_id": 1,
                "leader": True,
                "border_router": "",
                "quiet": False,
                "frames": 0,
            }
        ]
    )
    row = snapshot.rows[0]

    assert row["isLeader"] is True
    assert row["isBorderRouter"] is True
    assert row["parentRouterId"] == 1
    assert row["threadWatch"]["quiet"] is False
    assert any(item.reason == "child-leader-conflict" for item in snapshot.warnings)


def test_builder_rejects_nested_credentials_without_stripping() -> None:
    with pytest.raises(ThreadWatchSnapshotSecurityError):
        build_device_snapshot(
            [{"addr": "0000000000000001", "nested": {"api_key": "not-a-real-key"}}]
        )


def test_builder_accepts_benign_key_sequences() -> None:
    row = build_device_snapshot(
        [{"addr": "0000000000000001", "key_sequences": {"mac": {"latest": 0}}}]
    ).rows[0]

    assert row["threadWatch"]["key_sequences"]["mac"]["latest"] == 0


def test_builder_enriches_unique_router_with_otbr_style_children() -> None:
    snapshot = build_device_snapshot(
        [
            {
                "addr": "1111111111111111",
                "name": "Child",
                "role": "child",
                "rloc16": "0x901f",
                "router_id": 36,
                "parent_addr": "aaaaaaaaaaaaaaaa",
            },
            {
                "addr": "AAAAAAAAAAAAAAAA",
                "name": "Router",
                "role": "router",
                "rloc16": "9000",
                "router_id": 36,
            },
        ]
    )

    child, parent = snapshot.rows
    assert "children" not in child
    assert parent["children"] == [
        {
            "id": "0x001f",
            "rloc16": "0x901f",
            "role": "child",
            "extAddress": "1111111111111111",
            "deviceLabel": "Child",
        }
    ]
    assert parent["totalChildren"] == 1
    assert set(parent["children"][0]) == {
        "id",
        "rloc16",
        "role",
        "extAddress",
        "deviceLabel",
    }
    assert parent["threadWatch"] == {
        "addr": "AAAAAAAAAAAAAAAA",
        "name": "Router",
        "role": "router",
        "rloc16": "9000",
        "router_id": 36,
    }


@pytest.mark.parametrize(
    "parent",
    [
        {
            "addr": "aaaaaaaaaaaaaaaa",
            "role": "router",
            "rloc16": "0x8800",
            "router_id": 34,
        },
        {
            "addr": "aaaaaaaaaaaaaaaa",
            "role": "child",
            "rloc16": "0x9000",
            "router_id": 36,
        },
    ],
)
def test_builder_does_not_attach_child_without_unique_matching_router(
    parent,
) -> None:
    snapshot = build_device_snapshot(
        [
            parent,
            {
                "addr": "1111111111111111",
                "role": "child",
                "rloc16": "0x9001",
                "router_id": 36,
                "parent_addr": "aaaaaaaaaaaaaaaa",
            },
        ]
    )

    assert all("children" not in row for row in snapshot.rows)


def test_builder_requires_unique_parent_address_before_rloc_match() -> None:
    snapshot = build_device_snapshot(
        [
            {
                "addr": "aaaaaaaaaaaaaaaa",
                "role": "router",
                "rloc16": "0x8800",
                "router_id": 34,
            },
            {
                "addr": "aaaaaaaaaaaaaaaa",
                "role": "router",
                "rloc16": "0x9000",
                "router_id": 36,
            },
            {
                "addr": "1111111111111111",
                "role": "child",
                "rloc16": "0x9001",
                "router_id": 36,
                "parent_addr": "aaaaaaaaaaaaaaaa",
            },
        ]
    )

    assert all("children" not in row for row in snapshot.rows)


@pytest.mark.parametrize("child_rloc16", ["0x9000", "9000"])
def test_builder_rejects_router_rloc_as_child_locator(child_rloc16) -> None:
    snapshot = build_device_snapshot(
        [
            {
                "addr": "aaaaaaaaaaaaaaaa",
                "role": "router",
                "rloc16": "0x9000",
                "router_id": 36,
            },
            {
                "addr": "1111111111111111",
                "role": "child",
                "rloc16": child_rloc16,
                "router_id": 36,
                "parent_addr": "aaaaaaaaaaaaaaaa",
            },
        ]
    )

    assert "children" not in snapshot.rows[0]


def test_builder_does_not_choose_between_duplicate_parent_rows() -> None:
    parent = {
        "addr": "aaaaaaaaaaaaaaaa",
        "role": "router",
        "rloc16": "0x9000",
        "router_id": 36,
    }
    snapshot = build_device_snapshot(
        [
            parent,
            copy.deepcopy(parent),
            {
                "addr": "1111111111111111",
                "role": "child",
                "rloc16": "0x9001",
                "router_id": 36,
                "parent_addr": "aaaaaaaaaaaaaaaa",
            },
        ]
    )

    assert all("children" not in row for row in snapshot.rows)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"devices":[{"nested":{"same":1,"same":2}}]}',
        b'{"devices":[NaN]}',
        b'{"devices":[Infinity]}',
        b'{"devices":[-Infinity]}',
        b'{"devices":[1.234567890123456789]}',
        b'{"devices":[1e-4000]}',
        b'{"devices":[{"plain":1}],"error":"private"}',
        b'{"devices":[{"plain":1}],"errors":["private"]}',
        b'{"devices":[1]}',
        b'{"devices":{}}',
        b"[]",
        b'{"devices":[{"private_api_token":"not-for-test-output"}]}',
        b"\xff",
    ],
)
def test_parser_rejects_invalid_or_unsafe_responses_without_raw_values(
    payload
) -> None:
    with pytest.raises(ThreadWatchInvalidResponseError) as raised:
        parse_thread_watch_devices(payload)

    assert "private" not in str(raised.value)
    assert "not-for-test-output" not in str(raised.value)


def test_parser_preserves_large_exact_integers_and_ordinary_decimals() -> None:
    devices = parse_thread_watch_devices(
        b'{"devices":[{"integer":9007199254740993,"decimal":1795291939.1}]}'
    )

    assert devices == [{"integer": 9007199254740993, "decimal": 1795291939.1}]


def test_parser_rejects_integer_beyond_interpreter_limit() -> None:
    number = b"7" * 5000

    with pytest.raises(ThreadWatchInvalidResponseError):
        parse_thread_watch_devices(b'{"devices":[{"integer":' + number + b"}]}")


class ThreadWatchClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.requests = []

        async def devices(request: web.Request) -> web.Response:
            self.requests.append((request.path, request.query_string))
            return web.json_response({"devices": [{"addr": "0000000000000001"}]})

        app = web.Application()
        app.router.add_get("/api/devices", devices)
        self.server = TestServer(app)
        await self.server.start_server()
        self.addAsyncCleanup(self.server.close)
        self.uri = str(self.server.make_url("")).rstrip("/")

    async def test_fetch_uses_exactly_one_unfiltered_request(self) -> None:
        rows, endpoint = await fetch_thread_watch_devices(self.uri)

        self.assertEqual(rows, [{"addr": "0000000000000001"}])
        self.assertEqual(endpoint, f"{self.uri}/api/devices")
        self.assertEqual(self.requests, [("/api/devices", "")])

    async def test_fetch_rejects_redirects_without_following(self) -> None:
        async def redirected(request: web.Request) -> web.StreamResponse:
            self.requests.append((request.path, request.query_string))
            raise web.HTTPFound("/api/devices")

        app = web.Application()
        app.router.add_get("/redirect", redirected)
        app.router.add_get("/api/devices", redirected)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)

        with self.assertRaises(ThreadWatchTransportError):
            await fetch_thread_watch_devices(str(server.make_url("")).rstrip("/"))

        self.assertEqual(self.requests, [("/api/devices", "")])

    async def test_fetch_enforces_decompressed_body_limit_while_streaming(self) -> None:
        body = json.dumps(
            {"devices": [{"padding": "x" * 256}]}, separators=(",", ":")
        ).encode()

        async def devices(_request: web.Request) -> web.Response:
            return web.Response(
                body=gzip.compress(body),
                headers={
                    "Content-Type": "application/json",
                    "Content-Encoding": "gzip",
                },
            )

        app = web.Application()
        app.router.add_get("/api/devices", devices)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)

        with self.assertRaises(ThreadWatchInvalidResponseError):
            await fetch_thread_watch_devices(
                str(server.make_url("")).rstrip("/"), max_bytes=64
            )

    async def test_fetch_rejects_status_and_non_json_without_retrying(self) -> None:
        requests = []

        async def response(request: web.Request) -> web.Response:
            requests.append(request.path)
            if len(requests) == 1:
                return web.Response(status=503, text="private body")
            return web.Response(text="ok", content_type="text/plain")

        app = web.Application()
        app.router.add_get("/api/devices", response)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)

        with self.assertRaises(ThreadWatchTransportError):
            await fetch_thread_watch_devices(str(server.make_url("")).rstrip("/"))
        with self.assertRaises(ThreadWatchInvalidResponseError):
            await fetch_thread_watch_devices(str(server.make_url("")).rstrip("/"))
        self.assertEqual(requests, ["/api/devices", "/api/devices"])

    async def test_fetch_timeout_and_cancellation_bound_a_stalled_body(self) -> None:
        started = asyncio.Event()

        async def stalled(_request: web.Request) -> web.StreamResponse:
            stream = web.StreamResponse(status=200, headers={"Content-Type": "application/json"})
            await stream.prepare(_request)
            await stream.write(b'{"devices":[')
            started.set()
            await asyncio.sleep(1)
            return stream

        app = web.Application()
        app.router.add_get("/api/devices", stalled)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)
        uri = str(server.make_url("")).rstrip("/")

        with self.assertRaises(ThreadWatchTransportError):
            await fetch_thread_watch_devices(uri, request_timeout=0.05)

        task = asyncio.create_task(
            fetch_thread_watch_devices(uri, request_timeout=1)
        )
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_fetch_does_not_retry_a_disconnected_get(self) -> None:
        requests = 0

        async def disconnect(request: web.Request) -> web.StreamResponse:
            nonlocal requests
            requests += 1
            request.transport.abort()
            raise asyncio.CancelledError

        app = web.Application()
        app.router.add_get("/api/devices", disconnect)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)

        with self.assertRaises(ThreadWatchTransportError):
            await fetch_thread_watch_devices(str(server.make_url("")).rstrip("/"))
        self.assertEqual(requests, 1)


@pytest.mark.parametrize(
    ("kwargs", "env", "expected"),
    [
        ({}, {}, "http://localhost:9180"),
        (
            {},
            {
                "TD_THREAD_WATCH_HOST": "watch.local",
                "TD_THREAD_WATCH_PORT": "9090",
            },
            "http://watch.local:9090",
        ),
        (
            {"host": "cli.local", "port": 9191},
            {
                "TD_THREAD_WATCH_HOST": "env.local",
                "TD_THREAD_WATCH_PORT": "9190",
                "TD_THREAD_WATCH_URI": "https://ignored.example",
            },
            "http://cli.local:9191",
        ),
        (
            {"uri": "https://watch.example/"},
            {"TD_THREAD_WATCH_HOST": "ignored"},
            "https://watch.example",
        ),
        ({"host": "::1", "port": 9180}, {}, "http://[::1]:9180"),
    ],
)
def test_endpoint_resolution_precedence(kwargs, env, expected) -> None:
    assert resolve_thread_watch_uri(env=env, **kwargs) == expected


@pytest.mark.parametrize(
    "uri",
    [
        "",
        "ftp://watch.example",
        "http://user:pass@watch.example",
        "http://watch.example/api",
        "http://watch.example?query=secret",
        "http://watch.example#secret",
        "http://watch.example:0",
    ],
)
def test_endpoint_resolution_rejects_invalid_roots(uri) -> None:
    with pytest.raises(ThreadWatchArgumentError):
        resolve_thread_watch_uri(uri=uri, env={})


def test_cli_publishes_default_array_and_unknown_digest_scope(
    tmp_path, capsys
) -> None:
    async def fetch(*_args, **_kwargs):
        return (
            [
                {
                    "addr": "AABBCCDDEEFF0011",
                    "role": "router",
                    "rloc16": "4000",
                    "router_id": 16,
                    "future": {"nested": False},
                }
            ],
            "http://fixture/api/devices",
        )

    with patch.object(thread_watch_cli, "fetch_thread_watch_devices", fetch):
        assert thread_watch_cli.main(
            ["--datadir", str(tmp_path), "devices", "fetch-all"]
        ) == 0

    output = tmp_path / "td-thread-watch-devices.json"
    rows = json.loads(output.read_text())
    scope, error = read_network_scope(output)
    stdout = capsys.readouterr().out
    assert json.loads(stdout) == rows
    assert "Thread Network Topology CLI" not in stdout
    assert rows[0]["threadWatch"]["future"] == {"nested": False}
    assert error is None
    assert scope["extPanId"] is None
    assert scope["networkName"] is None
    assert scope["provenance"] == "unknown"
    assert scope["reason"] == "thread-watch-inventory-unscoped"
    assert scope["sources"] == ["thread-watch"]


def test_cli_quiet_mode_and_override_are_parseable_and_persisted(tmp_path, capsys) -> None:
    async def fetch(*_args, **_kwargs):
        return ([], "http://fixture/api/devices")

    output = tmp_path / "custom.json"
    with patch.object(thread_watch_cli, "fetch_thread_watch_devices", fetch):
        assert thread_watch_cli.main(
            [
                "--datadir",
                str(tmp_path),
                "--output",
                "custom.json",
                "--no-stdout-json",
                "devices",
                "fetch-all",
            ]
        ) == 0

    assert capsys.readouterr().out == ""
    assert output.read_text().strip() == "[]"
    assert read_network_scope(output)[1] is None


@pytest.mark.parametrize(
    "name",
    ["custom.txt", "custom.JSON", "custom.network.json", "x.NETWORK.JSON"],
)
def test_cli_rejects_output_names_that_collide_with_companions(
    tmp_path, name, capsys
) -> None:
    prior = tmp_path / "td-thread-watch-devices.json"
    prior.write_text('[{"old":true}]')

    assert thread_watch_cli.main(
        [
            "--datadir",
            str(tmp_path),
            "--output",
            name,
            "devices",
            "fetch-all",
        ]
    ) == 2

    assert json.loads(prior.read_text()) == [{"old": True}]
    assert "Thread Network Topology CLI" not in capsys.readouterr().out


def test_cli_rejects_file_as_datadir_before_fetch(tmp_path, capsys) -> None:
    datadir = tmp_path / "not-a-directory"
    datadir.touch()
    with patch.object(thread_watch_cli, "fetch_thread_watch_devices") as fetch:
        assert thread_watch_cli.main(
            ["--datadir", str(datadir), "devices", "fetch-all"]
        ) == 7
    fetch.assert_not_called()
    output = capsys.readouterr()
    assert output.out == ""
    assert "cannot prepare output" in output.err


def test_cli_scope_failure_is_nonzero_and_does_not_claim_rollback(
    tmp_path, capsys
) -> None:
    async def fetch(*_args, **_kwargs):
        return ([{"name": "new", "addr": "0000000000000002"}], "http://fixture")

    output = tmp_path / "td-thread-watch-devices.json"
    output.write_text('[{"old":true}]')

    with (
        patch.object(thread_watch_cli, "fetch_thread_watch_devices", fetch),
        patch.object(
            thread_watch_cli, "write_network_scope", side_effect=OSError("fixture")
        ),
    ):
        assert thread_watch_cli.main(
            ["--datadir", str(tmp_path), "devices", "fetch-all"]
        ) == 7

    assert json.loads(output.read_text())[0]["threadWatch"]["name"] == "new"
    assert capsys.readouterr().out == ""


def test_cli_quiet_failure_does_not_log_source_values(
    tmp_path, caplog
) -> None:
    async def fetch(*_args, **_kwargs):
        return (
            [
                {
                    "addr": "0000000000000002",
                    "name": "private household label",
                    "role": "unsupported-private-role",
                }
            ],
            "http://user:private@watch.example/api/devices",
        )

    with patch.object(thread_watch_cli, "fetch_thread_watch_devices", fetch):
        assert thread_watch_cli.main(
            [
                "--datadir",
                str(tmp_path),
                "--no-stdout-json",
                "devices",
                "fetch-all",
            ]
        ) == 0

    output = caplog.text + (tmp_path / "td-thread-watch-devices.network.json").read_text()
    assert "private household label" not in output
    assert "user:private" not in output


def test_publication_lock_rejects_a_competing_writer_without_replacing_files(
    tmp_path,
) -> None:
    output = tmp_path / "td-thread-watch-devices.json"

    with thread_watch_cli.publication_lock(output, timeout=0.05):
        with pytest.raises(thread_watch_cli.ThreadWatchPublicationBusyError):
            with thread_watch_cli.publication_lock(output, timeout=0.01):
                pass


def test_final_write_failure_preserves_previous_pair(tmp_path) -> None:
    async def fetch(*_args, **_kwargs):
        return ([{"name": "new"}], "http://fixture")

    output = tmp_path / "td-thread-watch-devices.json"
    thread_watch_cli._publish([{"old": True}], output)
    before = output.read_bytes()
    before_scope = thread_watch_cli.network_scope_path(output).read_bytes()

    with (
        patch.object(thread_watch_cli, "fetch_thread_watch_devices", fetch),
        patch.object(
            thread_watch_cli,
            "save_json_atomic",
            side_effect=OSError("fixture"),
        ),
    ):
        assert thread_watch_cli.main(
            ["--datadir", str(tmp_path), "devices", "fetch-all"]
        ) == 7

    assert output.read_bytes() == before
    assert thread_watch_cli.network_scope_path(output).read_bytes() == before_scope
