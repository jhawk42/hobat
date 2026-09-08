from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tests" / "js" / "run-phase1-regressions.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for JavaScript regressions")
def test_phase1_javascript_regressions() -> None:
    result = subprocess.run(
        ["node", str(RUNNER)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "phase1 regressions passed\n"