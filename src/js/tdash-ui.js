// Prevent browser from restoring scroll position on reload
if ('scrollRestoration' in history) {
  history.scrollRestoration = 'manual';
}

import { DATASET_REGISTRY, DATASOURCE_REGISTRY, DATASET_CATALOG_FALLBACK, setDatasetCatalog } from "./tdash-dataset-registry.js";
import {
  EMPTY_CAPABILITIES,
  datasetIsAvailable,
  isFileCached,
  loadSourceCapabilities,
  sourceIsAvailable,
} from "./tdash-capabilities.js";
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
  setTopologyHealthFindings,
  setAutoZoomEnabled,
  setAnimationEnabled,
  isAutoZoomEnabled,
  isAnimationEnabled,
  setOnPhysicsDisabledCallback,
} from "./tdash-topology-renderer.js";
import {
  renderTableForDataset,
  applyTableFilters,
  getTableColumnCategories,
  setTableHealthFindings,
  setTableColumnCategory,
  setMoreInfoEnabled,
  isMoreInfoEnabled,
} from "./tdash-table-renderer.js";
import { runAdaptor } from "./tdash-adaptors.js";
import { projectObservedTopologyLinkCounts } from "./tdash-adaptor-model.js";
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
  initContextDetailsPanel,
  initDetailPanelToggles,
  formatAgo,
  formatDuration,
  toFiniteNumber,
  getColumnValue,
  toText,
  DEVICE_SELECTION_EVENT,
  publishDeviceSelection,
} from "./tdash-utils.js";
import { canonicalizeExtAddress, getDeviceIdentityKeys } from "./tdash-device-fields.js";
import {
  populateFilterSelects,
  populateDiagnosticFilterBySource,
  populateDiagnosticFilterBySourceWithCapabilities,
  aggregateNetworkDiagnosticsForRows,
  evaluateDiagnosticsForRecord,
  selectHighestQualifyingDiagnosticEvaluations,
  getRowRoleProjection,
  computeRowCounts,
} from "./tdash-filters.js";
import { parseSearchQuery, filterRowsBySearch } from "./tdash-search.js";
import {
  activateViewStatus,
  configureViewStatusPresenter,
  networkInstanceStatus,
  supersedeViewStatus,
} from "./tdash-view-status.js";
import {
  clearActivityEntries,
  getActivityEntries,
  recordActivity,
  subscribeActivity,
  trackedFetch,
} from "./tdash-activity.js";
import {
  exportHealthAssessment,
  cancelHealthJob,
  fetchHealthJob,
  fetchHealthAssessment,
  fetchHealthDevice,
  fetchHealthRoster,
  fetchHealthRosterDevice,
  fetchHealthComparisons,
  fetchHealthComparison,
  isComparisonPageForAssessment,
  fetchHealthSupport,
  projectHealthFindingDetail,
  projectVisibleHealthFindingGroups,
  projectHealthSummaryRows,
  reconcileHealthInsightsSelection,
  renderDeviceHealth,
  renderHealthFindingDetails,
  renderHealthInsights,
  renderHealthRoster,
  renderHealthRosterDetail,
  renderHealthComparison,
  renderHealthStatus,
  startHealthProcessing,
} from "./tdash-health.js";
import {
  DEVICE_ACTIONS,
  buildDeviceDiagnosticsModel,
  deviceActionStatusLabel,
} from "./tdash-device-diagnostics.js";

configureViewStatusPresenter((status) => {
  const statusEl = document.getElementById("view-status-line-content");
  if (statusEl) statusEl.textContent = currentDataset?.entry
    ? `${status} | ${networkInstanceStatus(currentDataset.loadedFiles ?? currentDataset.entry.files, sourceCapabilities)}`
    : status;
});

// ── Build datasource <select> ────────────────────────────────────────

function populateDatasourceSelect(capabilities) {
  const sel = document.getElementById("datasource-filter");
  sel.innerHTML = ""; // Clear existing options

  for (let i = 0; i < DATASOURCE_REGISTRY.length; i++) {
    const entry = DATASOURCE_REGISTRY[i];
    if (!sourceIsAvailable(entry.value, capabilities)) continue;
    const opt = document.createElement("option");
    opt.value = entry.value;
    opt.textContent = entry.label;
    opt.title = entry.label;
    sel.appendChild(opt);
  }
  if (sel.options.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "No available sources";
    opt.disabled = true;
    opt.selected = true;
    sel.appendChild(opt);
  }
}


// ── Section 2: Build dataset <select> ────────────────────────────────────────

function populateDatasetSelect(sourceFilter = null, capabilities) {
  const sel = document.getElementById("dataset-select");
  sel.innerHTML = ""; // Clear existing options

  const filteredRegistry = sourceFilter
    ? DATASET_REGISTRY.filter((entry) => entry.source === sourceFilter && datasetIsAvailable(entry, capabilities))
    : DATASET_REGISTRY.filter((entry) => datasetIsAvailable(entry, capabilities));
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
  if (filteredRegistry.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "No available datasets";
    opt.disabled = true;
    opt.selected = true;
    sel.appendChild(opt);
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
let sourceCapabilities = EMPTY_CAPABILITIES;
let _fetchInProgress = false;
let logsSubview = "logs";
let healthTopologyColoringEnabled = false;
const JOBS_POLL_MIN_DELAY_MS = 2000;
const JOBS_POLL_EMPTY_DELAY_MS = 10000;
const JOBS_POLL_MAX_DELAY_MS = 60_000;
const jobsViewState = {
  jobs: [],
  error: "",
  loading: false,
  requestVersion: 0,
  abortController: null,
  pollTimer: null,
  cancellingJobIds: new Set(),
};
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
  roster: null,
  rosterDetail: null,
  rosterError: "",
  rosterLoading: false,
  comparisonPage: null,
  comparison: null,
  comparisonLoading: false,
  comparisonError: "",
  comparisonRequestVersion: 0,
  refreshJobId: null,
  refreshVersion: 0,
  refreshStatus: "",
  refreshDetail: "",
  refreshOutcome: null,
  refreshedAt: null,
};
const healthInsightsViewState = {
  assessmentId: null,
  view: "all",
  filters: { status: "all", scope: "all", evidenceKind: "all" },
  sort: { column: "priority", direction: "ascending" },
  selectedGroupId: null,
  selectedFindingId: null,
  tableScrollTop: 0,
  detailsOpen: false,
  sortWasChanged: false,
  mode: "snapshot",
  comparisonScope: "all",
  comparisonOffset: 0,
  comparisonItemOffset: 0,
};
let healthInsightsTab = "findings";
const healthRosterViewState = {
  assessmentId: null,
  search: "",
  presence: "observed",
  rosterState: "all",
  sort: { column: "label", direction: "ascending" },
  offset: 0,
  selectedDeviceId: null,
  tableScrollTop: 0,
  requestVersion: 0,
  detailVersion: 0,
};
const contextDetailsState = {
  mode: "device",
  device: { record: null, activePanelId: "device-properties-panel" },
  finding: { assessmentId: null, groupId: null, findingId: null },
};
let findingDeviceReturnContext = null;
let healthNavigationContext = null;

function clearSelectedDeviceDetails() {
  document.querySelectorAll("#device-properties-panel .node-details-list").forEach((list) => {
    list.innerHTML = "";
    list.classList.add("hidden");
  });
}

function resolveCurrentDeviceSelection(record) {
  const identityKeys = getDeviceIdentityKeys(record);
  for (const identityKey of identityKeys) {
    const matches = (currentDataset?.rows ?? []).filter(
      (candidate) => getDeviceIdentityKeys(candidate).includes(identityKey),
    );
    if (matches.length === 1) return matches[0];
    if (matches.length > 1) return null;
  }
  return null;
}

document.addEventListener(DEVICE_SELECTION_EVENT, (event) => {
  const selection = event.detail ?? {};
  if (selection.resolved) return;
  event.stopImmediatePropagation();
  const record = resolveCurrentDeviceSelection(selection.record);
  document.getElementById("device-details")?.classList.remove("roster-selected");
  if (!record) clearSelectedDeviceDetails();
  if (record && selection.direct) {
    setContextDetailsMode("device");
    contextDetailsController.setCollapsed(false);
  }
  publishDeviceSelection(record, { resolved: true });
}, true);

function renderWorkspaceLogs() {
  const contentEl = document.getElementById("workspace-log-content");
  if (!contentEl) return;
  contentEl.replaceChildren();

  const entries = getActivityEntries();
  if (entries.length === 0) {
    const emptyEl = document.createElement("p");
    emptyEl.textContent = "No browser activity logged yet.";
    contentEl.appendChild(emptyEl);
    return;
  }

  const listEl = document.createElement("ol");
  listEl.className = "workspace-log-list";
  [...entries].reverse().forEach((entry) => {
    const itemEl = document.createElement("li");
    const timeEl = document.createElement("time");
    const date = new Date(entry.timestamp);
    timeEl.dateTime = date.toISOString();
    timeEl.textContent = date.toLocaleTimeString();

    const categoryEl = document.createElement("strong");
    categoryEl.textContent = entry.category;
    const messageEl = document.createElement("span");
    const requestSummary = [
      entry.method,
      entry.route,
      entry.status ? `HTTP ${entry.status}` : "",
      Number.isFinite(entry.durationMs) ? `${entry.durationMs} ms` : "",
    ].filter(Boolean).join(" · ");
    messageEl.textContent = requestSummary
      ? `${entry.message} · ${requestSummary}`
      : entry.message;
    itemEl.append(timeEl, categoryEl, messageEl);

    if (entry.metadata && Object.keys(entry.metadata).length > 0) {
      const detailsEl = document.createElement("details");
      const summaryEl = document.createElement("summary");
      summaryEl.textContent = "Details";
      const metadataEl = document.createElement("code");
      metadataEl.textContent = JSON.stringify(entry.metadata);
      detailsEl.append(summaryEl, metadataEl);
      itemEl.appendChild(detailsEl);
    }
    listEl.appendChild(itemEl);
  });
  contentEl.appendChild(listEl);
}

function recordWorkspaceActivity(type, message, metadata = {}) {
  recordActivity({
    category: type.startsWith("job-") ? "job" : "dataset",
    phase: type === "job-cancel-requested" ? "cancelled" : "changed",
    message,
    jobId: metadata.jobId,
    metadata,
  });
}

setDatasetActivityObserver(({ type, metadata }) => {
  const messages = {
    "job-status": "Asynchronous job status changed",
    "job-cancel-requested": "Asynchronous job cancellation requested",
  };
  recordWorkspaceActivity(type, messages[type] || "Dataset activity", metadata);
});

subscribeActivity(() => {
  if (currentView === "logs" && logsSubview === "logs") renderWorkspaceLogs();
});

function jobsPanelIsVisible() {
  return currentView === "logs" && logsSubview === "jobs";
}

function stopJobsPolling() {
  jobsViewState.requestVersion += 1;
  jobsViewState.abortController?.abort();
  jobsViewState.abortController = null;
  jobsViewState.loading = false;
  if (jobsViewState.pollTimer !== null) {
    clearTimeout(jobsViewState.pollTimer);
    jobsViewState.pollTimer = null;
  }
}

function renderWorkspaceJobs() {
  const contentEl = document.getElementById("workspace-jobs-content");
  const cancelAllEl = document.getElementById("btn-cancel-all-jobs");
  if (!contentEl || !cancelAllEl) return;
  contentEl.replaceChildren();
  cancelAllEl.disabled = jobsViewState.jobs.length === 0 || jobsViewState.loading;

  if (jobsViewState.error) {
    const errorEl = document.createElement("p");
    errorEl.className = "workspace-jobs-error";
    errorEl.textContent = jobsViewState.error;
    contentEl.appendChild(errorEl);
    return;
  }
  if (jobsViewState.jobs.length === 0) {
    const emptyEl = document.createElement("p");
    emptyEl.textContent = jobsViewState.loading ? "Loading pending jobs..." : "No pending jobs.";
    contentEl.appendChild(emptyEl);
    return;
  }

  const wrapperEl = document.createElement("div");
  wrapperEl.className = "table-wrap workspace-jobs-table-wrap";
  const tableEl = document.createElement("table");
  tableEl.className = "workspace-jobs-table";
  tableEl.innerHTML = "<thead><tr><th>Type</th><th>Source</th><th>Task or action</th><th>Dataset/file</th><th>Status</th><th>Elapsed</th><th>Action</th></tr></thead>";
  const bodyEl = document.createElement("tbody");
  jobsViewState.jobs.forEach((job) => {
    const rowEl = document.createElement("tr");
    const values = [
      job.kind,
      job.source,
      job.task || job.action || "",
      job.dataset || job.filename || "",
      job.status,
      `${Math.max(0, Number(job.elapsedSeconds) || 0)}s`,
    ];
    values.forEach((value) => {
      const cellEl = document.createElement("td");
      cellEl.textContent = value;
      rowEl.appendChild(cellEl);
    });
    const actionCellEl = document.createElement("td");
    const cancelEl = document.createElement("button");
    cancelEl.type = "button";
    cancelEl.textContent = "Cancel";
    cancelEl.title = `Cancel ${job.kind} job`;
    cancelEl.disabled = !job.cancellable || jobsViewState.cancellingJobIds.has(job.jobId);
    cancelEl.addEventListener("click", () => void cancelWorkspaceJob(job));
    actionCellEl.appendChild(cancelEl);
    rowEl.appendChild(actionCellEl);
    bodyEl.appendChild(rowEl);
  });
  tableEl.appendChild(bodyEl);
  wrapperEl.appendChild(tableEl);
  contentEl.appendChild(wrapperEl);
}

function recordJobsSnapshotTransitions(previousJobs, currentJobs) {
  const previousById = new Map(previousJobs.map((job) => [job.jobId, job.status]));
  currentJobs.forEach((job) => {
    if (previousById.get(job.jobId) === job.status) return;
    recordActivity({
      category: "job",
      phase: "changed",
      message: "Pending job status changed",
      jobId: job.jobId,
      metadata: { kind: job.kind, source: job.source, status: job.status },
    });
  });
}

function getJobsPollDelayMs(jobs) {
  if (jobs.length === 0) return JOBS_POLL_EMPTY_DELAY_MS;
  const maxElapsedSeconds = Math.max(
    0,
    ...jobs.map((job) => Math.max(0, Number(job.elapsedSeconds) || 0)),
  );
  return Math.min(
    JOBS_POLL_MAX_DELAY_MS,
    Math.max(JOBS_POLL_MIN_DELAY_MS, maxElapsedSeconds * 500),
  );
}

async function refreshWorkspaceJobs() {
  if (!jobsPanelIsVisible()) return;
  if (jobsViewState.pollTimer !== null) {
    clearTimeout(jobsViewState.pollTimer);
    jobsViewState.pollTimer = null;
  }
  const requestVersion = ++jobsViewState.requestVersion;
  jobsViewState.abortController?.abort();
  const abortController = new AbortController();
  jobsViewState.abortController = abortController;
  jobsViewState.loading = true;
  jobsViewState.error = "";
  let pollDelayMs = JOBS_POLL_MIN_DELAY_MS;
  renderWorkspaceJobs();
  try {
    const response = await trackedFetch("/api/jobs", {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: abortController.signal,
    }, "silent");
    const payload = await response.json().catch(() => ({}));
    if (requestVersion !== jobsViewState.requestVersion || !jobsPanelIsVisible()) return;
    if (!response.ok || !Array.isArray(payload.jobs)) {
      throw new Error(`Pending jobs unavailable (HTTP ${response.status}).`);
    }
    recordJobsSnapshotTransitions(jobsViewState.jobs, payload.jobs);
    jobsViewState.jobs = payload.jobs;
    pollDelayMs = getJobsPollDelayMs(payload.jobs);
    jobsViewState.cancellingJobIds = new Set(
      [...jobsViewState.cancellingJobIds]
        .filter((jobId) => payload.jobs.some((job) => job.jobId === jobId)),
    );
  } catch (error) {
    if (error?.name !== "AbortError" && requestVersion === jobsViewState.requestVersion) {
      jobsViewState.error = "Pending jobs are unavailable.";
    }
  } finally {
    if (requestVersion === jobsViewState.requestVersion) {
      jobsViewState.loading = false;
      jobsViewState.abortController = null;
      renderWorkspaceJobs();
      if (jobsPanelIsVisible()) {
        jobsViewState.pollTimer = setTimeout(() => void refreshWorkspaceJobs(), pollDelayMs);
      }
    }
  }
}

async function cancelWorkspaceJob(job) {
  if (!job?.cancellable || jobsViewState.cancellingJobIds.has(job.jobId)) return;
  jobsViewState.cancellingJobIds.add(job.jobId);
  renderWorkspaceJobs();
  try {
    const response = await trackedFetch(job.cancelUrl, { method: "DELETE", cache: "no-store" });
    if (!response.ok && response.status !== 409) throw new Error("cancel failed");
  } catch {
    jobsViewState.error = "The job could not be cancelled.";
  } finally {
    jobsViewState.cancellingJobIds.delete(job.jobId);
    if (jobsPanelIsVisible()) void refreshWorkspaceJobs();
  }
}

function setLogsSubview(nextSubview) {
  if (!new Set(["logs", "jobs"]).has(nextSubview)) return;
  logsSubview = nextSubview;
  [
    ["logs", "btn-activity-log", "workspace-log-panel"],
    ["jobs", "btn-jobs", "workspace-jobs-panel"],
  ].forEach(([subview, buttonId, panelId]) => {
    const active = subview === nextSubview;
    const buttonEl = document.getElementById(buttonId);
    const panelEl = document.getElementById(panelId);
    if (panelEl) panelEl.hidden = !active;
    if (buttonEl) {
      buttonEl.classList.toggle("active", active);
      buttonEl.setAttribute("aria-selected", String(active));
      buttonEl.tabIndex = active ? 0 : -1;
    }
  });
  stopJobsPolling();
  if (nextSubview === "logs") renderWorkspaceLogs();
  if (nextSubview === "jobs" && currentView === "logs") void refreshWorkspaceJobs();
}

document.getElementById("btn-activity-log")?.addEventListener("click", () => setLogsSubview("logs"));
document.getElementById("btn-jobs")?.addEventListener("click", () => setLogsSubview("jobs"));
document.getElementById("btn-clear-logs")?.addEventListener("click", clearActivityEntries);
document.getElementById("btn-refresh-jobs")?.addEventListener("click", () => {
  stopJobsPolling();
  void refreshWorkspaceJobs();
});
document.getElementById("btn-cancel-all-jobs")?.addEventListener("click", async () => {
  if (jobsViewState.jobs.length === 0 || !window.confirm("Cancel all pending jobs?")) return;
  const response = await trackedFetch("/api/jobs", { method: "DELETE", cache: "no-store" });
  if (!response.ok) jobsViewState.error = "Pending jobs could not be cancelled.";
  if (jobsPanelIsVisible()) void refreshWorkspaceJobs();
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
  if (!force && lastRenderedDatasetByView.get(view) === currentDataset) {
    if (view === "topology") {
      const counts = getTopologyDatasetCounts();
      if (counts) updateDeviceStatusBar(counts);
    }
    return;
  }

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
    const adaptorResult = runAdaptor(effectiveDataset);
    const tableRows = projectObservedTopologyLinkCounts(
      effectiveDataset.rows,
      adaptorResult,
    ).rows;
    renderTableForDataset({ ...effectiveDataset, rows: tableRows }, currentDataset);
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
  if (contextDetailsState.mode === "finding") {
    healthInsightsViewState.detailsOpen = !isCollapsed;
  }
  resizeAndFitTopology();
}

let contextDetailsController = {
  getMode: () => "device",
  isCollapsed: () => false,
  setCollapsed: () => {},
  setMode: () => {},
};

function setContextDetailsMode(mode) {
  contextDetailsState.mode = mode;
  contextDetailsController.setMode(mode);
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
    onActivate: () => {
      if (!healthInsightsViewState.detailsOpen) contextDetailsController.setCollapsed(true);
      renderNetworkInsights();
    },
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
  if (currentView === "logs") stopJobsPolling();
  if (currentView === "insights" && newView !== "insights") {
    healthInsightsViewState.detailsOpen = false;
    findingDeviceReturnContext = null;
    document.getElementById("btn-back-to-health-finding")?.setAttribute("hidden", "");
    setContextDetailsMode("device");
  }
  currentView = newView;
  updateHealthRefreshControls();

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
  const tableCategoryLabel = document.getElementById("table-column-category-label");
  const tableCategorySelect = document.getElementById("table-column-category");
  if (tableCategoryLabel) tableCategoryLabel.hidden = newView !== "table";
  if (tableCategorySelect) tableCategorySelect.hidden = newView !== "table";

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
  if (newView === "logs" && logsSubview === "jobs") void refreshWorkspaceJobs();
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

const tableColumnCategoryEl = document.getElementById("table-column-category");
function populateTableColumnCategories(rows) {
  if (!tableColumnCategoryEl) return;
  const selectedCategory = tableColumnCategoryEl.value;
  tableColumnCategoryEl.replaceChildren();
  const allOption = document.createElement("option");
  allOption.value = "all";
  allOption.textContent = "All";
  tableColumnCategoryEl.appendChild(allOption);
  getTableColumnCategories(rows).forEach(({ value, label }) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    tableColumnCategoryEl.appendChild(option);
  });
  const categoryIsAvailable = [...tableColumnCategoryEl.options]
    .some((option) => option.value === selectedCategory);
  const nextCategory = categoryIsAvailable ? selectedCategory : "all";
  tableColumnCategoryEl.value = nextCategory;
  setTableColumnCategory(nextCategory);
}

if (tableColumnCategoryEl) {
  tableColumnCategoryEl.addEventListener("change", (event) => {
    setTableColumnCategory(event.target.value);
    if (currentDataset && currentView === "table") {
      applyTableFilters({ preserveSelection: true });
    }
  });
}

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
      "#identity-list, #highlights-list, #network-list, #connections-list, #thread-list, #mdns-list, #routes-links-list, #neighbors-list, #children-list, #counters-list, #details-list",
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
  const extAddress = canonicalizeExtAddress(getSelectedValue(record, [
    "extAddress", "extaddr", "Extended MAC",
    "attributes.extAddress", "attributes.extaddr",
  ]));
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
    const response = await trackedFetch(`/api/device/${encodeURIComponent(extAddress)}`, {
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
    const response = await trackedFetch(`/api/device/${encodeURIComponent(extAddress)}`, {
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

const deviceDiagnosticsState = {
  capabilities: null,
  record: null,
  model: null,
  invocationVersion: 0,
  jobId: null,
  startedAt: null,
};

function selectedDiagnosticTarget() {
  const model = deviceDiagnosticsState.model;
  if (!model || model.pingAction === DEVICE_ACTIONS.MATTER_PING) return null;
  const selectEl = document.getElementById("device-diagnostics-target");
  return model.targets.find(({ address }) => address === selectEl.value) ?? null;
}

function setDeviceDiagnosticsStatus(message = "", isError = false) {
  const statusEl = document.getElementById("device-diagnostics-status");
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function clearDeviceDiagnosticsResult() {
  document.getElementById("device-diagnostics-result").replaceChildren();
  setDeviceDiagnosticsStatus();
}

function setDeviceDiagnosticsPending(pending, cancelling = false) {
  const model = deviceDiagnosticsState.model;
  document.getElementById("device-diagnostics-target").disabled = pending;
  document.getElementById("device-diagnostics-attempts").disabled = pending;
  document.getElementById("device-diagnostics-timeout").disabled = pending;
  document.getElementById("device-diagnostics-allow-sed").disabled = pending;
  document.querySelectorAll('input[name="device-diagnostics-counters"]').forEach((input) => {
    input.disabled = pending;
  });
  document.getElementById("btn-device-diagnostics-ping").disabled = pending ||
    !model?.pingAction ||
    (model.targets.length > 1 && !selectedDiagnosticTarget()) ||
    (model.sleepy && !document.getElementById("device-diagnostics-allow-sed").checked);
  document.getElementById("btn-device-diagnostics-reset").disabled = pending ||
    !model?.resetSupported ||
    !selectedDiagnosticTarget() ||
    !document.querySelector('input[name="device-diagnostics-counters"]:checked');
  const cancelEl = document.getElementById("btn-device-diagnostics-cancel");
  cancelEl.hidden = !pending;
  cancelEl.disabled = cancelling;
}

function renderDeviceDiagnosticsSelection() {
  const model = deviceDiagnosticsState.model;
  const tabEl = document.getElementById("btn-device-details-diagnostics");
  tabEl.hidden = !model;
  if (!model) {
    if (!document.getElementById("device-diagnostics-panel").hidden) {
      setActiveDeviceDetailsPanel("device-properties-panel");
    }
    return;
  }

  document.getElementById("device-diagnostics-title").textContent =
    `Diagnostics: ${model.title}`;
  const targetGroupEl = document.getElementById("device-diagnostics-target-group");
  const targetSelectEl = document.getElementById("device-diagnostics-target");
  const singleTargetEl = document.getElementById("device-diagnostics-single-target");
  const hasAddressTarget = model.pingAction !== DEVICE_ACTIONS.MATTER_PING ||
    model.resetSupported;
  targetGroupEl.hidden = !hasAddressTarget;
  targetSelectEl.replaceChildren();
  singleTargetEl.textContent = "";
  if (hasAddressTarget && model.targets.length === 1) {
    targetSelectEl.hidden = true;
    singleTargetEl.hidden = false;
    singleTargetEl.textContent = `${model.targets[0].address} (${model.targets[0].family}, ${model.targets[0].provenance})`;
    const optionEl = document.createElement("option");
    optionEl.value = model.targets[0].address;
    optionEl.selected = true;
    targetSelectEl.appendChild(optionEl);
  } else if (hasAddressTarget) {
    targetSelectEl.hidden = false;
    singleTargetEl.hidden = true;
    const placeholderEl = document.createElement("option");
    placeholderEl.value = "";
    placeholderEl.textContent = "Select an address";
    targetSelectEl.appendChild(placeholderEl);
    model.targets.forEach(({ address, family, provenance }) => {
      const optionEl = document.createElement("option");
      optionEl.value = address;
      optionEl.textContent = `${address} (${family}, ${provenance})`;
      targetSelectEl.appendChild(optionEl);
    });
  }

  const attemptsEl = document.getElementById("device-diagnostics-attempts");
  attemptsEl.max = model.pingAction === DEVICE_ACTIONS.MATTER_PING ? "5" : "10";
  const timeoutEl = document.getElementById("device-diagnostics-timeout");
  timeoutEl.max = model.pingAction === DEVICE_ACTIONS.OTBR_PING ? "10" : "60";
  const timeoutLabelEl = document.querySelector(
    'label[for="device-diagnostics-timeout"]',
  );
  const supportsTimeout = model.pingAction !== DEVICE_ACTIONS.MATTER_PING;
  timeoutEl.hidden = !supportsTimeout;
  timeoutLabelEl.hidden = !supportsTimeout;
  document.getElementById("device-diagnostics-options").hidden = !model.pingAction;
  document.getElementById("device-diagnostics-sed-row").hidden = !model.sleepy;
  document.getElementById("device-diagnostics-allow-sed").checked = false;
  document.getElementById("btn-device-diagnostics-ping").hidden = !model.pingAction;
  document.getElementById("device-diagnostics-reset").hidden = !model.resetSupported;
  document.querySelectorAll('input[name="device-diagnostics-counters"]').forEach((input) => {
    input.checked = false;
  });
  setDeviceDiagnosticsPending(false);
}

function selectDeviceDiagnosticsRecord(record) {
  const oldJobId = deviceDiagnosticsState.jobId;
  deviceDiagnosticsState.invocationVersion += 1;
  deviceDiagnosticsState.jobId = null;
  deviceDiagnosticsState.record = record;
  deviceDiagnosticsState.model = buildDeviceDiagnosticsModel(
    record,
    currentDataset?.entry,
    deviceDiagnosticsState.capabilities,
  );
  clearDeviceDiagnosticsResult();
  renderDeviceDiagnosticsSelection();
  if (oldJobId) {
    void trackedFetch(`/api/device-action-jobs/${encodeURIComponent(oldJobId)}`, {
      method: "DELETE",
      cache: "no-store",
    });
  }
}

function appendDiagnosticResultRow(listEl, label, value) {
  const termEl = document.createElement("dt");
  termEl.textContent = label;
  const valueEl = document.createElement("dd");
  valueEl.textContent = value ?? "Not reported";
  listEl.append(termEl, valueEl);
}

function renderDeviceDiagnosticResult(result, detail = "") {
  const contentEl = document.getElementById("device-diagnostics-result");
  contentEl.replaceChildren();
  const listEl = document.createElement("dl");
  appendDiagnosticResultRow(listEl, "Action", result.action);
  appendDiagnosticResultRow(listEl, "Target kind", result.targetKind);
  appendDiagnosticResultRow(listEl, "Target", String(result.target ?? "Not reported"));
  appendDiagnosticResultRow(listEl, "Status", deviceActionStatusLabel(result.status));
  appendDiagnosticResultRow(listEl, "Observed", result.observedAt
    ? new Date(result.observedAt).toLocaleString()
    : "Not reported");
  appendDiagnosticResultRow(listEl, "Duration", Number.isFinite(result.durationSeconds)
    ? formatDuration(result.durationSeconds * 1000)
    : "Not reported");
  if (result.sent !== undefined) {
    appendDiagnosticResultRow(listEl, "Packets", `${result.received}/${result.sent} received`);
    appendDiagnosticResultRow(listEl, "Loss", `${Math.round(Number(result.loss) * 100)}%`);
    const summary = result.roundTripSummaryMs;
    appendDiagnosticResultRow(listEl, "Latency", summary
      ? `${summary.min} / ${summary.average} / ${summary.max} ms min/avg/max`
      : "Not reported");
  } else if (result.action === DEVICE_ACTIONS.MATTER_PING) {
    appendDiagnosticResultRow(listEl, "Latency", "Not reported");
  } else if (result.attemptsCompleted !== undefined) {
    appendDiagnosticResultRow(
      listEl,
      "Attempts",
      `${result.attemptsCompleted}/${result.attemptsRequested} completed`,
    );
  }
  if (detail || result.detail) {
    appendDiagnosticResultRow(listEl, "Detail", detail || result.detail);
  }
  contentEl.appendChild(listEl);

  const rows = result.action === DEVICE_ACTIONS.MATTER_PING
    ? Object.entries(result.results || {}).map(([address, success]) => ({
      label: address,
      status: success ? "Success" : "No response",
      duration: "Not reported",
    }))
    : (result.attempts || []).map((attempt) => ({
      label: `Attempt ${attempt.attempt}`,
      status: deviceActionStatusLabel(attempt.outcome),
      duration: Number.isFinite(attempt.durationSeconds)
        ? formatDuration(attempt.durationSeconds * 1000)
        : "Not reported",
    }));
  if (rows.length) {
    const tableEl = document.createElement("table");
    const headEl = document.createElement("thead");
    headEl.innerHTML = "<tr><th>Address / attempt</th><th>Status</th><th>Attempt duration</th></tr>";
    const bodyEl = document.createElement("tbody");
    rows.forEach((row) => {
      const trEl = document.createElement("tr");
      [row.label, row.status, row.duration].forEach((value) => {
        const cellEl = document.createElement("td");
        cellEl.textContent = value;
        trEl.appendChild(cellEl);
      });
      bodyEl.appendChild(trEl);
    });
    tableEl.append(headEl, bodyEl);
    contentEl.appendChild(tableEl);
  }
}

async function pollDeviceActionJob(jobId, invocationVersion) {
  let lastStatus = "running";
  while (invocationVersion === deviceDiagnosticsState.invocationVersion) {
    const response = await trackedFetch(`/api/device-action-jobs/${encodeURIComponent(jobId)}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    }, "silent");
    const payload = await response.json().catch(() => ({}));
    if (invocationVersion !== deviceDiagnosticsState.invocationVersion) return;
    if (!response.ok) throw new Error(payload.error || `Action polling failed (HTTP ${response.status}).`);
    if (payload.status !== lastStatus) {
      lastStatus = payload.status;
      recordActivity({
        category: "job",
        phase: "changed",
        message: "Device action job status changed",
        jobId,
        metadata: { status: payload.status, action: payload.action },
      });
    }
    if (["running", "cancelling"].includes(payload.status)) {
      const elapsed = deviceDiagnosticsState.startedAt
        ? formatDuration(Date.now() - deviceDiagnosticsState.startedAt)
        : "";
      setDeviceDiagnosticsStatus(
        payload.status === "cancelling"
          ? "Cancelling diagnostic action..."
          : `Diagnostic running${elapsed ? ` (${elapsed})` : ""}...`,
      );
      setDeviceDiagnosticsPending(true, payload.status === "cancelling");
      await new Promise((resolve) => setTimeout(resolve, 500));
      continue;
    }
    const result = payload.result || {
      action: payload.action,
      status: payload.status === "cancelled" ? "cancelled" : "failed",
    };
    renderDeviceDiagnosticResult(result, payload.detail || "");
    setDeviceDiagnosticsStatus(deviceActionStatusLabel(result.status), result.status === "failed");
    deviceDiagnosticsState.jobId = null;
    setDeviceDiagnosticsPending(false);
    return;
  }
}

async function invokeDeviceDiagnostic(action) {
  const model = deviceDiagnosticsState.model;
  if (!model || deviceDiagnosticsState.jobId) return;
  const target = selectedDiagnosticTarget();
  if (action !== DEVICE_ACTIONS.MATTER_PING && !target) return;
  const invocationVersion = ++deviceDiagnosticsState.invocationVersion;
  const invocationId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${invocationVersion}`;
  clearDeviceDiagnosticsResult();
  deviceDiagnosticsState.startedAt = Date.now();
  setDeviceDiagnosticsStatus("Queueing diagnostic action...");
  setDeviceDiagnosticsPending(true);
  const attempts = Number(document.getElementById("device-diagnostics-attempts").value);
  const timeoutSeconds = Number(document.getElementById("device-diagnostics-timeout").value);
  const payload = {
    action,
    invocationId,
    deviceId: model.deviceId,
    source: model.source,
    datasetFiles: model.datasetFiles,
    attempts,
    timeoutSeconds,
    deadlineSeconds: Math.min(600, Math.max(30, attempts * timeoutSeconds + 5)),
  };
  if (action === DEVICE_ACTIONS.MATTER_PING) {
    payload.nodeId = model.nodeId;
  } else {
    payload.target = target.address;
    payload.family = target.family;
  }
  if (action === DEVICE_ACTIONS.OTBR_PING) {
    payload.allowSed = document.getElementById("device-diagnostics-allow-sed").checked;
  }
  if (action === DEVICE_ACTIONS.OTBR_RESET) {
    payload.counters = document.querySelector(
      'input[name="device-diagnostics-counters"]:checked',
    )?.value;
    payload.confirmed = true;
  }
  try {
    const response = await fetch("/api/device-actions", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      cache: "no-store",
      body: JSON.stringify(payload),
    });
    const responsePayload = await response.json().catch(() => ({}));
    if (invocationVersion !== deviceDiagnosticsState.invocationVersion) return;
    if (!response.ok) throw new Error(responsePayload.error || `Action failed (HTTP ${response.status}).`);
    deviceDiagnosticsState.jobId = responsePayload.job_id;
    recordActivity({
      category: "job",
      phase: "started",
      message: "Device action job started",
      jobId: responsePayload.job_id,
      metadata: { action },
    });
    await pollDeviceActionJob(responsePayload.job_id, invocationVersion);
  } catch (error) {
    if (invocationVersion !== deviceDiagnosticsState.invocationVersion) return;
    deviceDiagnosticsState.jobId = null;
    renderDeviceDiagnosticResult({ action, status: "failed" }, error.message);
    setDeviceDiagnosticsStatus("Diagnostic action failed.", true);
    setDeviceDiagnosticsPending(false);
  }
}

async function loadDeviceActionCapabilities() {
  try {
    const response = await fetch("/api/device-actions", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    deviceDiagnosticsState.capabilities = await response.json();
  } catch (error) {
    console.warn("Device diagnostic capabilities are unavailable:", error);
    deviceDiagnosticsState.capabilities = { enabled: false, actions: [] };
  }
  selectDeviceDiagnosticsRecord(deviceDiagnosticsState.record);
}

function initDeviceDiagnostics() {
  document.addEventListener(DEVICE_SELECTION_EVENT, (event) => {
    selectDeviceDiagnosticsRecord(event.detail?.record ?? null);
  });
  document.getElementById("device-diagnostics-target").addEventListener("change", () => {
    clearDeviceDiagnosticsResult();
    document.getElementById("device-diagnostics-allow-sed").checked = false;
    document.querySelectorAll('input[name="device-diagnostics-counters"]').forEach((input) => {
      input.checked = false;
    });
    setDeviceDiagnosticsPending(false);
  });
  document.getElementById("device-diagnostics-allow-sed").addEventListener(
    "change",
    () => setDeviceDiagnosticsPending(false),
  );
  document.querySelectorAll('input[name="device-diagnostics-counters"]').forEach((input) => {
    input.addEventListener("change", () => setDeviceDiagnosticsPending(false));
  });
  document.getElementById("btn-device-diagnostics-ping").addEventListener("click", () => {
    void invokeDeviceDiagnostic(deviceDiagnosticsState.model?.pingAction);
  });
  document.getElementById("btn-device-diagnostics-reset").addEventListener("click", () => {
    const model = deviceDiagnosticsState.model;
    const target = selectedDiagnosticTarget();
    const counters = document.querySelector(
      'input[name="device-diagnostics-counters"]:checked',
    )?.value;
    if (!model || !target || !counters) return;
    if (window.confirm(
      `Reset ${counters.toUpperCase()} counters for ${model.title} at ${target.address}?`,
    )) void invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_RESET);
  });
  document.getElementById("btn-device-diagnostics-cancel").addEventListener("click", async () => {
    const jobId = deviceDiagnosticsState.jobId;
    if (!jobId) return;
    setDeviceDiagnosticsStatus("Cancelling diagnostic action...");
    setDeviceDiagnosticsPending(true, true);
    await fetch(`/api/device-action-jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
      cache: "no-store",
    });
  });
  void loadDeviceActionCapabilities();
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
  const healthWorkspaceEl = document.getElementById("health-insights-workspace");
  const tableWrapEl = document.getElementById("health-finding-table-wrap");
  if (!contentEl) return;
  const healthEligible = currentDataset?.entry?.healthEligible === true;
  document.getElementById("health-insights-filters")?.toggleAttribute("hidden", !healthEligible);
  healthWorkspaceEl?.toggleAttribute("hidden", !healthEligible);
  contentEl.toggleAttribute("hidden", healthEligible);
  if (healthEligible) {
    if (tableWrapEl && !healthWorkspaceEl.hidden) {
      healthInsightsViewState.tableScrollTop = tableWrapEl.scrollTop;
    }
    const assessment = healthInsightsState.assessment;
    if (assessment) {
      applyHealthAssessmentPresentation(assessment);
      if (currentDataset?.entry?.value === assessment.datasetId) {
        currentDataset.healthAssessment = assessment;
      }
      const visibleRows = projectHealthSummaryRows(
        assessment.findingGroups || [], healthInsightsViewState,
      );
      if (healthInsightsViewState.selectedGroupId && !visibleRows.some(
        ({ groupId }) => groupId === healthInsightsViewState.selectedGroupId,
      )) {
        healthInsightsViewState.selectedGroupId = null;
        healthInsightsViewState.selectedFindingId = null;
        healthInsightsViewState.detailsOpen = false;
        setContextDetailsMode("device");
        contextDetailsController.setCollapsed(true);
      }
    }
    renderHealthInsights(healthWorkspaceEl, healthInsightsState, healthInsightsViewState, {
      selectGroup: selectHealthFindingGroup,
      changeSort: (sort) => {
        healthInsightsViewState.sort = sort;
        healthInsightsViewState.sortWasChanged = true;
        renderNetworkInsights();
      },
    });
    const summary = document.getElementById("health-insights-summary");
    summary.replaceChildren();
    if (assessment) {
      appendNetworkInsightElement(summary, "strong", `${assessment.status} · ${assessment.completeness} · ${assessment.confidence} confidence`);
      appendNetworkInsightElement(summary, "span", `Observed ${assessment.observedAt || "unknown"}`);
      appendNetworkInsightElement(summary, "span", `${assessment.coverage?.deviceCount ?? "Unknown"} observed devices`);
    }
    const findingCount = projectHealthSummaryRows(assessment?.findingGroups || [], healthInsightsViewState).length;
    document.getElementById("health-findings-count").textContent = `${findingCount} groups`;
    document.getElementById("health-roster-count").textContent = healthInsightsState.roster
      ? `${healthInsightsState.roster.filteredTotal} of ${healthInsightsState.roster.total} devices` : "";
    for (const tab of ["findings", "roster"]) {
      const active = healthInsightsTab === tab;
      const button = document.getElementById(`health-tab-${tab}`);
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      document.getElementById(`health-panel-${tab}`).hidden = !active;
    }
    const rosterWrap = document.querySelector(".health-roster-table-wrap");
    if (rosterWrap && healthInsightsTab === "roster") healthRosterViewState.tableScrollTop = rosterWrap.scrollTop;
    renderHealthRoster(document.getElementById("health-roster"), healthInsightsState.roster,
      { ...healthRosterViewState, loading: healthInsightsState.rosterLoading,
        error: healthInsightsState.rosterError }, {
        select: selectRosterDevice, page: loadRosterPage, sort: changeRosterSort,
      });
    const newRosterWrap = document.querySelector(".health-roster-table-wrap");
    if (newRosterWrap) newRosterWrap.scrollTop = healthRosterViewState.tableScrollTop;
    const comparisonAvailable = healthInsightsState.capabilities?.comparisonReadModel === 1;
    const comparisonMode = comparisonAvailable && healthInsightsViewState.mode === "comparison";
    const modeSwitch = document.getElementById("health-mode-switch");
    modeSwitch.hidden = !comparisonAvailable;
    document.getElementById("health-mode-snapshot").setAttribute("aria-pressed", String(!comparisonMode));
    document.getElementById("health-mode-comparison").setAttribute("aria-pressed", String(comparisonMode));
    document.getElementById("btn-health-comparison-reset").hidden = !comparisonMode;
    document.getElementById("health-insights-filters").hidden = comparisonMode;
    document.getElementById("health-insights-evidence").hidden = comparisonMode;
    document.getElementById("health-insights-empty").hidden = comparisonMode;
    if (comparisonMode) {
      document.getElementById("health-finding-table-wrap").hidden = true;
    }
    const comparisonEl = document.getElementById("health-comparison");
    comparisonEl.hidden = !comparisonMode;
    if (comparisonMode) {
      renderHealthComparison(comparisonEl, healthInsightsState.comparisonPage,
        healthInsightsState.comparison, {
          loading: healthInsightsState.loading || healthInsightsState.comparisonLoading,
          error: healthInsightsState.comparisonError,
          scope: healthInsightsViewState.comparisonScope,
        }, {
          select: selectComparison, page: loadComparisonPage, items: loadComparisonItems,
          scope: (scope) => { healthInsightsViewState.comparisonScope = scope; renderNetworkInsights(); },
          canInspect: (deviceId) => Boolean(findCurrentDeviceRecord(deviceId)),
          inspect: (deviceId) => navigateToHealthTargets("table", { deviceIds: [deviceId] }),
        });
    }
    if (tableWrapEl) tableWrapEl.scrollTop = healthInsightsViewState.tableScrollTop;
    renderSelectedHealthFinding();
    renderHealthRefreshStatus();
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

  if (currentDataset.entry.healthEligible === false) {
    appendNetworkInsightElement(
      contentEl,
      "p",
      "Health assessment is unavailable for this dataset.",
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

function applyHealthAssessmentPresentation(assessment) {
  const findings = assessment
    ? projectVisibleHealthFindingGroups(assessment.findingGroups).flatMap(
      (group) => group.findings || [],
    )
    : [];
  setTopologyHealthFindings(findings, healthTopologyColoringEnabled);
  setTableHealthFindings(findings, assessment?.observedAt ?? "");
}

function renderHealthStatusSummary() {
  renderHealthStatus(document.getElementById("health-status-summary"), {
    ...healthInsightsState,
    topologyColoringEnabled: healthTopologyColoringEnabled,
  }, {
    openInsights: () => switchView("insights"),
    toggleTopologyColoring: () => {
      healthTopologyColoringEnabled = !healthTopologyColoringEnabled;
      renderNetworkInsights();
      renderHealthStatusSummary();
    },
  });
}

function updateHealthRefreshControls() {
  const visible = currentView === "insights" && currentDataset?.entry?.healthEligible === true;
  const refreshButton = document.getElementById("btn-health-refresh");
  const cancelButton = document.getElementById("btn-health-refresh-cancel");
  const pending = ["running", "cancelling"].includes(healthInsightsState.refreshStatus);
  if (refreshButton) {
    refreshButton.hidden = !visible;
    refreshButton.disabled = pending;
  }
  if (cancelButton) {
    cancelButton.hidden = !visible || !pending;
    cancelButton.disabled = healthInsightsState.refreshStatus === "cancelling";
  }
}

function renderHealthRefreshStatus() {
  const contentEl = document.getElementById("health-insights-empty");
  if (!contentEl || currentView !== "insights" || !healthInsightsState.refreshStatus) return;
  const message = document.createElement("p");
  const status = healthInsightsState.refreshStatus;
  message.className = status === "error" ? "network-insights-empty error" : "network-insights-empty";
  message.textContent = {
    running: "Processing cached dataset...",
    cancelling: "Cancelling health processing...",
    cancelled: "Health processing cancelled.",
    completed: healthInsightsState.refreshOutcome === true
      ? "Completed: processed cached dataset."
      : "Already current: cached dataset assessment is unchanged.",
    error: healthInsightsState.refreshDetail || "Health processing failed.",
  }[status] || "";
  if (message.textContent) contentEl.prepend(message);
}

function selectHealthFindingGroup(groupId) {
  const group = resolveHealthFindingGroup(groupId);
  healthInsightsViewState.selectedGroupId = groupId;
  healthInsightsViewState.selectedFindingId = group?.findings?.[0]?.findingId ?? null;
  healthInsightsViewState.detailsOpen = true;
  contextDetailsState.finding = {
    assessmentId: healthInsightsState.assessment?.assessmentId ?? null,
    groupId,
    findingId: healthInsightsViewState.selectedFindingId,
  };
  setContextDetailsMode("finding");
  contextDetailsController.setCollapsed(false);
  renderNetworkInsights();
  const selectedButton = document.querySelector(`.health-finding-select[data-group-id="${CSS.escape(groupId)}"]`);
  const isDesktop = window.matchMedia("(min-width: 1124px)").matches;
  const focusTarget = isDesktop ? selectedButton : document.getElementById("health-finding-details-heading");
  requestAnimationFrame(() => {
    focusTarget?.focus();
    if (!isDesktop) focusTarget?.scrollIntoView({ block: "start" });
  });
}

function resolveHealthFindingGroup(groupId) {
  return projectVisibleHealthFindingGroups(healthInsightsState.assessment?.findingGroups).find(
    (group) => group.groupId === groupId,
  ) ?? null;
}

function announceHealthInsight(message) {
  const announcement = document.getElementById("health-insights-announcement");
  if (announcement) announcement.textContent = message;
}

function closeHealthFindingDetails({ restoreFocus = true } = {}) {
  healthInsightsViewState.detailsOpen = false;
  contextDetailsController.setCollapsed(true);
  if (restoreFocus && healthInsightsViewState.selectedGroupId) {
    const groupId = healthInsightsViewState.selectedGroupId;
    requestAnimationFrame(() => document.querySelector(
      `.health-finding-select[data-group-id="${CSS.escape(groupId)}"]`,
    )?.focus());
  }
}

function renderSelectedHealthFinding() {
  if (!healthInsightsViewState.detailsOpen || !healthInsightsViewState.selectedGroupId) return;
  const group = resolveHealthFindingGroup(healthInsightsViewState.selectedGroupId);
  if (!group) {
    closeHealthFindingDetails({ restoreFocus: false });
    return;
  }
  const model = projectHealthFindingDetail(group, healthInsightsViewState.selectedFindingId);
  const heading = document.getElementById("health-finding-details-heading");
  if (heading) heading.textContent = model.heading;
  const availableDeviceIds = new Set(
    (group.deviceIds || []).filter((deviceId) => findCurrentDeviceRecord(deviceId)),
  );
  renderHealthFindingDetails(document.getElementById("health-finding-details-content"), model, {
    availableTargets: availableDeviceIds.size,
    groupDeviceCount: group.deviceIds?.length ?? 0,
    inspectableDeviceIds: availableDeviceIds,
    selectFinding: (findingId) => {
      healthInsightsViewState.selectedFindingId = findingId;
      contextDetailsState.finding.findingId = findingId;
      renderSelectedHealthFinding();
    },
    showTopology: (selectedGroupId) => navigateToHealthTargets(
      "topology", resolveHealthFindingGroup(selectedGroupId),
    ),
    showTable: (selectedGroupId) => navigateToHealthTargets(
      "table", resolveHealthFindingGroup(selectedGroupId),
    ),
    inspectDevice: (deviceId, findingId) => inspectHealthDevice(deviceId, findingId),
    compareEndpoints: (selectedGroupId) => compareHealthEndpoints(
      resolveHealthFindingGroup(selectedGroupId),
    ),
    applyFilter: (selectedGroupId) => applyHealthGroupFilter(
      resolveHealthFindingGroup(selectedGroupId),
    ),
  });
  setContextDetailsMode("finding");
  contextDetailsController.setCollapsed(false);
  announceHealthInsight(`Finding details updated: ${model.heading}`);
}

function findCurrentDeviceRecord(deviceId) {
  const extAddress = deviceId?.replace(/^extaddr:/, "").toLowerCase();
  return currentDataset?.rows?.find(
    (record) => projectSelectedDevice(record)?.extAddress === extAddress,
  ) ?? null;
}

function countAvailableHealthTargets(group) {
  return (group?.deviceIds || []).filter((deviceId) => findCurrentDeviceRecord(deviceId)).length;
}

function rememberHealthNavigationContext() {
  if (healthNavigationContext) return;
  const tableWrap = document.getElementById("health-finding-table-wrap");
  if (tableWrap) healthInsightsViewState.tableScrollTop = tableWrap.scrollTop;
  healthNavigationContext = {
    view: currentView,
    search: document.getElementById("search-input")?.value ?? "",
    nodeFilter: document.getElementById("node-filter")?.value ?? "all",
    linkFilter: document.getElementById("link-filter")?.value ?? "default_links",
    diagnosticFilter: document.getElementById("diagnostic-filter")?.value ?? "all",
    selectedRecord: deviceInsightsState.record,
    insights: currentView === "insights" ? {
      assessmentId: healthInsightsState.assessment?.assessmentId ?? null,
      view: healthInsightsViewState.view,
      filters: { ...healthInsightsViewState.filters },
      sort: { ...healthInsightsViewState.sort },
      sortWasChanged: healthInsightsViewState.sortWasChanged,
      selectedGroupId: healthInsightsViewState.selectedGroupId,
      selectedFindingId: healthInsightsViewState.selectedFindingId,
      tableScrollTop: healthInsightsViewState.tableScrollTop,
      detailsOpen: healthInsightsViewState.detailsOpen,
      mode: healthInsightsViewState.mode,
      comparisonScope: healthInsightsViewState.comparisonScope,
      comparisonOffset: healthInsightsViewState.comparisonOffset,
      comparisonItemOffset: healthInsightsViewState.comparisonItemOffset,
      comparisonId: healthInsightsState.comparison?.comparisonId ?? null,
    } : null,
  };
  document.getElementById("btn-health-return")?.removeAttribute("hidden");
}

function selectTopologyHealthTargets(deviceIds) {
  const targetAddresses = new Set(deviceIds.map((deviceId) => deviceId.replace(/^extaddr:/, "")));
  const nodeIds = (getTopologyNodeData() || [])
    .filter((node) => targetAddresses.has(projectSelectedDevice(node)?.extAddress))
    .map((node) => node.id);
  const network = getVisNetwork();
  if (!network || nodeIds.length === 0) return;
  const edges = nodeIds.length === 2
    ? network.getConnectedEdges(nodeIds[0]).filter(
      (edgeId) => network.getConnectedEdges(nodeIds[1]).includes(edgeId),
    )
    : [];
  network.setSelection({ nodes: nodeIds, edges }, { highlightEdges: false });
  network.fit({ nodes: nodeIds, animation: { duration: 300, easingFunction: "easeInOutQuad" } });
}

function navigateToHealthTargets(view, group, { compare = false } = {}) {
  if (!group?.deviceIds?.length) return;
  rememberHealthNavigationContext();
  document.getElementById("node-filter").value = "all";
  document.getElementById("diagnostic-filter").value = "all";
  if (view === "topology") document.getElementById("link-filter").value = "all_links";
  const search = compare ? "" : group.deviceIds[0].replace(/^extaddr:/, "");
  document.getElementById("search-input").value = search;
  _currentSearchQuery = parseSearchQuery(search);
  switchView(view);
  applySearch();
  if (view === "topology") selectTopologyHealthTargets(group.deviceIds);
}

function inspectHealthDevice(deviceId, findingId = null) {
  const record = findCurrentDeviceRecord(deviceId);
  if (!record) return;
  document.getElementById("device-details")?.classList.remove("roster-selected");
  if (healthInsightsViewState.selectedGroupId) {
    findingDeviceReturnContext = {
      assessmentId: healthInsightsState.assessment?.assessmentId ?? null,
      groupId: healthInsightsViewState.selectedGroupId,
      findingId: findingId ?? healthInsightsViewState.selectedFindingId,
    };
  } else {
    rememberHealthNavigationContext();
  }
  setContextDetailsMode("device");
  contextDetailsController.setCollapsed(false);
  publishDeviceSelection(record);
  setActiveDeviceDetailsPanel("device-insights-panel");
  document.getElementById("btn-back-to-health-finding")?.removeAttribute("hidden");
}

function compareHealthEndpoints(group) {
  navigateToHealthTargets("topology", group, { compare: true });
}

function applyHealthGroupFilter(group) {
  if (!group) return;
  healthInsightsViewState.filters.status = group.status;
  healthInsightsViewState.filters.scope = group.scope === "observation" ? "network" : group.scope;
  document.getElementById("health-status-filter").value = group.status;
  document.getElementById("health-scope-filter").value =
    group.scope === "observation" ? "network" : group.scope;
  const evidenceKinds = new Set(group.findings.map((finding) => finding.evidenceKind));
  const evidenceKind = evidenceKinds.size === 1 ? [...evidenceKinds][0] : "all";
  healthInsightsViewState.filters.evidenceKind = evidenceKind;
  document.getElementById("health-evidence-filter").value = evidenceKind;
  renderNetworkInsights();
}

function returnToHealthFinding() {
  const context = findingDeviceReturnContext;
  findingDeviceReturnContext = null;
  document.getElementById("btn-back-to-health-finding")?.setAttribute("hidden", "");
  if (!context || context.assessmentId !== healthInsightsState.assessment?.assessmentId) {
    announceHealthInsight("The health assessment changed; return to the finding summary.");
    return;
  }
  const group = resolveHealthFindingGroup(context.groupId);
  if (!group) {
    announceHealthInsight("The selected finding is no longer available.");
    return;
  }
  healthInsightsViewState.selectedGroupId = context.groupId;
  healthInsightsViewState.selectedFindingId = context.findingId;
  healthInsightsViewState.detailsOpen = true;
  contextDetailsState.finding = { ...context };
  renderSelectedHealthFinding();
  requestAnimationFrame(() => document.querySelector(
    `.health-affected-select[data-finding-id="${CSS.escape(context.findingId || "")}"]`,
  )?.focus());
}

function restoreHealthNavigationContext() {
  if (!healthNavigationContext) return;
  const context = healthNavigationContext;
  healthNavigationContext = null;
  document.getElementById("node-filter").value = context.nodeFilter;
  document.getElementById("link-filter").value = context.linkFilter;
  document.getElementById("diagnostic-filter").value = context.diagnosticFilter;
  document.getElementById("search-input").value = context.search;
  _currentSearchQuery = parseSearchQuery(context.search);
  if (context.insights) {
    Object.assign(healthInsightsViewState, context.insights);
    Object.assign(
      healthInsightsViewState,
      reconcileHealthInsightsSelection(healthInsightsViewState, healthInsightsState.assessment),
    );
    document.getElementById("health-view-filter").value = healthInsightsViewState.view;
    document.getElementById("health-status-filter").value = healthInsightsViewState.filters.status;
    document.getElementById("health-scope-filter").value = healthInsightsViewState.filters.scope;
    document.getElementById("health-evidence-filter").value = healthInsightsViewState.filters.evidenceKind;
    if (context.insights.comparisonId && healthInsightsState.comparison?.comparisonId !== context.insights.comparisonId) {
      void selectComparison(context.insights.comparisonId, context.insights.comparisonItemOffset);
    }
  }
  lastRenderedDatasetByView.delete("topology");
  lastRenderedDatasetByView.delete("table");
  publishDeviceSelection(context.selectedRecord);
  switchView(context.view);
  renderCurrentView({ force: true });
  if (context.insights?.detailsOpen && healthInsightsViewState.selectedGroupId) {
    renderSelectedHealthFinding();
  }
  requestAnimationFrame(() => {
    const tableWrap = document.getElementById("health-finding-table-wrap");
    if (tableWrap) tableWrap.scrollTop = healthInsightsViewState.tableScrollTop;
  });
  document.getElementById("btn-health-return")?.setAttribute("hidden", "");
}

function resetHealthWorkflow() {
  healthNavigationContext = null;
  findingDeviceReturnContext = null;
  healthInsightsViewState.view = "all";
  healthInsightsViewState.filters = { status: "all", scope: "all", evidenceKind: "all" };
  healthInsightsViewState.sort = { column: "priority", direction: "ascending" };
  healthInsightsViewState.sortWasChanged = false;
  healthInsightsViewState.selectedGroupId = null;
  healthInsightsViewState.selectedFindingId = null;
  healthInsightsViewState.tableScrollTop = 0;
  healthInsightsViewState.detailsOpen = false;
  healthInsightsViewState.mode = "snapshot";
  healthInsightsViewState.comparisonScope = "all";
  healthInsightsViewState.comparisonOffset = 0;
  healthInsightsViewState.comparisonItemOffset = 0;
  healthInsightsState.comparisonRequestVersion += 1;
  healthInsightsState.comparisonPage = null;
  healthInsightsState.comparison = null;
  healthInsightsState.comparisonLoading = false;
  healthInsightsState.comparisonError = "";
  contextDetailsState.finding = { assessmentId: null, groupId: null, findingId: null };
  setContextDetailsMode("device");
  contextDetailsController.setCollapsed(true);
  document.getElementById("btn-back-to-health-finding")?.setAttribute("hidden", "");
  const viewFilter = document.getElementById("health-view-filter");
  if (viewFilter) viewFilter.value = "all";
  for (const id of ["health-status-filter", "health-scope-filter", "health-evidence-filter"]) {
    const element = document.getElementById(id);
    if (element) element.value = "all";
  }
  document.getElementById("btn-health-return")?.setAttribute("hidden", "");
  switchView("insights");
  renderNetworkInsights();
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
      assessment: healthInsightsState.assessment,
      error: healthInsightsState.deviceError,
      loading: healthInsightsState.deviceLoading,
    }, {
      availableTargets: countAvailableHealthTargets,
      showTopology: (group) => navigateToHealthTargets("topology", group),
      showTable: (group) => navigateToHealthTargets("table", group),
      compareEndpoints: (group) => compareHealthEndpoints(group),
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
    contextDetailsState.device.record = deviceInsightsState.record;
    if (deviceInsightsState.record) setContextDetailsMode("device");
    void refreshSelectedDeviceHealth(deviceInsightsState.record);
  });
}

async function refreshSelectedDeviceHealth(record) {
  const projection = projectSelectedDevice(record);
  const requestVersion = ++healthInsightsState.deviceRequestVersion;
  healthInsightsState.device = null;
  healthInsightsState.deviceError = "";
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

async function loadRosterPage(offset) {
  const assessment = healthInsightsState.assessment;
  if (!assessment) return;
  healthRosterViewState.offset = offset;
  const version = ++healthRosterViewState.requestVersion;
  const query = { ...healthRosterViewState, sort: { ...healthRosterViewState.sort } };
  healthInsightsState.rosterLoading = true;
  healthInsightsState.rosterError = "";
  healthInsightsState.roster = null;
  renderNetworkInsights();
  try {
    const page = await fetchHealthRoster(assessment.networkId, assessment.assessmentId, query);
    if (version !== healthRosterViewState.requestVersion ||
        assessment.assessmentId !== healthInsightsState.assessment?.assessmentId) return;
    healthInsightsState.roster = page;
    if (healthRosterViewState.selectedDeviceId && offset === 0 &&
        page.devices.some((device) => device.deviceId === healthRosterViewState.selectedDeviceId)) {
      healthInsightsState.rosterDetailPresence = page.devices.find(
        (device) => device.deviceId === healthRosterViewState.selectedDeviceId,
      ).presenceState;
    }
    announceHealthInsight(`${page.filteredTotal} of ${page.total} roster devices, sorted by ${query.sort.column} ${query.sort.direction}.`);
  } catch (error) {
    if (version !== healthRosterViewState.requestVersion) return;
    healthInsightsState.rosterError = error.message;
    healthInsightsState.roster = null;
  } finally {
    if (version === healthRosterViewState.requestVersion) {
      healthInsightsState.rosterLoading = false;
      renderNetworkInsights();
    }
  }
}

async function selectRosterDevice(deviceId) {
  const networkId = healthInsightsState.assessment?.networkId;
  const assessmentId = healthInsightsState.assessment?.assessmentId;
  const version = ++healthRosterViewState.detailVersion;
  if (!networkId) return;
  if (healthRosterViewState.selectedDeviceId === deviceId) {
    healthRosterViewState.selectedDeviceId = null;
    healthInsightsState.rosterDetail = null;
    document.getElementById("device-details").classList.remove("roster-selected");
    contextDetailsController.setCollapsed(true);
    renderNetworkInsights();
    return;
  }
  healthRosterViewState.selectedDeviceId = deviceId;
  healthInsightsState.rosterDetailPresence = healthInsightsState.roster?.devices.find(
    (device) => device.deviceId === deviceId,
  )?.presenceState;
  renderNetworkInsights();
  try {
    const detail = await fetchHealthRosterDevice(networkId, deviceId);
    if (version !== healthRosterViewState.detailVersion ||
        assessmentId !== healthInsightsState.assessment?.assessmentId) return;
    healthInsightsState.rosterDetail = detail;
    renderHealthRosterDetail(document.getElementById("health-roster-details-content"), detail,
      healthInsightsState.rosterDetailPresence);
    document.getElementById("device-details").classList.add("roster-selected");
    setContextDetailsMode("device");
    contextDetailsController.setCollapsed(false);
    renderNetworkInsights();
  } catch (error) {
    if (version === healthRosterViewState.detailVersion) {
      healthRosterViewState.selectedDeviceId = null;
      announceHealthInsight(`Device details unavailable: ${error.message}`);
      renderNetworkInsights();
    }
  }
}

function changeRosterSort(column) {
  healthRosterViewState.sort = { column, direction: healthRosterViewState.sort.column === column &&
    healthRosterViewState.sort.direction === "ascending" ? "descending" : "ascending" };
  resetRosterScroll();
  void loadRosterPage(0);
}

function resetRosterScroll() {
  const wrap = document.querySelector(".health-roster-table-wrap");
  if (wrap) wrap.scrollTop = 0;
  healthRosterViewState.tableScrollTop = 0;
}

function applyRosterFilter() {
  const detail = healthInsightsState.rosterDetail;
  if (healthRosterViewState.selectedDeviceId && detail && (
    (healthRosterViewState.presence !== "all" &&
      healthRosterViewState.presence !== healthInsightsState.rosterDetailPresence) ||
    (healthRosterViewState.rosterState !== "all" &&
      healthRosterViewState.rosterState !== detail.rosterState) ||
    (healthRosterViewState.search && !detail.displayLabel.toLowerCase().includes(
      healthRosterViewState.search.toLowerCase()) && !detail.deviceId.toLowerCase().includes(
      healthRosterViewState.search.toLowerCase()))
  )) {
    healthRosterViewState.selectedDeviceId = null;
    healthRosterViewState.detailVersion += 1;
    healthInsightsState.rosterDetail = null;
    document.getElementById("device-details").classList.remove("roster-selected");
    contextDetailsController.setCollapsed(true);
  }
  resetRosterScroll();
  void loadRosterPage(0);
}

async function loadComparisonPage(offset) {
  const assessment = healthInsightsState.assessment;
  if (!assessment) return;
  const version = ++healthInsightsState.comparisonRequestVersion;
  healthInsightsState.comparisonError = "";
  healthInsightsState.comparisonLoading = true;
  renderNetworkInsights();
  try {
    const page = await fetchHealthComparisons(assessment.networkId, assessment.datasetId, offset);
    if (version !== healthInsightsState.comparisonRequestVersion ||
      healthInsightsState.assessment?.datasetId !== assessment.datasetId ||
      healthInsightsState.assessment?.networkId !== assessment.networkId) return;
    if (!isComparisonPageForAssessment(page, assessment, offset)) throw new Error("Invalid stored comparison page.");
    healthInsightsState.comparisonPage = page;
    healthInsightsViewState.comparisonOffset = offset;
  } catch (error) {
    if (version !== healthInsightsState.comparisonRequestVersion) return;
    healthInsightsState.comparisonError = error.message;
  }
  healthInsightsState.comparisonLoading = false;
  renderNetworkInsights();
}

async function loadComparisonItems(offset) {
  const comparisonId = healthInsightsState.comparison?.comparisonId;
  if (comparisonId) await selectComparison(comparisonId, offset);
}

async function selectComparison(comparisonId, offset = 0) {
  const assessment = healthInsightsState.assessment;
  const version = ++healthInsightsState.comparisonRequestVersion;
  healthInsightsState.comparisonError = "";
  if (!comparisonId) {
    healthInsightsState.comparison = null;
    healthInsightsState.comparisonLoading = false;
    healthInsightsViewState.comparisonItemOffset = 0;
    renderNetworkInsights();
    return;
  }
  healthInsightsState.comparisonLoading = true;
  renderNetworkInsights();
  try {
    const comparison = await fetchHealthComparison(comparisonId, offset);
    if (version !== healthInsightsState.comparisonRequestVersion ||
      healthInsightsState.assessment?.datasetId !== assessment?.datasetId ||
      healthInsightsState.assessment?.networkId !== assessment?.networkId) return;
    if (comparison?.schemaVersion !== 1 || comparison.comparisonId !== comparisonId ||
        comparison.networkId !== assessment.networkId || comparison.datasetId !== assessment.datasetId ||
      !Array.isArray(comparison.items) || comparison.offset !== offset ||
      !Number.isInteger(comparison.limit) || comparison.limit < 1 ||
      !Number.isInteger(comparison.itemCount) || comparison.itemCount < offset + comparison.items.length) {
      throw new Error("Invalid stored comparison response.");
    }
    healthInsightsState.comparison = comparison;
    healthInsightsViewState.comparisonItemOffset = offset;
  } catch (error) {
    if (version !== healthInsightsState.comparisonRequestVersion) return;
    healthInsightsState.comparisonError = error.message;
  }
  healthInsightsState.comparisonLoading = false;
  renderNetworkInsights();
}

async function refreshHealthAssessment() {
  const entry = currentDataset?.entry;
  const previousAssessmentId = healthInsightsState.assessment?.assessmentId;
  const datasetChanged = healthInsightsState.datasetId !== entry?.value;
  if (datasetChanged) {
    healthInsightsTab = "findings";
    healthTopologyColoringEnabled = false;
    healthInsightsState.assessment = null;
    healthInsightsViewState.assessmentId = null;
    healthInsightsViewState.view = "all";
    document.getElementById("health-view-filter").value = "all";
    healthInsightsViewState.selectedGroupId = null;
    healthInsightsViewState.selectedFindingId = null;
    healthInsightsViewState.tableScrollTop = 0;
    healthInsightsViewState.detailsOpen = false;
    healthInsightsViewState.mode = "snapshot";
    healthInsightsViewState.comparisonScope = "all";
    healthInsightsViewState.comparisonOffset = 0;
    healthInsightsViewState.comparisonItemOffset = 0;
    healthInsightsState.comparisonPage = null;
    healthInsightsState.comparison = null;
    healthInsightsState.comparisonLoading = false;
    healthInsightsState.comparisonRequestVersion += 1;
    findingDeviceReturnContext = null;
    setContextDetailsMode("device");
  }
  healthInsightsState.datasetId = entry?.value ?? null;
  healthInsightsState.error = "";
  healthInsightsState.device = null;
  healthInsightsState.deviceError = "";
  healthInsightsState.roster = null;
  if (datasetChanged) healthInsightsState.rosterDetail = null;
  healthInsightsState.rosterError = "";
  healthRosterViewState.requestVersion += 1;
  healthRosterViewState.detailVersion += 1;
  document.getElementById("device-details").classList.remove("roster-selected");
  applyHealthAssessmentPresentation(null);
  if (entry?.healthEligible !== true) {
    healthTopologyColoringEnabled = false;
    healthInsightsState.loading = false;
    renderHealthStatusSummary();
    renderNetworkInsights();
    return;
  }

  const requestVersion = ++healthInsightsState.assessmentRequestVersion;
  healthInsightsState.loading = true;
  renderHealthStatusSummary();
  renderNetworkInsights();
  try {
    const assessment = await fetchHealthAssessment(entry.value);
    if (requestVersion !== healthInsightsState.assessmentRequestVersion) return;
    healthInsightsState.assessment = assessment;
    if (previousAssessmentId !== assessment.assessmentId) {
      healthInsightsState.rosterDetail = null;
      healthRosterViewState.assessmentId = assessment.assessmentId;
      healthRosterViewState.selectedDeviceId = null;
      healthRosterViewState.offset = 0;
      healthRosterViewState.tableScrollTop = 0;
      if (datasetChanged) {
        healthRosterViewState.search = "";
        healthRosterViewState.presence = "observed";
        healthRosterViewState.rosterState = "all";
        healthRosterViewState.sort = { column: "label", direction: "ascending" };
        document.getElementById("health-roster-search").value = "";
        document.getElementById("health-roster-presence").value = "observed";
        document.getElementById("health-roster-designation").value = "all";
      }
    }
    if (healthInsightsTab === "roster" && healthInsightsState.rosterDetail) {
      document.getElementById("device-details").classList.add("roster-selected");
    }
    void loadRosterPage(healthRosterViewState.offset);
    Object.assign(
      healthInsightsViewState,
      reconcileHealthInsightsSelection(healthInsightsViewState, assessment),
    );
    if (currentDataset?.entry?.value === assessment.datasetId) {
      currentDataset.healthAssessment = assessment;
    }
    applyHealthAssessmentPresentation(assessment);
    lastRenderedDatasetByView.delete("table");
    if (currentView === "table") renderCurrentView({ force: true });
    try {
      const support = await fetchHealthSupport(assessment.networkId);
      if (requestVersion !== healthInsightsState.assessmentRequestVersion) return;
      healthInsightsState.capabilities = support.capabilities;
      healthInsightsState.observations = support.observations;
      if (support.capabilities?.comparisonReadModel === 1) {
        await loadComparisonPage(healthInsightsViewState.comparisonOffset);
      }
    } catch (error) {
      console.warn("Health history metadata is unavailable:", error);
    }
  } catch (error) {
    if (requestVersion !== healthInsightsState.assessmentRequestVersion) return;
    healthTopologyColoringEnabled = false;
    healthInsightsState.error = error.message;
  } finally {
    if (requestVersion === healthInsightsState.assessmentRequestVersion) {
      healthInsightsState.loading = false;
      renderHealthStatusSummary();
      renderNetworkInsights();
      updateHealthRefreshControls();
    }
  }
}

function invalidateHealthRefresh() {
  healthInsightsState.refreshVersion += 1;
  healthInsightsState.refreshJobId = null;
  healthInsightsState.refreshStatus = "";
  healthInsightsState.refreshDetail = "";
  healthInsightsState.refreshOutcome = null;
  healthInsightsState.refreshedAt = null;
  updateHealthRefreshControls();
}

async function runHealthRefresh() {
  const datasetId = currentDataset?.entry?.value;
  if (!datasetId || currentDataset?.entry?.healthEligible !== true) return;
  const version = ++healthInsightsState.refreshVersion;
  healthInsightsState.refreshJobId = null;
  healthInsightsState.refreshStatus = "running";
  healthInsightsState.refreshDetail = "";
  healthInsightsState.refreshOutcome = null;
  healthInsightsState.error = "";
  applyHealthAssessmentPresentation(null);
  renderHealthStatusSummary();
  renderNetworkInsights();
  updateHealthRefreshControls();
  try {
    const started = await startHealthProcessing(datasetId);
    if (version !== healthInsightsState.refreshVersion || currentDataset?.entry?.value !== datasetId) return;
    healthInsightsState.refreshJobId = started.job_id;
    recordActivity({
      category: "job",
      phase: "started",
      message: "Health processing job started",
      jobId: started.job_id,
      metadata: { dataset: datasetId, status: started.status },
    });
    let status = started;
    let lastStatus = started.status;
    while (["running", "cancelling"].includes(status.status)) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      status = await fetchHealthJob(started.job_id);
      if (version !== healthInsightsState.refreshVersion || currentDataset?.entry?.value !== datasetId) return;
      if (status.status !== lastStatus) {
        lastStatus = status.status;
        recordActivity({
          category: "job",
          phase: "changed",
          message: "Health processing job status changed",
          jobId: started.job_id,
          metadata: { dataset: datasetId, status: status.status },
        });
      }
      healthInsightsState.refreshStatus = status.status;
      renderNetworkInsights();
      updateHealthRefreshControls();
    }
    if (status.status === "done") {
      await refreshHealthAssessment();
      if (version !== healthInsightsState.refreshVersion || currentDataset?.entry?.value !== datasetId) return;
      if (healthInsightsState.error) {
        healthInsightsState.refreshStatus = "error";
        healthInsightsState.refreshDetail = healthInsightsState.error;
      } else {
        healthInsightsState.refreshStatus = "completed";
        healthInsightsState.refreshOutcome = status.result?.assessmentCreated === true;
        healthInsightsState.refreshedAt = new Date().toISOString();
      }
    } else {
      healthInsightsState.refreshStatus = status.status === "cancelled" ? "cancelled" : "error";
      healthInsightsState.refreshDetail = status.detail || "Health processing failed.";
    }
  } catch (error) {
    if (version !== healthInsightsState.refreshVersion || currentDataset?.entry?.value !== datasetId) return;
    healthTopologyColoringEnabled = false;
    healthInsightsState.refreshStatus = "error";
    healthInsightsState.refreshDetail = error.message;
  } finally {
    if (version === healthInsightsState.refreshVersion && currentDataset?.entry?.value === datasetId) {
      if (["cancelled", "error"].includes(healthInsightsState.refreshStatus)) {
        healthTopologyColoringEnabled = false;
      }
      renderHealthStatusSummary();
      renderNetworkInsights();
      updateHealthRefreshControls();
    }
  }
}

async function cancelHealthRefresh() {
  if (!healthInsightsState.refreshJobId) return;
  healthInsightsState.refreshStatus = "cancelling";
  renderNetworkInsights();
  updateHealthRefreshControls();
  try {
    await cancelHealthJob(healthInsightsState.refreshJobId);
  } catch (error) {
    healthInsightsState.refreshStatus = "error";
    healthInsightsState.refreshDetail = error.message;
    renderNetworkInsights();
    updateHealthRefreshControls();
  }
}

document.getElementById("health-view-filter")?.addEventListener("change", (event) => {
  healthInsightsViewState.view = event.target.value;
  healthInsightsViewState.filters.status = "all";
  document.getElementById("health-status-filter").value = "all";
  renderNetworkInsights();
});
function activateHealthTab(tab) {
  if (healthInsightsTab === "roster") {
    healthRosterViewState.tableScrollTop = document.querySelector(".health-roster-table-wrap")?.scrollTop ?? 0;
  }
  healthInsightsTab = tab;
  if (tab !== "roster") document.getElementById("device-details").classList.remove("roster-selected");
  if (tab === "findings" && healthInsightsViewState.detailsOpen && healthInsightsViewState.selectedGroupId) {
    renderSelectedHealthFinding();
  } else if (tab === "roster" && healthInsightsState.rosterDetail) {
    document.getElementById("device-details").classList.add("roster-selected");
    setContextDetailsMode("device");
    contextDetailsController.setCollapsed(false);
  } else {
    setContextDetailsMode("device");
    contextDetailsController.setCollapsed(true);
  }
  renderNetworkInsights();
  document.getElementById(`health-tab-${tab}`)?.focus();
}
for (const tab of ["findings", "roster"]) {
  const button = document.getElementById(`health-tab-${tab}`);
  button?.addEventListener("click", () => activateHealthTab(tab));
  button?.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    activateHealthTab(event.key === "Home" ? "findings" : event.key === "End" ? "roster"
      : healthInsightsTab === "findings" ? "roster" : "findings");
  });
}
let rosterSearchTimer;
document.getElementById("health-roster-search")?.addEventListener("input", (event) => {
  clearTimeout(rosterSearchTimer);
  const search = event.target.value;
  rosterSearchTimer = setTimeout(() => {
    healthRosterViewState.search = search;
    applyRosterFilter();
  }, 250);
});
for (const [id, key] of [["health-roster-presence", "presence"],
  ["health-roster-designation", "rosterState"]]) {
  document.getElementById(id)?.addEventListener("change", (event) => {
    healthRosterViewState[key] = event.target.value;
    applyRosterFilter();
  });
}
document.getElementById("health-mode-snapshot")?.addEventListener("click", () => {
  healthInsightsViewState.mode = "snapshot";
  renderNetworkInsights();
});
document.getElementById("health-mode-comparison")?.addEventListener("click", () => {
  healthInsightsViewState.mode = "comparison";
  renderNetworkInsights();
  if (!healthInsightsState.comparisonPage) void loadComparisonPage(0);
});
[
  ["health-status-filter", "status"],
  ["health-scope-filter", "scope"],
  ["health-evidence-filter", "evidenceKind"],
].forEach(([id, key]) => document.getElementById(id)?.addEventListener("change", (event) => {
  healthInsightsViewState.filters[key] = event.target.value;
  renderNetworkInsights();
}));
document.getElementById("btn-health-return")?.addEventListener("click", restoreHealthNavigationContext);
document.getElementById("btn-health-finding-close")?.addEventListener("click", () => {
  closeHealthFindingDetails();
});
document.getElementById("btn-back-to-health-finding")?.addEventListener("click", returnToHealthFinding);
document.getElementById("btn-health-reset")?.addEventListener("click", resetHealthWorkflow);
document.getElementById("btn-health-comparison-reset")?.addEventListener("click", resetHealthWorkflow);
document.getElementById("btn-health-export")?.addEventListener("click", () => {
  exportHealthAssessment(healthInsightsState.assessment);
});
document.getElementById("btn-health-refresh")?.addEventListener("click", () => {
  void runHealthRefresh();
});
document.getElementById("btn-health-refresh-cancel")?.addEventListener("click", () => {
  void cancelHealthRefresh();
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
    buttonId: "btn-device-details-diagnostics",
    panelId: "device-diagnostics-panel",
  },
  {
    buttonId: "btn-device-details-settings",
    panelId: "device-settings-panel",
  },
];

function setActiveDeviceDetailsPanel(activePanelId) {
  contextDetailsState.device.activePanelId = activePanelId;
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
          return el && !el.hidden ? { el, targetPanelId } : null;
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

// Reusable list of all status-bar span IDs for bulk updates.
const _FETCH_STATUS_IDS = ["fetch-timetaken-value", "fetch-cache-age-value"];
const _DEVICE_STATUS_IDS = ["device-count", "br-count", "router-count", "child-count",
                             "link-count", "lq3-count", "lq2-count", "lq1-count"];
const _CANCELLED_PARTIAL_STATUS_PIN_MS = 3000;

document
  .getElementById("datasource-filter")
  .addEventListener("change", async (event) => {
    selectDeviceDiagnosticsRecord(null);
    const selectedSource = event.target.value;
    populateDatasetSelect(selectedSource, sourceCapabilities);
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
    selectDeviceDiagnosticsRecord(null);
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

try {
  const response = await fetch("/api/catalog", { cache: "no-store" });
  if (!response.ok) throw new Error(`Catalog HTTP ${response.status}`);
  setDatasetCatalog(await response.json());
} catch (error) {
  console.warn("Unable to load dataset catalog; using bundled fallback", error);
  setDatasetCatalog(DATASET_CATALOG_FALLBACK);
}
try {
  sourceCapabilities = await loadSourceCapabilities();
} catch (error) {
  console.warn("Unable to load source capabilities", error);
}
populateDatasourceSelect(sourceCapabilities);
const initialSource = document.getElementById("datasource-filter").value;
populateDatasetSelect(initialSource, sourceCapabilities);
populateFilterSelects();
// Initialize diagnostic-filter with the default diagnostic source
const initialDiagSource = document.getElementById("diagnostic-source-filter").value;
populateDiagnosticFilterBySource(initialDiagSource);
applyLegendLineStylesFromConstants();
if (isFileCached("td-static-extaddr-device-label.json", sourceCapabilities)) {
  await loadStaticLabelMap();
}
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
initDeviceDiagnostics();
renderNetworkInsights();
initDeviceDetailsPanelTabs();
initDetailPanelToggles(document.getElementById("device-details"));
contextDetailsController = initContextDetailsPanel({
  host: document.getElementById("panel-context-details"),
  toggleButton: document.getElementById("btn-details-panel-toggle"),
  onVisibilityChanged: handleDetailsPanelVisibilityChanged,
});
document.getElementById("btn-device-details-close")?.addEventListener("click", () => {
  contextDetailsController.setCollapsed(true);
});

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
  return getRowRoleProjection(r).isChild;
}

// Derives device and link counts from a flat rows array (table-view path).
// Link counts are halved because each undirected link appears in both endpoints.
// Returns null for link fields when no row carries the link-count fields.
// Returns null for classification fields when no row carries Thread topology fields
// (rloc16 / br / type), which is the case for non-Thread sources such as mDNS.
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
async function doFetchDataset({ userInitiated = false, forceFresh = false } = {}) {
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

  let loadedDataset = null;
  try {
    loadedDataset = await loadDataset(selectedValue, {
      sessionId,
      forceFresh,
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

  // Require the result produced by this attempt, not a prior snapshot of the same dataset.
  if (!loadedDataset || currentDataset !== loadedDataset) {
    if (_incrementalRenderTimer !== null) { clearTimeout(_incrementalRenderTimer); _incrementalRenderTimer = null; }
    _setStatusSpans(_FETCH_STATUS_IDS, "—");
    _setStatusSpans(_DEVICE_STATUS_IDS, "—");
    supersedeViewStatus(`Dataset unavailable: could not load "${selectedValue}".`);
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

    const tableColumnCategoryEl = document.getElementById("table-column-category");
    if (tableColumnCategoryEl) tableColumnCategoryEl.value = "all";
    setTableColumnCategory("all");
    populateTableColumnCategories(currentDataset.rows);

  // Final reconciliation render: all files settled, isPartial is false.
  try {
    sourceCapabilities = await loadSourceCapabilities();
  } catch (error) {
    console.warn("Unable to refresh source capabilities", error);
  }
  resetDeviceDetailsPanelTabsToDefault();
  renderCurrentView();
  invalidateHealthRefresh();
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
document.getElementById("btn-fetch").addEventListener("click", (event) => {
  void doFetchDataset({ userInitiated: true, forceFresh: event.shiftKey });
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

