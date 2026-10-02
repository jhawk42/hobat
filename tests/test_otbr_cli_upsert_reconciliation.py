from __future__ import annotations

import pytest

from otbr_cli_networkdiag_topology import _upsert_device_record


@pytest.mark.parametrize(
    ("existing", "incoming", "field", "expected"),
    [
        ({"extaddr": "found-node"}, {"extaddr": "aabbccddeeff0011"}, "extaddr", "aabbccddeeff0011"),
        ({"rloc16": "Unknown"}, {"rloc16": "0x1234"}, "rloc16", "0x1234"),
        ({"device_label": "Unknown-node"}, {"device_label": "Kitchen"}, "device_label", "Kitchen"),
        ({"tlv_values": {}}, {"tlv_values": {"1": "aa"}}, "tlv_values", {"1": "aa"}),
        ({"thread_stack_version": "Unknown"}, {"thread_stack_version": "1.3"}, "thread_stack_version", "1.3"),
        ({"mode": {}}, {"mode": {"rx": 1}}, "mode", {"rx": 1}),
        ({"ipv6_addrs": ["fd00::1"]}, {"ipv6_addrs": ["fd00::1", "fd00::2"]}, "ipv6_addrs", ["fd00::1", "fd00::2"]),
        ({"responder_ipv6": "fd00::1"}, {"responder_ipv6": "fd00::2"}, "responder_ipv6", "fd00::1"),
        ({"children": []}, {"children": [{"rloc16": "0x2345"}]}, "children", [{"rloc16": "0x2345"}]),
    ],
)
def test_upsert_retry_reconciliation(existing, incoming, field, expected):
    records = {"0x1234": {"rloc16": "0x1234", "extaddr": "found-node", **existing}}
    incoming_record = {"rloc16": "0x1234", "extaddr": "found-node", **incoming}
    _upsert_device_record(records, incoming_record, {})
    assert records["0x1234"][field] == expected


def test_empty_vendor_observation_is_retained_without_erasing_prior_value():
    records = {
        "0x1234": {
            "rloc16": "0x1234",
            "extaddr": "0011223344556677",
            "vendor_name": "Acme",
        }
    }
    _upsert_device_record(
        records,
        {
            "rloc16": "0x1234",
            "extaddr": "0011223344556677",
            "vendor_name": "",
        },
        {},
    )

    assert records["0x1234"]["vendor_name"] == "Acme"
    assert records["0x1234"]["_merge_conflicts"] == [
        {"path": "vendorName", "current": "Acme", "incoming": ""}
    ]


def test_response_history_reconciliation_uses_observation_identity():
    records = {"0x1234": {"rloc16": "0x1234", "extaddr": "node"}}
    observation = {"observation_id": "collection:multicast:0:0"}
    incoming = {
        "rloc16": "0x1234",
        "extaddr": "node",
        "tlv_response_history": [observation, dict(observation)],
    }

    _upsert_device_record(records, incoming, {})
    _upsert_device_record(records, incoming, {})

    assert records["0x1234"]["tlv_response_history"] == [observation]


def test_malformed_or_unavailable_observation_cannot_clear_valid_vendor_value():
    records = {
        "0x1234": {
            "rloc16": "0x1234",
            "extaddr": "0011223344556677",
            "vendor_name": "Acme",
            "tlv_response_history": [{"observation_id": "valid", "parse_status": "valid"}],
        }
    }
    _upsert_device_record(
        records,
        {
            "rloc16": "0x1234",
            "extaddr": "0011223344556677",
            "vendor_name": None,
            "tlv_response_history": [
                {"observation_id": "malformed", "parse_status": "malformed"},
                {"observation_id": "unavailable", "parse_status": "raw-unavailable"},
            ],
        },
        {},
    )

    record = records["0x1234"]
    assert record["vendor_name"] == "Acme"
    assert [item["observation_id"] for item in record["tlv_response_history"]] == [
        "valid", "malformed", "unavailable"
    ]


def test_response_history_reconciliation_sorts_by_capture_sequence():
    records = {"0x1234": {"rloc16": "0x1234", "extaddr": "node"}}
    _upsert_device_record(
        records,
        {
            "rloc16": "0x1234",
            "extaddr": "node",
            "tlv_response_history": [
                {
                    "observation_id": "attempt-1",
                    "capture_attempt_index": 1,
                    "capture_sequence": 2,
                },
                {
                    "observation_id": "attempt-0",
                    "capture_attempt_index": 0,
                    "capture_sequence": 0,
                },
                {
                    "observation_id": "attempt-1-response-2",
                    "capture_attempt_index": 1,
                    "response_index": 1,
                    "capture_sequence": 3,
                },
            ],
        },
        {},
    )

    assert [
        item["observation_id"]
        for item in records["0x1234"]["tlv_response_history"]
    ] == ["attempt-0", "attempt-1", "attempt-1-response-2"]