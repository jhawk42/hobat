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
| `--datadir DIR` | Data directory for JSON reads/writes (`TD_DATA_DIR` → `--datadir` → `/data` or `./data`) |

---

## Command Summary

| Command | Description |
|---|---|
| `otbr-cli` | Scan OTBR CLI commands |
| `mdns` | Scan Thread-related mDNS scopes |
| `otbr-restapi` | Query OTBR REST API commands |
| `process-eve` | Parse and enhance an Eve Thread layout file |
| `merge-dataset` | Merge Thread sources into one cache file |

---

## Commands Usage

### `otbr-cli`

```text
td_cli otbr-cli {thread-network-info,router-table,meshdiag,networkdiag,all} ...
```

### `mdns`

```text
td_cli mdns [--browse-timeout SECONDS] [--haptcp] [--mattertcpsupported] [SCOPE]
```

### `otbr-restapi`

```text
td_cli otbr-restapi [global-forwarded-options] {download,node,devices,diagnostics,actions,mesh-diagnostics,topology} ...
```

### `process-eve`

```text
td_cli process-eve ...
```

### `merge-dataset`

```text
td_cli merge-dataset ...
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
                        Seconds of idle time before auto-exit (default: 10, or
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

### `process-eve`

```
usage: td_cli process-eve [-h]
```

### `merge-dataset`

```
usage: td_cli merge-dataset [-h]
```
