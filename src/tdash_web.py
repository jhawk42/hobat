import os
import argparse
import logging
import http.server
import socketserver
from typing import Sequence

TD_WEB_HOST = ""
TD_WEB_PORT = 8087


class TDashHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler that redirects '/' to '/tdash.html'."""

    def do_GET(self) -> None:
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/tdash.html")
            self.end_headers()
        else:
            super().do_GET()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start the Thread Network Topology Dashboard web server.",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", TD_WEB_HOST),
        help=f"Host/address to bind to (default: '{TD_WEB_HOST}', env: HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", TD_WEB_PORT)),
        help=f"Port to listen on (default: {TD_WEB_PORT}, env: PORT)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

    parser = build_parser()
    args = parser.parse_args(argv)

    Handler = TDashHandler

    with socketserver.TCPServer((args.host, args.port), Handler) as httpd:
        logging.info(f"Serving at http://{args.host or 'localhost'}:{args.port} (/ redirects to /tdash.html)")
        httpd.serve_forever()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())