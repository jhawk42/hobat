# Thread Mesh Network Dashboard

Thread Mesh Network Dashboard (tdash) is a Python toolkit for fetching thread device info and a browser dashboard for visualizing and monitoring [Thread](https://github.com/openthread/openthread) mesh networks. It collects thread device info from source like: OTBR CLI, OTBR REST API, mDNS, and Eve exports, then merges these datasets for dashboard visualization.

## Dataset Sources
- otbr-cli: Scans an OpenThread Border Router (OTBR) instance via ot-ctl commands [router table, meshdiag, networkdiag (detailed info, takes time) ] for thread device info. By default calls OTBR docker container. Also support calling otbr on the host.
- otbr-restapi: Downloads from OpenThread Border Router REST API for thread device info.
- mdns: Scans thread-related mdns scopes: _meshcop, _trel, _hap, _matter for thread device info.
- eve json file: The Eve app (iOS) supports querying a thread network for devices and sharing device info to a JSON file. Note: Eve app needs at least one Eve thread device like a smart outlet to collect info as the eve device has diagnostics code in device firmware to collect thread device info. Eve app works well with Apple Home (HAP) thread networks.

## Getting Started

### Setup - docker container

The tdash docker container hosts the td_cli and web server.

```
docker pull ghcr.io/jhawk42/tdash:latest
```

Note: Needs access to the docker socket to enable calls between docker containers via docker exec for tdash container to call into otbr container to execute ot-ctl commands.

```
docker run --name=tdash -d \
  --network=host \
  --volume $PWD/data:/data \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --restart=unless-stopped \
  tdash:latest 
```

### tdash cli
The top-level td_cli entry point:

```
docker exec -it tdash /bin/bash $*
```

Help:

```bash
python3 -m td_cli --help
```

Common commands:

```bash
# OTBR CLI
python3 -m td_cli otbr-cli router-table
python3 -m td_cli otbr-cli meshdiag topology
python3 -m td_cli otbr-cli networkdiag topology
python3 -m td_cli otbr-cli all

# OTBR REST API
python3 -m td_cli otbr-restapi download

# mDNS
python3 -m td_cli mdns thread

# Eve processing
python3 -m td_cli process-eve --input "data/Eve Thread Network Layout.evethreadlayout"

# Dataset merge
python3 -m td_cli merge-dataset

# Dashboard server
python3 -m td_cli web-server --host localhost --port 8087
```

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


## Data Directory Usage Examples

```bash
# Highest priority: environment variable
TD_DATA_DIR=/tmp/td-data python3 -m td_cli otbr-restapi download

# CLI argument when TD_DATA_DIR is not set
python3 -m td_cli --datadir ./my-data mdns thread

# web-server JSON reads from the effective data directory
python3 -m td_cli --datadir ./my-data web-server
```

## Data Directory Note

Current behavior uses `td_data_directory` consistently across command families, including web-server JSON responses. This makes docker and non-docker executions deterministic while preserving static dashboard asset serving.