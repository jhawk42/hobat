VENDOR_OUI = {
    "0017f2": "Apple",
    "d828c9": "Google (Nest)",
    "f0d1a9": "Amazon/Eero",
    "44d832": "Nanoleaf",
    "00124b": "Texas Instruments"
}

# Backward-compatible alias
XA_VENDORS = VENDOR_OUI


def get_vendor_from_extaddr(extaddr_hex: str) -> str:
    """Look up vendor name from the first 3 bytes (OUI) of an extended address."""
    oui = extaddr_hex[:6].lower()
    return VENDOR_OUI.get(oui, "Unknown Vendor")


# Backward-compatible alias
get_vendor_from_xa = get_vendor_from_extaddr
