from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_node_json(
    node_executable: str,
    script: str | Path,
    *args: str,
    evaluate: bool = False,
    timeout: float = 30,
) -> Any:
    if evaluate:
        command = [
            node_executable,
            "--experimental-default-type=module",
            "--input-type=module",
            "--eval",
            str(script),
        ]
    else:
        command = [node_executable, str(script), *args]

    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"Node command timed out after {timeout}s: {command!r}\n{exc.stderr or ''}")

    if completed.returncode != 0:
        pytest.fail(
            f"Node command failed with exit status {completed.returncode}: {command!r}\n"
            f"stderr:\n{completed.stderr}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"Node command returned invalid JSON: {command!r}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}\n{exc}"
        )