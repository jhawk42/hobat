# OTBR REST API CLI — Command Reference

CLI wrapper for the OpenThread Border Router REST API.

| Script | Output style |
|---|---|
| `otbr_restapi_cli.py` | Flattened (JSON:API envelopes unwrapped) |

Run from the project root with:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py [global-options] <command> ...
```

### Raw output — two equivalent approaches

Both of the following produce identical output:

```bash

# Using the standard script with --raw (raw per-invocation)
PYTHONPATH=src python3 src/otbr_restapi_cli.py --raw devices list
```

---

## Global Options

These options apply to every command and must be placed **before** the subcommand.

| Option | Default | Description |
|---|---|---|
| `--host HOST` | `localhost` | OTBR REST API host |
| `--port PORT` | `8081` | OTBR REST API port |
| `--base-url URL` | — | Override host/port with a full base URL |
| `--timeout SECS` | `10` | HTTP request timeout in seconds |
| `--accept MIME` | `application/vnd.api+json` | Default `Accept` header (`application/vnd.api+json`, `application/json`, `text/plain`) |
| `--raw` | off | Return raw API envelopes instead of flattened output |
| `--output FILE` | — | Write JSON result to a file instead of stdout |
| `--datadir DIR` | auto | Data directory for file reads/writes (falls back to `$TD_DATA_DIR`, then `/data`, then `./data`) |
| `--poll-interval FLOAT` | `2.0` | Seconds between action status polls |
| `--poll-timeout FLOAT` | `120.0` | Max wall-clock seconds to wait for an action to complete |
| `--no-progress` | off | Suppress per-device `[N/T] id → status (Xs)` progress lines on `fetch-all` commands |
| `--no-auto-output` | off | Disable automatic output file naming; send JSON to stdout instead of `<datadir>/td-otbr-restapi-<resource>-<command>.json` |

---

## Commands

### `node`

Read or mutate local OTBR node data.

#### `node get`

Get the OTBR node record from `/api/node`.

```
node get
```

No arguments.

**Examples:**

```bash
# Print full node record to stdout
PYTHONPATH=src python3 src/otbr_restapi_cli.py node get

# Save node record to a file
PYTHONPATH=src python3 src/otbr_restapi_cli.py --output data/node.json node get
```

#### `node state get`

Get current Thread radio state.

```
node state get
```

**Examples:**

```bash
# Check whether Thread is enabled or disabled
PYTHONPATH=src python3 src/otbr_restapi_cli.py node state get

# Check state on a remote OTBR
PYTHONPATH=src python3 src/otbr_restapi_cli.py --host 192.168.1.10 node state get
```

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
# Enable Thread radio
PYTHONPATH=src python3 src/otbr_restapi_cli.py node state set --value enable

# Disable Thread radio
PYTHONPATH=src python3 src/otbr_restapi_cli.py node state set --value disable
```

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
# Get the active dataset as JSON
PYTHONPATH=src python3 src/otbr_restapi_cli.py node dataset active get

# Get the active dataset as a raw TLV hex string
PYTHONPATH=src python3 src/otbr_restapi_cli.py node dataset active get --text
```

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
# Set dataset from a saved JSON file
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    node dataset active set --json-file data/dataset.json

# Set dataset from an inline TLV hex string
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
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
| `--fields FIELDS` | Repeatable sparse-field selector, e.g. `threadDevice=hostname,role` |
| `--with-meta` | Include collection `meta` alongside the flattened items |

**Examples:**

```bash
# List all devices with all fields
PYTHONPATH=src python3 src/otbr_restapi_cli.py devices list

# List only hostname and role for each device
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    devices list --fields 'threadDevice=hostName,role'

# Include collection meta (total count, offset, limit)
PYTHONPATH=src python3 src/otbr_restapi_cli.py devices list --with-meta
```

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
# Get all fields for a specific device
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    devices get --device-id aabbccddeeff0011

# Get only extAddress and role
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    devices get --device-id aabbccddeeff0011 \
    --fields 'threadDevice=extAddress,role'
```

#### `devices fetch`

Trigger `updateDeviceCollectionTask`, wait for completion, then return the populated device list. Combines enqueue + poll + list in one call.

```
devices fetch [--device-count N] [--task-timeout SECS] [--max-age SECS] [--max-retries N]
```

| Option | Default | Description |
|---|---|---|
| `--device-count` | `200` | Max devices to discover |
| `--task-timeout` | `300` | Server-side task timeout in seconds |
| `--max-age` | `60` | Max age of cached device entries in seconds |
| `--max-retries` | `5` | Max retries per device |

**Examples:**

```bash
# Discover up to 50 devices and print the list
PYTHONPATH=src python3 src/otbr_restapi_cli.py devices fetch

# Discover up to 20 devices with a shorter timeout and save to file
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    --output data/devices.json \
    devices fetch --device-count 20 --task-timeout 30
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
# List all cached diagnostics with all fields
PYTHONPATH=src python3 src/otbr_restapi_cli.py diagnostics list

# List only extAddress, rloc16, and macCounters
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    diagnostics list --fields 'networkDiagnostics=extAddress,rloc16,macCounters'
```

#### `diagnostics get`

Get a single diagnostic record by ID.

```
diagnostics get --diagnostics-id ID
```

**Examples:**

```bash
# Retrieve a specific diagnostic record by its UUID
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    diagnostics get --diagnostics-id a6a0b433-437e-45bf-9994-58e0d7b32399

# Retrieve and save to file
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    --output data/diag-a6a0.json \
    diagnostics get --diagnostics-id a6a0b433-437e-45bf-9994-58e0d7b32399
```

#### `diagnostics fetch`

Enqueue `getNetworkDiagnosticTask` for one device, wait for completion, and return the diagnostic result. MAC counter enrichment is applied by default (see `--no-enrich-mac-counters`).

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
| `--task-timeout` | `93` | Server-side task timeout in seconds |
| `--destination-type` | `extended` | Destination addressing mode |
| `--no-fallback` | off | Disable TLV fallback retry; on failure, skip the device immediately |
| `--fallback-preset` | `minimal` | TLV preset to retry with when the primary request fails (`medium`, `minimal`, or `basic`) |
| `--no-enrich-mac-counters` | off | Return raw `macCounters` values only; skip computed totals and ratios |

By default, if a device fails to respond to the primary TLV set, the command automatically retries with the `--fallback-preset` TLV set before giving up (P1). Pass `--no-fallback` to disable this retry.

**Examples:**

```bash
# Fetch diagnostics for a device using the recommended preset (auto-saved to file)
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    diagnostics fetch --device-id aabbccddeeff0011 --preset recommended

# Fetch only macCounters and mleCounters; disable enrichment
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    diagnostics fetch --device-id aabbccddeeff0011 \
    --types extAddress rloc16 macCounters mleCounters \
    --no-enrich-mac-counters

# Fetch with no fallback retry and print to stdout only
PYTHONPATH=src python3 src/otbr_restapi_cli.py --no-auto-output \
    diagnostics fetch --device-id aabbccddeeff0011 \
    --preset recommended --no-fallback
```

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
| `--task-timeout` | `93` | Server-side task timeout per device |
| `--destination-type` | `extended` | Destination addressing mode |
| `--no-update-devices` | off | Skip `updateDeviceCollectionTask`; use the cached device list as-is |
| `--no-fallback` | off | Disable per-device TLV fallback retry on failure |
| `--fallback-preset` | `minimal` | TLV preset to retry with when a device fails (`medium`, `minimal`, or `basic`) |
| `--no-enrich-mac-counters` | off | Return raw `macCounters` without computed totals and ratios |

> **Breaking change from earlier versions:** `--update-devices` has been replaced by `--no-update-devices`. Device list refresh now runs by default; pass `--no-update-devices` to opt out.

Results are automatically written to `<datadir>/td-otbr-restapi-diagnostics-fetch-all.json` unless `--no-auto-output` or `--output` is specified. Per-device progress (`[N/T] id → status (Xs)`) is printed to stderr.

**Examples:**

```bash
# Fetch diagnostics for all devices — refresh device list, enrich MAC counters, auto-save
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    diagnostics fetch-all --preset recommended

# Skip device refresh (device list was just updated)
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    diagnostics fetch-all --preset recommended --no-update-devices

# Fetch for two specific devices, raw counters only, suppress progress
PYTHONPATH=src python3 src/otbr_restapi_cli.py --no-progress \
    diagnostics fetch-all \
    --device-ids aabbccddeeff0011 aabbccddeeff0022 \
    --no-enrich-mac-counters

# Print to stdout only (no file write)
PYTHONPATH=src python3 src/otbr_restapi_cli.py --no-auto-output \
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

**Examples:**

```bash
# List all queued/completed actions
PYTHONPATH=src python3 src/otbr_restapi_cli.py actions list

# List only id, type, and status (lightweight polling view)
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions list --fields 'action=id,type,status'
```

#### `actions get`

Get a single action by ID (useful for polling status).

```
actions get --action-id ACTION_ID
```

Action `status` values: `running` · `completed` · `stopped` · `failed`

**Examples:**

```bash
# Poll the status of an action by UUID
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions get --action-id 9ecae480-07a0-4b72-869d-15858196144e

# Poll action status and save the result
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    --output data/action-status.json \
    actions get --action-id 9ecae480-07a0-4b72-869d-15858196144e
```

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
# Commission a joiner identified by EUI-64
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue add-thread-device \
    --eui aabbccddeeff0022 \
    --pskd J01NME \
    --timeout 120

# Commission using a joiner discerner value
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue add-thread-device \
    --discerner 0xabc \
    --pskd S3CRET
```

#### `actions enqueue get-network-diagnostic`

Enqueue `getNetworkDiagnosticTask` for a destination address.

```
actions enqueue get-network-diagnostic --destination DEST
    [--types TLV ...]
    [--preset {recommended,full,minimal}]
    [--timeout SECS]
    [--destination-type TYPE]
    [--wait]
```

| Option | Default | Description |
|---|---|---|
| `--destination` | required | Destination address |
| `--types` | — | TLV names or integers (required unless `--preset` given) |
| `--preset` | — | `recommended`, `full`, or `minimal` |
| `--timeout` | — | Server-side task timeout in seconds |
| `--destination-type` | — | Destination addressing mode |
| `--wait` | off | Poll until completion and return the diagnostic result; exit code 4 on stopped/failed |

**Examples:**

```bash
# Enqueue a diagnostic task and return immediately with the action record
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue get-network-diagnostic \
    --destination aabbccddeeff0011 \
    --preset recommended

# Enqueue and block until completed, returning the diagnostic result directly
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue get-network-diagnostic \
    --destination aabbccddeeff0011 \
    --types extAddress rloc16 macCounters mleCounters vendorName vendorModel \
    --timeout 120 \
    --wait
```

#### `actions enqueue reset-network-diag-counter`

Enqueue `resetNetworkDiagCounterTask`.

```
actions enqueue reset-network-diag-counter --types TYPE ...
    [--destination DEST]
    [--timeout SECS]
    [--destination-type TYPE]
```

**Examples:**

```bash
# Reset MAC and MLE counters on a specific device
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue reset-network-diag-counter \
    --destination aabbccddeeff0011 \
    --types macCounters mleCounters

# Reset only MLE counters with a custom timeout
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue reset-network-diag-counter \
    --destination aabbccddeeff0011 \
    --types mleCounters \
    --timeout 60
```

#### `actions enqueue get-energy-scan`

Enqueue `getEnergyScanTask`.

```
actions enqueue get-energy-scan --destination DEST
    --channel-mask MASK ...
    --count N
    --period N
    --scan-duration N
    --timeout SECS
    [--destination-type TYPE]
```

**Examples:**

```bash
# Energy scan on channels 11 and 15, 3 samples each
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue get-energy-scan \
    --destination aabbccddeeff0011 \
    --channel-mask 11 15 \
    --count 3 --period 32 --scan-duration 50 \
    --timeout 60

# Broader scan across channels 11–26
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue get-energy-scan \
    --destination aabbccddeeff0011 \
    --channel-mask 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 \
    --count 5 --period 32 --scan-duration 100 \
    --timeout 120
```

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
| `--device-count` | `50` | Max devices to discover |
| `--max-age` | `30` | Max age of cached device entries in seconds |
| `--max-retries` | `5` | Max retries per device |
| `--timeout` | `60` | Server-side task timeout in seconds |

**Polling / waiting for completion:**

This command has no `--wait` flag. It returns as soon as the action is enqueued. To wait for the task:

- **Recommended:** use `devices fetch` — it enqueues, polls, and returns the device list in one call.
- **Manual:** capture the `id` from the returned action record, then call `actions get --action-id <id>` in a loop until `status` is `completed`, `stopped`, or `failed`. Use the global `--poll-interval` and `--poll-timeout` options when issuing subsequent `actions get` calls.

Action `status` values: `running` · `completed` · `stopped` · `failed`

**Examples:**

```bash
# Enqueue update-device-collection with defaults and return immediately
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue update-device-collection

# Enqueue with custom parameters
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue update-device-collection \
    --device-count 20 --max-age 60 --max-retries 3 --timeout 90

# Enqueue and capture the action ID (output is a JSON array; id is at index 0)
ACTION_ID=$(PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue update-device-collection | jq -r '.[0].id')
echo "Enqueued action: $ACTION_ID"

# Poll until the action reaches a terminal status
while true; do
    STATUS=$(PYTHONPATH=src python3 src/otbr_restapi_cli.py \
        actions get --action-id "$ACTION_ID" | jq -r '.status')
    echo "status: $STATUS"
    [[ "$STATUS" == "completed" || "$STATUS" == "stopped" || "$STATUS" == "failed" ]] && break
    sleep 2
done

# Once completed, list the refreshed devices
PYTHONPATH=src python3 src/otbr_restapi_cli.py devices list

# Preferred: enqueue + wait + list devices in one shot
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    devices fetch --device-count 20 --task-timeout 90

# Combined enqueue + wait with custom poll tuning
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    --poll-interval 3.0 --poll-timeout 120.0 \
    devices fetch --device-count 50 --max-age 30
```

---

### `mesh-diagnostics`

Fetch mesh-diagnostic TLVs via `otMeshDiag`. These require an additional round-trip on the server and have higher latency than standard diagnostic TLVs.

Common options for all `mesh-diagnostics` subcommands:

| Option | Default | Description |
|---|---|---|
| `--device-id` | required | Device extAddress (16-char hex) |
| `--task-timeout` | `300` | Server-side task timeout in seconds |
| `--poll-timeout` | `360.0` | Max wall-clock seconds to wait |
| `--destination-type` | `extended` | Destination addressing mode |

#### `mesh-diagnostics children`

Fetch the child table for a device (TLV 29).

```
mesh-diagnostics children --device-id DEVICE_ID [options]
```

> **Router / leader devices only.** The server skips the `children` field when the device is a child (RLOC16 lower 10 bits are non-zero). Querying a child device returns a record with no `children` field.
>
> To find routers, first check roles:
> ```bash
> PYTHONPATH=src python3 src/otbr_restapi_cli.py \
>     devices list --fields 'threadDevice=extAddress,role,hostName'
> ```
> or check diagnostics for entries that have a `routerId` field:
> ```bash
> PYTHONPATH=src python3 src/otbr_restapi_cli.py \
>     diagnostics list --fields 'networkDiagnostics=extAddress,rloc16,routerId'
> ```

**Examples:**

```bash
# Fetch child table for a router device
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    mesh-diagnostics children --device-id aabbccddeeff0011

# Fetch child table and save to file
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    --output data/children-aabb.json \
    mesh-diagnostics children --device-id aabbccddeeff0011
```

#### `mesh-diagnostics child-ipv6`

Fetch child IPv6 addresses for a device (TLV 30).

```
mesh-diagnostics child-ipv6 --device-id DEVICE_ID [options]
```

> **Router / leader devices only.** Same restriction as `children` above.

**Examples:**

```bash
# List all IPv6 addresses assigned to children of a router
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    mesh-diagnostics child-ipv6 --device-id aabbccddeeff0011

# With a longer task timeout for a slow network
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    mesh-diagnostics child-ipv6 --device-id aabbccddeeff0011 --task-timeout 600
```

#### `mesh-diagnostics router-neighbors`

Fetch router neighbor table for a device (TLV 31).

```
mesh-diagnostics router-neighbors --device-id DEVICE_ID [options]
```

> **Router / leader devices only.** Same restriction as `children` above.

**Examples:**

```bash
# Fetch router neighbor table for a device
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    mesh-diagnostics router-neighbors --device-id aabbccddeeff0011

# Fetch and save to file
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    --output data/router-nbrs-aabb.json \
    mesh-diagnostics router-neighbors --device-id aabbccddeeff0011
```

#### `mesh-diagnostics fetch`

Fetch a caller-specified subset of mesh-diagnostic TLVs for one device.

```
mesh-diagnostics fetch --device-id DEVICE_ID
    [--types children childIpv6Addresses routerNeighbors]
    [--task-timeout SECS]
    [--poll-timeout FLOAT]
    [--destination-type TYPE]
```

`--types` defaults to all three TLVs when omitted.

> **Router / leader devices only.** `children`, `childIpv6Addresses`, and `routerNeighbors` are silently omitted from the response when the target device is a child. Querying a child returns a record with only the base diagnostic fields.
>
> To identify routers before querying:
> ```bash
> PYTHONPATH=src python3 src/otbr_restapi_cli.py \
>     devices list --fields 'threadDevice=extAddress,role,hostName'
> ```

**Examples:**

```bash
# Fetch all three mesh-diagnostic TLVs for a router device
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    mesh-diagnostics fetch --device-id aabbccddeeff0011

# Fetch only children and child IPv6 addresses
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    mesh-diagnostics fetch --device-id aabbccddeeff0011 \
    --types children childIpv6Addresses

# Single TLV — child table only
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    mesh-diagnostics fetch --device-id aabbccddeeff0011 \
    --types children
```

#### `mesh-diagnostics fetch-all`

Fetch mesh diagnostics for all known devices (or a given list), one device at a time. The device list is automatically refreshed before fetching (pass `--no-update-devices` to skip).

```
mesh-diagnostics fetch-all [--device-ids ID ...]
    [--types TLV ...]
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
| `--task-timeout` | `300` | Server-side task timeout per device |
| `--poll-timeout` | `360.0` | Max wall-clock seconds per device action |
| `--destination-type` | `extended` | Destination addressing mode |
| `--no-update-devices` | off | Skip `updateDeviceCollectionTask`; use the cached device list as-is |
| `--routers-only` | off | Filter device list to router devices only (`rloc16` lower 10 bits == 0); skips child devices that would return empty records |

> **Breaking change from earlier versions:** `--update-devices` has been replaced by `--no-update-devices`. Device list refresh now runs by default.

Results are automatically written to `<datadir>/td-otbr-restapi-mesh-diagnostics-fetch-all.json` unless `--no-auto-output` or `--output` is specified.

**Examples:**

```bash
# Fetch all mesh-diagnostic TLVs for router devices only (recommended usage)
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    mesh-diagnostics fetch-all --routers-only

# Fetch for all devices, skip device refresh
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    mesh-diagnostics fetch-all --no-update-devices

# Fetch only router neighbor tables for two specific devices
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
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
| `--no-enrich-mac-counters` | off | Disable MAC counter enrichment on diagnostic results |
| `--no-fallback` | off | Disable per-device TLV fallback retry in the diagnostics step |
| `--fallback-preset` | `minimal` | Fallback TLV preset for Step 2 |

Progress for each step and each device is printed to stderr. Pass `--no-progress` (global flag) to suppress. The command returns `None`; all data is written to files rather than printed to stdout.

**Examples:**

```bash
# Run the full topology sweep with defaults
PYTHONPATH=src python3 src/otbr_restapi_cli.py topology

# Run on a remote OTBR, save to a custom data directory
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    --host 192.168.1.10 --datadir /tmp/topology \
    topology

# Skip device refresh (already done by a prior command)
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    topology --skip-devices

# Diagnostics step only, no mesh diagnostics
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    topology --skip-mesh-diagnostics

# Silent (no progress output)
PYTHONPATH=src python3 src/otbr_restapi_cli.py --no-progress topology
```

---

## `--fields` Sparse Field Reference

The `--fields` option restricts which attributes are returned. The server filters at the source, so only the requested attributes are transmitted.

**Syntax:** `--fields 'TYPE=field1,field2'` or `--fields TYPE` (all fields of that type).  
**Repeatable:** pass `--fields` multiple times to select fields from more than one type.

The `TYPE` matches the JSON:API resource `type` value for the collection being queried.

---

### `threadDevice` / `threadBorderRouter` — Devices fields

Used with `devices list`, `devices get`, `devices fetch`.

| Field | Type | Description |
|---|---|---|
| `extAddress` | string (hex) | 64-bit IEEE 802.15.4 extended address — device ID |
| `mlEidIid` | string (hex) | Mesh-Local EID Interface Identifier |
| `omrIpv6Address` | string (IPv6) | Off-Mesh-Routable IPv6 address |
| `hostName` | string | mDNS hostname (`.local`) |
| `role` | string | Thread role: `leader`, `router`, `child`, `sleepy-child` |
| `mode` | object | Device mode flags (see sub-fields below) |
| `mode.deviceTypeFTD` | bool | `true` = Full Thread Device, `false` = Minimal Thread Device |
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
| `leaderData` | object | Leader data (see sub-fields below) |
| `leaderData.partitionId` | number | Partition ID |
| `leaderData.weighting` | number | Leader weighting |
| `leaderData.dataVersion` | number | Network data version |
| `leaderData.stableDataVersion` | number | Stable network data version |
| `leaderData.leaderRouterId` | number | Current leader's router ID |
| `baId` | string (hex) | Border Agent ID |
| `baState` | string | Border Agent state |

**Examples:**

```bash
# Hostname, role, and mode only
devices list --fields 'threadDevice=hostName,role,mode'

# All threadDevice fields (omit =... part)
devices list --fields threadDevice

# Only mode sub-fields
devices list --fields 'threadDevice=mode.deviceTypeFTD,mode.rxOnWhenIdle'
```

---

### `networkDiagnostics` — Diagnostics fields

Used with `diagnostics list`, `diagnostics get`, `diagnostics fetch`, `diagnostics fetch-all`.

These correspond directly to the Thread network diagnostic TLVs requested via `--types` / `--preset`.

| Field | TLV | Description |
|---|---|---|
| `extAddress` | 0 | 64-bit extended MAC address |
| `rloc16` | 1 | 16-bit RLOC (hex string, e.g. `0x1400`) |
| `routerId` | 1 | Router ID (derived from RLOC16; only present for routers) |
| `mode` | 2 | Device mode flags (`deviceTypeFTD`, `rxOnWhenIdle`, `fullNetworkData`) |
| `timeout` | 3 | Max polling period for SEDs (seconds) |
| `connectivity` | 4 | Connectivity info (`parentPriority`, `linkQuality1/2/3`, `leaderCost`, `idSequence`, `activeRouters`, `sedBufferSize`, `sedDatagramCount`) |
| `route` | 5 | Route64 info: `idSequence`, `routeData[]` (each with `routeId`, `linkQualityIn`, `linkQualityOut`, `routeCost`) |
| `leaderData` | 6 | Leader data object (same sub-fields as device `leaderData`) |
| `networkData` | 7 | Network data (hex string) |
| `ipv6Addresses` | 8 | List of IPv6 addresses |
| `macCounters` | 9 | MAC packet counters (raw: `ifInUnknownProtos`, `ifInErrors`, `ifOutErrors`, `ifInUcastPkts`, `ifInBroadcastPkts`, `ifInDiscards`, `ifOutUcastPkts`, `ifOutBroadcastPkts`, `ifOutDiscards`; enriched: `ifintotalpkts`, `ifouttotalpkts`, `iftotalpkts`, `iftotalerrors`, `iftotaldiscards`, plus per-direction ratio and pct fields) |
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
| `mleCounters` | 34 | MLE counters (`radioDisabledCount`, `detachedRoleCount`, `childRoleCount`, `routerRoleCount`, `leaderRoleCount`, `attachAttemptsCount`, `partIdChangesCount`, `betterPartIdAttachAttemptsCount`, `newParentCount`, plus time counters `totalTrackingTime`, `radioDisabledTime`, etc.) |
| `isBorderRouter` | ext | `true` if device is a border router (OTBR extension) |
| `isLeader` | ext | `true` if device is the current leader (OTBR extension) |
| `isPrimaryBBR` | ext | `true` if device is the primary Backbone Border Router (OTBR extension) |
| `hostsService` | ext | `true` if device hosts a Thread service (OTBR extension) |
| `brCounters` | ext | Border routing packet counters (OTBR extension) |

**Examples:**

```bash
# Minimal identity fields
diagnostics list --fields 'networkDiagnostics=extAddress,rloc16,role'

# Counters only
diagnostics list --fields 'networkDiagnostics=extAddress,macCounters,mleCounters'

# Vendor info
diagnostics list --fields 'networkDiagnostics=extAddress,vendorName,vendorModel,vendorSwVersion,threadStackVersion'
```

---

### `action` — Actions fields

Used with `actions list`, `actions get`.

The available fields depend on the task type; `id`, `type`, `status`, and `created` are always present.

| Field | Description |
|---|---|
| `id` | UUID assigned by the server |
| `type` | Task type: `addThreadDeviceTask`, `getNetworkDiagnosticTask`, `resetNetworkDiagCounterTask`, `getEnergyScanTask`, `updateDeviceCollectionTask` |
| `status` | `pending` → `active` → `completed` / `stopped` / `failed` (addThreadDeviceTask also uses `undiscovered`, `attempted`) |
| `created` | ISO 8601 creation timestamp |
| `destination` | Target device extAddress (diagnostic/reset/scan/update tasks) |
| `destinationType` | `extended` or `mlEidIid` |
| `types` | Requested TLV names (diagnostic and reset tasks) |
| `timeout` | Countdown timeout in seconds |
| `eui` | Joiner EUI-64 (addThreadDeviceTask) |
| `pskd` | Pre-Shared Key for the Device (addThreadDeviceTask) |
| `maxAge` | Max cache age in seconds (updateDeviceCollectionTask) |
| `maxRetries` | Max retries per device (updateDeviceCollectionTask) |
| `deviceCount` | Target device count (updateDeviceCollectionTask) |
| `channelMask` | Channel list (getEnergyScanTask) |
| `count` | Scan count (getEnergyScanTask) |
| `period` | Scan period in ms (getEnergyScanTask) |
| `scanDuration` | Scan duration in ms (getEnergyScanTask) |

**Examples:**

```bash
# ID and status only — cheap polling view
actions list --fields 'action=id,status,type'

# Full view with created timestamp
actions list --fields 'action=id,type,status,created,destination'
```

---

## Worked Examples

### 1. Discover devices — one-shot fetch

Enqueue `updateDeviceCollectionTask`, wait for it, and return the device list in a single call:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py devices fetch
```

Save the result to a file:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    --output data/devices.json \
    devices fetch
```

---

### 2. Discover devices — manual enqueue → poll → list

**Step 1 — Enqueue and capture the action ID:**

The enqueue output is a JSON array; the action `id` is at index 0.

```bash
ACTION_ID=$(PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue update-device-collection | jq -r '.[0].id')
echo "Enqueued action: $ACTION_ID"
```

**Step 2 — Poll until the action reaches a terminal status:**

```bash
while true; do
    STATUS=$(PYTHONPATH=src python3 src/otbr_restapi_cli.py \
        actions get --action-id "$ACTION_ID" | jq -r '.status')
    echo "status: $STATUS"
    [[ "$STATUS" == "completed" || "$STATUS" == "stopped" || "$STATUS" == "failed" ]] && break
    sleep 2
done
```

Terminal values for `status`: `completed` · `stopped` · `failed`.

**Step 3 — List the refreshed devices:**

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py devices list
```

---

### 3. Fetch diagnostics for a single device

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    diagnostics fetch --device-id aabbccddeeff0011
```

Using the `recommended` TLV preset:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    diagnostics fetch --device-id aabbccddeeff0011 --preset recommended
```

---

### 4. Fetch diagnostics for all devices

Refresh the device list and fetch diagnostics for every device (device refresh is on by default):

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    diagnostics fetch-all --preset recommended
```

Results are auto-saved to `<datadir>/td-otbr-restapi-diagnostics-fetch-all.json`.

Skip device refresh when the list was just updated:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    diagnostics fetch-all --preset recommended --no-update-devices
```

Explicit output path (overrides auto-naming):

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    --output data/all-diagnostics.json \
    diagnostics fetch-all --preset recommended
```

---

### 5. Fetch diagnostics — manual multi-step flow

**Step 1 — Refresh devices:**

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py devices fetch
```

**Step 2 — Fetch diagnostics (skip device refresh since Step 1 just ran it):**

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    diagnostics fetch-all --preset recommended --no-update-devices
```

---

### 6. Enqueue a diagnostic task and wait inline

The `--wait` flag polls until completion and returns the diagnostic result directly:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue get-network-diagnostic \
    --destination aabbccddeeff0011 \
    --preset recommended \
    --wait
```

---

### 7. Get node status and dataset

```bash
# Read full node record
PYTHONPATH=src python3 src/otbr_restapi_cli.py node get

# Check Thread radio state
PYTHONPATH=src python3 src/otbr_restapi_cli.py node state get

# Read the active dataset as JSON
PYTHONPATH=src python3 src/otbr_restapi_cli.py node dataset active get

# Read the active dataset as a TLV hex string
PYTHONPATH=src python3 src/otbr_restapi_cli.py node dataset active get --text
```

---

### 8. Mesh diagnostics for a device

All three mesh-diagnostic TLVs for one device:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    mesh-diagnostics fetch --device-id aabbccddeeff0011
```

Children table only:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    mesh-diagnostics children --device-id aabbccddeeff0011
```

All mesh diagnostics for every router device (recommended — skips child devices):

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    mesh-diagnostics fetch-all --routers-only
```

---

### 9. Commission a new joiner device

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions enqueue add-thread-device \
    --pskd J01NME \
    --eui aabbccddeeff0022 \
    --timeout 120
```

---

### 10. Sparse field selection

Return only `hostname` and `role` for each device:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    devices list --fields 'threadDevice=hostname,role'
```

Return only `id` and `status` for each action:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    actions list --fields 'action=id,status,type'
```

---

### 11. Target a non-default OTBR host

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    --host 192.168.1.100 --port 8081 \
    devices list
```

Or with a full base URL:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    --base-url http://192.168.1.100:8081 \
    devices list
```

---

### 12. Raw envelope output

Get the raw JSON:API envelope from the server instead of the flattened list:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py --raw devices list
```

---

### 13. Full topology sweep

Run device discovery, network diagnostics, and mesh diagnostics in one command, writing all three output files automatically:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py topology
```

Skip the mesh-diagnostics step (faster when only network diagnostics are needed):

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py topology --skip-mesh-diagnostics
```

Run against a remote OTBR and save to a specific data directory:

```bash
PYTHONPATH=src python3 src/otbr_restapi_cli.py \
    --host 192.168.1.10 --datadir /tmp/scan \
    topology
```
