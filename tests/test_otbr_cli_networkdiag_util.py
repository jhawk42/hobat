from __future__ import annotations

import otbr_cli_networkdiag_util as networkdiag_util


def test_detail_levels_map_to_router_and_child_tlv_sets() -> None:
    assert [
        networkdiag_util.get_tlv_values_for_detail_level(level)
        for level in (500, 490, 480, 470, 460)
    ] == [
        networkdiag_util.TLV_VALUES_DETAILED,
        networkdiag_util.TLV_VALUES_MEDIUM,
        networkdiag_util.TLV_VALUES_BASIC_8,
        networkdiag_util.TLV_VALUES_BASIC_28,
        networkdiag_util.TLV_VALUES_BASIC_2,
    ]
    assert [
        networkdiag_util.get_tlv_values_for_detail_level(level)
        for level in (200, 190, 180, 170, 160, 150)
    ] == [
        networkdiag_util.TLV_VALUES_CHILD_DETAILED,
        networkdiag_util.TLV_VALUES_CHILD_MEDIUM_MAC_MLE,
        networkdiag_util.TLV_VALUES_CHILD_MEDIUM_MAC,
        networkdiag_util.TLV_VALUES_CHILD_BASIC_8,
        networkdiag_util.TLV_VALUES_CHILD_BASIC_28,
        networkdiag_util.TLV_VALUES_CHILD_BASIC_2,
    ]


def test_parse_meshdiag_ipv6_addresses_tracks_router_headers_and_deduplicates() -> None:
    output = """preamble
id:02 rloc16:0x0800 ext-addr:8aa57d2c603fe16c
ip6-addrs:
    - fd00::1
    - 2001:db8:0:0::2
    - fd00::1
    - not:an:ipv6:address

id:46 rloc16:0xb800 ext-addr:fe109d277e0175cc
ip6-addrs:
    - fd00:1234::3
"""

    assert networkdiag_util._parse_meshdiag_ipv6_addresses(output) == {
        "0x0800": ["fd00::1", "2001:db8::2"],
        "0xb800": ["fd00:1234::3"],
    }


def test_fetch_ipv6_addresses_returns_empty_mapping_for_command_error(monkeypatch) -> None:
    monkeypatch.setattr(
        networkdiag_util.util_ot_ctl,
        "exec_ot_ctl",
        lambda _command: "Error: command timed out",
    )

    assert networkdiag_util.fetch_ipv6_addresses() == {}