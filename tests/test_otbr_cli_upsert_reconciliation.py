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