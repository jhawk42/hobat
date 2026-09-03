# td_cli — Command Reference

Thread Network Topology Dashboard CLI.

Run from the project root with:

```bash
PYTHONPATH=src python3 -m td_cli [global-options] <command> ...
```

---

## Global Options

| Option | Description |
|---|---|
| `-h`, `--help` | Show help message and exit |
| `--verbose`, `-v` | Enable verbose (INFO) logging |
| `--debug`, `-d` | Enable debug logging |
| `--output FILE`, `-o FILE` | Write command output to file |
| `--datadir DIR` | Data directory for JSON reads/writes (takes precedence over `TD_DATA_DIR`). If omitted and `TD_DATA_DIR` is unset: use `/data` when present; otherwise create/use `./data` under the current run directory. |

---

## Command Summary

| Command | Description |
|---|---|
| `otbr-cli` | Scan OTBR CLI commands |
| `otbr-restapi` | Query OTBR REST API commands |
| `ha-matter-ws` | Read commissioned nodes from Home Assistant Matter Server |
| `mdns` | Scan Thread-related mDNS scopes |
| `process-eve` | Parse and enhance an Eve Thread layout file |
| `health` | Process, inspect, or purge health history |
| `system` | Create or restore complete Hobat data-directory backups |
| `merge-dataset` (`merge-data`) | Merge Thread (otbr-cli, otbr-restapi, eve, mdns) sources into one cache file; `merge-data` is a compatibility alias |
| `merge-extaddr` | Read or upsert one device label, or bulk-merge missing extaddr entries into the static map |

---

## Commands Usage

### `otbr-cli`

```text
td_cli otbr-cli {thread-network-info,router-table,topology,meshdiag,networkdiag} ...
```

`otbr-cli topology` runs seven steps in order: thread network info, router
table, meshdiag topology, networkdiag multicast-network, networkdiag fetch-all,
meshdiag router-neighbor tables, and meshdiag child tables. It attempts every
step and returns the first non-zero step result.

### `otbr-restapi`

```text
td_cli otbr-restapi [global-forwarded-options] {download,node,devices,diagnostics,actions,mesh-diagnostics,topology} ...
```

### `ha-matter-ws`

```text
td_cli ha-matter-ws [source-options] {server-info,devices,diagnostics,mesh-diagnostics,topology,all} ...
```

Source options include `--uri`, `--connect-timeout`, `--request-timeout`,
`--settle-timeout`, `--output`, and `--no-progress`. The default URI is
`ws://localhost:5580/ws`. `devices`, `diagnostics`, and `mesh-diagnostics`
provide `get` and `fetch-all` commands; `devices` also provides `list`.
`topology` writes the canonical topology snapshot, while `all` performs one
inventory transaction and writes every fixed snapshot plus the collection
outcome. `--output` applies only to leaf commands.

Normal output excludes Matter credentials. Collection is read-only and limited
to nodes commissioned to the connected controller. Missing diagnostics on an
unavailable or non-Thread Matter node are not treated as zero values.

### `mdns`

```text
td_cli mdns [--browse-timeout SECONDS] [--haptcp] [--mattertcpsupported] [SCOPE]
```

The owning mDNS parser uses a 3-second idle timeout unless
`TD_MDNS_BROWSE_TIMEOUT` or `--browse-timeout` overrides it. `--haptcp` adds
`_hap._tcp.local.` for `thread` or `hap`; `--mattertcpsupported` includes
`_matter._tcp` records whose `T=1` TXT value reports TCP support.

### `process-eve`

```text
td_cli process-eve ...
```

### `health`

```text
td_cli health purge [--keep-days DAYS] [--dry-run] [--yes] [--json]
td_cli health purge-all [--dry-run] [--yes] [--json]
td_cli health purge-by-device --device EXTADDR [--network NETWORK_ID]
                              [--dry-run] [--yes] [--json]
```

Age purge defaults to 180 retained days and uses an exclusive UTC cutoff.
`purge-all` removes health-domain records and roster entries but preserves the
shared database, migrations, and non-health tables. Per-device purge preserves
shared observations but invalidates assessments derived from affected
observations. Purge does not remove identities from collector snapshots,
exports, or existing backups.

### `system backups`

```text
td_cli system backups create --output DIRECTORY [--json]
td_cli system backups restore --input BACKUP [--yes] [--json]
```

Create writes a versioned, checksummed copy of the complete effective data
directory and snapshots `hobat_v1.db` through SQLite's backup API. The output
must not already exist or be inside the active data directory. Restore requires
confirmation, validates checksums and database integrity, stages the complete
replacement, and refuses an active database writer. Stop the web server and all
writers before restore. Backups are unredacted and can contain credentials.

### `merge-dataset`

```text
td_cli {merge-dataset,merge-data} ...
```

### `merge-extaddr`

```text
td_cli merge-extaddr [--read-extaddr EXTADDR | --update-extaddr EXTADDR]
                        [--device-label DEVICE_LABEL] [bulk-merge-options]
```

Single-record operations use the configured data directory's
`td-static-extaddr-device-label.json`:

```bash
# Read one mapping without writing.
PYTHONPATH=src python3 -m td_cli --datadir ./data \
  merge-extaddr --read-extaddr 4e866ce96501b9ed

# Update an existing mapping or insert it when absent.
PYTHONPATH=src python3 -m td_cli --datadir ./data \
  merge-extaddr --update-extaddr 4e866ce96501b9ed \
  --device-label "Office Sensor"
```

Read success writes one JSON object to stdout:

```json
{"deviceLabel": "Office Sensor", "extAddress": "4e866ce96501b9ed"}
```

Upsert success adds an `operation` field:

```json
{"deviceLabel": "Office Sensor", "extAddress": "4e866ce96501b9ed", "operation": "updated"}
```

`operation` is `inserted` for a new mapping and `updated` for an existing one.
It is response metadata and is not persisted. ExtAddresses are normalized to
lowercase. Upsert preserves unrelated records and fields, sorts the map, and
atomically replaces the file. If the map is missing, upsert creates it;
single-record read returns exit code `4` instead.

Single-record exit codes:

| Code | Meaning |
|---|---|
| `0` | Read or upsert succeeded |
| `2` | Invalid option combination or missing required option |
| `3` | File access or atomic-write failure |
| `4` | Static map is missing during read |
| `5` | Invalid extAddress, label, JSON shape, map record, or duplicate normalized extAddress |
| `6` | Valid extAddress is not present during read |

Labels allow Unicode, are trimmed, must contain 1–128 characters, and cannot
contain control characters. ExtAddress must contain exactly 16 hexadecimal
characters. Blank labels do not delete mappings.

---

## `otbr-restapi` Summary

`td_cli otbr-restapi` forwards to OTBR REST API tooling:

- `download` routes to `otbr_restapi_download.py`
- `node`, `devices`, `diagnostics`, `actions`, `mesh-diagnostics`, `topology` route to `otbr_restapi_cli.py`

### Forwarded Global Options

These options must be placed after `otbr-restapi` and before its subcommand.

| Option | Description |
|---|---|
| `--host HOST` | OTBR REST API host |
| `--port PORT` | OTBR REST API port |
| `--base-url URL` | Full base URL override |
| `--timeout SECS` | HTTP request timeout |
| `--accept MIME` | Default Accept header |
| `--raw` | Return raw API envelopes |
| `--poll-interval FLOAT` | Seconds between action polls |
| `--poll-timeout FLOAT` | Max seconds to wait for action completion |
| `--no-progress` | Suppress per-device progress output |
| `--no-auto-output` | Disable automatic output file naming |
| `--lab` | Allow experimental `otbr-restapi` mutating commands (`node state set`, `node dataset active set`, `actions enqueue add-thread-device`, `actions enqueue reset-network-diag-counter`) |

### Commands and Subcommands

| Command | Subcommands | Purpose |
|---|---|---|
| `download` | *(none)* | Download OTBR REST API endpoint snapshots to JSON files |
| `node` | `get`, `state get`, `state set`, `dataset active get`, `dataset active set` | Read/mutate local OTBR node and active dataset |
| `devices` | `list`, `get`, `fetch` | List, read, or refresh device collection |
| `diagnostics` | `list`, `get`, `fetch`, `fetch-all` | Read or fetch network diagnostics |
| `actions` | `list`, `get`, `enqueue add-thread-device`, `enqueue get-network-diagnostic`, `enqueue reset-network-diag-counter`, `enqueue get-energy-scan`, `enqueue update-device-collection` | Inspect and enqueue OTBR action tasks |
| `mesh-diagnostics` | `children`, `child-ipv6`, `router-neighbors`, `fetch`, `fetch-all` | Fetch mesh-diagnostic TLV datasets |
| `topology` | *(none)* | Run full sweep: devices fetch + diagnostics fetch-all + mesh-diagnostics fetch-all |

---

## Data Directory Behavior

Data directory resolution precedence:

1. `--datadir` CLI argument
2. `TD_DATA_DIR` environment variable
3. Defaults (`/data` when present, otherwise `./data` under the current run directory)

When `TD_DATA_DIR` points at an empty or partially populated directory, command families now behave consistently:

| Family | Required local inputs | Optional local inputs | Missing-file behavior |
|---|---|---|---|
| `otbr-cli` | none | `td-static-extaddr-device-label.json` | Continue with no enrichment and log a warning |
| `mdns` | none | none | Continue unless the runtime browse/discovery itself fails |
| `process-eve` | `Eve Thread Network Layout.evethreadlayout` | none | Return `4` when the file is missing |
| `merge-extaddr` | Bulk merge: static map and merge input. Single read: static map. Single upsert: none. | none | Bulk/read return `4` for a missing required map; upsert creates a missing map atomically. |
| `merge-dataset` | `td-otbr-cli-thread-network-info.json` | `td-static-extaddr-device-label.json` and the merge source files listed in the plan | Return `4` when the seed is missing or no viable optional source loads |
| `otbr-restapi` | none, unless an explicit file argument is used by a mutating set command | command-dependent | Preserve OTBR REST API exit-code semantics |

Troubleshooting empty-data-dir runs:

- If `merge-dataset` returns `4`, confirm `td-otbr-cli-thread-network-info.json` exists and contains `prefix_omr_ipv6addr_prefix`.
- If an OTBR CLI command emits a warning about `td-static-extaddr-device-label.json`, the command still completed and wrote output without label enrichment.
- If `otbr-restapi` returns `4`, that still indicates an HTTP/action failure, not a local missing-file error.

### Final, checkpoint, and outcome files

Collectors atomically write mandatory final snapshots before reporting command
success. Long-running collectors may also replace a sibling `.partial.json`
checkpoint as records arrive. Checkpoints are transient progress data used by
the dashboard and never substitute for the final snapshot.

REST topology writes compatibility array snapshots plus
`td-otbr-restapi-diagnostics-fetch-all.outcome.json` and
`td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json`. Outcome sidecars
retain per-device status and partial-completion metadata without changing the
array shape consumed by the dashboard.

---

## Command Group Help Behavior

If you invoke a command group without the required deeper subcommand, `td_cli` prints contextual help for that group and exits successfully.

Examples:

- `td_cli otbr-cli meshdiag` prints `otbr-cli meshdiag` subcommand help
- `td_cli otbr-cli networkdiag` prints `otbr-cli networkdiag` subcommand help
- `td_cli otbr-restapi actions` prints `otbr-restapi actions` subcommand help
- `td_cli ha-matter-ws devices` prints `ha-matter-ws devices` subcommand help

---

## Subcommand Help Snapshots

### `otbr-cli`

```
usage: td_cli otbr-cli [-h]
                       {thread-network-info,router-table,meshdiag,networkdiag,topology}
                       ...

positional arguments:
  {thread-network-info,router-table,topology,meshdiag,networkdiag}
    thread-network-info        Scan and save thread network info
    router-table                Scan and save router table
    meshdiag                    Mesh diagnostic scans
    networkdiag                 Network diagnostic scans
    topology                    Run full otbr-cli topology sweep: thread-network-info, router-table, meshdiag topology, networkdiag multicast-network, networkdiag fetch-all, meshdiag routerneighbortable, meshdiag childtable
```

### `otbr-cli topology`

```
usage: td_cli otbr-cli topology [-h]

options:
  -h, --help  show this help message and exit
```

### `otbr-cli meshdiag`

```
usage: td_cli otbr-cli meshdiag [-h]
                                {topology,routerneighbortable,childtable,childip6}
                                ...

positional arguments:
  {topology,routerneighbortable,childtable,childip6}
    topology            Scan meshdiag topology
    routerneighbortable
                        Scan meshdiag router-neighbour table
    childtable          Scan meshdiag child table
    childip6            Scan meshdiag child IPv6 addresses
```

### `otbr-cli networkdiag`

```
usage: td_cli otbr-cli networkdiag [-h] {fetch-all,multicast-network,multicast-neighbors} ...

positional arguments:
  {fetch-all,multicast-network,multicast-neighbors}
    fetch-all       Scan and poll networkdiag topology (unicast, router-by-router)
    multicast-network
                        Scan networkdiag topology via multicast to all Thread devices (ff03::1)
    multicast-neighbors
                        Scan networkdiag topology via multicast to one-hop neighbors (ff02::1)
```

### `otbr-cli networkdiag fetch-all`

```
usage: td_cli otbr-cli networkdiag fetch-all [-h] [-c | -cno]

options:
  -h, --help           show this help message and exit
  -c, --children       Expand and include child nodes in the topology map (default)
  -cno, --children-no  Do not expand child nodes in the topology map
```

### `mdns`

```
usage: td_cli mdns [-h] [--browse-timeout SECONDS] [--haptcp]
                   [--mattertcpsupported]
                   [SCOPE]

positional arguments:
  SCOPE                 Scope filter: thread | br | hap | matter (default:
                        thread)

options:
  -h, --help            show this help message and exit
  --browse-timeout SECONDS
                        Seconds of idle time before auto-exit (default: 5, or
                        TD_MDNS_BROWSE_TIMEOUT env var)
  --haptcp              Also browse _hap._tcp.local. (Wi-Fi HomeKit
                        accessories). Applies when scope is 'thread' or 'hap'.
                        Off by default.
  --mattertcpsupported  Include _matter._tcp records where T=1 (TCP
                        supported). By default those records are excluded.
```

### `otbr-restapi`

```
usage: td_cli otbr-restapi [-h] [--host HOST] [--port PORT] [--base-url URL]
                           [--timeout SECS] [--accept MIME] [--raw]
                           [--poll-interval FLOAT] [--poll-timeout FLOAT]
                           [--no-progress] [--no-auto-output] [--lab]
                           {download,node,devices,diagnostics,actions,mesh-diagnostics,topology}
                           ...

positional arguments:
  {download,node,devices,diagnostics,actions,mesh-diagnostics,topology}
    download            Download OTBR REST API endpoints to JSON files
    node                Read or mutate local OTBR node data
    devices             Read OTBR devices
    diagnostics         Read OTBR network diagnostics
    actions             Read or enqueue OTBR task actions
    mesh-diagnostics    Fetch mesh-diagnostic TLVs (children, childIpv6,
                        routerNeighbors)
    topology            Full topology sweep: devices fetch + diagnostics
                        fetch-all + mesh-diagnostics fetch-all

options:
  -h, --help            show this help message and exit
  --host HOST           OTBR REST API host (forwarded to otbr_restapi_cli)
  --port PORT           OTBR REST API port (forwarded to otbr_restapi_cli)
  --base-url URL        Override host/port with a full base URL (forwarded)
  --timeout SECS        HTTP request timeout in seconds (forwarded)
  --accept MIME         Default Accept header (forwarded)
  --raw                 Return raw API envelopes instead of flattened output
                        (forwarded)
  --poll-interval FLOAT
                        Seconds between action status polls (forwarded)
  --poll-timeout FLOAT  Max seconds to wait for an action to complete
                        (forwarded)
  --no-progress         Suppress per-device progress output (forwarded)
  --no-auto-output      Disable automatic output file naming (forwarded)
  --lab                 Allow experimental otbr-restapi mutating commands
                        (node state set, node dataset active set, actions
                        enqueue add-thread-device, actions enqueue reset-
                        network-diag-counter)
```

### `otbr-restapi node`

```
usage: python3 -m td_cli node [-h] {get,state,dataset} ...

positional arguments:
  {get,state,dataset}
    get                Get the OTBR node record from /api/node
    state              Get or set Thread state
    dataset            Operate on node datasets

options:
  -h, --help           show this help message and exit
```

### `otbr-restapi devices`

```
usage: python3 -m td_cli devices [-h] {list,get,fetch} ...

positional arguments:
  {list,get,fetch}
    list            List devices
    get             Get a device by device ID
    fetch           Trigger updateDeviceCollectionTask, wait for it, and
                    return the populated device list

options:
  -h, --help        show this help message and exit
```

### `otbr-restapi diagnostics`

```
usage: python3 -m td_cli diagnostics [-h] {list,get,fetch,fetch-all} ...

positional arguments:
  {list,get,fetch,fetch-all}
    list                List diagnostics
    get                 Get a diagnostic by diagnostics ID
    fetch               Enqueue getNetworkDiagnosticTask for a device, wait
                        for completion, and return the diagnostic result
    fetch-all           Fetch diagnostics for all known devices (or a given
                        list), one device at a time

options:
  -h, --help            show this help message and exit
```

### `otbr-restapi actions`

```
usage: python3 -m td_cli actions [-h] {list,get,enqueue} ...

positional arguments:
  {list,get,enqueue}
    list              List actions
    get               Get an action by action ID
    enqueue           Enqueue a new OTBR task

options:
  -h, --help          show this help message and exit
```

### `otbr-restapi mesh-diagnostics`

```
usage: python3 -m td_cli mesh-diagnostics [-h]
                                          {children,child-ipv6,router-neighbors,fetch,fetch-all} ...

positional arguments:
  {children,child-ipv6,router-neighbors,fetch,fetch-all}
    children            Fetch the child table for a device via otMeshDiag (TLV
                        29). Higher latency than standard diagnostic TLVs.
    child-ipv6          Fetch child IPv6 addresses for a device via otMeshDiag
                        (TLV 30). Higher latency than standard diagnostic
                        TLVs.
    router-neighbors    Fetch router neighbor table for a device via
                        otMeshDiag (TLV 31). Higher latency than standard
                        diagnostic TLVs.
    fetch               Fetch a caller-specified subset of mesh-diagnostic
                        TLVs for a single device. Allowed types: children,
                        childIpv6Addresses, routerNeighbors.
    fetch-all           Fetch mesh diagnostics for all known devices (or a
                        given list), one device at a time.

options:
  -h, --help            show this help message and exit
```

### `otbr-restapi topology`

```
usage: python3 -m td_cli topology [-h]
                                  [--preset {recommended,full,minimal,basic}]
                                  [--skip-devices] [--skip-diagnostics]
                                  [--skip-mesh-diagnostics]
                                  [--no-update-devices]
                                  [--no-enrich-mac-counters] [--no-fallback]
                                  [--fallback-preset {medium,minimal,basic}]

options:
  -h, --help            show this help message and exit
  --preset {recommended,full,minimal,basic}
                        TLV preset for the diagnostics step (default:
                        recommended)
  --skip-devices        Skip Step 1 (device refresh via
                        updateDeviceCollectionTask)
  --skip-diagnostics    Skip Step 2 (network diagnostics fetch-all)
  --skip-mesh-diagnostics
                        Skip Step 3 (mesh diagnostics fetch-all)
  --no-update-devices   Skip updateDeviceCollectionTask before
                        diagnostics/mesh steps
  --no-enrich-mac-counters
                        Disable MAC counter enrichment on the diagnostics
                        result
  --no-fallback         Disable per-device TLV fallback retry on failure
  --fallback-preset {medium,minimal,basic}
                        TLV preset to retry with on per-device failure
                        (default: minimal)
```

### `process-eve`

```
usage: td_cli process-eve [-h]
```

### `merge-dataset`

```
usage: td_cli merge-dataset [-h]
```

### `merge-extaddr`

```
usage: td_cli merge-extaddr [-h] [--merge-mdns-br | --merge-topology-all]
                             [--read-extaddr EXTADDR | --update-extaddr EXTADDR]
                             [--device-label DEVICE_LABEL]
                             [--merge-input-file MERGE_INPUT_FILE]
                             [--merge_name_override] [--datadir DATADIR]

options:
  -h, --help            show this help message and exit
  --merge-mdns-br       Use td-mdns-scopes-br.json instead of the default
                        merge input file
  --merge-topology-all  Use td-merged-topology-all.json instead of the
                        default merge input file
  --read-extaddr EXTADDR
                        Read one deviceLabel by 16-digit extAddress as JSON
  --update-extaddr EXTADDR
                        Update or insert one deviceLabel by 16-digit
                        extAddress
  --device-label DEVICE_LABEL
                        Device label for --update-extaddr
  --merge-input-file MERGE_INPUT_FILE
                        Merge input file name (default:
                        td-otbr-cli-networkdiag-fetch-all.json)
  --merge_name_override
                        If set, replace static Unknown device_label values
                        with merge input name for matching extaddr entries
  --datadir DATADIR     Data directory for JSON reads/writes (takes precedence
                        over TD_DATA_DIR)
```
