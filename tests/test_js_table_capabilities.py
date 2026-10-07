def test_table_capability_predicates_shape_and_traversal(node_json) -> None:
    result = node_json("tests/js/run-table-capabilities.mjs")
    assert result["checked"] > 700
    assert result["flagCount"] == 27
    assert result["traversalReads"] == 21
