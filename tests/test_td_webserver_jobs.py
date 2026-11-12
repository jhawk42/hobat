from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import td_webserver
from td_device_actions import parse_device_action_request
from webserver_test_support import reset_webserver_state


class _DummyTask:
    def __init__(self, *, done: bool = False) -> None:
        self.cancel_called = False
        self.cancel_count = 0
        self._done = done

    def cancel(self) -> bool:
        self.cancel_called = True
        self.cancel_count += 1
        return True

    def done(self) -> bool:
        return self._done


def _action_request():
    return parse_device_action_request(
        {
            "action": "otbr-cli-ping",
            "deviceId": "extAddress:aabbccddeeff0011",
            "source": "otbr-cli",
            "datasetFiles": ["td-otbr-cli-networkdiag-topology.json"],
            "target": "fd00::10",
            "family": "ipv6",
        }
    )


class UnifiedJobsApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_webserver_state()

    def tearDown(self) -> None:
        reset_webserver_state()

    async def test_listing_merges_active_jobs_without_sensitive_payloads(self) -> None:
        td_webserver._job_registry["data-job"] = td_webserver.JobStatus(
            job_id="data-job",
            filename="td-example.json",
            status=td_webserver.JOB_STATUS_RUNNING,
            kind="data",
            source="otbr-cli",
            created_at=100.0,
        )
        td_webserver._job_registry["health-job"] = td_webserver.JobStatus(
            job_id="health-job",
            filename="",
            status=td_webserver.JOB_STATUS_CANCELLING,
            kind="health",
            source="health",
            task="health-process-dataset",
            dataset="network-topology",
            created_at=101.0,
        )
        td_webserver._job_registry["done-job"] = td_webserver.JobStatus(
            job_id="done-job",
            filename="secret-output.json",
            status=td_webserver.JOB_STATUS_DONE,
            result={"secret": "not-for-browser"},
            created_at=99.0,
        )
        td_webserver._device_action_job_registry["action-job"] = (
            td_webserver.DeviceActionJobStatus(
                job_id="action-job",
                invocation_id="private-invocation",
                request=_action_request(),
                status=td_webserver.JOB_STATUS_RUNNING,
                created_at=102.0,
            )
        )

        response = await td_webserver.handle_jobs_api(MagicMock())
        body = json.loads(response.text)

        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(
            [job["jobId"] for job in body["jobs"]],
            ["data-job", "health-job", "action-job"],
        )
        self.assertEqual(body["jobs"][0]["source"], "otbr-cli")
        self.assertEqual(body["jobs"][1]["kind"], "health")
        self.assertEqual(body["jobs"][1]["dataset"], "network-topology")
        self.assertFalse(body["jobs"][1]["cancellable"])
        self.assertEqual(
            body["jobs"][2]["cancelUrl"],
            "/api/device-action-jobs/action-job",
        )
        self.assertNotIn("invocation", response.text)
        self.assertNotIn("secret", response.text)
        self.assertNotIn("target", response.text)

    async def test_bulk_cancel_is_deterministic_and_idempotent(self) -> None:
        generic_task = _DummyTask()
        action_task = _DummyTask()
        td_webserver._job_registry["generic"] = td_webserver.JobStatus(
            job_id="generic",
            filename="td-example.json",
            status=td_webserver.JOB_STATUS_RUNNING,
            source="otbr-cli",
            created_at=20.0,
        )
        td_webserver._job_runtime_registry["generic"] = td_webserver.JobRuntime(
            job_id="generic",
            filename="td-example.json",
            source="otbr-cli",
            task=generic_task,  # type: ignore[arg-type]
        )
        td_webserver._device_action_job_registry["action"] = (
            td_webserver.DeviceActionJobStatus(
                job_id="action",
                invocation_id="invocation",
                request=_action_request(),
                status=td_webserver.JOB_STATUS_RUNNING,
                created_at=10.0,
            )
        )
        td_webserver._device_action_runtime_registry["action"] = (
            td_webserver.DeviceActionJobRuntime(
                job_id="action",
                source="otbr-cli",
                task=action_task,  # type: ignore[arg-type]
            )
        )

        first = await td_webserver.handle_jobs_cancel_api(MagicMock())
        second = await td_webserver.handle_jobs_cancel_api(MagicMock())

        self.assertEqual(first.status, 202)
        self.assertEqual(first.headers["Cache-Control"], "no-store")
        self.assertEqual(
            json.loads(first.text),
            {
                "requested": 2,
                "jobs": [
                    {"jobId": "action", "status": "cancelling"},
                    {"jobId": "generic", "status": "cancelling"},
                ],
            },
        )
        self.assertEqual(json.loads(second.text), json.loads(first.text))
        self.assertTrue(generic_task.cancel_called)
        self.assertTrue(action_task.cancel_called)
        self.assertEqual(generic_task.cancel_count, 1)
        self.assertEqual(action_task.cancel_count, 1)

    async def test_missing_runtime_becomes_terminal_instead_of_stuck(self) -> None:
        td_webserver._job_registry["generic"] = td_webserver.JobStatus(
            job_id="generic",
            filename="td-example.json",
            status=td_webserver.JOB_STATUS_RUNNING,
        )
        td_webserver._device_action_job_registry["action"] = (
            td_webserver.DeviceActionJobStatus(
                job_id="action",
                invocation_id="invocation",
                request=_action_request(),
                status=td_webserver.JOB_STATUS_RUNNING,
            )
        )

        response = await td_webserver.handle_jobs_cancel_api(MagicMock())
        body = json.loads(response.text)

        self.assertEqual(
            {item["status"] for item in body["jobs"]},
            {td_webserver.JOB_STATUS_CANCELLED},
        )
        self.assertEqual(
            td_webserver._job_registry["generic"].status,
            td_webserver.JOB_STATUS_CANCELLED,
        )
        self.assertEqual(
            td_webserver._device_action_job_registry["action"].status,
            td_webserver.JOB_STATUS_CANCELLED,
        )

    async def test_cancelling_records_with_missing_or_done_runtime_are_reconciled(self) -> None:
        for done_runtime in (False, True):
            with self.subTest(done_runtime=done_runtime):
                generic = td_webserver.JobStatus(
                    job_id="generic", filename="", status="cancelling",
                    dataset="health-dataset", detail="existing detail", created_at=20,
                )
                action = td_webserver.DeviceActionJobStatus(
                    job_id="action", invocation_id="invocation", request=_action_request(),
                    status="cancelling", detail="existing detail", created_at=10,
                )
                td_webserver._job_registry[generic.job_id] = generic
                td_webserver._device_action_job_registry[action.job_id] = action
                td_webserver._health_job_id_by_dataset["health-dataset"] = generic.job_id
                if done_runtime:
                    task = MagicMock(spec=asyncio.Task)
                    task.done.return_value = True
                    td_webserver._job_runtime_registry[generic.job_id] = td_webserver.JobRuntime(
                        job_id=generic.job_id, filename="", source="health", task=task,
                    )
                    td_webserver._device_action_runtime_registry[action.job_id] = td_webserver.DeviceActionJobRuntime(
                        job_id=action.job_id, source="otbr-cli", task=task,
                    )
                response = await td_webserver.handle_jobs_cancel_api(MagicMock())
                self.assertEqual(
                    json.loads(response.text),
                    {"requested": 2, "jobs": [
                        {"jobId": "action", "status": "cancelled"},
                        {"jobId": "generic", "status": "cancelled"},
                    ]},
                )
                self.assertEqual(generic.detail, "existing detail")
                self.assertEqual(action.detail, "existing detail")
                self.assertEqual(action.result, {
                    "action": "otbr-cli-ping", "targetKind": "ipv6",
                    "target": "fd00::10", "status": "cancelled",
                })
                self.assertNotIn("health-dataset", td_webserver._health_job_id_by_dataset)

    async def test_cancelled_callbacks_do_not_rewrite_terminal_records(self) -> None:
        async def never_started():
            self.fail("Cancelled worker must not start")

        for status in ("done", "error", "cancelled"):
            for kind in ("generic", "action"):
                with self.subTest(status=status, kind=kind):
                    if kind == "generic":
                        job = td_webserver.JobStatus(
                            job_id="generic", filename="", status=status,
                            detail="retained", result={"retained": True},
                        )
                        registry = td_webserver._job_registry
                        reverse = td_webserver._job_id_by_task
                        callback = td_webserver._on_background_task_done
                    else:
                        job = td_webserver.DeviceActionJobStatus(
                            job_id="action", invocation_id="invocation", request=_action_request(),
                            status=status, detail="retained", result={"retained": True},
                        )
                        registry = td_webserver._device_action_job_registry
                        reverse = td_webserver._device_action_job_id_by_task
                        callback = td_webserver._on_device_action_task_done
                    registry[job.job_id] = job
                    completed = asyncio.Event()
                    task = asyncio.create_task(never_started())
                    reverse[task] = job.job_id
                    task.add_done_callback(callback)
                    task.add_done_callback(lambda _: completed.set())
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    await asyncio.wait_for(completed.wait(), timeout=1)
                    self.assertEqual((job.status, job.detail, job.result), (
                        status, "retained", {"retained": True},
                    ))

    async def test_missing_runtime_matter_cancellation_keeps_node_target(self) -> None:
        request = replace(
            _action_request(), action="ha-matter-ws-ping", source="ha-matter-ws",
            node_id=42, target=None, family=None,
        )
        job = td_webserver.DeviceActionJobStatus(
            job_id="matter", invocation_id="invocation", request=request, status="running",
        )
        td_webserver._device_action_job_registry[job.job_id] = job
        self.assertEqual(td_webserver._cancel_device_action_job(job.job_id), "cancelled")
        self.assertEqual(job.result, {
            "action": "ha-matter-ws-ping", "targetKind": "matter-node",
            "target": 42, "status": "cancelled",
        })

    def test_main_registers_unified_job_routes_before_static_assets(self) -> None:
        source = Path(td_webserver.__file__).read_text(encoding="utf-8")
        get_route = 'app.router.add_get("/api/jobs", handle_jobs_api)'
        delete_route = 'app.router.add_delete("/api/jobs", handle_jobs_cancel_api)'
        static_route = 'app.router.add_static('

        self.assertIn(get_route, source)
        self.assertIn(delete_route, source)
        self.assertLess(source.index(get_route), source.index(static_route))
        self.assertLess(source.index(delete_route), source.index(static_route))


if __name__ == "__main__":
    unittest.main()
