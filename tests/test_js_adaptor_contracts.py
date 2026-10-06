from __future__ import annotations

import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.requires_data_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tests" / "js" / "run-adaptor-contracts.mjs"


def test_all_adaptors_preserve_the_public_result_contract(node_json) -> None:
    result = node_json(
        RUNNER, timeout=60,
    )
    assert result == {"adaptorCount": 12}


def test_cached_adaptor_outputs_preserve_contract(node_json) -> None:
    actual = node_json(
        RUNNER, "--snapshot", timeout=60,
    )
    baseline = REPO_ROOT / "tests" / "fixtures" / "adaptor_output_baseline.json"
    expected = json.loads(baseline.read_text(encoding="utf-8"))
    assert set(actual) == set(expected)
    for dataset, snapshot in actual.items():
        assert set(snapshot) == set(expected[dataset]), dataset
        # Cached network identities and counts can change independently of styling.
        assert [node[0] for node in snapshot["nodeEmphasis"]] == snapshot["nodeIds"], dataset
        assert all(
            len(node) == 3 and tuple(node[1:]) in {(5, 45), (3, 45), (1, 27)}
            for node in snapshot["nodeEmphasis"]
        ), dataset
        node_ids = set(snapshot["nodeIds"])
        edge_ids = [edge[0] for edge in snapshot["edges"]]
        assert len(node_ids) == len(snapshot["nodeIds"]), dataset
        assert len(edge_ids) == len(set(edge_ids)), dataset
        assert all(edge[1] in node_ids and edge[2] in node_ids for edge in snapshot["edges"]), dataset


def test_source_adaptors_emit_through_shared_model() -> None:
    modules = sorted((REPO_ROOT / "src" / "js").glob("tdash-adaptor-*.js"))
    sources = [module for module in modules if module.stem not in {"tdash-adaptor-shared", "tdash-adaptor-model"}]
    assert len(sources) == 6
    for module in sources:
        code = module.read_text(encoding="utf-8")
        assert "emitThroughAdaptorModel(" in code or "emitAdaptorResult(" in code, module.name
        assert "from './tdash-adaptor-model.js'" in code, module.name