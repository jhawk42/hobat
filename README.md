# Thread Mesh Network Dashboard

Thread Mesh Network Dashboard (tdash) is a Python toolkit and browser dashboard for visualizing and monitoring [Thread](https://github.com/openthread/openthread) mesh networks. It collects topology data from OTBR CLI, OTBR REST API, mDNS, and Eve exports, then merges these datasets for dashboard visualization.

## Dataset Sources
- otbr-cli: OpenThread CLI scans (router table, meshdiag, networkdiag)
- otbr-restapi: OpenThread Border Router REST API snapshots
- mdns: Thread-related mDNS browsing and capture
- Eve export: Eve Thread layout enhancement and conversion

## Data Directory Model

All JSON file reads/writes use one effective data directory (`td_data_directory`) resolved in this order:

1. `TD_DATA_DIR` environment variable
2. `--datadir DIR` command line argument
3. Defaults
   - If `/data` exists, use `/data`
   - Otherwise create and use `./data` under the current run directory

Important behavior:
- `TD_DATA_DIR` takes precedence over `--datadir`.
- User-supplied `TD_DATA_DIR`/`--datadir` paths are resolved to absolute paths.
- Local default `./data` is auto-created when selected.

## Getting Started

Use the top-level CLI entry point:

```bash
PYTHONPATH=src python3 -m td_cli --help
```

Common command families:

```bash
# OTBR CLI scans
PYTHONPATH=src python3 -m td_cli otbr-cli router-table
PYTHONPATH=src python3 -m td_cli otbr-cli meshdiag topology
PYTHONPATH=src python3 -m td_cli otbr-cli networkdiag topology
PYTHONPATH=src python3 -m td_cli otbr-cli all

# OTBR REST API downloads
PYTHONPATH=src python3 -m td_cli otbr-restapi download

# mDNS capture
PYTHONPATH=src python3 -m td_cli mdns thread

# Eve processing
PYTHONPATH=src python3 -m td_cli process-eve --input "data/Eve Thread Network Layout.evethreadlayout"

# Dataset merge
PYTHONPATH=src python3 -m td_cli merge-dataset

# Dashboard server
PYTHONPATH=src python3 -m td_cli web-server --host localhost --port 8087
```

## Data Directory Usage Examples

```bash
# Highest priority: environment variable
TD_DATA_DIR=/tmp/td-data PYTHONPATH=src python3 -m td_cli otbr-restapi download

# CLI argument when TD_DATA_DIR is not set
PYTHONPATH=src python3 -m td_cli --datadir ./my-data mdns thread

# web-server JSON reads from the effective data directory
PYTHONPATH=src python3 -m td_cli --datadir ./my-data web-server
```

## Migration Note

Previous behavior relied on process current working directory for many JSON paths.

Current behavior uses `td_data_directory` consistently across command families, including web-server JSON responses. This makes docker and non-docker executions deterministic while preserving static dashboard asset serving.