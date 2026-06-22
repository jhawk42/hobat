from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import td_webserver


def _reset_state() -> None:
    td_webserver._active_processes.clear()
    td_webserver._source_locks.clear()
    td_webserver._job_registry.clear()
    td_webserver._job_runtime_registry.clear()
    td_webserver._job_id_by_task.clear()
    td_webserver._background_tasks.clear()


def _make_job_request(job_id: str, data_dir: Path):
    req = MagicMock()
    req.match_info = {"job_id": job_id}
    req.headers = {}
    req.app = {"td_data_dir": data_dir}
    return req


class TestJobPollCheckpointMetadata(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _reset_state()
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        _reset_state()

    async def test_running_job_returns_checkpoint_filename_without_checkpoint_mtime(self) -> None:
        job_id = "job-running-no-checkpoint"
        filename = "td-otbr-cli-networkdiag-fetch-all.json"
        td_webserver._job_registry[job_id] = td_webserver.JobStatus(
            job_id=job_id,
            filename=filename,
            status=td_webserver.JOB_STATUS_RUNNING,
        )

        resp = await td_webserver.handle_job_api(_make_job_request(job_id, self.data_dir))
        body = json.loads(resp.text)

        self.assertEqual(resp.status, 200)
        self.assertEqual(body["status"], td_webserver.JOB_STATUS_RUNNING)
        self.assertEqual(
            body["checkpoint_filename"],
            "td-otbr-cli-networkdiag-fetch-all.partial.json",
        )
        self.assertIsNone(body["final_last_modified_if_exists"])
        self.assertNotIn("checkpoint_last_modified", body)
        self.assertNotIn("checkpoint_is_newer_than_final", body)

    async def test_running_job_returns_checkpoint_freshness_fields(self) -> None:
        job_id = "job-running-checkpoint"
        filename = "td-otbr-cli-networkdiag-fetch-all.json"
        td_webserver._job_registry[job_id] = td_webserver.JobStatus(
            job_id=job_id,
            filename=filename,
            status=td_webserver.JOB_STATUS_RUNNING,
        )

        final_path = self.data_dir / filename
        checkpoint_path = self.data_dir / "td-otbr-cli-networkdiag-fetch-all.partial.json"
        final_path.write_text("{}", encoding="utf-8")
        checkpoint_path.write_text("[]", encoding="utf-8")

        # Ensure checkpoint is newer than final file.
        final_stat = final_path.stat()
        os.utime(checkpoint_path, (final_stat.st_atime + 2, final_stat.st_mtime + 2))

        resp = await td_webserver.handle_job_api(_make_job_request(job_id, self.data_dir))
        body = json.loads(resp.text)

        self.assertEqual(resp.status, 200)
        self.assertEqual(body["status"], td_webserver.JOB_STATUS_RUNNING)
        self.assertIn("checkpoint_last_modified", body)
        self.assertIn("final_last_modified_if_exists", body)
        self.assertTrue(body["checkpoint_is_newer_than_final"])


if __name__ == "__main__":
    unittest.main()
