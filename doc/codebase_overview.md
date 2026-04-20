# Codebase Overview

## What Is tdash?

Thread Mesh Network Dashboard (tdash) is a Python toolkit and browser-based dashboard for visualizing and monitoring [Thread](https://github.com/openthread/openthread) mesh networks.  It collects network data from several sources (OTBR, mDNS, Eve), normalizes and merges that data, and renders it as an interactive topology graph and table in HTML dashboard page.

The tool collects data from various dataset sources including:
- otbr-cli: Open Thread OTBR cli. Executes ot-ctl command line tool against an OTBR instance to scan for information on thread devices. 
- otbr-restapi: Open Thread OTBR restapi. Web calls to OTBR instance restapi to collect information on thread devices.
- mDNS: Multicast DNS allows devices on a local network to discover each other and services
- Eve app: The native Eve JSON file has useful information for Apple Home thread mesh networks. This tool enhances the native Eve app JSON file with RLOC16 in hex format, etc
---

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
| Standard library only (`urllib`, `http.server`, `subprocess`, `argparse`, …) | No third-party Python runtime dependencies (except `zeroconf` for mDNS) |

---

## Repository Layout

```
tdash/
├── doc/                        # Documentation
│   ├── codebase_overview.md    # This file
│   └── otbr_restapi_clients.md # OTBR REST API client reference
├── src/                        # All source code
│   ├── tdash.py                # Unified CLI dispatcher (top-level entry point)
│   ├── tdash_web_server.py     # HTTP web server module
│   ├── tdash.html              # Combined single-page browser dashboard
│   ├── tdash.css               # Dashboard stylesheet
│   ├── js/                     # Dashboard JavaScript modules
│   │   ├── tdash-adaptors.js       # Topology adaptors (meshdiag/REST/Eve → vis-network)
│   │   ├── tdash-constants.js      # Merge strategies, link filters, edge category labels
│   │   ├── tdash-dataset-registry.js # Dataset registry (files, modes, filters)
│   │   ├── tdash-dataset.js        # Dataset loading and node label enrichment
│   │   ├── tdash-filters.js        # Node and edge visibility filters
│   │   ├── tdash-merge.js          # Client-side row merge by identity
│   │   ├── tdash-table-renderer.js # Sortable table renderer
│   │   ├── tdash-topology-renderer.js # vis-network topology renderer
│   │   ├── tdash-topology-utils.js # Node/edge helper utilities
│   │   ├── tdash-ui.js             # UI event wiring and render dispatch
│   │   └── tdash-utils.js          # Canonical identity and type helpers
│   ├── otbr_restapi_*.py       # OTBR REST API collectors and CLI clients
│   ├── otbr_cli_*.py           # ot-ctl CLI collectors
│   ├── mdns_thread_scopes.py   # mDNS discovery collector
│   ├── eve_parse.py            # Eve topology parser
│   ├── dataset_merge.py        # Dataset merge engine
│   ├── extaddr_device_label_map.py  # Static extaddr→label loader
│   ├── util_*.py               # Shared utility modules
│   └── td_web*.py              # HTTP server prototypes (scratch)
├── tests/                      # Test suite and local mock server
│   ├── test_*.py               # Unit tests
│   └── td_mock_otbr_restapi_server.py
├── .devcontainer/              # VS Code / Codespaces dev-container config
├── README.md
└── LICENSE
```

Collector and utility files use source-first prefixes (`otbr_restapi_`, `otbr_cli_`, `mdns_`, `eve_`, `util_`).
Test files use `test_*.py` names that follow the module under test.

---

## CLI vs REST API Naming

This codebase uses a strict naming split so the data source is visible from the filename.

| Prefix | Data source | Example |
|---|---|---|
| `otbr_cli_` | OTBR `ot-ctl` CLI wrappers (via Docker exec) | `otbr_cli_router_table.py` |
| `otbr_restapi_` | OTBR HTTP REST API clients and downloaders | `otbr_restapi_client.py` |
| `mdns_` | Zeroconf/mDNS discovery collectors | `mdns_thread_scopes.py` |
| `eve_` | Eve topology parsing helpers | `eve_parse.py` |
| `util_` | Shared helpers used across collectors/parsers | `util_network.py` |

---

## Source File Catalogue

### Data Collection — OTBR REST API

| File | Purpose |
|---|---|
| `otbr_restapi_download.py` | Fixed-target downloader: fetches `/node/dataset/active`, `/api/devices`, and `/api/diagnostics` and writes them to local JSON files.  Accepts CLI overrides for host, port, base URL, timeout, and headers. |
| `otbr_restapi_client.py` | Full-featured REST API client (`OTBRRestApiClient`).  Returns **flattened** Python objects by default (JSON:API `id`/`type`/`attributes` merged into a single dict). Also contains the shared exception hierarchy (`OTBRHTTPError`, `OTBRConnectionError`, etc.). |
| `otbr_restapi_raw_client.py` | Thin subclass (`OTBRRawRestApiClient`) that defaults to returning raw JSON:API envelopes (`{"data": …, "meta": …}`) rather than flattening them. |
| `otbr_restapi_client_cli.py` | CLI front-end for the flattened client.  Supports sub-commands: `node get/state get/state set/dataset get`, `devices list/get`, `diagnostics list/get`, `actions list/get/enqueue`. |
| `otbr_restapi_raw_client_cli.py` | Identical command surface as the flattened CLI but routes through the raw client. |

### Data Collection — ot-ctl CLI (via Docker)

| File | ot-ctl Command | Output File | Purpose |
|---|---|---|---|
| `otbr_cli_router_table.py` | `router table` | `td-otbr-cli-router-table.json` | Parses the pipe-delimited router table into a list of router dicts with fields: ID, RLOC16, Next Hop, Path Cost, LQ In/Out, Age, Extended MAC, and Link. Adds `extaddr` and `device_label` from the static label map. |
| `otbr_cli_meshdiag_topology.py` | `meshdiag topology ip6-addrs children` | `td-otbr-cli-meshdiag-topology.json` | Parses per-router blocks containing: RLOC16, extaddr, Thread version, BR flag, link-quality buckets (1/2/3-links with peer IDs), IPv6 address list, and children (RLOC16 + link quality + mode).  Also computes `total_children`, `total_links`, and `omrIpv6Address`. |
| `otbr_cli_meshdiag_childtable.py` | `meshdiag childtable <rloc16>` (once per router) | `td-otbr-cli-meshdiag-router-childtables.json` | For every router in the router table, collects per-child details: RLOC16, extaddr, Thread version, timeout, age, supervision interval, queued messages, rx-on flag, device type, full-net flag, RSS (avg/last/margin), frame/message error rates, connection time, and CSL parameters.  Handles `ResponseTimeout` gracefully. |
| `otbr_cli_meshdiag_routerneighbortable.py` | `meshdiag routerneighbortable <rloc16>` (once per router) | `td-otbr-cli-meshdiag-router-neighbortables.json` | For every router in the router table, collects per-neighbour details: RLOC16, extaddr, Thread version, RSS (avg/last/margin), frame/message error rates, and connection time.  Handles `ResponseTimeout` gracefully. |
| `otbr_cli_networkdiag_topology.py` | `networkdiag get <rloc-ipv6> <tlvs>` (once per router) | `td-otbr-cli-networkdiag-topology.json` | For every router, issues a network-diagnostic TLV request and parses: IPv6 address list, Mode TLV (RxOnWhenIdle / DeviceType / NetworkData → FTD/MTD classification), child table (IDs, timeouts, link quality, mode flags), MAC counters (error/discard totals and percentages relative to total packets), MLE counters (role changes, partition ID changes, parent changes, attach attempts), and time-in-role statistics. |
| `otbr_cli_network_dataset_info.py` | `dataset active`, `prefix meshlocal`, `br omrprefix favored` | `td-otbr-cli-network-dataset-info.json` | Collects the active Thread dataset (channel, PAN ID, extended PAN ID, mesh-local prefix, network name, etc.) and derives the mesh-local IPv6 RLOC prefix and the OMR prefix for use by other collectors. |

### Data Collection — Other Sources

| File | Purpose |
|---|---|
| `mdns_thread_scopes.py` | Uses `zeroconf` to browse for Thread-related mDNS service types (e.g. `_meshcop._udp`).  Decodes HAP categories, State Bitmaps, and OUI vendor lookups. |

### Data Parsing

| File | Purpose |
|---|---|
| `eve_parse.py` | Parses an Eve App `thread-eve-layout.json` export.  Normalises decimal RLOC16 to hex, converts base64-encoded extended addresses to hex, enriches nodes with OMR IPv6 address and route-destination names, and keys the output by `rloc16_hex`. |
| `extaddr_device_label_map.py` | Loads a static `td-static-extaddr-device-label.json` file that maps extended addresses to human-readable device labels. |

### Data Merging

| File | Purpose |
|---|---|
| `dataset_merge.py` | Reads multiple JSON data files (OTBR CLI, REST API, Eve) and merges all records into a single output file.  Supports three merge strategies: `none` (pass-through), `by-rloc16`, and `by-identity` (matches on RLOC16, canonical `extaddr`, or `omrIpv6Address`).  Tracks source provenance in `_source_files` and records conflicts without overwriting existing values. |

### Utilities

| File | Purpose |
|---|---|
| `util_ot_ctl.py` | Low-level wrapper that runs `ot-ctl <command>` inside a named Docker container via `docker exec`.  The container name defaults to `"otbr"` and can be overridden with the `TD_OTBR_CONTAINER_NAME` environment variable. |
| `util_network.py` | Network helpers: mesh-local and OMR prefix retrieval, IPv6 address prefix formatting, RLOC16 manipulation, OMR address matching in an address list, and full `get_network_dataset_info()` aggregator. |
| `util_convert.py` | Base64 ↔ hex conversion for 64-bit extended addresses (handles JSON-escaped slashes and optional byte-order reversal for 802.15.4 little-endianness). |

### Web Dashboard and Server

| File | Purpose |
|---|---|
| `tdash.html` | Combined single-page dashboard — replaces the former separate topology and tables HTML files.  See [Dashboard Functions](#dashboard-functions) below. |
| `tdash.css` | Stylesheet for the browser dashboard.  Defines CSS variables for colours, typography, and layout of all dashboard components. |
| `tdash_web_server.py` | HTTP server module.  Binds to `$HOST`/`$PORT` (default port `8087`) and serves `src/` as a static file tree with explicit MIME-type overrides.  Has `build_parser()` and `main(argv)` so it can be invoked standalone or via `tdash.py web-server`. |

### Dashboard JavaScript Modules (`js/`)

| File | Purpose |
|---|---|
| `tdash-adaptors.js` | Topology adaptors — converts raw data from each source (meshdiag, networkdiag, REST API, Eve native, Eve enhanced, router-table) into the unified `{nodes, edges}` format consumed by vis-network. |
| `tdash-constants.js` | Central registry of merge-strategy identifiers, link-filter mode names, edge-category label strings, and dropdown option metadata used across modules. |
| `tdash-dataset-registry.js` | Defines `DATASET_REGISTRY`: each entry names the JSON file(s) to fetch, the merge strategy, the topology adaptor mode, and the default link filter for that dataset. |
| `tdash-dataset.js` | Dataset loading pipeline — fetches JSON file(s) from the server, applies the client-side merge, and enriches nodes with static device labels from the extaddr map. |
| `tdash-filters.js` | Visibility filters — implements edge filtering by link-filter mode and node filtering by device type (FTD/MTD/BR/Router) and diagnostics thresholds. |
| `tdash-merge.js` | Client-side row-merge engine — normalises identifiers and merges rows by `rloc16`, canonical `extaddr`, or `omrIpv6Address`, mirroring the Python `dataset_merge.py` logic. |
| `tdash-table-renderer.js` | Renders the current dataset as a sortable, column-filterable HTML table; discovers columns dynamically from loaded rows. |
| `tdash-topology-renderer.js` | Drives the vis-network graph: creates nodes and edges via the active adaptor, applies node/edge filters, handles click-to-details-panel, and wires physics/animation/zoom toggles. |
| `tdash-topology-utils.js` | Low-level helpers shared by adaptors and renderers: node-ID selection, label building, and directed-edge deduplication with per-category tracking. |
| `tdash-ui.js` | Top-level UI wiring — binds dropdown and button event handlers, delegates dataset loads, and dispatches render calls to the topology or table renderer. |
| `tdash-utils.js` | Primitive helpers for canonical-identity comparison (`rloc16`, `extaddr`, `omrIpv6Address`) and type guards used by the merge and filter modules. |

### Unified CLI Dispatcher

| File | Purpose |
|---|---|
| `tdash.py` | Top-level CLI entry point.  Builds a hierarchical `argparse` tree and dispatches to the appropriate module `main()`.  Supported top-level commands: `scan` (otbr-cli sub-tree and mdns), `web` (otbr-restapi download/client/rawclient), `process` (eve), `merge` (dataset), and `web-server`.  Unknown trailing arguments are forwarded via `parse_known_args` to subordinate modules. |

### Scratch / Prototype Files

| File | Purpose |
|---|---|
| `td_web1.py` | Hello-world `HTTPServer` prototype. |
| `td_web2.py` | `socketserver.TCPServer` + `SimpleHTTPRequestHandler` prototype. |
| `td_web3.py` | Custom `GET` handler prototype. |
| `td_web4.py` | POST body-size-limited handler prototype. |
| `TODO_otbr_cli_meshdiag_childip6_add_parsing.py` | Placeholder stub for future `meshdiag childip6` parser (not yet implemented; referenced as `NotImplementedError` in `tdash.py`). |

---

## Dashboard Functions

`tdash.html` is a single-page application with no build step — open it directly in a browser.

### Dataset Selection

A **Dataset** dropdown (populated from `DATASET_REGISTRY`) lets you choose which JSON file(s) to load. Each registry entry specifies:

- `files[]` — one or more local JSON filenames to fetch (via `fetch()`)
- `mergeStrategy` — how to combine multiple files (`none` / `by-rloc16` / `by-identity`)
- `topologyMode` — which topology adaptor to use when drawing the graph
- `defaultLinkFilter` — the link filter pre-selected when this dataset loads

Pre-configured datasets include single-file views (router table, meshdiag-only, REST API devices) as well as rich multi-file merged views combining CLI collectors, REST API data, and Eve exports.

### View Modes

| Button | What it shows |
|---|---|
| **Topology** | Interactive [vis-network](https://visjs.github.io/vis-network/docs/network/) graph of the mesh.  Click any node to see all its properties in the side panel. |
| **Table** | Flat [sortable](https://github.com/tofsjonas/sortable) table of all rows in the loaded dataset.  Click any column header to sort. |
| **Physics** | Toggles the vis-network physics simulation on/off (spring-force layout vs. fixed positions). |
| **Auto Zoom** | Toggles automatic fit-to-view when a dataset loads. |
| **Animation** | Toggles vis-network fit animation.  Disabled by default — fit-to-view is instant on load. |

### Node Filter

Filters which nodes appear in both Topology and Table views:

| Option | Criteria |
|---|---|
| All Nodes | No filter |
| Full Thread Devices (FTD) | `mode.device == "FTD"` |
| Minimal Thread Devices (MTD) | `mode.device == "MTD"` |
| Border Routers | `br == true` |
| Routers | `role == "router"` |
| Routers with Children | `total_children > 0` |
| Routers without Children | `total_children == 0` |

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
| `meshdiag-networkdiag` | `td-otbr-cli-meshdiag-topology.json`, `td-otbr-cli-networkdiag-topology.json` | Nodes for every router; edges derived from the link-quality buckets (1/2/3-links), children arrays, child tables, and router-neighbour tables depending on the active link filter. |
| `merged-detailed` | `td-merged-topology-all.json` | Full merged dataset; all link types available. |
| `otbr_restapi` | `td-otbr-restapi-devices.json`, `td-otbr-restapi-diagnostics.json` | Nodes from OTBR REST API device list; edges from route data and child tables embedded in the REST API payloads. |
| `eve_enhanced` | `td-eve-topology.json` | Nodes from the pre-processed Eve topology; edges from enriched `routes` and `children` arrays. |
| `eve_native` | `*.evethreadlayout` | Nodes from a raw Eve App export; edges from the native `routes` and `children` arrays. |
| `router-table` | `td-otbr-cli-router-table.json` | Nodes from the router table only; edges based on Next Hop column. |

### Link Filters

The **Links** dropdown controls which edge types are drawn for the current topology mode.  The default filter for each dataset is set by `defaultLinkFilter` in `DATASET_REGISTRY`.

| Filter value | Edges drawn |
|---|---|
| `default_links` | Router-to-router links from the 3/2/1-link quality buckets, plus child links from the `children` array and `childTable` entries. |
| `default_plus_router_neighbors` | Everything in `default_links`, plus additional edges from the router-neighbour tables (`meshdiag routerneighbortable`). |
| `otbr_rest_api` | Edges from `routeData` and `childTable` fields in the OTBR REST API payloads. |
| `eve_enhanced_routes_children` | Edges from the `routes` and `children` arrays in the pre-processed Eve topology. |
| `eve_native_routes_children` | Edges from the `routes` and `children` arrays in a raw Eve App export. |
| `all_links` | All available edge types for the current topology mode.  Can produce a dense graph for large networks. |

> **Tip:** When a dataset is selected, its `defaultLinkFilter` is automatically applied.  Switch the link filter after loading to explore different views of the same data without reloading.

---

## Testing and Mock Server

| File | Purpose |
|---|---|
| `tests/td_mock_otbr_restapi_server.py` | In-process `ThreadingHTTPServer` that serves mock JSON:API responses for `/api/node`, `/node/state`, `/node/dataset/active`, `/api/devices`, `/api/diagnostics`, and `/api/actions`.  Used when a live OTBR is not available.  Runs on `127.0.0.1:18081` by default. |
| `tests/test_otbr_restapi_download.py` | Unit tests for `otbr_restapi_download.py`. |
| `tests/test_otbr_restapi_client.py` | Unit tests for the flattened client: JSON:API flattening, HTTP error parsing, usage validation, CLI output and exit codes. |
| `tests/test_otbr_restapi_raw_client.py` | Unit tests for the raw client: raw envelope pass-through, error handling. |
| `tests/test_td_merge_identity.py` | Unit tests for `build_merged_records()` in `dataset_merge.py`: verifies that `extaddr`, `extAddress`, and `Extended MAC` aliases all resolve to the same canonical record under `by-identity` merge. |
| `tests/test_tdash_argparse.py` | Unit tests for `tdash.py`: covers `build_parser()`, `dispatch()`, and `main()` — argument parsing, subcommand routing, and exit codes. |
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
│  otbr_restapi_*         otbr_cli_*             eve_parse.py    │
│  *.py                   *.py                   mdns_            │
│                                                thread_scopes.py│
└────────────────┬───────────────────┬───────────────────────────┘
                 │  JSON files        │  JSON files
                 ▼                   ▼
┌────────────────────────────────────────────────────────────────┐
│                         dataset_merge.py                       │
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

1. **Collect**: Run individual `otbr_restapi_*`, `otbr_cli_*`, and `mdns_*` scripts directly, or via `tdash.py scan` / `tdash.py web`.  Each saves data as a local JSON file (e.g. `td-otbr-restapi-devices.json`, `td-otbr-cli-router-table.json`, `td-eve-topology.json`).
2. **Normalize**: Each collector normalises its data — RLOC16 values are hex strings (`0x5000`), extended addresses are lowercase hex (`1a7fbf0434e4f043`), field aliases are canonicalised (`extAddress` → `extaddr`).
3. **Merge**: `dataset_merge.py` (or `tdash.py merge dataset`) reads the JSON files and merges records using the configured strategy.  Non-empty values are never silently overwritten; conflicts are recorded.  The output JSON (`td-merged-topology-all.json`) retains a `_source_files` list per row.
4. **Visualise**: Open `src/tdash.html` in a browser, select a dataset from the dropdown, and explore the interactive topology graph or table.  Alternatively, serve the `src/` directory with `tdash.py web-server` and open `http://localhost:8087/tdash.html`.

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

### Collect and merge data — via unified CLI (`tdash.py`)

Run all commands from the `src/` directory (or add `src/` to `PYTHONPATH`).

```bash
cd src

# Download REST API snapshots
python tdash.py web otbr-restapi download

# Collect network dataset info (provides OMR / mesh-local prefixes used by other collectors)
python tdash.py scan otbr-cli network-dataset-info

# Collect all CLI topology data in one shot
python tdash.py scan otbr-cli all

# Or collect individual CLI sources
python tdash.py scan otbr-cli router-table
python tdash.py scan otbr-cli meshdiag topology
python tdash.py scan otbr-cli meshdiag childtable
python tdash.py scan otbr-cli meshdiag routerneighbortable
python tdash.py scan otbr-cli networkdiag topology

# Scan mDNS (optional)
python tdash.py scan mdns all

# Process an Eve layout file (optional)
python tdash.py process eve

# Merge everything
python tdash.py merge dataset
```

### Collect and merge data — via individual modules
```bash
# Download REST API snapshots
python src/otbr_restapi_download.py

# Collect network dataset info (provides OMR / mesh-local prefixes used by other collectors)
python src/otbr_cli_network_dataset_info.py

# Collect CLI topology data
python src/otbr_cli_router_table.py
python src/otbr_cli_meshdiag_topology.py
python src/otbr_cli_meshdiag_childtable.py
python src/otbr_cli_meshdiag_routerneighbortable.py
python src/otbr_cli_networkdiag_topology.py

# Merge everything
python src/dataset_merge.py
```

### Use the REST API clients directly
```bash
# Flattened client CLI (via tdash.py)
python src/tdash.py web otbr-restapi client node get
python src/tdash.py web otbr-restapi client devices list --with-meta

# Raw client CLI (via tdash.py)
python src/tdash.py web otbr-restapi rawclient node get

# Or invoke the modules directly
python src/otbr_restapi_client_cli.py node get
python src/otbr_restapi_raw_client_cli.py node get
```

### Start the web server
```bash
# Via unified CLI (serves src/ on http://localhost:8087)
python src/tdash.py web-server

# Custom host/port
python src/tdash.py web-server --host 0.0.0.0 --port 8090

# Or run the module directly
python src/tdash_web_server.py --port 8087
```

### Open the dashboard
Open `http://localhost:8087/tdash.html` after starting the web server, or open `src/tdash.html` directly in a browser and select a dataset from the dropdown.

### Run tests
```bash
# All tests
python -m pytest tests/

# Specific test modules
python -m unittest tests/test_otbr_restapi_download.py tests/test_otbr_restapi_client.py tests/test_otbr_restapi_raw_client.py
python -m unittest tests/test_td_merge_identity.py
python -m unittest tests/test_tdash_argparse.py
```

### Mock server (no live OTBR needed)
```bash
python tests/td_mock_otbr_restapi_server.py --host 127.0.0.1 --port 18081
# then override client defaults:
python src/otbr_restapi_client_cli.py --host 127.0.0.1 --port 18081 node get
# or via tdash.py:
python src/tdash.py web otbr-restapi client --host 127.0.0.1 --port 18081 node get
```

---

## Merge Strategy Reference

| Strategy | Behaviour |
|---|---|
| `none` | Pass loaded JSON through without merging rows |
| `by-rloc16` | Merge rows only when `rloc16` matches |
| `by-identity` | Merge when any canonical identity matches (checked in order: `rloc16` → canonical `extaddr` → `omrIpv6Address`) |

Identity matching is case-insensitive and ignores leading/trailing whitespace.  Empty identifiers are never used for matching.

---

## Animation Button — Call Chain

The **Animation** button in `tdash.html` controls whether vis-network uses a smooth animated transition when fitting the graph to the viewport.

### 1. HTML button (`tdash.html:24`)
```html
<button id="btn-animation" class="active" title="Toggle vis.js animation">Animation</button>
```
Starts without `active` class (animation **OFF** by default).

### 2. Click handler wiring (`tdash-ui.js:135`)
```js
document.getElementById('btn-animation')
  .addEventListener('click', () => setAnimation(!isAnimationEnabled()));
```
On click, calls the local `setAnimation(bool)` with the toggled value.

### 3. `setAnimation()` (`tdash-ui.js:125`)
```js
function setAnimation(enabled) {
  setAnimationEnabled(enabled);              // writes state to renderer module
  const btn = document.getElementById('btn-animation');
  if (enabled) btn.classList.add('active');
  else         btn.classList.remove('active');
}
```
Updates the button's visual `active` class, then delegates state storage to the renderer.

### 4. State stored in renderer (`tdash-topology-renderer.js:20`)
```js
let _animationEnabled = false;   // module-level flag, OFF by default

export function setAnimationEnabled(val) { _animationEnabled = val; }
export function isAnimationEnabled()     { return _animationEnabled; }
```

### 5. vis.js consumption (`tdash-topology-renderer.js:237`)

`_animationEnabled` is read in `fitIfEnabled()`, stored in `_topologyFilterHandlers`, and called after every dataset load or filter change:

```js
fitIfEnabled: () => {
  if (_autoZoomEnabled && _visNetwork) {
    requestAnimationFrame(() => {
      if (_visNetwork) {
        _visNetwork.fit({ animation: _animationEnabled });  // vis.js call
      }
    });
  }
}
```

`_visNetwork.fit({ animation: true })` tells vis-network to **smoothly pan/zoom** the graph to fit all visible nodes.  When `animation: false`, the fit is **instant** with no transition.

### Visibility scoping

The button is shown/hidden when switching views (`tdash-ui.js:70`):
- `topology` view → `display: inline-block`
- `table` view → `display: none`

### Layer summary

| Layer | File | Role |
|---|---|---|
| Button `#btn-animation` | `tdash.html:24` | Toggle UI element, starts active |
| Click handler + `setAnimation()` | `tdash-ui.js:125,135` | Toggles `active` class, calls renderer setter |
| `_animationEnabled` flag | `tdash-topology-renderer.js:20` | Module-level boolean state |
| `setAnimationEnabled()` / `isAnimationEnabled()` | `tdash-topology-renderer.js:27,29` | Exported getter/setter |
| `_visNetwork.fit({ animation: bool })` | `tdash-topology-renderer.js:239` | Actual vis.js API call — animated vs instant fit |

---

## REST API Client Exit Codes

Both CLI pairs (`otbr_restapi_client_cli.py` and `otbr_restapi_raw_client_cli.py`) use the same exit codes:

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Unexpected error |
| `2` | Usage / local input error |
| `3` | Connection failure |
| `4` | OTBR HTTP error response |
| `5` | Invalid response payload |
