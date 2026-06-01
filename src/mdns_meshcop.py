"""mDNS processing for the _meshcop._udp.local. (Thread Border Router) scope.

Provides decode/format helpers, TXT field enrichers, and a console print
function for meshcop service records discovered by MDNSDumpListener.
"""
import socket

from mdns_thread_util import (
    FIELD_METADATA,
    _base_field_dict,
    get_vendor_from_oui,
)


# ---------------------------------------------------------------------------
# Decode / format helpers
# ---------------------------------------------------------------------------

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


def decode_thread_partition_id(pt_value):
    """Decode Thread Partition Identifier (pt) - 32-bit value"""
    try:
        pt_hex = pt_value.hex().upper()
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
        bb_hex = format(bb_int, "04x").upper()  # 32-bit value in hex

        bits = {
            "commissioning_active": bool(bb_int & (1 << 0)),
            "native_commissioner": bool(bb_int & (1 << 1)),
            "eth_interface": bool(bb_int & (1 << 2)),
            "wifi_interface": bool(bb_int & (1 << 3)),
            "thread_interface": bool(bb_int & (1 << 4)),
            "thread_ml_eid": bool(bb_int & (1 << 5)),
            "thread_dua": bool(bb_int & (1 << 6)),
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


# ---------------------------------------------------------------------------
# Per-field enricher functions (meshcop scope)
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


# ---------------------------------------------------------------------------
# Console print helper for meshcop scope
# ---------------------------------------------------------------------------

_MESHCOP_STANDARD_FIELDS = {
    "rv", "vn", "mn", "tv", "nn", "xp", "xa", "dd", "sq",
    "at", "id", "sb", "dt", "pt", "bb", "dn",
}


def print_meshcop_service_info(name: str, info, props: dict) -> None:
    """Print a human-readable summary of a _meshcop._udp.local. service record."""
    print(f"\n[ THREAD BORDER ROUTER FOUND ]")
    print(f"  Instance Name: {name}")
    print(f"  Hostname:      {info.server}")
    print(
        f"  Address:       {socket.inet_ntoa(info.addresses[0]) if info.addresses else 'Unknown'}:{info.port}"
    )

    print("\n  Thread Border Router Identity & Capabilities:")

    if "rv" in props and isinstance(props["rv"], bytes):
        print(f"    - Protocol Revision (rv): {props['rv'].decode('utf-8')}")

    if "vn" in props and isinstance(props["vn"], bytes):
        print(f"    - Vendor Name (vn): {props['vn'].decode('utf-8')}")

    if "mn" in props and isinstance(props["mn"], bytes):
        print(f"    - Model Name (mn): {props['mn'].decode('utf-8')}")

    if "tv" in props and isinstance(props["tv"], bytes):
        print(f"    - Thread Version (tv): {props['tv'].decode('utf-8')}")

    if "nn" in props and isinstance(props["nn"], bytes):
        print(f"    - Network Name (nn): {props['nn'].decode('utf-8')}")

    if "xp" in props and isinstance(props["xp"], bytes):
        xp_hex = props["xp"].hex().upper()
        print(f"    - Extended PAN ID (xp): {xp_hex}")

    if "xa" in props and isinstance(props["xa"], bytes):
        xa_hex = props["xa"].hex().upper()
        print(f"    - Extended Address (xa): {xa_hex}")

    if "dd" in props and isinstance(props["dd"], bytes):
        dd_hex = props["dd"].hex().upper()
        print(f"    - Discriminator ID (dd): {dd_hex}")

    if "sq" in props and isinstance(props["sq"], bytes):
        print(f"    - Sequence Number (sq): {props['sq'].decode('utf-8')}")

    if "at" in props and isinstance(props["at"], bytes):
        at_hex = props["at"].hex().upper()
        oui = at_hex[:6]
        vendor = get_vendor_from_oui(at_hex)
        ext_id = at_hex[6:]
        print(f"    - Extended Address (at): {at_hex}")
        print(f"      * OUI (Vendor): {oui} ({vendor})")
        print(f"      * Extension ID: {ext_id}")

    if "id" in props and isinstance(props["id"], bytes):
        print(f"    - Border Agent ID (id): {props['id'].hex().upper()}")

    if "sb" in props and isinstance(props["sb"], bytes):
        sb_hex = props["sb"].hex().upper()
        sb_bits = decode_state_bitmap_br(sb_hex)
        print(f"    - State Bitmap (sb): {sb_hex}")
        if sb_bits:
            print(f"      * Status: {format_state_bitmap_br(sb_bits)}")
            print(f"      * Individual Bits:")
            print(f"        - Bit 0 (Connection Allowed): {sb_bits['connection_allowed']}")
            print(f"        - Bit 1 (Native Commissioner): {sb_bits['native_commissioner']}")
            print(f"        - Bit 2 (Active Commissioner): {sb_bits['active_commissioner']}")
            print(f"        - Bit 3 (Active Thread Partition): {sb_bits['active_thread_partition']}")
            print(f"        - Bit 4 (Leader Role): {sb_bits['leader_role']}")
            print(f"        - Bit 5 (Backbone Router): {sb_bits['backbone_router']}")

    if "dt" in props and isinstance(props["dt"], bytes):
        print(f"    - Device Type (dt): {props['dt'].decode('utf-8', errors='ignore')}")

    if "pt" in props and isinstance(props["pt"], bytes):
        pt_val = props["pt"]
        pt_int, pt_hex = decode_thread_partition_id(pt_val)
        if pt_int is not None:
            print(f"    - Partition Identifier (pt): {pt_int} (0x{pt_hex})")
        else:
            print(f"    - Partition Identifier (pt): {pt_int}")

    if "bb" in props and isinstance(props["bb"], bytes):
        bb_val = props["bb"]
        bb_str = bb_val.hex().upper()
        bb_int, bb_hex, bb_bits = decode_thread_beacon_bitmap(bb_val)
        if bb_int is not None:
            print(f"    - Beacon Bitmap (bb): {bb_str} (0x{bb_hex})")
            if bb_bits:
                status_str = format_thread_beacon_bitmap(bb_bits)
                print(f"      * Status: {status_str}")
        else:
            print(f"    - Beacon Bitmap (bb): {bb_str}")

    if "dn" in props and isinstance(props["dn"], bytes):
        dn_str = props["dn"].decode("utf-8")
        print(f"    - Domain Name (dn): {dn_str}")

    other_fields = {
        k.decode("utf-8"): v
        for k, v in info.properties.items()
        if k.decode("utf-8") not in _MESHCOP_STANDARD_FIELDS
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
