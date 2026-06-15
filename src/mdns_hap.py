"""mDNS processing for the _hap._udp.local. (HomeKit Accessory Protocol) scope.

Provides decode/format helpers, TXT field enrichers, and a console print
function for HAP service records discovered by MDNSDumpListener.
"""
import base64
import logging
import socket

from mdns_thread_util import _base_field_dict


# ---------------------------------------------------------------------------
# HAP Category Mapping
# Source: Apple HomeKit Developer Documentation
# https://developer.apple.com/documentation/homekit
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Decode / format helpers
# ---------------------------------------------------------------------------

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
            else "Paired",
            "ip_networking_enabled": not bool(sf_int & (1 << 1)),
            "problem_detected": bool(sf_int & (1 << 2)),
            "reserved_bits": (sf_int >> 3) & 0x1F,
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
            "supports_hap_over_coap": bool(ff_int & (1 << 0)),
            "supports_wifi_throughput": bool(ff_int & (1 << 1)),
            "supports_matter_bridge": bool(ff_int & (1 << 2)),
            "supports_hap_over_ble": bool(ff_int & (1 << 3)),
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


def decode_hap_setup_hash(sh_value):
    """Decode HAP Setup Hash (sh) field from Base64 to hex bytes"""
    try:
        sh_b64 = (
            sh_value.decode("utf-8") if isinstance(sh_value, bytes) else str(sh_value)
        )
        hash_bytes = base64.b64decode(sh_b64)
        hash_hex = hash_bytes.hex().upper()
        return hash_hex
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-field enricher functions (HAP scope)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Console print helper for HAP scope
# ---------------------------------------------------------------------------

_HAP_STANDARD_FIELDS = {"id", "md", "pv", "ci", "c#", "s#", "sf", "ff", "sh"}


def print_hap_service_info(name: str, info, props: dict) -> None:
    """Print a human-readable summary of a _hap._udp.local. service record."""
    logging.debug("\n  HomeKit Accessory Protocol (HAP) Attributes:")

    # Device ID (id) - Mandatory
    if "id" in props:
        id_val = props["id"]
        id_str = (
            id_val.decode("utf-8") if isinstance(id_val, bytes) else id_val
        )
        logging.debug("    - Device ID (id): %s", id_str)

    # Model Name (md) - Mandatory
    if "md" in props:
        md_val = props["md"]
        md_str = (
            md_val.decode("utf-8") if isinstance(md_val, bytes) else md_val
        )
        logging.debug("    - Model Name (md): %s", md_str)

    # Protocol Version (pv) - Mandatory
    if "pv" in props:
        pv_val = props["pv"]
        pv_str = (
            pv_val.decode("utf-8") if isinstance(pv_val, bytes) else pv_val
        )
        logging.debug("    - Protocol Version (pv): %s", pv_str)

    # Category Identifier (ci) - Mandatory
    if "ci" in props:
        ci_val = props["ci"]
        ci_str = (
            ci_val.decode("utf-8") if isinstance(ci_val, bytes) else str(ci_val)
        )
        ci_name = get_hap_category_name(ci_str)
        logging.debug("    - Category Identifier (ci): %s (%s)", ci_str, ci_name)

    # Configuration Number (c#) - Mandatory
    if "c#" in props:
        c_hash_val = props["c#"]
        c_hash_str = (
            c_hash_val.decode("utf-8")
            if isinstance(c_hash_val, bytes)
            else str(c_hash_val)
        )
        logging.debug("    - Configuration Number (c#): %s", c_hash_str)

    # State Number (s#) - Mandatory
    if "s#" in props:
        s_hash_val = props["s#"]
        s_hash_str = (
            s_hash_val.decode("utf-8")
            if isinstance(s_hash_val, bytes)
            else str(s_hash_val)
        )
        logging.debug("    - State Number (s#): %s", s_hash_str)

    # Status Flags (sf) - Mandatory
    if "sf" in props:
        sf_val = props["sf"]
        sf_str = (
            sf_val.decode("utf-8") if isinstance(sf_val, bytes) else str(sf_val)
        )
        sf_bits = decode_hap_status_flags(sf_str)
        logging.debug("    - Status Flags (sf): %s", sf_str)
        if sf_bits:
            logging.debug("      * %s", format_hap_status_flags(sf_bits))
            logging.debug("      * Individual Bits:")
            logging.debug("        - Bit 0 (Pairing Status): %s", sf_bits["pairing_status"])
            logging.debug(
                "        - Bit 1 (IP Networking): %s",
                "Enabled" if sf_bits["ip_networking_enabled"] else "Disabled",
            )
            logging.debug(
                "        - Bit 2 (Problem Detected): %s",
                "Yes" if sf_bits["problem_detected"] else "No",
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
        logging.debug("    - Feature Flags (ff): %s", ff_int)
        if ff_bits:
            logging.debug("      * Supported Features: %s", format_hap_feature_flags(ff_bits))

    # Setup Hash (sh) - Optional, Base64-encoded 4-byte hash
    if "sh" in props:
        sh_val = props["sh"]
        sh_b64_str = (
            sh_val.decode("utf-8") if isinstance(sh_val, bytes) else str(sh_val)
        )
        sh_hex = decode_hap_setup_hash(sh_val)
        logging.debug("    - Setup Hash (sh): %s", sh_b64_str)
        if sh_hex:
            logging.debug("      * Hex Value: %s", sh_hex)
            logging.debug(
                "      * Purpose: Hash derived from Setup ID and Device ID for pairing verification"
            )

    other_fields = {k: v for k, v in props.items() if k not in _HAP_STANDARD_FIELDS}
    if other_fields:
        logging.debug("\n  Additional Metadata:")
        for key, val in other_fields.items():
            val_str = (
                val.decode("utf-8", errors="ignore") if isinstance(val, bytes) else val
            )
            logging.debug("    - %s: %s", key, val_str)
