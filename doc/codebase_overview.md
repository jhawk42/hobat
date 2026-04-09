# tdash Codebase Overview

## What Is tdash?

**tdash** (Thread Dashboard) is a Python toolkit and browser-based dashboard for visualizing and monitoring [Thread](https://www.threadgroup.org/) mesh networks.  It collects network data from several sources, normalizes and merges that data, and renders it as an interactive topology graph and table in plain HTML files.

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
│   ├── td_*.py                 # Python modules and scripts
│   ├── test_*.py               # Unit tests
│   └── td_web_*.html           # Browser dashboard pages
├── .devcontainer/              # VS Code / Codespaces dev-container config
├── README.md
└── LICENSE
```

All Python files share the `td_` prefix.  Test files are prefixed `test_td_`.

---

## Source File Catalogue

### Data Collection — OTBR REST API

| File | Purpose |
|---|---|
| `td_get_otbr_restapi.py` | Fixed-target downloader: fetches `/node/dataset/active`, `/api/devices`, and `/api/diagnostics` and writes them to local JSON files.  Accepts CLI overrides for host, port, base URL, timeout, and headers. |
| `td_get_otbr_restapi_client.py` | Full-featured REST API client (`OTBRRestApiClient`).  Returns **flattened** Python objects by default (JSON:API `id`/`type`/`attributes` merged into a single dict). Also contains the shared exception hierarchy (`OTBRHTTPError`, `OTBRConnectionError`, etc.). |
| `td_get_otbr_restapi_raw_client.py` | Thin subclass (`OTBRRawRestApiClient`) that defaults to returning raw JSON:API envelopes (`{"data": …, "meta": …}`) rather than flattening them. |
| `td_get_otbr_restapi_client_cli.py` | CLI front-end for the flattened client.  Supports sub-commands: `node get/state get/state set/dataset get`, `devices list/get`, `diagnostics list/get`, `actions list/get/enqueue`. |
| `td_get_otbr_restapi_raw_client_cli.py` | Identical command surface as the flattened CLI but routes through the raw client. |

### Data Collection — ot-ctl CLI (via Docker)

| File | ot-ctl Command | Output File | Purpose |
|---|---|---|---|
| `td_get_otbr_cli_router_table.py` | `router table` | `td-otbr-cli-router-table.json` | Parses the pipe-delimited router table into a list of router dicts with fields: ID, RLOC16, Next Hop, Path Cost, LQ In/Out, Age, Extended MAC, and Link. Adds `extaddr` and `device_label` from the static label map. |
| `td_get_otbr_cli_meshdiag_topology.py` | `meshdiag topology ip6-addrs children` | `td-otbr-cli-meshdiag-topology.json` | Parses per-router blocks containing: RLOC16, extaddr, Thread version, BR flag, link-quality buckets (1/2/3-links with peer IDs), IPv6 address list, and children (RLOC16 + link quality + mode).  Also computes `total_children`, `total_links`, and `omrIpv6Address`. |
| `td_get_otbr_cli_meshdiag_childtable.py` | `meshdiag childtable <rloc16>` (once per router) | `td-otbr-cli-meshdiag-router-childtables.json` | For every router in the router table, collects per-child details: RLOC16, extaddr, Thread version, timeout, age, supervision interval, queued messages, rx-on flag, device type, full-net flag, RSS (avg/last/margin), frame/message error rates, connection time, and CSL parameters.  Handles `ResponseTimeout` gracefully. |
| `td_get_otbr_cli_meshdiag_routerneighbortable.py` | `meshdiag routerneighbortable <rloc16>` (once per router) | `td-otbr-cli-meshdiag-router-neighbortables.json` | For every router in the router table, collects per-neighbour details: RLOC16, extaddr, Thread version, RSS (avg/last/margin), frame/message error rates, and connection time.  Handles `ResponseTimeout` gracefully. |
| `td_get_otbr_cli_networkdiag_topology.py` | `networkdiag get <rloc-ipv6> <tlvs>` (once per router) | `td-otbr-cli-networkdiag-topology.json` | For every router, issues a network-diagnostic TLV request and parses: IPv6 address list, Mode TLV (RxOnWhenIdle / DeviceType / NetworkData → FTD/MTD classification), child table (IDs, timeouts, link quality, mode flags), MAC counters (error/discard totals and percentages relative to total packets), MLE counters (role changes, partition ID changes, parent changes, attach attempts), and time-in-role statistics. |
| `td_get_otbr_cli_network_dataset_info.py` | `dataset active`, `prefix meshlocal`, `br omrprefix favored` | `td-otbr-cli-network-dataset-info.json` | Collects the active Thread dataset (channel, PAN ID, extended PAN ID, mesh-local prefix, network name, etc.) and derives the mesh-local IPv6 RLOC prefix and the OMR prefix for use by other collectors. |

### Data Collection — Other Sources

| File | Purpose |
|---|---|
| `td_get_mdns_thread_scopes.py` | Uses `zeroconf` to browse for Thread-related mDNS service types (e.g. `_meshcop._udp`).  Decodes HAP categories, State Bitmaps, and OUI vendor lookups. |

### Data Parsing

| File | Purpose |
|---|---|
| `td_parse_eve.py` | Parses an Eve App `thread-eve-layout.json` export.  Normalises decimal RLOC16 to hex, converts base64-encoded extended addresses to hex, enriches nodes with OMR IPv6 address and route-destination names, and keys the output by `rloc16_hex`. |
| `td_parse_extaddr_data_map.py` | Loads a static `td-static-extaddr-device-label.json` file that maps extended addresses to human-readable device labels. |

### Data Merging

| File | Purpose |
|---|---|
| `td_merge.py` | Reads multiple JSON data files (OTBR CLI, REST API, Eve) and merges all records into a single output file.  Supports three merge strategies: `none` (pass-through), `by-rloc16`, and `by-identity` (matches on RLOC16, canonical `extaddr`, or `omrIpv6Address`).  Tracks source provenance in `_source_files` and records conflicts without overwriting existing values. |

### Utilities

| File | Purpose |
|---|---|
| `td_util_ot_ctl.py` | Low-level wrapper that runs `ot-ctl <command>` inside a named Docker container via `docker exec`.  The container name defaults to `"otbr"` and can be overridden with the `TD_OTBR_CONTAINER_NAME` environment variable. |
| `td_util_network.py` | Network helpers: mesh-local and OMR prefix retrieval, IPv6 address prefix formatting, RLOC16 manipulation, OMR address matching in an address list, and full `get_network_dataset_info()` aggregator. |
| `td_util_convert.py` | Base64 ↔ hex conversion for 64-bit extended addresses (handles JSON-escaped slashes and optional byte-order reversal for 802.15.4 little-endianness). |
| `td_util_mdns.py` | OUI vendor lookup table (Apple, Google/Nest, Amazon/Eero, Nanoleaf, Texas Instruments). |

### Web Dashboard

| File | Purpose |
|---|---|
| `td_web_dash.html` | Main self-contained dashboard (see [Dashboard Functions](#dashboard-functions) below). |
| `td_web_tables.html` | Standalone table-only view for the merged dataset. |
| `td_web_topology.html` | Standalone topology-only view. |

---

## Dashboard Functions

`td_web_dash.html` is a single-page application with no build step — open it directly in a browser.

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
| **Animation** | Toggles vis-network edge animation. |

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
| `td_mock_otbr_restapi_server.py` | In-process `ThreadingHTTPServer` that serves mock JSON:API responses for `/api/node`, `/node/state`, `/node/dataset/active`, `/api/devices`, `/api/diagnostics`, and `/api/actions`.  Used when a live OTBR is not available.  Runs on `127.0.0.1:18081` by default. |
| `test_td_get_otbr_restapi.py` | Unit tests for `td_get_otbr_restapi.py`. |
| `test_td_get_otbr_restapi_client.py` | Unit tests for the flattened client: JSON:API flattening, HTTP error parsing, usage validation, CLI output and exit codes. |
| `test_td_get_otbr_restapi_raw_client.py` | Unit tests for the raw client: raw envelope pass-through, error handling. |

---

## Data Flow

```
┌────────────────────────────────────────────────────────────────┐
│                        Data Collection                         │
│                                                                │
│  OTBR REST API          ot-ctl (Docker)        Eve App / mDNS  │
│  td_get_otbr_           td_get_otbr_cli_*      td_parse_eve.py │
│  restapi*.py            *.py                   td_get_mdns_    │
│                                                thread_scopes.py│
└────────────────┬───────────────────┬───────────────────────────┘
                 │  JSON files        │  JSON files
                 ▼                   ▼
┌────────────────────────────────────────────────────────────────┐
│                         td_merge.py                            │
│  Normalize identifiers (RLOC16, extaddr, OMR IPv6)             │
│  Merge rows by identity  →  resolve conflicts                  │
│  Output: td-merged-topology.json                               │
└──────────────────────────────────┬─────────────────────────────┘
                                   │  merged JSON
                                   ▼
┌────────────────────────────────────────────────────────────────┐
│                    Browser Dashboard                           │
│  td_web_dash.html  (vis-network topology + sortable table)     │
└────────────────────────────────────────────────────────────────┘
```

### Step-by-step

1. **Collect**: Run individual `td_get_otbr_*` and `td_get_mdns_*` scripts.  Each saves data as a local JSON file (e.g. `td-otbr-restapi-devices.json`, `td-otbr-cli-router-table.json`, `td-eve-topology.json`).
2. **Normalize**: Each collector normalises its data — RLOC16 values are hex strings (`0x5000`), extended addresses are lowercase hex (`1a7fbf0434e4f043`), field aliases are canonicalised (`extAddress` → `extaddr`).
3. **Merge**: `td_merge.py` reads the JSON files and merges records using the configured strategy.  Non-empty values are never silently overwritten; conflicts are recorded.  The output JSON retains a `_source_files` list per row.
4. **Visualise**: Open one of the HTML files in a browser, select the merged JSON file from the dataset dropdown, and explore the interactive topology graph or table.

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

### Collect and merge data
```bash
# Download REST API snapshots
python src/td_get_otbr_restapi.py

# Collect network dataset info (provides OMR / mesh-local prefixes used by other collectors)
python src/td_get_otbr_cli_network_dataset_info.py

# Collect CLI topology data
python src/td_get_otbr_cli_router_table.py
python src/td_get_otbr_cli_meshdiag_topology.py
python src/td_get_otbr_cli_meshdiag_childtable.py
python src/td_get_otbr_cli_meshdiag_routerneighbortable.py
python src/td_get_otbr_cli_networkdiag_topology.py

# Merge everything
python src/td_merge.py
```

### Use the REST API clients directly
```bash
# Flattened client CLI
python src/td_get_otbr_restapi_client_cli.py node get
python src/td_get_otbr_restapi_client_cli.py devices list --with-meta

# Raw client CLI
python src/td_get_otbr_restapi_raw_client_cli.py node get
```

### Run tests
```bash
python -m unittest src/test_td_get_otbr_restapi_client.py src/test_td_get_otbr_restapi_raw_client.py
```

### Mock server (no live OTBR needed)
```bash
python src/td_mock_otbr_restapi_server.py --host 127.0.0.1 --port 18081
# then override client defaults:
python src/td_get_otbr_restapi_client_cli.py --host 127.0.0.1 --port 18081 node get
```

### Open the dashboard
Open `src/td_web_dash.html` in a browser and point it at the merged JSON file.

---

## Merge Strategy Reference

| Strategy | Behaviour |
|---|---|
| `none` | Pass loaded JSON through without merging rows |
| `by-rloc16` | Merge rows only when `rloc16` matches |
| `by-identity` | Merge when any canonical identity matches (checked in order: `rloc16` → canonical `extaddr` → `omrIpv6Address`) |

Identity matching is case-insensitive and ignores leading/trailing whitespace.  Empty identifiers are never used for matching.

---

## REST API Client Exit Codes

Both CLI pairs (`td_get_otbr_restapi_client_cli.py` and `td_get_otbr_restapi_raw_client_cli.py`) use the same exit codes:

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Unexpected error |
| `2` | Usage / local input error |
| `3` | Connection failure |
| `4` | OTBR HTTP error response |
| `5` | Invalid response payload |
