from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tests" / "js" / "run-adaptor-contracts.mjs"


@pytest.mark.frontend
def test_route_data_adaptor_contracts_are_executable(node_json) -> None:
    assert node_json(RUNNER) == {"adaptorCount": 8}
