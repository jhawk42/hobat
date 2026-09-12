"""Bounded validator for Matter Server's native schema-13 topology."""

from __future__ import annotations

import math
import re

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ha_matter_ws_contract import MatterWsContractError
from ha_matter_ws_snapshots import assert_snapshot_safe


MAX_SAFE_JSON_INTEGER = (1 << 53) - 1
MAX_UINT64 = (1 << 64) - 1
MAX_TOPOLOGY_NODES = 4096
MAX_TOPOLOGY_CONNECTIONS = 16384
MAX_TEXT_BYTES = 1024
MAX_EXTENSION_FIELDS = 32

TOPOLOGY_NODE_KINDS = frozenset(
    {"matter", "border_router", "thread_unknown", "wifi_ap"}
)
TOPOLOGY_NETWORK_TYPES = frozenset({"thread", "wifi", "ethernet", "unknown"})
TOPOLOGY_ROLES = frozenset(
    {
        "leader",
        "router",
        "reed",
        "end_device",
        "sleepy_end_device",
        "unassigned",
        "station",
        "ap",
    }
)
TOPOLOGY_STRENGTHS = frozenset(
    {"strong", "medium", "weak", "none", "unknown"}
)

_HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")
_DECIMAL_RE = re.compile(r"^(0|[1-9][0-9]*)$")
_BSSID_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
Validator = Callable[[Any, str], Any]


@dataclass(frozen=True)
class NativeTopologyValidationLimits:
    max_nodes: int = MAX_TOPOLOGY_NODES
    max_connections: int = MAX_TOPOLOGY_CONNECTIONS
    max_text_bytes: int = MAX_TEXT_BYTES
    max_extension_fields: int = MAX_EXTENSION_FIELDS


def _error(path: str, message: str) -> MatterWsContractError:
    return MatterWsContractError(f"{path} {message}")


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise _error(path, "must be an object with string keys")
    return value


def _array(value: Any, path: str, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        raise _error(path, "must be an array")
    if len(value) > maximum:
        raise _error(path, f"exceeds the limit of {maximum} items")
    return value


def _text(value: Any, path: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise _error(path, "must be a string")
    if len(value.encode("utf-8")) > maximum:
        raise _error(path, f"exceeds the limit of {maximum} UTF-8 bytes")
    return value


def _nonempty_text(value: Any, path: str, maximum: int) -> str:
    result = _text(value, path, maximum)
    if not result:
        raise _error(path, "must not be empty")
    return result


def _boolean(value: Any, path: str) -> bool:
    if type(value) is not bool:
        raise _error(path, "must be boolean")
    return value


def _integer(value: Any, path: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _error(path, f"must be an integer from {minimum} through {maximum}")
    return value


def _safe_uint(value: Any, path: str) -> int:
    return _integer(value, path, 0, MAX_SAFE_JSON_INTEGER)


def _node_id(value: Any, path: str) -> int | str:
    if type(value) is int and 0 <= value <= MAX_SAFE_JSON_INTEGER:
        return value
    if isinstance(value, str) and _DECIMAL_RE.fullmatch(value):
        if int(value) <= MAX_UINT64:
            return value
    raise _error(path, "must be a safe JSON integer or uint64 decimal string")


def _hex(value: Any, path: str, length: int) -> str:
    result = _text(value, path, MAX_TEXT_BYTES)
    if len(result) != length or not _HEX_RE.fullmatch(result):
        raise _error(path, f"must contain exactly {length} hexadecimal characters")
    return result


def _enum(value: Any, path: str, choices: frozenset[str], maximum: int) -> str:
    result = _text(value, path, maximum)
    if result not in choices:
        raise _error(path, f"must be one of {sorted(choices)!r}")
    return result


def _extension_scalar(value: Any, path: str, maximum_text: int) -> Any:
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return _integer(value, path, -MAX_SAFE_JSON_INTEGER, MAX_SAFE_JSON_INTEGER)
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, str):
        return _text(value, path, maximum_text)
    raise _error(path, "must be a bounded JSON scalar")


def _project_object(
    value: Any,
    path: str,
    validators: Mapping[str, Validator],
    *,
    required: frozenset[str],
    limits: NativeTopologyValidationLimits,
) -> dict[str, Any]:
    source = _mapping(value, path)
    missing = required.difference(source)
    if missing:
        raise _error(path, f"is missing required fields {sorted(missing)!r}")
    result = {
        key: validator(source[key], f"{path}.{key}")
        for key, validator in validators.items()
        if key in source
    }

    raw_extensions: dict[str, Any] = {}
    supplied = source.get("extensions")
    if supplied is not None:
        raw_extensions.update(_mapping(supplied, f"{path}.extensions"))
    for key, child in source.items():
        if key not in validators and key != "extensions":
            if key in raw_extensions:
                raise _error(f"{path}.{key}", "duplicates an extensions field")
            raw_extensions[key] = child
    if len(raw_extensions) > limits.max_extension_fields:
        raise _error(
            f"{path}.extensions",
            f"exceeds the limit of {limits.max_extension_fields} fields",
        )
    if raw_extensions:
        extensions: dict[str, Any] = {}
        for key, child in raw_extensions.items():
            _nonempty_text(key, f"{path}.extensions key", 128)
            extensions[key] = _extension_scalar(
                child, f"{path}.extensions.{key}", limits.max_text_bytes
            )
        result["extensions"] = extensions
    return result


def validate_native_topology(
    value: Any,
    *,
    limits: NativeTopologyValidationLimits = NativeTopologyValidationLimits(),
) -> dict[str, Any]:
    """Validate and project one native Matter Server topology graph."""

    node_ids: set[str] = set()

    def nodes(raw: Any, field_path: str) -> list[dict[str, Any]]:
        values = _array(raw, field_path, limits.max_nodes)
        result: list[dict[str, Any]] = []
        for index, node in enumerate(values):
            validated = _validate_node(node, f"{field_path}[{index}]", limits)
            node_id = validated["id"]
            if node_id in node_ids:
                raise _error(f"{field_path}[{index}].id", "must be unique")
            node_ids.add(node_id)
            result.append(validated)
        return result

    def connections(raw: Any, field_path: str) -> list[dict[str, Any]]:
        values = _array(raw, field_path, limits.max_connections)
        result = [
            _validate_connection(connection, f"{field_path}[{index}]", limits)
            for index, connection in enumerate(values)
        ]
        for index, connection in enumerate(result):
            for endpoint in ("source", "target"):
                if connection[endpoint] not in node_ids:
                    raise _error(
                        f"{field_path}[{index}].{endpoint}",
                        "must reference an existing node id",
                    )
        return result

    validators: dict[str, Validator] = {
        "collected_at": _safe_uint,
        "nodes": nodes,
        "connections": connections,
    }
    result = _project_object(
        value,
        "topology",
        validators,
        required=frozenset(validators),
        limits=limits,
    )
    assert_snapshot_safe(result)
    return result


def _validate_node(
    value: Any, path: str, limits: NativeTopologyValidationLimits
) -> dict[str, Any]:
    validators: dict[str, Validator] = {
        "id": lambda item, item_path: _nonempty_text(
            item, item_path, limits.max_text_bytes
        ),
        "kind": lambda item, item_path: _enum(
            item, item_path, TOPOLOGY_NODE_KINDS, limits.max_text_bytes
        ),
        "network_type": lambda item, item_path: _enum(
            item, item_path, TOPOLOGY_NETWORK_TYPES, limits.max_text_bytes
        ),
        "node_id": _node_id,
        "role": lambda item, item_path: _enum(
            item, item_path, TOPOLOGY_ROLES, limits.max_text_bytes
        ),
        "available": _boolean,
        "is_bridge": _boolean,
        "ext_address": lambda item, item_path: _hex(item, item_path, 16),
        "rloc16": lambda item, item_path: _integer(item, item_path, 0, 65535),
        "ext_pan_id": lambda item, item_path: _hex(item, item_path, 16),
        "network_name": lambda item, item_path: _text(
            item, item_path, limits.max_text_bytes
        ),
        "ssid": lambda item, item_path: _text(
            item, item_path, limits.max_text_bytes
        ),
        "bssid": _validate_bssid,
        "host_name": lambda item, item_path: _text(
            item, item_path, limits.max_text_bytes
        ),
        "vendor_name": lambda item, item_path: _text(
            item, item_path, limits.max_text_bytes
        ),
        "model_name": lambda item, item_path: _text(
            item, item_path, limits.max_text_bytes
        ),
        "last_seen": _safe_uint,
    }
    return _project_object(
        value,
        path,
        validators,
        required=frozenset({"id", "kind", "network_type"}),
        limits=limits,
    )


def _validate_bssid(value: Any, path: str) -> str:
    result = _text(value, path, MAX_TEXT_BYTES)
    if not _BSSID_RE.fullmatch(result):
        raise _error(path, "must be a six-octet colon-delimited hexadecimal BSSID")
    return result


def _validate_connection(
    value: Any, path: str, limits: NativeTopologyValidationLimits
) -> dict[str, Any]:
    def direction(raw: Any, field_path: str) -> dict[str, Any]:
        validators: dict[str, Validator] = {
            "strength": lambda item, item_path: _enum(
                item, item_path, TOPOLOGY_STRENGTHS, limits.max_text_bytes
            ),
            "lqi": lambda item, item_path: _integer(item, item_path, 0, 3),
            "rssi": lambda item, item_path: _integer(item, item_path, -200, 100),
        }
        return _project_object(
            raw,
            field_path,
            validators,
            required=frozenset({"strength"}),
            limits=limits,
        )

    validators: dict[str, Validator] = {
        "source": lambda item, item_path: _nonempty_text(
            item, item_path, limits.max_text_bytes
        ),
        "target": lambda item, item_path: _nonempty_text(
            item, item_path, limits.max_text_bytes
        ),
        "network": lambda item, item_path: _enum(
            item, item_path, frozenset({"thread", "wifi"}), limits.max_text_bytes
        ),
        "strength": lambda item, item_path: _enum(
            item, item_path, TOPOLOGY_STRENGTHS, limits.max_text_bytes
        ),
        "source_to_target": direction,
        "target_to_source": direction,
        "via_route_table": _boolean,
        "path_cost": lambda item, item_path: _integer(item, item_path, 0, 65535),
    }
    return _project_object(
        value,
        path,
        validators,
        required=frozenset({"source", "target", "network", "strength"}),
        limits=limits,
    )