from td_health_graph import GraphEdge, analyze_undirected_graph


def _edge(left: str, right: str) -> GraphEdge:
    return GraphEdge(f"{left}-{right}", left, right)


def test_line_has_bridges_and_middle_articulation():
    analysis = analyze_undirected_graph(
        ["a", "b", "c"], [_edge("a", "b"), _edge("b", "c")]
    )

    assert analysis.bridge_relationship_ids == ("a-b", "b-c")
    assert analysis.articulation_device_ids == ("b",)
    assert analysis.bridge_components["a-b"] == (("a",), ("b", "c"))
    assert analysis.articulation_components["b"] == (("a",), ("c",))


def test_ring_has_no_single_path_elements():
    analysis = analyze_undirected_graph(
        ["a", "b", "c"],
        [_edge("a", "b"), _edge("b", "c"), _edge("c", "a")],
    )

    assert analysis.bridge_relationship_ids == ()
    assert analysis.articulation_device_ids == ()


def test_star_has_center_articulation_and_all_bridges():
    analysis = analyze_undirected_graph(
        ["a", "b", "c", "d"],
        [_edge("a", "b"), _edge("a", "c"), _edge("a", "d")],
    )

    assert analysis.bridge_relationship_ids == ("a-b", "a-c", "a-d")
    assert analysis.articulation_device_ids == ("a",)


def test_disconnected_components_are_analyzed_independently():
    analysis = analyze_undirected_graph(
        ["a", "b", "c", "d", "e"],
        [_edge("a", "b"), _edge("c", "d"), _edge("d", "e"), _edge("e", "c")],
    )

    assert analysis.bridge_relationship_ids == ("a-b",)
    assert analysis.articulation_device_ids == ()


def test_repeated_directional_reports_share_one_graph_edge():
    analysis = analyze_undirected_graph(
        ["a", "b", "c"],
        [
            GraphEdge("a-to-b", "a", "b"),
            GraphEdge("b-to-a", "b", "a"),
            _edge("b", "c"),
            _edge("c", "a"),
        ],
    )

    assert analysis.edge_count == 3
    assert analysis.bridge_relationship_ids == ()
    assert analysis.articulation_device_ids == ()