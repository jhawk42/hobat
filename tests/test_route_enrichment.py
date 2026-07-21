#!/usr/bin/env python3
"""
Test to verify _enrich_device_route_data_with_router_info correctly enriches route data.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from otbr_cli_networkdiag_topology import _enrich_device_route_data_with_router_info


def test_route_enrichment_with_valid_data():
    """Test route enrichment with matching router table data."""
    
    # Sample device record with route (matches actual structure)
    device_record = {
        "rloc16": "0x5800",
        "route": {
            "id_sequence": 215,
            "route_data": [
                {
                    "route_id": "0x03",
                    "link_quality_out": 3,
                    "link_quality_in": 3,
                    "route_cost": 1
                },
                {
                    "route_id": "0x16",
                    "link_quality_out": 2,
                    "link_quality_in": 1,
                    "route_cost": 2
                },
                {
                    "route_id": "0x34",
                    "link_quality_out": 3,
                    "link_quality_in": 3,
                    "route_cost": 1
                }
            ]
        }
    }
    
    # Sample router table keyed by router_id (matches actual structure)
    router_table_by_router_id = {
        "0x03": {
            "ID": 3,
            "rloc16": "0x0c00",
            "router_id": "0x03",
            "device_label": "Office Eve Compute Outlet"
        },
        "0x16": {
            "ID": 22,
            "rloc16": "0x5800",
            "router_id": "0x16",
            "device_label": "Office HomePod"
        },
        "0x34": {
            "ID": 52,
            "rloc16": "0xd000",
            "router_id": "0x34",
            "device_label": "Studio SB Right HomePod"
        }
    }
    
    # Call enrichment function
    _enrich_device_route_data_with_router_info(device_record, router_table_by_router_id)
    
    # Verify routes were enriched
    routes = device_record["route"]["route_data"]
    
    assert len(routes) == 3, f"Expected 3 routes, got {len(routes)}"
    
    # Check first route
    assert routes[0]["route_id"] == "0x03"
    assert routes[0]["rloc16"] == "0x0c00", f"Expected '0x0c00', got '{routes[0].get('rloc16')}'"
    
    # Check second route
    assert routes[1]["route_id"] == "0x16"
    assert routes[1]["rloc16"] == "0x5800", f"Expected '0x5800', got '{routes[1].get('rloc16')}'"
    
    # Check third route
    assert routes[2]["route_id"] == "0x34"
    assert routes[2]["rloc16"] == "0xd000", f"Expected '0xd000', got '{routes[2].get('rloc16')}'"
    
    print("✓ Route enrichment with valid data works correctly")


def test_route_enrichment_with_missing_router():
    """Test route enrichment when router_id not found in router table."""
    
    device_record = {
        "route": {
            "id_sequence": 100,
            "route_data": [
                {
                    "route_id": "0x99",  # Not in router table
                    "link_quality_out": 2,
                    "route_cost": 2
                }
            ]
        }
    }
    
    router_table_by_router_id = {
        "0x03": {"rloc16": "0x0c00", "router_id": "0x03"}
    }
    
    _enrich_device_route_data_with_router_info(device_record, router_table_by_router_id)
    
    routes = device_record["route"]["route_data"]
    assert routes[0]["rloc16"] == "Unknown", f"Expected 'Unknown', got '{routes[0].get('rloc16')}'"
    
    print("✓ Route enrichment handles missing router correctly (sets 'Unknown')")


def test_route_enrichment_with_none_router_table():
    """Test route enrichment gracefully handles None router table."""
    
    device_record = {
        "route": {
            "id_sequence": 100,
            "route_data": [
                {"route_id": "0x03", "link_quality_out": 3}
            ]
        }
    }
    
    # Should not raise exception
    _enrich_device_route_data_with_router_info(device_record, None)
    
    # Route should not have rloc16 added
    routes = device_record["route"]["route_data"]
    assert "rloc16" not in routes[0], "rloc16 should not be added when router_table is None"
    
    print("✓ Route enrichment handles None router_table gracefully")


def test_route_enrichment_with_empty_route_data():
    """Test route enrichment handles empty route gracefully."""
    
    device_record = {
        "route": {}
    }
    
    router_table = {"0x03": {"rloc16": "0x0c00"}}
    
    # Should not raise exception
    _enrich_device_route_data_with_router_info(device_record, router_table)
    
    print("✓ Route enrichment handles empty route_data gracefully")


def test_route_enrichment_with_no_route_data():
    """Test route enrichment handles missing route field gracefully."""
    
    device_record = {
        "rloc16": "0x5800"
        # No route field
    }
    
    router_table = {"0x03": {"rloc16": "0x0c00"}}
    
    # Should not raise exception
    _enrich_device_route_data_with_router_info(device_record, router_table)
    
    print("✓ Route enrichment handles missing route field gracefully")


def test_route_enrichment_preserves_existing_fields():
    """Test that enrichment doesn't overwrite existing route fields."""
    
    device_record = {
        "route": {
            "id_sequence": 215,
            "route_data": [
                {
                    "route_id": "0x03",
                    "link_quality_out": 3,
                    "link_quality_in": 3,
                    "route_cost": 1
                }
            ]
        }
    }
    
    router_table = {
        "0x03": {"rloc16": "0x0c00", "router_id": "0x03"}
    }
    
    _enrich_device_route_data_with_router_info(device_record, router_table)
    
    route = device_record["route"]["route_data"][0]
    
    # Verify original fields preserved
    assert route["route_id"] == "0x03"
    assert route["link_quality_out"] == 3
    assert route["link_quality_in"] == 3
    assert route["route_cost"] == 1
    
    # Verify new field added
    assert route["rloc16"] == "0x0c00"
    
    print("✓ Route enrichment preserves existing fields")


if __name__ == "__main__":
    test_route_enrichment_with_valid_data()
    test_route_enrichment_with_missing_router()
    test_route_enrichment_with_none_router_table()
    test_route_enrichment_with_empty_route_data()
    test_route_enrichment_with_no_route_data()
    test_route_enrichment_preserves_existing_fields()
    
    print("\n" + "="*60)
    print("All route enrichment tests passed! ✓")
    print("="*60)
