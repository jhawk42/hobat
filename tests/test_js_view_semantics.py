import pytest


@pytest.mark.parametrize("section", ["capabilities", "visibility", "identities"])
def test_pinned_view_semantics(node_json, section: str) -> None:
    result = node_json(
        "tests/js/run-view-semantics.mjs", "tests/fixtures/js_view_semantics.json", section,
    )
    assert result["nodes"] == ["br", "isolated", "mtd", "reed", "router", "unknown"]
    assert result["scopedIdentities"] == 2
