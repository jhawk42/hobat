from __future__ import annotations

import argparse
import json
import os
import sys
import time
import logging
from pathlib import Path

from typing import Iterable, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from util_data import data_file_arg_or_default, resolve_td_data_dir
from const import TD_DATA_DIR_ARG_HELP

HOST = "127.0.0.1"
PORT = 8081
BASE_URL = f"http://{HOST}:{PORT}"
HEADERS = {"Accept": "application/vnd.api+json"}
TIMEOUT = 10
RETRIES = 3

# (endpoint path, output file)
DOWNLOAD_TARGETS: Iterable[Tuple[str, str]] = [
    ("/node/dataset/active", "td-otbr-restapi-dataset-active.json"),
    ("/api/devices", "td-otbr-restapi-devices.json"),
    ("/api/diagnostics", "td-otbr-restapi-diagnostics.json"),
]

_ACTIVE_TD_DATA_DIR: Path | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download a fixed set of OTBR REST API endpoints to local JSON files.",
    )
    parser.add_argument("--host", default=HOST, help="OTBR REST API host")
    parser.add_argument("--port", type=int, default=PORT, help="OTBR REST API port")
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    parser.add_argument("--base-url", help="Override host/port with a full base URL")
    parser.add_argument("--timeout", type=int, default=TIMEOUT, help="HTTP timeout in seconds")
    parser.add_argument(
        "--accept",
        default=HEADERS["Accept"],
        help="Accept header sent with each request",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="NAME:VALUE",
        help="Repeatable extra request header, for example 'Authorization: Bearer token'",
    )
    return parser


def build_base_url(host: str, port: int, base_url: str | None = None) -> str:
    return (base_url or f"http://{host}:{port}").rstrip("/")


def build_headers(accept: str, extra_headers: Sequence[str] | None = None) -> dict[str, str]:
    headers = {"Accept": accept}

    for raw_header in extra_headers or []:
        name, separator, value = raw_header.partition(":")
        if not separator:
            raise ValueError(f"Invalid header {raw_header!r}; expected NAME:VALUE")

        normalized_name = name.strip()
        normalized_value = value.strip()
        if not normalized_name:
            raise ValueError(f"Invalid header {raw_header!r}; header name is empty")

        headers[normalized_name] = normalized_value

    return headers


def download_json(url: str, headers: dict[str, str], output_file: str, timeout: int = TIMEOUT, retries: int = RETRIES) -> bool:
    """Download JSON from a URL and save it to a file."""
    request = Request(url=url, headers=headers, method="GET")
    last_exc: Exception | None = None

    for attempt in range(max(1, retries)):
        try:
            with urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                payload = response.read().decode(charset)

            data = json.loads(payload)

            tmp_file = output_file + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            os.replace(tmp_file, output_file)

            logging.info(f"OK: {url} -> {output_file}")
            # log the json data in a human readable format
            logging.info(json.dumps(data, indent=4))
            return True
        except HTTPError as e:
            if e.code < 500:
                logging.error(f"HTTP error for {url}: {e.code} {e.reason}")
                return False
            last_exc = e
            logging.warning(f"HTTP {e.code} on attempt {attempt + 1}/{retries} for {url}: {e.reason}")
        except URLError as e:
            last_exc = e
            logging.warning(f"Network error on attempt {attempt + 1}/{retries} for {url}: {e.reason}")
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON from {url}: {e}")
            return False
        except OSError as e:
            logging.error(f"File write error for {output_file}: {e}")
            return False
        except Exception:
            logging.error(f"Unexpected error for {url}", exc_info=True)
            raise

        if attempt < retries - 1:
            time.sleep(2 ** attempt)

    logging.error(f"All {retries} attempt(s) failed for {url}: {last_exc}")
    return False


def restapi_downloads(base_url: str = BASE_URL, headers: dict[str, str] | None = None, timeout: int = TIMEOUT) -> int:
    failures = 0
    request_headers = dict(headers or HEADERS)

    for endpoint, output_file in DOWNLOAD_TARGETS:
        url = f"{base_url}{endpoint}"
        resolved_output_file = output_file
        if _ACTIVE_TD_DATA_DIR is not None:
            resolved_output_file = str(data_file_arg_or_default(output_file, _ACTIVE_TD_DATA_DIR))

        ok = download_json(url, request_headers, resolved_output_file, timeout=timeout)
        if not ok:
            failures += 1

    if failures:
        logging.error(f"Completed with {failures} failure(s).")
        return 1

    logging.info("All downloads completed successfully.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

    parser = build_parser()
    args = parser.parse_args(argv)

    global _ACTIVE_TD_DATA_DIR
    previous_td_data_dir = _ACTIVE_TD_DATA_DIR
    _ACTIVE_TD_DATA_DIR = resolve_td_data_dir(datadir_arg=args.datadir)

    try:
        base_url = build_base_url(args.host, args.port, args.base_url)
        headers = build_headers(args.accept, args.header)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        return restapi_downloads(base_url=base_url, headers=headers, timeout=args.timeout)
    finally:
        _ACTIVE_TD_DATA_DIR = previous_td_data_dir

if __name__ == "__main__":
    sys.exit(main())
