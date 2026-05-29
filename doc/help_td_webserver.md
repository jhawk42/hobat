# td_webserver — Command Reference

usage: python3 -m td_webserver [-h] [--verbose] [--debug] [--host HOST]
                               [--port PORT] [--datadir DATADIR]

Start the Thread Network Topology Dashboard web server.


## Options

```
options:
  -h, --help         show this help message and exit
  --verbose, -v      No-op: INFO logging is the default. Only --debug changes
                     behaviour.
  --debug, -d        Enable debug logging
  --host HOST        Host/address to bind to (default: '', env: HOST)
  --port PORT        Port to listen on (default: 9165, env: PORT)
  --datadir DATADIR  Data directory for JSON reads/writes when TD_DATA_DIR is
                     not set. If omitted and TD_DATA_DIR is unset: use /data
                     when present; otherwise create/use ./data under the
                     current run directory.
```