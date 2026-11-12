def test_search_and_filter_menu_behavior(node_json) -> None:
    result = node_json("tests/js/run-search-filters.mjs")
    assert result == {"matchedIndices": [0, 1], "restoredNodeFilter": "all"}
