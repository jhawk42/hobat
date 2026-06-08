from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

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

        self.assertIs(result, payload)
        mac = result[0]["macCounters"]
        self.assertEqual(mac["ifintotalpkts"], 3)
        self.assertEqual(mac["ifouttotalpkts"], 7)
        self.assertEqual(mac["iftotalpkts"], 10)
        self.assertEqual(mac["iftotalerrors"], 2)
        time_stats = result[0]["time_statistics"]
        self.assertEqual(time_stats["tracked_time"], 10)
        self.assertEqual(time_stats["router_pct"], 60.0)
        self.assertEqual(time_stats["detached_disabled_pct"], 10.0)

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

        self.assertIs(result, payload)
        self.assertEqual(result["meta"], {"collection": {"total": 1}})
        self.assertEqual(result["items"][0]["macCounters"]["ifintotalpkts"], 10)
        self.assertEqual(result["items"][0]["macCounters"]["ifouttotalpkts"], 5)

    def test_list_no_enrich_flag_returns_raw_mac_counters(self) -> None:
        payload = [{"macCounters": {"ifInUcastPkts": 1}}]
        self.client.list_diagnostics.return_value = payload

        result = diagnostics_module.dispatch_diagnostics(
            self.client,
            self._args(no_enrich=True),
            _RAW_UNSET,
            fields=None,
        )

        self.assertIs(result, payload)
        self.assertNotIn("iftotalpkts", result[0]["macCounters"])

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

        self.assertIs(result, payload)
        self.assertEqual(result[0]["ipv6Addresses"], [None, 123, "fdde:ad00:beef::fc11"])


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
        )

        with unittest.mock.patch.object(
            diagnostics_module,
            "fetch_all_with_fallback",
            return_value=diagnostics_payload,
        ):
            result = diagnostics_module.dispatch_diagnostics(
                client,
                args,
                _RAW_UNSET,
                fields=None,
            )

        self.assertIs(result, diagnostics_payload)
        stats = result[0]["time_statistics"]
        self.assertEqual(stats["tracked_time"], 20)
        self.assertEqual(stats["detached_disabled_time"], 10)
        self.assertEqual(stats["detached_disabled_pct"], 50.0)
        self.assertEqual(stats["router_pct"], 25.0)


if __name__ == "__main__":
    unittest.main()
