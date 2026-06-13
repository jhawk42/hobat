# td_webserver — Command Reference

usage: python3 -m td_webserver [-h] [--verbose] [--debug] [--host HOST]
                               [--port PORT] [--file-cache-max-age SECONDS]
                               [--datadir DATADIR]

Start the Thread Network Topology Dashboard web server.

When the webserver regenerates data files by invoking `td_cli`, it surfaces the underlying command return codes instead of normalizing them away. That matters for empty- or partial-data-directory runs, where missing local inputs now distinguish rc `4` from runtime rc `3` and invalid-payload rc `5`.


## Options

```
options:
  -h, --help         show this help message and exit
  --verbose, -v      No-op: INFO logging is the default. Only --debug changes
                     behaviour.
  --debug, -d        Enable debug logging
  --host HOST        Host/address to bind to (default: '', env: HOST)
  --port PORT        Port to listen on (default: 9165, env: PORT)
  --file-cache-max-age SECONDS
                     Default max-age in seconds for data files
                     (CLI > TD_FILE_CACHE_MAX_AGE > 86400)
  --datadir DATADIR  Data directory for JSON reads/writes (takes precedence
                     over TD_DATA_DIR). If omitted and TD_DATA_DIR is unset:
                     use /data
                     when present; otherwise create/use ./data under the
                     current run directory.
```