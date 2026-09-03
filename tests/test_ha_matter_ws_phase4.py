from __future__ import annotations

import json

from pathlib import Path

from ha_matter_ws_topology import (
    TopologyValidationError,
    build_mesh_diagnostic_snapshot,
    build_topology_snapshot,
    validate_topology,
)


FIXTURE = Path(__file__).parent / "fixtures" / "ha_matter_ws_phase4_topology.json"


def _diagnostics() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["diagnostics"]


def _by_node_id(topology: list[dict], node_id: int) -> dict:
    return next(node for node in topology if node.get("nodeId") == node_id)


def test_topology_preserves_one_way_and_reciprocal_neighbor_observations() -> None:
    topology = build_topology_snapshot(_diagnostics())
    first = _by_node_id(topology, 1)
    second = _by_node_id(topology, 2)
    child = next(node for node in topology if node.get("relationshipOnly"))

    assert {link["targetId"] for link in first["routerNeighbors"]} == {
        second["topologyId"], child["topologyId"]
    }
    assert [link["targetId"] for link in second["routerNeighbors"]] == [first["topologyId"]]
    assert child["routerNeighbors"] == []
    assert first["routerNeighbors"][0]["observations"][0]["reporterMatterId"] == "FABRIC-1"
    assert second["routerNeighbors"][0]["lqi"] == 1


def test_children_placeholders_duplicates_and_conflicting_ids_are_deterministic() -> None:
    topology = build_topology_snapshot(_diagnostics())
    first = _by_node_id(topology, 1)
    second = _by_node_id(topology, 2)
    fourth = _by_node_id(topology, 4)
    child = next(node for node in topology if node.get("relationshipOnly"))

    assert child["extAddress"] == "cc00000000000003"
    assert child["rloc16"] == "0x3001"
    assert child.get("matterId") is None
    assert first["children"] == [
        next(link for link in first["routerNeighbors"] if link["targetId"] == child["topologyId"])
    ]
    link_to_second = next(link for link in first["routerNeighbors"] if link["targetId"] == second["topologyId"])
    assert len(link_to_second["observations"]) == 2
    assert [
        observation["entry"]["lqi"]
        for observation in link_to_second["observations"]
    ] == [3, 1]
    assert link_to_second["identityConflicts"] == [
        {"field": "rloc16", "reported": "0x4000", "resolved": fourth["topologyId"]}
    ]


def test_routes_filter_unallocated_keep_inactive_and_never_resolve_router_id_alone() -> None:
    topology = build_topology_snapshot(_diagnostics())
    first = _by_node_id(topology, 1)
    route_data = first["route"]["routeData"]

    assert len(route_data) == 1
    assert route_data[0]["targetId"] == _by_node_id(topology, 2)["topologyId"]
    assert route_data[0]["linkEstablished"] is False
    assert not any(node.get("extAddress") == "ee00000000000005" for node in topology)


def test_missing_reporter_identity_and_zero_link_network_remain_valid() -> None:
    topology = build_topology_snapshot(_diagnostics())
    missing_identity = _by_node_id(topology, 6)
    isolated = _by_node_id(topology, 7)

    assert missing_identity["topologyId"] == "matter:FABRIC-6"
    assert len(missing_identity["routerNeighbors"]) == 1
    assert isolated["routerNeighbors"] == []
    assert isolated["children"] == []
    assert isolated["route"] == {"routeData": []}
    assert isolated["totalLinks"] == 0
    assert isolated["totalChildren"] == 0
    validate_topology(topology)


def test_reporter_rloc16_is_derived_from_thread_rloc_address() -> None:
    diagnostics = [
        {
            "nodeId": 9,
            "matterId": "FABRIC-9",
            "meshLocalPrefix": "fd11:2233:4455:6677::/64",
            "ipv6Addresses": [
                "fd11:2233:4455:6677:0:ff:fe00:2401",
                "2001:db8::1",
            ],
            "neighborTable": [],
            "routeTable": [],
        }
    ]

    reporter = build_topology_snapshot(diagnostics)[0]

    assert reporter["rloc16"] == "0x2401"
    assert reporter["rloc16Provenance"] == {
        "source": "threadInterfaceIpv6",
        "address": "fd11:2233:4455:6677:0:ff:fe00:2401",
    }
    assert reporter["topologyId"].endswith(":rloc:0x2401")
    assert reporter["matterId"] == "FABRIC-9"


def test_topology_infers_router_and_child_relationships_from_rloc16() -> None:
    diagnostics = [
        {
            "nodeId": 20,
            "matterId": "FABRIC-20",
            "extPanId": "0x1111222233334444",
            "rloc16": "0x4c00",
            "neighborTable": [],
            "routeTable": [],
        },
        {
            "nodeId": 21,
            "matterId": "FABRIC-21",
            "extPanId": "0x1111222233334444",
            "rloc16": "0x4c92",
            "neighborTable": [],
            "routeTable": [],
        },
        {
            "nodeId": 22,
            "matterId": "FABRIC-22",
            "extPanId": "0x9999000011112222",
            "rloc16": "0x4c93",
            "neighborTable": [],
            "routeTable": [],
        },
    ]

    topology = build_topology_snapshot(diagnostics)
    parent = _by_node_id(topology, 20)
    child = _by_node_id(topology, 21)

    assert parent["isRouter"] is True
    assert child["isRouter"] is False
    assert parent["totalChildren"] == 1
    assert parent["children"][0]["targetId"] == child["topologyId"]
    assert parent["children"][0]["observations"][0]["source"] == "Rloc16Hierarchy"


def test_mesh_snapshot_excludes_relationship_only_nodes_but_topology_keeps_them() -> None:
    diagnostics = _diagnostics()

    mesh = build_mesh_diagnostic_snapshot(diagnostics)
    topology = build_topology_snapshot(diagnostics)

    assert len(mesh) == 5
    assert len(topology) == 6
    assert all(not node.get("relationshipOnly") for node in mesh)


def test_validation_rejects_unresolved_relationship_endpoint() -> None:
    topology = build_topology_snapshot(_diagnostics())
    _by_node_id(topology, 1)["routerNeighbors"][0]["targetId"] = "missing"

    try:
        validate_topology(topology)
    except TopologyValidationError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("invalid topology was accepted")