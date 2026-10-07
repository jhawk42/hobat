from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tests" / "js" / "run-dataset-fetch-behavior.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_dataset_fetch_behavior() -> None:
    completed = subprocess.run(
        ["node", str(RUNNER)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    summary = json.loads(completed.stdout)
    assert summary["scenarioCount"] == 8
    assert summary["requestCount"] > 0
    assert summary["controlledTimers"] is True
