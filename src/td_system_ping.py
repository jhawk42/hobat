"""Bounded, platform-aware host ICMP probing for system commands."""

from __future__ import annotations

import ipaddress
import math
import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any


EXIT_OK = 0
EXIT_PARTIAL = 2
EXIT_UNREACHABLE = 3
EXIT_ATTEMPT_TIMEOUT = 4
EXIT_DEADLINE = 5
EXIT_INVALID_ADDRESS = 6
EXIT_MISSING_EXECUTABLE = 7
EXIT_UNSUPPORTED = 8
EXIT_PROCESS_FAILURE = 9
MAX_ATTEMPTS = 10
MAX_TIMEOUT_SECONDS = 60.0
MAX_DEADLINE_SECONDS = 600.0


class SystemPingArgumentError(ValueError):
    """A system ping option is invalid."""


def validate_request(address: str, family: str, attempts: int, timeout: float, deadline: float) -> tuple[str, str]:
    if family not in {"auto", "ipv4", "ipv6"}:
        raise SystemPingArgumentError(f"unsupported address family: {family}")
    if "%" in address:
        raise SystemPingArgumentError("IPv6 zone identifiers are not supported")
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise SystemPingArgumentError(f"invalid IP address: {address}") from exc
    if parsed.is_multicast or parsed.is_unspecified or parsed.is_link_local:
        raise SystemPingArgumentError("address must be a unicast IP address")
    normalized_family = f"ipv{parsed.version}"
    if family != "auto" and family != normalized_family:
        raise SystemPingArgumentError(
            f"--family {family} does not match {normalized_family} address"
        )
    if not 1 <= attempts <= MAX_ATTEMPTS:
        raise SystemPingArgumentError(f"--attempts must be between 1 and {MAX_ATTEMPTS}")
    if not 0 < timeout <= MAX_TIMEOUT_SECONDS:
        raise SystemPingArgumentError(
            f"--timeout must be greater than zero and at most {MAX_TIMEOUT_SECONDS:g}"
        )
    if not 0 < deadline <= MAX_DEADLINE_SECONDS:
        raise SystemPingArgumentError(
            f"--deadline must be greater than zero and at most {MAX_DEADLINE_SECONDS:g}"
        )
    return str(parsed), normalized_family


def build_ping_command(system: str, executable: str, address: str, family: str, timeout: float) -> list[str]:
    """Build one platform-native, single-echo command without a shell."""
    family_flag = "-4" if family == "ipv4" else "-6"
    if system == "Linux":
        return [executable, family_flag, "-c", "1", "-W", str(math.ceil(timeout)), address]
    if system == "Darwin":
        return [
            executable,
            family_flag,
            "-c",
            "1",
            "-W",
            str(math.ceil(timeout * 1000)),
            address,
        ]
    if system == "Windows":
        return [
            executable,
            family_flag,
            "-n",
            "1",
            "-w",
            str(math.ceil(timeout * 1000)),
            address,
        ]
    raise SystemPingArgumentError(f"unsupported platform: {system}")


def _payload(address: str, family: str, attempts: int, started: float, records: list[dict[str, Any]], outcome: str, error: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "address": address,
        "family": family,
        "attemptsRequested": attempts,
        "attemptsCompleted": len(records),
        "attempts": records,
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "elapsedSeconds": round(time.monotonic() - started, 6),
        "outcome": outcome,
    }
    if error:
        result["error"] = error
    return result


def _terminate(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def run_ping(address: str, family: str, attempts: int, timeout: float, deadline: float) -> tuple[dict[str, Any], int]:
    """Probe one literal address, returning a JSON-safe payload and stable exit code."""
    started = time.monotonic()
    try:
        address, family = validate_request(address, family, attempts, timeout, deadline)
    except SystemPingArgumentError as exc:
        return _payload(address, family, attempts, started, [], "invalid-address", str(exc)), EXIT_INVALID_ADDRESS

    system = platform.system()
    try:
        command = build_ping_command(system, "ping", address, family, timeout)
    except SystemPingArgumentError as exc:
        return _payload(address, family, attempts, started, [], "unsupported-platform", str(exc)), EXIT_UNSUPPORTED
    executable = shutil.which(command[0])
    if not executable:
        return _payload(address, family, attempts, started, [], "missing-executable", "ping executable not found"), EXIT_MISSING_EXECUTABLE

    records: list[dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        remaining = deadline - (time.monotonic() - started)
        if remaining <= 0:
            return _payload(address, family, attempts, started, records, "deadline-exceeded"), EXIT_DEADLINE
        command = build_ping_command(system, executable, address, family, min(timeout, remaining))
        attempt_started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return _payload(address, family, attempts, started, records, "missing-executable", "ping executable not found"), EXIT_MISSING_EXECUTABLE
        except OSError as exc:
            return _payload(address, family, attempts, started, records, "process-failure", str(exc)), EXIT_PROCESS_FAILURE
        try:
            process.wait(timeout=min(timeout, remaining))
        except subprocess.TimeoutExpired:
            _terminate(process)
            records.append({"attempt": attempt, "outcome": "attempt-timeout", "durationSeconds": round(time.monotonic() - attempt_started, 6)})
            continue
        except BaseException:
            _terminate(process)
            raise
        records.append({"attempt": attempt, "outcome": "success" if process.returncode == 0 else "unreachable", "exitStatus": process.returncode, "durationSeconds": round(time.monotonic() - attempt_started, 6)})

    successes = sum(record["outcome"] == "success" for record in records)
    if successes == attempts:
        return _payload(address, family, attempts, started, records, "success"), EXIT_OK
    if successes:
        return _payload(address, family, attempts, started, records, "partial-success"), EXIT_PARTIAL
    if any(record["outcome"] == "attempt-timeout" for record in records):
        return _payload(address, family, attempts, started, records, "attempt-timeout"), EXIT_ATTEMPT_TIMEOUT
    return _payload(address, family, attempts, started, records, "unreachable"), EXIT_UNREACHABLE