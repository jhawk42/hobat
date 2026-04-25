from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from urllib.error import HTTPError

import otbr_restapi_client as client_module
import otbr_restapi_client_cli as cli_module


class FakeHeaders:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get(self, key: str, default: str | None = None) -> str | None:
        if key.lower() == "content-type":
            return self._content_type
        return default


class FakeResponse:
    def __init__(self, payload: bytes, content_type: str) -> None:
        self._payload = payload
        self.headers = FakeHeaders(content_type)

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


class OTBRCliTests(unittest.TestCase):
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
