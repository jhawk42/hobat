from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

import td_cli


def _dispatch(argv: list[str]) -> int:
    parser = td_cli.build_parser()
    args, extras = parser.parse_known_args(argv)
    return td_cli.dispatch(args, extras, parser)


@pytest.mark.parametrize(
    ("argv", "module_name", "expected_argv"),
    [
        (
            ["--datadir", "/tmp/td", "process-eve", "--input", "eve.json"],
            "eve_process",
            ["--datadir", "/tmp/td", "--input", "eve.json"],
        ),
        (
            ["merge-dataset", "--input", "source.json"],
            "merge_dataset",
            ["--input", "source.json"],
        ),
        (
            ["merge-data", "--input", "source.json"],
            "merge_dataset",
            ["--input", "source.json"],
        ),
        (
            ["merge-extaddr", "--input", "topology.json"],
            "merge_extaddr_device_label_map",
            ["--input", "topology.json"],
        ),
        (
            ["otbr-restapi", "download", "--url", "http://otbr.test"],
            "otbr_restapi_download",
            ["--url", "http://otbr.test"],
        ),
    ],
)
def test_family_forwarding_matrix(argv, module_name, expected_argv):
    module = getattr(td_cli, module_name)
    with patch.object(module, "main", return_value=7) as module_main:
        rc = _dispatch(argv)

    module_main.assert_called_once_with(expected_argv)
    assert rc == 7


@pytest.mark.parametrize(
    ("argv", "module_name", "expected_argv"),
    [
        (["otbr-cli", "thread-network-info"], "otbr_cli_thread_network_info", []),
        (["otbr-cli", "router-table"], "otbr_cli_router_table", []),
        (["otbr-cli", "meshdiag", "topology"], "otbr_cli_meshdiag_topology", []),
        (
            ["otbr-cli", "meshdiag", "routerneighbortable"],
            "otbr_cli_meshdiag_routerneighbortable",
            [],
        ),
        (["otbr-cli", "meshdiag", "childtable"], "otbr_cli_meshdiag_childtable", []),
        (["otbr-cli", "meshdiag", "childip6"], "otbr_cli_meshdiag_childip6", []),
        (
            ["otbr-cli", "networkdiag", "multicast-network"],
            "otbr_cli_networkdiag_topology",
            ["multicast-network"],
        ),
        (
            ["otbr-cli", "networkdiag", "multicast-neighbors"],
            "otbr_cli_networkdiag_topology",
            ["multicast-neighbors"],
        ),
        (
            ["otbr-cli", "networkdiag", "fetch-all"],
            "otbr_cli_networkdiag_topology",
            ["fetch-all", "--children-fetch-fast", "--children-fetch-detail-no"],
        ),
    ],
)
def test_otbr_cli_leaf_dispatch_matrix(argv, module_name, expected_argv):
    module = getattr(td_cli, module_name)
    with patch.object(module, "main", return_value=0) as module_main:
        assert _dispatch(argv) == 0

    module_main.assert_called_once_with(expected_argv)


@pytest.mark.parametrize(
    "resource",
    ["node", "devices", "diagnostics", "actions", "mesh-diagnostics", "topology"],
)
def test_restapi_resource_dispatch_matrix(resource):
    with patch.object(td_cli.otbr_restapi_cli, "main", return_value=0) as module_main:
        assert _dispatch(["otbr-restapi", resource, "list"]) == 0

    module_main.assert_called_once_with([resource, "list"])


def test_restapi_global_options_preserve_exact_forwarding_order():
    argv = [
        "--datadir", "/tmp/td", "otbr-restapi",
        "--output", "result.json", "--host", "otbr.test", "--port", "9090",
        "--base-url", "http://otbr.test", "--timeout", "12",
        "--accept", "application/json", "--raw", "--poll-interval", "0.5",
        "--poll-timeout", "40", "--no-progress", "--no-auto-output",
        "--debug", "--lab", "devices", "list",
    ]
    with patch.object(td_cli.otbr_restapi_cli, "main", return_value=0) as module_main:
        assert _dispatch(argv) == 0

    module_main.assert_called_once_with(
        [
            "--datadir", "/tmp/td", "--output", "result.json",
            "--host", "otbr.test", "--port", "9090",
            "--base-url", "http://otbr.test", "--timeout", "12",
            "--accept", "application/json", "--raw", "--poll-interval", "0.5",
            "--poll-timeout", "40.0", "--no-progress", "--no-auto-output",
            "--debug", "--lab", "devices", "list",
        ]
    )


@pytest.mark.parametrize(("raw_rc", "expected_rc"), [(None, 0), (5, 5), ("bad", 1)])
def test_family_return_codes_use_shared_normalization(raw_rc, expected_rc):
    with patch.object(td_cli.eve_process, "main", return_value=raw_rc):
        assert _dispatch(["process-eve"]) == expected_rc


@pytest.mark.parametrize(
    "argv",
    [
        ["otbr-restapi", "node", "state", "get"],
        ["otbr-restapi", "node", "dataset", "active", "get"],
        ["otbr-restapi", "actions", "enqueue", "get-network-diagnostic"],
        ["otbr-restapi", "actions", "list", "add-thread-device"],
    ],
)
def test_non_experimental_rest_commands_are_not_lab_gated(argv):
    with patch.object(td_cli.otbr_restapi_cli, "main", return_value=0) as module_main:
        assert _dispatch(argv) == 0

    module_main.assert_called_once()


def test_experimental_rest_command_metadata_is_exact():
    assert td_cli._EXPERIMENTAL_RESTAPI_COMMANDS == {
        ("node", "state", "set"),
        ("node", "dataset", "active", "set"),
        ("actions", "enqueue", "add-thread-device"),
        ("actions", "enqueue", "reset-network-diag-counter"),
    }


def test_dispatch_rejects_unknown_family():
    parser = td_cli.build_parser()
    args = argparse.Namespace(command="unknown", datadir=None)

    with pytest.raises(ValueError, match="Unhandled command: unknown"):
        td_cli.dispatch(args, [], parser)