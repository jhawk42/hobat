import os
import argparse
import logging
import http.server
import socketserver
from functools import partial
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote, urlparse

from util_data import (
    format_data_dir_log_message,
    resolve_data_dir_with_source,
)
from const import TD_DATA_DIR_ARG_HELP

TD_WEB_HOST_ADDR = ""
TD_WEB_HOST_PORT = 8087


class TDashHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler that serves '/tdash.html' for the root path."""

    def __init__(
        self,
        *args,
        directory: str | None = None,
        td_data_dir: Path | None = None,
        **kwargs,
    ) -> None:
        self.td_data_dir = td_data_dir
        super().__init__(*args, directory=directory, **kwargs)

    # Explicit MIME map so that ES modules are served with the correct
    # Content-Type on minimal container images where the OS mime database
    # may be absent or incomplete (browsers reject modules without
    # application/javascript).
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".json": "application/json",
        ".css": "text/css",
        ".html": "text/html",
    }

    def do_GET(self) -> None:
        if self.path == "/":
            self.path = "/tdash.html"

        if self._is_json_request(self.path):
            self._serve_json_from_data_dir(self.path)
            return

        super().do_GET()

    def _is_json_request(self, request_path: str) -> bool:
        parsed = urlparse(request_path)
        return parsed.path.lower().endswith(".json")

    def _resolve_json_file_path(self, request_path: str) -> Path:
        if self.td_data_dir is None:
            raise RuntimeError("TD data directory is not configured")

        parsed = urlparse(request_path)
        request_rel = Path(unquote(parsed.path).lstrip("/"))
        target = (self.td_data_dir / request_rel).resolve()

        if not target.is_relative_to(self.td_data_dir.resolve()):
            raise ValueError("JSON request attempts to escape data directory")

        return target

    def _serve_json_from_data_dir(self, request_path: str) -> None:
        try:
            target = self._resolve_json_file_path(request_path)
        except ValueError:
            self.send_error(404, "File not found")
            return

        if not target.exists() or not target.is_file():
            logging.warning(
                "JSON file not found in td_data_directory: %s", target)
            self.send_error(404, "File not found")
            return

        try:
            with open(target, "rb") as f:
                payload = f.read()
        except OSError:
            self.send_error(500, "Internal server error")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start the Thread Network Topology Dashboard web server.",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", TD_WEB_HOST_ADDR),
        help=f"Host/address to bind to (default: '{TD_WEB_HOST_ADDR}', env: HOST)",
    )
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", TD_WEB_HOST_PORT)),
        help=f"Port to listen on (default: {TD_WEB_HOST_PORT}, env: PORT)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    parser = build_parser()
    args = parser.parse_args(argv)

    static_root = Path(__file__).resolve().parent
    td_data_dir_resolution = resolve_data_dir_with_source(
        datadir_arg=args.datadir)
    td_data_dir = td_data_dir_resolution.path

    logging.info(format_data_dir_log_message(td_data_dir_resolution))

    Handler = partial(
        TDashHandler,
        directory=str(static_root),
        td_data_dir=td_data_dir,
    )

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((args.host, args.port), Handler) as httpd:
        logging.info("Starting tdash webserver dashboard httpd...")
        logging.info(
            f"Serving at http://{args.host or 'localhost'}:{args.port} (/ redirects to /tdash.html)"
        )
        logging.info("Static assets root: %s", static_root)
        logging.info("JSON data root: %s", td_data_dir)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        logging.info("Stopping httpd...")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
