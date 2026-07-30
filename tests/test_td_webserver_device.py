from __future__ import annotations

import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp.web
import td_webserver
from merge_extaddr_device_label_map import upsert_device_label


class DeviceApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        td_webserver._source_locks.clear()

    def tearDown(self) -> None:
        td_webserver._source_locks.clear()
        self._tmpdir.cleanup()

    def _request(self, extaddr: str, payload: object | None = None) -> MagicMock:
        request = MagicMock()
        request.match_info = {"extAddress": extaddr}
        request.app = {"td_data_dir": self.data_dir}
        request.json = AsyncMock(return_value=payload)
        return request

    def _write_map(self, payload: object) -> None:
        path = self.data_dir / "td-static-extaddr-device-label.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

    async def test_get_returns_normalized_matching_label(self) -> None:
        self._write_map(
            [{"extaddr": "4e866ce96501b9ed", "device_label": "Office"}]
        )

        response = await td_webserver.handle_device_get_api(
            self._request("4E866CE96501B9ED")
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(
            json.loads(response.text),
            {
                "extAddress": "4e866ce96501b9ed",
                "deviceLabel": "Office",
            },
        )

    async def test_get_rejects_invalid_extaddr(self) -> None:
        with self.assertRaises(aiohttp.web.HTTPBadRequest):
            await td_webserver.handle_device_get_api(self._request("not-an-extaddr"))

    async def test_get_returns_404_for_missing_map_or_entry(self) -> None:
        with self.assertRaises(aiohttp.web.HTTPNotFound):
            await td_webserver.handle_device_get_api(
                self._request("4e866ce96501b9ed")
            )

        self._write_map([])
        with self.assertRaises(aiohttp.web.HTTPNotFound):
            await td_webserver.handle_device_get_api(
                self._request("4e866ce96501b9ed")
            )

    async def test_get_rejects_invalid_static_map(self) -> None:
        self._write_map(
            [
                {"extaddr": "4e866ce96501b9ed", "device_label": "One"},
                {"extAddress": "4E866CE96501B9ED", "deviceLabel": "Two"},
            ]
        )

        with self.assertRaises(aiohttp.web.HTTPInternalServerError):
            await td_webserver.handle_device_get_api(
                self._request("4e866ce96501b9ed")
            )

    async def test_patch_inserts_via_cli_and_returns_201(self) -> None:
        async def fake_td_cli(args, data_dir, *, timeout_s=None):
            self.assertEqual(
                args,
                [
                    "merge-extaddr",
                    "--update-extaddr",
                    "4e866ce96501b9ed",
                    "--device-label",
                    "Büro Sensor",
                ],
            )
            self.assertEqual(data_dir, self.data_dir)
            self.assertEqual(timeout_s, 30)
            upsert_device_label(
                data_dir / "td-static-extaddr-device-label.json",
                args[2],
                args[4],
            )
            return 0

        with patch.object(td_webserver, "run_td_cli", side_effect=fake_td_cli):
            response = await td_webserver.handle_device_patch_api(
                self._request(
                    "4E866CE96501B9ED",
                    {"deviceLabel": "  Büro Sensor  "},
                )
            )

        self.assertEqual(response.status, 201)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(
            json.loads(response.text),
            {
                "extAddress": "4e866ce96501b9ed",
                "deviceLabel": "Büro Sensor",
            },
        )

    async def test_patch_updates_existing_record_and_returns_200(self) -> None:
        self._write_map(
            [{"extaddr": "4e866ce96501b9ed", "device_label": "Old"}]
        )

        async def fake_td_cli(args, data_dir, *, timeout_s=None):
            upsert_device_label(
                data_dir / "td-static-extaddr-device-label.json",
                args[2],
                args[4],
            )
            return 0

        with patch.object(td_webserver, "run_td_cli", side_effect=fake_td_cli):
            response = await td_webserver.handle_device_patch_api(
                self._request(
                    "4e866ce96501b9ed",
                    {"deviceLabel": "New"},
                )
            )

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.text)["deviceLabel"], "New")

    async def test_patch_rejects_invalid_payloads_before_cli(self) -> None:
        invalid_payloads = (
            [],
            "label",
            {},
            {"deviceLabel": "Office", "name": "unsupported"},
            {"deviceLabel": ""},
            {"deviceLabel": "line\nbreak"},
            {"deviceLabel": "x" * 129},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with patch.object(
                    td_webserver, "run_td_cli", new_callable=AsyncMock
                ) as run_td_cli:
                    with self.assertRaises(aiohttp.web.HTTPBadRequest):
                        await td_webserver.handle_device_patch_api(
                            self._request("4e866ce96501b9ed", payload)
                        )
                    run_td_cli.assert_not_awaited()

    async def test_patch_rejects_malformed_json_before_cli(self) -> None:
        request = self._request("4e866ce96501b9ed")
        request.json = AsyncMock(
            side_effect=json.JSONDecodeError("invalid", "not-json", 0)
        )
        with patch.object(
            td_webserver, "run_td_cli", new_callable=AsyncMock
        ) as run_td_cli:
            with self.assertRaises(aiohttp.web.HTTPBadRequest):
                await td_webserver.handle_device_patch_api(request)
            run_td_cli.assert_not_awaited()

    async def test_patch_rejects_invalid_extaddr_before_reading_body(self) -> None:
        request = self._request("invalid", {"deviceLabel": "Office"})
        with self.assertRaises(aiohttp.web.HTTPBadRequest):
            await td_webserver.handle_device_patch_api(request)
        request.json.assert_not_awaited()

    async def test_patch_maps_cli_failure_to_502(self) -> None:
        with patch.object(td_webserver, "run_td_cli", new=AsyncMock(return_value=5)):
            with self.assertRaises(aiohttp.web.HTTPBadGateway):
                await td_webserver.handle_device_patch_api(
                    self._request(
                        "4e866ce96501b9ed",
                        {"deviceLabel": "Office"},
                    )
                )

    async def test_patch_requires_successful_read_back(self) -> None:
        with patch.object(td_webserver, "run_td_cli", new=AsyncMock(return_value=0)):
            with self.assertRaises(aiohttp.web.HTTPInternalServerError):
                await td_webserver.handle_device_patch_api(
                    self._request(
                        "4e866ce96501b9ed",
                        {"deviceLabel": "Office"},
                    )
                )

    async def test_concurrent_patch_requests_are_serialized(self) -> None:
        currently_running = 0
        max_concurrent = 0

        async def fake_td_cli(args, data_dir, *, timeout_s=None):
            nonlocal currently_running, max_concurrent
            currently_running += 1
            max_concurrent = max(max_concurrent, currently_running)
            await asyncio.sleep(0.01)
            upsert_device_label(
                data_dir / "td-static-extaddr-device-label.json",
                args[2],
                args[4],
            )
            currently_running -= 1
            return 0

        with patch.object(td_webserver, "run_td_cli", side_effect=fake_td_cli):
            first, second = await asyncio.gather(
                td_webserver.handle_device_patch_api(
                    self._request(
                        "4e866ce96501b9ed",
                        {"deviceLabel": "First"},
                    )
                ),
                td_webserver.handle_device_patch_api(
                    self._request(
                        "4e866ce96501b9ed",
                        {"deviceLabel": "Second"},
                    )
                ),
            )

        self.assertEqual(max_concurrent, 1)
        self.assertEqual(sorted((first.status, second.status)), [200, 201])
        final_response = await td_webserver.handle_device_get_api(
            self._request("4e866ce96501b9ed")
        )
        self.assertEqual(json.loads(final_response.text)["deviceLabel"], "Second")

    def test_main_registers_get_and_patch_routes_before_static(self) -> None:
        with patch.object(td_webserver.aiohttp.web, "run_app") as run_app:
            rc = td_webserver.main(["--datadir", str(self.data_dir), "--port", "0"])

        self.assertEqual(rc, 0)
        app = run_app.call_args.args[0]
        routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
        self.assertIn(("GET", "/api/device/{extAddress}"), routes)
        self.assertIn(("PATCH", "/api/device/{extAddress}"), routes)


if __name__ == "__main__":
    unittest.main()