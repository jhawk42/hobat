#!/usr/bin/env python3
"""
Test to verify parse_ipv6_address_list correctly stops at new section headers
and doesn't incorrectly capture RouteId entries as IPv6 addresses.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from otbr_cli_networkdiag_parsers import parse_ipv6_address_list


def test_ipv6_parse_stops_at_connectivity():
    """Verify IPv6 parsing stops at Connectivity section."""
    sample = """
IP6 Address List:
    - fd3b:a255:4aa6:5483:0:ff:fe00:7c00
    - fd6e:44f0:ad93:1:2201:fa88:be40:3f6d
    - fe80:0:0:0:8c3b:369d:f65e:9496

Connectivity:
    ParentPriority: 0
    LinkQuality3: 13
"""
    result = parse_ipv6_address_list(sample)
    assert len(result) == 3, f"Expected 3 addresses, got {len(result)}"
    assert "fd3b:a255:4aa6:5483:0:ff:fe00:7c00" in result
    assert "fd6e:44f0:ad93:1:2201:fa88:be40:3f6d" in result
    assert "fe80:0:0:0:8c3b:369d:f65e:9496" in result
    assert "ParentPriority: 0" not in result
    print("✓ IPv6 parsing stops at Connectivity")


def test_ipv6_parse_stops_at_route():
    """Verify IPv6 parsing stops at Route section and doesn't capture RouteId."""
    sample = """
IP6 Address List:
    - fd3b:a255:4aa6:5483:0:ff:fe00:7c00
    - fd6e:44f0:ad93:1:2201:fa88:be40:3f6d

Route:
    IdSequence: 180
    RouteData:
        - RouteId: 0x03
          LinkQualityOut: 2
"""
    result = parse_ipv6_address_list(sample)
    assert len(result) == 2, f"Expected 2 addresses, got {len(result)}: {result}"
    assert "fd3b:a255:4aa6:5483:0:ff:fe00:7c00" in result
    assert "fd6e:44f0:ad93:1:2201:fa88:be40:3f6d" in result
    # Verify RouteId NOT captured
    for addr in result:
        assert "RouteId" not in addr, f"RouteId incorrectly captured: {addr}"
    print("✓ IPv6 parsing stops at Route (no RouteId captured)")


def test_ipv6_parse_stops_at_leader_data():
    """Verify IPv6 parsing stops at Leader Data section."""
    sample = """
IP6 Address List:
    - fd3b:a255:4aa6:5483:0:ff:fe00:6000
    - fd6e:44f0:ad93:1:d03e:3673:5923:8220

Leader Data:
    PartitionId: 0x533966c4
    Weighting: 68
"""
    result = parse_ipv6_address_list(sample)
    assert len(result) == 2, f"Expected 2 addresses, got {len(result)}"
    assert "PartitionId: 0x533966c4" not in result
    print("✓ IPv6 parsing stops at Leader Data")


def test_ipv6_parse_stops_at_vendor_fields():
    """Verify IPv6 parsing stops at Vendor fields."""
    sample = """
IP6 Address List:
    - fd6e:44f0:ad93:1:2201:fa88:be40:3f6d

Vendor Name: Apple
Vendor Model: Default
"""
    result = parse_ipv6_address_list(sample)
    assert len(result) == 1, f"Expected 1 address, got {len(result)}"
    assert "Apple" not in result
    assert "Default" not in result
    print("✓ IPv6 parsing stops at Vendor fields")


def test_ipv6_parse_full_example_from_7c00():
    """Test with real data from test_tlvs_7c00.txt."""
    sample = """
IP6 Address List:
    - fd3b:a255:4aa6:5483:0:ff:fe00:7c00
    - fd6e:44f0:ad93:1:2201:fa88:be40:3f6d
    - fd3b:a255:4aa6:5483:7721:98f4:1fdf:97d9
    - fe80:0:0:0:8c3b:369d:f65e:9496

Connectivity:
    ParentPriority: 0
    LinkQuality3: 13
    LinkQuality2: 3
    LinkQuality1: 3
    LeaderCost: 1
    IdSequence: 180
    ActiveRouters: 21
    SedBufferSize: 1280
    SedDatagramCount: 1

Leader Data:
    PartitionId: 0x533966c4
    Weighting: 68
    DataVersion: 113
    StableDataVersion: 140
    LeaderRouterId: 0x34

Vendor Name: Apple

Vendor Model: Default

Vendor SW Version: Default

Thread Stack Version: OPENTHREAD/0.01.00; POSIX; Apr 23 2026 20:16:51

Route:
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
"""
    result = parse_ipv6_address_list(sample)
    
    # Should have exactly 4 IPv6 addresses
    assert len(result) == 4, f"Expected 4 addresses, got {len(result)}: {result}"
    
    # Verify correct addresses captured
    assert "fd3b:a255:4aa6:5483:0:ff:fe00:7c00" in result
    assert "fd6e:44f0:ad93:1:2201:fa88:be40:3f6d" in result
    assert "fd3b:a255:4aa6:5483:7721:98f4:1fdf:97d9" in result
    assert "fe80:0:0:0:8c3b:369d:f65e:9496" in result
    
    # Verify no RouteId, Connectivity, Leader, or Vendor data captured
    for addr in result:
        assert "RouteId" not in addr, f"RouteId incorrectly captured: {addr}"
        assert "ParentPriority" not in addr
        assert "PartitionId" not in addr
        assert "Apple" not in addr
        assert "Default" not in addr
    
    print("✓ Full example from 7c00: Only IPv6 addresses captured (no Route/Connectivity/etc)")


if __name__ == "__main__":
    test_ipv6_parse_stops_at_connectivity()
    test_ipv6_parse_stops_at_route()
    test_ipv6_parse_stops_at_leader_data()
    test_ipv6_parse_stops_at_vendor_fields()
    test_ipv6_parse_full_example_from_7c00()
    
    print("\n" + "="*60)
    print("All IPv6 parsing fix tests passed! ✓")
    print("="*60)
