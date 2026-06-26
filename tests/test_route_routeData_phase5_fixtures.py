from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIX_SINGLE = REPO_ROOT / "tests" / "fixtures" / "route_routeData_single_source.json"
FIX_MERGED = REPO_ROOT / "tests" / "fixtures" / "route_routeData_merged_rows.json"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_single_source_fixture_uses_route_routeData_only() -> None:
    rows = _load_json(FIX_SINGLE)
    assert isinstance(rows, list) and rows

    row = rows[0]
    assert "route" in row
    assert "route_data" not in row

    route = row["route"]
    assert isinstance(route.get("routeData"), list)
    assert "idSequence" in route

    for entry in route["routeData"]:
        assert "routeId" in entry
        assert "linkQualityIn" in entry
        assert "linkQualityOut" in entry


def test_merged_fixture_models_route_sequence_precedence() -> None:
    payload = _load_json(FIX_MERGED)
    expected = payload["expected"]

    route = expected["route"]
    assert route["idSequence"] == 15

    route_ids = [r["routeId"] for r in route["routeData"]]
    assert route_ids == ["0x10", "0x11", "0x12"]

    route_0x11 = next(r for r in route["routeData"] if r["routeId"] == "0x11")
    assert route_0x11["idSequence"] == 15
    assert route_0x11["routeCost"] == 1
