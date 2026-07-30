from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from merge_extaddr_device_label_map import (
    ExtaddrNotFoundError,
    main,
    merge_extaddr_files,
    normalize_valid_device_label,
    normalize_valid_extaddr,
    read_device_label,
    upsert_device_label,
)


class MergeExtaddrFilesTests(unittest.TestCase):
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
                result,
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
                        "extaddr": "4e866ce96501b9ed",
                        "device_label": "Office Sensor",
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
            self.assertEqual(
                json.loads(stdout.getvalue()),
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
                    "extaddr": "2000000000000000",
                    "device_label": "Dining Room HomePod._meshcop._udp.local.",
                },
                updated_static,
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


if __name__ == "__main__":
    unittest.main()
