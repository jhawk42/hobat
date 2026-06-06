from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import otbr_restapi_cli as cli_module
from otbr_restapi_util import OTBRUsageError


class OTBRRestApiCLILabGateParserTests(unittest.TestCase):
    def test_parser_accepts_lab_flag(self) -> None:
        args = cli_module.build_parser().parse_args(
            ["--lab", "actions", "enqueue", "reset-network-diag-counter", "--types", "macCounters"]
        )

        self.assertTrue(args.lab)
        self.assertEqual(args.resource, "actions")


class OTBRRestApiCLILabGateDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Mock()
        self.client._resolve_raw.return_value = False

    def test_sensitive_commands_blocked_without_lab(self) -> None:
        blocked_args = [
            SimpleNamespace(resource="node", node_command="state", state_command="set", lab=False),
            SimpleNamespace(
                resource="node",
                node_command="dataset",
                dataset_kind="active",
                dataset_command="set",
                lab=False,
            ),
            SimpleNamespace(
                resource="actions",
                actions_command="enqueue",
                enqueue_type="add-thread-device",
                lab=False,
            ),
            SimpleNamespace(
                resource="actions",
                actions_command="enqueue",
                enqueue_type="reset-network-diag-counter",
                lab=False,
            ),
        ]

        for args in blocked_args:
            with self.subTest(args=args):
                with self.assertRaises(OTBRUsageError) as ctx:
                    cli_module.dispatch(self.client, args)
                self.assertIn("currently experimental", str(ctx.exception))
                self.assertIn("requires --lab", str(ctx.exception))

    def test_sensitive_command_allowed_with_lab_dispatches(self) -> None:
        args = SimpleNamespace(
            resource="node",
            node_command="state",
            state_command="set",
            lab=True,
            raw=False,
            fields=None,
        )

        with patch.object(cli_module, "dispatch_node", return_value={"ok": True}) as dispatch_node:
            result = cli_module.dispatch(self.client, args)

        self.assertEqual(result, {"ok": True})
        dispatch_node.assert_called_once()

    def test_non_sensitive_command_unaffected_without_lab(self) -> None:
        args = SimpleNamespace(
            resource="devices",
            devices_command="list",
            lab=False,
            raw=False,
            fields=None,
        )

        with patch.object(cli_module, "dispatch_devices", return_value=[{"id": "d1"}]) as dispatch_devices:
            result = cli_module.dispatch(self.client, args)

        self.assertEqual(result, [{"id": "d1"}])
        dispatch_devices.assert_called_once()


if __name__ == "__main__":
    unittest.main()
