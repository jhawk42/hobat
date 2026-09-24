"""Snapshot the pre-projection dashboard filters over cached datasets."""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/view_capability_baseline.json"


def test_cached_view_capabilities_match_baseline() -> None:
    result = subprocess.run(
        ["node", "tests/js/run-view-capability-snapshot.mjs", "data"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    actual = json.loads(result.stdout)
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert set(actual) == set(expected)
    assert actual == expected


def test_projected_view_capabilities_match_baseline() -> None:
    result = subprocess.run(
        ["node", "tests/js/run-view-capability-snapshot.mjs", "data", "--projection"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == json.loads(FIXTURE.read_text(encoding="utf-8"))