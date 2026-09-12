"""Bounded validators for native Matter Server Thread network responses."""

from __future__ import annotations

import asyncio
import ipaddress
import math
import re

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from ha_matter_ws_contract import MatterWsContractError
from ha_matter_ws_snapshots import assert_snapshot_safe


MAX_SAFE_JSON_INTEGER = (1 << 53) - 1
MAX_UINT64 = (1 << 64) - 1
MAX_TEXT_BYTES = 1024
MAX_EXTENSION_FIELDS = 32
MAX_BORDER_ROUTERS = 128
MAX_BORDER_ROUTER_ADDRESSES = 32
MAX_DIAGNOSTIC_NETWORKS = 32
MAX_DIAGNOSTIC_NODES = 512
MAX_IPV6_ADDRESSES = 64
MAX_ROUTE64_ENTRIES = 64
MAX_CHILD_TABLE_ENTRIES = 512
MAX_UNKNOWN_TLVS = 32
MAX_UNKNOWN_TLV_HEX_BYTES = 8 * 1024
MAX_HEX_BYTES = 2 * 1024 * 1024

THREAD_DIAGNOSTIC_SOURCES = frozenset({"meshcop", "otbr-rest", "none"})
THREAD_DIAGNOSTIC_PARTIAL_REASONS = frozenset(
    {
        "petition_rejected",
        "dtls_failed",
        "border_router_unreachable",
        "no_credentials",
        "no_source",
        "rest_unreachable",
        "rest_protocol",
        "timeout",
        "in_progress",
        "meshcop_no_responses_yet",
        "rest_no_responses_yet",
    }
)
THREAD_DIAGNOSTIC_TRANSIENT_REASONS = frozenset(
    {"in_progress", "meshcop_no_responses_yet", "rest_no_responses_yet"}
)
THREAD_DIAGNOSTIC_TERMINAL_REASONS = (
    THREAD_DIAGNOSTIC_PARTIAL_REASONS - THREAD_DIAGNOSTIC_TRANSIENT_REASONS
)

_HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")
_DECIMAL_RE = re.compile(r"^(0|[1-9][0-9]*)$")
Validator = Callable[[Any, str], Any]


@dataclass(frozen=True)
class ThreadValidationLimits:
    max_border_routers: int = MAX_BORDER_ROUTERS
    max_addresses_per_router: int = MAX_BORDER_ROUTER_ADDRESSES
    max_networks: int = MAX_DIAGNOSTIC_NETWORKS
    max_nodes_per_network: int = MAX_DIAGNOSTIC_NODES
    max_ipv6_addresses_per_node: int = MAX_IPV6_ADDRESSES
    max_route64_entries_per_node: int = MAX_ROUTE64_ENTRIES
    max_child_table_entries_per_node: int = MAX_CHILD_TABLE_ENTRIES
    max_unknown_tlvs_per_node: int = MAX_UNKNOWN_TLVS
    max_unknown_tlv_hex_bytes: int = MAX_UNKNOWN_TLV_HEX_BYTES
    max_text_bytes: int = MAX_TEXT_BYTES
    max_extension_fields: int = MAX_EXTENSION_FIELDS


@dataclass(frozen=True)
class DiagnosticBatchCoalesceResult:
    batches: tuple[dict[str, Any], ...]
    stale_count: int
    duplicate_count: int
    conflict_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class SelectedDiagnosticsResult:
    status: str
    batch: dict[str, Any] | None
    response_count: int
    event_count: int
    accepted_count: int
    stale_count: int
    duplicate_count: int
    conflict_count: int
    warnings: tuple[str, ...]


class ThreadDiagnosticsEventClient(Protocol):
    @property
    def event_cursor(self) -> int: ...

    async def request(self, command: str, **kwargs: Any) -> Any: ...

    async def next_event(
        self,
        *,
        after: int,
        predicate: Callable[[dict[str, Any]], bool],
        timeout: float | None = None,
    ) -> tuple[int, dict[str, Any]]: ...

    def raise_if_reader_failed(self) -> None: ...


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


def _text(value: Any, path: str, maximum: int = MAX_TEXT_BYTES) -> str:
    if not isinstance(value, str):
        raise _error(path, "must be a string")
    if len(value.encode("utf-8")) > maximum:
        raise _error(path, f"exceeds the limit of {maximum} UTF-8 bytes")
    return value


def _nonempty_text(value: Any, path: str, maximum: int = MAX_TEXT_BYTES) -> str:
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


def _uint64_wire(value: Any, path: str) -> int | str:
    if type(value) is int and 0 <= value <= MAX_SAFE_JSON_INTEGER:
        return value
    if isinstance(value, str) and _DECIMAL_RE.fullmatch(value):
        if int(value) <= MAX_UINT64:
            return value
    raise _error(path, "must be a safe JSON integer or uint64 decimal string")


def _hex(
    value: Any,
    path: str,
    length: int | None = None,
    maximum_bytes: int = MAX_HEX_BYTES,
) -> str:
    if not isinstance(value, str):
        raise _error(path, "must be a string")
    result = value
    if not result or not _HEX_RE.fullmatch(result):
        raise _error(path, "must contain hexadecimal characters")
    if length is not None and len(result) != length:
        raise _error(path, f"must contain exactly {length} hexadecimal characters")
    if length is None and len(result) % 2:
        raise _error(path, "must contain an even number of hexadecimal characters")
    if len(result) // 2 > maximum_bytes:
        raise _error(path, f"exceeds the decoded hex limit of {maximum_bytes} bytes")
    return result


def _enum(value: Any, path: str, choices: frozenset[str]) -> str:
    result = _text(value, path)
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


def _extensions(
    value: Mapping[str, Any],
    known_fields: frozenset[str],
    path: str,
    *,
    maximum_fields: int,
    maximum_text: int,
) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    supplied = value.get("extensions")
    if supplied is not None:
        raw.update(_mapping(supplied, f"{path}.extensions"))
    for key, child in value.items():
        if key not in known_fields and key != "extensions":
            if key in raw:
                raise _error(f"{path}.{key}", "duplicates an extensions field")
            raw[key] = child
    if len(raw) > maximum_fields:
        raise _error(
            f"{path}.extensions", f"exceeds the limit of {maximum_fields} fields"
        )
    result: dict[str, Any] = {}
    for key, child in raw.items():
        _nonempty_text(key, f"{path}.extensions key", 128)
        result[key] = _extension_scalar(
            child, f"{path}.extensions.{key}", maximum_text
        )
    return result


def _project_object(
    value: Any,
    path: str,
    validators: Mapping[str, Validator],
    *,
    required: frozenset[str] = frozenset(),
    limits: ThreadValidationLimits,
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
    extension_values = _extensions(
        source,
        frozenset(validators),
        path,
        maximum_fields=limits.max_extension_fields,
        maximum_text=limits.max_text_bytes,
    )
    if extension_values:
        result["extensions"] = extension_values
    return result


def validate_border_router_entries(
    value: Any, *, limits: ThreadValidationLimits = ThreadValidationLimits()
) -> list[dict[str, Any]]:
    """Validate and project a bounded Border Router inventory."""

    entries = _array(value, "borderRouters", limits.max_border_routers)
    result = [
        _validate_border_router(entry, f"borderRouters[{index}]", limits)
        for index, entry in enumerate(entries)
    ]
    assert_snapshot_safe(result)
    return result


def _validate_border_router(
    value: Any, path: str, limits: ThreadValidationLimits
) -> dict[str, Any]:
    def addresses(raw: Any, field_path: str) -> list[str]:
        values = _array(raw, field_path, limits.max_addresses_per_router)
        result: list[str] = []
        seen: set[str] = set()
        for index, address in enumerate(values):
            text = _text(address, f"{field_path}[{index}]", limits.max_text_bytes)
            try:
                identity = str(ipaddress.ip_address(text))
            except ValueError as exc:
                raise _error(f"{field_path}[{index}]", "must be an IPv4 or IPv6 address") from exc
            if identity not in seen:
                seen.add(identity)
                result.append(text)
        return result

    def sources(raw: Any, field_path: str) -> list[str]:
        values = _array(raw, field_path, 2)
        if not values:
            raise _error(field_path, "must not be empty")
        result: list[str] = []
        for index, source in enumerate(values):
            validated = _enum(
                source, f"{field_path}[{index}]", frozenset({"meshcop", "trel"})
            )
            if validated not in result:
                result.append(validated)
        return result

    validators: dict[str, Validator] = {
        "extAddressHex": lambda item, item_path: _hex(item, item_path, 16),
        "extendedPanIdHex": lambda item, item_path: _hex(item, item_path, 16),
        "networkName": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "vendorName": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "modelName": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "hostname": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "addresses": addresses,
        "meshcopPort": lambda item, item_path: _integer(item, item_path, 1, 65535),
        "trelPort": lambda item, item_path: _integer(item, item_path, 1, 65535),
        "threadVersion": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "swVersion": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "recordVersion": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "borderAgentIdHex": lambda item, item_path: _hex(item, item_path),
        "stateBitmapHex": lambda item, item_path: _hex(item, item_path, 8),
        "activeTimestampHex": lambda item, item_path: _hex(item, item_path, 16),
        "partitionIdHex": lambda item, item_path: _hex(item, item_path, 8),
        "domainName": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "sources": sources,
        "lastSeen": _safe_uint,
    }
    return _project_object(
        value,
        path,
        validators,
        required=frozenset({"extAddressHex", "addresses", "sources"}),
        limits=limits,
    )


def validate_thread_diagnostics_batches(
    value: Any, *, limits: ThreadValidationLimits = ThreadValidationLimits()
) -> list[dict[str, Any]]:
    """Validate a bounded immediate list of Thread diagnostic batches."""

    batches = _array(value, "batches", limits.max_networks)
    result = [
        validate_thread_diagnostics_batch(
            batch, limits=limits, path=f"batches[{index}]"
        )
        for index, batch in enumerate(batches)
    ]
    assert_snapshot_safe(result)
    return result


def coalesce_thread_diagnostics_batches(
    batches: list[dict[str, Any]], *, max_warnings: int = 32
) -> DiagnosticBatchCoalesceResult:
    """Keep one deterministic latest batch for each Extended PAN ID."""

    if max_warnings < 0:
        raise ValueError("max_warnings must not be negative")
    selected: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    stale_count = 0
    duplicate_count = 0
    conflict_count = 0
    warnings: list[str] = []
    for batch in batches:
        key = batch["extPanIdHex"].lower()
        current = selected.get(key)
        if current is None:
            selected[key] = batch
            order.append(key)
            continue
        current_time = current["collectedAt"]
        candidate_time = batch["collectedAt"]
        if candidate_time > current_time:
            stale_count += 1
            selected[key] = batch
        elif candidate_time < current_time:
            stale_count += 1
        elif batch == current:
            duplicate_count += 1
        else:
            conflict_count += 1
            if len(warnings) < max_warnings:
                warnings.append(
                    f"conflicting batch retained for {current['extPanIdHex']} "
                    f"at collectedAt={current_time}"
                )
    return DiagnosticBatchCoalesceResult(
        batches=tuple(selected[key] for key in order),
        stale_count=stale_count,
        duplicate_count=duplicate_count,
        conflict_count=conflict_count,
        warnings=tuple(warnings),
    )


def normalize_extended_pan_id(value: str) -> str:
    """Validate and normalize a command Extended PAN ID."""

    return _hex(value, "extPanId", 16).lower()


async def collect_selected_thread_diagnostics(
    client: ThreadDiagnosticsEventClient,
    ext_pan_id: str,
    *,
    force: bool,
    timeout: float,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
    checkpoint_interval: float = 1.0,
    max_warnings: int = 32,
) -> SelectedDiagnosticsResult:
    """Collect one selected network through its progressive update events."""

    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if checkpoint_interval < 0:
        raise ValueError("checkpoint_interval must not be negative")
    normalized_id = normalize_extended_pan_id(ext_pan_id)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    cursor = client.event_cursor
    latest: dict[str, Any] | None = None
    response_count = 0
    event_count = 0
    accepted_count = 0
    stale_count = 0
    duplicate_count = 0
    conflict_count = 0
    warnings: list[str] = []
    last_checkpoint_at: float | None = None
    last_checkpoint_batch: dict[str, Any] | None = None

    def matching_event(frame: dict[str, Any]) -> bool:
        if frame.get("event") != "thread_diagnostics_updated":
            return False
        data = frame.get("data")
        return (
            isinstance(data, Mapping)
            and isinstance(data.get("extPanIdHex"), str)
            and data["extPanIdHex"].lower() == normalized_id
        )

    def write_checkpoint(batch: dict[str, Any], *, required: bool = False) -> None:
        nonlocal last_checkpoint_at, last_checkpoint_batch
        if checkpoint is None:
            return
        if batch == last_checkpoint_batch:
            return
        now = loop.time()
        if (
            required
            or last_checkpoint_at is None
            or now - last_checkpoint_at >= checkpoint_interval
        ):
            checkpoint(batch)
            last_checkpoint_at = now
            last_checkpoint_batch = batch

    def accept(raw: Any) -> str:
        nonlocal latest, accepted_count, stale_count
        nonlocal duplicate_count, conflict_count
        batch = validate_thread_diagnostics_batch(raw)
        if batch["extPanIdHex"].lower() != normalized_id:
            raise MatterWsContractError(
                "selected diagnostics response Extended PAN ID does not match request"
            )
        if latest is not None:
            if batch["collectedAt"] < latest["collectedAt"]:
                stale_count += 1
                return "continue"
            if batch["collectedAt"] == latest["collectedAt"]:
                if batch == latest:
                    duplicate_count += 1
                else:
                    conflict_count += 1
                    if len(warnings) < max_warnings:
                        warnings.append(
                            f"conflicting batch retained for {latest['extPanIdHex']} "
                            f"at collectedAt={latest['collectedAt']}"
                        )
                return "continue"
        latest = batch
        accepted_count += 1
        reason = batch.get("partialReason")
        if reason is None:
            return "complete"
        write_checkpoint(
            batch, required=reason in THREAD_DIAGNOSTIC_TERMINAL_REASONS
        )
        if reason in THREAD_DIAGNOSTIC_TERMINAL_REASONS:
            return "partial"
        return "continue"

    result = await client.request(
        "get_thread_diagnostics",
        args={"ext_pan_id": normalized_id, "force": force},
        require_schema=12,
        timeout=max(0.001, deadline - loop.time()),
    )
    response_count = 1
    if result is None:
        client.raise_if_reader_failed()
        return SelectedDiagnosticsResult(
            "unavailable", None, response_count, 0, 0, 0, 0, 0, ()
        )
    state = accept(result)
    while state == "continue":
        remaining = deadline - loop.time()
        if remaining <= 0:
            state = "partial" if latest is not None else "timeout"
            break
        try:
            cursor, event = await client.next_event(
                after=cursor, predicate=matching_event, timeout=remaining
            )
        except asyncio.TimeoutError:
            state = "partial" if latest is not None else "timeout"
            break
        event_count += 1
        state = accept(event["data"])
    client.raise_if_reader_failed()
    if state == "partial" and latest is not None:
        write_checkpoint(latest, required=True)
    return SelectedDiagnosticsResult(
        state,
        latest,
        response_count,
        event_count,
        accepted_count,
        stale_count,
        duplicate_count,
        conflict_count,
        tuple(warnings),
    )


def validate_thread_diagnostics_batch(
    value: Any,
    *,
    limits: ThreadValidationLimits = ThreadValidationLimits(),
    path: str = "batch",
) -> dict[str, Any]:
    """Validate and project one native Thread diagnostic batch."""

    def nodes(raw: Any, field_path: str) -> list[dict[str, Any]]:
        values = _array(raw, field_path, limits.max_nodes_per_network)
        return [
            _validate_diagnostic_node(node, f"{field_path}[{index}]", limits)
            for index, node in enumerate(values)
        ]

    validators: dict[str, Validator] = {
        "extPanIdHex": lambda item, item_path: _hex(item, item_path, 16),
        "networkName": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "collectedAt": _safe_uint,
        "source": lambda item, item_path: _enum(item, item_path, THREAD_DIAGNOSTIC_SOURCES),
        "nodes": nodes,
        "partialReason": lambda item, item_path: _enum(
            item, item_path, THREAD_DIAGNOSTIC_PARTIAL_REASONS
        ),
    }
    result = _project_object(
        value,
        path,
        validators,
        required=frozenset(
            {"extPanIdHex", "networkName", "collectedAt", "source", "nodes"}
        ),
        limits=limits,
    )
    assert_snapshot_safe(result)
    return result


def _validate_diagnostic_node(
    value: Any, path: str, limits: ThreadValidationLimits
) -> dict[str, Any]:
    uint8 = lambda item, item_path: _integer(item, item_path, 0, 255)
    uint16 = lambda item, item_path: _integer(item, item_path, 0, 65535)
    uint32 = lambda item, item_path: _integer(item, item_path, 0, (1 << 32) - 1)

    def struct(
        raw: Any,
        field_path: str,
        validators: Mapping[str, Validator],
        required: frozenset[str],
    ) -> dict[str, Any]:
        return _project_object(
            raw, field_path, validators, required=required, limits=limits
        )

    mode_validators: dict[str, Validator] = {
        "rxOnWhenIdle": _boolean,
        "ftd": _boolean,
        "fullNetworkData": _boolean,
    }
    connectivity_validators: dict[str, Validator] = {
        "parentPriority": lambda item, item_path: _integer(item, item_path, -1, 1),
        "linkQuality3": uint8,
        "linkQuality2": uint8,
        "linkQuality1": uint8,
        "leaderCost": uint8,
        "idSequence": uint8,
        "activeRouters": uint8,
        "sedBufferSize": uint16,
        "sedDatagramCount": uint8,
    }
    route_entry_validators: dict[str, Validator] = {
        "routerId": lambda item, item_path: _integer(item, item_path, 0, 63),
        "linkQualityIn": lambda item, item_path: _integer(item, item_path, 0, 3),
        "linkQualityOut": lambda item, item_path: _integer(item, item_path, 0, 3),
        "routeCost": uint8,
    }
    leader_validators: dict[str, Validator] = {
        "partitionId": uint32,
        "weighting": uint8,
        "dataVersion": uint8,
        "stableDataVersion": uint8,
        "leaderRouterId": lambda item, item_path: _integer(item, item_path, 0, 63),
    }
    mac_counter_names = (
        "ifInUnknownProtos",
        "ifInErrors",
        "ifOutErrors",
        "ifInUcastPkts",
        "ifInBroadcastPkts",
        "ifInDiscards",
        "ifOutUcastPkts",
        "ifOutBroadcastPkts",
        "ifOutDiscards",
    )
    mle_uint_names = (
        "disabledRole",
        "detachedRole",
        "childRole",
        "routerRole",
        "leaderRole",
        "attachAttempts",
        "partitionIdChanges",
        "betterPartitionAttachAttempts",
        "parentChanges",
    )
    mle_time_names = (
        "trackedTime",
        "disabledTime",
        "detachedTime",
        "childTime",
        "routerTime",
        "leaderTime",
    )

    def route64(raw: Any, field_path: str) -> dict[str, Any]:
        def entries(item: Any, item_path: str) -> list[dict[str, Any]]:
            values = _array(item, item_path, limits.max_route64_entries_per_node)
            return [
                struct(
                    entry,
                    f"{item_path}[{index}]",
                    route_entry_validators,
                    frozenset(route_entry_validators),
                )
                for index, entry in enumerate(values)
            ]

        validators: dict[str, Validator] = {"idSequence": uint8, "entries": entries}
        return struct(raw, field_path, validators, frozenset(validators))

    def ipv6_addresses(raw: Any, field_path: str) -> list[str]:
        values = _array(raw, field_path, limits.max_ipv6_addresses_per_node)
        return [
            _hex(address, f"{field_path}[{index}]", 32)
            for index, address in enumerate(values)
        ]

    def child_table(raw: Any, field_path: str) -> list[dict[str, Any]]:
        values = _array(raw, field_path, limits.max_child_table_entries_per_node)
        child_validators: dict[str, Validator] = {
            "timeoutExponent": uint8,
            "timeoutSeconds": _safe_uint,
            "incomingLinkQuality": lambda item, item_path: _integer(item, item_path, 0, 3),
            "childId": lambda item, item_path: _integer(item, item_path, 0, 511),
            "mode": lambda item, item_path: struct(
                item, item_path, mode_validators, frozenset(mode_validators)
            ),
        }
        return [
            struct(
                child,
                f"{field_path}[{index}]",
                child_validators,
                frozenset(child_validators),
            )
            for index, child in enumerate(values)
        ]

    def channel_pages(raw: Any, field_path: str) -> list[int]:
        return [
            uint8(page, f"{field_path}[{index}]")
            for index, page in enumerate(_array(raw, field_path, 256))
        ]

    def unknown_tlvs(raw: Any, field_path: str) -> list[dict[str, Any]]:
        values = _array(raw, field_path, limits.max_unknown_tlvs_per_node)
        result: list[dict[str, Any]] = []
        total_hex_bytes = 0
        validators: dict[str, Validator] = {
            "type": uint8,
            "value": lambda item, item_path: _hex(
                item,
                item_path,
                maximum_bytes=limits.max_unknown_tlv_hex_bytes,
            ),
        }
        for index, item in enumerate(values):
            validated = struct(
                item,
                f"{field_path}[{index}]",
                validators,
                frozenset(validators),
            )
            total_hex_bytes += len(validated["value"]) // 2
            if total_hex_bytes > limits.max_unknown_tlv_hex_bytes:
                raise _error(
                    field_path,
                    f"exceeds the decoded hex limit of {limits.max_unknown_tlv_hex_bytes} bytes",
                )
            result.append(validated)
        return result

    validators: dict[str, Validator] = {
        "extMacAddress": lambda item, item_path: _hex(item, item_path, 16),
        "rloc16": uint16,
        "mode": lambda item, item_path: struct(
            item, item_path, mode_validators, frozenset(mode_validators)
        ),
        "timeout": _safe_uint,
        "connectivity": lambda item, item_path: struct(
            item,
            item_path,
            connectivity_validators,
            frozenset(connectivity_validators),
        ),
        "route64": route64,
        "leaderData": lambda item, item_path: struct(
            item, item_path, leader_validators, frozenset(leader_validators)
        ),
        "networkData": lambda item, item_path: _hex(item, item_path),
        "ipv6Addresses": ipv6_addresses,
        "macCounters": lambda item, item_path: struct(
            item,
            item_path,
            {name: uint32 for name in mac_counter_names},
            frozenset(mac_counter_names),
        ),
        "childTable": child_table,
        "channelPages": channel_pages,
        "maxChildTimeout": _safe_uint,
        "eui64": lambda item, item_path: _hex(item, item_path, 16),
        "version": uint16,
        "vendorName": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "vendorModel": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "vendorSwVersion": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "threadStackVersion": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "vendorAppUrl": lambda item, item_path: _text(item, item_path, limits.max_text_bytes),
        "mleCounters": lambda item, item_path: struct(
            item,
            item_path,
            {
                **{name: uint16 for name in mle_uint_names},
                **{name: _uint64_wire for name in mle_time_names},
            },
            frozenset((*mle_uint_names, *mle_time_names)),
        ),
        "batteryLevel": lambda item, item_path: _integer(item, item_path, 0, 100),
        "supplyVoltage": uint16,
        "unknown": unknown_tlvs,
    }
    return _project_object(value, path, validators, limits=limits)