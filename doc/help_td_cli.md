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
