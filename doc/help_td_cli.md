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
| `--datadir DIR` | Data directory for JSON reads/writes when `TD_DATA_DIR` is not set. If omitted and `TD_DATA_DIR` is unset: use `/data` when present; otherwise create/use `./data` under the current run directory. |

---

## Command Summary

| Command | Description |
|---|---|
| `otbr-cli` | Scan OTBR CLI commands |
| `otbr-restapi` | Query OTBR REST API commands |
| `mdns` | Scan Thread-related mDNS scopes |
| `process-eve` | Parse and enhance an Eve Thread layout file |
| `merge-dataset` | Merge Thread (otbr-cli, otbr-restapi, eve, mdns) sources into one cache file |
| `merge-extaddr` | Merge missing extaddr entries from a topology or mdns input file into the static extaddr map |

---

## Commands Usage

### `otbr-cli`

```text
td_cli otbr-cli {thread-network-info,router-table,meshdiag,networkdiag,all} ...
```

### `otbr-restapi`

```text
td_cli otbr-restapi [global-forwarded-options] {download,node,devices,diagnostics,actions,mesh-diagnostics,topology} ...
```

### `mdns`

```text
td_cli mdns [--browse-timeout SECONDS] [--haptcp] [--mattertcpsupported] [SCOPE]
```

### `process-eve`

```text
td_cli process-eve ...
```

### `merge-dataset`

```text
td_cli merge-dataset ...
```

### `merge-extaddr`

```text
td_cli merge-extaddr ...
```

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

1. `TD_DATA_DIR` environment variable
2. `--datadir` CLI argument
3. Defaults (`/data` when present, otherwise `./data` under the current run directory)

---

## Subcommand Help Snapshots

### `otbr-cli`

```
usage: td_cli otbr-cli [-h]
                       {thread-network-info,router-table,meshdiag,networkdiag,all}
                       ...

positional arguments:
  {thread-network-info,router-table,meshdiag,networkdiag,all}
    thread-network-info        Scan and save thread network info
    router-table                Scan and save router table
    meshdiag                    Mesh diagnostic scans
    networkdiag                 Network diagnostic scans
    all                         Run all otbr-cli scans
```

### `otbr-cli meshdiag`

```
usage: td_cli otbr-cli meshdiag [-h]
                                {topology,routerneighbortable,childtable,childip6,all}
                                ...

positional arguments:
  {topology,routerneighbortable,childtable,childip6,all}
    topology            Scan meshdiag topology
    routerneighbortable
                        Scan meshdiag router-neighbour table
    childtable          Scan meshdiag child table
    childip6            Scan meshdiag child IPv6 addresses
    all                 Run all meshdiag scans
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
                           [--no-progress] [--no-auto-output]
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
                             [--merge-input-file MERGE_INPUT_FILE]
                             [--merge_name_override]

options:
  -h, --help            show this help message and exit
  --merge-mdns-br       Use td-mdns-scopes-br.json instead of the default
                        merge input file
  --merge-topology-all  Use td-merged-topology-all.json instead of the
                        default merge input file
  --merge-input-file MERGE_INPUT_FILE
                        Merge input file name (default:
                        td-otbr-cli-networkdiag-fetch-all.json)
  --merge_name_override
                        If set, replace static Unknown device_label values
                        with merge input name for matching extaddr entries
```
