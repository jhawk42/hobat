from __future__ import annotations


def test_topology_profile_edge_constraints_exact_mutations(node_json) -> None:
    assert node_json("tests/js/run-topology-profile-edge-constraints.mjs") == {
        "profiles": 7,
        "exactEdgeComparisons": 175,
        "lengthComparisons": 297,
    }
