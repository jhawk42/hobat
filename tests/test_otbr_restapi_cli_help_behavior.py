from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

import otbr_restapi_cli as cli_module


class OTBRRestApiCLIIncompleteHelpTests(unittest.TestCase):
    def _run_and_capture(self, argv: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_module.main(argv)
        return rc, buf.getvalue()

    def test_incomplete_commands_print_contextual_help_and_return_success(self) -> None:
        cases = [
            ([], "usage:"),
            (["actions"], "{list,get,enqueue}"),
            (["actions", "enqueue"], "{add-thread-device,get-network-diagnostic,reset-network-diag-counter,get-energy-scan,update-device-collection}"),
            (["node"], "{get,state,dataset}"),
            (["node", "state"], "{get,set}"),
            (["node", "dataset"], "{active}"),
            (["node", "dataset", "active"], "{get,set}"),
            (["devices"], "{list,get,fetch}"),
            (["diagnostics"], "{list,get,fetch,fetch-all}"),
            (["mesh-diagnostics"], "{children,child-ipv6,router-neighbors,fetch,fetch-all}"),
        ]

        for argv, expected in cases:
            with self.subTest(argv=argv):
                rc, out = self._run_and_capture(argv)
                self.assertEqual(rc, 0)
                self.assertIn("usage:", out)
                self.assertIn(expected, out)

    def test_typo_commands_print_contextual_help_and_return_success(self) -> None:
        cases = [
            (["device"], "{node,devices,diagnostics,actions,mesh-diagnostics,topology}"),
            (["actions", "enqueu"], "{list,get,enqueue}"),
            (["node", "stte"], "{get,state,dataset}"),
        ]

        for argv, expected in cases:
            with self.subTest(argv=argv):
                rc, out = self._run_and_capture(argv)
                self.assertEqual(rc, 0)
                self.assertIn("usage:", out)
                self.assertIn(expected, out)

    def test_children_expand_by_rloc_is_diagnostics_fetch_all_only(self) -> None:
        parser = cli_module.build_parser()
        default = parser.parse_args(["diagnostics", "fetch-all"])
        enabled = parser.parse_args(
            ["diagnostics", "fetch-all", "--children-expand-by-rloc"]
        )
        self.assertIs(default.children_expand_by_rloc, False)
        self.assertIs(enabled.children_expand_by_rloc, True)

        rc, out = self._run_and_capture(["diagnostics", "fetch-all", "--help"])
        self.assertEqual(rc, 0)
        self.assertIn("--children-expand-by-rloc", out)
        for argv in (["topology"], ["mesh-diagnostics", "fetch-all"]):
            with self.subTest(argv=argv):
                with io.StringIO() as err, redirect_stderr(err):
                    with self.assertRaises(SystemExit):
                        parser.parse_args([*argv, "--children-expand-by-rloc"])


if __name__ == "__main__":
    unittest.main()
