from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Sequence, Tuple

from td_const import TD_DATA_DIR_ARG_HELP
from otbr_restapi_util import (
    RECOMMENDED_DIAGNOSTIC_TLVS,
    OTBRActionFailedError,
    OTBRActionTimeoutError,
    OTBRClientError,
    OTBRRestApiClient,
)
from util_data import resolve_data_dir, resolve_data_file_path, save_json_atomic

HOST = "127.0.0.1"
PORT = 8081
TIMEOUT = 10
DEFAULT_ACCEPT = "application/vnd.api+json"

# (client method name, output filename) – static endpoints downloaded unconditionally
_STATIC_ENDPOINTS: Sequence[Tuple[str, str]] = [
    ("get_active_dataset", "td-otbr-restapi-dataset-active.json"),
    ("list_devices",       "td-otbr-restapi-devices.json"),
    ("list_diagnostics",   "td-otbr-restapi-diagnostics.json"),
]

# Active data-dir context used by direct-entry verification tests.
_ACTIVE_TD_DATA_DIR: Path | None = None


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download OTBR REST API endpoints to local JSON files. "
            "Optionally trigger a device collection update and fetch "
            "per-device network diagnostics."
        ),
    )
    parser.add_argument("--host", default=HOST, help="OTBR REST API host")
    parser.add_argument("--port", type=int, default=PORT,
                        help="OTBR REST API port")
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    parser.add_argument("--base-url",
                        help="Override host/port with a full base URL")
    parser.add_argument("--timeout", type=int, default=TIMEOUT,
                        help="HTTP timeout in seconds")
    parser.add_argument("--accept", default=DEFAULT_ACCEPT,
                        help="Accept header sent with each request")
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="NAME:VALUE",
        help="Repeatable extra request header, e.g. 'Authorization: Bearer token'",
    )
    # 5.4 – optional device collection update
    parser.add_argument(
        "--update-devices",
        action="store_true",
        default=False,
        help=(
            "Trigger updateDeviceCollectionTask before downloading /api/devices, "
            "then wait for it to complete."
        ),
    )
    # 5.5 – optional per-device diagnostics
    parser.add_argument(
        "--fetch-diagnostics",
        action="store_true",
        default=False,
        help=(
            "For each device in the device collection, enqueue and wait for "
            "getNetworkDiagnosticTask and save each result to a separate file."
        ),
    )
    parser.add_argument(
        "--diag-types",
        nargs="+",
        default=None,
        metavar="TLV",
        help=(
            "TLV names to request for --fetch-diagnostics. "
            "Defaults to RECOMMENDED_DIAGNOSTIC_TLVS when omitted."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_extra_headers(raw_headers: Sequence[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw in raw_headers:
        name, separator, value = raw.partition(":")
        if not separator:
            raise ValueError(f"Invalid header {raw!r}; expected NAME:VALUE")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError(f"Invalid header {raw!r}; header name is empty")
        headers[normalized_name] = value.strip()
    return headers


def build_base_url(host: str, port: int, base_url: str | None = None) -> str:
    """Build normalized base URL, preferring explicit base_url when provided."""
    return (base_url or f"http://{host}:{port}").rstrip("/")


def build_headers(accept: str, raw_headers: Sequence[str]) -> dict[str, str]:
    """Build request headers dict from Accept plus repeatable NAME:VALUE pairs."""
    headers = {"Accept": accept}
    headers.update(_parse_extra_headers(raw_headers))
    return headers


def _build_client_from_options(
    *,
    base_url: str,
    timeout: int,
    headers: dict[str, str],
) -> OTBRRestApiClient:
    """Construct OTBRRestApiClient from normalized network options."""
    extra_header_names = [k for k in headers.keys() if k.lower() != "accept"]
    if extra_header_names:
        logging.warning(
            "Extra headers beyond Accept are not forwarded by OTBRRestApiClient: %s",
            extra_header_names,
        )
    return OTBRRestApiClient(
        base_url=base_url,
        timeout=timeout,
        accept=headers.get("Accept", DEFAULT_ACCEPT),
    )


# ---------------------------------------------------------------------------
# Core download logic
# ---------------------------------------------------------------------------

def download_all_restapi_endpoints(
    client: OTBRRestApiClient | None = None,
    data_dir: Path | None = None,
    *,
    base_url: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = TIMEOUT,
    update_devices: bool = False,
) -> int:
    """
    Download the three fixed static endpoints to local JSON files.

    Args:
        client: Configured OTBRRestApiClient instance.
        data_dir: Directory where output files are written.
        update_devices: When True, trigger updateDeviceCollectionTask before
                        downloading /api/devices.

    Returns:
        Exit code: 0 on full success, 1 if any download failed.
    """
    if client is None:
        effective_base_url = (base_url or f"http://{HOST}:{PORT}").rstrip("/")
        effective_headers = headers or {"Accept": DEFAULT_ACCEPT}
        client = _build_client_from_options(
            base_url=effective_base_url,
            timeout=timeout,
            headers=effective_headers,
        )

    if data_dir is None:
        data_dir = _ACTIVE_TD_DATA_DIR or resolve_data_dir(data_dir=None)

    failures = 0

    # Optionally refresh device collection first
    if update_devices:
        logging.info("Triggering updateDeviceCollectionTask …")
        try:
            client.trigger_and_wait_device_collection()
            logging.info("Device collection update completed.")
        except (OTBRActionFailedError, OTBRActionTimeoutError) as exc:
            logging.warning(
                "Device collection update did not complete cleanly: %s", exc)
        except OTBRClientError as exc:
            logging.warning("Device collection update failed: %s", exc)

    for method_name, filename in _STATIC_ENDPOINTS:
        output_file = resolve_data_file_path(filename, data_dir)
        method = getattr(client, method_name)
        try:
            data = method(raw=True)
            save_json_atomic(data, output_file)
            logging.info("OK: %s -> %s", method_name, output_file)
            logging.debug("Saved %s data into %s as JSON:\n%s",
                method_name, output_file, json.dumps(data, indent=4))
        except OTBRClientError as exc:
            logging.error("Failed to download %s: %s", method_name, exc)
            failures += 1
        except OSError as exc:
            logging.error("File write error for %s: %s", output_file, exc)
            failures += 1

    if failures:
        logging.error("Completed with %d failure(s).", failures)
        return 1

    logging.info("All downloads completed successfully.")
    return 0


def fetch_and_save_diagnostics(
    client: OTBRRestApiClient,
    data_dir: Path,
    diag_types: list[str],
) -> int:
    """
    5.5 – For each device in /api/devices, enqueue getNetworkDiagnosticTask,
    wait for the result, and save to td-otbr-restapi-diagnostic-{device_id}.json.

    Returns:
        Exit code: 0 on full success, 1 if any device diagnostic failed.
    """
    try:
        devices = client.list_devices(raw=False)
    except OTBRClientError as exc:
        logging.error("Failed to list devices for diagnostics: %s", exc)
        return 1

    if not devices:
        logging.info("No devices found; skipping diagnostics.")
        return 0

    failures = 0
    for device in devices:
        device_id = device.get("id") if isinstance(device, dict) else None
        if not device_id:
            continue
        filename = f"td-otbr-restapi-diagnostic-{device_id}.json"
        output_file = resolve_data_file_path(filename, data_dir)
        try:
            diag = client.fetch_device_diagnostics(
                device_id, types=diag_types, raw=True
            )
            save_json_atomic(diag, output_file)
            logging.info("Diagnostic saved: %s -> %s", device_id, output_file)
            logging.debug("Saved diagnostic data for %s into %s as JSON:\n%s",
                device_id, output_file, json.dumps(diag, indent=4))
        except (OTBRActionFailedError, OTBRActionTimeoutError) as exc:
            logging.warning("Diagnostic skipped for %s: %s", device_id, exc)
            failures += 1
        except OTBRClientError as exc:
            logging.error("Diagnostic error for %s: %s", device_id, exc)
            failures += 1
        except OSError as exc:
            logging.error("File write error for %s: %s", output_file, exc)
            failures += 1

    if failures:
        logging.warning("Diagnostics completed with %d failure(s).", failures)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        headers = build_headers(args.accept, args.header)
    except ValueError as exc:
        parser.error(str(exc))

    data_dir = resolve_data_dir(data_dir=args.datadir)
    base_url = build_base_url(args.host, args.port, args.base_url)

    global _ACTIVE_TD_DATA_DIR
    _ACTIVE_TD_DATA_DIR = data_dir
    try:
        if args.update_devices:
            exit_code = download_all_restapi_endpoints(
                base_url=base_url,
                headers=headers,
                timeout=args.timeout,
                update_devices=True,
            )
        else:
            exit_code = download_all_restapi_endpoints(
                base_url=base_url,
                headers=headers,
                timeout=args.timeout,
            )

        if args.fetch_diagnostics:
            diag_types = args.diag_types or list(RECOMMENDED_DIAGNOSTIC_TLVS)
            client = _build_client_from_options(
                base_url=base_url,
                timeout=args.timeout,
                headers=headers,
            )
            diag_exit = fetch_and_save_diagnostics(client, data_dir, diag_types)
            if diag_exit != 0:
                exit_code = diag_exit

        return exit_code
    finally:
        _ACTIVE_TD_DATA_DIR = None


if __name__ == "__main__":
    sys.exit(main())
