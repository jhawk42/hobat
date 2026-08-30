from __future__ import annotations

import json
from pathlib import Path

import pytest

from ha_matter_ws_contract import (
    COLLECTOR_SCHEMA_VERSION,
    GENERAL_DIAGNOSTICS_ATTRIBUTES,
    MIN_SUPPORTED_SERVER_SCHEMA_VERSION,
    NEIGHBOR_TABLE_FIELDS,
    NETWORK_INTERFACE_FIELDS,
    ROUTE_TABLE_FIELDS,
    THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES,
    MatterWsCommandError,
    MatterWsResponseCorrelationError,
    MatterWsSchemaCompatibilityError,
    attribute_definition,
    correlate_response,
    validate_server_info,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_protocol_fixture_correlates_out_of_order_response_and_retains_events() -> None:
    fixture = _load_fixture("ha_matter_ws_protocol_schema12.json")

    response = correlate_response(fixture["frames"], "request-nodes")

    assert response.message_id == "request-nodes"
    assert [node["node_id"] for node in response.result] == [1, 2, 1]
    assert response.server_info is not None
    assert response.server_info["schema_version"] == 12
    assert [event["event"] for event in response.events] == ["node_updated"]


def test_protocol_fixture_correlates_start_listening_inventory() -> None:
    fixture = _load_fixture("ha_matter_ws_protocol_schema12.json")

    response = correlate_response(fixture["frames"], "request-listen")

    assert [node["node_id"] for node in response.result] == [1]


def test_protocol_fixture_correlates_error_by_message_id() -> None:
    fixture = _load_fixture("ha_matter_ws_protocol_schema12.json")

    with pytest.raises(MatterWsCommandError) as exc_info:
        correlate_response(fixture["frames"], "request-missing")

    assert exc_info.value.error_code == 5
    assert exc_info.value.details == "Node 404 does not exist"


def test_protocol_fixture_models_timeout_as_missing_correlated_response() -> None:
    fixture = _load_fixture("ha_matter_ws_protocol_schema12.json")

    with pytest.raises(MatterWsResponseCorrelationError, match="request-timeout"):
        correlate_response(
            fixture["timeout"]["frames"], fixture["timeout"]["message_id"]
        )


def test_duplicate_correlated_response_is_rejected() -> None:
    duplicate = [
        {"message_id": "same", "result": []},
        {"message_id": "same", "result": []},
    ]

    with pytest.raises(MatterWsResponseCorrelationError, match="Duplicate response"):
        correlate_response(duplicate, "same")


def test_schema_compatibility_accepts_overlap_and_newer_optional_schema() -> None:
    fixture = _load_fixture("ha_matter_ws_protocol_schema12.json")
    server_info = fixture["frames"][0]
    validate_server_info(server_info)

    newer = dict(server_info, schema_version=13)
    validate_server_info(newer)

    assert COLLECTOR_SCHEMA_VERSION == 12
    assert MIN_SUPPORTED_SERVER_SCHEMA_VERSION == 11


def test_schema_compatibility_rejects_non_overlapping_ranges() -> None:
    fixture = _load_fixture("ha_matter_ws_protocol_schema12.json")
    server_info = fixture["frames"][0]

    with pytest.raises(MatterWsSchemaCompatibilityError, match="older"):
        validate_server_info(dict(server_info, schema_version=10))
    with pytest.raises(MatterWsSchemaCompatibilityError, match="requires schema 13"):
        validate_server_info(dict(server_info, schema_version=13, min_supported_schema_version=13))


def test_thread_diagnostics_fixture_resolves_correct_attribute_semantics() -> None:
    fixture = _load_fixture("ha_matter_thread_diagnostics_revision3.json")

    resolved = {
        path: attribute_definition(path).name
        for path in fixture["attributes"]
        if attribute_definition(path) is not None
    }

    assert resolved == fixture["expectedNames"]
    assert THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES[7].name == "NeighborTable"
    assert THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES[8].name == "RouteTable"
    assert THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES[9].name == "PartitionId"
    assert THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES[0x3F].name == "ExtAddress"
    assert THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES[0x40].name == "Rloc16"


def test_live_thread_contract_matches_model_without_inventing_null_identity() -> None:
    fixture = _load_fixture("ha_matter_ws_live_thread_contract_schema12.json")
    attributes = fixture["attributes"]

    assert fixture["serverInfo"]["schema_version"] == COLLECTOR_SCHEMA_VERSION
    assert fixture["inventory"]["threadClusterRevision"] == 3
    assert attributes["0/53/7"]["entryFields"] == [
        str(field_id) for field_id in NEIGHBOR_TABLE_FIELDS
    ]
    assert attributes["0/53/8"]["entryFields"] == [
        str(field_id) for field_id in ROUTE_TABLE_FIELDS
    ]
    assert attributes["0/53/9"]["name"] == "PartitionId"
    for path in ("0/53/63", "0/53/64"):
        assert attributes[path]["cachedKind"] == "null"
        assert attributes[path]["targetedReadReported"] is False


def test_struct_field_contracts_are_exact_and_do_not_define_child_table() -> None:
    assert [NEIGHBOR_TABLE_FIELDS[index].name for index in range(14)] == [
        "ExtAddress",
        "Age",
        "Rloc16",
        "LinkFrameCounter",
        "MleFrameCounter",
        "Lqi",
        "AverageRssi",
        "LastRssi",
        "FrameErrorRate",
        "MessageErrorRate",
        "RxOnWhenIdle",
        "FullThreadDevice",
        "FullNetworkData",
        "IsChild",
    ]
    assert [ROUTE_TABLE_FIELDS[index].name for index in range(10)] == [
        "ExtAddress",
        "Rloc16",
        "RouterId",
        "NextHop",
        "PathCost",
        "LqiIn",
        "LqiOut",
        "Age",
        "Allocated",
        "LinkEstablished",
    ]
    assert "ChildTable" not in {
        element.name for element in THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES.values()
    }


def test_general_diagnostics_network_interface_contract_separates_ip_versions() -> None:
    assert GENERAL_DIAGNOSTICS_ATTRIBUTES[0].name == "NetworkInterfaces"
    assert NETWORK_INTERFACE_FIELDS[4].name == "HardwareAddress"
    assert NETWORK_INTERFACE_FIELDS[5].name == "IPv4Addresses"
    assert NETWORK_INTERFACE_FIELDS[6].name == "IPv6Addresses"
    assert NETWORK_INTERFACE_FIELDS[7].name == "Type"


def test_unknown_or_malformed_paths_are_not_guessed() -> None:
    assert attribute_definition("0/53/999") is None
    assert attribute_definition("0/31/0") is None
    assert attribute_definition("not/a/path") is None