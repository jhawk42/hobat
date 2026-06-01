from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence, Tuple

from otbr_restapi_util import (
    OTBRActionFailedError,
    OTBRActionTimeoutError,
    OTBRClientError,
    OTBRRestApiClient,
    emit_rest_payload_output,
)
from util_data import resolve_data_file_path


def download_static_endpoints(
    client: OTBRRestApiClient,
    data_dir: Path,
    static_endpoints: Sequence[Tuple[str, str]],
) -> int:
    failures = 0
    logger = logging.getLogger(__name__)

    for method_name, filename in static_endpoints:
        output_file = resolve_data_file_path(filename, data_dir)
        method = getattr(client, method_name)
        try:
            data = method(raw=True)
            emit_rest_payload_output(data, output_file, logger)
            logging.info("OK: %s -> %s", method_name, output_file)
        except OTBRClientError as exc:
            logging.error("Failed to download %s: %s", method_name, exc)
            failures += 1
        except OSError as exc:
            logging.error("File write error for %s: %s", output_file, exc)
            failures += 1

    return failures


def save_device_diagnostics(
    client: OTBRRestApiClient,
    data_dir: Path,
    diag_types: list[str],
) -> int:
    try:
        devices = client.list_devices(raw=False)
    except OTBRClientError as exc:
        logging.error("Failed to list devices for diagnostics: %s", exc)
        return 1

    if not devices:
        logging.info("No devices found; skipping diagnostics.")
        return 0

    failures = 0
    logger = logging.getLogger(__name__)
    for device in devices:
        device_id = device.get("id") if isinstance(device, dict) else None
        if not device_id:
            continue
        filename = f"td-otbr-restapi-diagnostic-{device_id}.json"
        output_file = resolve_data_file_path(filename, data_dir)
        try:
            diag = client.fetch_device_diagnostics(device_id, types=diag_types, raw=True)
            emit_rest_payload_output(diag, output_file, logger)
            logging.info("Diagnostic saved: %s -> %s", device_id, output_file)
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
