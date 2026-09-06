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

function appendText(parent, tagName, text, className = "") {
  const element = document.createElement(tagName);
  element.textContent = text;
  if (className) element.className = className;
  parent.appendChild(element);
  return element;
}

async function healthRequest(path, signal) {
  const response = await fetch(path, { headers: { Accept: "application/json" }, signal });
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

function formatAge(timestamp) {
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - Date.parse(timestamp)) / 1000));
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
  const isAvailable = model.loading || (!model.error && Boolean(model.assessment));
  container.toggleAttribute("hidden", !isAvailable);
  if (!isAvailable) return;
  if (model.loading) {
    appendText(container, "span", "Health: loading", "health-status-state is-loading");
    return;
  }

  const assessment = model.assessment;
  appendText(container, "span", `Health: ${assessment.status}`,
    `health-status-state state-${assessment.status.toLowerCase()}`);
  appendText(container, "span", assessment.completeness, "health-status-detail");
  const time = appendText(container, "time", formatAge(assessment.observedAt), "health-status-detail");
  time.dateTime = assessment.observedAt;
  time.title = new Date(assessment.observedAt).toLocaleString();
}

function findingMatches(group, filters) {
  const effectiveScope = group.scope === "observation" ? "network" : group.scope;
  return (filters.status === "all" || group.status === filters.status) &&
    (filters.scope === "all" || effectiveScope === filters.scope) &&
    (filters.evidenceKind === "all" || group.findings.some(
      (finding) => finding.evidenceKind === filters.evidenceKind,
    ));
}

export function projectHealthFindingSections(groups, filters = {}) {
  const effectiveFilters = {
    status: filters.status ?? "all",
    scope: filters.scope ?? "all",
    evidenceKind: filters.evidenceKind ?? "all",
  };
  const matched = groups.filter((group) => findingMatches(group, effectiveFilters));
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

export function renderHealthInsights(container, model, filters = {}, actions = {}) {
  if (!container) return;
  container.replaceChildren();
  if (model.loading) {
    appendText(container, "p", "Loading processed health assessment…", "network-insights-empty");
    return;
  }
  if (model.error || !model.assessment) {
    appendText(container, "p", model.error || "Health assessment unavailable.", "network-insights-empty");
    return;
  }

  const assessment = model.assessment;
  const header = document.createElement("div");
  header.className = "health-assessment-header";
  appendText(header, "strong", assessment.status,
    `health-status-state state-${assessment.status.toLowerCase()}`);
  appendText(header, "span",
    `${assessment.completeness} · ${assessment.confidence} confidence · ${assessment.findingCount} findings`);
  const allFindings = (assessment.findingGroups || []).flatMap((group) => group.findings || []);
  const affectedDevices = new Set(allFindings.flatMap((finding) => finding.deviceIds || [])).size;
  const affectedRelationships = new Set(
    allFindings.flatMap((finding) => finding.relationshipIds || []),
  ).size;
  const totalDevices = assessment.coverage?.deviceCount;
  appendText(
    header,
    "span",
    `${affectedDevices}${Number.isInteger(totalDevices) ? `/${totalDevices}` : ""} devices · ${affectedRelationships} links`,
    "health-status-detail",
  );
  container.appendChild(header);

  const pillarHeading = appendText(container, "h2", "Dataset Evidence Pillars", "health-coverage-heading");
  const pillars = document.createElement("dl");
  pillars.className = "health-coverage-pillars";
  pillars.setAttribute("aria-labelledby", pillarHeading.id = "health-coverage-heading");
  Object.entries(PILLAR_LABELS).forEach(([pillar, label]) => {
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
    if (capability !== status) {
      appendText(value, "small", `Dataset: ${capability}`, "health-coverage-capability");
    }
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
    appendText(
      container,
      "p",
      `${model.capabilities.observationCount} stored observations · ${model.capabilities.expectedRosterCount} expected devices · showing ${model.observations.items.length} recent observations`,
      "health-history-summary",
    );
  }

  const sections = projectHealthFindingSections(assessment.findingGroups || [], filters);
  if (sections.every((section) => section.groups.length === 0)) {
    appendText(container, "p", "No findings match the selected health filters.", "network-insights-empty");
    return;
  }
  sections.forEach((section) => {
    const sectionElement = document.createElement("section");
    sectionElement.className = `health-finding-section health-finding-section-${section.id}`;
    appendText(sectionElement, "h2", section.title);
    if (section.groups.length === 0) {
      appendText(sectionElement, "p", "No findings in this section.", "network-insights-empty");
    } else {
      const list = document.createElement("ul");
      list.className = "health-finding-groups";
      section.groups.forEach((group) => list.appendChild(renderFindingGroup(group, actions)));
      sectionElement.appendChild(list);
    }
    container.appendChild(sectionElement);
  });
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