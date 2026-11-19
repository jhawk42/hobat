from __future__ import annotations

import json
import fcntl
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import device_label as label_map
import td_cli
real_timestamp = label_map._timestamp
from device_label import (
    ExtaddrNotFoundError,
    main,
    merge_extaddr_files,
    normalize_valid_device_label,
    normalize_valid_extaddr,
    read_device_label,
    upsert_device_label,
)


class MergeExtaddrFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        timestamp = patch.object(label_map, "_timestamp", return_value="2026-11-18T05:19:45Z")
        timestamp.start()
        self.addCleanup(timestamp.stop)

    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _read_json(self, path: Path) -> object:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_upsert_creates_missing_static_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            static_path = Path(temp_dir) / "td-static-extaddr-device-label.json"

            result = upsert_device_label(
                static_path,
                "4E866CE96501B9ED",
                "  Office Sensor  ",
            )

            self.assertEqual(
                {key: value for key, value in result.items() if key != "lastUpdated"},
                {
                    "extAddress": "4e866ce96501b9ed",
                    "deviceLabel": "Office Sensor",
                    "operation": "inserted",
                },
            )
            self.assertEqual(
                self._read_json(static_path),
                [
                    {
                        "extAddress": "4e866ce96501b9ed",
                        "deviceLabel": "Office Sensor",
                        "lastUpdated": "2026-11-18T05:19:45Z",
                    }
                ],
            )

    def test_read_normalizes_extaddr_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            static_path = Path(temp_dir) / "td-static-extaddr-device-label.json"
            self._write_json(
                static_path,
                [{"extaddr": "4e866ce96501b9ed", "device_label": "Office"}],
            )
            original_text = static_path.read_text(encoding="utf-8")

            result = read_device_label(static_path, "4E866CE96501B9ED")

            self.assertEqual(
                result,
                {
                    "extAddress": "4e866ce96501b9ed",
                    "deviceLabel": "Office",
                },
            )
            self.assertEqual(static_path.read_text(encoding="utf-8"), original_text)

    def test_read_unknown_extaddr_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            static_path = Path(temp_dir) / "td-static-extaddr-device-label.json"
            self._write_json(static_path, [])

            with self.assertRaises(ExtaddrNotFoundError):
                read_device_label(static_path, "4e866ce96501b9ed")

    def test_upsert_updates_one_record_and_preserves_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            static_path = Path(temp_dir) / "td-static-extaddr-device-label.json"
            self._write_json(
                static_path,
                [
                    {
                        "extaddr": "ffffffffffffffff",
                        "device_label": "Other",
                        "room": "Kitchen",
                    },
                    {
                        "extaddr": "4e866ce96501b9ed",
                        "device_label": "Old",
                        "source": "manual",
                    },
                ],
            )

            result = upsert_device_label(
                static_path,
                "4e866ce96501b9ed",
                "Office Sensor",
            )

            self.assertEqual(result["operation"], "updated")
            self.assertEqual(
                self._read_json(static_path),
                [
                    {
                        "extaddr": "4e866ce96501b9ed",
                        "device_label": "Office Sensor",
                        "source": "manual",
                        "lastUpdated": "2026-11-18T05:19:45Z",
                    },
                    {
                        "extaddr": "ffffffffffffffff",
                        "device_label": "Other",
                        "room": "Kitchen",
                    },
                ],
            )

    def test_upsert_rejects_duplicate_normalized_extaddrs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            static_path = Path(temp_dir) / "td-static-extaddr-device-label.json"
            self._write_json(
                static_path,
                [
                    {"extaddr": "4e866ce96501b9ed", "device_label": "One"},
                    {"extAddress": "4E866CE96501B9ED", "deviceLabel": "Two"},
                ],
            )
            original_text = static_path.read_text(encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicate extAddress"):
                upsert_device_label(static_path, "4e866ce96501b9ed", "New")
            self.assertEqual(static_path.read_text(encoding="utf-8"), original_text)

    def test_extaddr_validation_rejects_non_hex_and_wrong_lengths(self) -> None:
        for value in ("4e866ce96501b9e", "4e866ce96501b9ed0", "4e866ce96501b9eg"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_valid_extaddr(value)

    def test_device_label_validation_contract(self) -> None:
        self.assertEqual(normalize_valid_device_label("  Büro Sensor  "), "Büro Sensor")
        self.assertEqual(normalize_valid_device_label("x" * 128), "x" * 128)
        for value in ("", "   ", "line\nbreak", "x" * 129):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_valid_device_label(value)

    def test_main_read_and_update_emit_machine_readable_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = StringIO()
            with redirect_stdout(stdout):
                update_rc = main(
                    [
                        "--datadir",
                        temp_dir,
                        "--update-extaddr",
                        "4E866CE96501B9ED",
                        "--device-label",
                        "Office Sensor",
                    ]
                )
            self.assertEqual(update_rc, 0)
            self.assertEqual(json.loads(stdout.getvalue())["operation"], "inserted")

            stdout = StringIO()
            with redirect_stdout(stdout):
                read_rc = main(
                    [
                        "--datadir",
                        temp_dir,
                        "--read-extaddr",
                        "4e866ce96501b9ed",
                    ]
                )
            self.assertEqual(read_rc, 0)
            read_result = json.loads(stdout.getvalue())
            self.assertIn("lastUpdated", read_result)
            self.assertEqual(
                {key: value for key, value in read_result.items() if key != "lastUpdated"},
                {
                    "deviceLabel": "Office Sensor",
                    "extAddress": "4e866ce96501b9ed",
                },
            )

    def test_main_returns_distinct_code_for_unknown_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            static_path = Path(temp_dir) / "td-static-extaddr-device-label.json"
            self._write_json(static_path, [])
            stderr = StringIO()
            with redirect_stderr(stderr):
                rc = main(
                    [
                        "--datadir",
                        temp_dir,
                        "--read-extaddr",
                        "4e866ce96501b9ed",
                    ]
                )
            self.assertEqual(rc, 6)
            self.assertIn("extAddress not found", stderr.getvalue())

    def test_main_returns_missing_map_code_for_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stderr = StringIO()
            with redirect_stderr(stderr):
                rc = main(
                    [
                        "--datadir",
                        temp_dir,
                        "--read-extaddr",
                        "4e866ce96501b9ed",
                    ]
                )
            self.assertEqual(rc, 4)
            self.assertIn("Static extAddress map not found", stderr.getvalue())

    def test_main_returns_invalid_payload_code_for_malformed_maps(self) -> None:
        invalid_payloads = ("not json", json.dumps({"extaddr": "value"}))
        for payload in invalid_payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temp_dir:
                static_path = Path(temp_dir) / "td-static-extaddr-device-label.json"
                static_path.write_text(payload, encoding="utf-8")
                stderr = StringIO()
                with redirect_stderr(stderr):
                    rc = main(
                        [
                            "--datadir",
                            temp_dir,
                            "--read-extaddr",
                            "4e866ce96501b9ed",
                        ]
                    )
                self.assertEqual(rc, 5)
                self.assertIn("Invalid static extAddress map", stderr.getvalue())

    def test_main_rejects_incompatible_single_record_arguments(self) -> None:
        invalid_argv = (
            ["--read-extaddr", "4e866ce96501b9ed", "--device-label", "Office"],
            ["--update-extaddr", "4e866ce96501b9ed"],
            [
                "--read-extaddr",
                "4e866ce96501b9ed",
                "--merge-mdns-br",
            ],
        )
        for argv in invalid_argv:
            with self.subTest(argv=argv), redirect_stderr(StringIO()):
                with self.assertRaisesRegex(SystemExit, "2"):
                    main(argv)

    def test_adds_missing_extaddr_using_name_when_device_label_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            static_path = temp_path / "td-static-extaddr-device-label.json"
            topology_path = temp_path / "topology.json"

            self._write_json(
                static_path,
                [{"extaddr": "1000000000000000", "device_label": "Known Device"}],
            )
            self._write_json(
                topology_path,
                [
                    {
                        "extaddr": "2000000000000000",
                        "name": "Dining Room HomePod._meshcop._udp.local.",
                    }
                ],
            )

            num_added, added_entries, num_overridden, overridden_entries = merge_extaddr_files(
                static_path,
                topology_path,
            )

            self.assertEqual(num_added, 1)
            self.assertEqual(num_overridden, 0)
            self.assertEqual(overridden_entries, [])
            self.assertEqual(
                added_entries,
                [
                    {
                        "extaddr": "2000000000000000",
                        "device_label": "Dining Room HomePod._meshcop._udp.local.",
                    }
                ],
            )

            updated_static = self._read_json(static_path)
            self.assertIn(
                {
                    "extAddress": "2000000000000000",
                    "deviceLabel": "Dining Room HomePod._meshcop._udp.local.",
                    "lastUpdated": "2026-11-18T05:19:45Z",
                },
                updated_static,
            )

    def test_main_merge_mdns_br_creates_map_from_ext_address_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            self._write_json(
                data_dir / "td-mdns-scopes-br.json",
                [
                    {
                        "scope": "_meshcop._udp.local.",
                        "extAddress": "8AE5E52D91217AEC",
                        "name": "Dining Room HomePod._meshcop._udp.local.",
                    }
                ],
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                rc = main(["--datadir", temp_dir, "--merge-mdns-br", "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertIn("8ae5e52d91217aec: Dining Room HomePod", stdout.getvalue())
            self.assertNotIn("._meshcop.", stdout.getvalue())
            self.assertEqual(sorted(path.name for path in data_dir.iterdir()), ["td-mdns-scopes-br.json"])

            stdout = StringIO()
            with redirect_stdout(stdout):
                rc = main(["--datadir", temp_dir, "--merge-mdns-br"])

            self.assertEqual(rc, 0)
            self.assertIn("Added 1 new extaddr entry", stdout.getvalue())
            self.assertEqual(
                self._read_json(data_dir / "td-static-extaddr-device-label.json"),
                [
                    {
                        "extAddress": "8ae5e52d91217aec",
                        "deviceLabel": "Dining Room HomePod",
                        "lastUpdated": "2026-11-18T05:19:45Z",
                    }
                ],
            )

    def test_merge_uses_camel_case_device_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            static_path = temp_path / "td-static-extaddr-device-label.json"
            topology_path = temp_path / "topology.json"
            self._write_json(static_path, [])
            self._write_json(
                topology_path,
                [{"extAddress": "2000000000000000", "deviceLabel": "Unknown-0x0800"}],
            )

            num_added, added_entries, _, _ = merge_extaddr_files(
                static_path,
                topology_path,
            )

            self.assertEqual(num_added, 1)
            self.assertEqual(
                added_entries,
                [{"extaddr": "2000000000000000", "device_label": "Unknown-0x0800"}],
            )

    def test_main_generates_fallback_labels_for_unlabeled_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            self._write_json(
                data_dir / "topology.json",
                [{"extAddress": "2000000000000000"}],
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                rc = main(
                    [
                        "--datadir",
                        temp_dir,
                        "--merge-input-file",
                        "topology.json",
                        "--fallback-device-label-prefix",
                        "found",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertIn("Added 1 new extaddr entry", stdout.getvalue())
            self.assertEqual(
                self._read_json(data_dir / "td-static-extaddr-device-label.json"),
                [
                    {
                        "extAddress": "2000000000000000",
                        "deviceLabel": "found-2000000000000000",
                        "lastUpdated": "2026-11-18T05:19:45Z",
                    }
                ],
            )

    def test_merge_name_override_off_does_not_replace_unknown_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            static_path = temp_path / "td-static-extaddr-device-label.json"
            topology_path = temp_path / "topology.json"

            self._write_json(
                static_path,
                [{"extaddr": "3000000000000000", "device_label": "Unknown-0x1234"}],
            )
            self._write_json(
                topology_path,
                [{"extaddr": "3000000000000000", "name": "Office HomePod"}],
            )

            num_added, added_entries, num_overridden, overridden_entries = merge_extaddr_files(
                static_path,
                topology_path,
            )

            self.assertEqual(num_added, 0)
            self.assertEqual(added_entries, [])
            self.assertEqual(num_overridden, 0)
            self.assertEqual(overridden_entries, [])

            updated_static = self._read_json(static_path)
            self.assertEqual(updated_static[0]["device_label"], "Unknown-0x1234")

    def test_merge_name_override_on_replaces_unknown_label_with_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            static_path = temp_path / "td-static-extaddr-device-label.json"
            topology_path = temp_path / "topology.json"

            self._write_json(
                static_path,
                [{"extaddr": "4000000000000000", "device_label": "Unknown Device"}],
            )
            self._write_json(
                topology_path,
                [{"extaddr": "4000000000000000", "name": "Garage HomePod"}],
            )

            num_added, added_entries, num_overridden, overridden_entries = merge_extaddr_files(
                static_path,
                topology_path,
                merge_name_override=True,
            )

            self.assertEqual(num_added, 0)
            self.assertEqual(added_entries, [])
            self.assertEqual(num_overridden, 1)
            self.assertEqual(
                overridden_entries,
                [
                    {
                        "extaddr": "4000000000000000",
                        "old_device_label": "Unknown Device",
                        "new_device_label": "Garage HomePod",
                    }
                ],
            )

            updated_static = self._read_json(static_path)
            self.assertEqual(updated_static[0]["device_label"], "Garage HomePod")

    def test_merge_preserves_existing_record_keys_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            static_path = temp_path / "td-static-extaddr-device-label.json"
            topology_path = temp_path / "topology.json"
            self._write_json(
                static_path,
                [
                    {
                        "extAddress": "4000000000000000",
                        "deviceLabel": "Unknown Device",
                        "eui": "1234567890abcdef",
                        "rloc16": "0x4000",
                        "notes": {"source": "manual"},
                    }
                ],
            )
            self._write_json(
                topology_path,
                [
                    {"extaddr": "4000000000000000", "name": "Garage HomePod"},
                    {"extaddr": "5000000000000000", "device_label": "Kitchen Sensor"},
                ],
            )

            result = merge_extaddr_files(
                static_path,
                topology_path,
                merge_name_override=True,
            )

            self.assertEqual(result[0], 1)
            self.assertEqual(result[2], 1)
            self.assertEqual(
                self._read_json(static_path),
                [
                    {
                        "extAddress": "4000000000000000",
                        "deviceLabel": "Garage HomePod",
                        "eui": "1234567890abcdef",
                        "rloc16": "0x4000",
                        "notes": {"source": "manual"},
                        "lastUpdated": "2026-11-18T05:19:45Z",
                    },
                    {
                        "extAddress": "5000000000000000",
                        "deviceLabel": "Kitchen Sensor",
                        "lastUpdated": "2026-11-18T05:19:45Z",
                    },
                ],
            )

    def test_duplicate_extaddr_in_topology_uses_last_usable_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            static_path = temp_path / "td-static-extaddr-device-label.json"
            topology_path = temp_path / "topology.json"

            self._write_json(static_path, [])
            self._write_json(
                topology_path,
                [
                    {"extaddr": "5000000000000000", "device_label": "First Label"},
                    {
                        "extaddr": "5000000000000000",
                        "name": "Second Name._meshcop._udp.local.",
                    },
                ],
            )

            num_added, added_entries, num_overridden, overridden_entries = merge_extaddr_files(
                static_path,
                topology_path,
            )

            self.assertEqual(num_added, 1)
            self.assertEqual(num_overridden, 0)
            self.assertEqual(overridden_entries, [])
            self.assertEqual(
                added_entries[0],
                {
                    "extaddr": "5000000000000000",
                    "device_label": "Second Name._meshcop._udp.local.",
                },
            )

    def test_ignores_trel_scope_records_for_add_and_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            static_path = temp_path / "td-static-extaddr-device-label.json"
            topology_path = temp_path / "topology.json"

            self._write_json(
                static_path,
                [
                    {"extaddr": "6000000000000000", "device_label": "Unknown-0x9999"},
                ],
            )
            self._write_json(
                topology_path,
                [
                    {
                        "scope": "_trel._udp.local.",
                        "extaddr": "6000000000000000",
                        "name": "Should Not Override",
                    },
                    {
                        "scope": "_trel._udp.local.",
                        "extaddr": "7000000000000000",
                        "name": "Should Not Add",
                    },
                ],
            )

            num_added, added_entries, num_overridden, overridden_entries = merge_extaddr_files(
                static_path,
                topology_path,
                merge_name_override=True,
            )

            self.assertEqual(num_added, 0)
            self.assertEqual(added_entries, [])
            self.assertEqual(num_overridden, 0)
            self.assertEqual(overridden_entries, [])

            updated_static = self._read_json(static_path)
            self.assertEqual(len(updated_static), 1)
            self.assertEqual(updated_static[0]["extaddr"], "6000000000000000")
            self.assertEqual(updated_static[0]["device_label"], "Unknown-0x9999")

    def test_optional_field_validation_and_final_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "map.json"
            base = {"extaddr": "0000000000000000", "device_label": "One"}
            invalid = (
                {"eui": "00:00:00:00:00:00:00:00"},
                {"eui64": "bad"},
                {"lastUpdated": "2026-02-30T00:00:00Z"},
                {"lastUpdated": "2026-01-01T00:00:00+00:00"},
                {"comment": "x" * 513},
                {"comment": "bad\ncomment"},
                {"previousExtAddresses": "1234567890abcdef"},
                {"previousExtAddresses": ["invalid"]},
            )
            for fields in invalid:
                with self.subTest(fields=fields):
                    self._write_json(path, [{**base, **fields}])
                    with self.assertRaises(ValueError):
                        read_device_label(path, base["extaddr"])

            for duplicate_fields in (
                {"eui": "AA:BB:CC:DD:EE:FF:00:11"},
                {"previousExtAddresses": ["1111111111111111"]},
            ):
                rows = [
                    {**base, **duplicate_fields},
                    {"extaddr": "2222222222222222", "device_label": "Two", **duplicate_fields},
                ]
                self._write_json(path, rows)
                self.assertEqual(read_device_label(path, base["extaddr"])["deviceLabel"], "One")
                original = path.read_bytes()
                with self.assertRaises(ValueError):
                    upsert_device_label(path, base["extaddr"], "Changed")
                self.assertEqual(path.read_bytes(), original)
                self.assertFalse(path.with_name("map.json.bak").exists())

            self._write_json(path, [{**base, "previousExtAddresses": [base["extaddr"]]}])
            with self.assertRaises(ValueError):
                upsert_device_label(path, base["extaddr"], "Changed")

    def test_noop_preserves_unsorted_bytes_mtime_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "map.json"
            path.write_text('[{"extAddress":"ffffffffffffffff","deviceLabel":"Other"},'
                            '{"extaddr":"0000000000000000","device_label":"Label",'
                            '"lastUpdated":"2020-01-01T00:00:00Z"}]\n', encoding="utf-8")
            backup = path.with_name("map.json.bak")
            backup.write_bytes(b"old backup")
            before, mtime = path.read_bytes(), path.stat().st_mtime_ns
            result = upsert_device_label(path, "0000000000000000", " Label ", comment="")
            self.assertEqual(result["operation"], "updated")
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (before, mtime))
            self.assertEqual(backup.read_bytes(), b"old backup")
            source = Path(temp_dir) / "source.json"
            self._write_json(source, [{"extaddr": "0000000000000000", "name": "Other"}])
            self.assertEqual(merge_extaddr_files(path, source), (0, [], 0, []))
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (before, mtime))
            self.assertEqual(backup.read_bytes(), b"old backup")

    def test_eui_comment_and_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "td-static-extaddr-device-label.json"
            upsert_device_label(path, "1111111111111111", "One", eui="AA-BB-CC-DD-EE-FF-00-11", comment="note")
            row = self._read_json(path)[0]
            self.assertEqual((row["eui"], row["comment"]), ("aabbccddeeff0011", "note"))
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "requires --yes"):
                upsert_device_label(path, "1111111111111111", "New", eui="1234567890abcdef")
            self.assertEqual(path.read_bytes(), before)
            upsert_device_label(path, "1111111111111111", "New", eui="1234567890abcdef", comment="", yes=True)
            row = self._read_json(path)[0]
            self.assertEqual(row["eui"], "1234567890abcdef")
            self.assertNotIn("comment", row)
            self.assertEqual(path.with_name(path.name + ".bak").read_bytes(), before)

            stderr = StringIO()
            with redirect_stderr(stderr):
                rc = main(["--datadir", temp_dir, "--update-extaddr", "2222222222222222",
                           "--device-label", "Two", "--eui", "1234567890abcdef"])
            self.assertEqual(rc, 5)
            self.assertIn("device-label --sync-eui", stderr.getvalue())

            self._write_json(path, [
                {"extaddr": "1111111111111111", "device_label": "One", "eui": "1234567890abcdef"},
                {"extaddr": "2222222222222222", "device_label": "Two", "eui": "1234567890abcdef"},
            ])
            with self.assertRaisesRegex(ValueError, "duplicate eui"):
                upsert_device_label(path, "1111111111111111", "One", eui="1234567890abcdef")

    def test_backups_for_upsert_and_bulk_and_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "map.json"
            source = Path(temp_dir) / "source.json"
            backup = path.with_name("map.json.bak")
            upsert_device_label(path, "1111111111111111", "One")
            self.assertFalse(backup.exists())
            original = path.read_bytes()
            upsert_device_label(path, "1111111111111111", "Two")
            self.assertEqual(backup.read_bytes(), original)
            before_merge = path.read_bytes()
            self._write_json(source, [{"extaddr": "2222222222222222", "name": "Three"}])
            merge_extaddr_files(path, source)
            self.assertEqual(backup.read_bytes(), before_merge)
            before_failure = path.read_bytes()
            backup_before_failure = backup.read_bytes()
            self._write_json(source, [{"extaddr": "3333333333333333", "name": "Four"}])
            with patch.object(label_map.shutil, "copyfileobj", side_effect=OSError("backup failed")):
                with self.assertRaisesRegex(OSError, "backup failed"):
                    upsert_device_label(path, "1111111111111111", "Four")
                with self.assertRaisesRegex(OSError, "backup failed"):
                    merge_extaddr_files(path, source, merge_name_override=True)
            self.assertEqual(path.read_bytes(), before_failure)
            self.assertEqual(backup.read_bytes(), backup_before_failure)

    def test_injected_clock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "map.json"
            with patch.object(label_map, "_timestamp", wraps=real_timestamp):
                clock = lambda: datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
                upsert_device_label(path, "1111111111111111", "One", clock=clock)
            self.assertEqual(self._read_json(path)[0]["lastUpdated"], "2020-01-02T03:04:05Z")

    def test_bulk_validates_proposed_labels_before_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "map.json"
            source = Path(temp_dir) / "source.json"
            self._write_json(path, [{"extaddr": "1111111111111111", "device_label": "One"}])
            self._write_json(source, [{"extaddr": "2222222222222222", "name": "x" * 129}])
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                merge_extaddr_files(path, source)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(path.with_name("map.json.bak").exists())

    def test_cli_eui_replacement_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args = ["--datadir", temp_dir, "--update-extaddr", "1111111111111111",
                    "--device-label", "One", "--eui"]
            with redirect_stdout(StringIO()):
                self.assertEqual(main(args + ["1234567890abcdef"]), 0)
            for flag, eui in (("--yes", "1234567890abcde0"), ("--apply", "1234567890abcde1")):
                with redirect_stderr(StringIO()):
                    self.assertEqual(main(args + [eui]), 5)
                with redirect_stdout(StringIO()):
                    self.assertEqual(main(args + [eui, flag]), 0)

    def test_cli_alias_and_json_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            for command, address in (("device-label", "1111111111111111"),
                                     ("merge-extaddr", "2222222222222222")):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    rc = td_cli.main(["--datadir", temp_dir, command, "--update-extaddr",
                                      address, "--device-label", "Name", "--eui64", "1234567890abcde" + address[0]])
                self.assertEqual(rc, 0)
                self.assertEqual(json.loads(stdout.getvalue())["extAddress"], address)
            self.assertIn("device-label", td_cli.build_parser().format_help())

    def test_process_writers_and_lock_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            script = Path(label_map.__file__).resolve()
            def command(address):
                return [sys.executable, str(script), "--datadir", temp_dir,
                        "--update-extaddr", address, "--device-label", "Name"]
            path = Path(temp_dir) / "td-static-extaddr-device-label.json"
            with path.with_name(path.name + ".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                processes = [subprocess.Popen(command(addr), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                             for addr in ("1111111111111111", "2222222222222222")]
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, (stdout, stderr))
            self.assertEqual(len(self._read_json(path)), 2)
            self.assertEqual(len(self._read_json(path.with_name(path.name + ".bak"))), 1)
            before = path.read_bytes()
            with path.with_name(path.name + ".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                result = subprocess.run(command("3333333333333333"), capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 7)
            self.assertIn("map busy", result.stderr)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
