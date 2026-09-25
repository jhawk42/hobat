"""Snapshot the pre-projection dashboard filters over cached datasets."""

import json
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.requires_data_dir


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/view_capability_baseline.json"


def test_cached_view_capabilities_cover_catalog_and_preserve_shape() -> None:
    result = subprocess.run(
        ["node", "tests/js/run-view-capability-snapshot.mjs", "data"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    actual = json.loads(result.stdout)
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


def test_projected_view_capabilities_match_legacy_scan() -> None:
    result = subprocess.run(
        ["node", "tests/js/run-view-capability-snapshot.mjs", "data", "--projection"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    legacy = subprocess.run(
        ["node", "tests/js/run-view-capability-snapshot.mjs", "data"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == json.loads(legacy.stdout)