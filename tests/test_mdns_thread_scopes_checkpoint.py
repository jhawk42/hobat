from __future__ import annotations

import os
import json
import sys
import tempfile
import unittest
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

import mdns_thread_scopes as mdns
import util_network
import util_data


class TestMDNSCheckpointSnapshots(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(dir=".")
        self.data_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _scope_record(scope: str, name: str) -> dict:
        return {
            "record_key": f"{scope}|{name}",
            "scope": scope,
            "name": name,
            "service_info": {"type": scope},
        }

    def _run_mocked_thread_browse(self, argv: list[str], records: list[dict]):
        listener = MagicMock()
        listener.get_records.return_value = records

        with patch.object(
            mdns, "_resolve_optional_omr_ipv6addr_prefix", return_value=None
        ), patch.object(
            mdns, "MDNSDumpListener", return_value=listener
        ) as listener_class, patch.object(
            mdns, "Zeroconf"
        ), patch.object(
            mdns, "ServiceBrowser"
        ) as service_browser, patch.object(
            mdns.threading, "Thread"
        ), patch.object(
            mdns, "save_final_json"
        ) as save_final_json:
            result = mdns.main([*argv, "--datadir", str(self.data_dir)])

        self.assertIsNone(result)
        return listener_class, service_browser, save_final_json

    def test_thread_scope_snapshots_partition_one_browse_and_exclude_trel(self) -> None:
        br_type = "_meshcop._udp.local."
        hap_type = "_hap._udp.local."
        hap_tcp_type = "_hap._tcp.local."
        matter_commissioning_type = "_matterc._udp.local."
        matter_operational_type = "_matter._tcp.local."
        trel_type = "_trel._udp.local."
        records = [
            self._scope_record(br_type, "br.local."),
            self._scope_record(hap_type, "hap.local."),
            self._scope_record(hap_tcp_type, "hap-tcp.local."),
            self._scope_record(matter_commissioning_type, "commissioning.local."),
            self._scope_record(matter_operational_type, "operational.local."),
            self._scope_record(trel_type, "trel.local."),
        ]

        listener_class, service_browser, save_final_json = self._run_mocked_thread_browse(
            [
                "thread",
                "--write-scope-snapshots",
                "--haptcp",
                "--mattertcpsupported",
                "--ext-pan-id",
                "78b9775b001c1cbe",
            ],
            records,
        )

        listener_class.assert_called_once_with(
            include_matter_tcp_supported=True,
            omr_ipv6addr_prefix=None,
            checkpoint_output_file=self.data_dir.resolve() / "td-mdns-scopes-thread.partial.json",
            command="thread",
        )
        browsed_types = [call.args[1] for call in service_browser.call_args_list]
        self.assertEqual(
            browsed_types,
            [br_type, hap_type, matter_commissioning_type, matter_operational_type, hap_tcp_type],
        )
        self.assertNotIn(trel_type, browsed_types)

        snapshots = {
            Path(call.args[1]).name: call.args[0]
            for call in save_final_json.call_args_list
        }
        self.assertEqual(
            set(snapshots),
            {mdns.MDNS_SCOPE_FILENAMES[name] for name in ("thread", "br", "hap", "matter")},
        )
        self.assertEqual(
            [record["name"] for record in snapshots[mdns.MDNS_SCOPE_FILENAMES["thread"]]],
            ["br.local.", "hap.local.", "hap-tcp.local.", "commissioning.local.", "operational.local."],
        )
        self.assertEqual(
            [record["name"] for record in snapshots[mdns.MDNS_SCOPE_FILENAMES["br"]]],
            ["br.local."],
        )
        self.assertEqual(
            [record["name"] for record in snapshots[mdns.MDNS_SCOPE_FILENAMES["hap"]]],
            ["hap.local.", "hap-tcp.local."],
        )
        self.assertEqual(
            [record["name"] for record in snapshots[mdns.MDNS_SCOPE_FILENAMES["matter"]]],
            ["commissioning.local.", "operational.local."],
        )
        self.assertTrue(all(trel_type not in record["scope"] for data in snapshots.values() for record in data))
        for call in save_final_json.call_args_list:
            self.assertEqual(call.kwargs["ext_pan_id"], "78b9775b001c1cbe")
            self.assertIs(call.kwargs["writer"], mdns.save_json_atomic)

    def test_thread_scope_snapshots_write_empty_scope_files(self) -> None:
        _, _, save_final_json = self._run_mocked_thread_browse(
            ["thread", "--write-scope-snapshots"], []
        )

        self.assertEqual(save_final_json.call_count, 4)
        self.assertEqual(
            {Path(call.args[1]).name for call in save_final_json.call_args_list},
            {mdns.MDNS_SCOPE_FILENAMES[name] for name in ("thread", "br", "hap", "matter")},
        )
        self.assertTrue(all(call.args[0] == [] for call in save_final_json.call_args_list))

    def test_scoped_browse_passes_scope_to_checkpoint_events(self) -> None:
        listener_class, _, _ = self._run_mocked_thread_browse(["br"], [])
        self.assertEqual(listener_class.call_args.kwargs["command"], "br")

        listener = mdns.MDNSDumpListener(
            checkpoint_output_file=self.data_dir / "br.partial.json",
            command="br",
        )
        events = []
        with patch.object(mdns, "save_checkpoint_json", return_value=True), patch.object(
            mdns,
            "log_event",
            side_effect=lambda event, **fields: events.append((event, fields)),
        ):
            listener._write_checkpoint_snapshot()
        self.assertEqual(events[0][1]["command"], "br")
        self.assertEqual(events[0][0], "checkpoint")

    def test_browse_summary_uses_elapsed_time_and_dynamic_record_count(self) -> None:
        records = [self._scope_record("_meshcop._udp.local.", f"br-{i}.local.") for i in range(3)]
        events = []
        with patch.object(mdns, "_resolve_optional_omr_ipv6addr_prefix", return_value=None), patch.object(
            mdns, "MDNSDumpListener"
        ) as listener_class, patch.object(mdns, "Zeroconf"), patch.object(
            mdns, "ServiceBrowser"
        ), patch.object(mdns.threading, "Thread"), patch.object(
            mdns, "save_final_json", return_value=True
        ), patch.object(mdns.time, "monotonic", side_effect=(10.0, 12.75)), patch.object(
            mdns, "log_event", side_effect=lambda event, **fields: events.append((event, fields))
        ):
            listener_class.return_value.get_records.return_value = records
            mdns.main(["thread", "--datadir", str(self.data_dir)])

        summary = next(fields for event, fields in events if event == "collector_summary")
        self.assertEqual(summary["elapsed_s"], 2.75)
        self.assertEqual(summary["discovered_records"], 3)
        self.assertNotIn("total", summary)
        self.assertNotIn("targets", summary)

    def test_later_scope_snapshot_failure_reports_each_final_disposition(self) -> None:
        records = [
            self._scope_record("_meshcop._udp.local.", "br.local."),
            self._scope_record("_hap._udp.local.", "hap.local."),
        ]
        events = []
        with patch.object(mdns, "_resolve_optional_omr_ipv6addr_prefix", return_value=None), patch.object(
            mdns, "MDNSDumpListener"
        ) as listener_class, patch.object(mdns, "Zeroconf"), patch.object(
            mdns, "ServiceBrowser"
        ), patch.object(mdns.threading, "Thread"), patch.object(
            mdns, "save_final_json", side_effect=(True, OSError("scope companion failed"))
        ), patch.object(mdns.time, "monotonic", side_effect=(1.0, 2.0)), patch.object(
            mdns, "log_event", side_effect=lambda event, **fields: events.append((event, fields))
        ):
            listener_class.return_value.get_records.return_value = records
            with self.assertRaisesRegex(OSError, "scope companion failed"):
                mdns.main(
                    [
                        "thread",
                        "--write-scope-snapshots",
                        "--datadir",
                        str(self.data_dir),
                    ]
                )

        writes = [fields for event, fields in events if event == "write"]
        self.assertEqual(
            [entry["disposition"] for entry in writes], ["saved", "failed"]
        )
        self.assertEqual(writes[0]["output"], mdns.MDNS_SCOPE_FILENAMES["thread"])
        self.assertEqual(writes[1]["output"], mdns.MDNS_SCOPE_FILENAMES["br"])
        self.assertFalse(any(entry.get("disposition") == "all_saved" for entry in writes))

    def test_checkpoint_reports_actual_skipped_and_failed_results(self) -> None:
        checkpoint = self.data_dir / "empty.partial.json"
        listener = mdns.MDNSDumpListener(checkpoint_output_file=checkpoint)
        events = []
        with patch.object(
            mdns, "log_event", side_effect=lambda event, **fields: events.append((event, fields))
        ):
            listener._write_checkpoint_snapshot()
        self.assertEqual(events[-1][1]["disposition"], "skipped_unusable")
        self.assertEqual(events[-1][0], "checkpoint")

        events.clear()
        with patch.object(
            mdns, "save_checkpoint_json", side_effect=OSError("checkpoint failed")
        ), patch.object(
            mdns, "log_event", side_effect=lambda event, **fields: events.append((event, fields))
        ):
            with self.assertRaisesRegex(OSError, "checkpoint failed"):
                listener._write_checkpoint_snapshot()
        self.assertEqual(events[-1][1]["disposition"], "failed")
        self.assertEqual(events[-1][0], "checkpoint")

    def test_retained_final_result_is_not_logged_as_saved(self) -> None:
        events = []
        with patch.object(mdns, "_resolve_optional_omr_ipv6addr_prefix", return_value=None), patch.object(
            mdns, "MDNSDumpListener"
        ) as listener_class, patch.object(mdns, "Zeroconf"), patch.object(
            mdns, "ServiceBrowser"
        ), patch.object(mdns.threading, "Thread"), patch.object(
            mdns, "save_final_json", return_value=False
        ), patch.object(mdns.time, "monotonic", side_effect=(1.0, 2.0)), patch.object(
            mdns, "log_event", side_effect=lambda event, **fields: events.append((event, fields))
        ), self.assertLogs(level="INFO") as captured:
            listener_class.return_value.get_records.return_value = []
            mdns.main(["thread", "--datadir", str(self.data_dir)])

        write_events = [fields for event, fields in events if event == "write"]
        self.assertEqual(write_events[0]["disposition"], "retained_previous")
        self.assertIn("Retained previous mDNS scope data", "\n".join(captured.output))
        self.assertNotIn("Saved 0 mDNS record(s)", "\n".join(captured.output))

    def test_scope_companion_failure_is_reported_as_failed_after_primary_write(self) -> None:
        records = [self._scope_record("_meshcop._udp.local.", "br.local.")]
        events = []
        with patch.object(mdns, "_resolve_optional_omr_ipv6addr_prefix", return_value=None), patch.object(
            mdns, "MDNSDumpListener"
        ) as listener_class, patch.object(mdns, "Zeroconf"), patch.object(
            mdns, "ServiceBrowser"
        ), patch.object(mdns.threading, "Thread"), patch.object(
            mdns.time, "monotonic", side_effect=(1.0, 2.0)
        ), patch.object(
            mdns, "log_event", side_effect=lambda event, **fields: events.append((event, fields))
        ), patch.object(
            util_data, "write_network_scope", side_effect=OSError("companion failed")
        ):
            listener_class.return_value.get_records.return_value = records
            with self.assertRaisesRegex(OSError, "companion failed"):
                mdns.main(["thread", "--datadir", str(self.data_dir)])

        output = self.data_dir / mdns.MDNS_SCOPE_FILENAMES["thread"]
        self.assertTrue(output.exists())
        self.assertEqual(
            [fields["disposition"] for event, fields in events if event == "write"],
            ["failed"],
        )

    def test_thread_browse_resolves_relative_and_absolute_data_dirs(self) -> None:
        absolute_dir = self.data_dir.resolve()
        relative_dir = Path(os.path.relpath(absolute_dir))
        for data_dir in (relative_dir, absolute_dir):
            with self.subTest(data_dir=data_dir), patch.object(self, "data_dir", data_dir):
                listener_class, _, save_final_json = self._run_mocked_thread_browse(
                    ["thread"], []
                )

                self.assertEqual(
                    listener_class.call_args.kwargs["checkpoint_output_file"],
                    absolute_dir / "td-mdns-scopes-thread.partial.json",
                )
                save_final_json.assert_called_once()
                self.assertEqual(
                    Path(save_final_json.call_args.args[1]),
                    absolute_dir / "td-mdns-scopes-thread.json",
                )

    def test_matter_tcp_support_filter_is_preserved(self) -> None:
        info = SimpleNamespace(properties={b"T": b"1"})

        self.assertTrue(
            mdns.MDNSDumpListener()._is_matter_tcp_excluded(
                "_matter._tcp.local.", info
            )
        )
        self.assertFalse(
            mdns.MDNSDumpListener(include_matter_tcp_supported=True)._is_matter_tcp_excluded(
                "_matter._tcp.local.", info
            )
        )

    def test_add_service_writes_checkpoint_snapshot_immediately(self) -> None:
        checkpoint_path = self.data_dir / "td-mdns-scopes-thread.partial.json"
        listener = mdns.MDNSDumpListener(checkpoint_output_file=checkpoint_path)

        info = SimpleNamespace(
            addresses=[b"\x7f\x00\x00\x01"],
            properties={b"xa": bytes.fromhex("0011223344556677"), b"xp": bytes.fromhex("78b9775b001c1cbe")},
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
        self.assertEqual(written_payload[0]["extPanId"], "78b9775b001c1cbe")

    def test_address_failures_preserve_evidence_and_warn_once_per_category(self):
        checkpoint = self.data_dir / "checkpoint.json"
        listener = mdns.MDNSDumpListener(
            omr_ipv6addr_prefix="fd00:",
            checkpoint_output_file=checkpoint,
        )
        parsed = ["fd00::1", "192.0.2.1"]
        parser = MagicMock(side_effect=ValueError("secret-address-and-service"))
        info = SimpleNamespace(
            addresses=[b"\x7f\x00\x00\x01"], parsed_addresses=parser,
            properties={b"xa": bytes.fromhex("0011223344556677")},
            port=1234,
        )
        zc = MagicMock()
        zc.get_service_info.return_value = info

        def assert_snapshot(expected, event):
            record = listener.get_records()[0]
            self.assertEqual(record["event"], event)
            self.assertIs(record["service_info"]["addresses_parsed"], expected)
            self.assertEqual(record["service_info"]["addresses_raw_hex"], ["7f000001"])
            self.assertEqual(record["scope"], "_meshcop._udp.local.")
            self.assertEqual(record["extAddress"], "0011223344556677")
            self.assertNotIn("omrIpv6Address", record)
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))[0]
            self.assertEqual(saved["serviceInfo"]["addressesParsed"], expected)
            self.assertEqual(saved["serviceInfo"]["addressesRawHex"], ["7f000001"])
            self.assertEqual(saved["event"], event)

        with patch.object(mdns, "print_meshcop_service_info"), patch.object(
            mdns.util_network, "fetch_omr_prefix"
        ) as fetch_prefix, patch.object(
            mdns.util_network, "find_omr_address_in_list",
            side_effect=RuntimeError("secret-address-and-service"),
        ) as find_omr, self.assertLogs(level="WARNING") as captured:
            listener.add_service(zc, "_meshcop._udp.local.", "private.local.")
            empty = listener.get_records()[0]["service_info"]["addresses_parsed"]
            assert_snapshot(empty, "add")
            self.assertEqual(empty, [])
            listener.update_service(zc, "_meshcop._udp.local.", "private.local.")
            empty = listener.get_records()[0]["service_info"]["addresses_parsed"]
            assert_snapshot(empty, "update")
            self.assertEqual(empty, [])
            self.assertEqual(find_omr.call_count, 0)
            parser.side_effect = None
            parser.return_value = parsed
            listener.add_service(zc, "_meshcop._udp.local.", "private.local.")
            assert_snapshot(parsed, "add")
            listener.update_service(zc, "_meshcop._udp.local.", "private.local.")
            assert_snapshot(parsed, "update")
            fetch_prefix.assert_not_called()
        self.assertEqual(len(captured.records), 2)
        messages = "\n".join(captured.output)
        self.assertIn("address-parse", messages)
        self.assertIn("ValueError", messages)
        self.assertIn("omr-enrichment", messages)
        self.assertIn("RuntimeError", messages)
        self.assertNotIn("secret-address", messages)
        self.assertNotIn("private.local", messages)
        self.assertNotIn("fd00", messages)

    def test_address_enrichment_success_and_no_prefix_are_quiet(self):
        parsed = ["fd00::1"]
        info = SimpleNamespace(
            addresses=[b"\x7f\x00\x00\x01"], properties={},
            parsed_addresses=lambda: parsed,
        )
        for prefix in (None, "fd00:"):
            with self.subTest(prefix=prefix):
                listener = mdns.MDNSDumpListener(omr_ipv6addr_prefix=prefix)
                with patch.object(
                    mdns.util_network, "find_omr_address_in_list", return_value="fd00::1"
                ) as find_omr, patch.object(
                    mdns.util_network, "fetch_omr_prefix"
                ) as fetch_prefix, self.assertNoLogs(level="WARNING"):
                    record = listener._build_record_from_service_info(
                        "_meshcop._udp.local.", "test.local.", info, "add"
                    )
                self.assertIs(record["service_info"]["addresses_parsed"], parsed)
                if prefix:
                    self.assertEqual(record["omrIpv6Address"], "fd00::1")
                    find_omr.assert_called_once_with(parsed, prefix)
                else:
                    self.assertNotIn("omrIpv6Address", record)
                    find_omr.assert_not_called()
                fetch_prefix.assert_not_called()

    def test_post_parse_enrichment_failure_retains_exact_address_list(self):
        parsed = ["fd00::1", "192.0.2.1"]
        info = SimpleNamespace(
            addresses=[b"\x7f\x00\x00\x01"], properties={},
            parsed_addresses=lambda: parsed,
        )
        listener = mdns.MDNSDumpListener(omr_ipv6addr_prefix="fd00:")
        with patch.object(
            mdns.util_network, "find_omr_address_in_list",
            side_effect=ValueError("private-address"),
        ):
            record = listener._build_record_from_service_info(
                "_meshcop._udp.local.", "test.local.", info, "add"
            )
        self.assertIs(record["service_info"]["addresses_parsed"], parsed)
        self.assertNotIn("omrIpv6Address", record)

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
            checkpoint_output_file=self.data_dir.resolve() / "td-mdns-scopes-thread.partial.json",
            command="thread",
        )
        save_final_json.assert_called_once()


@pytest.mark.parametrize("origin", ["monitor", "callback", "shutdown"])
def test_collection_failure_releases_waiter_and_preserves_all_finals(tmp_path, monkeypatch, origin):
    listener = mdns.MDNSDumpListener(checkpoint_output_file=tmp_path / "checkpoint.json")
    listener._upsert_record({
        "record_key": "test", "scope": "_meshcop._udp.local.", "name": "test",
    })
    originals = {}
    for filename in mdns.MDNS_SCOPE_FILENAMES.values():
        for path in (tmp_path / filename, util_data.network_scope_path(tmp_path / filename)):
            path.write_bytes(b"previous")
            originals[path] = path.read_bytes()
    real_wait = listener.wait_for_idle
    monkeypatch.setattr(listener, "wait_for_idle", lambda **kwargs: real_wait(idle_timeout=0, poll=0.001))
    completed = []
    event_wait = listener.idle_done.wait
    monkeypatch.setattr(listener.idle_done, "wait", lambda: completed.append(event_wait(1)))
    discovery = MagicMock()
    if origin == "shutdown":
        discovery.close.side_effect = OSError("private close detail")
    else:
        monkeypatch.setattr(mdns, "save_checkpoint_json", MagicMock(side_effect=OSError("private write detail")))
    if origin == "callback":
        monkeypatch.setattr(mdns, "ServiceBrowser", lambda *args: listener._write_checkpoint_snapshot())
    else:
        monkeypatch.setattr(mdns, "ServiceBrowser", MagicMock())
    threads = []
    real_thread = threading.Thread

    def monitor_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(mdns.threading, "Thread", monitor_thread)
    monkeypatch.setattr(mdns, "Zeroconf", lambda: discovery)
    monkeypatch.setattr(mdns, "MDNSDumpListener", lambda **kwargs: listener)
    monkeypatch.setattr(mdns, "_resolve_optional_omr_ipv6addr_prefix", lambda: None)
    monkeypatch.setattr(mdns, "save_final_json", lambda *a, **k: pytest.fail("unexpected final write"))
    assert mdns.main(["thread", "--write-scope-snapshots", "--datadir", str(tmp_path)]) == 3
    assert completed == ([] if origin == "callback" else [True])
    assert all(not thread.is_alive() for thread in threads)
    discovery.close.assert_called_once()
    assert {path: path.read_bytes() for path in originals} == originals


def test_manual_stop_without_failure_still_publishes_collected_records(tmp_path, monkeypatch):
    listener = mdns.MDNSDumpListener()
    monkeypatch.setattr(listener.idle_done, "wait", MagicMock(side_effect=KeyboardInterrupt))
    discovery = MagicMock()
    monkeypatch.setattr(mdns, "Zeroconf", lambda: discovery)
    monkeypatch.setattr(mdns, "MDNSDumpListener", lambda **kwargs: listener)
    monkeypatch.setattr(mdns, "ServiceBrowser", MagicMock())
    monkeypatch.setattr(mdns.threading, "Thread", MagicMock())
    monkeypatch.setattr(mdns, "_resolve_optional_omr_ipv6addr_prefix", lambda: None)
    save = MagicMock(return_value=True)
    monkeypatch.setattr(mdns, "save_final_json", save)
    assert mdns.main(["thread", "--datadir", str(tmp_path)]) is None
    save.assert_called_once()
    discovery.close.assert_called_once()


def test_normal_idle_monitor_completes_and_can_be_joined():
    listener = mdns.MDNSDumpListener()
    thread = threading.Thread(target=listener.wait_for_idle, kwargs={"idle_timeout": 0, "poll": 0.001})
    thread.start()
    try:
        assert listener.idle_done.wait(1)
    finally:
        listener.stop()
        thread.join(1)
    assert not thread.is_alive()
    listener.raise_if_failed()


def test_mdns_enrichment_uses_one_full_cidr_query(monkeypatch):
    fetch = MagicMock(return_value="fda5:494c:9a12:0::/64")
    monkeypatch.setattr(util_network, "fetch_omr_prefix", fetch)
    prefix = mdns._resolve_optional_omr_ipv6addr_prefix()
    listener = mdns.MDNSDumpListener(omr_ipv6addr_prefix=prefix)
    info = SimpleNamespace(properties={}, addresses=[],
                           parsed_addresses=lambda: ["fda5:494c:9a12::1234"])
    record = listener._build_record_from_service_info("_hap._udp.local.", "test", info, "add")
    assert record["omrIpv6Address"] == "fda5:494c:9a12::1234"
    fetch.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()