from __future__ import annotations

import tempfile
import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

import otbr_restapi_download as script_module


class TdGetOtbrRestApiTests(unittest.TestCase):
    def test_build_base_url_prefers_explicit_base_url(self) -> None:
        self.assertEqual(
            script_module.build_base_url(
                "127.0.0.1", 8081, "http://example.test:1234/"
            ),
            "http://example.test:1234",
        )

    def test_build_headers_merges_accept_and_extra_headers(self) -> None:
        headers = script_module.build_headers(
            "application/json",
            ["Authorization: Bearer token", "X-Test: value"],
        )

        self.assertEqual(
            headers,
            {
                "Accept": "application/json",
                "Authorization": "Bearer token",
                "X-Test": "value",
            },
        )

    def test_main_passes_parsed_network_options_to_restapi_downloads(self) -> None:
        """Test that main() constructs a client and passes it to download_all_restapi_endpoints()."""
        with patch.object(
            script_module, "download_all_restapi_endpoints", return_value=0
        ) as download_all_restapi_endpoints:
            exit_code = script_module.main(
                [
                    "--host",
                    "192.168.4.77",
                    "--port",
                    "18081",
                    "--accept",
                    "application/json",
                    "--header",
                    "Authorization: Bearer token",
                    "--timeout",
                    "15",
                ]
            )

        self.assertEqual(exit_code, 0)
        
        # After Phase IV-2 migration, main() passes a client instead of base_url/headers/timeout
        download_all_restapi_endpoints.assert_called_once()
        call_kwargs = download_all_restapi_endpoints.call_args[1]
        
        # Verify client was passed with correct configuration
        self.assertIn("client", call_kwargs)
        client = call_kwargs["client"]
        self.assertEqual(client.base_url, "http://192.168.4.77:18081")
        self.assertEqual(client.timeout, 15)
        self.assertEqual(client.accept, "application/json")
        
        # Verify data_dir and update_devices were passed
        self.assertIn("data_dir", call_kwargs)
        self.assertIn("update_devices", call_kwargs)
        self.assertEqual(call_kwargs["update_devices"], False)

    def test_main_uses_otbr_env_defaults_when_args_omitted(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OT_REST_LISTEN_ADDR": "0.0.0.0",
                "OT_REST_LISTEN_PORT": "18081",
            },
            clear=False,
        ), patch.object(
            script_module, "download_all_restapi_endpoints", return_value=0
        ) as download_all_restapi_endpoints:
            exit_code = script_module.main([])

        self.assertEqual(exit_code, 0)
        client = download_all_restapi_endpoints.call_args.kwargs["client"]
        self.assertEqual(client.base_url, "http://0.0.0.0:18081")

    def test_download_all_falls_back_for_invalid_env_port(self) -> None:
        mock_client = MagicMock()
        mock_client.get_active_dataset.return_value = {}
        mock_client.list_devices.return_value = []
        mock_client.list_diagnostics.return_value = []

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ",
            {
                "OT_REST_LISTEN_ADDR": "0.0.0.0",
                "OT_REST_LISTEN_PORT": "invalid",
            },
            clear=False,
        ), patch.object(
            script_module, "_build_client_from_options", return_value=mock_client
        ) as build_client, patch.object(
            script_module, "emit_rest_payload_output", return_value=None
        ):
            script_module.download_all_restapi_endpoints(
                client=None,
                data_dir=script_module.Path(temp_dir),
                base_url=None,
                headers=None,
            )

        self.assertEqual(
            build_client.call_args.kwargs["base_url"],
            "http://0.0.0.0:8081",
        )

    def test_static_downloads_preserve_order_and_continue_after_failure(self) -> None:
        mock_client = MagicMock()
        mock_client.get_active_dataset.return_value = {"dataset": True}
        mock_client.list_devices.side_effect = script_module.OTBRClientError("failed")
        mock_client.list_diagnostics.return_value = {"diagnostics": True}

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = script_module.Path(temp_dir)
            exit_code = script_module.download_all_restapi_endpoints(
                client=mock_client,
                data_dir=data_dir,
            )

            output_filenames = [path.name for path in data_dir.iterdir()]

        self.assertEqual(exit_code, 1)
        mock_client.get_active_dataset.assert_called_once_with(raw=True)
        mock_client.list_devices.assert_called_once_with(raw=True)
        mock_client.list_diagnostics.assert_called_once_with(raw=True)
        self.assertEqual(
            mock_client.method_calls,
            [
                unittest.mock.call.get_active_dataset(raw=True),
                unittest.mock.call.list_devices(raw=True),
                unittest.mock.call.list_diagnostics(raw=True),
            ],
        )
        self.assertEqual(
            sorted(output_filenames),
            [
                "td-otbr-restapi-dataset-active.json",
                "td-otbr-restapi-diagnostics.json",
            ],
        )

    def test_static_download_saves_each_payload_before_collecting_the_next(self) -> None:
        events = []
        mock_client = MagicMock()

        def collect(name, payload):
            def _inner(raw):
                self.assertTrue(raw)
                events.append(f"collect:{name}")
                return payload

            return _inner

        mock_client.get_active_dataset.side_effect = collect("dataset", {"dataset": True})
        mock_client.list_devices.side_effect = collect("devices", [{"id": "dev-1"}])
        mock_client.list_diagnostics.side_effect = collect("diagnostics", [{"id": "diag-1"}])

        def save(_payload, output_file, _logger):
            events.append(f"save:{output_file.name}")

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            script_module, "emit_rest_payload_output", side_effect=save
        ):
            exit_code = script_module._download_static_endpoints(
                mock_client,
                script_module.Path(temp_dir),
                script_module._STATIC_ENDPOINTS,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            events,
            [
                "collect:dataset",
                "save:td-otbr-restapi-dataset-active.json",
                "collect:devices",
                "save:td-otbr-restapi-devices.json",
                "collect:diagnostics",
                "save:td-otbr-restapi-diagnostics.json",
            ],
        )

    def test_diagnostics_continue_after_device_failures(self) -> None:
        mock_client = MagicMock()
        mock_client.list_devices.return_value = [
            {"id": "ok"},
            {"missing": "id"},
            {"id": "action-failed"},
            {"id": "client-failed"},
        ]
        mock_client.fetch_device_diagnostics.side_effect = [
            {"data": "ok"},
            script_module.OTBRActionFailedError(
                "failed", "action-1", "failed"
            ),
            script_module.OTBRClientError("failed"),
        ]
        diag_types = ["EXT_ADDRESS", "RLOC16"]

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = script_module.Path(temp_dir)
            exit_code = script_module._save_device_diagnostics(
                mock_client,
                data_dir,
                diag_types,
            )

            output_filenames = [path.name for path in data_dir.iterdir()]

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            mock_client.fetch_device_diagnostics.call_args_list,
            [
                unittest.mock.call("ok", types=diag_types, raw=True),
                unittest.mock.call("action-failed", types=diag_types, raw=True),
                unittest.mock.call("client-failed", types=diag_types, raw=True),
            ],
        )
        self.assertEqual(
            output_filenames,
            ["td-otbr-restapi-diagnostic-ok.json"],
        )

    def test_diagnostics_skip_empty_device_collection(self) -> None:
        mock_client = MagicMock()
        mock_client.list_devices.return_value = []

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            script_module, "emit_rest_payload_output"
        ) as emit_output:
            exit_code = script_module._save_device_diagnostics(
                mock_client,
                script_module.Path(temp_dir),
                ["EXT_ADDRESS"],
            )

        self.assertEqual(exit_code, 0)
        mock_client.fetch_device_diagnostics.assert_not_called()
        emit_output.assert_not_called()


if __name__ == "__main__":
    unittest.main()
