#!/usr/bin/env python3
"""Regression tests for route.routeData merge behavior in merge_dataset.py."""

from __future__ import annotations

import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from merge_dataset import build_merged_records, deep_merge


def _load_first_route_row() -> dict:
    return {
        "extAddress": "aabbccddeeff0011",
        "rloc16": "0x1000",
        "deviceLabel": "router-a",
        "route": {
            "idSequence": 7,
            "routeData": [
                {
                    "routeId": 1,
                    "linkQualityIn": 3,
                    "linkQualityOut": 3,
                    "routeCost": 1,
                    "rloc16": "0x0400",
                }
            ],
        },
    }


def test_deep_merge_uses_route_routeData_from_real_networkdiag_row() -> None:
    """Ensure deep_merge merges canonical route.routeData and never requires route_data."""
    base_row = _load_first_route_row()
    base = deepcopy(base_row)

    # Incoming update uses canonical shape and includes one duplicate routeId + one new routeId.
    # Must include idSequence >= base sequence or merge will discard incoming routes.
    duplicate_route_id = base["route"]["routeData"][0]["routeId"]
    base_sequence = base["route"].get("idSequence", 0)
    incoming = {
        "route": {
            "idSequence": base_sequence,  # Match base to enable route-level merge
            "routeData": [
                {
                    "routeId": duplicate_route_id,
                    "linkQualityIn": 2,
                    "linkQualityOut": 2,
                    "routeCost": 5,
                    "rloc16": base["route"]["routeData"][0].get("rloc16"),
                },
                {
                    "routeId": "0xfe",
                    "linkQualityIn": 3,
                    "linkQualityOut": 3,
                    "routeCost": 1,
                    "rloc16": "0xfe00",
                },
            ]
        }
    }

    merged = deep_merge(base, incoming)

    assert "route" in merged
    assert "routeData" in merged["route"]
    assert "route_data" not in merged

    route_ids = [str(r.get("routeId")) for r in merged["route"]["routeData"] if isinstance(r, dict)]
    assert "0xfe" in route_ids
    assert len(route_ids) == len(set(route_ids)), "routeData should be deduplicated by routeId"


def test_build_merged_records_keeps_route_routeData_shape() -> None:
    """Ensure build_merged_records output stays on canonical route.routeData container."""
    base_row = _load_first_route_row()

    # Keep a minimal row set with stable merge identity + canonical route shape.
    row_a = {
        "extAddress": base_row.get("extAddress"),
        "rloc16": base_row.get("rloc16"),
        "route": deepcopy(base_row.get("route", {})),
        "deviceLabel": base_row.get("deviceLabel"),
    }
    # row_b must have idSequence >= row_a's sequence to enable route merge
    base_sequence = row_a["route"].get("idSequence", 0)
    row_b = {
        "extAddress": base_row.get("extAddress"),
        "rloc16": base_row.get("rloc16"),
        "route": {
            "idSequence": base_sequence,  # Match to enable route-level merge
            "routeData": [
                {
                    "routeId": "0xfd",
                    "linkQualityIn": 2,
                    "linkQualityOut": 2,
                    "routeCost": 2,
                    "rloc16": "0xfd00",
                }
            ]
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        f1 = base_dir / "source-a.json"
        f2 = base_dir / "source-b.json"
        f1.write_text(json.dumps([row_a]), encoding="utf-8")
        f2.write_text(json.dumps([row_b]), encoding="utf-8")

        merged, report = build_merged_records(
            base_dir=base_dir,
            omr_prefix="",
            input_files=["source-a.json", "source-b.json"],
            device_label_map={},
        )

    assert isinstance(report, dict)
    assert len(merged) == 1

    node = merged[0]
    assert "route" in node
    assert isinstance(node["route"], dict)
    assert "routeData" in node["route"]
    assert "route_data" not in node

    route_ids = [str(r.get("routeId")) for r in node["route"].get("routeData", []) if isinstance(r, dict)]
    assert "0xfd" in route_ids
