"""Refactor smoke tests 

Exercises the three primary execution paths through handle_data_api so that
every subsequent refactor phase can be verified against them.

  Path A — STATIC file served: file exists on disk → 200 with its contents.
  Path B — Short-cost regen:   dynamic file missing, low action_cost_s → td_cli
                                 is called, file written, 200 returned.
  Path C — Long-cost 202:      dynamic file missing, force_async=True (or
                                 action_cost_s > threshold) → 202 + job_id
                                 returned immediately without blocking.

These tests must pass before and after every refactor phase.

Run with:
    PYTHONPATH=/workspaces/tdash/src python -m pytest tests/test_webserver_smoke.py -v
"""

from __future__ import annotations
import td_webserver

import asyncio
import json
import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# Helpers (mirrors the pattern established in test_td_webserver_concurrency.py)
# ---------------------------------------------------------------------------

def _reset_module_state() -> None:
    """Clear module-level dicts between tests to prevent cross-test pollution."""
    td_webserver._active_processes.clear()
    td_webserver._source_locks.clear()
    td_webserver._job_registry.clear()
    td_webserver._background_tasks.clear()


def _make_app(data_dir: Path) -> dict:
    """Return a minimal app dict substituting for aiohttp.web.Application."""
    return {"td_data_dir": data_dir}


def _make_request(filename: str, app: dict, *, no_cache: bool = False) -> MagicMock:
    """Build a minimal mock aiohttp Request for handle_data_api."""
    req = MagicMock()
    req.match_info = {"filename": filename}
    req.app = app
    req.headers = {"Cache-Control": "no-cache"} if no_cache else {}
    return req


class SmokeTestBase(unittest.IsolatedAsyncioTestCase):
    """Common setUp / tearDown for all smoke tests."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        _reset_module_state()

    def tearDown(self) -> None:
        _reset_module_state()
        self._tmpdir.cleanup()


# ---------------------------------------------------------------------------
# Path A — STATIC file served
# ---------------------------------------------------------------------------

class TestSmokePath_A_StaticFile(SmokeTestBase):
    """Path A: a STATIC file that exists on disk is served with 200."""

    async def test_static_file_returns_200_with_content(self) -> None:
        # "td-static-extaddr-device-label.json" is STATIC in FILE_ACTION_MAP.
        filename = "td-static-extaddr-device-label.json"
        content = b'{"devices": []}'
        (self.data_dir / filename).write_bytes(content)

        app = _make_app(self.data_dir)
        req = _make_request(filename, app)

        response = await td_webserver.handle_data_api(req)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, content)

    async def test_static_file_missing_returns_404(self) -> None:
        """A STATIC file that is absent on disk must yield 404, not a regen attempt."""
        import aiohttp.web

        filename = "td-static-extaddr-device-label.json"
        # Do NOT write the file — it should be absent.
        app = _make_app(self.data_dir)
        req = _make_request(filename, app)

        with self.assertRaises(aiohttp.web.HTTPNotFound):
            await td_webserver.handle_data_api(req)

    async def test_path_traversal_returns_404(self) -> None:
        """A filename containing path-traversal characters must yield 404."""
        import aiohttp.web

        app = _make_app(self.data_dir)
        req = _make_request("../etc/passwd", app)

        with self.assertRaises(aiohttp.web.HTTPNotFound):
            await td_webserver.handle_data_api(req)

    async def test_unknown_filename_returns_404(self) -> None:
        """A filename not in FILE_ACTION_MAP must yield 404."""
        import aiohttp.web

        app = _make_app(self.data_dir)
        req = _make_request("not-a-known-file.json", app)

        with self.assertRaises(aiohttp.web.HTTPNotFound):
            await td_webserver.handle_data_api(req)


# ---------------------------------------------------------------------------
# Path B — Short-cost regen
# ---------------------------------------------------------------------------

class TestSmokePath_B_ShortCostRegen(SmokeTestBase):
    """Path B: dynamic file absent/stale → td_cli called → 200 returned."""

    async def test_missing_file_triggers_regen_and_returns_200(self) -> None:
        # "td-otbr-cli-router-table.json" has action_cost_s=1 → short-cost path.
        filename = "td-otbr-cli-router-table.json"
        file_path = self.data_dir / filename
        content = b'{"routers": []}'

        async def fake_td_cli(args, data_dir, *, timeout_s=None):
            file_path.write_bytes(content)
            return 0

        app = _make_app(self.data_dir)
        req = _make_request(filename, app)

        with patch.object(td_webserver, "run_td_cli", side_effect=fake_td_cli):
            response = await td_webserver.handle_data_api(req)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, content)

    async def test_fresh_file_served_without_regen(self) -> None:
        """A fresh file on disk must be served without invoking run_td_cli."""
        filename = "td-otbr-cli-router-table.json"
        content = b'{"cached": true}'
        (self.data_dir / filename).write_bytes(content)

        app = _make_app(self.data_dir)
        req = _make_request(filename, app)

        td_cli_called = False

        async def should_not_be_called(args, data_dir, *, timeout_s=None):
            nonlocal td_cli_called
            td_cli_called = True
            return 0

        with patch.object(td_webserver, "run_td_cli", side_effect=should_not_be_called):
            response = await td_webserver.handle_data_api(req)

        self.assertFalse(
            td_cli_called, "run_td_cli must not be called for a fresh file")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, content)

    async def test_no_cache_header_forces_regen(self) -> None:
        """Cache-Control: no-cache must force regen even when the file is fresh."""
        filename = "td-otbr-cli-router-table.json"
        old_content = b'{"old": true}'
        new_content = b'{"new": true}'
        (self.data_dir / filename).write_bytes(old_content)

        app = _make_app(self.data_dir)
        req = _make_request(filename, app, no_cache=True)

        async def overwrite_td_cli(args, data_dir, *, timeout_s=None):
            (data_dir / filename).write_bytes(new_content)
            return 0

        with patch.object(td_webserver, "run_td_cli", side_effect=overwrite_td_cli):
            response = await td_webserver.handle_data_api(req)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, new_content)

    async def test_short_cost_td_cli_failure_returns_502(self) -> None:
        """A non-zero td_cli exit code on the short-cost path must yield HTTPBadGateway."""
        import aiohttp.web

        filename = "td-otbr-cli-router-table.json"

        async def failing_td_cli(args, data_dir, *, timeout_s=None):
            return 1  # non-zero exit

        app = _make_app(self.data_dir)
        req = _make_request(filename, app)

        with patch.object(td_webserver, "run_td_cli", side_effect=failing_td_cli):
            with self.assertRaises(aiohttp.web.HTTPBadGateway):
                await td_webserver.handle_data_api(req)


# ---------------------------------------------------------------------------
# Path C — Long-cost 202
# ---------------------------------------------------------------------------

class TestSmokePath_C_LongCost202(SmokeTestBase):
    """Path C: force_async=True (or cost > threshold) → immediate 202 + job_id."""

    async def test_force_async_file_returns_202_immediately(self) -> None:
        # "td-otbr-cli-meshdiag-router-neighbortables.json" has force_async=True.
        filename = "td-otbr-cli-meshdiag-router-neighbortables.json"

        # td_cli will block on this event; the handler must still return 202 first.
        td_cli_started = asyncio.Event()
        td_cli_proceed = asyncio.Event()

        async def blocking_td_cli(args, data_dir, *, timeout_s=None):
            td_cli_started.set()
            await td_cli_proceed.wait()
            (data_dir / filename).write_bytes(b"{}")
            return 0

        app = _make_app(self.data_dir)
        req = _make_request(filename, app)

        # The patch must stay active while the background task runs run_td_cli.
        with patch.object(td_webserver, "run_td_cli", side_effect=blocking_td_cli):
            response = await td_webserver.handle_data_api(req)

            self.assertEqual(response.status, 202)
            body = json.loads(response.text)
            self.assertIn("job_id", body)
            self.assertEqual(body["status"], "running")
            self.assertEqual(body["filename"], filename)

            # Unblock and drain background tasks while the mock is still active.
            td_cli_proceed.set()
            await asyncio.gather(*list(td_webserver._background_tasks), return_exceptions=True)

    async def test_long_cost_threshold_file_returns_202(self) -> None:
        """A file whose action_cost_s exceeds _LONG_COST_THRESHOLD_S returns 202."""
        # "td-otbr-cli-networkdiag-topology-poll.json" has action_cost_s=480 > 300.
        filename = "td-otbr-cli-networkdiag-topology-poll.json"

        proceed = asyncio.Event()

        async def blocking_td_cli(args, data_dir, *, timeout_s=None):
            await proceed.wait()
            (data_dir / filename).write_bytes(b"{}")
            return 0

        app = _make_app(self.data_dir)
        req = _make_request(filename, app)

        # Keep patch active while the background task runs run_td_cli.
        with patch.object(td_webserver, "run_td_cli", side_effect=blocking_td_cli):
            response = await td_webserver.handle_data_api(req)

            self.assertEqual(response.status, 202)
            body = json.loads(response.text)
            self.assertIn("job_id", body)

            proceed.set()
            await asyncio.gather(*list(td_webserver._background_tasks), return_exceptions=True)

    async def test_duplicate_long_cost_request_reuses_job_id(self) -> None:
        """A second request for the same long-cost file while running gets the same job_id."""
        filename = "td-otbr-cli-networkdiag-topology-poll.json"

        proceed = asyncio.Event()

        async def blocking_td_cli(args, data_dir, *, timeout_s=None):
            await proceed.wait()
            (data_dir / filename).write_bytes(b"{}")
            return 0

        app = _make_app(self.data_dir)
        req = _make_request(filename, app)

        # Keep patch active while the background task runs run_td_cli.
        with patch.object(td_webserver, "run_td_cli", side_effect=blocking_td_cli):
            resp1 = await td_webserver.handle_data_api(req)
            resp2 = await td_webserver.handle_data_api(req)

            body1 = json.loads(resp1.text)
            body2 = json.loads(resp2.text)
            self.assertEqual(resp1.status, 202)
            self.assertEqual(resp2.status, 202)
            self.assertEqual(
                body1["job_id"], body2["job_id"],
                "Duplicate in-flight requests must reuse the same job_id",
            )

            proceed.set()
            await asyncio.gather(*list(td_webserver._background_tasks), return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
