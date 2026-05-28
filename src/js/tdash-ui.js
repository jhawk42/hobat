// Prevent browser from restoring scroll position on reload
if ('scrollRestoration' in history) {
  history.scrollRestoration = 'manual';
}

import { DATASET_REGISTRY } from "./tdash-dataset-registry.js";
import {
  currentDataset,
  loadDataset,
  loadStaticLabelMap,
  enrichRows,
  enrichRawFiles,
  setForceFresh,
  setOnlyCache,
} from "./tdash-dataset.js";
import {
  renderTopologyForDataset,
  getVisNetwork,
  getTopologyFilterHandlers,
  getTopologyNodeData,
  getTopologyDatasetCounts,
  setAutoZoomEnabled,
  setAnimationEnabled,
  isAutoZoomEnabled,
  isAnimationEnabled,
} from "./tdash-topology-renderer.js";
import {
  renderTableForDataset,
  applyTableFilters,
  setMoreInfoEnabled,
  isMoreInfoEnabled,
} from "./tdash-table-renderer.js";
import { EDGE_LQ_STYLES } from "./tdash-constants.js";
import { initDetailPanelToggles, formatAgo, formatDuration, toFiniteNumber } from "./tdash-utils.js";
import {
  populateFilterSelects,
  populateDiagnosticFilterBySource,
  populateDiagnosticFilterBySourceWithCapabilities,
} from "./tdash-filters.js";
import { parseSearchQuery, filterRowsBySearch } from "./tdash-search.js";

// ── Section 2: Build dataset <select> ────────────────────────────────────────

function populateDatasetSelect(sourceFilter = null) {
  const sel = document.getElementById("dataset-select");
  sel.innerHTML = ""; // Clear existing options

  const filteredRegistry = sourceFilter
    ? DATASET_REGISTRY.filter((entry) => entry.source === sourceFilter)
    : DATASET_REGISTRY;

  filteredRegistry.forEach((entry) => {
    const opt = document.createElement("option");
    opt.value = entry.value;
    opt.textContent = entry.label;
    sel.appendChild(opt);
  });
}

// ── Render dispatcher ────────────────────────────────────────────────────────

let currentView = "topology";
let _physicsEnabled = true;
let _enhanceEnabled = true;
let _lastFetchStartedAt = null;
let _currentSearchQuery = "";

export function getSearchQuery() {
  return _currentSearchQuery;
}

function applyLegendLineStylesFromConstants() {
  const root = document.documentElement;
  root.style.setProperty(
    "--lq-style-width-high",
    `${EDGE_LQ_STYLES.high.width}px`,
  );
  root.style.setProperty(
    "--lq-style-width-medium",
    `${EDGE_LQ_STYLES.medium.width}px`,
  );
  root.style.setProperty(
    "--lq-style-width-low",
    `${EDGE_LQ_STYLES.low.width}px`,
  );
  root.style.setProperty(
    "--lq-style-width-parent-child",
    `${EDGE_LQ_STYLES.parentChild.width}px`,
  );
  root.style.setProperty(
    "--lq-style-width-otbr",
    `${EDGE_LQ_STYLES.noLqPurple.width}px`,
  );
}

// ── Refresh diagnostic filter based on current source and dataset capabilities ──

function refreshDiagnosticFilterForCurrentSource() {
  if (!currentDataset || !currentDataset.capabilities) return;
  const diagSourceSelect = document.getElementById("diagnostic-source-filter");
  const selectedSource = diagSourceSelect.value;
  const currentDiagValue = document.getElementById("diagnostic-filter").value;
  
  // Get the appropriate node data for validation
  let nodeDataForValidation = null;
  if (currentView === "topology") {
    nodeDataForValidation = getTopologyNodeData();
  } else if (currentView === "table") {
    // For table view, use the raw rows
    nodeDataForValidation = currentDataset.rows;
  }
  
  // Repopulate with capability-aware filtering and data validation
  populateDiagnosticFilterBySourceWithCapabilities(selectedSource, currentDataset.capabilities, nodeDataForValidation);
  
  // Restore the previously selected value if it's still available
  const diagFilterEl = document.getElementById("diagnostic-filter");
  const optionExists = Array.from(diagFilterEl.options).some(opt => opt.value === currentDiagValue);
  if (optionExists) {
    diagFilterEl.value = currentDiagValue;
  } else {
    diagFilterEl.value = "all";
  }
}

function renderCurrentView() {
  if (!currentDataset) return;
  const view = currentView;

  const effectiveDataset = _enhanceEnabled
    ? {
      ...currentDataset,
      rows: enrichRows(currentDataset.rows),
      rawFiles: enrichRawFiles(currentDataset.rawFiles),
    }
    : currentDataset;

  if (view === "topology") {
    renderTopologyForDataset(effectiveDataset, _physicsEnabled);
    const counts = getTopologyDatasetCounts();
    if (counts) updateDeviceStatusBar(counts);
  } else {
    renderTableForDataset(effectiveDataset);
    updateDeviceStatusBar(computeRowCounts(currentDataset.rows));
  }

  // Sync capabilities back to currentDataset when effectiveDataset is a spread copy
  // (happens when _enhanceEnabled is true). The renderers set dataset.capabilities on
  // effectiveDataset, so we need to propagate it back so change-event handlers can use it.
  if (effectiveDataset !== currentDataset && effectiveDataset.capabilities) {
    currentDataset.capabilities = effectiveDataset.capabilities;
  }

  // Refresh diagnostic filter to show only relevant options for this dataset
  refreshDiagnosticFilterForCurrentSource();
}

// ── Section 7: View Toggle ────────────────────────────────────────────────────

function switchView(newView) {
  if (newView === currentView) return;
  currentView = newView;

  const topoPanel = document.getElementById("view-topology");
  const tablePanel = document.getElementById("view-table");
  const btnTopology = document.getElementById("btn-topology");
  const btnTable = document.getElementById("btn-table");
  const btnPhysics = document.getElementById("btn-physics");
  const btnAutoZoom = document.getElementById("btn-auto-zoom");
  const linkFilterEl = document.getElementById("link-filter");

  if (newView === "topology") {
    topoPanel.style.display = "block";
    tablePanel.style.display = "none";
    btnTopology.classList.add("active");
    btnTable.classList.remove("active");
    btnPhysics.style.display = "inline-block";
    if (btnAutoZoom) btnAutoZoom.style.display = "inline-block";
    linkFilterEl.classList.remove("filter-disabled");
    resetNodeDetailsLists();
  } else {
    topoPanel.style.display = "none";
    tablePanel.style.display = "block";
    btnTable.classList.add("active");
    btnTopology.classList.remove("active");
    btnPhysics.style.display = "none";
    if (btnAutoZoom) btnAutoZoom.style.display = "none";
    linkFilterEl.classList.add("filter-disabled");
    document.getElementById("table-details-list").innerHTML =
      "<li>Click a row to view its properties.</li>";
  }

  if (currentDataset) {
    renderCurrentView();
  }
}

document
  .getElementById("btn-topology")
  .addEventListener("click", () => switchView("topology"));
document
  .getElementById("btn-table")
  .addEventListener("click", () => switchView("table"));

// ── Physics toggle ────────────────────────────────────────────────────────────

function setPhysics(enabled) {
  _physicsEnabled = enabled;
  const btn = document.getElementById("btn-physics");
  if (enabled) {
    btn.classList.add("active");
    btn.textContent = "⏸"; // U+23F8 PAUSE
  } else {
    btn.classList.remove("active");
    btn.textContent = "▶"; // U+25B6 PLAY
  }
  const net = getVisNetwork();
  if (net) net.setOptions({ physics: { enabled } });
}

document
  .getElementById("btn-physics")
  .addEventListener("click", () => setPhysics(!_physicsEnabled));

// ── More Info toggle ──────────────────────────────────────────────────

function setMoreInfo(enabled) {
  setMoreInfoEnabled(enabled);
  const btn = document.getElementById("btn-more-info");
  if (enabled) {
    btn.classList.add("active");
  } else {
    btn.classList.remove("active");
  }
  if (currentDataset && currentView === "table") applyTableFilters();
}

document
  .getElementById("btn-more-info")
  .addEventListener("click", () => setMoreInfo(!isMoreInfoEnabled()));

// ── Legend toggle ────────────────────────────────────────────────────────────

const lqLegendEl = document.getElementById("lq-legend");
const btnLegendToggle = document.getElementById("btn-legend-toggle");
if (btnLegendToggle) {
  btnLegendToggle.addEventListener("click", () => {
    lqLegendEl.classList.toggle("hidden");
    btnLegendToggle.classList.toggle("active");
  });
}

// ── Section 8: Filter Controls + Dataset Select Wiring ───────────────────────

// Helper: Reset all node details lists
function resetNodeDetailsLists() {
  document.getElementById("summary-list").innerHTML =
    "<li>Click a node to view its properties.</li>";
  document
    .querySelectorAll(
      "#identity-list, #highlights-list, #connections-list, #mdns-list, #routes-links-list, #neighbors-list, #children-list, #counters-list, #details-list",
    )
    .forEach((list) => {
      list.innerHTML = "";
      list.classList.add("hidden");
    });
}

document
  .getElementById("datasource-filter")
  .addEventListener("change", async (event) => {
    const selectedSource = event.target.value;
    populateDatasetSelect(selectedSource);
    // Reset filter controls when source changes
    document.getElementById("node-filter").value = "all";
    document.getElementById("link-filter").value = "default_links";
    document.getElementById("diagnostic-filter").value = "all";

    // Auto-fetch if enabled (fixes bug where single-dataset source doesn't trigger change event)
    if (document.getElementById("chk-auto-fetch").checked) {
      await doFetchDataset();
    }
  });

document
  .getElementById("dataset-select")
  .addEventListener("change", async (event) => {
    document.getElementById("node-filter").value = "all";
    document.getElementById("diagnostic-filter").value = "all";

    // Switch view based on the dataset's defaultView field if auto-view is enabled
    const autoViewEnabled = document.getElementById("chk-auto-view").checked;
    if (autoViewEnabled) {
      const selectedValue = event.target.value;
      const selectedDataset = DATASET_REGISTRY.find((entry) => entry.value === selectedValue);
      if (selectedDataset && selectedDataset.defaultView) {
        switchView(selectedDataset.defaultView);
      }
    }
  });

document.getElementById("node-filter").addEventListener("change", () => {
  if (!currentDataset) return;
  if (currentView === "topology") {
    const handlers = getTopologyFilterHandlers();
    if (handlers) {
      const linkFilterEl = document.getElementById("link-filter");
      const nodeFilterEl = document.getElementById("node-filter");
      const diagFilterEl = document.getElementById("diagnostic-filter");
      const counts = handlers.applyFilters(
        nodeFilterEl.value,
        linkFilterEl.value,
        diagFilterEl.value,
      );
      handlers.updateStatus(counts);
      handlers.fitIfEnabled();
      resetNodeDetailsLists();
    }
  } else {
    applyTableFilters();
  }
});

document.getElementById("link-filter").addEventListener("change", () => {
  if (!currentDataset || currentView !== "topology") return;
  const handlers = getTopologyFilterHandlers();
  if (handlers) {
    const linkFilterEl = document.getElementById("link-filter");
    const nodeFilterEl = document.getElementById("node-filter");
    const diagFilterEl = document.getElementById("diagnostic-filter");
    const counts = handlers.applyFilters(
      nodeFilterEl.value,
      linkFilterEl.value,
      diagFilterEl.value,
    );
    handlers.updateStatus(counts);
    handlers.fitIfEnabled();
    resetNodeDetailsLists();
  }
});

document.getElementById("diagnostic-filter").addEventListener("change", () => {
  if (!currentDataset) return;
  if (currentView === "topology") {
    const handlers = getTopologyFilterHandlers();
    if (handlers) {
      const linkFilterEl = document.getElementById("link-filter");
      const nodeFilterEl = document.getElementById("node-filter");
      const diagFilterEl = document.getElementById("diagnostic-filter");
      const counts = handlers.applyFilters(
        nodeFilterEl.value,
        linkFilterEl.value,
        diagFilterEl.value,
      );
      handlers.updateStatus(counts);
      handlers.fitIfEnabled();
      resetNodeDetailsLists();
    }
  } else {
    applyTableFilters();
  }
});

document.getElementById("diagnostic-source-filter").addEventListener("change", (event) => {
  const selectedSource = event.target.value;
  // Use capability-aware population if dataset is loaded and has capabilities
  if (currentDataset && currentDataset.capabilities) {
    // Use view-aware node data so computed fields (lq3_ratio, etc.) are available
    const nodeDataForValidation = currentView === "topology"
      ? getTopologyNodeData()
      : currentDataset.rows;
    populateDiagnosticFilterBySourceWithCapabilities(selectedSource, currentDataset.capabilities, nodeDataForValidation);
  } else {
    populateDiagnosticFilterBySource(selectedSource);
  }
  // Reset diagnostic filter to "all" when source changes
  document.getElementById("diagnostic-filter").value = "all";
  // Trigger a change event on the diagnostic-filter to apply the new filters
  if (!currentDataset) return;
  if (currentView === "topology") {
    const handlers = getTopologyFilterHandlers();
    if (handlers) {
      const linkFilterEl = document.getElementById("link-filter");
      const nodeFilterEl = document.getElementById("node-filter");
      const diagFilterEl = document.getElementById("diagnostic-filter");
      const counts = handlers.applyFilters(
        nodeFilterEl.value,
        linkFilterEl.value,
        diagFilterEl.value,
      );
      handlers.updateStatus(counts);
      handlers.fitIfEnabled();
      resetNodeDetailsLists();
    }
  } else {
    applyTableFilters();
  }
});

// ── Bootstrap ─────────────────────────────────────────────────────────────────

const initialSource = document.getElementById("datasource-filter").value;
populateDatasetSelect(initialSource);
populateFilterSelects();
// Initialize diagnostic-filter with the default diagnostic source
const initialDiagSource = document.getElementById("diagnostic-source-filter").value;
populateDiagnosticFilterBySource(initialDiagSource);
applyLegendLineStylesFromConstants();
await loadStaticLabelMap();
// do not auto-load on startup; prompt the user instead.
document.getElementById("view-status-line-content").textContent =
  "Showing: no dataset loaded. Select a dataset and click Fetch.";

initDetailPanelToggles(document.getElementById("details"));
initDetailPanelToggles(document.getElementById("table-details"));

// Cache checkbox helper: make checkboxes mutually exclusive
function updateCacheCheckboxes(changedCheckbox) {
  const chkAutoFetch = document.getElementById("chk-auto-fetch");
  const chkForceFresh = document.getElementById("chk-force-fresh");
  const chkOnlyCache = document.getElementById("chk-only-cache");

  if (changedCheckbox === chkAutoFetch && chkAutoFetch.checked) {
    chkForceFresh.checked = false;
    chkOnlyCache.checked = false;
    setForceFresh(false);
    setOnlyCache(false);
  } else if (changedCheckbox === chkForceFresh && chkForceFresh.checked) {
    chkAutoFetch.checked = false;
    chkOnlyCache.checked = false;
    setForceFresh(true);
    setOnlyCache(false);
  } else if (changedCheckbox === chkOnlyCache && chkOnlyCache.checked) {
    chkAutoFetch.checked = false;
    chkForceFresh.checked = false;
    setForceFresh(false);
    setOnlyCache(true);
  }
}

// ── Status bar updaters ───────────────────────────────────────────────────────

// Mirrors isChildNode() in tdash-topology-utils.js but operates on row objects.
// Comparison is case-insensitive because some sources emit "Child" (capitalised).
function isChildRow(r) {
  const t = (r.type || "").toLowerCase();
  return t === "child" || t === "sleepy-child";
}

// Derives device and link counts from a flat rows array (table-view path).
// Link counts are halved because each undirected link appears in both endpoints.
// Returns null for link fields when no row carries the link-count fields.
// Returns null for classification fields when no row carries Thread topology fields
// (rloc16 / br / type), which is the case for non-Thread sources such as mDNS.
function computeRowCounts(rows) {
  const hasThreadClassification = rows.some(
    (r) => r.rloc16 != null || r.br != null || r.type != null,
  );
  if (!hasThreadClassification) {
    return {
      devices: rows.length,
      borderRouters: null, routers: null, children: null,
      links: null, lq3: null, lq2: null, lq1: null,
    };
  }
  let tl3 = 0, tl2 = 0, tl1 = 0, tl = 0, hasLinkFields = false;
  const routerRows = rows.filter((r) => !isChildRow(r));
  routerRows.forEach((r) => {
    const v3 = toFiniteNumber(r.total_link_3);
    const v2 = toFiniteNumber(r.total_link_2);
    const v1 = toFiniteNumber(r.total_link_1);
    const vt = toFiniteNumber(r.total_links);
    if (Number.isFinite(v3)) { tl3 += v3; hasLinkFields = true; }
    if (Number.isFinite(v2)) { tl2 += v2; hasLinkFields = true; }
    if (Number.isFinite(v1)) { tl1 += v1; hasLinkFields = true; }
    if (Number.isFinite(vt)) { tl  += vt; hasLinkFields = true; }
  });
  return {
    devices:       rows.length,
    borderRouters: rows.filter((r) => r.br === true).length,
    routers:       routerRows.filter((r) => !r.br).length,
    children:      rows.filter((r) => isChildRow(r)).length,
    links: hasLinkFields ? Math.round(tl  / 2) : null,
    lq3:   hasLinkFields ? Math.round(tl3 / 2) : null,
    lq2:   hasLinkFields ? Math.round(tl2 / 2) : null,
    lq1:   hasLinkFields ? Math.round(tl1 / 2) : null,
  };
}

function updateDeviceStatusBar(counts) {
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val != null ? String(val) : "—";
  };
  set("device-count",  counts.devices);
  set("br-count",      counts.borderRouters);
  set("router-count",  counts.routers);
  set("child-count",   counts.children);
  set("link-count",    counts.links);
  set("lq3-count",     counts.lq3);
  set("lq2-count",     counts.lq2);
  set("lq1-count",     counts.lq1);
}

function updateFetchStatusBar(fetchStartedAt) {
  document.getElementById("fetch-last-value").textContent =
    formatAgo(fetchStartedAt);
  document.getElementById("fetch-timetaken-value").textContent =
    currentDataset?.fetchDurationMs != null
      ? formatDuration(currentDataset.fetchDurationMs)
      : "—";
  document.getElementById("fetch-cache-age-value").textContent =
    currentDataset?.fileLastModifiedAt != null
      ? formatAgo(currentDataset.fileLastModifiedAt)
      : "—";
}

// Reusable list of all status-bar span IDs for bulk updates.
const _FETCH_STATUS_IDS = ["fetch-last-value", "fetch-timetaken-value", "fetch-cache-age-value"];
const _DEVICE_STATUS_IDS = ["device-count", "br-count", "router-count", "child-count",
                             "link-count", "lq3-count", "lq2-count", "lq1-count"];

function _setStatusSpans(ids, text) {
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  });
}

// Fetch dataset function
async function doFetchDataset() {
  _lastFetchStartedAt = Date.now();
  const selectedValue = document.getElementById("dataset-select").value;
  if (!selectedValue) return;

  // Reset status bars to loading state
  _setStatusSpans(_FETCH_STATUS_IDS, "…");
  _setStatusSpans(_DEVICE_STATUS_IDS, "…");

  // Apply defaultView from registry if auto-view is enabled
  const autoViewEnabled = document.getElementById("chk-auto-view").checked;
  if (autoViewEnabled) {
    const selectedDataset = DATASET_REGISTRY.find((entry) => entry.value === selectedValue);
    if (selectedDataset && selectedDataset.defaultView) {
      switchView(selectedDataset.defaultView);
    }
  }

  try {
    await loadDataset(selectedValue);
  } catch (err) {
    console.error("loadDataset threw:", err);
    _setStatusSpans(_FETCH_STATUS_IDS, "—");
    _setStatusSpans(_DEVICE_STATUS_IDS, "—");
    return;
  }

  // loadDataset returns early without updating currentDataset when all files fail.
  if (!currentDataset || currentDataset.entry?.value !== selectedValue) {
    _setStatusSpans(_FETCH_STATUS_IDS, "—");
    _setStatusSpans(_DEVICE_STATUS_IDS, "—");
    return;
  }

  // Reset search state when a new dataset is loaded
  _currentSearchQuery = "";
  const _srchInput = document.getElementById("search-input");
  if (_srchInput) _srchInput.value = "";

  renderCurrentView();
  updateFetchStatusBar(_lastFetchStartedAt);
}

// Fetch button drives data acquisition.
document.getElementById("btn-fetch").addEventListener("click", doFetchDataset);

// Auto-fetch when dataset is selected and chk-auto-fetch is enabled
document.getElementById("dataset-select").addEventListener("change", async () => {
  if (document.getElementById("chk-auto-fetch").checked) {
    await doFetchDataset();
  }
});

// ── Search wiring ────────────────────────────────────────────────────────────────────────

function applySearch() {
  if (!currentDataset) {
    document.getElementById("view-status-line-content").textContent =
      "No dataset loaded. Select a dataset and click Fetch.";
    return;
  }

  if (currentView === "table") {
    // applyTableFilters reads #search-input directly and updates #view-status-line-content
    applyTableFilters();
  } else {
    // Topology: apply node highlight
    const handlers = getTopologyFilterHandlers();
    if (handlers) {
      handlers.applySearchHighlight(_currentSearchQuery, isMoreInfoEnabled());
    }
  }
}

document.getElementById("btn-search-find")?.addEventListener("click", () => {
  _currentSearchQuery = parseSearchQuery(
    document.getElementById("search-input").value,
  );
  applySearch();
});

document.getElementById("search-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    _currentSearchQuery = parseSearchQuery(e.target.value);
    applySearch();
  }
});

document.getElementById("btn-search-clear")?.addEventListener("click", () => {
  document.getElementById("search-input").value = "";
  _currentSearchQuery = "";
  applySearch();
});

// Cache control checkboxes (mutually exclusive)
document.getElementById("chk-auto-fetch").addEventListener("change", (e) => {
  if (e.target.checked) {
    updateCacheCheckboxes(e.target);
  }
});

document.getElementById("chk-force-fresh").addEventListener("change", (e) => {
  if (e.target.checked) {
    updateCacheCheckboxes(e.target);
  }
});

document.getElementById("chk-only-cache").addEventListener("change", (e) => {
  if (e.target.checked) {
    updateCacheCheckboxes(e.target);
  }
});

// ── Collapsible cache-options fieldsets and containers ─────────────────────────────────────

["btn-toggle-cache", "btn-toggle-status", "btn-toggle-devices", "btn-toggle-panel-view", "btn-toggle-panel-dataset", "btn-toggle-filters", "btn-toggle-node-link-filters", "btn-toggle-diag-filters"].forEach((id) => {
  document.getElementById(id)?.addEventListener("click", () => {
    const btn = document.getElementById(id);
    const container = btn.closest("fieldset, [class*='cache-options'], #panel-view, #panel-dataset, #panel-node-link-filters");
    const isExpanded = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!isExpanded));
    if (container) container.classList.toggle("collapsed");
  });
});

// ── Collapsible Filters Panel ────────────────────────────────────────────────
// (Handled by unified collapse logic above)

// ── Collapse All / Expand All panels (home bar) ───────────────────────────────
{
  const MAIN_PANELS = [
    { panelId: "panel-dataset",          btnId: "btn-toggle-panel-dataset" },
    { panelId: "panel-node-link-filters", btnId: "btn-toggle-filters" },
    { panelId: "panel-view",             btnId: "btn-toggle-panel-view" },
  ];

  const allBtn   = document.getElementById("btn-panels-toggle-all");
  const allArrow = allBtn?.querySelector(".panels-toggle-arrow");
  let isAllCollapsed = false;

  allBtn?.addEventListener("click", () => {
    isAllCollapsed = !isAllCollapsed;
    allArrow.textContent = isAllCollapsed ? "▶" : "▼";
    allBtn.title = isAllCollapsed ? "Expand all panels" : "Collapse all panels";

    MAIN_PANELS.forEach(({ panelId, btnId }) => {
      const panel = document.getElementById(panelId);
      const btn   = document.getElementById(btnId);
      if (panel) panel.classList.toggle("collapsed", isAllCollapsed);
      if (btn)   btn.setAttribute("aria-expanded", String(!isAllCollapsed));
    });
  });
}
