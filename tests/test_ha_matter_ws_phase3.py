from __future__ import annotations

import json

from pathlib import Path

from ha_matter_ws_contract import (
    NEIGHBOR_TABLE_FIELDS,
    ROUTE_TABLE_FIELDS,
    THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES,
)
from ha_matter_ws_extractor import extract_nodes_info
from ha_matter_ws_snapshots import build_device_snapshot, build_diagnostic_snapshot
from ha_matter_ws_topology import build_mesh_diagnostic_snapshot, build_topology_snapshot


FIXTURE = Path(__file__).parent / "fixtures" / "ha_matter_ws_phase3_diagnostics.json"


def _records() -> list[dict]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return extract_nodes_info(fixture["nodes"])


def test_golden_thread_node_decodes_every_standard_scalar_and_counter() -> None:
    thread = _records()[0]["thread"]
    standard = thread["diagnosticsDetail"]["threadNetworkDiagnostics"]

    scalar_names = {
        definition.name[:1].lower() + definition.name[1:]
        for attribute_id, definition in THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES.items()
        if attribute_id not in {7, 8}
    }
    assert scalar_names <= set(standard)
    assert thread["routingRole"] == "Unknown (99)"
    assert thread["meshLocalPrefix"] == "fd00::/64"
    assert standard["channelPage0Mask"] == "0F"
    assert thread["extAddress"] == "1111222233334444"
    assert thread["rloc16"] == "0x0C00"
    assert thread["partitionId"] is None
    assert thread["macCounters"]["txTotalCount"] == 22
    assert thread["macCounters"]["rxErrOtherCount"] == 55
    assert thread["mleCounters"] == {
        "detachedRoleCount": 14,
        "childRoleCount": 15,
        "routerRoleCount": 16,
        "leaderRoleCount": 17,
        "attachAttemptCount": 18,
        "partIdChangesCount": 19,
        "betterPartIdAttachAttemptsCount": 20,
        "newParentCount": 21,
    }
    assert not any("ratio" in key.lower() for key in thread["macCounters"])


def test_golden_tables_decode_all_named_and_numeric_fields_and_keep_unknowns() -> None:
    thread = _records()[0]["thread"]
    neighbor = thread["neighborTable"][0]
    route = thread["routeTable"][0]

    expected_neighbor = {
        definition.name[:1].lower() + definition.name[1:]
        for definition in NEIGHBOR_TABLE_FIELDS.values()
    }
    expected_route = {
        definition.name[:1].lower() + definition.name[1:]
        for definition in ROUTE_TABLE_FIELDS.values()
    }
    assert expected_neighbor <= set(neighbor)
    assert expected_route <= set(route)
    assert neighbor["lqi"] == 3
    assert neighbor["unknownFields"] == {"FutureNeighborField": "kept"}
    assert route["unknownFields"] == {"10": "kept"}


def test_coverage_distinguishes_all_required_states() -> None:
    populated, unsupported_attributes, empty, read_error, wifi, _invalid = _records()

    assert populated["diagnosticCoverage"]["threadNetworkDiagnostics"]["cluster"] == "populated"
    assert populated["diagnosticCoverage"]["threadNetworkDiagnostics"]["attributes"]["partitionId"] == "null"
    assert unsupported_attributes["diagnosticCoverage"]["threadNetworkDiagnostics"]["attributes"]["channel"] == "attributeUnsupported"
    assert empty["diagnosticCoverage"]["threadNetworkDiagnostics"]["attributes"]["neighborTable"] == "implementedEmpty"
    assert read_error["diagnosticCoverage"]["threadNetworkDiagnostics"]["attributes"]["neighborTable"] == "readError"
    assert read_error["diagnosticCoverage"]["threadNetworkDiagnostics"]["cluster"] == "readError"
    assert wifi["diagnosticCoverage"]["threadNetworkDiagnostics"]["cluster"] == "clusterUnsupported"
    assert wifi["thread"] is None


def test_thread_details_retain_unknown_attributes_and_general_diagnostics() -> None:
    record = _records()[0]

    assert record["thread"]["diagnosticsDetail"]["unknownAttributes"] == {
        "0/53/65000": "future-value"
    }
    assert record["generalDiagnostics"]["rebootCount"] == 2
    assert record["generalDiagnostics"]["activeRadioFaults"] == [2]
    assert len(record["networkInterfaces"]) == 2
    assert record["thread"]["ipv6Addresses"] == ["fd00::1"]


def test_invalid_thread_identity_and_addresses_are_omitted() -> None:
    invalid = _records()[5]

    assert invalid["thread"]["extAddress"] is None
    assert invalid["thread"]["rloc16"] is None
    assert invalid["thread"]["ipv6Addresses"] == []


def test_diagnostic_snapshot_uses_canonical_fields_and_excludes_wifi_nodes() -> None:
    diagnostics = build_diagnostic_snapshot(_records())

    assert [record["nodeId"] for record in diagnostics] == [10, 11, 12, 13, 15]
    golden = diagnostics[0]
    assert golden["extAddress"] == "1111222233334444"
    assert golden["rloc16"] == "0x0c00"
    assert golden["mleCounters"]["partIdChangesCount"] == 19
    assert golden["mleCounters"]["newParentCount"] == 21
    assert golden["macCounters"]["txTotalCount"] == 22
    assert "children" not in golden
    assert "routerNeighbors" not in golden


def test_diagnostic_snapshot_role_facts_match_device_product_and_omit_unknowns() -> None:
    records = [
        {
            "matter": {"nodeId": 1, "matterId": "FABRIC-1"},
            "thread": {"routingRole": "Router"},
        },
        {
            "matter": {"nodeId": 2, "matterId": "FABRIC-2"},
            "thread": {"routingRole": "Reed"},
            "isReed": False,
        },
        {
            "matter": {"nodeId": 3, "matterId": "FABRIC-3"},
            "thread": {"routingRole": "Unknown (99)"},
        },
    ]

    diagnostics = build_diagnostic_snapshot(records)

    assert {
        key: diagnostics[0][key] for key in ("isRouter", "isLeader", "isReed")
    } == {"isRouter": True, "isLeader": False, "isReed": False}
    assert {
        key: diagnostics[1][key] for key in ("isRouter", "isLeader", "isReed")
    } == {"isRouter": False, "isLeader": False, "isReed": False}
    assert "isRouter" not in diagnostics[2]
    assert "isLeader" not in diagnostics[2]
    assert "isReed" not in diagnostics[2]
    assert diagnostics[1]["_merge_conflicts"] == [
        {"path": "isReed", "current": False, "incoming": True}
    ]


def test_operational_and_power_fields_survive_commissioned_products() -> None:
    record = {
        "matter": {
            "nodeId": 42,
            "matterId": "0000000000001234-0000000000000042",
            "compressedFabricId": 0x1234,
            "vendorName": "Root Vendor",
            "serialNumber": "ROOT-SERIAL",
        },
        "endpoints": [
            {
                "endpointId": 2,
                "basicInformation": {"productName": "Bridge"},
                "bridgedBasicInformation": {"vendorName": "Sensor Vendor"},
            }
        ],
        "deviceTypes": [{"endpointId": 2, "deviceType": 22, "revision": 1}],
        "serverClusters": [0x002F, 0x0039],
        "generalDiagnostics": {
            "rebootCount": 0,
            "upTime": "9223372036854775907",
            "activeHardwareFaults": [],
        },
        "powerSources": [
            {
                "endpointId": 2,
                "attributes": {"batPercentRemaining": 151, "endpointList": [2]},
                "batteryPercent": 75.5,
            }
        ],
        "diagnosticCoverage": {
            "powerSources": {
                "2": {
                    "cluster": "populated",
                    "attributes": {"batPercentRemaining": "populated"},
                }
            }
        },
        "networkInterfaces": [],
        "thread": {
            "routingRole": "Router",
            "extAddress": "1111222233334444",
            "diagnosticsDetail": {"threadNetworkDiagnostics": {"channel": 15}},
            "neighborTable": [],
            "routeTable": [],
        },
    }

    devices = build_device_snapshot([record])
    diagnostics = build_diagnostic_snapshot([record])
    mesh = build_mesh_diagnostic_snapshot(diagnostics)
    topology = build_topology_snapshot(diagnostics)

    assert devices[0]["powerSources"] == record["powerSources"]
    assert devices[0]["generalDiagnostics"] == record["generalDiagnostics"]
    assert devices[0]["matter"]["endpoints"] == record["endpoints"]
    assert devices[0]["matter"]["vendorName"] == "Root Vendor"
    for product in (diagnostics[0], mesh[0], topology[0]):
        assert product["matter"]["endpoints"] == record["endpoints"]
        assert product["matter"]["serialNumber"] == "ROOT-SERIAL"
        assert product["generalDiagnostics"] == record["generalDiagnostics"]
        assert product["powerSources"] == record["powerSources"]
        assert product["diagnosticCoverage"]["powerSources"] == record[
            "diagnosticCoverage"
        ]["powerSources"]