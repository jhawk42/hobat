from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import otbr_restapi_cli as cli_module
import otbr_restapi_diagnostics as diagnostics_module
from otbr_restapi_util import _RAW_UNSET


class DiagnosticsListEnrichmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Mock()

    def _args(self, *, with_meta: bool = False, no_enrich: bool = False) -> SimpleNamespace:
        return SimpleNamespace(
            diagnostics_command="list",
            with_meta=with_meta,
            no_enrich_mac_counters=no_enrich,
        )

    def test_list_enriches_mac_counters_by_default(self) -> None:
        payload = [
            {
                "id": "diag-1",
                "macCounters": {
                    "ifInUcastPkts": 1,
                    "ifInBroadcastPkts": 2,
                    "ifOutUcastPkts": 3,
                    "ifOutBroadcastPkts": 4,
                    "ifInErrors": 1,
                    "ifOutErrors": 1,
                    "ifInDiscards": 2,
                    "ifOutDiscards": 0,
                },
                "mleCounters": {
                    "totalTrackingTime": 10,
                    "routerRoleTime": 6,
                    "childRoleTime": 1,
                    "leaderRoleTime": 2,
                    "detachedRoleTime": 1,
                    "radioDisabledTime": 0,
                },
            }
        ]
        self.client.list_diagnostics.return_value = payload

        result = diagnostics_module.dispatch_diagnostics(
            self.client,
            self._args(),
            _RAW_UNSET,
            fields=None,
        )

        self.assertIsNot(result, payload)
        mac = result[0]["macCounters"]
        self.assertEqual(mac["ifInTotalPkts"], 3)
        self.assertEqual(mac["ifOutTotalPkts"], 7)
        self.assertEqual(mac["ifTotalPkts"], 10)
        self.assertEqual(mac["ifTotalErrors"], 2)
        time_stats = result[0]["timeStatistics"]
        self.assertEqual(time_stats["trackedTime"], 10)
        self.assertEqual(time_stats["routerPct"], 60.0)
        self.assertEqual(time_stats["detachedDisabledPct"], 10.0)

    def test_list_with_meta_enriches_items_and_preserves_meta(self) -> None:
        payload = {
            "items": [
                {
                    "id": "diag-1",
                    "macCounters": {
                        "ifInUcastPkts": 5,
                        "ifInBroadcastPkts": 5,
                        "ifOutUcastPkts": 2,
                        "ifOutBroadcastPkts": 3,
                    },
                }
            ],
            "meta": {"collection": {"total": 1}},
        }
        self.client.list_diagnostics.return_value = payload

        result = diagnostics_module.dispatch_diagnostics(
            self.client,
            self._args(with_meta=True),
            _RAW_UNSET,
            fields=None,
        )

        self.assertIsNot(result, payload)
        self.assertEqual(result["meta"], {"collection": {"total": 1}})
        self.assertEqual(result["items"][0]["macCounters"]["ifInTotalPkts"], 10)
        self.assertEqual(result["items"][0]["macCounters"]["ifOutTotalPkts"], 5)

    def test_list_no_enrich_flag_returns_raw_mac_counters(self) -> None:
        payload = [{
            "type": "threadNetworkDiagnostic",
            "eui64": "0011223344556677",
            "threadVersion": 4,
            "macCounters": {"ifInUcastPkts": 1},
            "ipv6Addresses": ["fdde:ad00:beef:0:0:ff:fe00:fc11"],
        }]
        self.client.list_diagnostics.return_value = payload

        result = diagnostics_module.dispatch_diagnostics(
            self.client,
            self._args(no_enrich=True),
            _RAW_UNSET,
            fields=None,
        )

        self.assertIsNot(result, payload)
        self.assertNotIn("iftotalpkts", result[0]["macCounters"])
        self.assertEqual(result[0]["eui"], "0011223344556677")
        self.assertEqual(result[0]["threadVersionDecimal"], 4)
        self.assertEqual(result[0]["threadVersion"], "1.3")
        self.assertNotIn("eui64", result[0])
        self.assertIs(result[0]["isBorderRouter"], True)

    def test_get_normalizes_thread_diagnostic_fields_by_default(self) -> None:
        args = SimpleNamespace(diagnostics_command="get", diagnostics_id="diag-1")
        payload = {
            "id": "diag-1",
            "type": "threadNetworkDiagnostic",
            "eui": "0011223344556677",
            "threadVersion": 4,
        }
        self.client.get_diagnostic.return_value = payload

        result = diagnostics_module.dispatch_diagnostics(
            self.client,
            args,
            _RAW_UNSET,
            fields=None,
        )

        self.assertEqual(result["eui"], "0011223344556677")
        self.assertEqual(result["threadVersionDecimal"], 4)
        self.assertEqual(result["threadVersion"], "1.3")
        self.assertNotIn("version", result)

    def test_get_applies_positive_border_router_address_evidence(self) -> None:
        args = SimpleNamespace(diagnostics_command="get", diagnostics_id="diag-1")
        self.client.get_diagnostic.return_value = {
            "isBorderRouter": False,
            "ipv6Addresses": ["fdde:ad00:beef:0:0:ff:fe00:fc11"],
        }

        result = diagnostics_module.dispatch_diagnostics(
            self.client,
            args,
            _RAW_UNSET,
            fields=None,
        )

        self.assertIs(result["isBorderRouter"], True)
        self.assertEqual(result["_merge_conflicts"], [
            {"path": "isBorderRouter", "current": False, "incoming": True}
        ])

    def test_get_keeps_explicit_false_without_positive_address_match(self) -> None:
        args = SimpleNamespace(diagnostics_command="get", diagnostics_id="diag-1")
        self.client.get_diagnostic.return_value = {
            "isBorderRouter": False,
            "ipv6Addresses": ["fdde:ad00:beef::1"],
        }

        result = diagnostics_module.dispatch_diagnostics(
            self.client,
            args,
            _RAW_UNSET,
            fields=None,
        )

        self.assertIs(result["isBorderRouter"], False)
        self.assertNotIn("_merge_conflicts", result)

    def test_fetch_applies_positive_border_router_address_evidence(self) -> None:
        args = SimpleNamespace(
            diagnostics_command="fetch",
            device_id="device-1",
            destination_type="extended",
            task_timeout=8,
            poll_interval=2.0,
            poll_timeout=8.0,
            no_enrich_mac_counters=True,
        )
        payload = {
            "isBorderRouter": False,
            "ipv6Addresses": ["fdde:ad00:beef:0:0:ff:fe00:fc11"],
        }

        with (
            patch.object(diagnostics_module, "resolve_types", return_value=[]),
            patch.object(diagnostics_module, "resolve_fallback_types", return_value=[]),
            patch.object(diagnostics_module, "fetch_device_with_fallback", return_value=payload),
        ):
            result = diagnostics_module.dispatch_diagnostics(
                self.client,
                args,
                _RAW_UNSET,
                fields=None,
            )

        self.assertIs(result["isBorderRouter"], True)
        self.assertEqual(result["_merge_conflicts"], [
            {"path": "isBorderRouter", "current": False, "incoming": True}
        ])

    def test_fetch_keeps_missing_without_positive_address_match(self) -> None:
        args = SimpleNamespace(
            diagnostics_command="fetch",
            device_id="device-1",
            destination_type="extended",
            task_timeout=8,
            poll_interval=2.0,
            poll_timeout=8.0,
            no_enrich_mac_counters=False,
        )
        payload = {"ipv6Addresses": ["fdde:ad00:beef::1"]}

        with (
            patch.object(diagnostics_module, "resolve_types", return_value=[]),
            patch.object(diagnostics_module, "resolve_fallback_types", return_value=[]),
            patch.object(diagnostics_module, "fetch_device_with_fallback", return_value=payload),
        ):
            result = diagnostics_module.dispatch_diagnostics(
                self.client,
                args,
                _RAW_UNSET,
                fields=None,
            )

        self.assertNotIn("isBorderRouter", result)

    def test_get_raw_preserves_wire_payload(self) -> None:
        args = SimpleNamespace(diagnostics_command="get", diagnostics_id="diag-1")
        payload = {"version": 4, "eui64": "0011223344556677"}
        self.client.get_diagnostic.return_value = payload

        result = diagnostics_module.dispatch_diagnostics(
            self.client,
            args,
            True,
            fields=None,
        )

        self.assertIs(result, payload)

    def test_fetch_raw_preserves_wire_payload(self) -> None:
        args = SimpleNamespace(
            diagnostics_command="fetch",
            device_id="device-1",
            destination_type="extended",
            task_timeout=8,
            poll_interval=2.0,
            poll_timeout=8.0,
            no_enrich_mac_counters=False,
        )
        payload = {
            "data": {
                "id": "diag-1",
                "attributes": {"is_border_router": False, "ipv6_addrs": []},
            }
        }

        with (
            patch.object(diagnostics_module, "resolve_types", return_value=[]),
            patch.object(diagnostics_module, "resolve_fallback_types", return_value=[]),
            patch.object(diagnostics_module, "fetch_device_with_fallback", return_value=payload),
        ):
            result = diagnostics_module.dispatch_diagnostics(
                self.client,
                args,
                True,
                fields=None,
            )

        self.assertIs(result, payload)
        self.assertIn("data", result)
        self.assertIn("attributes", result["data"])
        self.assertIn("is_border_router", result["data"]["attributes"])

    def test_fetch_all_raw_preserves_final_and_checkpoint_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "diagnostics.json"
            checkpoint_item = {
                "data": {
                    "id": "diag-checkpoint",
                    "attributes": {"is_border_router": False},
                }
            }
            final_item = {
                "data": {
                    "id": "diag-final",
                    "attributes": {"is_border_router": True},
                }
            }
            outcome = {
                "items": [final_item],
                "deviceResults": [{"status": "completed"}],
                "partial": False,
            }
            self.client.list_devices.return_value = [{"id": "device-1"}]

            def fetch_all(_devices, **kwargs):
                kwargs["on_checkpoint"](
                    [checkpoint_item], 1, 1, "device-1", "completed"
                )
                return outcome

            self.client.fetch_all_devices_diagnostics.side_effect = fetch_all
            args = SimpleNamespace(
                diagnostics_command="fetch-all",
                resolved_output_path=str(output_path),
                no_basic_fallback=False,
                no_enrich_mac_counters=False,
                no_update_devices=True,
                device_ids=None,
                destination_type="extended",
                task_timeout=8,
                poll_interval=2.0,
                poll_timeout=8.0,
                preserve_diagnostics=True,
                no_progress=True,
                items_only=False,
                types=None,
                preset="recommended",
            )

            with (
                patch.object(diagnostics_module, "resolve_types", return_value=[]),
                patch.object(diagnostics_module, "resolve_fallback_types", return_value=[]),
                patch.object(diagnostics_module, "use_progressive_fallback", return_value=False),
            ):
                result = diagnostics_module.dispatch_diagnostics(
                    self.client,
                    args,
                    True,
                    fields=None,
                )

            self.assertIs(result, outcome)
            self.assertIn("data", result["items"][0])
            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8")), outcome
            )
            [checkpoint_path] = Path(tmpdir).glob("*.partial.json")
            self.assertEqual(
                json.loads(checkpoint_path.read_text(encoding="utf-8")),
                [checkpoint_item],
            )

    def test_list_raw_true_skips_enrichment(self) -> None:
        payload = [{"macCounters": {"ifInUcastPkts": 1}}]
        self.client.list_diagnostics.return_value = payload

        result = diagnostics_module.dispatch_diagnostics(
            self.client,
            self._args(),
            True,
            fields=None,
        )

        self.assertIs(result, payload)
        self.assertNotIn("iftotalpkts", result[0]["macCounters"])

    def test_list_enrichment_skips_invalid_ipv6_addresses(self) -> None:
        payload = [
            {
                "id": "diag-1",
                "ipv6Addresses": [None, 123, "fdde:ad00:beef::fc11"],
                "macCounters": {
                    "ifInUcastPkts": 0,
                    "ifInBroadcastPkts": 0,
                    "ifOutUcastPkts": 0,
                    "ifOutBroadcastPkts": 0,
                    "ifInErrors": 0,
                    "ifOutErrors": 0,
                    "ifInDiscards": 0,
                    "ifOutDiscards": 0,
                },
                "mleCounters": {
                    "totalTrackingTime": 1,
                    "routerRoleTime": 0,
                    "childRoleTime": 0,
                    "leaderRoleTime": 0,
                    "detachedRoleTime": 0,
                    "radioDisabledTime": 0,
                },
            }
        ]
        self.client.list_diagnostics.return_value = payload

        result = diagnostics_module.dispatch_diagnostics(
            self.client,
            self._args(),
            _RAW_UNSET,
            fields=None,
        )

        self.assertIsNot(result, payload)
        self.assertEqual(result[0]["ipv6Addresses"], [None, 123, "fdde:ad00:beef::fc11"])

    def test_border_router_address_evidence_overrides_false_and_records_conflict(self) -> None:
        record = {
            "isBorderRouter": False,
            "is_border_router": True,
            "br": False,
            "ipv6Addresses": ["fdde:ad00:beef:0:0:ff:fe00:fc11"],
        }

        diagnostics_module.enrich_border_router(record)

        self.assertIs(record["isBorderRouter"], True)
        self.assertNotIn("br", record)
        self.assertNotIn("is_border_router", record)
        self.assertEqual(record["_merge_conflicts"], [
            {"path": "isBorderRouter", "current": False, "incoming": True}
        ])

    def test_border_router_enrichment_preserves_false_without_positive_evidence(self) -> None:
        record = {
            "isBorderRouter": False,
            "ipv6Addresses": ["fdde:ad00:beef::1"],
        }

        diagnostics_module.enrich_border_router(record)

        self.assertIs(record["isBorderRouter"], False)
        self.assertNotIn("_merge_conflicts", record)
        self.assertNotIn("br", record)

    def test_border_router_enrichment_keeps_missing_evidence_absent(self) -> None:
        record = {"ipv6Addresses": ["fdde:ad00:beef::1"]}

        diagnostics_module.enrich_border_router(record)

        self.assertNotIn("isBorderRouter", record)

    def test_diagnostics_checkpoint_normalizes_border_router_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "diagnostics.partial.json"
            diagnostics_module._write_checkpoint_best_effort(
                [{
                    "isBorderRouter": False,
                    "is_border_router": True,
                    "br": False,
                }],
                checkpoint_path,
                "otbr-restapi diagnostics fetch-all",
                "device",
            )

            [saved] = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertIs(saved["isBorderRouter"], False)
            self.assertNotIn("br", saved)
            self.assertNotIn("is_border_router", saved)
            self.assertEqual(saved["_merge_conflicts"], [
                {"path": "isBorderRouter", "current": False, "incoming": True}
            ])


class DiagnosticsListParserTests(unittest.TestCase):
    def test_diagnostics_list_accepts_no_enrich_mac_counters_flag(self) -> None:
        args = cli_module.build_parser().parse_args(
            ["diagnostics", "list", "--no-enrich-mac-counters"]
        )

        self.assertEqual(args.resource, "diagnostics")
        self.assertEqual(args.diagnostics_command, "list")
        self.assertTrue(args.no_enrich_mac_counters)


class DiagnosticsFetchAllEnrichmentTests(unittest.TestCase):
    def test_fetch_all_enriches_time_statistics(self) -> None:
        client = Mock()
        client.list_devices.return_value = [{"id": "dev-1"}]

        diagnostics_payload = [
            {
                "id": "diag-1",
                "mleCounters": {
                    "totalTrackingTime": 20,
                    "routerRoleTime": 5,
                    "childRoleTime": 5,
                    "leaderRoleTime": 0,
                    "detachedRoleTime": 8,
                    "radioDisabledTime": 2,
                },
            }
        ]

        args = SimpleNamespace(
            diagnostics_command="fetch-all",
            no_enrich_mac_counters=False,
            no_update_devices=True,
            device_ids=None,
            destination_type="extended",
            task_timeout=8,
            poll_interval=2.0,
            poll_timeout=8.0,
            no_progress=True,
            no_fallback=True,
            preset="recommended",
            types=None,
            items_only=True,
        )
        client.fetch_all_devices_diagnostics.return_value = {
            "items": diagnostics_payload,
            "deviceResults": [{"deviceId": "dev-1", "status": "completed"}],
            "partial": False,
        }

        result = diagnostics_module.dispatch_diagnostics(
            client,
            args,
            _RAW_UNSET,
            fields=None,
        )

        self.assertIsNot(result, diagnostics_payload)
        stats = result[0]["timeStatistics"]
        self.assertEqual(stats["trackedTime"], 20)
        self.assertEqual(stats["detachedDisabledTime"], 10)
        self.assertEqual(stats["detachedDisabledPct"], 50.0)
        self.assertEqual(stats["routerPct"], 25.0)


class DiagnosticsRoleEvidenceTests(unittest.TestCase):
    def test_list_normalizes_explicit_and_derived_role_evidence(self) -> None:
        client = Mock()
        client.list_diagnostics.return_value = [
            {
                "routerId": "0x23",
                "leaderData": {"leaderRouterId": "35"},
                "isLeader": False,
                "isPrimaryBBR": True,
            },
            {
                "routerId": "0",
                "leaderData": {"leaderRouterId": 0},
                "isPrimaryBBR": "true",
            },
        ]

        result = diagnostics_module.dispatch_diagnostics(
            client,
            SimpleNamespace(diagnostics_command="list", with_meta=False, no_enrich_mac_counters=False),
            _RAW_UNSET,
            fields=None,
        )

        self.assertEqual(result[0]["routerId"], 35)
        self.assertFalse(result[0]["isLeader"])
        self.assertEqual(result[0]["leaderEvidence"], "explicit")
        self.assertEqual(result[0]["roleEvidenceConflicts"], [{"role": "isLeader", "explicit": False, "derived": True}])
        self.assertTrue(result[0]["isPrimaryBBR"])
        self.assertEqual(result[0]["primaryBBREvidence"], "explicit-rest")
        self.assertEqual(result[1]["routerId"], 0)
        self.assertTrue(result[1]["isLeader"])
        self.assertEqual(result[1]["leaderEvidence"], "leader-router-id-match")
        self.assertNotIn("isPrimaryBBR", result[1])


if __name__ == "__main__":
    unittest.main()
