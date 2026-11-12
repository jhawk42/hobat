from unittest.mock import Mock

import pytest

import otbr_cli_meshdiag_childip6 as childip6
import otbr_cli_meshdiag_childtable as childtable
import otbr_cli_meshdiag_routerneighbortable as neighbors
from otbr_cli_meshdiag_topology import parse_meshdiag_topology_output


def test_topology_sections_stay_with_their_router_and_child():
    text = """id:01 rloc16:0x0400 ext-addr:AABBCCDDEEFF0011 ver:5 - br - leader
3-links:{ 02 03 }
2-links:{ 04 }
1-links:{ 05 }
ip6-addrs:
    fd00::1
    fe80::1
children:
    rloc16:0x0401 lq:3, mode:rdn
    rloc16:0x0402 lq:1, mode:-
unrelated section
    fd00::bad
id:02 rloc16:0x0800 ext-addr:1122334455667788
3-links:{ }
ip6-addrs:
    fd00::2
children: none
    rloc16:0x0801 lq:2, mode:rdn
Done
"""
    assert parse_meshdiag_topology_output(text, {"aabbccddeeff0011": "BR"}) == [
        {"id": "01", "router_id": "01", "rloc16": "0x0400",
         "extaddr": "AABBCCDDEEFF0011", "thread_version_decimal": 5,
         "thread_version": "1.4", "br": True, "leader": True,
         "device_label": "BR", "3_links": ["02", "03"], "2_links": ["04"],
         "1_links": ["05"], "ipv6_addrs": ["fd00::1", "fe80::1"],
         "children": [{"rloc16": "0x0401", "lq": "3", "mode": "rdn"},
                      {"rloc16": "0x0402", "lq": "1", "mode": "-"}]},
        {"id": "02", "router_id": "02", "rloc16": "0x0800",
         "extaddr": "1122334455667788", "thread_version": "Unknown",
         "br": False, "leader": False, "3_links": [], "2_links": [],
         "1_links": [], "ipv6_addrs": ["fd00::2"], "children": []},
    ]


def test_topology_malformed_header_does_not_contribute_sections(caplog):
    text = """id:malformed
ip6-addrs:
    fd00::bad
id:02 rloc16:0x0800 ext-addr:1122334455667788
children: none
Done
"""
    rows = parse_meshdiag_topology_output(text)
    assert len(rows) == 1
    assert rows[0]["rloc16"] == "0x0800"
    assert rows[0]["ipv6_addrs"] == []
    assert "unexpected format" in caplog.text


def test_childtable_all_telemetry_and_final_entry_flush(monkeypatch):
    text = """ignored before first header
rloc16:0x0401 ext-addr:AABBCCDDEEFF0011 ver:5
timeout:300 age:2 supvn:7 q-msg:4
rx-on:yes type:FTD full-net:yes
rss - ave:-20 last:-18 margin:80
err-rate - frame:0.50% msg:1.25%
conn-time:00:12:34
csl - sync:yes period:10 timeout:20 channel:15

rloc16:0x0402 ext-addr:1122334455667788
timeout:600 age:8 supvn:9 q-msg:0
rx-on:no type:MTD full-net:no
rss - ave:-70 last:-75 margin:10
err-rate - frame:2% msg:3%
conn-time:1d2h
csl - sync:no period:30 timeout:40 channel:20
unrelated text
Done
"""
    transport = Mock(return_value=text)
    monkeypatch.setattr(childtable, "exec_ot_ctl", transport)
    result = childtable.fetch_meshdiag_child_table_for_device(
        "0x0400", {"extaddr": "parent"}, {"parent": "BR", "aabbccddeeff0011": "Child"},
    )
    transport.assert_called_once_with("meshdiag childtable 0x0400")
    assert result["device_label"] == "BR"
    assert result["router_child_table_count"] == 2
    assert result["router_child_table"] == [
        {"rloc16": "0x0401", "extaddr": "aabbccddeeff0011", "device_label": "Child",
         "thread_version_decimal": 5, "thread_version": "1.4", "timeout": 300,
         "age": 2, "supvn": 7, "q_msg": 4, "rx_on": True, "type": "FTD",
         "full_net": True, "rss_ave": -20, "rss_last": -18, "rss_margin": 80,
         "err_rate_frame_pct": 0.5, "err_rate_msg_pct": 1.25,
         "conn_time": "00:12:34", "csl_sync": True, "csl_period": 10,
         "csl_timeout": 20, "csl_channel": 15},
        {"rloc16": "0x0402", "extaddr": "1122334455667788", "device_label": "Unknown",
         "thread_version": "Unknown", "timeout": 600, "age": 8, "supvn": 9,
         "q_msg": 0, "rx_on": False, "type": "MTD", "full_net": False,
         "rss_ave": -70, "rss_last": -75, "rss_margin": 10,
         "err_rate_frame_pct": 2.0, "err_rate_msg_pct": 3.0, "conn_time": "1d2h",
         "csl_sync": False, "csl_period": 30, "csl_timeout": 40, "csl_channel": 20},
    ]


def test_neighbors_keep_separate_metrics_and_labels(monkeypatch):
    text = """rloc16:0x0800 ext-addr:AABBCCDDEEFF0011 ver:5
rss - ave:-20 last:-18 margin:80
err-rate - frame:0.50% msg:1.25%
conn-time:00:12:34
rloc16:0x0c00 ext-addr:1122334455667788
rss - ave:-70 last:-75 margin:10
err-rate - frame:2% msg:3%
conn-time:1d2h
Done
"""
    transport = Mock(return_value=text)
    monkeypatch.setattr(neighbors, "exec_ot_ctl", transport)
    result = neighbors.fetch_meshdiag_router_neighbor_table_for_device(
        "0x0400", extaddr_map={"aabbccddeeff0011": "Neighbor"},
    )
    transport.assert_called_once_with("meshdiag routerneighbortable 0x0400")
    assert result["router_neighbor_table_count"] == 2
    assert result["router_neighbor_table"] == [
        {"rloc16": "0x0800", "extaddr": "aabbccddeeff0011", "device_label": "Neighbor",
         "thread_version_decimal": 5, "thread_version": "1.4", "rss_ave": -20,
         "rss_last": -18, "rss_margin": 80, "err_rate_frame_pct": 0.5,
         "err_rate_msg_pct": 1.25, "conn_time": "00:12:34"},
        {"rloc16": "0x0c00", "extaddr": "1122334455667788", "device_label": "Unknown",
         "thread_version": "Unknown", "rss_ave": -70, "rss_last": -75,
         "rss_margin": 10, "err_rate_frame_pct": 2.0, "err_rate_msg_pct": 3.0,
         "conn_time": "1d2h"},
    ]


@pytest.mark.parametrize("module,collector,key", [
    (childtable, childtable.fetch_meshdiag_child_table_for_device, "router_child_table"),
    (neighbors, neighbors.fetch_meshdiag_router_neighbor_table_for_device, "router_neighbor_table"),
])
def test_malformed_table_header_discards_orphan_telemetry(monkeypatch, caplog, module, collector, key):
    monkeypatch.setattr(module, "exec_ot_ctl", Mock(return_value="""rloc16:bad
rss - ave:-99 last:-99 margin:1
timeout:999 age:999 supvn:999 q-msg:999

rloc16:0x0401 ext-addr:AABBCCDDEEFF0011
unrecognized line
Done
"""))
    result = collector("0x0400")
    assert result[key] == [
        {"rloc16": "0x0401", "extaddr": "aabbccddeeff0011",
         "device_label": "Unknown", "thread_version": "Unknown"},
    ]
    assert result[key + "_count"] == 1
    assert "unexpected format" in caplog.text


def test_childip6_counts_empty_children_and_normalizes_addresses(monkeypatch):
    transport = Mock(return_value="""unrelated text
child-rloc16: 0x0401
    FD00::AB
    FE80::1
not an address
child-rloc16: 0x0402
    FD00::CD
child-rloc16: 0x0403

Done
""")
    monkeypatch.setattr(childip6, "exec_ot_ctl", transport)
    result = childip6.fetch_meshdiag_child_ip6_for_device("0x0400")
    transport.assert_called_once_with("meshdiag childip6 0x0400")
    assert result["router_child_ip6_table_count"] == 3
    assert result["router_child_ip6_table"] == [
        {"child_rloc16": "0x0401", "ip6_addrs": ["fd00::ab", "fe80::1"], "ip6_addr_count": 2},
        {"child_rloc16": "0x0402", "ip6_addrs": ["fd00::cd"], "ip6_addr_count": 1},
        {"child_rloc16": "0x0403", "ip6_addrs": [], "ip6_addr_count": 0},
    ]
