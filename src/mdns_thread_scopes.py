import argparse
import json
import os
from platform import node
import socket
import sys
import threading
import time
import base64
import logging
from typing import Sequence
import util_network

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
from util_data import resolve_data_file_path, resolve_data_dir, save_json_atomic
from const import TD_DATA_DIR_ARG_HELP

TD_MDNS_BROWSE_TIMEOUT_ENV_NAME = "TD_MDNS_BROWSE_TIMEOUT"
# seconds (default if env var not set)"
TD_MDNS_BROWSE_TIMEOUT_DEFAULT_VALUE = 5

# Vendor OUI Lookup Table
VENDORS = {
    "0017f2": "Apple",
    "d828c9": "Google (Nest)",
    "f0d1a9": "Amazon/Eero",
    "44d832": "Nanoleaf",
    "00124b": "Texas Instruments",
}


def get_vendor_from_oui(oui):
    """Extract vendor from OUI (first 3 bytes of Extended Address)"""
    oui = oui[:6].lower()
    return VENDORS.get(oui, "Unknown Vendor")


def decode_state_bitmap_br(sb_hex):
    """Decode the State Bitmap (sb) field into individual bit meanings"""
    try:
        sb_int = int(sb_hex, 16)
        bits = {
            "connection_allowed": bool(sb_int & (1 << 0)),
            "native_commissioner": bool(sb_int & (1 << 1)),
            "active_commissioner": bool(sb_int & (1 << 2)),
            "active_thread_partition": bool(sb_int & (1 << 3)),
            "leader_role": bool(sb_int & (1 << 4)),
            "backbone_router": bool(sb_int & (1 << 5)),
        }
        return bits
    except ValueError:
        return None


def format_state_bitmap_br(bits):
    """Format State Bitmap bits into a readable summary"""
    if not bits:
        return "Invalid"

    status = []
    if bits["connection_allowed"]:
        status.append("Connection Allowed")
    if bits["native_commissioner"]:
        status.append("Native Commissioner")
    if bits["active_commissioner"]:
        status.append("Active Commissioner")
    if bits["active_thread_partition"]:
        status.append("Active Thread Partition")
    if bits["leader_role"]:
        status.append("Leader Role")
    if bits["backbone_router"]:
        status.append("Backbone Router")

    return ", ".join(status) if status else "No flags set"


# HAP Category Mapping
# Source: Apple HomeKit Developer Documentation
# https://developer.apple.com/documentation/homekit
HAP_CATEGORIES = {
    1: "Other (Generic/Unspecified)",
    2: "Bridges",
    3: "Fans",
    4: "Garage Door Openers",
    5: "Lighting (Light Bulb / Switch)",
    6: "Locks (Door Lock)",
    7: "Outlets (Smart Plug)",
    8: "Switches",
    9: "Thermostats",
    10: "Sensors",
    11: "Home Security (Alarm / Camera)",
    12: "Doors",
    13: "Windows",
    14: "Window Coverings (Blinds / Curtains)",
    15: "Programmable Switches (Smart Button)",
    17: "IP Cameras",
    18: "Video Doorbells",
    19: "Air Purifiers",
    20: "Air Heaters",
    21: "Air Conditioners",
    22: "Air Humidifiers",
    23: "Air Dehumidifiers",
    28: "Sprinklers",
    29: "Faucets",
    30: "Shower Systems",
    31: "Televisions",
    32: "Displays",
}


def decode_hap_status_flags(sf_value):
    """Decode HAP Status Flags (sf) - indicates accessory status.
    Source: Apple HAP Specification
      Bit 0: Pairing Status - 0=Paired, 1=Not Paired
      Bit 1: IP Networking - 0=Enabled, 1=Disabled
      Bit 2: Problem Detected - 0=No problem, 1=Problem Detected
      Bits 3-7: Reserved (shall be 0)
    """
    try:
        sf_int = int(sf_value)
        bits = {
            "pairing_status": "Not Paired"
            if bool(sf_int & (1 << 0))
            else "Paired",  # Bit 0: 1 = Not Paired, 0 = Paired
            "ip_networking_enabled": not bool(
                sf_int & (1 << 1)
            ),  # Bit 1: 0 = Enabled, 1 = Disabled
            # Bit 2: 1 = Problem Detected
            "problem_detected": bool(sf_int & (1 << 2)),
            "reserved_bits": (sf_int >> 3) & 0x1F,  # Bits 3-7: Reserved
        }
        return bits
    except (ValueError, TypeError):
        return None


def format_hap_status_flags(bits):
    """Format HAP Status Flags into a readable summary"""
    if not bits:
        return "Invalid"

    status = []
    status.append(f"Pairing: {bits['pairing_status']}")
    status.append(
        f"IP Networking: {'Enabled' if bits['ip_networking_enabled'] else 'Disabled'}"
    )
    status.append(
        f"Problem Detected: {'Yes' if bits['problem_detected'] else 'No'}")

    return " | ".join(status)


def decode_hap_feature_flags(ff_value):
    """Decode HAP Feature Flags (ff) - indicates supported features"""
    try:
        ff_int = (
            int(ff_value)
            if isinstance(ff_value, str)
            else int.from_bytes(ff_value, "big")
        )
        bits = {
            "supports_hap_over_coap": bool(
                ff_int & (1 << 0)
            ),  # Bit 0: Supports HAP over CoAP
            "supports_wifi_throughput": bool(
                ff_int & (1 << 1)
            ),  # Bit 1: Supports Wi-Fi Throughput
            "supports_matter_bridge": bool(
                ff_int & (1 << 2)
            ),  # Bit 2: Supports Matter Bridge
            "supports_hap_over_ble": bool(
                ff_int & (1 << 3)
            ),  # Bit 3: Supports HAP over BLE
        }
        return bits
    except (ValueError, TypeError):
        return None


def format_hap_feature_flags(bits):
    """Format HAP Feature Flags into a readable summary"""
    if not bits:
        return "Invalid"

    features = []
    if bits["supports_hap_over_coap"]:
        features.append("HAP over CoAP")
    if bits["supports_wifi_throughput"]:
        features.append("Wi-Fi Throughput Management")
    if bits["supports_matter_bridge"]:
        features.append("Matter Bridge")
    if bits["supports_hap_over_ble"]:
        features.append("HAP over BLE")

    return ", ".join(features) if features else "No special features"


def get_hap_category_name(ci_value):
    """Convert HAP Category Identifier to readable name"""
    try:
        ci_int = int(ci_value)
        return HAP_CATEGORIES.get(ci_int, f"Unknown Category ({ci_int})")
    except (ValueError, TypeError):
        return "Invalid Category"


# Matter Device Type Mapping
MATTER_DEVICE_TYPES = {
    16: "Dimmable Light",
    17: "On/Off Light",
    18: "On/Off Light Switch",
    19: "Dimmer Switch",
    20: "Color Dimmer Switch",
    33: "Extended Color Light",
    49: "Generic Switch",
    256: "On/Off Plug-in Unit",
    257: "Dimmable Plug-in Unit",
    258: "Color Temperature Light",
    259: "Extended Color Light",
    512: "Smart Plug",
    513: "Smart Light",
    768: "Door Lock",
    769: "Thermostat",
    770: "Door Lock with Bolt/Latch",
    1024: "Shade",
    1025: "Shade Controller",
    1280: "Occupancy Sensor",
    1281: "Temperature Sensor",
    1282: "Humidity Sensor",
    1283: "Light Sensor",
    1284: "Pressure Sensor",
    1285: "Flow Sensor",
    1536: "Thermostat",
    1792: "Color Controller",
    1793: "Extended Color Light",
    2048: "Pump",
    2049: "Pump Controller",
    2304: "Generic Switch",
    2305: "Dimmer Switch",
    2306: "Color Dimmer Switch",
    2307: "Light Switch",
    2308: "Occupancy Sensor",
    2560: "Bridged Node",
    2816: "Speaker",
    3072: "Content App",
    3328: "Casting Video Player",
    3584: "Basic Video Player",
    3840: "Television",
    4096: "Video Remote Control",
    4352: "Keyboard Remote Control",
    4608: "Generic Remote Control",
    4864: "Voice Remote Control",
    5120: "Microphone",
    5376: "Device Energy Management",
    5632: "Electric Vehicle Charging Unit",
    65539: "Speaker",
}


def get_matter_device_type_name(dt_value):
    """Convert Matter Device Type to readable name"""
    try:
        dt_int = int(dt_value)
        return MATTER_DEVICE_TYPES.get(dt_int, f"Unknown Device Type ({dt_int})")
    except (ValueError, TypeError):
        return "Invalid Device Type"


def parse_matter_vp(vp_value):
    """Parse Matter Vendor Product (VP) field: VendorID+ProductID"""
    try:
        vp_str = (
            vp_value.decode("utf-8") if isinstance(vp_value,
                                                   bytes) else str(vp_value)
        )
        if "+" in vp_str:
            parts = vp_str.split("+")
            vendor_id = int(parts[0])
            product_id = int(parts[1])
            return vendor_id, product_id, vp_str
        return None, None, vp_str
    except (ValueError, AttributeError):
        return None, None, str(vp_value)


def decode_matter_commissioning_data(cd_value):
    """Decode Matter Commissioning Data (CD) field"""
    try:
        cd_int = int(cd_value)
        bits = {
            "operational": bool(
                cd_int & (1 << 0)
            ),  # Bit 0: 1 = Operational, 0 = Commissioning mode
        }
        return bits
    except (ValueError, TypeError):
        return None


def format_matter_commissioning_data(bits):
    """Format Matter Commissioning Data into readable status"""
    if not bits:
        return "Invalid"
    return "Operational" if bits["operational"] else "Commissioning Mode"


def decode_matter_tcp_support(t_value):
    """Decode Matter TCP Support flag"""
    try:
        t_int = int(t_value)
        return bool(t_int)
    except (ValueError, TypeError):
        return None


def get_pairing_hint_description(ph_value):
    """Get description for Matter Pairing Hint"""
    try:
        ph_int = int(ph_value)
        hints = {
            0: "Default",
            1: "Setup Code Available",
            2: "Custom Setup Code",
            4: "Requires Physical Interaction",
            8: "Uses WiFi",
            16: "Uses Bluetooth",
            32: "Uses NFC",
            64: "Uses QR Code",
            128: "Already Paired/Commissioned",
        }
        descriptions = []
        for bit_val, desc in hints.items():
            if ph_int & bit_val:
                descriptions.append(desc)
        return " | ".join(descriptions) if descriptions else f"Unknown Hint ({ph_int})"
    except (ValueError, TypeError):
        return "Invalid Hint"


def decode_hap_setup_hash(sh_value):
    """Decode HAP Setup Hash (sh) field from Base64 to hex bytes"""
    try:
        sh_b64 = (
            sh_value.decode("utf-8") if isinstance(sh_value,
                                                   bytes) else str(sh_value)
        )
        # Decode Base64 to bytes
        hash_bytes = base64.b64decode(sh_b64)
        # Convert to hex string
        hash_hex = hash_bytes.hex().upper()
        return hash_hex
    except Exception as e:
        return None


def decode_thread_partition_id(pt_value):
    """Decode Thread Partition Identifier (pt) - 32-bit value"""
    try:
        pt_hex = pt_value.hex().upper()
        # pt_str = pt_value.decode('utf-8') if isinstance(pt_value, bytes) else str(pt_value)
        pt_int = int(pt_hex, 16)
        pt_hex = format(pt_int, "08x").upper()  # 32-bit value in hex
        return pt_int, pt_hex
    except (ValueError, TypeError):
        return None, None


def decode_thread_beacon_bitmap(bb_value):
    """Decode Thread Beacon Bitmap (bb) - 32-bit bitmap indicating network state"""
    try:
        bb_hex = bb_value.hex().upper()
        bb_int = int(bb_hex, 16)
        # bb_str = bb_value.decode('utf-8') if isinstance(bb_value, bytes) else str(bb_value)
        # bb_int = int(bb_value, 16) if isinstance(bb_value, str) else int(bb_value)
        bb_hex = format(bb_int, "04x").upper()  # 32-bit value in hex

        # Decode specific bits if any are set
        bits = {
            "commissioning_active": bool(
                bb_int & (1 << 0)
            ),  # Bit 0: Active commissioning
            "native_commissioner": bool(
                bb_int & (1 << 1)
            ),  # Bit 1: Native Commissioner
            # Bit 2: Ethernet Interface
            "eth_interface": bool(bb_int & (1 << 2)),
            "wifi_interface": bool(bb_int & (1 << 3)),  # Bit 3: WiFi Interface
            # Bit 4: Thread Interface
            "thread_interface": bool(bb_int & (1 << 4)),
            "thread_ml_eid": bool(
                bb_int & (1 << 5)
            ),  # Bit 5: Thread Multicast Listener EID
            "thread_dua": bool(
                bb_int & (1 << 6)
            ),  # Bit 6: Thread Domain Unicast Address
            # Bit 7: Backbone Router
            "backbone_router": bool(bb_int & (1 << 7)),
        }

        return bb_int, bb_hex, bits
    except (ValueError, TypeError):
        return None, None, None


def format_thread_beacon_bitmap(bits):
    """Format Thread Beacon Bitmap bits into readable summary"""
    if not bits:
        return "No flags set"

    status = []
    if bits["commissioning_active"]:
        status.append("Active Commissioning")
    if bits["native_commissioner"]:
        status.append("Native Commissioner")
    if bits["eth_interface"]:
        status.append("Ethernet Interface")
    if bits["wifi_interface"]:
        status.append("WiFi Interface")
    if bits["thread_interface"]:
        status.append("Thread Interface")
    if bits["thread_ml_eid"]:
        status.append("Thread Multicast Listener EID")
    if bits["thread_dua"]:
        status.append("Thread Domain Unicast Address")
    if bits["backbone_router"]:
        status.append("Backbone Router")

    return ", ".join(status) if status else "No flags set"


def decode_matter_icd_capability(icd_value):
    """Decode Matter ICD (Intermittently Connected Device) capability"""
    try:
        icd_str = (
            icd_value.decode("utf-8")
            if isinstance(icd_value, bytes)
            else str(icd_value)
        )
        icd_int = int(icd_str)

        if icd_int == 0:
            return "Not a Long Idle Time (LIT) Device - Short Idle Time (SIT) or Mains-Powered"
        elif icd_int == 1:
            return "Long Idle Time (LIT) Device with Extended Sleep/Check-in Protocol"
        else:
            return f"Unknown ICD Mode ({icd_int})"
    except (ValueError, TypeError):
        return None


def parse_fabric_and_node_ids_from_name(service_name):
    """Extract FabricID and NodeID from Matter operational service instance name

    Format: [64-bit Compressed Fabric ID]-[64-bit Node ID]._matter._tcp.local
    Example: 0000000000001234-000000000000ABCD._matter._tcp.local
    """
    try:
        # Remove the service type suffix to get the instance name
        # Example: "0000000000001234-000000000000ABCD._matter._tcp.local" -> "0000000000001234-000000000000ABCD"
        instance_name = service_name.replace("._matter._tcp.local", "").replace(
            "._matterc._udp.local", ""
        )

        # Split by hyphen to get FabricID and NodeID
        if "-" in instance_name:
            parts = instance_name.split("-")
            if len(parts) >= 2:
                fabric_id_hex = parts[0]
                node_id_hex = parts[1]

                # Convert to decimal for additional context
                try:
                    fabric_id_decimal = int(fabric_id_hex, 16)
                    node_id_decimal = int(node_id_hex, 16)
                    return (
                        fabric_id_hex,
                        node_id_hex,
                        fabric_id_decimal,
                        node_id_decimal,
                    )
                except ValueError:
                    return fabric_id_hex, node_id_hex, None, None

        return None, None, None, None
    except Exception:
        return None, None, None, None


# ---------------------------------------------------------------------------
# Field metadata registry
# Maps each known TXT record key to its human-readable full name.
# ---------------------------------------------------------------------------
FIELD_METADATA = {
    # Thread Border Router (_meshcop, _trel)
    "rv": "Protocol Revision",
    "vn": "Vendor Name",
    "mn": "Model Name",
    "tv": "Thread Version",
    "nn": "Network Name",
    "xp": "Extended PAN ID",
    "xa": "Extended Address",
    "dd": "Discriminator ID",
    "sq": "Sequence Number",
    "at": "IEEE 802.15.4 Extended Address",
    "id": "Device ID",
    "sb": "State Bitmap",
    "dt": "Device Type",
    "pt": "Partition Identifier",
    "bb": "Beacon Bitmap",
    "dn": "Domain Name",
    # HAP (_hap._udp, _hap._tcp)
    "md": "Model Name",
    "pv": "Protocol Version",
    "ci": "Category Identifier",
    "c#": "Configuration Number",
    "s#": "State Number",
    "sf": "Status Flags",
    "ff": "Feature Flags",
    "sh": "Setup Hash",
    # Matter (_matter._tcp, _matterc._udp)
    "txtvers": "TXT Record Version",
    "VP": "Vendor Product",
    "DT": "Device Type",
    "DN": "Device Name",
    "RI": "Rotating Identifier",
    "PI": "Product / Pairing Identifier",
    "CD": "Commissioning Data",
    "D": "Discriminator",
    "PH": "Pairing Hint",
    "SII": "Sleepy Idle Interval",
    "SAI": "Sleepy Active Interval",
    "SAT": "Sleepy Active Threshold",
    "T": "TCP Support",
    "ICD": "ICD Capability",
    "FabricID": "Fabric ID",
    "NodeID": "Node ID",
}


# ---------------------------------------------------------------------------
# Base helper: produces decoded / hex / base64 envelope for any TXT value.
# ---------------------------------------------------------------------------
def _base_field_dict(raw_value, full_name: str) -> dict:
    """Produce the common decoded/hex/base64 envelope for a TXT field value."""
    if isinstance(raw_value, bytes):
        return {
            "full_name": full_name,
            "decoded": raw_value.decode("utf-8", errors="replace"),
            "hex": raw_value.hex(),
            "base64": base64.b64encode(raw_value).decode("ascii"),
        }
    return {
        "full_name": full_name,
        "decoded": str(raw_value),
    }


# ---------------------------------------------------------------------------
# Per-field enricher functions
# Each takes (raw_value, full_name) and returns an enriched dict.
# ---------------------------------------------------------------------------


def _enrich_field_sb(raw_value, full_name: str) -> dict:
    """Enrich Thread Border Router State Bitmap (sb)."""
    result = _base_field_dict(raw_value, full_name)
    try:
        sb_hex = raw_value.hex() if isinstance(raw_value, bytes) else str(raw_value)
        sb_int = int(sb_hex, 16)
        result["int_value"] = sb_int
        bits = decode_state_bitmap_br(sb_hex)
        if bits:
            result["status"] = format_state_bitmap_br(bits)
            result["individual_bits"] = [
                {
                    "bit": 0,
                    "name": "connection_allowed",
                    "label": "Connection Allowed",
                    "value": bits["connection_allowed"],
                },
                {
                    "bit": 1,
                    "name": "native_commissioner",
                    "label": "Native Commissioner",
                    "value": bits["native_commissioner"],
                },
                {
                    "bit": 2,
                    "name": "active_commissioner",
                    "label": "Active Commissioner",
                    "value": bits["active_commissioner"],
                },
                {
                    "bit": 3,
                    "name": "active_thread_partition",
                    "label": "Active Thread Partition",
                    "value": bits["active_thread_partition"],
                },
                {
                    "bit": 4,
                    "name": "leader_role",
                    "label": "Leader Role",
                    "value": bits["leader_role"],
                },
                {
                    "bit": 5,
                    "name": "backbone_router",
                    "label": "Backbone Router",
                    "value": bits["backbone_router"],
                },
            ]
    except (ValueError, TypeError):
        pass
    return result


def _enrich_field_bb(raw_value, full_name: str) -> dict:
    """Enrich Thread Beacon Bitmap (bb)."""
    result = _base_field_dict(raw_value, full_name)
    bb_int, bb_hex, bits = decode_thread_beacon_bitmap(raw_value)
    if bb_int is not None:
        result["int_value"] = bb_int
        result["hex_value"] = bb_hex
        if bits:
            result["status"] = format_thread_beacon_bitmap(bits)
            result["individual_bits"] = [
                {
                    "bit": 0,
                    "name": "commissioning_active",
                    "label": "Active Commissioning",
                    "value": bits["commissioning_active"],
                },
                {
                    "bit": 1,
                    "name": "native_commissioner",
                    "label": "Native Commissioner",
                    "value": bits["native_commissioner"],
                },
                {
                    "bit": 2,
                    "name": "eth_interface",
                    "label": "Ethernet Interface",
                    "value": bits["eth_interface"],
                },
                {
                    "bit": 3,
                    "name": "wifi_interface",
                    "label": "WiFi Interface",
                    "value": bits["wifi_interface"],
                },
                {
                    "bit": 4,
                    "name": "thread_interface",
                    "label": "Thread Interface",
                    "value": bits["thread_interface"],
                },
                {
                    "bit": 5,
                    "name": "thread_ml_eid",
                    "label": "Thread Multicast Listener EID",
                    "value": bits["thread_ml_eid"],
                },
                {
                    "bit": 6,
                    "name": "thread_dua",
                    "label": "Thread Domain Unicast Address",
                    "value": bits["thread_dua"],
                },
                {
                    "bit": 7,
                    "name": "backbone_router",
                    "label": "Backbone Router",
                    "value": bits["backbone_router"],
                },
            ]
    return result


def _enrich_field_at(raw_value, full_name: str) -> dict:
    """Enrich IEEE 802.15.4 Extended Address (at)."""
    result = _base_field_dict(raw_value, full_name)
    try:
        at_hex = (
            raw_value.hex().upper()
            if isinstance(raw_value, bytes)
            else str(raw_value).upper()
        )
        result["oui"] = at_hex[:6]
        result["vendor"] = get_vendor_from_oui(at_hex)
        result["extension_id"] = at_hex[6:]
    except (ValueError, TypeError, AttributeError):
        pass
    return result


def _enrich_field_xa(raw_value, full_name: str) -> dict:
    """Enrich Extended Address (xa)."""
    result = _base_field_dict(raw_value, full_name)
    try:
        xa_hex = (
            raw_value.hex().upper()
            if isinstance(raw_value, bytes)
            else str(raw_value).upper()
        )
        result["oui"] = xa_hex[:6]
        result["vendor"] = get_vendor_from_oui(xa_hex)
    except (ValueError, TypeError, AttributeError):
        pass
    return result


def _enrich_field_pt(raw_value, full_name: str) -> dict:
    """Enrich Thread Partition Identifier (pt)."""
    result = _base_field_dict(raw_value, full_name)
    pt_int, pt_hex = decode_thread_partition_id(raw_value)
    if pt_int is not None:
        result["int_value"] = pt_int
        result["hex_value"] = pt_hex
    return result


def _enrich_field_sf(raw_value, full_name: str) -> dict:
    """Enrich HAP Status Flags (sf)."""
    result = _base_field_dict(raw_value, full_name)
    try:
        sf_str = (
            raw_value.decode("utf-8")
            if isinstance(raw_value, bytes)
            else str(raw_value)
        )
        bits = decode_hap_status_flags(sf_str)
        if bits:
            result["status"] = format_hap_status_flags(bits)
            result["individual_bits"] = [
                {
                    "bit": 0,
                    "name": "pairing_status",
                    "label": "Pairing Status",
                    "value": bits["pairing_status"],
                },
                {
                    "bit": 1,
                    "name": "ip_networking_enabled",
                    "label": "IP Networking",
                    "value": "Enabled" if bits["ip_networking_enabled"] else "Disabled",
                },
                {
                    "bit": 2,
                    "name": "problem_detected",
                    "label": "Problem Detected",
                    "value": "Yes" if bits["problem_detected"] else "No",
                },
            ]
    except (ValueError, TypeError):
        pass
    return result


def _enrich_field_ff(raw_value, full_name: str) -> dict:
    """Enrich HAP Feature Flags (ff)."""
    result = _base_field_dict(raw_value, full_name)
    try:
        ff_int = (
            int.from_bytes(raw_value, "big")
            if isinstance(raw_value, bytes)
            else int(raw_value)
        )
        bits = decode_hap_feature_flags(ff_int)
        if bits:
            result["supported_features"] = format_hap_feature_flags(bits)
            result["individual_bits"] = [
                {
                    "bit": 0,
                    "name": "supports_hap_over_coap",
                    "label": "HAP over CoAP",
                    "value": bits["supports_hap_over_coap"],
                },
                {
                    "bit": 1,
                    "name": "supports_wifi_throughput",
                    "label": "Wi-Fi Throughput Management",
                    "value": bits["supports_wifi_throughput"],
                },
                {
                    "bit": 2,
                    "name": "supports_matter_bridge",
                    "label": "Matter Bridge",
                    "value": bits["supports_matter_bridge"],
                },
                {
                    "bit": 3,
                    "name": "supports_hap_over_ble",
                    "label": "HAP over BLE",
                    "value": bits["supports_hap_over_ble"],
                },
            ]
    except (ValueError, TypeError):
        pass
    return result


def _enrich_field_sh(raw_value, full_name: str) -> dict:
    """Enrich HAP Setup Hash (sh)."""
    result = _base_field_dict(raw_value, full_name)
    sh_hex = decode_hap_setup_hash(raw_value)
    if sh_hex:
        result["hex_value"] = sh_hex
        result["purpose"] = (
            "Hash derived from Setup ID and Device ID for pairing verification"
        )
    return result


def _enrich_field_ci(raw_value, full_name: str) -> dict:
    """Enrich HAP Category Identifier (ci)."""
    result = _base_field_dict(raw_value, full_name)
    try:
        ci_str = (
            raw_value.decode("utf-8")
            if isinstance(raw_value, bytes)
            else str(raw_value)
        )
        result["category_name"] = get_hap_category_name(ci_str)
    except (ValueError, TypeError):
        pass
    return result


def _enrich_field_VP(raw_value, full_name: str) -> dict:
    """Enrich Matter Vendor Product (VP)."""
    result = _base_field_dict(raw_value, full_name)
    vendor_id, product_id, vp_str = parse_matter_vp(raw_value)
    if vendor_id is not None:
        result["vendor_id"] = vendor_id
    if product_id is not None:
        result["product_id"] = product_id
    return result


def _enrich_field_DT(raw_value, full_name: str) -> dict:
    """Enrich Matter Device Type (DT)."""
    result = _base_field_dict(raw_value, full_name)
    try:
        dt_str = (
            raw_value.decode("utf-8")
            if isinstance(raw_value, bytes)
            else str(raw_value)
        )
        result["device_type_name"] = get_matter_device_type_name(dt_str)
    except (ValueError, TypeError):
        pass
    return result


def _enrich_field_CD(raw_value, full_name: str) -> dict:
    """Enrich Matter Commissioning Data (CD)."""
    result = _base_field_dict(raw_value, full_name)
    try:
        cd_str = (
            raw_value.decode("utf-8")
            if isinstance(raw_value, bytes)
            else str(raw_value)
        )
        bits = decode_matter_commissioning_data(cd_str)
        if bits:
            result["status"] = format_matter_commissioning_data(bits)
    except (ValueError, TypeError):
        pass
    return result


def _enrich_field_D(raw_value, full_name: str) -> dict:
    """Enrich Matter Discriminator (D)."""
    result = _base_field_dict(raw_value, full_name)
    try:
        d_str = (
            raw_value.decode("utf-8")
            if isinstance(raw_value, bytes)
            else str(raw_value)
        )
        d_int = int(d_str)
        result["int_value"] = d_int
        result["hex_value"] = format(d_int, "03x")
    except (ValueError, TypeError):
        pass
    return result


def _enrich_field_PH(raw_value, full_name: str) -> dict:
    """Enrich Matter Pairing Hint (PH)."""
    result = _base_field_dict(raw_value, full_name)
    try:
        ph_str = (
            raw_value.decode("utf-8")
            if isinstance(raw_value, bytes)
            else str(raw_value)
        )
        result["description"] = get_pairing_hint_description(ph_str)
    except (ValueError, TypeError):
        pass
    return result


def _enrich_field_interval_ms(raw_value, full_name: str) -> dict:
    """Enrich a millisecond interval field (SII, SAI, SAT)."""
    result = _base_field_dict(raw_value, full_name)
    try:
        ms_str = (
            raw_value.decode("utf-8")
            if isinstance(raw_value, bytes)
            else str(raw_value)
        )
        ms_int = int(ms_str)
        result["milliseconds"] = ms_int
        result["seconds"] = round(ms_int / 1000.0, 3)
    except (ValueError, TypeError):
        pass
    return result


def _enrich_field_T(raw_value, full_name: str) -> dict:
    """Enrich Matter TCP Support flag (T)."""
    result = _base_field_dict(raw_value, full_name)
    try:
        t_str = (
            raw_value.decode("utf-8")
            if isinstance(raw_value, bytes)
            else str(raw_value)
        )
        tcp_support = decode_matter_tcp_support(t_str)
        if tcp_support is not None:
            result["supported"] = tcp_support
    except (ValueError, TypeError):
        pass
    return result


def _enrich_field_ICD(raw_value, full_name: str) -> dict:
    """Enrich Matter ICD Capability (ICD)."""
    result = _base_field_dict(raw_value, full_name)
    desc = decode_matter_icd_capability(raw_value)
    if desc:
        result["description"] = desc
    return result


# ---------------------------------------------------------------------------
# Enricher dispatch table
# ---------------------------------------------------------------------------
FIELD_ENRICHERS = {
    "sb": _enrich_field_sb,
    "bb": _enrich_field_bb,
    "at": _enrich_field_at,
    "xa": _enrich_field_xa,
    "pt": _enrich_field_pt,
    "sf": _enrich_field_sf,
    "ff": _enrich_field_ff,
    "sh": _enrich_field_sh,
    "ci": _enrich_field_ci,
    "VP": _enrich_field_VP,
    "DT": _enrich_field_DT,
    "CD": _enrich_field_CD,
    "D": _enrich_field_D,
    "PH": _enrich_field_PH,
    "SII": _enrich_field_interval_ms,
    "SAI": _enrich_field_interval_ms,
    "SAT": _enrich_field_interval_ms,
    "T": _enrich_field_T,
    "ICD": _enrich_field_ICD,
}


def _enrich_properties(properties: dict) -> dict:
    """Return an enriched copy of a zeroconf properties dict.

    Each key maps to a structured object with full_name, decoded, hex, base64,
    plus any field-specific decoded information (bitmaps, categories, etc.).
    Unknown fields fall back to _base_field_dict.
    """
    enriched = {}
    for raw_key, raw_value in properties.items():
        key_str = (
            raw_key.decode("utf-8", errors="replace")
            if isinstance(raw_key, bytes)
            else str(raw_key)
        )
        full_name = FIELD_METADATA.get(key_str, key_str)
        enricher = FIELD_ENRICHERS.get(key_str)
        if enricher:
            enriched[key_str] = enricher(raw_value, full_name)
        else:
            enriched[key_str] = _base_field_dict(raw_value, full_name)
    return enriched


class MDNSDumpListener(ServiceListener):
    def __init__(self, include_matter_tcp_supported: bool = False, omr_ipv6addr_prefix: str = None):
        self._last_update = time.time()
        self.idle_done = threading.Event()
        self._lock = threading.Lock()
        self._records_by_key = {}
        self._include_matter_tcp_supported = include_matter_tcp_supported
        self._omr_ipv6addr_prefix = omr_ipv6addr_prefix

    def _update_last_event_time(self):
        """Record the time of the most recent service event."""
        self._last_update = time.time()

    def _to_json_safe_value(self, value):
        """Convert values to JSON-safe representations."""
        if isinstance(value, bytes):
            return {
                "decoded": value.decode("utf-8", errors="replace"),
                "hex": value.hex(),
                "base64": base64.b64encode(value).decode("ascii"),
            }
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            safe = {}
            for k, v in value.items():
                key_str = (
                    k.decode("utf-8", errors="replace")
                    if isinstance(k, bytes)
                    else str(k)
                )
                safe[key_str] = self._to_json_safe_value(v)
            return safe
        if isinstance(value, (list, tuple, set)):
            return [self._to_json_safe_value(v) for v in value]
        if hasattr(value, "__dict__"):
            return self._to_json_safe_value(vars(value))
        return str(value)

    def _build_record_from_service_info(self, type_: str, name: str, info, event: str):
        """Build a common JSON record from zeroconf ServiceInfo + metadata."""
        parsed_addresses = []
        omrIpv6Address = None
        if info and hasattr(info, "parsed_addresses"):
            try:
                parsed_addresses = info.parsed_addresses()
                # Enhance node with OMR IPv6 address  using OMR prefix
                if self._omr_ipv6addr_prefix:
                    omrIpv6Address = util_network.find_omr_address_in_list(
                        parsed_addresses, self._omr_ipv6addr_prefix
                    )
            except Exception:
                parsed_addresses = []

        raw_addresses = []
        if info and getattr(info, "addresses", None):
            raw_addresses = [
                a.hex() if isinstance(a, bytes) else str(a) for a in info.addresses
            ]

        properties = {}
        if info and getattr(info, "properties", None):
            properties = _enrich_properties(info.properties)

        # For Matter operational scope, inject FabricID / NodeID extracted from
        # the service instance name when they are absent from the TXT properties.
        if type_ == "_matter._tcp.local.":
            if "FabricID" not in properties:
                fabric_id_hex, node_id_hex, fabric_id_dec, node_id_dec = (
                    parse_fabric_and_node_ids_from_name(name)
                )
                if fabric_id_hex:
                    entry = {
                        "full_name": FIELD_METADATA.get("FabricID", "Fabric ID"),
                        "decoded": fabric_id_hex,
                        "source": "instance_name",
                    }
                    if fabric_id_dec is not None:
                        entry["int_value"] = fabric_id_dec
                    properties["FabricID"] = entry
            if "NodeID" not in properties:
                fabric_id_hex, node_id_hex, fabric_id_dec, node_id_dec = (
                    parse_fabric_and_node_ids_from_name(name)
                )
                if node_id_hex:
                    entry = {
                        "full_name": FIELD_METADATA.get("NodeID", "Node ID"),
                        "decoded": node_id_hex,
                        "source": "instance_name",
                    }
                    if node_id_dec is not None:
                        entry["int_value"] = node_id_dec
                    properties["NodeID"] = entry

        service_info = {}
        if info:
            # Start with all public non-callable attributes from ServiceInfo.
            if hasattr(info, "__dict__"):
                try:
                    for k, v in vars(info).items():
                        if not k.startswith("_"):
                            service_info[k] = self._to_json_safe_value(v)
                except TypeError:
                    pass
            for attr_name in dir(info):
                if attr_name.startswith("_") or attr_name in service_info:
                    continue
                try:
                    attr_value = getattr(info, attr_name)
                except Exception:
                    continue
                if callable(attr_value):
                    continue
                service_info[attr_name] = self._to_json_safe_value(attr_value)

            # Override with explicitly structured / enriched fields.
            service_info.update(
                {
                    "name": getattr(info, "name", None),
                    "type": getattr(info, "type", None),
                    "server": getattr(info, "server", None),
                    "port": getattr(info, "port", None),
                    "priority": getattr(info, "priority", None),
                    "weight": getattr(info, "weight", None),
                    "interface_index": getattr(info, "interface_index", None),
                    "host_ttl": getattr(info, "host_ttl", None),
                    "other_ttl": getattr(info, "other_ttl", None),
                    "key": getattr(info, "key", None),
                    "text": self._to_json_safe_value(getattr(info, "text", None)),
                    "addresses_raw_hex": raw_addresses,
                    "addresses_parsed": parsed_addresses,
                    "properties": properties,
                }
            )

        # Build the final record object with metadata and enriched service info.
        retobj = {}
        retobj["record_key"] = f"{type_}|{name}"
        retobj["record_key"] = f"{type_}|{name}"
        retobj["event"] = event
        retobj["captured_at_epoch"] = time.time()
        retobj["captured_at_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        retobj["scope"] = type_
        retobj["name"] = name
        # Add extaddr if xa exists. promote to top level for easier access
        extaddr = service_info.get("properties", {}).get(
            "xa", {}).get("hex", None)
        if extaddr is not None:
            retobj["extaddr"] = extaddr
        # Add omrIpv6Address if exists. promote to top level for easier access
        if omrIpv6Address is not None:
            retobj["omrIpv6Address"] = omrIpv6Address
        retobj["service_info"] = service_info

        return retobj

    def _is_matter_tcp_excluded(self, type_: str, info) -> bool:
        """Return True for _matter._tcp records that advertise TCP support (T=1).

        By default, Matter operational records with T=1 (TCP supported) are
        excluded from JSON output and console printing.  Records with T=0 or
        no T key are included.

        Pass --mattertcpsupported to include T=1 records.
        """
        if self._include_matter_tcp_supported:
            return False  # opt-in: never exclude
        if type_ != "_matter._tcp.local.":
            return False
        if info is None or not getattr(info, "properties", None):
            return False
        for raw_key, raw_val in info.properties.items():
            key_str = (
                raw_key.decode("utf-8", errors="replace")
                if isinstance(raw_key, bytes)
                else str(raw_key)
            )
            if key_str == "T":
                try:
                    val_str = (
                        raw_val.decode("utf-8")
                        if isinstance(raw_val, bytes)
                        else str(raw_val)
                    )
                    return bool(int(val_str))  # T=1 → exclude
                except (ValueError, TypeError):
                    return False
        return False  # T absent → include

    def _upsert_record(self, record):
        with self._lock:
            self._records_by_key[record["record_key"]] = record

    def get_records(self):
        with self._lock:
            return sorted(self._records_by_key.values(), key=lambda r: r["record_key"])

    def wait_for_idle(self, idle_timeout: float = 30.0, poll: float = 0.5):
        """Block until no service events have arrived for *idle_timeout* seconds,
        then set idle_done so callers can close Zeroconf cleanly."""
        while True:
            time.sleep(poll)
            if time.time() - self._last_update >= idle_timeout:
                self.idle_done.set()
                return

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._update_last_event_time()
        info = zc.get_service_info(type_, name)
        if self._is_matter_tcp_excluded(type_, info):
            return
        self._upsert_record(self._build_record_from_service_info(
            type_, name, info, "update"))

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._update_last_event_time()
        # Only record remove events for records we actually stored.
        record_key = f"{type_}|{name}"
        with self._lock:
            if record_key not in self._records_by_key:
                return
        self._upsert_record(self._build_record_from_service_info(
            type_, name, None, "remove"))
        print(f"Service Removed: {name}")

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._update_last_event_time()
        info = zc.get_service_info(type_, name)
        if self._is_matter_tcp_excluded(type_, info):
            return
        self._upsert_record(
            self._build_record_from_service_info(type_, name, info, "add"))
        if info:
            print(f"\n[ SCOPE: {type_} ]")
            print(f"  Name:    {name}")
            print(
                f"  Address: {socket.inet_ntoa(info.addresses[0]) if info.addresses else 'Unknown'}:{info.port}"
            )
            if hasattr(info, "parsed_addresses"):
                print(f"  Parsed Addresses: {info.parsed_addresses()}")
                # TODO print out the info.parsed_addresses list

            # Print TXT Records (where Matter/HAP data lives)
            if info.properties:
                # Check if this is a Thread Border Router scope with special attributes
                is_thread_br_scope = type_ in [
                    "_meshcop._udp.local.",
                    "_trel._udp.local.",
                ]
                is_hap_scope = type_ in [
                    "_hap._udp.local.", "_hap._tcp.local."]
                is_matter_scope = type_ in [
                    "_matter._tcp.local.",
                    "_matterc._udp.local.",
                ]

                if is_thread_br_scope:
                    print(f"\n[ THREAD BORDER ROUTER FOUND ]")
                else:
                    print(f"\n[ SCOPE: {type_} ]")

                print(f"  Instance Name: {name}")
                print(f"  Hostname:      {info.server}")
                print(
                    f"  Address:       {socket.inet_ntoa(info.addresses[0]) if info.addresses else 'Unknown'}:{info.port}"
                )

                if is_thread_br_scope:
                    props = {k.decode("utf-8"): v for k,
                             v in info.properties.items()}
                    print("\n  Thread Border Router Identity & Capabilities:")

                    # Revision
                    if "rv" in props and isinstance(props["rv"], bytes):
                        print(
                            f"    - Protocol Revision (rv): {props['rv'].decode('utf-8')}"
                        )

                    # Vendor Name
                    if "vn" in props and isinstance(props["vn"], bytes):
                        print(
                            f"    - Vendor Name (vn): {props['vn'].decode('utf-8')}")

                    # Model Name
                    if "mn" in props and isinstance(props["mn"], bytes):
                        print(
                            f"    - Model Name (mn): {props['mn'].decode('utf-8')}")

                    # Thread Version (tv)
                    if "tv" in props and isinstance(props["tv"], bytes):
                        print(
                            f"    - Thread Version (tv): {props['tv'].decode('utf-8')}"
                        )

                    # Network Name
                    if "nn" in props and isinstance(props["nn"], bytes):
                        print(
                            f"    - Network Name (nn): {props['nn'].decode('utf-8')}")

                    # Extended PAN ID (xp)
                    if "xp" in props and isinstance(props["xp"], bytes):
                        xp_hex = props["xp"].hex().upper()
                        print(f"    - Extended PAN ID (xp): {xp_hex}")

                    # Device ID (xa)
                    if "xa" in props and isinstance(props["xa"], bytes):
                        xa_hex = props["xa"].hex().upper()
                        print(f"    - Extended Address (xa): {xa_hex}")

                    # Discriminator ID (dd)
                    if "dd" in props and isinstance(props["dd"], bytes):
                        dd_hex = props["dd"].hex().upper()
                        print(f"    - Discriminator ID (dd): {dd_hex}")

                    # Sequence Number (sq)
                    # Monotonically increasing value that represents the version or state of the Thread Network's operational dataset.
                    if "sq" in props and isinstance(props["sq"], bytes):
                        print(
                            f"    - Sequence Number (sq): {props['sq'].decode('utf-8')}"
                        )

                    # Extended Address (at) - IEEE 802.15.4 Extended Address
                    if "at" in props and isinstance(props["at"], bytes):
                        at_hex = props["at"].hex().upper()
                        oui = at_hex[:6]
                        vendor = get_vendor_from_oui(at_hex)
                        ext_id = at_hex[6:]
                        print(f"    - Extended Address (at): {at_hex}")
                        print(f"      * OUI (Vendor): {oui} ({vendor})")
                        print(f"      * Extension ID: {ext_id}")

                    # Border Agent ID (id)
                    if "id" in props and isinstance(props["id"], bytes):
                        print(
                            f"    - Border Agent ID (id): {props['id'].hex().upper()}"
                        )

                    # State Bitmap (sb)
                    if "sb" in props and isinstance(props["sb"], bytes):
                        sb_hex = props["sb"].hex().upper()
                        sb_bits = decode_state_bitmap_br(sb_hex)
                        print(f"    - State Bitmap (sb): {sb_hex}")
                        if sb_bits:
                            print(
                                f"      * Status: {format_state_bitmap_br(sb_bits)}")
                            print(f"      * Individual Bits:")
                            print(
                                f"        - Bit 0 (Connection Allowed): {sb_bits['connection_allowed']}"
                            )
                            print(
                                f"        - Bit 1 (Native Commissioner): {sb_bits['native_commissioner']}"
                            )
                            print(
                                f"        - Bit 2 (Active Commissioner): {sb_bits['active_commissioner']}"
                            )
                            print(
                                f"        - Bit 3 (Active Thread Partition): {sb_bits['active_thread_partition']}"
                            )
                            print(
                                f"        - Bit 4 (Leader Role): {sb_bits['leader_role']}"
                            )
                            print(
                                f"        - Bit 5 (Backbone Router): {sb_bits['backbone_router']}"
                            )

                    # Device Type (dt)
                    if "dt" in props and isinstance(props["dt"], bytes):
                        print(
                            f"    - Device Type (dt): {props['dt'].decode('utf-8', errors='ignore')}"
                        )

                    # Partition Identifier (pt) - 32-bit value
                    if "pt" in props and isinstance(props["pt"], bytes):
                        pt_val = props["pt"]
                        # pt_hex = pt_val.hex().upper()
                        # pt_str = pt_val.decode('utf-8')
                        pt_int, pt_hex = decode_thread_partition_id(pt_val)
                        if pt_int is not None:
                            print(
                                f"    - Partition Identifier (pt): {pt_int} (0x{pt_hex})"
                            )
                        else:
                            print(f"    - Partition Identifier (pt): {pt_int}")

                    # Beacon Bitmap (bb) - 32-bit bitmap indicating network state
                    if "bb" in props and isinstance(props["bb"], bytes):
                        bb_val = props["bb"]
                        bb_str = bb_val.hex().upper()
                        bb_int, bb_hex, bb_bits = decode_thread_beacon_bitmap(
                            bb_val)
                        if bb_int is not None:
                            print(
                                f"    - Beacon Bitmap (bb): {bb_str} (0x{bb_hex})")
                            if bb_bits:
                                status_str = format_thread_beacon_bitmap(
                                    bb_bits)
                                print(f"      * Status: {status_str}")
                        else:
                            print(f"    - Beacon Bitmap (bb): {bb_str}")

                    # Domain Name (dn) - Human-readable Thread Network domain
                    if "dn" in props and isinstance(props["dn"], bytes):
                        dn_val = props["dn"]
                        dn_str = dn_val.decode("utf-8")
                        print(f"    - Domain Name (dn): {dn_str}")

                    # Print any vendor-specific or other metadata
                    standard_fields = {
                        "rv",
                        "vn",
                        "mn",
                        "tv",
                        "nn",
                        "xp",
                        "xa",
                        "dd",
                        "sq",
                        "at",
                        "id",
                        "sb",
                        "dt",
                        "pt",
                        "bb",
                        "dn",
                    }
                    other_fields = {
                        k.decode("utf-8"): v
                        for k, v in info.properties.items()
                        if k.decode("utf-8") not in standard_fields
                    }
                    if other_fields:
                        print("\n  Additional Metadata:")
                        for key, val in other_fields.items():
                            val_str = (
                                val.decode("utf-8", errors="ignore")
                                if isinstance(val, bytes)
                                else val
                            )
                            print(f"    - {key}: {val_str}")
                elif is_hap_scope:
                    props = {k.decode("utf-8"): v for k,
                             v in info.properties.items()}
                    print("\n  HomeKit Accessory Protocol (HAP) Attributes:")

                    # Device ID (id) - Mandatory
                    if "id" in props:
                        id_val = props["id"]
                        id_str = (
                            id_val.decode("utf-8")
                            if isinstance(id_val, bytes)
                            else id_val
                        )
                        print(f"    - Device ID (id): {id_str}")

                    # Model Name (md) - Mandatory
                    if "md" in props:
                        md_val = props["md"]
                        md_str = (
                            md_val.decode("utf-8")
                            if isinstance(md_val, bytes)
                            else md_val
                        )
                        print(f"    - Model Name (md): {md_str}")

                    # Protocol Version (pv) - Mandatory
                    if "pv" in props:
                        pv_val = props["pv"]
                        pv_str = (
                            pv_val.decode("utf-8")
                            if isinstance(pv_val, bytes)
                            else pv_val
                        )
                        print(f"    - Protocol Version (pv): {pv_str}")

                    # Category Identifier (ci) - Mandatory
                    if "ci" in props:
                        ci_val = props["ci"]
                        ci_str = (
                            ci_val.decode("utf-8")
                            if isinstance(ci_val, bytes)
                            else str(ci_val)
                        )
                        ci_name = get_hap_category_name(ci_str)
                        print(
                            f"    - Category Identifier (ci): {ci_str} ({ci_name})")

                    # Configuration Number (c#) - Mandatory
                    if "c#" in props:
                        c_hash_val = props["c#"]
                        c_hash_str = (
                            c_hash_val.decode("utf-8")
                            if isinstance(c_hash_val, bytes)
                            else str(c_hash_val)
                        )
                        print(f"    - Configuration Number (c#): {c_hash_str}")

                    # State Number (s#) - Mandatory
                    if "s#" in props:
                        s_hash_val = props["s#"]
                        s_hash_str = (
                            s_hash_val.decode("utf-8")
                            if isinstance(s_hash_val, bytes)
                            else str(s_hash_val)
                        )
                        print(f"    - State Number (s#): {s_hash_str}")

                    # Status Flags (sf) - Mandatory
                    if "sf" in props:
                        sf_val = props["sf"]
                        sf_str = (
                            sf_val.decode("utf-8")
                            if isinstance(sf_val, bytes)
                            else str(sf_val)
                        )
                        sf_bits = decode_hap_status_flags(sf_str)
                        print(f"    - Status Flags (sf): {sf_str}")
                        if sf_bits:
                            print(
                                f"      * {format_hap_status_flags(sf_bits)}")
                            print(f"      * Individual Bits:")
                            print(
                                f"        - Bit 0 (Pairing Status): {sf_bits['pairing_status']}"
                            )
                            print(
                                f"        - Bit 1 (IP Networking): {'Enabled' if sf_bits['ip_networking_enabled'] else 'Disabled'}"
                            )
                            print(
                                f"        - Bit 2 (Problem Detected): {'Yes' if sf_bits['problem_detected'] else 'No'}"
                            )

                    # Feature Flags (ff) - Optional
                    if "ff" in props:
                        ff_val = props["ff"]
                        ff_int = (
                            int(ff_val)
                            if isinstance(ff_val, bytes)
                            else int.from_bytes(ff_val, "big")
                            if isinstance(ff_val, bytes)
                            else ff_val
                        )
                        ff_bits = decode_hap_feature_flags(ff_int)
                        print(f"    - Feature Flags (ff): {ff_int}")
                        if ff_bits:
                            print(
                                f"      * Supported Features: {format_hap_feature_flags(ff_bits)}"
                            )

                    # Setup Hash (sh) - Optional, Base64-encoded 4-byte hash
                    if "sh" in props:
                        sh_val = props["sh"]
                        sh_b64_str = (
                            sh_val.decode("utf-8")
                            if isinstance(sh_val, bytes)
                            else str(sh_val)
                        )
                        sh_hex = decode_hap_setup_hash(sh_val)
                        print(f"    - Setup Hash (sh): {sh_b64_str}")
                        if sh_hex:
                            print(f"      * Hex Value: {sh_hex}")
                            print(
                                f"      * Purpose: Hash derived from Setup ID and Device ID for pairing verification"
                            )

                    # Print any vendor-specific or other metadata
                    standard_fields = {
                        "id",
                        "md",
                        "pv",
                        "ci",
                        "c#",
                        "s#",
                        "sf",
                        "ff",
                        "sh",
                    }
                    other_fields = {
                        k: v for k, v in props.items() if k not in standard_fields
                    }
                    if other_fields:
                        print("\n  Additional Metadata:")
                        for key, val in other_fields.items():
                            val_str = (
                                val.decode("utf-8", errors="ignore")
                                if isinstance(val, bytes)
                                else val
                            )
                            print(f"    - {key}: {val_str}")
                elif is_matter_scope:
                    props = {k.decode("utf-8"): v for k,
                             v in info.properties.items()}
                    is_commissionable = type_ == "_matterc._udp.local."
                    scope_name = (
                        "Matter Commissionable (Pairing Mode)"
                        if is_commissionable
                        else "Matter Operational"
                    )
                    print(f"\n  {scope_name} Attributes:")

                    # TXT Record Version (txtvers)
                    if "txtvers" in props:
                        txtvers_val = props["txtvers"]
                        txtvers_str = (
                            txtvers_val.decode("utf-8")
                            if isinstance(txtvers_val, bytes)
                            else str(txtvers_val)
                        )
                        print(
                            f"    - TXT Record Version (txtvers): {txtvers_str}")

                    # Vendor Product (VP) - VendorID+ProductID
                    if "VP" in props:
                        vendor_id, product_id, vp_str = parse_matter_vp(
                            props["VP"])
                        print(f"    - Vendor Product (VP): {vp_str}")
                        if vendor_id is not None and product_id is not None:
                            print(f"      * Vendor ID: {vendor_id}")
                            print(f"      * Product ID: {product_id}")

                    # Device Type (DT)
                    if "DT" in props:
                        dt_val = props["DT"]
                        dt_str = (
                            dt_val.decode("utf-8")
                            if isinstance(dt_val, bytes)
                            else str(dt_val)
                        )
                        dt_name = get_matter_device_type_name(dt_str)
                        print(f"    - Device Type (DT): {dt_str} ({dt_name})")

                    # Device Name (DN)
                    if "DN" in props:
                        dn_val = props["DN"]
                        dn_str = (
                            dn_val.decode("utf-8")
                            if isinstance(dn_val, bytes)
                            else dn_val
                        )
                        print(f"    - Device Name (DN): {dn_str}")

                    # Rotating Identifier (RI) - Privacy protection
                    if "RI" in props:
                        ri_val = props["RI"]
                        ri_str = (
                            ri_val.decode("utf-8")
                            if isinstance(ri_val, bytes)
                            else ri_val
                        )
                        print(f"    - Rotating Identifier (RI): {ri_str}")

                    # Product Identifier (PI) - Optional vendor-specific
                    if "PI" in props:
                        pi_val = props["PI"]
                        pi_str = (
                            pi_val.decode("utf-8")
                            if isinstance(pi_val, bytes)
                            else pi_val
                        )
                        print(f"    - Product Identifier (PI): {pi_str}")

                    # Commissioning Data (CD)
                    if "CD" in props:
                        cd_val = props["CD"]
                        cd_str = (
                            cd_val.decode("utf-8")
                            if isinstance(cd_val, bytes)
                            else str(cd_val)
                        )
                        cd_bits = decode_matter_commissioning_data(cd_str)
                        print(f"    - Commissioning Data (CD): {cd_str}")
                        if cd_bits:
                            print(
                                f"      * Status: {format_matter_commissioning_data(cd_bits)}"
                            )

                    # Discriminator (D) - 12-bit value for differentiating devices during commissioning
                    if "D" in props:
                        d_val = props["D"]
                        d_str = (
                            d_val.decode("utf-8")
                            if isinstance(d_val, bytes)
                            else str(d_val)
                        )
                        try:
                            d_int = int(d_str)
                            d_hex = format(d_int, "03x")  # 12-bit value
                            print(
                                f"    - Discriminator (D): {d_str} (0x{d_hex})")
                        except ValueError:
                            print(f"    - Discriminator (D): {d_str}")

                    # Pairing Hint (PH) - Commissionable only
                    if "PH" in props:
                        ph_val = props["PH"]
                        ph_str = (
                            ph_val.decode("utf-8")
                            if isinstance(ph_val, bytes)
                            else str(ph_val)
                        )
                        ph_desc = get_pairing_hint_description(ph_str)
                        print(f"    - Pairing Hint (PH): {ph_str}")
                        print(f"      * Description: {ph_desc}")

                    # Pairing Instruction (PI) - Commissionable only, replaces Product ID
                    if "PI" in props and is_commissionable:
                        pi_val = props["PI"]
                        pi_str = (
                            pi_val.decode("utf-8")
                            if isinstance(pi_val, bytes)
                            else pi_val
                        )
                        print(f"    - Pairing Instruction (PI): {pi_str}")

                    # Fabric ID (Operational only)
                    if "FabricID" in props:
                        fabric_val = props["FabricID"]
                        fabric_str = (
                            fabric_val.decode("utf-8")
                            if isinstance(fabric_val, bytes)
                            else fabric_val
                        )
                        print(f"    - Fabric ID: {fabric_str}")
                    else:
                        # Fallback: Extract from service instance name
                        fabric_id_hex, node_id_hex, fabric_id_dec, node_id_dec = (
                            parse_fabric_and_node_ids_from_name(name)
                        )
                        if fabric_id_hex:
                            print(
                                f"    - Fabric ID (from name): {fabric_id_hex}")
                            if fabric_id_dec is not None:
                                print(f"      * Decimal: {fabric_id_dec}")

                    # Node ID (Operational only)
                    if "NodeID" in props:
                        node_val = props["NodeID"]
                        node_str = (
                            node_val.decode("utf-8")
                            if isinstance(node_val, bytes)
                            else node_val
                        )
                        print(f"    - Node ID: {node_str}")
                    else:
                        # Fallback: Extract from service instance name
                        fabric_id_hex, node_id_hex, fabric_id_dec, node_id_dec = (
                            parse_fabric_and_node_ids_from_name(name)
                        )
                        if node_id_hex:
                            print(f"    - Node ID (from name): {node_id_hex}")
                            if node_id_dec is not None:
                                print(f"      * Decimal: {node_id_dec}")

                    # Sleepy Idle Interval (SII) - Optional, for sleepy end devices
                    if "SII" in props:
                        sii_val = props["SII"]
                        sii_str = (
                            sii_val.decode("utf-8")
                            if isinstance(sii_val, bytes)
                            else str(sii_val)
                        )
                        try:
                            sii_ms = int(sii_str)
                            sii_sec = sii_ms / 1000.0
                            print(
                                f"    - Sleepy Idle Interval (SII): {sii_str}ms ({sii_sec:.1f}s)"
                            )
                        except ValueError:
                            print(
                                f"    - Sleepy Idle Interval (SII): {sii_str}")

                    # Sleepy Active Interval (SAI) - Optional, for sleepy end devices
                    if "SAI" in props:
                        sai_val = props["SAI"]
                        sai_str = (
                            sai_val.decode("utf-8")
                            if isinstance(sai_val, bytes)
                            else str(sai_val)
                        )
                        try:
                            sai_ms = int(sai_str)
                            sai_sec = sai_ms / 1000.0
                            print(
                                f"    - Sleepy Active Interval (SAI): {sai_str}ms ({sai_sec:.1f}s)"
                            )
                        except ValueError:
                            print(
                                f"    - Sleepy Active Interval (SAI): {sai_str}")

                    # Sleepy Active Threshold (SAT) - Optional, for sleepy end devices
                    if "SAT" in props:
                        sat_val = props["SAT"]
                        sat_str = (
                            sat_val.decode("utf-8")
                            if isinstance(sat_val, bytes)
                            else str(sat_val)
                        )
                        try:
                            sat_ms = int(sat_str)
                            sat_sec = sat_ms / 1000.0
                            print(
                                f"    - Sleepy Active Threshold (SAT): {sat_str}ms ({sat_sec:.1f}s)"
                            )
                        except ValueError:
                            print(
                                f"    - Sleepy Active Threshold (SAT): {sat_str}")

                    # TCP Support (T) - Optional flag for Matter-over-TCP support
                    if "T" in props:
                        t_val = props["T"]
                        t_str = (
                            t_val.decode("utf-8")
                            if isinstance(t_val, bytes)
                            else str(t_val)
                        )
                        tcp_support = decode_matter_tcp_support(t_str)
                        if tcp_support is not None:
                            print(
                                f"    - TCP Support (T): {t_str} ({'Supported' if tcp_support else 'Not Supported'})"
                            )
                        else:
                            print(f"    - TCP Support (T): {t_str}")

                    # ICD (Intermittently Connected Device) - Power management capability
                    if "ICD" in props:
                        icd_val = props["ICD"]
                        icd_str = (
                            icd_val.decode("utf-8")
                            if isinstance(icd_val, bytes)
                            else str(icd_val)
                        )
                        icd_desc = decode_matter_icd_capability(icd_val)
                        print(
                            f"    - Intermittently Connected Device (ICD): {icd_str}")
                        if icd_desc:
                            print(f"      * Description: {icd_desc}")

                    # Print any additional metadata
                    standard_fields = {
                        "txtvers",
                        "VP",
                        "DT",
                        "DN",
                        "RI",
                        "PI",
                        "CD",
                        "D",
                        "FabricID",
                        "NodeID",
                        "SII",
                        "SAI",
                        "SAT",
                        "T",
                        "PH",
                        "ICD",
                    }
                    other_fields = {
                        k: v for k, v in props.items() if k not in standard_fields
                    }
                    if other_fields:
                        print("\n  Additional Metadata:")
                        for key, val in other_fields.items():
                            val_str = (
                                val.decode("utf-8", errors="ignore")
                                if isinstance(val, bytes)
                                else val
                            )
                            print(f"    - {key}: {val_str}")
                else:
                    # For non-Thread BR, non-HAP, and non-Matter scopes, print all TXT records
                    print("  TXT Records:")
                    for key, value in info.properties.items():
                        # Decode bytes to string if possible
                        val_str = (
                            value.decode(
                                "utf-8") if isinstance(value, bytes) else value
                        )
                        print(
                            f"    - {key.decode('utf-8') if isinstance(key, bytes) else key}: {val_str}"
                        )


def main(argv: Sequence[str] | None = None) -> int:

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="Browse Thread-related mDNS scopes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""scope argument:
  (none)   browse all thread scopes (default)
  thread   browse Thread-related scopes (_meshcop._udp, _trel._udp, _hap._udp, _matterc._udp, _matter._tcp)
  br       browse Thread Border Router scopes (_meshcop._udp, _trel._udp)
  hap      browse Apple HomeKit HAP scopes (_hap._udp)
  matter   browse Matter scopes (_matter._tcp, _matterc._udp)

options:
  --haptcp   Also browse _hap._tcp.local. (Wi-Fi HomeKit accessories).
             Applies when scope is 'all' or 'hap'. Off by default.""",
    )

    parser.add_argument(
        "scope",
        nargs="?",
        choices=["thread", "br", "hap", "matter"],
        default="thread",
        help="Scope filter: thread | br | hap | matter  (default: thread scopes)",
    )
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    parser.add_argument(
        "--browse-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=f"Seconds of idle time before auto-exit (default: {TD_MDNS_BROWSE_TIMEOUT_DEFAULT_VALUE}, or {TD_MDNS_BROWSE_TIMEOUT_ENV_NAME} env var)",
    )
    parser.add_argument(
        "--haptcp",
        action="store_true",
        default=False,
        help="Also browse _hap._tcp.local. (Wi-Fi HomeKit accessories). "
        "Applies when scope is 'thread' or 'hap'. Off by default.",
    )
    parser.add_argument(
        "--mattertcpsupported",
        action="store_true",
        default=False,
        help="Include _matter._tcp records where T=1 (TCP supported). "
        "By default those records are excluded.",
    )
    args = parser.parse_args(argv)
    td_data_dir = resolve_data_dir(data_dir=args.datadir)

    scopes_all = [
        "_meshcop._udp.local.",
        "_trel._udp.local.",
        "_hap._udp.local.",
        "_matterc._udp.local.",
        "_matter._tcp.local.",
    ]

    scopes_br = ["_meshcop._udp.local.", "_trel._udp.local."]

    scopes_apple_hap = ["_hap._udp.local."]

    scopes_matter = ["_matterc._udp.local.", "_matter._tcp.local."]

    scope_map = {
        None: (scopes_all, "thread"),
        "thread": (scopes_all, "Thread"),
        "br": (scopes_br, "Thread Border Router"),
        "hap": (scopes_apple_hap, "Apple HomeKit HAP"),
        "matter": (scopes_matter, "Matter"),
    }

    selected_scopes, scope_label = scope_map[args.scope]

    # Opt-in: append _hap._tcp.local. (Wi-Fi HomeKit) when --haptcp is set
    if args.haptcp and args.scope in (None, "thread", "hap"):
        if "_hap._tcp.local." not in selected_scopes:
            selected_scopes = selected_scopes + ["_hap._tcp.local."]

    logging.info(
        f"Browsing {scope_label} scopes ({len(selected_scopes)} service type(s))... (Press Ctrl+C to stop)"
    )

    _default_timeout = float(
        os.environ.get(
            TD_MDNS_BROWSE_TIMEOUT_ENV_NAME, str(
                TD_MDNS_BROWSE_TIMEOUT_DEFAULT_VALUE)
        )
    )
    IDLE_TIMEOUT = (
        args.browse_timeout if args.browse_timeout is not None else _default_timeout
    )

   # Main execution:

    # Get network dataset info for reference in parsing and enriching mdns data
    network_dataset_info = util_network.fetch_network_dataset_info()
    omr_ipv6addr_prefix = (
        network_dataset_info["prefix_omr_ipv6addr_prefix"]
        if network_dataset_info and "prefix_omr_ipv6addr_prefix" in network_dataset_info
        else None
    )

    zeroconf = Zeroconf()
    listener = MDNSDumpListener(
        include_matter_tcp_supported=args.mattertcpsupported, omr_ipv6addr_prefix=omr_ipv6addr_prefix)

    # Start browsers for each scope
    browsers = [ServiceBrowser(zeroconf, s, listener) for s in selected_scopes]

    # Monitor in a background thread; signals idle_done when quiet for IDLE_TIMEOUT seconds
    idle_thread = threading.Thread(
        target=listener.wait_for_idle,
        kwargs={"idle_timeout": IDLE_TIMEOUT},
        daemon=True,
    )
    idle_thread.start()

    try:
        logging.info(
            f"Waiting (exits automatically after {int(IDLE_TIMEOUT)}s of no new updates)..."
        )
        listener.idle_done.wait()
    except KeyboardInterrupt:
        pass
    finally:
        logging.info("Stopping...")
        zeroconf.close()

        records = listener.get_records()
        if args.scope is None:
            scope_tag = "thread"
        else:
            scope_tag = args.scope.lower()

        output_file = resolve_data_file_path(
            f"td-mdns-scopes-{scope_tag}.json", td_data_dir
        )
        save_json_atomic(records, output_file, indent=2)

        logging.info(f"Saved {len(records)} mDNS record(s) to {output_file}")
        logging.info(json.dumps(records, indent=2))


if __name__ == "__main__":
    sys.exit(main())
