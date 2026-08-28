from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path

import pytest

import otbr_cli_meshdiag_childip6 as childip6
import otbr_cli_meshdiag_childtable as childtable
import otbr_cli_meshdiag_routerneighbortable as neighbortable
import otbr_cli_meshdiag_topology as meshdiag_topology
import otbr_cli_networkdiag_topology as networkdiag
import otbr_cli_router_table as router_table
import otbr_cli_thread_network_info as thread_info
from td_const import (
    OTBR_CLI_MESHDIAG_ROUTER_CHILDIP6_FILENAME,
    OTBR_CLI_MESHDIAG_ROUTER_CHILDTABLES_FILENAME,
    OTBR_CLI_MESHDIAG_ROUTER_NEIGHBORTABLES_FILENAME,
    OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME,
    OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
    OTBR_CLI_NETWORKDIAG_MULTICAST_NEIGHBORS_FILENAME,
    OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME,
    OTBR_CLI_ROUTER_TABLE_FILENAME,
    OTBR_CLI_THREAD_NETWORK_INFO_FILENAME,
)


@dataclass(frozen=True)
class CollectorCase:
    module: object
    collector_name: str
    filename: str
    payload: object
    saved_payload: object


COLLECTOR_CASES = (
    CollectorCase(thread_info, "collect_thread_network_info", OTBR_CLI_THREAD_NETWORK_INFO_FILENAME, {"network_name": "test"}, {"networkName": "test"}),
    CollectorCase(router_table, "fetch_and_parse_router_table", OTBR_CLI_ROUTER_TABLE_FILENAME, [{"router_id": "0x01"}], [{"routerId": "0x01"}]),
    CollectorCase(meshdiag_topology, "get_meshdiag_topology", OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME, [{"router_id": "0x01"}], [{"routerId": "0x01"}]),
    CollectorCase(neighbortable, "fetch_all_meshdiag_router_neighbor_tables", OTBR_CLI_MESHDIAG_ROUTER_NEIGHBORTABLES_FILENAME, [{"router_neighbor_table_count": 1}], [{"routerNeighborsCount": 1}]),
    CollectorCase(childtable, "fetch_all_meshdiag_child_tables", OTBR_CLI_MESHDIAG_ROUTER_CHILDTABLES_FILENAME, [{"router_child_table_count": 1}], [{"childTableCount": 1}]),
    CollectorCase(childip6, "fetch_all_meshdiag_child_ip6_tables", OTBR_CLI_MESHDIAG_ROUTER_CHILDIP6_FILENAME, [{"router_child_ip6_table_count": 1}], [{"childIp6TableCount": 1}]),
)


def _prepare_collector(monkeypatch, case: CollectorCase, events: list[str]):
    if case.module is thread_info:
        monkeypatch.setattr(thread_info.util_network, "fetch_thread_network_info", lambda: events.append("collect") or case.payload)
        return lambda output_path=None: thread_info.collect_thread_network_info(output_path)
    if case.module is router_table:
        monkeypatch.setattr(router_table, "fetch_router_table", lambda: events.append("collect") or "raw")
        monkeypatch.setattr(router_table, "parse_router_table", lambda *_args: case.payload)
        return lambda output_path=None: router_table.fetch_and_parse_router_table({}, output_path=output_path)
    if case.module is meshdiag_topology:
        monkeypatch.setattr(meshdiag_topology, "fetch_meshdiag_topology", lambda: events.append("collect") or "raw")
        monkeypatch.setattr(meshdiag_topology, "parse_meshdiag_topology_output", lambda *_args: case.payload)
        monkeypatch.setattr(meshdiag_topology, "enrich_topology_routers", lambda *_args: case.payload)
        return lambda output_path=None: meshdiag_topology.get_meshdiag_topology({}, {}, output_path=output_path)

    monkeypatch.setattr(case.module, "fetch_and_parse_router_table", lambda _map: [])
    monkeypatch.setattr(case.module, "collect_per_router", lambda **_kwargs: events.append("collect") or case.payload)
    return lambda output_path=None: getattr(case.module, case.collector_name)({}, output_path=output_path)


@pytest.mark.parametrize("case", COLLECTOR_CASES, ids=lambda case: case.filename)
def test_cli_collector_saves_normalized_output_before_return(monkeypatch, tmp_path, case):
    events = []
    output_path = tmp_path / case.filename
    collect = _prepare_collector(monkeypatch, case, events)

    def save(payload, path):
        assert payload == case.saved_payload
        assert Path(path) == output_path
        events.append("save")

    monkeypatch.setattr(case.module, "save_json_atomic", save)
    result = collect(output_path)
    events.append("returned")

    assert result is case.payload
    assert events == ["collect", "save", "returned"]


@pytest.mark.parametrize("case", COLLECTOR_CASES, ids=lambda case: case.filename)
def test_cli_collector_without_output_path_does_not_save(monkeypatch, case):
    events = []
    collect = _prepare_collector(monkeypatch, case, events)
    monkeypatch.setattr(case.module, "save_json_atomic", lambda *_args: pytest.fail("unexpected save"))

    assert collect() is case.payload
    assert events == ["collect"]


@pytest.mark.parametrize("case", COLLECTOR_CASES, ids=lambda case: case.filename)
def test_cli_main_delegates_resolved_output_and_maps_collector_failures(monkeypatch, tmp_path, case):
    expected_path = tmp_path / case.filename
    calls = []
    if hasattr(case.module, "os"):
        monkeypatch.setattr(case.module.os.path, "exists", lambda _path: False)
    if case.module is meshdiag_topology:
        monkeypatch.setattr(meshdiag_topology.util_network, "fetch_thread_network_info", lambda: {})
    if case.module in {neighbortable, childtable, childip6}:
        monkeypatch.setattr(case.module, "load_extaddr_map_or_empty", lambda _path: {})

    def collector(*args, **kwargs):
        output_path = args[0] if case.module is thread_info else kwargs["output_path"]
        calls.append(Path(output_path))
        return case.payload

    monkeypatch.setattr(case.module, case.collector_name, collector)
    monkeypatch.setattr(case.module, "save_json_atomic", lambda *_args: pytest.fail("main performed persistence"))

    assert case.module.main(["--datadir", str(tmp_path)]) == 0
    assert calls == [expected_path]

    monkeypatch.setattr(case.module, case.collector_name, lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))
    assert case.module.main(["--datadir", str(tmp_path)]) == 3


@pytest.mark.parametrize("case", COLLECTOR_CASES[3:], ids=lambda case: case.filename)
def test_per_router_collectors_checkpoint_then_save_final_once(monkeypatch, tmp_path, case):
    events = []
    output_path = tmp_path / case.filename
    monkeypatch.setattr(case.module, "fetch_and_parse_router_table", lambda _map: [])

    def collect_per_router(**kwargs):
        events.append("collect")
        kwargs["on_result"](case.payload, "0x0400", {})
        return case.payload

    monkeypatch.setattr(case.module, "collect_per_router", collect_per_router)
    monkeypatch.setattr(case.module, "_write_checkpoint_best_effort", lambda payload, path: events.append(("checkpoint", payload, Path(path))))
    monkeypatch.setattr(case.module, "save_json_atomic", lambda payload, path: events.append(("final", payload, Path(path))))

    result = getattr(case.module, case.collector_name)({}, output_path=output_path)

    assert result is case.payload
    assert events == [
        "collect",
        ("checkpoint", case.payload, tmp_path / case.filename.replace(".json", ".partial.json")),
        ("final", case.saved_payload, output_path),
    ]


def _stub_fetch_all_stages(monkeypatch, events):
    monkeypatch.setattr(networkdiag, "fetch_network_diag_topology_router_table", lambda *_args: events.append("router-table") or ([], [], {}))
    monkeypatch.setattr(networkdiag, "fetch_network_diag_topology_meshdiag_topology", lambda *_args: events.append("meshdiag") or [])
    monkeypatch.setattr(networkdiag, "fetch_network_diag_topology_ipv6_addresses", lambda *_args: events.append("ipv6") or {})
    monkeypatch.setattr(networkdiag, "fetch_network_diag_topology_multicast", lambda *_args: events.append("multicast") or {})
    monkeypatch.setattr(networkdiag, "fetch_network_diag_topology_detail_routers", lambda *_args: events.append("routers"))
    monkeypatch.setattr(networkdiag, "fetch_network_diag_topology_expand_children", lambda *_args: events.append("children"))


def test_networkdiag_fetch_all_collector_saves_after_all_stages(monkeypatch, tmp_path):
    events = []
    output_path = tmp_path / OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME
    _stub_fetch_all_stages(monkeypatch, events)
    monkeypatch.setattr(networkdiag, "save_topology_to_json_file", lambda _data, path: events.append(("save", Path(path))))

    result = networkdiag.fetch_network_diag_topology({}, {}, expand_children=True, final_output_path=output_path)
    events.append("returned")

    assert result == {}
    assert events == ["router-table", "meshdiag", "ipv6", "multicast", "routers", "children", ("save", output_path), "returned"]


@pytest.mark.parametrize(
    ("collector_name", "filename"),
    [
        ("fetch_network_diag_topology_multicast_network", OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME),
        ("fetch_network_diag_topology_multicast_neighbors", OTBR_CLI_NETWORKDIAG_MULTICAST_NEIGHBORS_FILENAME),
    ],
)
def test_networkdiag_multicast_collector_checkpoint_final_and_return_order(monkeypatch, tmp_path, collector_name, filename):
    events = []
    payload = {"0x0400": {"extaddr": "0011223344556677"}}
    checkpoint_path = tmp_path / filename.replace(".json", ".partial.json")
    output_path = tmp_path / filename
    monkeypatch.setattr(networkdiag, "fetch_network_diag_multicast", lambda **_kwargs: events.append("collect") or payload)
    monkeypatch.setattr(networkdiag, "save_topology_to_json_file", lambda _data, path: events.append(Path(path)))

    result = getattr(networkdiag, collector_name)(checkpoint_filepath=str(checkpoint_path), final_output_path=str(output_path))
    events.append("returned")

    assert result is payload
    assert events == ["collect", checkpoint_path, output_path, "returned"]


def test_networkdiag_collectors_without_paths_do_not_write_standalone_files(monkeypatch):
    events = []
    _stub_fetch_all_stages(monkeypatch, events)
    monkeypatch.setattr(networkdiag, "fetch_network_diag_multicast", lambda **_kwargs: {})
    monkeypatch.setattr(networkdiag, "save_topology_to_json_file", lambda *_args: pytest.fail("unexpected save"))

    assert networkdiag.fetch_network_diag_topology({}, {}) == {}
    assert networkdiag.fetch_network_diag_topology_multicast_network() == {}
    assert networkdiag.fetch_network_diag_topology_multicast_neighbors() == {}


def test_networkdiag_checkpoint_serializer_treats_none_as_no_output(monkeypatch):
    monkeypatch.setattr(
        networkdiag,
        "save_json_atomic",
        lambda *_args: pytest.fail("unexpected save"),
    )

    assert networkdiag.save_topology_to_json_file({}, None) is None


def test_networkdiag_fetch_all_main_delegates_both_output_paths(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(networkdiag.os.path, "exists", lambda _path: False)
    monkeypatch.setattr(networkdiag.util_network, "fetch_thread_network_info", lambda: {})
    monkeypatch.setattr(networkdiag, "print_network_diag_topology", lambda _data: None)

    def collect(*_args, **kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(networkdiag, "fetch_network_diag_topology", collect)
    monkeypatch.setattr(
        networkdiag,
        "save_topology_to_json_file",
        lambda *_args: pytest.fail("main performed persistence"),
    )

    assert networkdiag.main_fetch_all(["--datadir", str(tmp_path)]) == 0
    assert Path(captured["checkpoint_filepath"]) == (
        tmp_path / OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME.replace(".json", ".partial.json")
    )
    assert Path(captured["final_output_path"]) == (
        tmp_path / OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME
    )

    monkeypatch.setattr(
        networkdiag,
        "fetch_network_diag_topology",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    assert networkdiag.main_fetch_all(["--datadir", str(tmp_path)]) == 3


@pytest.mark.parametrize(
    ("main_fn", "collector_name", "filename"),
    [
        (
            networkdiag.main_multicast_network,
            "fetch_network_diag_topology_multicast_network",
            OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME,
        ),
        (
            networkdiag.main_multicast_neighbors,
            "fetch_network_diag_topology_multicast_neighbors",
            OTBR_CLI_NETWORKDIAG_MULTICAST_NEIGHBORS_FILENAME,
        ),
    ],
)
def test_networkdiag_multicast_main_delegates_both_output_paths(
    monkeypatch, tmp_path, main_fn, collector_name, filename
):
    captured = {}
    monkeypatch.setattr(networkdiag.os.path, "exists", lambda _path: False)
    monkeypatch.setattr(networkdiag.util_network, "fetch_thread_network_info", lambda: {})
    monkeypatch.setattr(networkdiag, "fetch_and_parse_router_table", lambda _map: [])
    monkeypatch.setattr(networkdiag, "print_network_diag_topology", lambda _data: None)

    def collect(*_args, **kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(networkdiag, collector_name, collect)
    monkeypatch.setattr(
        networkdiag,
        "save_topology_to_json_file",
        lambda *_args: pytest.fail("main performed persistence"),
    )

    assert main_fn(["--datadir", str(tmp_path)]) == 0
    assert Path(captured["checkpoint_filepath"]) == (
        tmp_path / filename.replace(".json", ".partial.json")
    )
    assert Path(captured["final_output_path"]) == tmp_path / filename

    monkeypatch.setattr(
        networkdiag,
        collector_name,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError, match="disk full"):
        main_fn(["--datadir", str(tmp_path)])


def test_cli_mains_no_longer_contain_final_save_calls():
    mains = [
        thread_info.main,
        router_table.main,
        meshdiag_topology.main,
        neighbortable.main,
        childtable.main,
        childip6.main,
        networkdiag.main_fetch_all,
        networkdiag.main_multicast_network,
        networkdiag.main_multicast_neighbors,
    ]
    for main_fn in mains:
        source = inspect.getsource(main_fn)
        assert "save_json_atomic(" not in source
        assert "save_topology_to_json_file(" not in source