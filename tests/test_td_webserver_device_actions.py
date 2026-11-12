from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp.test_utils import TestClient, TestServer

import td_webserver
from td_const import OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME
from td_device_actions import ACTION_OTBR_PING, ACTION_OTBR_RESET
from webserver_test_support import cleanup_webserver_state


class DeviceActionApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.addAsyncCleanup(cleanup_webserver_state)
        self.data_dir = Path(self._tmpdir.name)
        (self.data_dir / OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME).write_text(
            json.dumps(
                [
                    {
                        "extAddress": "aabbccddeeff0011",
                        "ipv6Addresses": ["fd00::10"],
                        "mode": {"rxOnWhenIdle": True},
                    }
                ]
            ),
            encoding="utf-8",
        )

    def _request(self, payload: object, *, enabled: bool = True, reset: bool = True):
        request = MagicMock()
        request.app = {
            td_webserver.TD_DATA_DIR_APP_KEY: self.data_dir,
            td_webserver.TD_DEVICE_ACTIONS_ENABLED_APP_KEY: enabled,
            td_webserver.TD_DEVICE_RESET_ENABLED_APP_KEY: reset,
        }
        request.json = AsyncMock(return_value=payload)
        return request

    def _ping_payload(self) -> dict[str, object]:
        return {
            "action": ACTION_OTBR_PING,
            "deviceId": "extAddress:aabbccddeeff0011",
            "source": "otbr-cli",
            "datasetFiles": [OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME],
            "target": "fd00::10",
            "family": "ipv6",
        }

    async def test_disabled_actions_are_rejected_without_dispatch(self) -> None:
        with patch.object(
            td_webserver, "run_device_action_cli", new_callable=AsyncMock
        ) as runner:
            response = await td_webserver.handle_device_actions_api(
                self._request(self._ping_payload(), enabled=False)
            )
        self.assertEqual(response.status, 403)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        runner.assert_not_awaited()

    async def test_rejects_target_not_present_in_cached_record(self) -> None:
        payload = self._ping_payload()
        payload["target"] = "fd00::99"
        response = await td_webserver.handle_device_actions_api(
            self._request(payload)
        )
        self.assertEqual(response.status, 400)
        self.assertIn("cached address", json.loads(response.text)["error"])

    async def test_dispatches_allowlisted_action_and_polls_structured_result(self) -> None:
        before = {
            path.name: path.read_bytes()
            for path in self.data_dir.iterdir()
            if path.is_file()
        }

        async def fake_runner(args, data_dir, **kwargs):
            self.assertEqual(
                args,
                [
                    "otbr-cli",
                    "device",
                    "ping",
                    "fd00::10",
                    "--count",
                    "1",
                    "--timeout",
                    "3",
                    "--json",
                ],
            )
            self.assertEqual(data_dir, self.data_dir)
            return (
                0,
                json.dumps(
                    {
                        "sent": 1,
                        "received": 1,
                        "loss": 0,
                        "roundTripSamplesMs": [8.5],
                        "roundTripSummaryMs": {
                            "min": 8.5,
                            "average": 8.5,
                            "max": 8.5,
                        },
                        "observedAt": "2026-09-11T12:00:00Z",
                        "errorCategory": "none",
                    }
                ).encode(),
                b"",
                0.25,
            )

        with patch.object(td_webserver, "run_device_action_cli", side_effect=fake_runner):
            response = await td_webserver.handle_device_actions_api(
                self._request(self._ping_payload())
            )
            body = json.loads(response.text)
            await asyncio.wait_for(
                td_webserver._device_action_runtime_registry[body["job_id"]].task,
                timeout=1,
            )

        poll_request = MagicMock()
        poll_request.match_info = {"job_id": body["job_id"]}
        poll_response = await td_webserver.handle_device_action_job_api(poll_request)
        poll_body = json.loads(poll_response.text)
        self.assertEqual(response.status, 202)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(poll_body["status"], "done")
        self.assertEqual(poll_body["result"]["status"], "success")
        self.assertNotIn("output", poll_body["result"])
        self.assertEqual(
            before,
            {
                path.name: path.read_bytes()
                for path in self.data_dir.iterdir()
                if path.is_file()
            },
        )

    async def test_reset_has_independent_server_gate(self) -> None:
        payload = {
            "action": ACTION_OTBR_RESET,
            "deviceId": "extAddress:aabbccddeeff0011",
            "source": "otbr-cli",
            "datasetFiles": [OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME],
            "target": "fd00::10",
            "family": "ipv6",
            "counters": "both",
            "confirmed": True,
        }
        response = await td_webserver.handle_device_actions_api(
            self._request(payload, reset=False)
        )
        self.assertEqual(response.status, 403)
        self.assertIn("Reset Counters", json.loads(response.text)["error"])

    async def test_default_enabled_reset_dispatches(self) -> None:
        payload = {
            "action": ACTION_OTBR_RESET,
            "deviceId": "extAddress:aabbccddeeff0011",
            "source": "otbr-cli",
            "datasetFiles": [OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME],
            "target": "fd00::10",
            "family": "ipv6",
            "counters": "both",
            "confirmed": True,
        }

        async def fake_runner(args, data_dir, **kwargs):
            self.assertEqual(
                args,
                [
                    "otbr-cli",
                    "device",
                    "reset-counters",
                    "fd00::10",
                    "--counters",
                    "both",
                    "--confirm",
                    "--json",
                ],
            )
            self.assertEqual(data_dir, self.data_dir)
            return 0, b'{"acceptedForTransmission": true}', b"", 0.25

        with patch.object(td_webserver, "run_device_action_cli", side_effect=fake_runner):
            response = await td_webserver.handle_device_actions_api(self._request(payload))
            body = json.loads(response.text)
            await asyncio.wait_for(
                td_webserver._device_action_runtime_registry[body["job_id"]].task,
                timeout=1,
            )

        self.assertEqual(response.status, 202)

    async def test_poll_response_does_not_expose_subprocess_stderr(self) -> None:
        secret = "endpoint-token=not-for-browser"

        async def failed_runner(*args, **kwargs):
            return (
                3,
                json.dumps(
                    {
                        "sent": 1,
                        "received": 0,
                        "loss": 100,
                        "roundTripSamplesMs": [],
                        "observedAt": "2026-09-11T12:00:00Z",
                        "errorCategory": "no-response",
                    }
                ).encode(),
                secret.encode(),
                3.0,
            )

        with patch.object(
            td_webserver, "run_device_action_cli", side_effect=failed_runner
        ):
            response = await td_webserver.handle_device_actions_api(
                self._request(self._ping_payload())
            )
            body = json.loads(response.text)
            await td_webserver._device_action_runtime_registry[body["job_id"]].task

        poll_request = MagicMock()
        poll_request.match_info = {"job_id": body["job_id"]}
        poll_response = await td_webserver.handle_device_action_job_api(poll_request)
        poll_body = json.loads(poll_response.text)
        self.assertEqual(poll_body["detail"], "device action exited with code 3")
        self.assertNotIn(secret, poll_response.text)

    async def test_native_action_rejects_unrelated_allowlisted_dataset(self) -> None:
        payload = self._ping_payload()
        payload["datasetFiles"] = ["td-ha-matter-ws-dashboard.json"]
        (self.data_dir / "td-ha-matter-ws-dashboard.json").write_text(
            json.dumps(
                [{"extAddress": "aabbccddeeff0011", "ipv6Addresses": ["fd00::10"]}]
            ),
            encoding="utf-8",
        )
        response = await td_webserver.handle_device_actions_api(
            self._request(payload)
        )
        self.assertEqual(response.status, 400)
        self.assertIn("selected source", json.loads(response.text)["error"])

    async def test_capabilities_respect_independent_enablement(self) -> None:
        response = await td_webserver.handle_device_actions_capabilities_api(
            self._request({}, enabled=True, reset=False)
        )
        body = json.loads(response.text)
        self.assertTrue(body["enabled"])
        self.assertFalse(body["resetEnabled"])
        self.assertNotIn(ACTION_OTBR_RESET, body["actions"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_cancel_marks_action_terminal_and_discards_late_success(self) -> None:
        started = asyncio.Event()

        async def blocking_runner(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        with patch.object(
            td_webserver, "run_device_action_cli", side_effect=blocking_runner
        ):
            response = await td_webserver.handle_device_actions_api(
                self._request(self._ping_payload())
            )
            body = json.loads(response.text)
            await asyncio.wait_for(started.wait(), timeout=1)
            cancel_request = MagicMock()
            cancel_request.match_info = {"job_id": body["job_id"]}
            cancel_response = await td_webserver.handle_device_action_job_cancel_api(
                cancel_request
            )
            task = td_webserver._device_action_runtime_registry[body["job_id"]].task
            await asyncio.gather(task, return_exceptions=True)

        job = td_webserver._device_action_job_registry[body["job_id"]]
        self.assertEqual(cancel_response.status, 202)
        self.assertEqual(job.status, "cancelled")
        self.assertEqual(job.result["status"], "cancelled")

    async def test_prestart_cancel_preserves_envelope_and_cleans_runtime(self) -> None:
        completed = asyncio.Event()
        payload = self._ping_payload() | {"invocationId": "prestart-invocation"}
        with patch.object(td_webserver, "run_device_action_cli", new_callable=AsyncMock) as runner:
            response = await td_webserver.handle_device_actions_api(self._request(payload))
            job_id = json.loads(response.text)["job_id"]
            task = td_webserver._device_action_runtime_registry[job_id].task
            task.add_done_callback(lambda _: completed.set())
            request = MagicMock()
            request.match_info = {"job_id": job_id}
            cancel_response = await td_webserver.handle_device_action_job_cancel_api(request)
            self.assertEqual(cancel_response.status, 202)
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.wait_for(completed.wait(), timeout=1)
            poll = await td_webserver.handle_device_action_job_api(request)
            self.assertEqual(json.loads(poll.text), {
                "job_id": job_id, "invocationId": "prestart-invocation",
                "action": ACTION_OTBR_PING, "status": "cancelled",
                "detail": td_webserver._JOB_CANCEL_GRACE_DETAIL,
                "result": {
                    "action": ACTION_OTBR_PING, "targetKind": "ipv6",
                    "target": "fd00::10", "status": "cancelled",
                },
            })
            self.assertEqual(poll.headers["Cache-Control"], "no-store")
            self.assertNotIn(job_id, td_webserver._device_action_runtime_registry)
            self.assertNotIn(task, td_webserver._device_action_job_id_by_task)
            self.assertNotIn(task, td_webserver._device_action_background_tasks)
            self.assertNotIn(job_id, {item["jobId"] for item in td_webserver._project_pending_jobs()})
            again = await td_webserver.handle_device_action_job_cancel_api(request)
            self.assertEqual(again.status, 409)
            runner.assert_not_awaited()

    async def test_bounded_stream_retains_only_limit(self) -> None:
        stream = asyncio.StreamReader()
        stream.feed_data(b"x" * (td_webserver._DEVICE_ACTION_OUTPUT_LIMIT_BYTES + 100))
        stream.feed_eof()
        output = await td_webserver._read_bounded_stream(stream)
        self.assertEqual(len(output), td_webserver._DEVICE_ACTION_OUTPUT_LIMIT_BYTES)


class _RunnerProcess:
    def __init__(self, mode, exit_code=0):
        self.mode = mode
        self.exit_code = exit_code
        self.returncode = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(b"stdout-prefix" * 1000)
        self.stderr.feed_data(b"stderr-prefix" * 1000)
        self.entered = asyncio.Event()
        self.calls = []
        self.timeout = TimeoutError("synthetic child wait timed out")

    def _exit(self, code):
        self.returncode = code
        self.stdout.feed_eof()
        self.stderr.feed_eof()

    async def wait(self):
        self.calls.append("wait")
        self.entered.set()
        count = self.calls.count("wait")
        if count == 1:
            if self.mode == "cancel":
                await asyncio.Event().wait()
            elif self.mode in {"timeout", "kill"}:
                raise self.timeout
            else:
                self._exit(self.exit_code)
        elif self.mode == "kill" and count == 2:
            raise TimeoutError("synthetic termination grace expired")
        return self.returncode

    def terminate(self):
        self.calls.append("terminate")
        if self.mode != "kill":
            self._exit(-15)

    def kill(self):
        self.calls.append("kill")
        self._exit(-9)


class DeviceActionRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data_dir = Path(directory.name)
        self.args = ["system-ping", "--target", "127.0.0.1"]

    def _assert_spawn(self, spawn):
        spawn.assert_awaited_once_with(
            sys.executable, str(Path(td_webserver.__file__).parent / "td_cli.py"),
            "--datadir", str(self.data_dir), *self.args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )

    async def test_real_runner_exit_status_prefixes_and_complete_stream_draining(self):
        for code in (0, 7):
            with self.subTest(code=code):
                process = _RunnerProcess("success", code)
                started = MagicMock()
                ended = MagicMock()
                before = asyncio.all_tasks()
                with patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=process)) as spawn:
                    result = await asyncio.wait_for(td_webserver.run_device_action_cli(
                        self.args, self.data_dir, timeout_s=60, output_limit_bytes=11,
                        on_process_started=started, on_process_ended=ended,
                    ), 5)
                self._assert_spawn(spawn)
                self.assertEqual(result[:3], (code, b"stdout-pref", b"stderr-pref"))
                self.assertGreaterEqual(result[3], 0)
                self.assertTrue(process.stdout.at_eof())
                self.assertTrue(process.stderr.at_eof())
                self.assertEqual(process.calls, ["wait"])
                started.assert_called_once_with(process)
                ended.assert_called_once_with()
                self.assertFalse(asyncio.all_tasks() - before)
        self.assertEqual(await td_webserver._read_bounded_stream(None), b"")

    async def test_timeout_and_cancellation_reap_before_callback_and_propagate(self):
        for mode in ("timeout", "kill", "cancel"):
            with self.subTest(mode=mode):
                process = _RunnerProcess(mode)
                started = MagicMock()
                ended_state = []

                def ended():
                    ended_state.append((
                        process.returncode, process.stdout.at_eof(), process.stderr.at_eof(),
                    ))

                before = asyncio.all_tasks()
                with patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=process)) as spawn:
                    task = asyncio.create_task(td_webserver.run_device_action_cli(
                        self.args, self.data_dir, timeout_s=60,
                        on_process_started=started, on_process_ended=ended,
                    ))
                    self.addAsyncCleanup(self._finish_task, task)
                    if mode == "cancel":
                        await asyncio.wait_for(process.entered.wait(), 5)
                        task.cancel()
                    error_type = asyncio.CancelledError if mode == "cancel" else TimeoutError
                    with self.assertRaises(error_type) as raised:
                        await asyncio.wait_for(task, 5)
                if mode != "cancel":
                    self.assertIs(raised.exception, process.timeout)
                self._assert_spawn(spawn)
                started.assert_called_once_with(process)
                self.assertEqual(process.calls, (
                    ["wait", "terminate", "wait", "kill", "wait"] if mode == "kill"
                    else ["wait", "terminate", "wait"]
                ))
                self.assertEqual(ended_state, [(-9 if mode == "kill" else -15, True, True)])
                self.assertTrue(task.done())
                self.assertFalse(asyncio.all_tasks() - before)

    async def _finish_task(self, task):
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_spawn_error_does_not_report_started_or_ended_process(self):
        started, ended = MagicMock(), MagicMock()
        error = OSError("synthetic spawn failure")
        with patch.object(asyncio, "create_subprocess_exec", AsyncMock(side_effect=error)):
            with self.assertRaises(OSError) as raised:
                await asyncio.wait_for(td_webserver.run_device_action_cli(
                    self.args, self.data_dir, timeout_s=60,
                    on_process_started=started, on_process_ended=ended,
                ), 5)
        self.assertIs(raised.exception, error)
        started.assert_not_called()
        ended.assert_not_called()

    async def test_real_child_pipe_pressure_is_drained_and_reaped(self):
        real_spawn = asyncio.create_subprocess_exec
        children = []

        async def reap(process):
            if process.returncode is None:
                process.kill()
            await asyncio.wait_for(process.wait(), 10)

        async def spawn(*args, **kwargs):
            self.assertEqual(args, (
                sys.executable, str(Path(td_webserver.__file__).parent / "td_cli.py"),
                "--datadir", str(self.data_dir), *self.args,
            ))
            process = await real_spawn(
                sys.executable, "-c",
                "import sys; sys.stdout.buffer.write(b'A'*262144); "
                "sys.stdout.buffer.flush(); sys.stderr.buffer.write(b'B'*262144); "
                "sys.stderr.buffer.flush()",
                **kwargs,
            )
            children.append(process)
            self.addAsyncCleanup(reap, process)
            return process

        with patch.object(asyncio, "create_subprocess_exec", side_effect=spawn):
            result = await asyncio.wait_for(td_webserver.run_device_action_cli(
                self.args, self.data_dir, timeout_s=20, output_limit_bytes=17,
            ), 30)
        self.assertEqual(result[:3], (0, b"A" * 17, b"B" * 17))
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].returncode, 0)
        self.assertTrue(children[0].stdout.at_eof())
        self.assertTrue(children[0].stderr.at_eof())


class StartupDeviceActionCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.addAsyncCleanup(cleanup_webserver_state)
        with patch.object(td_webserver.aiohttp.web, "run_app") as run_app:
            td_webserver.main(["--datadir", self._tmpdir.name, "--port", "0"])
        self.client = TestClient(TestServer(run_app.call_args.args[0]))
        self.addAsyncCleanup(self.client.close)
        await self.client.start_server()

    async def test_no_flag_start_exposes_all_device_actions(self) -> None:
        response = await self.client.get("/api/device-actions")
        body = await response.json()

        self.assertEqual(response.status, 200)
        self.assertTrue(body["enabled"])
        self.assertTrue(body["resetEnabled"])
        self.assertEqual(
            body["actions"],
            [
                "otbr-cli-ping",
                "ha-matter-ws-ping",
                "system-ping",
                "otbr-cli-reset-counters",
            ],
        )
        self.assertEqual(response.headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
