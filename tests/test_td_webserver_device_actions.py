from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import td_webserver
from td_const import OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME
from td_device_actions import ACTION_OTBR_PING, ACTION_OTBR_RESET


class DeviceActionApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        td_webserver._device_action_job_registry.clear()
        td_webserver._device_action_runtime_registry.clear()
        td_webserver._device_action_job_id_by_task.clear()
        td_webserver._device_action_background_tasks.clear()
        td_webserver._source_locks.clear()
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

    async def asyncTearDown(self) -> None:
        tasks = list(td_webserver._device_action_background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tmpdir.cleanup()

    def _request(self, payload: object, *, enabled: bool = True, reset: bool = False):
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

    async def test_bounded_stream_retains_only_limit(self) -> None:
        stream = asyncio.StreamReader()
        stream.feed_data(b"x" * (td_webserver._DEVICE_ACTION_OUTPUT_LIMIT_BYTES + 100))
        stream.feed_eof()
        output = await td_webserver._read_bounded_stream(stream)
        self.assertEqual(len(output), td_webserver._DEVICE_ACTION_OUTPUT_LIMIT_BYTES)


if __name__ == "__main__":
    unittest.main()
