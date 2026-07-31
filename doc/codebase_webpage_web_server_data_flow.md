doc/codebase_webpage_web_server_data_flow.md# Design: Webpage, Web Server, and Data Flow

_Covers `td_webserver.py`, `tdash.html`, and all `js/*.js` modules._

---

## 1. Layered Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser                                                            │
│                                                                     │
│  ┌──────────────────────┐   ┌─────────────────────────────────────┐ │
│  │  tdash.html (DOM)    │   │  JavaScript ES Modules              │ │
│  │  - control bars      │   │                                     │ │
│  │  - filter dropdowns  │   │  tdash-ui.js         (event wiring) │ │
│  │  - topology canvas   │   │  tdash-dataset.js    (fetch+merge)  │ │
│  │  - sortable table    │   │  tdash-merge.js      (row merge)    │ │
│  │  - details panels    │   │  tdash-adaptors.js   (→vis format)  │ │
│  └──────────────────────┘   │  tdash-filters.js    (predicates)   │ │
│                             │  tdash-topology-renderer.js         │ │
│                             │  tdash-table-renderer.js            │ │
│                             │  tdash-topology-utils.js            │ │
│                             │  tdash-utils.js                     │ │
│                             │  tdash-constants.js  (string consts)│ │
│                             │  tdash-dataset-registry.js          │ │
│                             └─────────────────────────────────────┘ │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ HTTP (fetch API)
                        /api/data/{filename}
                        /api/job/{job_id}
                        DELETE /api/job/{job_id}
                        GET/PATCH /api/device/{extAddress}
                        /tdash.html, /js/*, /tdash.css
┌──────────────────────────────────┴──────────────────────────────────┐
│  td_webserver.py  (aiohttp)                                         │
│                                                                     │
│  ┌──────────────────┐  ┌─────────────────────────────────────────┐  │
│  │ Static serving   │  │  /api/data/{filename}                   │  │
│  │ src/ tree        │  │  - FILE_ACTION_MAP lookup               │  │
│  │ (no-cache        │  │  - freshness check (mtime, max_age)     │  │
│  │ revalidation)    │  │  - short-cost: sync subprocess 200      │  │
│  └──────────────────┘  │  - long-cost / force_async: 202 + job   │  │
│                        └─────────────────────────────────────────┘  │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ subprocess
                            python3 -m td_cli {command} + data collectors
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
| `DELETE /api/job/{job_id}` | `handle_job_cancel_api` | Request cancellation of a running long-cost job |
| `GET /api/device/{extAddress}` | `handle_device_get_api` | Read one authoritative static device label |
| `PATCH /api/device/{extAddress}` | `handle_device_patch_api` | Atomically update or insert one static device label |
| `GET /**` | static file server | All other paths served from `src/` directory |

### Device-label resource

`GET /api/device/{extAddress}` reads
`td-static-extaddr-device-label.json` directly from `app["td_data_dir"]` and
returns `200` with `{ "extAddress", "deviceLabel" }`. A missing map or unknown
address returns `404`.

`PATCH /api/device/{extAddress}` accepts exactly:

```json
{"deviceLabel": "Office Sensor"}
```

The handler validates the request, acquires the existing `merge-extaddr`
source lock, and invokes:

```text
td_cli --datadir DATA_DIR merge-extaddr --update-extaddr EXTADDR --device-label LABEL
```

It reads the persisted value back before responding. Updating an existing
record returns `200`; inserting a missing record returns `201`. Device API
responses use `Cache-Control: no-store`.

| Condition | Status |
|---|---|
| Invalid extAddress, body shape, or label | `400 Bad Request` |
| Missing map or unknown extAddress on GET | `404 Not Found` |
| CLI failure or timeout | `502 Bad Gateway` |
| Persisted value cannot be read back or map is invalid | `500 Internal Server Error` |

PATCH requests in one server process are serialized with other
`merge-extaddr` work. Atomic replacement prevents partial JSON. A writer in a
different process is not coordinated by this lock, so concurrent external
writes remain last-write-wins.

### Phase 1 contract: cancellation state model

Phase 1 establishes a shared status model used by both browser polling and
server responses.  The model defines five states:

- `running`
- `cancelling`
- `cancelled`
- `done`
- `error`

Terminal states are `cancelled`, `done`, and `error`.
The only cancellable state is `running`.

For browser behavior, Phase 1 also codifies two decisions:

- Cancel scope: cancel all in-flight jobs for the active fetch session.
- Partial-result policy: when partial data is available, commit the partial view
  and show a cancellation warning in the fetch status line.

Phase 1 does not yet introduce subprocess kill mechanics; those are implemented
in later phases on top of this contract.

### Cancel endpoint contract (`DELETE /api/job/{job_id}`)

The cancellation endpoint semantics are:

- Unknown `job_id` → `404 Not Found`
- Job already terminal (`done`, `error`, `cancelled`) → `409 Conflict`
- Job currently `running` → `202 Accepted` and transition to `cancelling`

After `202`, the server cancels the background task and terminates the tracked
`td_cli` subprocess (graceful terminate with force-kill fallback), then polling
transitions to `cancelled`.

Static assets (`tdash.html`, `tdash.css`, `js/*.js`) get `Cache-Control: no-cache` so browsers revalidate via ETag / If-Modified-Since but never serve stale bytes without checking the server.

### `FILE_ACTION_MAP` — the filename→action registry

Every data file the browser can request is listed in `FILE_ACTION_MAP` as a `FileAction` dataclass:

```python
@dataclasses.dataclass
class FileAction:
    max_age_s: int          # seconds until the cached file is considered stale
    action: str | list[str] # "STATIC" or td_cli command args
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

  ### Cancellation flow for polled jobs

  ```
  click #btn-fetch-cancel
      │
      ▼
  cancelActiveFetchSession() [tdash-dataset.js]
    - marks current session cancelRequested
    - aborts local fetch/poll waits
    - sends DELETE /api/job/{id} for all tracked active jobs
      │
      ▼
  handle_job_cancel_api() [td_webserver.py]
    - running -> cancelling
    - cancels runtime task
    - cancellation path terminates td_cli subprocess
      │
      ▼
  poll /api/job/{id}
    cancelling -> cancelled
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
| `currentDataset` | Exported live binding; holds final or partial dataset state (`isPartial` flag) and fetch metrics |
| `staticExtaddrLabelMap` | `Map<lowercase-extaddr, device_label>` pre-loaded at startup |
| `setStaticDeviceLabel(extaddr, label)` | Updates one authoritative in-memory label after PATCH succeeds |
| `fileMaxAgeCache` | `Map<filename, { maxAge, fetchedAt, lastModifiedAt }>` — per-file cache |
| `_forceFresh` / `_onlyCache` | Toggle flags set by the Force Refresh / Only Cache checkboxes |
| `_activeFetchSession` | Current fetch session state: `id`, `cancelRequested`, `AbortController`, and tracked active `job_id`s |

### `loadDataset(entryValue)` walkthrough (progressive)

```
Looks up DATASET_REGISTRY entry by value
    │
    ▼
Evaluate progressive rollout gate
  progressiveEnabled =
    feature flag enabled (URL/localStorage) AND
    dataset includes rollout-approved long files
    │
    ▼
Start concurrent per-file fetches (Promise.allSettled)
  Each file fetch:
    - sends per-file cache header (force-fresh / only-cache / remembered max-age)
    - if 202: enters pollJobUntilDone()
      - polls /api/job/{job_id}
      - when checkpoint metadata is fresher, fetches checkpoint file and emits onCheckpointData
      - enforces monotonic freshness and redraw cadence guards
    - on checkpoint or final file data:
      - updates rawFilesInProgress[fileIdx]
      - rebuilds partial dataset via _buildPartialDataset(...)
      - sets currentDataset.isPartial = true
      - notifies UI via onFileReady callback
    │
    ▼
After all files settle:
  - build final rows with merge strategy
  - set currentDataset.isPartial = false
  - attach fetchMetrics
```

### Normalisation and merge (`tdash-merge.js`)

`normalizeRows(rawData, sourceName)` converts any JSON shape (array, object, scalar) into a flat array of plain objects. Every row is stamped with `_source_files: [sourceName]`.

`mergeRowsByIdentity` uses three identity keys in priority order:
1. `rloc16:<hex>` — canonical RLOC16
2. `extAddress:<hex>` — canonical extended address (resolves aliases: `extAddress`, `extaddr`, `Extended MAC`)
3. `omrIpv6Address:<addr>` — OMR IPv6 address

When two rows share any key, they are merged: the first non-empty value wins; conflicts are recorded in `_merge_conflicts`; `_source_files` arrays are unioned.

### Field alias system (`FIELD_ALIASES` registry)

Different data sources use inconsistent field naming conventions—OTBR CLI uses snake_case (`err_rate_frame_pct`, `rss_ave`) while OTBR REST API uses camelCase (`frameErrorRate`, `averageRssi`). To unify these, the application maintains a centralized `FIELD_ALIASES` registry in `tdash-constants.js` that maps canonical snake_case field names to arrays of known aliases.

**Normalization flow:**

1. `normalizeFieldNames(row)` (in `tdash-utils.js`) walks the `FIELD_ALIASES` registry and adds canonical snake_case field names alongside any matching camelCase aliases found in the row. The original field names are preserved, so both `frameErrorRate` and `err_rate_frame_pct` exist in the normalized row.

2. `normalizeNestedArrayFields(arr)` extends this to nested arrays (`router_neighbor_table[]`, `router_child_table[]`) commonly found in OTBR REST API mesh diagnostics. It applies field normalization to each array element and converts decimal error rates (0–1 range) to percentages (0–100 range) for fields ending in `_pct`.

3. The normalization happens in `adaptOtbrRestApi()` for REST API data sources, ensuring that by the time data reaches the filter system (`tdash-filters.js`), all diagnostic fields use the canonical snake_case names that filter predicates expect.

**Example:** OTBR REST API returns `{ frameErrorRate: 0.05, averageRssi: -65 }` in a neighbor entry. After normalization, the row contains both the original fields plus `{ err_rate_frame_pct: 5, rss_ave: -65 }`, allowing filter predicates like `row.err_rate_frame_pct >= 2` to work correctly regardless of the data source.

### Static label enrichment

`enrichRows(rows)` / `enrichRawFiles(rawFiles)` are called by `renderCurrentView()` when the **Enhance** toggle is on. They walk every node/row, look up `staticExtaddrLabelMap` by canonical extaddr, and inject the authoritative `deviceLabel` on a spread copy — the originals in `currentDataset` are never mutated. A static mapping overrides stale raw label fields for that extAddress.

---

## 4. Adaptation Layer (`tdash-adaptors.js`, `tdash-topology-utils.js`)

### Dispatch

`runAdaptor(dataset)` selects the adaptor function from `dataset.entry.topologyMode`:

| topologyMode | Adaptor | Input |
|---|---|---|
| `meshdiag-networkdiag` | `adaptMeshdiagNetworkdiag` | meshdiag + networkdiag (with routeData links) + neighbor/child tables |
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

**Source data:** `route.routeData[]` arrays with `linkQualityIn` and `linkQualityOut` numeric values (0–3 scale)

**Processing:** Each route entry creates an edge with:
- `linkCategories: [EDGE_CATEGORY_OTBR_ROUTE]`
- `lqLevel: 0–3` computed by `lqStyleFromAvgLqi(max(lqi_in, lqi_out), 3)` — takes the conservative (max) value
  - `avgLqi >= 3` → `lqLevel: 3` (high)
  - `avgLqi >= 2` → `lqLevel: 2` (medium)
  - `avgLqi < 2` → `lqLevel: 1` (low)
- Visual style from `EDGE_LQ_STYLES` based on computed level

**Example:** A route with `"linkQualityIn": 3, "linkQualityOut": 2` computes `max(3, 2) = 3` → `lqLevel: 3`, edge category `EDGE_CATEGORY_OTBR_ROUTE`.

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
vis.Network click event → publishDeviceSelection() + populateNodeDetailsLists()
  - publishes the selected merged record through `tdash:device-selected`
  - reads rawByIdForDetails and populates detail sections using runtime
    data-fields bindings from DEVICE_DETAILS_SECTIONS
```

### Device details and diagnostic insights

Both topology-node clicks and table-row clicks publish the selected record via
`tdash:device-selected`. `tdash-ui.js` uses the event to update Device Settings
and the Device Insights tab, including when Insights is not the active tab.

Insights evaluates the selected record with
`evaluateDiagnosticsForRecord(record, view)`. It is informational and does not
change any filter state. Evaluations are grouped by diagnostic source (MAC
Counters, MLE Counters, Time Statistics, and Link Quality) and show the
observed value plus the structured threshold when that view supplies a metric.
For topology boolean summaries without a numeric measurement, an insight is
shown only when the condition is triggered. The tab has explicit no-selection
and no-available-metrics states.

When several triggered options describe tiers of the same source/group metric,
Insights shows only the highest-severity qualifying tier. For example, a 9.3%
MAC discard ratio renders the high `>= 8%` condition and omits the redundant
medium `>= 2%` condition. Non-triggered observed tiers remain visible as
context only while the **Advanced** control is active. With Advanced inactive,
Insights shows only matching conditions.

`DIAGNOSTIC_FILTER_OPTIONS` is the shared source of diagnostic labels, fields,
severity, threshold, comparison, and unit metadata. This keeps dropdown
matching and selected-device insight evaluation aligned without parsing the
display label text.

#### Physics profile behavior (current)

- Profile-specific seeded layout dispatch happens before `vis.Network(...)` construction.
- `mesh-ring` runs `applyRingStarSeedLayout(...)`.
- `mesh-compact` runs `applyMeshLabHybridSeedLayout(...)`.
- `mesh-tree-horizontal` runs `applyMeshTreeHorizontalSeedLayout(...)`.
- `mesh-tree-vertical` runs `applyMeshTreeVerticalSeedLayout(...)`.

Mesh-tree profiles are currently manual-select only (not auto-mapped by `topologyMode`) and use shared five-zone classification precedence:

1. Zone 1 border routers
2. Zone 2 routers
3. Zone 3 FTD child nodes
4. Zone 4 non-FTD child nodes with parent-child links
5. Zone 5 non-FTD child nodes without parent-child links

Operational note: in dense merged datasets, route-only FTD non-router nodes can still behave as outliers in mesh-tree layouts; this is tracked as a known refinement area in layout documentation.

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
loadDataset(selectedValue, { onFileReady })  ← tdash-dataset.js
  (fetches files, emits progressive partial updates, then final dataset)
    │
    ▼
onFileReady() in UI
  - coalesced via setTimeout(0) debounce
  - renderCurrentView() on partial dataset
  - status line: "⚠ Partial result: N of M files ready — still loading…"
    │
    ▼
final reconciliation renderCurrentView()
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
  console.info("[tdash] fetch metrics", ...)
```

### Selected-device settings flow

Topology clicks, table row clicks, and automatic single-search-result
selection publish `tdash:device-selected`. `tdash-ui.js` owns the selected
record and projects `rloc16`, extAddress aliases, `deviceLabel` aliases, and
non-empty `name` into `#device-settings-panel`. Clearing, filtering out, or
selecting a record without a valid extAddress clears and disables the form.

When Settings opens for a valid selection:

```text
selected record
  │
  ▼
GET /api/device/{extAddress}
  ├─ 200: input uses authoritative static-map label
  └─ 404: input uses selected record label, or blank (Save will insert)
  │
  ▼
operator edits
  ├─ Cancel/Escape: restore last loaded value without a request
  └─ Save/Enter: PATCH { deviceLabel }
            │
            ▼
        setStaticDeviceLabel()
            │
            ▼
        renderCurrentView()
```

Selection/request version checks discard late GET or PATCH responses after the
user selects another device. The input and actions are disabled while pending;
failed saves keep the unsaved edit and announce a safe inline error. HTTP `201`
is displayed as an added label and `200` as a saved label.

### Fetch cancel flow (triggered by Cancel button)

```
click #btn-fetch-cancel
    │
    ▼
cancelActiveFetchSession()             ← tdash-dataset.js
  - abort local waits (AbortController)
  - DELETE /api/job/{id} for active session jobs
    │
    ▼
doFetchDataset() catch branch          ← tdash-ui.js
  - detect FetchCancelledError
  - if partial dataset is available: commit rendered partial view
  - set status line: "⚠ Cancelled — partial result: N of M files loaded"
  - pin this status for a short interval so renderer "Loaded:" updates cannot overwrite it
  - if no partial dataset is available: show "Fetch cancelled for <dataset>"
```

### Control-to-action mapping

| Control | Event | Action |
|---|---|---|
| `#datasource-filter` | `change` | Re-populate dataset select; auto-fetch if enabled |
| `#dataset-select` | `change` | Auto-fetch if enabled; auto-switch view if `defaultView` set |
| `#btn-fetch` | `click` | `doFetchDataset()` |
| `#btn-fetch-cancel` | `click` | `cancelActiveFetchSession()` for current fetch session |
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
  label:             "otbr-cli-*, networkdiag-fetch-all",
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
loadDataset(value, { onFileReady }) [tdash-dataset.js]
  ├── fetch /api/data/<file> per entry.files[]
  │     └── server: check freshness → run python3 -m td_cli {command} if stale → return JSON
  │     └── HTTP 202: poll /api/job/{id} until terminal status
  │           └── poll metadata may advertise fresher checkpoint file
  │           └── client fetches checkpoint via /api/data/<checkpoint_filename>
  │           └── client renders checkpoint-backed partial dataset while polling continues
  │
  ├── progressive partial path:
  │     currentDataset = { ..., isPartial: true }
  │     onFileReady() → debounced incremental render
  │
  ├── final path after all files settle:
  │     normalizeRows() per loaded file group [tdash-merge.js]
  │     mergeRowsByIdentity() / mergeRowsByRloc16() / pass-through [tdash-merge.js]
  │     currentDataset = { ..., isPartial: false, fetchMetrics }
  │
  └── final reconciliation render
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

---

## 10. Cancellation Failure and Race Outcomes

Implemented edge-case behavior:

- `cancel-after-done`: `DELETE /api/job/{id}` returns `409` with terminal status.
- Unknown job id: `DELETE /api/job/{id}` returns `404`.
- Concurrent complete vs cancel:
  - cancel-first: `running -> cancelling -> cancelled`
  - complete-first: terminal (`done`/`error`) and cancel returns `409`
- Cancel while queued on source lock: task is cancelled before subprocess start and transitions to `cancelled`.
- Cancel while subprocess is running: task cancellation path in `run_td_cli` terminates subprocess (terminate, then kill fallback).

UI-level outcomes during cancellation with progressive fetch enabled:

- If at least one file/checkpoint has rendered, cancellation commits the partial view and surfaces a warning in the fetch status line.
- The cancelled-partial warning is briefly pinned so view renderers cannot immediately replace it with "Loaded: ...".
- If no partial data has rendered yet, the status line shows a plain cancellation message and the current view is preserved or cleared by existing fallback rules.

---

## 11. Rollout and Observability Additions

Major improvements introduced by the progressive-fetch plan:

- Independent dataset file rendering:
  - each file can render as soon as it resolves, without waiting for all files.
- Checkpoint partial rendering:
  - long-running jobs expose checkpoint metadata from `/api/job/{job_id}`;
  - clients fetch checkpoint files from `/api/data/{checkpoint_filename}` and render incremental updates.
- Final reconciliation render:
  - once all files settle, the UI performs one canonical final render (`isPartial = false`).
- Feature-flagged rollout:
  - progressive mode is default-off and enabled via query/local storage flag;
  - additionally constrained to datasets containing approved long-running file set.
- Built-in observability:
  - metrics tracked and logged for `timeToFirstRenderMs`, `checkpointUpdateCount`, `completedFileUpdateCount`, and `timeToFinalRenderMs`.
  - latest metrics are exposed at `window.tdashDebug.lastFetchMetrics` for browser-side validation.
