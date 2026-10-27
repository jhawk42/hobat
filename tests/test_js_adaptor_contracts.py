from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

import pytest

from td_dataset_catalog import load_dataset_catalog


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
    for entry in load_dataset_catalog()["datasets"]:
        if "unified" in entry and all(
            (REPO_ROOT / "data" / filename).is_file() for filename in entry["files"]
        ):
            expected[entry["value"]] = expected["otbr_restapi_topology"]
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


def test_pinned_adaptor_outputs_match_exact_baseline(node_executable: str) -> None:
    completed = subprocess.run(
        [node_executable, str(RUNNER), "--pinned-snapshot"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
        timeout=60,
    )
    baseline = REPO_ROOT / "tests" / "fixtures" / "adaptor_refactor_baseline.json"
    actual = json.loads(completed.stdout)
    expected = json.loads(baseline.read_text(encoding="utf-8"))
    roles = {"router", "borderRouter", "child", "eve", "unknown"}
    colors = {"lqHigh", "lqMedium", "lqLow", "lqNone", "lqParentChild", "lqOtbr"}
    for result in actual.values():
        for node in result["nodeData"]:
            assert node.pop("themeRole") in roles
        for edge in result["edgeData"]:
            if isinstance(edge.get("lqLevel"), (int, float)) and edge["lqLevel"] > 0:
                assert edge.get("themeColorKey") in colors
            if "themeColorKey" in edge:
                assert edge.pop("themeColorKey") in colors
        for key in ("rawByIdForDetails", "nodeMap"):
            assert "themeRole" not in json.dumps(result[key])
            assert "themeColorKey" not in json.dumps(result[key])
    assert actual == expected


def test_source_adaptors_emit_through_shared_model() -> None:
    modules = sorted((REPO_ROOT / "src" / "js").glob("tdash-adaptor-*.js"))
    sources = [module for module in modules if module.stem not in {"tdash-adaptor-shared", "tdash-adaptor-model"}]
    assert len(sources) == 7
    for module in sources:
        code = module.read_text(encoding="utf-8")
        assert "emitThroughAdaptorModel(" in code or "emitAdaptorResult(" in code, module.name
        assert re.search(r"""from ["']\./tdash-adaptor-model\.js["']""", code), module.name