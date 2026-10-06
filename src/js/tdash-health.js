import { trackedFetch } from "./tdash-activity.js";

const PILLAR_LABELS = Object.freeze({
  availability: "Availability",
  connectivity: "Connectivity",
  delivery: "Delivery",
  resilience: "Resilience",
  externalRouting: "External routing",
});

const PILLAR_TOOLTIPS = Object.freeze({
  availability: "Observed device presence and expected-device coverage.",
  connectivity: "Attachment and relationship evidence showing how devices connect to the mesh.",
  delivery: "Packet delivery and error-counter evidence from observed devices and relationships.",
  resilience: "Router, Border Router, and alternate-path evidence for avoiding single points of failure.",
  externalRouting: "Evidence that the Thread mesh has usable external or Border Router connectivity.",
});

const HEALTH_PRESENTATION_POLICY = Object.freeze({
  visiblePillars: Object.freeze(["availability", "connectivity", "delivery", "resilience"]),
  suppressedRuleIds: new Set(["network.external-routing"]),
});

const COVERAGE_STATUS_TOOLTIPS = Object.freeze({
  sufficient: "Sufficient: the assessment has the evidence required for this pillar.",
  limited: "Limited: some useful evidence is available, but coverage is incomplete.",
  missing: "Missing: the assessment does not have the evidence required for this pillar.",
});

const COVERAGE_STATUS_GLYPHS = Object.freeze({
  sufficient: "\u2713",
  limited: "!",
  missing: "\u00d7",
});

const FINDING_SECTIONS = Object.freeze([
  { id: "needs-work", title: "Needs Work", statuses: new Set(["poor"]) },
  { id: "needs-attention", title: "Needs Attention", statuses: new Set(["moderate", "unknown"]) },
  { id: "going-well", title: "Going Well", statuses: new Set(["strong"]) },
]);

const HEALTH_STATUS_ORDER = Object.freeze({ poor: 0, moderate: 1, unknown: 2, strong: 3 });
const HEALTH_MATERIALITY_ORDER = Object.freeze({ network: 0, relationship: 1, device: 2, informational: 3 });
const HEALTH_CONFIDENCE_ORDER = Object.freeze({ high: 0, medium: 1, low: 2 });

function appendText(parent, tagName, text, className = "") {
  const element = document.createElement(tagName);
  element.textContent = text;
  if (className) element.className = className;
  parent.appendChild(element);
  return element;
}

async function healthRequest(path, signal) {
  const response = await trackedFetch(path, { headers: { Accept: "application/json" }, signal });
  if (!response.ok) {
    const error = new Error(response.status === 404
      ? "No processed health assessment is available for this dataset."
      : `Health service unavailable (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

export function fetchHealthAssessment(datasetId, signal) {
  return healthRequest(`api/health/summary?dataset=${encodeURIComponent(datasetId)}`, signal);
}

export async function startHealthProcessing(datasetId, signal) {
  const response = await trackedFetch("api/health/process-dataset", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ dataset: datasetId }),
    signal,
  });
  if (!response.ok) throw new Error(`Health processing unavailable (${response.status}).`);
  return response.json();
}

export async function fetchHealthJob(jobId, signal) {
  const response = await trackedFetch(`api/job/${encodeURIComponent(jobId)}`, {
    headers: { Accept: "application/json" }, signal,
  }, "silent");
  if (!response.ok) throw new Error(`Health task unavailable (${response.status}).`);
  return response.json();
}

export async function cancelHealthJob(jobId, signal) {
  const response = await trackedFetch(`api/job/${encodeURIComponent(jobId)}`, {
    method: "DELETE", headers: { Accept: "application/json" }, signal,
  });
  if (!response.ok && response.status !== 409) {
    throw new Error(`Health task cancellation unavailable (${response.status}).`);
  }
  return response.json();
}

export function fetchHealthDevice(assessmentId, deviceId, signal) {
  const query = new URLSearchParams({ assessment: assessmentId });
  return healthRequest(`api/health/devices/${encodeURIComponent(deviceId)}?${query}`, signal);
}

export function fetchHealthRoster(networkId, assessmentId, view, signal) {
  const query = new URLSearchParams({ network: networkId, assessment: assessmentId,
    limit: "25", offset: String(view.offset), q: view.search, presence: view.presence,
    rosterState: view.rosterState, sort: view.sort.column, direction: view.sort.direction });
  return healthRequest(`api/health/roster?${query}`, signal);
}

export function fetchHealthRosterDevice(networkId, deviceId, signal, assessmentId = null) {
  const query = new URLSearchParams({ network: networkId });
  if (assessmentId) query.set("assessment", assessmentId);
  return healthRequest(`api/health/roster/${encodeURIComponent(deviceId)}?${query}`, signal);
}

export function patchHealthRosterDevice(networkId, deviceId, payload, signal) {
  const query = new URLSearchParams({ network: networkId });
  return trackedFetch(
    `api/health/roster/${encodeURIComponent(deviceId)}?${query}`,
    {
      method: "PATCH",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    },
  ).then(async (response) => {
    if (!response.ok) {
      const responseText = await response.text();
      let details = responseText.trim();
      try {
        const body = JSON.parse(responseText);
        details = typeof body?.reason === "string" ? body.reason
          : typeof body?.error === "string" ? body.error : details;
      } catch {
        details = details.split(/\r?\n\r?\n/).at(-1)?.trim() || details;
      }
      details = details.replace(/^\d{3}:\s*/, "");
      if (details.startsWith("Conflict\n\n")) details = details.slice("Conflict\n\n".length);
      const code = details.match(/^(stale-revision|reassessment-baseline-unavailable):/)?.[1];
      const error = new Error(details || `Roster action rejected (${response.status}).`);
      error.status = response.status;
      error.code = code;
      throw error;
    }
    return response.json();
  });
}

export function createHealthMutationRequestId(cryptoApi = globalThis.crypto) {
  if (typeof cryptoApi?.randomUUID === "function") return cryptoApi.randomUUID();
  const bytes = new Uint8Array(16);
  if (typeof cryptoApi?.getRandomValues === "function") {
    cryptoApi.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function fetchHealthComparisons(networkId, datasetId, offset = 0, signal) {
  const query = new URLSearchParams({ network: networkId, dataset: datasetId, limit: "25", offset: String(offset) });
  return healthRequest(`api/health/comparisons?${query}`, signal);
}

export function fetchHealthComparison(comparisonId, offset = 0, signal, filters = {}) {
  const query = new URLSearchParams({
    limit: "25",
    offset: String(offset),
    scope: filters.scope || "all",
    result: filters.result || "changed",
  });
  return healthRequest(`api/health/comparisons/${encodeURIComponent(comparisonId)}?${query}`, signal);
}

export function fetchHealthComparisonEndpoints(
  networkId, datasetId, side, offset = 0, signal, options = {},
) {
  const query = new URLSearchParams({
    network: networkId,
    dataset: datasetId,
    side,
    limit: "25",
    offset: String(offset),
  });
  if (options.afterAssessmentId) query.set("after", options.afterAssessmentId);
  if (options.selectedAssessmentId) query.set("selected", options.selectedAssessmentId);
  return healthRequest(`api/health/comparison-endpoints?${query}`, signal);
}

export function fetchHealthComparisonPair(query, offset = 0, signal) {
  const parameters = new URLSearchParams({
    network: query.networkId,
    dataset: query.datasetId,
    before: query.beforeAssessmentId,
    after: query.afterAssessmentId,
    limit: "25",
    offset: String(offset),
    scope: query.scope || "all",
    result: query.result || "changed",
  });
  return healthRequest(`api/health/comparison?${parameters}`, signal);
}

export function isHealthComparisonEndpointPageForQuery(page, query) {
  const validEndpoint = (endpoint) => !endpoint || (
    endpoint.networkId === query.networkId && endpoint.datasetId === query.datasetId
    && typeof endpoint.assessmentId === "string" && endpoint.assessmentId.length > 0
    && typeof endpoint.observedAt === "string" && Number.isFinite(Date.parse(endpoint.observedAt))
    && typeof endpoint.assessedAt === "string" && Number.isFinite(Date.parse(endpoint.assessedAt))
    && ["complete", "partial"].includes(endpoint.completeness)
  );
  return page?.schemaVersion === 1 && page.networkId === query.networkId
    && page.datasetId === query.datasetId && page.side === query.side
    && (page.afterAssessmentId || null) === (query.afterAssessmentId || null)
    && page.comparisonVersion === query.comparisonVersion
    && page.comparisonPolicyDigest === query.comparisonPolicyDigest
    && Number.isInteger(page.total) && page.total >= 0
    && page.limit === 25 && page.offset === query.offset
    && Array.isArray(page.items) && page.items.length <= page.limit
    && page.offset + page.items.length <= page.total
    && page.items.every((endpoint) => Boolean(endpoint) && validEndpoint(endpoint))
    && validEndpoint(page.selected)
    && validEndpoint(page.defaultAfter)
    && validEndpoint(page.defaultBefore)
    && validEndpoint(page.predecessor)
    && Array.isArray(page.shortcuts)
    && page.shortcuts.every((shortcut) => (
      ["1d", "3d", "1w", "1m"].includes(shortcut?.interval)
      && Number.isInteger(shortcut.durationSeconds) && shortcut.durationSeconds > 0
      && validEndpoint(shortcut.candidate)
    ))
    && (!page.selected || page.selected.assessmentId === query.selectedAssessmentId);
}

export function findHealthComparisonEndpointMetadata(
  assessmentId, pages, comparison, pinnedBefore = null,
) {
  if (!assessmentId) return null;
  if (pinnedBefore?.assessmentId === assessmentId) return pinnedBefore;
  for (const side of ["before", "after"]) {
    const page = pages?.[side];
    const match = page?.items.find((item) => item.assessmentId === assessmentId);
    if (match) return match;
    if (page?.selected?.assessmentId === assessmentId) return page.selected;
    for (const key of ["defaultAfter", "defaultBefore", "predecessor"]) {
      if (page?.[key]?.assessmentId === assessmentId) return page[key];
    }
  }
  if (comparison?.beforeAssessmentId === assessmentId) {
    return { assessmentId, observedAt: comparison.beforeObservedAt };
  }
  if (comparison?.afterAssessmentId === assessmentId) {
    return { assessmentId, observedAt: comparison.afterObservedAt };
  }
  return null;
}

export function isHealthComparisonPairForQuery(comparison, query) {
  return comparison?.schemaVersion === 1
    && comparison.networkId === query.networkId
    && comparison.datasetId === query.datasetId
    && comparison.beforeAssessmentId === query.beforeAssessmentId
    && comparison.afterAssessmentId === query.afterAssessmentId
    && comparison.comparisonPolicyDigest === query.comparisonPolicyDigest
    && comparison.comparisonVersion === query.comparisonVersion
    && ["stored", "derived"].includes(comparison.origin)
    && (comparison.origin !== "derived" || comparison.createdAt === null)
    && Number.isInteger(comparison.itemCount) && comparison.itemCount >= 0
    && Number.isInteger(comparison.filteredItemCount)
    && comparison.filteredItemCount >= 0
    && comparison.filteredItemCount <= comparison.itemCount
    && Number.isInteger(comparison.limit) && comparison.limit === 25
    && Number.isInteger(comparison.offset) && comparison.offset === query.offset
    && Array.isArray(comparison.items) && comparison.items.length <= comparison.limit
    && (comparison.items.length === 0
      ? comparison.offset > 0 || comparison.filteredItemCount === 0
      : comparison.offset + comparison.items.length <= comparison.filteredItemCount)
    && comparison.items.every((item) => (
      typeof item.itemId === "string" && typeof item.scope === "string"
      && typeof item.subjectId === "string"
    ));
}

export function isHealthComparisonDetailForQuery(comparison, query) {
  return comparison?.schemaVersion === 1
    && comparison.comparisonId === query.comparisonId
    && comparison.networkId === query.networkId
    && comparison.datasetId === query.datasetId
    && Number.isInteger(comparison.itemCount) && comparison.itemCount >= 0
    && Number.isInteger(comparison.filteredItemCount)
    && comparison.filteredItemCount >= 0
    && comparison.filteredItemCount <= comparison.itemCount
    && Number.isInteger(comparison.limit) && comparison.limit > 0
    && Number.isInteger(comparison.offset) && comparison.offset === query.offset
    && comparison.offset >= 0
    && Array.isArray(comparison.items)
    && comparison.items.length <= comparison.limit
    && comparison.items.length <= comparison.itemCount
    && (comparison.items.length === 0
      ? comparison.offset > 0 || comparison.filteredItemCount === 0
      : comparison.offset + comparison.items.length <= comparison.filteredItemCount
        && comparison.offset + comparison.items.length <= comparison.itemCount);
}

export function isComparisonPageForAssessment(page, assessment, offset) {
  return page?.schemaVersion === 1 && Array.isArray(page.items)
    && Number.isInteger(page.total) && page.total >= 0
    && Number.isInteger(page.limit) && page.limit > 0
    && Number.isInteger(page.offset) && page.offset >= 0
    && page.offset === offset && page.items.length <= page.limit
    && page.offset + page.items.length <= page.total
    && page.items.every((item) => item?.networkId === assessment.networkId
      && item.datasetId === assessment.datasetId && typeof item.comparisonId === "string"
      && item.comparisonId.length > 0);
}

const COMPARISON_HEADER_FIELDS = [
  "comparisonVersion",
  "beforeAssessmentId",
  "afterAssessmentId",
  "beforeObservationId",
  "afterObservationId",
  "baselineState",
  "comparable",
  "itemCount",
];

function comparisonHeaderMatches(left, right) {
  if (!left || !right) return left === right;
  return COMPARISON_HEADER_FIELDS.every((field) => left[field] === right[field]);
}

function comparisonHeaderSnapshot(header) {
  if (!header) return null;
  return Object.fromEntries(COMPARISON_HEADER_FIELDS.map((field) => [field, header[field]]));
}

function sameComparisonQuery(left, right) {
  return Boolean(left && right && left.networkId === right.networkId &&
    left.datasetId === right.datasetId && left.comparisonId === right.comparisonId &&
    left.scope === right.scope && left.result === right.result && left.offset === right.offset);
}

export function createHealthComparisonDetailController({
  state,
  getAssessment,
  getSelection,
  getSummary,
  getOffset,
  setOffset,
  updateSelection,
  fetchDetail = fetchHealthComparison,
  onChange = () => {},
}) {
  function makeQuery(assessment, selection, offset) {
    return {
      networkId: assessment.networkId,
      datasetId: assessment.datasetId,
      comparisonId: selection.comparisonId,
      scope: selection.scope,
      result: selection.result,
      offset,
    };
  }

  function isCurrent(query, version) {
    const assessment = getAssessment();
    const selection = getSelection();
    return version === state.comparisonDetailRequestVersion &&
      assessment?.networkId === query.networkId &&
      assessment?.datasetId === query.datasetId &&
      selection.comparisonId === query.comparisonId &&
      selection.scope === query.scope &&
      selection.result === query.result;
  }

  async function select(comparisonId, offset = 0, headerRetries = 0) {
    const version = ++state.comparisonDetailRequestVersion;
    state.comparisonDetailError = "";
    if (!comparisonId) {
      state.comparison = null;
      state.comparisonQueryIdentity = null;
      state.comparisonDetailRequestIdentity = null;
      state.comparisonDetailRequestHeader = null;
      state.comparisonDetailLoading = false;
      setOffset(0);
      onChange();
      return;
    }
    const assessment = getAssessment();
    if (!assessment) return;
    const selection = getSelection();
    const query = makeQuery(assessment, { ...selection, comparisonId }, offset);
    const summary = getSummary(comparisonId);
    if (sameComparisonQuery(state.comparisonQueryIdentity, query) &&
        state.comparison?.comparisonId === comparisonId &&
        (!summary || comparisonHeaderMatches(summary, state.comparison))) {
      state.comparisonDetailLoading = false;
      onChange();
      return;
    }

    state.comparison = null;
    state.comparisonQueryIdentity = null;
    state.comparisonDetailRequestIdentity = query;
    state.comparisonDetailRequestHeader = comparisonHeaderSnapshot(summary);
    state.comparisonDetailLoading = true;
    onChange();
    try {
      const comparison = await fetchDetail(comparisonId, offset, undefined, {
        scope: query.scope,
        result: query.result,
      });
      if (!isCurrent(query, version)) return;
      if (!isHealthComparisonDetailForQuery(comparison, query)) {
        throw new Error("Invalid stored comparison response.");
      }
      const currentSummary = getSummary(comparisonId);
      if (currentSummary && !comparisonHeaderMatches(currentSummary, comparison)) {
        if (headerRetries < 1) {
          await select(comparisonId, offset, headerRetries + 1);
          return;
        }
        throw new Error("Comparison changed while it was being read. Retry the request.");
      }
      if (offset > 0 && comparison.items.length === 0) {
        setOffset(0);
        await select(comparisonId, 0, headerRetries);
        return;
      }
      state.comparison = comparison;
      state.comparisonQueryIdentity = query;
    } catch (error) {
      if (!isCurrent(query, version)) return;
      state.comparisonDetailError = error.message;
    } finally {
      if (isCurrent(query, version)) {
        state.comparisonDetailLoading = false;
        state.comparisonDetailRequestIdentity = null;
        state.comparisonDetailRequestHeader = null;
        onChange();
      }
    }
  }

  function retrySelected() {
    const selection = getSelection();
    if (!selection.comparisonId) return;
    return select(selection.comparisonId, getOffset());
  }

  function reconcileSummary() {
    const selection = getSelection();
    if (!selection.comparisonId) return;
    const summary = getSummary(selection.comparisonId);
    if (!summary) return;
    const activeRequest = state.comparisonDetailRequestIdentity;
    const activeRequestStale = state.comparisonDetailLoading &&
      activeRequest?.comparisonId === selection.comparisonId &&
      !comparisonHeaderMatches(state.comparisonDetailRequestHeader, summary);
    const cachedDetailStale = state.comparison?.comparisonId === selection.comparisonId &&
      !comparisonHeaderMatches(summary, state.comparison);
    if (activeRequestStale || cachedDetailStale) {
      return select(selection.comparisonId, getOffset());
    }
  }

  function invalidate() {
    state.comparisonDetailRequestVersion += 1;
    state.comparison = null;
    state.comparisonQueryIdentity = null;
    state.comparisonDetailRequestIdentity = null;
    state.comparisonDetailRequestHeader = null;
    state.comparisonDetailLoading = false;
    state.comparisonDetailError = "";
  }

  function cancelPending() {
    state.comparisonDetailRequestVersion += 1;
    state.comparisonDetailRequestIdentity = null;
    state.comparisonDetailRequestHeader = null;
    state.comparisonDetailLoading = false;
  }

  function changeFilter(filter, value) {
    const selection = getSelection();
    if (selection[filter] === value) return;
    updateSelection(filter, value);
    setOffset(0);
    if (selection.comparisonId) {
      return select(selection.comparisonId, 0);
    }
    onChange();
  }

  return { select, retrySelected, reconcileSummary, invalidate, cancelPending, changeFilter };
}

function formatComparisonTime(timestamp, now) {
  if (typeof timestamp !== "string" || !timestamp.trim()) return "unknown";
  const observedAt = Date.parse(timestamp);
  if (!Number.isFinite(observedAt)) return "unknown";
  const totalMinutes = Math.max(0, Math.floor((now - observedAt) / 60_000));
  const days = Math.floor(totalMinutes / 1_440);
  const hours = Math.floor((totalMinutes % 1_440) / 60);
  const minutes = totalMinutes % 60;
  return [days > 0 && `${days}d`, hours > 0 && `${hours}h`, `${minutes}m`].filter(Boolean).join(" ");
}

function formatUtcComparisonTimestamp(timestamp) {
  if (typeof timestamp !== "string" || !timestamp.trim()) return "unknown";
  const observedAt = Date.parse(timestamp);
  if (!Number.isFinite(observedAt)) return "unknown";
  return new Date(observedAt).toISOString().slice(0, 19).replace("T", " ");
}

function appendEndpointPicker(controls, side, page, selectedId, selected, loading, actions) {
  const label = appendText(controls, "label", side === "before" ? "Before" : "After",
    "health-comparison-endpoint-control");
  const picker = document.createElement("select");
  picker.setAttribute("aria-label", side === "before" ? "Before assessment" : "After assessment");
  picker.disabled = loading || !page || !page.total;
  const now = Date.now();
  const appendOption = (endpoint, isSelected = false) => {
    const option = document.createElement("option");
    option.value = endpoint.assessmentId;
    option.textContent = `${formatComparisonTime(endpoint.observedAt, now)} · ${formatUtcComparisonTimestamp(endpoint.observedAt)}`
      + `${endpoint.completeness === "partial" ? " · Partial" : ""}`
      + `${isSelected ? " (selected)" : ""}`;
    option.title = `${endpoint.assessmentId} · observed ${endpoint.observedAt}`
      + ` · assessed ${endpoint.assessedAt} · ${endpoint.completeness}`;
    picker.appendChild(option);
  };
  (page?.items || []).forEach((endpoint) => appendOption(endpoint));
  if (selectedId && selected && !page?.items.some((item) => item.assessmentId === selectedId)) {
    appendOption(selected, true);
  }
  picker.value = selectedId || "";
  picker.addEventListener("change", () => actions.endpointSelect?.(side, picker.value));
  label.appendChild(picker);
}

function appendEndpointHistoryNavigation(container, side, page, loading, actions) {
  const navigation = appendText(container, "div", "", "health-comparison-endpoint-navigation");
  const title = side === "before" ? "Before assessments" : "After assessments";
  const previous = appendText(navigation, "button", `Previous ${title}`);
  previous.type = "button";
  previous.disabled = loading || !page || page.offset === 0;
  previous.addEventListener("click", () => actions.endpointPage?.(
    side, Math.max(0, page.offset - page.limit),
  ));
  const next = appendText(navigation, "button", `Next ${title}`);
  next.type = "button";
  next.disabled = loading || !page || page.offset + page.items.length >= page.total;
  next.addEventListener("click", () => actions.endpointPage?.(
    side, page.offset + page.limit,
  ));
  return navigation;
}

function appendComparisonPresets(controls, viewState, actions, liveStatus) {
  const group = appendText(controls, "div", "", "health-comparison-presets");
  appendText(group, "span", "Compare:", "health-comparison-presets-label");
  const shortcuts = viewState.latestPresetPage?.shortcuts || [];
  const loading = viewState.presetLoading || viewState.endpointLoading?.after;
  const labels = [
    ["1d", "1D", "1 day"],
    ["3d", "3D", "3 days"],
    ["1w", "1W", "7 days"],
  ];
  const statusMessages = [];
  labels.forEach(([interval, label, duration]) => {
    const shortcut = shortcuts.find((item) => item.interval === interval);
    const candidate = shortcut?.candidate;
    const unavailable = `Not enough history for ${label}: no retained baseline at least ${duration} before the latest assessment.`;
    const button = appendText(group, "button", label);
    button.type = "button";
    button.disabled = Boolean(loading || !viewState.afterAssessmentId || !candidate);
    button.setAttribute("aria-pressed", String(viewState.intent === interval));
    button.title = loading
      ? `${label} comparison is resolving against the latest assessment.`
      : candidate
        ? `Compare against the latest assessment at least ${duration} before the latest After.`
        : unavailable;
    button.setAttribute("aria-label", button.disabled && !loading ? unavailable
      : `Compare with the latest assessment at least ${duration} before the latest After`);
    if (!loading && !candidate) statusMessages.push(unavailable);
    button.addEventListener("click", () => {
      if (!button.disabled) actions.preset?.(interval);
    });
  });
  const custom = appendText(group, "button", "Custom");
  custom.type = "button";
  custom.setAttribute("aria-pressed", String(viewState.intent === "custom"));
  custom.setAttribute("aria-expanded", String(viewState.customOpen === true));
  custom.setAttribute("aria-controls", "health-comparison-custom-controls");
  custom.addEventListener("click", () => actions.customOpen?.(viewState.customOpen !== true));
  if (loading) statusMessages.push("Resolving the selected interval against the latest assessment.");
  if (viewState.presetError) statusMessages.push(viewState.presetError);
  liveStatus.textContent = statusMessages.join(" ");
}

function formatElapsedInterval(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "unknown";
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  const parts = [];
  if (days) parts.push(`${days} ${days === 1 ? "day" : "days"}`);
  if (hours) parts.push(`${hours} ${hours === 1 ? "hour" : "hours"}`);
  if (minutes || !parts.length) parts.push(`${minutes} ${minutes === 1 ? "minute" : "minutes"}`);
  return parts.join(" ");
}

function formatComparisonCount(value) {
  return new Intl.NumberFormat().format(value);
}

function appendComparisonRowPagination(container, comparison, loading, actions) {
  const pageCount = Math.ceil(comparison.filteredItemCount / comparison.limit);
  if (pageCount < 1) return;
  const currentPage = Math.floor(comparison.offset / comparison.limit) + 1;
  const navigation = appendText(container, "nav", "", "health-comparison-row-pagination");
  navigation.setAttribute("aria-label", "Comparison result pages");
  const appendPageButton = (label, action, offset, disabled) => {
    const button = appendText(navigation, "button", label);
    button.type = "button";
    button.disabled = loading || disabled;
    button.setAttribute("data-comparison-page-action", action);
    button.addEventListener("click", () => actions.items?.(offset, action));
    return button;
  };
  appendPageButton("First", "first", 0, currentPage === 1);
  appendPageButton("Previous", "previous", Math.max(0, comparison.offset - comparison.limit),
    currentPage === 1);
  const pagePicker = document.createElement("select");
  pagePicker.setAttribute("aria-label", "Comparison result page");
  pagePicker.setAttribute("data-comparison-page-action", "page");
  for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
    const option = document.createElement("option");
    option.value = String(pageNumber);
    option.textContent = `Page ${formatComparisonCount(pageNumber)} of ${formatComparisonCount(pageCount)}`;
    pagePicker.appendChild(option);
  }
  pagePicker.value = String(currentPage);
  pagePicker.disabled = loading || pageCount === 1;
  pagePicker.addEventListener("change", () => {
    const selectedPage = Number(pagePicker.value);
    if (Number.isInteger(selectedPage) && selectedPage >= 1 && selectedPage <= pageCount) {
      actions.items?.((selectedPage - 1) * comparison.limit, "page");
    }
  });
  navigation.appendChild(pagePicker);
  appendPageButton("Next", "next", comparison.offset + comparison.limit,
    currentPage >= pageCount);
  appendPageButton("Last", "last", (pageCount - 1) * comparison.limit,
    currentPage >= pageCount);
}

export function renderHealthComparison(container, page, comparison, viewState = {}, actions = {}) {
  if (!container) return;
  const focusedDisclosureId = document.activeElement?.getAttribute?.("aria-controls");
  const focusedPageAction = document.activeElement?.getAttribute?.("data-comparison-page-action");
  const appendError = (message) => {
    const error = appendText(container, "p", message, "error");
    error.setAttribute("role", "alert");
    return error;
  };
  const appendRetry = (retryAction = actions.retry) => {
    const retry = appendText(container, "button", "Retry comparison read");
    retry.type = "button";
    retry.addEventListener("click", () => retryAction?.());
  };
  const restoreDisclosureFocus = () => {
    if (!container.querySelectorAll) return;
    if (focusedDisclosureId) {
      const replacement = Array.from(container.querySelectorAll("button[aria-controls]"))
        .find((button) => button.getAttribute("aria-controls") === focusedDisclosureId);
      replacement?.focus?.({ preventScroll: true });
    }
    if (viewState.focusTarget) {
      const pageControls = Array.from(container.querySelectorAll("[data-comparison-page-action]"));
      const replacement = pageControls.find(
        (control) => control.getAttribute("data-comparison-page-action") === viewState.focusTarget,
      );
      const focusTarget = replacement && !replacement.disabled
        ? replacement
        : pageControls.find((control) => control.getAttribute("data-comparison-page-action") === "page"
          && !control.disabled);
      focusTarget?.focus?.({ preventScroll: true });
      if (focusTarget) actions.focusRestored?.();
    } else if (focusedPageAction) {
      const pageControls = Array.from(container.querySelectorAll("[data-comparison-page-action]"));
      const replacement = pageControls.find(
        (control) => control.getAttribute("data-comparison-page-action") === focusedPageAction,
      );
      replacement?.focus?.({ preventScroll: true });
    }
  };
  const endpointSelection = viewState.endpointSelection === true;
  if (viewState.supportLoading) {
    container.replaceChildren();
    const status = appendText(container, "p", "Loading comparison availability…");
    status.setAttribute("role", "status");
    restoreDisclosureFocus();
    return;
  }
  if (viewState.assessmentError && !viewState.assessmentAvailable) {
    container.replaceChildren();
    appendError(`The selected assessment is unavailable: ${viewState.assessmentError}`);
    appendRetry();
    restoreDisclosureFocus();
    return;
  }
  if (viewState.supportError || viewState.capabilityKnown === false) {
    container.replaceChildren();
    appendError(viewState.supportError
      ? `Comparison availability could not be loaded: ${viewState.supportError}`
      : "Comparison availability could not be determined.");
    appendRetry();
    restoreDisclosureFocus();
    return;
  }
  if (viewState.capabilityKnown === true && !viewState.comparisonReadModel) {
    container.replaceChildren();
    const status = appendText(
      container,
      "p",
      "Comparison is unavailable because this health service does not support comparison reads.",
    );
    status.setAttribute("role", "status");
    restoreDisclosureFocus();
    return;
  }
  const liveStatusClass = "visually-hidden health-comparison-shortcut-status";
  let liveStatus = endpointSelection
    ? Array.from(container.children).find((child) => child.className === liveStatusClass)
    : null;
  if (liveStatus) {
    Array.from(container.children).forEach((child) => {
      if (child !== liveStatus) child.remove();
    });
  } else if (endpointSelection) {
    container.replaceChildren();
    liveStatus = document.createElement("span");
    liveStatus.className = liveStatusClass;
    liveStatus.setAttribute("role", "status");
    liveStatus.setAttribute("aria-live", "polite");
    liveStatus.setAttribute("aria-atomic", "true");
    container.appendChild(liveStatus);
  } else {
    container.replaceChildren();
  }
  if (liveStatus) liveStatus.textContent = "";
  if (endpointSelection && viewState.listLoading
      && !viewState.endpointPages?.after && !viewState.endpointPages?.before) {
    liveStatus.textContent = "Loading retained assessments.";
    appendText(container, "p", "Loading retained assessments…").setAttribute("role", "status");
    restoreDisclosureFocus();
    return;
  }
  if (!endpointSelection && viewState.listLoading && !page) {
    appendText(container, "p", "Loading stored comparisons…").setAttribute("role", "status");
    restoreDisclosureFocus();
    return;
  }
  if (!endpointSelection && viewState.listError && !page) {
    appendError(`Comparison read failed: ${viewState.listError}`);
    appendRetry();
    restoreDisclosureFocus();
    return;
  }
  if (!endpointSelection && (!page || !Array.isArray(page.items))) {
    appendError("Stored comparison history is unavailable.");
    appendRetry();
    restoreDisclosureFocus();
    return;
  }
  if (!endpointSelection && viewState.listError) {
    appendError(`Comparison read failed: ${viewState.listError}`);
    appendRetry();
  }
  if (!endpointSelection && !page.total) {
    const status = appendText(container, "p", "Not enough retained history for a comparison yet.");
    status.setAttribute("role", "status");
    restoreDisclosureFocus();
    return;
  }
  const selectedComparisonId = endpointSelection
    ? comparison?.comparisonId || ""
    : viewState.comparisonId || comparison?.comparisonId || "";
  const controls = appendText(container, "div", "", "health-comparison-controls");
  if (endpointSelection) {
    appendComparisonPresets(controls, viewState, actions, liveStatus);
    const customControls = appendText(container, "div", "", "health-comparison-custom");
    customControls.id = "health-comparison-custom-controls";
    customControls.hidden = viewState.customOpen !== true;
    if (!customControls.hidden) {
      for (const side of ["before", "after"]) {
        const endpointGroup = appendText(customControls, "div", "", "health-comparison-endpoint-group");
        appendEndpointPicker(endpointGroup, side, viewState.endpointPages?.[side],
          viewState[`${side}AssessmentId`], viewState[side],
          viewState.endpointLoading?.[side], actions);
        appendEndpointHistoryNavigation(endpointGroup, side, viewState.endpointPages?.[side],
          viewState.endpointLoading?.[side], actions);
      }
    }
  } else {
    const picker = document.createElement("select");
    picker.setAttribute("aria-label", "Stored comparison");
    const now = Date.now();
    const comparisonLabel = (item) => `Before: ${formatComparisonTime(item.beforeObservedAt, now)} · After: ${formatComparisonTime(item.afterObservedAt, now)}`;
    const prompt = document.createElement("option");
    prompt.value = "";
    prompt.textContent = "Select a comparison";
    picker.appendChild(prompt);
    page.items.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.comparisonId;
      option.textContent = comparisonLabel(item);
      picker.appendChild(option);
    });
    if (selectedComparisonId && !page.items.some((item) => item.comparisonId === selectedComparisonId)) {
      const pinned = document.createElement("option");
      pinned.value = selectedComparisonId;
      const selectedComparison = comparison?.comparisonId === selectedComparisonId ? comparison : null;
      pinned.textContent = selectedComparison
        ? `${comparisonLabel(selectedComparison)} (selected)`
        : `${selectedComparisonId} (selected)`;
      picker.appendChild(pinned);
    }
    picker.value = selectedComparisonId;
    picker.addEventListener("change", () => actions.select?.(picker.value));
    controls.appendChild(picker);
  }
  if (endpointSelection) {
    if (viewState.endpointErrors?.before) {
      appendError(`Before assessment history read failed: ${viewState.endpointErrors.before}`);
      appendRetry();
    }
    if (viewState.endpointErrors?.after) {
      appendError(`After assessment history read failed: ${viewState.endpointErrors.after}`);
      appendRetry();
    }
    if (viewState.presetError) {
      appendError(`Comparison preset read failed: ${viewState.presetError}`);
      appendRetry();
    }
    if (viewState.endpointUnavailable) {
      const status = appendText(
        container,
        "p",
        "A selected assessment is no longer retained. Select new endpoints.",
        "health-comparison-endpoint-unavailable",
      );
      status.setAttribute("role", "status");
    } else if (viewState.endpointPages?.after?.total === 0) {
      const status = appendText(
        container, "p",
        "Not enough history: no retained assessments are available for this network and dataset.",
      );
      status.setAttribute("role", "status");
    } else if (viewState.presetLoading) {
      appendText(container, "p", "Resolving the latest retained After assessment…")
        .setAttribute("role", "status");
    } else if (!viewState.afterAssessmentId) {
      if (!viewState.presetError && !viewState.listLoading) {
        const status = appendText(container, "p", "Not enough history: no retained After assessment is available.");
        status.setAttribute("role", "status");
      }
    } else if (!viewState.beforeAssessmentId) {
      const status = appendText(
        container, "p",
        "Not enough history for the selected interval. Open Custom to choose retained endpoints.",
      );
      status.setAttribute("role", "status");
    }
  } else {
    const nav = appendText(container, "div", "", "health-comparison-navigation");
    const previous = appendText(nav, "button", "Previous pairs");
    previous.type = "button";
    previous.disabled = page.offset === 0;
    previous.addEventListener("click", () => actions.page?.(Math.max(0, page.offset - page.limit)));
    const next = appendText(nav, "button", "Next pairs");
    next.type = "button";
    next.disabled = page.offset + page.items.length >= page.total;
    next.addEventListener("click", () => actions.page?.(page.offset + page.limit));
  }
  if (viewState.endpointPairLoading || viewState.detailLoading) {
    appendText(container, "p", "Loading comparison rows…").setAttribute("role", "status");
    restoreDisclosureFocus();
    return;
  }
  if (viewState.endpointPairError || viewState.detailError) {
    appendError(`Comparison rows could not be loaded: ${viewState.endpointPairError || viewState.detailError}`);
    appendRetry(endpointSelection ? actions.retry : actions.retryDetail);
    restoreDisclosureFocus();
    return;
  }
  if (!comparison || (!endpointSelection && comparison.comparisonId !== selectedComparisonId)) {
    restoreDisclosureFocus();
    return;
  }
  if (endpointSelection && (
    comparison.beforeAssessmentId !== viewState.beforeAssessmentId
    || comparison.afterAssessmentId !== viewState.afterAssessmentId
  )) {
    restoreDisclosureFocus();
    return;
  }
  const heading = appendText(container, "p",
    `Before ${formatUtcComparisonTimestamp(comparison.beforeObservedAt)}`
    + ` → After ${formatUtcComparisonTimestamp(comparison.afterObservedAt)} UTC`
    + ` · ${formatElapsedInterval(comparison.elapsedSeconds)}`,
    "health-comparison-pair-summary");
  heading.title = `Before ${comparison.beforeObservedAt} · After ${comparison.afterObservedAt}`;
  const status = appendText(container, "p", comparison.comparable ? "Comparable" : "Unknown",
    "health-comparison-primary-status");
  status.setAttribute("role", "status");
  if (comparison.resetState === "unknown") {
    appendText(container, "p", "Reset status unknown.", "health-comparison-caveat");
  }
  if (!comparison.comparable && comparison.reasons?.length) {
    appendText(container, "p", comparison.reasons.join(", "), "health-comparison-caveat");
  }
  const detailsToggle = appendText(container, "button", "Details");
  detailsToggle.type = "button";
  detailsToggle.setAttribute("aria-expanded", String(viewState.detailsOpen === true));
  detailsToggle.setAttribute("aria-controls", "health-comparison-details");
  detailsToggle.addEventListener("click", () => actions.detailsOpen?.(viewState.detailsOpen !== true));
  const details = appendText(container, "div", "", "health-comparison-details");
  details.id = "health-comparison-details";
  details.hidden = viewState.detailsOpen !== true;
  if (!details.hidden) {
    appendText(details, "p", `Baseline: ${comparison.baselineState} · Gap: ${comparison.gapState || "unknown"} · Reset: ${comparison.resetState}`);
    appendText(details, "p", `Reasons: ${comparison.reasons?.join(", ") || "none"}`);
    appendText(details, "p", `Before observed ${comparison.beforeObservedAt} · After observed ${comparison.afterObservedAt}`);
    appendText(
      details,
      "p",
      `Endpoint revisions: Before ${comparison.beforeEndpointRevisionState || "unknown"} · After ${comparison.afterEndpointRevisionState || "unknown"}`,
    );
    [
      ["Before", comparison.beforeEndpointEvaluationContext],
      ["After", comparison.afterEndpointEvaluationContext],
    ].forEach(([label, context]) => {
      if (!context) return;
      const unavailable = Array.isArray(context.unavailableEvaluationDomains)
        ? context.unavailableEvaluationDomains.join(", ")
        : "";
      const roster = context.historicalRosterRevision === null
        || context.historicalRosterRevision === undefined
        ? "roster revision unavailable"
        : `roster revision ${context.historicalRosterRevision}`;
      appendText(
        details,
        "p",
        `${label} context: ${unavailable ? `unavailable inputs ${unavailable}; ` : ""}${roster}`,
        "health-comparison-context",
      );
    });
    if (comparison.origin === "derived") {
      appendText(details, "p", "Derived from retained endpoint evidence; not stored.",
        "health-comparison-origin");
    }
  }
  const filterRow = appendText(container, "div", "", "health-comparison-filter-row");
  const filter = document.createElement("select");
  filter.setAttribute("aria-label", "Comparison scope");
  ["all", "network", "device", "relationship"].forEach((scope) => {
    const option = document.createElement("option");
    option.value = scope;
    option.textContent = scope === "all" ? "All scopes" : scope;
    filter.appendChild(option);
  });
  filter.value = viewState.scope || "all";
  filter.addEventListener("change", () => actions.scope?.(filter.value));
  filterRow.appendChild(filter);
  const resultFilter = document.createElement("select");
  resultFilter.setAttribute("aria-label", "Result");
  [
    ["changed", "Changed"],
    ["unchanged", "Unchanged"],
    ["unknown", "Unknown"],
    ["all", "All results"],
  ].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    resultFilter.appendChild(option);
  });
  resultFilter.value = viewState.result || "changed";
  resultFilter.disabled = endpointSelection
    ? !viewState.beforeAssessmentId || !viewState.afterAssessmentId
    : !selectedComparisonId;
  resultFilter.addEventListener("change", () => actions.result?.(resultFilter.value));
  filterRow.appendChild(resultFilter);
  const count = appendText(
    filterRow, "span",
    comparison.filteredItemCount === 0
      ? "0 matching rows"
      : comparison.items.length
        ? `${formatComparisonCount(comparison.offset + 1)}–${formatComparisonCount(comparison.offset + comparison.items.length)} of ${formatComparisonCount(comparison.filteredItemCount)} matching rows`
        : `No rows on this page · ${formatComparisonCount(comparison.filteredItemCount)} matching rows`,
    "health-comparison-row-count",
  );
  count.setAttribute("role", "status");
  count.setAttribute("aria-live", "polite");
  appendText(
    filterRow, "span",
    `${formatComparisonCount(comparison.itemCount)} total rows`,
    "health-comparison-total-count",
  );
  if (!comparison.items?.length) {
    appendText(container, "p", "No rows match the selected comparison filters.");
  } else {
    const wrap = appendText(container, "div", "", "health-comparison-table-wrap");
    const table = document.createElement("table");
    const header = document.createElement("tr");
    ["Subject", "Evidence", "Before", "After", "Delta", "Result", "Source / reset"].forEach((label) => appendText(header, "th", label));
    const head = document.createElement("thead");
    head.appendChild(header);
    table.appendChild(head);
    const body = document.createElement("tbody");
    comparison.items.forEach((item) => {
        const row = document.createElement("tr");
        const format = (value) => value == null ? "Unknown" : typeof value === "string" ? value : JSON.stringify(value);
        const subject = appendText(row, "td", item.subjectId);
        if (item.scope === "device" && actions.canInspect?.(item.subjectId)) {
          const inspect = appendText(subject, "button", "Show in table");
          inspect.type = "button";
          inspect.setAttribute("aria-label", `Show ${item.subjectId} in table`);
          inspect.dataset.healthFocusKey = `comparison-device:${item.subjectId}`;
          inspect.addEventListener("click", () => actions.inspect?.(item.subjectId));
        }
        appendText(row, "td", `${item.metric || item.itemKind} · ${item.sampleCount} ${item.sampleCount === 1 ? "sample" : "samples"}`);
        appendText(row, "td", format(item.beforeValue));
        appendText(row, "td", format(item.afterValue));
        appendText(row, "td", item.delta == null ? "—" : `${item.delta} ${item.unit || ""}`);
        appendText(row, "td", item.comparable ? `${item.change}${item.direction ? ` · ${item.direction}` : ""}` : `Unknown · ${item.primaryReason || "unqualified"}`);
        appendText(row, "td", `${item.sourceFiles?.join(", ") || "Unknown"} · ${item.resetState}`);
        body.appendChild(row);
      });
    table.appendChild(body);
    wrap.appendChild(table);
  }
  appendText(container, "span", `${comparison.limit} rows per page`, "health-comparison-page-size");
  appendComparisonRowPagination(
    container, comparison, viewState.itemsLoading === true, actions,
  );
  restoreDisclosureFocus();
}

const ROSTER_COLUMNS = [
  ["label", "Device"], ["presence", "Presence"], ["rosterState", "Roster designation"],
  ["lastObserved", "Last observed"], ["quality", "Data quality"],
];

function rosterLabel(value) {
  return value?.replaceAll("-", " ").replace(/^./, (letter) => letter.toUpperCase()) || "Unknown";
}

export function renderHealthRoster(container, page, view, actions = {}) {
  if (!container) return;
  container.replaceChildren();
  if (view.loading && !page) {
    appendText(container, "p", "Loading device roster…");
    return;
  }
  if (view.error) appendText(container, "p", `Device roster unavailable: ${view.error}`, "error");
  if (!page) return;
  appendText(container, "p", `${page.filteredTotal} of ${page.total} devices · ${page.devices.length
    ? `${page.offset + 1}–${page.offset + page.devices.length}` : "no rows on this page"}`,
  "health-roster-results");
  if (!page.activeExpectedTotal) appendText(container, "p", "No active expected roster is configured.");
  if (!page.filteredTotal) {
    appendText(container, "p", view.presence === "observed" && view.rosterState === "all" && !view.search
      ? "No devices were observed in this assessment; this does not establish network health."
      : "No devices match these roster filters.");
    return;
  }
  const wrap = appendText(container, "div", "", "health-roster-table-wrap");
  const table = document.createElement("table");
  const head = table.createTHead().insertRow();
  ROSTER_COLUMNS.forEach(([column, title]) => {
    const cell = document.createElement("th");
    cell.scope = "col";
    const button = appendText(cell, "button", title);
    button.type = "button";
    button.addEventListener("click", () => actions.sort?.(column));
    if (view.sort.column === column) {
      cell.setAttribute("aria-sort", view.sort.direction);
      appendText(button, "span", view.sort.direction === "ascending" ? " ▲" : " ▼", "health-sort-icon");
    }
    head.appendChild(cell);
  });
  const body = table.createTBody();
  page.devices.forEach((device) => {
    const row = body.insertRow();
    row.classList.toggle("selected", view.selectedDeviceId === device.deviceId);
    const deviceCell = row.insertCell();
    const button = appendText(deviceCell, "button", device.displayLabel);
    button.type = "button";
    button.dataset.deviceId = device.deviceId;
    button.title = device.deviceId;
    button.setAttribute("aria-label", `${device.displayLabel}, ${device.deviceId}, inspect device`);
    button.setAttribute("aria-expanded", String(view.selectedDeviceId === device.deviceId));
    button.addEventListener("click", () => actions.select?.(device.deviceId));
    appendText(deviceCell, "small", `${rosterLabel(device.presenceState)} · ${rosterLabel(device.rosterState)} · ${
      device.lastEndpointPresenceAt ? formatAge(device.lastEndpointPresenceAt) : "Never observed"}`,
    "health-roster-mobile-meta");
    appendText(row.insertCell(), "span", rosterLabel(device.presenceState));
    appendText(row.insertCell(), "span", rosterLabel(device.rosterState));
    appendText(row.insertCell(), "time", device.lastEndpointPresenceAt
      ? `${formatAge(device.lastEndpointPresenceAt)} · ${device.lastEndpointPresenceAt}` : "Unknown");
    const counts = device.fieldCounts;
    appendText(row.insertCell(), "span", `${counts.fresh} fresh · ${counts.stale} stale · ${counts.conflicted} conflicted`);
  });
  wrap.appendChild(table);
  const navigation = appendText(container, "div", "", "health-roster-navigation");
  const previous = appendText(navigation, "button", "Previous");
  previous.type = "button";
  previous.disabled = page.offset === 0;
  previous.addEventListener("click", () => actions.page?.(Math.max(0, page.offset - page.limit)));
  const next = appendText(navigation, "button", "Next");
  next.type = "button";
  next.disabled = page.offset + page.devices.length >= page.filteredTotal;
  next.addEventListener("click", () => actions.page?.(page.offset + page.limit));
}

const ROSTER_ACTION_LABELS = Object.freeze({
  enroll: "Add to Roster",
  "mark-offline": "Mark Offline",
  "clear-offline": "Clear Offline",
  retire: "Retire Device",
  unretire: "Unretire Device",
});

export function renderHealthRosterDetail(container, detail, presenceState, actions = {}) {
  if (!container) return;
  container.replaceChildren();
  if (!detail) return;
  const heading = appendText(container, "h3", detail.displayLabel);
  heading.id = "health-roster-device-heading";
  heading.tabIndex = -1;
  appendText(container, "p", detail.deviceId, "health-roster-identity");
  const copy = appendText(container, "button", "Copy ID");
  copy.type = "button";
  copy.addEventListener("click", () => navigator.clipboard.writeText(detail.deviceId));
  appendText(container, "p", `Presence in selected assessment: ${
    rosterLabel(detail.presenceState || presenceState)
  }`);
  appendText(container, "p", `Current roster designation: ${rosterLabel(detail.rosterState)}`);
  appendText(container, "p", `Last endpoint presence: ${detail.lastEndpointPresenceAt || "Unknown"}`);
  if (detail.reason) appendText(container, "p", `Reason: ${detail.reason}`);
  if (detail.updatedAt) appendText(container, "p", `Updated: ${detail.updatedAt}`);
  if (detail.expectedSince) appendText(container, "p", `Expected since: ${detail.expectedSince}`);
  if (detail.changeSource) appendText(container, "p", `Change origin: ${detail.changeSource}`);
  if (detail.lastLifecycleEvent) {
    appendText(container, "p", `Last action: ${rosterLabel(detail.lastLifecycleEvent.action)} · ${
      detail.lastLifecycleEvent.actor || detail.lastLifecycleEvent.origin
    } · ${detail.lastLifecycleEvent.occurred_at}`);
  }
  const actionBar = appendText(container, "div", "", "health-roster-action-bar");
  if (actions.mutationAvailable) {
    for (const action of detail.allowedActions || []) {
      const button = appendText(actionBar, "button", ROSTER_ACTION_LABELS[action] || action);
      button.type = "button";
      button.disabled = actions.pending === true;
      button.addEventListener("click", () => actions.action?.(action, detail));
    }
  }
  const unavailableReason = detail.disabledActionReasons?.enroll;
  if (unavailableReason) {
    appendText(container, "p", unavailableReason === "observation-context-required"
      ? "Add to Roster requires a retained assessment context."
      : unavailableReason === "device-not-present-in-context"
        ? "Add to Roster is available only for a device observed in this assessment."
        : "Add to Roster is unavailable in the current context.",
    "health-roster-action-note");
  }
  const table = document.createElement("table");
  const body = table.createTBody();
  Object.entries(detail.fields).forEach(([field, fact]) => {
    const row = body.insertRow();
    const heading = document.createElement("th");
    heading.scope = "row";
    heading.textContent = field;
    row.appendChild(heading);
    appendText(row.insertCell(), "span", fact.freshness === "absent" ? "Absent"
      : `${JSON.stringify(fact.value)} · ${fact.freshness} · ${fact.confidence} · ${fact.sourceFile || "unknown source"}`);
  });
  container.appendChild(table);
}

export async function fetchHealthSupport(networkId, signal) {
  const query = new URLSearchParams({ network: networkId, limit: "5", offset: "0" });
  const [capabilities, observations] = await Promise.all([
    healthRequest("api/health/capabilities", signal),
    healthRequest(`api/health/observations?${query}`, signal),
  ]);
  return { capabilities, observations };
}

export function formatAge(timestamp, parsedTimestamp = Date.parse(timestamp)) {
  if (!Number.isFinite(parsedTimestamp)) return "unknown";
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - parsedTimestamp) / 1000));
  if (elapsedSeconds < 60) return "just now";
  const units = [
    [86400, "day"],
    [3600, "hour"],
    [60, "minute"],
  ];
  const [seconds, label] = units.find(([unitSeconds]) => elapsedSeconds >= unitSeconds);
  const value = Math.floor(elapsedSeconds / seconds);
  return `${value} ${label}${value === 1 ? "" : "s"} ago`;
}

export function renderHealthStatus(container, model) {
  if (!container) return;
  container.replaceChildren();
  const isRefreshing = ["running", "cancelling"].includes(model.refreshStatus);
  const isAvailable = isRefreshing || model.loading || (!model.error && Boolean(model.assessment));
  container.toggleAttribute("hidden", !isAvailable);
  if (!isAvailable) return;
  if (isRefreshing) {
    appendText(container, "span", "Health: refreshing", "health-status-state is-loading");
    return;
  }
  if (model.refreshStatus === "cancelled") {
    appendText(container, "span", "Health: cancelled", "health-status-state");
    return;
  }
  if (model.refreshStatus === "error") {
    appendText(container, "span", "Health: failed", "health-status-state state-poor");
    appendText(container, "span", model.refreshDetail, "health-status-detail");
    return;
  }
  if (model.loading) {
    appendText(container, "span", "Health: loading", "health-status-state is-loading");
    return;
  }

  const assessment = model.assessment;
  const status = typeof assessment.status === "string" ? assessment.status.trim() : "";
  if (!status) {
    appendText(container, "span", "Health: unavailable", "health-status-state");
    return;
  }
  appendText(container, "span", "Health:", "health-status-label");
  appendText(
    container,
    "span",
    status,
    `health-status-state state-${status.toLowerCase()}`,
  );
  appendText(container, "span", assessment.completeness, "health-status-detail");
  const displayedAt = model.refreshedAt ?? assessment.observedAt;
  const parsedDisplayedAt = Date.parse(displayedAt);
  const time = appendText(container, "time", formatAge(displayedAt, parsedDisplayedAt), "health-status-detail");
  if (Number.isFinite(parsedDisplayedAt)) {
    time.dateTime = displayedAt;
    const observedAt = Date.parse(assessment.observedAt);
    time.title = model.refreshedAt && Number.isFinite(observedAt)
      ? `Health processed: ${new Date(parsedDisplayedAt).toLocaleString()}; assessment observed: ${new Date(observedAt).toLocaleString()}`
      : new Date(parsedDisplayedAt).toLocaleString();
  }
}

export function findingMatches(group, filters) {
  const effectiveScope = group.scope === "observation" ? "network" : group.scope;
  return (filters.status === "all" || group.status === filters.status) &&
    (filters.scope === "all" || effectiveScope === filters.scope) &&
    (filters.evidenceKind === "all" || group.findings.some(
      (finding) => finding.evidenceKind === filters.evidenceKind,
    ));
}

function uniqueValues(values) {
  return [...new Set(values.filter((value) => value !== null && value !== undefined && value !== ""))];
}

function boundedValueLabel(values) {
  if (values.length === 0) return "Not specified";
  if (values.length === 1) return values[0];
  return "Mixed";
}

function projectAffected(group) {
  if (group.scope === "relationship") {
    const count = uniqueValues(group.relationshipIds || []).length;
    if (count > 0) return { kind: "relationship", count, label: `${count} relationship${count === 1 ? "" : "s"}` };
  }
  if (group.scope === "device") {
    const count = uniqueValues(group.deviceIds || []).length;
    if (count > 0) return { kind: "device", count, label: `${count} device${count === 1 ? "" : "s"}` };
  }
  if (group.scope === "network") return { kind: "network", count: 1, label: "Network" };
  if (group.scope === "observation") return { kind: "observation", count: 1, label: "Observation" };
  const count = Number.isInteger(group.count) ? group.count : (group.findings || []).length;
  return { kind: "finding", count, label: `${count} finding${count === 1 ? "" : "s"}` };
}

function compareText(left, right) {
  return String(left ?? "").localeCompare(String(right ?? ""), undefined, { sensitivity: "base" });
}

function compareNumber(left, right) {
  return Number(left ?? 0) - Number(right ?? 0);
}

function comparePriority(left, right) {
  return compareNumber(HEALTH_STATUS_ORDER[left.status] ?? 99, HEALTH_STATUS_ORDER[right.status] ?? 99)
    || compareNumber(
      Math.min(...left.materialities.map((value) => HEALTH_MATERIALITY_ORDER[value] ?? 99), 99),
      Math.min(...right.materialities.map((value) => HEALTH_MATERIALITY_ORDER[value] ?? 99), 99),
    )
    || compareNumber(right.affected.count, left.affected.count);
}

export function compareHealthSummaryRows(left, right, sort = {}) {
  const column = sort.column ?? "priority";
  const direction = sort.direction === "descending" ? -1 : 1;
  let primary = 0;
  if (column === "priority") primary = comparePriority(left, right);
  else if (column === "status") {
    primary = compareNumber(HEALTH_STATUS_ORDER[left.status] ?? 99, HEALTH_STATUS_ORDER[right.status] ?? 99);
  } else if (column === "affected") primary = compareNumber(left.affected.count, right.affected.count);
  else if (column === "confidence") {
    primary = compareNumber(
      HEALTH_CONFIDENCE_ORDER[left.confidence] ?? 99,
      HEALTH_CONFIDENCE_ORDER[right.confidence] ?? 99,
    );
  } else if (column === "materiality") {
    primary = compareNumber(
      Math.min(...left.materialities.map((value) => HEALTH_MATERIALITY_ORDER[value] ?? 99), 99),
      Math.min(...right.materialities.map((value) => HEALTH_MATERIALITY_ORDER[value] ?? 99), 99),
    );
  } else if (column === "evidence") primary = compareText(left.evidenceLabel, right.evidenceLabel);
  else primary = compareText(left[column], right[column]);
  return (primary * direction)
    || compareNumber(left.catalogOrder, right.catalogOrder)
    || compareText(left.groupId, right.groupId);
}

export function projectVisibleHealthFindingGroups(groups) {
  return (groups || []).filter(
    ({ ruleId }) => !HEALTH_PRESENTATION_POLICY.suppressedRuleIds.has(ruleId),
  );
}

export function projectHealthSummaryRows(groups, options = {}) {
  const filters = {
    status: options.filters?.status ?? "all",
    scope: options.filters?.scope ?? "all",
    evidenceKind: options.filters?.evidenceKind ?? "all",
  };
  const view = options.view ?? "actionable";
  const rows = projectVisibleHealthFindingGroups(groups).map((group, catalogOrder) => {
    const findings = group.findings || [];
    const evidenceKinds = uniqueValues(findings.map((finding) => finding.evidenceKind));
    const materialities = uniqueValues(findings.map((finding) => finding.materiality));
    return {
      groupId: group.groupId,
      ruleId: group.ruleId,
      presentationVariant: group.presentationVariant ?? null,
      status: group.status,
      title: group.title,
      summary: findingSummary(group),
      scope: group.scope,
      confidence: group.confidence,
      evidenceKinds,
      evidenceLabel: boundedValueLabel(evidenceKinds),
      materialities,
      materialityLabel: boundedValueLabel(materialities),
      affected: projectAffected(group),
      rank: Math.max(...findings.map((finding) => Number(finding.rank) || 0), 0),
      catalogOrder,
      group,
    };
  }).filter((row) => {
    const inView = view === "all"
      || (view === "actionable" && ["poor", "moderate", "unknown"].includes(row.status))
      || (view === "going-well" && row.status === "strong");
    return inView && findingMatches(row.group, filters);
  });
  return rows.sort((left, right) => compareHealthSummaryRows(left, right, options.sort));
}

function sharedFindingValue(findings, key) {
  const values = uniqueValues(findings.map((finding) => finding[key]));
  return values.length === 1 ? values[0] : null;
}

export function projectHealthFindingDetail(group, selectedFindingId = null, selectedEndpointId = null) {
  if (!projectVisibleHealthFindingGroups([group]).length) return null;
  const findings = group.findings || [];
  const row = projectHealthSummaryRows([group], { view: "all" })[0];
  const summary = findingSummary(group);
  const findingSummaryCounts = new Map();
  findings.forEach((finding) => {
    const findingSummaryText = typeof finding.summary === "string" ? finding.summary.trim() : "";
    if (findingSummaryText) {
      findingSummaryCounts.set(findingSummaryText, (findingSummaryCounts.get(findingSummaryText) || 0) + 1);
    }
  });
  const deviceFindingCounts = new Map();
  findings.forEach((finding) => {
    uniqueValues([
      ...(finding.deviceIds || []),
      ...(finding.endpoints || []).map(({ deviceId }) => deviceId),
    ]).forEach((deviceId) => {
      deviceFindingCounts.set(deviceId, (deviceFindingCounts.get(deviceId) || 0) + 1);
    });
  });
  const affectedDeviceIds = new Set(findings.flatMap((finding) => [
    ...(finding.deviceIds || []),
    ...(finding.endpoints || []).map(({ deviceId }) => deviceId),
  ]));
  const relatedDevices = new Map();
  const relatedDeviceIds = new Set();
  findings.forEach((finding) => {
    (finding.routerEndpoints || []).forEach((endpoint) => {
      relatedDevices.set(`${finding.findingId}\n${endpoint.deviceId}`, {
        ...endpoint,
        findingId: finding.findingId,
        association: "Router path evidence",
        summary: finding.summary,
      });
      relatedDeviceIds.add(endpoint.deviceId);
    });
  });
  (group.endpoints || []).forEach((endpoint) => {
    if (!affectedDeviceIds.has(endpoint.deviceId) && !relatedDeviceIds.has(endpoint.deviceId)) {
      relatedDevices.set(`\n${endpoint.deviceId}`, {
        ...endpoint,
        findingId: null,
        association: "Group endpoint",
        summary: group.summary,
      });
      relatedDeviceIds.add(endpoint.deviceId);
    }
  });
  return {
    groupId: group.groupId,
    heading: group.title,
    status: group.status,
    summary,
    scope: group.scope,
    confidence: group.confidence,
    evidenceLabel: row.evidenceLabel,
    materialityLabel: row.materialityLabel,
    affected: row.affected,
    shared: {
      whyItMatters: sharedFindingValue(findings, "whyItMatters"),
      action: sharedFindingValue(findings, "action"),
      verify: sharedFindingValue(findings, "verify"),
      sourceFiles: uniqueValues(findings.flatMap((finding) => finding.sourceFiles || [])).sort(),
    },
    relatedDevices: [...relatedDevices.values()],
    items: findings.flatMap((finding) => {
      const findingSummaryText = typeof finding.summary === "string" ? finding.summary.trim() : "";
      const endpointsById = new Map((finding.endpoints || []).map((endpoint) => [
        endpoint.deviceId, endpoint,
      ]));
      const endpointIds = uniqueValues([
        ...(finding.deviceIds || []),
        ...(finding.endpoints || []).map(({ deviceId }) => deviceId),
      ].filter((deviceId) => typeof deviceId === "string" && deviceId));
      const endpointEntries = endpointIds.map((deviceId) => {
        const endpoint = endpointsById.get(deviceId);
        return {
          findingId: finding.findingId,
          endpointId: deviceId,
          label: endpoint?.displayName || deviceId.replace(/^extaddr:/, ""),
          identityLabel: deviceId.replace(/^extaddr:/, ""),
          findingContext: endpointIds.length > 1 || (deviceFindingCounts.get(deviceId) || 0) > 1
            ? findingSummaryText
            : null,
          highlightSummary: findingSummaryText
            && findingSummaryText !== summary
            && findingSummaryCounts.get(findingSummaryText) === 1
            ? findingSummaryText
            : null,
          endpointIds: [deviceId],
          relationshipIds: [...(finding.relationshipIds || [])],
          evidenceRows: Object.entries(finding.evidence || {})
            .filter(([key]) => !["evidenceKind", "materiality", "presentationVariant"].includes(key)),
          isExpanded: finding.findingId === selectedFindingId
            && (selectedEndpointId === deviceId || (!selectedEndpointId && endpointIds.length === 1)),
          finding,
        };
      });
      if (endpointEntries.length > 0) return endpointEntries;
      return [{
        findingId: finding.findingId,
        endpointId: null,
        label: findingSummaryText,
        identityLabel: "",
        highlightSummary: null,
        endpointIds: [],
        relationshipIds: [...(finding.relationshipIds || [])],
        evidenceRows: Object.entries(finding.evidence || {})
          .filter(([key]) => !["evidenceKind", "materiality", "presentationVariant"].includes(key)),
        isExpanded: finding.findingId === selectedFindingId && !selectedEndpointId,
        finding,
      }];
    }),
  };
}

export function toggleHealthFindingSelection(selectedFindingId, findingId) {
  return selectedFindingId === findingId ? null : findingId;
}

export function toggleHealthFindingEndpointSelection(
  selectedFindingId, selectedEndpointId, findingId, endpointId,
) {
  if (selectedFindingId === findingId && selectedEndpointId === endpointId) {
    return { findingId: null, endpointId: null };
  }
  return { findingId, endpointId };
}

export function reconcileHealthInsightsSelection(viewState, assessment) {
  const next = { ...viewState, assessmentId: assessment?.assessmentId ?? null };
  const group = projectVisibleHealthFindingGroups(assessment?.findingGroups).find(
    ({ groupId }) => groupId === viewState.selectedGroupId,
  );
  if (!group) {
    return {
      ...next, selectedGroupId: null, selectedFindingId: null, selectedEndpointId: null,
      detailsOpen: false,
    };
  }
  const selectedFinding = (group.findings || []).find(
    ({ findingId }) => findingId === viewState.selectedFindingId,
  );
  const selectedEndpointId = selectedFinding
    && uniqueValues([
      ...(selectedFinding.deviceIds || []),
      ...(selectedFinding.endpoints || []).map(({ deviceId }) => deviceId),
    ]).includes(viewState.selectedEndpointId)
    ? viewState.selectedEndpointId
    : null;
  return {
    ...next,
    selectedFindingId: selectedFinding ? viewState.selectedFindingId : null,
    selectedEndpointId,
  };
}

export function projectHealthFindingSections(groups, filters = {}) {
  const effectiveFilters = {
    status: filters.status ?? "all",
    scope: filters.scope ?? "all",
    evidenceKind: filters.evidenceKind ?? "all",
  };
  const matched = projectVisibleHealthFindingGroups(groups).filter(
    (group) => findingMatches(group, effectiveFilters),
  );
  return FINDING_SECTIONS.map((section) => ({
    ...section,
    groups: matched.filter((group) => section.statuses.has(group.status)),
  }));
}

function findingSummary(group) {
  if (group.ruleId !== "network.observed-link-quality-ratios") return group.summary;
  const evidence = group.findings[0]?.evidence;
  const lq3Ratio = evidence?.lq3Ratio;
  const lq1Ratio = evidence?.lq1Ratio;
  if (typeof lq3Ratio !== "number" || typeof lq1Ratio !== "number") return group.summary;
  const lq2Ratio = typeof evidence?.lq2Ratio === "number"
    ? evidence.lq2Ratio
    : Math.max(0, 1 - lq3Ratio - lq1Ratio);
  return `LQ3 is ${(lq3Ratio * 100).toFixed(1)}%; LQ2 is ${(lq2Ratio * 100).toFixed(1)}%; `
    + `LQ1 is ${(lq1Ratio * 100).toFixed(1)}% of observed links.`;
}

function numberedEndpointLabel({ deviceId, displayName }) {
  const canonicalAddress = deviceId.replace(/^extaddr:/, "");
  return displayName ? `${canonicalAddress} ${displayName}` : canonicalAddress;
}

function appendEndpointInspection(parent, endpoint, groupId, findingId, actions) {
  const row = document.createElement("li");
  appendText(row, "span", numberedEndpointLabel(endpoint));
  if (actions.canInspectDevice?.(endpoint.deviceId)) {
    const identity = endpoint.deviceId.replace(/^extaddr:/, "");
    appendDetailAction(row, "Inspect device", () => actions.inspectEndpoint?.(
      groupId, findingId, endpoint.deviceId,
    ), true, `Inspect ${endpoint.displayName || identity} (${identity})`);
  }
  parent.appendChild(row);
}

function appendRouterNames(details, group, actions) {
  const routers = group.findings.flatMap((finding) => finding.routerEndpoints || []);
  const uniqueRouters = [...new Map(routers.map((router) => [router.deviceId, router])).values()];
  appendText(details, "summary", `Show ${uniqueRouters.length} Router name${uniqueRouters.length === 1 ? "" : "s"}`);
  const names = document.createElement("ol");
  uniqueRouters.forEach((router) => appendEndpointInspection(
    names, router, group.groupId, null, actions,
  ));
  details.appendChild(names);
}

function appendRedundancyDevices(details, group, deviceType, actions) {
  appendText(
    details,
    "summary",
    `Show ${group.endpoints.length} ${deviceType}${group.endpoints.length === 1 ? "" : "s"}`,
  );
  const devices = document.createElement("ol");
  group.endpoints.forEach((endpoint) => appendEndpointInspection(
    devices, endpoint, group.groupId, null, actions,
  ));
  details.appendChild(devices);
}

function formatEvidenceValue(value) {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (Array.isArray(value)) return value.length > 0 ? value.join(", ") : "None observed";
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "Not observed");
}

function evidenceLabel(key) {
  return key.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/^./, (letter) => letter.toUpperCase());
}

function appendFindingEvidence(parent, finding) {
  appendText(parent, "p", finding.whyItMatters, "health-finding-impact");
  const metadata = document.createElement("dl");
  metadata.className = "health-finding-evidence";
  [
    ["Evidence kind", finding.evidenceKind],
    ["Materiality", finding.materiality],
    ["Confidence", finding.confidence],
  ].forEach(([label, value]) => {
    appendText(metadata, "dt", label);
    appendText(metadata, "dd", formatEvidenceValue(value));
  });
  Object.entries(finding.evidence || {})
    .filter(([key]) => !["evidenceKind", "materiality", "presentationVariant"].includes(key))
    .forEach(([key, value]) => {
      appendText(metadata, "dt", evidenceLabel(key));
      appendText(metadata, "dd", formatEvidenceValue(value));
    });
  parent.appendChild(metadata);
  appendText(parent, "p", `Action: ${finding.action}`, "health-finding-action-copy");
  appendText(parent, "p", `Verify: ${finding.verify}`, "health-finding-verify-copy");
  if (finding.sourceFiles?.length > 0) {
    appendText(parent, "p", `Sources: ${finding.sourceFiles.join(", ")}`, "health-finding-sources");
  }
}

function appendAttributedFindings(details, group, actions) {
  appendText(details, "summary", `Show ${group.count} attributed finding${group.count === 1 ? "" : "s"}`);
  const findings = document.createElement("ol");
  group.findings.forEach((finding) => {
    const child = document.createElement("li");
    if (finding.endpoints.length > 0) {
      const endpoints = document.createElement("ol");
      finding.endpoints.forEach((endpoint) => appendEndpointInspection(
        endpoints, endpoint, group.groupId, finding.findingId, actions,
      ));
      child.appendChild(endpoints);
      appendText(child, "span", finding.summary);
    } else {
      appendText(child, "strong", finding.summary);
    }
    appendFindingEvidence(child, finding);
    findings.appendChild(child);
  });
  details.appendChild(findings);
}

function appendFindingActions(item, group, actions) {
  const actionBar = document.createElement("div");
  actionBar.className = "health-finding-actions";
  const addAction = (label, action, enabled) => {
    if (!enabled) return;
    const button = appendText(actionBar, "button", label);
    button.type = "button";
    button.dataset.healthAction = action;
    button.title = label;
    button.addEventListener("click", () => actions[action]?.(group));
  };
  const availableTargets = actions.availableTargets?.(group) ?? group.deviceIds.length;
  const availableTopologyTargets = actions.availableTopologyTargets?.(group) ?? 0;
  addAction("Show in topology", "showTopology", availableTopologyTargets > 0);
  addAction("Show in table", "showTable", availableTargets > 0);
  addAction("Inspect device", "inspectDevice", group.deviceIds.length === 1 && availableTargets === 1);
  addAction("Compare endpoints", "compareEndpoints",
    group.deviceIds.length === 2 && availableTargets === 2 && availableTopologyTargets === 2);
  addAction("Apply related filter", "applyFilter", true);
  if (actionBar.childNodes.length > 0) item.appendChild(actionBar);
}

function renderFindingGroup(group, actions) {
  const item = document.createElement("li");
  item.className = `health-finding-group state-${group.status.toLowerCase()}`;
  appendText(item, "h3", group.title);
  appendText(item, "p", findingSummary(group));
  appendText(item, "p",
    `${group.count} finding${group.count === 1 ? "" : "s"} · ${group.scope} · ${group.confidence} confidence`,
    "health-finding-meta");
  if (group.endpoints.length > 0) {
    const endpoints = document.createElement("ol");
    endpoints.className = "health-finding-endpoints";
    const shownEndpoints = group.endpoints.slice(0, 8);
    shownEndpoints.forEach((endpoint) => appendEndpointInspection(
      endpoints, endpoint, group.groupId, null, actions,
    ));
    if (group.endpoints.length > shownEndpoints.length) {
      appendText(item, "p", `${group.endpoints.length - shownEndpoints.length} more devices not shown.`,
        "health-finding-endpoints-omitted");
    }
    item.appendChild(endpoints);
  }
  appendFindingActions(item, group, actions);
  const details = document.createElement("details");
  details.className = "health-finding-details";
  if (group.ruleId === "network.current-path-redundancy") {
    appendRouterNames(details, group, actions);
    item.appendChild(details);
    return item;
  }
  if (group.ruleId === "network.router-redundancy") {
    appendRedundancyDevices(details, group, "Router", actions);
    item.appendChild(details);
    return item;
  }
  if (group.ruleId === "network.border-router-redundancy") {
    appendRedundancyDevices(details, group, "Border Router", actions);
    item.appendChild(details);
    return item;
  }
  appendAttributedFindings(details, group, actions);
  item.appendChild(details);
  return item;
}

function renderHealthAssessmentSummary(container, model) {
  container.replaceChildren();
  const assessment = model.assessment;
  const visibleGroups = projectVisibleHealthFindingGroups(assessment.findingGroups);
  const allFindings = visibleGroups.flatMap((group) => group.findings || []);
  const header = document.createElement("div");
  header.className = "health-assessment-header";
  appendText(header, "strong", assessment.status,
    `health-status-state state-${assessment.status.toLowerCase()}`);
  appendText(header, "span", `${assessment.completeness} · ${assessment.confidence} confidence`);
  appendText(header, "span",
    `${visibleGroups.length} finding groups · ${allFindings.length} attributed findings`);
  container.appendChild(header);

  const affectedDevices = new Set(allFindings.flatMap((finding) => finding.deviceIds || [])).size;
  const affectedRelationships = new Set(
    allFindings.flatMap((finding) => finding.relationshipIds || []),
  ).size;
  const populations = document.createElement("p");
  populations.className = "health-population-summary";
  const populationParts = [];
  if (Number.isInteger(assessment.coverage?.deviceCount)) {
    populationParts.push(`${assessment.coverage.deviceCount} observed devices`);
  }
  populationParts.push(`${affectedDevices} affected identities`);
  populationParts.push(`${affectedRelationships} affected relationships`);
  populations.textContent = populationParts.join(" · ");
  container.appendChild(populations);

  const pillarHeading = appendText(container, "h3", "Dataset Evidence Pillars", "health-coverage-heading");
  const pillars = document.createElement("dl");
  pillars.className = "health-coverage-pillars";
  pillars.setAttribute("aria-labelledby", pillarHeading.id = "health-coverage-heading");
  HEALTH_PRESENTATION_POLICY.visiblePillars.forEach((pillar) => {
    const label = PILLAR_LABELS[pillar];
    const item = document.createElement("div");
    item.className = "health-coverage-pillar";
    const name = appendText(item, "dt", label);
    name.title = PILLAR_TOOLTIPS[pillar];
    const capability = assessment.coverage?.pillars?.[pillar] ?? "missing";
    const observed = assessment.coverage?.observedPillars?.[pillar];
    const status = observed?.state ?? capability;
    const value = appendText(item, "dd", "", `health-coverage-state state-${status}`);
    appendText(value, "span", COVERAGE_STATUS_GLYPHS[status] ?? "?", "health-coverage-glyph");
    appendText(value, "span", status.replace(/^./, (letter) => letter.toUpperCase()), "health-coverage-state-label");
    if (capability !== status) appendText(value, "small", `Dataset: ${capability}`, "health-coverage-capability");
    const reasons = Array.isArray(observed?.reasons) ? observed.reasons.join(" ") : "";
    value.title = [
      COVERAGE_STATUS_TOOLTIPS[status] ?? `Coverage status: ${status}.`,
      `Dataset capability: ${capability}.`,
      reasons,
    ].filter(Boolean).join(" ");
    pillars.appendChild(item);
  });
  container.appendChild(pillars);

  if (model.capabilities && model.observations) {
    appendText(container, "p",
      `History: ${model.capabilities.observationCount} observations · ${model.capabilities.expectedRosterCount} expected devices`,
      "health-history-summary");
  }
  if (assessment.evaluationContextComplete === false) {
    const unavailable = Array.isArray(assessment.unavailableEvaluationDomains)
      ? assessment.unavailableEvaluationDomains.join(", ")
      : "";
    appendText(
      container,
      "p",
      `Some evaluation context is unavailable${unavailable ? `: ${unavailable}` : ""}.`,
      "health-context-gap-summary",
    );
  }
  if (assessment.migration) {
    appendText(
      container,
      "p",
      `Replayed from retained history (source ${assessment.migration.sourceAssessmentId}); migration does not certify network health.`,
      "health-migration-summary",
    );
  }
}

const HEALTH_TABLE_COLUMNS = Object.freeze([
  { id: "status", label: "Status", className: "health-col-status" },
  { id: "title", label: "Finding", className: "health-col-finding" },
  { id: "affected", label: "Affected", className: "health-col-affected" },
  { id: "scope", label: "Scope", className: "health-col-secondary" },
  { id: "confidence", label: "Confidence", className: "health-col-secondary" },
  { id: "evidence", label: "Evidence", className: "health-col-secondary" },
]);

function nextSort(currentSort, column) {
  if (currentSort.column !== column) return { column, direction: "ascending" };
  return { column, direction: currentSort.direction === "ascending" ? "descending" : "ascending" };
}

function appendHealthSummaryRow(body, row, viewState, actions) {
  const tableRow = document.createElement("tr");
  tableRow.className = `health-summary-row state-${row.status}`;
  tableRow.dataset.groupId = row.groupId;
  tableRow.classList.toggle("is-selected", row.groupId === viewState.selectedGroupId);
  tableRow.addEventListener("click", () => actions.selectGroup?.(row.groupId));
  appendText(tableRow, "td", row.status.replace(/^./, (letter) => letter.toUpperCase()),
    "health-col-status table-health-status").classList.add(`state-${row.status}`);
  const findingCell = document.createElement("td");
  findingCell.className = "health-col-finding";
  const button = appendText(findingCell, "button", row.title, "health-finding-select");
  button.type = "button";
  button.dataset.groupId = row.groupId;
  button.setAttribute("aria-label", `${row.title}, ${row.status}, ${row.affected.label}`);
  if (row.groupId === viewState.selectedGroupId) button.setAttribute("aria-current", "true");
  if (row.summary) appendText(findingCell, "span", row.summary, "health-finding-row-summary");
  tableRow.appendChild(findingCell);
  appendText(tableRow, "td", row.affected.label, "health-col-affected");
  appendText(tableRow, "td", row.scope, "health-col-secondary");
  appendText(tableRow, "td", row.confidence, "health-col-secondary");
  appendText(tableRow, "td", row.evidenceLabel, "health-col-secondary");
  body.appendChild(tableRow);
}

export function renderHealthInsights(container, model, viewState = {}, actions = {}) {
  if (!container) return;
  const summary = container.querySelector("#health-insights-evidence");
  const table = container.querySelector("#health-finding-table");
  const tableWrap = container.querySelector("#health-finding-table-wrap");
  const empty = container.querySelector("#health-insights-empty");
  if (!summary || !table || !tableWrap || !empty) return;
  summary.replaceChildren();
  table.tHead?.replaceChildren();
  table.tBodies[0]?.replaceChildren();
  tableWrap.hidden = true;
  empty.replaceChildren();
  if (model.loading && !model.assessment) {
    appendText(empty, "p", "Loading processed health assessment…", "network-insights-empty");
    return;
  }
  if (!model.assessment) {
    appendText(empty, "p", model.error || "Health assessment unavailable.", "network-insights-empty");
    return;
  }

  renderHealthAssessmentSummary(summary, model);
  if (model.error) {
    appendText(empty, "p", `Latest refresh failed: ${model.error}`, "network-insights-empty error");
  }
  const rows = projectHealthSummaryRows(model.assessment.findingGroups || [], viewState);
  const headRow = document.createElement("tr");
  HEALTH_TABLE_COLUMNS.forEach((column) => {
    const heading = document.createElement("th");
    heading.scope = "col";
    heading.className = column.className;
    const button = appendText(heading, "button", column.label, "health-sort-button");
    button.type = "button";
    button.addEventListener("click", () => actions.changeSort?.(nextSort(viewState.sort || {}, column.id)));
    if (viewState.sort?.column === column.id) {
      heading.setAttribute("aria-sort", viewState.sort.direction ?? "ascending");
      appendText(button, "span", viewState.sort.direction === "descending" ? "▼" : "▲", "health-sort-icon");
    }
    headRow.appendChild(heading);
  });
  table.tHead.appendChild(headRow);
  rows.forEach((row) => appendHealthSummaryRow(table.tBodies[0], row, viewState, actions));
  if (rows.length === 0) {
    appendText(empty, "p", "No findings match the selected health filters.", "network-insights-empty");
  } else {
    tableWrap.hidden = false;
    const sortLabel = viewState.sort?.column === "priority"
      ? "priority"
      : `${viewState.sort?.column ?? "priority"} ${viewState.sort?.direction ?? "ascending"}`;
    appendText(empty, "p",
      `${rows.length} finding group${rows.length === 1 ? "" : "s"} shown · sorted by ${sortLabel}`,
      "health-table-footer");
  }
}

function appendDetailAction(parent, label, action, enabled = true, ariaLabel = null, focusKey = null) {
  if (!enabled) return;
  const button = appendText(parent, "button", label);
  button.type = "button";
  if (ariaLabel) button.setAttribute("aria-label", ariaLabel);
  if (focusKey) button.dataset.healthFocusKey = focusKey;
  button.addEventListener("click", action);
  return button;
}

function appendSharedDetailSection(parent, heading, value) {
  if (!value) return;
  const section = document.createElement("section");
  section.className = "health-finding-detail-section";
  appendText(section, "h3", heading);
  appendText(section, "p", value);
  parent.appendChild(section);
}

export function renderHealthFindingDetails(container, model, actions = {}) {
  if (!container) return;
  container.replaceChildren();
  if (!model) {
    appendText(container, "p", "Select a finding group to inspect its evidence.", "network-insights-empty");
    return;
  }

  appendText(container, "p", model.summary, "health-finding-detail-summary");
  const priority = document.createElement("div");
  priority.className = "health-finding-detail-priority";
  const statusClass = String(model.status || "").toLowerCase().replace(/[^a-z0-9-]/g, "");
  appendText(priority, "span", model.status, `health-finding-detail-status state-${statusClass}`);
  appendText(priority, "span", model.affected.label, "health-finding-detail-count");
  container.appendChild(priority);

  const metadata = document.createElement("div");
  metadata.className = "health-finding-detail-meta";
  [model.scope, `${model.confidence} confidence`, model.evidenceLabel, model.materialityLabel]
    .filter(Boolean)
    .forEach((value) => appendText(metadata, "span", value));
  container.appendChild(metadata);

  appendSharedDetailSection(
    container,
    "Why it matters",
    model.shared.whyItMatters || "Varies by affected item.",
  );

  appendSharedDetailSection(container, "Recommended action", model.shared.action || "Varies by affected item.");
  appendSharedDetailSection(container, "Verify", model.shared.verify || "Varies by affected item.");

  const investigation = document.createElement("section");
  investigation.className = "health-finding-detail-section health-finding-investigation";
  appendText(investigation, "h3", "Investigate");
  const actionBar = document.createElement("div");
  actionBar.className = "health-finding-actions";
  if (actions.groupDeviceCount > 1) {
    appendText(investigation, "p",
      `${actions.availableTargets} of ${actions.groupDeviceCount} affected devices are available in the current dataset/network. `
      + `${actions.availableTopologyTargets} of ${actions.groupDeviceCount} are represented in topology. `
      + "Table navigation selects the first available device. "
      + "Stored-only devices are excluded.",
      "health-finding-navigation-note");
  }
  appendDetailAction(actionBar, "Show in topology", () => actions.showTopology?.(model.groupId),
    actions.availableTopologyTargets > 0);
  appendDetailAction(
    actionBar,
    actions.groupDeviceCount > 1 ? "Show first available in table" : "Show in table",
    () => actions.showTable?.(model.groupId),
    actions.availableTargets > 0);
  appendDetailAction(actionBar, "Compare endpoints", () => actions.compareEndpoints?.(model.groupId),
    actions.groupDeviceCount === 2
      && actions.availableTargets === 2
      && actions.availableTopologyTargets === 2);
  appendDetailAction(actionBar, "Apply related filter", () => actions.applyFilter?.(model.groupId));
  if (actionBar.childNodes.length > 0) {
    investigation.appendChild(actionBar);
    container.appendChild(investigation);
  }

  const affectedSection = document.createElement("section");
  affectedSection.className = "health-finding-detail-section";
  appendText(affectedSection, "h3", "Affected items");
  const list = document.createElement("ol");
  list.className = "health-affected-list";
  model.items.forEach((item) => {
    const listItem = document.createElement("li");
    listItem.className = "health-affected-item";
    const selectButton = document.createElement("button");
    selectButton.className = "health-affected-select";
    selectButton.type = "button";
    selectButton.dataset.findingId = item.findingId;
    selectButton.setAttribute("aria-expanded", String(item.isExpanded));
    const endpointId = item.endpointId ?? item.endpointIds[0] ?? null;
    const identityLabel = item.identityLabel || endpointId?.replace(/^extaddr:/, "") || "";
    const entryId = `${item.findingId}-${endpointId ?? "finding"}`;
    const detailId = `health-affected-details-${encodeURIComponent(entryId)}`;
    selectButton.setAttribute("aria-controls", detailId);
    const endpointContext = identityLabel ? `Device ID ${identityLabel}.` : "";
    const findingContext = item.findingContext ? `Finding: ${item.findingContext}.` : "";
    selectButton.setAttribute("aria-label", [
      item.label, endpointContext, findingContext, item.highlightSummary,
    ].filter(Boolean).join(" "));
    if (endpointId) selectButton.dataset.deviceId = endpointId;
    selectButton.addEventListener("click", () => actions.selectFinding?.(
      item.findingId, endpointId,
    ));

    const buttonCopy = document.createElement("span");
    buttonCopy.className = "health-affected-copy";
    appendText(buttonCopy, "span", item.label, "health-affected-label");
    if (identityLabel) {
      appendText(buttonCopy, "span", `Device ID ${identityLabel}`, "health-affected-identity");
    }
    if (item.highlightSummary) {
      appendText(buttonCopy, "span", item.highlightSummary, "health-affected-summary");
    }
    if (item.findingContext) {
      appendText(buttonCopy, "span", `Finding: ${item.findingContext}`, "health-affected-summary");
    }
    selectButton.appendChild(buttonCopy);
    const chevron = appendText(selectButton, "span", "", "health-affected-chevron");
    chevron.setAttribute("aria-hidden", "true");
    listItem.appendChild(selectButton);

    const details = document.createElement("div");
    details.id = detailId;
    details.className = "health-affected-details";
    details.hidden = !item.isExpanded;
    if (item.isExpanded) {
      const evidence = document.createElement("dl");
      evidence.className = "health-finding-evidence health-affected-evidence";
      item.evidenceRows.forEach(([key, value]) => {
        appendText(evidence, "dt", evidenceLabel(key));
        appendText(evidence, "dd", formatEvidenceValue(value));
      });
      details.appendChild(evidence);
      if (!model.shared.whyItMatters && item.finding.whyItMatters) {
        appendText(details, "p", `Why it matters: ${item.finding.whyItMatters}`);
      }
      if (!model.shared.action && item.finding.action) {
        appendText(details, "p", `Action: ${item.finding.action}`);
      }
      if (!model.shared.verify && item.finding.verify) {
        appendText(details, "p", `Verify: ${item.finding.verify}`);
      }
      if (endpointId && actions.inspectableDeviceIds?.has(endpointId)) {
        const focusKey = `finding-inspect:${item.findingId}:${endpointId}`;
        appendDetailAction(details, "Inspect device", () => actions.inspectDevice?.(
          endpointId, item.findingId, endpointId, focusKey,
        ), true, `Inspect ${item.label} (${identityLabel})`, focusKey);
      }
      if (actions.mutationAvailable && endpointId
          && item.finding.scope === "device") {
        const deviceId = endpointId;
        const allowedActions = actions.rosterActionsByDevice?.get(deviceId) || [];
        if (allowedActions.includes("enroll")) {
          appendDetailAction(details, "Add to Roster", () => actions.rosterAction?.(
            "enroll", deviceId, item.findingId,
          ));
        }
        if (item.finding.ruleId === "device.offline"
            && allowedActions.includes("mark-offline")) {
          appendDetailAction(details, "Mark Offline", () => actions.rosterAction?.(
            "mark-offline", deviceId, item.findingId,
          ));
        }
        const actionError = actions.rosterActionErrors?.get(deviceId);
        if (actionError) {
          appendText(details, "p", `Stored device actions unavailable: ${actionError}`, "error");
        }
      }
    }
    listItem.appendChild(details);
    list.appendChild(listItem);
  });
  affectedSection.appendChild(list);
  container.appendChild(affectedSection);

  if ((model.relatedDevices || []).length > 0) {
    const relatedSection = document.createElement("section");
    relatedSection.className = "health-finding-detail-section";
    appendText(relatedSection, "h3", "Related devices");
    const relatedList = document.createElement("ol");
    relatedList.className = "health-related-devices";
    const shownDevices = model.relatedDevices.slice(0, 8);
    shownDevices.forEach((device) => {
      const entry = document.createElement("li");
      const identity = device.deviceId.replace(/^extaddr:/, "");
      const copy = document.createElement("div");
      appendText(copy, "strong", device.displayName || identity);
      appendText(copy, "span", `Device ID ${identity}`, "health-affected-identity");
      appendText(copy, "span", device.association, "health-related-device-association");
      if (device.summary) appendText(copy, "span", device.summary, "health-affected-summary");
      entry.appendChild(copy);
      if (actions.inspectableDeviceIds?.has(device.deviceId)) {
        const focusKey = `related-inspect:${model.groupId}:${device.findingId || "group"}:${device.deviceId}`;
        const inspect = appendDetailAction(
          entry,
          "Inspect device",
          () => actions.inspectRelatedDevice?.(model.groupId, device.findingId, device.deviceId, focusKey),
          true,
          `Inspect ${device.displayName || identity} (${identity})`,
          focusKey,
        );
        inspect.className = "health-related-device-inspect";
        inspect.dataset.deviceId = device.deviceId;
        if (device.findingId) inspect.dataset.findingId = device.findingId;
      }
      relatedList.appendChild(entry);
    });
    relatedSection.appendChild(relatedList);
    if (model.relatedDevices.length > shownDevices.length) {
      appendText(relatedSection, "p",
        `${model.relatedDevices.length - shownDevices.length} more related devices not shown.`,
        "health-finding-endpoints-omitted");
    }
    container.appendChild(relatedSection);
  }

  if (model.shared.sourceFiles.length > 0) {
    appendSharedDetailSection(container, "Sources", model.shared.sourceFiles.join(", "));
  }
}

export function projectFindingDeviceAvailability(currentDeviceIds, storedDeviceIds) {
  return {
    availableTargets: currentDeviceIds.size,
    inspectableDeviceIds: new Set([...currentDeviceIds, ...storedDeviceIds]),
  };
}

export function exportHealthAssessment(assessment) {
  if (!assessment) return;
  const blob = new Blob([`${JSON.stringify(assessment, null, 2)}\n`], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `td-health-${assessment.datasetId}-${assessment.assessmentId.replaceAll(":", "-")}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function renderDeviceHealth(container, model, actions = {}) {
  if (!container) return;
  container.replaceChildren();
  if (model.loading) {
    appendText(container, "p", "Loading device health…", "device-insights-empty");
    return;
  }
  if (model.error || !model.device) {
    appendText(container, "p", model.error || "No processed health findings for this device.", "device-insights-empty");
    return;
  }
  appendText(container, "h3", model.device.displayName, "device-insights-title");
  appendText(container, "p",
    `${model.device.role || "Unknown role"}${model.device.isBorderRouter ? " · Border Router" : ""}`,
    "health-finding-meta");
  if (model.assessment) {
    appendText(
      container,
      "p",
      `${model.assessment.completeness} assessment · ${model.assessment.confidence} confidence · ${formatAge(model.assessment.observedAt)}`,
      "health-finding-meta",
    );
  }
  if (model.device.findings.length === 0) {
    appendText(container, "p", "No attributed findings in this assessment.", "device-insights-empty");
    return;
  }
  const groups = model.device.findings.map((finding) => ({
    ...finding,
    count: 1,
    deviceIds: finding.deviceIds || [model.device.deviceId],
    relationshipIds: finding.relationshipIds || [],
    endpoints: finding.endpoints || [],
    findings: [finding],
  }));
  projectHealthFindingSections(groups).forEach((section) => {
    if (section.groups.length === 0) return;
    const sectionElement = document.createElement("section");
    sectionElement.className = `device-health-section health-finding-section-${section.id}`;
    appendText(sectionElement, "h4", section.title);
    const list = document.createElement("ul");
    list.className = "device-insights-list";
    section.groups.forEach((group) => {
      const finding = group.findings[0];
      const item = document.createElement("li");
      item.className = `device-insight-item state-${finding.status.toLowerCase()}`;
      appendText(item, "strong", finding.title);
      appendText(item, "p", finding.summary);
      appendFindingEvidence(item, finding);
      appendFindingActions(item, group, actions);
      list.appendChild(item);
    });
    sectionElement.appendChild(list);
    container.appendChild(sectionElement);
  });
}