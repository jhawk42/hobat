# Hobat - Thread mesh dashboard and tools

Hobat is a cache-first Thread network dashboard and command-line toolkit. It
collects data from OTBR `ot-ctl`, the OTBR REST API, Home Assistant Matter
Server, mDNS, Eve exports, and Thread Tools exports, then presents topology and
table views in a browser.

The cache-first model keeps routine analysis off the live mesh. Long diagnostic
collections can consume time and battery, especially on sleepy end devices, so
run them deliberately or schedule them for quiet periods.

## Capabilities

- Interactive topology and sortable table views.
- Multiple physics profiles for topology layout: mesh compact, mesh ring, mesh tree horizontal, mesh tree vertical and hub spoke.
- OTBR CLI, OTBR REST, Home Assistant Matter, mDNS, Eve, Thread Tools, and merged datasets.
- Search and capability-driven node, link, and diagnostic filters.
- Canonical identity and field normalization across source formats.
- Progressive rendering from `.partial.json` checkpoints during long jobs.
- Cache-only and force-refresh browser modes.
- Cancellable background collection jobs.
- Editable device labels stored in the configured data directory.
- Atomic snapshot writes and source-level collection serialization.

See [Codebase Overview](doc/codebase_overview.md), [Webpage and Server Data
Flow](doc/codebase_webpage_web_server_data_flow.md), and the [CLI Reference](doc/help_td_cli.md).

## Requirements

- Python 3.10 or newer.
- Dependencies from `requirements.txt`.
- An OTBR instance for live OTBR collection for `otbr-cli` and `otbr-restapi` collection.
- Optional Home Assistant Matter Server for `ha-matter-ws` collection.
- Docker access when using the default container-based `ot-ctl` path.

Install development and test dependencies from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt -r requirements_test.txt
```

## Data Directory

All tools use one effective data directory, resolved in this order:

1. `--datadir DIR`
2. `TD_DATA_DIR`
3. `/data` when that directory exists
4. `./data` under the current working directory

The local default is created when needed. See [Data Directory Model](doc/codebase_datadirectory.md).

```bash
mkdir -p "$PWD/data"
export TD_DATA_DIR="$PWD/data"
```

Optional operator-managed inputs include:

- `Eve Thread Network Layout.evethreadlayout`
- `diagnostics.json` from Thread Tools
- `td-static-extaddr-device-label.json`

## Start the Dashboard

From the repository root:

```bash
PYTHONPATH=src python3 -m td_webserver --host 0.0.0.0 --port 9165 --datadir ./data
```

Open `http://localhost:9165/`. The root redirects to `/tdash.html`.

On startup the dashboard does not fetch a dataset until **Sync** is selected. Default is **Auto**. Enable **Cache Only** before Sync to not trigger live collection. **Force Refresh** requests regeneration. Long actions return a background job that the browser polls and can cancel.

Dashboard API calls are same-origin and do not receive CORS authorization
headers. When using a reverse proxy, serve the dashboard and `/api/*` through
the same browser origin (and the same path prefix when one is used). Changing
the bind host does not create an origin allowlist. This browser restriction is
not authentication: direct clients such as `curl` or `wget` can call any API
route they can reach, so use firewall or authenticated proxy controls when the
API must be restricted.

## CLI Quick Start

Run commands from the repository root with `PYTHONPATH=src`:

```bash
PYTHONPATH=src python3 -m td_cli --help

# Fast OTBR CLI snapshots
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-cli router-table
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-cli meshdiag topology
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-cli networkdiag multicast-network

# Detailed OTBR CLI collection; may take minutes and reach sleepy devices
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-cli networkdiag fetch-all
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-cli topology

# OTBR REST snapshots
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-restapi devices list
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-restapi devices fetch
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-restapi diagnostics fetch-all
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-restapi topology

# Home Assistant Matter Server snapshots
PYTHONPATH=src python3 -m td_cli --datadir ./data ha-matter-ws server-info
PYTHONPATH=src python3 -m td_cli --datadir ./data ha-matter-ws topology
PYTHONPATH=src python3 -m td_cli --datadir ./data ha-matter-ws all

# Other sources and processing
PYTHONPATH=src python3 -m td_cli --datadir ./data mdns thread
PYTHONPATH=src python3 -m td_cli --datadir ./data process-eve
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset otbr_cli_networkdiag_fetch_all --dry-run
PYTHONPATH=src python3 -m td_cli --datadir ./data merge-dataset

# Health maintenance and complete data-directory backups
PYTHONPATH=src python3 -m td_cli --datadir ./data health purge --keep-days 180 --dry-run
PYTHONPATH=src python3 -m td_cli --datadir ./data system backups create --output ./hobat-backup
```

`otbr-cli topology` runs the complete CLI collection sequence. Detailed
`networkdiag fetch-all` and REST diagnostic sweeps are the highest-impact
commands; use cached snapshots for repeated analysis.

`health process-dataset` is cache-only: it never invokes a collector or modifies source
snapshots. Remove `--dry-run` to atomically store the observation and assessment
in the Hobat-wide `hobat_v1.db`; add `--json` for machine-readable output. Use `--dataset all`
to process every health-eligible dataset in the manifest. Offline assessment
requires an explicitly imported expected-device roster and two distinct complete
observations. See [Thread Network Health](doc/thread_network_health.md).
For health-eligible datasets, the dashboard reads the current stored assessment
through bounded, read-only `/api/health/*` routes. Run `health process-dataset`
after a successful cache collection to refresh the assessment shown by the browser.

Health purge commands support dry-run previews and require confirmation unless
`--yes` is supplied. `system backups create` uses SQLite's backup API and writes
a checksummed full-data-directory backup outside the active data directory.
Stop the web server and all writers before `system backups restore`; restore
validates and stages the backup before replacing the data directory. Backups
are unredacted and must be protected like the source data.

`ha-matter-ws` connects to `ws://localhost:5580/ws` by default. Set
`TD_HA_MATTER_WS_HOST` and `TD_HA_MATTER_WS_PORT`, or use `--host` and `--port`,
when Matter Server is reachable elsewhere. `--uri` overrides both host and port
with a complete WebSocket URI. It is read-only and
controller-scoped: only commissioned Matter nodes are visible, sleeping or
unavailable nodes may omit diagnostics, and Wi-Fi Matter nodes do not provide
Thread telemetry. This source complements OTBR network-wide collection rather
than replacing it. The dashboard serializes Matter refreshes and serves cached
snapshots until they are stale or explicitly refreshed.

See [CLI Reference](doc/help_td_cli.md), [OTBR REST CLI Reference](doc/help_td_restapi_cli.md), [Thread Network Health](doc/thread_network_health.md), and [Environment Variables](doc/help_env_vars.md).

## Device Labels

The authoritative label map is `td-static-extaddr-device-label.json`. Each
record maps a 16-hex-digit `extAddress` to a `deviceLabel`:

```json
[
  {
    "extAddress": "eeeaffeaffeaffe1",
    "deviceLabel": "Office Sensor"
  }
]
```

Select a device in the topology or table, open **Device Settings**, edit the
label, and apply the change. Labels are trimmed, may contain Unicode display
text, must be 1-128 characters, and cannot contain control characters. The
server atomically inserts or updates the record. Concurrent writers in separate
processes remain last-write-wins.

The same operation is available through the CLI:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data \
  merge-extaddr --update-extaddr eeeaffeaffeaffe1 \
  --device-label "Office Sensor"
```

## Docker

The published container starts the dashboard on port 9165. Mount a data
directory and, only when OTBR CLI collection is required, the Docker socket:

```bash
docker run --name hobat -d \
  --network host \
  --volume "$PWD/data:/data" \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --restart unless-stopped \
  ghcr.io/jhawk42/hobat:latest
```

Set `TD_OTBR_CONTAINER_USE=0` to run `ot-ctl` locally instead of through
`docker exec`. 

Home Assistant add-on configuration is under `addon_hobat/`.

The Matter WebSocket default requires the container to share the host network;
otherwise run the CLI with a reachable `--uri`.

## Tests

The authoritative default suite is offline and treats checked-in data as
immutable fixtures:

```bash
python3 -m pytest -q
```

Benchmark and live checks are explicit opt-ins:

```bash
python3 -m pytest -q -m benchmark
TD_LIVE_TESTS=1 python3 -m pytest -q -m live
python3 -m pytest -q --cov
```

The live suite requires a configured OTBR environment. The default suite does
not require OTBR, mDNS network access, Docker, or internet access.

## Documentation

- [Codebase Overview](doc/codebase_overview.md)
- [Webpage, Web Server, and Data Flow](doc/codebase_webpage_web_server_data_flow.md)
- [Data Directory Model](doc/codebase_datadirectory.md)
- [Dashboard Fields](doc/dashboard_ui_fields.md)
- [Topology Node Colors](doc/dashboard_vis_node_colors.md)
- [Merge Model](doc/merge_thread_device_info.md)
- [Merge Troubleshooting](doc/merge_troubleshooting.md)
- [CLI Reference](doc/help_td_cli.md)
- [OTBR REST CLI Reference](doc/help_td_restapi_cli.md)
- [Web Server Reference](doc/help_td_webserver.md)
- [Environment Variables](doc/help_env_vars.md)