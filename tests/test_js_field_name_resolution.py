from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from td_device_fields import FIELD_DEFINITIONS, normalize_input_record


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_browser_field_name_resolution() -> None:
    result = subprocess.run(
        ["node", "--experimental-default-type=module", "tests/js/run-field-name-resolution.mjs"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    rows = {row["input"]: row for row in json.loads(result.stdout)}
    for definition in FIELD_DEFINITIONS:
        path = definition["path"]
        candidates = set((path, *definition["aliases"]))
        for name in candidates:
            assert rows[name]["preferred"] == path
            assert rows[name]["tablePreferred"] == path
            assert set(rows[name]["candidates"]) == candidates


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_duplicate_alias_columns_in_both_runtimes() -> None:
    fixture = ROOT / "tests/fixtures/duplicate_alias_columns.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))["cases"]
    result = subprocess.run(
        ["node", "--experimental-default-type=module", "tests/js/run-field-name-resolution.mjs", str(fixture)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout)["fixtureResults"] == [case["expected"] for case in cases]
    for case in cases:
        assert normalize_input_record(case["input"]) == case["expected"], case["source"]