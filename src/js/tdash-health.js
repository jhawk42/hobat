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
  appendText(container, "span", `Health: ${assessment.status}`,
    `health-status-state state-${assessment.status.toLowerCase()}`);
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

export function projectHealthFindingDetail(group, selectedFindingId = null) {
  if (!projectVisibleHealthFindingGroups([group]).length) return null;
  const findings = group.findings || [];
  const row = projectHealthSummaryRows([group], { view: "all" })[0];
  return {
    groupId: group.groupId,
    heading: group.title,
    status: group.status,
    summary: findingSummary(group),
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
    items: findings.map((finding) => ({
      findingId: finding.findingId,
      label: finding.endpoints?.map(
        ({ deviceId, displayName }) => displayName || deviceId.replace(/^extaddr:/, ""),
      ).join(", ") || finding.summary,
      endpointIds: [...(finding.deviceIds || [])],
      relationshipIds: [...(finding.relationshipIds || [])],
      evidenceRows: Object.entries(finding.evidence || {})
        .filter(([key]) => !["evidenceKind", "materiality", "presentationVariant"].includes(key)),
      isExpanded: finding.findingId === selectedFindingId,
      finding,
    })),
  };
}

export function reconcileHealthInsightsSelection(viewState, assessment) {
  const next = { ...viewState, assessmentId: assessment?.assessmentId ?? null };
  const group = projectVisibleHealthFindingGroups(assessment?.findingGroups).find(
    ({ groupId }) => groupId === viewState.selectedGroupId,
  );
  if (!group) {
    return { ...next, selectedGroupId: null, selectedFindingId: null, detailsOpen: false };
  }
  const findingExists = (group.findings || []).some(
    ({ findingId }) => findingId === viewState.selectedFindingId,
  );
  return { ...next, selectedFindingId: findingExists ? viewState.selectedFindingId : null };
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
  return `${deviceId.replace(/^extaddr:/, "")} ${displayName}`;
}

function appendRouterNames(details, group) {
  const routers = group.findings.flatMap((finding) => finding.routerEndpoints || []);
  const uniqueRouters = [...new Map(routers.map((router) => [router.deviceId, router])).values()];
  appendText(details, "summary", `Show ${uniqueRouters.length} Router name${uniqueRouters.length === 1 ? "" : "s"}`);
  const names = document.createElement("ol");
  uniqueRouters.forEach((router) => appendText(names, "li", numberedEndpointLabel(router)));
  details.appendChild(names);
}

function appendRedundancyDevices(details, group, deviceType) {
  appendText(
    details,
    "summary",
    `Show ${group.endpoints.length} ${deviceType}${group.endpoints.length === 1 ? "" : "s"}`,
  );
  const devices = document.createElement("ol");
  group.endpoints.forEach((endpoint) => appendText(devices, "li", numberedEndpointLabel(endpoint)));
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

function appendAttributedFindings(details, group) {
  appendText(details, "summary", `Show ${group.count} attributed finding${group.count === 1 ? "" : "s"}`);
  const findings = document.createElement("ol");
  group.findings.forEach((finding) => {
    const child = document.createElement("li");
    if (finding.endpoints.length > 0) {
      appendText(child, "strong", finding.endpoints.map(numberedEndpointLabel).join(", "));
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
  addAction("Show in topology", "showTopology", availableTargets > 0);
  addAction("Show in table", "showTable", availableTargets > 0);
  addAction("Inspect device", "inspectDevice", group.deviceIds.length === 1 && availableTargets === 1);
  addAction("Compare endpoints", "compareEndpoints", group.deviceIds.length === 2 && availableTargets === 2);
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
    appendText(item, "p",
      group.endpoints.slice(0, 8).map(({ displayName }) => displayName).join(", "),
      "health-finding-endpoints");
  }
  appendFindingActions(item, group, actions);
  const details = document.createElement("details");
  details.className = "health-finding-details";
  if (group.ruleId === "network.current-path-redundancy") {
    appendRouterNames(details, group);
    item.appendChild(details);
    return item;
  }
  if (group.ruleId === "network.router-redundancy") {
    appendRedundancyDevices(details, group, "Router");
    item.appendChild(details);
    return item;
  }
  if (group.ruleId === "network.border-router-redundancy") {
    appendRedundancyDevices(details, group, "Border Router");
    item.appendChild(details);
    return item;
  }
  appendAttributedFindings(details, group);
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
  const summary = container.querySelector("#health-insights-summary");
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

function appendDetailAction(parent, label, action, enabled = true) {
  if (!enabled) return;
  const button = appendText(parent, "button", label);
  button.type = "button";
  button.addEventListener("click", action);
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
  const metadata = document.createElement("div");
  metadata.className = "health-finding-detail-meta";
  [model.status, model.affected.label, model.scope, `${model.confidence} confidence`,
    model.evidenceLabel, model.materialityLabel].forEach((value) => appendText(metadata, "span", value));
  container.appendChild(metadata);

  const actionBar = document.createElement("div");
  actionBar.className = "health-finding-actions";
  appendDetailAction(actionBar, "Show in topology", () => actions.showTopology?.(model.groupId),
    actions.availableTargets > 0);
  appendDetailAction(actionBar, "Show in table", () => actions.showTable?.(model.groupId),
    actions.availableTargets > 0);
  appendDetailAction(actionBar, "Inspect device", () => actions.inspectDevice?.(
    model.items[0]?.endpointIds[0], model.items[0]?.findingId,
  ), actions.groupDeviceCount === 1 && actions.availableTargets === 1);
  appendDetailAction(actionBar, "Compare endpoints", () => actions.compareEndpoints?.(model.groupId),
    actions.groupDeviceCount === 2 && actions.availableTargets === 2);
  appendDetailAction(actionBar, "Apply related filter", () => actions.applyFilter?.(model.groupId));
  container.appendChild(actionBar);

  appendSharedDetailSection(
    container,
    "Why it matters",
    model.shared.whyItMatters || "Varies by affected item.",
  );

  const affectedSection = document.createElement("section");
  affectedSection.className = "health-finding-detail-section";
  appendText(affectedSection, "h3", "Affected items");
  const list = document.createElement("ol");
  list.className = "health-affected-list";
  model.items.forEach((item) => {
    const listItem = document.createElement("li");
    listItem.className = "health-affected-item";
    const selectButton = appendText(listItem, "button", item.label, "health-affected-select");
    selectButton.type = "button";
    selectButton.dataset.findingId = item.findingId;
    selectButton.setAttribute("aria-expanded", String(item.isExpanded));
    selectButton.addEventListener("click", () => actions.selectFinding?.(item.findingId));
    if (item.isExpanded) {
      const evidence = document.createElement("dl");
      evidence.className = "health-finding-evidence health-affected-evidence";
      item.evidenceRows.forEach(([key, value]) => {
        appendText(evidence, "dt", evidenceLabel(key));
        appendText(evidence, "dd", formatEvidenceValue(value));
      });
      listItem.appendChild(evidence);
      if (!model.shared.whyItMatters) appendText(listItem, "p", item.finding.whyItMatters);
      if (!model.shared.action) appendText(listItem, "p", `Action: ${item.finding.action}`);
      if (!model.shared.verify) appendText(listItem, "p", `Verify: ${item.finding.verify}`);
      if (item.endpointIds.length === 1 && actions.inspectableDeviceIds?.has(item.endpointIds[0])) {
        appendDetailAction(listItem, "Inspect device", () => actions.inspectDevice?.(
          item.endpointIds[0], item.findingId,
        ));
      }
    }
    list.appendChild(listItem);
  });
  affectedSection.appendChild(list);
  container.appendChild(affectedSection);

  appendSharedDetailSection(container, "Recommended action", model.shared.action || "Varies by affected item.");
  appendSharedDetailSection(container, "Verify", model.shared.verify || "Varies by affected item.");
  if (model.shared.sourceFiles.length > 0) {
    appendSharedDetailSection(container, "Sources", model.shared.sourceFiles.join(", "));
  }
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