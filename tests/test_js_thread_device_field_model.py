from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / "tests" / "fixtures" / "thread_device_field_model.json"
RUNNER_PATH = REPO_ROOT / "tests" / "js" / "run-thread-device-field-model.mjs"
MODEL = json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def run_javascript_model() -> dict[str, Any]:
    completed = subprocess.run(
        [
            "node",
            "--experimental-default-type=module",
            str(RUNNER_PATH),
            str(MODEL_PATH),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_javascript_field_model_normalization() -> None:
    results = run_javascript_model()
    expected_definitions = {
        field["path"]: {
            "path": field["path"],
            "aliases": field["aliases"],
            "transform": field["transform"],
        }
        for field in MODEL["fields"]
    }
    actual_definitions = {
        field["path"]: field for field in results["_fieldDefinitions"]
    }
    assert actual_definitions == expected_definitions
    for model_case in MODEL["normalizationCases"]:
        result = results[model_case["id"]]
        assert result["normalized"] == model_case["expected"], model_case["id"]
        assert result["idempotent"], model_case["id"]
        assert result["inputUnchanged"], model_case["id"]
        assert result["identityKeys"] == model_case.get("identityKeys", {}), model_case["id"]
    assert results["_placeholderPolicy"] == {
        "empty": True,
        "zero": True,
        "concrete": False,
    }
