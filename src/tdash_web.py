import http.server
import socketserver

TD_WEB_PORT = 8087
PORT = TD_WEB_PORT

Handler = http.server.SimpleHTTPRequestHandler

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"Serving at port {PORT}")
    httpd.serve_forever()
