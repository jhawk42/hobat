// Prevent browser from restoring scroll position on reload
if ('scrollRestoration' in history) {
  history.scrollRestoration = 'manual';
}

import { DATASET_REGISTRY, DATASOURCE_REGISTRY } from "./tdash-dataset-registry.js";
import {
  currentDataset,
  loadDataset,
  loadStaticLabelMap,
  setStaticDeviceLabel,
  enrichRows,
  enrichRawFiles,
  setForceFresh,
  setOnlyCache,
  startFetchSession,
  endFetchSession,
  cancelActiveFetchSession,
  isFetchCancelledError,
  setDatasetActivityObserver,
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
  PHYSICS_PROFILE_MESH_TREE_HORIZONTAL,
  PHYSICS_PROFILE_MESH_TREE_VERTICAL,
  PHYSICS_PROFILES,
  getPhysicsProfileLabel,
} from "./tdash-constants.js";
import {
  bindDeviceDetailsSectionFields,
  initDetailPanelToggles,
  formatAgo,
  formatDuration,
  toFiniteNumber,
  getColumnValue,
  toText,
  DEVICE_SELECTION_EVENT,
  publishDeviceSelection,
} from "./tdash-utils.js";
import {
  populateFilterSelects,
  populateDiagnosticFilterBySource,
  populateDiagnosticFilterBySourceWithCapabilities,
  aggregateNetworkDiagnosticsForRows,
  evaluateDiagnosticsForRecord,
  selectHighestQualifyingDiagnosticEvaluations,
} from "./tdash-filters.js";
import { parseSearchQuery, filterRowsBySearch } from "./tdash-search.js";
import {
  activateViewStatus,
  configureViewStatusPresenter,
  supersedeViewStatus,
} from "./tdash-view-status.js";
import {
  exportHealthAssessment,
  fetchHealthAssessment,
  fetchHealthDevice,
  fetchHealthSupport,
  renderDeviceHealth,
  renderHealthInsights,
  renderHealthStatus,
} from "./tdash-health.js";

configureViewStatusPresenter((status) => {
  const statusEl = document.getElementById("view-status-line-content");
  if (statusEl) statusEl.textContent = status;
});

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
  const defaultDatasetValue = sourceFilter
    ? DATASOURCE_REGISTRY.find((entry) => entry.value === sourceFilter)?.default_dataset_value
    : null;

  let currentGroupLabel = undefined;
  let currentOptgroup = null;
  let defaultOption = null;

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
    if (entry.value === defaultDatasetValue) {
      opt.selected = true;
      defaultOption = opt;
    }

    // Append to optgroup if one exists, otherwise to select element
    (currentOptgroup ?? sel).appendChild(opt);
  }

  if (!defaultOption) {
    sel.selectedIndex = filteredRegistry.length > 0 ? 0 : -1;
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
const WORKSPACE_ACTIVITY_LIMIT = 100;
const workspaceActivity = [];
const healthInsightsState = {
  assessment: null,
  datasetId: null,
  error: "",
  loading: false,
  assessmentRequestVersion: 0,
  device: null,
  deviceError: "",
  deviceLoading: false,
  deviceRequestVersion: 0,
  capabilities: null,
  observations: null,
};

function renderWorkspaceLogs() {
  const contentEl = document.getElementById("workspace-log-content");
  if (!contentEl) return;
  contentEl.replaceChildren();

  if (workspaceActivity.length === 0) {
    const emptyEl = document.createElement("p");
    emptyEl.textContent = "No browser activity logged yet.";
    contentEl.appendChild(emptyEl);
    return;
  }

  const listEl = document.createElement("ol");
  listEl.className = "workspace-log-list";
  [...workspaceActivity].reverse().forEach(({ timestamp, type, message, metadata }) => {
    const itemEl = document.createElement("li");
    const timeEl = document.createElement("time");
    const date = new Date(timestamp);
    timeEl.dateTime = date.toISOString();
    timeEl.textContent = date.toLocaleTimeString();

    const typeEl = document.createElement("strong");
    typeEl.textContent = type;
    const messageEl = document.createElement("span");
    messageEl.textContent = message;
    itemEl.append(timeEl, typeEl, messageEl);

    if (metadata && Object.keys(metadata).length > 0) {
      const metadataEl = document.createElement("code");
      metadataEl.textContent = JSON.stringify(metadata);
      itemEl.appendChild(metadataEl);
    }
    listEl.appendChild(itemEl);
  });
  contentEl.appendChild(listEl);
}

function recordWorkspaceActivity(type, message, metadata = {}) {
  workspaceActivity.push({ timestamp: Date.now(), type, message, metadata });
  if (workspaceActivity.length > WORKSPACE_ACTIVITY_LIMIT) {
    workspaceActivity.splice(0, workspaceActivity.length - WORKSPACE_ACTIVITY_LIMIT);
  }
  if (currentView === "logs") renderWorkspaceLogs();
}

setDatasetActivityObserver(({ type, metadata }) => {
  const messages = {
    "api-request": "API request started",
    "api-response": "API response received",
    "api-error": "API request failed",
    "job-status": "Asynchronous job status changed",
    "job-cancel-requested": "Asynchronous job cancellation requested",
  };
  recordWorkspaceActivity(type, messages[type] || "Dataset activity", metadata);
});

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

const lastRenderedDatasetByView = new Map();

function renderCurrentView({ force = false } = {}) {
  if (!currentDataset) return;
  renderNetworkInsights();
  const view = currentView;
  if (view !== "topology" && view !== "table") return;
  activateViewStatus(view, currentDataset);
  if (!force && lastRenderedDatasetByView.get(view) === currentDataset) return;

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
      currentDataset,
    );
    const counts = getTopologyDatasetCounts();
    if (counts) updateDeviceStatusBar(counts);
  } else if (view === "table") {
    renderTableForDataset(effectiveDataset, currentDataset);
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

  // Reapply the active search after a re-render so topology view keeps the
  // same filtered state when switching views or reloading a dataset.
  if (_currentSearchQuery) {
    applySearch();
  }

  lastRenderedDatasetByView.set(view, currentDataset);
}

function getPhysicsProfileSelect() {
  return document.getElementById("physics-profile-select");
}

function getSelectedDatasetEntry() {
  const selectedValue = document.getElementById("dataset-select")?.value;
  return DATASET_REGISTRY.find((entry) => entry.value === selectedValue) || null;
}

function getEffectivePhysicsProfileName(entry = getSelectedDatasetEntry()) {
  // Manual user selection (not auto) has highest precedence
  if (_physicsProfileName !== PHYSICS_PROFILE_AUTO) return _physicsProfileName;

  const isMeshTreeProfile = (profileName) =>
    profileName === PHYSICS_PROFILE_MESH_TREE_HORIZONTAL
    || profileName === PHYSICS_PROFILE_MESH_TREE_VERTICAL;
  
  // Mesh-tree profiles are manual-only for initial rollout (Phase 6).
  if (entry?.defaultPhysicsProfile && !isMeshTreeProfile(entry.defaultPhysicsProfile)) {
    return entry.defaultPhysicsProfile;
  }

  return PHYSICS_PROFILE_MESH_BASELINE;
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
    statusEl.textContent = `Showing: no dataset loaded. Select a dataset and click Sync. Physics profile: ${getPhysicsProfileStatusLabel()}.`;
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
      renderCurrentView({ force: true });
    }
  });
}

// ── Section 7: View Toggle ────────────────────────────────────────────────────

let topologyResizeObserver = null;
let topologyResizeFrame = null;

function fitTopologyToContainer() {
  const network = getVisNetwork();
  const container = document.getElementById("topology-view");
  if (!network || !container || container.clientWidth === 0 || container.clientHeight === 0) return;
  network.setSize(`${container.clientWidth}px`, `${container.clientHeight}px`);
  network.redraw();
  network.fit({ animation: { duration: 220, easingFunction: "easeInOutQuad" } });
}

function resizeAndFitTopology() {
  const container = document.getElementById("topology-view");
  if (container && !topologyResizeObserver && typeof ResizeObserver === "function") {
    topologyResizeObserver = new ResizeObserver(() => {
      if (topologyResizeFrame !== null) cancelAnimationFrame(topologyResizeFrame);
      topologyResizeFrame = requestAnimationFrame(() => {
        topologyResizeFrame = null;
        fitTopologyToContainer();
      });
    });
    topologyResizeObserver.observe(container);
  }
  requestAnimationFrame(fitTopologyToContainer);
}

function handleDetailsPanelVisibilityChanged(isCollapsed) {
  document.querySelector(".dashboard-shell")?.classList.toggle(
    "details-panel-collapsed",
    isCollapsed,
  );
  resizeAndFitTopology();
}

function setFunctionsPanelCollapsed(isCollapsed) {
  const shell = document.querySelector(".dashboard-shell");
  const toggleButton = document.getElementById("btn-functions-panel-toggle");
  shell?.classList.toggle("functions-panel-collapsed", isCollapsed);
  if (toggleButton) {
    const action = isCollapsed ? "Expand" : "Collapse";
    toggleButton.title = `${action} functions panel`;
    toggleButton.setAttribute("aria-label", `${action} functions panel`);
    toggleButton.setAttribute("aria-expanded", String(!isCollapsed));
    toggleButton.textContent = isCollapsed ? "▶" : "◀";
  }
  resizeAndFitTopology();
}

document.getElementById("btn-functions-panel-toggle")?.addEventListener("click", () => {
  const shell = document.querySelector(".dashboard-shell");
  setFunctionsPanelCollapsed(!shell?.classList.contains("functions-panel-collapsed"));
});

function setNavigationPanelCollapsed(isCollapsed) {
  const shell = document.querySelector(".dashboard-shell");
  const toggleButton = document.getElementById("btn-navigation-panel-toggle");
  shell?.classList.toggle("navigation-panel-collapsed", isCollapsed);
  if (toggleButton) {
    const action = isCollapsed ? "Show icons and labels" : "Show icons only";
    toggleButton.title = action;
    toggleButton.setAttribute("aria-label", action);
    toggleButton.setAttribute("aria-expanded", String(!isCollapsed));
    toggleButton.textContent = isCollapsed ? "▶" : "◀";
  }
  resizeAndFitTopology();
}

document.getElementById("btn-navigation-panel-toggle")?.addEventListener("click", () => {
  const shell = document.querySelector(".dashboard-shell");
  setNavigationPanelCollapsed(!shell?.classList.contains("navigation-panel-collapsed"));
});

const WORKSPACE_VIEWS = Object.freeze([
  {
    view: "topology",
    buttonId: "btn-topology",
    panelId: "view-topology",
    rendersDataset: true,
    onActivate: resizeAndFitTopology,
  },
  { view: "table", buttonId: "btn-table", panelId: "view-table", rendersDataset: true },
  {
    view: "insights",
    buttonId: "btn-insights",
    panelId: "view-insights",
    onActivate: renderNetworkInsights,
  },
  { view: "settings", buttonId: "btn-settings", panelId: "view-settings" },
  {
    view: "logs",
    buttonId: "btn-logs",
    panelId: "view-logs",
    onActivate: renderWorkspaceLogs,
  },
]);

function switchView(newView) {
  const nextView = WORKSPACE_VIEWS.find(({ view }) => view === newView);
  if (!nextView) return;
  if (newView === currentView) return;
  currentView = newView;

  WORKSPACE_VIEWS.forEach(({ view, buttonId, panelId }) => {
    const isActive = view === newView;
    const buttonEl = document.getElementById(buttonId);
    const panelEl = document.getElementById(panelId);

    if (panelEl) panelEl.hidden = !isActive;
    if (buttonEl) {
      buttonEl.classList.toggle("active", isActive);
      buttonEl.setAttribute("aria-selected", String(isActive));
      buttonEl.tabIndex = isActive ? 0 : -1;
    }
  });

  const moreInfoButton = document.getElementById("btn-more-info");
  if (moreInfoButton) moreInfoButton.hidden = newView !== "table";

  const linkFilterEl = document.getElementById("link-filter");
  linkFilterEl.classList.toggle("filter-disabled", newView !== "topology");

  if (newView === "topology") {
    resetNodeDetailsLists();
  } else if (newView === "table") {
    document.getElementById("details-list").innerHTML = "";
    const summaryListEl = document.getElementById("summary-list");
    if (summaryListEl)
      summaryListEl.innerHTML = "<li>Click a node or row to view its properties.</li>";
  }

  if (currentDataset && nextView.rendersDataset) {
    renderCurrentView();
  }
  nextView.onActivate?.();
}

WORKSPACE_VIEWS.forEach(({ view, buttonId }, index) => {
  const buttonEl = document.getElementById(buttonId);
  buttonEl?.addEventListener("click", () => switchView(view));
  buttonEl?.addEventListener("keydown", (event) => {
    const navigationKeys = ["ArrowLeft", "ArrowRight", "Home", "End"];
    if (!navigationKeys.includes(event.key)) return;

    event.preventDefault();
    let nextIndex = index;
    if (event.key === "ArrowLeft") {
      nextIndex = (index - 1 + WORKSPACE_VIEWS.length) % WORKSPACE_VIEWS.length;
    } else if (event.key === "ArrowRight") {
      nextIndex = (index + 1) % WORKSPACE_VIEWS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = WORKSPACE_VIEWS.length - 1;
    }

    const nextView = WORKSPACE_VIEWS[nextIndex];
    document.getElementById(nextView.buttonId)?.focus();
    switchView(nextView.view);
  });
});

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
  renderDeviceInsights(deviceInsightsState.record);
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
  publishDeviceSelection(null);
}

const DEVICE_EXTADDRESS_PATTERN = /^[0-9a-f]{16}$/;
const DEVICE_LABEL_CONTROL_PATTERN = /[\u0000-\u001f\u007f-\u009f]/u;
const DEVICE_LABEL_MAX_LENGTH = 128;
const deviceSettingsState = {
  record: null,
  projection: null,
  loadedLabel: "",
  requestVersion: 0,
  loading: false,
  saving: false,
};

function getSelectedValue(record, paths) {
  for (const path of paths) {
    const value = getColumnValue(record, path);
    if (value !== undefined && value !== null && toText(value)) return toText(value);
  }
  return "";
}

function projectSelectedDevice(record) {
  if (!record || typeof record !== "object") return null;
  const extAddress = getSelectedValue(record, [
    "extAddress", "extaddr", "Extended MAC",
    "attributes.extAddress", "attributes.extaddr",
  ]).trim().toLowerCase();
  return {
    rloc16: getSelectedValue(record, ["rloc16", "attributes.rloc16"]),
    extAddress,
    deviceLabel: getSelectedValue(record, [
      "deviceLabel", "device_label",
      "attributes.deviceLabel", "attributes.device_label",
    ]).trim(),
    name: getSelectedValue(record, ["name", "attributes.name"]),
    hasValidExtAddress: DEVICE_EXTADDRESS_PATTERN.test(extAddress),
  };
}

function getDeviceLabelValidationError(value) {
  const label = value.trim();
  if (!label) return "Device label is required.";
  if (label.length > DEVICE_LABEL_MAX_LENGTH) {
    return `Device label must be ${DEVICE_LABEL_MAX_LENGTH} characters or fewer.`;
  }
  if (DEVICE_LABEL_CONTROL_PATTERN.test(label)) {
    return "Device label cannot contain control characters.";
  }
  return "";
}

function setDeviceSettingsStatus(message = "", isError = false) {
  const statusEl = document.getElementById("device-settings-status");
  if (!statusEl) return;
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function updateDeviceSettingsControls() {
  const inputEl = document.getElementById("device-label");
  const saveEl = document.getElementById("btn-device-settings-save");
  const cancelEl = document.getElementById("btn-device-settings-cancel");
  if (!inputEl || !saveEl || !cancelEl) return;

  const hasDevice = deviceSettingsState.projection?.hasValidExtAddress === true;
  const pending = deviceSettingsState.loading || deviceSettingsState.saving;
  const currentLabel = inputEl.value.trim();
  const changed = currentLabel !== deviceSettingsState.loadedLabel;
  inputEl.disabled = !hasDevice || pending;
  saveEl.disabled = !hasDevice || pending || !changed || Boolean(getDeviceLabelValidationError(inputEl.value));
  cancelEl.disabled = !hasDevice || pending || !changed;
}

function displaySelectedDevice(record, loadedLabel = null) {
  deviceSettingsState.requestVersion += 1;
  const candidateProjection = projectSelectedDevice(record);
  const hasValidSelection = candidateProjection?.hasValidExtAddress === true;
  deviceSettingsState.record = hasValidSelection ? record : null;
  deviceSettingsState.projection = hasValidSelection ? candidateProjection : null;
  deviceSettingsState.loading = false;
  deviceSettingsState.saving = false;

  const projection = deviceSettingsState.projection;
  const fallbackLabel = projection?.deviceLabel ?? "";
  deviceSettingsState.loadedLabel = loadedLabel ?? fallbackLabel;
  document.getElementById("device-rloc16").textContent = projection?.rloc16 ?? "";
  document.getElementById("device-extaddress").textContent = projection?.extAddress ?? "";
  document.getElementById("device-label").value = deviceSettingsState.loadedLabel;
  document.getElementById("device-name").textContent = projection?.name ?? "";
  document.getElementById("device-name-row").hidden = !projection?.name;
  setDeviceSettingsStatus();
  updateDeviceSettingsControls();
}

async function loadSelectedDeviceLabel() {
  const projection = deviceSettingsState.projection;
  if (!projection?.hasValidExtAddress) return;

  const extAddress = projection.extAddress;
  const requestVersion = ++deviceSettingsState.requestVersion;
  deviceSettingsState.loading = true;
  setDeviceSettingsStatus("Loading device label...");
  updateDeviceSettingsControls();

  try {
    const response = await fetch(`/api/device/${encodeURIComponent(extAddress)}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (requestVersion !== deviceSettingsState.requestVersion ||
        extAddress !== deviceSettingsState.projection?.extAddress) return;

    if (response.status === 404) {
      deviceSettingsState.loadedLabel = projection.deviceLabel;
    } else if (response.ok) {
      const payload = await response.json();
      deviceSettingsState.loadedLabel = toText(payload.deviceLabel).trim();
    } else {
      throw new Error(`Unable to load device label (HTTP ${response.status}).`);
    }
    document.getElementById("device-label").value = deviceSettingsState.loadedLabel;
    setDeviceSettingsStatus();
  } catch (error) {
    if (requestVersion !== deviceSettingsState.requestVersion) return;
    setDeviceSettingsStatus(error.message || "Unable to load device label.", true);
  } finally {
    if (requestVersion === deviceSettingsState.requestVersion) {
      deviceSettingsState.loading = false;
      updateDeviceSettingsControls();
    }
  }
}

async function saveSelectedDeviceLabel() {
  const projection = deviceSettingsState.projection;
  const inputEl = document.getElementById("device-label");
  if (!projection?.hasValidExtAddress || deviceSettingsState.saving) return;

  const deviceLabel = inputEl.value.trim();
  const validationError = getDeviceLabelValidationError(inputEl.value);
  if (validationError) {
    setDeviceSettingsStatus(validationError, true);
    updateDeviceSettingsControls();
    return;
  }

  const extAddress = projection.extAddress;
  const selectedRecord = deviceSettingsState.record;
  const requestVersion = ++deviceSettingsState.requestVersion;
  deviceSettingsState.saving = true;
  setDeviceSettingsStatus("Saving device label...");
  updateDeviceSettingsControls();

  try {
    const response = await fetch(`/api/device/${encodeURIComponent(extAddress)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ deviceLabel }),
    });
    const payload = await response.json().catch(() => ({}));
    if (requestVersion !== deviceSettingsState.requestVersion ||
        extAddress !== deviceSettingsState.projection?.extAddress) return;
    if (!response.ok) {
      throw new Error(payload.error || `Unable to save device label (HTTP ${response.status}).`);
    }

    const savedLabel = toText(payload.deviceLabel).trim() || deviceLabel;
    setStaticDeviceLabel(extAddress, savedLabel);
    renderCurrentView({ force: true });
    displaySelectedDevice(selectedRecord, savedLabel);
    setDeviceSettingsStatus(response.status === 201 ? "Device label added." : "Device label saved.");
  } catch (error) {
    if (requestVersion !== deviceSettingsState.requestVersion) return;
    setDeviceSettingsStatus(error.message || "Unable to save device label.", true);
  } finally {
    if (requestVersion === deviceSettingsState.requestVersion) {
      deviceSettingsState.saving = false;
      updateDeviceSettingsControls();
    }
  }
}

function initDeviceSettings() {
  displaySelectedDevice(null);
  document.addEventListener(DEVICE_SELECTION_EVENT, (event) => {
    displaySelectedDevice(event.detail?.record ?? null);
    if (!document.getElementById("device-settings-panel").hidden) {
      void loadSelectedDeviceLabel();
    }
  });

  const inputEl = document.getElementById("device-label");
  inputEl.addEventListener("input", updateDeviceSettingsControls);
  inputEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void saveSelectedDeviceLabel();
    } else if (event.key === "Escape") {
      event.preventDefault();
      inputEl.value = deviceSettingsState.loadedLabel;
      setDeviceSettingsStatus();
      updateDeviceSettingsControls();
    }
  });
  document.getElementById("btn-device-settings-cancel").addEventListener("click", () => {
    inputEl.value = deviceSettingsState.loadedLabel;
    setDeviceSettingsStatus();
    updateDeviceSettingsControls();
  });
  document.getElementById("btn-device-settings-save").addEventListener("click", () => {
    void saveSelectedDeviceLabel();
  });
}

const DIAGNOSTIC_SOURCE_LABELS = Object.freeze({
  macCounters: "MAC Counters",
  mlecounters: "MLE Counters",
  time_statistics: "Time Statistics",
  link_quality: "Link Quality",
});

const NETWORK_INSIGHT_DEVICE_LIMIT = 10;

function appendNetworkInsightElement(parent, tagName, text, className = "") {
  const element = document.createElement(tagName);
  element.textContent = text;
  if (className) element.className = className;
  parent.appendChild(element);
  return element;
}

function selectNetworkInsightConditions(conditions) {
  const selectedByGroup = new Map();
  conditions.forEach((condition) => {
    const groupKey = condition.option.group ?? condition.option.value;
    const selected = selectedByGroup.get(groupKey);
    if (condition.triggeredDeviceCount > 0 || !selected) {
      selectedByGroup.set(groupKey, condition);
    }
  });
  return [...selectedByGroup.values()];
}

function renderNetworkInsightCondition(parent, condition, eligibleDeviceCount) {
  const itemEl = document.createElement("li");
  const triggered = condition.triggeredDeviceCount > 0;
  itemEl.className = [
    "network-insight-item",
    `severity-${condition.option.severity}`,
    triggered ? "is-triggered" : "is-observed",
  ].join(" ");
  appendNetworkInsightElement(itemEl, "h4", condition.option.label);

  if (condition.observedDeviceCount > 0) {
    const range = condition.minMetricText === condition.maxMetricText
      ? condition.minMetricText
      : `${condition.minMetricText} to ${condition.maxMetricText}`;
    appendNetworkInsightElement(
      itemEl,
      "p",
      `${condition.observedDeviceCount}/${eligibleDeviceCount} devices report values; range ${range}; ${condition.nonTriggeredDeviceCount} not triggering this condition.`,
      "network-insight-observed",
    );
  }

  if (!triggered) return itemEl;

  appendNetworkInsightElement(
    itemEl,
    "p",
    `${condition.option.severity}: ${condition.triggeredDeviceCount} affected device${condition.triggeredDeviceCount === 1 ? "" : "s"}.`,
    "network-insight-triggered",
  );
  const deviceListEl = document.createElement("ul");
  deviceListEl.className = "network-insight-device-list";
  condition.triggeredDevices.slice(0, NETWORK_INSIGHT_DEVICE_LIMIT).forEach((device) => {
    appendNetworkInsightElement(deviceListEl, "li", device.displayName);
  });
  itemEl.appendChild(deviceListEl);

  const remainingCount = condition.triggeredDeviceCount - NETWORK_INSIGHT_DEVICE_LIMIT;
  if (remainingCount > 0) {
    appendNetworkInsightElement(
      itemEl,
      "p",
      `${remainingCount} additional affected devices.`,
      "network-insight-remaining",
    );
  }
  return itemEl;
}

function renderNetworkInsights() {
  const contentEl = document.getElementById("network-insights-content");
  if (!contentEl) return;
  const healthEligible = currentDataset?.entry?.healthEligible === true;
  document.getElementById("health-insights-filters")?.toggleAttribute("hidden", !healthEligible);
  if (healthEligible) {
    renderHealthInsights(contentEl, healthInsightsState, {
      status: document.getElementById("health-status-filter")?.value ?? "all",
      scope: document.getElementById("health-scope-filter")?.value ?? "all",
    });
    return;
  }
  contentEl.replaceChildren();

  if (!currentDataset) {
    appendNetworkInsightElement(
      contentEl,
      "p",
      "Load a dataset to view network diagnostic insights.",
      "network-insights-empty",
    );
    return;
  }

  const model = aggregateNetworkDiagnosticsForRows(currentDataset.rows);
  if (model.eligibleDeviceCount === 0) {
    appendNetworkInsightElement(
      contentEl,
      "p",
      "No eligible Thread devices are available in this dataset.",
      "network-insights-empty",
    );
    return;
  }
  if (model.evaluableDeviceCount === 0) {
    appendNetworkInsightElement(
      contentEl,
      "p",
      "Eligible Thread devices do not provide diagnostic metrics.",
      "network-insights-empty",
    );
    return;
  }

  appendNetworkInsightElement(
    contentEl,
    "p",
    `${model.evaluableDeviceCount}/${model.eligibleDeviceCount} Thread devices provide diagnostic metrics.`,
    "network-insights-coverage",
  );
  model.sources.forEach((source) => {
    const sectionEl = document.createElement("section");
    sectionEl.className = "network-insights-source";
    appendNetworkInsightElement(
      sectionEl,
      "h3",
      DIAGNOSTIC_SOURCE_LABELS[source.source] ?? source.source,
    );
    const listEl = document.createElement("ul");
    listEl.className = "network-insights-list";
    selectNetworkInsightConditions(source.conditions).forEach((condition) => {
      listEl.appendChild(renderNetworkInsightCondition(
        listEl,
        condition,
        model.eligibleDeviceCount,
      ));
    });
    sectionEl.appendChild(listEl);
    contentEl.appendChild(sectionEl);
  });
}

const deviceInsightsState = {
  record: null,
};

function appendDeviceInsightElement(parent, tagName, text, className = "") {
  const element = document.createElement(tagName);
  element.textContent = text;
  if (className) element.className = className;
  parent.appendChild(element);
  return element;
}

function renderDeviceInsights(record) {
  const contentEl = document.getElementById("device-insights-panel-content");
  if (!contentEl) return;
  if (currentDataset?.entry?.healthEligible === true) {
    renderDeviceHealth(contentEl, {
      device: healthInsightsState.device,
      error: healthInsightsState.deviceError,
      loading: healthInsightsState.deviceLoading,
    });
    return;
  }
  contentEl.replaceChildren();

  if (!record) {
    appendDeviceInsightElement(
      contentEl,
      "p",
      "Select a device to view diagnostic insights.",
      "device-insights-empty",
    );
    return;
  }

  const projection = projectSelectedDevice(record);
  const identity = projection.deviceLabel || projection.name || projection.rloc16 ||
    projection.extAddress || "Selected device";
  appendDeviceInsightElement(contentEl, "h3", identity, "device-insights-title");

  const evaluations = selectHighestQualifyingDiagnosticEvaluations(
    evaluateDiagnosticsForRecord(record, currentView)
      .filter((evaluation) =>
        evaluation.triggered || (isMoreInfoEnabled() && evaluation.metricText),
      ),
  );
  if (evaluations.length === 0) {
    appendDeviceInsightElement(
      contentEl,
      "p",
      "No diagnostic metrics are available for this device.",
      "device-insights-empty",
    );
    return;
  }

  const evaluationsBySource = new Map();
  evaluations.forEach((evaluation) => {
    const source = evaluation.option.source;
    const sourceEvaluations = evaluationsBySource.get(source) ?? [];
    sourceEvaluations.push(evaluation);
    evaluationsBySource.set(source, sourceEvaluations);
  });

  evaluationsBySource.forEach((sourceEvaluations, source) => {
    const sectionEl = document.createElement("section");
    sectionEl.className = "device-insights-source";
    appendDeviceInsightElement(
      sectionEl,
      "h4",
      DIAGNOSTIC_SOURCE_LABELS[source] ?? source,
    );
    const listEl = document.createElement("ul");
    listEl.className = "device-insights-list";

    sourceEvaluations.forEach((evaluation) => {
      const { option, metricText, thresholdText, triggered } = evaluation;
      const itemEl = document.createElement("li");
      itemEl.className = [
        "device-insight-item",
        `severity-${option.severity}`,
        triggered ? "is-triggered" : "is-observed",
      ].join(" ");
      const valueText = metricText ?? "Triggered";
      itemEl.textContent = `${option.label}: ${valueText} (${thresholdText})`;
      listEl.appendChild(itemEl);
    });

    sectionEl.appendChild(listEl);
    contentEl.appendChild(sectionEl);
  });
}

function initDeviceInsights() {
  renderDeviceInsights(null);
  document.addEventListener(DEVICE_SELECTION_EVENT, (event) => {
    deviceInsightsState.record = event.detail?.record ?? null;
    void refreshSelectedDeviceHealth(deviceInsightsState.record);
  });
}

async function refreshSelectedDeviceHealth(record) {
  const projection = projectSelectedDevice(record);
  const requestVersion = ++healthInsightsState.deviceRequestVersion;
  healthInsightsState.device = null;
  healthInsightsState.deviceError = "";
  healthInsightsState.capabilities = null;
  healthInsightsState.observations = null;
  healthInsightsState.deviceLoading = false;
  if (currentDataset?.entry?.healthEligible !== true) {
    renderDeviceInsights(record);
    return;
  }
  if (!projection?.hasValidExtAddress || !healthInsightsState.assessment) {
    renderDeviceInsights(record);
    return;
  }
  healthInsightsState.deviceLoading = true;
  renderDeviceInsights(record);
  try {
    const deviceId = `extaddr:${projection.extAddress}`;
    const device = await fetchHealthDevice(
      healthInsightsState.assessment.assessmentId,
      deviceId,
    );
    if (requestVersion !== healthInsightsState.deviceRequestVersion) return;
    healthInsightsState.device = device;
  } catch (error) {
    if (requestVersion !== healthInsightsState.deviceRequestVersion) return;
    healthInsightsState.deviceError = error.message;
  } finally {
    if (requestVersion === healthInsightsState.deviceRequestVersion) {
      healthInsightsState.deviceLoading = false;
      renderDeviceInsights(record);
    }
  }
}

async function refreshHealthAssessment() {
  const entry = currentDataset?.entry;
  healthInsightsState.assessment = null;
  healthInsightsState.datasetId = entry?.value ?? null;
  healthInsightsState.error = "";
  healthInsightsState.device = null;
  healthInsightsState.deviceError = "";
  const statusEl = document.getElementById("health-status-summary");
  if (entry?.healthEligible !== true) {
    healthInsightsState.loading = false;
    renderHealthStatus(statusEl, healthInsightsState);
    renderNetworkInsights();
    return;
  }

  const requestVersion = ++healthInsightsState.assessmentRequestVersion;
  healthInsightsState.loading = true;
  renderHealthStatus(statusEl, healthInsightsState);
  renderNetworkInsights();
  try {
    const assessment = await fetchHealthAssessment(entry.value);
    if (requestVersion !== healthInsightsState.assessmentRequestVersion) return;
    healthInsightsState.assessment = assessment;
    try {
      const support = await fetchHealthSupport(assessment.networkId);
      if (requestVersion !== healthInsightsState.assessmentRequestVersion) return;
      healthInsightsState.capabilities = support.capabilities;
      healthInsightsState.observations = support.observations;
    } catch (error) {
      console.warn("Health history metadata is unavailable:", error);
    }
  } catch (error) {
    if (requestVersion !== healthInsightsState.assessmentRequestVersion) return;
    healthInsightsState.error = error.message;
  } finally {
    if (requestVersion === healthInsightsState.assessmentRequestVersion) {
      healthInsightsState.loading = false;
      renderHealthStatus(statusEl, healthInsightsState);
      renderNetworkInsights();
    }
  }
}

document.getElementById("health-status-filter")?.addEventListener("change", renderNetworkInsights);
document.getElementById("health-scope-filter")?.addEventListener("change", renderNetworkInsights);
document.getElementById("btn-health-export")?.addEventListener("click", () => {
  exportHealthAssessment(healthInsightsState.assessment);
});

const DEVICE_DETAILS_PANEL_TABS = [
  {
    buttonId: "btn-device-details-properties",
    panelId: "device-properties-panel",
  },
  {
    buttonId: "btn-device-details-insights",
    panelId: "device-insights-panel",
  },
  {
    buttonId: "btn-device-details-settings",
    panelId: "device-settings-panel",
  },
];

function setActiveDeviceDetailsPanel(activePanelId) {
  DEVICE_DETAILS_PANEL_TABS.forEach(({ buttonId, panelId }) => {
    const buttonEl = document.getElementById(buttonId);
    const panelEl = document.getElementById(panelId);
    const isActive = panelId === activePanelId;

    if (panelEl) {
      panelEl.hidden = !isActive;
      panelEl.setAttribute("aria-hidden", String(!isActive));
    }

    if (buttonEl) {
      buttonEl.classList.toggle("active", isActive);
      buttonEl.setAttribute("aria-pressed", String(isActive));
      buttonEl.setAttribute("aria-selected", String(isActive));
      buttonEl.tabIndex = isActive ? 0 : -1;
    }
  });
  if (activePanelId === "device-settings-panel") {
    void loadSelectedDeviceLabel();
  }
}

function initDeviceDetailsPanelTabs() {
  const defaultPanelId = "device-properties-panel";
  setActiveDeviceDetailsPanel(defaultPanelId);

  const tablistEl = document.getElementById("device-details-nav-bar-left");
  if (tablistEl) {
    tablistEl.setAttribute("role", "tablist");
    tablistEl.setAttribute("aria-label", "Device details sections");
  }

  DEVICE_DETAILS_PANEL_TABS.forEach(({ buttonId, panelId }) => {
    const buttonEl = document.getElementById(buttonId);
    if (!buttonEl) return;

    buttonEl.setAttribute("role", "tab");
    buttonEl.setAttribute("aria-controls", panelId);

    buttonEl.addEventListener("click", () => {
      setActiveDeviceDetailsPanel(panelId);
    });

    buttonEl.addEventListener("keydown", (event) => {
      const navKeys = ["ArrowLeft", "ArrowRight", "Home", "End"];
      if (!navKeys.includes(event.key)) return;

      const tabs = DEVICE_DETAILS_PANEL_TABS
        .map(({ buttonId: id, panelId: targetPanelId }) => {
          const el = document.getElementById(id);
          return el ? { el, targetPanelId } : null;
        })
        .filter(Boolean);
      if (!tabs.length) return;

      const currentIndex = tabs.findIndex(({ el }) => el === event.currentTarget);
      if (currentIndex < 0) return;

      event.preventDefault();

      let nextIndex = currentIndex;
      if (event.key === "ArrowLeft") {
        nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
      } else if (event.key === "ArrowRight") {
        nextIndex = (currentIndex + 1) % tabs.length;
      } else if (event.key === "Home") {
        nextIndex = 0;
      } else if (event.key === "End") {
        nextIndex = tabs.length - 1;
      }

      const nextTab = tabs[nextIndex];
      nextTab.el.focus();
      setActiveDeviceDetailsPanel(nextTab.targetPanelId);
    });
  });
}

function resetDeviceDetailsPanelTabsToDefault() {
  setActiveDeviceDetailsPanel("device-properties-panel");
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
        statusEl.textContent = `Showing: no dataset loaded. Select a dataset and click Sync. Physics profile: ${getPhysicsProfileStatusLabel(selectedDataset)}.`;
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
  `Showing: no dataset loaded. Select a dataset and click Sync. Physics profile: ${getPhysicsProfileStatusLabel()}.`;

bindDeviceDetailsSectionFields();
initDeviceSettings();
initDeviceInsights();
renderNetworkInsights();
initDeviceDetailsPanelTabs();
initDetailPanelToggles(
  document.getElementById("device-details"),
  handleDetailsPanelVisibilityChanged,
);

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
async function doFetchDataset({ userInitiated = false } = {}) {
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
  const selectedDataset = DATASET_REGISTRY.find((entry) => entry.value === selectedValue);
  supersedeViewStatus(`Loading ${selectedDataset?.label ?? selectedValue}…`);
  recordWorkspaceActivity("dataset-sync", "Dataset sync started", {
    dataset: selectedValue,
    userInitiated,
  });
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
    if (["topology", "table"].includes(selectedDataset?.defaultView)) {
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
      recordWorkspaceActivity("dataset-sync", "Dataset sync cancelled", {
        dataset: selectedValue,
      });
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
          activateViewStatus(currentView, currentDataset);
          renderCurrentView();
          updateFetchStatusBar(_lastFetchStartedAt);
        } else {
          _setStatusSpans(_FETCH_STATUS_IDS, "—");
          _setStatusSpans(_DEVICE_STATUS_IDS, "—");
        }
      }
    } else {
      recordWorkspaceActivity("dataset-sync", "Dataset sync failed", {
        dataset: selectedValue,
        error: err?.message || String(err),
      });
      console.error("loadDataset threw:", err);
      supersedeViewStatus(`Error loading "${selectedValue}": ${err?.message || String(err)}`);
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
    supersedeViewStatus(`Error: could not load dataset "${selectedValue}".`);
    recordWorkspaceActivity("dataset-sync", "Dataset sync produced no usable data", {
      dataset: selectedValue,
    });
    return;
  }

  // Cancel any pending incremental render — final reconciliation render takes over.
  if (_incrementalRenderTimer !== null) { clearTimeout(_incrementalRenderTimer); _incrementalRenderTimer = null; }

  // Reset search state when a new dataset is loaded
  _currentSearchQuery = "";
  const _srchInput = document.getElementById("search-input");
  if (_srchInput) _srchInput.value = "";

  // Final reconciliation render: all files settled, isPartial is false.
  resetDeviceDetailsPanelTabsToDefault();
  renderCurrentView();
  void refreshHealthAssessment();
  updateFetchStatusBar(_lastFetchStartedAt);
  if (currentDataset?.fetchMetrics) {
    const fetchMetricsPayload = {
      dataset: currentDataset.entry?.value,
      ...currentDataset.fetchMetrics,
    };
    //console.info("[tdash] fetch metrics", fetchMetricsPayload);
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
  recordWorkspaceActivity("dataset-sync", "Dataset sync completed", {
    dataset: selectedValue,
    durationMs: currentDataset.fetchDurationMs,
    loadedFiles: currentDataset.loadedFiles?.length ?? 0,
    totalFiles: currentDataset.entry?.files?.length ?? 0,
  });
}

// Fetch button drives data acquisition.
document.getElementById("btn-fetch").addEventListener("click", () => {
  void doFetchDataset({ userInitiated: true });
});

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
      "No dataset loaded. Select a dataset and click Sync.";
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
  } else {
    setForceFresh(false);
  }
});

document.getElementById("chk-only-cache").addEventListener("change", (e) => {
  if (e.target.checked) {
    updateCacheCheckboxes(e.target);
  } else {
    setOnlyCache(false);
  }
});

// ── Collapsible cache-options fieldsets and containers ─────────────────────────────────────

const COLLAPSE_CONTAINER_BY_BUTTON_ID = {
  "btn-toggle-devices": "device-status",
  "btn-toggle-panel-dataset": "panel-dataset",
  "btn-toggle-filters": "panel-node-link-filters",
};

["btn-toggle-cache", "btn-toggle-status", "btn-toggle-devices", "btn-toggle-panel-dataset", "btn-toggle-filters", "btn-toggle-node-link-filters", "btn-toggle-diag-filters"].forEach((id) => {
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

