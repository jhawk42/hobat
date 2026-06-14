#!/usr/bin/env python3
"""Extract Matter and Thread information from Matter node payloads.

Reusable functions in this module are designed to be imported by
`matter_nodes_fetch_all.py`, while preserving a standalone CLI mode.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import re
import sys

from pathlib import Path
from typing import Any

CORE_MATTER_DATA_MODEL_PATHS_MAP = {
    "thread_core_fields": {
        "0/53/0": "channel",
        "0/53/1": "routing_role",
        "0/53/2": "network_name",
        "0/53/3": "pan_id",
        "0/53/4": "extended_pan_id",
        "0/53/7": "rloc16",
    },
    "thread_version_candidates": ("0/53/5", "0/53/6", "0/53/17"),
    "network_interfaces": "0/51/0",
    "matter_device_info": "0/40/5",
    "operational_credentials_fields": {
        "0/62/0": "nocs",
        "0/62/1": "fabrics",
        "0/62/2": "supported_fabrics",
        "0/62/3": "commissioned_fabrics",
        "0/62/4": "trusted_root_certificates",
        "0/62/5": "current_fabric_index",
        "0/62/65528": "generated_command_list",
        "0/62/65529": "accepted_command_list",
        "0/62/65531": "attribute_list",
        "0/62/65532": "feature_map",
        "0/62/65533": "cluster_revision",
    },
    "group_key_management_fields": {
        "0/63/0": "group_key_map",
        "0/63/1": "group_table",
        "0/63/2": "max_groups_per_fabric",
        "0/63/3": "max_group_keys_per_fabric",
        "0/63/65528": "generated_command_list",
        "0/63/65529": "accepted_command_list",
        "0/63/65531": "attribute_list",
        "0/63/65532": "feature_map",
        "0/63/65533": "cluster_revision",
    },
    "neighbor_table_preferred": ("0/53/8",),
    "route_table_preferred": ("0/53/9", "0/53/7"),
    "child_table_preferred": ("0/53/10", "0/53/11", "0/53/12", "0/53/62"),
    "thread_prefix": "0/53/",
    "descriptor_prefix": "0/31/",
}

ROUTING_ROLE_ENUM = {
    0: "Unspecified",
    1: "Unassigned",
    2: "SleepyEndDevice",
    3: "EndDevice",
    4: "REED",
    5: "Router",
    6: "Leader",
}


def parse_dump_file(path: Path) -> list[dict[str, Any]]:
    """Parse nodes from either a legacy websocket text dump or JSON payload file."""

    raw = path.read_text(encoding="utf-8")
    stripped = raw.strip()

    if not stripped:
        return []

    # New JSON file shapes (preferred)
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict):
            if isinstance(obj.get("nodes"), list):
                return [entry for entry in obj["nodes"] if isinstance(entry, dict)]

            if isinstance(obj.get("messages"), list):
                nodes: list[dict[str, Any]] = []
                for msg in obj["messages"]:
                    if isinstance(msg, dict) and isinstance(msg.get("result"), list):
                        for entry in msg["result"]:
                            if isinstance(entry, dict):
                                nodes.append(entry)
                return nodes

            if isinstance(obj.get("result"), list):
                return [entry for entry in obj["result"] if isinstance(entry, dict)]

        if isinstance(obj, list):
            return [entry for entry in obj if isinstance(entry, dict)]
    except json.JSONDecodeError:
        pass

    # Legacy text format from `matter_ws_client.py` printing
    parts = re.split(r"Received from server:\s*", raw)
    nodes: list[dict[str, Any]] = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        try:
            payload = json.loads(part)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Unable to parse JSON object from {path}: {exc}") from exc

        if isinstance(payload, dict) and isinstance(payload.get("result"), list):
            for entry in payload["result"]:
                if isinstance(entry, dict):
                    nodes.append(entry)

    return nodes


def dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[int, dict[str, Any]] = {}
    for node in nodes:
        node_id = node.get("node_id")
        if isinstance(node_id, int):
            unique[node_id] = node

    return [unique[node_id] for node_id in sorted(unique)]


def normalize_base64(text: str) -> str:
    text = text.strip()
    padded_len = (-len(text)) % 4
    if padded_len:
        text += "=" * padded_len
    return text


def decode_base64_bytes(text: str | None) -> bytes | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        return base64.b64decode(normalize_base64(text), validate=False)
    except (ValueError, TypeError):
        return None


def format_hardware_address(value: str | None) -> str | None:
    data = decode_base64_bytes(value)
    if not data:
        return None
    return ":".join(f"{byte:02X}" for byte in data)


def format_network_address(value: str) -> str:
    data = decode_base64_bytes(value)
    if not data:
        return value

    if len(data) == 4:
        return str(ipaddress.IPv4Address(data))

    if len(data) == 16:
        return str(ipaddress.IPv6Address(data))

    return "0x" + data.hex().upper()


def safe_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        if any(ord(ch) < 32 for ch in value):
            return value.encode("unicode_escape").decode("ascii")
        return value

    return str(value)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            if value.lower().startswith("0x"):
                return int(value, 16)
            return int(value)
        except ValueError:
            return None
    return None


def _hex16(value: Any) -> str | None:
    num = _as_int(value)
    if num is None:
        return None
    return f"0x{num & 0xFFFF:04X}"


def _hex64(value: Any) -> str | None:
    num = _as_int(value)
    if num is None:
        return None
    return f"0x{num & 0xFFFFFFFFFFFFFFFF:016X}"


def decode_thread_version_value(value: Any) -> Any:
    """Best-effort decode for Thread-related version/encoded values.

    Matter payloads sometimes expose base64-encoded binary fields in path slots where
    the label can be ambiguous across implementations. This helper decodes when possible
    and returns a user-meaningful representation.
    """

    if not isinstance(value, str):
        return value

    raw = value.strip()
    if not raw:
        return value

    decoded = decode_base64_bytes(raw)
    if not decoded:
        return value

    # If this decodes cleanly to printable text, use that as-is.
    if all(32 <= b < 127 for b in decoded):
        try:
            return decoded.decode("ascii")
        except UnicodeDecodeError:
            pass

    # Common Thread mesh-local prefix representation:
    # [prefix_length (1 byte)] + [prefix bytes].
    # Example: QP07olVKplSD -> 40 fd 3b a2 55 4a a6 54 83 -> fd3b:a255:4aa6:5483::/64
    if len(decoded) in {5, 9, 17}:
        prefix_len = decoded[0]
        prefix_bytes = decoded[1:]
        if prefix_len <= 128 and prefix_bytes:
            addr_bytes = prefix_bytes.ljust(16, b"\x00")
            try:
                network = ipaddress.IPv6Network((addr_bytes, prefix_len), strict=False)
                return str(network)
            except ipaddress.AddressValueError:
                pass

    return "0x" + decoded.hex().upper()


def decode_scalar_value(value: Any) -> Any:
    """Best-effort decode for generic Matter scalar values."""

    numeric = _as_int(value)
    if numeric is not None:
        return numeric

    if not isinstance(value, str):
        return value

    decoded = decode_base64_bytes(value)
    if not decoded:
        return value

    if all(32 <= b < 127 for b in decoded):
        try:
            return decoded.decode("ascii")
        except UnicodeDecodeError:
            pass

    if len(decoded) <= 8:
        return int.from_bytes(decoded, byteorder="big", signed=False)

    return "0x" + decoded.hex().upper()


def _decode_base64_hex(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    decoded = decode_base64_bytes(value)
    if not decoded:
        return None
    return "0x" + decoded.hex().upper()


def compute_compressed_fabric_id(root_public_key_bytes: bytes, fabric_id: int) -> str | None:
    """Compute Matter Compressed Fabric ID per spec section 2.5.3.1.

    HKDF-SHA-256(
        InputKeyMaterial = RootPublicKey key material (64-byte X||Y),
        Salt             = FabricId encoded as 8-byte big-endian,
        Info             = b"CompressedFabric",
        Length           = 8 bytes,
    )
    If the input is an uncompressed EC point (65 bytes, leading 0x04),
    strip the prefix byte to match matter.js / CHIP derivation behavior.
    Returns the 8-byte result as a 16-character uppercase hex string.
    Used to build the mDNS operational instance name:
        <CompressedFabricId>-<NodeId16Hex>._matter._tcp.local.
    """
    if not root_public_key_bytes or fabric_id is None:
        return None
    try:
        ikm = root_public_key_bytes
        if len(ikm) == 65 and ikm[0] == 0x04:
            ikm = ikm[1:]

        salt = fabric_id.to_bytes(8, byteorder="big")
        info = b"CompressedFabric"
        prk = hmac.new(salt, ikm, hashlib.sha256).digest()
        t1 = hmac.new(prk, info + b"\x01", hashlib.sha256).digest()
        return t1[:8].hex().upper()
    except (ValueError, OverflowError):
        return None


def parse_operational_credentials(attrs: dict[str, Any]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}

    for path, key in CORE_MATTER_DATA_MODEL_PATHS_MAP["operational_credentials_fields"].items():
        if path not in attrs:
            continue
        parsed[key] = attrs[path]

    raw_fabrics = parsed.get("fabrics")
    if isinstance(raw_fabrics, list):
        decoded_fabrics: list[dict[str, Any]] = []
        for entry in raw_fabrics:
            if not isinstance(entry, dict):
                continue

            # FabricDescriptorStruct field mapping (Matter spec):
            # 1 = RootPublicKey (65-byte uncompressed EC key, base64)
            # 2 = VendorID (uint16)
            # 3 = FabricID (uint64)
            # 4 = NodeID (uint64, per-fabric node identity)
            # 5 = Label (string)
            # 254 = FabricIndex (Matter list-entry index attribute)
            root_public_key_raw = _pick_value(entry, "1", "RootPublicKey")
            vendor_id_raw = _pick_value(entry, "2", "VendorID")
            fabric_id_raw = _pick_value(entry, "3", "FabricId")
            node_id_raw = _pick_value(entry, "4", "NodeId")
            label_raw = _pick_value(entry, "5", "Label")
            fabric_index_raw = _pick_value(entry, "254", "FabricIndex")

            node_id = _hex64(node_id_raw)
            if node_id is None:
                node_id = _decode_base64_hex(node_id_raw)

            fabric_id = _hex64(fabric_id_raw)
            if fabric_id is None:
                fabric_id = _decode_base64_hex(fabric_id_raw)

            fabric_index = _as_int(fabric_index_raw)
            if fabric_index is None:
                decoded_index = decode_scalar_value(fabric_index_raw)
                fabric_index = decoded_index if isinstance(decoded_index, int) else None

            vendor_id = _as_int(vendor_id_raw)
            if vendor_id is not None:
                vendor_id_hex = f"0x{vendor_id & 0xFFFF:04X}"
            else:
                vendor_id_hex = None

            label = decode_scalar_value(label_raw)
            if not isinstance(label, str):
                label = safe_text(label_raw) if label_raw is not None else None

            # Compressed Fabric ID (mDNS operational discovery)
            fabric_id_int = _as_int(fabric_id_raw)
            rk_bytes = decode_base64_bytes(root_public_key_raw) if isinstance(root_public_key_raw, str) else None
            compressed_fabric_id = compute_compressed_fabric_id(rk_bytes, fabric_id_int) if rk_bytes and fabric_id_int is not None else None

            mdns_instance_name = None
            if compressed_fabric_id and isinstance(node_id, str) and node_id.startswith("0x"):
                node_id_16hex = node_id[2:].upper()
                mdns_instance_name = f"{compressed_fabric_id}-{node_id_16hex}._matter._tcp.local."

            decoded_fabrics.append(
                {
                    "node_id": node_id,
                    "fabric_id": fabric_id,
                    "fabric_index": fabric_index,
                    "vendor_id": vendor_id_hex,
                    "label": label,
                    "compressed_fabric_id": compressed_fabric_id,
                    "mdns_instance_name": mdns_instance_name,
                    "root_public_key": _decode_base64_hex(root_public_key_raw),
                    "raw_entry": entry,
                }
            )

        parsed["fabrics_decoded"] = decoded_fabrics

    for int_field in (
        "supported_fabrics",
        "commissioned_fabrics",
        "current_fabric_index",
        "feature_map",
        "cluster_revision",
    ):
        if int_field in parsed:
            parsed[f"{int_field}_decoded"] = decode_scalar_value(parsed[int_field])

    return parsed


def parse_group_key_management(attrs: dict[str, Any]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}

    for path, key in CORE_MATTER_DATA_MODEL_PATHS_MAP["group_key_management_fields"].items():
        if path not in attrs:
            continue
        parsed[key] = attrs[path]

    for int_field in (
        "max_groups_per_fabric",
        "max_group_keys_per_fabric",
        "feature_map",
        "cluster_revision",
    ):
        if int_field in parsed:
            parsed[f"{int_field}_decoded"] = decode_scalar_value(parsed[int_field])

    return parsed


def _pick_value(entry: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in entry:
            return entry.get(key)
        if key.isdigit():
            int_key = int(key)
            if int_key in entry:
                return entry.get(int_key)
        else:
            try:
                int_key = int(key)
            except ValueError:
                int_key = None
            if int_key is not None and int_key in entry:
                return entry.get(int_key)
    return None


def _is_table_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


def _find_table_entries(
    attrs: dict[str, Any],
    *,
    preferred_paths: tuple[str, ...],
    named_key_hints: set[str],
    allowed_prefixes: tuple[str, ...],
    min_numeric_keys: int = 3,
) -> tuple[str | None, list[dict[str, Any]]]:
    for path in preferred_paths:
        value = attrs.get(path)
        if _is_table_list(value):
            return path, list(value)

    for path, value in attrs.items():
        if path in preferred_paths or not _is_table_list(value):
            continue
        if not any(path.startswith(prefix) for prefix in allowed_prefixes):
            continue

        sample_keys = {str(key) for key in value[0].keys()} if value else set()
        numeric_count = sum(1 for key in sample_keys if key.isdigit())

        if sample_keys.intersection(named_key_hints) or numeric_count >= min_numeric_keys:
            return path, list(value)

    return None, []


def extract_network_interfaces(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    raw_interfaces = attrs.get(CORE_MATTER_DATA_MODEL_PATHS_MAP["network_interfaces"], [])

    if not isinstance(raw_interfaces, list):
        return entries

    for interface in raw_interfaces:
        if not isinstance(interface, dict):
            continue

        addresses = [
            format_network_address(addr)
            for addr in interface.get("5", [])
            if isinstance(addr, str)
        ]

        entries.append(
            {
                "name": safe_text(interface.get("0")),
                "enabled": interface.get("1"),
                "interface_type": interface.get("7"),
                "hardware_address": format_hardware_address(interface.get("4")),
                "network_addresses": addresses,
                "ipv4_addresses": [addr for addr in addresses if "." in addr],
                "ipv6_addresses": [addr for addr in addresses if ":" in addr],
            }
        )

    return entries


def parse_core_thread_data(attrs: dict[str, Any]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}

    for path, key in CORE_MATTER_DATA_MODEL_PATHS_MAP["thread_core_fields"].items():
        if path not in attrs:
            continue
        value = attrs[path]

        if key == "routing_role":
            role_id = _as_int(value)
            parsed[key] = ROUTING_ROLE_ENUM.get(role_id, f"Unknown ({value})")
        elif key in {"pan_id", "rloc16"}:
            parsed[key] = _hex16(value)
        elif key == "extended_pan_id":
            parsed[key] = _hex64(value)
        else:
            parsed[key] = value

    # Best-effort thread version extraction from common paths.
    for version_path in CORE_MATTER_DATA_MODEL_PATHS_MAP["thread_version_candidates"]:
        if version_path in attrs:
            raw_value = attrs.get(version_path)
            parsed["thread_version_raw"] = raw_value
            parsed["thread_version"] = decode_thread_version_value(raw_value)
            break

    return parsed


def process_neighbor_table(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    source_path, raw_list = _find_table_entries(
        attrs,
        preferred_paths=CORE_MATTER_DATA_MODEL_PATHS_MAP["neighbor_table_preferred"],
        named_key_hints={"ExtAddress", "Rloc16", "LQI", "IsChild", "RxOnWhenIdle"},
        allowed_prefixes=(CORE_MATTER_DATA_MODEL_PATHS_MAP["thread_prefix"],),
        min_numeric_keys=6,
    )
    if not raw_list:
        return []

    table: list[dict[str, Any]] = []
    for entry in raw_list:
        if not isinstance(entry, dict):
            continue

        ext = _hex64(_pick_value(entry, "ExtAddress", "0"))
        age_seconds = _pick_value(entry, "Age", "2")
        rloc16 = _hex16(_pick_value(entry, "Rloc16", "1"))
        link_quality = _pick_value(entry, "LQI", "5")
        avg_rssi = _pick_value(entry, "AverageRssi", "3")
        last_rssi = _pick_value(entry, "LastRssi", "4")
        is_child_node = _pick_value(entry, "IsChild", "8")
        rx_on_idle = _pick_value(entry, "RxOnWhenIdle", "9")

        if all(
            value is None
            for value in (ext, age_seconds, rloc16, link_quality, avg_rssi, last_rssi)
        ):
            continue

        table.append(
            {
                "extended_mac": ext[2:] if isinstance(ext, str) else None,
                "age_seconds": age_seconds,
                "rloc16": rloc16,
                "link_quality": link_quality,
                "avg_rssi_dbm": avg_rssi,
                "last_rssi_dbm": last_rssi,
                "is_child_node": is_child_node,
                "device_can_sleep": None if rx_on_idle is None else not bool(rx_on_idle),
                "source_path": source_path,
                "raw_entry": entry,
            }
        )

    return table


def process_route_table(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    source_path, raw_list = _find_table_entries(
        attrs,
        preferred_paths=CORE_MATTER_DATA_MODEL_PATHS_MAP["route_table_preferred"],
        named_key_hints={"Rloc16", "RouterId", "NextHop", "PathCost", "Allocated"},
        allowed_prefixes=(CORE_MATTER_DATA_MODEL_PATHS_MAP["thread_prefix"],),
        min_numeric_keys=8,
    )
    if not raw_list:
        return []

    table: list[dict[str, Any]] = []
    for entry in raw_list:
        if not isinstance(entry, dict):
            continue

        allocated = _pick_value(entry, "Allocated", "10")
        if allocated is not None and not bool(allocated):
            continue

        target_rloc16 = _hex16(_pick_value(entry, "Rloc16", "2", "1"))
        router_id = _pick_value(entry, "RouterId", "0")
        next_hop_router_id = _pick_value(entry, "NextHop", "3")
        link_cost = _pick_value(entry, "PathCost", "4")
        lqi_in = _pick_value(entry, "LQIIn", "5")
        lqi_out = _pick_value(entry, "LQIOut", "6")
        is_active_link = _pick_value(entry, "LinkEstablished", "11")

        if all(
            value is None
            for value in (target_rloc16, router_id, next_hop_router_id, link_cost)
        ):
            continue

        table.append(
            {
                "target_rloc16": target_rloc16,
                "router_id": router_id,
                "next_hop_router_id": next_hop_router_id,
                "link_cost": link_cost,
                "is_active_link": bool(is_active_link) if is_active_link is not None else None,
                "lqi_in_out": [lqi_in, lqi_out],
                "source_path": source_path,
                "raw_entry": entry,
            }
        )

    return table


def process_child_table(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    source_path, raw_list = _find_table_entries(
        attrs,
        preferred_paths=CORE_MATTER_DATA_MODEL_PATHS_MAP["child_table_preferred"],
        named_key_hints={"ExtAddress", "Rloc16", "Timeout", "NetworkDataVersion", "LinkFrameCounter"},
        allowed_prefixes=(CORE_MATTER_DATA_MODEL_PATHS_MAP["thread_prefix"], CORE_MATTER_DATA_MODEL_PATHS_MAP["descriptor_prefix"]),
        min_numeric_keys=5,
    )
    if not raw_list:
        return []

    table: list[dict[str, Any]] = []
    for entry in raw_list:
        if not isinstance(entry, dict):
            continue

        ext = _hex64(_pick_value(entry, "ExtAddress", "1", "3"))
        child_rloc16 = _hex16(_pick_value(entry, "Rloc16", "0", "2"))
        timeout_seconds = _pick_value(entry, "Timeout", "2", "4")
        network_data_version = _pick_value(entry, "NetworkDataVersion", "3", "5")
        frame_counter = _pick_value(entry, "LinkFrameCounter", "4", "6")

        if all(
            value is None
            for value in (ext, child_rloc16, timeout_seconds, network_data_version, frame_counter)
        ):
            continue

        table.append(
            {
                "child_rloc16": child_rloc16,
                "ext_address": ext[2:] if isinstance(ext, str) else None,
                "timeout_seconds": timeout_seconds,
                "network_data_version": network_data_version,
                "frame_counter": frame_counter,
                "source_path": source_path,
                "raw_entry": entry,
            }
        )

    return table


def extract_matter_identity(node: dict[str, Any], attrs: dict[str, Any]) -> dict[str, Any]:
    device_info = attrs.get(CORE_MATTER_DATA_MODEL_PATHS_MAP["matter_device_info"])

    identity = {
        "node_id": node.get("node_id"),
        "device_info_0_40_5": device_info,
        "device_name": None,
        "device_type": None,
        "available": node.get("available"),
        "is_bridge": node.get("is_bridge"),
        "date_commissioned": node.get("date_commissioned"),
    }

    # Best-effort extraction from common shapes.
    if isinstance(device_info, dict):
        for name_key in ("deviceName", "nodeLabel", "name", "productName"):
            if isinstance(device_info.get(name_key), str) and device_info[name_key]:
                identity["device_name"] = device_info[name_key]
                break

        for type_key in ("deviceType", "type", "productLabel", "description"):
            if device_info.get(type_key) is not None:
                identity["device_type"] = device_info.get(type_key)
                break

    if identity["device_name"] is None and isinstance(node.get("name"), str):
        identity["device_name"] = node.get("name")

    return identity


def extract_node_info(node: dict[str, Any]) -> dict[str, Any]:
    attrs = node.get("attributes", {}) or {}
    if not isinstance(attrs, dict):
        attrs = {}

    network_interfaces = extract_network_interfaces(attrs)
    thread_core = parse_core_thread_data(attrs)
    operational_credentials = parse_operational_credentials(attrs)
    group_key_management = parse_group_key_management(attrs)
    neighbor_table = process_neighbor_table(attrs)
    route_table = process_route_table(attrs)
    child_table = process_child_table(attrs)

    ipv6_addresses: list[str] = []
    ext_macs: list[str] = []

    for interface in network_interfaces:
        ipv6_addresses.extend(interface.get("ipv6_addresses", []))
        hw = interface.get("hardware_address")
        if isinstance(hw, str) and hw:
            ext_macs.append(hw)

    thread_extended_mac = None
    if neighbor_table and isinstance(neighbor_table[0].get("extended_mac"), str):
        thread_extended_mac = neighbor_table[0]["extended_mac"]
    elif ext_macs:
        thread_extended_mac = ext_macs[0]

    return {
        "matter": extract_matter_identity(node, attrs),
        "matter_operational_credentials": operational_credentials,
        "matter_group_key_management": group_key_management,
        "network_interfaces": network_interfaces,
        "thread": {
            "extended_mac": thread_extended_mac,
            "ipv6_addresses": sorted(set(ipv6_addresses)),
            "rloc16": thread_core.get("rloc16"),
            "thread_version": thread_core.get("thread_version"),
            "core": thread_core,
            "neighbor_table": neighbor_table,
            "route_table": route_table,
            "child_table": child_table,
            "table_counts": {
                "neighbors": len(neighbor_table),
                "routes": len(route_table),
                "children": len(child_table),
            },
        },
    }


def extract_nodes_info(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [extract_node_info(node) for node in dedupe_nodes(nodes)]


def print_node_info(node_info: dict[str, Any]) -> None:
    matter = node_info.get("matter", {})
    thread = node_info.get("thread", {})

    print(f"Node {matter.get('node_id')}:")
    print(f"  Device Name: {matter.get('device_name')!r}")
    print(f"  Device Type: {matter.get('device_type')!r}")
    print(f"  Device info (0/40/5): {matter.get('device_info_0_40_5')!r}")
    print(f"  Thread Extended MAC: {thread.get('extended_mac')}")
    print(f"  Thread RLOC16: {thread.get('rloc16')}")
    print(f"  Thread Version: {thread.get('thread_version')}")

    interfaces = node_info.get("network_interfaces", [])
    if not interfaces:
        print("  NetworkInterfaces (0/51/0): <none>")
    else:
        print("  NetworkInterfaces (0/51/0):")
        for index, interface in enumerate(interfaces, start=1):
            print(f"    Interface {index}: {interface.get('name')!r}")
            print(f"      HardwareAddress: {interface.get('hardware_address')}")
            print(f"      IPv6: {interface.get('ipv6_addresses')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract Matter/Thread data from a Matter dump file."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=Path(__file__).resolve().parent / "td-matter-ws-devices-fetch-all.json",
        type=Path,
        help="Path to dump file produced by matter websocket fetch tools.",
    )
    parser.add_argument("--json", action="store_true", help="Output extracted data as JSON.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        nodes = parse_dump_file(args.path)
        extracted = extract_nodes_info(nodes)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(extracted, indent=2, sort_keys=True))
        return 0

    for node_info in extracted:
        print_node_info(node_info)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
