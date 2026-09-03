"""Read-only health API handler tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import MagicMock

import aiohttp.web
from aiohttp.test_utils import TestClient, TestServer

import td_webserver
from td_health_sqlite import SQLiteHealthStore
from test_td_health_sqlite import _result


def _request(data_dir, *, query=None, match_info=None):
    request = MagicMock()
    request.app = {td_webserver.TD_DATA_DIR_APP_KEY: data_dir}
    request.query = query or {}
    request.match_info = match_info or {}
    return request


class HealthApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_is_pinned_grouped_and_no_store(self) -> None:
        with self.subTest("stored assessment"):
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory() as directory:
                data_dir = Path(directory)
                SQLiteHealthStore(data_dir / "td-health.db").save_processing_result(
                    *_result()
                )
                response = await td_webserver.handle_health_summary_api(
                    _request(data_dir, query={"dataset": "otbr_cli_networkdiag_fetch_all"})
                )
                payload = json.loads(response.text)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(payload["assessmentId"], "assessment-1")
                self.assertIn("findingGroups", payload)

    async def test_summary_requires_dataset_and_missing_store_is_unavailable(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            with self.assertRaises(aiohttp.web.HTTPBadRequest):
                await td_webserver.handle_health_summary_api(_request(data_dir))
            with self.assertRaises(aiohttp.web.HTTPServiceUnavailable):
                await td_webserver.handle_health_summary_api(
                    _request(data_dir, query={"dataset": "otbr_cli_networkdiag_fetch_all"})
                )

    async def test_observation_limit_is_bounded_before_store_access(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(aiohttp.web.HTTPBadRequest):
                await td_webserver.handle_health_observations_api(
                    _request(Path(directory), query={"limit": "101"})
                )

    async def test_findings_validate_filters_before_store_access(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            request = _request(
                Path(directory),
                query={"assessment": "assessment-1", "scope": "invalid"},
            )
            with self.assertRaises(aiohttp.web.HTTPBadRequest):
                await td_webserver.handle_health_findings_api(request)


class SameOriginApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        SQLiteHealthStore(self.data_dir / "td-health.db").save_processing_result(
            *_result()
        )
        with patch.object(td_webserver.aiohttp.web, "run_app") as run_app:
            td_webserver.main(["--datadir", str(self.data_dir), "--port", "0"])
        self.client = TestClient(TestServer(run_app.call_args.args[0]))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self._tmpdir.cleanup()

    async def test_same_origin_health_reads_reach_every_endpoint_without_cors(self) -> None:
        paths = (
            "/api/health/summary?dataset=otbr_cli_networkdiag_fetch_all",
            "/api/health/findings?assessment=assessment-1",
            "/api/health/devices/extaddr:8672766ae0578187?assessment=assessment-1",
            "/api/health/observations?network=extpan:78b9775b001c1cbe&limit=5&offset=0",
            "/api/health/latest?dataset=otbr_cli_networkdiag_fetch_all",
            "/api/health/capabilities",
        )
        for path in paths:
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status, 200)
                self.assertFalse(
                    any(name.lower().startswith("access-control-") for name in response.headers)
                )

    async def test_foreign_origin_is_not_authorized_and_mutating_preflights_fail(self) -> None:
        health_paths = (
            "/api/health/summary?dataset=otbr_cli_networkdiag_fetch_all",
            "/api/health/findings?assessment=assessment-1",
            "/api/health/devices/extaddr:8672766ae0578187?assessment=assessment-1",
            "/api/health/observations?limit=5&offset=0",
            "/api/health/latest?dataset=otbr_cli_networkdiag_fetch_all",
            "/api/health/capabilities",
        )
        for path in health_paths:
            with self.subTest(path=path):
                response = await self.client.get(
                    path, headers={"Origin": "https://foreign.example"}
                )
                self.assertEqual(response.status, 200)
                self.assertFalse(
                    any(name.lower().startswith("access-control-") for name in response.headers)
                )

        preflights = (
            ("/api/device/8672766ae0578187", "PATCH"),
            ("/api/job/job-1", "DELETE"),
        )
        for path, method in preflights:
            with self.subTest(path=path, method=method):
                response = await self.client.options(
                    path,
                    headers={
                        "Origin": "https://foreign.example",
                        "Access-Control-Request-Method": method,
                        "Access-Control-Request-Headers": "content-type",
                    },
                )
                self.assertEqual(response.status, 405)
                self.assertFalse(
                    any(name.lower().startswith("access-control-") for name in response.headers)
                )