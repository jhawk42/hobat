#!/usr/bin/env python3
"""
End-to-end test to verify multicast parsing and JSON output includes all new TLV fields.
"""

import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from otbr_cli_networkdiag_topology import (
    parse_multicast_diag_output,
    save_topology_to_json_file,
)


def test_multicast_to_json_output_has_all_fields():
    """Verify that multicast parsing → JSON output includes all new TLV fields."""
    
    # Load real multicast output from example file
    example_file = os.path.join(os.path.dirname(__file__), 'logs', 'test_tlvs_7c00.txt')
    with open(example_file, 'r') as f:
        multicast_output = f.read()
    
    # Parse multicast output
    parsed = parse_multicast_diag_output(multicast_output)
    
    # Should have 1 device
    assert len(parsed) == 1, f"Expected 1 device, got {len(parsed)}"
    
    # Get the device record (keyed by extaddr)
    device = list(parsed.values())[0]
    
    # Verify all new TLV fields are present
    assert "eui64" in device, "eui64 field missing"
    assert "connectivity" in device, "connectivity field missing"
    assert "leader_data" in device, "leader_data field missing"
    assert "vendor_name" in device, "vendor_name field missing"
    assert "vendor_model" in device, "vendor_model field missing"
    assert "vendor_sw_version" in device, "vendor_sw_version field missing"
    assert "route" in device, "route field missing"
    
    # Verify values
    assert device["eui64"] == "f434f0fffe1e1774", f"Wrong eui64: {device['eui64']}"
    assert device["vendor_name"] == "Apple", f"Wrong vendor_name: {device['vendor_name']}"
    assert device["vendor_model"] == "Default", f"Wrong vendor_model: {device['vendor_model']}"
    assert device["connectivity"]["link_quality_3"] == 13
    assert device["leader_data"]["partition_id"] == "0x533966c4"
    assert device["route"]["id_sequence"] == 180
    
    # Verify IPv6 addresses don't contain RouteId
    ipv6_addrs = device.get("ipv6_addrs", [])
    assert len(ipv6_addrs) == 4, f"Expected 4 IPv6 addresses, got {len(ipv6_addrs)}"
    for addr in ipv6_addrs:
        assert "RouteId" not in addr, f"RouteId incorrectly in ipv6_addrs: {addr}"
    
    print("✓ Parsed multicast output has all new TLV fields with correct values")
    
    # Now test JSON output
    # Create a dict keyed by rloc16 (as expected by save_topology_to_json_list)
    data_by_rloc = {
        device["rloc16"]: device
    }
    
    # Save to temporary JSON file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
        tmp_filename = tmp.name
    
    try:
        save_topology_to_json_file(data_by_rloc, tmp_filename)
        
        # Read back the JSON
        with open(tmp_filename, 'r') as f:
            json_output = json.load(f)
        
        # Should be a list with 1 device
        assert isinstance(json_output, list), "JSON output should be a list"
        assert len(json_output) == 1, f"Expected 1 device in JSON, got {len(json_output)}"
        
        json_device = json_output[0]
        
        # Verify all new TLV fields are in the JSON output (camelCase after normalization)
        assert "eui64" in json_device, "eui64 missing from JSON output"
        assert "connectivity" in json_device, "connectivity missing from JSON output"
        assert "leaderData" in json_device, "leaderData missing from JSON output"
        assert "vendorName" in json_device, "vendorName missing from JSON output"
        assert "vendorModel" in json_device, "vendorModel missing from JSON output"
        assert "vendorSwVersion" in json_device, "vendorSwVersion missing from JSON output"
        assert "route" in json_device, "route missing from JSON output"
        
        # Verify values in JSON (note: keys are normalized to camelCase)
        assert json_device["eui64"] == "f434f0fffe1e1774"
        assert json_device["vendorName"] == "Apple"
        assert json_device["vendorModel"] == "Default"
        assert json_device["vendorSwVersion"] == "Default"
        assert json_device["connectivity"]["linkQuality3"] == 13
        assert json_device["leaderData"]["partitionId"] == "0x533966c4"
        assert json_device["route"]["idSequence"] == 180
        assert len(json_device["route"]["routeData"]) == 21  # 21 routes
        
        # Verify IPv6 addresses in JSON don't contain RouteId
        json_ipv6_addrs = json_device.get("ipv6Addresses", [])
        assert len(json_ipv6_addrs) == 4, f"Expected 4 IPv6 addresses in JSON, got {len(json_ipv6_addrs)}"
        for addr in json_ipv6_addrs:
            assert "RouteId" not in addr, f"RouteId incorrectly in ipv6Addresses: {addr}"
        
        # Verify route is separate and has proper structure (camelCase keys)
        assert isinstance(json_device["route"], dict)
        assert "idSequence" in json_device["route"]
        assert "routeData" in json_device["route"]
        assert isinstance(json_device["route"]["routeData"], list)
        
        # Check first route entry structure (camelCase keys)
        first_route = json_device["route"]["routeData"][0]
        assert "routeId" in first_route
        assert "linkQualityOut" in first_route
        assert "linkQualityIn" in first_route
        assert "routeCost" in first_route
        assert first_route["routeId"] == "0x03"
        
        print("✓ JSON output has all new TLV fields with correct structure")
        print(f"✓ IPv6 addresses correctly separated from Route data")
        print(f"✓ Route data properly structured with {len(json_device['route']['routeData'])} routes")
        
    finally:
        # Clean up temp file
        if os.path.exists(tmp_filename):
            os.unlink(tmp_filename)


def test_device_with_empty_vendor_fields():
    """Test device with empty vendor fields (test_tlvs_6000.txt)."""
    
    example_file = os.path.join(os.path.dirname(__file__), 'logs', 'test_tlvs_6000.txt')
    with open(example_file, 'r') as f:
        multicast_output = f.read()
    
    parsed = parse_multicast_diag_output(multicast_output)
    assert len(parsed) == 1
    
    device = list(parsed.values())[0]
    
    # Verify empty vendor fields are None (not empty strings)
    assert device["vendor_name"] is None, f"Expected None, got {device['vendor_name']}"
    assert device["vendor_model"] is None, f"Expected None, got {device['vendor_model']}"
    assert device["vendor_sw_version"] is None, f"Expected None, got {device['vendor_sw_version']}"
    
    # Other fields should still be present
    assert device["eui64"] == "f4ce36a9111c02c1"
    assert device["connectivity"]["link_quality_3"] == 6
    assert device["leader_data"]["partition_id"] == "0x533966c4"
    assert device["route"]["id_sequence"] == 183
    
    print("✓ Device with empty vendor fields handled correctly (None values)")


if __name__ == "__main__":
    test_multicast_to_json_output_has_all_fields()
    test_device_with_empty_vendor_fields()
    
    print("\n" + "="*60)
    print("All end-to-end tests passed! ✓")
    print("Complete data flow verified:")
    print("  • Multicast parsing includes all new TLV fields")
    print("  • IPv6 addresses correctly separated from Route data")
    print("  • JSON output includes all fields with correct structure")
    print("  • Empty vendor fields handled as None")
    print("="*60)
