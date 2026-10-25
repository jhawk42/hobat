from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


def test_theme_controller() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for theme controller tests.")
    result = subprocess.run(
        [node, "tests/js/run-theme-controller.mjs"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "theme controller: passed"
