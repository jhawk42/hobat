from __future__ import annotations

import base64
import ipaddress
import json
from pathlib import Path

import pytest

from ha_matter_ws_extractor import extract_nodes_info, parse_dump_file
from ha_matter_ws_snapshots import (
    MatterSnapshotSecurityError,
    build_device_snapshot,
)


FIXTURE = Path(__file__).parent / "fixtures" / "ha_matter_ws_phase1_nodes.json"


def test_phase1_fixture_parses_and_deduplicates_deterministically() -> None:
    nodes = parse_dump_file(FIXTURE)

    extracted = extract_nodes_info(nodes)

    assert [record["matter"]["nodeId"] for record in extracted] == [3, 7]
    assert extracted[1]["matter"]["deviceLabel"] == "Office Sensor"


def test_normalized_output_is_stable_under_frame_and_key_reordering() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def reverse_keys(value):
        if isinstance(value, dict):
            return {
                key: reverse_keys(child)
                for key, child in reversed(list(value.items()))
            }
        if isinstance(value, list):
            return [reverse_keys(child) for child in value]
        return value

    reordered_nodes = [
        reverse_keys(fixture["nodes"][1]),
        reverse_keys(fixture["nodes"][0]),
        reverse_keys(fixture["nodes"][2]),
    ]

    expected = build_device_snapshot(extract_nodes_info(fixture["nodes"]))
    actual = build_device_snapshot(extract_nodes_info(reordered_nodes))

    assert actual == expected


def test_non_thread_node_has_no_fake_thread_identity_or_relationships() -> None:
    wifi_record = extract_nodes_info(parse_dump_file(FIXTURE))[0]

    assert wifi_record["matter"]["deviceLabel"] == "Kitchen Plug"
    assert wifi_record["matter"]["vendorName"] == "Example Vendor"
    assert wifi_record["matter"]["vendorModel"] == "Example Plug"
    assert wifi_record["thread"] is None


def test_network_interfaces_keep_ip_versions_separate_and_select_thread() -> None:
    thread_record = extract_nodes_info(parse_dump_file(FIXTURE))[1]

    wifi, thread = thread_record["networkInterfaces"]
    assert wifi["ipv4Addresses"] == ["192.168.1.2"]
    assert wifi["ipv6Addresses"] == ["2001:db8::1"]
    assert thread["interfaceType"] == "Thread"
    assert thread_record["thread"]["extAddress"] == "1122334455667788"
    assert thread_record["thread"]["ipv6Addresses"] == ["fd3b:a255:4aa6:5483::1"]


def test_exact_thread_paths_do_not_invent_child_table_or_local_neighbor_identity() -> None:
    thread = extract_nodes_info(parse_dump_file(FIXTURE))[1]["thread"]

    assert thread["extAddress"] == "1122334455667788"
    assert thread["rloc16"] is None
    assert thread["partitionId"] == 343066305
    assert len(thread["neighborTable"]) == 1
    assert thread["neighborTable"][0]["isChild"] is True
    assert thread["routeTable"] == []
    assert "childTable" not in thread


@pytest.mark.parametrize(
    ("raw_percent", "expected"),
    [(0, 0), (1, 0.5), (151, 75.5), (200, 100)],
)
def test_power_source_converts_valid_half_percent_values(raw_percent, expected) -> None:
    record = extract_nodes_info(
        [{"node_id": 20, "attributes": {"4/47/12": raw_percent}}]
    )[0]
    source = record["powerSources"][0]

    assert source == {
        "endpointId": 4,
        "attributes": {"batPercentRemaining": raw_percent},
        "batteryPercent": expected,
    }
    assert record["endpoints"][0]["endpointId"] == 4
    assert record["diagnosticCoverage"]["powerSources"]["4"]["attributes"][
        "batPercentRemaining"
    ] == "populated"


@pytest.mark.parametrize("raw_percent", [-1, 201, 255, "50", 50.0, True])
def test_invalid_power_percent_is_omitted_and_covered(raw_percent) -> None:
    record = extract_nodes_info(
        [{"node_id": 21, "attributes": {"2/47/12": raw_percent}}]
    )[0]
    coverage = record["diagnosticCoverage"]["powerSources"]["2"]

    assert record["powerSources"] == [{"endpointId": 2, "attributes": {}}]
    assert coverage["attributes"]["batPercentRemaining"] == "invalidValue"
    assert coverage["invalidValues"]["2/47/12"] == "expected uint8 (0..200)"


def test_power_percent_null_missing_and_error_only_are_distinct() -> None:
    explicit_null = extract_nodes_info(
        [{"node_id": 22, "attributes": {"1/47/12": None}}]
    )[0]
    missing = extract_nodes_info(
        [{"node_id": 23, "attributes": {"1/47/0": 1}}]
    )[0]
    error_only = extract_nodes_info(
        [
            {
                "node_id": 24,
                "attributes": {},
                "attribute_errors": {"1/47/12": "Timeout"},
            }
        ]
    )[0]

    assert explicit_null["powerSources"][0]["attributes"]["batPercentRemaining"] is None
    assert explicit_null["powerSources"][0]["batteryPercent"] is None
    assert explicit_null["diagnosticCoverage"]["powerSources"]["1"]["attributes"][
        "batPercentRemaining"
    ] == "null"
    assert missing["powerSources"][0]["attributes"] == {"status": 1}
    assert "batteryPercent" not in missing["powerSources"][0]
    assert missing["diagnosticCoverage"]["powerSources"]["1"]["attributes"][
        "batPercentRemaining"
    ] == "notObserved"
    assert error_only["powerSources"] == []
    assert error_only["diagnosticCoverage"]["powerSources"]["1"]["attributes"][
        "batPercentRemaining"
    ] == "readError"
    assert error_only["diagnosticCoverage"]["powerSources"]["1"]["cluster"] == "readError"


def test_power_source_scope_bridged_identity_and_wired_only_sources_stay_separate() -> None:
    record = extract_nodes_info(
        [
            {
                "node_id": 25,
                "attributes": {
                    "1/57/1": "Bridge sensor vendor",
                    "1/57/3": "Window sensor",
                    "1/57/17": False,
                    "1/57/65533": 6,
                    "2/47/0": 1,
                    "2/47/2": "Sensor battery",
                    "2/47/12": 151,
                    "2/47/31": [1],
                    "3/47/0": 1,
                    "3/47/2": "Backup battery",
                    "3/47/12": 0,
                    "3/47/31": [],
                    "4/47/0": 2,
                    "4/47/2": "USB power",
                    "4/47/9": True,
                    "4/47/31": [4],
                },
            }
        ]
    )[0]
    endpoints = {endpoint["endpointId"]: endpoint for endpoint in record["endpoints"]}
    sources = {source["endpointId"]: source for source in record["powerSources"]}

    assert endpoints[1]["bridgedBasicInformation"] == {
        "vendorName": "Bridge sensor vendor",
        "productName": "Window sensor",
        "reachable": False,
        "clusterRevision": 6,
    }
    assert "vendorName" not in record["matter"] or record["matter"]["vendorName"] is None
    assert sources[2]["batteryPercent"] == 75.5
    assert sources[2]["attributes"]["endpointList"] == [1]
    assert sources[3]["batteryPercent"] == 0
    assert sources[3]["attributes"]["endpointList"] == []
    assert sources[4]["attributes"] == {
        "status": 2,
        "description": "USB power",
        "wiredPresent": True,
        "endpointList": [4],
    }
    assert "batteryPercent" not in sources[4]
    assert record["diagnosticCoverage"]["bridgedBasicInformation"]["1"]["cluster"] == "populated"
    assert record["diagnosticCoverage"]["powerSources"]["2"]["cluster"] == "populated"


def test_power_source_revision_one_unknown_enums_and_malformed_lists_are_retained_safely() -> None:
    record = extract_nodes_info(
        [
            {
                "node_id": 26,
                "attributes": {
                    "5/47/0": 255,
                    "5/47/12": 200,
                    "5/47/18": [False, "bad"],
                    "5/47/31": "not-an-endpoint-list",
                    "5/47/65533": 1,
                },
            }
        ]
    )[0]
    source = record["powerSources"][0]
    coverage = record["diagnosticCoverage"]["powerSources"]["5"]

    assert source["attributes"]["status"] == 255
    assert source["attributes"]["batPercentRemaining"] == 200
    assert source["batteryPercent"] == 100
    assert source["attributes"]["clusterRevision"] == 1
    assert "endpointList" not in source["attributes"]
    assert coverage["attributes"]["endpointList"] == "invalidValue"
    assert coverage["invalidValues"]["5/47/31"] == "expected list<endpoint-no>"
    assert coverage["attributes"]["batChargeState"] == "notObserved"


def test_coverage_uses_complete_descriptor_and_attribute_lists_without_feature_guesses() -> None:
    record = extract_nodes_info(
        [
            {
                "node_id": 27,
                "attributes": {
                    "0/29/1": [0x001D, 0x0028, 0x002F, 0x0033],
                    "0/40/65531": [0xFFFB, 0xFFFC, 0xFFFD],
                    "0/40/65533": 6,
                    "0/47/65531": [0, 1, 2, 0xFFFB, 0xFFFC, 0xFFFD],
                    "0/47/65532": 0,
                    "0/47/65533": 3,
                    "0/51/65531": [0xFFFB, 0xFFFC, 0xFFFD],
                    "0/51/65533": 3,
                    "1/29/1": [0x001D, 0x002F],
                    "1/47/65532": 0,
                    "1/47/65533": 3,
                },
            }
        ]
    )[0]
    coverage = record["diagnosticCoverage"]

    assert coverage["basicInformation"]["attributes"]["vendorName"] == "attributeUnsupported"
    assert coverage["generalDiagnostics"]["attributes"]["rebootCount"] == "attributeUnsupported"
    assert coverage["powerSources"]["0"]["attributes"]["batPercentRemaining"] == "attributeUnsupported"
    assert coverage["powerSources"]["0"]["cluster"] == "populated"
    assert coverage["powerSources"]["1"]["attributes"]["batPercentRemaining"] == "notObserved"
    assert coverage["bridgedBasicInformation"] == {}
    assert record["powerSources"][0]["attributes"]["featureMap"] == 0
    assert "batPercentRemaining" not in record["powerSources"][0]["attributes"]


def test_observed_values_override_contradictory_metadata_and_malformed_lists_are_unknown() -> None:
    record = extract_nodes_info(
        [
            {
                "node_id": 28,
                "attributes": {
                    "0/29/1": [0x001D],
                    "0/47/12": 1,
                    "0/47/65531": ["malformed", 1],
                    "0/47/65533": 3,
                },
                "attribute_errors": {"0/47/12": "StaleReadError"},
            }
        ]
    )[0]
    coverage = record["diagnosticCoverage"]["powerSources"]["0"]

    assert record["powerSources"][0]["batteryPercent"] == 0.5
    assert coverage["attributes"]["batPercentRemaining"] == "readError"
    assert coverage["attributes"]["attributeList"] == "invalidValue"
    assert coverage["cluster"] == "readError"
    assert record["diagnosticCoverage"]["basicInformation"]["cluster"] == "notObserved"


def test_general_diagnostics_type_checks_values_and_preserves_exact_uint64() -> None:
    large_uptime = 2**63 + 99
    record = extract_nodes_info(
        [
            {
                "node_id": 29,
                "attributes": {
                    "0/51/2": large_uptime,
                    "0/51/3": True,
                    "0/51/5": [0, False],
                },
            }
        ]
    )[0]
    diagnostics = record["generalDiagnostics"]
    coverage = record["diagnosticCoverage"]["generalDiagnostics"]

    assert diagnostics["upTime"] == large_uptime
    assert type(diagnostics["upTime"]) is int
    assert "totalOperationalHours" not in diagnostics
    assert "activeHardwareFaults" not in diagnostics
    assert coverage["attributes"]["upTime"] == "populated"
    assert coverage["attributes"]["totalOperationalHours"] == "invalidValue"
    assert coverage["attributes"]["activeHardwareFaults"] == "invalidValue"


@pytest.mark.parametrize(
    "uptime",
    ["0", "9223372036854775907", "18446744073709551615"],
)
def test_uint64_uptime_decimal_strings_remain_exact(uptime) -> None:
    record = extract_nodes_info(
        [{"node_id": 30, "attributes": {"0/51/2": uptime}}]
    )[0]

    assert record["generalDiagnostics"]["upTime"] == uptime
    assert record["diagnosticCoverage"]["generalDiagnostics"]["attributes"][
        "upTime"
    ] == "populated"


@pytest.mark.parametrize(
    "uptime",
    [
        "18446744073709551616",
        "-1",
        "1.0",
        "not-a-number",
        "9" * 21,
    ],
)
def test_invalid_uint64_uptime_strings_are_not_coerced(uptime) -> None:
    record = extract_nodes_info(
        [{"node_id": 31, "attributes": {"0/51/2": uptime}}]
    )[0]

    assert "upTime" not in record["generalDiagnostics"]
    assert record["diagnosticCoverage"]["generalDiagnostics"]["attributes"][
        "upTime"
    ] == "invalidValue"


def test_thread_rloc16_falls_back_to_interface_ipv6_without_overriding_reported_value() -> None:
    rloc_address = base64.b64encode(
        ipaddress.IPv6Address("fd3b:a255:4aa6:5483:0:ff:fe00:1c05").packed
    ).decode()
    hardware_address = base64.b64encode(bytes.fromhex("1122334455667788")).decode()
    attributes = {
        "0/51/0": [
            {
                "0": "thread0",
                "1": True,
                "4": hardware_address,
                "5": [],
                "6": [rloc_address],
                "7": 4,
            }
        ],
        "0/53/64": None,
    }

    derived = extract_nodes_info([{"node_id": 1, "attributes": attributes}])[0]
    reported = extract_nodes_info(
        [{"node_id": 2, "attributes": {**attributes, "0/53/64": 0x2400}}]
    )[0]

    assert derived["thread"]["rloc16"] == "0x1c05"
    assert reported["thread"]["rloc16"] == "0x2400"


def test_normalized_records_do_not_retain_sensitive_clusters() -> None:
    records = extract_nodes_info(parse_dump_file(FIXTURE))
    payload = json.dumps(build_device_snapshot(records), sort_keys=True)

    for forbidden in ("SENSITIVE-NOC", "SENSITIVE-ROOT", "SENSITIVE-GROUP-KEY"):
        assert forbidden not in payload
    assert "operationalCredentials" not in payload
    assert "groupKey" not in payload


def test_snapshot_builder_rejects_credential_shaped_final_fields() -> None:
    with pytest.raises(MatterSnapshotSecurityError, match="trustedRootCertificates"):
        build_device_snapshot(
            [{"matter": {"nodeId": 1}, "trustedRootCertificates": ["secret"]}]
        )


def test_device_snapshot_maps_commissioned_thread_roles_and_explicit_false() -> None:
    records = [
        {
            "matter": {"nodeId": 1, "matterId": "FABRIC-1"},
            "thread": {"routingRole": "Reed", "isRouter": True},
        },
        {
            "matter": {"nodeId": 2, "matterId": "FABRIC-2"},
            "thread": {"routingRole": "Leader"},
            "isLeader": False,
        },
        {"matter": {"nodeId": 3, "matterId": "FABRIC-3"}},
    ]

    devices = build_device_snapshot(records)

    assert {
        key: devices[0][key]
        for key in ("isRouter", "isLeader", "isReed")
    } == {"isRouter": True, "isLeader": False, "isReed": True}
    assert devices[0]["_merge_conflicts"] == [
        {"path": "isRouter", "current": True, "incoming": False}
    ]
    assert devices[1]["isLeader"] is False
    assert devices[1]["_merge_conflicts"] == [
        {"path": "isLeader", "current": False, "incoming": True}
    ]
    assert not any(
        key in devices[2] for key in ("isBorderRouter", "isRouter", "isLeader", "isReed")
    )


def test_device_snapshot_resolves_strict_role_aliases_before_generic_normalization() -> None:
    records = [
        {
            "matter": {"nodeId": 1, "matterId": "FABRIC-1"},
            "thread": {"routingRole": "Reed"},
            "isRouter": "true",
            "is_router": True,
        },
        {
            "matter": {"nodeId": 2, "matterId": "FABRIC-2"},
            "thread": {"routingRole": "Leader"},
            "isBorderRouter": "true",
        },
        {
            "matter": {"nodeId": 3, "matterId": "FABRIC-3"},
            "thread": {"routingRole": "Reed"},
            "isRouter": "true",
        },
    ]

    devices = build_device_snapshot(records)

    assert devices[0]["isRouter"] is True
    assert devices[0]["_merge_conflicts"] == [
        {"path": "isRouter", "current": True, "incoming": False}
    ]
    assert "isBorderRouter" not in devices[1]
    assert devices[2]["isRouter"] is False