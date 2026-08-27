from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_layout_characterization() -> dict[str, object]:
    node_executable = shutil.which("node")
    if node_executable is None:
        pytest.skip("Node.js is required for layout tests.")
    result = subprocess.run(
        [node_executable, "tests/js/run-layout-characterization.mjs"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_mesh_tree_zoning_is_deterministic() -> None:
    result = run_layout_characterization()
    context = result["context"]
    assert context["total"] == 7
    assert ["tie", "r-a"] in context["parents"]
    assert len(context["zones"]) == 7