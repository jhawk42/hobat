"""Read-only health API handler tests."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

import aiohttp.web

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