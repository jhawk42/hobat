import json
import tempfile
import unittest
from pathlib import Path

from merge_dataset import build_merged_records


class BuildMergedRecordsIdentityTests(unittest.TestCase):
    def write_json(self, base_dir: Path, filename: str, payload: object) -> None:
        (base_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    def test_merges_extaddr_aliases_into_one_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            self.write_json(
                base_dir,
                "one.json",
                [{"extAddress": "AA11BB22CC33DD44", "name": "node-a"}],
            )
            self.write_json(
                base_dir,
                "two.json",
                [{"extAddress": "aa11bb22cc33dd44", "deviceLabel": "Kitchen"}],
            )
            self.write_json(
                base_dir,
                "three.json",
                [{"Extended MAC": "AA11BB22CC33DD44", "type": "router"}],
            )

            merged_records, report = build_merged_records(
                base_dir,
                "fd00:1234::",
                ["one.json", "two.json", "three.json"],
                {},
            )

            self.assertEqual(len(merged_records), 1)
            record = merged_records[0]
            self.assertEqual(str(record["extAddress"]).lower(), "aa11bb22cc33dd44")
            self.assertEqual(record["name"], "node-a")
            self.assertEqual(record["deviceLabel"], "Kitchen")
            self.assertEqual(record["type"], "router")
            self.assertCountEqual(
                record["_source_files"], ["one.json", "two.json", "three.json"]
            )
            self.assertEqual(report["multi_source_nodes_total"], 1)

    def test_merges_records_by_omr_ipv6_address_when_extaddr_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            self.write_json(
                base_dir,
                "one.json",
                [{"omrIpv6Address": "FD00:ABCD::1234", "name": "node-a"}],
            )
            self.write_json(
                base_dir,
                "two.json",
                [{"omrIpv6Address": "fd00:abcd::1234", "deviceLabel": "Bedroom"}],
            )

            merged_records, report = build_merged_records(
                base_dir,
                "fd00:abcd::",
                ["one.json", "two.json"],
                {},
            )

            self.assertEqual(len(merged_records), 1)
            record = merged_records[0]
            self.assertEqual(str(record["omrIpv6Address"]).lower(), "fd00:abcd::1234")
            self.assertEqual(record["name"], "node-a")
            self.assertEqual(record["deviceLabel"], "Bedroom")
            self.assertCountEqual(record["_source_files"], ["one.json", "two.json"])
            self.assertEqual(report["multi_source_nodes_total"], 1)

    def test_merges_omr_ipv6_address_camelcase_alias(self) -> None:
        """Test that omrIpv6Address (REST API camelCase) merges with omr_ipv6_addr (CLI snake_case)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            # CLI source with snake_case
            self.write_json(
                base_dir,
                "cli.json",
                [{"omrIpv6Address": "FD00:ABCD::1234", "name": "cli-node"}],
            )
            # REST API source with camelCase
            self.write_json(
                base_dir,
                "restapi.json",
                [{"omrIpv6Address": "fd00:abcd::1234", "deviceLabel": "API Node"}],
            )

            merged_records, report = build_merged_records(
                base_dir,
                "fd00:abcd::",
                ["cli.json", "restapi.json"],
                {},
            )

            # Should merge into ONE record, not two
            self.assertEqual(len(merged_records), 1)
            record = merged_records[0]
            # Canonical field name should be set
            self.assertEqual(str(record["omrIpv6Address"]).lower(), "fd00:abcd::1234")
            # Both fields merged
            self.assertEqual(record["name"], "cli-node")
            self.assertEqual(record["deviceLabel"], "API Node")
            # Both sources recorded
            self.assertCountEqual(record["_source_files"], ["cli.json", "restapi.json"])
            # Should be counted as multi-source node
            self.assertEqual(report["multi_source_nodes_total"], 1)
            self.assertEqual(report["single_source_nodes_total"], 0)

    def test_records_with_distinct_identities_do_not_merge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            self.write_json(
                base_dir,
                "one.json",
                [{"extAddress": "aa11bb22cc33dd44", "deviceLabel": "same-label"}],
            )
            self.write_json(
                base_dir,
                "two.json",
                [{"extAddress": "ff00ee11dd22cc33", "deviceLabel": "same-label"}],
            )
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
                [
                    record.get("extAddress", "")
                    for record in merged_records
                    if record.get("extAddress")
                ],
                ["aa11bb22cc33dd44", "ff00ee11dd22cc33"],
            )
            self.assertIn(
                "no-identifiers", [record.get("name") for record in merged_records]
            )


if __name__ == "__main__":
    unittest.main()
