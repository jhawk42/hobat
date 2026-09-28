# td_webserver — Command Reference

usage: python3 -m td_webserver [-h] [--verbose] [--debug]
                               [--log-thread-secrets] [--host HOST]
                               [--port PORT] [--file-cache-max-age SECONDS]
                               [--datadir DATADIR] [--disable-device-actions]
                               [--disable-device-reset]

Start the Thread Network Topology Dashboard web server.

When the webserver regenerates data files by invoking `td_cli`, it surfaces the underlying command return codes instead of normalizing them away. That matters for empty- or partial-data-directory runs, where missing local inputs now distinguish rc `4` from runtime rc `3` and invalid-payload rc `5`.

The root route redirects to `/tdash.html`. Data requests use the allowlisted
`/api/data/{filename}` endpoint. Fresh files are served from cache; stale or
missing dynamic files invoke `td_cli` unless the browser requests Cache Only.
Short actions are awaited. Long or forced-background actions return HTTP 202
and are polled through `/api/job/{job_id}`; running jobs can be cancelled with
DELETE on the same route.

Logging uses `--debug`/`-d`, then `--verbose`/`-v`, then
`TD_DEBUG_LEVEL`, then INFO. The environment accepts `DEBUG`, `INFO`,
`WARNING`, or `ERROR` case-insensitively with surrounding whitespace ignored.
An invalid value exits with status 2 before server startup unless a CLI level
switch overrides it; `--debug` wins if both switches are given. Child CLI
processes inherit the environment and resolve their own level.

DEBUG may include HTTP traffic and `ot-ctl` diagnostics, but Thread Network Key
and PSKc values are redacted by default, including captured child output. The
false-by-default `--log-thread-secrets` option is forwarded only to OTBR REST
data jobs and disables redaction only in REST DEBUG response-body logs. It does
not affect stdout, saved snapshots, or other child jobs. Opt in only when log
access and retention are controlled; the option is not exposed through HTTP.

Example:

```bash
TD_DEBUG_LEVEL=' debug ' PYTHONPATH=src python3 -m td_webserver --datadir ./data
```

Data files use `Cache-Control`, `Last-Modified`, and ETag revalidation. Static
HTML, CSS, and JavaScript use `Cache-Control: no-cache`. Progressive
`.partial.json` checkpoints are served without triggering regeneration.
Device labels are read and updated through `GET`/`PATCH
/api/device/{extAddress}` and use `Cache-Control: no-store`.

Active Device Diagnostics use `POST /api/device-actions` and the distinct
`/api/device-action-jobs/{job_id}` polling and cancellation resource. These
responses use `Cache-Control: no-store`, results remain in memory for bounded
polling, and no action writes a snapshot or checkpoint. Ping and Reset Counters
are enabled by default. `--disable-device-actions` or a false
`TD_DEVICE_ACTIONS_ENABLED` value disables all actions. `--disable-device-reset`
or a false `TD_DEVICE_RESET_ENABLED` value disables only Reset Counters.

Browser API access is same-origin. API responses do not include CORS
authorization headers, and cross-origin preflights for mutating methods are not
handled. Changing `--host` or deploying behind a reverse proxy does not add an
origin allowlist; serve the dashboard and API through the same browser origin.
This policy is not authentication and does not prevent direct HTTP clients with
network access from calling the API. Default-on device actions require Hobat to
be behind authenticated access control or a firewall outside a trusted network.


## Options

```
options:
  -h, --help         show this help message and exit
  --verbose, -v      Select INFO logging, overriding TD_DEBUG_LEVEL
  --debug, -d        Enable debug logging
  --log-thread-secrets
                     Show Thread Network Key and PSKc in OTBR REST DEBUG
                     response-body logs
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
  --disable-device-actions
                     Disable all active device diagnostics (env:
                     TD_DEVICE_ACTIONS_ENABLED; enabled by default).
  --disable-device-reset
                     Disable destructive OTBR Reset Counters actions (env:
                     TD_DEVICE_RESET_ENABLED; enabled by default).
```