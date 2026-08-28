from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

import otbr_restapi_cli as rest_cli
from td_const import (
    OTBR_RESTAPI_ACTIONS_LIST_FILENAME,
    OTBR_RESTAPI_DEVICES_FETCH_FILENAME,
    OTBR_RESTAPI_DEVICES_LIST_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_LIST_FILENAME,
    OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_FILENAME,
)


AUTOMATIC_JSON = "automatic JSON output"
EXPLICIT_JSON = "explicit-only JSON output"
EXPLICIT_TEXT = "explicit plain-text output"
COMPOSITE = "composite"
ALREADY_OWNED = "already-owned output"


@dataclass(frozen=True)
class PersistenceContract:
    command: str
    classification: str
    current_owner: str


COMMAND_CONTRACTS = (
    PersistenceContract("otbr-cli thread-network-info", AUTOMATIC_JSON, "collect_thread_network_info"),
    PersistenceContract("otbr-cli router-table", AUTOMATIC_JSON, "fetch_and_parse_router_table"),
    PersistenceContract("otbr-cli meshdiag topology", AUTOMATIC_JSON, "get_meshdiag_topology"),
    PersistenceContract("otbr-cli meshdiag routerneighbortable", AUTOMATIC_JSON, "fetch_all_meshdiag_router_neighbor_tables"),
    PersistenceContract("otbr-cli meshdiag childtable", AUTOMATIC_JSON, "fetch_all_meshdiag_child_tables"),
    PersistenceContract("otbr-cli meshdiag childip6", AUTOMATIC_JSON, "fetch_all_meshdiag_child_ip6_tables"),
    PersistenceContract("otbr-cli networkdiag fetch-all", AUTOMATIC_JSON, "fetch_network_diag_topology"),
    PersistenceContract("otbr-cli networkdiag multicast-network", AUTOMATIC_JSON, "fetch_network_diag_topology_multicast_network"),
    PersistenceContract("otbr-cli networkdiag multicast-neighbors", AUTOMATIC_JSON, "fetch_network_diag_topology_multicast_neighbors"),
    PersistenceContract("otbr-cli topology", COMPOSITE, "td_cli._dispatch_otbr_cli"),
    PersistenceContract("otbr-restapi download", ALREADY_OWNED, "download helpers"),
    PersistenceContract("otbr-restapi node get", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi node state get", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi node state set", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi node dataset active get", EXPLICIT_TEXT, "run_cli"),
    PersistenceContract("otbr-restapi node dataset active set", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi devices list", AUTOMATIC_JSON, "run_cli"),
    PersistenceContract("otbr-restapi devices get", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi devices fetch", AUTOMATIC_JSON, "run_cli"),
    PersistenceContract("otbr-restapi diagnostics list", AUTOMATIC_JSON, "run_cli"),
    PersistenceContract("otbr-restapi diagnostics get", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi diagnostics fetch", AUTOMATIC_JSON, "run_cli"),
    PersistenceContract("otbr-restapi diagnostics fetch-all", AUTOMATIC_JSON, "run_cli"),
    PersistenceContract("otbr-restapi actions list", AUTOMATIC_JSON, "run_cli"),
    PersistenceContract("otbr-restapi actions get", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi actions enqueue add-thread-device", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi actions enqueue get-network-diagnostic", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi actions enqueue reset-network-diag-counter", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi actions enqueue get-energy-scan", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi actions enqueue update-device-collection", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi mesh-diagnostics children", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi mesh-diagnostics child-ipv6", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi mesh-diagnostics router-neighbors", EXPLICIT_JSON, "run_cli"),
    PersistenceContract("otbr-restapi mesh-diagnostics fetch", AUTOMATIC_JSON, "run_cli"),
    PersistenceContract("otbr-restapi mesh-diagnostics fetch-all", AUTOMATIC_JSON, "run_cli"),
    PersistenceContract("otbr-restapi topology", COMPOSITE, "dispatch_topology"),
)


@pytest.mark.parametrize("contract", COMMAND_CONTRACTS, ids=lambda item: item.command)
def test_every_inventory_row_has_a_persistence_classification(contract):
    assert contract.classification in {
        AUTOMATIC_JSON,
        EXPLICIT_JSON,
        EXPLICIT_TEXT,
        COMPOSITE,
        ALREADY_OWNED,
    }
    assert contract.current_owner


def test_inventory_has_every_approved_command_once():
    commands = [contract.command for contract in COMMAND_CONTRACTS]
    assert len(commands) == 36
    assert len(set(commands)) == len(commands)


def test_rest_auto_output_filename_matrix_is_exact():
    assert rest_cli._AUTO_OUTPUT_NAMES == {
        ("devices", "list"): OTBR_RESTAPI_DEVICES_LIST_FILENAME,
        ("devices", "fetch"): OTBR_RESTAPI_DEVICES_FETCH_FILENAME,
        ("diagnostics", "list"): OTBR_RESTAPI_DIAGNOSTICS_LIST_FILENAME,
        ("diagnostics", "fetch"): OTBR_RESTAPI_DIAGNOSTICS_FETCH_FILENAME,
        ("diagnostics", "fetch-all"): OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
        ("actions", "list"): OTBR_RESTAPI_ACTIONS_LIST_FILENAME,
        ("mesh-diagnostics", "fetch"): OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_FILENAME,
        ("mesh-diagnostics", "fetch-all"): OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    }


def _run_with_result(argv: list[str], result):
    with patch.object(rest_cli, "build_client", return_value=object()), patch.object(
        rest_cli, "dispatch", return_value=result
    ):
        return rest_cli.main(argv)


def test_rest_auto_json_output_preserves_payload_filename_summary_and_exit_code(
    tmp_path, capsys
):
    result = {"items": [{"deviceId": "dev-1"}], "partial": False}

    rc = _run_with_result(
        ["--datadir", str(tmp_path), "devices", "list"],
        result,
    )

    output_path = tmp_path / OTBR_RESTAPI_DEVICES_LIST_FILENAME
    assert rc == rest_cli.EXIT_SUCCESS
    assert json.loads(output_path.read_text(encoding="utf-8")) == result
    assert capsys.readouterr().out == f"Saved 1 records to {output_path}\n"


def test_rest_explicit_json_output_takes_precedence_over_auto_output(tmp_path, capsys):
    result = [{"deviceId": "dev-1"}]

    rc = _run_with_result(
        [
            "--datadir",
            str(tmp_path),
            "--output",
            "explicit.json",
            "devices",
            "list",
        ],
        result,
    )

    output_path = tmp_path / "explicit.json"
    assert rc == rest_cli.EXIT_SUCCESS
    assert json.loads(output_path.read_text(encoding="utf-8")) == result
    assert not (tmp_path / OTBR_RESTAPI_DEVICES_LIST_FILENAME).exists()
    assert capsys.readouterr().out == f"Saved 1 records to {output_path}\n"


def test_rest_explicit_plain_text_output_remains_unquoted(tmp_path, capsys):
    rc = _run_with_result(
        [
            "--datadir",
            str(tmp_path),
            "--output",
            "dataset.txt",
            "node",
            "dataset",
            "active",
            "get",
            "--text",
        ],
        "0e080000000000010000",
    )

    output_path = tmp_path / "dataset.txt"
    assert rc == rest_cli.EXIT_SUCCESS
    assert output_path.read_text(encoding="utf-8") == "0e080000000000010000\n"
    assert capsys.readouterr().out == f"Saved 20 records to {output_path}\n"


def test_rest_no_auto_output_writes_only_stdout(tmp_path, capsys):
    result = [{"deviceId": "dev-1"}]

    rc = _run_with_result(
        ["--datadir", str(tmp_path), "--no-auto-output", "devices", "list"],
        result,
    )

    assert rc == rest_cli.EXIT_SUCCESS
    assert list(tmp_path.iterdir()) == []
    assert capsys.readouterr().out == (
        '[\n    {\n        "deviceId": "dev-1"\n    }\n]\n'
        "Output written to stdout\n"
    )


def test_rest_run_cli_orders_dispatch_then_save_before_success_return(tmp_path):
    events = []

    def dispatch(_client, _args):
        events.append("collect")
        return [{"deviceId": "dev-1"}]

    def emit_output(result, output_path):
        assert result == [{"deviceId": "dev-1"}]
        assert Path(output_path).name == OTBR_RESTAPI_DEVICES_LIST_FILENAME
        events.append("save")

    with patch.object(rest_cli, "build_client", return_value=object()), patch.object(
        rest_cli, "dispatch", side_effect=dispatch
    ), patch.object(rest_cli, "emit_output", side_effect=emit_output):
        rc = rest_cli.main(["--datadir", str(tmp_path), "devices", "list"])
        events.append("returned")

    assert rc == rest_cli.EXIT_SUCCESS
    assert events == ["collect", "save", "returned"]


def test_rest_final_write_failure_is_unexpected_error_and_nonzero(tmp_path, capsys):
    with patch.object(rest_cli, "build_client", return_value=object()), patch.object(
        rest_cli, "dispatch", return_value=[{"deviceId": "dev-1"}]
    ), patch.object(Path, "write_text", side_effect=OSError("disk full")):
        rc = rest_cli.main(
            ["--datadir", str(tmp_path), "--output", "result.json", "devices", "list"]
        )

    captured = capsys.readouterr()
    assert rc == rest_cli.EXIT_UNEXPECTED
    assert captured.out == ""
    assert '"type": "unexpected"' in captured.err
    assert "disk full" in captured.err