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
import { initDetailPanelToggles } from "./tdash-utils.js";

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
  } else {
    renderTableForDataset(effectiveDataset);
  }
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
      "#identity-list, #highlights-list, #connections-list, #counters-list, #details-list",
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

    //## make optional to oad dataset and render immediately on select change; for now, 
    //## require explicit Fetch button click to do so, to avoid accidental dataset loads while exploring the dropdown.

    //## await loadDataset(event.target.value);
    //## renderCurrentView();
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

// ── Bootstrap ─────────────────────────────────────────────────────────────────

const initialSource = document.getElementById("datasource-filter").value;
populateDatasetSelect(initialSource);
applyLegendLineStylesFromConstants();
await loadStaticLabelMap();
// Phase 3 (task 3.1): do not auto-load on startup; prompt the user instead.
document.getElementById("status").textContent =
  "Select a dataset and press Fetch.";

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

// Fetch dataset function
async function doFetchDataset() {
  const selectedValue = document.getElementById("dataset-select").value;
  if (!selectedValue) return;

  // Apply defaultView from registry if auto-view is enabled
  const autoViewEnabled = document.getElementById("chk-auto-view").checked;
  if (autoViewEnabled) {
    const selectedDataset = DATASET_REGISTRY.find((entry) => entry.value === selectedValue);
    if (selectedDataset && selectedDataset.defaultView) {
      switchView(selectedDataset.defaultView);
    }
  }

  await loadDataset(selectedValue);
  renderCurrentView();
}

// Phase 3 (task 3.5): Fetch button drives data acquisition.
document.getElementById("btn-fetch").addEventListener("click", doFetchDataset);

// Auto-fetch when dataset is selected and chk-auto-fetch is enabled
document.getElementById("dataset-select").addEventListener("change", async () => {
  if (document.getElementById("chk-auto-fetch").checked) {
    await doFetchDataset();
  }
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

// ── Collapsible Filters Panel ────────────────────────────────────────────────

document.getElementById("btn-toggle-filters").addEventListener("click", () => {
  const btn = document.getElementById("btn-toggle-filters");
  const content = document.getElementById("filters-content");
  const isExpanded = btn.getAttribute("aria-expanded") === "true";

  btn.setAttribute("aria-expanded", !isExpanded);
  content.classList.toggle("collapsed");
});
