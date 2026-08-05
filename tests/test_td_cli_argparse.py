"""Tests for td_cli.py build_parser(), dispatch(), and main()."""

from __future__ import annotations

import io
import logging
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import call, patch

import td_cli
import td_webserver
import otbr_cli_networkdiag_topology


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

    def test_webserver_module_accepts_file_cache_max_age(self):
        parser = td_webserver.build_parser()
        args = parser.parse_args(["--file-cache-max-age", "120"])
        self.assertEqual(args.file_cache_max_age, 120)

    def test_webserver_module_rejects_negative_file_cache_max_age(self):
        parser = td_webserver.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--file-cache-max-age", "-1"])

    def test_webserver_module_cli_cache_max_age_overrides_env(self):
        parser = td_webserver.build_parser()
        with patch.dict(os.environ, {"TD_FILE_CACHE_MAX_AGE": "600"}, clear=True):
            args = parser.parse_args(["--file-cache-max-age", "42"])
            value, source = td_webserver._resolve_file_cache_max_age(args, parser)
        self.assertEqual(value, 42)
        self.assertEqual(source, "cli")


# ---------------------------------------------------------------------------
# Parser: nested command trees and passthrough extras
# ---------------------------------------------------------------------------


class TestOtbrCliParser(unittest.TestCase):
    def test_otbr_cli_without_subcommand_is_allowed(self):
        args = _parse(["otbr-cli"])
        self.assertEqual(args.command, "otbr-cli")
        self.assertIsNone(args.cli_command)

    def test_meshdiag_without_subcommand_is_allowed(self):
        args = _parse(["otbr-cli", "meshdiag"])
        self.assertEqual(args.cli_command, "meshdiag")
        self.assertIsNone(args.meshdiag_command)

    def test_networkdiag_without_subcommand_is_allowed(self):
        args = _parse(["otbr-cli", "networkdiag"])
        self.assertEqual(args.cli_command, "networkdiag")
        self.assertIsNone(args.networkdiag_command)

    def test_meshdiag_childip6(self):
        args = _parse(["otbr-cli", "meshdiag", "childip6"])
        self.assertEqual(args.cli_command, "meshdiag")
        self.assertEqual(args.meshdiag_command, "childip6")

    def test_networkdiag_topology_default_children(self):
        args = _parse(["otbr-cli", "networkdiag", "fetch-all"])
        self.assertEqual(args.cli_command, "networkdiag")
        self.assertEqual(args.networkdiag_command, "fetch-all")
        self.assertTrue(args.expand_children)

    def test_networkdiag_topology_children_no(self):
        args = _parse(["otbr-cli", "networkdiag",
                      "fetch-all", "--children-no"])
        self.assertFalse(args.expand_children)

    def test_networkdiag_topology_multicast_network(self):
        args = _parse(["otbr-cli", "networkdiag",
                      "multicast-network"])
        self.assertEqual(args.cli_command, "networkdiag")
        self.assertEqual(args.networkdiag_command,
                         "multicast-network")

    def test_networkdiag_topology_multicast_neighbors(self):
        args = _parse(["otbr-cli", "networkdiag",
                      "multicast-neighbors"])
        self.assertEqual(args.cli_command, "networkdiag")
        self.assertEqual(args.networkdiag_command,
                         "multicast-neighbors")

    def test_networkdiag_old_topology_command_no_longer_valid(self):
        with self.assertRaises(SystemExit):
            _parse(["otbr-cli", "networkdiag", "topology"])

    def test_otbr_cli_topology(self):
        args = _parse(["otbr-cli", "topology"])
        self.assertEqual(args.command, "otbr-cli")
        self.assertEqual(args.cli_command, "topology")


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

    def test_meshdiag_without_subcommand_prints_help(self):
        parser = td_cli.build_parser()
        args, extras = parser.parse_known_args(["otbr-cli", "meshdiag"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = td_cli.dispatch(args, extras, parser)
        self.assertEqual(rc, 0)
        self.assertIn("usage: td_cli otbr-cli meshdiag", buf.getvalue())

    def test_networkdiag_without_subcommand_prints_help(self):
        parser = td_cli.build_parser()
        args, extras = parser.parse_known_args(["otbr-cli", "networkdiag"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = td_cli.dispatch(args, extras, parser)
        self.assertEqual(rc, 0)
        self.assertIn("usage: td_cli otbr-cli networkdiag", buf.getvalue())

    def test_meshdiag_childip6_calls_module_main(self):
        with patch.object(
            td_cli.otbr_cli_meshdiag_childip6, "main", return_value=0
        ) as m:
            rc = self._dispatch(["otbr-cli", "meshdiag", "childip6"])
        m.assert_called_once_with([])
        self.assertEqual(rc, 0)

    def test_meshdiag_all_is_invalid_choice(self):
        with self.assertRaises(SystemExit):
            _parse(["otbr-cli", "meshdiag", "all"])

    def test_networkdiag_children_no_forwards_cno(self):
        with patch.object(
            td_cli.otbr_cli_networkdiag_topology, "main", return_value=0
        ) as m:
            rc = self._dispatch(
                ["otbr-cli", "networkdiag", "fetch-all", "--children-no"]
            )
        m.assert_called_once_with(
            [
                "fetch-all",
                "-cno",
                "--children-fetch-fast",
                "--children-fetch-detail-no",
            ]
        )
        self.assertEqual(rc, 0)

    def test_router_table_none_return_keeps_compat_success(self):
        with patch.object(td_cli.otbr_cli_router_table, "main", return_value=None) as m:
            rc = self._dispatch(["otbr-cli", "router-table"])
        m.assert_called_once_with([])
        self.assertEqual(rc, 0)

    def test_router_table_non_int_return_is_internal_error(self):
        with patch.object(td_cli.otbr_cli_router_table, "main", return_value="bad") as m:
            rc = self._dispatch(["otbr-cli", "router-table"])
        m.assert_called_once_with([])
        self.assertEqual(rc, 1)

    def test_topology_calls_all_steps_in_required_order(self):
        order: list[str] = []

        def _mark(name: str):
            def _inner(_argv):
                order.append(name)
                return 0
            return _inner

        with patch.object(
            td_cli.otbr_cli_thread_network_info, "main", side_effect=_mark("thread-network-info")
        ) as m_thread_info, patch.object(
            td_cli.otbr_cli_router_table, "main", side_effect=_mark("router-table")
        ) as m_router_table, patch.object(
            td_cli.otbr_cli_meshdiag_topology, "main", side_effect=_mark("meshdiag-topology")
        ) as m_meshdiag_topology, patch.object(
            td_cli.otbr_cli_networkdiag_topology, "main", side_effect=lambda argv: _mark(
                f"networkdiag-{argv[0]}"
            )(argv)
        ) as m_networkdiag, patch.object(
            td_cli.otbr_cli_meshdiag_routerneighbortable,
            "main",
            side_effect=_mark("meshdiag-routerneighbortable"),
        ) as m_meshdiag_neighbors, patch.object(
            td_cli.otbr_cli_meshdiag_childtable, "main", side_effect=_mark("meshdiag-childtable")
        ) as m_meshdiag_childtable:
            rc = self._dispatch(["otbr-cli", "topology"])

        self.assertEqual(rc, 0)
        self.assertEqual(
            order,
            [
                "thread-network-info",
                "router-table",
                "meshdiag-topology",
                "networkdiag-multicast-network",
                "networkdiag-fetch-all",
                "meshdiag-routerneighbortable",
                "meshdiag-childtable",
            ],
        )
        self.assertEqual(
            [
                m_thread_info.call_args_list,
                m_router_table.call_args_list,
                m_meshdiag_topology.call_args_list,
                m_networkdiag.call_args_list,
                m_meshdiag_neighbors.call_args_list,
                m_meshdiag_childtable.call_args_list,
            ],
            [
                [call([])],
                [call([])],
                [call([])],
                [call(["multicast-network"]), call(["fetch-all"])],
                [call([])],
                [call([])],
            ],
        )

    def test_topology_best_effort_runs_all_steps_on_failure(self):
        with patch.object(
            td_cli.otbr_cli_thread_network_info, "main", return_value=0
        ) as m_thread_info, patch.object(
            td_cli.otbr_cli_router_table, "main", return_value=4
        ) as m_router_table, patch.object(
            td_cli.otbr_cli_meshdiag_topology, "main", return_value=0
        ) as m_meshdiag_topology, patch.object(
            td_cli.otbr_cli_networkdiag_topology, "main", return_value=0
        ) as m_networkdiag, patch.object(
            td_cli.otbr_cli_meshdiag_routerneighbortable, "main", return_value=0
        ) as m_meshdiag_neighbors, patch.object(
            td_cli.otbr_cli_meshdiag_childtable, "main", return_value=0
        ) as m_meshdiag_childtable:
            rc = self._dispatch(["otbr-cli", "topology"])

        self.assertEqual(rc, 4)
        for mocked in (
            m_thread_info,
            m_router_table,
            m_meshdiag_topology,
            m_meshdiag_neighbors,
            m_meshdiag_childtable,
        ):
            mocked.assert_called_once_with([])
        self.assertEqual(
            m_networkdiag.call_args_list,
            [call(["multicast-network"]), call(["fetch-all"])],
        )

    def test_topology_forwards_datadir_to_every_step(self):
        with patch.object(
            td_cli.otbr_cli_thread_network_info, "main", return_value=0
        ) as m_thread_info, patch.object(
            td_cli.otbr_cli_router_table, "main", return_value=0
        ) as m_router_table, patch.object(
            td_cli.otbr_cli_meshdiag_topology, "main", return_value=0
        ) as m_meshdiag_topology, patch.object(
            td_cli.otbr_cli_networkdiag_topology, "main", return_value=0
        ) as m_networkdiag, patch.object(
            td_cli.otbr_cli_meshdiag_routerneighbortable, "main", return_value=0
        ) as m_meshdiag_neighbors, patch.object(
            td_cli.otbr_cli_meshdiag_childtable, "main", return_value=0
        ) as m_meshdiag_childtable:
            rc = self._dispatch(["--datadir", "/tmp/td", "otbr-cli", "topology"])

        self.assertEqual(rc, 0)
        expected_argv = ["--datadir", "/tmp/td"]
        for mocked in (
            m_thread_info,
            m_router_table,
            m_meshdiag_topology,
            m_meshdiag_neighbors,
            m_meshdiag_childtable,
        ):
            mocked.assert_called_once_with(expected_argv)
        self.assertEqual(
            m_networkdiag.call_args_list,
            [
                call(["--datadir", "/tmp/td", "multicast-network"]),
                call(["--datadir", "/tmp/td", "fetch-all"]),
            ],
        )


class TestNetworkdiagModuleDispatch(unittest.TestCase):
    def test_fetch_all_forwards_command_options(self):
        with patch.object(
            otbr_cli_networkdiag_topology, "main_fetch_all", return_value=0
        ) as handler:
            rc = otbr_cli_networkdiag_topology.main(
                ["fetch-all", "--children-no"]
            )
        handler.assert_called_once_with(["--children-no"])
        self.assertEqual(rc, 0)

    def test_multicast_network_forwards_datadir(self):
        with patch.object(
            otbr_cli_networkdiag_topology, "main_multicast_network", return_value=0
        ) as handler:
            rc = otbr_cli_networkdiag_topology.main(
                ["--datadir", "/tmp/td", "multicast-network"]
            )
        handler.assert_called_once_with(["--datadir", "/tmp/td"])
        self.assertEqual(rc, 0)

    def test_multicast_neighbors_dispatches_to_handler(self):
        with patch.object(
            otbr_cli_networkdiag_topology, "main_multicast_neighbors", return_value=0
        ) as handler:
            rc = otbr_cli_networkdiag_topology.main(["multicast-neighbors"])
        handler.assert_called_once_with([])
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

    def test_restapi_actions_without_subcommand_prints_help(self):
        parser = td_cli.build_parser()
        args, extras = parser.parse_known_args(["otbr-restapi", "actions"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = td_cli.dispatch(args, extras, parser)
        self.assertEqual(rc, 0)
        self.assertIn("usage:", buf.getvalue())
        self.assertIn("{list,get,enqueue}", buf.getvalue())

    def test_restapi_node_without_subcommand_prints_help(self):
        parser = td_cli.build_parser()
        args, extras = parser.parse_known_args(["otbr-restapi", "node"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = td_cli.dispatch(args, extras, parser)
        self.assertEqual(rc, 0)
        self.assertIn("usage:", buf.getvalue())
        self.assertIn("{get,state,dataset}", buf.getvalue())

    def test_restapi_devices_without_subcommand_prints_help(self):
        parser = td_cli.build_parser()
        args, extras = parser.parse_known_args(["otbr-restapi", "devices"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = td_cli.dispatch(args, extras, parser)
        self.assertEqual(rc, 0)
        self.assertIn("usage:", buf.getvalue())
        self.assertIn("{list,get,fetch}", buf.getvalue())

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

    def test_restapi_all_global_options_forwarded_before_resource(self):
        argv = [
            "otbr-restapi",
            "--host", "192.168.1.2",
            "--port", "9090",
            "--base-url", "http://otbr.test:8081",
            "--timeout", "12",
            "--accept", "application/json",
            "--output", "result.json",
            "--datadir", "/tmp/td-rest",
            "--raw",
            "--poll-interval", "0.5",
            "--poll-timeout", "40",
            "--no-progress",
            "--no-auto-output",
            "--debug",
            "--lab",
            "devices", "list",
        ]
        with patch.object(td_cli.otbr_restapi_cli, "main", return_value=0) as mocked_main:
            rc = self._dispatch(argv)

        forwarded = mocked_main.call_args.args[0]
        resource_index = forwarded.index("devices")
        for option in (
            "--host",
            "--port",
            "--base-url",
            "--timeout",
            "--accept",
            "--output",
            "--datadir",
            "--raw",
            "--poll-interval",
            "--poll-timeout",
            "--no-progress",
            "--no-auto-output",
            "--debug",
            "--lab",
        ):
            self.assertIn(option, forwarded)
            self.assertLess(forwarded.index(option), resource_index)
        self.assertEqual(rc, 0)

    def test_restapi_frontend_exposes_all_subordinate_global_options(self):
        frontend_parser = td_cli._find_child_subparser(
            td_cli.build_parser(), "otbr-restapi"
        )
        self.assertIsNotNone(frontend_parser)
        subordinate_parser = td_cli.otbr_restapi_cli.build_parser()

        frontend_options = {
            option
            for action in frontend_parser._actions
            for option in action.option_strings
        }
        subordinate_options = {
            option
            for action in subordinate_parser._actions
            for option in action.option_strings
        }

        self.assertEqual(subordinate_options - frontend_options, set())

    def test_process_eve_forwards_extras(self):
        argv = ["process-eve", "--input", "layout.evethreadlayout"]
        with patch.object(td_cli.eve_process, "main", return_value=0) as m:
            rc = self._dispatch(argv)
        m.assert_called_once_with(["--input", "layout.evethreadlayout"])
        self.assertEqual(rc, 0)

    def test_merge_dataset_forwards_extras(self):
        argv = ["merge-dataset", "--input1", "a.json"]
        with patch.object(td_cli.merge_dataset, "main", return_value=0) as m:
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

    def test_main_typo_restapi_subcommand_prints_help_and_returns_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = td_cli.main(["otbr-restapi", "device"])
        self.assertEqual(rc, 0)
        self.assertIn("usage: td_cli otbr-restapi", buf.getvalue())

    def test_main_typo_meshdiag_subcommand_prints_help_and_returns_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = td_cli.main(["otbr-cli", "meshdiag", "topologg"])
        self.assertEqual(rc, 0)
        self.assertIn("usage: td_cli otbr-cli meshdiag", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
