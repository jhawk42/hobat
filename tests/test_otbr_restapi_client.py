from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from urllib.error import HTTPError

import otbr_restapi_util as client_module
import otbr_restapi_cli as cli_module
import td_cli


class FakeHeaders(dict):
    def __init__(self, content_type: str) -> None:
        super().__init__()
        self["content-type"] = content_type

    def get(self, key: str, default: str | None = None) -> str | None:
        return super().get(key.lower(), default)

    def __getitem__(self, key):
        if isinstance(key, str):
            return super().__getitem__(key.lower())
        return super().__getitem__(key)


class FakeResponse:
    def __init__(self, payload: bytes, content_type: str) -> None:
        self._payload = payload
        self.headers = FakeHeaders(content_type)
        self.status = 200

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class OTBRClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = client_module.OTBRRestApiClient(base_url="http://example.test")

    def test_list_devices_flattens_jsonapi_collection_with_meta(self) -> None:
        payload = b'{"meta":{"collection":{"total":1}},"data":[{"id":"abc123","type":"threadDevice","attributes":{"hostname":"node-1","role":"leader"}}]}'

        with patch.object(
            client_module,
            "urlopen",
            return_value=FakeResponse(payload, "application/vnd.api+json"),
        ):
            result = self.client.list_devices(with_meta=True)

        self.assertEqual(
            result,
            {
                "items": [
                    {
                        "id": "abc123",
                        "type": "threadDevice",
                        "hostname": "node-1",
                        "role": "leader",
                    }
                ],
                "meta": {"collection": {"total": 1}},
            },
        )

    def test_http_error_parses_jsonapi_error_document(self) -> None:
        error_payload = io.BytesIO(
            b'{"errors":[{"title":"Not Found","status":404,"detail":"No device matches the requested ID."}]}'
        )
        error = HTTPError(
            url="http://example.test/api/devices/badid",
            code=404,
            msg="Not Found",
            hdrs={"Content-Type": "application/vnd.api+json"},
            fp=error_payload,
        )

        with patch.object(client_module, "urlopen", side_effect=error):
            with self.assertRaises(client_module.OTBRHTTPError) as ctx:
                self.client.get_device("badid")

        exc = ctx.exception
        self.assertEqual(exc.status_code, 404)
        self.assertEqual(exc.errors[0].title, "Not Found")
        self.assertEqual(exc.errors[0].detail, "No device matches the requested ID.")

    def test_empty_task_type_list_raises_usage_error(self) -> None:
        with self.assertRaises(client_module.OTBRUsageError):
            self.client.enqueue_get_network_diagnostic_task(
                destination="abcd1234abcd1234", types=[]
            )

    def test_network_diagnostic_task_uses_otbr_wire_type_names(self) -> None:
        payload = b'{"data":[{"id":"action-1","type":"getNetworkDiagnosticTask","attributes":{}}]}'

        with patch.object(
            client_module,
            "urlopen",
            return_value=FakeResponse(payload, "application/vnd.api+json"),
        ) as urlopen:
            self.client.enqueue_get_network_diagnostic_task(
                destination="abcd1234abcd1234",
                destination_type="extended",
                types=["extAddress", "eui", "threadVersion", 34],
            )

        request_body = json.loads(urlopen.call_args.args[0].data)
        attributes = request_body["data"][0]["attributes"]
        self.assertEqual(
            attributes["types"], ["extAddress", "eui", "threadVersion", "mleCounters"]
        )

    def test_child_rloc_diagnostic_task_posts_six_char_rloc_destination(self) -> None:
        payload = b'{"data":[{"id":"action-1","type":"getNetworkDiagnosticTask","attributes":{}}]}'

        with patch.object(
            client_module,
            "urlopen",
            return_value=FakeResponse(payload, "application/vnd.api+json"),
        ) as urlopen:
            self.client.enqueue_get_network_diagnostic_task(
                destination="00382a",
                destination_type="rloc",
                types=["extAddress", "rloc16"],
                timeout=30,
            )

        attributes = json.loads(urlopen.call_args.args[0].data)["data"][0]["attributes"]
        self.assertEqual(attributes["destination"], "00382a")
        self.assertEqual(attributes["destinationType"], "rloc")
        self.assertEqual(attributes["types"], ["extAddress", "rloc16"])
        with self.assertRaises(client_module.OTBRUsageError):
            self.client.enqueue_get_network_diagnostic_task(
                destination="382a", destination_type="rloc", types=["extAddress"]
            )

    def test_legacy_network_diagnostic_type_names_remain_input_only(self) -> None:
        payload = b'{"data":[{"id":"action-1","type":"getNetworkDiagnosticTask","attributes":{}}]}'

        with patch.object(
            client_module,
            "urlopen",
            return_value=FakeResponse(payload, "application/vnd.api+json"),
        ) as urlopen:
            self.client.enqueue_get_network_diagnostic_task(
                destination="abcd1234abcd1234",
                destination_type="extended",
                types=["eui64", "version"],
            )

        request_body = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(
            request_body["data"][0]["attributes"]["types"],
            ["eui", "threadVersion"],
        )

    def test_reset_counter_task_uses_otbr_wire_type_names(self) -> None:
        payload = b'{"data":[{"id":"action-1","type":"resetNetworkDiagCounterTask","attributes":{}}]}'

        with patch.object(
            client_module,
            "urlopen",
            return_value=FakeResponse(payload, "application/vnd.api+json"),
        ) as urlopen:
            self.client.enqueue_reset_network_diag_counter_task(types=[9, 34])

        request_body = json.loads(urlopen.call_args.args[0].data)
        attributes = request_body["data"][0]["attributes"]
        self.assertEqual(attributes["types"], ["macCounters", "mleCounters"])

    def test_invalid_destination_type_raises_usage_error(self) -> None:
        with self.assertRaisesRegex(
            client_module.OTBRUsageError, "destination_type must be one of"
        ):
            self.client.enqueue_get_network_diagnostic_task(
                destination="abcd1234abcd1234",
                destination_type="invalid",
                types=["extAddress"],
            )


class OTBRCliTests(unittest.TestCase):
    def test_devices_clear_requires_yes_before_building_client(self) -> None:
        for entrypoint, argv in (
            (cli_module.main, ["devices", "clear"]),
            (td_cli.main, ["otbr-restapi", "devices", "clear"]),
        ):
            with self.subTest(argv=argv), patch.object(cli_module, "build_client") as build_client:
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    exit_code = entrypoint(argv)
                self.assertEqual(exit_code, cli_module.EXIT_USAGE)
                self.assertIn("--yes", stderr.getvalue())
                build_client.assert_not_called()

    def test_devices_clear_deletes_remote_collection_without_changing_caches(self) -> None:
        for entrypoint, argv in (
            (cli_module.main, ["--base-url", "http://example.test", "devices", "clear", "--yes"]),
            (td_cli.main, ["otbr-restapi", "--base-url", "http://example.test",
                           "devices", "clear", "--yes"]),
        ):
            response = FakeResponse(b"", "application/vnd.api+json")
            response.status = 204
            with self.subTest(argv=argv), patch.object(
                client_module, "urlopen", return_value=response
            ) as urlopen, patch.object(
                client_module, "emit_rest_payload_output"
            ) as write_payload, redirect_stdout(io.StringIO()) as stdout:
                exit_code = entrypoint(argv)
                self.assertEqual(exit_code, cli_module.EXIT_SUCCESS)
                urlopen.assert_called_once()
                request = urlopen.call_args.args[0]
                self.assertEqual(request.get_method(), "DELETE")
                self.assertEqual(request.full_url, "http://example.test/api/devices")
                self.assertIn('"cleared": true', stdout.getvalue())
                write_payload.assert_not_called()

    def test_devices_clear_reports_http_failure_without_success(self) -> None:
        error = HTTPError(
            url="http://example.test/api/devices", code=403, msg="Forbidden",
            hdrs={"Content-Type": "application/vnd.api+json"},
            fp=io.BytesIO(b'{"errors":[{"title":"Forbidden","status":403}]}'),
        )
        with patch.object(client_module, "urlopen", side_effect=error) as urlopen:
            with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
                exit_code = cli_module.main(
                    ["--base-url", "http://example.test", "devices", "clear", "--yes"]
                )
        self.assertEqual(exit_code, cli_module.EXIT_HTTP)
        self.assertIn('"status": 403', stderr.getvalue())
        self.assertNotIn('"cleared": true', stdout.getvalue())
        urlopen.assert_called_once()

    def test_emit_output_keeps_plain_text_unquoted(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            cli_module.emit_output("fd00::/64", None)
        self.assertEqual(stdout.getvalue(), "fd00::/64\n")

    def test_main_returns_usage_exit_code_for_invalid_dataset_json(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = cli_module.main(
                ["node", "dataset", "active", "set", "--json", "{"]
            )

        self.assertEqual(exit_code, cli_module.EXIT_USAGE)
        self.assertIn('"type": "usage"', stderr.getvalue())

    def test_main_returns_http_exit_code_for_http_error(self) -> None:
        error = client_module.OTBRHTTPError(
            status_code=404,
            reason="Not Found",
            url="http://example.test/api/actions/missing",
            errors=[
                client_module.OTBRErrorDetail(
                    title="Not Found", status=404, detail="Missing action"
                )
            ],
        )

        with patch.object(cli_module, "dispatch", side_effect=error):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = cli_module.main(["actions", "list"])

        self.assertEqual(exit_code, cli_module.EXIT_HTTP)
        self.assertIn('"status": 404', stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
