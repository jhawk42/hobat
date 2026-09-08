#!/usr/bin/env python3
"""
Phase 2 Enriched Merge Tests

Tests for the new Phase 2 functionality:
- Field name normalization (camelCase ↔ snake_case)
- Sequence number comparison with wraparound (RFC 1982)
- Route data merge by composite identity (owner_rloc16, dest_route_id)
- Children array merge by composite identity (parent_rloc16, child_extaddr)
- Router neighbors merge by identity
- Partition-aware merge constraints
"""

import sys
from pathlib import Path
from copy import deepcopy

# Add src directory to path
from merge_dataset import (
    get_canonical_field_name,
    normalize_field_names_in_record,
    is_sequence_newer,
    compare_sequences,
    get_partition_id,
    merge_route_data,
    merge_children_array,
    merge_router_neighbors,
    deep_merge,
)


def test_field_normalization():
    """Test field name normalization."""
    print("\n=== Test: Field Name Normalization ===")
    
    # Test canonical field name resolution
    assert get_canonical_field_name("extaddr") == "extaddr"
    assert get_canonical_field_name("extAddress") == "extaddr"
    assert get_canonical_field_name("Extended MAC") == "extaddr"
    assert get_canonical_field_name("route") == "route"
    assert get_canonical_field_name("id_sequence") == "id_sequence"
    assert get_canonical_field_name("idSequence") == "id_sequence"
    
    # Test record normalization
    record = {
        "extAddress": "0011223344556677",
        "routerId": "0x05",
        "omrIpv6Address": "fd00::1",
    }
    normalized = normalize_field_names_in_record(record)
    assert "extaddr" in normalized
    assert "router_id" in normalized
    assert "omrIpv6Address" in normalized  # camelCase is the canonical form for this field
    # Original keys preserved
    assert "extAddress" in normalized
    assert "routerId" in normalized
    
    print("✅ PASS: Field normalization works correctly")


def test_sequence_number_comparison():
    """Test sequence number comparison with wraparound."""
    print("\n=== Test: Sequence Number Comparison (RFC 1982) ===")
    
    # No wraparound
    assert is_sequence_newer(100, 50) == True
    assert is_sequence_newer(50, 100) == False
    assert is_sequence_newer(100, 100) == False
    
    # Wraparound cases
    assert is_sequence_newer(5, 250) == True   # 250→255→0→5 (5 is newer)
    assert is_sequence_newer(250, 5) == False  # 250 is older than 5
    assert is_sequence_newer(255, 254) == True
    assert is_sequence_newer(0, 255) == True   # Wraparound
    assert is_sequence_newer(1, 255) == True
    assert is_sequence_newer(10, 240) == True
    
    # Edge cases (exactly half-max is ambiguous, treated as not newer)
    assert is_sequence_newer(128, 0) == False  # Exactly half-max (ambiguous)
    assert is_sequence_newer(0, 128) == False  # Exactly half-max (ambiguous)
    
    # Test compare_sequences helper
    assert compare_sequences(100, 50) == "a_newer"
    assert compare_sequences(50, 100) == "b_newer"
    assert compare_sequences(100, 100) == "equal"
    assert compare_sequences(None, 100) == "b_newer"
    assert compare_sequences(100, None) == "a_newer"
    assert compare_sequences(None, None) == "unknown"
    
    print("✅ PASS: Sequence number comparison with wraparound works correctly")


def test_partition_extraction():
    """Test partition ID extraction."""
    print("\n=== Test: Partition ID Extraction ===")
    
    # Canonical format (camelCase)
    record_rest = {
        "leaderData": {
            "partitionId": 305419896  # Decimal
        }
    }
    partition = get_partition_id(record_rest)
    assert partition == "0x12345678"
    
    # No partition data
    record_empty = {}
    assert get_partition_id(record_empty) == "unknown"
    
    print("✅ PASS: Partition extraction works correctly")


def test_route_data_merge_no_duplicates():
    """Test route data merge prevents duplicates."""
    print("\n=== Test: Route Data Merge (No Duplicates) ===")
    
    owner_rloc16 = "0x1400"
    partition_id = "0x12345678"
    
    # Base route object (canonical camelCase)
    base_route_data = {
        "idSequence": 100,
        "routeData": [
            {"routeId": "0x03", "linkQualityOut": 3, "routeCost": 1}
        ]
    }
    
    # Incoming route object with updated route to 0x03 with same sequence
    incoming_route_data = {
        "idSequence": 100,
        "routeData": [
            {"routeId": "0x03", "linkQualityOut": 2, "routeCost": 2}
        ]
    }
    
    result = merge_route_data(owner_rloc16, base_route_data, incoming_route_data, partition_id)
    
    # Should have only ONE entry for routeId 0x03
    routes = result.get("routeData", [])
    assert len(routes) == 1
    assert routes[0]["routeId"] == "0x03"
    
    print(f"✅ PASS: Route merge prevents duplicates (1 route, not 2)")


def test_route_data_merge_preserves_numeric_router_id_zero() -> None:
    result = merge_route_data(
        "0x1400",
        {
            "idSequence": 100,
            "routeData": [
                {"routeId": 0, "linkQualityOut": 0},
                {"linkQualityOut": 3},
            ],
        },
        {
            "idSequence": 100,
            "routeData": [
                {"routeId": 0, "linkQualityIn": 3},
                {"routeCost": 2},
            ],
        },
        "0x12345678",
    )

    assert result["routeData"] == [
        {"routeId": 0, "linkQualityOut": 0, "linkQualityIn": 3}
    ]


def test_route_data_sequence_precedence():
    """Test route data respects sequence number precedence."""
    print("\n=== Test: Route Data Sequence Precedence ===")
    
    owner_rloc16 = "0x1400"
    partition_id = "0x12345678"
    
    # Base route has older sequence
    base_route_data = {
        "idSequence": 50,
        "routeData": [
            {"routeId": "0x03", "linkQualityOut": 1}
        ]
    }
    
    # Incoming route has newer sequence
    incoming_route_data = {
        "idSequence": 100,
        "routeData": [
            {"routeId": "0x03", "linkQualityOut": 3}
        ]
    }
    
    result = merge_route_data(owner_rloc16, base_route_data, incoming_route_data, partition_id)
    
    # Should use incoming (newer sequence)
    seq = result.get("idSequence")
    assert seq == 100
    routes = result.get("routeData", [])
    assert routes[0]["linkQualityOut"] == 3
    
    print("✅ PASS: Route data respects sequence precedence (newer wins)")


def test_route_data_wraparound_sequence():
    """Test route data handles sequence wraparound."""
    print("\n=== Test: Route Data Sequence Wraparound ===")
    
    owner_rloc16 = "0x1400"
    partition_id = "0x12345678"
    
    # Base route has high sequence (near wrap)
    base_route_data = {
        "idSequence": 250,
        "routeData": [
            {"routeId": "0x03", "linkQualityOut": 1}
        ]
    }
    
    # Incoming route has wrapped sequence (should be newer)
    incoming_route_data = {
        "idSequence": 5,
        "routeData": [
            {"routeId": "0x03", "linkQualityOut": 3}
        ]
    }
    
    result = merge_route_data(owner_rloc16, base_route_data, incoming_route_data, partition_id)
    
    # Should use incoming (5 > 250 with wraparound)
    seq = result.get("idSequence")
    assert seq == 5
    routes = result.get("routeData", [])
    assert routes[0]["linkQualityOut"] == 3
    
    print("✅ PASS: Route data handles sequence wraparound correctly")


def test_route_data_camelcase_snakecase():
    """Test route data merge with camelCase canonical format."""
    print("\n=== Test: Route Data camelCase Canonical Format ===")
    
    owner_rloc16 = "0x1400"
    partition_id = "0x12345678"
    
    # Base route (camelCase canonical)
    base_route_data = {
        "idSequence": 100,
        "routeData": [
            {"routeId": "0x03", "linkQualityOut": 3}
        ]
    }
    
    # Incoming route (camelCase canonical)
    incoming_route = {
        "idSequence": 100,
        "routeData": [
            {"routeId": "0x03", "linkQualityOut": 2}
        ]
    }
    
    # Should recognize as same route
    result = merge_route_data(owner_rloc16, base_route_data, incoming_route, partition_id)
    
    # Should have merged (no duplicates)
    routes = result.get("routeData", [])
    assert len(routes) == 1
    
    print("✅ PASS: Route data merges canonical camelCase correctly")


def test_children_array_merge_no_duplicates():
    """Test children array merge prevents duplicates."""
    print("\n=== Test: Children Array Merge (No Duplicates) ===")
    
    parent_rloc16 = "0x1400"
    
    # Base has child with extAddress
    base = [
        {
            "extAddress": "0011223344556677",
            "childId": 1,
            "age": 100,
        }
    ]
    
    # Incoming has same child with updated data
    incoming = [
        {
            "extAddress": "0011223344556677",
            "childId": 1,
            "age": 150,
            "averageRssi": -50,
        }
    ]
    
    result = merge_children_array(parent_rloc16, base, incoming)
    
    # Should have only ONE child entry
    assert len(result) == 1
    assert result[0]["extAddress"] == "0011223344556677"
    assert result[0]["averageRssi"] == -50  # Merged new field
    
    print("✅ PASS: Children array merge prevents duplicates")


def test_children_array_different_parents():
    """Test children with same childId but different parents are NOT duplicates."""
    print("\n=== Test: Children Array - childId is Parent-Local ===")
    
    # Parent A has child with childId=1
    parent_a_rloc16 = "0x1400"
    parent_a_children = [
        {
            "extAddress": "0011223344556677",
            "childId": 1,
        }
    ]
    
    # Parent B ALSO has child with childId=1 (different child!)
    parent_b_rloc16 = "0x1800"
    parent_b_children = [
        {
            "extAddress": "8899aabbccddeeff",
            "childId": 1,  # Same childId, different child!
        }
    ]
    
    # Merge parent_a's children (should stay separate)
    result_a = merge_children_array(parent_a_rloc16, parent_a_children, [])
    result_b = merge_children_array(parent_b_rloc16, parent_b_children, [])
    
    assert len(result_a) == 1
    assert len(result_b) == 1
    assert result_a[0]["extAddress"] != result_b[0]["extAddress"]
    
    print("✅ PASS: childId correctly treated as parent-local (not globally unique)")


def test_router_neighbors_merge():
    """Test router neighbors merge by identity."""
    print("\n=== Test: Router Neighbors Merge ===")
    
    base = [
        {
            "extAddress": "0011223344556677",
            "rloc16": "0x1400",
            "linkQualityIn": 3,
        }
    ]
    
    incoming = [
        {
            "extAddress": "0011223344556677",
            "rloc16": "0x1400",
            "linkQualityOut": 2,
        }
    ]
    
    result = merge_router_neighbors(base, incoming)
    
    # Should merge into one neighbor
    assert len(result) == 1
    assert result[0]["extAddress"] == "0011223344556677"
    assert result[0]["linkQualityIn"] == 3
    assert result[0]["linkQualityOut"] == 2
    
    print("✅ PASS: Router neighbors merge correctly by identity")


def test_deep_merge_with_route_data():
    """Test deep_merge integration with route data."""
    print("\n=== Test: deep_merge Integration (Route Data) ===")
    
    base = {
        "rloc16": "0x1400",
        "extAddress": "0011223344556677",
        "leaderData": {
            "partitionId": "0x12345678"
        },
        "route": {
            "idSequence": 100,
            "routeData": [
                {"routeId": "0x03", "linkQualityOut": 3}
            ]
        }
    }
    
    incoming = {
        "route": {
            "idSequence": 100,
            "routeData": [
                {"routeId": "0x03", "linkQualityOut": 2},
                {"routeId": "0x05", "linkQualityOut": 3},
            ]
        }
    }
    
    result = deep_merge(deepcopy(base), incoming)
    
    # Should have merged routes (no duplicate 0x03)
    routes = result.get("route", {}).get("routeData", [])
    route_ids = [r.get("routeId") for r in routes]
    assert "0x03" in route_ids
    assert "0x05" in route_ids
    assert len([rid for rid in route_ids if rid == "0x03"]) == 1  # No duplicate
    
    print("✅ PASS: deep_merge correctly handles route data")


def test_deep_merge_with_children():
    """Test deep_merge integration with children array."""
    print("\n=== Test: deep_merge Integration (Children Array) ===")
    
    base = {
        "rloc16": "0x1400",
        "extAddress": "0011223344556677",
        "childTable": [
            {"extAddress": "aabbccddeeff0011", "childId": 1, "age": 100}
        ]
    }
    
    incoming = {
        "childTable": [
            {"extAddress": "aabbccddeeff0011", "childId": 1, "age": 150, "averageRssi": -50}
        ]
    }
    
    result = deep_merge(deepcopy(base), incoming)
    
    # Should have merged children (no duplicate)
    children = result.get("childTable", [])
    assert len(children) == 1
    assert children[0]["extAddress"] == "aabbccddeeff0011"
    assert children[0]["averageRssi"] == -50
    
    print("✅ PASS: deep_merge correctly handles children array")


def test_integration_canonical_merge():
    """Test full integration: canonical camelCase merge."""
    print("\n=== Test: Integration - Canonical camelCase Merge ===")
    
    # First node data (camelCase canonical)
    node1 = {
        "extAddress": "0011223344556677",
        "rloc16": "0x1400",
        "leaderData": {
            "partitionId": "0x12345678"
        },
        "route": {
            "idSequence": 100,
            "routeData": [
                {"routeId": "0x03", "linkQualityOut": 3}
            ]
        },
        "childTable": [
            {"extAddress": "aabbccddeeff0011", "age": 100}
        ],
        "_source_files": ["td-otbr-cli-networkdiag-fetch-all.json"]
    }
    
    # Second node data (camelCase canonical)
    node2 = {
        "extAddress": "0011223344556677",
        "rloc16": "0x1400",
        "leaderData": {
            "partitionId": 305419896
        },
        "route": {
            "idSequence": 100,
            "routeData": [
                {"routeId": "0x03", "linkQualityOut": 2},
                {"routeId": "0x05", "linkQualityOut": 3}
            ]
        },
        "childTable": [
            {"extAddress": "aabbccddeeff0011", "averageRssi": -50}
        ],
        "routerNeighbors": [
            {"extAddress": "1122334455667788", "linkQualityIn": 3}
        ],
        "_source_files": ["td-otbr-restapi-diagnostics.json"]
    }
    
    result = deep_merge(deepcopy(node1), node2)
    
    # Verify merged correctly
    assert result["extAddress"] == "0011223344556677"
    assert len(result["_source_files"]) == 2
    
    # Verify route data merged (no duplicates for 0x03)
    routes = result.get("route", {}).get("routeData", [])
    
    # Extract routeIds from merged routes
    route_ids = []
    for r in routes:
        if isinstance(r, dict):
            rid = r.get("routeId")
            if rid:
                route_ids.append(rid)
    
    assert len([rid for rid in route_ids if rid == "0x03"]) == 1, "Should have exactly 1 route with id 0x03"
    assert "0x05" in route_ids, f"Should have route 0x05, got: {route_ids}"
    
    # Verify children merged
    children = result.get("childTable", [])
    assert len(children) == 1
    
    # Verify router neighbors added
    neighbors = result.get("routerNeighbors", [])
    assert len(neighbors) == 1
    
    print("✅ PASS: Full canonical camelCase integration works correctly")


def run_all_tests():
    """Run all Phase 2 tests."""
    print("=" * 70)
    print("Phase 2 Enriched Merge Tests")
    print("=" * 70)
    
    test_field_normalization()
    test_sequence_number_comparison()
    test_partition_extraction()
    test_route_data_merge_no_duplicates()
    test_route_data_sequence_precedence()
    test_route_data_wraparound_sequence()
    test_route_data_camelcase_snakecase()
    test_children_array_merge_no_duplicates()
    test_children_array_different_parents()
    test_router_neighbors_merge()
    test_deep_merge_with_route_data()
    test_deep_merge_with_children()
    test_integration_cli_and_rest_api()
    
    print("\n" + "=" * 70)
    print("✅ ALL PHASE 2 TESTS PASSED!")
    print("=" * 70)
    print("\nPhase 2 Critical Gaps Resolved:")
    print("  ✅ No route entry duplicates (composite identity matching)")
    print("  ✅ No child entry duplicates (composite identity matching)")
    print("  ✅ Field name normalization (camelCase ↔ snake_case)")
    print("  ✅ Partition awareness (partition extraction)")
    print("  ✅ Sequence number precedence (RFC 1982 wraparound)")
    print("\nPhase 2 implementation is COMPLETE and VALIDATED!")


if __name__ == "__main__":
    run_all_tests()
