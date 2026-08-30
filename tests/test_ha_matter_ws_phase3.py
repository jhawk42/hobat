from __future__ import annotations

import json

from pathlib import Path

from ha_matter_ws_contract import (
    NEIGHBOR_TABLE_FIELDS,
    ROUTE_TABLE_FIELDS,
    THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES,
)
from ha_matter_ws_extractor import extract_nodes_info
from ha_matter_ws_snapshots import build_diagnostic_snapshot


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