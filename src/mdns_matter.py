"""mDNS processing for the _matterc._udp.local. and _matter._tcp.local. scopes.

Provides decode/format helpers, TXT field enrichers, and a console print
function for Matter service records discovered by MDNSDumpListener.
"""
from dataclasses import dataclass
import logging
from typing import Any, Callable, Literal

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


MATTER_FIELD_ENRICHERS = {
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


# ---------------------------------------------------------------------------
# Console print helper for Matter scope
# ---------------------------------------------------------------------------

MatterApplicability = Literal["commissionable", "operational", "both"]


@dataclass(frozen=True)
class MatterFieldDescriptor:
    txt_key: str
    label: str
    applicability: MatterApplicability
    decoder: Callable[[Any], Any]
    formatter: Callable[[str, Any], tuple[str, str]]
    detail_renderer: Callable[[Any], tuple[str, ...]] | None = None


@dataclass(frozen=True)
class _MatterIdentifier:
    value: str
    from_name: bool = False
    decimal: int | None = None


def _decode_text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _decode_vendor_product(value: Any) -> tuple[int | None, int | None, str]:
    return parse_matter_vp(value)


def _decode_device_type(value: Any) -> tuple[str, str]:
    text = _decode_text(value)
    return text, get_matter_device_type_name(text)


def _decode_commissioning(value: Any) -> tuple[str, dict | None]:
    text = _decode_text(value)
    return text, decode_matter_commissioning_data(text)


def _decode_discriminator(value: Any) -> tuple[str, str | None]:
    text = _decode_text(value)
    try:
        return text, f"0x{format(int(text), '03x')}"
    except ValueError:
        return text, None


def _decode_pairing_hint(value: Any) -> tuple[str, str]:
    text = _decode_text(value)
    return text, get_pairing_hint_description(text)


def _decode_interval(value: Any) -> tuple[str, float | None]:
    text = _decode_text(value)
    try:
        return text, int(text) / 1000.0
    except ValueError:
        return text, None


def _decode_tcp(value: Any) -> tuple[str, bool | None]:
    text = _decode_text(value)
    return text, decode_matter_tcp_support(text)


def _decode_icd(value: Any) -> tuple[str, str | None]:
    return _decode_text(value), decode_matter_icd_capability(value)


def _decode_identifier(value: Any) -> _MatterIdentifier:
    if isinstance(value, _MatterIdentifier):
        return value
    return _MatterIdentifier(_decode_text(value))


def _format_text(label: str, value: str) -> tuple[str, str]:
    return label, value


def _format_vendor_product(
    label: str, value: tuple[int | None, int | None, str]
) -> tuple[str, str]:
    return label, value[2]


def _format_primary(label: str, value: tuple[str, Any]) -> tuple[str, str]:
    return label, value[0]


def _format_parenthetical(
    label: str, value: tuple[str, str | None]
) -> tuple[str, str]:
    text, detail = value
    return label, f"{text} ({detail})" if detail is not None else text


def _format_interval(label: str, value: tuple[str, float | None]) -> tuple[str, str]:
    text, seconds = value
    if seconds is None:
        return label, text
    return label, f"{text}ms ({seconds:.1f}s)"


def _format_tcp(label: str, value: tuple[str, bool | None]) -> tuple[str, str]:
    text, supported = value
    if supported is None:
        return label, text
    status = "Supported" if supported else "Not Supported"
    return label, f"{text} ({status})"


def _format_identifier(
    label: str, identifier: _MatterIdentifier
) -> tuple[str, str]:
    if identifier.from_name and label == "Node ID":
        label = "Node ID (from name)"
    return label, identifier.value


def _vendor_product_details(
    value: tuple[int | None, int | None, str]
) -> tuple[str, ...]:
    vendor_id, product_id, _ = value
    if vendor_id is None or product_id is None:
        return ()
    return f"Vendor ID: {vendor_id}", f"Product ID: {product_id}"


def _commissioning_details(value: tuple[str, dict | None]) -> tuple[str, ...]:
    bits = value[1]
    return (f"Status: {format_matter_commissioning_data(bits)}",) if bits else ()


def _pairing_hint_details(value: tuple[str, str]) -> tuple[str, ...]:
    return (f"Description: {value[1]}",)


def _icd_details(value: tuple[str, str | None]) -> tuple[str, ...]:
    return (f"Description: {value[1]}",) if value[1] else ()


def _identifier_details(identifier: _MatterIdentifier) -> tuple[str, ...]:
    if identifier.from_name and identifier.decimal is not None:
        return (f"Decimal: {identifier.decimal}",)
    return ()


MATTER_PRESENTATION_DESCRIPTORS = (
    MatterFieldDescriptor("txtvers", "TXT Record Version (txtvers)", "both", _decode_text, _format_text),
    MatterFieldDescriptor("VP", "Vendor Product (VP)", "both", _decode_vendor_product, _format_vendor_product, _vendor_product_details),
    MatterFieldDescriptor("DT", "Device Type (DT)", "both", _decode_device_type, _format_parenthetical),
    MatterFieldDescriptor("DN", "Device Name (DN)", "both", _decode_text, _format_text),
    MatterFieldDescriptor("RI", "Rotating Identifier (RI)", "both", _decode_text, _format_text),
    MatterFieldDescriptor("PI", "Product Identifier (PI)", "both", _decode_text, _format_text),
    MatterFieldDescriptor("CD", "Commissioning Data (CD)", "both", _decode_commissioning, _format_primary, _commissioning_details),
    MatterFieldDescriptor("D", "Discriminator (D)", "both", _decode_discriminator, _format_parenthetical),
    MatterFieldDescriptor("PH", "Pairing Hint (PH)", "both", _decode_pairing_hint, _format_primary, _pairing_hint_details),
    MatterFieldDescriptor("PI", "Pairing Instruction (PI)", "commissionable", _decode_text, _format_text),
    MatterFieldDescriptor("FabricID", "Fabric ID (raw)", "both", _decode_text, _format_text),
    MatterFieldDescriptor("FabricID_compressed", "Compressed Fabric ID (from name)", "both", _decode_identifier, _format_identifier, _identifier_details),
    MatterFieldDescriptor("NodeID", "Node ID", "both", _decode_identifier, _format_identifier, _identifier_details),
    MatterFieldDescriptor("SII", "Sleepy Idle Interval (SII)", "both", _decode_interval, _format_interval),
    MatterFieldDescriptor("SAI", "Sleepy Active Interval (SAI)", "both", _decode_interval, _format_interval),
    MatterFieldDescriptor("SAT", "Sleepy Active Threshold (SAT)", "both", _decode_interval, _format_interval),
    MatterFieldDescriptor("T", "TCP Support (T)", "both", _decode_tcp, _format_tcp),
    MatterFieldDescriptor("ICD", "Intermittently Connected Device (ICD)", "both", _decode_icd, _format_primary, _icd_details),
)


def _validate_presentation_descriptors(
    descriptors: tuple[MatterFieldDescriptor, ...],
) -> None:
    registrations = set()
    for descriptor in descriptors:
        registration = (descriptor.txt_key, descriptor.applicability)
        if registration in registrations:
            raise ValueError(
                f"Duplicate Matter presentation descriptor: {descriptor.txt_key} "
                f"({descriptor.applicability})"
            )
        registrations.add(registration)
        if descriptor.applicability not in {"commissionable", "operational", "both"}:
            raise ValueError(
                f"Invalid Matter descriptor applicability: {descriptor.applicability}"
            )
        for callback in (descriptor.decoder, descriptor.formatter):
            if not callable(callback):
                raise TypeError(
                    f"Matter presentation callback for {descriptor.txt_key} must be callable"
                )
        if descriptor.detail_renderer is not None and not callable(
            descriptor.detail_renderer
        ):
            raise TypeError(
                f"Matter detail renderer for {descriptor.txt_key} must be callable"
            )


_validate_presentation_descriptors(MATTER_PRESENTATION_DESCRIPTORS)

_MATTER_STANDARD_FIELDS = {
    descriptor.txt_key for descriptor in MATTER_PRESENTATION_DESCRIPTORS
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

    presentation_props = dict(props)
    compressed_hex, node_hex, compressed_decimal, node_decimal = (
        parse_fabric_and_node_ids_from_name(name)
    )
    if "FabricID_compressed" not in presentation_props and compressed_hex:
        presentation_props["FabricID_compressed"] = _MatterIdentifier(
            compressed_hex, from_name=True, decimal=compressed_decimal
        )
    if "NodeID" not in presentation_props and node_hex:
        presentation_props["NodeID"] = _MatterIdentifier(
            node_hex, from_name=True, decimal=node_decimal
        )

    applicability = "commissionable" if is_commissionable else "operational"
    for descriptor in MATTER_PRESENTATION_DESCRIPTORS:
        if descriptor.applicability not in {"both", applicability}:
            continue
        if descriptor.txt_key not in presentation_props:
            continue
        decoded = descriptor.decoder(presentation_props[descriptor.txt_key])
        label, value = descriptor.formatter(descriptor.label, decoded)
        logging.debug("    - %s: %s", label, value)
        if descriptor.detail_renderer:
            for detail in descriptor.detail_renderer(decoded):
                logging.debug("      * %s", detail)

    other_fields = {k: v for k, v in props.items() if k not in _MATTER_STANDARD_FIELDS}
    if other_fields:
        logging.debug("\n  Additional Metadata:")
        for key, val in other_fields.items():
            val_str = (
                val.decode("utf-8", errors="ignore") if isinstance(val, bytes) else val
            )
            logging.debug("    - %s: %s", key, val_str)
