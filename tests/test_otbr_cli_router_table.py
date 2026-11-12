import json
import logging
from unittest.mock import Mock

import pytest

import otbr_cli_router_table as router_table


TABLE = """router table
| ID | RLOC16 | Next Hop | Path Cost | LQ In | LQ Out | Age | Extended MAC | Link |
+----+--------+----------+-----------+-------+--------+-----+--------------+------+
| 1 | 0x0C00 | 25 | 1 | 2 | 3 | 20 | AABBCCDDEEFF0011 | 1 |
| 25 | 0x6400 | 1 | 2 | 3 | 1 | 40 | 112233445566ABCD | 0 |
Done
"""


def test_real_router_rows_keep_numeric_types_identifiers_labels_and_order():
    rows = router_table.parse_router_table(TABLE, {"aabbccddeeff0011": "Kitchen"})
    assert rows == [
        {"ID": 1, "rloc16": "0x0c00", "Next Hop": "25", "Path Cost": 1,
         "LQ In": 2, "LQ Out": 3, "Age": 20, "Extended MAC": "AABBCCDDEEFF0011",
         "Link": 1, "extaddr": "aabbccddeeff0011", "device_label": "Kitchen",
         "router_id": "0x01"},
        {"ID": 25, "rloc16": "0x6400", "Next Hop": "1", "Path Cost": 2,
         "LQ In": 3, "LQ Out": 1, "Age": 40, "Extended MAC": "112233445566ABCD",
         "Link": 0, "extaddr": "112233445566abcd", "router_id": "0x19"},
    ]
    assert all(type(row[key]) is int for row in rows
               for key in ("ID", "Path Cost", "LQ In", "LQ Out", "Age", "Link"))


@pytest.mark.parametrize("text", ["", "Done", "| unrelated | table |"])
def test_router_missing_header_is_empty(text):
    assert router_table.parse_router_table(text) == []


def test_router_boundaries_preserve_nonnumeric_telemetry_and_warn(caplog):
    text = TABLE.replace("| 1 | 0x0C00", "| missing | fields |\n| 1 | 0x0C00")
    text = text.replace("| 20 |", "| unknown |")
    with caplog.at_level(logging.WARNING):
        rows = router_table.parse_router_table(text)
    assert len(rows) == 2
    assert rows[0]["Age"] == "unknown"
    assert "unexpected format" in caplog.text
    assert "missing | fields" in caplog.text


def test_router_nonstring_input_reports_type_error():
    with pytest.raises(TypeError, match="Expected output to be a string"):
        router_table.parse_router_table(None)


def test_real_router_collector_persists_canonical_rows(tmp_path, monkeypatch):
    transport = Mock(return_value=TABLE)
    monkeypatch.setattr(router_table.util_ot_ctl, "exec_ot_ctl", transport)
    unrelated = tmp_path / "unrelated.json"
    unrelated.write_bytes(b'{"keep": true}')
    output = tmp_path / "td-otbr-cli-router-table.json"

    rows = router_table.fetch_and_parse_router_table(
        {"aabbccddeeff0011": "Kitchen"}, output_path=output,
    )

    transport.assert_called_once_with("router table")
    assert len(rows) == 2
    saved = json.loads(output.read_text())
    assert saved == [
        {"id": 1, "rloc16": "0x0c00", "nextHop": "25", "pathCost": 1,
         "linkQualityIn": 2, "linkQualityOut": 3, "age": 20,
         "link": 1, "extAddress": "aabbccddeeff0011", "deviceLabel": "Kitchen",
         "routerId": "0x01"},
        {"id": 25, "rloc16": "0x6400", "nextHop": "1", "pathCost": 2,
         "linkQualityIn": 3, "linkQualityOut": 1, "age": 40,
         "link": 0, "extAddress": "112233445566abcd", "routerId": "0x19"},
    ]
    assert unrelated.read_bytes() == b'{"keep": true}'
