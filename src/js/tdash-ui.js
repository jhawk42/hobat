// Prevent browser from restoring scroll position on reload
if ('scrollRestoration' in history) {
  history.scrollRestoration = 'manual';
}

import { DATASET_REGISTRY, DATASOURCE_REGISTRY } from "./tdash-dataset-registry.js";
import {
  currentDataset,
  loadDataset,
  loadStaticLabelMap,
  enrichRows,
  enrichRawFiles,
  setForceFresh,
  setOnlyCache,
  startFetchSession,
  endFetchSession,
  cancelActiveFetchSession,
  isFetchCancelledError,
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
  setOnPhysicsDisabledCallback,
} from "./tdash-topology-renderer.js";
import {
  renderTableForDataset,
  applyTableFilters,
  setMoreInfoEnabled,
  isMoreInfoEnabled,
} from "./tdash-table-renderer.js";
import { EDGE_LQ_STYLES } from "./tdash-constants.js";
import {
  PHYSICS_PROFILE_MESH_BASELINE,
  PHYSICS_PROFILE_MESH_DENSE,
  PHYSICS_PROFILE_MESH_BALANCED,
  PHYSICS_PROFILE_MESH_SPARSE,
  PHYSICS_PROFILE_MESH_COMPACT,
  PHYSICS_PROFILE_MESH_RING,
  PHYSICS_PROFILES,
  getPhysicsProfileLabel,
} from "./tdash-constants.js";
import { initDetailPanelToggles, formatAgo, formatDuration, toFiniteNumber, getColumnValue, toText } from "./tdash-utils.js";
import {
  populateFilterSelects,
  populateDiagnosticFilterBySource,
  populateDiagnosticFilterBySourceWithCapabilities,
} from "./tdash-filters.js";
import { parseSearchQuery, filterRowsBySearch } from "./tdash-search.js";

// ── Build datasource <select> ────────────────────────────────────────

function populateDatasourceSelect() {
  const sel = document.getElementById("datasource-filter");
  sel.innerHTML = ""; // Clear existing options

  for (let i = 0; i < DATASOURCE_REGISTRY.length; i++) {
    const entry = DATASOURCE_REGISTRY[i];
    const opt = document.createElement("option");
    opt.value = entry.value;
    opt.textContent = entry.label;
    opt.title = entry.label;
    sel.appendChild(opt);
  }
}


// ── Section 2: Build dataset <select> ────────────────────────────────────────

function populateDatasetSelect(sourceFilter = null) {
  const sel = document.getElementById("dataset-select");
  sel.innerHTML = ""; // Clear existing options

  const filteredRegistry = sourceFilter
    ? DATASET_REGISTRY.filter((entry) => entry.source === sourceFilter)
    : DATASET_REGISTRY;

  let currentGroupLabel = undefined;
  let currentOptgroup = null;

  for (let i = 0; i < filteredRegistry.length; i++) {
    const entry = filteredRegistry[i];

    // Create new optgroup when group changes
    if (entry.group !== currentGroupLabel) {
      currentGroupLabel = entry.group;
      if (entry.group != null) {
        currentOptgroup = document.createElement("optgroup");
        currentOptgroup.label = entry.group;
        sel.appendChild(currentOptgroup);
      } else {
        currentOptgroup = null;
      }
    }

    const opt = document.createElement("option");
    opt.value = entry.value;
    opt.textContent = entry.label;
    opt.title = entry.label; // Use the label as the tooltip content

    // Append to optgroup if one exists, otherwise to select element
    (currentOptgroup ?? sel).appendChild(opt);
  }
}

// ── Render dispatcher ────────────────────────────────────────────────────────

let currentView = "topology";
let _physicsEnabled = true;
let _physicsProfileName = PHYSICS_PROFILE_MESH_BASELINE;
const PHYSICS_PROFILE_AUTO = "auto";
let _enhanceEnabled = true;
let _lastFetchStartedAt = null;
let _currentSearchQuery = "";
let _fetchInProgress = false;

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
  populateDiagnosticFilterBySourceWithCapabilities(selectedSource, currentDataset.capabilities, nodeDataForValidation, currentView);
  
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
    // Re-enable physics for new dataset so it can stabilize
    setPhysics(true);
    const selectedEntry = effectiveDataset?.entry || getSelectedDatasetEntry();
    const effectivePhysicsProfileName = getEffectivePhysicsProfileName(selectedEntry);
    renderTopologyForDataset(
      effectiveDataset,
      _physicsEnabled,
      effectivePhysicsProfileName,
    );
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

function getPhysicsProfileSelect() {
  return document.getElementById("physics-profile-select");
}

function getSelectedDatasetEntry() {
  const selectedValue = document.getElementById("dataset-select")?.value;
  return DATASET_REGISTRY.find((entry) => entry.value === selectedValue) || null;
}

function getModeMappedPhysicsProfileName(entry) {
  const topologyMode = entry?.topologyMode;
  if (topologyMode === "meshdiag-networkdiag") return PHYSICS_PROFILE_MESH_COMPACT;
  if (topologyMode === "merged-detailed") return PHYSICS_PROFILE_MESH_RING;
  if (topologyMode === "router-table") return PHYSICS_PROFILE_MESH_BALANCED;
  if (topologyMode === "eve_native") return PHYSICS_PROFILE_MESH_COMPACT;
  if (topologyMode === "eve_enhanced") return PHYSICS_PROFILE_MESH_RING;
  if (topologyMode === "raw-array") return PHYSICS_PROFILE_MESH_BALANCED;
  if (topologyMode === "otbr_restapi") return PHYSICS_PROFILE_MESH_COMPACT;
  return PHYSICS_PROFILE_MESH_BASELINE;
}

function getEffectivePhysicsProfileName(entry = getSelectedDatasetEntry()) {
  // Manual user selection (not auto) has highest precedence
  if (_physicsProfileName !== PHYSICS_PROFILE_AUTO) return _physicsProfileName;
  
  // If auto mode: dataset-level physicsProfile takes precedence over topologyMode mapping
  if (entry?.physicsProfile) return entry.physicsProfile;
  
  // Fall back to topologyMode-based auto mapping
  return getModeMappedPhysicsProfileName(entry);
}

function getPhysicsProfileStatusLabel(entry = getSelectedDatasetEntry()) {
  const effective = getEffectivePhysicsProfileName(entry);
  if (_physicsProfileName === PHYSICS_PROFILE_AUTO) {
    return `Auto (${getPhysicsProfileLabel(effective)})`;
  }
  return getPhysicsProfileLabel(effective);
}

function setPhysicsProfile(profileName) {
  const key = typeof profileName === "string" ? profileName.toLowerCase() : "";
  _physicsProfileName = key === PHYSICS_PROFILE_AUTO || Object.prototype.hasOwnProperty.call(PHYSICS_PROFILES, key)
    ? key
    : PHYSICS_PROFILE_MESH_BASELINE;

  const select = getPhysicsProfileSelect();
  if (select) select.value = _physicsProfileName;

  try {
    localStorage.setItem("tdash.physicsProfile", _physicsProfileName);
  } catch {
    // Ignore localStorage failures (e.g., private mode policies)
  }

  const statusEl = document.getElementById("view-status-line-content");
  if (statusEl && !currentDataset) {
    statusEl.textContent = `Showing: no dataset loaded. Select a dataset and click Fetch. Physics profile: ${getPhysicsProfileStatusLabel()}.`;
  }
}

function initPhysicsProfileSelector() {
  const select = getPhysicsProfileSelect();
  if (!select) return;

  let initialProfile = PHYSICS_PROFILE_AUTO;
  try {
    //const stored = localStorage.getItem("tdash.physicsProfile");
    //if (stored) initialProfile = stored;
  } catch {
    // Ignore localStorage failures
  }

  setPhysicsProfile(initialProfile);

  select.addEventListener("change", () => {
    setPhysicsProfile(select.value);
    if (currentDataset && currentView === "topology") {
      renderCurrentView();
    }
  });
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
    document.getElementById("details-list").innerHTML = "";
    const summaryListEl = document.getElementById("summary-list");
    if (summaryListEl)
      summaryListEl.innerHTML = "<li>Click a node or row to view its properties.</li>";
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

// Common topology select-change path: reapply filters first,
// then restore canonical node styling to preserve node type colors.
function refreshTopologyFiltersWithRestoredStyling() {
  if (!currentDataset || currentView !== "topology") return false;
  const handlers = getTopologyFilterHandlers();
  if (!handlers) return false;

  const linkFilterEl = document.getElementById("link-filter");
  const nodeFilterEl = document.getElementById("node-filter");
  const diagFilterEl = document.getElementById("diagnostic-filter");
  const counts = handlers.applyFilters(
    nodeFilterEl.value,
    linkFilterEl.value,
    diagFilterEl.value,
  );
  handlers.updateStatus(counts);

  // Apply visual styling after filters to ensure correct colors are displayed
  if (typeof handlers.restoreOriginalNodeStyling === "function") {
    handlers.restoreOriginalNodeStyling();
  }

  handlers.fitIfEnabled();
  resetNodeDetailsLists();
  return true;
}

document
  .getElementById("datasource-filter")
  .addEventListener("change", async (event) => {
    const selectedSource = event.target.value;
    populateDatasetSelect(selectedSource);
    setPhysicsProfile(PHYSICS_PROFILE_AUTO);
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
    setPhysicsProfile(PHYSICS_PROFILE_AUTO);

    // Switch view based on the dataset's defaultView field if auto-view is enabled
    const autoViewEnabled = document.getElementById("chk-auto-view").checked;
    if (autoViewEnabled) {
      const selectedValue = event.target.value;
      const selectedDataset = DATASET_REGISTRY.find((entry) => entry.value === selectedValue);
      if (selectedDataset && selectedDataset.defaultView) {
        switchView(selectedDataset.defaultView);
      }
    }

    // Update estimated fetch time immediately on dataset selection
    const selectedValue = event.target.value;
    const selectedDataset = DATASET_REGISTRY.find((entry) => entry.value === selectedValue);
    if (selectedDataset && selectedDataset.estimateActionCostSecs != null) {
      updateEstimatedFetchTime(selectedDataset.estimateActionCostSecs);
    } else {
      updateEstimatedFetchTime(null);
    }

    if (_physicsProfileName === PHYSICS_PROFILE_AUTO && !currentDataset) {
      const statusEl = document.getElementById("view-status-line-content");
      if (statusEl) {
        statusEl.textContent = `Showing: no dataset loaded. Select a dataset and click Fetch. Physics profile: ${getPhysicsProfileStatusLabel(selectedDataset)}.`;
      }
    }
  });

document.getElementById("node-filter").addEventListener("change", () => {
  if (!currentDataset) return;
  if (currentView === "topology") {
    refreshTopologyFiltersWithRestoredStyling();
  } else {
    applyTableFilters();
  }
});

document.getElementById("link-filter").addEventListener("change", () => {
  refreshTopologyFiltersWithRestoredStyling();
});

document.getElementById("diagnostic-filter").addEventListener("change", () => {
  if (!currentDataset) return;
  if (currentView === "topology") {
    refreshTopologyFiltersWithRestoredStyling();
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
    populateDiagnosticFilterBySourceWithCapabilities(selectedSource, currentDataset.capabilities, nodeDataForValidation, currentView);
  } else {
    populateDiagnosticFilterBySource(selectedSource);
  }
  // Reset diagnostic filter to "all" when source changes
  document.getElementById("diagnostic-filter").value = "all";
  // Trigger a change event on the diagnostic-filter to apply the new filters
  if (!currentDataset) return;
  if (currentView === "topology") {
    refreshTopologyFiltersWithRestoredStyling();
  } else {
    applyTableFilters();
  }
});

// ── Bootstrap ─────────────────────────────────────────────────────────────────

// Register callback to sync physics button state when auto-disabled after stabilization
setOnPhysicsDisabledCallback(() => setPhysics(false));

populateDatasourceSelect();
const initialSource = document.getElementById("datasource-filter").value;
populateDatasetSelect(initialSource);
populateFilterSelects();
// Initialize diagnostic-filter with the default diagnostic source
const initialDiagSource = document.getElementById("diagnostic-source-filter").value;
populateDiagnosticFilterBySource(initialDiagSource);
applyLegendLineStylesFromConstants();
await loadStaticLabelMap();
initPhysicsProfileSelector();

// Initialize estimated fetch time from the initially selected dataset
const initialDatasetValue = document.getElementById("dataset-select").value;
if (initialDatasetValue) {
  const initialDataset = DATASET_REGISTRY.find((entry) => entry.value === initialDatasetValue);
  if (initialDataset && initialDataset.estimateActionCostSecs != null) {
    updateEstimatedFetchTime(initialDataset.estimateActionCostSecs);
  }
}

// do not auto-load on startup; prompt the user instead.
document.getElementById("view-status-line-content").textContent =
  `Showing: no dataset loaded. Select a dataset and click Fetch. Physics profile: ${getPhysicsProfileStatusLabel()}.`;

initDetailPanelToggles(document.getElementById("device-details"));

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
  const t = toText(getColumnValue(r, "type")).toLowerCase();
  return t === "child" || t === "sleepy-child";
}

// Derives device and link counts from a flat rows array (table-view path).
// Link counts are halved because each undirected link appears in both endpoints.
// Returns null for link fields when no row carries the link-count fields.
// Returns null for classification fields when no row carries Thread topology fields
// (rloc16 / br / type), which is the case for non-Thread sources such as mDNS.
function computeRowCounts(rows) {
  const hasThreadClassification = rows.some(
    (r) => getColumnValue(r, "rloc16") != null || getColumnValue(r, "br") != null || getColumnValue(r, "type") != null,
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
    const v3 = toFiniteNumber(getColumnValue(r, "totalLink3") ?? getColumnValue(r, "total_link_3"));
    const v2 = toFiniteNumber(getColumnValue(r, "totalLink2") ?? getColumnValue(r, "total_link_2"));
    const v1 = toFiniteNumber(getColumnValue(r, "totalLink1") ?? getColumnValue(r, "total_link_1"));
    const vt = toFiniteNumber(getColumnValue(r, "totalLinks") ?? getColumnValue(r, "total_links"));
    if (Number.isFinite(v3)) { tl3 += v3; hasLinkFields = true; }
    if (Number.isFinite(v2)) { tl2 += v2; hasLinkFields = true; }
    if (Number.isFinite(v1)) { tl1 += v1; hasLinkFields = true; }
    if (Number.isFinite(vt)) { tl  += vt; hasLinkFields = true; }
  });
  return {
    devices:       rows.length,
    borderRouters: rows.filter((r) => getColumnValue(r, "br") === true).length,
    routers:       routerRows.filter((r) => getColumnValue(r, "br") !== true).length,
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
const _FETCH_STATUS_IDS = ["fetch-timetaken-value", "fetch-cache-age-value"];
const _DEVICE_STATUS_IDS = ["device-count", "br-count", "router-count", "child-count",
                             "link-count", "lq3-count", "lq2-count", "lq1-count"];
const _CANCELLED_PARTIAL_STATUS_PIN_MS = 3000;

function _pinFetchStatusLineMessage(message, pinDurationMs = _CANCELLED_PARTIAL_STATUS_PIN_MS) {
  const statusEl = document.getElementById("fetch-status-line-content");
  if (statusEl) statusEl.textContent = message;
  window.tdashDebug = window.tdashDebug || {};
  window.tdashDebug.fetchStatusPinnedUntil = Date.now() + pinDurationMs;
}

function _setStatusSpans(ids, text) {
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  });
}

// Update estimated fetch time from dataset registry
function updateEstimatedFetchTime(estimateSeconds) {
  const el = document.getElementById("fetch-timetaken-value");
  if (!el) return;
  if (estimateSeconds == null || !Number.isFinite(estimateSeconds)) {
    el.textContent = "—";
  } else {
    el.textContent = `~${Math.ceil(estimateSeconds)}s`;
  }
}

function setFetchButtonsState(fetching) {
  const fetchBtn = document.getElementById("btn-fetch");
  const cancelBtn = document.getElementById("btn-fetch-cancel");
  if (fetchBtn) fetchBtn.disabled = fetching;
  if (cancelBtn) cancelBtn.disabled = !fetching;
}

function resetFetchTimeTakenProgressToDefault() {
  const progressEl = document.getElementById("fetch-timetaken-progress");
  if (!progressEl) return;
  progressEl.removeAttribute("value");
}

// Fetch dataset function
async function doFetchDataset() {
  if (_fetchInProgress) return;

  _fetchInProgress = true;
  setFetchButtonsState(true);

  _lastFetchStartedAt = Date.now();
  const selectedValue = document.getElementById("dataset-select").value;
  if (!selectedValue) {
    _fetchInProgress = false;
    setFetchButtonsState(false);
    return;
  }

  const sessionId = startFetchSession();
  // Debounce handle: coalesces rapid-fire onFileReady calls (e.g. cached files all resolving in
  // one tick) into a single incremental render. setTimeout(0) lets all microtask .then() callbacks
  // settle before the render fires.
  let _incrementalRenderTimer = null;

  const _scheduleIncrementalRender = () => {
    if (_incrementalRenderTimer !== null) clearTimeout(_incrementalRenderTimer);
    _incrementalRenderTimer = setTimeout(() => {
      _incrementalRenderTimer = null;
      if (!currentDataset || currentDataset.entry?.value !== selectedValue) return;
      renderCurrentView();
      updateFetchStatusBar(_lastFetchStartedAt);
      if (currentDataset.isPartial) {
        const loadedCount = currentDataset.loadedFiles?.length ?? 0;
        const totalCount = currentDataset.entry?.files?.length ?? 0;
        const statusEl = document.getElementById("fetch-status-line-content");
        if (statusEl) {
          statusEl.textContent = `⚠ Partial result: ${loadedCount} of ${totalCount} files ready — still loading…`;
        }
      }
    }, 0);
  };

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
    await loadDataset(selectedValue, {
      sessionId,
      onFileReady: _scheduleIncrementalRender,
    });
  } catch (err) {
    if (_incrementalRenderTimer !== null) { clearTimeout(_incrementalRenderTimer); _incrementalRenderTimer = null; }
    if (isFetchCancelledError(err)) {
      resetFetchTimeTakenProgressToDefault();

      const statusEl = document.getElementById("fetch-status-line-content");
      const hasPartialResult = currentDataset &&
        currentDataset.entry?.value === selectedValue &&
        currentDataset.isPartial === true;

      if (hasPartialResult) {
        // Partial-with-warning committed state: render what loaded and surface the cancellation.
        const loadedCount = currentDataset.loadedFiles?.length ?? 0;
        const totalCount = currentDataset.entry?.files?.length ?? 0;
        _pinFetchStatusLineMessage(
          `⚠ Cancelled — partial result: ${loadedCount} of ${totalCount} files loaded`,
        );
        renderCurrentView();
        updateFetchStatusBar(_lastFetchStartedAt);
      } else {
        if (statusEl) statusEl.textContent = `Fetch cancelled for "${selectedValue}".`;
        // No partial data available: keep current view or clear bars.
        if (currentDataset) {
          renderCurrentView();
          updateFetchStatusBar(_lastFetchStartedAt);
        } else {
          _setStatusSpans(_FETCH_STATUS_IDS, "—");
          _setStatusSpans(_DEVICE_STATUS_IDS, "—");
        }
      }
    } else {
      console.error("loadDataset threw:", err);
      _setStatusSpans(_FETCH_STATUS_IDS, "—");
      _setStatusSpans(_DEVICE_STATUS_IDS, "—");
    }
    return;
  } finally {
    endFetchSession(sessionId);
    _fetchInProgress = false;
    setFetchButtonsState(false);
  }

  // loadDataset returns early without updating currentDataset when all files fail.
  if (!currentDataset || currentDataset.entry?.value !== selectedValue) {
    if (_incrementalRenderTimer !== null) { clearTimeout(_incrementalRenderTimer); _incrementalRenderTimer = null; }
    _setStatusSpans(_FETCH_STATUS_IDS, "—");
    _setStatusSpans(_DEVICE_STATUS_IDS, "—");
    return;
  }

  // Cancel any pending incremental render — final reconciliation render takes over.
  if (_incrementalRenderTimer !== null) { clearTimeout(_incrementalRenderTimer); _incrementalRenderTimer = null; }

  // Reset search state when a new dataset is loaded
  _currentSearchQuery = "";
  const _srchInput = document.getElementById("search-input");
  if (_srchInput) _srchInput.value = "";

  // Final reconciliation render: all files settled, isPartial is false.
  renderCurrentView();
  updateFetchStatusBar(_lastFetchStartedAt);
  if (currentDataset?.fetchMetrics) {
    const fetchMetricsPayload = {
      dataset: currentDataset.entry?.value,
      ...currentDataset.fetchMetrics,
    };
    console.info("[tdash] fetch metrics", fetchMetricsPayload);
    window.tdashDebug = window.tdashDebug || {};
    window.tdashDebug.lastFetchMetrics = fetchMetricsPayload;
  }
  // Clear any "⚠ Partial" message from incremental renders; warn if some files unavailable.
  const _fetchStatusEl = document.getElementById("fetch-status-line-content");
  if (_fetchStatusEl) {
    const failedCount = (currentDataset.entry?.files?.length ?? 0) - (currentDataset.loadedFiles?.length ?? 0);
    _fetchStatusEl.textContent = failedCount > 0
      ? `⚠ ${failedCount} file(s) unavailable — showing partial data`
      : "";
  }
}

// Fetch button drives data acquisition.
document.getElementById("btn-fetch").addEventListener("click", doFetchDataset);

document.getElementById("btn-fetch-cancel")?.addEventListener("click", async () => {
  if (!_fetchInProgress) return;

  const cancelBtn = document.getElementById("btn-fetch-cancel");
  if (cancelBtn) cancelBtn.disabled = true;

  try {
    await cancelActiveFetchSession();
  } catch (err) {
    console.warn("Failed to cancel active fetch session:", err);
  }
});

setFetchButtonsState(false);

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

document.getElementById("search-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    _currentSearchQuery = parseSearchQuery(e.target.value);
    applySearch();
  }
});

document.getElementById("btn-search-clear")?.addEventListener("click", () => {
  document.getElementById("search-input").value = "";
  _currentSearchQuery = "";
  if (currentView === "topology") {
    refreshTopologyFiltersWithRestoredStyling();
  }
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

const COLLAPSE_CONTAINER_BY_BUTTON_ID = {
  "btn-toggle-panel-view": "panel-view",
  "btn-toggle-panel-dataset": "panel-dataset",
  "btn-toggle-filters": "panel-node-link-filters",
};

["btn-toggle-cache", "btn-toggle-status", "btn-toggle-devices", "btn-toggle-panel-view", "btn-toggle-panel-dataset", "btn-toggle-filters", "btn-toggle-node-link-filters", "btn-toggle-diag-filters"].forEach((id) => {
  document.getElementById(id)?.addEventListener("click", () => {
    const btn = document.getElementById(id);
    const explicitContainerId = COLLAPSE_CONTAINER_BY_BUTTON_ID[id];
    const container = explicitContainerId
      ? document.getElementById(explicitContainerId)
      : btn.closest("fieldset, [class*='cache-options'], #panel-view, #panel-dataset, #panel-node-link-filters");
    const isExpanded = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!isExpanded));
    if (container) container.classList.toggle("collapsed");
  });
});

document.getElementById("btn-toggle-node-diag-filters")?.addEventListener("click", () => {
  const nodeLinkFieldset = document.getElementById("fieldset-node-link-filters");
  const diagFieldset = document.getElementById("fieldset-diag-filters");
  const nodeLinkToggleBtn = document.getElementById("btn-toggle-node-link-filters");
  const diagToggleBtn = document.getElementById("btn-toggle-diag-filters");

  if (!nodeLinkFieldset || !diagFieldset) return;

  const shouldShow = nodeLinkFieldset.hidden || diagFieldset.hidden;

  nodeLinkFieldset.hidden = !shouldShow;
  diagFieldset.hidden = !shouldShow;

  if (shouldShow) {
    nodeLinkFieldset.classList.remove("collapsed");
    diagFieldset.classList.remove("collapsed");
  }

  nodeLinkToggleBtn?.setAttribute("aria-expanded", String(shouldShow));
  diagToggleBtn?.setAttribute("aria-expanded", String(shouldShow));
});

{
  const cacheFieldset = document.getElementById("fieldset-cache");
  const cacheLegendBtn = document.getElementById("btn-toggle-cache");
  if (cacheFieldset) {
    cacheFieldset.hidden = true;
    cacheFieldset.classList.add("collapsed");
    cacheLegendBtn?.setAttribute("aria-expanded", "false");
  }
}

document.getElementById("btn-fetch-toggle-status-chk-cache")?.addEventListener("click", () => {
  const cacheFieldset = document.getElementById("fieldset-cache");
  const cacheLegendBtn = document.getElementById("btn-toggle-cache");
  if (!cacheFieldset) return;

  const shouldShow = cacheFieldset.hidden;
  cacheFieldset.hidden = !shouldShow;

  // When revealed via the fetch/status toggle, show cache controls immediately.
  if (shouldShow) {
    cacheFieldset.classList.remove("collapsed");
    cacheLegendBtn?.setAttribute("aria-expanded", "true");
  } else {
    cacheFieldset.classList.add("collapsed");
    cacheLegendBtn?.setAttribute("aria-expanded", "false");
  }
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
