from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import td_webserver
from aiohttp.test_utils import TestClient, TestServer


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