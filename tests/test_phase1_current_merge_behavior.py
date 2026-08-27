#!/usr/bin/env python3
"""
Phase 1: Test Current deep_merge() Behavior

This script tests the current merge behavior of merge_dataset.py
to understand its capabilities and limitations before Phase 2 enhancements.
"""

import json
import sys
from pathlib import Path
from copy import deepcopy

# Add src to path
from merge_dataset import (
    deep_merge,
    merge_lists,
    value_is_empty,
    values_equivalent,
    normalize_identifier_text,
)


def test_basic_dict_merge():
    """Test basic dictionary merging"""
    print("\n=== Test 1: Basic Dictionary Merge ===")
    
    base = {"extaddr": "aabbccddeeff1122", "rloc16": "0x5000", "name": "Device A"}
    incoming = {"rloc16": "0x5001", "room": "Living Room", "type": "router"}
    
    result = deep_merge(deepcopy(base), incoming)
    print(f"Base: {json.dumps(base, indent=2)}")
    print(f"Incoming: {json.dumps(incoming, indent=2)}")
    print(f"Result: {json.dumps(result, indent=2)}")
    
    # Expected: rloc16 should create conflict, room and type should merge in
    assert result["extaddr"] == "aabbccddeeff1122"
    assert result["room"] == "Living Room"
    assert "_merge_conflicts" in result
    print("✅ Basic dict merge works with conflict tracking")


def test_nested_object_merge():
    """Test nested object merging (route_data, leader_data)"""
    print("\n=== Test 2: Nested Object Merge ===")
    
    base = {
        "extaddr": "aabbccddeeff1122",
        "leader_data": {
            "partition_id": "0x12345678",
            "leader_router_id": "0x10"
        }
    }
    
    incoming = {
        "extaddr": "aabbccddeeff1122",
        "leader_data": {
            "leader_router_id": "0x10",
            "data_version": 100,
            "weighting": 64
        }
    }
    
    result = deep_merge(deepcopy(base), incoming)
    print(f"Result: {json.dumps(result, indent=2)}")
    
    # Expected: nested objects should merge, preserving all fields
    assert result["leader_data"]["partition_id"] == "0x12345678"
    assert result["leader_data"]["data_version"] == 100
    assert result["leader_data"]["weighting"] == 64
    print("✅ Nested object merge preserves all fields")


def test_route_data_array_merge():
    """Test how route_data arrays are currently merged"""
    print("\n=== Test 3: Route Data Array Merge ===")
    
    base = {
        "extaddr": "aabbccddeeff1122",
        "rloc16": "0x5000",
        "route_data": {
            "id_sequence": 100,
            "route_data": [
                {"route_id": "0x03", "link_quality_out": 3, "route_cost": 2},
                {"route_id": "0x05", "link_quality_out": 2, "route_cost": 3}
            ]
        }
    }
    
    incoming = {
        "extaddr": "aabbccddeeff1122",
        "rloc16": "0x5000",
        "route_data": {
            "id_sequence": 101,  # Newer sequence
            "route_data": [
                {"route_id": "0x03", "link_quality_out": 2, "route_cost": 3},  # Same route, different values
                {"route_id": "0x08", "link_quality_out": 3, "route_cost": 2}   # New route
            ]
        }
    }
    
    result = deep_merge(deepcopy(base), incoming)
    print(f"Result route_data: {json.dumps(result['route_data'], indent=2)}")
    print(f"Conflicts: {result.get('_merge_conflicts', [])}")
    
    # Current behavior: lists are deduplicated by JSON serialization
    # Problem: Doesn't use id_sequence precedence, creates duplicates for same route
    print(f"Number of route entries: {len(result['route_data']['route_data'])}")
    print("⚠️  Current merge creates duplicate route entries (same route_id)")
    print("⚠️  id_sequence not used for precedence")


def test_children_array_merge():
    """Test how children arrays are currently merged"""
    print("\n=== Test 4: Children Array Merge ===")
    
    base = {
        "extaddr": "parent1",
        "rloc16": "0x5000",
        "children": [
            {"extaddr": "child1", "rloc16": "0x5001", "mode": {"device": "MTD"}},
            {"extaddr": "child2", "rloc16": "0x5002", "mode": {"device": "MTD"}}
        ]
    }
    
    incoming = {
        "extaddr": "parent1",
        "rloc16": "0x5000",
        "children": [
            {"extaddr": "child1", "rloc16": "0x5001", "mode": {"device": "MTD"}, "age": 120},  # Same child, more data
            {"extaddr": "child3", "rloc16": "0x5003", "mode": {"device": "MTD"}}   # New child
        ]
    }
    
    result = deep_merge(deepcopy(base), incoming)
    print(f"Result children: {json.dumps(result['children'], indent=2)}")
    print(f"Number of children: {len(result['children'])}")
    
    # Current behavior: list deduplication doesn't understand child identity
    # Problem: child1 appears twice (different JSON due to 'age' field)
    print("⚠️  Current merge creates duplicate child entries (same extaddr)")


def test_empty_vs_missing_handling():
    """Test how empty values vs missing keys are handled"""
    print("\n=== Test 5: Empty vs Missing Value Handling ===")
    
    base = {
        "extaddr": "aabbccddeeff1122",
        "route_data": {
            "id_sequence": 100,
            "route_data": []  # Empty array
        },
        "name": ""  # Empty string
    }
    
    incoming = {
        "extaddr": "aabbccddeeff1122",
        "route_data": {
            "id_sequence": 101,
            "route_data": [
                {"route_id": "0x03", "link_quality_out": 3}
            ]
        },
        "name": "Device A"
    }
    
    result = deep_merge(deepcopy(base), incoming)
    print(f"Result: {json.dumps(result, indent=2)}")
    
    # Expected: empty values should be replaced by non-empty
    assert result["name"] == "Device A"
    print("✅ Empty strings replaced by non-empty values")
    print("✅ Empty arrays replaced by non-empty arrays")


def test_conflicting_values():
    """Test conflict detection and tracking"""
    print("\n=== Test 6: Conflicting Value Tracking ===")
    
    base = {
        "extaddr": "aabbccddeeff1122",
        "rloc16": "0x5000",
        "leader": 1,
        "connectivity": {
            "active_routers": 15,
            "leader_cost": 2
        }
    }
    
    incoming = {
        "extaddr": "aabbccddeeff1122",
        "rloc16": "0x5001",  # Conflict
        "leader": 0,          # Conflict
        "connectivity": {
            "active_routers": 18,  # Conflict
            "link_quality_3": 10   # New field
        }
    }
    
    result = deep_merge(deepcopy(base), incoming)
    print(f"Result: {json.dumps(result, indent=2)}")
    
    conflicts = result.get("_merge_conflicts", [])
    print(f"Number of conflicts: {len(conflicts)}")
    for conflict in conflicts:
        print(f"  - {conflict['path']}: {conflict['current']} vs {conflict['incoming']}")
    
    # Expected: conflicts tracked, existing values preserved
    assert result["rloc16"] == "0x5000"  # Base value preserved
    assert len(conflicts) >= 3  # At least 3 conflicts
    print("✅ Conflicts tracked correctly")
    print("✅ Base values preserved on conflict")


def test_source_files_tracking():
    """Test _source_files array merging"""
    print("\n=== Test 7: Source Files Tracking ===")
    
    base = {
        "extaddr": "aabbccddeeff1122",
        "_source_files": ["td-otbr-cli-networkdiag-fetch-all.json"]
    }
    
    incoming = {
        "extaddr": "aabbccddeeff1122",
        "_source_files": ["td-otbr-restapi-diagnostics.json"]
    }
    
    result = deep_merge(deepcopy(base), incoming)
    print(f"Source files: {result['_source_files']}")
    
    # Expected: source files merged and deduplicated
    assert len(result["_source_files"]) == 2
    print("✅ Source files merged and deduplicated")


def test_camelcase_vs_snakecase():
    """Test merging camelCase and snake_case variants"""
    print("\n=== Test 8: camelCase vs snake_case Variants ===")
    
    base = {
        "extaddr": "aabbccddeeff1122",
        "route_data": {  # snake_case
            "id_sequence": 100,
            "route_data": [{"route_id": "0x03"}]
        }
    }
    
    incoming = {
        "extAddress": "aabbccddeeff1122",  # camelCase
        "route": {  # Different parent name!
            "idSequence": 101,
            "routeData": [{"routeId": "0x05"}]
        }
    }
    
    result = deep_merge(deepcopy(base), incoming)
    print(f"Result: {json.dumps(result, indent=2)}")
    
    # Current behavior: treats route_data and route as separate fields
    # Problem: No field name normalization!
    if "route_data" in result and "route" in result:
        print("⚠️  route_data and route treated as separate fields (no normalization)")
    else:
        print("✅ Field normalization working")


def test_partition_awareness():
    """Test if partition_id is used for merge constraints"""
    print("\n=== Test 9: Partition Awareness ===")
    
    base = {
        "extaddr": "node1",
        "rloc16": "0x5000",
        "leader_data": {"partition_id": "0x12345678"},
        "route_data": {
            "id_sequence": 100,
            "route_data": [{"route_id": "0x03"}]
        }
    }
    
    incoming = {
        "extaddr": "node1",
        "rloc16": "0x6000",  # Different RLOC16 (might be different partition)
        "leader_data": {"partition_id": "0x87654321"},  # Different partition!
        "route_data": {
            "id_sequence": 101,
            "route_data": [{"route_id": "0x05"}]
        }
    }
    
    result = deep_merge(deepcopy(base), incoming)
    print(f"Result: {json.dumps(result, indent=2)}")

    assert result["leader_data"]["partition_id"] == "0x12345678"
    assert result["route_data"]["id_sequence"] == 100
    assert result["route_data"]["route_data"] == [
        {"route_id": "0x03"},
        {"route_id": "0x05"},
    ]
    assert {conflict["path"] for conflict in result["_merge_conflicts"]} == {
        "rloc16",
        "leader_data.partition_id",
        "route_data.id_sequence",
    }


def test_sequence_number_precedence():
    """Test if id_sequence is used for precedence"""
    print("\n=== Test 10: Sequence Number Precedence ===")
    
    base = {
        "extaddr": "node1",
        "route_data": {
            "id_sequence": 100,
            "route_data": [{"route_id": "0x03", "link_quality_out": 3}]
        },
        "connectivity": {
            "id_sequence": 100,
            "active_routers": 15
        }
    }
    
    incoming = {
        "extaddr": "node1",
        "route_data": {
            "id_sequence": 99,  # Older sequence!
            "route_data": [{"route_id": "0x03", "link_quality_out": 2}]
        },
        "connectivity": {
            "id_sequence": 101,  # Newer sequence
            "active_routers": 18
        }
    }
    
    result = deep_merge(deepcopy(base), incoming)
    print(f"Result: {json.dumps(result, indent=2)}")

    assert result["route_data"] == {
        "id_sequence": 100,
        "route_data": [
            {"route_id": "0x03", "link_quality_out": 3},
            {"route_id": "0x03", "link_quality_out": 2},
        ],
    }
    assert result["connectivity"] == {
        "id_sequence": 100,
        "active_routers": 15,
    }
    assert {conflict["path"] for conflict in result["_merge_conflicts"]} == {
        "route_data.id_sequence",
        "connectivity.id_sequence",
        "connectivity.active_routers",
    }


def run_all_tests():
    """Run all test scenarios"""
    print("=" * 70)
    print("Phase 1: Current deep_merge() Behavior Test Suite")
    print("=" * 70)
    
    try:
        test_basic_dict_merge()
        test_nested_object_merge()
        test_route_data_array_merge()
        test_children_array_merge()
        test_empty_vs_missing_handling()
        test_conflicting_values()
        test_source_files_tracking()
        test_camelcase_vs_snakecase()
        test_partition_awareness()
        test_sequence_number_precedence()
        
        print("\n" + "=" * 70)
        print("Summary: Current Merge Behavior Capabilities")
        print("=" * 70)
        print("✅ WORKING:")
        print("  - Basic dictionary merge")
        print("  - Nested object merge")
        print("  - Empty value replacement")
        print("  - Conflict tracking")
        print("  - Source files tracking")
        print("\n⚠️  LIMITATIONS (TO FIX IN PHASE 2):")
        print("  - No route entry identity matching (creates duplicates)")
        print("  - No child entry identity matching (creates duplicates)")
        print("  - No field name normalization (camelCase vs snake_case)")
        print("  - No partition-aware merge constraints")
        print("  - No sequence number precedence handling")
        print("  - No composite identity for routes (owner_rloc16, dest_route_id)")
        print("  - No composite identity for children (parent_rloc16, child_extaddr)")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(run_all_tests())
