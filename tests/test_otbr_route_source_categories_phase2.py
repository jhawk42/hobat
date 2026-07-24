from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "otbr_route_source_categories.json"


def _load_fixture() -> dict[str, list[dict[str, Any]]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _expected_category(row: dict[str, Any]) -> str | None:
    role = str(row.get("role", "")).strip().lower()
    mode = row.get("mode") if isinstance(row.get("mode"), dict) else {}
    mode_device = str(
        row.get("mode.device")
        or mode.get("device")
        or row.get("modeDevice")
        or row.get("mode_device")
        or ("FTD" if mode.get("deviceTypeFTD") is True else "")
    ).upper()
    has_router_flag = row.get("isBorderRouter") is True or row.get("isRouter") is True

    if role == "child":
        if has_router_flag:
            return None
        return "otbr_route_ftd_child" if mode_device == "FTD" else None
    if has_router_flag or role in {"border router", "router"}:
        return "otbr_route_router"
    return None


def test_route_source_fixtures_define_the_scoped_adaptor_contract() -> None:
    fixture = _load_fixture()

    for source_name in ("networkdiag", "restApi", "mergedDetailed"):
        for case in fixture[source_name]:
            row = case["row"]
            assert row["route"]["routeData"], case["name"]
            assert _expected_category(row) == case["expectedCategory"], case["name"]


def test_route_source_fixtures_define_skipped_source_rows() -> None:
    fixture = _load_fixture()

    for case in fixture["skipped"]:
        assert case["row"]["route"]["routeData"], case["name"]
        assert _expected_category(case["row"]) is None, case["name"]