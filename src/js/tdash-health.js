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
  return healthRequest(`/api/health/summary?dataset=${encodeURIComponent(datasetId)}`, signal);
}

export function fetchHealthDevice(assessmentId, deviceId, signal) {
  const query = new URLSearchParams({ assessment: assessmentId });
  return healthRequest(`/api/health/devices/${encodeURIComponent(deviceId)}?${query}`, signal);
}

export async function fetchHealthSupport(networkId, signal) {
  const query = new URLSearchParams({ network: networkId, limit: "5", offset: "0" });
  const [capabilities, observations] = await Promise.all([
    healthRequest("/api/health/capabilities", signal),
    healthRequest(`/api/health/observations?${query}`, signal),
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
  return (filters.status === "all" || group.status === filters.status) &&
    (filters.scope === "all" || group.scope === filters.scope);
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

function renderFindingGroup(group) {
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
  const details = document.createElement("details");
  details.className = "health-finding-details";
  if (group.ruleId === "network.current-path-redundancy") {
    appendRouterNames(details, group);
    item.appendChild(details);
    return item;
  }
  appendText(details, "summary", `Show ${group.count} attributed finding${group.count === 1 ? "" : "s"}`);
  const children = document.createElement("ol");
  group.findings.forEach((finding) => {
    const child = document.createElement("li");
    appendText(child, "strong", finding.summary);
    if (finding.endpoints.length > 0) {
      appendText(child, "span", finding.endpoints.map(numberedEndpointLabel).join(", "));
    }
    children.appendChild(child);
  });
  details.appendChild(children);
  item.appendChild(details);
  return item;
}

export function renderHealthInsights(container, model, filters = { status: "all", scope: "all" }) {
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
  container.appendChild(header);

  const pillars = document.createElement("dl");
  pillars.className = "health-coverage-pillars";
  Object.entries(PILLAR_LABELS).forEach(([pillar, label]) => {
    const name = appendText(pillars, "dt", label);
    name.title = PILLAR_TOOLTIPS[pillar];
    const status = assessment.coverage?.pillars?.[pillar] ?? "missing";
    const value = appendText(pillars, "dd", status);
    value.title = COVERAGE_STATUS_TOOLTIPS[status] ?? `Coverage status: ${status}.`;
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

  const groups = (assessment.findingGroups || []).filter((group) => findingMatches(group, filters));
  if (groups.length === 0) {
    appendText(container, "p", "No findings match the selected health filters.", "network-insights-empty");
    return;
  }
  const list = document.createElement("ul");
  list.className = "health-finding-groups";
  groups.forEach((group) => list.appendChild(renderFindingGroup(group)));
  container.appendChild(list);
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

export function renderDeviceHealth(container, model) {
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
  if (model.device.findings.length === 0) {
    appendText(container, "p", "No attributed findings in this assessment.", "device-insights-empty");
    return;
  }
  const list = document.createElement("ul");
  list.className = "device-insights-list";
  model.device.findings.forEach((finding) => {
    const item = appendText(list, "li", `${finding.title}: ${finding.summary}`);
    item.className = `device-insight-item state-${finding.status.toLowerCase()}`;
  });
  container.appendChild(list);
}