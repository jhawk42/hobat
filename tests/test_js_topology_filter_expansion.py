from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_topology_edge_indexes_and_relationship_expansion() -> None:
    node_executable = shutil.which("node")
    if node_executable is None:
        pytest.skip("Node.js is required for topology filter expansion tests.")

    result = subprocess.run(
        [node_executable, "tests/js/run-topology-filter-expansion.mjs"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "endpointPairCount": 2,
        "incidentNodeCount": 3,
        "categoryCount": 4,
        "forcedEdgeIds": ["child", "neighbor-a", "neighbor-b"],
    }