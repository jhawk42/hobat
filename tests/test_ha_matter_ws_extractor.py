from __future__ import annotations

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