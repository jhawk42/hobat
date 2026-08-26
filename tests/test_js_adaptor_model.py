from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tests" / "js" / "run-adaptor-model.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_adaptor_intermediate_model_contract() -> None:
    completed = subprocess.run(
        ["node", str(RUNNER)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    assert summary == {"deviceCount": 2, "relationshipCount": 2}