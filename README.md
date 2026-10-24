# Hobat - Thread mesh dashboard and tools

Hobat is a Thread network dashboard and command-line toolkit that takes a  cache-first approach for collecting, visualizing, monitoring and troubleshooting. It collects data from dataset sources like OTBR `ot-ctl`, the OTBR REST API, Home Assistant Matter Server, mDNS, Eve exports, and Thread Tools exports. It provides visualizing with the Topology view that shows the Thread network in a number of layout options and the Table view in easy to navigate list. The Health view provides useful insights for Thread network health for eligible datasets.

[![OTBR CLI topology with a selected device and its details panel alongside the network graph.](https://raw.githubusercontent.com/jhawk42/smarthome/main/hobat/images/hobat-topology-selected-device-thumbnail.png)](https://github.com/jhawk42/smarthome/blob/main/hobat/screenshots.md)

## Capabilities

- Collector Dataset sources: OTBR CLI, OTBR REST, Home Assistant Matter, mDNS, Eve, Thread Tools and merged datasets.
- Interactive topology and sortable table views.
- Multiple visualization for topology layout: mesh compact, mesh ring, mesh tree horizontal, mesh tree vertical and hub spoke.
- Cache-first model keeps routine analysis off the live mesh. Long diagnostic
collections can consume time and battery, especially on sleepy end devices, so
run them deliberately or schedule them (cron) for quiet periods.
- Canonical identity (rloc16, extAddress) and field normalization across source formats.
- Atomic snapshot writes and source-level collection serialization.
- Progressive rendering from `.partial.json` checkpoints during long jobs.
- Cache-only, Direct-Refresh and Auto browser modes.
- Cancellable background collection jobs.
- Bounded in-memory browser activity logs and a unified pending-jobs view.
- Search and capability-driven node, link, and diagnostic filters.
- Health view summarizes network health and highlights issues in eligible datasets.
- Editable device labels stored in the configured data directory.

See [Codebase Overview](doc/codebase_overview.md), [Webpage and Server Data
Flow](doc/codebase_webpage_web_server_data_flow.md), [CLI Reference](doc/help_td_cli.md) and [Screenshots](https://github.com/jhawk42/smarthome/blob/main/hobat/screenshots.md)

## Requirements

- Python 3.11 or newer. Also tested on Python 3.14. Tested on Debian.
- Dependencies from `requirements.txt`.
- An OTBR instance for live OTBR collection for `otbr-cli` and `otbr-restapi` collection.
- Optional Home Assistant Matter Server for `ha-matter-ws` collection.
- Docker access when using the default container-based `ot-ctl` path.

Optional operator-managed inputs in data directory include:

- `Eve Thread Network Layout.evethreadlayout` from Eve app
- `diagnostics.json` from Thread Tools
- `td-static-extaddr-device-label.json`


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

## Start the Dashboard

From the repository root:

```bash
PYTHONPATH=src python3 -m td_webserver --host 0.0.0.0 --port 9165 --datadir ./data
```

Open `http://localhost:9165/`. The root redirects to `/tdash.html`.

On startup the dashboard does not fetch a dataset until **Sync** is selected. Default is **Auto**. Enable **Cache Only** before Sync to not trigger live collection. **Force Refresh** requests regeneration. Long actions return a background job that the browser polls and can cancel.

**Operations > Thread Network** includes source-backed partition identifiers
and counts of uniquely identified devices in the currently loaded observation.
Partial or conflicting membership is called out, and the counts are not a
complete mesh census; viewing the panel does not collect additional data.

For a health-eligible dataset, the **Refresh Health** control in Network
Insights processes the currently loaded cached snapshot with partial input
allowed. It writes health history in `hobat_v1.db`, but does not collect source
data, update snapshots, or probe devices.

In Table view, **Health** inserts Health Status, Health Reason, and Health
Observed immediately after `deviceLabel`, before `eui`, with **More Info**
either on or off and for each column category. If `deviceLabel` is absent,
they appear before `eui`, or at the end if neither field is available.
Turning Health off restores the dataset column order.

See the [Operator Guide](doc/help_operator.md#troubleshooting-logs) for
troubleshooting logs, detailed dashboard workflows, and operational controls.

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
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-cli networkdiag fetch-all \
  --children-ping-fallback
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-cli meshdiag routerneighbortable
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-cli meshdiag childtable
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-cli meshdiag childip6
PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-cli topology

# Explicit active device operations; neither runs as part of collection or health processing
PYTHONPATH=src python3 -m td_cli otbr-cli device ping <thread device ipv6address> --json
PYTHONPATH=src python3 -m td_cli otbr-cli device reset-counters <thread device ipv6address> \
  --counters mac --confirm --json
# Host ICMP probe of one literal address; this does not determine Thread or Matter reachability
PYTHONPATH=src python3 -m td_cli system device ping --address 2001:db8::1 --attempts 2

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
PYTHONPATH=src python3 -m td_cli --datadir ./data health migrate-history \
  --dataset all --policy-config-dir /absolute/path/to/server/config --dry-run --json
PYTHONPATH=src python3 -m td_cli --datadir ./data merge-dataset

# Health maintenance and complete data-directory backups
PYTHONPATH=src python3 -m td_cli --datadir ./data health purge --keep-days 30 --dry-run
PYTHONPATH=src python3 -m td_cli --datadir ./data system backups create --output ./hobat-backup
```

`system device ping` accepts only literal unicast IPv4 or IPv6 addresses. IPv6
link-local targets and zone identifiers require a later interface-aware design;
this command does not resolve names or change cached snapshots.

`otbr-cli topology` runs the complete CLI collection sequence.
See [Collection and Diagnostic Policies](doc/help_operator.md#collection-and-diagnostic-policies)
for collection costs, dataset configuration, diagnostic profiles, and fallback
behavior.

`otbr-cli device ping` sends bounded active Thread traffic and returns one
complete result. Its default timeout is 3 seconds, or 10 seconds with
`--allow-sed`; an explicit `--timeout` overrides either default.
`otbr-cli device reset-counters` is destructive, requires an explicit counter
selection and `--confirm`, and only reports `Done` as local acceptance for
transmission, not remote confirmation. Health processing does not run these
active operations.

`health process-dataset` is cache-only: it never invokes a collector or modifies source
snapshots. Remove `--dry-run` to atomically store the observation and assessment
in the Hobat-wide `hobat_v1.db`; add `--json` for machine-readable output. Use `--dataset all`
to process every active browser dataset marked `healthEligible: true`; the shared
manifest is kept in lockstep with that registry contract. Offline assessment
requires an explicitly imported expected-device roster and two distinct complete
observations. See [Thread Network Health](doc/thread_network_health.md).
`health migrate-history` is an explicit, backup-first maintenance operation for
replaying supported retained history; it does not collect data or infer missing
historical context from current snapshots. Stop health writers and consult
[Thread Network Health](doc/thread_network_health.md) before using it.
For health-eligible datasets, the dashboard reads the current stored assessment
through bounded, read-only `/api/health/*` routes. Run `health process-dataset`
after a successful cache collection to refresh the assessment shown by the browser.
In Health Insights, Latest follows the newest assessment; choosing or stepping
through retained runs pins the shared Findings/Device Roster assessment and its
health coloring. History navigation is read-only. Same-context Refresh Health
processes the current cached files without starting a collector: a pin remains
selected, while Latest follows the resulting assessment. Comparison endpoints
remain independent. Historical roster presence and health coloring are shown
with current/last-known roster facts and the currently loaded topology/table,
not reconstructed historical layouts. See
[Thread Network Health](doc/thread_network_health.md).

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

Matter device details show reported reboot count, uptime, operational hours,
boot reason, active fault lists, endpoint-scoped bridged identity, and cached
Power Source values when available. Battery percentage is derived from the
reported half-percent units; voltage is shown in millivolts and estimated times
in seconds. Empty `EndpointList` means a node-wide power source; an absent list
has unknown scope. These values describe the saved snapshot, not a live timer or
freshness guarantee, and opening the dashboard details does not issue extra
Matter reads. Firmware is not exposed as a separate field beyond reported
software-version attributes.

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

With **Enhance** enabled, the static label takes precedence over collected
labels in tables, topology node labels and hover popups, and the **Keys**
section of Device details, including all Home Assistant Matter datasets.
Records without a matching static label retain their collected label or
source-specific display fallback.

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

For the Compose configuration, use the included environment example:

```bash
docker compose \
  --env-file examples/.env.docker.example \
  --file examples/docker-compose.yaml \
  up -d --build
```

## Home Assistant OS App

To install Hobat on Home Assistant OS (HAOS):

1. In Home Assistant, go to **Settings > Apps > Install app**.
2. Open the three-dot menu, select **Repositories**, and add
  `https://github.com/jhawk42/hobat`.
3. Select **Hobat** from the added repository and select **Install**.
4. Follow the [Home Assistant app documentation](addon_hobat/DOCS.md) to
  configure Protection mode and optional OpenThread Border Router and Matter
  Server access, then start the app and select **Open Web UI**.

Home Assistant labels add-ons as "apps" in current UI releases. The app is
supported on `amd64` and `aarch64` HAOS installations.

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

If `data/` is empty (for example, a fresh clone before any collection has run),
skip the small subset of tests that read checked-in snapshots from that
directory with the `requires_data_dir` marker:

```bash
python3 -m pytest -q -m "not requires_data_dir"
```

Everything else builds its own isolated data directory with `tmp_path` and
`--datadir`/`TD_DATA_DIR`, so it does not depend on the contents of `data/`.

The [cached adaptor contract test](tests/test_js_adaptor_contracts.py) checks
output shape, node styling pairs, and graph integrity without pinning network
identities or counts to an older capture. Exact role-to-style behavior is
covered by deterministic cases in the
[adaptor contract runner](tests/js/run-adaptor-contracts.mjs).

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
- [Operator Guide](doc/help_operator.md#troubleshooting-logs)