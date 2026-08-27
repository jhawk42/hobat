from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_topology_view_model_and_lifecycle_primitives() -> None:
    node_executable = shutil.which("node")
    if node_executable is None:
        pytest.skip("Node.js is required for topology view-model tests.")

    result = subprocess.run(
        [node_executable, "tests/js/run-topology-view-model.mjs"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "nodeCount": 2,
        "visibleNodeIds": ["child-a", "router-a"],
        "forcedVisibleEdgeIds": ["child-edge"],
        "searchFocus": "child-a",
        "listenerCountAfterDispose": 0,
    }