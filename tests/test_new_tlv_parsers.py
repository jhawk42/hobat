"""
Unit tests for new TLV parsing functions (Phase 3 Testing).

Tests the 8 new parsing functions added for TLVs: 23, 4, 6, 24, 25, 26, 27, 5
"""

import os
import ipaddress

import otbr_cli_networkdiag_topology as topology
from otbr_cli_networkdiag_util import (
    TLV_VALUES_BASIC,
    TLV_VALUES_CHILD_DETAILED,
    TLV_VALUES_DETAILED,
)
from otbr_cli_networkdiag_parsers import (
    build_tlv_response_observation,
    build_unframed_tlv_response_observation,
    build_tlv_response_observation,
    create_diagnostic_collection_context,
    decode_diagnostic_tlvs,
    parse_diagnostic_tlv_payload,
    parse_network_diagnostic_response_frames,
    register_diagnostic_request,
)

# Add src directory to path
from otbr_cli_networkdiag_topology import (
    parse_eui64,
    parse_connectivity,
    parse_leader_data,
    parse_vendor_name,
    parse_vendor_model,
    parse_vendor_sw_version,
    parse_route_data,
    parse_multicast_diag_output,
    fetch_network_diag_for_device,
    _attach_router_id,
    _mark_primary_bbr,
)
from td_device_fields import normalize_input_record


def _wire_tlv(tlv_type, value):
    if len(value) < 0xFF:
        return bytes((tlv_type, len(value))) + value
    return bytes((tlv_type, 0xFF)) + len(value).to_bytes(2, "big") + value


def _response(responder, payload, fields=""):
    return f"DIAG_GET.rsp/ans from {responder}: {payload.hex()}\n{fields}"


def test_parse_eui64():
    """Test EUI64 parsing (TLV 23)."""
    print("\n--- Testing parse_eui64 ---")
    
    # Test valid EUI64
    output = "EUI64: f434f0fffe1e1774"
    result = parse_eui64(output)
    assert result == "f434f0fffe1e1774"
    
    # Test missing EUI64
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_eui64(output)
    assert result is None


def test_parse_connectivity():
    """Test Connectivity parsing (TLV 4)."""
    print("\n--- Testing parse_connectivity ---")
    
    # Test full connectivity block
    output = """Connectivity:
    ParentPriority: 0
    LinkQuality3: 13
    LinkQuality2: 3
    LinkQuality1: 3
    LeaderCost: 1
    IdSequence: 180
    ActiveRouters: 21
    SedBufferSize: 1280
    SedDatagramCount: 1"""
    
    result = parse_connectivity(output)
    assert result.get("parent_priority") == 0
    assert result.get("link_quality_3") == 13
    assert result.get("leader_cost") == 1
    assert result.get("id_sequence") == 180
    assert result.get("active_routers") == 21
    assert result.get("sed_buffer_size") == 1280
    
    # Test missing connectivity
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_connectivity(output)
    assert result == {}


def test_parse_leader_data():
    """Test Leader Data parsing (TLV 6)."""
    print("\n--- Testing parse_leader_data ---")
    
    # Test full leader data block
    output = """Leader Data:
    PartitionId: 0x533966c4
    Weighting: 68
    DataVersion: 113
    StableDataVersion: 140
    LeaderRouterId: 0x34"""
    
    result = parse_leader_data(output)
    assert result.get("partition_id") == "0x533966c4"
    assert result.get("weighting") == 68
    assert result.get("data_version") == 113
    assert result.get("stable_data_version") == 140
    assert result.get("leader_router_id") == "0x34"
    
    # Test missing leader data
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_leader_data(output)
    assert result == {}


def test_cli_leader_evidence_requires_matching_router_id_in_same_record():
    record = {"rloc16": "0x8c00", "leader_data": {"leader_router_id": "0x3e"}}
    _attach_router_id(record, {"0x3e": {"rloc16": "0x8c00", "router_id": "0x3e"}})
    normalized = normalize_input_record(record, source="cli")
    assert normalized["routerId"] == 62
    assert normalized["leaderData"]["leaderRouterId"] == 62
    assert normalized["isLeader"] is True
    assert normalized["leaderEvidence"] == "leader-router-id-match"

    unmatched = normalize_input_record(
        {"router_id": "0x00", "leader_data": {"leader_router_id": "0x3e"}},
        source="cli",
    )
    assert "isLeader" not in unmatched


def test_cli_primary_bbr_evidence_marks_only_matching_multicast_record():
    matching = {"rloc16": "0x8c00"}
    _mark_primary_bbr(matching, {"primary": {"server16": "0x8c00"}})
    assert matching["is_primary_bbr"] is True
    assert matching["primary_bbr_evidence"] == "otbr-cli-bbr-server16-match"

    unmatched = {"rloc16": "0x9000"}
    _mark_primary_bbr(unmatched, {"primary": {"server16": "0x8c00"}})
    assert "is_primary_bbr" not in unmatched


def test_parse_vendor_fields():
    """Test Vendor Name, Model, and SW Version parsing (TLVs 25, 26, 27)."""
    print("\n--- Testing parse_vendor_* ---")
    
    # Test valid vendor name
    output = "Vendor Name: Apple"
    result = parse_vendor_name(output)
    assert result == "Apple"
    
    # Test empty vendor name
    output = "Vendor Name: "
    result = parse_vendor_name(output)
    assert result == ""
    
    # Test missing vendor name
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_vendor_name(output)
    assert result is None
    
    # Test valid vendor model
    output = "Vendor Model: Default"
    result = parse_vendor_model(output)
    assert result == "Default"
    
    # Test empty vendor model
    output = "Vendor Model: "
    result = parse_vendor_model(output)
    assert result == ""
    
    # Test valid vendor SW version
    output = "Vendor SW Version: Default"
    result = parse_vendor_sw_version(output)
    assert result == "Default"
    
    # Test empty vendor SW version
    output = "Vendor SW Version: "
    result = parse_vendor_sw_version(output)
    assert result == ""


def test_parse_route_data():
    """Test Route data parsing (TLV 5)."""
    print("\n--- Testing parse_route_data ---")
    
    # Test route with multiple entries
    output = """Route:
    IdSequence: 180
    RouteData:
        - RouteId: 0x03
          LinkQualityOut: 2
          LinkQualityIn: 2
          RouteCost: 2
        - RouteId: 0x04
          LinkQualityOut: 3
          LinkQualityIn: 3
          RouteCost: 1
        - RouteId: 0x08
          LinkQualityOut: 3
          LinkQualityIn: 3
          RouteCost: 1"""
    
    result = parse_route_data(output)
    assert result.get("id_sequence") == 180
    
    route_data = result.get("route_data", [])
    assert len(route_data) == 3
    
    if len(route_data) >= 1:
        assert route_data[0].get("route_id") == "0x03"
        assert route_data[0].get("link_quality_out") == 2
        assert route_data[0].get("route_cost") == 2
    
    if len(route_data) >= 2:
        assert route_data[1].get("route_id") == "0x04"
        assert route_data[1].get("route_cost") == 1
    
    # Test missing route data
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_route_data(output)
    assert result == {}


def test_example_file_7c00():
    """Test parsing against test_tlvs_7c00.txt example file."""
    print("\n--- Testing test_tlvs_7c00.txt ---")
    
    file_path = os.path.join(os.path.dirname(__file__), 'logs', 'test_tlvs_7c00.txt')
    with open(file_path, 'r') as f:
        output = f.read()
    
    # Test individual parsers
    eui64 = parse_eui64(output)
    assert eui64 == "f434f0fffe1e1774"
    
    connectivity = parse_connectivity(output)
    assert connectivity.get("link_quality_3") == 13
    assert connectivity.get("leader_cost") == 1
    
    leader_data = parse_leader_data(output)
    assert leader_data.get("partition_id") == "0x533966c4"
    assert leader_data.get("weighting") == 68
    
    vendor_name = parse_vendor_name(output)
    assert vendor_name == "Apple"
    
    vendor_model = parse_vendor_model(output)
    assert vendor_model == "Default"
    
    vendor_sw_version = parse_vendor_sw_version(output)
    assert vendor_sw_version == "Default"
    
    route_data = parse_route_data(output)
    assert route_data.get("id_sequence") == 180
    assert len(route_data.get("route_data", [])) >= 3


def test_example_file_6000():
    """Test parsing against test_tlvs_6000.txt example file (empty vendor fields)."""
    print("\n--- Testing test_tlvs_6000.txt ---")
    
    file_path = os.path.join(os.path.dirname(__file__), 'logs', 'test_tlvs_6000.txt')
    with open(file_path, 'r') as f:
        output = f.read()
    
    # A present, zero-length vendor TLV is distinct from an omitted TLV.
    vendor_name = parse_vendor_name(output)
    assert vendor_name == ""
    
    vendor_model = parse_vendor_model(output)
    assert vendor_model == ""
    
    vendor_sw_version = parse_vendor_sw_version(output)
    assert vendor_sw_version == ""
    
    # Other fields should still parse correctly
    eui64 = parse_eui64(output)
    assert eui64 == "f4ce36a9111c02c1"
    
    connectivity = parse_connectivity(output)
    assert connectivity.get("leader_cost") == 2


def test_multicast_integration():
    """Test parse_multicast_diag_output integration with new TLV fields."""
    print("\n--- Testing multicast integration ---")
    
    file_path = os.path.join(os.path.dirname(__file__), 'logs', 'test_tlvs_7c00.txt')
    with open(file_path, 'r') as f:
        output = f.read()
    
    # Parse as multicast output
    parsed = parse_multicast_diag_output(output, extaddr_map={})
    
    # Should have one device
    assert len(parsed) == 1
    
    # Get the device record
    device = list(parsed.values())[0] if parsed else {}
    
    # Verify new fields are present
    assert "eui64" in device
    assert "connectivity" in device
    assert "leader_data" in device
    assert "vendor_name" in device
    assert "vendor_model" in device
    assert "vendor_sw_version" in device
    assert "route" in device
    
    # Verify field values
    assert device.get("eui64") == "f434f0fffe1e1774"
    assert device.get("vendor_name") == "Apple"
    assert device.get("rloc16") == "0x7c00"
    assert device["thread_version_decimal"] == 4
    assert device["thread_version"] == "1.3"


def test_multicast_thread_version_requires_valid_tlv_24() -> None:
    for payload in (
        "00080011223344556677",
        "180100",
        "180200",
        "190418020004",
    ):
        output = f"DIAG_GET.rsp/ans from fd00::1: {payload}\nExt Address: 0011223344556677\n"
        device = parse_multicast_diag_output(output)["0011223344556677"]
        assert "thread_version_decimal" not in device
        assert "thread_version" not in device

    payload = "00ff0008001122334455667718020005"
    output = f"DIAG_GET.rsp/ans from fd00::1: {payload}\nExt Address: 0011223344556677\n"
    device = parse_multicast_diag_output(output)["0011223344556677"]
    assert device["thread_version_decimal"] == 5
    assert device["thread_version"] == "1.4"


def test_raw_tlv_parser_validates_complete_stream_and_extended_lengths() -> None:
    malformed = parse_diagnostic_tlv_payload("18020005ff")
    assert malformed["status"] == "malformed"
    assert malformed["error"] == "truncated-header"
    assert malformed["tlvs"] == []

    extended = parse_diagnostic_tlv_payload("feff0100" + "ab" * 256)
    assert extended["status"] == "valid"
    assert extended["received_type_ids"] == [254]
    assert len(extended["tlvs"][0]["value"]) == 256

    invalid_hex = parse_diagnostic_tlv_payload("1802000g")
    assert invalid_hex["status"] == "malformed"
    assert invalid_hex["error"] == "malformed-hex"


def test_raw_tlv_parser_classifies_all_truncated_frame_boundaries() -> None:
    cases = (
        ("g0", "malformed-hex"),
        ("ff", "truncated-header"),
        ("01ff00", "truncated-extended-length"),
        ("0102ff", "truncated-value"),
        ("18020005ff", "truncated-header"),
    )
    for payload, expected_error in cases:
        parsed = parse_diagnostic_tlv_payload(payload)
        assert parsed["status"] == "malformed"
        assert parsed["error"] == expected_error
        assert parsed["tlvs"] == []
        assert parsed["received_type_ids"] == []


def test_response_envelope_without_payload_retains_responder_address() -> None:
    frames = parse_network_diagnostic_response_frames(
        "DIAG_GET.rsp/ans from fd00::1: \n"
    )

    assert len(frames) == 1
    assert frames[0]["responder_ipv6"] == "fd00::1"
    assert frames[0]["payload_hex"] is None


def test_multicast_thread_version_rejects_malformed_suffix_after_tlv() -> None:
    output = (
        "DIAG_GET.rsp/ans from fd00::1: 18020005ff\n"
        "Ext Address: 0011223344556677\n"
    )

    device = parse_multicast_diag_output(output)["0011223344556677"]

    assert "thread_version_decimal" not in device
    assert "thread_version" not in device


def test_raw_tlv_semantic_validation_preserves_other_valid_types() -> None:
    payload = (
        _wire_tlv(0, bytes.fromhex("0011223344556677"))
        + _wire_tlv(1, b"\x04")
        + _wire_tlv(24, b"\x00\x05")
        + _wire_tlv(24, b"\x00\x06")
        + _wire_tlv(200, b"\x01")
    )
    parsed = parse_diagnostic_tlv_payload(payload.hex())
    decoded = decode_diagnostic_tlvs(parsed)

    assert parsed["received_type_ids"] == [0, 1, 24, 24, 200]
    assert decoded["values"]["extaddr"] == "0011223344556677"
    assert 1 in decoded["malformed_type_ids"]
    assert 24 in decoded["malformed_type_ids"]
    assert decoded["undecoded_type_ids"] == [200]
    assert "thread_version_decimal" not in decoded["values"]


def test_raw_parser_uses_open_thread_control_tlv_wire_values() -> None:
    payload = (
        _wire_tlv(32, b"\x80\x07")
        + _wire_tlv(33, b"\x12\x34")
    )
    decoded = decode_diagnostic_tlvs(parse_diagnostic_tlv_payload(payload.hex()))

    assert decoded["query_id"] == 0x1234
    assert decoded["answer_index"] == 7
    assert decoded["is_final_answer"] is True


def test_route64_length_accepts_standard_and_packed_long_route_entries() -> None:
    router_mask = b"\xc0" + bytes(7)
    standard = _wire_tlv(5, b"\x01" + router_mask + b"\x00\x00")
    packed_long = _wire_tlv(5, b"\x01" + router_mask + b"\x00\x00\x00")

    assert decode_diagnostic_tlvs(parse_diagnostic_tlv_payload(standard.hex()))[
        "malformed_type_ids"
    ] == []
    assert decode_diagnostic_tlvs(parse_diagnostic_tlv_payload(packed_long.hex()))[
        "malformed_type_ids"
    ] == []

    invalid = _wire_tlv(5, b"\x01" + router_mask + b"\x00\x00\x00\x00")
    assert decode_diagnostic_tlvs(parse_diagnostic_tlv_payload(invalid.hex()))[
        "malformed_type_ids"
    ] == [5]


def test_multicast_query_id_correlation_groups_answers_and_keeps_unknown_ids_unknown() -> None:
    collection = create_diagnostic_collection_context()
    detail_request = register_diagnostic_request(
        collection, "multicast-network", "ff03::1", 0, TLV_VALUES_DETAILED
    )
    base_payload = (
        _wire_tlv(0, bytes.fromhex("0011223344556677"))
        + _wire_tlv(1, b"\x04\x00")
        + _wire_tlv(2, b"\x0f")
        + _wire_tlv(8, ipaddress.IPv6Address("fd00::1").packed)
        + _wire_tlv(24, b"\x00\x05")
    )
    first = _response(
        "fd00::1",
        base_payload + _wire_tlv(32, b"\x80\x00") + _wire_tlv(33, b"\x12\x34"),
        "Ext Address: 0011223344556677\nRloc16: 0x0400\n",
    )
    first_record = parse_multicast_diag_output(
        first,
        collection_context=collection,
        request_context=detail_request,
        capture_stage="multicast-network",
        capture_target="ff03::1",
        capture_attempt_index=0,
    )["0011223344556677"]
    [first_observation] = first_record["tlv_response_history"]
    assert first_observation["attributed_request_attempt_index"] == 0
    assert first_observation["requested_type_ids"] == [int(t) for t in TLV_VALUES_DETAILED.split()]

    basic_request = register_diagnostic_request(
        collection, "multicast-network", "ff03::1", 1, TLV_VALUES_BASIC
    )
    answer_zero = _response(
        "fd00::1",
        base_payload + _wire_tlv(32, b"\x00\x00") + _wire_tlv(33, b"\x12\x34"),
        "Ext Address: 0011223344556677\nRloc16: 0x0400\n",
    )
    answer_one = _response(
        "fd00::1",
        base_payload + _wire_tlv(32, b"\x80\x01") + _wire_tlv(33, b"\x12\x34"),
        "Ext Address: 0011223344556677\nRloc16: 0x0400\n",
    )
    grouped = parse_multicast_diag_output(
        answer_zero + answer_one,
        collection_context=collection,
        request_context=basic_request,
        capture_stage="multicast-network",
        capture_target="ff03::1",
        capture_attempt_index=1,
    )["0011223344556677"]["tlv_response_history"]
    assert [entry["answer_index"] for entry in grouped] == [0, 0, 1]
    assert [entry["final_answer"] for entry in grouped] == [True, False, True]
    assert len({entry["response_group_id"] for entry in grouped}) == 1
    assert all(entry["attributed_request_attempt_index"] == 0 for entry in grouped)

    unknown_payload = (
        _wire_tlv(0, bytes.fromhex("0011223344556677"))
        + _wire_tlv(1, b"\x04\x00")
        + _wire_tlv(2, b"\x0f")
        + _wire_tlv(8, ipaddress.IPv6Address("fd00::1").packed)
        + _wire_tlv(32, b"\x80\x00")
        + _wire_tlv(33, b"\x99\x99")
    )
    unknown = parse_multicast_diag_output(
        _response("fd00::1", unknown_payload, "Ext Address: 0011223344556677\nRloc16: 0x0400\n"),
        collection_context=collection,
        request_context=basic_request,
        capture_stage="multicast-network",
        capture_target="ff03::1",
        capture_attempt_index=1,
    )["0011223344556677"]["tlv_response_history"][0]
    assert unknown["query_id"] == 0x9999
    assert unknown["request_association"] == "ambiguous"
    assert unknown["attributed_request"] is None
    assert unknown["requested_type_ids"] is None

    legacy = parse_multicast_diag_output(
        _response("fd00::1", base_payload, "Ext Address: 0011223344556677\nRloc16: 0x0400\n"),
        collection_context=collection,
        request_context=basic_request,
        capture_stage="multicast-network",
        capture_target="ff03::1",
        capture_attempt_index=1,
    )["0011223344556677"]["tlv_response_history"][0]
    assert legacy["request_association"] == "uncorrelated"
    assert legacy["attributed_request"] is None
    assert legacy["requested_type_ids"] is None


def test_later_exclusive_tlv_binds_prior_same_query_observation() -> None:
    collection = create_diagnostic_collection_context()
    detail_request = register_diagnostic_request(
        collection, "multicast-network", "ff03::1", 0, TLV_VALUES_DETAILED
    )
    basic_request = register_diagnostic_request(
        collection, "multicast-network", "ff03::1", 1, TLV_VALUES_BASIC
    )
    extaddr = "0011223344556677"
    common_payload = (
        _wire_tlv(0, bytes.fromhex(extaddr))
        + _wire_tlv(1, b"\x04\x00")
        + _wire_tlv(2, b"\x0f")
        + _wire_tlv(8, ipaddress.IPv6Address("fd00::1").packed)
    )
    common_output = _response(
        "fd00::1",
        common_payload + _wire_tlv(32, b"\x80\x00") + _wire_tlv(33, b"\x12\x34"),
        f"Ext Address: {extaddr}\nRloc16: 0x0400\n",
    )
    parse_multicast_diag_output(
        common_output,
        collection_context=collection,
        request_context=detail_request,
        capture_stage="multicast-network",
        capture_target="ff03::1",
        capture_attempt_index=0,
    )
    assert collection["observations"][0]["request_association"] == "ambiguous"

    detailed_late_output = _response(
        "fd00::1",
        common_payload
        + _wire_tlv(24, b"\x00\x05")
        + _wire_tlv(32, b"\x80\x01")
        + _wire_tlv(33, b"\x12\x34"),
        f"Ext Address: {extaddr}\nRloc16: 0x0400\n",
    )
    parse_multicast_diag_output(
        detailed_late_output,
        collection_context=collection,
        request_context=basic_request,
        capture_stage="multicast-network",
        capture_target="ff03::1",
        capture_attempt_index=1,
    )

    prior, late = collection["observations"]
    assert prior["request_association"] == "query-id"
    assert prior["attributed_request_attempt_index"] == 0
    assert late["attributed_request_attempt_index"] == 0
    assert prior["requested_type_ids"] == [int(t) for t in TLV_VALUES_DETAILED.split()]


def test_multicast_answer_frames_merge_fields_and_retain_grouped_history() -> None:
    extaddr = "0011223344556677"
    query_id = b"\x22\x22"
    answer_zero = _response(
        "fd00::1",
        _wire_tlv(0, bytes.fromhex(extaddr))
        + _wire_tlv(1, b"\x04\x00")
        + _wire_tlv(25, b"Acme")
        + _wire_tlv(32, b"\x00\x00")
        + _wire_tlv(33, query_id),
        f"Ext Address: {extaddr}\nRloc16: 0x0400\nVendor Name: Acme\n",
    )
    answer_one = _response(
        "fd00::1",
        _wire_tlv(1, b"\x04\x00")
        + _wire_tlv(2, b"\x0f")
        + _wire_tlv(8, ipaddress.IPv6Address("fd00::1").packed)
        + _wire_tlv(16, b"\x00\x00\x0f")
        + _wire_tlv(32, b"\x80\x01")
        + _wire_tlv(33, query_id),
        "Rloc16: 0x0400\n"
        "Mode:\n    RxOnWhenIdle: 1\n    DeviceType: 1\n    NetworkData: 1\n"
        "IP6 Address List:\n    - fd00::1\n"
        "Child Table:\n    ChildId: 0x0001\n    Timeout: 30\n    Link Quality: 3\n",
    )
    collection = create_diagnostic_collection_context()
    request = register_diagnostic_request(
        collection, "multicast-network", "ff03::1", 0, TLV_VALUES_DETAILED
    )

    first_record = parse_multicast_diag_output(
        answer_zero,
        collection_context=collection,
        request_context=request,
        capture_stage="multicast-network",
        capture_target="ff03::1",
        capture_attempt_index=0,
    )[extaddr]
    basic_request = register_diagnostic_request(
        collection, "multicast-network", "ff03::1", 1, TLV_VALUES_BASIC
    )
    [record] = parse_multicast_diag_output(
        answer_one,
        collection_context=collection,
        request_context=basic_request,
        capture_stage="multicast-network",
        capture_target="ff03::1",
        capture_attempt_index=1,
    ).values()

    assert record["vendor_name"] == "Acme"
    assert record["rloc16"] == "0x0400"
    assert record["mode"]["rx_on_when_idle"] == 1
    assert record["children"][0]["rloc16"] == "0x0401"
    assert [item["answer_index"] for item in record["tlv_response_history"]] == [0, 1]
    assert len({item["response_group_id"] for item in record["tlv_response_history"]}) == 1
    assert first_record["tlv_response_history"][0]["observation_id"] == record["tlv_response_history"][0]["observation_id"]

    [context_free_record] = parse_multicast_diag_output(
        answer_zero + answer_one
    ).values()
    assert context_free_record["extaddr"] == extaddr
    assert context_free_record["rloc16"] == "0x0400"
    assert context_free_record["vendor_name"] == "Acme"
    assert context_free_record["mode"]["rx_on_when_idle"] == 1
    assert context_free_record["children"][0]["rloc16"] == "0x0401"


def test_direct_router_path_decodes_raw_version_and_preserves_empty_vendor(monkeypatch) -> None:
    rloc_prefix = topology.util_network.build_rloc_ipv6_address_prefix("fd00::/64")
    target = topology.util_network.build_rloc16_ipv6_address(rloc_prefix, "0400")
    extaddr = "0011223344556677"
    payload = (
        _wire_tlv(0, bytes.fromhex(extaddr))
        + _wire_tlv(1, b"\x04\x00")
        + _wire_tlv(2, b"\x0f")
        + _wire_tlv(8, ipaddress.IPv6Address("fd00::1").packed)
        + _wire_tlv(24, b"\x00\x05")
        + _wire_tlv(25, b"")
        + _wire_tlv(26, b"")
        + _wire_tlv(27, b"")
        + _wire_tlv(28, b"stack-version")
    )
    output = _response(
        target,
        payload,
        "Ext Address: 0011223344556677\n"
        "Rloc16: 0x0400\n"
        "Mode:\n    RxOnWhenIdle: 1\n    DeviceType: 1\n    NetworkData: 1\n"
        "IP6 Address List:\n    - fd00::1\n"
        "Vendor Name: \nVendor Model: \nVendor SW Version: \n"
        "Thread Stack Version: stack-version\n",
    )
    monkeypatch.setattr(topology.util_ot_ctl, "exec_ot_ctl", lambda _command: output)
    collection = create_diagnostic_collection_context()

    record = fetch_network_diag_for_device(
        "0x0400",
        rloc_prefix,
        {},
        {},
        {},
        10,
        collection_context=collection,
        capture_stage="direct-router",
        capture_attempt_index=0,
    )

    assert record["thread_version_decimal"] == 5
    assert record["thread_version"] == "1.4"
    assert record["thread_stack_version"] == "stack-version"
    assert record["vendor_name"] == ""
    assert record["vendor_model"] == ""
    assert record["vendor_sw_version"] == ""
    [observation] = record["tlv_response_history"]
    assert observation["capture_stage"] == "direct-router"
    assert observation["query_id"] is None
    assert observation["request_association"] == "responder-target"
    assert observation["requested_type_ids"] == [int(t) for t in TLV_VALUES_DETAILED.split()]
    assert observation["omitted_type_ids"] == [4, 5, 6, 9, 16, 23, 34]
    assert observation["unrequested_type_ids"] == []


def test_direct_child_path_records_child_request_provenance_and_retries(monkeypatch) -> None:
    rloc_prefix = topology.util_network.build_rloc_ipv6_address_prefix("fd00::/64")
    target = topology.util_network.build_rloc16_ipv6_address(rloc_prefix, "1001")
    payload = (
        _wire_tlv(0, bytes.fromhex("8899aabbccddeeff"))
        + _wire_tlv(1, b"\x10\x01")
        + _wire_tlv(2, b"\x00")
        + _wire_tlv(8, ipaddress.IPv6Address("fd00::1001").packed)
        + _wire_tlv(28, b"child-stack")
    )
    output = _response(
        target,
        payload,
        "Ext Address: 8899aabbccddeeff\n"
        "Rloc16: 0x1001\n"
        "Mode:\n    RxOnWhenIdle: 0\n    DeviceType: 0\n    NetworkData: 0\n"
        "IP6 Address List:\n    - fd00::1001\n"
        "Thread Stack Version: child-stack\n",
    )
    monkeypatch.setattr(topology.util_ot_ctl, "exec_ot_ctl", lambda _command: output)
    collection = create_diagnostic_collection_context()

    records = [
        fetch_network_diag_for_device(
            "0x1001",
            rloc_prefix,
            {},
            {},
            {},
            4,
            collection_context=collection,
            capture_stage="direct-child-detail",
            capture_attempt_index=attempt,
        )
        for attempt in (0, 1)
    ]

    assert all(record["rloc16"] == "0x1001" for record in records)
    assert all(record["thread_stack_version"] == "child-stack" for record in records)
    assert [
        [item["capture_attempt_index"] for item in record["tlv_response_history"]]
        for record in records
    ] == [[0], [1]]
    assert all(
        record["tlv_response_history"][0]["requested_type_ids"]
        == [int(t) for t in TLV_VALUES_CHILD_DETAILED.split()]
        for record in records
    )
    assert records[0]["tlv_response_history"][0]["query_id"] is None
    assert records[0]["tlv_response_history"][0]["request_association"] == "responder-target"
    assert records[0]["tlv_response_history"][0]["observation_id"] != records[1]["tlv_response_history"][0]["observation_id"]
    assert len(collection["observations"]) == 2


def test_unseen_query_id_cannot_bind_unicast_or_backfill_multicast_history() -> None:
    collection = create_diagnostic_collection_context()
    detailed = register_diagnostic_request(
        collection, "multicast-network", "ff03::1", 0, TLV_VALUES_DETAILED
    )
    basic = register_diagnostic_request(
        collection, "multicast-network", "ff03::1", 1, TLV_VALUES_BASIC
    )
    extaddr = "0011223344556677"
    shared_payload = (
        _wire_tlv(0, bytes.fromhex(extaddr))
        + _wire_tlv(1, b"\x04\x00")
        + _wire_tlv(2, b"\x0f")
        + _wire_tlv(8, ipaddress.IPv6Address("fd00::1").packed)
        + _wire_tlv(32, b"\x80\x00")
        + _wire_tlv(33, b"\x77\x77")
    )
    parse_multicast_diag_output(
        _response("fd00::1", shared_payload, f"Ext Address: {extaddr}\nRloc16: 0x0400\n"),
        collection_context=collection,
        request_context=detailed,
        capture_stage="multicast-network",
        capture_target="ff03::1",
        capture_attempt_index=0,
    )
    prior = collection["observations"][0]
    assert prior["request_association"] == "ambiguous"

    direct_target = topology.util_network.build_rloc16_ipv6_address(
        topology.util_network.build_rloc_ipv6_address_prefix("fd00::/64"),
        "0400",
    )
    direct_request = register_diagnostic_request(
        collection, "direct-router", direct_target, 0, TLV_VALUES_DETAILED, "0x0400"
    )
    direct_payload = (
        _wire_tlv(0, bytes.fromhex(extaddr))
        + _wire_tlv(1, b"\x04\x00")
        + _wire_tlv(33, b"\x77\x77")
        + _wire_tlv(32, b"\x80\x00")
    )
    parsed_direct = parse_multicast_diag_output(
        _response(direct_target, direct_payload, f"Ext Address: {extaddr}\nRloc16: 0x0400\n"),
        collection_context=collection,
        request_context=direct_request,
        capture_stage="direct-router",
        capture_target=direct_target,
        capture_attempt_index=0,
    )[extaddr]
    direct_observation = parsed_direct["tlv_response_history"][0]

    assert direct_observation["request_association"] == "unknown"
    assert direct_observation["attributed_request"] is None
    assert collection["query_origins"] == {}
    assert prior["request_association"] == "ambiguous"


def test_response_history_distinguishes_no_response_unavailable_and_malformed() -> None:
    collection = create_diagnostic_collection_context()
    request = register_diagnostic_request(
        collection, "direct-router", "fd00::400", 0, TLV_VALUES_DETAILED, "0x0400"
    )
    no_response = build_unframed_tlv_response_observation(
        "Error 23: ResponseTimeout", collection, request,
        "direct-router", "fd00::400", 0,
    )
    done_no_response = build_unframed_tlv_response_observation(
        "Done", collection, request, "direct-router", "fd00::400", 0,
    )
    unavailable = parse_multicast_diag_output(
        "DIAG_GET.rsp/ans from fd00::400\nExt Address: 0011223344556677\n",
        collection_context=collection,
        request_context=request,
        capture_stage="direct-router",
        capture_target="fd00::400",
        capture_attempt_index=0,
    )["0011223344556677"]["tlv_response_history"][0]
    malformed = parse_multicast_diag_output(
        "DIAG_GET.rsp/ans from fd00::400: zz\nExt Address: 0011223344556677\n",
        collection_context=collection,
        request_context=request,
        capture_stage="direct-router",
        capture_target="fd00::400",
        capture_attempt_index=0,
    )["0011223344556677"]["tlv_response_history"][0]

    assert no_response["parse_status"] == "no-response"
    assert done_no_response["parse_status"] == "no-response"
    assert no_response["requested_type_ids"] == [int(t) for t in TLV_VALUES_DETAILED.split()]
    assert unavailable["parse_status"] == "raw-unavailable"
    assert malformed["parse_status"] == "malformed"


def test_formatted_value_wins_raw_disagreement_and_logs_debug(caplog) -> None:
    payload = _wire_tlv(0, bytes.fromhex("0011223344556677"))
    output = _response(
        "fd00::1",
        payload,
        "Ext Address: 8899aabbccddeeff\nRloc16: 0x0400\n",
    )
    caplog.set_level("DEBUG")

    device = parse_multicast_diag_output(output)["8899aabbccddeeff"]

    assert device["extaddr"] == "8899aabbccddeeff"
    assert "raw/formatted mismatch" in caplog.text


def test_multicast_missing_rloc16_does_not_discard_later_responder() -> None:
    output = """DIAG_GET.rsp/ans from fd00::1: 0011
Ext Address: 0011223344556677
Child Table:
 ChildId: 0x01
DIAG_GET.rsp/ans from fd00::2: 0022
Ext Address: 8899aabbccddeeff
Rloc16: 0x2400
Child Table:
 ChildId: 0x02
"""

    parsed = parse_multicast_diag_output(output, extaddr_map={})

    assert set(parsed) == {"0011223344556677", "8899aabbccddeeff"}
    assert parsed["0011223344556677"]["rloc16"] == "Unknown"
    assert parsed["0011223344556677"]["children"] == []
    assert parsed["8899aabbccddeeff"]["children"][0]["rloc16"] == "0x2402"
# Run this module through the repository pytest entry point.



