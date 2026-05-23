from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import otbr_restapi_util as base_client_module
import otbr_restapi_cli as cli_module


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


class OTBRRawClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = base_client_module.OTBRRestApiClient(
            base_url="http://example.test"
        )

    def test_list_devices_returns_raw_jsonapi_collection_by_default(self) -> None:
        payload = b'{"meta":{"collection":{"total":1}},"data":[{"id":"abc123","type":"threadDevice","attributes":{"hostname":"node-1"}}]}'

        with patch.object(
            base_client_module,
            "urlopen",
            return_value=FakeResponse(payload, "application/vnd.api+json"),
        ):
            result = self.client.list_devices(raw=True)

        self.assertEqual(result["meta"]["collection"]["total"], 1)
        self.assertEqual(result["data"][0]["id"], "abc123")
        self.assertEqual(result["data"][0]["attributes"]["hostname"], "node-1")

    def test_get_node_can_still_flatten_when_explicitly_requested(self) -> None:
        payload = b'{"data":{"id":"abc123","type":"threadBorderRouter","attributes":{"hostname":"node-1"}}}'

        with patch.object(
            base_client_module,
            "urlopen",
            return_value=FakeResponse(payload, "application/vnd.api+json"),
        ):
            result = self.client.get_node(raw=True)

        self.assertEqual(result["data"]["id"], "abc123")
        self.assertEqual(result["data"]["attributes"]["hostname"], "node-1")


class OTBRRawCliTests(unittest.TestCase):
    def test_main_emits_raw_jsonapi_document(self) -> None:
        raw_document = {
            "data": [
                {
                    "id": "abc123",
                    "type": "threadDevice",
                    "attributes": {"hostname": "node-1"},
                }
            ]
        }

        with patch.object(cli_module, "dispatch", return_value=raw_document):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_module.main(["--no-auto-output", "devices", "list"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"data"', stdout.getvalue())
        self.assertIn('"attributes"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
