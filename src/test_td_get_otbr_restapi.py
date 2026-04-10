from __future__ import annotations

import unittest
from unittest.mock import patch

import td_otbr_download as script_module


class TdGetOtbrRestApiTests(unittest.TestCase):
    def test_build_base_url_prefers_explicit_base_url(self) -> None:
        self.assertEqual(
            script_module.build_base_url("127.0.0.1", 8081, "http://example.test:1234/"),
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
        with patch.object(script_module, "restapi_downloads", return_value=0) as restapi_downloads:
            exit_code = script_module.main(
                [
                    "--host",
                    "192.0.2.1",
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
        restapi_downloads.assert_called_once_with(
            base_url="http://192.0.2.1:18081",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer token",
            },
            timeout=15,
        )


if __name__ == "__main__":
    unittest.main()