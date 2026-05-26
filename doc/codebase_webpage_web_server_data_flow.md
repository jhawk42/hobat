# Design: Webpage, Web Server, and Data Flow

_Covers `td_webserver.py`, `tdash.html`, and all `js/*.js` modules._

---

## 1. Layered Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser                                                            │
│                                                                     │
│  ┌──────────────────────┐   ┌─────────────────────────────────────┐│
│  │  tdash.html (DOM)    │   │  JavaScript ES Modules              ││
│  │  - control bars      │   │                                     ││
│  │  - filter dropdowns  │   │  tdash-ui.js         (event wiring) ││
│  │  - topology canvas   │   │  tdash-dataset.js    (fetch+merge)  ││
│  │  - sortable table    │   │  tdash-merge.js      (row merge)    ││
│  │  - details panels    │   │  tdash-adaptors.js   (→vis format)  ││
│  └──────────────────────┘   │  tdash-filters.js    (predicates)   ││
│                             │  tdash-topology-renderer.js         ││
│                             │  tdash-table-renderer.js            ││
│                             │  tdash-topology-utils.js            ││
│                             │  tdash-utils.js                     ││
│                             │  tdash-constants.js  (string consts)││
│                             │  tdash-dataset-registry.js          ││
│                             └─────────────────────────────────────┘│
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ HTTP (fetch API)
                        /api/data/{filename}
                        /api/job/{job_id}
                        /tdash.html, /js/*, /tdash.css
┌──────────────────────────────────┴──────────────────────────────────┐
│  td_webserver.py  (aiohttp)                                         │
│                                                                     │
│  ┌──────────────────┐  ┌─────────────────────────────────────────┐ │
│  │ Static serving   │  │  /api/data/{filename}                   │ │
│  │ src/ tree        │  │  - FILE_ACTION_MAP lookup               │ │
│  │ (no-cache revalidation)│  - freshness check (mtime, max_age) │ │
│  └──────────────────┘  │  - short-cost: sync subprocess 200      │ │
│                        │  - long-cost / force_async: 202 + job   │ │
│                        └─────────────────────────────────────────┘ │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ subprocess
                            td_cli.py + data collectors
                                   │ writes JSON
                            data/ directory  (JSON files on disk)
```

There are four distinct layers:

| Layer | Files | Responsibility |
|---|---|---|
| **Server** | `td_webserver.py` | HTTP serving, cache gating, subprocess dispatch |
| **Data loading** | `tdash-dataset.js`, `tdash-merge.js` | Fetch, normalise, merge raw JSON from server |
| **Adaptation** | `tdash-adaptors.js`, `tdash-topology-utils.js` | Transform merged rows → vis-network node/edge objects |
| **Rendering + filtering** | `tdash-topology-renderer.js`, `tdash-table-renderer.js`, `tdash-filters.js`, `tdash-ui.js` | Render views, apply filters, handle user events |

---

## 2. Server Layer (`td_webserver.py`)

### Routes

| Route | Handler | Purpose |
|---|---|---|
| `GET /` | `handle_root` | 302 redirect to `/tdash.html` |
| `GET /api/data/{filename}` | `handle_data_api` | Serve or regenerate a data file |
| `GET /api/job/{job_id}` | `handle_job_api` | Poll a long-running background job |
| `GET /**` | static file server | All other paths served from `src/` directory |

Static assets (`tdash.html`, `tdash.css`, `js/*.js`) get `Cache-Control: no-cache` so browsers revalidate via ETag / If-Modified-Since but never serve stale bytes without checking the server.

### `FILE_ACTION_MAP` — the filename→action registry

Every data file the browser can request is listed in `FILE_ACTION_MAP` as a `FileAction` dataclass:

```python
@dataclasses.dataclass
class FileAction:
    max_age_s: int          # seconds until the cached file is considered stale
    action: str | list[str] # "STATIC" or td_cli.py CLI args
    action_cost_s: int      # estimated wall-clock seconds for the action
    force_async: bool       # True → always return 202 regardless of cost
```

### Request flow for `/api/data/{filename}`

```
Request arrives
    │
    ▼
_resolve_and_validate()
  - path-traversal guard (_safe_filename)
  - case-insensitive FILE_ACTION_MAP lookup → FileAction
    │
    ▼ (STATIC action)
is_file_fresh?  ──no──▶  HTTPNotFound (404)
    │ yes
    ▼
_build_file_response()   → 200 / 304

    │ (dynamic action)
    ▼
parse Cache-Control header   (no-cache → force regen)
    │
    ▼
_should_regenerate()?
  absent | no-cache | stale?
    │ no           │ yes
    ▼               ▼
serve file      force_async or action_cost_s > 300s?
                  │ yes                    │ no
                  ▼                        ▼
           _dispatch_long_cost()    _dispatch_short_cost()
           - dedup by filename       - dedup by filename
           - create asyncio Task     - acquire per-source lock
           - anchor in _background_tasks  - await run_td_cli subprocess
           - return HTTP 202         - raise HTTPBadGateway on failure
             { job_id, status,
               filename }
                  │                        │
                  ▼                        ▼
            client polls              _build_file_response()
           /api/job/{job_id}           → 200 / 304
           every 5 s
```

### Per-source serialisation

`_source_locks` is a `dict[source_name → asyncio.Lock]`.  All subprocess calls for the same source (`"otbr-cli"`, `"mdns"`, `"otbr-restapi"`) share one lock, so they never run concurrently — preventing hardware and socket conflicts in the underlying CLI layer.

### Response cache headers

Data files get `Cache-Control: max-age=<n>` plus `Last-Modified` and an ETag derived from the file's mtime and size. The client stores the `max-age` in `fileMaxAgeCache` (keyed by filename) and sends it back as a request header on the next fetch, letting the server decide without a round-trip stat.

---

## 3. Data Loading Layer (`tdash-dataset.js`, `tdash-merge.js`)

### Module-level state in `tdash-dataset.js`

| Symbol | Purpose |
|---|---|
| `currentDataset` | Exported live binding; holds `{ entry, rows, rawFiles, capabilities }` after a successful load |
| `staticExtaddrLabelMap` | `Map<lowercase-extaddr, device_label>` pre-loaded at startup |
| `fileMaxAgeCache` | `Map<filename, { maxAge, fetchedAt, lastModifiedAt }>` — per-file cache |
| `_forceFresh` / `_onlyCache` | Toggle flags set by the Force Refresh / Only Cache checkboxes |

### `loadDataset(entryValue)` walkthrough

```
Looks up DATASET_REGISTRY entry by value
    │
    ▼
Set default link-filter in UI from entry.defaultLinkFilter
    │
    ▼
Promise.allSettled( entry.files.map( fetchJson ) )
  Each fetchJson call:
    - attaches per-file cached max-age header (or force-fresh / only-cache)
    - if response.status === 202 → pollJobUntilDone() (5s polling)
    - stores response max-age back into fileMaxAgeCache
    │
    ▼
Build rawFiles[] (null for failed files)  and  loadedFiles[]
    │
    ▼
Apply merge strategy:
  'none'         → normalizeDatasetPayload on first loaded file → rows[]
  'by-rloc16'    → normalizeRows per group → mergeRowsByRloc16(groups)
  'by-identity'  → normalizeRows per group → mergeRowsByIdentity(groups)
    │
    ▼
currentDataset = { entry, rows, rawFiles }
```

### Normalisation and merge (`tdash-merge.js`)

`normalizeRows(rawData, sourceName)` converts any JSON shape (array, object, scalar) into a flat array of plain objects. Every row is stamped with `_source_files: [sourceName]`.

`mergeRowsByIdentity` uses three identity keys in priority order:
1. `rloc16:<hex>` — canonical RLOC16
2. `extaddr:<hex>` — canonical extended address (resolves aliases: `extaddr`, `extAddress`, `Extended MAC`)
3. `omr_ipv6_addr:<addr>` — OMR IPv6 address

When two rows share any key, they are merged: the first non-empty value wins; conflicts are recorded in `_merge_conflicts`; `_source_files` arrays are unioned.

### Static label enrichment

`enrichRows(rows)` / `enrichRawFiles(rawFiles)` are called by `renderCurrentView()` when the **Enhance** toggle is on. They walk every node/row, look up `staticExtaddrLabelMap` by canonical extaddr, and inject `device_label` on a spread copy — the originals in `currentDataset` are never mutated.

---

## 4. Adaptation Layer (`tdash-adaptors.js`, `tdash-topology-utils.js`)

### Dispatch

`runAdaptor(dataset)` selects the adaptor function from `dataset.entry.topologyMode`:

| topologyMode | Adaptor | Input |
|---|---|---|
| `meshdiag-networkdiag` | `adaptMeshdiagNetworkdiag` | meshdiag + networkdiag (with route_data links) + neighbor/child tables |
| `merged-detailed` | `adaptMergedDetailed` | pre-merged topology-all file |
| `otbr_restapi` | `adaptOtbrRestApi` | REST API devices + diagnostics |
| `eve_enhanced` | `adaptEve` | td-eve-topology.json |
| `eve_native` | `adaptEveNative` | raw .evethreadlayout |
| `router-table` | `adaptRouterTable` | td-otbr-cli-router-table.json |
| `raw-array` | `adaptRawArray` | any flat JSON array |

### Output shape

Every adaptor returns the same shape consumed by `renderTopologyForDataset`:

```js
{
  nodeData:              vis-node object[]
  edgeData:              vis-edge object[]
  nodeMap:               Map<nodeId, rawNodeObject>
  rawByIdForDetails:     Map<nodeId, rawObject>  // for the details panel
  routerNeighborByRloc16: Map<rloc16, neighborTableRow>
  sourceNames:           string[]
}
```

### vis-node computed properties

Each node object carries both vis rendering properties (id, label, color, shape, size) and domain-specific boolean/numeric fields used exclusively by the filter predicates:

| Property | How derived | Used by filter |
|---|---|---|
| `isMainRouter` | `rloc16` ends in `00` | node-filter: main-routers |
| `isBorderRouter` | `br === true` | node-filter: border-routers |
| `isRouter` | main router or has children | node-filter: routers-with-children |
| `hasChildren` | `total_children > 0` or `children.length > 0` | node-filter: routers-with-children |
| `mode_device` | `mode.device` field → `"FTD"` or `"MTD"` | node-filter: ftd / mtd |
| `lq3_ratio` / `lq1_ratio` | `total_link_3 / total_links` | diag-filter: link quality distribution |
| `ifinerrors_pct`, `ifouterrors_pct` | from mac_counters | diag-filter: MAC error rate |
| `partitionidchanges`, `parentchanges` | from mle_counters | diag-filter: MLE counters |
| `router_neighbor_max_err_rate_frame_pct` | `computeRouterNeighborStats()` | diag-filter: neighbor frame errors |
| `router_neighbor_min_rss_ave` / `max_rss_ave` | `computeRouterNeighborStats()` | diag-filter: neighbor RSS |

### vis-edge computed properties

Every edge is built by `addEdge()` in `tdash-topology-utils.js`. Deduplication uses `[from, to].sort().join('|')` as the key (plus an optional suffix for distinct edge types). On duplicate, `width` is maxed and `linkCategories[]` is unioned.

Each edge carries:

| Property | Purpose |
|---|---|
| `linkCategories: string[]` | Set of edge-category tokens (`default_3_links`, `router_neighbor`, etc.) — tested by the link filter |
| `lqLevel: 0–3` | LQ bucket; used by `lq_high` / `lq_medium` / `lq_low` filter modes |
| `isParentChild: bool` | True for parent→child edges; used by `lq_parent_child` filter |
| `baseHidden: bool` | When `true` the edge is never shown regardless of filter |
| `color`, `width`, `dashes` | Visual style from `EDGE_LQ_STYLES` constants |

### Link Quality Processing by Dataset Type

Different datasets encode link quality information in different formats. The adaptors normalize these into the common `lqLevel` (0–3) and `linkCategories[]` properties:

#### meshdiag datasets (OTBR CLI `meshdiag topology`)

**Source data:** `3_links[]`, `2_links[]`, `1_links[]` arrays on each router node

**Processing:** Each link array is iterated, creating edges with:
- `linkCategories: [EDGE_CATEGORY_DEFAULT_3]` (for `3_links`), `[EDGE_CATEGORY_DEFAULT_2]` (for `2_links`), or `[EDGE_CATEGORY_DEFAULT_1]` (for `1_links`)
- `lqLevel: 3` (high), `2` (medium), or `1` (low) via `lqStyleFromField(field)`
- Visual style (width, color, dashes) from `EDGE_LQ_STYLES.high`/`.medium`/`.low`

**Example:** A router with `"3_links": [{"id": "52", "rloc16": "0xd000", ...}]` creates an edge with `EDGE_CATEGORY_DEFAULT_3` and `lqLevel: 3`.

#### networkdiag datasets (OTBR CLI `networkdiag topology`)

**Source data:** `route_data.route_data[]` arrays with `link_quality_in` and `link_quality_out` numeric values (0–3 scale)

**Processing:** Each route entry creates an edge with:
- `linkCategories: [EDGE_CATEGORY_OTBR_ROUTE]`
- `lqLevel: 0–3` computed by `lqStyleFromAvgLqi(max(lqi_in, lqi_out), 3)` — takes the conservative (max) value
  - `avgLqi >= 3` → `lqLevel: 3` (high)
  - `avgLqi >= 2` → `lqLevel: 2` (medium)
  - `avgLqi < 2` → `lqLevel: 1` (low)
- Visual style from `EDGE_LQ_STYLES` based on computed level

**Example:** A route with `"link_quality_in": 3, "link_quality_out": 2` computes `max(3, 2) = 3` → `lqLevel: 3`, edge category `EDGE_CATEGORY_OTBR_ROUTE`.

#### Eve datasets (Eve Thread Network Layout)

**Source data (enhanced):** `routes[]` with `avgLqi` values (0–255 scale)

**Processing:**
- `linkCategories: [EDGE_CATEGORY_EVE_ROUTE]`
- `lqLevel` computed via `lqStyleFromAvgLqi(avgLqi, 255)`:
  - `avgLqi >= 200` → `lqLevel: 3`
  - `avgLqi >= 128` → `lqLevel: 2`
  - `avgLqi < 128` → `lqLevel: 1`

**Source data (native):** `routes[]` with `quality` values (0–3 scale)

**Processing:**
- `linkCategories: [EDGE_CATEGORY_EVE_NATIVE_ROUTE]`
- `lqLevel` computed via `lqStyleFromAvgLqi(quality, 3)` (same thresholds as networkdiag)

### Edge Category and Filter Mapping

Link filter dropdown options declare `requiredEdgeCategories[]` — the option is shown only when the dataset contains edges with at least one matching category. This ensures link quality filters (High/Medium/Low) appear for any dataset type that provides link quality data:

| Filter Option | Required Edge Categories | Actual Filter Predicate |
|---|---|---|
| `lq_high` (High LQ3) | `DEFAULT_3`, `EVE_ROUTE`, `EVE_NATIVE_ROUTE`, `OTBR_ROUTE` | `edge.lqLevel === 3` |
| `lq_medium` (Medium LQ2) | `DEFAULT_2`, `EVE_ROUTE`, `EVE_NATIVE_ROUTE`, `OTBR_ROUTE` | `edge.lqLevel === 2` |
| `lq_low` (Low LQ1) | `DEFAULT_1`, `EVE_ROUTE`, `EVE_NATIVE_ROUTE`, `OTBR_ROUTE` | `edge.lqLevel === 1` |

The filter predicate tests `lqLevel` (not category), so it works uniformly across all dataset types. The category list only controls dropdown visibility.

---

## 5. Rendering Layer

### Topology renderer (`tdash-topology-renderer.js`)

```
renderTopologyForDataset(dataset, physicsEnabled)
    │
    ▼
Destroy previous vis.Network (memory cleanup)
    │
    ▼
runAdaptor(dataset) → { nodeData, edgeData, nodeMap, … }
    │
    ▼
_topologyNodeData = nodeData   (stored for filter validation)
    │
    ▼
computeTopologyCapabilities(nodeData, edgeData)
  → capabilities object (which fields are actually present)
    │
    ▼
updateFilterOptionVisibility(capabilities, 'topology')
  → show/hide dropdown <option> elements
    │
    ▼
new vis.DataSet(nodeData), new vis.DataSet(edgeData)
new vis.Network(container, { nodes, edges }, VIS_OPTIONS)
    │
    ▼
applyFilters(nodeMode, linkMode, diagMode)   ← called here + on every filter change
  1. Compute visibleNodeIds from node filter + diagnostic filter predicates
  2. Expand set: routers-with-children → add child node IDs via parent-child edges
  3. Router-neighbor diagnostic modes: add matched neighbor IDs + force-visible their edges
  4. nodesDataset.update({ id, hidden: !visible }) for each node
  5. edgesDataset.update({ id, hidden: !shouldShow }) for each edge
     shouldShow = endpointsVisible AND (edgeMatchesLinkFilter OR forcedVisible)
    │
    ▼
vis.Network click event → populateNodeDetailsLists()
  - reads rawByIdForDetails to populate all <ul data-fields="..."> panels
```

### Table renderer (`tdash-table-renderer.js`)

```
renderTableForDataset(dataset)
    │
    ▼
computeTableCapabilities(rows) → capabilities
    │
    ▼
updateFilterOptionVisibility(capabilities, 'table')
    │
    ▼
Discover columns: union of all top-level keys across all rows
Priority columns (TABLE_PRIORITY_COLUMNS) sorted first
    │
    ▼
Render <thead> (column headers) and <tbody> (rows)
    │
    ▼
applyTableFilters()   ← called here + on every filter change
  isRowVisibleByNodeFilter(row, nodeMode)
  isRowVisibleByDiagnosticFilter(row, diagMode)
  → toggle each <tr> display
    │
    ▼
Row click → populateNodeDetailsLists()
```

In **More Info** mode all discovered columns are shown; otherwise only priority columns are visible.

---

## 6. UI Event Wiring (`tdash-ui.js`)

`tdash-ui.js` is the single `<script type="module">` entry point loaded by `tdash.html`. It bootstraps the page and owns all DOM event wiring.

### Bootstrap sequence

```
populateDatasetSelect(initialSource)   ← from DATASET_REGISTRY
populateFilterSelects()                ← from NODE_FILTER_OPTIONS, LINK_FILTER_OPTIONS
populateDiagnosticFilterBySource(...)
applyLegendLineStylesFromConstants()   ← sync EDGE_LQ_STYLES → CSS variables
await loadStaticLabelMap()             ← fetch td-static-extaddr-device-label.json
status: "Select a dataset to load."
```

### Fetch flow (triggered by Fetch button or auto-fetch)

```
doFetchDataset()
    │
    ▼
loadDataset(selectedValue)             ← tdash-dataset.js
  (fetches files, merges rows, sets currentDataset)
    │
    ▼
renderCurrentView()
  effectiveDataset = _enhanceEnabled
    ? { ...currentDataset, rows: enrichRows(rows), rawFiles: enrichRawFiles(rawFiles) }
    : currentDataset
    │
    ├─ view === 'topology' ──▶ renderTopologyForDataset(effectiveDataset, physicsEnabled)
    └─ view === 'table'    ──▶ renderTableForDataset(effectiveDataset)
    │
    ▼
updateDeviceStatusBar(counts)
refreshDiagnosticFilterForCurrentSource()
```

### Control-to-action mapping

| Control | Event | Action |
|---|---|---|
| `#datasource-filter` | `change` | Re-populate dataset select; auto-fetch if enabled |
| `#dataset-select` | `change` | Auto-fetch if enabled; auto-switch view if `defaultView` set |
| `#btn-fetch` | `click` | `doFetchDataset()` |
| `#btn-topology` | `click` | `switchView('topology')` → re-render |
| `#btn-table` | `click` | `switchView('table')` → re-render |
| `#node-filter` | `change` | Topology: `applyFilters()`; Table: `applyTableFilters()` |
| `#link-filter` | `change` | Topology only: `applyFilters()` |
| `#diagnostic-source-filter` | `change` | Repopulate `#diagnostic-filter` options by capability; then `applyFilters()` |
| `#diagnostic-filter` | `change` | Topology: `applyFilters()`; Table: `applyTableFilters()` |
| `#chk-force-fresh` | `change` | Sets `_forceFresh = true` in tdash-dataset.js |
| `#chk-only-cache` | `change` | Sets `_onlyCache = true` in tdash-dataset.js |
| `#btn-physics` | `click` | `visNetwork.setOptions({ physics: { enabled } })` |
| `#btn-more-info` | `click` | `setMoreInfoEnabled()`; re-apply table filters |
| **Enhance** (inline) | `change` | Toggle `_enhanceEnabled`; re-render with enriched dataset copy |

---

## 7. Filter System in Depth

### Three independent filter dimensions

1. **Node / Device filter** — which node types are visible  
2. **Link filter** — which edge categories are drawn (topology only)  
3. **Diagnostic filter** — which nodes survive a health-metric threshold test  

All three are evaluated together in `applyFilters()`. A node is shown only when it passes **both** the node filter **and** the diagnostic filter. An edge is shown only when both its endpoints are visible **and** its `linkCategories` satisfy the link filter predicate.

### Node filter predicates

| Filter value | Topology: vis-node field test | Table: row field test |
|---|---|---|
| `all` | always true | always true |
| `border-routers` | `node.isBorderRouter === true` | `getColumnValue(row, 'br') === true` |
| `main-routers` | `node.isMainRouter === true` | `rloc16` ends in `'00'` |
| `routers-with-children` | `node.isRouter && node.hasChildren` | `total_children > 0` or `children.length > 0` |
| `routers-without-children` | `node.isRouter && !node.hasChildren` | inverse of above |
| `ftd` | `node.mode_device.toUpperCase() === 'FTD'` | `mode.device === 'FTD'` |
| `mtd` | `node.mode_device.toUpperCase() === 'MTD'` | `mode.device === 'MTD'` |

When `routers-with-children` is active, a second pass expands the visible set by following all parent-child edges that originate from a visible router — this ensures child nodes are always shown alongside their parent.

### Link filter predicates (`edgeMatchesLinkFilter`)

Link filters test `edge.linkCategories[]` against the following sets:

| Filter | Accepted edge categories |
|---|---|
| `all_links` | any |
| `default_links` | `default_children`, `default_1/2/3_links`, `otbr_child` |
| `default_plus_router_neighbors` | above + `router_neighbor` |
| `otbr_rest_api` | `otbr_route`, `otbr_child` |
| `eve_enhanced_routes_children` | `eve_route`, `eve_child` |
| `eve_native_routes_children` | `eve_native_route`, `eve_native_child` |
| `lq_high` | `edge.lqLevel === 3` |
| `lq_medium` | `edge.lqLevel === 2` |
| `lq_low` | `edge.lqLevel === 1` |
| `lq_parent_child` | `edge.isParentChild === true` |
| `lq_otbr_neighbor` | `otbr_route`, `otbr_child`, `router_neighbor` |
| `lq_none` | `!edge.lqLevel` (no LQ data) |

### Diagnostic filter predicates

Diagnostics are grouped by a **source** selector (`mac_counters`, `mle_counters`, `time_statistics`, `link_quality`, `other`) that gates the available diagnostic options in the second dropdown. The actual thresholds are tested against pre-computed summary fields on the node/row object:

| Diagnostic option | Field tested | Threshold |
|---|---|---|
| MAC total error % (medium) | `iftotalerrors_totalpkts_ratio` | ≥ 0.05 |
| MAC total error % (high) | `iftotalerrors_totalpkts_ratio` | ≥ 0.10 |
| MAC discard % (high) | `iftotaldiscards_totalpkts_ratio` | ≥ 0.15 |
| MLE partition changes (medium) | `partitionidchanges` | ≥ 2 |
| MLE partition changes (high) | `partitionidchanges` | ≥ 5 |
| MLE parent changes (medium) | `parentchanges` | ≥ 2 |
| MLE parent changes (high) | `parentchanges` | ≥ 5 |
| Neighbor frame error rate | `router_neighbor_max_err_rate_frame_pct` | ≥ 2 / 5 / 10 % |
| Neighbor message error rate | `router_neighbor_max_err_rate_msg_pct` | ≥ 2 / 5 / 10 % |
| Neighbor RSS bad | `router_neighbor_min_rss_ave` | < −80 dBm |
| LQ distribution skewed (poor) | `lq1_ratio` | ≥ 0.33 |
| LQ distribution good | `lq3_ratio` | ≥ 0.67 |

For the router-neighbor diagnostic modes (`lq_otbr_neighbor_*`) the topology filter applies an extra special-case pass: it expands `visibleNodeIds` to include neighbor target nodes matched by the sub-row predicate `routerNeighborRowMatchesDiagnosticFilter`, and force-shows the connecting `router_neighbor` edges regardless of the link filter.

### Capability-driven filter option visibility

After each render, `computeTopologyCapabilities()` (topology) or `computeTableCapabilities()` (table) scans all loaded node/row data and produces a `capabilities` object (`hasFtdNodes`, `hasNeighborFrameErrRate`, etc.). `updateFilterOptionVisibility(capabilities, view)` then shows or hides individual `<option>` elements in the filter dropdowns based on what is actually present in the dataset. Options with `alwaysShow: true` are never hidden.

This means the diagnostic filter dropdown automatically contracts to only the options that have data, and expands again when a richer dataset is loaded.

---

## 8. Dataset Registry and Constants

### `DATASET_REGISTRY` (`tdash-dataset-registry.js`)

Each entry is a plain object:

```js
{
  source:            "otbr-cli",           // drives the #datasource-filter grouping
  value:             "merged_otbr_cli_all", // <option value>
  label:             "otbr-cli-*, network-poll",
  files:             ["td-otbr-cli-meshdiag-topology.json", ...],
  mergeStrategy:     "by-identity",
  topologyMode:      "meshdiag-networkdiag",
  defaultView:       "topology",
  defaultLinkFilter: "all_links"
}
```

### `tdash-constants.js`

Single source of truth for:
- `MERGE_STRATEGIES` — string constants for the three merge modes  
- `LINK_FILTER_*` constants — string tokens matched in `edgeMatchesLinkFilter`  
- `EDGE_CATEGORY_*` constants — string tokens stamped onto edges by adaptors  
- `PALETTE` / `NODE_COLORS` / `EDGE_LQ_STYLES` — all colors and widths; CSS variables are synced from `EDGE_LQ_STYLES` at startup  
- `NODE_FILTER_OPTIONS`, `LINK_FILTER_OPTIONS`, `DIAGNOSTIC_FILTER_OPTIONS` — option metadata arrays that drive both dropdown population and capability checking  
- `TABLE_PRIORITY_COLUMNS` — ordered list of column names shown in default (non-More Info) table view  
- `VIS_OPTIONS` — vis-network physics, layout, and interaction settings  

---

## 9. End-to-End Data Flow Summary

```
User selects dataset and clicks Fetch
        │
        ▼
doFetchDataset() [tdash-ui.js]
        │
        ▼
loadDataset(value) [tdash-dataset.js]
  ├── fetch /api/data/<file> per entry.files[]
  │     └── server: check freshness → run td_cli.py if stale → return JSON
  │     └── HTTP 202: poll /api/job/{id} until "done"
  │
  ├── normalizeRows() per loaded file group [tdash-merge.js]
  ├── mergeRowsByIdentity() / mergeRowsByRloc16() / pass-through [tdash-merge.js]
  └── currentDataset = { entry, rows, rawFiles }
        │
        ▼
renderCurrentView() [tdash-ui.js]
  (optional: enrichRows() injects device_label from staticExtaddrLabelMap)
        │
        ├── topology view:
        │     runAdaptor(dataset) [tdash-adaptors.js]
        │       → nodeData[], edgeData[]
        │     new vis.Network() [tdash-topology-renderer.js]
        │     applyFilters(nodeMode, linkMode, diagMode)
        │       isNodeVisibleByFilter()        [tdash-filters.js]
        │       isNodeVisibleByDiagnosticFilter() [tdash-filters.js]
        │       edgeMatchesLinkFilter()         [tdash-filters.js]
        │       → nodesDataset.update({ hidden })
        │       → edgesDataset.update({ hidden })
        │
        └── table view:
              discover columns from rows
              render <thead> + <tbody> [tdash-table-renderer.js]
              applyTableFilters()
                isRowVisibleByNodeFilter()        [tdash-filters.js]
                isRowVisibleByDiagnosticFilter()  [tdash-filters.js]
                → toggle <tr> display

Filter dropdown change [tdash-ui.js]
  → topology: handlers.applyFilters() (in-place DataSet updates, no re-fetch)
  → table:    applyTableFilters()     (in-place <tr> show/hide, no re-fetch)
```

Filter changes never re-fetch data or re-run the adaptor. They update the existing `vis.DataSet` objects or toggle table row visibility directly — making all filter interactions instant regardless of dataset size.
