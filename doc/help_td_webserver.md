usage: td_webserver.py [-h] [--verbose] [--debug] [--host HOST] [--port PORT] [--datadir DATADIR]

Start the Thread Network Topology Dashboard web server.

options:
  -h, --help         show this help message and exit
  --verbose, -v      Enable verbose (INFO) logging
  --debug, -d        Enable debug logging
  --host HOST        Host/address to bind to (default: '', env: HOST)
  --port PORT        Port to listen on (default: 8087, env: PORT)
  --datadir DATADIR  Data directory for JSON reads/writes when TD_DATA_DIR is not set. If omitted and TD_DATA_DIR is unset:
                     use /data when present; otherwise create/use ./data under the current run directory.
  