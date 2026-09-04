"""Pure extraction from Home Assistant Matter node snapshots."""

from __future__ import annotations

import base64
import ipaddress
import json
import re

from pathlib import Path
from typing import Any, Mapping

from util_network import find_rloc16_in_ipv6_addresses

from ha_matter_ws_contract import (
    BASIC_INFORMATION_ATTRIBUTES,
    GENERAL_DIAGNOSTICS_ATTRIBUTES,
    INTERFACE_TYPE_ENUM,
    NEIGHBOR_TABLE_FIELDS,
    NETWORK_INTERFACE_FIELDS,
    ROUTE_TABLE_FIELDS,
    ROUTING_ROLE_ENUM,
    THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES,
    matter_attribute_path,
)


class MatterExtractionError(ValueError):
    """A Matter snapshot cannot be decoded at the normalized boundary."""


def parse_dump_file(path: Path) -> list[dict[str, Any]]:
    """Parse nodes from a JSON snapshot or the legacy printed frame format."""

    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise MatterExtractionError(f"Unable to read Matter snapshot {path}: {exc}") from exc

    if not raw.strip():
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _parse_legacy_dump(raw, path)

    if isinstance(payload, list):
        return _dict_entries(payload)
    if not isinstance(payload, dict):
        raise MatterExtractionError(f"Matter snapshot {path} must contain an object or array")
    if isinstance(payload.get("nodes"), list):
        return _dict_entries(payload["nodes"])
    if isinstance(payload.get("result"), list):
        return _dict_entries(payload["result"])
    if isinstance(payload.get("messages"), list):
        return _nodes_from_legacy_messages(payload["messages"])
    raise MatterExtractionError(f"Matter snapshot {path} does not contain a node array")


def _dict_entries(values: list[Any]) -> list[dict[str, Any]]:
    return [value for value in values if isinstance(value, dict)]


def _nodes_from_legacy_messages(messages: list[Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, dict) and isinstance(message.get("result"), list):
            nodes.extend(_dict_entries(message["result"]))
    return nodes


def _parse_legacy_dump(raw: str, path: Path) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for part in re.split(r"Received from server:\s*", raw):
        if not part.strip():
            continue
        try:
            message = json.loads(part)
        except json.JSONDecodeError as exc:
            raise MatterExtractionError(
                f"Unable to parse JSON object from {path}: {exc}"
            ) from exc
        if isinstance(message, dict) and isinstance(message.get("result"), list):
            nodes.extend(_dict_entries(message["result"]))
    return nodes


def dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the latest snapshot for each integer controller-local node ID."""

    unique: dict[int, dict[str, Any]] = {}
    for node in nodes:
        node_id = node.get("node_id")
        if isinstance(node_id, int) and not isinstance(node_id, bool):
            unique[node_id] = node
    return [unique[node_id] for node_id in sorted(unique)]


def _field_value(entry: Mapping[Any, Any], field_id: int, name: str) -> Any:
    for key in (str(field_id), field_id, name, name[:1].lower() + name[1:]):
        if key in entry:
            return entry[key]
    normalized_name = re.sub(r"[^a-z0-9]", "", name.lower())
    for key, value in entry.items():
        if re.sub(r"[^a-z0-9]", "", str(key).lower()) == normalized_name:
            return value
    return None


def _camel(name: str) -> str:
    return name[:1].lower() + name[1:]


def _decode_bytes(value: Any) -> bytes | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), validate=True)
    except (ValueError, TypeError):
        return None


def _decode_address(value: Any, size: int) -> str | None:
    raw = _decode_bytes(value)
    if raw is None or len(raw) != size:
        return None
    address_type = ipaddress.IPv4Address if size == 4 else ipaddress.IPv6Address
    return str(address_type(raw))


def _hex_value(value: Any, bits: int, *, prefix: bool = False) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            number = int(value, 0)
        except ValueError:
            return None
    elif isinstance(value, int):
        number = value
    else:
        return None
    if number < 0 or number >= 1 << bits:
        return None
    text = f"{number:0{bits // 4}X}"
    return f"0x{text}" if prefix else text


def _ext_address(value: Any) -> str | None:
    address = _hex_value(value, 64)
    if address in {None, "0000000000000000", "FFFFFFFFFFFFFFFF"}:
        return None
    return address


def _rloc16(value: Any) -> str | None:
    address = _hex_value(value, 16, prefix=True)
    if address in {None, "0xFFFE", "0xFFFF"}:
        return None
    return address


def _decode_prefix(value: Any) -> str | None:
    raw = _decode_bytes(value)
    if raw is None or len(raw) not in {8, 16}:
        return None
    try:
        return str(ipaddress.IPv6Network((raw.ljust(16, b"\x00"), 64)))
    except ipaddress.AddressValueError:
        return None


def _decode_standard_value(value: Any, data_type: str) -> Any:
    if value is None:
        return None
    base_type = data_type.rstrip("?")
    if base_type == "ipv6pre":
        return _decode_prefix(value)
    if base_type == "octstr":
        raw = _decode_bytes(value)
        return raw.hex().upper() if raw is not None else None
    return value


def extract_network_interfaces(attributes: Mapping[str, Any]) -> list[dict[str, Any]]:
    path = matter_attribute_path(0, 0x0033, 0)
    raw_interfaces = attributes.get(path)
    if not isinstance(raw_interfaces, list):
        return []

    interfaces: list[dict[str, Any]] = []
    for raw_interface in raw_interfaces:
        if not isinstance(raw_interface, dict):
            continue
        values = {
            definition.name: _field_value(raw_interface, field_id, definition.name)
            for field_id, definition in NETWORK_INTERFACE_FIELDS.items()
        }
        interface_type = values["Type"]
        hardware = _decode_bytes(values["HardwareAddress"])
        raw_ipv4 = values["IPv4Addresses"] if isinstance(values["IPv4Addresses"], list) else []
        raw_ipv6 = values["IPv6Addresses"] if isinstance(values["IPv6Addresses"], list) else []
        interfaces.append(
            {
                "name": values["Name"] if isinstance(values["Name"], str) else None,
                "isOperational": values["IsOperational"],
                "interfaceType": INTERFACE_TYPE_ENUM.get(interface_type, f"Unknown ({interface_type})"),
                "hardwareAddress": hardware.hex().upper() if hardware else None,
                "ipv4Addresses": [
                    address
                    for value in raw_ipv4
                    if (address := _decode_address(value, 4)) is not None
                ],
                "ipv6Addresses": [
                    address
                    for value in raw_ipv6
                    if (address := _decode_address(value, 16)) is not None
                ],
            }
        )
    return interfaces


def _basic_information(
    attributes: Mapping[str, Any], endpoint_id: int
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for attribute_id, definition in BASIC_INFORMATION_ATTRIBUTES.items():
        path = matter_attribute_path(endpoint_id, 0x0028, attribute_id)
        if path in attributes:
            values[definition.name] = attributes[path]
    return values


def _matter_id(server_info: Mapping[str, Any], node_id: Any) -> str | None:
    if not isinstance(node_id, int) or isinstance(node_id, bool) or node_id < 0:
        return None
    fabric_scope = server_info.get("compressed_fabric_id")
    if not isinstance(fabric_scope, int) or isinstance(fabric_scope, bool):
        fabric_scope = server_info.get("fabric_id")
    if not isinstance(fabric_scope, int) or isinstance(fabric_scope, bool):
        return None
    if fabric_scope < 0 or fabric_scope >= 1 << 64 or node_id >= 1 << 64:
        return None
    return f"{fabric_scope:016X}-{node_id:016X}"


def _extract_matter(
    node: Mapping[str, Any],
    attributes: Mapping[str, Any],
    server_info: Mapping[str, Any],
) -> dict[str, Any]:
    values = _basic_information(attributes, 0)
    node_label = values.get("NodeLabel")
    fallback_name = node.get("name")
    return {
        "nodeId": node.get("node_id"),
        "matterId": _matter_id(server_info, node.get("node_id")),
        "fabricId": server_info.get("fabric_id"),
        "compressedFabricId": server_info.get("compressed_fabric_id"),
        "fabricIndex": server_info.get("fabric_index"),
        "deviceLabel": node_label if isinstance(node_label, str) and node_label else fallback_name,
        "vendorName": values.get("VendorName"),
        "vendorModel": values.get("ProductName"),
        "vendorId": values.get("VendorId"),
        "productId": values.get("ProductId"),
        "productLabel": values.get("ProductLabel"),
        "vendorHwVersion": values.get("HardwareVersionString"),
        "vendorHwVersionNumber": values.get("HardwareVersion"),
        "vendorSwVersion": values.get("SoftwareVersionString"),
        "vendorSwVersionNumber": values.get("SoftwareVersion"),
        "available": node.get("available"),
        "isBridge": node.get("is_bridge"),
        "dateCommissioned": node.get("date_commissioned"),
    }


def _device_types(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    device_types: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        device_type = _field_value(entry, 0, "DeviceType")
        revision = _field_value(entry, 1, "Revision")
        if isinstance(device_type, int) and not isinstance(device_type, bool):
            device_types.append({"deviceType": device_type, "revision": revision})
    return device_types


def extract_endpoints(attributes: Mapping[str, Any]) -> list[dict[str, Any]]:
    endpoint_ids: set[int] = set()
    for path in attributes:
        match = re.fullmatch(r"(\d+)/(29|40)/\d+", path)
        if match is not None:
            endpoint_ids.add(int(match.group(1)))

    endpoints: list[dict[str, Any]] = []
    for endpoint_id in sorted(endpoint_ids):
        device_types = _device_types(
            attributes.get(matter_attribute_path(endpoint_id, 0x001D, 0))
        )
        raw_servers = attributes.get(matter_attribute_path(endpoint_id, 0x001D, 1))
        server_clusters = (
            sorted(
                cluster_id
                for cluster_id in raw_servers
                if isinstance(cluster_id, int) and not isinstance(cluster_id, bool)
            )
            if isinstance(raw_servers, list)
            else []
        )
        raw_parts = attributes.get(matter_attribute_path(endpoint_id, 0x001D, 3))
        parts = (
            sorted(
                part
                for part in raw_parts
                if isinstance(part, int) and not isinstance(part, bool)
            )
            if isinstance(raw_parts, list)
            else []
        )
        endpoint: dict[str, Any] = {
            "endpointId": endpoint_id,
            "deviceTypes": device_types,
            "serverClusters": server_clusters,
            "partsList": parts,
        }
        basic_information = _basic_information(attributes, endpoint_id)
        if basic_information:
            endpoint["basicInformation"] = basic_information
        endpoints.append(endpoint)
    return endpoints


def _known_struct_key(key: Any, definitions: Mapping[int, Any]) -> bool:
    if isinstance(key, int):
        return key in definitions
    if isinstance(key, str) and key.isdigit():
        return int(key) in definitions
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return any(
        normalized == re.sub(r"[^a-z0-9]", "", definition.name.lower())
        for definition in definitions.values()
    )


def _decode_struct_list(value: Any, definitions: Mapping[int, Any]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    records: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        record: dict[str, Any] = {}
        for field_id, definition in definitions.items():
            field_value = _field_value(entry, field_id, definition.name)
            if field_value is not None:
                key = _camel(definition.name)
                record[key] = field_value
        if "extAddress" in record:
            record["extAddress"] = _ext_address(record["extAddress"])
        if "rloc16" in record:
            record["rloc16"] = _rloc16(record["rloc16"])
        unknown_fields = {
            str(key): field_value
            for key, field_value in entry.items()
            if not _known_struct_key(key, definitions)
        }
        if unknown_fields:
            record["unknownFields"] = unknown_fields
        records.append(record)
    return records


MLE_COUNTER_NAMES = {
    0x0E: "detachedRoleCount",
    0x0F: "childRoleCount",
    0x10: "routerRoleCount",
    0x11: "leaderRoleCount",
    0x12: "attachAttemptCount",
    0x13: "partIdChangesCount",
    0x14: "betterPartIdAttachAttemptsCount",
    0x15: "newParentCount",
}


def _thread_supported(
    attributes: Mapping[str, Any], endpoints: list[dict[str, Any]]
) -> bool:
    if any(0x0035 in endpoint["serverClusters"] for endpoint in endpoints):
        return True
    return any(re.fullmatch(r"0/53/\d+", path) for path in attributes)


def _coverage_state(value: Any, *, present: bool, read_error: bool) -> str:
    if read_error:
        return "readError"
    if not present:
        return "attributeUnsupported"
    if value is None:
        return "null"
    if value == "" or value == [] or value == {}:
        return "implementedEmpty"
    return "populated"


def _thread_coverage(
    attributes: Mapping[str, Any],
    attribute_errors: Mapping[str, Any],
    *,
    supported: bool,
) -> dict[str, Any]:
    if not supported:
        return {"cluster": "clusterUnsupported", "attributes": {}}
    states: dict[str, str] = {}
    for attribute_id, definition in THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES.items():
        path = matter_attribute_path(0, 0x0035, attribute_id)
        states[_camel(definition.name)] = _coverage_state(
            attributes.get(path),
            present=path in attributes,
            read_error=path in attribute_errors,
        )
    state_values = set(states.values())
    if "populated" in state_values:
        cluster_state = "populated"
    elif "readError" in state_values:
        cluster_state = "readError"
    elif "implementedEmpty" in state_values:
        cluster_state = "implementedEmpty"
    elif "null" in state_values:
        cluster_state = "null"
    else:
        cluster_state = "attributeUnsupported"
    return {"cluster": cluster_state, "attributes": states}


def extract_general_diagnostics(
    attributes: Mapping[str, Any], interfaces: list[dict[str, Any]]
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    for attribute_id, definition in GENERAL_DIAGNOSTICS_ATTRIBUTES.items():
        path = matter_attribute_path(0, 0x0033, attribute_id)
        if path not in attributes:
            continue
        diagnostics[_camel(definition.name)] = (
            interfaces
            if attribute_id == 0
            else _decode_standard_value(attributes[path], definition.data_type)
        )
    return diagnostics


def _extract_thread(
    attributes: Mapping[str, Any],
    interfaces: list[dict[str, Any]],
    endpoints: list[dict[str, Any]],
    attribute_errors: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not _thread_supported(attributes, endpoints):
        return None

    values: dict[str, Any] = {}
    for attribute_id, definition in THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES.items():
        path = matter_attribute_path(0, 0x0035, attribute_id)
        if path in attributes:
            values[definition.name] = _decode_standard_value(
                attributes[path], definition.data_type
            )

    thread_interface = next(
        (
            interface
            for interface in interfaces
            if interface["interfaceType"] == "Thread"
            and isinstance(interface["hardwareAddress"], str)
            and len(interface["hardwareAddress"]) == 16
            and interface["hardwareAddress"]
            not in {"0000000000000000", "FFFFFFFFFFFFFFFF"}
        ),
        None,
    )
    ext_address = _ext_address(values.get("ExtAddress"))
    if ext_address is None and thread_interface is not None:
        ext_address = thread_interface["hardwareAddress"]

    role = values.get("RoutingRole")
    standard_attributes = {
        _camel(definition.name): values[definition.name]
        for attribute_id, definition in THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES.items()
        if attribute_id not in {7, 8} and definition.name in values
    }
    mac_counters = {
        _camel(THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES[attribute_id].name): values[
            THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES[attribute_id].name
        ]
        for attribute_id in range(0x16, 0x38)
        if THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES[attribute_id].name in values
    }
    mle_counters = {
        canonical_name: values[THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES[attribute_id].name]
        for attribute_id, canonical_name in MLE_COUNTER_NAMES.items()
        if THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES[attribute_id].name in values
    }
    known_paths = {
        matter_attribute_path(0, 0x0035, attribute_id)
        for attribute_id in THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES
    }
    unknown_attributes = {
        path: value
        for path, value in attributes.items()
        if re.fullmatch(r"0/53/\d+", path) and path not in known_paths
    }
    ipv6_addresses = thread_interface["ipv6Addresses"] if thread_interface else []
    rloc16 = _rloc16(values.get("Rloc16"))
    if rloc16 is None:
        rloc16 = find_rloc16_in_ipv6_addresses(ipv6_addresses)

    return {
        "extAddress": ext_address,
        "rloc16": rloc16,
        "channel": values.get("Channel"),
        "routingRole": ROUTING_ROLE_ENUM.get(role, f"Unknown ({role})") if role is not None else None,
        "networkName": values.get("NetworkName"),
        "panId": _hex_value(values.get("PanId"), 16, prefix=True),
        "extendedPanId": _hex_value(values.get("ExtendedPanId"), 64, prefix=True),
        "meshLocalPrefix": values.get("MeshLocalPrefix"),
        "partitionId": values.get("PartitionId"),
        "clusterRevision": values.get("ClusterRevision"),
        "ipv6Addresses": ipv6_addresses,
        "neighborTable": _decode_struct_list(values.get("NeighborTable"), NEIGHBOR_TABLE_FIELDS),
        "routeTable": _decode_struct_list(values.get("RouteTable"), ROUTE_TABLE_FIELDS),
        "macCounters": mac_counters,
        "mleCounters": mle_counters,
        "diagnosticsDetail": {
            "threadNetworkDiagnostics": standard_attributes,
            "unknownAttributes": unknown_attributes,
            "readErrors": {
                path: error
                for path, error in attribute_errors.items()
                if re.fullmatch(r"0/53/\d+", path)
            },
        },
    }


def extract_node_info(
    node: dict[str, Any], *, server_info: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    attributes = node.get("attributes")
    if attributes is None:
        attributes = {}
    if not isinstance(attributes, dict):
        raise MatterExtractionError(
            f"Matter node {node.get('node_id')!r} attributes must be an object"
        )
    interfaces = extract_network_interfaces(attributes)
    endpoints = extract_endpoints(attributes)
    attribute_errors = node.get("attribute_errors")
    if not isinstance(attribute_errors, dict):
        attribute_errors = {}
    thread_supported = _thread_supported(attributes, endpoints)
    return {
        "matter": _extract_matter(node, attributes, server_info or {}),
        "endpoints": endpoints,
        "deviceTypes": [
            {"endpointId": endpoint["endpointId"], **device_type}
            for endpoint in endpoints
            for device_type in endpoint["deviceTypes"]
        ],
        "serverClusters": sorted(
            {
                cluster_id
                for endpoint in endpoints
                for cluster_id in endpoint["serverClusters"]
            }
        ),
        "networkInterfaces": interfaces,
        "generalDiagnostics": extract_general_diagnostics(attributes, interfaces),
        "diagnosticCoverage": {
            "threadNetworkDiagnostics": _thread_coverage(
                attributes, attribute_errors, supported=thread_supported
            )
        },
        "thread": _extract_thread(
            attributes, interfaces, endpoints, attribute_errors
        ),
    }


def extract_nodes_info(
    nodes: list[dict[str, Any]], *, server_info: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [
        extract_node_info(node, server_info=server_info)
        for node in dedupe_nodes(nodes)
    ]