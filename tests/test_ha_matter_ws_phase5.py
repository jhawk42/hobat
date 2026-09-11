from __future__ import annotations

import asyncio
import json

from pathlib import Path

import pytest

import ha_matter_ws_cli
import td_cli

from ha_matter_ws_cli import (
    DASHBOARD_SCHEMA_VERSION,
    EXIT_ARGUMENT,
    EXIT_CANCELLED,
    EXIT_CONNECTION,
    EXIT_EXTRACTION,
    EXIT_PARTIAL,
    EXIT_PERSISTENCE,
    EXIT_PROTOCOL,
    MatterPartialCollectionError,
    build_dashboard_snapshot,
    build_parser,
    main,
)
from ha_matter_ws_client import (
    MatterWsCommandError,
    MatterWsContractError,
    MatterWsRequestTimeoutError,
    MatterWsTransportError,
)
from ha_matter_ws_contract import MatterWsSchemaCompatibilityError
from ha_matter_ws_extractor import MatterExtractionError
from ha_matter_ws_fetch_all import MatterCollection
from td_const import (
    HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME,
    HA_MATTER_WS_DASHBOARD_FILENAME,
    HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME,
    HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_SERVER_INFO_FILENAME,
    HA_MATTER_WS_TOPOLOGY_FILENAME,
)


FINAL_FILENAMES = [
    HA_MATTER_WS_SERVER_INFO_FILENAME,
    HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME,
    HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_TOPOLOGY_FILENAME,
    HA_MATTER_WS_DASHBOARD_FILENAME,
    HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME,
]


def _collection() -> MatterCollection:
    coverage = {
        "threadNetworkDiagnostics": {
            "cluster": "populated",
            "attributes": {"channel": "populated", "partitionId": "null"},
        }
    }
    device = {
        "id": "matter:fixture:1",
        "type": "threadDevice",
        "deviceLabel": "Fixture",
        "available": True,
        "matter": {"nodeId": "0x0000000000000001", "endpoints": []},
    }
    diagnostic = {
        "nodeId": 1,
        "matterId": "fixture:1",
        "extAddress": "1122334455667788",
        "diagnosticCoverage": coverage,
        "diagnosticsDetail": {"readErrors": {}},
    }
    mesh = {**diagnostic, "children": [], "routerNeighbors": [], "route": {"routeData": []}}
    return MatterCollection(
        uri="ws://fixture/ws",
        message_count=2,
        node_count=1,
        server_info={
            "schema_version": 12,
            "min_supported_schema_version": 11,
            "sdk_version": "fixture-sdk",
        },
        devices=(device,),
        diagnostics=(diagnostic,),
        mesh_diagnostics=(mesh,),
        topology=(mesh,),
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["server-info"],
        ["devices", "list"],
        ["devices", "get", "--node-id", "1"],
        ["devices", "fetch-all"],
        ["diagnostics", "get", "--node-id", "1"],
        ["diagnostics", "fetch-all"],
        ["mesh-diagnostics", "get", "--node-id", "1"],
        ["mesh-diagnostics", "fetch-all"],
        ["device", "ping", "--node-id", "1"],
        ["topology"],
        ["dashboard"],
        ["all"],
    ],
)
def test_owner_parser_accepts_every_command_path(argv) -> None:
    assert build_parser().parse_args(argv)


def test_owner_parser_resolves_endpoint_precedence(monkeypatch) -> None:
    monkeypatch.setenv("TD_HA_MATTER_WS_HOST", "environment.test")
    monkeypatch.setenv("TD_HA_MATTER_WS_PORT", "15580")

    environment_args = build_parser().parse_args(["server-info"])
    explicit_args = build_parser().parse_args(
        ["--host", "explicit.test", "--port", "25580", "server-info"]
    )
    uri_args = build_parser().parse_args(
        [
            "--host",
            "ignored.test",
            "--port",
            "35580",
            "--uri",
            "wss://matter.test/custom",
            "server-info",
        ]
    )

    assert ha_matter_ws_cli._collection_kwargs(environment_args)["uri"] == (
        "ws://environment.test:15580/ws"
    )
    assert ha_matter_ws_cli._collection_kwargs(explicit_args)["uri"] == (
        "ws://explicit.test:25580/ws"
    )
    assert ha_matter_ws_cli._collection_kwargs(uri_args)["uri"] == (
        "wss://matter.test/custom"
    )


def test_snapshot_filenames_match_approved_contract() -> None:
    assert FINAL_FILENAMES == [
        "td-ha-matter-ws-server-info.json",
        "td-ha-matter-ws-devices-fetch-all.json",
        "td-ha-matter-ws-diagnostics-fetch-all.json",
        "td-ha-matter-ws-mesh-diagnostics-fetch-all.json",
        "td-ha-matter-ws-topology.json",
        "td-ha-matter-ws-dashboard.json",
        "td-ha-matter-ws-collection.outcome.json",
    ]


def test_dashboard_snapshot_preserves_table_and_topology_projections() -> None:
    payload = build_dashboard_snapshot(_collection())

    assert payload == {
        "schemaVersion": DASHBOARD_SCHEMA_VERSION,
        "devices": list(_collection().devices),
        "diagnostics": list(_collection().diagnostics),
        "meshDiagnostics": list(_collection().mesh_diagnostics),
        "topology": list(_collection().topology),
    }


def test_all_collects_once_and_writes_outcome_last(monkeypatch, tmp_path) -> None:
    calls = []

    async def fake_collect_devices(*args, **kwargs):
        calls.append((args, kwargs))
        return _collection()

    monkeypatch.setattr(ha_matter_ws_cli, "collect_devices", fake_collect_devices)
    monkeypatch.setattr(
        ha_matter_ws_cli,
        "save_json_atomic",
        lambda payload, path, **kwargs: calls.append(Path(path).name),
    )

    rc = main(["--datadir", str(tmp_path), "--no-progress", "all"])

    assert rc == 0
    assert len([call for call in calls if isinstance(call, tuple)]) == 1
    assert [call for call in calls if isinstance(call, str)] == FINAL_FILENAMES


def test_leaf_explicit_output_resolves_under_datadir(monkeypatch, tmp_path) -> None:
    written = []

    async def fake_collect_devices(*args, **kwargs):
        return _collection()

    monkeypatch.setattr(ha_matter_ws_cli, "collect_devices", fake_collect_devices)
    monkeypatch.setattr(
        ha_matter_ws_cli,
        "save_json_atomic",
        lambda payload, path, **kwargs: written.append((payload, Path(path))),
    )

    rc = main(
        [
            "--datadir",
            str(tmp_path),
            "--output",
            "custom.json",
            "devices",
            "fetch-all",
        ]
    )

    assert rc == 0
    assert written == [(list(_collection().devices), tmp_path / "custom.json")]


def test_list_and_get_emit_concise_or_selected_json(monkeypatch, capsys) -> None:
    async def fake_collect_devices(*args, **kwargs):
        return _collection()

    monkeypatch.setattr(ha_matter_ws_cli, "collect_devices", fake_collect_devices)

    assert main(["devices", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed == [
        {
            "nodeId": "0x0000000000000001",
            "deviceLabel": "Fixture",
            "available": True,
            "isBridge": None,
        }
    ]
    assert main(["diagnostics", "get", "--node-id", "1"]) == 0
    selected = json.loads(capsys.readouterr().out)
    assert selected["nodeId"] == 1


@pytest.mark.parametrize(
    ("results", "outcome"),
    [
        ({}, "no-addresses"),
        ({"192.0.2.10": True}, "success"),
        ({"192.0.2.10": False}, "all-address-failure"),
        ({"192.0.2.10": True, "2001:db8::10": False}, "partial-success"),
    ],
)
def test_device_ping_emits_structured_outcome_without_persistence(
    monkeypatch, tmp_path, capsys, results, outcome
) -> None:
    calls = []

    async def fake_ping(uri, node_id, attempts, **kwargs):
        calls.append((uri, node_id, attempts, kwargs))
        return results

    monkeypatch.setattr(ha_matter_ws_cli, "_ping_node", fake_ping)
    data_dir = tmp_path / "new-data-dir"

    assert (
        main(
            [
                "--datadir",
                str(data_dir),
                "--uri",
                "ws://matter.test/ws",
                "device",
                "ping",
                "--node-id",
                "0x2a",
                "--attempts",
                "3",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["nodeId"] == 42
    assert payload["uri"] == "ws://matter.test/ws"
    assert payload["attempts"] == 3
    assert payload["addresses"] == list(results)
    assert payload["results"] == results
    assert payload["outcome"] == outcome
    assert calls == [
        (
            "ws://matter.test/ws",
            42,
            3,
            {"connect_timeout": 10.0, "request_timeout": 5.0},
        )
    ]
    assert not data_dir.exists()


def test_device_ping_rejects_invalid_node_and_attempts_without_connecting(
    monkeypatch,
) -> None:
    async def unexpected_ping(*args, **kwargs):
        raise AssertionError("ping should not start")

    monkeypatch.setattr(ha_matter_ws_cli, "_ping_node", unexpected_ping)
    assert main(["device", "ping", "--node-id", str(1 << 64)]) == EXIT_ARGUMENT
    with pytest.raises(SystemExit):
        build_parser().parse_args(["device", "ping", "--node-id", "1", "--attempts", "6"])


@pytest.mark.parametrize(
    ("error", "outcome", "expected_rc"),
    [
        (MatterWsRequestTimeoutError("slow"), "request-timeout", EXIT_CONNECTION),
        (MatterWsTransportError("offline"), "transport-failure", EXIT_CONNECTION),
        (
            MatterWsCommandError("1", 9, "Invalid command: ping_node"),
            "command-unsupported",
            EXIT_PROTOCOL,
        ),
        (MatterWsContractError("malformed"), "protocol-error", EXIT_PROTOCOL),
    ],
)
def test_device_ping_emits_structured_failure(
    monkeypatch, capsys, error, outcome, expected_rc
) -> None:
    async def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(ha_matter_ws_cli, "_ping_node", fail)

    assert main(["device", "ping", "--node-id", "7"]) == expected_rc
    payload = json.loads(capsys.readouterr().out)
    assert payload["nodeId"] == 7
    assert payload["outcome"] == outcome
    assert payload["addresses"] == []
    assert payload["results"] == {}


def test_checkpoint_payload_identifies_partial_completeness(monkeypatch, tmp_path) -> None:
    writes = []
    monkeypatch.setattr(
        ha_matter_ws_cli,
        "save_json_atomic",
        lambda payload, path, **kwargs: writes.append((payload, Path(path))),
    )
    callback = ha_matter_ws_cli.make_checkpoint_callback(
        {"devices": tmp_path / HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME},
        show_progress=False,
    )

    callback(1, 2, _collection())
    callback(2, 2, _collection())

    assert len(writes) == 1
    payload, path = writes[0]
    assert payload["partial"] is True
    assert payload["completed"] == 1
    assert payload["total"] == 2
    assert path.name == "td-ha-matter-ws-devices-fetch-all.partial.json"


def test_fetch_all_wires_collection_progress_to_checkpoint(monkeypatch, tmp_path) -> None:
    writes = []

    async def fake_collect_devices(*args, **kwargs):
        kwargs["progress_callback"](1, 2, _collection())
        return _collection()

    monkeypatch.setattr(ha_matter_ws_cli, "collect_devices", fake_collect_devices)
    monkeypatch.setattr(
        ha_matter_ws_cli,
        "save_json_atomic",
        lambda payload, path, **kwargs: writes.append((payload, Path(path))),
    )

    assert main(["--datadir", str(tmp_path), "devices", "fetch-all"]) == 0
    assert [path.name for _, path in writes] == [
        "td-ha-matter-ws-devices-fetch-all.partial.json",
        HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME,
    ]
    assert writes[0][0]["records"] == list(_collection().devices)


def test_outcome_counts_extractor_coverage_states() -> None:
    diagnostics = [
        {
            "diagnosticCoverage": {
                "threadNetworkDiagnostics": {
                    "cluster": "readError",
                    "attributes": {
                        "channel": "populated",
                        "partitionId": "attributeUnsupported",
                        "neighborTable": "implementedEmpty",
                        "routeTable": "readError",
                    },
                }
            }
        },
        {
            "diagnosticCoverage": {
                "threadNetworkDiagnostics": {
                    "cluster": "clusterUnsupported",
                    "attributes": {},
                }
            }
        },
    ]

    coverage = ha_matter_ws_cli._coverage_summary(diagnostics)

    assert coverage["clusters"]["readError"] == 1
    assert coverage["clusters"]["clusterUnsupported"] == 1
    assert coverage["attributes"]["populated"] == 1
    assert coverage["attributes"]["attributeUnsupported"] == 1
    assert coverage["attributes"]["implementedEmpty"] == 1
    assert coverage["attributes"]["readError"] == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["--output", "ignored.json", "all"],
        ["devices", "get", "--node-id", "not-a-node"],
        ["--request-timeout", "0", "devices", "list"],
    ],
)
def test_invalid_arguments_return_argument_exit_without_collection(
    monkeypatch, argv
) -> None:
    async def unexpected_collect(*args, **kwargs):
        raise AssertionError("collection should not start")

    monkeypatch.setattr(ha_matter_ws_cli, "collect_devices", unexpected_collect)
    assert main(argv) == ha_matter_ws_cli.EXIT_ARGUMENT


def test_environment_datadir_precedence(monkeypatch, tmp_path) -> None:
    written = []

    async def fake_collect_devices(*args, **kwargs):
        return _collection()

    monkeypatch.setenv("TD_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ha_matter_ws_cli, "collect_devices", fake_collect_devices)
    monkeypatch.setattr(
        ha_matter_ws_cli,
        "save_json_atomic",
        lambda payload, path, **kwargs: written.append(Path(path)),
    )

    assert main(["devices", "fetch-all"]) == 0
    assert written == [tmp_path / HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME]


def test_all_write_failure_stops_before_outcome(monkeypatch, tmp_path) -> None:
    written = []

    async def fake_collect_devices(*args, **kwargs):
        return _collection()

    def fail_second_write(payload, path, **kwargs):
        written.append(Path(path).name)
        if len(written) == 2:
            raise OSError("disk full")

    monkeypatch.setattr(ha_matter_ws_cli, "collect_devices", fake_collect_devices)
    monkeypatch.setattr(ha_matter_ws_cli, "save_json_atomic", fail_second_write)

    assert main(["--datadir", str(tmp_path), "all"]) == EXIT_PERSISTENCE
    assert written == FINAL_FILENAMES[:2]
    assert HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME not in written


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (MatterWsTransportError("offline"), EXIT_CONNECTION),
        (MatterWsSchemaCompatibilityError("schema"), EXIT_PROTOCOL),
        (MatterPartialCollectionError("partial"), EXIT_PARTIAL),
        (MatterExtractionError("bad node"), EXIT_EXTRACTION),
    ],
)
def test_collection_errors_map_to_stable_exit_codes(monkeypatch, error, expected) -> None:
    async def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(ha_matter_ws_cli, "collect_devices", fail)
    assert main(["devices", "fetch-all"]) == expected


def test_persistence_and_cancellation_have_stable_exit_codes(monkeypatch, tmp_path) -> None:
    async def fake_collect_devices(*args, **kwargs):
        return _collection()

    monkeypatch.setattr(ha_matter_ws_cli, "collect_devices", fake_collect_devices)
    monkeypatch.setattr(
        ha_matter_ws_cli,
        "save_json_atomic",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    assert main(["--datadir", str(tmp_path), "devices", "fetch-all"]) == EXIT_PERSISTENCE

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(ha_matter_ws_cli, "collect_devices", cancelled)
    assert main(["devices", "fetch-all"]) == EXIT_CANCELLED


def test_td_cli_routes_family_options_and_nested_command(monkeypatch, tmp_path) -> None:
    forwarded = []
    monkeypatch.setattr(
        td_cli.ha_matter_ws_cli,
        "main",
        lambda argv: forwarded.append(argv) or 0,
    )
    parser = td_cli.build_parser()
    args, extras = parser.parse_known_args(
        [
            "--datadir",
            str(tmp_path),
            "ha-matter-ws",
            "--host",
            "matter-host.test",
            "--port",
            "15580",
            "--uri",
            "ws://matter.test/ws",
            "--connect-timeout",
            "11",
            "--request-timeout",
            "6",
            "--settle-timeout",
            "0.5",
            "--output",
            "diagnostic.json",
            "--no-progress",
            "--debug",
            "diagnostics",
            "get",
            "--node-id",
            "7",
        ]
    )

    assert td_cli.dispatch(args, extras, parser) == 0
    assert forwarded == [
        [
            "--datadir",
            str(tmp_path),
            "--host",
            "matter-host.test",
            "--port",
            "15580",
            "--uri",
            "ws://matter.test/ws",
            "--connect-timeout",
            "11.0",
            "--request-timeout",
            "6.0",
            "--settle-timeout",
            "0.5",
            "--output",
            "diagnostic.json",
            "--no-progress",
            "--debug",
            "diagnostics",
            "get",
            "--node-id",
            "7",
        ]
    ]


def test_td_cli_routes_device_ping_and_attempts(monkeypatch) -> None:
    forwarded = []
    monkeypatch.setattr(
        td_cli.ha_matter_ws_cli,
        "main",
        lambda argv: forwarded.append(argv) or 0,
    )
    parser = td_cli.build_parser()
    args, extras = parser.parse_known_args(
        ["ha-matter-ws", "device", "ping", "--node-id", "7", "--attempts", "3"]
    )

    assert td_cli.dispatch(args, extras, parser) == 0
    assert forwarded == [
        ["device", "ping", "--node-id", "7", "--attempts", "3"]
    ]


def test_td_cli_routes_dashboard_command(monkeypatch) -> None:
    forwarded = []
    monkeypatch.setattr(
        td_cli.ha_matter_ws_cli,
        "main",
        lambda argv: forwarded.append(argv) or 0,
    )

    assert td_cli.main(["ha-matter-ws", "dashboard"]) == 0
    assert forwarded == [["dashboard"]]


def test_td_cli_device_ping_failure_output_has_no_banner(monkeypatch, capsys) -> None:
    async def fail(*args, **kwargs):
        raise MatterWsRequestTimeoutError("slow")

    monkeypatch.setattr(ha_matter_ws_cli, "_ping_node", fail)

    assert td_cli.main([
        "ha-matter-ws", "device", "ping", "--node-id", "12"
    ]) == EXIT_CONNECTION

    payload = json.loads(capsys.readouterr().out)
    assert payload["nodeId"] == 12
    assert payload["outcome"] == "request-timeout"


def test_td_cli_family_help_path(capsys) -> None:
    assert td_cli.main(["ha-matter-ws"]) == 0
    output = capsys.readouterr().out
    assert "Collect snapshots from Home Assistant Matter Server" in output
    assert "mesh-diagnostics" in output


def test_td_cli_nested_family_help_path(capsys) -> None:
    assert td_cli.main(["ha-matter-ws", "devices"]) == 0
    output = capsys.readouterr().out
    assert "{list,get,fetch-all}" in output