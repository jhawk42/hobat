from __future__ import annotations

import pytest


pytestmark = pytest.mark.requires_data_dir


def test_matter_presentation_keeps_units_scope_and_safe_endpoint_labels(node_json) -> None:
    assert node_json("tests/js/run-ha-matter-ws-presentation.mjs") == {"checks": 9}
