import os
import argparse
import logging
import http.server
import socketserver
from typing import Sequence

TD_WEB_HOST = ""
TD_WEB_PORT = 8087


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

    Handler = http.server.SimpleHTTPRequestHandler

    with socketserver.TCPServer((args.host, args.port), Handler) as httpd:
        logging.info(f"Serving at http://{args.host or 'localhost'}:{args.port}")
        httpd.serve_forever()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())