from __future__ import annotations

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