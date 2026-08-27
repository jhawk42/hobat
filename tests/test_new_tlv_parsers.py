"""
Unit tests for new TLV parsing functions (Phase 3 Testing).

Tests the 8 new parsing functions added for TLVs: 23, 4, 6, 24, 25, 26, 27, 5
"""

import os

# Add src directory to path
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


def test_parse_eui64():
    """Test EUI64 parsing (TLV 23)."""
    print("\n--- Testing parse_eui64 ---")
    
    # Test valid EUI64
    output = "EUI64: f434f0fffe1e1774"
    result = parse_eui64(output)
    assert result == "f434f0fffe1e1774"
    
    # Test missing EUI64
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_eui64(output)
    assert result is None


def test_parse_connectivity():
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
    assert result.get("parent_priority") == 0
    assert result.get("link_quality_3") == 13
    assert result.get("leader_cost") == 1
    assert result.get("id_sequence") == 180
    assert result.get("active_routers") == 21
    assert result.get("sed_buffer_size") == 1280
    
    # Test missing connectivity
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_connectivity(output)
    assert result == {}


def test_parse_leader_data():
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
    assert result.get("partition_id") == "0x533966c4"
    assert result.get("weighting") == 68
    assert result.get("data_version") == 113
    assert result.get("stable_data_version") == 140
    assert result.get("leader_router_id") == "0x34"
    
    # Test missing leader data
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_leader_data(output)
    assert result == {}


def test_parse_vendor_fields():
    """Test Vendor Name, Model, and SW Version parsing (TLVs 25, 26, 27)."""
    print("\n--- Testing parse_vendor_* ---")
    
    # Test valid vendor name
    output = "Vendor Name: Apple"
    result = parse_vendor_name(output)
    assert result == "Apple"
    
    # Test empty vendor name
    output = "Vendor Name: "
    result = parse_vendor_name(output)
    assert result is None
    
    # Test missing vendor name
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_vendor_name(output)
    assert result is None
    
    # Test valid vendor model
    output = "Vendor Model: Default"
    result = parse_vendor_model(output)
    assert result == "Default"
    
    # Test empty vendor model
    output = "Vendor Model: "
    result = parse_vendor_model(output)
    assert result is None
    
    # Test valid vendor SW version
    output = "Vendor SW Version: Default"
    result = parse_vendor_sw_version(output)
    assert result == "Default"
    
    # Test empty vendor SW version
    output = "Vendor SW Version: "
    result = parse_vendor_sw_version(output)
    assert result is None


def test_parse_route_data():
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
    assert result.get("id_sequence") == 180
    
    route_data = result.get("route_data", [])
    assert len(route_data) == 3
    
    if len(route_data) >= 1:
        assert route_data[0].get("route_id") == "0x03"
        assert route_data[0].get("link_quality_out") == 2
        assert route_data[0].get("route_cost") == 2
    
    if len(route_data) >= 2:
        assert route_data[1].get("route_id") == "0x04"
        assert route_data[1].get("route_cost") == 1
    
    # Test missing route data
    output = "Ext Address: 8e3b369df65e9496"
    result = parse_route_data(output)
    assert result == {}


def test_example_file_7c00():
    """Test parsing against test_tlvs_7c00.txt example file."""
    print("\n--- Testing test_tlvs_7c00.txt ---")
    
    file_path = os.path.join(os.path.dirname(__file__), 'logs', 'test_tlvs_7c00.txt')
    with open(file_path, 'r') as f:
        output = f.read()
    
    # Test individual parsers
    eui64 = parse_eui64(output)
    assert eui64 == "f434f0fffe1e1774"
    
    connectivity = parse_connectivity(output)
    assert connectivity.get("link_quality_3") == 13
    assert connectivity.get("leader_cost") == 1
    
    leader_data = parse_leader_data(output)
    assert leader_data.get("partition_id") == "0x533966c4"
    assert leader_data.get("weighting") == 68
    
    vendor_name = parse_vendor_name(output)
    assert vendor_name == "Apple"
    
    vendor_model = parse_vendor_model(output)
    assert vendor_model == "Default"
    
    vendor_sw_version = parse_vendor_sw_version(output)
    assert vendor_sw_version == "Default"
    
    route_data = parse_route_data(output)
    assert route_data.get("id_sequence") == 180
    assert len(route_data.get("route_data", [])) >= 3


def test_example_file_6000():
    """Test parsing against test_tlvs_6000.txt example file (empty vendor fields)."""
    print("\n--- Testing test_tlvs_6000.txt ---")
    
    file_path = os.path.join(os.path.dirname(__file__), 'logs', 'test_tlvs_6000.txt')
    with open(file_path, 'r') as f:
        output = f.read()
    
    # Test empty vendor fields (should return None)
    vendor_name = parse_vendor_name(output)
    assert vendor_name is None
    
    vendor_model = parse_vendor_model(output)
    assert vendor_model is None
    
    vendor_sw_version = parse_vendor_sw_version(output)
    assert vendor_sw_version is None
    
    # Other fields should still parse correctly
    eui64 = parse_eui64(output)
    assert eui64 == "f4ce36a9111c02c1"
    
    connectivity = parse_connectivity(output)
    assert connectivity.get("leader_cost") == 2


def test_multicast_integration():
    """Test parse_multicast_diag_output integration with new TLV fields."""
    print("\n--- Testing multicast integration ---")
    
    file_path = os.path.join(os.path.dirname(__file__), 'logs', 'test_tlvs_7c00.txt')
    with open(file_path, 'r') as f:
        output = f.read()
    
    # Parse as multicast output
    parsed = parse_multicast_diag_output(output, extaddr_map={})
    
    # Should have one device
    assert len(parsed) == 1
    
    # Get the device record
    device = list(parsed.values())[0] if parsed else {}
    
    # Verify new fields are present
    assert "eui64" in device
    assert "connectivity" in device
    assert "leader_data" in device
    assert "vendor_name" in device
    assert "vendor_model" in device
    assert "vendor_sw_version" in device
    assert "route" in device
    
    # Verify field values
    assert device.get("eui64") == "f434f0fffe1e1774"
    assert device.get("vendor_name") == "Apple"
    assert device.get("rloc16") == "0x7c00"
# Run this module through the repository pytest entry point.



