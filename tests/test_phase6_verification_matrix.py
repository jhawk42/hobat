from __future__ import annotations

import http.client
import os
import socketserver
import tempfile
import threading
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import patch

import util_data
import td_webserver
import otbr_restapi_download


class DataDirResolutionTests(unittest.TestCase):
    """Verification coverage for matrix cases around path resolution."""

    def test_case_2b_cli_relative_datadir_resolves_from_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            resolved = util_data.resolve_data_dir(
                data_dir="relative-data",
                env={},
                cwd=tmpdir,
            )
            self.assertEqual(
                resolved, (Path(tmpdir) / "relative-data").resolve())

    def test_case_2c_missing_user_supplied_datadir_is_not_auto_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "does-not-exist"
            resolved = util_data.resolve_data_dir(
                data_dir=str(missing),
                env={},
                cwd=tmpdir,
            )
            self.assertEqual(resolved, missing.resolve())
            self.assertFalse(resolved.exists())

    def test_case_3b_local_default_creation_permission_error_bubbles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("util_data.Path.exists", return_value=False),
                patch(
                    "util_data.Path.mkdir",
                    side_effect=PermissionError("permission denied"),
                ),
            ):
                with self.assertRaises(PermissionError):
                    util_data.resolve_data_dir(
                        data_dir=None, env={}, cwd=tmpdir)


@unittest.skip("td_webserver uses aiohttp; TDashHandler-based tests superseded by test_td_webserver_concurrency.py")
class WebServerRoutingTests(unittest.TestCase):
    """Verification coverage for matrix web-server behavior checks."""

    server: socketserver.TCPServer
    port: int
    thread: threading.Thread
    static_dir: str
    data_dir: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.static_dir = tempfile.mkdtemp()
        with open(
            os.path.join(cls.static_dir, "tdash.html"), "w", encoding="utf-8"
        ) as f:
            f.write("<html><body>dashboard</body></html>")
        with open(os.path.join(cls.static_dir, "app.js"), "w", encoding="utf-8") as f:
            f.write("console.log('ok');")

        cls.data_dir = tempfile.mkdtemp()
        with open(os.path.join(cls.data_dir, "data.json"), "w", encoding="utf-8") as f:
            f.write('{"ok": true}')

        handler = partial(
            web_server.TDashHandler,  # type: ignore[attr-defined]  # old API, class removed
            directory=cls.static_dir,
            td_data_dir=Path(cls.data_dir),
        )

        cls.server = socketserver.TCPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.thread.join(timeout=5)

    def _get(self, path: str) -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        return conn.getresponse()

    def test_case_5b_static_js_still_served_from_static_root(self) -> None:
        response = self._get("/app.js")
        self.assertEqual(response.status, 200)
        self.assertIn("javascript", response.getheader(
            "Content-Type", "").lower())

    def test_case_5c_json_path_traversal_returns_404(self) -> None:
        # Encoded traversal path should be denied and never escape td_data_dir.
        response = self._get("/%2e%2e/secret.json")
        self.assertEqual(response.status, 404)


class DirectModuleInvocationTests(unittest.TestCase):
    """Verification coverage for direct module entry points bypassing td_cli."""

    def test_case_6b_restapi_download_main_uses_datadir_arg_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {}, clear=False) as env_patch:
            env_patch.pop("TD_DATA_DIR", None)
            datadir = Path(tmpdir) / "direct-entry-dir"
            expected = datadir.resolve()

            def _assert_datadir_and_return(*_args, **_kwargs) -> int:
                self.assertEqual(
                    otbr_restapi_download._ACTIVE_TD_DATA_DIR, expected)
                return 0

            with patch.object(
                otbr_restapi_download,
                "download_all_restapi_endpoints",
                side_effect=_assert_datadir_and_return,
            ):
                rc = otbr_restapi_download.main(["--datadir", str(datadir)])

            self.assertEqual(rc, 0)
            self.assertIsNone(otbr_restapi_download._ACTIVE_TD_DATA_DIR)


if __name__ == "__main__":
    unittest.main()
