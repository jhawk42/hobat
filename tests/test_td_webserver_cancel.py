from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import aiohttp.web
import td_webserver
from webserver_test_support import reset_webserver_state as _reset_state


class _DummyTask:
    def __init__(self) -> None:
        self._cancel_called = False

    def cancel(self) -> bool:
        self._cancel_called = True
        return True

    def done(self) -> bool:
        return False


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminate_called = False
        self.kill_called = False
        self._communicate_calls = 0
        self._block_event = asyncio.Event()
        self.communicate_started = asyncio.Event()

    def terminate(self) -> None:
        self.terminate_called = True

    def kill(self) -> None:
        self.kill_called = True

    async def communicate(self):
        self._communicate_calls += 1
        self.communicate_started.set()
        if self._communicate_calls == 1:
            await self._block_event.wait()
        return b"", b""


def _make_job_request(job_id: str):
    req = MagicMock()
    req.match_info = {"job_id": job_id}
    req.headers = {}
    req.app = {}
    return req


class TestJobCancelApi(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _reset_state()

    def tearDown(self) -> None:
        _reset_state()

    async def test_cancel_unknown_job_returns_404(self) -> None:
        req = _make_job_request("missing")
        with self.assertRaises(aiohttp.web.HTTPNotFound):
            await td_webserver.handle_job_cancel_api(req)

    async def test_cancel_terminal_job_returns_409(self) -> None:
        job_id = "job-terminal"
        td_webserver._job_registry[job_id] = td_webserver.JobStatus(
            job_id=job_id,
            filename="x.json",
            status=td_webserver.JOB_STATUS_DONE,
        )

        resp = await td_webserver.handle_job_cancel_api(_make_job_request(job_id))
        self.assertEqual(resp.status, 409)

    async def test_cancel_running_job_marks_cancelling_and_cancels_task(self) -> None:
        job_id = "job-running"
        td_webserver._job_registry[job_id] = td_webserver.JobStatus(
            job_id=job_id,
            filename="x.json",
            status=td_webserver.JOB_STATUS_RUNNING,
        )
        task = _DummyTask()
        td_webserver._job_runtime_registry[job_id] = td_webserver.JobRuntime(
            job_id=job_id,
            filename="x.json",
            source="otbr-cli",
            task=task,  # type: ignore[arg-type]
            process=None,
        )

        resp = await td_webserver.handle_job_cancel_api(_make_job_request(job_id))

        self.assertEqual(resp.status, 202)
        self.assertEqual(
            td_webserver._job_registry[job_id].status,
            td_webserver.JOB_STATUS_CANCELLING,
        )
        self.assertTrue(task._cancel_called)


class TestRunTdCliCancellation(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _reset_state()

    def tearDown(self) -> None:
        _reset_state()

    async def test_run_td_cli_cancel_terminates_subprocess(self) -> None:
        fake_process = _FakeProcess()

        with patch.object(
            td_webserver.asyncio,
            "create_subprocess_exec",
            return_value=fake_process,
        ):
            task = asyncio.create_task(
                td_webserver.run_td_cli(
                    ["otbr-cli", "router-table"],
                    Path("/tmp"),
                )
            )
            await asyncio.wait_for(fake_process.communicate_started.wait(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertTrue(fake_process.terminate_called)


if __name__ == "__main__":
    unittest.main()
