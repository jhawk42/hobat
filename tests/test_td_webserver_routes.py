from __future__ import annotations

import errno
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import td_webserver
from aiohttp.test_utils import TestClient, TestServer


class WebServerStartupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.argv = ["--datadir", self._tmpdir.name, "--port", "9165"]

    def test_occupied_port_returns_error_without_retry(self) -> None:
        for port, alternative in ((9165, 9166), (65535, 65534)):
            with self.subTest(port=port):
                with (
                    patch.object(td_webserver, "configure_logging"),
                    patch.object(
                        td_webserver.aiohttp.web,
                        "run_app",
                        side_effect=OSError(errno.EADDRINUSE, "Address already in use"),
                    ) as run_app,
                    self.assertLogs(level="INFO") as logs,
                ):
                    rc = td_webserver.main([
                        "--datadir", self._tmpdir.name,
                        "--host", "0.0.0.0", "--port", str(port),
                    ])

                self.assertEqual(rc, 1)
                run_app.assert_called_once()
                output = "\n".join(logs.output)
                self.assertIn(f"Port {port} is already in use", output)
                self.assertIn("0.0.0.0", output)
                self.assertIn(f"--port {alternative}", output)
                self.assertNotIn("Serving at", output)

    def test_other_os_errors_are_not_hidden(self) -> None:
        error = OSError(errno.EACCES, "Permission denied")
        with (
            patch.object(td_webserver, "configure_logging"),
            patch.object(td_webserver.aiohttp.web, "run_app", side_effect=error),
            self.assertRaises(OSError) as raised,
        ):
            td_webserver.main(self.argv)

        self.assertIs(raised.exception, error)

    def test_normal_shutdown_returns_success(self) -> None:
        with (
            patch.object(td_webserver, "configure_logging"),
            patch.object(td_webserver.aiohttp.web, "run_app") as run_app,
        ):
            self.assertEqual(td_webserver.main(self.argv), 0)

        run_app.assert_called_once()
        self.assertEqual(run_app.call_args.kwargs["port"], 9165)

    def test_cli_occupied_port_exits_without_traceback(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(td_webserver.__file__).parent)
            env["TD_DEBUG_LEVEL"] = "INFO"
            result = subprocess.run(
                [
                    sys.executable, "-m", "td_webserver",
                    "--host", "127.0.0.1", "--port", str(port),
                    "--datadir", self._tmpdir.name,
                ],
                capture_output=True, text=True, timeout=30, env=env,
            )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn(f"Port {port} is already in use", output)
        self.assertIn("different --port", output)
        self.assertNotIn("Traceback", output)
        self.assertNotIn("Serving at", output)


class WebServerRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        self.data_content = b'{"cached": true}'
        (self.data_dir / "Eve Thread Network Layout.evethreadlayout").write_bytes(
            self.data_content
        )

        with patch.object(td_webserver.aiohttp.web, "run_app") as run_app:
            td_webserver.main(["--datadir", str(self.data_dir), "--port", "0"])

        app = run_app.call_args.args[0]
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self._tmpdir.cleanup()

    async def test_root_redirects_to_dashboard(self) -> None:
        response = await self.client.get("/", allow_redirects=False)

        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "/tdash.html")

    async def test_static_dashboard_and_javascript_are_served(self) -> None:
        for path in ("/tdash.html", "/js/tdash-ui.js"):
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status, 200)
                self.assertTrue(await response.read())
                self.assertEqual(response.headers["Cache-Control"], "no-cache")

    async def test_data_api_serves_registered_static_snapshot(self) -> None:
        response = await self.client.get(
            "/api/data/Eve%20Thread%20Network%20Layout.evethreadlayout"
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), self.data_content)

    async def test_data_api_preserves_canonical_border_router_snapshot_bytes(self) -> None:
        content = b'[{"isBorderRouter":false}]'
        filename = "td-otbr-cli-meshdiag-topology.json"
        (self.data_dir / filename).write_bytes(content)

        response = await self.client.get(f"/api/data/{filename}")

        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), content)

    async def test_stricter_and_zero_request_ages_refresh_short_snapshots(self) -> None:
        filename = td_webserver.OTBR_CLI_ROUTER_TABLE_FILENAME
        file_path = self.data_dir / filename

        async def refresh(*args, **kwargs):
            file_path.write_bytes(b"replacement")
            return 0

        for header in ("max-age=1", "max-age=0", "no-cache"):
            with self.subTest(header=header):
                file_path.write_bytes(b"old")
                os.utime(file_path, (990, 990))
                with patch.object(td_webserver.time, "time", return_value=1000), patch.object(
                    td_webserver, "run_td_cli", side_effect=refresh
                ) as runner:
                    response = await self.client.get(
                        f"/api/data/{filename}", headers={"Cache-Control": header}
                    )
                    self.assertEqual(response.status, 200)
                    self.assertEqual(await response.read(), b"replacement")
                runner.assert_awaited_once()

    async def test_invalid_dynamic_request_age_returns_400_without_dispatch(self) -> None:
        for header in (
            "max-age=invalid", "only-if-cached, max-age=invalid", "max-age",
            "max-age=", "max-age=-1", "max-age=1.5", 'max-age="60',
        ):
            with self.subTest(header=header), patch.object(
                td_webserver, "run_td_cli", new_callable=AsyncMock
            ) as data_runner, patch.object(
                td_webserver, "run_device_action_cli", new_callable=AsyncMock
            ) as action_runner:
                response = await self.client.get(
                    f"/api/data/{td_webserver.OTBR_CLI_ROUTER_TABLE_FILENAME}",
                    headers={"Cache-Control": header},
                )
                self.assertEqual(response.status, 400)
                self.assertIn(
                    "Invalid Cache-Control max-age: expected a non-negative integer",
                    await response.text(),
                )
                data_runner.assert_not_awaited()
                action_runner.assert_not_awaited()

    async def test_quoted_and_unquoted_request_ages_have_the_same_cache_policy(self) -> None:
        filename = td_webserver.OTBR_CLI_ROUTER_TABLE_FILENAME
        file_path = self.data_dir / filename

        async def refresh(*args, **kwargs):
            file_path.write_bytes(b"replacement")
            return 0

        for age, expected_calls, expected_body in (
            ("60", 0, b"old"), ("1", 1, b"replacement"),
        ):
            for value in (age, f'"{age}"'):
                with self.subTest(value=value):
                    file_path.write_bytes(b"old")
                    os.utime(file_path, (990, 990))
                    with patch.object(td_webserver.time, "time", return_value=1000), patch.object(
                        td_webserver, "run_td_cli", side_effect=refresh
                    ) as runner:
                        response = await self.client.get(
                            f"/api/data/{filename}",
                            headers={"Cache-Control": f"max-age={value}"},
                        )
                        self.assertEqual(response.status, 200)
                        self.assertEqual(await response.read(), expected_body)
                    self.assertEqual(runner.await_count, expected_calls)

    async def test_age_validation_preserves_static_checkpoint_and_404_paths(self) -> None:
        checkpoint = "td-otbr-cli-router-table.partial.json"
        (self.data_dir / checkpoint).write_bytes(b"checkpoint")
        cases = (
            ("Eve%20Thread%20Network%20Layout.evethreadlayout", "max-age=invalid", 200, self.data_content),
            (checkpoint, "max-age=invalid", 200, b"checkpoint"),
            ("unknown.json", "max-age=invalid", 404, None),
            (td_webserver.OTBR_CLI_ROUTER_TABLE_FILENAME, "only-if-cached, max-age=60", 404, None),
        )
        with patch.object(td_webserver, "run_td_cli", new_callable=AsyncMock) as runner:
            for filename, header, status, body in cases:
                with self.subTest(filename=filename):
                    response = await self.client.get(
                        f"/api/data/{filename}", headers={"Cache-Control": header}
                    )
                    self.assertEqual(response.status, status)
                    if body is not None:
                        self.assertEqual(await response.read(), body)
            runner.assert_not_awaited()

    async def test_secret_log_override_is_forwarded_only_to_rest_jobs(self) -> None:
        with patch.object(td_webserver.aiohttp.web, "run_app") as run_app:
            td_webserver.main([
                "--datadir", str(self.data_dir), "--port", "0",
                "--log-thread-secrets",
            ])
        app = run_app.call_args.args[0]
        client = TestClient(TestServer(app))
        await client.start_server()
        commands: list[list[str]] = []

        async def fake_td_cli(args, data_dir, *, timeout_s=None):
            commands.append(args)
            output_name = (
                td_webserver.OTBR_RESTAPI_DEVICES_LIST_FILENAME
                if args[0] == "otbr-restapi"
                else td_webserver.OTBR_CLI_ROUTER_TABLE_FILENAME
            )
            (data_dir / output_name).write_text("[]", encoding="utf-8")
            return 0

        try:
            with patch.object(td_webserver, "run_td_cli", side_effect=fake_td_cli):
                rest_response = await client.get(
                    f"/api/data/{td_webserver.OTBR_RESTAPI_DEVICES_LIST_FILENAME}"
                )
                cli_response = await client.get(
                    f"/api/data/{td_webserver.OTBR_CLI_ROUTER_TABLE_FILENAME}"
                )

            self.assertEqual(rest_response.status, 200)
            self.assertEqual(cli_response.status, 200)
            self.assertEqual(commands[0][:2], ["otbr-restapi", "--log-thread-secrets"])
            self.assertEqual(commands[1][0], "otbr-cli")
            self.assertNotIn("--debug", commands[0])
            self.assertNotIn("--debug", commands[1])
        finally:
            await client.close()

    async def test_logging_level_does_not_change_cache_or_collector_arguments(self) -> None:
        commands: list[list[str]] = []

        async def fake_td_cli(args, data_dir, *, timeout_s=None):
            commands.append(list(args))
            (data_dir / td_webserver.OTBR_RESTAPI_DEVICES_LIST_FILENAME).write_text(
                "[]", encoding="utf-8"
            )
            return 0

        path = f"/api/data/{td_webserver.OTBR_RESTAPI_DEVICES_LIST_FILENAME}"
        with patch.object(td_webserver, "run_td_cli", side_effect=fake_td_cli):
            with patch.dict(os.environ, {"TD_DEBUG_LEVEL": "INFO"}):
                first = await self.client.get(path, headers={"Cache-Control": "no-cache"})
            with patch.dict(os.environ, {"TD_DEBUG_LEVEL": "DEBUG"}):
                second = await self.client.get(path, headers={"Cache-Control": "no-cache"})
                cached = await self.client.get(path)

        self.assertEqual((first.status, second.status, cached.status), (200, 200, 200))
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0], commands[1])
        self.assertNotIn("--debug", commands[0])