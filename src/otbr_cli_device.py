"""Explicit, bounded active OTBR device commands."""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import re
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
    ping.add_argument("--timeout", type=_bounded_int(1, PING_MAX_TIMEOUT), default=PING_DEFAULT_TIMEOUT)
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


def _ping_command(args: argparse.Namespace) -> str:
    # Materialize each positional default so later values retain their OpenThread meaning.
    source = f"-I {args.source} " if args.source else ""
    return (
        f"ping {source}{args.target} {args.size} {args.count} {args.interval} "
        f"{args.hop_limit} {args.timeout}"
    )


def _ping_result(output: str, args: argparse.Namespace) -> dict[str, object]:
    samples = [float(value) for value in re.findall(r"(?:time|rtt)=([0-9.]+) ?ms", output)]
    received = len(samples)
    sent = args.count
    error_category = "none"
    if output.startswith("Error:"):
        error_category = "local-dispatch"
    elif received == 0:
        error_category = "timeout"
    result: dict[str, object] = {
        "target": args.target,
        "source": args.source,
        "container": os.getenv(
            util_ot_ctl.TD_OTBR_CONTAINER_NAME_ENV,
            util_ot_ctl.TD_OTBR_CONTAINER_NAME_DEFAULT,
        ),
        "sent": sent,
        "received": received,
        "loss": (sent - received) / sent,
        "roundTripSamplesMs": samples,
        "roundTripSummaryMs": (
            {"min": min(samples), "max": max(samples), "average": sum(samples) / received}
            if samples
            else None
        ),
        "timeoutSeconds": args.timeout,
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "errorCategory": error_category,
        "output": output,
    }
    return result


def _emit(result: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, sort_keys=True))
        return
    print(json.dumps(result, indent=2, sort_keys=True))


def _run_ping(args: argparse.Namespace) -> int:
    if args.count * args.interval + args.timeout > util_ot_ctl.TD_OT_CTL_TIMEOUT_DEFAULT:
        raise ValueError("ping duration exceeds the 30-second OTBR command limit")
    if args.allow_sed:
        logging.warning("Active traffic override requested for a sleepy end device.")
    output = util_ot_ctl.exec_ot_ctl(_ping_command(args))
    _emit(_ping_result(output, args), args.json)
    return 3 if output.startswith("Error:") else 0


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