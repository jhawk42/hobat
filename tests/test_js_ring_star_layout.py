from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_node_json(script: str) -> dict[str, object]:
    node_executable = shutil.which("node")
    if node_executable is None:
        pytest.skip("Node.js is required for layout tests.")
    result = subprocess.run(
        [node_executable, script], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def test_ring_star_layout_stages_are_deterministic_and_bounded() -> None:
    result = run_node_json("tests/js/run-ring-star-layout.mjs")
    assert result == {"nodes": 6, "denseNodes": 25, "bounded": True}