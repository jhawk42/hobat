"""Validation and allowlisted command construction for device actions."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


ACTION_OTBR_PING = "otbr-cli-ping"
ACTION_MATTER_PING = "ha-matter-ws-ping"
ACTION_SYSTEM_PING = "system-ping"
ACTION_OTBR_RESET = "otbr-cli-reset-counters"

PING_ACTIONS = frozenset(
    {ACTION_OTBR_PING, ACTION_MATTER_PING, ACTION_SYSTEM_PING}
)
SUPPORTED_ACTIONS = PING_ACTIONS | {ACTION_OTBR_RESET}
COUNTER_SETS = frozenset({"mac", "mle", "both"})

MAX_ATTEMPTS = 10
MAX_TIMEOUT_SECONDS = 60.0
MAX_DEADLINE_SECONDS = 600.0

_EXT_ADDRESS_RE = re.compile(r"^[0-9a-fA-F]{16}$")
_RLOC16_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]{1,4}$")


class DeviceActionError(ValueError):
    """A device action request does not satisfy the server contract."""


@dataclass(frozen=True)
class DeviceActionRequest:
    action: str
    device_id: str
    source: str
    dataset_files: tuple[str, ...]
    target: str | None
    family: str | None
    node_id: int | None
    attempts: int
    timeout_seconds: float
    deadline_seconds: float
    allow_sed: bool
    counters: str | None
    confirmed: bool


def _bounded_number(
    value: object,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DeviceActionError(f"{name} must be a number")
    parsed = float(value)
    if not minimum <= parsed <= maximum:
        raise DeviceActionError(
            f"{name} must be between {minimum:g} and {maximum:g}"
        )
    return parsed


def _bounded_int(
    value: object,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    parsed = _bounded_number(
        value,
        name=name,
        minimum=float(minimum),
        maximum=float(maximum),
    )
    if not parsed.is_integer():
        raise DeviceActionError(f"{name} must be an integer")
    return int(parsed)


def parse_device_action_request(payload: object) -> DeviceActionRequest:
    if not isinstance(payload, Mapping):
        raise DeviceActionError("request body must be a JSON object")

    allowed_keys = {
        "action",
        "invocationId",
        "deviceId",
        "source",
        "datasetFiles",
        "target",
        "family",
        "nodeId",
        "attempts",
        "timeoutSeconds",
        "deadlineSeconds",
        "allowSed",
        "counters",
        "confirmed",
    }
    unknown = set(payload) - allowed_keys
    if unknown:
        raise DeviceActionError(
            f"unsupported request field(s): {', '.join(sorted(unknown))}"
        )

    action = payload.get("action")
    device_id = payload.get("deviceId")
    source = payload.get("source")
    if action not in SUPPORTED_ACTIONS:
        raise DeviceActionError("unsupported device action")
    if not isinstance(device_id, str) or not device_id.strip():
        raise DeviceActionError("deviceId must be a non-empty string")
    if not isinstance(source, str) or not source.strip():
        raise DeviceActionError("source must be a non-empty string")
    source = source.strip()
    if action in {ACTION_OTBR_PING, ACTION_OTBR_RESET} and source not in {
        "otbr-cli",
        "merged",
    }:
        raise DeviceActionError("OTBR action requires OTBR CLI source evidence")
    if action == ACTION_MATTER_PING and source not in {"ha-matter-ws", "merged"}:
        raise DeviceActionError("Matter action requires HA Matter source evidence")
    if action == ACTION_SYSTEM_PING and source in {"otbr-cli", "ha-matter-ws"}:
        raise DeviceActionError("system ping cannot replace a native source action")

    dataset_files_value = payload.get("datasetFiles")
    if (
        not isinstance(dataset_files_value, Sequence)
        or isinstance(dataset_files_value, (str, bytes))
        or not dataset_files_value
        or len(dataset_files_value) > 16
        or any(not isinstance(item, str) or not item for item in dataset_files_value)
    ):
        raise DeviceActionError("datasetFiles must be a non-empty list of filenames")
    dataset_files = tuple(dataset_files_value)

    attempts = _bounded_int(
        payload.get("attempts", 1),
        name="attempts",
        minimum=1,
        maximum=MAX_ATTEMPTS,
    )
    timeout_seconds = _bounded_number(
        payload.get("timeoutSeconds", 3),
        name="timeoutSeconds",
        minimum=0.1,
        maximum=MAX_TIMEOUT_SECONDS,
    )
    deadline_seconds = _bounded_number(
        payload.get("deadlineSeconds", 30),
        name="deadlineSeconds",
        minimum=0.1,
        maximum=MAX_DEADLINE_SECONDS,
    )
    if action == ACTION_MATTER_PING and attempts > 5:
        raise DeviceActionError("Matter ping attempts must be between 1 and 5")
    if action in {ACTION_OTBR_PING, ACTION_OTBR_RESET}:
        if not timeout_seconds.is_integer() or timeout_seconds > 10:
            raise DeviceActionError(
                "OTBR timeoutSeconds must be an integer between 1 and 10"
            )

    allow_sed = payload.get("allowSed", False)
    confirmed = payload.get("confirmed", False)
    if not isinstance(allow_sed, bool) or not isinstance(confirmed, bool):
        raise DeviceActionError("allowSed and confirmed must be booleans")

    target = payload.get("target")
    family = payload.get("family")
    node_id_value = payload.get("nodeId")
    counters = payload.get("counters")

    if action == ACTION_MATTER_PING:
        if isinstance(node_id_value, bool) or not isinstance(node_id_value, (int, str)):
            raise DeviceActionError("nodeId must be an integer or decimal string")
        try:
            node_id_value = int(node_id_value)
        except ValueError as exc:
            raise DeviceActionError("nodeId must be an integer or decimal string") from exc
        if not 0 <= node_id_value <= (2**64 - 1):
            raise DeviceActionError("nodeId must be an unsigned 64-bit integer")
        if target is not None or family is not None:
            raise DeviceActionError("Matter ping does not accept an address target")
    else:
        node_id_value = None
        if not isinstance(target, str):
            raise DeviceActionError("target must be a literal IP address")
        target, normalized_family = normalize_unicast_address(target)
        if action in {ACTION_OTBR_PING, ACTION_OTBR_RESET} and normalized_family != "ipv6":
            raise DeviceActionError("OTBR device actions require an IPv6 target")
        if family is not None and family != normalized_family:
            raise DeviceActionError("family does not match target address")
        family = normalized_family

    if action == ACTION_OTBR_RESET:
        if counters not in COUNTER_SETS:
            raise DeviceActionError("counters must be mac, mle, or both")
        if not confirmed:
            raise DeviceActionError("reset-counters requires confirmation")
    elif counters is not None or confirmed:
        raise DeviceActionError("ping actions do not accept reset options")

    return DeviceActionRequest(
        action=action,
        device_id=device_id.strip(),
        source=source,
        dataset_files=dataset_files,
        target=target,
        family=family,
        node_id=node_id_value,
        attempts=attempts,
        timeout_seconds=timeout_seconds,
        deadline_seconds=deadline_seconds,
        allow_sed=allow_sed,
        counters=counters,
        confirmed=confirmed,
    )


def normalize_unicast_address(value: str) -> tuple[str, str]:
    if "%" in value:
        raise DeviceActionError("IPv6 zone identifiers are not supported")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise DeviceActionError("target must be a literal IP address") from exc
    if (
        address.is_multicast
        or address.is_unspecified
        or address.is_loopback
        or address.is_link_local
    ):
        raise DeviceActionError("target must be an eligible unicast IP address")
    return str(address), f"ipv{address.version}"


def _nested_value(record: Mapping[str, Any], path: Sequence[str]) -> object:
    current: object = record
    for part in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def record_device_ids(record: Mapping[str, Any]) -> set[str]:
    identities: set[str] = set()
    for key in ("extAddress", "extaddr", "eui64", "eui"):
        value = record.get(key)
        if isinstance(value, str):
            normalized = value.replace(":", "").replace("-", "")
            if _EXT_ADDRESS_RE.fullmatch(normalized):
                identities.add(f"extAddress:{normalized.lower()}")

    node_id = _nested_value(record, ("matter", "nodeId"))
    if node_id is None:
        node_id = record.get("nodeId")
    try:
        if not isinstance(node_id, bool) and node_id is not None:
            parsed_node_id = int(str(node_id), 0)
            if 0 <= parsed_node_id <= (2**64 - 1):
                identities.add(f"matterNode:{parsed_node_id}")
    except ValueError:
        pass

    for key in ("rloc16", "RLOC16"):
        value = record.get(key)
        if isinstance(value, (str, int)):
            text = str(value)
            if isinstance(value, int) or _RLOC16_RE.fullmatch(text):
                parsed = value if isinstance(value, int) else int(text, 16)
                if 0 <= parsed <= 0xFFFF:
                    identities.add(f"rloc16:{parsed:04x}")

    for key in ("id", "ID"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            identities.add(f"id:{value.strip()}")
    return identities


def _iter_address_values(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            if isinstance(item, str):
                yield item
            elif isinstance(item, Mapping):
                for key in ("address", "ipAddress", "ip"):
                    candidate = item.get(key)
                    if isinstance(candidate, str):
                        yield candidate


def eligible_record_addresses(record: Mapping[str, Any]) -> list[dict[str, str]]:
    paths = (
        ("omrIpv6Address",),
        ("omrIpv6Addr",),
        ("omr_ipv6_addr",),
        ("peerAddress",),
        ("ipv6Addresses",),
        ("ipv6_addresses",),
        ("addresses",),
        ("serviceInfo", "addressesParsed"),
        ("networkInterfaces",),
    )
    candidates: dict[str, dict[str, str]] = {}
    for path in paths:
        value = _nested_value(record, path)
        for raw_address in _iter_address_values(value):
            try:
                address, family = normalize_unicast_address(raw_address)
            except DeviceActionError:
                continue
            candidates.setdefault(
                address,
                {
                    "address": address,
                    "family": family,
                    "provenance": ".".join(path),
                },
            )
    return list(candidates.values())


def record_is_sleepy(record: Mapping[str, Any]) -> bool:
    mode = record.get("mode")
    rx_on_when_idle = mode.get("rxOnWhenIdle") if isinstance(mode, Mapping) else None
    if rx_on_when_idle is False:
        return True
    values = (record.get("type"), record.get("role"), record.get("Role"))
    return any(
        isinstance(value, str)
        and value.lower().replace("-", "").replace(" ", "")
        in {"sleepychild", "sleepyenddevice", "sed"}
        for value in values
    )


def build_cli_args(request: DeviceActionRequest) -> list[str]:
    if request.action == ACTION_OTBR_PING:
        args = [
            "otbr-cli",
            "device",
            "ping",
            request.target or "",
            "--count",
            str(request.attempts),
            "--timeout",
            str(int(request.timeout_seconds)),
            "--json",
        ]
        if request.allow_sed:
            args.append("--allow-sed")
        return args
    if request.action == ACTION_MATTER_PING:
        return [
            "ha-matter-ws",
            "device",
            "ping",
            "--node-id",
            str(request.node_id),
            "--attempts",
            str(request.attempts),
        ]
    if request.action == ACTION_SYSTEM_PING:
        return [
            "system",
            "device",
            "ping",
            "--address",
            request.target or "",
            "--family",
            request.family or "auto",
            "--attempts",
            str(request.attempts),
            "--timeout",
            f"{request.timeout_seconds:g}",
            "--deadline",
            f"{request.deadline_seconds:g}",
        ]
    return [
        "otbr-cli",
        "device",
        "reset-counters",
        request.target or "",
        "--counters",
        request.counters or "",
        "--confirm",
        "--json",
    ]


def validate_request_against_record(
    request: DeviceActionRequest,
    record: Mapping[str, Any],
) -> None:
    if request.device_id not in record_device_ids(record):
        raise DeviceActionError("device identity does not match cached record")

    if request.action == ACTION_MATTER_PING:
        record_node_ids = {
            int(identity.split(":", 1)[1])
            for identity in record_device_ids(record)
            if identity.startswith("matterNode:")
        }
        if request.node_id not in record_node_ids:
            raise DeviceActionError("Matter node ID does not match cached record")
        return

    addresses = {item["address"] for item in eligible_record_addresses(record)}
    if request.target not in addresses:
        raise DeviceActionError("target does not match an eligible cached address")
    if record_is_sleepy(record) and not request.allow_sed and request.action == ACTION_OTBR_PING:
        raise DeviceActionError("sleepy device ping requires acknowledgement")


def normalize_action_result(
    request: DeviceActionRequest,
    payload: Mapping[str, Any],
    *,
    exit_code: int,
    duration_seconds: float,
) -> dict[str, Any]:
    status = "failed"
    detail = ""
    if request.action == ACTION_OTBR_PING:
        sent = payload.get("sent")
        received = payload.get("received")
        error_category = str(payload.get("errorCategory", "none"))
        if error_category not in {"none", "timeout"}:
            status = "failed"
            detail = error_category
        elif isinstance(sent, int) and isinstance(received, int):
            status = (
                "success"
                if sent > 0 and received == sent
                else "partial-success"
                if received > 0
                else "no-response"
            )
    elif request.action == ACTION_MATTER_PING:
        status = {
            "success": "success",
            "partial-success": "partial-success",
            "all-address-failure": "no-response",
            "no-addresses": "no-addresses",
            "request-timeout": "timed-out",
            "command-unsupported": "unsupported",
            "command-error": "protocol-error",
            "protocol-error": "protocol-error",
            "transport-failure": "transport-failure",
        }.get(str(payload.get("outcome")), "failed")
    elif request.action == ACTION_SYSTEM_PING:
        status = {
            "success": "success",
            "partial-success": "partial-success",
            "unreachable": "no-response",
            "attempt-timeout": "timed-out",
            "deadline-exceeded": "deadline-exceeded",
            "missing-executable": "local-dispatch-failure",
            "unsupported-platform": "unsupported",
            "process-failure": "local-dispatch-failure",
            "invalid-address": "failed",
        }.get(str(payload.get("outcome")), "failed")
    else:
        accepted = payload.get("acceptedForTransmission") is True
        status = "accepted-for-transmission" if accepted else "failed"
        detail = str(payload.get("errorCategory", ""))

    if exit_code != 0 and status == "success":
        status = "failed"
    error = payload.get("error")
    if isinstance(error, str) and error:
        detail = error[:512]

    result: dict[str, Any] = {
        "action": request.action,
        "targetKind": "matter-node" if request.node_id is not None else request.family,
        "target": request.node_id if request.node_id is not None else request.target,
        "status": status,
        "observedAt": payload.get("observedAt"),
        "durationSeconds": round(duration_seconds, 6),
    }
    if detail:
        result["detail"] = detail

    allowed_result_fields = {
        ACTION_OTBR_PING: (
            "sent",
            "received",
            "loss",
            "roundTripSamplesMs",
            "roundTripSummaryMs",
        ),
        ACTION_MATTER_PING: ("attempts", "addresses", "results"),
        ACTION_SYSTEM_PING: (
            "attemptsRequested",
            "attemptsCompleted",
            "attempts",
            "elapsedSeconds",
        ),
        ACTION_OTBR_RESET: ("counters", "acceptedForTransmission"),
    }[request.action]
    for key in allowed_result_fields:
        if key in payload:
            result[key] = payload[key]
    return result
