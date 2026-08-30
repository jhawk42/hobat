from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tests" / "js" / "run-dataset-row-assembly.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_dataset_row_assembly_contract() -> None:
    completed = subprocess.run(
        ["node", str(RUNNER)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    assert summary["datasetCount"] > 0
    assert summary["extractorCount"] == 5
    assert summary["adaptorCount"] == 9