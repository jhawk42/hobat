from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from merge_extaddr_file_into_static_map import merge_extaddr_files


class MergeExtaddrFilesTests(unittest.TestCase):
    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _read_json(self, path: Path) -> object:
        return json.loads(path.read_text(encoding="utf-8"))

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
