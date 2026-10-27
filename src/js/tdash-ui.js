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
  sourceHasAvailableDatasets,
} from "./tdash-capabilities.js";
import {
  currentDataset,
  loadDataset,
  restoreLastKnownGoodDataset,
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
  readThemePalette,
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
  selectTableDeviceById,
  getTableColumnCategories,
  setTableHealthFindings,
  setTableHealthColumnsEnabled,
  setTableColumnCategory,
  setMoreInfoEnabled,
  isMoreInfoEnabled,
} from "./tdash-table-renderer.js";
import { runAdaptor } from "./tdash-adaptors.js";
import { projectObservedTopologyLinkCounts } from "./tdash-adaptor-model.js";
import { buildThreadNetworkModel } from "./tdash-thread-network.js";
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
  flattenObjectEntries,
  shouldExcludeDetailPath,
  sortDetailsWithPriority,
  populateNodeDetailsLists,
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
  updateFilterOptionVisibility,
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
  invalidateViewStatuses,
  networkInstanceStatus,
  networkInstanceMatchesId,
  supersedeViewStatus,
} from "./tdash-view-status.js";
import {
  clearActivityEntries,
  getActivityEntries,
  recordActivity,
  subscribeActivity,
  trackedFetch,
} from "./tdash-activity.js";
import { createTopologyViewModel, resolveTopologyNodeId } from "./tdash-topology-view-model.js";
import {
  exportHealthAssessment,
  cancelHealthJob,
  fetchHealthJob,
  fetchHealthAssessment,
  fetchHealthDevice,
  fetchHealthRoster,
  fetchHealthRosterDevice,
  patchHealthRosterDevice,
  projectFindingDeviceAvailability,
  createHealthMutationRequestId,
  fetchHealthComparisons,
  fetchHealthComparisonEndpoints,
  fetchHealthComparisonPair,
  findHealthComparisonEndpointMetadata,
  isComparisonPageForAssessment,
  isHealthComparisonEndpointPageForQuery,
  isHealthComparisonPairForQuery,
  isHealthRosterPageForQuery,
  fetchHealthSupport,
  projectHealthFindingDetail,
  projectVisibleHealthFindingGroups,
  projectHealthSummaryRows,
  reconcileHealthInsightsSelection,
  toggleHealthFindingEndpointSelection,
  createHealthComparisonDetailController,
  renderDeviceHealth,
  renderHealthFindingDetails,
  renderHealthInsights,
  renderHealthRoster,
  renderHealthRosterDetail,
  renderHealthComparison,
  renderHealthAssessmentHistory,
  renderHealthStatus,
  formatHealthAssessmentObservation,
  formatHealthInsightsTabAccessibleName,
  startHealthProcessing,
} from "./tdash-health.js";
import {
  DEVICE_ACTIONS,
  buildDeviceDiagnosticsModel,
  deviceActionStatusLabel,
} from "./tdash-device-diagnostics.js";

let fetchFailureState = null;

function datasetIdentityLabel(dataset) {
  const source = DATASOURCE_REGISTRY.find((entry) => entry.value === dataset?.entry?.source);
  const label = dataset?.entry?.label ?? dataset?.entry?.value ?? "unknown dataset";
  return `${source?.label ?? dataset?.entry?.source ?? "unknown source"} / ${label}`;
}

configureViewStatusPresenter((status) => {
  const statusEl = document.getElementById("view-status-line-content");
  const statusFiles = currentDataset
    ? [...new Set([
      ...(currentDataset.loadedFiles ?? currentDataset.entry.files ?? []),
      ...Object.keys(currentDataset.auxiliaryFiles ?? {}),
    ])]
    : [];
  const statusParts = [currentDataset?.entry
    ? `${status} | ${networkInstanceStatus(statusFiles, sourceCapabilities)}`
    : status];
  if (currentDataset?.isPartial) {
    statusParts.push(`Incomplete preview: ${datasetIdentityLabel(currentDataset)}`);
  }
  if (fetchFailureState) statusParts.push(fetchFailureState);
  if (statusEl) statusEl.textContent = statusParts.filter(Boolean).join(" | ");
});

// ── Build datasource <select> ────────────────────────────────────────

function populateDatasourceSelect(capabilities) {
  const sel = document.getElementById("datasource-filter");
  sel.innerHTML = ""; // Clear existing options

  for (let i = 0; i < DATASOURCE_REGISTRY.length; i++) {
    const entry = DATASOURCE_REGISTRY[i];
    if (!sourceHasAvailableDatasets(entry.value, capabilities, DATASET_REGISTRY)) continue;
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
    ? DATASET_REGISTRY.filter((entry) => entry.selectable !== false
      && entry.source === sourceFilter && datasetIsAvailable(entry, capabilities))
    : DATASET_REGISTRY.filter((entry) => entry.selectable !== false && datasetIsAvailable(entry, capabilities));
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
let fetchAttemptVersion = 0;
let operationsSubview = "logs";
let threadNetworkModelCache = null;
let currentDeviceStatusCounts = null;
const HEALTH_COLORING_PREFERENCE_KEY = "tdash.healthColoringEnabled";
const HEALTH_COLUMNS_PREFERENCE_KEY = "tdash.healthColumnsEnabled";

function readBooleanPreference(key) {
  try {
    const stored = globalThis.localStorage.getItem(key);
    return stored === "true" ? true : stored === "false" ? false : null;
  } catch {
    return null;
  }
}

function writeBooleanPreference(key, value) {
  try {
    globalThis.localStorage.setItem(key, String(value));
  } catch {
    // Keep the current-page choice when browser storage is unavailable.
  }
}

const storedHealthColoringPreference = readBooleanPreference(HEALTH_COLORING_PREFERENCE_KEY);
let healthTopologyColoringEnabled = storedHealthColoringPreference === true;
let healthColoringPreferenceSet = storedHealthColoringPreference !== null;
let healthTableColumnsEnabled = readBooleanPreference(HEALTH_COLUMNS_PREFERENCE_KEY) === true;
setTableHealthColumnsEnabled(healthTableColumnsEnabled);
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
  supportError: "",
  observations: null,
  roster: null,
  rosterDetail: null,
  rosterError: "",
  rosterLoading: false,
  comparisonPage: null,
  comparison: null,
  comparisonListLoading: false,
  comparisonListError: "",
  comparisonListRequestVersion: 0,
  comparisonDetailLoading: false,
  comparisonDetailError: "",
  comparisonDetailRequestVersion: 0,
  comparisonQueryIdentity: null,
  comparisonDetailRequestIdentity: null,
  comparisonDetailRequestHeader: null,
  comparisonEndpointPages: { before: null, after: null },
  comparisonLatestPresetPage: null,
  comparisonPinnedBefore: null,
  comparisonEndpointLoading: { before: false, after: false },
  comparisonEndpointErrors: { before: "", after: "" },
  comparisonEndpointRequestVersions: { before: 0, after: 0 },
  comparisonEndpointRevision: 0,
  comparisonEndpointDefaultsPending: true,
  comparisonEndpointPairLoading: false,
  comparisonEndpointPairError: "",
  comparisonEndpointPairRequestVersion: 0,
  comparisonEndpointPairRequestIdentity: null,
  comparisonEndpointUnavailable: false,
  comparisonPresetLoading: false,
  comparisonPresetError: "",
  comparisonPresetRequestVersion: 0,
  comparisonResetPendingRefresh: false,
  refreshJobId: null,
  refreshVersion: 0,
  refreshStatus: "",
  refreshDetail: "",
  refreshOutcome: null,
  refreshedAt: null,
};
const healthAssessmentHistoryState = {
  mode: "latest",
  pinnedAssessmentId: null,
  networkId: null,
  page: null,
  navigation: null,
  offset: 0,
  loading: false,
  pageLoading: false,
  error: "",
  targetError: "",
  unsupported: false,
  chooserOpen: false,
  requestVersion: 0,
  announceSelection: false,
};
const healthInsightsViewState = {
  assessmentId: null,
  view: "all",
  filters: { status: "all", scope: "all", evidenceKind: "all" },
  sort: { column: "priority", direction: "ascending" },
  selectedGroupId: null,
  selectedFindingId: null,
  selectedEndpointId: null,
  tableScrollTop: 0,
  detailsOpen: false,
  sortWasChanged: false,
  comparisonId: null,
  comparisonScope: "all",
  comparisonResult: "changed",
  comparisonSearch: "",
  comparisonSort: "subject",
  comparisonDirection: "ascending",
  comparisonLimit: 100,
  comparisonControlFocusTarget: null,
  comparisonOffset: 0,
  comparisonItemOffset: 0,
  comparisonIntent: "1d",
  comparisonCustomOpen: false,
  comparisonDetailsOpen: false,
  comparisonFocusTarget: null,
  comparisonTableScrollTop: 0,
  comparisonTableScrollLeft: 0,
  beforeAssessmentId: null,
  afterAssessmentId: null,
  beforeHistoryOffset: 0,
  afterHistoryOffset: 0,
};
const healthComparisonDetailController = createHealthComparisonDetailController({
  state: healthInsightsState,
  getAssessment: () => healthInsightsState.assessment,
  getSelection: () => ({
    comparisonId: healthInsightsViewState.comparisonId,
    scope: healthInsightsViewState.comparisonScope,
    result: healthInsightsViewState.comparisonResult,
    q: healthInsightsViewState.comparisonSearch,
    sort: healthInsightsViewState.comparisonSort,
    direction: healthInsightsViewState.comparisonDirection,
    limit: healthInsightsViewState.comparisonLimit,
  }),
  getSummary: (comparisonId) => healthInsightsState.comparisonPage?.items.find(
    (item) => item.comparisonId === comparisonId,
  ) ?? null,
  getOffset: () => healthInsightsViewState.comparisonItemOffset,
  setOffset: (offset) => { healthInsightsViewState.comparisonItemOffset = offset; },
  updateSelection: (filter, value) => {
    const key = {
      scope: "comparisonScope",
      result: "comparisonResult",
      q: "comparisonSearch",
      sort: "comparisonSort",
      direction: "comparisonDirection",
      limit: "comparisonLimit",
    }[filter];
    if (key) healthInsightsViewState[key] = value;
  },
  onChange: () => renderNetworkInsights(),
});
const HEALTH_INSIGHTS_TABS = [
  { id: "findings", buttonId: "health-tab-findings", panelId: "health-panel-findings" },
  { id: "comparison", buttonId: "health-tab-comparison", panelId: "health-panel-comparison" },
  { id: "roster", buttonId: "health-tab-roster", panelId: "health-panel-roster" },
];
let healthInsightsTab = HEALTH_INSIGHTS_TABS[0].id;
const healthRosterViewState = {
  assessmentId: null,
  search: "",
  presence: "observed",
  rosterState: "all",
  sort: { column: "label", direction: "ascending" },
  limit: 100,
  offset: 0,
  selectedDeviceId: null,
  tableScrollTop: 0,
  tableScrollLeft: 0,
  requestVersion: 0,
  detailVersion: 0,
  sortFocusColumn: null,
  pageFocusTarget: null,
};
let rosterMutationPendingDeviceId = null;
let activeRosterAction = null;
let activeRosterRequest = null;
const findingRosterActionEligibility = new Map();
const findingRosterActionPending = new Set();
let rosterNavigationGeneration = 0;
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
    const details = sortDetailsWithPriority(
      flattenObjectEntries(record).filter(
        ([key]) => !shouldExcludeDetailPath(key, "table"),
      ),
    );
    document.getElementById("summary-list")?.replaceChildren();
    if (details.length) {
      populateNodeDetailsLists(details);
    } else {
      clearSelectedDeviceDetails();
      const summaryList = document.getElementById("summary-list");
      if (summaryList) {
        const empty = document.createElement("li");
        empty.textContent = "No details available for selected device.";
        summaryList.appendChild(empty);
      }
    }
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
  if (currentView === "operations" && operationsSubview === "logs") renderWorkspaceLogs();
});

function jobsPanelIsVisible() {
  return currentView === "operations" && operationsSubview === "jobs";
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

function getCurrentThreadNetworkViewData(includeAdaptor = false) {
  if (!currentDataset) {
    return { model: buildThreadNetworkModel(null, sourceCapabilities, null), error: "" };
  }
  if (threadNetworkModelCache?.dataset === currentDataset
      && threadNetworkModelCache.capabilities === sourceCapabilities
      && (!includeAdaptor || threadNetworkModelCache.hasAdaptor)) {
    return threadNetworkModelCache;
  }

  let adaptorResult = null;
  let adaptorError = "";
  if (includeAdaptor) {
    try {
      const rawAdaptorResult = runAdaptor(currentDataset);
      const relationshipProjection = projectObservedTopologyLinkCounts(
        currentDataset.rows,
        rawAdaptorResult,
      );
      adaptorResult = {
        ...rawAdaptorResult,
        relationshipCapabilityPresent: relationshipProjection.hasRelationshipCapability,
      };
    } catch {
      adaptorError = "Relationship details are unavailable for this dataset.";
    }
  }
  threadNetworkModelCache = {
    dataset: currentDataset,
    capabilities: sourceCapabilities,
    statusCounts: currentDeviceStatusCounts,
    hasAdaptor: includeAdaptor,
    model: buildThreadNetworkModel(
      currentDataset,
      sourceCapabilities,
      adaptorResult,
      currentDeviceStatusCounts,
    ),
    error: adaptorError,
  };
  return threadNetworkModelCache;
}

function threadRoleTargetLabel(holder) {
  if (!holder.canSelect) return "Unidentified";
  const identifier = holder.rloc16 !== "n/a" ? holder.rloc16 : holder.extAddress;
  return holder.deviceLabel !== "n/a"
    ? `${holder.deviceLabel} (${identifier})`
    : identifier;
}

function appendThreadNetworkSourceTooltips(target, sourceFiles) {
  const filenames = [...new Set((sourceFiles ?? []).filter((filename) => toText(filename).trim()))];
  if (!filenames.length) return;
  const group = document.createElement("span");
  group.className = "thread-network-source-list";
  group.setAttribute("aria-label", "Source files");
  filenames.forEach((filename) => {
    const tooltip = document.createElement("span");
    tooltip.className = "thread-network-source-tooltip";
    tooltip.tabIndex = 0;
    tooltip.setAttribute("role", "img");
    tooltip.setAttribute("aria-label", `Source file: ${filename}`);
    tooltip.title = filename;
    tooltip.textContent = "i";
    group.appendChild(tooltip);
  });
  target.appendChild(group);
}

function appendThreadNetworkSource(target, fact) {
  if (!fact.provenance && !fact.sources?.length) return;
  const note = document.createElement("small");
  note.className = "thread-network-source";
  if (fact.provenance) {
    const provenance = document.createElement("span");
    provenance.textContent = `Provenance: ${fact.provenance}`;
    note.appendChild(provenance);
  }
  if (fact.sources?.length) {
    if (fact.provenance) {
      const separator = document.createElement("span");
      separator.setAttribute("aria-hidden", "true");
      separator.textContent = " · ";
      note.appendChild(separator);
    }
    const sourceLabel = document.createElement("span");
    sourceLabel.textContent = "Source: ";
    note.appendChild(sourceLabel);
    appendThreadNetworkSourceTooltips(note, fact.sources);
  }
  target.appendChild(note);
}

function appendThreadNetworkFacts(target, facts) {
  const list = document.createElement("dl");
  list.className = "thread-network-facts";
  facts.forEach((fact) => {
    const item = document.createElement("div");
    item.className = "thread-network-fact";
    const label = document.createElement("dt");
    label.textContent = fact.label;
    const value = document.createElement("dd");
    value.textContent = toText(fact.value) || "n/a";
    item.append(label, value);
    appendThreadNetworkSource(item, fact);
    list.appendChild(item);
  });
  target.appendChild(list);
}

function appendThreadNetworkSummarySection(target, title, entries) {
  const section = document.createElement("section");
  section.className = "thread-network-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.appendChild(heading);
  const list = document.createElement("dl");
  list.className = "thread-network-counts";
  entries.forEach(([label, value]) => {
    const item = document.createElement("div");
    item.className = "thread-network-count";
    const term = document.createElement("dt");
    term.textContent = label;
    const definition = document.createElement("dd");
    definition.textContent = toText(value) || "n/a";
    item.append(term, definition);
    list.appendChild(item);
  });
  section.appendChild(list);
  target.appendChild(section);
}

function appendThreadRoleTable(target, title, roleHolders) {
  const section = document.createElement("section");
  section.className = "thread-network-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.appendChild(heading);
  if (!roleHolders.length) {
    const empty = document.createElement("p");
    empty.textContent = "n/a";
    section.appendChild(empty);
    target.appendChild(section);
    return;
  }

  const wrapper = document.createElement("div");
  wrapper.className = "thread-network-table-wrap";
  const table = document.createElement("table");
  table.className = "thread-network-table";
  const headers = ["Device", "extAddress", "rloc16", "deviceLabel", "threadVersion", "threadStackVersion", "Source"];
  const head = document.createElement("thead");
  const headerRow = document.createElement("tr");
  headers.forEach((text) => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = text;
    headerRow.appendChild(cell);
  });
  head.appendChild(headerRow);
  table.appendChild(head);

  const body = document.createElement("tbody");
  roleHolders.forEach((holder) => {
    const row = document.createElement("tr");
    const deviceCell = document.createElement("td");
    if (holder.canSelect) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Open device";
      button.title = `Show details for ${threadRoleTargetLabel(holder)}`;
      button.addEventListener("click", () => publishDeviceSelection(holder.record, { direct: true }));
      deviceCell.appendChild(button);
    } else {
      deviceCell.textContent = "Unidentified";
    }
    row.appendChild(deviceCell);
    [holder.extAddress, holder.rloc16, holder.deviceLabel, holder.threadVersion,
      holder.threadStackVersion].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value || "n/a";
      row.appendChild(cell);
    });
    const sourceCell = document.createElement("td");
    if (holder.sourceFiles.length) appendThreadNetworkSourceTooltips(sourceCell, holder.sourceFiles);
    else sourceCell.textContent = "n/a";
    row.appendChild(sourceCell);
    body.appendChild(row);
  });
  table.appendChild(body);
  wrapper.appendChild(table);
  section.appendChild(wrapper);
  target.appendChild(section);
}

function appendThreadPartitionsSection(target, partitions) {
  const section = document.createElement("section");
  section.className = "thread-network-section";
  const heading = document.createElement("h3");
  heading.textContent = "Partitions";
  section.appendChild(heading);

  const messages = {
    supported: "Counts are unique identified Thread devices observed in the loaded dataset; this is not a complete mesh census.",
    partial: "Known observed membership only. Some devices or source records could not be attributed to a partition; counts are not a complete mesh census.",
    conflicting: "Known observed membership only. Conflicting partition claims prevent some devices from being attributed; counts are not a complete mesh census.",
    "no-evidence": "No valid partition membership evidence is available in the loaded dataset. This does not mean there are zero partitions.",
    "unresolved-scope": "The active network identity is mixed or unresolved, so partition membership cannot be safely attributed.",
  };
  const notice = document.createElement("p");
  notice.textContent = partitions.state === "no-evidence" && partitions.isPartialDataset
    ? "No valid partition membership evidence is available in the loaded partial dataset. This does not mean there are zero partitions."
    : messages[partitions.state] ?? messages["no-evidence"];
  section.appendChild(notice);

  if (partitions.partitions.length) {
    const wrapper = document.createElement("div");
    wrapper.className = "thread-network-table-wrap";
    const table = document.createElement("table");
    table.className = "thread-network-table";
    table.classList.add("thread-network-partitions-table");
    const head = document.createElement("thead");
    const headerRow = document.createElement("tr");
    ["Partition ID", partitions.state === "supported"
      ? "Unique identified devices" : "Known observed devices", "Source file(s)"].forEach((text) => {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = text;
      headerRow.appendChild(cell);
    });
    head.appendChild(headerRow);
    table.appendChild(head);

    const body = document.createElement("tbody");
    partitions.partitions.forEach((partition) => {
      const row = document.createElement("tr");
      const id = document.createElement("td");
      id.textContent = partition.partitionId;
      const count = document.createElement("td");
      count.textContent = String(partition.count);
      const source = document.createElement("td");
      if (partition.sourceFiles.length) {
        const sourceList = document.createElement("ul");
        sourceList.className = "thread-network-partition-sources";
        partition.sourceFiles.forEach((filename) => {
          const item = document.createElement("li");
          item.textContent = filename;
          sourceList.appendChild(item);
        });
        source.appendChild(sourceList);
      } else {
        source.textContent = "Source filename unavailable in loaded row evidence.";
      }
      row.append(id, count, source);
      body.appendChild(row);
    });
    table.appendChild(body);
    wrapper.appendChild(table);
    section.appendChild(wrapper);
  }
  target.appendChild(section);
}

function renderThreadNetworkPanel() {
  const content = document.getElementById("thread-network-content");
  if (!content) return;
  content.replaceChildren();
  if (!currentDataset) {
    const empty = document.createElement("p");
    empty.textContent = "Load a dataset to view Thread Network information.";
    content.appendChild(empty);
    return;
  }

  const { model, error } = getCurrentThreadNetworkViewData(true);
  if (!model.loaded) {
    const empty = document.createElement("p");
    empty.textContent = "No dataset loaded.";
    content.appendChild(empty);
    return;
  }
  const datasetLabel = document.createElement("p");
  datasetLabel.className = "thread-network-dataset";
  datasetLabel.textContent = `Dataset: ${model.datasetLabel || "n/a"}`;
  content.appendChild(datasetLabel);

  const networkSection = document.createElement("section");
  networkSection.className = "thread-network-section";
  const networkHeading = document.createElement("h3");
  networkHeading.textContent = "Thread Network";
  networkSection.appendChild(networkHeading);
  appendThreadNetworkFacts(networkSection, model.networkFacts);
  content.appendChild(networkSection);

  appendThreadRoleTable(content, "Leader", model.roleHolders.leaders);
  appendThreadRoleTable(content, "Primary BBR", model.roleHolders.primaryBbrs);
  appendThreadNetworkSummarySection(content, "Devices", [
    ["Total Devices", model.deviceCounts.total],
    ["Thread Border Routers", model.deviceCounts.borderRouters],
    ["Routers", model.deviceCounts.routers],
    ["Router Eligible End Devices", model.deviceCounts.reed],
    ["End Devices", model.deviceCounts.endDevices],
  ]);
  appendThreadNetworkSummarySection(content, "Links", [
    ["Total Links", model.links.total],
    ["LQI3", model.links.lqi[3].count === "n/a"
      ? "n/a" : `${model.links.lqi[3].count} (${model.links.lqi[3].percent}%)`],
    ["LQI2", model.links.lqi[2].count === "n/a"
      ? "n/a" : `${model.links.lqi[2].count} (${model.links.lqi[2].percent}%)`],
    ["LQI1", model.links.lqi[1].count === "n/a"
      ? "n/a" : `${model.links.lqi[1].count} (${model.links.lqi[1].percent}%)`],
  ]);
  appendThreadPartitionsSection(content, model.partitions);
  if (error) {
    const notice = document.createElement("p");
    notice.className = "thread-network-error";
    notice.textContent = error;
    content.appendChild(notice);
  }
}

const OPERATIONS_SUBVIEWS = Object.freeze([
  ["thread-network", "btn-thread-network", "workspace-thread-network-panel"],
  ["logs", "btn-activity-log", "workspace-log-panel"],
  ["jobs", "btn-jobs", "workspace-jobs-panel"],
]);

function renderOperationsSubview() {
  OPERATIONS_SUBVIEWS.forEach(([subview, buttonId, panelId]) => {
    const active = subview === operationsSubview;
    const button = document.getElementById(buttonId);
    const panel = document.getElementById(panelId);
    if (panel) panel.hidden = !active;
    if (button) {
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    }
  });
  if (currentView !== "operations") return;
  if (operationsSubview === "thread-network") renderThreadNetworkPanel();
  if (operationsSubview === "logs") renderWorkspaceLogs();
  if (operationsSubview === "jobs") void refreshWorkspaceJobs();
}

function setOperationsSubview(nextSubview) {
  if (!OPERATIONS_SUBVIEWS.some(([subview]) => subview === nextSubview)) return;
  operationsSubview = nextSubview;
  stopJobsPolling();
  renderOperationsSubview();
}

OPERATIONS_SUBVIEWS.forEach(([subview, buttonId], index) => {
  const button = document.getElementById(buttonId);
  button?.addEventListener("click", () => setOperationsSubview(subview));
  button?.addEventListener("keydown", (event) => {
    const navigationKeys = ["ArrowLeft", "ArrowRight", "Home", "End"];
    if (!navigationKeys.includes(event.key)) return;
    event.preventDefault();
    const nextIndex = event.key === "Home" ? 0
      : event.key === "End" ? OPERATIONS_SUBVIEWS.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + OPERATIONS_SUBVIEWS.length)
          % OPERATIONS_SUBVIEWS.length;
    const [nextSubview, nextButtonId] = OPERATIONS_SUBVIEWS[nextIndex];
    setOperationsSubview(nextSubview);
    document.getElementById(nextButtonId)?.focus();
  });
});

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
let healthTopologyViewModelCache = null;

function renderCurrentView({ force = false } = {}) {
  if (!currentDataset) return;
  if (force) threadNetworkModelCache = null;
  updateHealthPresentationControls();
  renderNetworkInsights();
  const view = currentView;
  if (view !== "topology" && view !== "table") {
    updateDeviceStatusBar(computeRowCounts(currentDataset.rows));
    if (view === "operations") renderOperationsSubview();
    return;
  }
  activateViewStatus(view, currentDataset);
  const renderedState = lastRenderedDatasetByView.get(view);
  if (!force && renderedState?.dataset === currentDataset) {
    currentDataset.capabilities = renderedState.capabilities;
    updateFilterOptionVisibility(currentDataset.capabilities, view);
    refreshDiagnosticFilterForCurrentSource();
    if (view === "topology") {
      const counts = getTopologyDatasetCounts();
      if (counts) updateDeviceStatusBar(counts);
      refreshTopologyFiltersWithRestoredStyling();
      if (_currentSearchQuery) applySearch();
    } else {
      applyTableFilters();
      updateDeviceStatusBar(computeRowCounts(currentDataset.rows));
    }
    return;
  }

  const effectiveDataset = _enhanceEnabled
    ? {
      ...currentDataset,
      rows: enrichRows(currentDataset.rows),
      adaptorRows: currentDataset.adaptorRows
        ? enrichRows(currentDataset.adaptorRows)
        : undefined,
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
    populateTableColumnCategories(tableRows);
    const tableDataset = { ...effectiveDataset, rows: tableRows };
    renderTableForDataset(tableDataset, currentDataset);
    effectiveDataset.capabilities = tableDataset.capabilities;
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

  lastRenderedDatasetByView.set(view, {
    dataset: currentDataset,
    capabilities: currentDataset.capabilities,
  });
}

function clearRenderedDatasetViews(emptyDataset) {
  renderTopologyForDataset(emptyDataset, _physicsEnabled, _physicsProfileName, emptyDataset);
  renderTableForDataset(emptyDataset, emptyDataset);
  lastRenderedDatasetByView.clear();
  invalidateViewStatuses();
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
  const closeButton = document.getElementById("btn-device-status-close");
  const action = isCollapsed ? "Expand" : "Collapse";
  [toggleButton, closeButton].forEach((button) => {
    if (button) {
      button.title = `${action} functions panel`;
      button.setAttribute("aria-label", `${action} functions panel`);
      button.setAttribute("aria-expanded", String(!isCollapsed));
    }
  });
  if (toggleButton) {
    toggleButton.textContent = isCollapsed ? "▶" : "◀";
  }
  resizeAndFitTopology();
}

function toggleFunctionsPanel() {
  const shell = document.querySelector(".dashboard-shell");
  setFunctionsPanelCollapsed(!shell?.classList.contains("functions-panel-collapsed"));
}

document.getElementById("btn-functions-panel-toggle")?.addEventListener("click", toggleFunctionsPanel);
document.getElementById("btn-device-status-close")?.addEventListener("click", toggleFunctionsPanel);

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
  {
    view: "operations",
    buttonId: "btn-operations",
    panelId: "view-operations",
    onActivate: renderOperationsSubview,
  },
  { view: "settings", buttonId: "btn-settings", panelId: "view-settings" },
]);

function switchView(newView) {
  const nextView = WORKSPACE_VIEWS.find(({ view }) => view === newView);
  if (!nextView) return;
  if (newView === currentView) return;
  if (currentView === "operations") stopJobsPolling();
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
  const healthEligible = currentDataset?.entry?.healthEligible === true;
  const healthColumnsButton = document.getElementById("btn-health-columns");
  if (healthColumnsButton) healthColumnsButton.hidden = newView !== "table" || !healthEligible;
  const healthColoringButton = document.getElementById("btn-health-coloring");
  if (healthColoringButton) healthColoringButton.hidden = newView !== "topology" || !healthEligible;
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
  if (newView === "insights") enableHealthColoringOnFirstInsightsVisit();
  updateHealthPresentationControls();
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
  btn.setAttribute("aria-pressed", String(enabled));
  if (enabled) {
    btn.classList.add("active");
    btn.textContent = "⏸"; // U+23F8 PAUSE
    btn.title = "Pause physics simulation";
  } else {
    btn.classList.remove("active");
    btn.textContent = "▶"; // U+25B6 PLAY
    btn.title = "Resume physics simulation";
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

document.getElementById("btn-health-coloring")?.addEventListener("click", () => {
  setHealthColoringEnabled(!healthTopologyColoringEnabled);
});

document.getElementById("btn-health-columns")?.addEventListener("click", () => {
  setHealthColumnsEnabled(!healthTableColumnsEnabled);
});

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
  setTableColumnCategory(nextCategory, rows);
}

if (tableColumnCategoryEl) {
  tableColumnCategoryEl.addEventListener("change", (event) => {
    setTableColumnCategory(event.target.value);
    if (currentDataset && currentView === "table") {
      applyTableFilters({ preserveSelection: true });
    }
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
  invocation: null,
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
  pending = pending || deviceDiagnosticsState.invocation?.active === true;
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
  cancelEl.hidden = !pending && !deviceDiagnosticsState.jobId;
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
  invalidateDeviceDiagnostic();
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
}

function isCurrentDiagnostic(invocation) {
  return deviceDiagnosticsState.invocation === invocation &&
    invocation.version === deviceDiagnosticsState.invocationVersion;
}

function diagnosticActivity(invocation, phase,
    message = "Device diagnostic server state uncertain; check Pending Jobs") {
  try {
    recordActivity({
      category: "job", phase,
      message,
      jobId: invocation.jobId,
      metadata: { action: invocation.action, status: invocation.status },
    });
  } catch {
    console.warn("Device diagnostic activity unavailable");
  }
}

function invalidateDeviceDiagnostic() {
  const invocation = deviceDiagnosticsState.invocation;
  deviceDiagnosticsState.invocation = null;
  if (!invocation) return;
  invocation.cancelIntent = true;
  invocation.readController.abort();
  if (invocation.jobId) void cancelDeviceDiagnostic(invocation, true);
}

function diagnosticProtocolError() {
  return new Error("Diagnostic protocol error: invalid server response.");
}

function validateDiagnosticEnvelope(payload, invocation) {
  const object = payload && typeof payload === "object" && !Array.isArray(payload);
  if (!object || payload.job_id !== invocation.jobId ||
      payload.action !== invocation.action || payload.invocationId !== invocation.id ||
      !["running", "cancelling", "done", "error", "cancelled"].includes(payload.status)) {
    throw diagnosticProtocolError();
  }
  const result = payload.result;
  const resultStatuses = [
    "success", "partial-success", "no-response", "no-addresses", "timed-out",
    "unsupported", "protocol-error", "transport-failure", "deadline-exceeded",
    "local-dispatch-failure", "accepted-for-transmission", "failed", "cancelled",
  ];
  if ((payload.status === "done" || result !== undefined) &&
      (!result || typeof result !== "object" || Array.isArray(result) ||
       result.action !== invocation.action || !resultStatuses.includes(result.status))) {
    throw diagnosticProtocolError();
  }
  return payload;
}

async function diagnosticRequest(invocation, url, options, signal = null, bound = 15000) {
  const controller = new AbortController();
  const startedAt = performance.now();
  let timer;
  let onAbort;
  const stopped = new Promise((_, reject) => {
    onAbort = () => {
      reject(new DOMException("Diagnostic read stopped locally.", "AbortError"));
      controller.abort();
    };
    if (signal?.aborted) onAbort();
    else signal?.addEventListener("abort", onAbort, { once: true });
    timer = setTimeout(() => {
      reject(new Error("Diagnostic local timeout."));
      controller.abort();
    }, bound);
    invocation.timers.add(timer);
  });
  const request = (async () => {
    const response = await fetch(url, { ...options, signal: controller.signal });
    let payload;
    try {
      payload = await response.json();
    } catch {
      if (response.ok) throw diagnosticProtocolError();
    }
    let terminalConflict = false;
    if (response.status === 409 && options.method === "DELETE") {
      try {
        validateDiagnosticEnvelope(payload, invocation);
        terminalConflict = ["done", "error", "cancelled"].includes(payload.status);
      } catch {
        terminalConflict = false;
      }
    }
    if (!response.ok && !terminalConflict) {
      const detail = typeof payload?.error === "string" ? ` ${payload.error.slice(0, 512)}` : "";
      throw new Error(`Diagnostic HTTP ${response.status}.${detail}` +
        (response.status === 404 ? " Job no longer discoverable; cancellation not proven." : ""));
    }
    return { response, payload };
  })();
  try {
    const result = await Promise.race([request, stopped]);
    if (performance.now() - startedAt >= bound) {
      controller.abort();
      throw new Error("Diagnostic local timeout.");
    }
    return result;
  } finally {
    clearTimeout(timer);
    invocation.timers.delete(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

function diagnosticFailure(invocation, error) {
  invocation.active = false;
  invocation.readController.abort();
  if (!isCurrentDiagnostic(invocation) || invocation.terminal) {
    if (!invocation.terminal) diagnosticActivity(invocation, "failed");
    return;
  }
  setDeviceDiagnosticsStatus(
    `${error.message} Result unavailable; server state uncertain. ` +
    `${invocation.jobId ? `Job ${invocation.jobId}: Cancel or check Pending Jobs.` : "Check Pending Jobs."}`,
    true,
  );
  setDeviceDiagnosticsPending(false);
}

function finishDeviceDiagnostic(invocation, payload) {
  invocation.terminal = true;
  invocation.active = false;
  invocation.readController.abort();
  if (!isCurrentDiagnostic(invocation)) return;
  deviceDiagnosticsState.jobId = null;
  if (payload.result) renderDeviceDiagnosticResult(payload.result, payload.detail || "");
  setDeviceDiagnosticsStatus(
    payload.result ? deviceActionStatusLabel(payload.result.status)
      : `Server diagnostic ${payload.status}${payload.detail ? `: ${payload.detail}` : "."}`,
    payload.status === "error" || payload.result?.status === "failed",
  );
  setDeviceDiagnosticsPending(false);
}

async function cancelDeviceDiagnostic(invocation = deviceDiagnosticsState.invocation, automatic = false) {
  if (!invocation || invocation.terminal) return;
  invocation.cancelIntent = true;
  if (invocation.cancelPromise) return invocation.cancelPromise;
  if (!invocation.jobId) {
    if (isCurrentDiagnostic(invocation)) {
      setDeviceDiagnosticsStatus("Cancellation requested; awaiting submission acceptance.");
      setDeviceDiagnosticsPending(true, true);
    }
    return;
  }
  if (automatic && invocation.disposalAttempted) return;
  if (automatic) invocation.disposalAttempted = true;
  invocation.cancelPromise = (async () => {
    try {
      if (isCurrentDiagnostic(invocation)) {
        setDeviceDiagnosticsStatus("Cancellation requested; server state not yet confirmed.");
        setDeviceDiagnosticsPending(invocation.active, true);
      }
      const { response, payload } = await diagnosticRequest(invocation,
        `/api/device-action-jobs/${encodeURIComponent(invocation.jobId)}`,
        { method: "DELETE", cache: "no-store" });
      validateDiagnosticEnvelope(payload, invocation);
      if (response.status === 409 && !["done", "error", "cancelled"].includes(payload.status)) {
        throw diagnosticProtocolError();
      }
      if (["done", "error", "cancelled"].includes(payload.status)) {
        finishDeviceDiagnostic(invocation, payload);
      } else if (isCurrentDiagnostic(invocation) && !invocation.active &&
          invocation.acceptedAt !== null) {
        diagnosticPollRemaining(invocation);
        invocation.readController = new AbortController();
        invocation.active = true;
        setDeviceDiagnosticsPending(true, true);
        try {
          await pollDeviceActionJob(invocation);
        } catch (error) {
          diagnosticFailure(invocation, error);
        }
      }
    } catch (error) {
      if (isCurrentDiagnostic(invocation)) {
        setDeviceDiagnosticsStatus(
          `Cancellation unconfirmed (${error.message}); server state uncertain. ` +
          `Job ${invocation.jobId}: retry Cancel or check Pending Jobs.`, true,
        );
      } else diagnosticActivity(invocation, "failed");
    } finally {
      invocation.cancelPromise = null;
      if (isCurrentDiagnostic(invocation)) setDeviceDiagnosticsPending(invocation.active);
    }
  })();
  return invocation.cancelPromise;
}

function appendDiagnosticResultRow(listEl, label, value) {
  const termEl = document.createElement("dt");
  termEl.textContent = label;
  const valueEl = document.createElement("dd");
  valueEl.textContent = value ?? "Not reported";
  listEl.append(termEl, valueEl);
}

function formatDiagnosticDuration(durationSeconds) {
  return Number.isFinite(durationSeconds)
    ? `${Math.round(durationSeconds * 1000)} ms`
    : "Not reported";
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
  appendDiagnosticResultRow(
    listEl,
    "Duration",
    formatDiagnosticDuration(result.durationSeconds),
  );
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
      duration: formatDiagnosticDuration(attempt.durationSeconds),
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

function diagnosticPollRemaining(invocation) {
  const remaining = invocation.deadlineSeconds * 1000 + 30000 -
    (performance.now() - invocation.acceptedAt);
  if (remaining <= 0) throw new Error("Diagnostic local polling timeout.");
  return remaining;
}

async function diagnosticPollDelay(invocation) {
  const remaining = diagnosticPollRemaining(invocation);
  const signal = invocation.readController.signal;
  let timer;
  let onAbort;
  try {
    await new Promise((resolve, reject) => {
      onAbort = () => reject(new DOMException("Diagnostic read stopped locally.", "AbortError"));
      if (signal.aborted) return onAbort();
      signal.addEventListener("abort", onAbort, { once: true });
      timer = setTimeout(resolve, Math.min(500, remaining));
      invocation.timers.add(timer);
    });
  } finally {
    clearTimeout(timer);
    invocation.timers.delete(timer);
    signal.removeEventListener("abort", onAbort);
  }
}

async function pollDeviceActionJob(invocation) {
  while (isCurrentDiagnostic(invocation) && !invocation.terminal) {
    const { response, payload } = await diagnosticRequest(invocation,
      `/api/device-action-jobs/${encodeURIComponent(invocation.jobId)}`, {
        headers: { Accept: "application/json" }, cache: "no-store",
      }, invocation.readController.signal, Math.min(15000, diagnosticPollRemaining(invocation)));
    if (!isCurrentDiagnostic(invocation) || invocation.terminal) return;
    diagnosticPollRemaining(invocation);
    if (response.status !== 200) throw diagnosticProtocolError();
    validateDiagnosticEnvelope(payload, invocation);
    if (payload.status !== invocation.status) {
      invocation.status = payload.status;
      diagnosticActivity(invocation, "changed", "Device action job status changed");
    }
    if (["running", "cancelling"].includes(payload.status)) {
      setDeviceDiagnosticsStatus(
        payload.status === "cancelling"
          ? "Server cancellation pending..."
          : invocation.cancelIntent ? "Cancellation requested; server diagnostic still running."
            : `Diagnostic running (${formatDuration(performance.now() - invocation.acceptedAt)})...`,
      );
      setDeviceDiagnosticsPending(true, Boolean(invocation.cancelPromise));
      await diagnosticPollDelay(invocation);
      continue;
    }
    finishDeviceDiagnostic(invocation, payload);
    return;
  }
}

async function invokeDeviceDiagnostic(action) {
  const model = deviceDiagnosticsState.model;
  if (!model || deviceDiagnosticsState.invocation?.active) return;
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
  invalidateDeviceDiagnostic();
  const invocation = {
    version: invocationVersion, id: invocationId,
    targetIdentity: `${model.deviceId}:${target?.address ?? model.nodeId}`,
    action, submissionStart: performance.now(), deadlineSeconds: payload.deadlineSeconds,
    jobId: null, acceptedAt: null, active: true, terminal: false,
    cancelIntent: false, cancelPromise: null, disposalAttempted: false,
    readController: new AbortController(), timers: new Set(),
  };
  deviceDiagnosticsState.invocation = invocation;
  deviceDiagnosticsState.jobId = null;
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
    const { response, payload: responsePayload } = await diagnosticRequest(invocation, "/api/device-actions", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      cache: "no-store",
      body: JSON.stringify(payload),
    });
    if (typeof responsePayload?.job_id === "string" && responsePayload.job_id.trim()) {
      invocation.jobId = responsePayload.job_id;
      if (isCurrentDiagnostic(invocation)) deviceDiagnosticsState.jobId = invocation.jobId;
    }
    try {
      if (response.status !== 202 || !invocation.jobId) throw diagnosticProtocolError();
      validateDiagnosticEnvelope(responsePayload, invocation);
    } catch (error) {
      if (invocation.jobId && (invocation.cancelIntent || !isCurrentDiagnostic(invocation))) {
        await cancelDeviceDiagnostic(invocation, true);
      }
      throw error;
    }
    invocation.acceptedAt = performance.now();
    invocation.status = responsePayload.status;
    if (isCurrentDiagnostic(invocation)) {
      diagnosticActivity(invocation, "started", "Device action job started");
    }
    if (invocation.cancelIntent || !isCurrentDiagnostic(invocation)) {
      const cancellation = cancelDeviceDiagnostic(invocation, !isCurrentDiagnostic(invocation));
      if (!isCurrentDiagnostic(invocation)) {
        await cancellation;
        invocation.active = false;
        return;
      }
    }
    if (["done", "error", "cancelled"].includes(responsePayload.status)) {
      finishDeviceDiagnostic(invocation, responsePayload);
      return;
    }
    await pollDeviceActionJob(invocation);
  } catch (error) {
    diagnosticFailure(invocation, error);
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
    invalidateDeviceDiagnostic();
    deviceDiagnosticsState.invocationVersion += 1;
    deviceDiagnosticsState.jobId = null;
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
  document.getElementById("btn-device-diagnostics-cancel").addEventListener("click", () => {
    void cancelDeviceDiagnostic();
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
  const summaryEl = document.getElementById("health-insights-summary");
  const navigationEl = document.getElementById("health-insights-navigation");
  const tableWrapEl = document.getElementById("health-finding-table-wrap");
  if (!contentEl) return;
  const healthEligible = currentDataset?.entry?.healthEligible === true;
  summaryEl?.toggleAttribute("hidden", !healthEligible || !healthInsightsState.assessment);
  navigationEl?.toggleAttribute("hidden", !healthEligible);
  if (!healthEligible) summaryEl?.replaceChildren();
  document.getElementById("health-insights-filters")?.toggleAttribute("hidden", !healthEligible);
  healthWorkspaceEl?.toggleAttribute("hidden", !healthEligible);
  contentEl.toggleAttribute("hidden", healthEligible);
  renderHealthAssessmentHistory(
    document.getElementById("health-assessment-history"),
    {
      ...healthAssessmentHistoryState,
      assessment: healthInsightsState.assessment,
      loading: healthInsightsState.loading,
      selectedAssessmentId: healthAssessmentHistoryState.mode === "pinned"
        ? healthAssessmentHistoryState.pinnedAssessmentId
        : healthInsightsState.assessment?.assessmentId ?? null,
    },
    {
      followLatest: followLatestHealthAssessment,
      selectAssessment: selectHealthAssessment,
      selectOldest: () => {
        void loadHealthAssessmentHistoryPage(0, {
          selectedAssessmentId: null, selectOldest: true, announce: true,
        });
      },
      page: (offset) => {
        void loadHealthAssessmentHistoryPage(offset, { announce: true });
      },
      retry: () => { void retryHealthAssessmentHistory(); },
      retryTarget: () => { void refreshHealthAssessment(); },
      chooserToggle: (open) => { healthAssessmentHistoryState.chooserOpen = open; },
    },
  );
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
        healthInsightsViewState.selectedEndpointId = null;
        healthInsightsViewState.detailsOpen = false;
        setContextDetailsMode("device");
        contextDetailsController.setCollapsed(true);
      }
    }
    renderHealthInsights(healthWorkspaceEl, healthInsightsState, healthInsightsViewState, {
      selectGroup: selectHealthFindingGroup,
      availableTargets: countAvailableHealthTargets,
      availableTopologyTargets: countAvailableTopologyHealthTargets,
      canInspectDevice: (deviceId) => Boolean(findCurrentDeviceRecord(deviceId)),
      inspectEndpoint: inspectHealthFindingEndpoint,
      inspectRelatedDevice: inspectHealthRelatedDevice,
      inspectDevice: (group) => {
        const deviceId = group.deviceIds[0];
        const finding = group.findings.find(({ deviceIds = [] }) => deviceIds.includes(deviceId));
        inspectHealthFindingEndpoint(group.groupId, finding?.findingId ?? null, deviceId);
      },
      changeSort: (sort) => {
        healthInsightsViewState.sort = sort;
        healthInsightsViewState.sortWasChanged = true;
        document.getElementById("health-findings-sort").value = sort.column;
        renderNetworkInsights();
      },
    });
    document.getElementById("health-findings-sort").value = healthInsightsViewState.sort.column;
    const summary = summaryEl;
    summary.replaceChildren();
    if (assessment) {
      appendNetworkInsightElement(summary, "strong",
        `Selected assessment: ${assessment.status} · ${assessment.completeness} · ${assessment.confidence} confidence`);
      const observedAt = appendNetworkInsightElement(summary, "span",
        formatHealthAssessmentObservation(assessment.observedAt));
      if (assessment.observedAt) observedAt.title = assessment.observedAt;
      appendNetworkInsightElement(summary, "span", `${assessment.coverage?.deviceCount ?? "Unknown"} observed devices`);
    }
    const findingCount = projectHealthSummaryRows(assessment?.findingGroups || [], healthInsightsViewState).length;
    document.getElementById("health-findings-count").textContent = String(findingCount);
    document.getElementById("health-tab-findings").setAttribute("aria-label",
      formatHealthInsightsTabAccessibleName("Findings", findingCount, "group"));
    const rosterCount = healthInsightsState.roster
      ? healthInsightsState.roster.filteredTotal : null;
    document.getElementById("health-roster-count").textContent = rosterCount === null
      ? "" : String(rosterCount);
    document.getElementById("health-tab-roster").setAttribute("aria-label",
      formatHealthInsightsTabAccessibleName("Device Roster", rosterCount, "device"));
    for (const { id, buttonId, panelId } of HEALTH_INSIGHTS_TABS) {
      const active = healthInsightsTab === id;
      const button = document.getElementById(buttonId);
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      document.getElementById(panelId).hidden = !active;
    }
    const rosterWrap = document.querySelector(".health-roster-table-wrap");
    if (rosterWrap && healthInsightsTab === "roster") {
      healthRosterViewState.tableScrollTop = rosterWrap.scrollTop;
      healthRosterViewState.tableScrollLeft = rosterWrap.scrollLeft;
    }
    renderHealthRoster(document.getElementById("health-roster"), healthInsightsState.roster,
      { ...healthRosterViewState, loading: healthInsightsState.rosterLoading,
        error: healthInsightsState.rosterError }, {
        select: selectRosterDevice,
        page: (offset, action) => {
          rosterNavigationGeneration += 1;
          healthRosterViewState.pageFocusTarget = action;
          void loadRosterPage(offset);
        },
        pageSize: changeRosterPageSize,
        sort: changeRosterSort,
        focusRestored: () => {
          healthRosterViewState.sortFocusColumn = null;
          healthRosterViewState.pageFocusTarget = null;
        },
      });
    const newRosterWrap = document.querySelector(".health-roster-table-wrap");
    if (newRosterWrap) {
      newRosterWrap.scrollTop = healthRosterViewState.tableScrollTop;
      newRosterWrap.scrollLeft = healthRosterViewState.tableScrollLeft;
    }
    const endpointSelectionAvailable =
      healthInsightsState.capabilities?.comparisonEndpointSelection === 1;
    const previousComparisonWrap = document.querySelector(".health-comparison-table-wrap");
    if (previousComparisonWrap && healthInsightsTab === "comparison") {
      healthInsightsViewState.comparisonTableScrollTop = previousComparisonWrap.scrollTop;
      healthInsightsViewState.comparisonTableScrollLeft = previousComparisonWrap.scrollLeft;
    }
    const comparisonEl = document.getElementById("health-comparison");
    if (tableWrapEl) tableWrapEl.hidden = false;
    if (healthInsightsTab === "comparison" && currentView === "insights") {
      renderHealthComparison(comparisonEl, healthInsightsState.comparisonPage,
        healthInsightsState.comparison, {
          supportLoading: healthInsightsState.loading && !healthInsightsState.capabilities
            && !healthInsightsState.error,
          supportError: healthInsightsState.supportError,
          capabilityKnown: Boolean(healthInsightsState.capabilities),
          comparisonReadModel: healthInsightsState.capabilities?.comparisonReadModel === 1,
          assessmentAvailable: Boolean(healthInsightsState.assessment),
          assessmentError: healthInsightsState.error,
          listLoading: healthInsightsState.loading || healthInsightsState.comparisonListLoading,
          listError: healthInsightsState.comparisonListError,
          endpointSelection: endpointSelectionAvailable,
          endpointPages: healthInsightsState.comparisonEndpointPages,
          latestPresetPage: healthInsightsState.comparisonLatestPresetPage,
          endpointLoading: healthInsightsState.comparisonEndpointLoading,
          endpointErrors: healthInsightsState.comparisonEndpointErrors,
          before: healthInsightsState.comparisonEndpointPages.before?.selected
            || healthInsightsState.comparisonEndpointPages.before?.items.find(
              (item) => item.assessmentId === healthInsightsViewState.beforeAssessmentId,
            )
            || healthInsightsState.comparisonEndpointPages.after?.defaultBefore,
          after: healthInsightsState.comparisonEndpointPages.after?.selected
            || healthInsightsState.comparisonEndpointPages.after?.items.find(
              (item) => item.assessmentId === healthInsightsViewState.afterAssessmentId,
            )
            || healthInsightsState.comparisonEndpointPages.after?.defaultAfter,
          beforeAssessmentId: healthInsightsViewState.beforeAssessmentId,
          afterAssessmentId: healthInsightsViewState.afterAssessmentId,
          beforeHistoryOffset: healthInsightsViewState.beforeHistoryOffset,
          afterHistoryOffset: healthInsightsViewState.afterHistoryOffset,
          endpointPairLoading: healthInsightsState.comparisonEndpointPairLoading,
          endpointPairError: healthInsightsState.comparisonEndpointPairError,
          endpointUnavailable: healthInsightsState.comparisonEndpointUnavailable,
          presetLoading: healthInsightsState.comparisonPresetLoading,
          presetError: healthInsightsState.comparisonPresetError,
          comparisonPolicyDigest: healthInsightsState.capabilities?.comparisonPolicyDigest,
          comparisonVersion: healthInsightsState.capabilities?.comparisonVersion,
          detailLoading: healthInsightsState.comparisonDetailLoading,
          detailError: healthInsightsState.comparisonDetailError,
          comparisonId: healthInsightsViewState.comparisonId,
          intent: healthInsightsViewState.comparisonIntent,
          customOpen: healthInsightsViewState.comparisonCustomOpen,
          detailsOpen: healthInsightsViewState.comparisonDetailsOpen,
          itemsLoading: healthInsightsState.comparisonEndpointPairLoading
            || healthInsightsState.comparisonDetailLoading,
          focusTarget: healthInsightsViewState.comparisonFocusTarget,
          tableScrollTop: healthInsightsViewState.comparisonTableScrollTop,
          scope: healthInsightsViewState.comparisonScope,
          result: healthInsightsViewState.comparisonResult,
          q: healthInsightsViewState.comparisonSearch,
          sort: healthInsightsViewState.comparisonSort,
          direction: healthInsightsViewState.comparisonDirection,
          controlFocusTarget: healthInsightsViewState.comparisonControlFocusTarget,
        }, {
          select: selectComparison, page: loadComparisonPage, items: loadComparisonItems,
          pageSize: changeComparisonPageSize,
          retry: () => { void refreshHealthAssessment(); },
          retryDetail: () => { void healthComparisonDetailController.retrySelected(); },
          focusRestored: () => { healthInsightsViewState.comparisonFocusTarget = null; },
          controlFocusRestored: () => {
            healthInsightsViewState.comparisonControlFocusTarget = null;
          },
          endpointSelect: selectComparisonEndpoint,
          endpointPage: loadComparisonEndpointPage,
          preset: selectComparisonPreset,
          customOpen: setComparisonCustomOpen,
          detailsOpen: (open) => {
            healthInsightsViewState.comparisonDetailsOpen = open;
            renderNetworkInsights();
          },
          scope: (scope) => changeComparisonFilter("scope", scope),
          result: (result) => changeComparisonFilter("result", result),
          search: changeComparisonSearch,
          order: changeComparisonOrder,
          canInspect: (deviceId) => Boolean(findCurrentDeviceRecord(deviceId)),
          inspect: (deviceId) => navigateToHealthTargets("table", { deviceIds: [deviceId] }),
        });
    }
    const updatedComparisonWrap = document.querySelector(".health-comparison-table-wrap");
    if (currentView === "insights" && healthInsightsTab === "comparison" && updatedComparisonWrap) {
      updatedComparisonWrap.scrollTop = healthInsightsViewState.comparisonTableScrollTop;
      updatedComparisonWrap.scrollLeft = healthInsightsViewState.comparisonTableScrollLeft;
    }
    if (tableWrapEl) tableWrapEl.scrollTop = healthInsightsViewState.tableScrollTop;
    renderSelectedHealthFinding();
    renderHealthRefreshStatus();
    return;
  }
  renderLegacyNetworkInsights(contentEl, currentDataset);
}

function renderLegacyNetworkInsights(contentEl, dataset) {
  contentEl.replaceChildren();

  if (!dataset) {
    appendNetworkInsightElement(
      contentEl,
      "p",
      "Load a dataset to view network diagnostic insights.",
      "network-insights-empty",
    );
    return;
  }

  if (dataset.entry.healthEligible === false) {
    appendNetworkInsightElement(
      contentEl,
      "p",
      "Health assessment is unavailable for this dataset.",
      "network-insights-empty",
    );
    return;
  }

  const model = aggregateNetworkDiagnosticsForRows(dataset.rows);
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
  const matchingAssessment = assessment && currentDataset?.entry?.healthEligible === true &&
    assessment.datasetId === currentDataset.entry.value
    ? assessment
    : null;
  const findings = matchingAssessment
    ? projectVisibleHealthFindingGroups(matchingAssessment.findingGroups).flatMap(
      (group) => group.findings || [],
    )
    : [];
  setTopologyHealthFindings(findings, healthTopologyColoringEnabled && matchingAssessment !== null);
  setTableHealthFindings(findings, matchingAssessment?.observedAt ?? "", matchingAssessment !== null);
  updateHealthPresentationControls();
}

function getCurrentHealthAssessment() {
  const entry = currentDataset?.entry;
  const assessment = healthInsightsState.assessment;
  return entry?.healthEligible === true && assessment?.datasetId === entry.value &&
    !healthInsightsState.error
    ? assessment
    : null;
}

function setHealthColoringEnabled(enabled) {
  healthTopologyColoringEnabled = enabled === true;
  healthColoringPreferenceSet = true;
  writeBooleanPreference(HEALTH_COLORING_PREFERENCE_KEY, healthTopologyColoringEnabled);
  applyHealthAssessmentPresentation(getCurrentHealthAssessment());
  renderNetworkInsights();
  renderHealthStatusSummary();
}

function enableHealthColoringOnFirstInsightsVisit() {
  if (currentView !== "insights" || healthColoringPreferenceSet || !getCurrentHealthAssessment()) return;
  setHealthColoringEnabled(true);
}

function setHealthColumnsEnabled(enabled) {
  healthTableColumnsEnabled = enabled === true;
  writeBooleanPreference(HEALTH_COLUMNS_PREFERENCE_KEY, healthTableColumnsEnabled);
  setTableHealthColumnsEnabled(healthTableColumnsEnabled);
  if (currentView === "table" && currentDataset) {
    applyTableFilters({ preserveSelection: true });
  }
  updateHealthPresentationControls();
}

function updateHealthPresentationControls() {
  const healthEligible = currentDataset?.entry?.healthEligible === true;
  const available = getCurrentHealthAssessment() !== null;
  const coloringButton = document.getElementById("btn-health-coloring");
  if (coloringButton) {
    coloringButton.hidden = currentView !== "topology" || !healthEligible;
    coloringButton.disabled = !available;
    coloringButton.setAttribute("aria-pressed", String(healthTopologyColoringEnabled));
    coloringButton.classList.toggle("active", healthTopologyColoringEnabled);
    coloringButton.title = available
      ? `${healthTopologyColoringEnabled ? "Hide" : "Show"} health coloring`
      : "Health coloring is unavailable until an assessment is loaded for this dataset";
  }
  const columnsButton = document.getElementById("btn-health-columns");
  if (columnsButton) {
    columnsButton.hidden = currentView !== "table" || !healthEligible;
    columnsButton.disabled = !available;
    columnsButton.setAttribute("aria-pressed", String(healthTableColumnsEnabled));
    columnsButton.classList.toggle("active", healthTableColumnsEnabled);
    columnsButton.title = available
      ? `${healthTableColumnsEnabled ? "Hide" : "Show"} health columns in table view`
      : "Health columns are unavailable until an assessment is loaded for this dataset";
  }
}

function renderHealthStatusSummary() {
  renderHealthStatus(document.getElementById("health-status-summary"), {
    ...healthInsightsState,
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
  healthInsightsViewState.selectedGroupId = groupId;
  healthInsightsViewState.selectedFindingId = null;
  healthInsightsViewState.selectedEndpointId = null;
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

function ensureFindingRosterActionEligibility(model, assessment) {
  if (healthInsightsState.capabilities?.rosterMutation !== 1 || !assessment) return;
  for (const item of model.items) {
    if (!item.isExpanded || item.endpointIds.length !== 1
        || item.finding.scope !== "device") continue;
    const deviceId = item.endpointIds[0];
    const key = `${assessment.assessmentId}\n${deviceId}`;
    if (findingRosterActionEligibility.has(key) || findingRosterActionPending.has(key)) continue;
    findingRosterActionPending.add(key);
    void fetchHealthRosterDevice(
      assessment.networkId, deviceId, undefined, assessment.assessmentId,
    ).then((detail) => {
      findingRosterActionEligibility.set(key, { detail, error: null });
    }).catch((error) => {
      findingRosterActionEligibility.set(key, { detail: null, error });
    }).finally(() => {
      findingRosterActionPending.delete(key);
      if (healthInsightsState.assessment?.assessmentId === assessment.assessmentId
          && healthInsightsViewState.detailsOpen
          && healthInsightsViewState.selectedGroupId === model.groupId) {
        renderSelectedHealthFinding();
      }
    });
  }
}

function renderSelectedHealthFinding() {
  if (healthInsightsTab !== "findings" || !healthInsightsViewState.detailsOpen
      || !healthInsightsViewState.selectedGroupId) return;
  const group = resolveHealthFindingGroup(healthInsightsViewState.selectedGroupId);
  if (!group) {
    closeHealthFindingDetails({ restoreFocus: false });
    return;
  }
  const model = projectHealthFindingDetail(
    group,
    healthInsightsViewState.selectedFindingId,
    healthInsightsViewState.selectedEndpointId,
  );
  const assessment = healthInsightsState.assessment;
  ensureFindingRosterActionEligibility(model, assessment);
  const heading = document.getElementById("health-finding-details-heading");
  if (heading) heading.textContent = model.heading;
  const availableDeviceIds = new Set(
    (group.deviceIds || []).filter((deviceId) => findCurrentDeviceRecord(deviceId)),
  );
  const relatedCurrentDeviceIds = new Set(
    (model.relatedDevices || [])
      .map(({ deviceId }) => deviceId)
      .filter((deviceId) => findCurrentDeviceRecord(deviceId)),
  );
  const storedInspectableDeviceIds = new Set();
  const rosterActionsByDevice = new Map();
  const rosterActionErrors = new Map();
  for (const item of model.items) {
    if (!item.isExpanded || item.endpointIds.length !== 1) continue;
    const deviceId = item.endpointIds[0];
    const eligibility = findingRosterActionEligibility.get(
      `${assessment?.assessmentId}\n${deviceId}`,
    );
    if (eligibility?.detail) {
      storedInspectableDeviceIds.add(deviceId);
      rosterActionsByDevice.set(deviceId, eligibility.detail.allowedActions || []);
    } else if (eligibility?.error) {
      rosterActionErrors.set(deviceId, eligibility.error.message);
    }
  }
  const deviceAvailability = projectFindingDeviceAvailability(
    availableDeviceIds, storedInspectableDeviceIds,
  );
  const inspectableDeviceIds = new Set([
    ...deviceAvailability.inspectableDeviceIds,
    ...relatedCurrentDeviceIds,
  ]);
  renderHealthFindingDetails(document.getElementById("health-finding-details-content"), model, {
    mutationAvailable: healthInsightsState.capabilities?.rosterMutation === 1,
    rosterActionsByDevice,
    rosterActionErrors,
    availableTargets: deviceAvailability.availableTargets,
    availableTopologyTargets: countAvailableTopologyHealthTargets(group),
    groupDeviceCount: group.deviceIds?.length ?? 0,
    inspectableDeviceIds,
    selectFinding: (findingId, endpointId) => {
      const selection = toggleHealthFindingEndpointSelection(
        healthInsightsViewState.selectedFindingId,
        healthInsightsViewState.selectedEndpointId,
        findingId,
        endpointId,
      );
      healthInsightsViewState.selectedFindingId = selection.findingId;
      healthInsightsViewState.selectedEndpointId = selection.endpointId;
      contextDetailsState.finding = {
        assessmentId: healthInsightsState.assessment?.assessmentId ?? null,
        groupId: healthInsightsViewState.selectedGroupId,
        findingId: selection.findingId,
        endpointId: selection.endpointId,
      };
      renderSelectedHealthFinding();
      requestAnimationFrame(() => document.querySelector(
        `.health-affected-select[data-finding-id="${CSS.escape(findingId)}"]`
          + (endpointId ? `[data-device-id="${CSS.escape(endpointId)}"]` : ""),
      )?.focus({ preventScroll: true }));
    },
    showTopology: (selectedGroupId) => navigateToHealthTargets(
      "topology", resolveHealthFindingGroup(selectedGroupId),
    ),
    showTable: (selectedGroupId) => navigateToHealthTargets(
      "table", resolveHealthFindingGroup(selectedGroupId),
    ),
    inspectDevice: (deviceId, findingId, endpointId, focusKey) => inspectHealthDevice(
      deviceId, findingId, endpointId, focusKey,
    ),
    inspectRelatedDevice: (groupId, findingId, deviceId, focusKey) => inspectHealthRelatedDevice(
      groupId, findingId, deviceId, focusKey,
    ),
    rosterAction: (action, deviceId) => {
      const detail = findingRosterActionEligibility.get(
        `${assessment?.assessmentId}\n${deviceId}`,
      )?.detail;
      void beginRosterAction(action, deviceId, detail);
    },
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
  const assessment = healthInsightsState.assessment;
  if (assessment) {
    const statusFiles = currentDataset
      ? [...new Set([
        ...(currentDataset.loadedFiles ?? currentDataset.entry.files ?? []),
        ...Object.keys(currentDataset.auxiliaryFiles ?? {}),
      ])]
      : [];
    if (!networkInstanceMatchesId(statusFiles, sourceCapabilities, assessment.networkId)
        || currentDataset?.entry?.value !== assessment.datasetId) {
      return null;
    }
  }
  return currentDataset?.rows?.find(
    (record) => projectSelectedDevice(record)?.extAddress === extAddress,
  ) ?? null;
}

function countAvailableHealthTargets(group) {
  return currentHealthTargetIds(group).length;
}

function countAvailableTopologyHealthTargets(group) {
  return currentTopologyHealthTargetIds(group).length;
}

function currentHealthTargetIds(group) {
  return [...new Set(group?.deviceIds || [])].filter((deviceId) => findCurrentDeviceRecord(deviceId));
}

function currentTopologyHealthTargetIds(group) {
  const resolvedTargets = currentHealthTargetIds(group)
    .map((deviceId) => ({ deviceId, nodeId: topologyNodeIdForHealthDevice(deviceId) }))
    .filter(({ nodeId }) => nodeId !== null);
  const nodeCounts = new Map();
  resolvedTargets.forEach(({ nodeId }) => nodeCounts.set(nodeId, (nodeCounts.get(nodeId) ?? 0) + 1));
  return resolvedTargets
    .filter(({ nodeId }) => nodeCounts.get(nodeId) === 1)
    .map(({ deviceId }) => deviceId);
}

function topologyNodeIdForHealthDevice(deviceId) {
  const record = findCurrentDeviceRecord(deviceId);
  const viewModel = record ? getCurrentHealthTopologyViewModel() : null;
  return viewModel ? resolveTopologyNodeId(viewModel, record) : null;
}

function rememberHealthNavigationContext() {
  if (healthNavigationContext) return;
  const tableWrap = document.getElementById("health-finding-table-wrap");
  const comparisonWrap = document.querySelector(".health-comparison-table-wrap");
  const rosterWrap = document.querySelector(".health-roster-table-wrap");
  if (tableWrap) healthInsightsViewState.tableScrollTop = tableWrap.scrollTop;
  if (comparisonWrap) {
    healthInsightsViewState.comparisonTableScrollTop = comparisonWrap.scrollTop;
    healthInsightsViewState.comparisonTableScrollLeft = comparisonWrap.scrollLeft;
  }
  if (rosterWrap) {
    healthRosterViewState.tableScrollTop = rosterWrap.scrollTop;
    healthRosterViewState.tableScrollLeft = rosterWrap.scrollLeft;
  }
  healthNavigationContext = {
    view: currentView,
    healthTab: healthInsightsTab,
    search: document.getElementById("search-input")?.value ?? "",
    nodeFilter: document.getElementById("node-filter")?.value ?? "all",
    linkFilter: document.getElementById("link-filter")?.value ?? "default_links",
    diagnosticFilter: document.getElementById("diagnostic-filter")?.value ?? "all",
    selectedRecord: deviceInsightsState.record,
    focusKey: document.activeElement?.dataset?.healthFocusKey ?? null,
    networkId: healthInsightsState.assessment?.networkId ?? null,
    datasetId: healthInsightsState.assessment?.datasetId ?? null,
    insights: currentView === "insights" ? {
      assessmentId: healthInsightsState.assessment?.assessmentId ?? null,
      view: healthInsightsViewState.view,
      filters: { ...healthInsightsViewState.filters },
      sort: { ...healthInsightsViewState.sort },
      sortWasChanged: healthInsightsViewState.sortWasChanged,
      selectedGroupId: healthInsightsViewState.selectedGroupId,
      selectedFindingId: healthInsightsViewState.selectedFindingId,
      selectedEndpointId: healthInsightsViewState.selectedEndpointId,
      tableScrollTop: healthInsightsViewState.tableScrollTop,
      detailsOpen: healthInsightsViewState.detailsOpen,
      comparisonId: healthInsightsViewState.comparisonId,
      comparisonScope: healthInsightsViewState.comparisonScope,
      comparisonResult: healthInsightsViewState.comparisonResult,
      comparisonSearch: healthInsightsViewState.comparisonSearch,
      comparisonSort: healthInsightsViewState.comparisonSort,
      comparisonDirection: healthInsightsViewState.comparisonDirection,
      comparisonLimit: healthInsightsViewState.comparisonLimit,
      comparisonControlFocusTarget: healthInsightsViewState.comparisonControlFocusTarget,
      comparisonOffset: healthInsightsViewState.comparisonOffset,
      comparisonItemOffset: healthInsightsViewState.comparisonItemOffset,
      comparisonIntent: healthInsightsViewState.comparisonIntent,
      comparisonCustomOpen: healthInsightsViewState.comparisonCustomOpen,
      comparisonDetailsOpen: healthInsightsViewState.comparisonDetailsOpen,
      comparisonFocusTarget: healthInsightsViewState.comparisonFocusTarget,
      comparisonTableScrollTop: healthInsightsViewState.comparisonTableScrollTop,
      comparisonTableScrollLeft: healthInsightsViewState.comparisonTableScrollLeft,
      roster: {
        search: healthRosterViewState.search,
        presence: healthRosterViewState.presence,
        rosterState: healthRosterViewState.rosterState,
        sort: { ...healthRosterViewState.sort },
        limit: healthRosterViewState.limit,
        offset: healthRosterViewState.offset,
        selectedDeviceId: healthRosterViewState.selectedDeviceId,
        tableScrollTop: healthRosterViewState.tableScrollTop,
        tableScrollLeft: healthRosterViewState.tableScrollLeft,
      },
      beforeAssessmentId: healthInsightsViewState.beforeAssessmentId,
      afterAssessmentId: healthInsightsViewState.afterAssessmentId,
      beforeHistoryOffset: healthInsightsViewState.beforeHistoryOffset,
      afterHistoryOffset: healthInsightsViewState.afterHistoryOffset,
    } : null,
  };
  document.getElementById("btn-health-return")?.removeAttribute("hidden");
}

function selectTopologyHealthTargets(deviceIds) {
  const nodeIds = deviceIds
    .map((deviceId) => topologyNodeIdForHealthDevice(deviceId))
    .filter((nodeId) => nodeId !== null);
  const network = getVisNetwork();
  if (!network || nodeIds.length === 0) return;
  const edges = nodeIds.length === 2
    ? network.getConnectedEdges(nodeIds[0]).filter(
      (edgeId) => network.getConnectedEdges(nodeIds[1]).includes(edgeId),
    )
    : [];
  network.setSelection({ nodes: nodeIds, edges }, { highlightEdges: false });
  getTopologyFilterHandlers()?.applySelectionPresentation({ healthTarget: true });
  network.fit({ nodes: nodeIds, animation: { duration: 300, easingFunction: "easeInOutQuad" } });
}

function getCurrentHealthTopologyViewModel() {
  if (!currentDataset) return null;
  if (healthTopologyViewModelCache?.dataset !== currentDataset) {
    const adaptorResult = runAdaptor(currentDataset);
    healthTopologyViewModelCache = {
      dataset: currentDataset,
      viewModel: createTopologyViewModel(
        adaptorResult,
        currentDataset.deviceProjections,
      ),
    };
  }
  return healthTopologyViewModelCache.viewModel;
}

function navigateToHealthTargets(view, group, { compare = false } = {}) {
  const eligibleDeviceIds = view === "topology"
    ? currentTopologyHealthTargetIds(group)
    : currentHealthTargetIds(group);
  if (eligibleDeviceIds.length === 0) return;
  rememberHealthNavigationContext();
  document.getElementById("node-filter").value = "all";
  document.getElementById("diagnostic-filter").value = "all";
  if (view === "topology") document.getElementById("link-filter").value = "all_links";
  const search = compare ? "" : eligibleDeviceIds[0].replace(/^extaddr:/, "");
  document.getElementById("search-input").value = search;
  _currentSearchQuery = parseSearchQuery(search);
  switchView(view);
  applySearch();
  if (view === "topology") {
    selectTopologyHealthTargets(eligibleDeviceIds);
  } else {
    selectTableDeviceById(eligibleDeviceIds[0]);
  }
}

function inspectHealthFindingEndpoint(groupId, findingId, deviceId) {
  const group = resolveHealthFindingGroup(groupId);
  if (!group || !group.deviceIds?.includes(deviceId)) return;
  const finding = group.findings.find(({ findingId: candidateId }) => candidateId === findingId);
  healthInsightsViewState.selectedGroupId = groupId;
  healthInsightsViewState.selectedFindingId = finding ? findingId : null;
  healthInsightsViewState.selectedEndpointId = finding ? deviceId : null;
  healthInsightsViewState.detailsOpen = true;
  contextDetailsState.finding = {
    assessmentId: healthInsightsState.assessment?.assessmentId ?? null,
    groupId,
    findingId: healthInsightsViewState.selectedFindingId,
    endpointId: healthInsightsViewState.selectedEndpointId,
  };
  inspectHealthDevice(deviceId, healthInsightsViewState.selectedFindingId, deviceId);
}

function inspectHealthRelatedDevice(groupId, findingId, deviceId, focusKey = null) {
  const group = resolveHealthFindingGroup(groupId);
  const relation = projectHealthFindingDetail(group)?.relatedDevices.find(
    (candidate) => candidate.deviceId === deviceId && candidate.findingId === findingId,
  );
  if (!relation) return;
  const returnFindingId = healthInsightsViewState.selectedFindingId;
  const returnEndpointId = healthInsightsViewState.selectedEndpointId;
  healthInsightsViewState.selectedGroupId = groupId;
  healthInsightsViewState.selectedFindingId = null;
  healthInsightsViewState.selectedEndpointId = null;
  healthInsightsViewState.detailsOpen = true;
  contextDetailsState.finding = {
    assessmentId: healthInsightsState.assessment?.assessmentId ?? null,
    groupId,
    findingId: null,
    endpointId: null,
  };
  inspectHealthDevice(deviceId, returnFindingId, returnEndpointId, focusKey, deviceId);
}

function inspectHealthDevice(deviceId, findingId = null, endpointId = null, focusKey = null, relatedDeviceId = null) {
  const record = findCurrentDeviceRecord(deviceId);
  if (healthInsightsViewState.selectedGroupId) {
    findingDeviceReturnContext = {
      assessmentId: healthInsightsState.assessment?.assessmentId ?? null,
      groupId: healthInsightsViewState.selectedGroupId,
      findingId: findingId ?? healthInsightsViewState.selectedFindingId,
      endpointId: endpointId ?? healthInsightsViewState.selectedEndpointId,
      focusKey,
      relatedDeviceId,
    };
  } else {
    rememberHealthNavigationContext();
  }
  if (!record) {
    const assessment = healthInsightsState.assessment;
    if (!assessment) return;
    healthRosterViewState.selectedDeviceId = null;
    healthInsightsState.rosterDetail = null;
    document.getElementById("btn-back-to-health-finding")?.removeAttribute("hidden");
    activateHealthTab("roster");
    void selectRosterDevice(deviceId);
    return;
  }
  document.getElementById("device-details")?.classList.remove("roster-selected");
  setContextDetailsMode("device");
  contextDetailsController.setCollapsed(false);
  publishDeviceSelection(record);
  setActiveDeviceDetailsPanel("device-insights-panel");
  document.getElementById("btn-back-to-health-finding")?.removeAttribute("hidden");
  requestAnimationFrame(() => document.getElementById("device-details-heading")?.focus());
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
  const findingId = group.findings.some(({ findingId: candidateId }) => candidateId === context.findingId)
    ? context.findingId
    : null;
  const endpointId = findingId && group.findings.some(({ findingId: candidateId, deviceIds = [] }) =>
    candidateId === findingId && deviceIds.includes(context.endpointId))
    ? context.endpointId
    : null;
  const relatedDevice = context.relatedDeviceId && projectHealthFindingDetail(group).relatedDevices.some(
    ({ deviceId }) => deviceId === context.relatedDeviceId,
  ) ? context.relatedDeviceId : null;
  healthInsightsViewState.selectedGroupId = context.groupId;
  healthInsightsViewState.selectedFindingId = findingId;
  healthInsightsViewState.selectedEndpointId = endpointId;
  healthInsightsViewState.detailsOpen = true;
  contextDetailsState.finding = { ...context, findingId, endpointId };
  if (healthInsightsTab === "findings") {
    renderSelectedHealthFinding();
  } else {
    activateHealthTab("findings");
  }
  requestAnimationFrame(() => {
    const returnTarget = context.focusKey && [...document.querySelectorAll("[data-health-focus-key]")]
      .find(({ dataset }) => dataset.healthFocusKey === context.focusKey);
    const focusSelector = relatedDevice
      ? `.health-related-device-inspect[data-device-id="${CSS.escape(relatedDevice)}"]`
        + (context.findingId
          ? `[data-finding-id="${CSS.escape(context.findingId)}"]`
          : "")
      : findingId
        ? `.health-affected-select[data-finding-id="${CSS.escape(findingId)}"]`
          + (endpointId ? `[data-device-id="${CSS.escape(endpointId)}"]` : "")
        : `.health-finding-select[data-group-id="${CSS.escape(context.groupId)}"]`;
    (returnTarget || document.querySelector(focusSelector))?.focus({ preventScroll: true });
  });
}

function resetHealthFindingState() {
  healthInsightsViewState.view = "all";
  healthInsightsViewState.filters = { status: "all", scope: "all", evidenceKind: "all" };
  healthInsightsViewState.sort = { column: "priority", direction: "ascending" };
  healthInsightsViewState.sortWasChanged = false;
  healthInsightsViewState.selectedGroupId = null;
  healthInsightsViewState.selectedFindingId = null;
  healthInsightsViewState.selectedEndpointId = null;
  healthInsightsViewState.tableScrollTop = 0;
  healthInsightsViewState.detailsOpen = false;
  const viewFilter = document.getElementById("health-view-filter");
  if (viewFilter) viewFilter.value = "all";
  const sortFilter = document.getElementById("health-findings-sort");
  if (sortFilter) sortFilter.value = "priority";
  for (const id of ["health-status-filter", "health-scope-filter", "health-evidence-filter"]) {
    const element = document.getElementById(id);
    if (element) element.value = "all";
  }
}

function resetHealthRosterViewState() {
  healthRosterViewState.search = "";
  healthRosterViewState.presence = "observed";
  healthRosterViewState.rosterState = "all";
  healthRosterViewState.sort = { column: "label", direction: "ascending" };
  healthRosterViewState.limit = 100;
  healthRosterViewState.offset = 0;
  healthRosterViewState.selectedDeviceId = null;
  healthRosterViewState.tableScrollTop = 0;
  healthRosterViewState.tableScrollLeft = 0;
  healthRosterViewState.sortFocusColumn = null;
  healthRosterViewState.pageFocusTarget = null;
  document.getElementById("health-roster-search").value = "";
  document.getElementById("health-roster-presence").value = "observed";
  document.getElementById("health-roster-designation").value = "all";
}

function restoreHealthNavigationContext() {
  if (!healthNavigationContext) return;
  const context = healthNavigationContext;
  healthNavigationContext = null;
  const assessment = healthInsightsState.assessment;
  const contextIdentityMatches = context.networkId === assessment?.networkId &&
    context.datasetId === assessment?.datasetId;
  if (context.insights && !contextIdentityMatches) {
    healthInsightsTab = HEALTH_INSIGHTS_TABS[0].id;
    resetHealthFindingState();
    resetHealthRosterViewState();
    healthInsightsState.rosterDetail = null;
    resetHealthComparisonState();
    contextDetailsState.finding = { assessmentId: null, groupId: null, findingId: null };
    setContextDetailsMode("device");
    contextDetailsController.setCollapsed(true);
    document.getElementById("btn-health-return")?.setAttribute("hidden", "");
    switchView("insights");
    renderCurrentView({ force: true });
    return;
  }
  document.getElementById("node-filter").value = context.nodeFilter;
  document.getElementById("link-filter").value = context.linkFilter;
  document.getElementById("diagnostic-filter").value = context.diagnosticFilter;
  document.getElementById("search-input").value = context.search;
  _currentSearchQuery = parseSearchQuery(context.search);
  if (context.insights) {
    Object.assign(healthInsightsViewState, context.insights);
    healthInsightsTab = context.healthTab ?? HEALTH_INSIGHTS_TABS[0].id;
    Object.assign(
      healthInsightsViewState,
      reconcileHealthInsightsSelection(healthInsightsViewState, healthInsightsState.assessment),
    );
    document.getElementById("health-view-filter").value = healthInsightsViewState.view;
    document.getElementById("health-status-filter").value = healthInsightsViewState.filters.status;
    document.getElementById("health-scope-filter").value = healthInsightsViewState.filters.scope;
    document.getElementById("health-evidence-filter").value = healthInsightsViewState.filters.evidenceKind;
    const rosterContext = context.insights.roster;
    if (rosterContext) {
      Object.assign(healthRosterViewState, rosterContext, {
        sort: { ...rosterContext.sort },
        limit: rosterContext.limit ?? 100,
        tableScrollLeft: rosterContext.tableScrollLeft ?? 0,
      });
      document.getElementById("health-roster-search").value = healthRosterViewState.search;
      document.getElementById("health-roster-presence").value = healthRosterViewState.presence;
      document.getElementById("health-roster-designation").value = healthRosterViewState.rosterState;
    }
    healthInsightsState.comparisonDetailError = "";
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
    const returnTarget = context.focusKey && [...document.querySelectorAll("[data-health-focus-key]")]
      .find(({ dataset }) => dataset.healthFocusKey === context.focusKey);
    if (returnTarget) {
      returnTarget.focus({ preventScroll: true });
      return;
    }
    if (contextIdentityMatches && context.view === "insights"
        && context.healthTab === "comparison") {
      document.getElementById("health-tab-comparison")?.focus({ preventScroll: true });
    }
  });
  document.getElementById("btn-health-return")?.setAttribute("hidden", "");
}

function resetHealthComparisonState() {
  healthInsightsState.comparisonResetPendingRefresh = false;
  resetComparisonEndpointState();
  healthInsightsState.comparisonListRequestVersion += 1;
  healthComparisonDetailController.invalidate();
  healthInsightsState.comparisonPage = null;
  healthInsightsState.comparisonListLoading = false;
  healthInsightsState.comparisonListError = "";
}

function updateSavedComparisonNavigationContext() {
  const savedInsights = healthNavigationContext?.insights;
  if (!savedInsights) return;
  for (const key of [
    "comparisonId",
    "comparisonScope",
    "comparisonResult",
    "comparisonSearch",
    "comparisonSort",
    "comparisonDirection",
    "comparisonLimit",
    "comparisonControlFocusTarget",
    "comparisonOffset",
    "comparisonItemOffset",
    "comparisonIntent",
    "comparisonCustomOpen",
    "comparisonDetailsOpen",
    "comparisonFocusTarget",
    "comparisonTableScrollTop",
    "comparisonTableScrollLeft",
    "beforeAssessmentId",
    "afterAssessmentId",
    "beforeHistoryOffset",
    "afterHistoryOffset",
  ]) {
    savedInsights[key] = healthInsightsViewState[key];
  }
}

function resetHealthComparison() {
  resetHealthComparisonState();
  updateSavedComparisonNavigationContext();
  healthInsightsState.comparisonResetPendingRefresh = healthInsightsState.loading;
  renderNetworkInsights();
  if (!healthInsightsState.comparisonResetPendingRefresh
      && healthInsightsTab === "comparison" && currentView === "insights") {
    ensureHealthComparisonLoaded();
  }
}

function resetHealthWorkflow() {
  healthNavigationContext = null;
  findingDeviceReturnContext = null;
  resetHealthFindingState();
  healthInsightsTab = HEALTH_INSIGHTS_TABS[0].id;
  resetHealthComparisonState();
  contextDetailsState.finding = { assessmentId: null, groupId: null, findingId: null };
  setContextDetailsMode("device");
  contextDetailsController.setCollapsed(true);
  document.getElementById("btn-back-to-health-finding")?.setAttribute("hidden", "");
  document.getElementById("btn-health-return")?.setAttribute("hidden", "");
  switchView("insights");
  renderNetworkInsights();
}

function updateSavedFindingNavigationContext() {
  const savedInsights = healthNavigationContext?.insights;
  if (!savedInsights) return;
  for (const key of [
    "view", "filters", "sort", "sortWasChanged", "selectedGroupId",
    "selectedFindingId", "selectedEndpointId", "tableScrollTop", "detailsOpen",
  ]) {
    savedInsights[key] = key === "filters"
      ? { ...healthInsightsViewState.filters }
      : key === "sort"
        ? { ...healthInsightsViewState.sort }
        : healthInsightsViewState[key];
  }
}

function updateSavedRosterNavigationContext() {
  const savedInsights = healthNavigationContext?.insights;
  if (!savedInsights) return;
  savedInsights.roster = {
    search: healthRosterViewState.search,
    presence: healthRosterViewState.presence,
    rosterState: healthRosterViewState.rosterState,
    sort: { ...healthRosterViewState.sort },
    limit: healthRosterViewState.limit,
    offset: healthRosterViewState.offset,
    selectedDeviceId: healthRosterViewState.selectedDeviceId,
    tableScrollTop: healthRosterViewState.tableScrollTop,
    tableScrollLeft: healthRosterViewState.tableScrollLeft,
  };
}

function resetHealthFindings() {
  resetHealthFindingState();
  updateSavedFindingNavigationContext();
  if (contextDetailsState.mode === "finding") {
    contextDetailsState.finding = { assessmentId: null, groupId: null, findingId: null };
    setContextDetailsMode("device");
    contextDetailsController.setCollapsed(true);
  }
  renderNetworkInsights();
}

function resetHealthRoster() {
  clearTimeout(rosterSearchTimer);
  rosterNavigationGeneration += 1;
  healthRosterViewState.requestVersion += 1;
  healthRosterViewState.detailVersion += 1;
  resetHealthRosterViewState();
  healthInsightsState.rosterDetail = null;
  healthInsightsState.rosterDetailPresence = null;
  healthInsightsState.roster = null;
  healthInsightsState.rosterError = "";
  healthInsightsState.rosterLoading = false;
  document.getElementById("device-details").classList.remove("roster-selected");
  contextDetailsController.setCollapsed(true);
  updateSavedRosterNavigationContext();
  if (healthInsightsTab === "roster" && currentView === "insights"
      && healthInsightsState.assessment) {
    void loadRosterPage(0);
  } else {
    renderNetworkInsights();
  }
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

  if (currentView !== "topology" && currentView !== "table") {
    appendDeviceInsightElement(
      contentEl,
      "p",
      "Diagnostic metrics are unavailable in this view.",
      "device-insights-empty",
    );
    return;
  }

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
    if (!isHealthRosterPageForQuery(page, assessment.assessmentId, offset, query.limit)) {
      throw new Error("Invalid device roster response for the selected page.");
    }
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
  rosterNavigationGeneration += 1;
  const networkId = healthInsightsState.assessment?.networkId;
  const assessmentId = healthInsightsState.assessment?.assessmentId;
  const version = ++healthRosterViewState.detailVersion;
  if (!networkId) return;
  healthRosterViewState.selectedDeviceId = deviceId;
  healthInsightsState.rosterDetailPresence = healthInsightsState.roster?.devices.find(
    (device) => device.deviceId === deviceId,
  )?.presenceState;
  renderNetworkInsights();
  try {
    const detail = await fetchHealthRosterDevice(networkId, deviceId, undefined, assessmentId);
    if (version !== healthRosterViewState.detailVersion ||
        assessmentId !== healthInsightsState.assessment?.assessmentId) return;
    healthInsightsState.rosterDetail = detail;
    renderRosterDetailPanel(detail, healthInsightsState.rosterDetailPresence);
    document.getElementById("device-details").classList.add("roster-selected");
    setContextDetailsMode("device");
    contextDetailsController.setCollapsed(false);
    renderNetworkInsights();
    requestAnimationFrame(() => document.getElementById("health-roster-device-heading")?.focus());
  } catch (error) {
    if (version === healthRosterViewState.detailVersion) {
      healthRosterViewState.selectedDeviceId = null;
      announceHealthInsight(`Device details unavailable: ${error.message}`);
      if (findingDeviceReturnContext?.assessmentId === assessmentId) {
        findingDeviceReturnContext = null;
        document.getElementById("btn-back-to-health-finding")?.setAttribute("hidden", "");
      }
      renderNetworkInsights();
    }
  }
}

function renderRosterDetailPanel(detail, presenceState) {
  renderHealthRosterDetail(
    document.getElementById("health-roster-details-content"),
    detail,
    presenceState,
    {
      mutationAvailable: healthInsightsState.capabilities?.rosterMutation === 1,
      pending: rosterMutationPendingDeviceId === detail?.deviceId,
      action: (action, selectedDetail) => {
        void beginRosterAction(action, selectedDetail.deviceId, selectedDetail);
      },
    },
  );
}

function clearRosterMutationRefreshStatus() {
  const status = document.getElementById("health-roster-mutation-status");
  if (!status) return;
  status.replaceChildren();
  status.hidden = true;
}

function showRosterMutationRefreshFailure(capture, error) {
  const status = document.getElementById("health-roster-mutation-status");
  if (!status) return;
  status.replaceChildren();
  status.hidden = false;
  const message = document.createElement("span");
  message.textContent = `Change saved; view refresh failed: ${error.message}`;
  const retry = document.createElement("button");
  retry.type = "button";
  retry.textContent = "Retry refresh";
  retry.addEventListener("click", () => {
    retry.disabled = true;
    void reconcileCommittedRosterAction(capture).then(
      clearRosterMutationRefreshStatus,
      (retryError) => {
        retry.disabled = false;
        message.textContent = `Change saved; view refresh failed: ${retryError.message}`;
      },
    );
  });
  status.append(message, retry);
  announceHealthInsight(`Change saved; view refresh failed: ${error.message}`);
}

const ROSTER_ACTION_TITLES = Object.freeze({
  enroll: "Add to roster",
  "mark-offline": "Designate as intentionally offline",
  "clear-offline": "Clear offline designation",
  retire: "Retire device",
  unretire: "Return to Expected",
});

const ROSTER_ACTION_DESCRIPTIONS = Object.freeze({
  enroll: "Adds this observed device to the Expected roster for future absence monitoring.",
  "mark-offline": "Records operator intent only; it does not send a command to disconnect or power off the device. It will no longer be counted as Missing or Offline.",
  "clear-offline": "Returns this device to Expected and starts a fresh absence-monitoring epoch.",
  retire: "Removes this device from Expected roster monitoring. Observed facts and history are preserved; unretire it to resume monitoring.",
  unretire: "Returns this device to Expected and starts a fresh absence-monitoring epoch.",
});

const ROSTER_ACTION_BUTTON_LABELS = Object.freeze({
  enroll: "Add to roster",
  "mark-offline": "Designate offline",
  "clear-offline": "Clear designation",
  retire: "Retire device",
  unretire: "Return to Expected",
});

const ROSTER_STATE_LABELS = Object.freeze({
  expected: "Expected",
  "intentionally-offline": "Intentionally offline",
  intermittent: "Intermittent",
  retired: "Retired",
  untracked: "Untracked",
});

function beginRosterAction(action, deviceId, knownDetail = null) {
  if (rosterMutationPendingDeviceId) {
    announceHealthInsight("Wait for the pending roster action to finish before starting another.");
    return;
  }
  const assessment = healthInsightsState.assessment;
  if (!assessment || healthInsightsState.capabilities?.rosterMutation !== 1) {
    announceHealthInsight("Roster actions are unavailable on this server.");
    return;
  }
  const capture = {
    action,
    deviceId,
    networkId: assessment.networkId,
    datasetId: assessment.datasetId,
    assessmentId: assessment.assessmentId,
    generation: healthInsightsState.assessmentRequestVersion,
    navigation: {
      generation: rosterNavigationGeneration,
      tab: healthInsightsTab,
      view: currentView,
      deviceId: healthRosterViewState.selectedDeviceId,
      groupId: healthInsightsViewState.selectedGroupId,
      findingId: healthInsightsViewState.selectedFindingId,
    },
  };
  const showConfirmation = (detail) => {
    if (healthInsightsState.assessment?.networkId !== capture.networkId
        || healthInsightsState.assessment?.assessmentId !== capture.assessmentId
        || healthInsightsState.assessmentRequestVersion !== capture.generation) {
      announceHealthInsight("The assessment changed; reopen roster details before acting.");
      return;
    }
    if (!detail.allowedActions?.includes(action)) {
      announceHealthInsight(
        `Action unavailable: ${detail.disabledActionReasons?.[action] || "invalid-transition"}.`,
      );
      return;
    }
    activeRosterAction = {
      ...capture,
      revision: detail.revision,
      detail,
    };
    activeRosterRequest = null;
    const dialog = document.getElementById("health-roster-action-dialog");
    const labelRow = document.getElementById("health-roster-action-label-row");
    const label = document.getElementById("health-roster-action-label");
    const labelHint = document.getElementById("health-roster-action-label-hint");
    const reason = document.getElementById("health-roster-action-reason");
    document.getElementById("health-roster-action-heading").textContent =
      ROSTER_ACTION_TITLES[action] || "Confirm roster action";
    const context = document.getElementById("health-roster-action-context");
    context.replaceChildren();
    const identityRows = [
      ["Device", detail.displayLabel],
      ["Network", capture.networkId],
      ["Extended address", capture.deviceId.replace(/^extaddr:/, "")],
      ["Current designation", ROSTER_STATE_LABELS[detail.rosterState] || detail.rosterState],
      ["Change", ROSTER_ACTION_TITLES[action] || action],
    ];
    for (const [labelText, value] of identityRows) {
      const term = document.createElement("dt");
      term.textContent = labelText;
      const description = document.createElement("dd");
      description.textContent = value;
      context.append(term, description);
    }
    document.getElementById("health-roster-action-description").textContent =
      ROSTER_ACTION_DESCRIPTIONS[action] || "";
    labelRow.hidden = action !== "enroll";
    label.disabled = action !== "enroll";
    label.required = false;
    label.value = action === "enroll" ? detail.proposedEnrollmentLabel || "" : "";
    labelHint.textContent =
      `Optional. Clear to use found-${capture.deviceId.replace(/^extaddr:/, "")}.`;
    reason.value = "";
    document.getElementById("health-roster-action-status").textContent = "";
    document.getElementById("health-roster-action-confirm").textContent =
      ROSTER_ACTION_BUTTON_LABELS[action] || "Confirm";
    document.getElementById("health-roster-action-confirm").disabled = false;
    dialog.showModal();
    if (action === "enroll") label.focus();
  };
  if (knownDetail) {
    showConfirmation(knownDetail);
    return;
  }
  void fetchHealthRosterDevice(
    capture.networkId, deviceId, undefined, capture.assessmentId,
  ).then(showConfirmation).catch((error) => {
    announceHealthInsight(`Roster action context unavailable: ${error.message}`);
  });
}

async function reconcileCommittedRosterAction(capture) {
  if (healthInsightsState.datasetId !== capture.datasetId
      || healthInsightsState.assessment?.networkId !== capture.networkId) return;
  await refreshHealthAssessment();
  if (healthInsightsState.error || !healthInsightsState.assessment) {
    throw new Error(healthInsightsState.error || "Current assessment could not be refreshed.");
  }
  clearRosterMutationRefreshStatus();
  const currentAssessment = healthInsightsState.assessment;
  await loadRosterPage(healthRosterViewState.offset);
  if (healthInsightsState.rosterError) {
    throw new Error(healthInsightsState.rosterError);
  }
  const detail = await fetchHealthRosterDevice(
    currentAssessment.networkId, capture.deviceId, undefined, currentAssessment.assessmentId,
  );
  if (healthInsightsState.assessment?.assessmentId !== currentAssessment.assessmentId) return;
  const navigationIsUnchanged = () => healthInsightsTab === capture.navigation.tab
    && rosterNavigationGeneration === capture.navigation.generation
    && currentView === capture.navigation.view
    && (capture.navigation.tab !== "roster"
      || healthRosterViewState.selectedDeviceId === null
      || healthRosterViewState.selectedDeviceId === capture.deviceId)
    && healthInsightsViewState.selectedGroupId === capture.navigation.groupId
    && healthInsightsViewState.selectedFindingId === capture.navigation.findingId;
  if (!navigationIsUnchanged()) return;
  if (healthInsightsTab !== "roster") return;
  healthRosterViewState.selectedDeviceId = capture.deviceId;
  healthRosterViewState.detailVersion += 1;
  healthInsightsState.rosterDetail = detail;
  healthInsightsState.rosterDetailPresence = detail.presenceState;
  const changedFilters = [];
  if (healthRosterViewState.rosterState !== "all"
      && healthRosterViewState.rosterState !== detail.rosterState) {
    healthRosterViewState.rosterState = "all";
    document.getElementById("health-roster-designation").value = "all";
    changedFilters.push("designation");
  }
  if (healthRosterViewState.presence !== "all"
      && healthRosterViewState.presence !== detail.presenceState) {
    healthRosterViewState.presence = "all";
    document.getElementById("health-roster-presence").value = "all";
    changedFilters.push("presence");
  }
  if (changedFilters.length) {
    announceHealthInsight(`Roster action saved; ${changedFilters.join(" and ")} filter changed to All to keep the device visible.`);
    healthRosterViewState.offset = 0;
    await loadRosterPage(0);
    if (healthInsightsState.assessment?.assessmentId !== currentAssessment.assessmentId
        || !navigationIsUnchanged()) return;
    if (healthInsightsState.rosterError) {
      throw new Error(healthInsightsState.rosterError);
    }
  }
  renderRosterDetailPanel(detail, detail.presenceState);
  document.getElementById("device-details").classList.add("roster-selected");
  contextDetailsController.setCollapsed(false);
  renderNetworkInsights();
}

async function submitRosterAction(event) {
  event.preventDefault();
  const capture = activeRosterAction;
  if (!capture) return;
  if (rosterMutationPendingDeviceId === capture.deviceId) return;
  if (healthInsightsState.assessment?.networkId !== capture.networkId
      || healthInsightsState.assessment?.assessmentId !== capture.assessmentId
      || healthInsightsState.datasetId !== capture.datasetId
      || healthInsightsState.assessmentRequestVersion !== capture.generation) {
    document.getElementById("health-roster-action-dialog")?.close();
    activeRosterAction = null;
    activeRosterRequest = null;
    announceHealthInsight("The selected assessment changed. Reopen details before acting.");
    return;
  }
  if (!activeRosterRequest) {
    const payload = {
      action: capture.action,
      requestId: createHealthMutationRequestId(),
      expectedRevision: capture.revision,
    };
    if (capture.action === "enroll") {
      payload.contextAssessmentId = capture.assessmentId;
      const deviceLabel = document.getElementById("health-roster-action-label").value.trim();
      if (deviceLabel) payload.deviceLabel = deviceLabel;
    }
    const reason = document.getElementById("health-roster-action-reason").value.trim();
    if (reason) payload.reason = reason;
    activeRosterRequest = payload;
  }
  const requestPayload = activeRosterRequest;
  const confirm = document.getElementById("health-roster-action-confirm");
  const cancel = document.getElementById("health-roster-action-cancel");
  const status = document.getElementById("health-roster-action-status");
  confirm.disabled = true;
  cancel.disabled = true;
  rosterMutationPendingDeviceId = capture.deviceId;
  let reconfirmAfterConflict = false;
  if (healthInsightsState.rosterDetail?.deviceId === capture.deviceId) {
    renderRosterDetailPanel(
      healthInsightsState.rosterDetail, healthInsightsState.rosterDetailPresence,
    );
  }
  try {
    const response = await patchHealthRosterDevice(
      capture.networkId, capture.deviceId, requestPayload,
    );
    document.getElementById("health-roster-action-dialog").close();
    if (activeRosterAction === capture) {
      activeRosterAction = null;
      activeRosterRequest = null;
    }
    announceHealthInsight(response.changed ? "Roster change saved." : "Roster is already in the requested state.");
    try {
      await reconcileCommittedRosterAction(capture);
    } catch (error) {
      status.textContent = "";
      showRosterMutationRefreshFailure(capture, error);
    }
  } catch (error) {
    confirm.disabled = false;
    cancel.disabled = false;
    if (error.status == null) {
      status.textContent = "Outcome unclear. Retry safely with the same request, or close this dialog.";
      confirm.textContent = "Retry same request";
    } else {
      activeRosterRequest = null;
      if (error.status === 409 && error.code === "stale-revision") {
        reconfirmAfterConflict = true;
        document.getElementById("health-roster-action-dialog").close();
        activeRosterAction = null;
        status.textContent = "";
      } else if (error.status === 409
          && error.code === "reassessment-baseline-unavailable") {
        status.textContent = `Refresh Health before changing the roster. ${error.message}`;
      } else {
        status.textContent = `Roster action failed (${error.status}): ${error.message}`;
      }
    }
  } finally {
    if (rosterMutationPendingDeviceId === capture.deviceId) {
      rosterMutationPendingDeviceId = null;
    }
    cancel.disabled = false;
    if (healthInsightsState.rosterDetail?.deviceId === capture.deviceId) {
      renderRosterDetailPanel(
        healthInsightsState.rosterDetail, healthInsightsState.rosterDetailPresence,
      );
    }
    if (reconfirmAfterConflict
        && healthInsightsState.assessment?.networkId === capture.networkId
        && healthInsightsState.assessment?.assessmentId === capture.assessmentId) {
      announceHealthInsight(
        "No change was made. The roster changed since confirmation; review the refreshed state and confirm again.",
      );
      void beginRosterAction(capture.action, capture.deviceId);
    }
  }
}

function changeRosterSort(column) {
  rosterNavigationGeneration += 1;
  healthRosterViewState.sortFocusColumn = column;
  healthRosterViewState.sort = { column, direction: healthRosterViewState.sort.column === column &&
    healthRosterViewState.sort.direction === "ascending" ? "descending" : "ascending" };
  resetRosterScroll();
  void loadRosterPage(0);
}

function changeRosterPageSize(limit) {
  if (![25, 50, 100].includes(limit) || healthRosterViewState.limit === limit) return;
  rosterNavigationGeneration += 1;
  healthRosterViewState.limit = limit;
  healthRosterViewState.pageFocusTarget = "page-size";
  resetRosterScroll();
  void loadRosterPage(0);
}

function resetRosterScroll() {
  const wrap = document.querySelector(".health-roster-table-wrap");
  if (wrap) wrap.scrollTop = 0;
  healthRosterViewState.tableScrollTop = 0;
}

function applyRosterFilter() {
  rosterNavigationGeneration += 1;
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
  const version = ++healthInsightsState.comparisonListRequestVersion;
  healthInsightsState.comparisonListError = "";
  healthInsightsState.comparisonListLoading = true;
  renderNetworkInsights();
  try {
    const page = await fetchHealthComparisons(assessment.networkId, assessment.datasetId, offset);
    if (version !== healthInsightsState.comparisonListRequestVersion ||
      healthInsightsState.assessment?.datasetId !== assessment.datasetId ||
      healthInsightsState.assessment?.networkId !== assessment.networkId) return;
    if (!isComparisonPageForAssessment(page, assessment, offset)) throw new Error("Invalid stored comparison page.");
    healthInsightsState.comparisonPage = page;
    healthInsightsViewState.comparisonOffset = offset;
    healthComparisonDetailController.reconcileSummary();
  } catch (error) {
    if (version !== healthInsightsState.comparisonListRequestVersion) return;
    healthInsightsState.comparisonListError = error.message;
  } finally {
    if (version === healthInsightsState.comparisonListRequestVersion) {
      healthInsightsState.comparisonListLoading = false;
      renderNetworkInsights();
    }
  }
}

function endpointSelectionEnabled() {
  return healthInsightsState.capabilities?.comparisonEndpointSelection === 1;
}

function endpointMetadata(assessmentId) {
  return findHealthComparisonEndpointMetadata(
    assessmentId,
    healthInsightsState.comparisonEndpointPages,
    healthInsightsState.comparison,
    healthInsightsState.comparisonPinnedBefore,
  );
}

function clearEndpointComparison() {
  healthInsightsState.comparisonEndpointPairRequestVersion += 1;
  healthInsightsState.comparisonEndpointPairRequestIdentity = null;
  healthInsightsState.comparisonEndpointPairLoading = false;
  healthInsightsState.comparisonEndpointPairError = "";
  healthInsightsState.comparisonEndpointUnavailable = false;
  healthInsightsState.comparison = null;
  healthInsightsState.comparisonQueryIdentity = null;
}

function resetComparisonEndpointState() {
  healthInsightsState.comparisonEndpointRevision += 1;
  healthInsightsState.comparisonPresetRequestVersion += 1;
  healthInsightsState.comparisonPresetLoading = false;
  healthInsightsState.comparisonPresetError = "";
  invalidateComparisonEndpointRequests();
  healthInsightsState.comparisonEndpointPages = { before: null, after: null };
  healthInsightsState.comparisonLatestPresetPage = null;
  healthInsightsState.comparisonPinnedBefore = null;
  healthInsightsState.comparisonEndpointDefaultsPending = true;
  healthInsightsState.comparisonEndpointUnavailable = false;
  healthInsightsViewState.beforeAssessmentId = null;
  healthInsightsViewState.afterAssessmentId = null;
  healthInsightsViewState.beforeHistoryOffset = 0;
  healthInsightsViewState.afterHistoryOffset = 0;
  healthInsightsViewState.comparisonId = null;
  healthInsightsViewState.comparisonScope = "all";
  healthInsightsViewState.comparisonResult = "changed";
  healthInsightsViewState.comparisonSearch = "";
  healthInsightsViewState.comparisonSort = "subject";
  healthInsightsViewState.comparisonDirection = "ascending";
  healthInsightsViewState.comparisonLimit = 100;
  healthInsightsViewState.comparisonControlFocusTarget = null;
  healthInsightsViewState.comparisonOffset = 0;
  healthInsightsViewState.comparisonItemOffset = 0;
  healthInsightsViewState.comparisonIntent = "1d";
  healthInsightsViewState.comparisonCustomOpen = false;
  healthInsightsViewState.comparisonDetailsOpen = false;
  healthInsightsViewState.comparisonFocusTarget = null;
  healthInsightsViewState.comparisonTableScrollTop = 0;
  clearEndpointComparison();
}

function resetComparisonTableScroll() {
  healthInsightsViewState.comparisonTableScrollTop = 0;
  const wrap = document.querySelector(".health-comparison-table-wrap");
  if (wrap) wrap.scrollTop = 0;
}

function invalidateComparisonEndpointRequests(sides = ["before", "after"]) {
  for (const side of sides) {
    healthInsightsState.comparisonEndpointRequestVersions[side] += 1;
    healthInsightsState.comparisonEndpointLoading[side] = false;
    healthInsightsState.comparisonEndpointErrors[side] = "";
  }
}

async function requestComparisonEndpointPage(side, offset, options = {}) {
  const assessment = healthInsightsState.assessment;
  if (!assessment || !endpointSelectionEnabled()) return null;
  const afterAssessmentId = side === "before"
    ? (options.afterAssessmentId ?? healthInsightsViewState.afterAssessmentId)
    : null;
  if (side === "before" && !afterAssessmentId) return null;
  const selectedAssessmentId = options.selectedAssessmentId
    ?? healthInsightsViewState[side === "before" ? "beforeAssessmentId" : "afterAssessmentId"];
  const query = {
    networkId: assessment.networkId,
    datasetId: assessment.datasetId,
    side,
    afterAssessmentId,
    selectedAssessmentId,
    comparisonVersion: healthInsightsState.capabilities?.comparisonVersion,
    comparisonPolicyDigest: healthInsightsState.capabilities?.comparisonPolicyDigest,
    offset,
  };
  const version = ++healthInsightsState.comparisonEndpointRequestVersions[side];
  const revision = healthInsightsState.comparisonEndpointRevision;
  healthInsightsState.comparisonEndpointLoading[side] = true;
  healthInsightsState.comparisonEndpointErrors[side] = "";
  renderNetworkInsights();
  try {
    const page = await fetchHealthComparisonEndpoints(
      assessment.networkId, assessment.datasetId, side, offset, undefined, {
        afterAssessmentId,
        selectedAssessmentId,
      },
    );
    if (version !== healthInsightsState.comparisonEndpointRequestVersions[side]
        || revision !== healthInsightsState.comparisonEndpointRevision
        || healthInsightsState.assessment?.networkId !== query.networkId
        || healthInsightsState.assessment?.datasetId !== query.datasetId
        || healthInsightsViewState[
          side === "before" ? "beforeAssessmentId" : "afterAssessmentId"
        ] !== selectedAssessmentId
        || (side === "before"
          && healthInsightsViewState.afterAssessmentId !== afterAssessmentId)) return null;
    if (!isHealthComparisonEndpointPageForQuery(page, query)) {
      throw new Error("Invalid assessment endpoint page.");
    }
    healthInsightsState.comparisonEndpointPages[side] = page;
    if (side === "before" && options.resolveSelection && !selectedAssessmentId) {
      healthInsightsViewState.beforeAssessmentId = page.predecessor?.assessmentId ?? null;
    }
    healthInsightsViewState[side === "before" ? "beforeHistoryOffset" : "afterHistoryOffset"] = offset;
    return page;
  } catch (error) {
    if (version !== healthInsightsState.comparisonEndpointRequestVersions[side]
        || revision !== healthInsightsState.comparisonEndpointRevision) return null;
    healthInsightsState.comparisonEndpointErrors[side] = error.message;
    if (selectedAssessmentId && error.status === 404) {
      healthInsightsState.comparisonPinnedBefore = null;
      healthInsightsViewState.beforeAssessmentId = null;
      healthInsightsViewState.afterAssessmentId = null;
      clearEndpointComparison();
      healthInsightsState.comparisonEndpointUnavailable = true;
    }
    return null;
  } finally {
    if (version === healthInsightsState.comparisonEndpointRequestVersions[side]
        && revision === healthInsightsState.comparisonEndpointRevision) {
      healthInsightsState.comparisonEndpointLoading[side] = false;
      renderNetworkInsights();
    }
  }
}

async function loadComparisonEndpointPair(offset = 0) {
  const assessment = healthInsightsState.assessment;
  const beforeAssessmentId = healthInsightsViewState.beforeAssessmentId;
  const afterAssessmentId = healthInsightsViewState.afterAssessmentId;
  const policyDigest = healthInsightsState.capabilities?.comparisonPolicyDigest;
  const comparisonVersion = healthInsightsState.capabilities?.comparisonVersion;
  if (!assessment || !beforeAssessmentId || !afterAssessmentId || !policyDigest
      || !comparisonVersion || !endpointSelectionEnabled()) {
    clearEndpointComparison();
    healthInsightsViewState.comparisonItemOffset = 0;
    renderNetworkInsights();
    return;
  }
  const query = {
    networkId: assessment.networkId,
    datasetId: assessment.datasetId,
    beforeAssessmentId,
    afterAssessmentId,
    comparisonPolicyDigest: policyDigest,
    comparisonVersion,
    scope: healthInsightsViewState.comparisonScope,
    result: healthInsightsViewState.comparisonResult,
    q: healthInsightsViewState.comparisonSearch,
    sort: healthInsightsViewState.comparisonSort,
    direction: healthInsightsViewState.comparisonDirection,
    limit: healthInsightsViewState.comparisonLimit,
    offset,
  };
  const version = ++healthInsightsState.comparisonEndpointPairRequestVersion;
  healthInsightsState.comparisonEndpointPairRequestIdentity = query;
  healthInsightsState.comparisonEndpointPairLoading = true;
  healthInsightsState.comparisonEndpointPairError = "";
  healthInsightsState.comparison = null;
  healthInsightsState.comparisonQueryIdentity = null;
  healthInsightsViewState.comparisonItemOffset = offset;
  renderNetworkInsights();
  const isCurrent = () => version === healthInsightsState.comparisonEndpointPairRequestVersion
    && healthInsightsState.assessment?.networkId === query.networkId
    && healthInsightsState.assessment?.datasetId === query.datasetId
    && healthInsightsViewState.beforeAssessmentId === query.beforeAssessmentId
    && healthInsightsViewState.afterAssessmentId === query.afterAssessmentId
    && healthInsightsViewState.comparisonScope === query.scope
    && healthInsightsViewState.comparisonResult === query.result
    && healthInsightsViewState.comparisonSearch === query.q
    && healthInsightsViewState.comparisonSort === query.sort
    && healthInsightsViewState.comparisonDirection === query.direction
    && healthInsightsViewState.comparisonLimit === query.limit
    && healthInsightsState.capabilities?.comparisonPolicyDigest === query.comparisonPolicyDigest
    && healthInsightsState.capabilities?.comparisonVersion === query.comparisonVersion;
  try {
    const comparison = await fetchHealthComparisonPair(query, offset);
    if (!isCurrent()) return;
    if (!isHealthComparisonPairForQuery(comparison, query)) {
      throw new Error("Invalid comparison response for the selected endpoints.");
    }
    if (offset > 0 && comparison.items.length === 0 && comparison.filteredItemCount > 0) {
      healthInsightsViewState.comparisonItemOffset = 0;
      await loadComparisonEndpointPair(0);
      return;
    }
    healthInsightsState.comparison = comparison;
    healthInsightsState.comparisonQueryIdentity = query;
  } catch (error) {
    if (!isCurrent()) return;
    if (error.status === 404) {
      clearEndpointComparison();
      healthInsightsState.comparisonEndpointUnavailable = true;
      healthInsightsState.comparisonEndpointPairError =
        "A selected assessment is no longer retained. Select new endpoints.";
      renderNetworkInsights();
    } else {
      healthInsightsState.comparisonEndpointPairError = error.message;
    }
  } finally {
    if (isCurrent()) {
      healthInsightsState.comparisonEndpointPairLoading = false;
      healthInsightsState.comparisonEndpointPairRequestIdentity = null;
      renderNetworkInsights();
    }
  }
}

async function selectComparisonPreset(
  interval, { preserveOffset = false, preserveDisclosure = false } = {},
) {
  if (!["1d", "3d", "1w"].includes(interval) || !endpointSelectionEnabled()) return;
  const assessment = healthInsightsState.assessment;
  if (!assessment) return;
  const previousPair = {
    before: healthInsightsViewState.beforeAssessmentId,
    after: healthInsightsViewState.afterAssessmentId,
    offset: healthInsightsViewState.comparisonItemOffset,
  };
  const customWasOpen = healthInsightsViewState.comparisonCustomOpen;
  const requestVersion = ++healthInsightsState.comparisonPresetRequestVersion;
  const revision = ++healthInsightsState.comparisonEndpointRevision;
  invalidateComparisonEndpointRequests();
  healthInsightsState.comparisonPresetLoading = true;
  healthInsightsState.comparisonPresetError = "";
  healthInsightsViewState.comparisonIntent = interval;
  healthInsightsViewState.comparisonCustomOpen = preserveDisclosure && customWasOpen;
  healthInsightsViewState.comparisonFocusTarget = null;
  resetComparisonTableScroll();
  healthInsightsViewState.afterAssessmentId = null;
  healthInsightsViewState.beforeAssessmentId = null;
  healthInsightsViewState.comparisonItemOffset = 0;
  healthInsightsState.comparisonEndpointDefaultsPending = true;
  healthInsightsState.comparisonEndpointPages = { before: null, after: null };
  healthInsightsState.comparisonPinnedBefore = null;
  clearEndpointComparison();
  renderNetworkInsights();
  const isCurrent = () => requestVersion === healthInsightsState.comparisonPresetRequestVersion
    && revision === healthInsightsState.comparisonEndpointRevision
    && healthInsightsState.assessment?.networkId === assessment.networkId
    && healthInsightsState.assessment?.datasetId === assessment.datasetId;
  try {
    const latestPage = await fetchHealthComparisonEndpoints(
      assessment.networkId, assessment.datasetId, "after", 0,
    );
    const query = {
      networkId: assessment.networkId,
      datasetId: assessment.datasetId,
      side: "after",
      afterAssessmentId: null,
      selectedAssessmentId: null,
      comparisonVersion: healthInsightsState.capabilities?.comparisonVersion,
      comparisonPolicyDigest: healthInsightsState.capabilities?.comparisonPolicyDigest,
      offset: 0,
    };
    if (!isCurrent()) return;
    if (!isHealthComparisonEndpointPageForQuery(latestPage, query)) {
      throw new Error("Invalid latest assessment endpoint page.");
    }
    healthInsightsState.comparisonLatestPresetPage = latestPage;
    const after = latestPage.defaultAfter;
    const candidate = latestPage.shortcuts.find((item) => item.interval === interval)?.candidate ?? null;
    healthInsightsViewState.afterAssessmentId = after?.assessmentId ?? null;
    healthInsightsViewState.beforeAssessmentId = candidate?.assessmentId ?? null;
    healthInsightsState.comparisonPinnedBefore = candidate;
    healthInsightsState.comparisonEndpointPages.after = latestPage;
    healthInsightsState.comparisonEndpointDefaultsPending = false;
    if (!after) return;
    const [afterPage, beforePage] = await Promise.all([
      requestComparisonEndpointPage("after", 0, { selectedAssessmentId: after.assessmentId }),
      candidate
        ? requestComparisonEndpointPage("before", 0, {
          afterAssessmentId: after.assessmentId,
          selectedAssessmentId: candidate.assessmentId,
        })
        : Promise.resolve(null),
    ]);
    if (!isCurrent() || !afterPage) return;
    if (candidate && !beforePage) return;
    if (candidate) {
      const offset = preserveOffset
        && previousPair.before === candidate.assessmentId
        && previousPair.after === after.assessmentId
        ? previousPair.offset
        : 0;
      await loadComparisonEndpointPair(offset);
    }
  } catch (error) {
    if (isCurrent()) healthInsightsState.comparisonPresetError = error.message;
  } finally {
    if (isCurrent()) {
      healthInsightsState.comparisonPresetLoading = false;
      renderNetworkInsights();
    }
  }
}

function initializeComparisonEndpoints() {
  return selectComparisonPreset("1d");
}

function setComparisonCustomOpen(open) {
  healthInsightsViewState.comparisonCustomOpen = open;
  renderNetworkInsights();
  if (open && healthInsightsViewState.afterAssessmentId
      && !healthInsightsState.comparisonEndpointPages.before
      && !healthInsightsState.comparisonEndpointLoading.before) {
    void requestComparisonEndpointPage("before", 0, {
      afterAssessmentId: healthInsightsViewState.afterAssessmentId,
      selectedAssessmentId: healthInsightsViewState.beforeAssessmentId,
    });
  }
}

async function selectComparisonEndpoint(side, assessmentId) {
  if (!assessmentId) return;
  healthInsightsState.comparisonPresetRequestVersion += 1;
  healthInsightsState.comparisonPresetLoading = false;
  healthInsightsState.comparisonPresetError = "";
  healthInsightsViewState.comparisonIntent = "custom";
  healthInsightsViewState.comparisonCustomOpen = true;
  if (side === "before") {
    invalidateComparisonEndpointRequests(["before"]);
  } else {
    healthInsightsState.comparisonEndpointRevision += 1;
    invalidateComparisonEndpointRequests();
  }
  renderNetworkInsights();
  if (side === "before") {
    if (assessmentId === healthInsightsViewState.beforeAssessmentId) return;
    resetComparisonTableScroll();
    healthInsightsViewState.comparisonFocusTarget = null;
    healthInsightsState.comparisonPinnedBefore = null;
    healthInsightsViewState.beforeAssessmentId = assessmentId;
    clearEndpointComparison();
    healthInsightsViewState.comparisonItemOffset = 0;
    const page = await requestComparisonEndpointPage(
      "before", healthInsightsViewState.beforeHistoryOffset, {
        afterAssessmentId: healthInsightsViewState.afterAssessmentId,
        selectedAssessmentId: assessmentId,
      },
    );
    if (!page) return;
    await loadComparisonEndpointPair(0);
    return;
  }
  if (assessmentId === healthInsightsViewState.afterAssessmentId) return;
  resetComparisonTableScroll();
  healthInsightsViewState.comparisonFocusTarget = null;
  const beforeId = healthInsightsViewState.beforeAssessmentId;
  const before = endpointMetadata(beforeId);
  const after = endpointMetadata(assessmentId);
  const preserveBefore = Boolean(before?.observedAt && after?.observedAt
    && Date.parse(before.observedAt) < Date.parse(after.observedAt));
  const revision = healthInsightsState.comparisonEndpointRevision;
  healthInsightsViewState.afterAssessmentId = assessmentId;
  if (healthInsightsState.comparisonEndpointPages.after) {
    healthInsightsState.comparisonEndpointPages.after = {
      ...healthInsightsState.comparisonEndpointPages.after,
      shortcuts: [],
    };
  }
  if (!preserveBefore) {
    healthInsightsViewState.beforeAssessmentId = null;
    healthInsightsState.comparisonPinnedBefore = null;
  }
  healthInsightsViewState.comparisonItemOffset = 0;
  clearEndpointComparison();
  void requestComparisonEndpointPage("after", healthInsightsViewState.afterHistoryOffset, {
    selectedAssessmentId: assessmentId,
  });
  const beforePage = await requestComparisonEndpointPage(
    "before", 0, {
      afterAssessmentId: assessmentId,
      selectedAssessmentId: preserveBefore ? beforeId : null,
      resolveSelection: !preserveBefore,
    },
  );
  if (revision !== healthInsightsState.comparisonEndpointRevision || !beforePage) return;
  if (preserveBefore && !beforePage.selected) {
    healthInsightsState.comparisonEndpointUnavailable = true;
    healthInsightsViewState.beforeAssessmentId = null;
    clearEndpointComparison();
    renderNetworkInsights();
    return;
  }
  if (revision === healthInsightsState.comparisonEndpointRevision) {
    await loadComparisonEndpointPair(0);
  }
}

async function loadComparisonEndpointPage(side, offset) {
  if (!endpointSelectionEnabled()) return;
  const currentId = healthInsightsViewState[side === "before" ? "beforeAssessmentId" : "afterAssessmentId"];
  await requestComparisonEndpointPage(side, offset, { selectedAssessmentId: currentId });
}

async function loadComparisonItems(offset, focusTarget = null) {
  resetComparisonTableScroll();
  healthInsightsViewState.comparisonFocusTarget = focusTarget;
  if (endpointSelectionEnabled()) return loadComparisonEndpointPair(offset);
  const comparisonId = healthInsightsViewState.comparisonId;
  if (comparisonId) await selectComparison(comparisonId, offset);
}

let comparisonSearchTimer = null;

function loadComparisonFromFirstPage() {
  healthInsightsViewState.comparisonItemOffset = 0;
  if (endpointSelectionEnabled()) return loadComparisonEndpointPair(0);
  const comparisonId = healthInsightsViewState.comparisonId;
  if (comparisonId) return selectComparison(comparisonId, 0);
  renderNetworkInsights();
}

function changeComparisonSearch(value) {
  const search = String(value).slice(0, 120);
  if (healthInsightsViewState.comparisonSearch === search) return;
  healthInsightsViewState.comparisonSearch = search;
  healthInsightsViewState.comparisonControlFocusTarget = "search";
  healthInsightsViewState.comparisonItemOffset = 0;
  resetComparisonTableScroll();
  clearTimeout(comparisonSearchTimer);
  comparisonSearchTimer = setTimeout(() => {
    comparisonSearchTimer = null;
    void loadComparisonFromFirstPage();
  }, 250);
}

function changeComparisonOrder(sort, direction) {
  if (!["subject", "evidence", "result"].includes(sort)
      || !["ascending", "descending"].includes(direction)) return;
  if (healthInsightsViewState.comparisonSort === sort
      && healthInsightsViewState.comparisonDirection === direction) return;
  clearTimeout(comparisonSearchTimer);
  comparisonSearchTimer = null;
  healthInsightsViewState.comparisonSort = sort;
  healthInsightsViewState.comparisonDirection = direction;
  healthInsightsViewState.comparisonControlFocusTarget = "order";
  resetComparisonTableScroll();
  return loadComparisonFromFirstPage();
}

function changeComparisonPageSize(limit) {
  if (![25, 50, 100].includes(limit)
      || healthInsightsViewState.comparisonLimit === limit) return;
  clearTimeout(comparisonSearchTimer);
  comparisonSearchTimer = null;
  healthInsightsViewState.comparisonLimit = limit;
  healthInsightsViewState.comparisonFocusTarget = "page-size";
  resetComparisonTableScroll();
  return loadComparisonFromFirstPage();
}

function changeComparisonFilter(filter, value) {
  clearTimeout(comparisonSearchTimer);
  comparisonSearchTimer = null;
  resetComparisonTableScroll();
  healthInsightsViewState.comparisonFocusTarget = null;
  healthInsightsViewState.comparisonControlFocusTarget = filter;
  if (endpointSelectionEnabled()) {
    const key = filter === "scope" ? "comparisonScope" : "comparisonResult";
    if (healthInsightsViewState[key] === value) return;
    healthInsightsViewState[key] = value;
    healthInsightsViewState.comparisonItemOffset = 0;
    return loadComparisonEndpointPair(0);
  }
  healthComparisonDetailController.changeFilter(filter, value);
}

function selectComparison(comparisonId, offset = 0) {
  if (comparisonId && !healthInsightsState.assessment) return;
  if (comparisonId !== healthInsightsViewState.comparisonId) resetComparisonTableScroll();
  healthInsightsViewState.comparisonId = comparisonId;
  healthInsightsViewState.comparisonItemOffset = offset;
  return healthComparisonDetailController.select(comparisonId, offset);
}

function resetHealthAssessmentHistory() {
  healthAssessmentHistoryState.requestVersion += 1;
  Object.assign(healthAssessmentHistoryState, {
    mode: "latest",
    pinnedAssessmentId: null,
    networkId: null,
    page: null,
    navigation: null,
    offset: 0,
    loading: false,
    pageLoading: false,
    error: "",
    targetError: "",
    unsupported: false,
    chooserOpen: false,
    announceSelection: false,
  });
}

function selectHealthAssessment(assessmentId) {
  if (typeof assessmentId !== "string" || !assessmentId) return;
  if (healthAssessmentHistoryState.mode === "pinned"
      && healthAssessmentHistoryState.pinnedAssessmentId === assessmentId) return;
  healthAssessmentHistoryState.mode = "pinned";
  healthAssessmentHistoryState.pinnedAssessmentId = assessmentId;
  healthAssessmentHistoryState.page = null;
  healthAssessmentHistoryState.navigation = null;
  healthAssessmentHistoryState.error = "";
  healthAssessmentHistoryState.targetError = "";
  healthAssessmentHistoryState.unsupported = false;
  healthAssessmentHistoryState.announceSelection = true;
  void refreshHealthAssessment();
}

function followLatestHealthAssessment() {
  healthAssessmentHistoryState.mode = "latest";
  healthAssessmentHistoryState.pinnedAssessmentId = null;
  healthAssessmentHistoryState.page = null;
  healthAssessmentHistoryState.navigation = null;
  healthAssessmentHistoryState.offset = 0;
  healthAssessmentHistoryState.chooserOpen = false;
  healthAssessmentHistoryState.error = "";
  healthAssessmentHistoryState.targetError = "";
  healthAssessmentHistoryState.unsupported = false;
  healthAssessmentHistoryState.announceSelection = true;
  void refreshHealthAssessment();
}

function retryHealthAssessmentHistory() {
  void loadHealthAssessmentHistoryPage(0, {
    selectedAssessmentId: healthInsightsState.assessment?.assessmentId ?? null,
    preserveTargetError: true,
    announce: true,
  });
}

async function loadHealthAssessmentHistoryPage(offset, options = {}) {
  const assessment = healthInsightsState.assessment;
  const networkId = options.networkId ?? assessment?.networkId
    ?? healthAssessmentHistoryState.networkId;
  const datasetId = options.datasetId ?? assessment?.datasetId
    ?? healthInsightsState.datasetId;
  const selectedAssessmentId = Object.hasOwn(options, "selectedAssessmentId")
    ? options.selectedAssessmentId
    : healthAssessmentHistoryState.mode === "pinned"
      ? healthAssessmentHistoryState.pinnedAssessmentId
      : assessment?.assessmentId ?? null;
  const assessmentRequestVersion = healthInsightsState.assessmentRequestVersion;
  const mode = healthAssessmentHistoryState.mode;
  const pinnedAssessmentId = healthAssessmentHistoryState.pinnedAssessmentId;
  if (!networkId || !datasetId) return;
  if (healthInsightsState.capabilities?.comparisonEndpointSelection !== 1) {
    healthAssessmentHistoryState.page = null;
    healthAssessmentHistoryState.navigation = null;
    healthAssessmentHistoryState.unsupported = true;
    healthAssessmentHistoryState.pageLoading = false;
    healthAssessmentHistoryState.error = "";
    renderNetworkInsights();
    return;
  }

  const requestVersion = ++healthAssessmentHistoryState.requestVersion;
  const isCurrent = () => requestVersion === healthAssessmentHistoryState.requestVersion
    && assessmentRequestVersion === healthInsightsState.assessmentRequestVersion
    && healthAssessmentHistoryState.mode === mode
    && healthAssessmentHistoryState.pinnedAssessmentId === pinnedAssessmentId
    && currentDataset?.entry?.value === datasetId
    && (!selectedAssessmentId
      || healthInsightsState.assessment?.assessmentId === selectedAssessmentId);
  healthAssessmentHistoryState.offset = offset;
  healthAssessmentHistoryState.pageLoading = true;
  healthAssessmentHistoryState.error = "";
  if (!options.preserveTargetError) healthAssessmentHistoryState.targetError = "";
  if (options.announce) announceHealthInsight("Loading retained assessment runs.");
  renderNetworkInsights();
  try {
    const page = await fetchHealthComparisonEndpoints(
      networkId, datasetId, "after", offset, undefined,
      { selectedAssessmentId: selectedAssessmentId || undefined },
    );
    if (!isCurrent()) return;
    const query = {
      networkId,
      datasetId,
      side: "after",
      afterAssessmentId: null,
      selectedAssessmentId,
      comparisonVersion: healthInsightsState.capabilities?.comparisonVersion,
      comparisonPolicyDigest: healthInsightsState.capabilities?.comparisonPolicyDigest,
      offset,
    };
    if (!isHealthComparisonEndpointPageForQuery(page, query)) {
      throw new Error("Invalid retained assessment page.");
    }
    if (options.selectOldest) {
      const lastOffset = Math.max(0, Math.floor((page.total - 1) / page.limit) * page.limit);
      if (offset === 0 && lastOffset > 0) {
        await loadHealthAssessmentHistoryPage(lastOffset, options);
        return;
      }
      if (offset !== lastOffset || page.items.length === 0) {
        throw new Error("Oldest retained run is unavailable; history may have changed. Retry the run list.");
      }
      selectHealthAssessment(page.items.at(-1).assessmentId);
      return;
    }
    healthAssessmentHistoryState.page = page;
    healthAssessmentHistoryState.navigation = page.navigation ?? null;
    healthAssessmentHistoryState.networkId = networkId;
    healthAssessmentHistoryState.unsupported = false;
    if (page.items.length === 0 && page.total > 0) {
      announceHealthInsight("No retained runs are available on this page.");
    } else if (options.announce) {
      const first = page.total === 0 ? 0 : offset + 1;
      const last = Math.min(page.total, offset + page.items.length);
      announceHealthInsight(
        page.total === 0
          ? "No retained assessment runs are available."
          : `Retained assessment runs ${first} through ${last} loaded.`,
      );
    }
  } catch (error) {
    if (!isCurrent()) return;
    if (selectedAssessmentId && error.status === 404) {
      const unavailable = "Selected assessment is no longer retained.";
      healthAssessmentHistoryState.targetError = unavailable;
      announceHealthInsight(unavailable);
      healthAssessmentHistoryState.page = null;
      healthAssessmentHistoryState.navigation = null;
      if (healthAssessmentHistoryState.mode === "pinned"
          && healthAssessmentHistoryState.pinnedAssessmentId === selectedAssessmentId) {
        healthInsightsState.assessment = null;
        healthInsightsState.error = unavailable;
        healthInsightsState.device = null;
        healthInsightsState.roster = null;
        healthInsightsState.rosterDetail = null;
        healthInsightsState.deviceRequestVersion += 1;
        healthRosterViewState.requestVersion += 1;
        healthRosterViewState.detailVersion += 1;
        if (currentDataset?.entry?.value === datasetId) currentDataset.healthAssessment = null;
        applyHealthAssessmentPresentation(null);
      }
      void loadHealthAssessmentHistoryPage(0, {
        networkId,
        datasetId,
        selectedAssessmentId: null,
        preserveTargetError: true,
      });
    } else {
      healthAssessmentHistoryState.error = `Retained run list unavailable: ${error.message}`;
      announceHealthInsight(healthAssessmentHistoryState.error);
    }
  } finally {
    if (requestVersion === healthAssessmentHistoryState.requestVersion) {
      healthAssessmentHistoryState.pageLoading = false;
      renderNetworkInsights();
    }
  }
}

function resetHealthInsightsForDatasetChange() {
  findingRosterActionEligibility.clear();
  findingRosterActionPending.clear();
  clearRosterMutationRefreshStatus();
  healthInsightsTab = HEALTH_INSIGHTS_TABS[0].id;
  resetHealthAssessmentHistory();
  healthInsightsState.assessment = null;
  healthInsightsViewState.assessmentId = null;
  resetHealthFindingState();
  resetHealthComparisonState();
  healthInsightsState.capabilities = null;
  healthNavigationContext = null;
  document.getElementById("btn-health-return")?.setAttribute("hidden", "");
  findingDeviceReturnContext = null;
  resetHealthRosterViewState();
  healthInsightsState.rosterDetail = null;
  contextDetailsState.finding = { assessmentId: null, groupId: null, findingId: null };
  setContextDetailsMode("device");
}

function resetHealthInsightsForNetworkChange() {
  clearRosterMutationRefreshStatus();
  healthInsightsTab = HEALTH_INSIGHTS_TABS[0].id;
  resetHealthAssessmentHistory();
  resetHealthFindingState();
  resetHealthComparisonState();
  healthInsightsState.capabilities = null;
  healthNavigationContext = null;
  document.getElementById("btn-health-return")?.setAttribute("hidden", "");
  findingDeviceReturnContext = null;
  resetHealthRosterViewState();
  healthInsightsState.rosterDetail = null;
  contextDetailsState.finding = { assessmentId: null, groupId: null, findingId: null };
  setContextDetailsMode("device");
  contextDetailsController.setCollapsed(true);
}

async function refreshHealthAssessment() {
  const requestVersion = ++healthInsightsState.assessmentRequestVersion;
  const dataset = currentDataset;
  const entry = currentDataset?.entry;
  const datasetId = entry?.value;
  const isCurrent = () => requestVersion === healthInsightsState.assessmentRequestVersion
    && currentDataset === dataset
    && currentDataset?.entry?.value === datasetId;
  const previousAssessmentId = healthInsightsState.assessment?.assessmentId;
  const previousNetworkId = healthInsightsState.assessment?.networkId;
  const datasetChanged = healthInsightsState.datasetId !== entry?.value;
  if (datasetChanged) resetHealthInsightsForDatasetChange();
  const announceSelection = healthAssessmentHistoryState.announceSelection;
  healthAssessmentHistoryState.announceSelection = false;
  const requestedAssessmentId = healthAssessmentHistoryState.mode === "pinned"
    ? healthAssessmentHistoryState.pinnedAssessmentId
    : null;
  const requestedNetworkId = requestedAssessmentId
    ? healthAssessmentHistoryState.networkId
    : null;
  healthInsightsState.datasetId = entry?.value ?? null;
  healthInsightsState.error = "";
  healthInsightsState.supportError = "";
  healthInsightsState.assessment = null;
  healthInsightsState.device = null;
  healthInsightsState.deviceError = "";
  healthInsightsState.roster = null;
  healthInsightsState.rosterDetail = null;
  healthInsightsState.deviceRequestVersion += 1;
  healthInsightsState.rosterError = "";
  healthRosterViewState.requestVersion += 1;
  healthRosterViewState.detailVersion += 1;
  healthInsightsViewState.selectedGroupId = null;
  healthInsightsViewState.selectedFindingId = null;
  healthInsightsViewState.selectedEndpointId = null;
  healthInsightsViewState.detailsOpen = false;
  healthInsightsViewState.tableScrollTop = 0;
  findingDeviceReturnContext = null;
  document.getElementById("btn-back-to-health-finding")?.setAttribute("hidden", "");
  document.getElementById("btn-health-return")?.setAttribute("hidden", "");
  contextDetailsState.finding = { assessmentId: null, groupId: null, findingId: null };
  setContextDetailsMode("device");
  contextDetailsController.setCollapsed(true);
  healthAssessmentHistoryState.loading = true;
  healthAssessmentHistoryState.pageLoading = false;
  healthAssessmentHistoryState.requestVersion += 1;
  healthAssessmentHistoryState.page = null;
  healthAssessmentHistoryState.navigation = null;
  healthAssessmentHistoryState.error = "";
  healthAssessmentHistoryState.targetError = "";
  healthAssessmentHistoryState.unsupported = false;
  if (requestedNetworkId) healthAssessmentHistoryState.networkId = requestedNetworkId;
  if (currentDataset) currentDataset.healthAssessment = null;
  if (currentView === "insights") {
    announceHealthInsight(requestedAssessmentId
      ? "Loading the selected retained assessment."
      : "Loading the latest health assessment.");
  }
  document.getElementById("device-details").classList.remove("roster-selected");
  applyHealthAssessmentPresentation(null);
  if (entry?.healthEligible !== true) {
    healthInsightsState.loading = false;
    healthAssessmentHistoryState.loading = false;
    renderHealthStatusSummary();
    renderNetworkInsights();
    updateHealthPresentationControls();
    return;
  }

  healthInsightsState.loading = true;
  renderHealthStatusSummary();
  renderNetworkInsights();
  try {
    const assessment = await fetchHealthAssessment(
      entry.value,
      undefined,
      requestedAssessmentId
        ? { networkId: requestedNetworkId, assessmentId: requestedAssessmentId }
        : {},
    );
    if (!isCurrent()) return;
    if (requestedAssessmentId && (
      assessment.assessmentId !== requestedAssessmentId
      || assessment.networkId !== requestedNetworkId
    )) {
      throw new Error("Selected assessment is no longer retained.");
    }
    const networkChanged = Boolean(previousNetworkId && previousNetworkId !== assessment.networkId);
    if (networkChanged) resetHealthInsightsForNetworkChange();
    healthInsightsState.assessment = assessment;
    healthAssessmentHistoryState.networkId = assessment.networkId;
    if (announceSelection) {
      announceHealthInsight(requestedAssessmentId
        ? `Pinned retained assessment ${assessment.assessmentId}.`
        : "Following the latest retained assessment.");
    } else if (previousAssessmentId && previousAssessmentId !== assessment.assessmentId) {
      announceHealthInsight("Following a newer latest assessment.");
    }
    if (previousAssessmentId !== assessment.assessmentId) {
      findingRosterActionEligibility.clear();
      findingRosterActionPending.clear();
      healthInsightsState.rosterDetail = null;
      healthRosterViewState.assessmentId = assessment.assessmentId;
      healthRosterViewState.selectedDeviceId = null;
      healthRosterViewState.offset = 0;
      healthRosterViewState.tableScrollTop = 0;
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
    enableHealthColoringOnFirstInsightsVisit();
    applyHealthAssessmentPresentation(assessment);
    lastRenderedDatasetByView.delete("table");
    if (currentView === "table") renderCurrentView({ force: true });
    try {
      const support = await fetchHealthSupport(assessment.networkId);
      if (!isCurrent()) return;
      healthInsightsState.capabilities = support.capabilities;
      healthInsightsState.supportError = "";
      healthInsightsState.observations = support.observations;
      if (support.capabilities?.comparisonEndpointSelection === 1) {
        await loadHealthAssessmentHistoryPage(
          healthAssessmentHistoryState.offset,
          { selectedAssessmentId: assessment.assessmentId },
        );
        if (!isCurrent()) return;
      } else {
        healthAssessmentHistoryState.unsupported = true;
        healthAssessmentHistoryState.page = null;
        healthAssessmentHistoryState.navigation = null;
      }
      if (healthInsightsState.rosterDetail) {
        renderRosterDetailPanel(
          healthInsightsState.rosterDetail, healthInsightsState.rosterDetailPresence,
        );
      }
      if (support.capabilities?.comparisonReadModel === 1 && healthInsightsTab === "comparison") {
        if (support.capabilities.comparisonEndpointSelection === 1) {
          if (healthInsightsViewState.comparisonIntent !== "custom") {
            await selectComparisonPreset(
              healthInsightsViewState.comparisonIntent,
              { preserveOffset: true, preserveDisclosure: true },
            );
            if (!isCurrent()) return;
          } else if (healthInsightsState.comparisonEndpointDefaultsPending
              && !healthInsightsState.comparisonEndpointUnavailable) {
            await initializeComparisonEndpoints();
            if (!isCurrent()) return;
          } else if (!healthInsightsState.comparisonEndpointUnavailable) {
            const endpointRevision = ++healthInsightsState.comparisonEndpointRevision;
            const [afterPage, beforePage] = await Promise.all([
              requestComparisonEndpointPage("after", healthInsightsViewState.afterHistoryOffset, {
                selectedAssessmentId: healthInsightsViewState.afterAssessmentId,
              }),
              healthInsightsViewState.afterAssessmentId
                ? requestComparisonEndpointPage("before", healthInsightsViewState.beforeHistoryOffset, {
                  afterAssessmentId: healthInsightsViewState.afterAssessmentId,
                  selectedAssessmentId: healthInsightsViewState.beforeAssessmentId,
                })
                : Promise.resolve(null),
            ]);
            if (!isCurrent()) return;
            if (afterPage && (beforePage || !healthInsightsViewState.beforeAssessmentId)
                && endpointRevision === healthInsightsState.comparisonEndpointRevision
                && !healthInsightsState.comparisonEndpointUnavailable) {
              await loadComparisonEndpointPair(healthInsightsViewState.comparisonItemOffset);
              if (!isCurrent()) return;
            }
          }
        } else {
          await loadComparisonPage(healthInsightsViewState.comparisonOffset);
          if (!isCurrent()) return;
        }
      }
    } catch (error) {
      if (!isCurrent()) return;
      healthInsightsState.supportError = error.message;
      healthAssessmentHistoryState.error =
        `Retained run history unavailable: ${error.message}`;
      announceHealthInsight(healthAssessmentHistoryState.error);
      console.warn("Health history metadata is unavailable:", error);
    }
  } catch (error) {
    if (!isCurrent()) return;
    const selectedUnavailable = Boolean(requestedAssessmentId && error.status === 404);
    healthInsightsState.error = selectedUnavailable
      ? "Selected assessment is no longer retained."
      : error.message;
    if (currentView === "insights") announceHealthInsight(healthInsightsState.error);
    if (selectedUnavailable) {
      healthAssessmentHistoryState.targetError = healthInsightsState.error;
      healthAssessmentHistoryState.page = null;
      healthAssessmentHistoryState.navigation = null;
      void loadHealthAssessmentHistoryPage(0, {
        networkId: requestedNetworkId,
        datasetId: entry.value,
        selectedAssessmentId: null,
        preserveTargetError: true,
      });
    } else if (requestedAssessmentId && error.message === "Selected assessment is no longer retained.") {
      healthAssessmentHistoryState.targetError = error.message;
    } else {
      healthAssessmentHistoryState.targetError = healthInsightsState.error;
    }
  } finally {
    if (isCurrent()) {
      const resetComparisonDuringRefresh = healthInsightsState.comparisonResetPendingRefresh;
      healthInsightsState.comparisonResetPendingRefresh = false;
      healthInsightsState.loading = false;
      healthAssessmentHistoryState.loading = false;
      renderHealthStatusSummary();
      renderNetworkInsights();
      updateHealthPresentationControls();
      updateHealthRefreshControls();
      if (resetComparisonDuringRefresh && healthInsightsTab === "comparison") {
        ensureHealthComparisonLoaded();
      }
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
    healthInsightsState.refreshStatus = "error";
    healthInsightsState.refreshDetail = error.message;
  } finally {
    if (version === healthInsightsState.refreshVersion && currentDataset?.entry?.value === datasetId) {
      applyHealthAssessmentPresentation(getCurrentHealthAssessment());
      renderHealthStatusSummary();
      renderNetworkInsights();
      updateHealthPresentationControls();
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
function ensureHealthComparisonLoaded() {
  if (healthInsightsState.loading || !healthInsightsState.assessment
      || healthInsightsState.supportError
      || healthInsightsState.capabilities?.comparisonReadModel !== 1) return;
  if (endpointSelectionEnabled()) {
    if (healthInsightsState.comparisonPresetLoading
        || healthInsightsState.comparisonEndpointPairLoading
        || Object.values(healthInsightsState.comparisonEndpointLoading).some(Boolean)) return;
    if (healthInsightsState.comparisonEndpointDefaultsPending) {
      void initializeComparisonEndpoints();
    } else if (!healthInsightsState.comparisonEndpointPages.after) {
      void requestComparisonEndpointPage("after", 0, {
        selectedAssessmentId: healthInsightsViewState.afterAssessmentId,
      });
    }
  } else if (!healthInsightsState.comparisonPage && !healthInsightsState.comparisonListLoading) {
    void loadComparisonPage(0);
  }
}

function activateHealthTab(tab) {
  if (!HEALTH_INSIGHTS_TABS.some(({ id }) => id === tab)) return;
  if (healthInsightsTab !== tab) rosterNavigationGeneration += 1;
  if (healthInsightsTab === "findings") {
    healthInsightsViewState.tableScrollTop =
      document.getElementById("health-finding-table-wrap")?.scrollTop ?? 0;
  }
  if (healthInsightsTab === "comparison") {
    healthInsightsViewState.comparisonTableScrollTop =
      document.querySelector(".health-comparison-table-wrap")?.scrollTop ?? 0;
    healthInsightsViewState.comparisonTableScrollLeft =
      document.querySelector(".health-comparison-table-wrap")?.scrollLeft ?? 0;
  }
  if (healthInsightsTab === "roster") {
    healthRosterViewState.tableScrollTop = document.querySelector(".health-roster-table-wrap")?.scrollTop ?? 0;
    healthRosterViewState.tableScrollLeft = document.querySelector(".health-roster-table-wrap")?.scrollLeft ?? 0;
  }
  const tabChanged = healthInsightsTab !== tab;
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
  if (tab === "comparison" && tabChanged) ensureHealthComparisonLoaded();
  if (tab === "roster" && tabChanged && !healthInsightsState.roster
      && !healthInsightsState.rosterLoading && healthInsightsState.assessment) {
    void loadRosterPage(healthRosterViewState.offset);
  }
}

for (const { id, buttonId } of HEALTH_INSIGHTS_TABS) {
  const button = document.getElementById(buttonId);
  button?.addEventListener("click", () => activateHealthTab(id));
  button?.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const activeIndex = HEALTH_INSIGHTS_TABS.findIndex(({ id: tabId }) => tabId === healthInsightsTab);
    const targetIndex = event.key === "Home" ? 0
      : event.key === "End" ? HEALTH_INSIGHTS_TABS.length - 1
        : (activeIndex + (event.key === "ArrowRight" ? 1 : -1) + HEALTH_INSIGHTS_TABS.length)
          % HEALTH_INSIGHTS_TABS.length;
    activateHealthTab(HEALTH_INSIGHTS_TABS[targetIndex].id);
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
[
  ["health-status-filter", "status"],
  ["health-scope-filter", "scope"],
  ["health-evidence-filter", "evidenceKind"],
].forEach(([id, key]) => document.getElementById(id)?.addEventListener("change", (event) => {
  healthInsightsViewState.filters[key] = event.target.value;
  renderNetworkInsights();
}));
document.getElementById("health-findings-sort")?.addEventListener("change", (event) => {
  healthInsightsViewState.sort = { column: event.target.value, direction: "ascending" };
  healthInsightsViewState.sortWasChanged = true;
  renderNetworkInsights();
});
document.getElementById("btn-health-return")?.addEventListener("click", restoreHealthNavigationContext);
document.addEventListener("scroll", (event) => {
  if (currentView !== "insights"
      || !event.target?.matches?.(".health-comparison-table-wrap")) return;
  healthInsightsViewState.comparisonTableScrollTop = event.target.scrollTop;
}, true);
document.getElementById("btn-health-finding-close")?.addEventListener("click", () => {
  closeHealthFindingDetails();
});
document.getElementById("btn-back-to-health-finding")?.addEventListener("click", returnToHealthFinding);
document.getElementById("btn-health-reset")?.addEventListener("click", resetHealthFindings);
document.getElementById("btn-health-comparison-reset")?.addEventListener("click", resetHealthComparison);
document.getElementById("btn-health-roster-reset")?.addEventListener("click", resetHealthRoster);
document.getElementById("btn-health-export")?.addEventListener("click", () => {
  exportHealthAssessment(healthInsightsState.assessment);
});
document.getElementById("btn-health-refresh")?.addEventListener("click", () => {
  void runHealthRefresh();
});
document.getElementById("btn-health-refresh-cancel")?.addEventListener("click", () => {
  void cancelHealthRefresh();
});
document.getElementById("health-roster-action-form")?.addEventListener("submit", (event) => {
  void submitRosterAction(event);
});
document.getElementById("health-roster-action-cancel")?.addEventListener("click", () => {
  if (!rosterMutationPendingDeviceId) {
    document.getElementById("health-roster-action-dialog")?.close();
  }
});
document.getElementById("health-roster-action-dialog")?.addEventListener("cancel", () => {
  if (!rosterMutationPendingDeviceId) {
    activeRosterAction = null;
    activeRosterRequest = null;
  }
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

function initAppearanceControls() {
  const controller = globalThis.tdashTheme;
  if (!controller) return;
  const buttons = ["theme-toggle", "settings-theme-toggle"].map((id) => document.getElementById(id));
  const modes = [
    { preference: "system", label: "System", symbol: "\u25d1" },
    { preference: "light", label: "Light", symbol: "\u263c" },
    { preference: "dark", label: "Dark", symbol: "\u263e" },
  ];
  let paletteError = "";
  function applyAppearance() {
    try {
      const palette = readThemePalette();
      getTopologyFilterHandlers()?.applyTheme(palette);
      paletteError = "";
    } catch (error) {
      console.error("Unable to apply appearance palette.", error);
      paletteError = "Appearance palette unavailable; topology could not be updated.";
    }
  }
  function synchronize(state) {
    const index = modes.findIndex((mode) => mode.preference === state.preference);
    const mode = modes[index];
    const label = mode.preference === "system" ? `${mode.label} (${state.resolvedTheme})` : mode.label;
    const description = `Theme: ${label}. Switch to ${modes[(index + 1) % modes.length].label}.`;
    for (const button of buttons) {
      button.disabled = false;
      button.dataset.themePreference = state.preference;
      button.querySelector(".theme-toggle-icon").textContent = mode.symbol;
      button.setAttribute("aria-label", description);
      button.title = description;
    }
    const message = paletteError || (state.persistenceStatus === "unavailable"
      ? "Theme applies to this page only. Browser storage is unavailable."
      : state.persistenceStatus === "invalid-value"
        ? "Saved theme was not recognized. Using System; choose a theme to save it."
        : "");
    for (const id of ["theme-status", "settings-theme-status"]) {
      document.getElementById(id).textContent = message;
    }
  }
  function cyclePreference() {
    const index = modes.findIndex((mode) => mode.preference === controller.getState().preference);
    controller.setPreference(modes[(index + 1) % modes.length].preference);
  }
  buttons.forEach((button) => button.addEventListener("click", cyclePreference));
  document.addEventListener("tdash:theme-changed", (event) => {
    applyAppearance();
    synchronize(event.detail);
  });
  applyAppearance();
  synchronize(controller.getState());
}

initAppearanceControls();

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
initDetailPanelToggles(
  document.getElementById("device-details"),
  () => closeDeviceDetailsPanel({ restoreFocus: true }),
);
contextDetailsController = initContextDetailsPanel({
  host: document.getElementById("panel-context-details"),
  toggleButton: document.getElementById("btn-details-panel-toggle"),
  onVisibilityChanged: handleDetailsPanelVisibilityChanged,
});

function closeDeviceDetailsPanel({ restoreFocus = false } = {}) {
  if (healthInsightsTab === "roster" && healthRosterViewState.selectedDeviceId) {
    rosterNavigationGeneration += 1;
    healthRosterViewState.selectedDeviceId = null;
    healthInsightsState.rosterDetail = null;
    document.getElementById("device-details")?.classList.remove("roster-selected");
  }
  contextDetailsController.setCollapsed(true);
  if (restoreFocus) {
    requestAnimationFrame(() => document.getElementById("btn-details-panel-toggle")?.focus());
  }
}

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
// (rloc16 / isBorderRouter / type), which is the case for non-Thread sources such as mDNS.
function updateDeviceStatusBar(counts) {
  currentDeviceStatusCounts = counts ? { ...counts } : null;
  threadNetworkModelCache = null;
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
  window.tdashDebug.fetchStatusPinnedUntil = Date.now() + (
    fetchFailureState ? Number.POSITIVE_INFINITY : pinDurationMs
  );
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

function handleDatasetFetchCancellation(selectedValue, fetchStartedAt) {
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
    updateFetchStatusBar(fetchStartedAt);
  } else {
    if (statusEl) statusEl.textContent = `Fetch cancelled for "${selectedValue}".`;
    // No partial data available: keep current view or clear bars.
    if (currentDataset) {
      activateViewStatus(currentView, currentDataset);
      renderCurrentView();
      updateFetchStatusBar(fetchStartedAt);
    } else {
      _setStatusSpans(_FETCH_STATUS_IDS, "—");
      _setStatusSpans(_DEVICE_STATUS_IDS, "—");
    }
  }
}

function handleDatasetFetchError(err, selectedValue, selectedDataset, refreshIntent, fetchStartedAt) {
  restoreLastKnownGoodDataset();
  recordWorkspaceActivity("dataset-sync", "Dataset sync failed", {
    dataset: selectedValue,
    error: err?.message || String(err),
  });
  console.error("loadDataset threw:", err);
  const attempted = datasetIdentityLabel({ entry: selectedDataset ?? { value: selectedValue, label: selectedValue } });
  const displayed = currentDataset
    ? `Still displaying ${datasetIdentityLabel(currentDataset)}.`
    : "No dataset is available to display.";
  const sameDataset = currentDataset?.entry?.value === selectedValue;
  fetchFailureState = currentDataset && sameDataset && refreshIntent
    ? `Refresh failed for ${datasetIdentityLabel(currentDataset)}; the prior snapshot remains displayed and freshness is unconfirmed.`
    : `Sync failed for ${attempted}. ${displayed}`;
  if (currentDataset) {
    renderCurrentView();
    updateFetchStatusBar(fetchStartedAt);
  } else {
    clearRenderedDatasetViews({
      ...(selectedDataset ?? {}),
      entry: selectedDataset ?? { value: selectedValue, label: selectedValue },
      rows: [],
      rawFiles: [],
      loadedFiles: [],
      deviceProjections: new Map(),
      auxiliaryFiles: {},
    });
    _setStatusSpans(_FETCH_STATUS_IDS, "—");
    _setStatusSpans(_DEVICE_STATUS_IDS, "—");
  }
  const statusEl = document.getElementById("fetch-status-line-content");
  if (statusEl) statusEl.textContent = fetchFailureState;
  _pinFetchStatusLineMessage(fetchFailureState, Number.POSITIVE_INFINITY);
  supersedeViewStatus(`Error loading "${selectedValue}": ${err?.message || String(err)}`);
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
  const attemptVersion = ++fetchAttemptVersion;
  const refreshIntent = forceFresh || document.getElementById("chk-force-fresh")?.checked === true;
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
      handleDatasetFetchCancellation(selectedValue, _lastFetchStartedAt);
    } else {
      handleDatasetFetchError(err, selectedValue, selectedDataset, refreshIntent, _lastFetchStartedAt);
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
    const fetchStatusEl = document.getElementById("fetch-status-line-content");
    const failureDetails = fetchStatusEl?.textContent || `Could not load "${selectedValue}".`;
    const attempted = datasetIdentityLabel({ entry: selectedDataset ?? { value: selectedValue, label: selectedValue } });
    const displayed = currentDataset
      ? `Still displaying ${datasetIdentityLabel(currentDataset)}.`
      : "No dataset is available to display.";
    const sameDataset = currentDataset?.entry?.value === selectedValue;
    fetchFailureState = currentDataset
      ? sameDataset && refreshIntent
        ? `Refresh failed for ${datasetIdentityLabel(currentDataset)}; the prior snapshot remains displayed and freshness is unconfirmed.`
        : `Could not load ${attempted}. ${displayed}`
      : `Could not load ${attempted}. No dataset is available to display.`;
    if (failureDetails && !failureDetails.startsWith("Loading")) {
      fetchFailureState += ` ${failureDetails}`;
    }
    if (currentDataset) {
      renderCurrentView();
      updateFetchStatusBar(_lastFetchStartedAt);
    } else {
      clearRenderedDatasetViews({
        ...(selectedDataset ?? {}),
        entry: selectedDataset ?? { value: selectedValue, label: selectedValue },
        rows: [],
        rawFiles: [],
        loadedFiles: [],
        deviceProjections: new Map(),
        auxiliaryFiles: {},
      });
      _setStatusSpans(_FETCH_STATUS_IDS, "—");
      _setStatusSpans(_DEVICE_STATUS_IDS, "—");
    }
    if (fetchStatusEl) fetchStatusEl.textContent = fetchFailureState;
    _pinFetchStatusLineMessage(fetchFailureState, Number.POSITIVE_INFINITY);
    supersedeViewStatus(currentDataset ? "Retained last complete dataset." : "No dataset loaded.");
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

  // Final reconciliation render after every primary request has settled.
  try {
    sourceCapabilities = await loadSourceCapabilities();
  } catch (error) {
    console.warn("Unable to refresh source capabilities", error);
  }
  if (attemptVersion !== fetchAttemptVersion) return;
  if (!currentDataset.isPartial) {
    fetchFailureState = null;
    if (window.tdashDebug) window.tdashDebug.fetchStatusPinnedUntil = 0;
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
    const failedFiles = (currentDataset.entry?.files ?? [])
      .filter((filename) => !currentDataset.loadedFiles?.includes(filename));
    _fetchStatusEl.textContent = currentDataset.materializationState === "partial"
      ? `⚠ Incomplete Unified dataset ${datasetIdentityLabel(currentDataset)}: cached source coverage is partial. Showing partial data.`
      : failedFiles.length > 0
      ? `⚠ Incomplete dataset ${datasetIdentityLabel(currentDataset)}: ${currentDataset.loadedFiles?.length ?? 0} of ${currentDataset.entry.files.length} required files loaded; ${failedFiles.length} required file(s) unavailable. Showing partial data.`
      : "";
    if (currentDataset.isPartial) {
      _pinFetchStatusLineMessage(_fetchStatusEl.textContent, Number.POSITIVE_INFINITY);
    }
  }
  recordWorkspaceActivity("dataset-sync", currentDataset.isPartial
    ? "Dataset sync incomplete"
    : "Dataset sync completed", {
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

const FIELDSET_DISCLOSURES = [
  {
    buttonId: "btn-fetch-toggle-status-chk-cache",
    fieldsetIds: ["fieldset-cache"],
    label: "cache options",
  },
  {
    buttonId: "btn-toggle-node-diag-filters",
    fieldsetIds: ["fieldset-node-link-filters", "fieldset-diag-filters"],
    label: "node, link and diagnostic filters",
  },
];

function isFieldsetExpanded(id) {
  const fieldset = document.getElementById(id);
  return !fieldset.hidden && !fieldset.classList.contains("collapsed");
}

function syncFieldsetDisclosures() {
  for (const { buttonId, fieldsetIds, label } of FIELDSET_DISCLOSURES) {
    const button = document.getElementById(buttonId);
    const expanded = fieldsetIds.every(isFieldsetExpanded);
    button.setAttribute("aria-expanded", String(expanded));
    button.setAttribute("aria-label", `${expanded ? "Hide" : "Show"} ${label}`);
    button.title = button.getAttribute("aria-label");
  }
}

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
    syncFieldsetDisclosures();
  });
});

document.getElementById("btn-toggle-node-diag-filters")?.addEventListener("click", () => {
  const nodeLinkFieldset = document.getElementById("fieldset-node-link-filters");
  const diagFieldset = document.getElementById("fieldset-diag-filters");
  const nodeLinkToggleBtn = document.getElementById("btn-toggle-node-link-filters");
  const diagToggleBtn = document.getElementById("btn-toggle-diag-filters");

  if (!nodeLinkFieldset || !diagFieldset) return;

  const shouldShow = !["fieldset-node-link-filters", "fieldset-diag-filters"].every(isFieldsetExpanded);

  nodeLinkFieldset.hidden = !shouldShow;
  diagFieldset.hidden = !shouldShow;

  if (shouldShow) {
    nodeLinkFieldset.classList.remove("collapsed");
    diagFieldset.classList.remove("collapsed");
  }

  nodeLinkToggleBtn?.setAttribute("aria-expanded", String(shouldShow));
  diagToggleBtn?.setAttribute("aria-expanded", String(shouldShow));
  syncFieldsetDisclosures();
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

  const shouldShow = !isFieldsetExpanded("fieldset-cache");
  cacheFieldset.hidden = !shouldShow;

  // When revealed via the fetch/status toggle, show cache controls immediately.
  if (shouldShow) {
    cacheFieldset.classList.remove("collapsed");
    cacheLegendBtn?.setAttribute("aria-expanded", "true");
  } else {
    cacheFieldset.classList.add("collapsed");
    cacheLegendBtn?.setAttribute("aria-expanded", "false");
  }
  syncFieldsetDisclosures();
});

syncFieldsetDisclosures();

// ── Collapsible Filters Panel ────────────────────────────────────────────────
// (Handled by unified collapse logic above)
