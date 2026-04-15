import http.server
import socketserver
import logging

TD_WEB_PORT = 8087
PORT = TD_WEB_PORT

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

Handler = http.server.SimpleHTTPRequestHandler

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    logging.info(f"Serving at port {PORT}")
    httpd.serve_forever()
