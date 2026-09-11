from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import mdns_thread_scopes as mdns
import util_network


class TestMDNSCheckpointSnapshots(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_add_service_writes_checkpoint_snapshot_immediately(self) -> None:
        checkpoint_path = self.data_dir / "td-mdns-scopes-thread.partial.json"
        listener = mdns.MDNSDumpListener(checkpoint_output_file=checkpoint_path)

        info = SimpleNamespace(
            addresses=[b"\x7f\x00\x00\x01"],
            properties={b"xa": bytes.fromhex("0011223344556677")},
            parsed_addresses=lambda: ["fd00::1"],
            name="test.local.",
            type="_meshcop._udp.local.",
            server="test.local.",
            port=1234,
            priority=0,
            weight=0,
            interface_index=0,
            host_ttl=120,
            other_ttl=120,
            key="test",
            text=None,
        )

        zc = MagicMock()
        zc.get_service_info.return_value = info

        with patch.object(mdns, "print_meshcop_service_info") as print_mock, patch.object(
            mdns, "save_json_atomic"
        ) as save_mock:
            listener.add_service(zc, "_meshcop._udp.local.", "test.local.")

        print_mock.assert_called_once()
        save_mock.assert_called_once()

        written_payload, written_path = save_mock.call_args.args[:2]
        self.assertEqual(written_path, checkpoint_path)
        self.assertIsInstance(written_payload, list)
        self.assertEqual(len(written_payload), 1)
        self.assertEqual(written_payload[0]["recordKey"], "_meshcop._udp.local.|test.local.")
        self.assertEqual(written_payload[0]["name"], "test.local.")
        self.assertEqual(written_payload[0]["event"], "add")

    def test_add_service_handles_packed_address_variants(self) -> None:
        address_cases = {
            "ipv4": [b"\x7f\x00\x00\x01"],
            "ipv6": [bytes.fromhex("fd001234000000000000000000000001")],
            "empty": [],
            "malformed": [b"\x01\x02"],
        }

        for case_name, addresses in address_cases.items():
            with self.subTest(case_name=case_name):
                checkpoint_path = self.data_dir / f"{case_name}.json"
                listener = mdns.MDNSDumpListener(
                    checkpoint_output_file=checkpoint_path)
                info = SimpleNamespace(
                    addresses=addresses,
                    properties={b"xa": bytes.fromhex("0011223344556677")},
                    parsed_addresses=lambda: ["fd00::1"],
                    name="test.local.",
                    type="_meshcop._udp.local.",
                    server="test.local.",
                    port=1234,
                    priority=0,
                    weight=0,
                    interface_index=0,
                    host_ttl=120,
                    other_ttl=120,
                    key="test",
                    text=None,
                )
                zc = MagicMock()
                zc.get_service_info.return_value = info

                with patch.object(mdns, "save_json_atomic") as save_mock:
                    listener.add_service(zc, "_meshcop._udp.local.", "test.local.")

                self.assertEqual(save_mock.call_count, 1)
                self.assertEqual(
                    save_mock.call_args.args[0][0]["recordKey"],
                    "_meshcop._udp.local.|test.local.",
                )

    def test_optional_omr_prefix_failure_does_not_block_mdn_browse(self) -> None:
        listener = MagicMock()
        listener.get_records.return_value = []
        thread = MagicMock()

        with patch.object(
            mdns.util_network,
            "fetch_omr_prefix",
            side_effect=util_network.PrefixFetchError("otbr unavailable"),
        ), patch.object(mdns, "MDNSDumpListener", return_value=listener) as listener_class, patch.object(
            mdns, "Zeroconf"
        ), patch.object(mdns, "ServiceBrowser"), patch.object(
            mdns.threading, "Thread", return_value=thread
        ), patch.object(mdns, "save_final_json") as save_final_json:
            self.assertIsNone(mdns._resolve_optional_omr_ipv6addr_prefix())
            self.assertIsNone(mdns.main(["thread", "--datadir", str(self.data_dir)]))

        listener_class.assert_called_once_with(
            include_matter_tcp_supported=False,
            omr_ipv6addr_prefix=None,
            checkpoint_output_file=self.data_dir / "td-mdns-scopes-thread.partial.json",
        )
        save_final_json.assert_called_once()


if __name__ == "__main__":
    unittest.main()