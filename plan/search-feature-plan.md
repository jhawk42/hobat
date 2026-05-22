# Plan: Browser-Side Search for Thread Device Dataset Rows

**Status:** Draft — awaiting review before implementation

---

## Overview

Add a search feature to the tdash dashboard that allows users to search across the in-browser loaded dataset of thread device rows. Search results are highlighted in both the topology view and table view. All matching is done entirely client-side against the already-loaded `currentDataset.rows` array — no new server calls.

---

## Background: Key Codebase Observations

### Dataset loading and processing pipeline (Layer 6 – Browser Dashboard)

1. **`tdash-dataset-registry.js`** — defines every selectable dataset (`DATASET_REGISTRY[]`), each with: files to fetch, merge strategy, topology mode, default view.
2. **`tdash-dataset.js` – `loadDataset(entryValue)`** — fetches dataset JSON files, normalizes them via `normalizeDatasetPayload()`, runs the merge strategy (`mergeRowsByRloc16` / `mergeRowsByIdentity` / none via `normalizeRows()`), and writes the result to `currentDataset.rows` (flat array of row objects) plus `currentDataset.rawFiles`.
3. **`tdash-merge.js`** — merges rows from multiple source files into one flat array. Each row is a plain JS object keyed by field names from the underlying JSON.
4. **`tdash-constants.js` – `TABLE_PRIORITY_COLUMNS`** — the ordered list of highest-priority fields for the table view: `rloc16`, `extaddr`, `device_label`, `name`, `room`, `ID`, `Extended MAC`, `type`, `br`, `ver`, `thread_version`, `total_children`, `total_links`, `mode.device`, `omr_ipv6_addr`, etc. These are the natural search targets.
5. **`tdash-table-renderer.js` – `renderTableForDataset()` / `applyTableFilters()`** — renders the table. `applyTableFilters()` is the choke-point already used for node-filter and diagnostic-filter; it calls `renderTableRows(filtered, activeColumns)`. Search filtering fits cleanly here.
6. **`tdash-topology-renderer.js` – `renderTopologyForDataset()`** — builds a vis-network graph from the dataset. Existing filter handlers (`applyFilters()`, `isNodeVisibleByFilter()`) control node/edge visibility.
7. **`tdash-filters.js`** — houses all filter predicates (`isRowVisibleByNodeFilter`, `isRowVisibleByDiagnosticFilter`). New `isRowMatchingSearch()` predicate can be added here.
8. **`tdash-ui.js`** — wires all controls to data/render functions. New "Find" button and search input event listeners go here.
9. **`tdash.html`** — single-page HTML. The **Filters panel** (`#panel-node-link-filters`) is where the search UI elements will be added.

### Priority fields for search
Search will match against the `TABLE_PRIORITY_COLUMNS` subset: `rloc16`, `extaddr`, `device_label`, `name`, `room`, `ID`, `Extended MAC`, `type`, `br`, `ver`, `thread_version`, `thread_stack_version`, `mode.device`, `omr_ipv6_addr`, `scope`, `status`. These cover all the human-meaningful identity and role fields.

---

## Structured Implementation Phases

### Phase 1 — Search Logic Module (`tdash-search.js`)

**Goal:** Pure data logic, no DOM dependencies. Isolated and independently testable.

**Work items:**

1. Create `src/js/tdash-search.js`.
2. Implement `parseSearchQuery(queryText)` — normalizes input (trim, lowercase). For now: single string matching. Future: support `field:value` syntax.
3. Implement `rowMatchesSearch(row, query)` — iterates over search target fields (the `TABLE_PRIORITY_COLUMNS` priority subset), stringifies each value via the existing `toText()` / `getColumnValue()` helpers, and checks if any field value contains the query string (case-insensitive). Uses dot-path lookup for nested fields like `mode.device`.
4. Implement `filterRowsBySearch(rows, query)` — returns `{ matchingRows, matchingIndices }`. When query is empty/blank, returns all rows (no filtering).
5. Export a `SEARCH_TARGET_FIELDS` constant listing the exact fields to search (drawn from `TABLE_PRIORITY_COLUMNS`).

**Dependencies:** `tdash-utils.js` (`toText`, `getColumnValue`, `isPlainObject`), `tdash-constants.js` (`TABLE_PRIORITY_COLUMNS`).

---

### Phase 2 — HTML: Add Search UI to Filters Panel

**Goal:** Non-breaking addition of search controls inside the existing `#panel-node-link-filters` block in `tdash.html`.

**Work items:**

1. Add a `<div class="control-pair control-pair-search">` block inside `#filters-content .controls`, after the existing Diagnostics filter row.
2. Inside it:
   - `<label for="search-input">Search</label>`
   - `<input type="text" id="search-input" placeholder="e.g. device_label, rloc16, extaddr…" />`
   - `<button id="btn-search-find">Find</button>`
   - `<button id="btn-search-clear">✕</button>` (clears the input and resets search state)
3. Add a `<div id="search-status">` span below the input for showing match count (e.g., "3 of 12 rows match").

---

### Phase 3 — Table View Integration

**Goal:** Apply search filter to table rows, highlight matches.

**Work items:**

1. In `tdash-table-renderer.js`, import `filterRowsBySearch` from `tdash-search.js`.
2. Extend `applyTableFilters()` to read the current search query (via a new exported accessor `getSearchQuery()` from `tdash-ui.js` or a module-level store in `tdash-search.js`) and pass it through `filterRowsBySearch()` after the existing node/diagnostic filters.
3. In `renderTableRows()`, add a CSS class `search-match` to `<tr>` elements whose row index is in `matchingIndices`. Update `tdash.css` to style `.search-match` with a subtle highlight (e.g., yellow/amber left border or background tint).
4. Update `updateTableStatus()` to include search match count in the status line.

---

### Phase 4 — Topology View Integration

**Goal:** Visually distinguish nodes that match the search from those that don't, without hiding non-matching nodes.

**Work items:**

1. In `tdash-topology-renderer.js`, import `filterRowsBySearch`.
2. After vis-network renders, compute matched node IDs by running `filterRowsBySearch` over the topology node data (using `_topologyNodeData` which stores the vis-node objects with their source row fields).
3. Two display options (choose one after review):
   - **Option A – Highlight-only:** For matching nodes, apply a distinct border color (e.g., amber/orange) and increased border width via `_visNetwork.body.data.nodes.update(...)`. Non-matching nodes are visually dimmed (reduced opacity via color alpha). Reset to normal when search is cleared.
   - **Option B – Select + Focus:** Programmatically call `_visNetwork.selectNodes(matchingNodeIds)` and optionally `_visNetwork.fit({ nodes: matchingNodeIds })` to zoom to matches. Less invasive to the existing color scheme.
   - **Recommended:** Option A for richer visual feedback; Option B as fallback.
4. Wire search result application to the existing `applyFilters()` pipeline in the topology filter handlers so search + existing node/link/diagnostic filters compose correctly.

---

### Phase 5 — UI Event Wiring (`tdash-ui.js`)

**Goal:** Connect the new HTML controls to the search and render logic.

**Work items:**

1. Import `filterRowsBySearch`, `parseSearchQuery` from `tdash-search.js`.
2. Add module-level `let _currentSearchQuery = ""` state.
3. Wire `#btn-search-find` click → `_currentSearchQuery = parseSearchQuery(input.value); applySearch()`.
4. Wire `#search-input` keydown (Enter) → same as Find button.
5. Wire `#btn-search-clear` click → clear input, reset `_currentSearchQuery = ""`, call `applySearch()`.
6. Implement `applySearch()`:
   - If `currentView === "table"`: call `applyTableFilters()` (which now reads the search query).
   - If `currentView === "topology"`: call the topology highlight function from Phase 4.
   - Update `#search-status` with match count.
7. Reset `_currentSearchQuery` when a new dataset is loaded (in the `doFetchDataset()` flow).
8. Export `getSearchQuery()` for use by the table renderer.

---

### Phase 6 — CSS Styling (`tdash.css`)

**Goal:** Style the new search UI elements consistently with the existing design system.

**Work items:**

1. Add `.control-pair-search` layout styles (flex row, gap, consistent with `.control-pair-source`).
2. Style `#search-input` to match existing `<select>` and `<input>` elements.
3. Style `#btn-search-find` and `#btn-search-clear` consistent with existing `<button>` styles.
4. Add `#search-status` text style (small, muted, inline).
5. Add `.search-match` row highlight for table (amber left border or background tint).
6. Add topology node highlight class / inline style override for matched nodes (amber/orange border).

---

## High-Level Future Work TODOs (Server-Side Search Expansion)

The following are known extension points for when search needs to go beyond the in-browser loaded dataset:

| ID | Future Work Item | Notes |
|----|-----------------|-------|
| FW-1 | **Server-side full-text search endpoint** | Add a new `/api/search?q=<query>&dataset=<value>` route to `td_webserver.py` that runs the search against the on-disk JSON files, supporting queries over data not yet loaded in the browser. |
| FW-2 | **Cross-dataset search** | Allow search to span multiple datasets simultaneously by having the server merge results from multiple JSON files. Requires `dataset_merge.py` to expose a search-capable API. |
| FW-3 | **Structured `field:value` query syntax** | Extend `parseSearchQuery()` to support expressions like `rloc16:0x0c00` or `br:true`, and pass the structured query to the server endpoint. |
| FW-4 | **Search result export** | Allow exporting matched rows to CSV or JSON from both client and server paths. |
| FW-5 | **Persistent search history** | Store recent queries in `localStorage` and offer a dropdown history in the search input. |
| FW-6 | **Search across all loaded dataset files (not just merged rows)** | Currently the merged `rows` array is searched; future work could also search within nested structures like `router_neighbor_table[]` or `children[]`. |
| FW-7 | **Regex / wildcard search** | Optionally support `rloc16:0x0[cd]*` style regex queries. |

---

## File Change Summary

| File | Change Type | Description |
|------|------------|-------------|
| `src/js/tdash-search.js` | **New** | Search logic module (query parsing, row matching, filtering) |
| `src/tdash.html` | **Edit** | Add search input, Find button, Clear button, status span to Filters panel |
| `src/js/tdash-filters.js` | **Edit** | (Optional) Add `isRowMatchingSearch()` predicate or delegate to `tdash-search.js` |
| `src/js/tdash-table-renderer.js` | **Edit** | Apply search filter in `applyTableFilters()`; apply `.search-match` CSS class to matching rows |
| `src/js/tdash-topology-renderer.js` | **Edit** | Apply node highlight for matching topology nodes |
| `src/js/tdash-ui.js` | **Edit** | Wire Find/Clear buttons and Enter key; manage `_currentSearchQuery` state; export `getSearchQuery()` |
| `src/tdash.css` | **Edit** | Add search UI styles and `.search-match` highlight |

---

## Open Questions for Review

1. **Topology highlight strategy:** Option A (color highlight + dim non-matches) vs. Option B (vis-network `selectNodes` + fit)? Or a hybrid?
2. **Search scope:** Should search only target `TABLE_PRIORITY_COLUMNS`, or should it also scan all other row fields when the "Advanced" (More Info) toggle is on?
3. **Placement:** Should the search controls go inside the existing Filters panel (`#panel-node-link-filters`) or as a standalone panel between Dataset and Filters?
4. **Auto-search on typing:** Should search fire on each keystroke (with debounce) rather than requiring a button click?
