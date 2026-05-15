"""Tests for source-level process serialization in td_webserver.py.

Covers the two-level concurrency control introduced in Phases 1–6:
  - Same-filename deduplication (short-cost path)
  - Per-source serialization (short-cost path)
  - Cross-source concurrency (short-cost path)
  - Post-lock freshness re-check (short-cost path)
  - Per-source serialization (long-cost / job-registry path)
  - Long-cost + short-cost same-source interaction

Run with:
    PYTHONPATH=/workspaces/tdash/src python -m pytest tests/test_td_webserver_concurrency.py -v
"""

from __future__ import annotations
import td_webserver

import asyncio
import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_module_state() -> None:
    """Clear module-level dicts between tests to prevent cross-test pollution."""
    td_webserver._active_processes.clear()
    td_webserver._source_locks.clear()
    td_webserver._job_registry.clear()


def _make_app(data_dir: Path) -> object:
    """Return a minimal app-like dict used in place of aiohttp.web.Application."""
    return {"td_data_dir": data_dir}


def _make_request(filename: str, app: object, *, no_cache: bool = False):
    """Build a minimal mock aiohttp Request for handle_data_api."""
    from unittest.mock import MagicMock
    req = MagicMock()
    req.match_info = {"filename": filename}
    req.app = app
    req.headers = {"Cache-Control": "no-cache"} if no_cache else {}
    return req


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------

class ConcurrencyTestBase(unittest.IsolatedAsyncioTestCase):
    """Base class that sets up a temp data_dir and resets module state."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        _reset_module_state()

    def tearDown(self) -> None:
        _reset_module_state()
        self._tmpdir.cleanup()

    def _write_file(self, filename: str, content: str = "{}") -> Path:
        p = self.data_dir / filename
        p.write_text(content)
        return p


# ---------------------------------------------------------------------------
# Test 1 — Same-filename deduplication (short-cost)
# ---------------------------------------------------------------------------

class TestSameFilenameDeduplication(ConcurrencyTestBase):
    """Two concurrent requests for the same short-cost file must call run_td_cli once."""

    async def test_deduplication_calls_td_cli_once(self) -> None:
        filename = "td-otbr-cli-router-table.json"  # action_cost_s=1 → short-cost

        call_count = 0
        barrier = asyncio.Event()

        async def slow_td_cli(args, data_dir, *, timeout_s=None):
            nonlocal call_count
            call_count += 1
            await barrier.wait()  # hold until released
            # Write the file so the handler is satisfied
            (data_dir / filename).write_text("{}")
            return 0

        app = _make_app(self.data_dir)
        req = _make_request(filename, app)

        with patch.object(td_webserver, "run_td_cli", side_effect=slow_td_cli):
            # Launch both requests concurrently before releasing the barrier.
            t1 = asyncio.ensure_future(td_webserver.handle_data_api(req))
            # Give t1 a chance to register in _active_processes.
            await asyncio.sleep(0)
            t2 = asyncio.ensure_future(td_webserver.handle_data_api(req))

            barrier.set()
            await asyncio.gather(t1, t2)

        self.assertEqual(
            call_count, 1, "run_td_cli must be called exactly once")


# ---------------------------------------------------------------------------
# Test 2 — Same-source serialization (short-cost)
# ---------------------------------------------------------------------------

class TestSameSourceSerializationShortCost(ConcurrencyTestBase):
    """Two short-cost requests for different files of the same source must not overlap."""

    async def test_same_source_runs_sequentially(self) -> None:
        file_a = "td-otbr-cli-router-table.json"          # otbr-cli, cost=1
        file_b = "td-otbr-cli-meshdiag-topology.json"     # otbr-cli, cost=5

        running_at_same_time = False
        currently_running = 0
        max_concurrent = 0

        async def controlled_td_cli(args, data_dir, *, timeout_s=None):
            nonlocal currently_running, max_concurrent, running_at_same_time
            currently_running += 1
            if currently_running > 1:
                running_at_same_time = True
            max_concurrent = max(max_concurrent, currently_running)
            await asyncio.sleep(0.01)  # simulate work
            # Write the output file
            fname = args[args.index("--datadir") -
                         1] if "--datadir" in args else None
            # Determine filename from action args: find the FileAction whose action matches
            for fn, fa in td_webserver.FILE_ACTION_MAP.items():
                if fa.action == args[: len(fa.action) if isinstance(fa.action, list) else 1]:
                    (data_dir / fn).write_text("{}")
                    break
            # Simpler: write both files unconditionally
            (data_dir / file_a).write_text("{}")
            (data_dir / file_b).write_text("{}")
            currently_running -= 1
            return 0

        app = _make_app(self.data_dir)
        req_a = _make_request(file_a, app)
        req_b = _make_request(file_b, app)

        with patch.object(td_webserver, "run_td_cli", side_effect=controlled_td_cli):
            await asyncio.gather(
                td_webserver.handle_data_api(req_a),
                td_webserver.handle_data_api(req_b),
            )

        self.assertFalse(running_at_same_time,
                         "Two otbr-cli short-cost tasks must not run concurrently")
        self.assertEqual(max_concurrent, 1)


# ---------------------------------------------------------------------------
# Test 3 — Cross-source concurrency (short-cost)
# ---------------------------------------------------------------------------

class TestCrossSourceConcurrency(ConcurrencyTestBase):
    """Short-cost requests for different sources must run concurrently."""

    async def test_different_sources_run_concurrently(self) -> None:
        file_otbr = "td-otbr-cli-router-table.json"       # otbr-cli
        file_mdns = "td-otbr-cli-meshdiag-topology.json"  # actually also otbr-cli
        # Use restapi (different source) for the second file
        file_restapi = "td-otbr-restapi-devices.json"     # otbr-restapi

        max_concurrent = 0
        currently_running = 0
        barrier = asyncio.Barrier(2)  # both must reach it simultaneously

        async def concurrent_td_cli(args, data_dir, *, timeout_s=None):
            nonlocal currently_running, max_concurrent
            currently_running += 1
            max_concurrent = max(max_concurrent, currently_running)
            await barrier.wait()  # both tasks rendezvous here
            (data_dir / file_otbr).write_text("{}")
            (data_dir / file_restapi).write_text("{}")
            currently_running -= 1
            return 0

        app = _make_app(self.data_dir)
        req_otbr = _make_request(file_otbr, app)
        req_restapi = _make_request(file_restapi, app)

        with patch.object(td_webserver, "run_td_cli", side_effect=concurrent_td_cli):
            await asyncio.gather(
                td_webserver.handle_data_api(req_otbr),
                td_webserver.handle_data_api(req_restapi),
            )

        self.assertEqual(max_concurrent, 2,
                         "Different-source short-cost tasks must run concurrently")


# ---------------------------------------------------------------------------
# Test 4 — Post-lock freshness re-check (short-cost)
# ---------------------------------------------------------------------------

class TestPostLockFreshnessRecheck(ConcurrencyTestBase):
    """If the file becomes fresh while waiting on the source lock, skip regeneration."""

    async def test_second_request_skips_regen_if_file_fresh(self) -> None:
        filename = "td-otbr-cli-meshdiag-topology.json"  # otbr-cli, cost=5

        call_count = 0
        first_running = asyncio.Event()
        proceed = asyncio.Event()

        async def slow_td_cli(args, data_dir, *, timeout_s=None):
            nonlocal call_count
            call_count += 1
            first_running.set()
            await proceed.wait()
            # Write the file (makes it fresh)
            (data_dir / filename).write_text("{}")
            return 0

        app = _make_app(self.data_dir)
        req = _make_request(filename, app)

        with patch.object(td_webserver, "run_td_cli", side_effect=slow_td_cli):
            # Launch request A; wait until it has the lock and is running.
            t1 = asyncio.ensure_future(td_webserver.handle_data_api(req))
            await first_running.wait()

            # Launch request B for a *different* file with the same source
            # so it queues behind the lock (not deduplicated via _active_processes).
            file_b = "td-otbr-cli-router-table.json"
            req_b = _make_request(file_b, app)
            t2 = asyncio.ensure_future(td_webserver.handle_data_api(req_b))

            # Release A; it writes filename and frees the lock.
            # Before B starts its own td_cli, write file_b to make it fresh too.
            (self.data_dir / file_b).write_text("{}")
            proceed.set()

            await asyncio.gather(t1, t2)

        # Only the first call (for filename) should have happened;
        # file_b was fresh when B acquired the lock so no second call.
        self.assertEqual(call_count, 1,
                         "Second request must skip td_cli when file is already fresh")


# ---------------------------------------------------------------------------
# Test 5 — Same-source serialization (long-cost / job registry)
# ---------------------------------------------------------------------------

class TestSameSourceSerializationLongCost(ConcurrencyTestBase):
    """Two long-cost jobs for different files of the same source must not overlap."""

    async def test_long_cost_same_source_runs_sequentially(self) -> None:
        # networkdiag-topology (cost=480) and networkdiag-topology-multicast-network
        # (cost=16) are both otbr-cli but multicast is short-cost.
        # Use two long-cost files: networkdiag-topology and mdns files.
        # Actually let's use a short-cost threshold patch so we can use real files.
        file_a = "td-otbr-cli-networkdiag-topology-poll.json"             # cost=480, long
        file_b = "td-otbr-cli-networkdiag-topology-multicast-network.json"  # cost=16, short

        # Temporarily lower the threshold so file_b also goes through the job path.
        original_threshold = td_webserver._LONG_COST_THRESHOLD_S
        td_webserver._LONG_COST_THRESHOLD_S = 10

        running_at_same_time = False
        currently_running = 0

        async def controlled_td_cli(args, data_dir, *, timeout_s=None):
            nonlocal currently_running, running_at_same_time
            currently_running += 1
            if currently_running > 1:
                running_at_same_time = True
            await asyncio.sleep(0.02)
            (data_dir / file_a).write_text("{}")
            (data_dir / file_b).write_text("{}")
            currently_running -= 1
            return 0

        app = _make_app(self.data_dir)
        req_a = _make_request(file_a, app)
        req_b = _make_request(file_b, app)

        try:
            with patch.object(td_webserver, "run_td_cli", side_effect=controlled_td_cli):
                # Both requests return 202 immediately; gather them.
                resp_a, resp_b = await asyncio.gather(
                    td_webserver.handle_data_api(req_a),
                    td_webserver.handle_data_api(req_b),
                )
                self.assertEqual(resp_a.status, 202)
                self.assertEqual(resp_b.status, 202)

                # Wait for both background jobs to complete.
                for _ in range(50):
                    await asyncio.sleep(0.01)
                    done = all(
                        j.status != "running"
                        for j in td_webserver._job_registry.values()
                    )
                    if done:
                        break
        finally:
            td_webserver._LONG_COST_THRESHOLD_S = original_threshold

        self.assertFalse(running_at_same_time,
                         "Two long-cost otbr-cli jobs must not run concurrently")


# ---------------------------------------------------------------------------
# Test 6 — Long-cost job holds lock; short-cost same-source must wait
# ---------------------------------------------------------------------------

class TestLongCostBlocksShortCostSameSource(ConcurrencyTestBase):
    """A running long-cost job must block a short-cost request for the same source."""

    async def test_short_cost_waits_for_long_cost_lock(self) -> None:
        file_long = "td-otbr-cli-networkdiag-topology-poll.json"    # cost=480, long
        file_short = "td-otbr-cli-router-table.json"           # cost=1, short

        running_at_same_time = False
        currently_running = 0
        long_job_started = asyncio.Event()
        long_job_proceed = asyncio.Event()

        async def controlled_td_cli(args, data_dir, *, timeout_s=None):
            nonlocal currently_running, running_at_same_time
            currently_running += 1
            if currently_running > 1:
                running_at_same_time = True
            long_job_started.set()
            await long_job_proceed.wait()
            (data_dir / file_long).write_text("{}")
            (data_dir / file_short).write_text("{}")
            currently_running -= 1
            return 0

        app = _make_app(self.data_dir)
        req_long = _make_request(file_long, app)
        req_short = _make_request(file_short, app)

        with patch.object(td_webserver, "run_td_cli", side_effect=controlled_td_cli):
            # Fire the long-cost request; it returns 202 immediately.
            resp_long = await td_webserver.handle_data_api(req_long)
            self.assertEqual(resp_long.status, 202)

            # Wait until the background job has actually acquired the lock.
            await long_job_started.wait()

            # Now fire the short-cost request in a task; it must block on the lock.
            short_task = asyncio.ensure_future(
                td_webserver.handle_data_api(req_short))

            # Give the short-cost task a moment to reach the lock.
            await asyncio.sleep(0.01)

            # It should still be pending (lock held by long-cost job).
            self.assertFalse(short_task.done(),
                             "Short-cost task must be blocked by the long-cost job's lock")

            # Release the long-cost job.
            long_job_proceed.set()
            await short_task  # must complete now

        self.assertFalse(running_at_same_time,
                         "Long-cost and short-cost otbr-cli tasks must not run concurrently")


if __name__ == "__main__":
    unittest.main()
