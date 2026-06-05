# OTBR REST API CLI — Command Reference

CLI wrapper for the OpenThread Border Router REST API.

| Script | Output style |
|---|---|
| `otbr_restapi_cli.py` | Flattened (JSON:API envelopes unwrapped by default) |

Run from the project root with:

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi [global-options] <command> ...
```

The wrapper forwards the same OTBR REST API global options to `otbr_restapi_cli.py`.

---

## Global Options

These options apply to every command and must be placed **before** the subcommand.

| Option | Default | Description |
|---|---|---|
| `--host HOST` | `127.0.0.1` | OTBR REST API host |
| `--port PORT` | `8081` | OTBR REST API port |
| `--base-url URL` | — | Override host/port with a full base URL |
| `--timeout SECS` | `10` | HTTP request timeout in seconds |
| `--accept MIME` | `application/vnd.api+json` | Default `Accept` header; choices: `application/vnd.api+json`, `application/json`, `text/plain` |
| `--raw` | off | Return raw JSON:API envelopes instead of flattened output |
| `--output FILE` | — | Write JSON result to a file instead of stdout |
| `--datadir DIR` | auto | Data directory for file reads/writes (takes precedence over `$TD_DATA_DIR`; if omitted: `$TD_DATA_DIR`, then `/data`, then `./data`) |
| `--poll-interval FLOAT` | `2.0` | Seconds between action status polls |
| `--poll-timeout FLOAT` | `8.0` | Max wall-clock seconds to wait for an action to complete |
| `--no-progress` | off | Suppress per-device `[N/T] id → status (Xs)` progress lines printed to stderr on `fetch-all` commands |
| `--no-auto-output` | off | Disable automatic output file naming; send JSON to stdout instead of `<datadir>/td-otbr-restapi-<resource>-<command>.json` |
| `--debug`, `-d` | off | Enable debug logging |

---

## Command Summary

| Command | Description |
|---|---|
| `node get` | Get full OTBR node record from `/api/node` |
| `node state get` | Get current Thread radio state |
| `node state set` | Enable or disable Thread |
| `node dataset active get` | Get active Thread dataset (JSON or TLV hex) |
| `node dataset active set` | Create or update active Thread dataset |
| `devices list` | List all known devices from `/api/devices` |
| `devices get` | Get a single device by extAddress |
| `devices fetch` | Trigger updateDeviceCollectionTask, wait, return device list |
| `diagnostics list` | List all cached diagnostic records |
| `diagnostics get` | Get a single diagnostic record by ID |
| `diagnostics fetch` | Fetch diagnostics for one device (enqueue + wait + return result) |
| `diagnostics fetch-all` | Fetch diagnostics for all (or given) devices |
| `actions list` | List all actions |
| `actions get` | Get a single action by ID |
| `actions enqueue add-thread-device` | Enqueue `addThreadDeviceTask` |
| `actions enqueue get-network-diagnostic` | Enqueue `getNetworkDiagnosticTask` |
| `actions enqueue reset-network-diag-counter` | Enqueue `resetNetworkDiagCounterTask` |
| `actions enqueue get-energy-scan` | Enqueue `getEnergyScanTask` |
| `actions enqueue update-device-collection` | Enqueue `updateDeviceCollectionTask` |
| `mesh-diagnostics children` | Fetch child table for a device (TLV 29) |
| `mesh-diagnostics child-ipv6` | Fetch child IPv6 addresses for a device (TLV 30) |
| `mesh-diagnostics router-neighbors` | Fetch router neighbor table for a device (TLV 31) |
| `mesh-diagnostics fetch` | Fetch caller-specified mesh-diagnostic TLVs for one device |
| `mesh-diagnostics fetch-all` | Fetch mesh diagnostics for all (or given) devices |
| `topology` | Full sweep: devices fetch → diagnostics fetch-all → mesh-diagnostics fetch-all |

---

## Commands

### `node`

Read or mutate local OTBR node data.

#### `node get`

Get the OTBR node record from `/api/node`.

```
node get [--fields FIELDS]
```

| Option | Description |
|---|---|
| `--fields` | Sparse-field selector (repeatable) |

**Examples:**

```bash
# Print full node record
PYTHONPATH=src python3 -m td_cli otbr-restapi node get

# Select specific fields only
PYTHONPATH=src python3 -m td_cli otbr-restapi node get \
    --fields 'threadBorderRouter=extAddress,rloc16,role'

# Save to file
PYTHONPATH=src python3 -m td_cli otbr-restapi --output data/node.json node get
```

---

#### `node state get`

Get current Thread radio state.

```
node state get
```

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi node state get

PYTHONPATH=src python3 -m td_cli otbr-restapi --host 192.168.1.10 node state get
```

---

#### `node state set`

Enable or disable Thread.

```
node state set --value {enable,disable}
```

| Option | Required | Description |
|---|---|---|
| `--value` | yes | `enable` or `disable` |

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi node state set --value enable

PYTHONPATH=src python3 -m td_cli otbr-restapi node state set --value disable
```

---

#### `node dataset active get`

Get the active Thread dataset.

```
node dataset active get [--text]
```

| Option | Description |
|---|---|
| `--text` | Request as `text/plain` TLV hex string instead of JSON |

**Examples:**

```bash
# JSON
PYTHONPATH=src python3 -m td_cli otbr-restapi node dataset active get

# Raw TLV hex string
PYTHONPATH=src python3 -m td_cli otbr-restapi node dataset active get --text
```

---

#### `node dataset active set`

Create or update the active Thread dataset. Exactly one input source is required.

```
node dataset active set (--json JSON | --json-file FILE | --text TEXT | --text-file FILE)
```

| Option | Description |
|---|---|
| `--json JSON` | Inline JSON payload |
| `--json-file FILE` | Path to a JSON file |
| `--text TEXT` | Inline TLV hex string |
| `--text-file FILE` | Path to a file containing the TLV hex string |

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    node dataset active set --json-file data/dataset.json

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    node dataset active set --text 0e080000000000010000000300000f...
```

---

### `devices`

Read Thread devices from `/api/devices`.

#### `devices list`

List all known devices.

```
devices list [--fields FIELDS] [--with-meta]
```

| Option | Description |
|---|---|
| `--fields` | Repeatable sparse-field selector, e.g. `threadDevice=hostName,role` |
| `--with-meta` | Include collection `meta` alongside the flattened items |

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi devices list

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    devices list --fields 'threadDevice=hostName,role'

PYTHONPATH=src python3 -m td_cli otbr-restapi devices list --with-meta
```

---

#### `devices get`

Get a single device by its extAddress.

```
devices get --device-id DEVICE_ID [--fields FIELDS]
```

| Option | Required | Description |
|---|---|---|
| `--device-id` | yes | Device extAddress (16-char hex) |
| `--fields` | no | Sparse-field selector |

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    devices get --device-id aabbccddeeff0011

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    devices get --device-id aabbccddeeff0011 \
    --fields 'threadDevice=extAddress,role'
```

---

#### `devices fetch`

Trigger `updateDeviceCollectionTask`, wait for completion, then return the populated device list. Combines enqueue + poll + list in one call.

```
devices fetch [--device-count N] [--task-timeout SECS] [--max-age SECS] [--max-retries N]
```

| Option | Default | Description |
|---|---|---|
| `--device-count` | `255` | Max devices to discover |
| `--task-timeout` | `6` | Server-side task timeout in seconds |
| `--max-age` | `60` | Max age of cached device entries in seconds |
| `--max-retries` | `2` | Max retries per device |

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi devices fetch

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    --output data/devices.json \
    devices fetch --device-count 20 --task-timeout 60
```

---

### `diagnostics`

Read Thread network diagnostics from `/api/diagnostics`.

#### `diagnostics list`

List all known diagnostic records.

```
diagnostics list [--fields FIELDS] [--with-meta]
```

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi diagnostics list

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    diagnostics list --fields 'networkDiagnostics=extAddress,rloc16,macCounters'
```

---

#### `diagnostics get`

Get a single diagnostic record by ID.

```
diagnostics get --diagnostics-id ID
```

| Option | Required | Description |
|---|---|---|
| `--diagnostics-id` | yes | Diagnostic record UUID |

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    diagnostics get --diagnostics-id a6a0b433-437e-45bf-9994-58e0d7b32399

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    --output data/diag-a6a0.json \
    diagnostics get --diagnostics-id a6a0b433-437e-45bf-9994-58e0d7b32399
```

---

#### `diagnostics fetch`

Enqueue `getNetworkDiagnosticTask` for one device, wait for completion, and return the diagnostic result. MAC counter enrichment is applied by default.

```
diagnostics fetch --device-id DEVICE_ID
                  [--types TLV ...]
                  [--preset {recommended,full,minimal,basic}]
                  [--task-timeout SECS]
                  [--destination-type TYPE]
                  [--no-fallback]
                  [--fallback-preset {medium,minimal,basic}]
                  [--no-enrich-mac-counters]
```

| Option | Default | Description |
|---|---|---|
| `--device-id` | required | Device extAddress (16-char hex) |
| `--types` | recommended set | Space-separated diagnostic TLV names |
| `--preset` | — | `recommended`, `full`, `minimal`, or `basic`; overrides `--types` |
| `--task-timeout` | `6` | Server-side task timeout in seconds |
| `--destination-type` | `extended` | Destination addressing mode: `extended`, `mleid`, or `rloc` |
| `--no-fallback` | off | Disable TLV fallback retry; skip the device immediately on failure |
| `--fallback-preset` | `minimal` | TLV preset to retry with when the primary request fails: `medium`, `minimal`, or `basic` |
| `--no-enrich-mac-counters` | off | Return raw `macCounters` values only; skip computed totals and ratios |

By default, if a device fails to respond to the primary TLV set the command automatically retries with the `--fallback-preset` TLV set. Pass `--no-fallback` to disable this.

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    diagnostics fetch --device-id aabbccddeeff0011 --preset recommended

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    diagnostics fetch --device-id aabbccddeeff0011 \
    --types extAddress rloc16 macCounters mleCounters \
    --no-enrich-mac-counters

PYTHONPATH=src python3 -m td_cli otbr-restapi --no-auto-output \
    diagnostics fetch --device-id aabbccddeeff0011 --preset recommended --no-fallback
```

---

#### `diagnostics fetch-all`

Fetch diagnostics for all known devices (or a given list), one device at a time. The device list is automatically refreshed via `updateDeviceCollectionTask` before fetching (pass `--no-update-devices` to skip). MAC counter enrichment and per-device progress are on by default.

```
diagnostics fetch-all [--device-ids ID ...]
                      [--types TLV ...]
                      [--preset {recommended,full,minimal,basic}]
                      [--task-timeout SECS]
                      [--destination-type TYPE]
                      [--no-update-devices]
                      [--no-fallback]
                      [--fallback-preset {medium,minimal,basic}]
                      [--no-enrich-mac-counters]
```

| Option | Default | Description |
|---|---|---|
| `--device-ids` | all devices | Space-separated extAddress IDs to query |
| `--types` | recommended set | Diagnostic TLV names |
| `--preset` | — | `recommended`, `full`, `minimal`, or `basic`; overrides `--types` |
| `--task-timeout` | `6` | Server-side task timeout per device in seconds |
| `--destination-type` | `extended` | Destination addressing mode: `extended`, `mleid`, or `rloc` |
| `--no-update-devices` | off | Skip `updateDeviceCollectionTask`; use the cached device list |
| `--no-fallback` | off | Disable per-device TLV fallback retry on failure |
| `--fallback-preset` | `minimal` | TLV preset to retry with on device failure: `medium`, `minimal`, or `basic` |
| `--no-enrich-mac-counters` | off | Return raw `macCounters` without computed totals and ratios |

> **Note:** `--update-devices` has been replaced by `--no-update-devices`. Device list refresh now runs by default; pass `--no-update-devices` to opt out.

Results are automatically written to `<datadir>/td-otbr-restapi-diagnostics-fetch-all.json` unless `--no-auto-output` or `--output` is specified.

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    diagnostics fetch-all --preset recommended

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    diagnostics fetch-all --preset recommended --no-update-devices

PYTHONPATH=src python3 -m td_cli otbr-restapi --no-progress \
    diagnostics fetch-all \
    --device-ids aabbccddeeff0011 aabbccddeeff0022 \
    --no-enrich-mac-counters

PYTHONPATH=src python3 -m td_cli otbr-restapi --no-auto-output \
    diagnostics fetch-all --preset recommended
```

---

### `actions`

Read or enqueue OTBR task actions.

#### `actions list`

List all actions.

```
actions list [--fields FIELDS] [--with-meta]
```

| Option | Description |
|---|---|
| `--fields` | Sparse-field selector (repeatable) |
| `--with-meta` | Include collection `meta` alongside the flattened items |

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi actions list

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions list --fields 'action=id,type,status'
```

---

#### `actions get`

Get a single action by ID (useful for polling status).

```
actions get --action-id ACTION_ID [--fields FIELDS]
```

| Option | Required | Description |
|---|---|---|
| `--action-id` | yes | Action UUID |
| `--fields` | no | Sparse-field selector (repeatable) |

Action `status` values: `pending` → `active` → `completed` / `stopped` / `failed`  
(`addThreadDeviceTask` also uses `undiscovered` and `attempted`)

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions get --action-id 9ecae480-07a0-4b72-869d-15858196144e

# Lightweight status-only poll
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions get --action-id 9ecae480-07a0-4b72-869d-15858196144e \
    --fields 'action=id,status'

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    --output data/action-status.json \
    actions get --action-id 9ecae480-07a0-4b72-869d-15858196144e
```

---

#### `actions enqueue add-thread-device`

Enqueue `addThreadDeviceTask` to commission a new joiner device.

```
actions enqueue add-thread-device --pskd PSKD
    (--eui EUI | --discerner DISCERNER | --joiner-id JOINER_ID)
    [--timeout SECS]
```

| Option | Required | Description |
|---|---|---|
| `--pskd` | yes | Pre-Shared Key for the Device |
| `--eui` | one of three | EUI-64 address |
| `--discerner` | one of three | Joiner discerner value |
| `--joiner-id` | one of three | Joiner ID |
| `--timeout` | no | Task timeout in seconds |

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue add-thread-device \
    --eui aabbccddeeff0022 \
    --pskd J01NME \
    --timeout 120

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue add-thread-device \
    --discerner 0xabc \
    --pskd S3CRET
```

---

#### `actions enqueue get-network-diagnostic`

Enqueue `getNetworkDiagnosticTask` for a destination address.

```
actions enqueue get-network-diagnostic --destination DEST
    [--types TLV ...]
    [--preset {recommended,full,minimal,basic}]
    [--timeout SECS]
    [--destination-type TYPE]
    [--wait]
```

| Option | Default | Description |
|---|---|---|
| `--destination` | required | Destination address |
| `--types` | recommended set | TLV names or integers |
| `--preset` | — | `recommended`, `full`, `minimal`, or `basic`; overrides `--types` |
| `--timeout` | — | Server-side task timeout in seconds |
| `--destination-type` | — | `extended`, `mleid`, or `rloc` |
| `--wait` | off | Poll until completion and return the diagnostic result; exit code 4 on stopped/failed |

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue get-network-diagnostic \
    --destination aabbccddeeff0011 \
    --preset recommended

# Block until complete, return diagnostic result
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue get-network-diagnostic \
    --destination aabbccddeeff0011 \
    --types extAddress rloc16 macCounters mleCounters \
    --timeout 120 \
    --wait
```

---

#### `actions enqueue reset-network-diag-counter`

Enqueue `resetNetworkDiagCounterTask`. Only `macCounters` (TLV 9) and `mleCounters` (TLV 34) are resettable; passing any other TLV name is rejected client-side before the request is sent.

```
actions enqueue reset-network-diag-counter --types TYPE ...
    [--destination DEST]
    [--timeout SECS]
    [--destination-type TYPE]
```

| Option | Required | Description |
|---|---|---|
| `--types` | yes | Counter TLV names: `macCounters` and/or `mleCounters` |
| `--destination` | no | Target device address |
| `--timeout` | no | Server-side task timeout in seconds |
| `--destination-type` | no | `extended`, `mleid`, or `rloc` |

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue reset-network-diag-counter \
    --destination aabbccddeeff0011 \
    --types macCounters mleCounters

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue reset-network-diag-counter \
    --destination aabbccddeeff0011 \
    --types mleCounters \
    --timeout 60
```

---

#### `actions enqueue get-energy-scan`

Enqueue `getEnergyScanTask`. All scan parameters are optional; the server applies its own defaults when they are omitted.

```
actions enqueue get-energy-scan --destination DEST
    --channel-mask CHAN ...
    [--count N]
    [--period N]
    [--scan-duration N]
    [--timeout SECS]
    [--destination-type TYPE]
```

| Option | Required | Description |
|---|---|---|
| `--destination` | yes | Target device address |
| `--channel-mask` | yes | One or more channel numbers |
| `--count` | no | Number of scans per channel (server default: 1) |
| `--period` | no | Time between scans in ms (server default: 32) |
| `--scan-duration` | no | Duration per channel scan in ms (server default: 0) |
| `--timeout` | no | Server-side task timeout in seconds |
| `--destination-type` | no | `extended`, `mleid`, or `rloc` |

**Examples:**

```bash
# Minimal — server uses defaults for count, period, scan-duration
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue get-energy-scan \
    --destination aabbccddeeff0011 \
    --channel-mask 11 15

# Explicit parameters
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue get-energy-scan \
    --destination aabbccddeeff0011 \
    --channel-mask 11 15 \
    --count 3 --period 32 --scan-duration 50 \
    --timeout 60

# Full channel scan 11-26
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue get-energy-scan \
    --destination aabbccddeeff0011 \
    --channel-mask 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 \
    --count 5 --period 32 --scan-duration 100 \
    --timeout 120
```

---

#### `actions enqueue update-device-collection`

Enqueue `updateDeviceCollectionTask` and return immediately with the action record. Use `actions get` to poll status, or use `devices fetch` for the combined enqueue-wait-list workflow.

```
actions enqueue update-device-collection
    [--device-count N]
    [--max-age SECS]
    [--max-retries N]
    [--timeout SECS]
```

| Option | Default | Description |
|---|---|---|
| `--device-count` | `255` | Max devices to discover |
| `--max-age` | `60` | Max age of cached device entries in seconds |
| `--max-retries` | `2` | Max retries per device |
| `--timeout` | `5` | Server-side task timeout in seconds |

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue update-device-collection

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue update-device-collection \
    --device-count 20 --max-age 60 --max-retries 3 --timeout 90

# Capture action ID and poll manually
ACTION_ID=$(PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue update-device-collection | jq -r '.[0].id')
echo "Enqueued action: $ACTION_ID"

while true; do
    STATUS=$(PYTHONPATH=src python3 -m td_cli otbr-restapi \
        actions get --action-id "$ACTION_ID" | jq -r '.status')
    echo "status: $STATUS"
    [[ "$STATUS" == "completed" || "$STATUS" == "stopped" || "$STATUS" == "failed" ]] && break
    sleep 2
done

# Preferred: enqueue + wait + list in one shot
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    devices fetch --device-count 20 --task-timeout 90
```

---

### `mesh-diagnostics`

Fetch mesh-diagnostic TLVs via `otMeshDiag`. These require an additional round-trip on the server and have higher latency than standard diagnostic TLVs.

> **Router / leader devices only.** The server omits `children`, `childIpv6Addresses`, and `routerNeighbors` for child devices (RLOC16 lower 10 bits non-zero). Use `--routers-only` on `fetch-all` or check roles first:
> ```bash
> PYTHONPATH=src python3 -m td_cli otbr-restapi \
>     devices list --fields 'threadDevice=extAddress,role,hostName'
> ```

Common per-device options for `children`, `child-ipv6`, `router-neighbors`, and `fetch`:

| Option | Default | Description |
|---|---|---|
| `--device-id` | required | Device extAddress (16-char hex) |
| `--task-timeout` | `8` | Server-side task timeout in seconds |
| `--poll-timeout` | `8.0` | Max wall-clock seconds to wait |
| `--destination-type` | `extended` | Destination addressing mode: `extended`, `mleid`, or `rloc` |

---

#### `mesh-diagnostics children`

Fetch the child table for a device (TLV 29).

```
mesh-diagnostics children --device-id DEVICE_ID
    [--task-timeout SECS] [--poll-timeout FLOAT] [--destination-type TYPE]
```

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    mesh-diagnostics children --device-id aabbccddeeff0011

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    --output data/children-aabb.json \
    mesh-diagnostics children --device-id aabbccddeeff0011
```

---

#### `mesh-diagnostics child-ipv6`

Fetch child IPv6 addresses for a device (TLV 30).

```
mesh-diagnostics child-ipv6 --device-id DEVICE_ID
    [--task-timeout SECS] [--poll-timeout FLOAT] [--destination-type TYPE]
```

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    mesh-diagnostics child-ipv6 --device-id aabbccddeeff0011

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    mesh-diagnostics child-ipv6 --device-id aabbccddeeff0011 --task-timeout 600
```

---

#### `mesh-diagnostics router-neighbors`

Fetch router neighbor table for a device (TLV 31).

```
mesh-diagnostics router-neighbors --device-id DEVICE_ID
    [--task-timeout SECS] [--poll-timeout FLOAT] [--destination-type TYPE]
```

**Examples:**

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    mesh-diagnostics router-neighbors --device-id aabbccddeeff0011

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    --output data/router-nbrs-aabb.json \
    mesh-diagnostics router-neighbors --device-id aabbccddeeff0011
```

---

#### `mesh-diagnostics fetch`

Fetch a caller-specified subset of mesh-diagnostic TLVs for one device. Defaults to all three TLVs when `--types` is omitted.

```
mesh-diagnostics fetch --device-id DEVICE_ID
    [--types {children,childIpv6Addresses,routerNeighbors} ...]
    [--task-timeout SECS] [--poll-timeout FLOAT] [--destination-type TYPE]
```

**Examples:**

```bash
# All three TLVs
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    mesh-diagnostics fetch --device-id aabbccddeeff0011

# Selected subset
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    mesh-diagnostics fetch --device-id aabbccddeeff0011 \
    --types children childIpv6Addresses

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    mesh-diagnostics fetch --device-id aabbccddeeff0011 --types children
```

---

#### `mesh-diagnostics fetch-all`

Fetch mesh diagnostics for all known devices (or a given list), one device at a time. Device list is refreshed automatically before fetching (pass `--no-update-devices` to skip).

```
mesh-diagnostics fetch-all [--device-ids ID ...]
    [--types {children,childIpv6Addresses,routerNeighbors} ...]
    [--task-timeout SECS]
    [--poll-timeout FLOAT]
    [--destination-type TYPE]
    [--no-update-devices]
    [--routers-only]
```

| Option | Default | Description |
|---|---|---|
| `--device-ids` | all devices | Space-separated extAddress IDs to query |
| `--types` | all three | `children`, `childIpv6Addresses`, `routerNeighbors` |
| `--task-timeout` | `8` | Server-side task timeout per device in seconds |
| `--poll-timeout` | `8.0` | Max wall-clock seconds per device action |
| `--destination-type` | `extended` | Destination addressing mode: `extended`, `mleid`, or `rloc` |
| `--no-update-devices` | off | Skip `updateDeviceCollectionTask`; use the cached device list |
| `--routers-only` | off | Filter to router devices only (RLOC16 lower 10 bits == 0); skips child devices that return empty mesh-diag records |

> **Note:** `--update-devices` has been replaced by `--no-update-devices`. Device list refresh now runs by default.

Results are automatically written to `<datadir>/td-otbr-restapi-mesh-diagnostics-fetch-all.json` unless `--no-auto-output` or `--output` is specified.

**Examples:**

```bash
# Router devices only (recommended)
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    mesh-diagnostics fetch-all --routers-only

# All devices, skip device refresh
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    mesh-diagnostics fetch-all --no-update-devices

# Two specific devices, router-neighbors only
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    mesh-diagnostics fetch-all \
    --device-ids aabbccddeeff0011 aabbccddeeff0022 \
    --types routerNeighbors
```

---

### `topology`

Run the full topology sweep in a single command. Executes three steps in sequence and writes all output files automatically under `--datadir`:

| Step | Action | Output file |
|---|---|---|
| 1 | `devices fetch` (updateDeviceCollectionTask) | `td-otbr-restapi-devices-fetch.json` |
| 2 | `diagnostics fetch-all --preset recommended` | `td-otbr-restapi-diagnostics-fetch-all.json` |
| 3 | `mesh-diagnostics fetch-all --routers-only` | `td-otbr-restapi-mesh-diagnostics-fetch-all.json` |

```
topology [--preset {recommended,full,minimal,basic}]
         [--skip-devices]
         [--skip-diagnostics]
         [--skip-mesh-diagnostics]
         [--no-update-devices]
         [--no-enrich-mac-counters]
         [--no-fallback]
         [--fallback-preset {medium,minimal,basic}]
```

| Option | Default | Description |
|---|---|---|
| `--preset` | `recommended` | TLV preset for the diagnostics step |
| `--skip-devices` | off | Skip Step 1 (device refresh); use the current device list for subsequent steps |
| `--skip-diagnostics` | off | Skip Step 2 (network diagnostics fetch-all) |
| `--skip-mesh-diagnostics` | off | Skip Step 3 (mesh diagnostics fetch-all) |
| `--no-update-devices` | off | When `--skip-devices` is set, also skip `updateDeviceCollectionTask` in Steps 2 and 3 |
| `--no-enrich-mac-counters` | off | Disable MAC counter enrichment on the diagnostics result |
| `--no-fallback` | off | Disable per-device TLV fallback retry in the diagnostics step |
| `--fallback-preset` | `minimal` | Fallback TLV preset for Step 2: `medium`, `minimal`, or `basic` |

Progress for each step and each device is printed to stderr. Pass `--no-progress` (global flag) to suppress. The command returns `None`; all data is written to files rather than printed to stdout.

**Examples:**

```bash
# Full sweep with defaults
PYTHONPATH=src python3 -m td_cli otbr-restapi topology

# Remote OTBR, custom data directory
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    --host 192.168.1.10 --datadir /tmp/topology \
    topology

# Skip device refresh (already done)
PYTHONPATH=src python3 -m td_cli otbr-restapi topology --skip-devices

# Diagnostics step only
PYTHONPATH=src python3 -m td_cli otbr-restapi topology --skip-mesh-diagnostics

# Silent (no progress output)
PYTHONPATH=src python3 -m td_cli otbr-restapi --no-progress topology
```

---

## Exit Codes

| Code | Constant | Meaning |
|---|---|---|
| `0` | `EXIT_SUCCESS` | Success |
| `1` | `EXIT_UNEXPECTED` | Unexpected / unhandled error |
| `2` | `EXIT_USAGE` | Usage / argument error (`OTBRUsageError`) |
| `3` | `EXIT_CONNECTION` | Connection error (`OTBRConnectionError`) |
| `4` | `EXIT_HTTP` | HTTP error, or action stopped/failed (`OTBRHTTPError`, `OTBRActionError`) |
| `5` | `EXIT_INVALID_RESPONSE` | Invalid or unexpected API response (`OTBRInvalidResponseError`) |

---

## Auto-Output File Names

When `--no-auto-output` is not set and `--output` is not specified, fetch/list commands automatically write results to `<datadir>/<filename>`:

| Command | Auto-output filename |
|---|---|
| `devices list` | `td-otbr-restapi-devices-list.json` |
| `devices fetch` | `td-otbr-restapi-devices-fetch.json` |
| `diagnostics list` | `td-otbr-restapi-diagnostics-list.json` |
| `diagnostics fetch` | `td-otbr-restapi-diagnostics-fetch.json` |
| `diagnostics fetch-all` | `td-otbr-restapi-diagnostics-fetch-all.json` |
| `actions list` | `td-otbr-restapi-actions-list.json` |
| `mesh-diagnostics fetch` | `td-otbr-restapi-mesh-diagnostics-fetch.json` |
| `mesh-diagnostics fetch-all` | `td-otbr-restapi-mesh-diagnostics-fetch-all.json` |
| `topology` (step 1 — devices) | `td-otbr-restapi-devices-fetch.json` |
| `topology` (step 2 — diagnostics) | `td-otbr-restapi-diagnostics-fetch-all.json` |
| `topology` (step 3 — mesh-diagnostics) | `td-otbr-restapi-mesh-diagnostics-fetch-all.json` |

> **Note:** The `topology` command always writes its three files regardless of `--no-auto-output` because all output is file-based (the command returns nothing to stdout).

---

## `--fields` Sparse Field Reference

The `--fields` option restricts which attributes are returned. The server filters at the source, so only the requested attributes are transmitted.

**Syntax:** `--fields 'TYPE=field1,field2'` or `--fields TYPE` (all fields of that type).  
**Repeatable:** pass `--fields` multiple times to select fields from more than one type.

The `TYPE` matches the JSON:API resource `type` value for the collection being queried.

---

### `threadDevice` / `threadBorderRouter` — Devices fields

Used with `devices list`, `devices get`, `devices fetch`, `node get`.

| Field | Type | Description |
|---|---|---|
| `extAddress` | string (hex) | 64-bit IEEE 802.15.4 extended address — device ID |
| `mlEidIid` | string (hex) | Mesh-Local EID Interface Identifier |
| `omrIpv6Address` | string (IPv6) | Off-Mesh-Routable IPv6 address |
| `hostName` | string | mDNS hostname (`.local`) |
| `role` | string | Thread role: `leader`, `router`, `child`, `sleepy-child` |
| `mode` | object | Device mode flags |
| `mode.deviceTypeFTD` | bool | `true` = Full Thread Device |
| `mode.rxOnWhenIdle` | bool | `true` = receiver always on |
| `mode.fullNetworkData` | bool | `true` = subscribes to full network data |
| `created` | ISO 8601 | Timestamp when the device entry was created |
| `updated` | ISO 8601 | Timestamp when the device entry was last updated |

Additional fields present only on `threadBorderRouter` items:

| Field | Type | Description |
|---|---|---|
| `rloc16` | string (hex) | 16-bit RLOC address |
| `routerId` | number | Router ID (upper 6 bits of RLOC16) |
| `rlocAddress` | string (IPv6) | Full RLOC IPv6 address |
| `routerCount` | number | Number of active routers in the network |
| `networkName` | string | Thread network name |
| `extPanId` | string (hex) | Extended PAN ID |
| `leaderData` | object | Leader data |
| `leaderData.partitionId` | number | Partition ID |
| `leaderData.weighting` | number | Leader weighting |
| `leaderData.dataVersion` | number | Network data version |
| `leaderData.stableDataVersion` | number | Stable network data version |
| `leaderData.leaderRouterId` | number | Current leader's router ID |
| `baId` | string (hex) | Border Agent ID |
| `baState` | string | Border Agent state |

**Examples:**

```bash
devices list --fields 'threadDevice=hostName,role,mode'
devices list --fields threadDevice
node get --fields 'threadBorderRouter=extAddress,rloc16,baId'
```

---

### `networkDiagnostics` — Diagnostics fields

Used with `diagnostics list`, `diagnostics get`, `diagnostics fetch`, `diagnostics fetch-all`.

| Field | TLV | Description |
|---|---|---|
| `extAddress` | 0 | 64-bit extended MAC address |
| `rloc16` | 1 | 16-bit RLOC (hex string, e.g. `0x1400`) |
| `routerId` | 1 | Router ID (derived from RLOC16; routers only) |
| `mode` | 2 | Device mode flags (`deviceTypeFTD`, `rxOnWhenIdle`, `fullNetworkData`) |
| `timeout` | 3 | Max polling period for SEDs (seconds) |
| `connectivity` | 4 | Connectivity info (`parentPriority`, `linkQuality1/2/3`, `leaderCost`, `idSequence`, `activeRouters`, `sedBufferSize`, `sedDatagramCount`) |
| `route` | 5 | Route64 info: `idSequence`, `routeData[]` (each with `routeId`, `linkQualityIn`, `linkQualityOut`, `routeCost`) |
| `leaderData` | 6 | Leader data object |
| `networkData` | 7 | Network data (hex string) |
| `ipv6Addresses` | 8 | List of IPv6 addresses |
| `macCounters` | 9 | MAC packet counters (raw: `ifInUnknownProtos`, `ifInErrors`, `ifOutErrors`, `ifInUcastPkts`, `ifInBroadcastPkts`, `ifInDiscards`, `ifOutUcastPkts`, `ifOutBroadcastPkts`, `ifOutDiscards`; enriched: `ifintotalpkts`, `ifouttotalpkts`, `iftotalpkts`, `iftotalerrors`, `iftotaldiscards`, plus per-direction error/discard totals) |
| `batteryLevel` | 14 | Battery level (0–100) |
| `supplyVoltage` | 15 | Supply voltage (mV) |
| `childTable` | 16 | Array of child entries (`childId`, `timeout`, `linkQuality`, `mode`) |
| `channelPages` | 17 | Supported channel pages (hex string) |
| `maxChildTimeout` | 19 | Max child timeout (seconds) |
| `eui64` | 23 | EUI-64 address |
| `version` | 24 | Thread version number |
| `vendorName` | 25 | Vendor name string |
| `vendorModel` | 26 | Vendor model string |
| `vendorSwVersion` | 27 | Vendor software version string |
| `threadStackVersion` | 28 | Thread stack version string |
| `children` | 29 | Mesh-diag child table (routers only) — requires `otMeshDiag` |
| `childIpv6Addresses` | 30 | Mesh-diag child IPv6 addresses (routers only) — requires `otMeshDiag` |
| `routerNeighbors` | 31 | Mesh-diag router neighbor table (routers only) — requires `otMeshDiag` |
| `mleCounters` | 34 | MLE counters (`radioDisabledCount`, `detachedRoleCount`, `childRoleCount`, `routerRoleCount`, `leaderRoleCount`, `attachAttemptsCount`, `partIdChangesCount`, `betterPartIdAttachAttemptsCount`, `newParentCount`, plus time counters) |
| `isBorderRouter` | ext | `true` if device is a border router |
| `isLeader` | ext | `true` if device is the current leader |
| `isPrimaryBBR` | ext | `true` if device is the primary Backbone Border Router |
| `hostsService` | ext | `true` if device hosts a Thread service |
| `brCounters` | ext | Border routing packet counters |

**Examples:**

```bash
diagnostics list --fields 'networkDiagnostics=extAddress,rloc16'
diagnostics list --fields 'networkDiagnostics=extAddress,macCounters,mleCounters'
diagnostics list --fields 'networkDiagnostics=extAddress,vendorName,vendorModel,vendorSwVersion,threadStackVersion'
```

---

### `action` — Actions fields

Used with `actions list`, `actions get`.

| Field | Description |
|---|---|
| `id` | UUID assigned by the server |
| `type` | Task type: `addThreadDeviceTask`, `getNetworkDiagnosticTask`, `resetNetworkDiagCounterTask`, `getEnergyScanTask`, `updateDeviceCollectionTask` |
| `status` | `pending` → `active` → `completed` / `stopped` / `failed` (`addThreadDeviceTask` also: `undiscovered`, `attempted`) |
| `created` | ISO 8601 creation timestamp |
| `destination` | Target device address |
| `destinationType` | `extended`, `mleid`, or `rloc` |
| `types` | Requested TLV names (diagnostic and reset tasks) |
| `timeout` | Countdown timeout in seconds |
| `eui` | Joiner EUI-64 (`addThreadDeviceTask`) |
| `pskd` | Pre-Shared Key for the Device (`addThreadDeviceTask`) |
| `maxAge` | Max cache age in seconds (`updateDeviceCollectionTask`) |
| `maxRetries` | Max retries per device (`updateDeviceCollectionTask`) |
| `deviceCount` | Target device count (`updateDeviceCollectionTask`) |
| `channelMask` | Channel list (`getEnergyScanTask`) |
| `count` | Scan count (`getEnergyScanTask`) |
| `period` | Scan period in ms (`getEnergyScanTask`) |
| `scanDuration` | Scan duration in ms (`getEnergyScanTask`) |

**Examples:**

```bash
actions list --fields 'action=id,status,type'
actions get --action-id <UUID> --fields 'action=id,status,destination'
```

---

## Worked Examples

### 1. Discover devices — one-shot fetch

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi devices fetch

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    --output data/devices.json \
    devices fetch
```

---

### 2. Discover devices — manual enqueue → poll → list

```bash
# Enqueue and capture the action ID
ACTION_ID=$(PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue update-device-collection | jq -r '.[0].id')
echo "Enqueued: $ACTION_ID"

# Poll until terminal status
while true; do
    STATUS=$(PYTHONPATH=src python3 -m td_cli otbr-restapi \
        actions get --action-id "$ACTION_ID" | jq -r '.status')
    echo "status: $STATUS"
    [[ "$STATUS" == "completed" || "$STATUS" == "stopped" || "$STATUS" == "failed" ]] && break
    sleep 2
done

# List the refreshed devices
PYTHONPATH=src python3 -m td_cli otbr-restapi devices list
```

---

### 3. Fetch diagnostics for a single device

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    diagnostics fetch --device-id aabbccddeeff0011 --preset recommended
```

---

### 4. Fetch diagnostics for all devices

```bash
# Refresh device list and fetch (auto-saved to file)
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    diagnostics fetch-all --preset recommended

# Skip device refresh when the list was just updated
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    diagnostics fetch-all --preset recommended --no-update-devices

# Explicit output path
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    --output data/all-diagnostics.json \
    diagnostics fetch-all --preset recommended
```

---

### 5. Enqueue a diagnostic task and wait inline

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue get-network-diagnostic \
    --destination aabbccddeeff0011 \
    --preset recommended \
    --wait
```

---

### 6. Get node status and dataset

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi node get
PYTHONPATH=src python3 -m td_cli otbr-restapi node state get
PYTHONPATH=src python3 -m td_cli otbr-restapi node dataset active get
PYTHONPATH=src python3 -m td_cli otbr-restapi node dataset active get --text
```

---

### 7. Mesh diagnostics for a device

```bash
# All three TLVs for one device
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    mesh-diagnostics fetch --device-id aabbccddeeff0011

# Child table only
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    mesh-diagnostics children --device-id aabbccddeeff0011

# All mesh diagnostics for all router devices (recommended)
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    mesh-diagnostics fetch-all --routers-only
```

---

### 8. Commission a new joiner device

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue add-thread-device \
    --pskd J01NME \
    --eui aabbccddeeff0022 \
    --timeout 120
```

---

### 9. Reset diagnostic counters

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions enqueue reset-network-diag-counter \
    --destination aabbccddeeff0011 \
    --types macCounters mleCounters
```

---

### 10. Sparse field selection

```bash
# Device hostname and role
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    devices list --fields 'threadDevice=hostName,role'

# Action id and status only (lightweight polling view)
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions list --fields 'action=id,status,type'

# Single action with sparse fields
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    actions get --action-id 9ecae480-07a0-4b72-869d-15858196144e \
    --fields 'action=id,status'
```

---

### 11. Target a non-default OTBR host

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    --host 192.168.1.100 --port 8081 \
    devices list

PYTHONPATH=src python3 -m td_cli otbr-restapi \
    --base-url http://192.168.1.100:8081 \
    devices list
```

---

### 12. Raw envelope output

```bash
PYTHONPATH=src python3 -m td_cli otbr-restapi --raw devices list
```

---

### 13. Full topology sweep

```bash
# Default sweep — all three steps, auto-save all files
PYTHONPATH=src python3 -m td_cli otbr-restapi topology

# Skip mesh diagnostics (faster)
PYTHONPATH=src python3 -m td_cli otbr-restapi topology --skip-mesh-diagnostics

# Remote OTBR, custom data directory
PYTHONPATH=src python3 -m td_cli otbr-restapi \
    --host 192.168.1.10 --datadir /tmp/scan \
    topology
```
