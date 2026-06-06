from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

import td_cli


class TDCLILabGateTests(unittest.TestCase):
    def _parse_known(self, argv: list[str]):
        parser = td_cli.build_parser()
        args, extras = parser.parse_known_args(argv)
        return parser, args, extras

    def test_sensitive_commands_blocked_without_lab(self) -> None:
        sensitive_argv = [
            ["otbr-restapi", "node", "state", "set", "--value", "enable"],
            [
                "otbr-restapi",
                "node",
                "dataset",
                "active",
                "set",
                "--text",
                "0e08",
            ],
            [
                "otbr-restapi",
                "actions",
                "enqueue",
                "add-thread-device",
                "--pskd",
                "J01NME",
                "--eui",
                "0011223344556677",
            ],
            [
                "otbr-restapi",
                "actions",
                "enqueue",
                "reset-network-diag-counter",
                "--types",
                "macCounters",
            ],
        ]

        for argv in sensitive_argv:
            with self.subTest(argv=argv):
                parser, args, extras = self._parse_known(argv)
                stderr = io.StringIO()
                with patch.object(td_cli.otbr_restapi_cli, "main", return_value=0) as module_main:
                    with redirect_stderr(stderr):
                        rc = td_cli.dispatch(args, extras, parser)

                self.assertEqual(rc, 2)
                self.assertIn("currently experimental", stderr.getvalue())
                self.assertIn("requires --lab", stderr.getvalue())
                module_main.assert_not_called()

    def test_sensitive_commands_forward_with_lab(self) -> None:
        argv = [
            "otbr-restapi",
            "--lab",
            "actions",
            "enqueue",
            "reset-network-diag-counter",
            "--types",
            "macCounters",
        ]
        parser, args, extras = self._parse_known(argv)

        with patch.object(td_cli.otbr_restapi_cli, "main", return_value=0) as module_main:
            rc = td_cli.dispatch(args, extras, parser)

        self.assertEqual(rc, 0)
        module_main.assert_called_once()
        forwarded = module_main.call_args.args[0]
        self.assertIn("--lab", forwarded)
        self.assertEqual(forwarded[-4:], ["enqueue", "reset-network-diag-counter", "--types", "macCounters"])

    def test_non_sensitive_command_not_blocked_without_lab(self) -> None:
        argv = ["otbr-restapi", "devices", "list"]
        parser, args, extras = self._parse_known(argv)

        with patch.object(td_cli.otbr_restapi_cli, "main", return_value=0) as module_main:
            rc = td_cli.dispatch(args, extras, parser)

        self.assertEqual(rc, 0)
        module_main.assert_called_once()


if __name__ == "__main__":
    unittest.main()
