from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.requires_data_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tests" / "js" / "run-adaptor-contracts.mjs"


def test_all_adaptors_preserve_the_public_result_contract() -> None:
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
    assert json.loads(result.stdout) == {"adaptorCount": 12}


def test_cached_adaptor_outputs_match_baseline() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the JavaScript adaptor contract")

    result = subprocess.run(
        [node, str(RUNNER), "--snapshot"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    baseline = REPO_ROOT / "tests" / "fixtures" / "adaptor_output_baseline.json"
    assert json.loads(result.stdout) == json.loads(baseline.read_text(encoding="utf-8"))


def test_source_adaptors_emit_through_shared_model() -> None:
    modules = sorted((REPO_ROOT / "src" / "js").glob("tdash-adaptor-*.js"))
    sources = [module for module in modules if module.stem not in {"tdash-adaptor-shared", "tdash-adaptor-model"}]
    assert len(sources) == 6
    for module in sources:
        code = module.read_text(encoding="utf-8")
        assert "emitThroughAdaptorModel(" in code or "emitAdaptorResult(" in code, module.name
        assert "from './tdash-adaptor-model.js'" in code, module.name