"""Unit tests for the five helpers extracted in Issue-12 refactor phases R1–R2.

Each test class targets a single helper and can run entirely in isolation —
no real server, no real subprocess, no real filesystem beyond a temp dir.

Run with:
    PYTHONPATH=/workspaces/tdash/src python -m pytest tests/test_webserver_helpers.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp.web
import td_webserver
from webserver_test_support import reset_webserver_state as _reset_module_state
from td_webserver import (
    FileAction,
    _build_file_response,
    _dispatch_long_cost,
    _dispatch_short_cost,
    _resolve_and_validate,
    _should_regenerate,
)

TD_DATA_FILE_CACHE_MAX_AGE_DEFAULT = td_webserver.TD_DATA_FILE_CACHE_MAX_AGE_DEFAULT


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_file_action(
    *,
    action: "str | list[str]" = ["otbr-cli", "router-table"],
    action_cost_s: int = 1,
    max_age_s: int = TD_DATA_FILE_CACHE_MAX_AGE_DEFAULT,
    force_async: bool = False,
) -> FileAction:
    return FileAction(
        max_age_s=max_age_s,
        action=action,
        action_cost_s=action_cost_s,
        force_async=force_async,
    )


# ---------------------------------------------------------------------------
# R4a — _resolve_and_validate
# ---------------------------------------------------------------------------

class TestResolveAndValidate(unittest.TestCase):
    """Pure function — no asyncio, no shared state."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_known_filename_returns_file_action_and_path(self) -> None:
        filename = "td-otbr-cli-router-table.json"
        file_action, file_path = _resolve_and_validate(filename, self.data_dir)
        self.assertIsInstance(file_action, FileAction)
        self.assertEqual(file_path, self.data_dir / filename)

    def test_does_not_require_file_to_exist_on_disk(self) -> None:
        # The file is NOT created — _resolve_and_validate must not check existence.
        filename = "td-otbr-cli-router-table.json"
        file_action, file_path = _resolve_and_validate(filename, self.data_dir)
        self.assertFalse(file_path.exists())

    def test_path_traversal_dot_dot_raises_404(self) -> None:
        with self.assertRaises(aiohttp.web.HTTPNotFound):
            _resolve_and_validate("../etc/passwd", self.data_dir)

    def test_path_traversal_slash_raises_404(self) -> None:
        with self.assertRaises(aiohttp.web.HTTPNotFound):
            _resolve_and_validate("subdir/file.json", self.data_dir)

    def test_path_traversal_backslash_raises_404(self) -> None:
        with self.assertRaises(aiohttp.web.HTTPNotFound):
            _resolve_and_validate("subdir\\file.json", self.data_dir)

    def test_path_traversal_null_byte_raises_404(self) -> None:
        with self.assertRaises(aiohttp.web.HTTPNotFound):
            _resolve_and_validate("file\x00.json", self.data_dir)

    def test_unknown_filename_raises_404(self) -> None:
        with self.assertRaises(aiohttp.web.HTTPNotFound):
            _resolve_and_validate("not-a-known-file.json", self.data_dir)

    def test_empty_filename_raises_404(self) -> None:
        with self.assertRaises(aiohttp.web.HTTPNotFound):
            _resolve_and_validate("", self.data_dir)

    def test_case_insensitive_lookup(self) -> None:
        # FILE_ACTION_MAP keys are lowercased; lookup should tolerate mixed case.
        filename = "TD-OTBR-CLI-ROUTER-TABLE.JSON"
        file_action, _ = _resolve_and_validate(filename, self.data_dir)
        self.assertIsInstance(file_action, FileAction)


# ---------------------------------------------------------------------------
# R4b — _should_regenerate
# ---------------------------------------------------------------------------

class TestShouldRegenerate(unittest.TestCase):
    """Pure function — no asyncio, no shared state."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        self.fa = _make_file_action(max_age_s=60)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _write(self, name: str = "file.json", *, mtime_offset: float = 0.0) -> Path:
        p = self.data_dir / name
        p.write_text("{}")
        if mtime_offset:
            t = time.time() + mtime_offset
            os.utime(p, (t, t))
        return p

    def test_missing_file_returns_true(self) -> None:
        p = self.data_dir / "missing.json"
        self.assertTrue(_should_regenerate(p, self.fa, no_cache=False))

    def test_fresh_file_no_cache_false_returns_false(self) -> None:
        p = self._write()
        self.assertFalse(_should_regenerate(p, self.fa, no_cache=False))

    def test_no_cache_true_on_fresh_file_returns_true(self) -> None:
        p = self._write()
        self.assertTrue(_should_regenerate(p, self.fa, no_cache=True))

    def test_stale_file_returns_true(self) -> None:
        # mtime 120 s in the past, max_age_s=60 -> stale
        p = self._write(mtime_offset=-120.0)
        self.assertTrue(_should_regenerate(p, self.fa, no_cache=False))

    def test_file_at_exact_boundary_is_fresh(self) -> None:
        # mtime set to now -> age ~= 0, well within 60 s
        p = self._write()
        self.assertFalse(_should_regenerate(p, self.fa, no_cache=False))


class TestFileCacheMaxAgeResolution(unittest.TestCase):
    """Validate CLI > ENV > default precedence for cache max-age."""

    def test_defaults_when_cli_and_env_are_unset(self) -> None:
        parser = td_webserver.build_parser()
        with patch.dict(os.environ, {}, clear=True):
            args = parser.parse_args([])
            value, source = td_webserver._resolve_file_cache_max_age(args, parser)
        self.assertEqual(value, td_webserver.TD_DATA_FILE_CACHE_MAX_AGE_DEFAULT)
        self.assertEqual(source, "default")

    def test_env_used_when_cli_is_omitted(self) -> None:
        parser = td_webserver.build_parser()
        with patch.dict(
            os.environ,
            {td_webserver.TD_FILE_CACHE_MAX_AGE_ENV_NAME: "120"},
            clear=True,
        ):
            args = parser.parse_args([])
            value, source = td_webserver._resolve_file_cache_max_age(args, parser)
        self.assertEqual(value, 120)
        self.assertEqual(source, "env")

    def test_cli_overrides_env(self) -> None:
        parser = td_webserver.build_parser()
        with patch.dict(
            os.environ,
            {td_webserver.TD_FILE_CACHE_MAX_AGE_ENV_NAME: "120"},
            clear=True,
        ):
            args = parser.parse_args(["--file-cache-max-age", "30"])
            value, source = td_webserver._resolve_file_cache_max_age(args, parser)
        self.assertEqual(value, 30)
        self.assertEqual(source, "cli")

    def test_invalid_env_value_raises_parser_error(self) -> None:
        parser = td_webserver.build_parser()
        with patch.dict(
            os.environ,
            {td_webserver.TD_FILE_CACHE_MAX_AGE_ENV_NAME: "not-an-int"},
            clear=True,
        ):
            args = parser.parse_args([])
            with self.assertRaises(SystemExit):
                td_webserver._resolve_file_cache_max_age(args, parser)

    def test_negative_env_value_raises_parser_error(self) -> None:
        parser = td_webserver.build_parser()
        with patch.dict(
            os.environ,
            {td_webserver.TD_FILE_CACHE_MAX_AGE_ENV_NAME: "-1"},
            clear=True,
        ):
            args = parser.parse_args([])
            with self.assertRaises(SystemExit):
                td_webserver._resolve_file_cache_max_age(args, parser)


# ---------------------------------------------------------------------------
# R4c — _build_file_response
# ---------------------------------------------------------------------------

class TestBuildFileResponse(unittest.TestCase):
    """Pure function — no asyncio, no shared state."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_json_file_returns_200_with_json_content_type(self) -> None:
        content = b'{"ok": true}'
        p = self.data_dir / "data.json"
        p.write_bytes(content)
        fa = _make_file_action(max_age_s=3600)

        resp = _build_file_response(p, fa)

        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, content)
        self.assertEqual(resp.content_type, "application/json")

    def test_non_json_file_returns_octet_stream_content_type(self) -> None:
        content = b"\x00\x01\x02"
        p = self.data_dir / "blob.bin"
        p.write_bytes(content)
        fa = _make_file_action(action="STATIC", max_age_s=3600)

        resp = _build_file_response(p, fa)

        self.assertEqual(resp.content_type, "application/octet-stream")

    def test_cache_control_header_reflects_max_age(self) -> None:
        p = self.data_dir / "data.json"
        p.write_bytes(b"{}")
        fa = _make_file_action(max_age_s=999)

        resp = _build_file_response(p, fa)

        self.assertIn("max-age=999", resp.headers.get("Cache-Control", ""))

    def test_last_modified_header_is_present(self) -> None:
        p = self.data_dir / "data.json"
        p.write_bytes(b"{}")
        fa = _make_file_action(max_age_s=60)

        resp = _build_file_response(p, fa)

        self.assertIn("Last-Modified", resp.headers)

    def test_missing_file_raises_500(self) -> None:
        p = self.data_dir / "nonexistent.json"
        fa = _make_file_action()

        with self.assertRaises(aiohttp.web.HTTPInternalServerError):
            _build_file_response(p, fa)


# ---------------------------------------------------------------------------
# R4d — _dispatch_long_cost
# ---------------------------------------------------------------------------

class TestDispatchLongCost(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        _reset_module_state()

    def tearDown(self) -> None:
        _reset_module_state()
        self._tmpdir.cleanup()

    async def test_new_job_returns_202_with_job_id(self) -> None:
        filename = "td-otbr-cli-networkdiag-fetch-all.json"
        fa = _make_file_action(action_cost_s=480)
        proceed = asyncio.Event()

        async def fake_td_cli(args, data_dir, *, timeout_s=None):
            await proceed.wait()
            (data_dir / filename).write_bytes(b"{}")
            return 0

        with patch.object(td_webserver, "run_td_cli", side_effect=fake_td_cli):
            resp = await _dispatch_long_cost(filename, fa.action, self.data_dir, fa)

            self.assertEqual(resp.status, 202)
            body = json.loads(resp.text)
            self.assertIn("job_id", body)
            self.assertEqual(body["status"], "running")
            self.assertEqual(body["filename"], filename)
            self.assertIn("/api/job/", resp.headers.get("Location", ""))

            # Job must be registered while still running.
            self.assertTrue(
                any(j.filename == filename for j in td_webserver._job_registry.values()),
                "Job must be in _job_registry",
            )

            proceed.set()
            await asyncio.gather(*list(td_webserver._background_tasks), return_exceptions=True)

    async def test_duplicate_in_flight_request_reuses_same_job_id(self) -> None:
        filename = "td-otbr-cli-networkdiag-fetch-all.json"
        fa = _make_file_action(action_cost_s=480)
        proceed = asyncio.Event()

        async def fake_td_cli(args, data_dir, *, timeout_s=None):
            await proceed.wait()
            (data_dir / filename).write_bytes(b"{}")
            return 0

        with patch.object(td_webserver, "run_td_cli", side_effect=fake_td_cli):
            resp1 = await _dispatch_long_cost(filename, fa.action, self.data_dir, fa)
            resp2 = await _dispatch_long_cost(filename, fa.action, self.data_dir, fa)

            body1 = json.loads(resp1.text)
            body2 = json.loads(resp2.text)
            self.assertEqual(resp1.status, 202)
            self.assertEqual(resp2.status, 202)
            self.assertEqual(body1["job_id"], body2["job_id"],
                             "Duplicate in-flight calls must reuse the same job_id")

            proceed.set()
            await asyncio.gather(*list(td_webserver._background_tasks), return_exceptions=True)

    async def test_background_task_anchored_in_background_tasks_set(self) -> None:
        filename = "td-otbr-cli-networkdiag-fetch-all.json"
        fa = _make_file_action(action_cost_s=480)
        proceed = asyncio.Event()

        async def fake_td_cli(args, data_dir, *, timeout_s=None):
            await proceed.wait()
            return 0

        with patch.object(td_webserver, "run_td_cli", side_effect=fake_td_cli):
            await _dispatch_long_cost(filename, fa.action, self.data_dir, fa)

            self.assertGreater(len(td_webserver._background_tasks), 0,
                               "Background task must be anchored in _background_tasks")

            proceed.set()
            await asyncio.gather(*list(td_webserver._background_tasks), return_exceptions=True)

    async def test_job_status_transitions_to_done_on_success(self) -> None:
        filename = "td-otbr-cli-networkdiag-fetch-all.json"
        fa = _make_file_action(action_cost_s=480)

        async def instant_td_cli(args, data_dir, *, timeout_s=None):
            (data_dir / filename).write_bytes(b"{}")
            return 0

        with patch.object(td_webserver, "run_td_cli", side_effect=instant_td_cli):
            await _dispatch_long_cost(filename, fa.action, self.data_dir, fa)
            await asyncio.gather(*list(td_webserver._background_tasks), return_exceptions=True)

        jobs = list(td_webserver._job_registry.values())
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].status, "done")

    async def test_job_status_transitions_to_error_on_failure(self) -> None:
        filename = "td-otbr-cli-networkdiag-fetch-all.json"
        fa = _make_file_action(action_cost_s=480)

        async def failing_td_cli(args, data_dir, *, timeout_s=None):
            return 1  # non-zero exit

        with patch.object(td_webserver, "run_td_cli", side_effect=failing_td_cli):
            await _dispatch_long_cost(filename, fa.action, self.data_dir, fa)
            await asyncio.gather(*list(td_webserver._background_tasks), return_exceptions=True)

        jobs = list(td_webserver._job_registry.values())
        self.assertEqual(jobs[0].status, "error")


# ---------------------------------------------------------------------------
# R4e — _dispatch_short_cost
# ---------------------------------------------------------------------------

class TestDispatchShortCost(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        _reset_module_state()

    def tearDown(self) -> None:
        _reset_module_state()
        self._tmpdir.cleanup()

    async def test_new_subprocess_success_writes_file(self) -> None:
        filename = "td-otbr-cli-router-table.json"
        fa = _make_file_action(action_cost_s=1)

        async def fake_td_cli(args, data_dir, *, timeout_s=None):
            (data_dir / filename).write_bytes(b"{}")
            return 0

        with patch.object(td_webserver, "run_td_cli", side_effect=fake_td_cli):
            await _dispatch_short_cost(filename, fa.action, self.data_dir, fa, no_cache=False)

        self.assertTrue((self.data_dir / filename).is_file())

    async def test_new_subprocess_failure_raises_502(self) -> None:
        filename = "td-otbr-cli-router-table.json"
        fa = _make_file_action(action_cost_s=1)

        async def failing_td_cli(args, data_dir, *, timeout_s=None):
            return 1

        with patch.object(td_webserver, "run_td_cli", side_effect=failing_td_cli):
            with self.assertRaises(aiohttp.web.HTTPBadGateway):
                await _dispatch_short_cost(filename, fa.action, self.data_dir, fa, no_cache=False)

    async def test_active_process_is_cleaned_up_after_success(self) -> None:
        """_active_processes entry must be removed after the task completes."""
        filename = "td-otbr-cli-router-table.json"
        fa = _make_file_action(action_cost_s=1)

        async def fake_td_cli(args, data_dir, *, timeout_s=None):
            (data_dir / filename).write_bytes(b"{}")
            return 0

        with patch.object(td_webserver, "run_td_cli", side_effect=fake_td_cli):
            await _dispatch_short_cost(filename, fa.action, self.data_dir, fa, no_cache=False)

        self.assertNotIn(filename, td_webserver._active_processes)

    async def test_active_process_is_cleaned_up_after_failure(self) -> None:
        """_active_processes entry must be removed even when td_cli fails."""
        filename = "td-otbr-cli-router-table.json"
        fa = _make_file_action(action_cost_s=1)

        async def failing_td_cli(args, data_dir, *, timeout_s=None):
            return 1

        with patch.object(td_webserver, "run_td_cli", side_effect=failing_td_cli):
            with self.assertRaises(aiohttp.web.HTTPBadGateway):
                await _dispatch_short_cost(filename, fa.action, self.data_dir, fa, no_cache=False)

        self.assertNotIn(filename, td_webserver._active_processes)

    async def test_join_existing_in_flight_task_success(self) -> None:
        """A second call while the first is in flight joins the task, not a new subprocess."""
        filename = "td-otbr-cli-router-table.json"
        fa = _make_file_action(action_cost_s=1)
        call_count = 0
        barrier = asyncio.Event()

        async def slow_td_cli(args, data_dir, *, timeout_s=None):
            nonlocal call_count
            call_count += 1
            await barrier.wait()
            (data_dir / filename).write_bytes(b"{}")
            return 0

        with patch.object(td_webserver, "run_td_cli", side_effect=slow_td_cli):
            t1 = asyncio.ensure_future(
                _dispatch_short_cost(filename, fa.action, self.data_dir, fa, no_cache=False)
            )
            await asyncio.sleep(0)  # let t1 register in _active_processes
            t2 = asyncio.ensure_future(
                _dispatch_short_cost(filename, fa.action, self.data_dir, fa, no_cache=False)
            )
            barrier.set()
            await asyncio.gather(t1, t2)

        self.assertEqual(call_count, 1, "run_td_cli must be called exactly once")

    async def test_join_existing_in_flight_task_failure_re_raises(self) -> None:
        """When the originating task raises, the joining call also raises."""
        filename = "td-otbr-cli-router-table.json"
        fa = _make_file_action(action_cost_s=1)
        barrier = asyncio.Event()

        async def failing_slow_td_cli(args, data_dir, *, timeout_s=None):
            await barrier.wait()
            return 1  # non-zero → HTTPBadGateway in the originating call

        with patch.object(td_webserver, "run_td_cli", side_effect=failing_slow_td_cli):
            t1 = asyncio.ensure_future(
                _dispatch_short_cost(filename, fa.action, self.data_dir, fa, no_cache=False)
            )
            await asyncio.sleep(0)  # let t1 register
            t2 = asyncio.ensure_future(
                _dispatch_short_cost(filename, fa.action, self.data_dir, fa, no_cache=False)
            )
            barrier.set()
            results = await asyncio.gather(t1, t2, return_exceptions=True)

        # t1 raises HTTPBadGateway; t2 joins t1's task and the exit code is 1.
        # t2 then checks file_path.is_file() (False) → raises HTTPBadGateway too.
        self.assertTrue(
            any(isinstance(r, aiohttp.web.HTTPBadGateway) for r in results),
            "At least one of the two calls must raise HTTPBadGateway",
        )

    async def test_post_lock_freshness_recheck_skips_regen(self) -> None:
        """If file becomes fresh while waiting on the lock, td_cli is not called."""
        filename = "td-otbr-cli-router-table.json"
        fa = _make_file_action(action_cost_s=1, max_age_s=86400)
        call_count = 0

        # Pre-write a fresh file so the re-check inside the lock sees it.
        (self.data_dir / filename).write_bytes(b"{}")

        async def should_not_be_called(args, data_dir, *, timeout_s=None):
            nonlocal call_count
            call_count += 1
            return 0

        with patch.object(td_webserver, "run_td_cli", side_effect=should_not_be_called):
            await _dispatch_short_cost(filename, fa.action, self.data_dir, fa, no_cache=False)

        self.assertEqual(call_count, 0,
                         "run_td_cli must not be called when the file is already fresh")


if __name__ == "__main__":
    unittest.main()
