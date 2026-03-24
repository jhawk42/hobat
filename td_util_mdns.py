XA_VENDORS = {
    "0017f2": "Apple",
    "d828c9": "Google (Nest)",
    "f0d1a9": "Amazon/Eero",
    "44d832": "Nanoleaf",
    "00124b": "Texas Instruments"
}

def get_vendor_from_xa(xa_hex):
    # Take first 6 chars (3 bytes) for OUI
    oui = xa_hex[:6].lower()
    return XA_VENDORS.get(oui, "Unknown Vendor")
