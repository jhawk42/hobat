"""Snapshot the pre-projection dashboard filters over cached datasets."""

import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.requires_data_dir


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/view_capability_baseline.json"


def test_cached_view_capabilities_cover_catalog_and_preserve_shape(node_json) -> None:
    actual = node_json(
        "tests/js/run-view-capability-snapshot.mjs", "data", "--shape-only", timeout=60,
    )
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert set(actual) == set(expected)
    for dataset, snapshot in actual.items():
        assert set(snapshot) == set(expected[dataset]), dataset
        assert set(snapshot["flags"]) == set(expected[dataset]["flags"]), dataset
        assert set(snapshot["offered"]) == set(expected[dataset]["offered"]), dataset
        assert set(snapshot["diagnosticMatches"]) == set(expected[dataset]["diagnosticMatches"]), dataset
        offered = snapshot["offered"]
        combinations = {
            f"{node}|{link}|{diagnostic}"
            for node in offered["nodeModes"]
            for link in offered["linkModes"]
            for diagnostic in offered["diagnosticModes"]
        }
        assert set(snapshot["visibility"]) == combinations, dataset
        assert all(value is None for value in snapshot["visibility"].values()), dataset


def test_projected_view_capabilities_match_legacy_scan(node_json) -> None:
    comparisons = node_json(
        "tests/js/run-view-capability-snapshot.mjs", "data", "--compare", timeout=90,
    )
    for dataset, comparison in comparisons.items():
        assert set(comparison) == {"legacy", "projected"}, dataset
        assert comparison["projected"] == comparison["legacy"], dataset