def test_table_capability_predicates_shape_and_traversal(node_json) -> None:
    result = node_json("tests/js/run-table-capabilities.mjs")
    assert result["checked"] > 700
    assert result["flagCount"] == 27
    assert result["traversalReads"] == 21


def test_table_renderer_sorting_accessibility_and_selection(node_json) -> None:
    result = node_json("tests/js/run-table-renderer-sorting.mjs")

    assert result["ascendingMetrics"] == ["Beta", "Alpha", "Gamma", "Delta"]
    assert result["descendingMetrics"] == ["Alpha", "Beta", "Gamma", "Delta"]
    assert result["ascendingAddresses"] == ["Gamma", "Beta", "Delta", "Alpha"]
    assert result["ascendingTimestamps"] == ["Gamma", "Beta", "Alpha", "Delta"]
    assert result["ascendingVersions"] == ["Gamma", "Beta", "Alpha", "Delta"]
    assert result["ascendingHealthStatus"] == ["Beta", "Alpha", "Gamma", "Delta"]
    assert result["descendingHealthStatus"] == ["Delta", "Gamma", "Alpha", "Beta"]
    assert result["ascendingUptime"] == ["Uptime 99", "Uptime 100", "Uptime uint64"]
    assert result["descendingUptime"] == ["Uptime uint64", "Uptime 100", "Uptime 99"]
    assert result["matterTableStatusColumns"][0] >= result["matterTableStatusColumns"][1]
    assert result["ascendingAriaSort"] == "ascending"
    assert result["descendingAriaSort"] == "descending"
    assert result["metricFocusColumn"] == "metric"
    assert result["selectedName"] == "Beta"
    assert result["selectedRowPreserved"] is True
    assert result["identityActionButtons"] == 4
    assert result["healthColumnOrderingCases"] == 16
