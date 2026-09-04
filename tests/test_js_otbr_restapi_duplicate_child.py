from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tests" / "js" / "run-otbr-restapi-duplicate-child.mjs"


def test_otbr_restapi_childtable_and_children_share_one_child_node() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the JavaScript adaptor contract")

    result = subprocess.run(
        [node, str(RUNNER)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"duplicateChildNodes": 0}