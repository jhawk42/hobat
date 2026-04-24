"""Tests for TDashHandler URI routing in web_server.py.

Run with:
    PYTHONPATH=/workspaces/tdash/src python -m pytest tests/test_tdash_web_routing.py -v
"""
from __future__ import annotations

import http.client
import os
import tempfile
import threading
import unittest
import socketserver
from functools import partial
from pathlib import Path

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import web_server


class TestTDashHandlerRouting(unittest.TestCase):
    """Start a real TCPServer in a thread and exercise URI routing."""

    server: socketserver.TCPServer
    port: int
    thread: threading.Thread
    static_dir: str
    data_dir: str

    @classmethod
    def setUpClass(cls) -> None:
        # Static files are served from one directory.
        cls.static_dir = tempfile.mkdtemp()
        with open(os.path.join(cls.static_dir, "tdash.html"), "w") as f:
            f.write("<html><body>dashboard</body></html>")

        # JSON files are served from td_data_dir, not static_dir.
        cls.data_dir = tempfile.mkdtemp()
        with open(os.path.join(cls.data_dir, "data.json"), "w") as f:
            f.write('{"key": "value"}')

        handler = partial(
            web_server.TDashHandler,
            directory=cls.static_dir,
            td_data_dir=Path(cls.data_dir),
        )

        cls.server = socketserver.TCPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.thread.join(timeout=5)

    def _get(self, path: str) -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        return conn.getresponse()

    # ------------------------------------------------------------------
    # Test cases
    # ------------------------------------------------------------------

    def test_root_redirects_to_tdash_html(self):
        """GET / must return 302 with Location: /tdash.html."""
        resp = self._get("/")
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.getheader("Location"), "/tdash.html")

    def test_tdash_html_returns_200(self):
        """GET /tdash.html must return 200."""
        resp = self._get("/tdash.html")
        self.assertEqual(resp.status, 200)

    def test_json_file_returns_200(self):
        """GET /data.json must return 200 with JSON content-type from td_data_dir."""
        resp = self._get("/data.json")
        self.assertEqual(resp.status, 200)
        content_type = resp.getheader("Content-Type", "")
        self.assertIn("json", content_type)

    def test_missing_json_file_returns_404(self):
        """GET missing JSON must return 404."""
        resp = self._get("/missing.json")
        self.assertEqual(resp.status, 404)


if __name__ == "__main__":
    unittest.main()
