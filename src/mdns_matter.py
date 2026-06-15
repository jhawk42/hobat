"""mDNS processing for the _matterc._udp.local. and _matter._tcp.local. scopes.

Provides decode/format helpers, TXT field enrichers, and a console print
function for Matter service records discovered by MDNSDumpListener.
"""
import logging

from mdns_thread_util import _base_field_dict


# ---------------------------------------------------------------------------
# Matter Device Type Mapping
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Decode / format helpers
# ---------------------------------------------------------------------------

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
            vp_value.decode("utf-8") if isinstance(vp_value, bytes) else str(vp_value)
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
            "operational": bool(cd_int & (1 << 0)),
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
    """Extract Compressed Fabric ID and Node ID from Matter operational service instance name.

    Format: [Compressed Fabric ID]-[Node ID]._matter._tcp.local.
    Both IDs are 16-character uppercase hex strings (64-bit values).
    Example: 2906C908D115D362-8FC7772401CD0696._matter._tcp.local.

    Note: the leading component is the *Compressed* Fabric ID (HKDF-derived),
    not the raw Matter Fabric ID.
    """
    try:
        # Strip trailing dot then service suffix (handle both with and without trailing dot)
        instance_name = service_name.rstrip(".")
        for suffix in ("._matter._tcp.local", "._matterc._udp.local"):
            if instance_name.endswith(suffix):
                instance_name = instance_name[: -len(suffix)]
                break

        if "-" in instance_name:
            parts = instance_name.split("-", 1)
            compressed_fabric_id_hex = parts[0]
            node_id_hex = parts[1]

            try:
                compressed_fabric_id_decimal = int(compressed_fabric_id_hex, 16)
                node_id_decimal = int(node_id_hex, 16)
                return (
                    compressed_fabric_id_hex,
                    node_id_hex,
                    compressed_fabric_id_decimal,
                    node_id_decimal,
                )
            except ValueError:
                return compressed_fabric_id_hex, node_id_hex, None, None

        return None, None, None, None
    except Exception:
        return None, None, None, None


# ---------------------------------------------------------------------------
# Per-field enricher functions (Matter scope)
# ---------------------------------------------------------------------------

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
# Console print helper for Matter scope
# ---------------------------------------------------------------------------

_MATTER_STANDARD_FIELDS = {
    "txtvers", "VP", "DT", "DN", "RI", "PI", "CD", "D",
    "FabricID", "FabricID_compressed", "NodeID", "SII", "SAI", "SAT", "T", "PH", "ICD",
}


def print_matter_service_info(name: str, type_: str, info, props: dict) -> None:
    """Print a human-readable summary of a Matter service record."""
    is_commissionable = type_ == "_matterc._udp.local."
    scope_name = (
        "Matter Commissionable (Pairing Mode)"
        if is_commissionable
        else "Matter Operational"
    )
    logging.debug("\n  %s Attributes:", scope_name)

    # TXT Record Version (txtvers)
    if "txtvers" in props:
        txtvers_val = props["txtvers"]
        txtvers_str = (
            txtvers_val.decode("utf-8")
            if isinstance(txtvers_val, bytes)
            else str(txtvers_val)
        )
        logging.debug("    - TXT Record Version (txtvers): %s", txtvers_str)

    # Vendor Product (VP) - VendorID+ProductID
    if "VP" in props:
        vendor_id, product_id, vp_str = parse_matter_vp(props["VP"])
        logging.debug("    - Vendor Product (VP): %s", vp_str)
        if vendor_id is not None and product_id is not None:
            logging.debug("      * Vendor ID: %s", vendor_id)
            logging.debug("      * Product ID: %s", product_id)

    # Device Type (DT)
    if "DT" in props:
        dt_val = props["DT"]
        dt_str = (
            dt_val.decode("utf-8") if isinstance(dt_val, bytes) else str(dt_val)
        )
        dt_name = get_matter_device_type_name(dt_str)
        logging.debug("    - Device Type (DT): %s (%s)", dt_str, dt_name)

    # Device Name (DN)
    if "DN" in props:
        dn_val = props["DN"]
        dn_str = (
            dn_val.decode("utf-8") if isinstance(dn_val, bytes) else dn_val
        )
        logging.debug("    - Device Name (DN): %s", dn_str)

    # Rotating Identifier (RI) - Privacy protection
    if "RI" in props:
        ri_val = props["RI"]
        ri_str = (
            ri_val.decode("utf-8") if isinstance(ri_val, bytes) else ri_val
        )
        logging.debug("    - Rotating Identifier (RI): %s", ri_str)

    # Product Identifier (PI) - Optional vendor-specific
    if "PI" in props:
        pi_val = props["PI"]
        pi_str = (
            pi_val.decode("utf-8") if isinstance(pi_val, bytes) else pi_val
        )
        logging.debug("    - Product Identifier (PI): %s", pi_str)

    # Commissioning Data (CD)
    if "CD" in props:
        cd_val = props["CD"]
        cd_str = (
            cd_val.decode("utf-8") if isinstance(cd_val, bytes) else str(cd_val)
        )
        cd_bits = decode_matter_commissioning_data(cd_str)
        logging.debug("    - Commissioning Data (CD): %s", cd_str)
        if cd_bits:
            logging.debug("      * Status: %s", format_matter_commissioning_data(cd_bits))

    # Discriminator (D) - 12-bit value for differentiating devices during commissioning
    if "D" in props:
        d_val = props["D"]
        d_str = (
            d_val.decode("utf-8") if isinstance(d_val, bytes) else str(d_val)
        )
        try:
            d_int = int(d_str)
            d_hex = format(d_int, "03x")
            logging.debug("    - Discriminator (D): %s (0x%s)", d_str, d_hex)
        except ValueError:
            logging.debug("    - Discriminator (D): %s", d_str)

    # Pairing Hint (PH) - Commissionable only
    if "PH" in props:
        ph_val = props["PH"]
        ph_str = (
            ph_val.decode("utf-8") if isinstance(ph_val, bytes) else str(ph_val)
        )
        ph_desc = get_pairing_hint_description(ph_str)
        logging.debug("    - Pairing Hint (PH): %s", ph_str)
        logging.debug("      * Description: %s", ph_desc)

    # Pairing Instruction (PI) - Commissionable only, replaces Product ID
    if "PI" in props and is_commissionable:
        pi_val = props["PI"]
        pi_str = (
            pi_val.decode("utf-8") if isinstance(pi_val, bytes) else pi_val
        )
        logging.debug("    - Pairing Instruction (PI): %s", pi_str)

    # Compressed Fabric ID and Node ID (Operational only — encoded in instance name)
    compressed_fabric_id_hex, node_id_hex, compressed_fabric_id_dec, node_id_dec = (
        parse_fabric_and_node_ids_from_name(name)
    )

    # Raw Fabric ID — only present when explicitly carried in TXT props (rare)
    if "FabricID" in props:
        fabric_val = props["FabricID"]
        fabric_str = (
            fabric_val.decode("utf-8") if isinstance(fabric_val, bytes) else fabric_val
        )
        logging.debug("    - Fabric ID (raw): %s", fabric_str)

    # Compressed Fabric ID — derived via HKDF from RootPublicKey + FabricID;
    # always present for operational records, encoded as the first 16 hex chars
    # of the instance name: <CompressedFabricID>-<NodeID>._matter._tcp.local.
    if "FabricID_compressed" in props:
        cfid_val = props["FabricID_compressed"]
        cfid_str = (
            cfid_val.decode("utf-8") if isinstance(cfid_val, bytes) else cfid_val
        )
        logging.debug("    - Compressed Fabric ID (from name): %s", cfid_str)
    elif compressed_fabric_id_hex:
        logging.debug(
            "    - Compressed Fabric ID (from name): %s", compressed_fabric_id_hex
        )
        if compressed_fabric_id_dec is not None:
            logging.debug("      * Decimal: %s", compressed_fabric_id_dec)

    # Node ID (Operational only)
    if "NodeID" in props:
        node_val = props["NodeID"]
        node_str = (
            node_val.decode("utf-8") if isinstance(node_val, bytes) else node_val
        )
        logging.debug("    - Node ID: %s", node_str)
    elif node_id_hex:
        logging.debug("    - Node ID (from name): %s", node_id_hex)
        if node_id_dec is not None:
            logging.debug("      * Decimal: %s", node_id_dec)

    # Sleepy Idle Interval (SII) - Optional, for sleepy end devices
    if "SII" in props:
        sii_val = props["SII"]
        sii_str = (
            sii_val.decode("utf-8") if isinstance(sii_val, bytes) else str(sii_val)
        )
        try:
            sii_ms = int(sii_str)
            sii_sec = sii_ms / 1000.0
            logging.debug(
                "    - Sleepy Idle Interval (SII): %sms (%.1fs)", sii_str, sii_sec
            )
        except ValueError:
            logging.debug("    - Sleepy Idle Interval (SII): %s", sii_str)

    # Sleepy Active Interval (SAI) - Optional, for sleepy end devices
    if "SAI" in props:
        sai_val = props["SAI"]
        sai_str = (
            sai_val.decode("utf-8") if isinstance(sai_val, bytes) else str(sai_val)
        )
        try:
            sai_ms = int(sai_str)
            sai_sec = sai_ms / 1000.0
            logging.debug(
                "    - Sleepy Active Interval (SAI): %sms (%.1fs)", sai_str, sai_sec
            )
        except ValueError:
            logging.debug("    - Sleepy Active Interval (SAI): %s", sai_str)

    # Sleepy Active Threshold (SAT) - Optional, for sleepy end devices
    if "SAT" in props:
        sat_val = props["SAT"]
        sat_str = (
            sat_val.decode("utf-8") if isinstance(sat_val, bytes) else str(sat_val)
        )
        try:
            sat_ms = int(sat_str)
            sat_sec = sat_ms / 1000.0
            logging.debug(
                "    - Sleepy Active Threshold (SAT): %sms (%.1fs)", sat_str, sat_sec
            )
        except ValueError:
            logging.debug("    - Sleepy Active Threshold (SAT): %s", sat_str)

    # TCP Support (T) - Optional flag for Matter-over-TCP support
    if "T" in props:
        t_val = props["T"]
        t_str = (
            t_val.decode("utf-8") if isinstance(t_val, bytes) else str(t_val)
        )
        tcp_support = decode_matter_tcp_support(t_str)
        if tcp_support is not None:
            logging.debug(
                "    - TCP Support (T): %s (%s)",
                t_str,
                "Supported" if tcp_support else "Not Supported",
            )
        else:
            logging.debug("    - TCP Support (T): %s", t_str)

    # ICD (Intermittently Connected Device) - Power management capability
    if "ICD" in props:
        icd_val = props["ICD"]
        icd_str = (
            icd_val.decode("utf-8") if isinstance(icd_val, bytes) else str(icd_val)
        )
        icd_desc = decode_matter_icd_capability(icd_val)
        logging.debug("    - Intermittently Connected Device (ICD): %s", icd_str)
        if icd_desc:
            logging.debug("      * Description: %s", icd_desc)

    other_fields = {k: v for k, v in props.items() if k not in _MATTER_STANDARD_FIELDS}
    if other_fields:
        logging.debug("\n  Additional Metadata:")
        for key, val in other_fields.items():
            val_str = (
                val.decode("utf-8", errors="ignore") if isinstance(val, bytes) else val
            )
            logging.debug("    - %s: %s", key, val_str)
