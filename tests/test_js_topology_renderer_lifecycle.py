from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_topology_renderer_replacement_disposes_prior_resources() -> None:
    node_executable = shutil.which("node")
    if node_executable is None:
        pytest.skip("Node.js is required for topology renderer lifecycle tests.")

    result = subprocess.run(
        [node_executable, "tests/js/run-topology-renderer-lifecycle.mjs"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "renderCount": 5,
        "responseCount": 5,
        "remainingListeners": 0,
        "destroyedNetworks": 5,
    }