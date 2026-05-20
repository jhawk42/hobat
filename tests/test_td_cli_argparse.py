"""Tests for td_cli.py build_parser(), dispatch(), and main()."""

from __future__ import annotations

import io
import logging
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import td_cli
import td_webserver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(argv: list[str]):
    """Strict parse. Raises SystemExit on invalid input."""
    return td_cli.build_parser().parse_args(argv)


def _parse_known(argv: list[str]):
    """Lenient parse for command forwarding tests."""
    return td_cli.build_parser().parse_known_args(argv)


# ---------------------------------------------------------------------------
# Parser: common options and top-level commands
# ---------------------------------------------------------------------------


class TestCommonOptions(unittest.TestCase):
    def test_verbose_short_flag(self):
        args = _parse(["-v", "otbr-cli", "router-table"])
        self.assertTrue(args.verbose)

    def test_debug_long_flag(self):
        args = _parse(["--debug", "otbr-cli", "router-table"])
        self.assertTrue(args.debug)

    def test_output_and_datadir(self):
        args = _parse(["--output", "out.json", "--datadir",
                      "/tmp/td", "merge-dataset"])
        self.assertEqual(args.output, "out.json")
        self.assertEqual(args.datadir, "/tmp/td")

    def test_help_exits_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                td_cli.build_parser().parse_args(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_no_command_is_error(self):
        with self.assertRaises(SystemExit) as cm:
            _parse([])
        self.assertNotEqual(cm.exception.code, 0)


class TestTopLevelCommands(unittest.TestCase):
    def test_otbr_cli_command(self):
        args = _parse(["otbr-cli", "router-table"])
        self.assertEqual(args.command, "otbr-cli")
        self.assertEqual(args.cli_command, "router-table")

    def test_otbr_restapi_command(self):
        args = _parse(["otbr-restapi", "download"])
        self.assertEqual(args.command, "otbr-restapi")
        self.assertEqual(args.restapi_command, "download")

    def test_mdns_defaults(self):
        args = _parse(["mdns"])
        self.assertEqual(args.command, "mdns")
        self.assertEqual(args.mdns_scope, "thread")
        self.assertIsNone(args.browse_timeout)
        self.assertFalse(args.haptcp)
        self.assertFalse(args.mattertcpsupported)

    def test_process_eve_command(self):
        args = _parse(["process-eve"])
        self.assertEqual(args.command, "process-eve")

    def test_merge_dataset_command(self):
        args = _parse(["merge-dataset"])
        self.assertEqual(args.command, "merge-dataset")

    def test_webserver_module_defaults(self):
        parser = td_webserver.build_parser()
        args = parser.parse_args([])
        self.assertEqual(args.port, 9165)


# ---------------------------------------------------------------------------
# Parser: nested command trees and passthrough extras
# ---------------------------------------------------------------------------


class TestOtbrCliParser(unittest.TestCase):
    def test_otbr_cli_without_subcommand_is_allowed(self):
        args = _parse(["otbr-cli"])
        self.assertEqual(args.command, "otbr-cli")
        self.assertIsNone(args.cli_command)

    def test_meshdiag_requires_subcommand(self):
        with self.assertRaises(SystemExit):
            _parse(["otbr-cli", "meshdiag"])

    def test_meshdiag_childip6(self):
        args = _parse(["otbr-cli", "meshdiag", "childip6"])
        self.assertEqual(args.cli_command, "meshdiag")
        self.assertEqual(args.meshdiag_command, "childip6")

    def test_networkdiag_topology_default_children(self):
        args = _parse(["otbr-cli", "networkdiag", "topology-poll"])
        self.assertEqual(args.cli_command, "networkdiag")
        self.assertEqual(args.networkdiag_command, "topology-poll")
        self.assertTrue(args.expand_children)

    def test_networkdiag_topology_children_no(self):
        args = _parse(["otbr-cli", "networkdiag",
                      "topology-poll", "--children-no"])
        self.assertFalse(args.expand_children)

    def test_networkdiag_topology_multicast_network(self):
        args = _parse(["otbr-cli", "networkdiag",
                      "topology-multicast-network"])
        self.assertEqual(args.cli_command, "networkdiag")
        self.assertEqual(args.networkdiag_command,
                         "topology-multicast-network")

    def test_networkdiag_topology_multicast_neighbors(self):
        args = _parse(["otbr-cli", "networkdiag",
                      "topology-multicast-neighbors"])
        self.assertEqual(args.cli_command, "networkdiag")
        self.assertEqual(args.networkdiag_command,
                         "topology-multicast-neighbors")

    def test_networkdiag_old_topology_command_no_longer_valid(self):
        with self.assertRaises(SystemExit):
            _parse(["otbr-cli", "networkdiag", "topology"])


class TestForwardingParsers(unittest.TestCase):
    def test_restapi_devices_extras_preserved(self):
        args, extras = _parse_known(
            ["otbr-restapi", "devices", "list"])
        self.assertEqual(args.restapi_command, "devices")
        self.assertEqual(extras, ["list"])

    def test_restapi_node_extras_preserved(self):
        args, extras = _parse_known(["otbr-restapi", "node", "get"])
        self.assertEqual(args.restapi_command, "node")
        self.assertEqual(extras, ["get"])

    def test_restapi_client_subcommand_is_removed(self):
        with self.assertRaises(SystemExit):
            _parse(["otbr-restapi", "client", "devices", "list"])

    def test_process_eve_extras_preserved(self):
        args, extras = _parse_known(["process-eve", "--input", "layout.json"])
        self.assertEqual(args.command, "process-eve")
        self.assertEqual(extras, ["--input", "layout.json"])

    def test_merge_dataset_extras_preserved(self):
        args, extras = _parse_known(
            ["merge-dataset", "--input1", "a.json", "--input2", "b.json"]
        )
        self.assertEqual(args.command, "merge-dataset")
        self.assertEqual(extras, ["--input1", "a.json", "--input2", "b.json"])


# ---------------------------------------------------------------------------
# Dispatch behavior
# ---------------------------------------------------------------------------


class TestDispatchOtbrCli(unittest.TestCase):
    def _dispatch(self, argv: list[str]) -> int:
        parser = td_cli.build_parser()
        args, extras = parser.parse_known_args(argv)
        return td_cli.dispatch(args, extras, parser)

    def test_router_table_calls_module_main(self):
        with patch.object(td_cli.otbr_cli_router_table, "main", return_value=0) as m:
            rc = self._dispatch(["otbr-cli", "router-table"])
        m.assert_called_once_with([])
        self.assertEqual(rc, 0)

    def test_meshdiag_childip6_calls_module_main(self):
        with patch.object(
            td_cli.otbr_cli_meshdiag_childip6, "main", return_value=0
        ) as m:
            rc = self._dispatch(["otbr-cli", "meshdiag", "childip6"])
        m.assert_called_once_with([])
        self.assertEqual(rc, 0)

    def test_meshdiag_all_calls_all_meshdiag_modules(self):
        with (
            patch.object(
                td_cli.otbr_cli_meshdiag_topology, "main", return_value=0
            ) as mt,
            patch.object(
                td_cli.otbr_cli_meshdiag_routerneighbortable, "main", return_value=0
            ) as mr,
            patch.object(
                td_cli.otbr_cli_meshdiag_childtable, "main", return_value=0
            ) as mc,
            patch.object(
                td_cli.otbr_cli_meshdiag_childip6, "main", return_value=0
            ) as mi,
        ):
            rc = self._dispatch(["otbr-cli", "meshdiag", "all"])
        mt.assert_called_once_with([])
        mr.assert_called_once_with([])
        mc.assert_called_once_with([])
        mi.assert_called_once_with([])
        self.assertEqual(rc, 0)

    def test_networkdiag_children_no_forwards_cno(self):
        with patch.object(
            td_cli.otbr_cli_networkdiag_topology, "main", return_value=0
        ) as m:
            rc = self._dispatch(
                ["otbr-cli", "networkdiag", "topology-poll", "--children-no"]
            )
        m.assert_called_once_with(["-cno"])
        self.assertEqual(rc, 0)


class TestDispatchOtherCommands(unittest.TestCase):
    def _dispatch(self, argv: list[str]) -> int:
        parser = td_cli.build_parser()
        args, extras = parser.parse_known_args(argv)
        return td_cli.dispatch(args, extras, parser)

    def test_mdns_builds_expected_argv(self):
        argv = [
            "mdns",
            "hap",
            "--browse-timeout",
            "3",
            "--haptcp",
            "--mattertcpsupported",
        ]
        with patch.object(td_cli.mdns_thread_scopes, "main", return_value=0) as m:
            rc = self._dispatch(argv)
        m.assert_called_once_with(
            ["hap", "--browse-timeout", "3.0", "--haptcp", "--mattertcpsupported"]
        )
        self.assertEqual(rc, 0)

    def test_restapi_download_forwards_extras(self):
        argv = [
            "otbr-restapi",
            "download",
            "--url",
            "http://localhost:8080/api/v1/diagnostics",
        ]
        with patch.object(td_cli.otbr_restapi_download, "main", return_value=0) as m:
            rc = self._dispatch(argv)
        m.assert_called_once_with(
            ["--url", "http://localhost:8080/api/v1/diagnostics"])
        self.assertEqual(rc, 0)

    def test_restapi_devices_list_dispatches_to_restapi_cli(self):
        with patch.object(td_cli.otbr_restapi_cli, "main", return_value=0) as m:
            rc = self._dispatch(["otbr-restapi", "devices", "list"])
        m.assert_called_once_with(["devices", "list"])
        self.assertEqual(rc, 0)

    def test_restapi_diagnostics_fetch_all_dispatches(self):
        with patch.object(td_cli.otbr_restapi_cli, "main", return_value=0) as m:
            rc = self._dispatch(
                ["otbr-restapi", "diagnostics", "fetch-all", "--preset", "recommended"]
            )
        m.assert_called_once_with(
            ["diagnostics", "fetch-all", "--preset", "recommended"]
        )
        self.assertEqual(rc, 0)

    def test_restapi_global_host_forwarded_before_resource(self):
        """Global --host must appear before the resource name in forwarded argv."""
        with patch.object(td_cli.otbr_restapi_cli, "main", return_value=0) as m:
            rc = self._dispatch(
                ["otbr-restapi", "--host", "192.168.1.1", "devices", "list"]
            )
        forwarded = m.call_args[0][0]
        self.assertIn("--host", forwarded)
        self.assertIn("devices", forwarded)
        self.assertLess(forwarded.index("--host"), forwarded.index("devices"))
        self.assertEqual(rc, 0)

    def test_restapi_raw_flag_forwarded(self):
        with patch.object(td_cli.otbr_restapi_cli, "main", return_value=0) as m:
            rc = self._dispatch(["otbr-restapi", "--raw", "devices", "list"])
        forwarded = m.call_args[0][0]
        self.assertIn("--raw", forwarded)
        self.assertLess(forwarded.index("--raw"), forwarded.index("devices"))
        self.assertEqual(rc, 0)

    def test_process_eve_forwards_extras(self):
        argv = ["process-eve", "--input", "layout.evethreadlayout"]
        with patch.object(td_cli.eve_parse, "main", return_value=0) as m:
            rc = self._dispatch(argv)
        m.assert_called_once_with(["--input", "layout.evethreadlayout"])
        self.assertEqual(rc, 0)

    def test_merge_dataset_forwards_extras(self):
        argv = ["merge-dataset", "--input1", "a.json"]
        with patch.object(td_cli.dataset_merge, "main", return_value=0) as m:
            rc = self._dispatch(argv)
        m.assert_called_once_with(["--input1", "a.json"])
        self.assertEqual(rc, 0)

    def test_webserver_module_accepts_host_port(self):
        with patch.object(td_webserver, "main", return_value=0) as m:
            rc = td_webserver.main(["--host", "0.0.0.0", "--port", "9090"])
        self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------


class TestMain(unittest.TestCase):
    def test_main_no_argv_prints_help_and_returns_zero(self):
        with patch.object(td_cli, "build_parser") as mock_build:
            parser = td_cli.build_parser()
            mock_build.return_value = parser
            with patch.object(parser, "print_help") as help_mock:
                rc = td_cli.main([])
        help_mock.assert_called_once_with()
        self.assertEqual(rc, 0)

    def test_main_debug_flag_sets_root_logger_debug(self):
        logging.getLogger().setLevel(logging.INFO)
        with patch.object(td_cli.otbr_cli_router_table, "main", return_value=0):
            td_cli.main(["--debug", "otbr-cli", "router-table"])
        self.assertEqual(logging.getLogger().level, logging.DEBUG)


if __name__ == "__main__":
    unittest.main()
