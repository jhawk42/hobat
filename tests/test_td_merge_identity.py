import json
import tempfile
import unittest
from pathlib import Path

from dataset_merge import build_merged_records


class BuildMergedRecordsIdentityTests(unittest.TestCase):
    def write_json(self, base_dir: Path, filename: str, payload: object) -> None:
        (base_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    def test_merges_extaddr_aliases_into_one_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            self.write_json(base_dir, "one.json", [{"extaddr": "AA11BB22CC33DD44", "name": "node-a"}])
            self.write_json(base_dir, "two.json", [{"extAddress": "aa11bb22cc33dd44", "device_label": "Kitchen"}])
            self.write_json(base_dir, "three.json", [{"Extended MAC": "AA11BB22CC33DD44", "type": "router"}])

            merged_records, report = build_merged_records(
                base_dir,
                "fd00:1234::",
                ["one.json", "two.json", "three.json"],
                {},
            )

            self.assertEqual(len(merged_records), 1)
            record = merged_records[0]
            self.assertEqual(record["extaddr"], "aa11bb22cc33dd44")
            self.assertEqual(record["name"], "node-a")
            self.assertEqual(record["device_label"], "Kitchen")
            self.assertEqual(record["type"], "router")
            self.assertCountEqual(record["_source_files"], ["one.json", "two.json", "three.json"])
            self.assertEqual(report["multi_source_nodes_total"], 1)

    def test_merges_records_by_omr_ipv6_address_when_extaddr_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            self.write_json(base_dir, "one.json", [{"omrIpv6Address": "FD00:ABCD::1234", "name": "node-a"}])
            self.write_json(base_dir, "two.json", [{"omrIpv6Address": "fd00:abcd::1234", "device_label": "Bedroom"}])

            merged_records, report = build_merged_records(
                base_dir,
                "fd00:abcd::",
                ["one.json", "two.json"],
                {},
            )

            self.assertEqual(len(merged_records), 1)
            record = merged_records[0]
            self.assertEqual(record["omrIpv6Address"], "fd00:abcd::1234")
            self.assertEqual(record["name"], "node-a")
            self.assertEqual(record["device_label"], "Bedroom")
            self.assertCountEqual(record["_source_files"], ["one.json", "two.json"])
            self.assertEqual(report["multi_source_nodes_total"], 1)

    def test_records_with_distinct_identities_do_not_merge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            self.write_json(base_dir, "one.json", [{"extaddr": "aa11bb22cc33dd44", "device_label": "same-label"}])
            self.write_json(base_dir, "two.json", [{"extAddress": "ff00ee11dd22cc33", "device_label": "same-label"}])
            self.write_json(base_dir, "three.json", [{"name": "no-identifiers"}])

            merged_records, report = build_merged_records(
                base_dir,
                "fd00:abcd::",
                ["one.json", "two.json", "three.json"],
                {},
            )

            self.assertEqual(len(merged_records), 3)
            self.assertEqual(report["multi_source_nodes_total"], 0)
            self.assertCountEqual(
                [record.get("extaddr", "") for record in merged_records if record.get("extaddr")],
                ["aa11bb22cc33dd44", "ff00ee11dd22cc33"],
            )
            self.assertIn("no-identifiers", [record.get("name") for record in merged_records])


if __name__ == "__main__":
    unittest.main()