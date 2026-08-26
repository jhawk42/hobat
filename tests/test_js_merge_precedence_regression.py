from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from merge_dataset import SOURCE_PRECEDENCE


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tests" / "js" / "run-merge-policy-metadata.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_javascript_policy_metadata_matches_python() -> None:
    completed = subprocess.run(
        ["node", "--experimental-default-type=module", str(RUNNER)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["sourcePrecedence"] == SOURCE_PRECEDENCE
    assert set(result["handlerPaths"]) == {
        "route",
        "children",
        "childTable",
        "childIpv6Addresses",
        "routerNeighbors",
    }
    assert result["context"]["existingPriority"] == 10
    assert result["context"]["incomingPriority"] == 0
    assert result["contextFrozen"] is True


MERGE_JS = REPO_ROOT / "src" / "js" / "tdash-merge.js"
ADAPTORS_JS = REPO_ROOT / "src" / "js" / "tdash-adaptors.js"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_sort_row_groups_uses_descending_source_priority() -> None:
    """Regression guard: higher SOURCE_PRECEDENCE must be processed first."""
    text = _read_text(MERGE_JS)

    m = re.search(
        r"export\s+function\s+sortRowGroupsByPriority\s*\([^)]*\)\s*\{(?P<body>.*?)\n\}",
        text,
        flags=re.DOTALL,
    )
    assert m, "Could not find sortRowGroupsByPriority() in tdash-merge.js"

    body = m.group("body")
    assert "const prioA = map[srcA] ?? 0;" in body
    assert "const prioB = map[srcB] ?? 0;" in body
    assert "return prioB - prioA;" in body, (
        "sortRowGroupsByPriority must sort descending so higher priority rows "
        "are merged first"
    )


def test_supplementary_details_merge_does_not_clobber_primary_fields() -> None:
    """Regression guard: supplementary mdns enrichment must not override primary labels."""
    text = _read_text(ADAPTORS_JS)

    # In the supplementary-file merge path, we expect mergeForDisplay(record, existing)
    # so existing primary values win over supplementary values when both are non-empty.
    pattern = r"rawByIdForDetails\.set\(nodeId,\s*mergeForDisplay\(record,\s*existing\)\);"
    assert re.search(pattern, text), (
        "Supplementary merge must call mergeForDisplay(record, existing) so "
        "supplementary records only enrich missing values"
    )

    forbidden = r"rawByIdForDetails\.set\(nodeId,\s*mergeForDisplay\(existing,\s*record\)\);"
    assert not re.search(forbidden, text), (
        "Found old clobbering merge order mergeForDisplay(existing, record)"
    )
