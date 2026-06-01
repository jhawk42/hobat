"""Shared utility constants and helpers for mDNS Thread scope processing.

This module provides common building blocks used by the scope-specific modules
(mdns_meshcop, mdns_hap, mdns_matter) and the main listener in
mdns_thread_scopes.
"""
import base64

# ---------------------------------------------------------------------------
# Vendor OUI Lookup Table
# ---------------------------------------------------------------------------
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
