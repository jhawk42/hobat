#!/usr/bin/env python3
"""
Unit tests for new TLV parsing functions (Phase 3 Testing).

Tests the 8 new parsing functions added for TLVs: 23, 4, 6, 24, 25, 26, 27, 5
"""

import sys
import os

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from otbr_cli_networkdiag_topology import (
    parse_eui64,
    parse_connectivity,
    parse_leader_data,
    parse_vendor_name,
    parse_vendor_model,
    parse_vendor_sw_version,
    parse_route_data,
    parse_multicast_diag_output,
)


class TestResults:
    """Simple test results tracker."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []
    
    def assert_equal(self, actual, expected, test_name):
        if actual == expected:
            self.passed += 1
            print(f"✓ {test_name}")
        else:
            self.failed += 1
            self.failures.append(test_name)
            print(f"✗ {test_name}")
            print(f"  Expected: {expected}")
            print(f"  Got: {actual}")
    
    def assert_none(self, actual, test_name):
        self.assert_equal(actual, None, test_name)
    
    def assert_empty_dict(self, actual, test_name):
        self.assert_equal(actual, {}, test_name)
    
    def assert_in(self, key, dictionary, test_name):
        if key in dictionary:
            self.passed += 1
            print(f"✓ {test_name}")
        else:
            self.failed += 1
            self.failures.append(test_name)
            print(f"✗ {test_name}")
            print(f"  Key '{key}' not found in dict")
    
    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Test Results: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"\nFailed tests:")
            for failure in self.failures:
                print(f"  - {failure}")
            return 1
        else:
            print("All tests passed! ✓")
            return 0


def test_parse_eui64(results):
    """Test EUI64 parsing (TLV 23)."""
    print("\n--- Testing parse_eui64 ---")
    
    # Test valid EUI64
    output = "EUI64: f434f0fffe1e1774"
    result = parse_eui64(output)
    results.assert_equal(result, "f434f0fffe1e1774", "parse_eui64_valid")
    
    # Test missing EUI64
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_eui64(output)
    results.assert_none(result, "parse_eui64_missing")


def test_parse_connectivity(results):
    """Test Connectivity parsing (TLV 4)."""
    print("\n--- Testing parse_connectivity ---")
    
    # Test full connectivity block
    output = """Connectivity:
    ParentPriority: 0
    LinkQuality3: 13
    LinkQuality2: 3
    LinkQuality1: 3
    LeaderCost: 1
    IdSequence: 180
    ActiveRouters: 21
    SedBufferSize: 1280
    SedDatagramCount: 1"""
    
    result = parse_connectivity(output)
    results.assert_equal(result.get("parent_priority"), 0, "connectivity_parent_priority")
    results.assert_equal(result.get("link_quality_3"), 13, "connectivity_link_quality_3")
    results.assert_equal(result.get("leader_cost"), 1, "connectivity_leader_cost")
    results.assert_equal(result.get("id_sequence"), 180, "connectivity_id_sequence")
    results.assert_equal(result.get("active_routers"), 21, "connectivity_active_routers")
    results.assert_equal(result.get("sed_buffer_size"), 1280, "connectivity_sed_buffer_size")
    
    # Test missing connectivity
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_connectivity(output)
    results.assert_empty_dict(result, "connectivity_missing")


def test_parse_leader_data(results):
    """Test Leader Data parsing (TLV 6)."""
    print("\n--- Testing parse_leader_data ---")
    
    # Test full leader data block
    output = """Leader Data:
    PartitionId: 0x533966c4
    Weighting: 68
    DataVersion: 113
    StableDataVersion: 140
    LeaderRouterId: 0x34"""
    
    result = parse_leader_data(output)
    results.assert_equal(result.get("partition_id"), "0x533966c4", "leader_data_partition_id")
    results.assert_equal(result.get("weighting"), 68, "leader_data_weighting")
    results.assert_equal(result.get("data_version"), 113, "leader_data_data_version")
    results.assert_equal(result.get("stable_data_version"), 140, "leader_data_stable_data_version")
    results.assert_equal(result.get("leader_router_id"), "0x34", "leader_data_leader_router_id")
    
    # Test missing leader data
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_leader_data(output)
    results.assert_empty_dict(result, "leader_data_missing")


def test_parse_vendor_fields(results):
    """Test Vendor Name, Model, and SW Version parsing (TLVs 25, 26, 27)."""
    print("\n--- Testing parse_vendor_* ---")
    
    # Test valid vendor name
    output = "Vendor Name: Apple"
    result = parse_vendor_name(output)
    results.assert_equal(result, "Apple", "vendor_name_valid")
    
    # Test empty vendor name
    output = "Vendor Name: "
    result = parse_vendor_name(output)
    results.assert_none(result, "vendor_name_empty")
    
    # Test missing vendor name
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_vendor_name(output)
    results.assert_none(result, "vendor_name_missing")
    
    # Test valid vendor model
    output = "Vendor Model: Default"
    result = parse_vendor_model(output)
    results.assert_equal(result, "Default", "vendor_model_valid")
    
    # Test empty vendor model
    output = "Vendor Model: "
    result = parse_vendor_model(output)
    results.assert_none(result, "vendor_model_empty")
    
    # Test valid vendor SW version
    output = "Vendor SW Version: Default"
    result = parse_vendor_sw_version(output)
    results.assert_equal(result, "Default", "vendor_sw_version_valid")
    
    # Test empty vendor SW version
    output = "Vendor SW Version: "
    result = parse_vendor_sw_version(output)
    results.assert_none(result, "vendor_sw_version_empty")


def test_parse_route_data(results):
    """Test Route data parsing (TLV 5)."""
    print("\n--- Testing parse_route_data ---")
    
    # Test route with multiple entries
    output = """Route:
    IdSequence: 180
    RouteData:
        - RouteId: 0x03
          LinkQualityOut: 2
          LinkQualityIn: 2
          RouteCost: 2
        - RouteId: 0x04
          LinkQualityOut: 3
          LinkQualityIn: 3
          RouteCost: 1
        - RouteId: 0x08
          LinkQualityOut: 3
          LinkQualityIn: 3
          RouteCost: 1"""
    
    result = parse_route_data(output)
    results.assert_equal(result.get("id_sequence"), 180, "route_data_id_sequence")
    
    route_data = result.get("route_data", [])
    results.assert_equal(len(route_data), 3, "route_data_count")
    
    if len(route_data) >= 1:
        results.assert_equal(route_data[0].get("route_id"), "0x03", "route_data_entry0_id")
        results.assert_equal(route_data[0].get("link_quality_out"), 2, "route_data_entry0_lqo")
        results.assert_equal(route_data[0].get("route_cost"), 2, "route_data_entry0_cost")
    
    if len(route_data) >= 2:
        results.assert_equal(route_data[1].get("route_id"), "0x04", "route_data_entry1_id")
        results.assert_equal(route_data[1].get("route_cost"), 1, "route_data_entry1_cost")
    
    # Test missing route data
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_route_data(output)
    results.assert_empty_dict(result, "route_data_missing")


def test_example_file_7c00(results):
    """Test parsing against test_tlvs_7c00.txt example file."""
    print("\n--- Testing test_tlvs_7c00.txt ---")
    
    file_path = os.path.join(os.path.dirname(__file__), '..', 'test', 'test_tlvs_7c00.txt')
    if not os.path.exists(file_path):
        print(f"Warning: {file_path} not found, skipping")
        return
    
    with open(file_path, 'r') as f:
        output = f.read()
    
    # Test individual parsers
    eui64 = parse_eui64(output)
    results.assert_equal(eui64, "f434f0fffe1e1774", "7c00_eui64")
    
    connectivity = parse_connectivity(output)
    results.assert_equal(connectivity.get("link_quality_3"), 13, "7c00_connectivity_lq3")
    results.assert_equal(connectivity.get("leader_cost"), 1, "7c00_connectivity_leader_cost")
    
    leader_data = parse_leader_data(output)
    results.assert_equal(leader_data.get("partition_id"), "0x533966c4", "7c00_leader_partition_id")
    results.assert_equal(leader_data.get("weighting"), 68, "7c00_leader_weighting")
    
    vendor_name = parse_vendor_name(output)
    results.assert_equal(vendor_name, "Apple", "7c00_vendor_name")
    
    vendor_model = parse_vendor_model(output)
    results.assert_equal(vendor_model, "Default", "7c00_vendor_model")
    
    vendor_sw_version = parse_vendor_sw_version(output)
    results.assert_equal(vendor_sw_version, "Default", "7c00_vendor_sw_version")
    
    route_data = parse_route_data(output)
    results.assert_equal(route_data.get("id_sequence"), 180, "7c00_route_id_sequence")
    results.assert_equal(len(route_data.get("route_data", [])) >= 3, True, "7c00_route_has_entries")


def test_example_file_6000(results):
    """Test parsing against test_tlvs_6000.txt example file (empty vendor fields)."""
    print("\n--- Testing test_tlvs_6000.txt ---")
    
    file_path = os.path.join(os.path.dirname(__file__), '..', 'test', 'test_tlvs_6000.txt')
    if not os.path.exists(file_path):
        print(f"Warning: {file_path} not found, skipping")
        return
    
    with open(file_path, 'r') as f:
        output = f.read()
    
    # Test empty vendor fields (should return None)
    vendor_name = parse_vendor_name(output)
    results.assert_none(vendor_name, "6000_vendor_name_empty")
    
    vendor_model = parse_vendor_model(output)
    results.assert_none(vendor_model, "6000_vendor_model_empty")
    
    vendor_sw_version = parse_vendor_sw_version(output)
    results.assert_none(vendor_sw_version, "6000_vendor_sw_version_empty")
    
    # Other fields should still parse correctly
    eui64 = parse_eui64(output)
    results.assert_equal(eui64, "f4ce36a9111c02c1", "6000_eui64")
    
    connectivity = parse_connectivity(output)
    results.assert_equal(connectivity.get("leader_cost"), 2, "6000_connectivity_leader_cost")


def test_multicast_integration(results):
    """Test parse_multicast_diag_output integration with new TLV fields."""
    print("\n--- Testing multicast integration ---")
    
    file_path = os.path.join(os.path.dirname(__file__), '..', 'test', 'test_tlvs_7c00.txt')
    if not os.path.exists(file_path):
        print(f"Warning: {file_path} not found, skipping")
        return
    
    with open(file_path, 'r') as f:
        output = f.read()
    
    # Parse as multicast output
    parsed = parse_multicast_diag_output(output, extaddr_map={})
    
    # Should have one device
    results.assert_equal(len(parsed), 1, "multicast_one_device")
    
    # Get the device record
    device = list(parsed.values())[0] if parsed else {}
    
    # Verify new fields are present
    results.assert_in("eui64", device, "multicast_has_eui64")
    results.assert_in("connectivity", device, "multicast_has_connectivity")
    results.assert_in("leader_data", device, "multicast_has_leader_data")
    results.assert_in("vendor_name", device, "multicast_has_vendor_name")
    results.assert_in("vendor_model", device, "multicast_has_vendor_model")
    results.assert_in("vendor_sw_version", device, "multicast_has_vendor_sw_version")
    results.assert_in("route_data", device, "multicast_has_route_data")
    
    # Verify field values
    results.assert_equal(device.get("eui64"), "f434f0fffe1e1774", "multicast_eui64_value")
    results.assert_equal(device.get("vendor_name"), "Apple", "multicast_vendor_name_value")
    results.assert_equal(device.get("rloc16"), "0x7c00", "multicast_rloc16_value")


def main():
    """Run all tests."""
    print("="*60)
    print("Phase 3: TLV Parsing Tests")
    print("="*60)
    
    results = TestResults()
    
    # Unit tests for each parser
    test_parse_eui64(results)
    test_parse_connectivity(results)
    test_parse_leader_data(results)
    test_parse_vendor_fields(results)
    test_parse_route_data(results)
    
    # Integration tests with example files
    test_example_file_7c00(results)
    test_example_file_6000(results)
    
    # Multicast integration test
    test_multicast_integration(results)
    
    return results.summary()


if __name__ == "__main__":
    sys.exit(main())
