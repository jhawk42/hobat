"""Tests for Phase 2: serving checkpoint partial files via /api/data/{filename}."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import aiohttp.web
import td_webserver


def _reset_state() -> None:
    td_webserver._active_processes.clear()
    td_webserver._source_locks.clear()
    td_webserver._job_registry.clear()
    td_webserver._job_runtime_registry.clear()
    td_webserver._job_id_by_task.clear()
    td_webserver._background_tasks.clear()


def _make_app(data_dir: Path) -> dict:
    return {"td_data_dir": data_dir}


def _make_request(filename: str, app: dict) -> MagicMock:
    req = MagicMock()
    req.match_info = {"filename": filename}
    req.app = app
    req.headers = {}
    return req


class TestCheckpointFileServing(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _reset_state()
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()
        _reset_state()

    async def test_checkpoint_file_served_200_when_exists(self) -> None:
        checkpoint = "td-otbr-cli-networkdiag-fetch-all.partial.json"
        payload = b'[{"rloc16": "0x0400"}]'
        (self.data_dir / checkpoint).write_bytes(payload)

        resp = await td_webserver.handle_data_api(
            _make_request(checkpoint, _make_app(self.data_dir))
        )

        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, payload)

    async def test_checkpoint_file_returns_404_when_absent(self) -> None:
        checkpoint = "td-otbr-cli-networkdiag-fetch-all.partial.json"

        with self.assertRaises(aiohttp.web.HTTPNotFound):
            await td_webserver.handle_data_api(
                _make_request(checkpoint, _make_app(self.data_dir))
            )

    async def test_unknown_partial_filename_returns_404(self) -> None:
        """A .partial.json name that isn't derived from any known file is rejected."""
        with self.assertRaises(aiohttp.web.HTTPNotFound):
            await td_webserver.handle_data_api(
                _make_request("td-unknown-file.partial.json", _make_app(self.data_dir))
            )

    async def test_all_long_running_files_have_checkpoint_in_set(self) -> None:
        """Every force_async or long-cost file must have a checkpoint filename registered."""
        from td_const import TD_CHECKPOINT_FILENAME_SUFFIX
        for name, fa in td_webserver.FILE_ACTION_MAP.items():
            if fa.action == "STATIC":
                continue
            expected = (
                name.rsplit(".", 1)[0] + TD_CHECKPOINT_FILENAME_SUFFIX
            ).lower()
            self.assertIn(
                expected,
                td_webserver._CHECKPOINT_FILENAMES,
                f"Missing checkpoint entry for {name}",
            )

    async def test_checkpoint_filename_derivation_for_mdns(self) -> None:
        """mDNS files (force_async) must also produce a checkpoint entry."""
        self.assertIn(
            "td-mdns-scopes-thread.partial.json",
            td_webserver._CHECKPOINT_FILENAMES,
        )

    async def test_checkpoint_max_age_is_zero(self) -> None:
        """Checkpoint files must not be cached by the client."""
        self.assertEqual(td_webserver._CHECKPOINT_FILE_ACTION.max_age_s, 0)

    async def test_path_traversal_in_checkpoint_name_returns_404(self) -> None:
        with self.assertRaises(aiohttp.web.HTTPNotFound):
            await td_webserver.handle_data_api(
                _make_request(
                    "../td-otbr-cli-networkdiag-fetch-all.partial.json",
                    _make_app(self.data_dir),
                )
            )

    async def test_checkpoint_set_rebuilt_on_max_age_change(self) -> None:
        """_set_default_file_cache_max_age must rebuild _CHECKPOINT_FILENAMES."""
        original = td_webserver._CHECKPOINT_FILENAMES
        td_webserver._set_default_file_cache_max_age(3600)
        rebuilt = td_webserver._CHECKPOINT_FILENAMES
        # Must be a fresh object with the same content.
        self.assertIsNot(original, rebuilt)
        self.assertEqual(original, rebuilt)
        # Restore to avoid polluting other tests.
        td_webserver._set_default_file_cache_max_age(td_webserver.TD_DATA_FILE_CACHE_MAX_AGE_DEFAULT)


if __name__ == "__main__":
    unittest.main()
