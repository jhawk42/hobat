"""Command owner for bounded Thread Watch devices collection."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import math
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from td_const import (
    THREAD_WATCH_DEVICES_FILENAME,
    TD_DATA_DIR_ARG_HELP,
)
from td_logging import configure_logging, log_event
from td_network_identity import NetworkScope
from thread_watch_client import (
    THREAD_WATCH_HOST_DEFAULT,
    THREAD_WATCH_HOST_ENV,
    THREAD_WATCH_PORT_DEFAULT,
    THREAD_WATCH_PORT_ENV,
    THREAD_WATCH_URI_ENV,
    ThreadWatchArgumentError,
    ThreadWatchInvalidResponseError,
    ThreadWatchTransportError,
    fetch_thread_watch_devices,
)
from thread_watch_snapshots import (
    ThreadWatchSnapshotSecurityError,
    build_device_snapshot,
)
from util_data import (
    ensure_data_dir_exists,
    network_scope_path,
    resolve_data_dir,
    resolve_data_file_path,
    save_json_atomic,
    write_network_scope,
)


EXIT_OK = 0
EXIT_ARGUMENT = 2
EXIT_CONNECTION = 3
EXIT_PROTOCOL = 4
EXIT_SNAPSHOT = 6
EXIT_PERSISTENCE = 7
EXIT_CANCELLED = 130
PUBLICATION_LOCK_TIMEOUT_SECONDS = 5.0


class ThreadWatchPublicationBusyError(TimeoutError):
    """Another process holds the final/companion publication lock."""


class ThreadWatchPublicationError(OSError):
    """The final or companion could not be published."""


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="td_cli thread-watch",
        description="Collect one bounded Thread Watch devices inventory",
    )
    parser.add_argument(
        "--host",
        default=None,
        help=(
            f"Thread Watch host (default: {THREAD_WATCH_HOST_DEFAULT}; "
            f"environment: {THREAD_WATCH_HOST_ENV})"
        ),
    )
    parser.add_argument(
        "--port",
        default=None,
        help=(
            f"Thread Watch port (default: {THREAD_WATCH_PORT_DEFAULT}; "
            f"environment: {THREAD_WATCH_PORT_ENV})"
        ),
    )
    parser.add_argument(
        "--uri",
        default=None,
        help=f"Override host and port with a root HTTP(S) URL ({THREAD_WATCH_URI_ENV})",
    )
    parser.add_argument("--connect-timeout", type=_positive_float, default=10.0)
    parser.add_argument("--request-timeout", type=_positive_float, default=30.0)
    parser.add_argument("--datadir", help=TD_DATA_DIR_ARG_HELP)
    parser.add_argument("--output", "-o", metavar="FILE")
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--no-stdout-json", action="store_true")
    parser.add_argument("--debug", "-d", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    devices = commands.add_parser("devices", help="Read the complete devices inventory")
    device_commands = devices.add_subparsers(dest="devices_command", required=True)
    device_commands.add_parser(
        "fetch-all", help="Fetch and atomically save all returned device rows"
    )
    return parser


def _resolve_output(args: argparse.Namespace) -> Path:
    data_dir = ensure_data_dir_exists(resolve_data_dir(args.datadir))
    output = resolve_data_file_path(
        args.output or THREAD_WATCH_DEVICES_FILENAME, data_dir
    )
    filename = output.name
    if (
        not filename.endswith(".json")
        or filename.lower().endswith(".network.json")
    ):
        raise ThreadWatchArgumentError(
            "Thread Watch output must end in .json and not .network.json"
        )
    return output


@contextmanager
def publication_lock(output_path: Path, timeout: float = PUBLICATION_LOCK_TIMEOUT_SECONDS):
    lock_path = network_scope_path(output_path).with_name(
        network_scope_path(output_path).name + ".lock"
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock_file:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise ThreadWatchPublicationBusyError(
                        "Thread Watch publication is busy"
                    ) from exc
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _publish(rows: list[dict[str, object]], output_path: Path) -> None:
    try:
        with publication_lock(output_path):
            save_json_atomic(rows, output_path, add_trailing_newline=True)
            write_network_scope(
                output_path,
                NetworkScope(
                    ext_pan_id=None,
                    network_name=None,
                    provenance="unknown",
                    reason="thread-watch-inventory-unscoped",
                    observed_at=datetime.now(timezone.utc).isoformat(),
                    sources=("thread-watch",),
                ),
            )
    except (OSError, TimeoutError, TypeError, ValueError) as exc:
        raise ThreadWatchPublicationError("Thread Watch publication failed") from exc


async def _collect(args: argparse.Namespace, output_path: Path) -> list[dict[str, object]]:
    started = time.monotonic()
    log_event(
        "collection_start",
        source="thread-watch",
        command="devices fetch-all",
        stage="request",
    )
    devices, _endpoint = await fetch_thread_watch_devices(
        args.uri,
        host=args.host,
        port=args.port,
        connect_timeout=args.connect_timeout,
        request_timeout=args.request_timeout,
    )
    snapshot = build_device_snapshot(devices)
    for warning in snapshot.warnings:
        log_event(
            "projection_warning",
            source="thread-watch",
            command="devices fetch-all",
            stage="projection",
            **warning.as_dict(),
        )
    try:
        _publish(snapshot.rows, output_path)
    except Exception:
        log_event(
            "write",
            source="thread-watch",
            command="devices fetch-all",
            stage="publication",
            output=output_path.name,
            records=len(snapshot.rows),
            disposition="failed",
        )
        raise
    log_event(
        "collection_complete",
        source="thread-watch",
        command="devices fetch-all",
        stage="summary",
        records=len(snapshot.rows),
        warnings=len(snapshot.warnings),
        output=output_path.name,
        elapsed_ms=max(0, round((time.monotonic() - started) * 1000)),
    )
    return snapshot.rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        output_path = _resolve_output(args)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_ARGUMENT
    except (ThreadWatchArgumentError, ValueError) as exc:
        print(f"Invalid Thread Watch configuration: {exc}", file=sys.stderr)
        return EXIT_ARGUMENT
    except OSError as exc:
        print(f"Thread Watch cannot prepare output: {exc}", file=sys.stderr)
        return EXIT_PERSISTENCE
    configure_logging(args, parser)
    try:
        rows = asyncio.run(_collect(args, output_path))
    except KeyboardInterrupt:
        return EXIT_CANCELLED
    except asyncio.CancelledError:
        return EXIT_CANCELLED
    except ThreadWatchArgumentError as exc:
        logging.error("Invalid Thread Watch configuration: %s", exc)
        return EXIT_ARGUMENT
    except ThreadWatchTransportError as exc:
        logging.error("Thread Watch collection failed: %s", exc)
        return EXIT_CONNECTION
    except ThreadWatchInvalidResponseError as exc:
        logging.error("Thread Watch response invalid: %s", exc)
        return EXIT_PROTOCOL
    except (ThreadWatchSnapshotSecurityError, TypeError, ValueError) as exc:
        logging.error("Thread Watch snapshot construction failed: %s", exc)
        return EXIT_SNAPSHOT
    except ThreadWatchPublicationError as exc:
        logging.error("Thread Watch publication failed: %s", exc)
        return EXIT_PERSISTENCE
    except OSError as exc:
        logging.error("Thread Watch publication failed: %s", exc)
        return EXIT_PERSISTENCE
    if not args.no_stdout_json:
        json.dump(rows, sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
