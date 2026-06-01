# TDash Codebase Overview

## Key Technologies

| Technology | Role |
|---|---|
| Python 3 | All data-collection, parsing, merging, and server logic |
| [OpenThread Border Router (OTBR)](https://openthread.io/guides/border-router) REST API | Primary live data source for devices, diagnostics, and actions |
| `ot-ctl` CLI (via Docker) | Secondary data source for router table, mesh topology, and network dataset |
| [JSON:API](https://jsonapi.org/) | Response format used by the OTBR REST API |
| [Zeroconf / mDNS](https://pypi.org/project/zeroconf/) | Thread service discovery on the local network |
| [Eve App](https://www.evehome.com/) | Optional third-party topology JSON export |
| [vis-network.js](https://visjs.github.io/vis-network/docs/network/) | Interactive topology graph in the browser dashboard |
| [sortable.js](https://github.com/tofsjonas/sortable) | Sortable table columns in the browser dashboard |
| [`aiohttp`](https://docs.aiohttp.org/) | Async HTTP server powering the REST API and static file serving (`td_webserver.py`) |
| Standard library (`subprocess`, `asyncio`, `argparse`, …) | Core Python runtime; `aiohttp` and `zeroconf` are the only third-party dependencies |

---

## Repository Layout

```
tdash/
├── doc/                        # Documentation
│   ├── codebase_overview.md    # This file
│   ├── help_td_cli.md          # td_cli --help snapshot
│   ├── help_td_webserver.md    # td_webserver --help snapshot
│   └── merge_strategy.md       # Merge strategy reference
├── src/                        # All source code
│   ├── td_cli.py               # Unified CLI dispatcher (top-level entry point)
│   ├── td_webserver.py         # HTTP web server module
│   ├── tdash.html              # Combined single-page browser dashboard
│   ├── tdash.css               # Dashboard stylesheet
│   ├── js/                     # Dashboard JavaScript modules
│   │   ├── tdash-adaptors.js       # Topology adaptors (meshdiag/REST/Eve → vis-network)
│   │   ├── tdash-constants.js      # Merge strategies, link filters, edge category labels, vis options
│   │   ├── tdash-dataset-registry.js # Dataset registry (files, modes, filters)
│   │   ├── tdash-dataset.js        # Dataset loading and node label enrichment
│   │   ├── tdash-filters.js        # Node and edge visibility filters
│   │   ├── tdash-merge.js          # Client-side row merge by identity
│   │   ├── tdash-table-renderer.js # Sortable table renderer
│   │   ├── tdash-topology-renderer.js # vis-network topology renderer
│   │   ├── tdash-topology-utils.js # Node/edge helper utilities
│   │   ├── tdash-ui.js             # UI event wiring and render dispatch
│   │   └── tdash-utils.js          # Canonical identity and type helpers
│   ├── otbr_restapi_*.py       # OTBR REST API collectors and CLI handlers
│   ├── otbr_cli_*.py           # ot-ctl CLI collectors and parsers
│   ├── mdns_*.py               # mDNS discovery collectors and scope helpers
│   ├── eve_process.py          # Eve topology parser
│   ├── merge_dataset.py        # Dataset merge engine
│   ├── merge_extaddr_device_label_map.py  # Admin utility: merge extaddr entries into static label map
│   ├── extaddr_device_label_map.py  # Static extaddr→label loader
│   ├── td_const.py             # Shared constants (data-dir defaults, env var names, filenames)
│   ├── util_data.py            # Data-directory resolution utilities
│   ├── util_*.py               # Other shared utility modules
│   ├── profile_wrapper_td_cli.py      # cProfile wrapper for td_cli.py
│   └── profile_wrapper_td_webserver.py # cProfile wrapper for td_webserver.py
├── tests/                      # Test suite and local mock server
│   ├── test_*.py               # Unit tests
│   └── td_mock_otbr_restapi_server.py
├── .devcontainer/              # VS Code / Codespaces dev-container config
├── README.md
└── LICENSE
```

Collector and utility files use source-first prefixes (`otbr_restapi_`, `otbr_cli_`, `mdns_`, `eve_`, `util_`). The REST API, ot-ctl, and mDNS families are split across handler and helper modules rather than a single large file.
Test files use `test_*.py` names that follow the module under test.

---

## CLI vs REST API Naming

This codebase uses a strict naming split so the data source is visible from the filename.

| Prefix | Data source | Example |
|---|---|---|
| `otbr_cli_` | OTBR `ot-ctl` CLI wrappers and parsers (via Docker exec) | `otbr_cli_router_table.py` |
| `otbr_restapi_` | OTBR HTTP REST API clients, handlers, and download helpers | `otbr_restapi_util.py` |
| `mdns_` | Zeroconf/mDNS discovery collectors and scope helpers | `mdns_thread_scopes.py` |
| `eve_` | Eve topology parsing helpers | `eve_process.py` |
| `util_` | Shared helpers used across collectors/parsers | `util_network.py` |

---

## Architecture: Layers and Data Flow

### How the Code Is Layered

The Python codebase has six distinct layers, each with a single responsibility.  Dependencies flow strictly downward — upper layers call lower layers, never the reverse.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 6 — Browser Dashboard (JS, not Python)                           │
│  tdash.html + js/*.js + tdash.css                                       │
│  Fetch → merge → adapt → render (topology graph / sortable table)       │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ HTTP (fetch API)
┌──────────────────────────────────▼──────────────────────────────────────┐
│  Layer 5 — HTTP Server  (td_webserver.py)                               │
│  aiohttp + aiohttp_cors; routes: /, /api/data/{f}, /api/job/{id}, /**   │
│  • FILE_ACTION_MAP: filename → FileAction (max_age_s, action, cost)     │
│  • Cache gating: freshness check → serve 200/304 or regenerate          │
│  • Short-cost (≤300 s): sync subprocess → 200                           │
│  • Long-cost (>300 s) or force_async: background Task → 202 + polling   │
│  • ETag / If-None-Match / If-Modified-Since conditional GET support     │
│  • Per-source asyncio.Lock serialises concurrent subprocess calls       │
│  • _job_registry TTL cleanup (evict after 15 min)                       │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ subprocess (sys.executable td_cli.py)
┌──────────────────────────────────▼──────────────────────────────────────┐
│  Layer 4 — CLI Dispatcher  (td_cli.py)                                  │
│  argparse tree: otbr-cli / mdns / otbr-restapi / process-eve /          │
│  merge-dataset / merge-extaddr → forwards --datadir to every subcommand │
└──┬───────────────┬───────────────┬───────────────┬──────────────────────┘
   │               │               │               │
┌──▼──────────┐ ┌──▼──────────┐ ┌──▼──────────┐ ┌──▼──────────────────────┐
│ Layer 3a    │ │ Layer 3b    │ │ Layer 3c    │ │ Layer 3d                │
│ ot-ctl CLI  │ │ REST API    │ │ mDNS / Eve  │ │ Data Processing         │
│ Collectors  │ │ Collectors  │ │ Collectors  │ │ (Merge / Parse)         │
│             │ │             │ │             │ │                         │
│ otbr_cli_*.py│ │ otbr_restapi_*.py │ │ mdns_*.py │ │ merge_dataset.py     │
│ router_table │ │ cli + download   │ │ scopes +  │ │ merge_extaddr_device_│
│ meshdiag_*   │ │ + handlers        │ │ helpers   │ │ label_map.py         │
│ networkdiag_* │ │                   │ │ eve_process.py│ │ extaddr_device_   │
│ parsers/util │ │                   │ │           │ │ label_map.py         │
└──┬──────────┘ └──┬──────────┘ └─────────────┘ └─────────────────────────┘
   │               │
┌──▼───────────────▼──────────────────────────────────────────────────────┐
│  Layer 2 — Shared Utilities                                             │
│  td_const.py      — project-wide constants                              │
│  util_data.py     — data-dir resolution, atomic JSON writes             │
│  util_ot_ctl.py   — docker exec / local ot-ctl subprocess wrapper       │
│  util_network.py  — IPv6 / RLOC16 / prefix helpers                     │
│  util_convert.py  — base64 ↔ hex for extended addresses                │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ reads / writes
┌──────────────────────────────────▼──────────────────────────────────────┐
│  Layer 1 — Data Directory  (data/ on disk)                              │
│  JSON snapshot files written by collectors; read by the server/browser  │
└─────────────────────────────────────────────────────────────────────────┘
```

| Layer | Python files | Responsibility |
|---|---|---|
| **1 — Data Directory** | `data/` (files on disk) | JSON snapshots: written by collectors, read by server and browser |
| **2 — Shared Utilities** | `td_const.py`, `util_data.py`, `util_ot_ctl.py`, `util_network.py`, `util_convert.py` | Constants, data-dir resolution, subprocess wrapper, network math |
| **3a — ot-ctl Collectors** | `otbr_cli_*.py` | Run `ot-ctl` inside the OTBR Docker container; parse output; write JSON |
| **3b — REST API Collectors** | `otbr_restapi_*.py` | HTTP calls to OTBR REST API; dispatch into `node`, `devices`, `diagnostics`, `actions`, `mesh-diagnostics`, and `topology` handlers; write JSON |
| **3c — mDNS / Eve Collectors** | `mdns_*.py`, `eve_process.py` | Zeroconf browse and Eve App export parsing; write JSON |
| **3d — Data Processing** | `merge_dataset.py`, `merge_extaddr_device_label_map.py`, `extaddr_device_label_map.py` | Normalise identifiers, merge multi-source records, manage label map |
| **4 — CLI Dispatcher** | `td_cli.py` | `argparse` tree; forward `--datadir`; call Layer 3 `main()` functions |
| **5 — HTTP Server** | `td_webserver.py` | aiohttp server; cache gating; subprocess dispatch of Layer 4 |
| **6 — Browser Dashboard** | `tdash.html`, `js/*.js`, `tdash.css` | Fetch JSON via Layer 5; merge, adapt, and render in-browser |

### How Data Flows Through the Layers

#### Offline CLI path (direct use)

```
User / shell script
    │  python3 -m td_cli otbr-cli meshdiag topology --datadir ./data
    ▼
Layer 4 — td_cli.py (argparse dispatch)
    │  calls otbr_cli_meshdiag_topology.main(["--datadir", "./data"])
    ▼
Layer 3a — otbr_cli_meshdiag_topology.py
    │  calls util_ot_ctl.exec_ot_ctl("meshdiag topology ip6-addrs children")
    ▼
Layer 2 — util_ot_ctl.py
    │  docker exec otbr sh -c "ot-ctl meshdiag topology ip6-addrs children"
    ▼
OTBR Docker container  →  raw text output
    │  returned to Layer 3a parser
    ▼
Layer 3a — parse text → list of dicts → save_json_atomic()
    ▼
Layer 1 — data/td-otbr-cli-meshdiag-topology.json  (written atomically)
```

#### Server-driven path (browser Fetch button)

```
Browser  →  GET /api/data/td-otbr-cli-meshdiag-topology.json
    ▼
Layer 5 — td_webserver.py handle_data_api()
    │  _resolve_and_validate() → FILE_ACTION_MAP lookup
    │  _should_regenerate()    → mtime vs max_age_s
    │  if stale / absent:
    │    short-cost  → _dispatch_short_cost()  → await asyncio subprocess
    │    long-cost   → _dispatch_long_cost()   → 202 + background Task
    │  ETag / If-None-Match check → 304 if unchanged
    ▼
Layer 4 — td_cli.py (subprocess)
    │  dispatches to Layer 3 as in the offline path above
    ▼
Layer 1 — data/*.json  (file written; server reads it back)
    ▼
Layer 5 — _build_file_response()  →  200 JSON + Cache-Control + ETag
    ▼
Browser  →  tdash-dataset.js loadDataset()
    │  mergeRowsByIdentity() / mergeRowsByRloc16()  (tdash-merge.js)
    │  runAdaptor()  →  { nodeData, edgeData }      (tdash-adaptors.js)
    │  new vis.Network() / renderTable()             (topology/table renderer)
    ▼
Interactive topology graph or sortable table in the browser
```

#### Merge / label-enrichment path (offline admin)

```
python merge_dataset.py --datadir ./data
    │  loads multiple JSON files from Layer 1
    │  normalize_identifiers() → canonical rloc16 / extaddr / omr_ipv6_addr
    │  derive_mode_device()    → infer FTD/MTD from various field shapes
    │  build_merged_records()  → first-value-wins, conflict log
    ▼
Layer 1 — data/td-merged-topology-all.json

python3 -m td_cli merge-extaddr --merge-input-file td-mdns-scopes-thread.json
    │  reads topology file + td-static-extaddr-device-label.json
    │  adds missing extaddr entries (prefers device_label, falls back to name)
    ▼
Layer 1 — data/td-static-extaddr-device-label.json  (updated atomically)
```

### Key Design Decisions

| Decision | Where enforced | Why |
|---|---|---|
| `td_` prefix on project-level files | `td_const.py`, `td_cli.py`, `td_webserver.py` | Distinguishes project entry-points from collector/utility modules |
| Atomic JSON writes (`save_json_atomic`) | `util_data.py` | Prevents partial files being read by the server when a collector is interrupted |
| Per-source `asyncio.Lock` in the server | `td_webserver.py` `_source_locks` | Prevents two `otbr-cli` (or `mdns`) subprocesses from hitting the hardware simultaneously |
| `force_async=True` for 30–300 s actions | `FILE_ACTION_MAP` entries | Avoids blocking an aiohttp worker for browser-unsafe durations without hitting the long-cost threshold |
| ETag + conditional GET | `td_webserver.py` `_build_file_response` | Allows browsers to revalidate cheaply without re-downloading unchanged JSON |
| `TD_OTBR_CONTAINER_USE=0` | `util_ot_ctl.py` | Allows running `ot-ctl` locally without Docker (development / bare-metal OTBR) |
| `_cleanup_job_registry_loop` | `td_webserver.py` | Prevents unbounded growth of `_job_registry` in long-lived server processes |

---

## Source File Catalogue

### Data Collection — OTBR REST API

| File | Purpose |
|---|---|
| `otbr_restapi_download.py` | Fixed-target downloader: fetches the active dataset, devices, and diagnostics snapshots and writes them to local JSON files.  Uses shared download helpers for static endpoint writes and per-device diagnostics updates. |
| `otbr_restapi_download_helpers.py` | Shared helper functions for downloading static endpoints and saving device diagnostics. |
| `otbr_restapi_util.py` | Full-featured REST API client (`OTBRRestApiClient`).  Returns **flattened** Python objects by default (JSON:API `id`/`type`/`attributes` merged into a single dict). Also contains the shared exception hierarchy (`OTBRHTTPError`, `OTBRConnectionError`, etc.). |
| `otbr_restapi_cli.py` | CLI front-end for the flattened client.  Dispatches to handler modules for `node`, `devices`, `diagnostics`, `actions`, `mesh-diagnostics`, and `topology` commands. |
| `otbr_restapi_node.py` | REST CLI handlers for node, state, and dataset commands. |
| `otbr_restapi_devices.py` | REST CLI handlers for device list/get/fetch commands. |
| `otbr_restapi_diagnostics.py` | REST CLI handlers for diagnostics list/get/fetch commands and TLV presets. |
| `otbr_restapi_actions.py` | REST CLI handlers for action list/get/enqueue commands. |
| `otbr_restapi_mesh_diagnostics.py` | REST CLI helpers and handlers for child tables, child IPv6 addresses, router neighbours, and mesh-diagnostic batch fetches. |
| `otbr_restapi_topology.py` | Combined topology sweep for devices, diagnostics, and mesh diagnostics. |


### Data Collection — ot-ctl CLI (via Docker)

| File | ot-ctl Command | Output File | Purpose |
|---|---|---|---|
| `otbr_cli_router_table.py` | `router table` | `td-otbr-cli-router-table.json` | Parses the pipe-delimited router table into a list of router dicts with fields: ID, RLOC16, Next Hop, Path Cost, LQ In/Out, Age, Extended MAC, and Link. Adds `extaddr` and `device_label` from the static label map. |
| `otbr_cli_meshdiag_topology.py` | `meshdiag topology ip6-addrs children` | `td-otbr-cli-meshdiag-topology.json` | Parses per-router blocks containing: RLOC16, extaddr, Thread version, BR flag, link-quality buckets (1/2/3-links with peer IDs), IPv6 address list, and children (RLOC16 + link quality + mode).  Also computes `total_children`, `total_links`, and `omr_ipv6_addr`. |
| `otbr_cli_meshdiag_childtable.py` | `meshdiag childtable <rloc16>` (once per router) | `td-otbr-cli-meshdiag-router-childtables.json` | For every router in the router table, collects per-child details: RLOC16, extaddr, Thread version, timeout, age, supervision interval, queued messages, rx-on flag, device type, full-net flag, RSS (avg/last/margin), frame/message error rates, connection time, and CSL parameters.  Handles `ResponseTimeout` gracefully. |
| `otbr_cli_meshdiag_childip6.py` | `meshdiag childip6 <rloc16>` (once per router) | `td-otbr-cli-meshdiag-router-childip6.json` | For every router in the router table, collects child IPv6 address lists grouped by child RLOC16 and records per-child IP address counts.  Handles `ResponseTimeout` gracefully. |
| `otbr_cli_meshdiag_routerneighbortable.py` | `meshdiag routerneighbortable <rloc16>` (once per router) | `td-otbr-cli-meshdiag-router-neighbortables.json` | For every router in the router table, collects per-neighbour details: RLOC16, extaddr, Thread version, RSS (avg/last/margin), frame/message error rates, and connection time.  Handles `ResponseTimeout` gracefully. |
| `otbr_cli_networkdiag_parsers.py` | `networkdiag get` parser helpers | n/a | Parser helpers for networkdiag output sections, TLV decoding, and record normalization. |
| `otbr_cli_networkdiag_util.py` | `networkdiag get` utilities | n/a | Shared utilities for networkdiag collection, device classification, and record merging. |
| `otbr_cli_networkdiag_topology.py` | `networkdiag get <rloc-ipv6> <tlvs>` (unicast per router) or `networkdiag get ff03::1/ff02::1 <tlvs>` (multicast) | `td-otbr-cli-networkdiag-fetch-all.json` (unicast poll), `td-otbr-cli-networkdiag-multicast-network.json` (multicast all), `td-otbr-cli-networkdiag-multicast-neighbors.json` (multicast neighbors) | Collects network diagnostic data from Thread devices via three modes: (1) Unicast fetch-all: polls each router individually via rloc IPv6. (2) Multicast network: broadcasts to all mesh devices (ff03::1) with retry strategy and TLV merging. (3) Multicast neighbors: broadcasts to one-hop neighbors (ff02::1) with retry strategy and TLV merging. For every device, parses 16 TLVs including: Ext Address (0), RLOC16 (1), Mode (2), EUI64 (23), IPv6 addresses (8), Connectivity (4), Leader Data (6), Thread Version (24), Vendor Name (25), Vendor Model (26), Vendor SW Version (27), Vendor App URL (28), Route64 (5), Child Table (16), MAC Counters (9), MLE Counters (34), and time-in-role statistics. Mode TLV provides RxOnWhenIdle/DeviceType/NetworkData for FTD/MTD classification. MAC counters include error/discard totals and percentages. MLE counters track role changes, partition ID changes, parent changes, and attach attempts. |
| `otbr_cli_thread_network_info.py` | `dataset active`, `prefix meshlocal`, `br omrprefix favored` | `td-otbr-cli-thread-network-info.json` | Collects the active Thread dataset (channel, PAN ID, extended PAN ID, mesh-local prefix, network name, etc.) and derives the mesh-local IPv6 RLOC prefix and the OMR prefix for use by other collectors. |

### Data Collection — Other Sources

| File | Purpose |
|---|---|
| `mdns_thread_scopes.py` | Uses `zeroconf` to browse for Thread-related mDNS service types (e.g. `_meshcop._udp`).  Delegates scope-specific parsing and enrichment to `mdns_hap.py`, `mdns_matter.py`, `mdns_meshcop.py`, and `mdns_thread_util.py`. |
| `mdns_hap.py` | HAP-specific mDNS parsing and enrichment helpers. |
| `mdns_matter.py` | Matter-specific mDNS parsing and enrichment helpers. |
| `mdns_meshcop.py` | Thread meshcop mDNS parsing and enrichment helpers. |
| `mdns_thread_util.py` | Shared mDNS and Thread helper utilities. |

### Data Parsing

| File | Purpose |
|---|---|
| `eve_process.py` | Parses an Eve App `Eve Thread Network Layout.evethreadlayout` exported file.  Normalises decimal RLOC16 to hex, converts base64-encoded extended addresses to hex, enriches nodes with OMR IPv6 address and route-destination names, and keys the output by `rloc16_hex`. |
| `extaddr_device_label_map.py` | Loads a static `td-static-extaddr-device-label.json` file that maps extended addresses to human-readable device labels. |

### Data Merging

| File | Purpose |
|---|---|
| `merge_dataset.py` | Reads multiple JSON data files (OTBR CLI, REST API, Eve) and merges all records into a single output file.  Supports three merge strategies: `none` (pass-through), `by-rloc16`, and `by-identity` (matches on RLOC16, canonical `extaddr`, or `omr_ipv6_addr`).  Tracks source provenance in `_source_files` and records conflicts without overwriting existing values.  Also provides `normalize_identifiers()` (canonicalises RLOC16, extaddr aliases, and OMR address) and `derive_mode_device()` (infers FTD/MTD from multiple field shapes). |
| `merge_extaddr_device_label_map.py` | Admin utility that reads a topology JSON file (e.g. an mDNS or networkdiag output) and adds any previously unseen `extaddr` entries to `td-static-extaddr-device-label.json`.  Falls back from `device_label` to `name` for the label text.  Accepts `--merge_name_override` to overwrite existing `Unknown` labels with the topology name. |

### Utilities

| File | Purpose |
|---|---|
| `td_const.py` | Shared constants used across all modules: `TD_DATA_DIR_ENV_VAR`, `TD_DATA_DIR_ARG`, `TD_DATA_DIR_DOCKER_DEFAULT`, `TD_DATA_DIR_LOCAL_DEFAULT`, `TD_DATA_DIR_RESOLUTION_SUMMARY`, `TD_DATA_DIR_ARG_HELP`, and `EXTADDR_DEVICE_LABEL_MAP_FILENAME`.  The `td_` prefix aligns this project-level file with `td_cli.py` and `td_webserver.py`. |
| `util_data.py` | Data-directory resolution utilities.  Provides `TDDataDirSource` (enum), `TDDataDirResolution` (dataclass), `parse_datadir_from_argv()`, `resolve_data_dir()`, `resolve_data_dir_with_source()`, `ensure_data_dir_exists()`, `format_data_dir_log_message()`, `data_file_path()`, `resolve_data_file_path()`, and `save_json_atomic()`.  Implements the `TD_DATA_DIR` env → `--datadir` CLI → `/data` → `./data` precedence chain. |
| `util_ot_ctl.py` | Low-level wrapper that runs `ot-ctl <command>` inside a named Docker container via `docker exec`.  The container name defaults to `"otbr"` and can be overridden with `TD_OTBR_CONTAINER_NAME`.  Docker container use itself can be disabled via `TD_OTBR_CONTAINER_USE=0`, which falls back to running `ot-ctl` locally without `docker exec`.  The subprocess timeout defaults to 30 s and is overridable via `TD_OT_CTL_TIMEOUT`. |
| `util_network.py` | Network helpers: mesh-local and OMR prefix retrieval, IPv6 address prefix formatting, RLOC16 manipulation, OMR address matching in an address list, and full `get_network_dataset_info()` aggregator. |
| `util_convert.py` | Base64 ↔ hex conversion for 64-bit extended addresses (handles JSON-escaped slashes and optional byte-order reversal for 802.15.4 little-endianness). |

### Development / Profiling Wrappers

| File | Purpose |
|---|---|
| `profile_wrapper_td_cli.py` | Runs `td_cli.main()` under `cProfile`.  Dumps a `.prof` file (`profile_td_cli.prof`) and prints the top-20 cumulative hotspots to stderr.  Invoked like `td_cli.py` but with profiling active. |
| `profile_wrapper_td_webserver.py` | Runs `td_webserver.main()` under `cProfile`.  Dumps `profile_td_webserver.prof` and prints the top-20 hotspots.  Used for benchmarking server startup or request handling. |

### Web Dashboard and Server

| File | Purpose |
|---|---|
| `tdash.html` | Combined single-page dashboard — replaces the former separate topology and tables HTML files.  See [Dashboard Functions](#dashboard-functions) below. |
| `tdash.css` | Stylesheet for the browser dashboard.  Defines CSS variables for colours, typography, and layout of all dashboard components. |
| `td_webserver.py` | Async HTTP server built on `aiohttp`.  Binds to `$HOST`/`$PORT` (default `9165`).  Serves `src/` as a static file tree with explicit MIME-type overrides.  Exposes a REST API (`/api/data/{filename}`, `/api/job/{job_id}`) that checks file freshness, invokes `td_cli.py` subprocesses on demand, and streams results back with `Cache-Control` and CORS headers.  Actions with `action_cost_s > 300 s` or `force_async=True` return HTTP 202 immediately and complete as background asyncio tasks that clients poll via `/api/job/{job_id}`.  Accepts `--datadir`; run standalone as `python3 -m td_webserver`. |

### Dashboard JavaScript Modules (`js/`)

| File | Purpose |
|---|---|
| `tdash-adaptors.js` | Topology adaptors — converts raw data from each source (meshdiag, networkdiag, REST API, Eve native, Eve enhanced, router-table) into the unified `{nodes, edges}` format consumed by vis-network. |
| `tdash-constants.js` | Central registry of merge-strategy identifiers, link-filter mode names, edge-category label strings, link-quality edge styles (`EDGE_LQ_STYLES`), vis-network physics/layout options (`VIS_OPTIONS`), priority column ordering for the table renderer (`TABLE_PRIORITY_COLUMNS`), and dropdown option metadata used across modules. |
| `tdash-dataset-registry.js` | Defines `DATASET_REGISTRY`: each entry names the JSON file(s) to fetch, the merge strategy, the topology adaptor mode, and the default link filter for that dataset. |
| `tdash-dataset.js` | Dataset loading pipeline — fetches JSON file(s) from the server, applies the client-side merge, and enriches nodes with static device labels from the extaddr map. |
| `tdash-filters.js` | Visibility filters — implements edge filtering by link-filter mode and node filtering by device type (FTD/MTD/BR/Router) and diagnostics thresholds. |
| `tdash-merge.js` | Client-side row-merge engine — normalises identifiers and merges rows by `rloc16`, canonical `extaddr`, or `omr_ipv6_addr`, mirroring the Python `merge_dataset.py` logic. |
| `tdash-table-renderer.js` | Renders the current dataset as a sortable, column-filterable HTML table; discovers columns dynamically from loaded rows. |
| `tdash-topology-renderer.js` | Drives the vis-network graph: creates nodes and edges via the active adaptor, applies node/edge filters, handles click-to-details-panel, and wires physics/animation/zoom toggles. |
| `tdash-topology-utils.js` | Low-level helpers shared by adaptors and renderers: node-ID selection, label building, and directed-edge deduplication with per-category tracking. |
| `tdash-ui.js` | Top-level UI wiring — binds dropdown and button event handlers, delegates dataset loads, and dispatches render calls to the topology or table renderer. |
| `tdash-utils.js` | Primitive helpers for canonical-identity comparison (`rloc16`, `extaddr`, `omr_ipv6_addr`) and type guards used by the merge and filter modules. |

### Unified CLI Dispatcher

| File | Purpose |
|---|---|
| `td_cli.py` | Top-level CLI entry point.  Builds the flattened `argparse` tree and dispatches to the appropriate module `main()`.  Supported top-level commands: `otbr-cli`, `mdns`, `otbr-restapi`, `process-eve`, `merge-dataset`, `merge-extaddr`.  The web server is a separate module (`td_webserver.py`) and is **not** a `td_cli.py` subcommand.  Accepts a global `--datadir` option (overridden by `TD_DATA_DIR` env var) that is forwarded to every subcommand.  Unknown trailing arguments are forwarded via `parse_known_args` to subordinate modules. |

---

## Data Directory

All JSON data files (collected snapshots, merged output, static label map) are read from and written to a configurable **data directory**.

### Resolution precedence

| Priority | Source | Notes |
|---|---|---|
| 1 | `TD_DATA_DIR` environment variable | Highest priority; overrides all other settings |
| 2 | `--datadir` CLI argument | Passed globally to `td_cli.py` or directly to any module |
| 3 | `/data` (Docker default) | Used when the path exists (i.e. running inside the Docker container) |
| 4 | `./data` (local default) | Created under the current working directory if it does not exist |

### Implementation

- `td_const.py` defines the constant names (`TD_DATA_DIR_ENV_VAR`, `TD_DATA_DIR_ARG`, `TD_DATA_DIR_DOCKER_DEFAULT`, `TD_DATA_DIR_LOCAL_DEFAULT`).
- `util_data.py` implements `resolve_data_dir_with_source()` (returns a `TDDataDirResolution` dataclass with `path` and `source`) and the simpler `resolve_data_dir()` wrapper.  It also provides `data_file_path()` and `resolve_data_file_path()` for locating individual JSON files within the resolved directory.
- `td_webserver.py` exposes `/api/data/{filename}` which checks the resolved data directory for freshness and invokes `td_cli.py` subprocesses to regenerate stale files on demand.

---

## REST API and Caching Architecture

### Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/data/{filename}` | GET | Serve or generate a data file.  Checks `FILE_ACTION_MAP` for the filename, validates freshness, optionally invokes `td_cli.py`, and returns the file with `Cache-Control` and `Last-Modified` headers. |
| `/api/job/{job_id}` | GET | Poll the status of a long-running background job.  Returns `{ status: "running" }`, `{ status: "done", filename }`, or `{ status: "error", detail }`. |

### Server-side cache flow (`/api/data/{filename}`)

1. Reject any filename containing path-traversal characters (`/`, `\`, `..`, null bytes) → 404.
2. Look up `FILE_ACTION_MAP` by filename (case-insensitive) → 404 if unknown.
3. Parse `Cache-Control` request header (`no-cache` → force regeneration).
4. Resolve `data_dir / filename`.
5. If `action == "STATIC"`: serve the file as-is; 404 if missing.
6. Otherwise, check freshness (`is_file_fresh`).  If stale or missing:
   - **Short-cost** (`action_cost_s ≤ 300 s`): run `td_cli.py` synchronously; await exit code; 502 on failure.
   - **Long-cost** (`action_cost_s > 300 s`): spawn `td_cli.py` as a background asyncio task; return **HTTP 202** with `{ job_id, status, filename }` and `Location: /api/job/{job_id}`.
7. Return the file with `Cache-Control: max-age=<n>`, `Last-Modified`, and `Access-Control-Allow-Origin: *`.

### Client-side cache flow (`tdash-dataset.js`)

- On page load no data is fetched; the status bar reads *"Select a dataset and press Fetch."*
- Clicking **Fetch** calls `loadDataset()`, which requests each file via `/api/data/{filename}`.
- Before each request the per-file `fileMaxAgeCache` map is consulted; if a previous `max-age` was recorded the corresponding `Cache-Control: max-age=<n>` request header is sent, letting the server decide whether the cached file is still fresh.
- After each successful response the `Cache-Control: max-age=<n>` response header is stored back into `fileMaxAgeCache`.
- The **Force Refresh** checkbox (`#chk-force-fresh`) sets `_forceFresh = true`, causing all requests to carry `Cache-Control: no-cache` regardless of the local cache.
- If the server returns **HTTP 202** the client enters polling mode: `pollJobUntilDone()` pings `/api/job/{job_id}` every 5 s, updates the status bar with elapsed time, and fetches the completed file when `status == "done"`.

### `FILE_ACTION_MAP` — filename → action mapping

Defined in `td_webserver.py`.  Each entry is a `FileAction` dataclass:

| Field | Type | Meaning |
|---|---|---|
| `max_age_s` | `int` | Seconds before a cached file is considered stale |
| `action` | `"STATIC"` \| `list[str]` | `"STATIC"` = externally managed; list = CLI args forwarded to `td_cli.py` |
| `action_cost_s` | `int` | Estimated wall-clock seconds for the action; determines 200 vs 202 response |
| `force_async` | `bool` | When `True`, always dispatches via 202 + polling regardless of `action_cost_s` (used for actions whose worst-case duration exceeds the browser-safe synchronous limit but is under the 300 s threshold) |

### HTTP Cache Revalidation (ETag / Conditional GET)

`_build_file_response()` computes an ETag as `"{mtime_ns:x}-{size:x}"` and sets `Last-Modified`.  Browsers and API clients can send `If-None-Match` or `If-Modified-Since`; the server returns **304 Not Modified** (no body retransmitted) when the cached copy is still valid.  `If-None-Match` takes precedence over `If-Modified-Since` per RFC 9110.

Static assets (`tdash.html`, `js/*.js`, `tdash.css`) receive `Cache-Control: no-cache` from the `_set_static_cache_headers` middleware so browsers always revalidate via ETag before serving a cached file.

### CORS

CORS is configured via `aiohttp_cors` (an explicit third-party dependency).  The `/api/data/{filename}` and `/api/job/{job_id}` routes are wrapped to allow all origins (`*`) with any request headers and exposed response headers.  Static routes are same-origin by design and not CORS-wrapped.

### Job Registry TTL Cleanup

A background asyncio task (`_cleanup_job_registry_loop`) runs every 60 s and evicts completed or errored jobs older than 15 minutes (`_JOB_TTL_S = 900`) from `_job_registry`.  On server shutdown, the cleanup task and all in-flight background job tasks are cancelled and awaited via `app.on_shutdown`.

---

## Dashboard Functions

### Dataset Selection

A **Dataset** dropdown (populated from `DATASET_REGISTRY`) lets you choose which JSON file(s) to load. Each registry entry specifies:

- `files[]` — one or more local JSON filenames to fetch (via `fetch()`)
- `mergeStrategy` — how to combine multiple files (`none` / `by-rloc16` / `by-identity`)
- `topologyMode` — which topology adaptor to use when drawing the graph
- `defaultLinkFilter` — the link filter preselected when this dataset loads

The full set of pre-configured datasets is listed below, grouped by category:

**otbr-cli — single-file views**

| Dataset key | Label | Files | Topology mode |
|---|---|---|---|
| `meshdiag_only` | otbr-cli: meshdiag topology | `td-otbr-cli-meshdiag-topology.json` | `meshdiag-networkdiag` |
| `networkdiag_only` | otbr-cli: networkdiag topology | `td-otbr-cli-networkdiag-fetch-all.json` | `meshdiag-networkdiag` |
| `router_table` | otbr-cli: router table | `td-otbr-cli-router-table.json` | `router-table` |
| `router_neighbortables` | otbr-cli: meshdiag router neighbortables | `td-otbr-cli-meshdiag-router-neighbortables.json` | `merged-detailed` |
| `router_childtables` | otbr-cli: meshdiag router childtables | `td-otbr-cli-meshdiag-router-childtables.json` | `merged-detailed` |

**otbr-cli — multi-file merged views**

| Dataset key | Label | Files | Topology mode |
|---|---|---|---|
| `merged_otbr_cli_all` | otbr-cli: merged [meshdiag, networkdiag, neighbors, children] | meshdiag + networkdiag + neighbortables + childtables | `meshdiag-networkdiag` |
| `merged_otbr_cli_all_mdns` | lab: otbr-cli: mdns: merged [meshdiag, networkdiag, neighbors, children] | above + `td-mdns-scopes-thread.json` | `meshdiag-networkdiag` |
| `merged_all_deep_wide_otbr_cli_restapi_eve` | lab: premerged: all 1 file: [otbr-cli, otbr-restapi, eve] | `td-merged-topology-all.json` | `merged-detailed` |

**otbr-restapi — REST API views**

| Dataset key | Label | Files | Topology mode |
|---|---|---|---|
| `restapi_devices_diagnostics` | lab: otbr-restapi: [devices, diagnostics] | `td-otbr-restapi-devices.json` + `td-otbr-restapi-diagnostics.json` | `otbr_restapi` |
| `restapi_devices` | lab: otbr-restapi: devices | `td-otbr-restapi-devices.json` | `otbr_restapi` |
| `restapi_diagnostics` | lab: otbr-restapi: diagnostics | `td-otbr-restapi-diagnostics.json` | `otbr_restapi` |

**mDNS**

| Dataset key | Label | Files | Topology mode |
|---|---|---|---|
| `mdns_scopes_thread` | mdns: thread scopes | `td-mdns-scopes-thread.json` | `raw-array` |

**Eve App exports**

| Dataset key | Label | Files | Topology mode |
|---|---|---|---|
| `example_small_eve_native_threadlayout` | lab: eve native: example | `example-small-Eve Thread Network Layout` | `eve_native` |
| `eve_native_threadlayout` | lab: eve native: Eve Thread Network Layout | `Eve Thread Network Layout.evethreadlayout` | `eve_native` |
| `eve_enhanced_topology` | lab: eve enhanced: td-eve-topology.json | `td-eve-topology.json` | `eve_enhanced` |

**Multi-source merged views**

| Dataset key | Label | Sources | Topology mode |
|---|---|---|---|
| `merged_otbr_cli_otbr_restapi` | lab: merged: [otbr-cli, otbr-restapi] | meshdiag + networkdiag + neighbortables + childtables + REST API devices + diagnostics | `meshdiag-networkdiag` |
| `merged_otbr_cli_meshdiag_networkdiag_neighbortables_eve` | lab: merged: [otbr-cli, eve] | meshdiag + networkdiag + neighbortables + Eve enhanced | `meshdiag-networkdiag` |
| `merged_otbr_cli_meshdiag_networkdiag_neighbortables_restapi_eve` | lab: merged: [otbr-cli, otbr-restapi, eve] | meshdiag + networkdiag + neighbortables + childtables + REST API + Eve enhanced | `meshdiag-networkdiag` |

**System**

| Dataset key | Label | Files | Topology mode |
|---|---|---|---|
| `static_extaddr_device_label` | system: Extended MAC to Device Label Mapping | `td-static-extaddr-device-label.json` | `raw-array` |

### View Modes

| Button | What it shows / does |
|---|---|
| **Fetch** | Manually re-fetches the currently selected dataset from the server without changing the dataset selection. |
| **Topology** | Interactive [vis-network](https://visjs.github.io/vis-network/docs/network/) graph of the mesh.  Click any node to see all its properties in the side panel. |
| **Table** | Flat [sortable](https://github.com/tofsjonas/sortable) table of all rows in the loaded dataset.  Click any column header to sort. |
| **Physics** | Toggles the vis-network physics simulation on/off (spring-force layout vs. fixed positions).  Topology view only. |
| **Auto Zoom** | Toggles automatic fit-to-view when a dataset loads.  Topology view only. |
| **Legend** | Toggles the link-quality colour/style legend panel.  Starts active (legend visible).  Topology view only. |
| **Advanced** | Toggles expanded column display in Table view — shows all discovered columns rather than the priority subset.  Table view only. |
| **lab** | Placeholder lab/debug toggle (wired to the DOM but no handler yet). |

### Node Filter

Filters which nodes appear in both Topology and Table views:

| Option | Criteria |
|---|---|
| All Nodes | No filter |
| Full Thread Devices (FTD) | `mode.device == "FTD"` (topology: `mode_device`; table: `mode.device`) |
| Minimal Thread Devices (MTD) | `mode.device == "MTD"` (topology: `mode_device`; table: `mode.device`) |
| Main Routers | RLOC16 ends in `00` (topology: `isMainRouter` flag; table: RLOC16 suffix check) |
| Border Routers | `br == true` (topology: `isBorderRouter` flag) |
| Routers with Children | Router node with at least one child (topology: `isRouter && hasChildren`; table: `total_children > 0`) |
| Routers without Children | Router node with no children (topology: `isRouter && !hasChildren`; table: router-shaped with zero children) |

### Link Filter

Controls which edges are drawn in the Topology view (see [Topology Modes and Link Filters](#topology-modes-and-link-filters) for details).

### Diagnostics Filter

Filters rows in the Table view to highlight nodes with health issues:

| Category | Filters available |
|---|---|
| MAC errors | Total error packet % ≥ 5 % (medium) or ≥ 10 % (high) |
| MAC discards | Total discard packet % ≥ 15 % (high) |
| MLE partition changes | ≥ 2 (medium) or ≥ 5 (high) |
| MLE parent changes | ≥ 2 (medium) or ≥ 5 (high) |
| Router neighbour frame error rate | ≥ 2 % (low), ≥ 5 % (medium), ≥ 10 % (high) |
| Router neighbour message error rate | ≥ 2 % (low), ≥ 5 % (medium), ≥ 10 % (high) |
| Router neighbour RSS | Bad (< −80 dBm), Fair (−70 to −80), Good (−60 to −70), Excellent (> −60) |

### Node Details Panel

Clicking a node in Topology view populates a scrollable side panel listing every field from the underlying data row — useful for inspecting raw diagnostic counters, IPv6 addresses, mode flags, and link quality values without opening the Table view.

---

## Topology Modes and Link Filters

### Topology Modes

The `topologyMode` field in each dataset registry entry selects the JavaScript adaptor that transforms raw JSON rows into vis-network nodes and edges.

| Mode | Typical Input Files | What it draws |
|---|---|---|
| `meshdiag-networkdiag` | `td-otbr-cli-meshdiag-topology.json`, `td-otbr-cli-networkdiag-fetch-all.json` | Nodes for every router; edges derived from the link-quality buckets (1/2/3-links), children arrays, child tables, and router-neighbour tables depending on the active link filter. |
| `merged-detailed` | `td-merged-topology-all.json` | Full merged dataset; all link types available. |
| `otbr_restapi` | `td-otbr-restapi-devices.json`, `td-otbr-restapi-diagnostics.json` | Nodes from OTBR REST API device list; edges from route data and child tables embedded in the REST API payloads. |
| `eve_enhanced` | `td-eve-topology.json` | Nodes from the pre-processed Eve topology; edges from enriched `routes` and `children` arrays. |
| `eve_native` | `*.evethreadlayout` | Nodes from a raw Eve App export; edges from the native `routes` and `children` arrays. |
| `router-table` | `td-otbr-cli-router-table.json` | Nodes from the router table only; edges based on Next Hop column. |
| `raw-array` | any flat JSON array | Passes rows directly to the table renderer with no topology edges; used for mDNS scopes and the static extaddr→label map. |

### Link Filters

The **Links** dropdown controls which edge types are drawn for the current topology mode.  The default filter for each dataset is set by `defaultLinkFilter` in `DATASET_REGISTRY`.

| Filter value | Edges drawn |
|---|---|
| `all_links` | All available edge types for the current topology mode.  Can produce a dense graph for large networks. |
| `default_links` | Router-to-router links from the 3/2/1-link quality buckets, plus child links from the `children` array and `childTable` entries. |
| `default_plus_router_neighbors` | Everything in `default_links`, plus additional edges from the router-neighbour tables (`meshdiag routerneighbortable`). |
| `otbr_rest_api` | Edges from `routeData` and `childTable` fields in the OTBR REST API payloads. |
| `eve_enhanced_routes_children` | Edges from the `routes` and `children` arrays in the pre-processed Eve topology. |
| `eve_native_routes_children` | Edges from the `routes` and `children` arrays in a raw Eve App export. |
| `lq_high` | Only high-quality (LQ3 / 3-link bucket) router-to-router edges. |
| `lq_medium` | Only medium-quality (LQ2 / 2-link bucket) router-to-router edges. |
| `lq_low` | Only low-quality (LQ1 / 1-link bucket) router-to-router edges. |
| `lq_parent_child` | Only parent→child edges from all source types (default children, Eve child, OTBR child). |
| `lq_otbr_neighbor` | OTBR route edges and router-neighbour table edges only. |
| `lq_none` | No edges — topology nodes are shown without any connections. |

> **Tip:** When a dataset is selected, its `defaultLinkFilter` is automatically applied.  Switch the link filter after loading to explore different views of the same data without reloading.

---

## Testing and Mock Server

| File | Purpose |
|---|---|
| `tests/td_mock_otbr_restapi_server.py` | In-process `ThreadingHTTPServer` that serves mock JSON:API responses for `/api/node`, `/node/state`, `/node/dataset/active`, `/api/devices`, `/api/diagnostics`, and `/api/actions`.  Used when a live OTBR is not available.  Runs on `127.0.0.1:18081` by default. |
| `tests/test_otbr_restapi_download.py` | Unit tests for `otbr_restapi_download.py`. |
| `tests/test_otbr_restapi_client.py` | Unit tests for the flattened client: JSON:API flattening, HTTP error parsing, usage validation, CLI output and exit codes. |
| `tests/test_otbr_restapi_raw_client.py` | Unit tests for the raw client: raw envelope pass-through, error handling. |
| `tests/test_td_merge_identity.py` | Unit tests for `build_merged_records()` in `merge_dataset.py`: verifies that `extaddr`, `extAddress`, and `Extended MAC` aliases all resolve to the same canonical record under `by-identity` merge. |
| `tests/test_td_cli_argparse.py` | Unit tests for `td_cli.py`: covers `build_parser()`, `dispatch()`, and `main()` — argument parsing, subcommand routing, and exit codes. |
| `tests/test_td_cli_datadir_forwarding.py` | Unit tests for `--datadir` forwarding: verifies the global `--datadir` argument is correctly parsed and forwarded to subcommand modules. |
| `tests/test_td_webserver_concurrency.py` | Unit tests for web server concurrency: verifies that long-running background jobs are tracked correctly and that concurrent requests to the same file do not spawn duplicate subprocesses. |
| `tests/test_tdash_web_routing.py` | Tests for dashboard/web route handling. |
| `tests/test_util_data.py` | Unit tests for `util_data.py`: data-directory resolution precedence (env var, CLI arg, Docker default, local default) and path normalisation. |
| `tests/test_phase6_verification_matrix.py` | Integration tests for data-dir resolution edge cases and web server routing behaviour. |
| `tests/test_util_convert_base64_extaddr_to_hexnumber.py` | Script exercising `b64_to_extended_address()` for a single Base64 extended-address string. |
| `tests/test_util_convert_base64_extaddr_list_to_hexnumber_list.py` | Script exercising `b64_to_extended_address()` across a list of Base64 extended-address strings. |
| `tests/test_util_convert_hexnumber_extaddr_to_base64.py` | Script exercising `convert_hexnumber_extaddr_to_base64()` for a single hex extended-address string. |

---

## Data Flow

```
┌────────────────────────────────────────────────────────────────┐
│                        Data Collection                         │
│                                                                │
│  OTBR REST API          ot-ctl (Docker)        Eve App / mDNS  │
│  otbr_restapi_*         otbr_cli_*             eve_process.py  │
│  *.py                   *.py                   mdns_            │
│                                                thread_scopes.py│
└────────────────┬───────────────────┬───────────────────────────┘
                 │  JSON files        │  JSON files
                 ▼                   ▼
┌────────────────────────────────────────────────────────────────┐
│                         merge_dataset.py                       │
│  Normalize identifiers (RLOC16, extaddr, OMR IPv6)             │
│  Merge rows by identity  →  resolve conflicts                  │
│  Output: td-merged-topology-all.json                           │
└──────────────────────────────────┬─────────────────────────────┘
                                   │  merged JSON
                                   ▼
┌────────────────────────────────────────────────────────────────┐
│                    Browser Dashboard                           │
│  tdash.html  (vis-network topology + sortable table)           │
└────────────────────────────────────────────────────────────────┘
```

### Step-by-step

1. **Collect**: Run individual `otbr_restapi_*`, `otbr_cli_*`, and `mdns_*` scripts directly, or via `python3 -m td_cli`.  Each saves data as a local JSON file (e.g. `td-otbr-restapi-devices.json`, `td-otbr-cli-router-table.json`, `td-eve-topology.json`).
2. **Normalize**: Each collector normalises its data — RLOC16 values are hex strings (`0x5000`), extended addresses are lowercase hex (`1a7fbf0434e4f043`), field aliases are canonicalised (`extAddress` → `extaddr`).
3. **Merge**: `merge_dataset.py` (or `python3 -m td_cli merge-dataset`) reads the JSON files and merges records using the configured strategy.  Non-empty values are never silently overwritten; conflicts are recorded.  The output JSON (`td-merged-topology-all.json`) retains a `_source_files` list per row.
4. **Visualise**: Open `src/tdash.html` in a browser, select a dataset from the dropdown, and explore the interactive topology graph or table.  Alternatively, serve the `src/` directory with `python3 -m td_webserver` and open `http://localhost:9165/tdash.html`.

---

## Key Thread Concepts Used in the Code

| Term | Meaning |
|---|---|
| **RLOC16** | 16-bit Routing Locator.  Primary in-network identifier for a Thread node. |
| **extaddr / Extended MAC** | 64-bit IEEE 802.15.4 extended address.  Used as a stable identity across resets. |
| **OMR** | Off-Mesh Routable prefix.  IPv6 prefix assigned by the Border Router for reachability from the wider network. |
| **Mesh-Local Prefix** | IPv6 prefix (`fd…::/64`) private to the Thread partition; used to derive RLOC addresses. |
| **FTD / MTD** | Full Thread Device (can become a Router) vs. Minimal Thread Device (end device only). |
| **Border Router (BR)** | A device connecting the Thread network to an IP backbone (usually running OTBR). |
| **JSON:API** | Structured REST response format used by OTBR; `id`, `type`, `attributes` are top-level keys. |

---

## Running the Tools

### Prerequisites

- Python 3.10+
- A running OTBR Docker container named `otbr` (or set `TD_OTBR_CONTAINER_NAME`)
- For mDNS discovery: `pip install zeroconf`

### Collect and merge data — via unified CLI (`python3 -m td_cli {command}`)

Run all commands from the `src/` directory (or add `src/` to `PYTHONPATH`).

```bash
cd src

# Download REST API snapshots
python3 -m td_cli otbr-restapi download

# Collect thread network info (provides OMR / mesh-local prefixes used by other collectors)
python3 -m td_cli otbr-cli thread-network-info

# Collect all CLI topology data in one shot
python3 -m td_cli otbr-cli all

# Or collect individual CLI sources
python3 -m td_cli otbr-cli router-table
python3 -m td_cli otbr-cli meshdiag topology
python3 -m td_cli otbr-cli meshdiag childtable
python3 -m td_cli otbr-cli meshdiag childip6
python3 -m td_cli otbr-cli meshdiag routerneighbortable
python3 -m td_cli otbr-cli networkdiag fetch-all

# Scan mDNS (optional)
python3 -m td_cli mdns thread

# Process an Eve layout file (optional)
python3 -m td_cli process-eve

# Merge everything
python3 -m td_cli merge-dataset

# Use a custom data directory (overrides TD_DATA_DIR env var)
python3 -m td_cli --datadir /path/to/data otbr-cli all
python3 -m td_cli --datadir /path/to/data merge-dataset
```

### Collect and merge data — via individual modules

```bash
# Download REST API snapshots
python src/otbr_restapi_download.py

# Collect thread network info (provides OMR / mesh-local prefixes used by other collectors)
python src/otbr_cli_thread_network_info.py

# Collect CLI topology data (unicast polling)
python src/otbr_cli_router_table.py
python src/otbr_cli_meshdiag_topology.py
python src/otbr_cli_meshdiag_childtable.py
python src/otbr_cli_meshdiag_routerneighbortable.py
python src/otbr_cli_networkdiag_topology.py

# Alternatively, collect CLI topology data via multicast (faster, discovers entire network at once)
python3 -m td_cli otbr-cli networkdiag multicast-network
python3 -m td_cli otbr-cli networkdiag multicast-neighbors

# Merge everything
python src/merge_dataset.py
```

### Use the REST API clients directly

```bash
# Flattened client CLI (via td_cli.py)
python3 -m td_cli otbr-restapi node get
python3 -m td_cli otbr-restapi devices list --with-meta

# Raw client CLI (via td_cli.py)
python3 -m td_cli otbr-restapi --raw node get

# Or invoke the modules directly
python src/otbr_restapi_cli.py node get
```

### Start the web server

```bash
# Run the web server module directly (serves src/ on http://localhost:9165, data from ./data)
python3 -m td_webserver

# Custom host/port
python3 -m td_webserver --host 0.0.0.0 --port 8090

# Custom data directory (JSON files served from /path/to/data)
python3 -m td_webserver --datadir /path/to/data

# Or as a module (from the repository root)
python3 -m td_webserver --port 9165
python3 -m td_webserver --port 9165 --datadir /path/to/data
```

### Open the dashboard

Open `http://localhost:9165/tdash.html` after starting the web server, in a browser and select a dataset from the dropdown.

### Run tests

```bash
# All tests
python -m pytest tests/

# Specific test modules
python -m unittest tests/test_otbr_restapi_download.py tests/test_otbr_restapi_client.py 
python -m unittest tests/test_td_merge_identity.py
python -m unittest tests/test_td_cli_argparse.py
python -m unittest tests/test_tdash_web_routing.py
```

### Mock server (no live OTBR needed)

```bash
python tests/td_mock_otbr_restapi_server.py --host 127.0.0.1 --port 18081
# then override client defaults:
python src/otbr_restapi_cli.py --host 127.0.0.1 --port 18081 node get
# or via td_cli.py:
python3 -m td_cli otbr-restapi --host 127.0.0.1 --port 18081 node get
```

---

## Merge Strategy Reference

| Strategy | Behaviour |
|---|---|
| `none` | Pass loaded JSON through without merging rows |
| `by-rloc16` | Merge rows only when `rloc16` matches |
| `by-identity` | Merge when any canonical identity matches (checked in order: `extaddr` → `omr_ipv6_addr` → `rloc16`) |

Identity matching is case-insensitive and ignores leading/trailing whitespace.  Empty identifiers are never used for matching.

---

## REST API Client Exit Codes

The `otbr_restapi_cli.py` exit codes:

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Unexpected error |
| `2` | Usage / local input error |
| `3` | Connection failure |
| `4` | OTBR HTTP error response |
| `5` | Invalid response payload |
