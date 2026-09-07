"""Explicit, bounded active OTBR device commands."""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Sequence

import util_ot_ctl


PING_DEFAULT_SIZE = 56
PING_DEFAULT_COUNT = 1
PING_DEFAULT_INTERVAL = 1
PING_DEFAULT_HOP_LIMIT = 64
PING_DEFAULT_TIMEOUT = 3
PING_MAX_SIZE = 1024
PING_MAX_COUNT = 10
PING_MAX_INTERVAL = 5
PING_MAX_TIMEOUT = 10
PING_SED_DEFAULT_TIMEOUT = 10


@dataclass(frozen=True)
class PingRequest:
    target: str
    source: str | None = None
    size: int = PING_DEFAULT_SIZE
    count: int = PING_DEFAULT_COUNT
    interval_seconds: int = PING_DEFAULT_INTERVAL
    hop_limit: int = PING_DEFAULT_HOP_LIMIT
    timeout_seconds: int = PING_DEFAULT_TIMEOUT


@dataclass(frozen=True)
class PingResult:
    target: str
    source: str | None
    container: str
    sent: int
    received: int
    loss: float
    round_trip_samples_ms: tuple[float, ...]
    round_trip_summary_ms: dict[str, float] | None
    timeout_seconds: int
    observed_at: str
    error_category: str
    output: str

    def as_json_dict(self) -> dict[str, object]:
        result = asdict(self)
        return {
            "target": result["target"],
            "source": result["source"],
            "container": result["container"],
            "sent": result["sent"],
            "received": result["received"],
            "loss": result["loss"],
            "roundTripSamplesMs": list(result["round_trip_samples_ms"]),
            "roundTripSummaryMs": result["round_trip_summary_ms"],
            "timeoutSeconds": result["timeout_seconds"],
            "observedAt": result["observed_at"],
            "errorCategory": result["error_category"],
            "output": result["output"],
        }


def _unicast_ipv6(value: str) -> str:
    if "%" in value:
        raise argparse.ArgumentTypeError("IPv6 zone identifiers are not supported")
    try:
        address = ipaddress.IPv6Address(value)
    except ipaddress.AddressValueError as exc:
        raise argparse.ArgumentTypeError("must be a valid IPv6 address") from exc
    if (
        address.is_multicast
        or address.is_unspecified
        or address.is_loopback
        or address.is_link_local
            or address.ipv4_mapped is not None
    ):
        raise argparse.ArgumentTypeError("must be a unicast IPv6 address")
    return str(address)


def _bounded_int(minimum: int, maximum: int):
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("must be an integer") from exc
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError(
                f"must be between {minimum} and {maximum}"
            )
        return parsed

    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="td_cli otbr-cli device",
        description="Explicit active Thread device traffic commands.",
    )
    commands = parser.add_subparsers(dest="device_command", required=True)

    ping = commands.add_parser(
        "ping", help="Send bounded active Thread ICMPv6 traffic to one device."
    )
    ping.add_argument("target", type=_unicast_ipv6, metavar="IPV6")
    ping.add_argument("--source", type=_unicast_ipv6, metavar="IPV6")
    ping.add_argument("--size", type=_bounded_int(0, PING_MAX_SIZE), default=PING_DEFAULT_SIZE)
    ping.add_argument("--count", type=_bounded_int(1, PING_MAX_COUNT), default=PING_DEFAULT_COUNT)
    ping.add_argument("--interval", type=_bounded_int(1, PING_MAX_INTERVAL), default=PING_DEFAULT_INTERVAL)
    ping.add_argument("--hop-limit", type=_bounded_int(1, 64), default=PING_DEFAULT_HOP_LIMIT)
    ping.add_argument("--timeout", type=_bounded_int(1, PING_MAX_TIMEOUT), default=None)
    ping.add_argument(
        "--allow-sed",
        action="store_true",
        help="Acknowledge active traffic to a positively identified sleepy end device.",
    )
    ping.add_argument("--json", action="store_true", help="Emit a JSON result.")

    reset = commands.add_parser(
        "reset-counters", help="Destructively request remote MAC and/or MLE counter reset."
    )
    reset.add_argument("target", type=_unicast_ipv6, metavar="IPV6")
    reset.add_argument("--counters", choices=("mac", "mle", "both"), required=True)
    reset.add_argument("--confirm", action="store_true", help="Confirm the destructive request.")
    reset.add_argument("--json", action="store_true", help="Emit a JSON result.")
    return parser


def _ping_command(request: PingRequest) -> str:
    # Materialize each positional default so later values retain their OpenThread meaning.
    source = f"-I {request.source} " if request.source else ""
    return (
        f"ping {source}{request.target} {request.size} {request.count} "
        f"{request.interval_seconds} {request.hop_limit} {request.timeout_seconds}"
    )


def _ping_result(output: str, request: PingRequest) -> PingResult:
    samples = [float(value) for value in re.findall(r"(?:time|rtt)=([0-9.]+) ?ms", output)]
    summary = re.search(r"(\d+) packets transmitted, (\d+) packets received\.", output)
    sent = int(summary.group(1)) if summary else request.count
    received = int(summary.group(2)) if summary else 0
    if output.startswith("Error:"):
        error_category = "local-dispatch"
    elif summary is None:
        error_category = "incomplete-output"
    elif received == 0:
        error_category = "timeout"
    else:
        error_category = "none"
    return PingResult(
        target=request.target,
        source=request.source,
        container=os.getenv(
            util_ot_ctl.TD_OTBR_CONTAINER_NAME_ENV,
            util_ot_ctl.TD_OTBR_CONTAINER_NAME_DEFAULT,
        ),
        sent=sent,
        received=received,
        loss=(sent - received) / sent if sent else 0.0,
        round_trip_samples_ms=tuple(samples),
        round_trip_summary_ms=(
            {"min": min(samples), "max": max(samples), "average": sum(samples) / received}
            if samples and received
            else None
        ),
        timeout_seconds=request.timeout_seconds,
        observed_at=datetime.now(timezone.utc).isoformat(),
        error_category=error_category,
        output=output,
    )


def ping_device(request: PingRequest) -> PingResult:
    if request.count * request.interval_seconds + request.timeout_seconds > util_ot_ctl.TD_OT_CTL_TIMEOUT_DEFAULT:
        raise ValueError("ping duration exceeds the 30-second OTBR command limit")
    return _ping_result(util_ot_ctl.exec_ot_ctl(_ping_command(request)), request)


def _emit(result: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, sort_keys=True))
        return
    print(json.dumps(result, indent=2, sort_keys=True))


def _run_ping(args: argparse.Namespace) -> int:
    if args.allow_sed:
        logging.warning("Active traffic override requested for a sleepy end device.")
    timeout_seconds = (
        args.timeout
        if args.timeout is not None
        else PING_SED_DEFAULT_TIMEOUT if args.allow_sed else PING_DEFAULT_TIMEOUT
    )
    result = ping_device(PingRequest(
        target=args.target,
        source=args.source,
        size=args.size,
        count=args.count,
        interval_seconds=args.interval,
        hop_limit=args.hop_limit,
        timeout_seconds=timeout_seconds,
    ))
    _emit(result.as_json_dict(), args.json)
    return 3 if result.error_category == "local-dispatch" else 0


def _run_reset(args: argparse.Namespace) -> int:
    if not args.confirm:
        raise ValueError("reset-counters requires --confirm")
    tlvs = {"mac": "9", "mle": "34", "both": "9 34"}[args.counters]
    output = util_ot_ctl.exec_ot_ctl(f"networkdiagnostic reset {args.target} {tlvs}")
    accepted = output.rstrip().endswith("Done")
    error_category = "none"
    if not accepted:
        if "unsupported" in output.lower():
            error_category = "unsupported"
        elif output.startswith("Error:"):
            error_category = "local-dispatch"
        else:
            error_category = "remote-rejected"
    result = {
        "target": args.target,
        "counters": args.counters,
        "container": os.getenv(
            util_ot_ctl.TD_OTBR_CONTAINER_NAME_ENV,
            util_ot_ctl.TD_OTBR_CONTAINER_NAME_DEFAULT,
        ),
        "acceptedForTransmission": accepted,
        "errorCategory": error_category,
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "output": output,
    }
    _emit(result, args.json)
    return 0 if accepted else 3


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.device_command == "ping":
        return _run_ping(args)
    return _run_reset(args)