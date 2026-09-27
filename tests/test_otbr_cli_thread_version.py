from __future__ import annotations

import json

import pytest

import otbr_cli_meshdiag_childtable as childtable
import otbr_cli_meshdiag_routerneighbortable as neighbortable
import otbr_cli_meshdiag_topology as topology
from td_json_key_normalizer import convert_keys_to_camel_case
from util_network import decode_short_thread_version


KNOWN_VERSIONS = [(2, "1.1"), (3, "1.2"), (4, "1.3"), (5, "1.4")]


@pytest.mark.parametrize(("decimal", "decoded"), KNOWN_VERSIONS + [(99, "Unknown")])
def test_meshdiag_topology_emits_decimal_and_decoded_thread_version(decimal, decoded):
    output = (
        "id: 01 rloc16:0x0400 ext-addr:0011223344556677 "
        f"ver:{decimal} - me - br"
    )

    [router] = topology.parse_meshdiag_topology_output(output)

    assert router["thread_version_decimal"] == decimal
    assert router["thread_version"] == decoded
    assert "ver" not in router


def test_meshdiag_topology_omits_decimal_when_not_reported():
    output = "id: 01 rloc16:0x0400 ext-addr:0011223344556677 - me"

    [router] = topology.parse_meshdiag_topology_output(output)

    assert "thread_version_decimal" not in router
    assert router["thread_version"] == "Unknown"


def test_meshdiag_topology_snapshot_uses_canonical_border_router_field(monkeypatch, tmp_path):
    output = "\n".join([
        "id: 01 rloc16:0x0400 ext-addr:0011223344556677 - me - br",
        "id: 02 rloc16:0x0800 ext-addr:8899aabbccddeeff - me",
    ])
    output_path = tmp_path / "td-otbr-cli-meshdiag-topology.json"
    monkeypatch.setattr(topology, "fetch_meshdiag_topology", lambda: output)

    topology.get_meshdiag_topology(output_path=output_path)

    records = json.loads(output_path.read_text(encoding="utf-8"))
    assert [record["isBorderRouter"] for record in records] == [True, False]
    assert all("br" not in record and "is_border_router" not in record for record in records)


@pytest.mark.parametrize(
    ("module", "collector_name", "table_key"),
    [
        (childtable, "fetch_meshdiag_child_table_for_device", "router_child_table"),
        (neighbortable, "fetch_meshdiag_router_neighbor_table_for_device", "router_neighbor_table"),
    ],
)
@pytest.mark.parametrize(("decimal", "decoded"), KNOWN_VERSIONS + [(99, "Unknown"), (None, "Unknown")])
def test_per_router_meshdiag_rows_emit_decimal_and_decoded_version(
    monkeypatch, module, collector_name, table_key, decimal, decoded
):
    version_text = f" ver:{decimal}" if decimal is not None else ""
    output = f"rloc16:0x0401 ext-addr:0011223344556677{version_text}\nDone"
    monkeypatch.setattr(module, "exec_ot_ctl", lambda _command: output)

    result = getattr(module, collector_name)("0x0400")

    [record] = result[table_key]
    if decimal is None:
        assert "thread_version_decimal" not in record
    else:
        assert record["thread_version_decimal"] == decimal
    assert record["thread_version"] == decoded
    assert "ver" not in record


def test_cli_snapshot_key_normalization_keeps_version_names_distinct():
    record = convert_keys_to_camel_case({
        "eui64": "0011223344556677",
        "thread_version_decimal": 4,
        "thread_version": "1.3",
        "version": 7,
    })

    assert record == {
        "eui": "0011223344556677",
        "threadVersionDecimal": 4,
        "threadVersion": "1.3",
        "version": 7,
    }
    assert decode_short_thread_version(99) == "Unknown"