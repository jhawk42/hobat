"""Tests for td_cli.py build_parser(), dispatch(), and main() (Phase 8).

Run with:
    PYTHONPATH=/workspaces/tdash/src python -m pytest tests/test_tdash_argparse.py -v
"""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import call, patch


import td_cli as tdash_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(argv: list[str]):
    """Strict parse – returns Namespace.  Raises SystemExit for invalid input."""
    return tdash_module.build_parser().parse_args(argv)


def _parse_known(argv: list[str]):
    """Lenient parse – returns (Namespace, extras) like parse_known_args."""
    return tdash_module.build_parser().parse_known_args(argv)


# ---------------------------------------------------------------------------
# Phase 1 – common options
# ---------------------------------------------------------------------------

class TestCommonOptions(unittest.TestCase):

    def test_verbose_short_flag(self):
        # Common options must come before the first subcommand token.
        args = _parse(["-v", "scan", "otbr-cli", "router-table"])
        self.assertTrue(args.verbose)

    def test_verbose_long_flag(self):
        args = _parse(["--verbose", "scan", "otbr-cli", "router-table"])
        self.assertTrue(args.verbose)

    def test_debug_short_flag(self):
        args = _parse(["-d", "scan", "otbr-cli", "router-table"])
        self.assertTrue(args.debug)

    def test_debug_long_flag(self):
        args = _parse(["--debug", "scan", "otbr-cli", "router-table"])
        self.assertTrue(args.debug)

    def test_output_short_flag(self):
        args = _parse(["-o", "out.json", "scan", "otbr-cli", "router-table"])
        self.assertEqual(args.output, "out.json")

    def test_output_long_flag(self):
        args = _parse(["--output", "result.json", "scan", "otbr-cli", "router-table"])
        self.assertEqual(args.output, "result.json")

    def test_defaults_are_false_and_none(self):
        args = _parse(["scan", "otbr-cli", "router-table"])
        self.assertFalse(args.verbose)
        self.assertFalse(args.debug)
        self.assertIsNone(args.output)

    def test_help_exits_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                tdash_module.build_parser().parse_args(["--help"])
        self.assertEqual(cm.exception.code, 0)


# ---------------------------------------------------------------------------
# Phase 2 – top-level command routing
# ---------------------------------------------------------------------------

class TestTopLevelCommands(unittest.TestCase):

    def _check_command(self, argv, expected_command):
        args = _parse(argv)
        self.assertEqual(args.command, expected_command)

    def test_no_command_exits_nonzero(self):
        with self.assertRaises(SystemExit) as cm:
            _parse([])
        self.assertNotEqual(cm.exception.code, 0)

    def test_unknown_command_exits_nonzero(self):
        with self.assertRaises(SystemExit) as cm:
            _parse(["bogus"])
        self.assertNotEqual(cm.exception.code, 0)

    def test_command_web_server(self):
        args = _parse(["web-server"])
        self.assertEqual(args.command, "web-server")
        self.assertEqual(args.host, "localhost")
        self.assertEqual(args.port, 8087)

    def test_web_server_custom_host_and_port(self):
        args = _parse(["web-server", "--host", "0.0.0.0", "--port", "9090"])
        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 9090)


# ---------------------------------------------------------------------------
# Phase 3 – scan subcommand tree
# ---------------------------------------------------------------------------

class TestScanParser(unittest.TestCase):

    def test_scan_requires_subcommand(self):
        with self.assertRaises(SystemExit) as cm:
            _parse(["scan"])
        self.assertNotEqual(cm.exception.code, 0)

    def test_scan_otbr_cli_requires_subcommand(self):
        with self.assertRaises(SystemExit):
            _parse(["scan", "otbr-cli"])

    def test_scan_otbr_cli_network_dataset_info(self):
        args = _parse(["scan", "otbr-cli", "network-dataset-info"])
        self.assertEqual(args.command, "scan")
        self.assertEqual(args.scan_type, "otbr-cli")
        self.assertEqual(args.cli_command, "network-dataset-info")

    def test_scan_otbr_cli_router_table(self):
        args = _parse(["scan", "otbr-cli", "router-table"])
        self.assertEqual(args.cli_command, "router-table")

    def test_scan_otbr_cli_meshdiag_topology(self):
        args = _parse(["scan", "otbr-cli", "meshdiag", "topology"])
        self.assertEqual(args.cli_command, "meshdiag")
        self.assertEqual(args.meshdiag_command, "topology")

    def test_scan_otbr_cli_meshdiag_routerneighbortable(self):
        args = _parse(["scan", "otbr-cli", "meshdiag", "routerneighbortable"])
        self.assertEqual(args.meshdiag_command, "routerneighbortable")

    def test_scan_otbr_cli_meshdiag_childtable(self):
        args = _parse(["scan", "otbr-cli", "meshdiag", "childtable"])
        self.assertEqual(args.meshdiag_command, "childtable")

    def test_scan_otbr_cli_meshdiag_childip6(self):
        args = _parse(["scan", "otbr-cli", "meshdiag", "childip6"])
        self.assertEqual(args.meshdiag_command, "childip6")

    def test_scan_otbr_cli_meshdiag_all(self):
        args = _parse(["scan", "otbr-cli", "meshdiag", "all"])
        self.assertEqual(args.meshdiag_command, "all")

    def test_scan_otbr_cli_meshdiag_requires_subcommand(self):
        with self.assertRaises(SystemExit):
            _parse(["scan", "otbr-cli", "meshdiag"])

    def test_scan_otbr_cli_networkdiag_topology(self):
        args = _parse(["scan", "otbr-cli", "networkdiag", "topology"])
        self.assertEqual(args.cli_command, "networkdiag")
        self.assertEqual(args.networkdiag_command, "topology")

    def test_scan_otbr_cli_all(self):
        args = _parse(["scan", "otbr-cli", "all"])
        self.assertEqual(args.cli_command, "all")

    def test_scan_help_exits_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                _parse(["scan", "--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_scan_otbr_cli_help_exits_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                _parse(["scan", "otbr-cli", "--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_scan_otbr_cli_meshdiag_help_exits_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                _parse(["scan", "otbr-cli", "meshdiag", "--help"])
        self.assertEqual(cm.exception.code, 0)


# ---------------------------------------------------------------------------
# Phase 4 – web subcommand tree
# ---------------------------------------------------------------------------

class TestWebParser(unittest.TestCase):

    def test_web_requires_subcommand(self):
        with self.assertRaises(SystemExit):
            _parse(["web"])

    def test_web_otbr_restapi_requires_subcommand(self):
        with self.assertRaises(SystemExit):
            _parse(["web", "otbr-restapi"])

    def test_web_otbr_restapi_download_no_sub_argv(self):
        args, extras = _parse_known(["web", "otbr-restapi", "download"])
        self.assertEqual(args.command, "web")
        self.assertEqual(args.web_type, "otbr-restapi")
        self.assertEqual(args.restapi_command, "download")
        self.assertEqual(extras, [])

    def test_web_otbr_restapi_download_with_sub_argv(self):
        args, extras = _parse_known(["web", "otbr-restapi", "download", "--host", "10.0.0.1", "--port", "8888"])
        self.assertEqual(args.restapi_command, "download")
        self.assertEqual(extras, ["--host", "10.0.0.1", "--port", "8888"])

    def test_web_otbr_restapi_client_sub_argv(self):
        args, extras = _parse_known(["web", "otbr-restapi", "client", "diagnostics", "list"])
        self.assertEqual(args.restapi_command, "client")
        self.assertEqual(extras, ["diagnostics", "list"])

    def test_web_otbr_restapi_rawclient_sub_argv(self):
        args, extras = _parse_known(["web", "otbr-restapi", "rawclient", "actions", "list"])
        self.assertEqual(args.restapi_command, "rawclient")
        self.assertEqual(extras, ["actions", "list"])

    def test_web_help_exits_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                _parse(["web", "--help"])
        self.assertEqual(cm.exception.code, 0)


# ---------------------------------------------------------------------------
# Phase 5 – process and merge subcommand trees
# ---------------------------------------------------------------------------

class TestProcessParser(unittest.TestCase):

    def test_process_requires_subcommand(self):
        with self.assertRaises(SystemExit):
            _parse(["process"])

    def test_process_eve_no_sub_argv(self):
        args, extras = _parse_known(["process", "eve"])
        self.assertEqual(args.command, "process")
        self.assertEqual(args.process_type, "eve")
        self.assertEqual(extras, [])

    def test_process_eve_with_sub_argv(self):
        args, extras = _parse_known(["process", "eve", "--input", "layout.json", "--output", "out.json"])
        self.assertEqual(extras, ["--input", "layout.json", "--output", "out.json"])


class TestMergeParser(unittest.TestCase):

    def test_merge_requires_subcommand(self):
        with self.assertRaises(SystemExit):
            _parse(["merge"])

    def test_merge_dataset_no_sub_argv(self):
        args, extras = _parse_known(["merge", "dataset"])
        self.assertEqual(args.command, "merge")
        self.assertEqual(args.merge_type, "dataset")
        self.assertEqual(extras, [])

    def test_merge_dataset_with_sub_argv(self):
        args, extras = _parse_known(["merge", "dataset", "--input1", "a.json", "--input2", "b.json"])
        self.assertEqual(extras, ["--input1", "a.json", "--input2", "b.json"])


# ---------------------------------------------------------------------------
# Phase 3 – dispatch: scan commands call correct module main()
# ---------------------------------------------------------------------------

class TestDispatchScan(unittest.TestCase):

    def _dispatch(self, argv: list[str]) -> int:
        args, extras = tdash_module.build_parser().parse_known_args(argv)
        return tdash_module.dispatch(args, extras)

    def _mock_module(self, module_attr: str, return_value: int = 0):
        return patch.object(tdash_module, module_attr, **{"main.return_value": return_value})

    def test_scan_network_dataset_info_calls_module_main(self):
        with self._mock_module("otbr_cli_network_dataset_info") as m:
            rc = self._dispatch(["scan", "otbr-cli", "network-dataset-info"])
        m.main.assert_called_once_with()
        self.assertEqual(rc, 0)

    def test_scan_router_table_calls_module_main(self):
        with self._mock_module("otbr_cli_router_table") as m:
            rc = self._dispatch(["scan", "otbr-cli", "router-table"])
        m.main.assert_called_once_with()
        self.assertEqual(rc, 0)

    def test_scan_meshdiag_topology_calls_module_main(self):
        with self._mock_module("otbr_cli_meshdiag_topology") as m:
            rc = self._dispatch(["scan", "otbr-cli", "meshdiag", "topology"])
        m.main.assert_called_once_with()
        self.assertEqual(rc, 0)

    def test_scan_meshdiag_routerneighbortable_calls_module_main(self):
        with self._mock_module("otbr_cli_meshdiag_routerneighbortable") as m:
            rc = self._dispatch(["scan", "otbr-cli", "meshdiag", "routerneighbortable"])
        m.main.assert_called_once_with()
        self.assertEqual(rc, 0)

    def test_scan_meshdiag_childtable_calls_module_main(self):
        with self._mock_module("otbr_cli_meshdiag_childtable") as m:
            rc = self._dispatch(["scan", "otbr-cli", "meshdiag", "childtable"])
        m.main.assert_called_once_with()
        self.assertEqual(rc, 0)

    def test_scan_meshdiag_childip6_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            self._dispatch(["scan", "otbr-cli", "meshdiag", "childip6"])

    def test_scan_meshdiag_all_calls_three_modules(self):
        with (
            self._mock_module("otbr_cli_meshdiag_topology") as mt,
            self._mock_module("otbr_cli_meshdiag_routerneighbortable") as mrn,
            self._mock_module("otbr_cli_meshdiag_childtable") as mct,
        ):
            rc = self._dispatch(["scan", "otbr-cli", "meshdiag", "all"])
        mt.main.assert_called_once_with()
        mrn.main.assert_called_once_with()
        mct.main.assert_called_once_with()
        self.assertEqual(rc, 0)

    def test_scan_networkdiag_topology_calls_module_main(self):
        with self._mock_module("otbr_cli_networkdiag_topology") as m:
            rc = self._dispatch(["scan", "otbr-cli", "networkdiag", "topology"])
        m.main.assert_called_once_with()
        self.assertEqual(rc, 0)

    def test_scan_all_calls_all_modules(self):
        with (
            self._mock_module("otbr_cli_network_dataset_info") as m1,
            self._mock_module("otbr_cli_router_table") as m2,
            self._mock_module("otbr_cli_meshdiag_topology") as m3,
            self._mock_module("otbr_cli_meshdiag_routerneighbortable") as m4,
            self._mock_module("otbr_cli_meshdiag_childtable") as m5,
            self._mock_module("otbr_cli_networkdiag_topology") as m6,
        ):
            rc = self._dispatch(["scan", "otbr-cli", "all"])
        for m in (m1, m2, m3, m4, m5, m6):
            m.main.assert_called_once_with()
        self.assertEqual(rc, 0)

    def test_scan_exit_code_propagates(self):
        with self._mock_module("otbr_cli_network_dataset_info", return_value=5) as m:
            rc = self._dispatch(["scan", "otbr-cli", "network-dataset-info"])
        self.assertEqual(rc, 5)


# ---------------------------------------------------------------------------
# Phase 4 – dispatch: web commands forward sub_argv to module main()
# ---------------------------------------------------------------------------

class TestDispatchWeb(unittest.TestCase):

    def _dispatch(self, argv: list[str]) -> int:
        args, extras = tdash_module.build_parser().parse_known_args(argv)
        return tdash_module.dispatch(args, extras)

    def test_web_download_forwards_sub_argv(self):
        argv = ["web", "otbr-restapi", "download", "--host", "10.0.0.1"]
        args, extras = tdash_module.build_parser().parse_known_args(argv)
        with patch.object(tdash_module.otbr_restapi_download, "main", return_value=0) as m:
            rc = tdash_module.dispatch(args, extras)
        m.assert_called_once_with(["--host", "10.0.0.1"])
        self.assertEqual(rc, 0)

    def test_web_client_forwards_sub_argv(self):
        argv = ["web", "otbr-restapi", "client", "diagnostics", "list"]
        args, extras = tdash_module.build_parser().parse_known_args(argv)
        with patch.object(tdash_module.otbr_restapi_client_cli, "main", return_value=0) as m:
            rc = tdash_module.dispatch(args, extras)
        m.assert_called_once_with(["diagnostics", "list"])
        self.assertEqual(rc, 0)

    def test_web_rawclient_forwards_sub_argv(self):
        argv = ["web", "otbr-restapi", "rawclient", "actions", "list"]
        args, extras = tdash_module.build_parser().parse_known_args(argv)
        with patch.object(tdash_module.otbr_restapi_raw_client_cli, "main", return_value=0) as m:
            rc = tdash_module.dispatch(args, extras)
        m.assert_called_once_with(["actions", "list"])
        self.assertEqual(rc, 0)

    def test_web_exit_code_propagates(self):
        argv = ["web", "otbr-restapi", "download"]
        args, extras = tdash_module.build_parser().parse_known_args(argv)
        with patch.object(tdash_module.otbr_restapi_download, "main", return_value=3) as m:
            rc = tdash_module.dispatch(args, extras)
        self.assertEqual(rc, 3)

    def test_web_download_no_sub_argv(self):
        argv = ["web", "otbr-restapi", "download"]
        args, extras = tdash_module.build_parser().parse_known_args(argv)
        with patch.object(tdash_module.otbr_restapi_download, "main", return_value=0) as m:
            self._dispatch(argv)
        m.assert_called_once_with([])


# ---------------------------------------------------------------------------
# Phase 5 – dispatch: process and merge forward sub_argv to module main()
# ---------------------------------------------------------------------------

class TestDispatchProcess(unittest.TestCase):

    def _dispatch(self, argv: list[str]) -> int:
        args, extras = tdash_module.build_parser().parse_known_args(argv)
        return tdash_module.dispatch(args, extras)

    def test_process_eve_calls_eve_parse_main(self):
        argv = ["process", "eve"]
        with patch.object(tdash_module.eve_parse, "main", return_value=0) as m:
            rc = self._dispatch(argv)
        m.assert_called_once_with([])
        self.assertEqual(rc, 0)

    def test_process_eve_forwards_sub_argv(self):
        argv = ["process", "eve", "--input", "layout.json"]
        args, extras = tdash_module.build_parser().parse_known_args(argv)
        with patch.object(tdash_module.eve_parse, "main", return_value=0) as m:
            tdash_module.dispatch(args, extras)
        m.assert_called_once_with(["--input", "layout.json"])


class TestDispatchMerge(unittest.TestCase):

    def _dispatch(self, argv: list[str]) -> int:
        args, extras = tdash_module.build_parser().parse_known_args(argv)
        return tdash_module.dispatch(args, extras)

    def test_merge_dataset_calls_dataset_merge_main(self):
        argv = ["merge", "dataset"]
        with patch.object(tdash_module.dataset_merge, "main", return_value=0) as m:
            rc = self._dispatch(argv)
        m.assert_called_once_with([])
        self.assertEqual(rc, 0)

    def test_merge_dataset_forwards_sub_argv(self):
        argv = ["merge", "dataset", "--input1", "a.json", "--input2", "b.json"]
        args, extras = tdash_module.build_parser().parse_known_args(argv)
        with patch.object(tdash_module.dataset_merge, "main", return_value=0) as m:
            tdash_module.dispatch(args, extras)
        m.assert_called_once_with(["--input1", "a.json", "--input2", "b.json"])


# ---------------------------------------------------------------------------
# Phase 6 – dispatch: web-server forwards host/port to tdash_web.main()
# ---------------------------------------------------------------------------

class TestDispatchWebServer(unittest.TestCase):

    def _dispatch(self, argv: list[str]) -> int:
        args, extras = tdash_module.build_parser().parse_known_args(argv)
        return tdash_module.dispatch(args, extras)

    def test_web_server_default_host_and_port(self):
        argv = ["web-server"]
        with patch.object(tdash_module.tdash_web, "main", return_value=0) as m:
            rc = self._dispatch(argv)
        m.assert_called_once_with(["--host", "localhost", "--port", "8087"])
        self.assertEqual(rc, 0)

    def test_web_server_custom_host_and_port(self):
        argv = ["web-server", "--host", "0.0.0.0", "--port", "9090"]
        with patch.object(tdash_module.tdash_web, "main", return_value=0) as m:
            rc = self._dispatch(argv)
        m.assert_called_once_with(["--host", "0.0.0.0", "--port", "9090"])


# ---------------------------------------------------------------------------
# main() integration: --debug sets logging level
# ---------------------------------------------------------------------------

class TestMainLogging(unittest.TestCase):

    def test_main_debug_flag_sets_debug_level(self):
        import logging
        argv = ["--debug", "scan", "otbr-cli", "router-table"]
        with patch.object(tdash_module.otbr_cli_router_table, "main", return_value=0):
            tdash_module.main(argv)
        self.assertEqual(logging.getLogger().level, logging.DEBUG)
        # reset so other tests are not affected
        logging.getLogger().setLevel(logging.WARNING)


if __name__ == "__main__":
    unittest.main()
