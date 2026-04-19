"""Tests for TDashHandler URI routing in tdash_web.py.

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

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import tdash_web


class TestTDashHandlerRouting(unittest.TestCase):
    """Start a real TCPServer in a thread and exercise URI routing."""

    server: socketserver.TCPServer
    port: int
    thread: threading.Thread
    tmpdir: str

    @classmethod
    def setUpClass(cls) -> None:
        # Serve from a temp directory that contains a minimal tdash.html and a .json file.
        cls.tmpdir = tempfile.mkdtemp()
        with open(os.path.join(cls.tmpdir, "tdash.html"), "w") as f:
            f.write("<html><body>dashboard</body></html>")
        with open(os.path.join(cls.tmpdir, "data.json"), "w") as f:
            f.write('{"key": "value"}')

        # Change CWD so SimpleHTTPRequestHandler finds the files.
        cls._orig_cwd = os.getcwd()
        os.chdir(cls.tmpdir)

        cls.server = socketserver.TCPServer(("127.0.0.1", 0), tdash_web.TDashHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        os.chdir(cls._orig_cwd)

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
        """GET /data.json must return 200 with JSON content-type."""
        resp = self._get("/data.json")
        self.assertEqual(resp.status, 200)
        content_type = resp.getheader("Content-Type", "")
        self.assertIn("json", content_type)


if __name__ == "__main__":
    unittest.main()
