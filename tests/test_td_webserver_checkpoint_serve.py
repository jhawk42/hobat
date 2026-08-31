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

import aiohttp.web
import td_webserver
from webserver_test_support import (
    make_data_request as _make_request,
    make_webserver_app as _make_app,
    reset_webserver_state as _reset_state,
)


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

    async def test_all_mdns_scope_files_are_progressive_checkpoint_sources(self) -> None:
        """All mdns scope datasets used by the dashboard must support checkpoint polling."""
        expected_files = {
            "td-mdns-scopes-thread.json",
            "td-mdns-scopes-br.json",
            "td-mdns-scopes-hap.json",
            "td-mdns-scopes-matter.json",
        }

        for filename in expected_files:
            self.assertIn(
                filename,
                td_webserver.FILE_ACTION_MAP,
                f"Missing FILE_ACTION_MAP entry for {filename}",
            )
            self.assertIn(
                filename.replace(".json", ".partial.json"),
                td_webserver._CHECKPOINT_FILENAMES,
                f"Missing checkpoint filename for {filename}",
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

    async def test_phase4_required_entries_are_force_async(self) -> None:
        """Phase 4 regression: entries that rely on job polling must dispatch async."""
        required_async = {
            "td-otbr-cli-networkdiag-multicast-network.json",
            "td-otbr-cli-networkdiag-multicast-neighbors.json",
            "td-otbr-restapi-devices-fetch.json",
        }

        for filename in required_async:
            self.assertIn(filename, td_webserver.FILE_ACTION_MAP)
            self.assertTrue(
                td_webserver.FILE_ACTION_MAP[filename].force_async,
                f"Expected force_async=True for {filename}",
            )

    async def test_restapi_actions_match_workflow_contracts(self) -> None:
        devices = td_webserver.FILE_ACTION_MAP[
            "td-otbr-restapi-devices-fetch.json"
        ]
        diagnostics = td_webserver.FILE_ACTION_MAP[
            "td-otbr-restapi-diagnostics-fetch-all.json"
        ]
        mesh = td_webserver.FILE_ACTION_MAP[
            "td-otbr-restapi-mesh-diagnostics-fetch-all.json"
        ]

        self.assertGreaterEqual(devices.action_cost_s, 40)
        self.assertEqual(
            diagnostics.action,
            ["otbr-restapi", "diagnostics", "fetch-all", "--items-only"],
        )
        self.assertEqual(
            mesh.action,
            [
                "otbr-restapi",
                "mesh-diagnostics",
                "fetch-all",
                "--routers-only",
                "--items-only",
            ],
        )
        self.assertGreaterEqual(diagnostics.action_cost_s, 1200)
        self.assertGreaterEqual(mesh.action_cost_s, 1200)

    async def test_ha_matter_ws_actions_share_source_and_expensive_work_is_async(self) -> None:
        expected_actions = {
            "td-ha-matter-ws-server-info.json": ["ha-matter-ws", "server-info"],
            "td-ha-matter-ws-devices-fetch-all.json": [
                "ha-matter-ws", "devices", "fetch-all"
            ],
            "td-ha-matter-ws-diagnostics-fetch-all.json": [
                "ha-matter-ws", "diagnostics", "fetch-all"
            ],
            "td-ha-matter-ws-mesh-diagnostics-fetch-all.json": [
                "ha-matter-ws", "mesh-diagnostics", "fetch-all"
            ],
            "td-ha-matter-ws-topology.json": ["ha-matter-ws", "topology"],
            "td-ha-matter-ws-dashboard.json": ["ha-matter-ws", "dashboard"],
            "td-ha-matter-ws-collection.outcome.json": ["ha-matter-ws", "all"],
        }

        for filename, action in expected_actions.items():
            file_action = td_webserver.FILE_ACTION_MAP[filename]
            self.assertEqual(file_action.action, action)
            self.assertEqual(file_action.action[0], "ha-matter-ws")

        self.assertFalse(
            td_webserver.FILE_ACTION_MAP[
                "td-ha-matter-ws-server-info.json"
            ].force_async
        )
        for filename in set(expected_actions) - {"td-ha-matter-ws-server-info.json"}:
            self.assertTrue(td_webserver.FILE_ACTION_MAP[filename].force_async)

        self.assertIs(
            td_webserver._get_source_lock("ha-matter-ws"),
            td_webserver._get_source_lock("ha-matter-ws"),
        )


if __name__ == "__main__":
    unittest.main()
