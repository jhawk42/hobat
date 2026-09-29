import { getRowRoleProjection } from "./tdash-filters.js";
import { getColumnValue, toText } from "./tdash-utils.js";
import { resolveNetworkInstance } from "./tdash-view-status.js";

const NETWORK_FACT_KEYS = Object.freeze({
  networkName: { label: "Name", priority: 0 },
  network_name: { label: "Name", priority: 0 },
  omrPrefix: { label: "OMR Prefix", priority: 0 },
  prefixOmr: { label: "OMR Prefix", priority: 0 },
  prefixOmrIpv6AddrPrefix: { label: "OMR Prefix", priority: 1 },
  prefix_omr_ipv6addr_prefix: { label: "OMR Prefix", priority: 1 },
  extPanId: { label: "Ext PAN ID", priority: 0 },
  extendedPanId: { label: "Ext PAN ID", priority: 0 },
  meshLocalPrefix: { label: "Mesh Local Prefix", priority: 0 },
  prefixMeshLocal: { label: "Mesh Local Prefix", priority: 0 },
  prefixMeshlocal: { label: "Mesh Local Prefix", priority: 0 },
  channel: { label: "Channel", priority: 0 },
});

const THREAD_ROW_FIELDS = Object.freeze([
  "threadVersion",
  "threadStackVersion",
  "threadVersionDecimal",
  "rloc16",
  "routerId",
  "childId",
  "parentId",
  "mode.device",
  "mode.fullThreadDevice",
  "isRouterEligible",
  "isLeader",
  "isPrimaryBBR",
  "isBorderRouter",
  "isRouter",
  "leaderData.partitionId",
  "partitionId",
  "children",
  "childTable",
  "routerNeighbors",
]);

const END_DEVICE_ROLES = new Set([
  "child",
  "end_device",
  "sleepy_child",
  "sleepy_end_device",
  "sleepyenddevice",
  "enddevice",
]);
const ROUTER_ROLES = new Set(["border_router", "border router", "leader", "router"]);
const THREAD_COLLECTION_FILE_PATTERNS = Object.freeze([
  /^td-otbr-cli-/,
  /^td-otbr-restapi-(devices-|diagnostics-fetch|mesh-diagnostics-|topology-)/,
  /^td-ha-matter-ws-(thread-border-routers|thread-diagnostics|network-topology|topology)/,
  /^Eve Thread Network Layout\.evethreadlayout$/,
]);

function hasEvidence(value) {
  if (value === null || value === undefined) return false;
  return typeof value !== "string" || value.trim() !== "";
}

function normalizeFactValue(label, value) {
  const text = toText(value).trim();
  if (label === "OMR Prefix" || label === "Mesh Local Prefix" || label === "Ext PAN ID") {
    return text.toLowerCase();
  }
  return text;
}

function collectFactMatches(value, filename, matches, depth = 0) {
  if (!value || typeof value !== "object" || depth > 8) return;
  const entries = Array.isArray(value)
    ? value.entries()
    : Object.entries(value);
  for (const [key, child] of entries) {
    const factDefinition = NETWORK_FACT_KEYS[key];
    if (factDefinition && (typeof child === "string" || typeof child === "number")) {
      const { label, priority } = factDefinition;
      const normalized = normalizeFactValue(label, child);
      if (normalized) {
        const group = matches.get(label) ?? new Map();
        const match = group.get(normalized) ?? { priority, sources: new Set() };
        match.priority = Math.min(match.priority, priority);
        match.sources.add(filename);
        group.set(normalized, match);
        matches.set(label, group);
      }
    }
    if (child && typeof child === "object") collectFactMatches(child, filename, matches, depth + 1);
  }
}

function factFromMatches(matches, label) {
  const values = matches.get(label);
  if (!values?.size) return { label, value: "n/a", sources: [] };
  const bestPriority = Math.min(...[...values.values()].map((match) => match.priority));
  const preferredValues = [...values.entries()].filter(([, match]) => match.priority === bestPriority);
  if (preferredValues.length > 1) {
    return {
      label,
      value: "Mixed",
      sources: [...new Set(preferredValues.flatMap(([, match]) => [...match.sources]))],
    };
  }
  const [[value, match]] = preferredValues;
  return { label, value, sources: [...match.sources] };
}

function rowRoleValues(row) {
  return [getColumnValue(row, "role"), getColumnValue(row, "type")]
    .map((value) => toText(value).trim().toLowerCase().replace(/[\s-]+/g, "_"))
    .filter(Boolean);
}

function declaredThreadFiles(entry) {
  return (entry?.files ?? []).filter((filename) =>
    THREAD_COLLECTION_FILE_PATTERNS.some((pattern) => pattern.test(filename))
    || (entry?.source === "thread-tools" && filename === "diagnostics.json"),
  );
}

function isDeclaredThreadRecord(row, entry, threadFiles) {
  if (!threadFiles.length) return false;
  const sourceFiles = getColumnValue(row, "_source_files")
    ?? getColumnValue(row, "sourceFiles");
  if (Array.isArray(sourceFiles)) return sourceFiles.some((filename) => threadFiles.includes(filename));
  if (typeof sourceFiles === "string") {
    return threadFiles.some((filename) => sourceFiles.split(",").map((part) => part.trim()).includes(filename));
  }
  return threadFiles.length === (entry?.files?.length ?? 0);
}

function isThreadDeviceRow(row, entry, threadFiles) {
  if (!row || typeof row !== "object") return false;
  if (isDeclaredThreadRecord(row, entry, threadFiles)) return true;
  if (THREAD_ROW_FIELDS.some((field) => hasEvidence(getColumnValue(row, field)))) return true;
  if (rowRoleValues(row).some((role) =>
    ROUTER_ROLES.has(role) || END_DEVICE_ROLES.has(role) || role === "reed",
  )) return true;
  return false;
}

function classifyThreadDevice(row) {
  const roles = rowRoleValues(row);
  const role = roles.find((value) => value) ?? "";
  const explicitBorderRouter = getColumnValue(row, "isBorderRouter");
  const explicitRouter = getColumnValue(row, "isRouter");
  const routerEligible = getColumnValue(row, "isRouterEligible") === true
    || getColumnValue(row, "routerEligible") === true
    || getColumnValue(row, "mode.routerEligible") === true
    || getColumnValue(row, "mode.isRouterEligible") === true
    || role === "reed"
    || toText(getColumnValue(row, "mode.device")).toUpperCase() === "REED";

  if (explicitBorderRouter === true) return "borderRouters";
  if (explicitRouter === true) return "routers";
  if (routerEligible) return "reed";
  if (explicitRouter === false) {
    const deviceMode = toText(getColumnValue(row, "mode.device")).toUpperCase();
    if (END_DEVICE_ROLES.has(role) || deviceMode === "MTD") return "endDevices";
    return null;
  }
  if (explicitBorderRouter === false && role === "border_router") return null;
  if (ROUTER_ROLES.has(role) || getRowRoleProjection(row).isRouter) return "routers";

  const deviceMode = toText(getColumnValue(row, "mode.device")).toUpperCase();
  if (deviceMode === "MTD" || ["end_device", "sleepy_end_device", "sleepyenddevice", "enddevice"].includes(role)) {
    return "endDevices";
  }
  if (role === "child" && deviceMode === "MTD") return "endDevices";
  return null;
}

function roleHolder(row) {
  const extAddress = toText(getColumnValue(row, "extAddress")).trim();
  const rloc16 = toText(getColumnValue(row, "rloc16")).trim();
  const sourceFiles = getColumnValue(row, "_source_files");
  return {
    record: row,
    deviceLabel: toText(getColumnValue(row, "deviceLabel")).trim() || "n/a",
    extAddress: extAddress || "n/a",
    rloc16: rloc16 || "n/a",
    threadVersion: toText(getColumnValue(row, "threadVersion")).trim() || "n/a",
    threadStackVersion: toText(getColumnValue(row, "threadStackVersion")).trim() || "n/a",
    sourceFiles: Array.isArray(sourceFiles) ? sourceFiles.map(toText) : [],
    canSelect: Boolean(extAddress || rloc16),
  };
}

function relationshipCapabilityPresent(adaptorResult) {
  const capabilities = adaptorResult?.relationshipCapabilities;
  return (capabilities?.datasetWide?.size ?? 0) > 0
    || (capabilities?.byDeviceId?.size ?? 0) > 0;
}

function edgeLqiLevel(edge) {
  const level = Number(edge?.lqLevel);
  return Number.isInteger(level) && level >= 1 && level <= 3 ? level : null;
}

function summarizeLinks(rows, adaptorResult) {
  const edges = Array.isArray(adaptorResult?.edgeData)
    ? adaptorResult.edgeData.filter((edge) => edge?.baseHidden !== true)
    : [];
  const supported = edges.length > 0 || relationshipCapabilityPresent(adaptorResult);
  if (!supported) {
    return {
      total: "n/a",
      lqiSupported: false,
      lqi: { 1: { count: "n/a", percent: "n/a" }, 2: { count: "n/a", percent: "n/a" }, 3: { count: "n/a", percent: "n/a" } },
    };
  }

  const uniqueLinks = new Map();
  edges.forEach((edge) => {
    if (edge?.from === undefined || edge?.to === undefined) return;
    const endpoints = [String(edge.from).toLowerCase(), String(edge.to).toLowerCase()].sort();
    if (endpoints[0] === endpoints[1]) return;
    const key = `${endpoints[0]}\u0000${endpoints[1]}`;
    const link = uniqueLinks.get(key) ?? { levels: new Set() };
    const level = edgeLqiLevel(edge);
    if (level !== null) link.levels.add(level);
    uniqueLinks.set(key, link);
  });

  const lqiSupported = [...uniqueLinks.values()].some((link) => link.levels.size > 0);
  const lqiCounts = { 1: 0, 2: 0, 3: 0 };
  uniqueLinks.forEach((link) => {
    if (link.levels.size === 1) lqiCounts[[...link.levels][0]] += 1;
  });
  const total = uniqueLinks.size;
  return {
    total,
    lqiSupported,
    lqi: Object.fromEntries([1, 2, 3].map((level) => [level, {
      count: lqiSupported ? lqiCounts[level] : "n/a",
      percent: lqiSupported && total > 0
        ? Number(((lqiCounts[level] / total) * 100).toFixed(1))
        : "n/a",
    }])),
  };
}

function isReedDevice(row) {
  const roles = rowRoleValues(row);
  const role = roles.find(Boolean) ?? "";
  const deviceMode = toText(getColumnValue(row, "mode.device")).toUpperCase();
  return getColumnValue(row, "isRouterEligible") === true
    || getColumnValue(row, "routerEligible") === true
    || getColumnValue(row, "mode.routerEligible") === true
    || getColumnValue(row, "mode.isRouterEligible") === true
    || role === "reed"
    || deviceMode === "REED"
    || (role === "child" && deviceMode === "FTD");
}

function countValue(value) {
  if (value === null || value === undefined || value === "") return "n/a";
  return Number.isFinite(Number(value)) ? Number(value) : "n/a";
}

function summarizeDeviceCounts(threadRows, summaryCounts) {
  if (!summaryCounts) return null;
  const reedSupported = threadRows.some((row) => {
    const role = rowRoleValues(row).find(Boolean) ?? "";
    const deviceMode = toText(getColumnValue(row, "mode.device")).toUpperCase();
    return typeof getColumnValue(row, "isRouterEligible") === "boolean"
      || typeof getColumnValue(row, "routerEligible") === "boolean"
      || typeof getColumnValue(row, "mode.routerEligible") === "boolean"
      || typeof getColumnValue(row, "mode.isRouterEligible") === "boolean"
      || role === "reed"
      || deviceMode === "REED"
      || (role === "child" && deviceMode === "FTD");
  });
  return {
    total: countValue(summaryCounts.devices),
    borderRouters: countValue(summaryCounts.borderRouters),
    routers: countValue(summaryCounts.routers),
    reed: reedSupported ? threadRows.filter(isReedDevice).length : "n/a",
    endDevices: countValue(summaryCounts.children),
  };
}

function summarizeStatusLinks(summaryCounts) {
  if (!summaryCounts) return null;
  const total = countValue(summaryCounts.links);
  return {
    total,
    lqiSupported: true,
    lqi: Object.fromEntries([1, 2, 3].map((level) => {
      const count = countValue(summaryCounts[`lq${level}`]);
      return [level, {
        count,
        percent: typeof total === "number" && total > 0 && typeof count === "number"
          ? Number(((count / total) * 100).toFixed(1))
          : "n/a",
      }];
    })),
  };
}

export function buildThreadNetworkModel(dataset, capabilities, adaptorResult, summaryCounts = null) {
  const loaded = Boolean(dataset?.entry && Array.isArray(dataset.loadedFiles) && dataset.loadedFiles.length);
  const rows = loaded && Array.isArray(dataset.rows) ? dataset.rows : [];
  const auxiliaryFiles = loaded && dataset.auxiliaryFiles && typeof dataset.auxiliaryFiles === "object"
    ? dataset.auxiliaryFiles
    : {};
  const fileNames = loaded
    ? [...new Set([...dataset.loadedFiles, ...Object.keys(auxiliaryFiles)])]
    : [];
  const networkInstance = resolveNetworkInstance(fileNames, capabilities);
  const matches = new Map();
  if (loaded) {
    const entryFiles = dataset.entry.files ?? [];
    entryFiles.forEach((filename, index) => {
      const payload = dataset.rawFiles?.[index];
      if (payload !== null && payload !== undefined && fileNames.includes(filename)) {
        collectFactMatches(payload, filename, matches);
      }
    });
    Object.entries(auxiliaryFiles).forEach(([filename, payload]) => {
      collectFactMatches(payload, filename, matches);
    });
  }

  const sourceExtPanFact = factFromMatches(matches, "Ext PAN ID");
  const extPanFact = networkInstance.status === "mixed"
    ? { label: "Ext PAN ID", value: "Mixed", sources: networkInstance.sources }
    : networkInstance.extPanId
      ? { label: "Ext PAN ID", value: networkInstance.extPanId, sources: networkInstance.sources, provenance: networkInstance.provenance }
      : sourceExtPanFact;
  const networkFacts = [
    factFromMatches(matches, "Name"),
    extPanFact,
    factFromMatches(matches, "OMR Prefix"),
    factFromMatches(matches, "Mesh Local Prefix"),
    factFromMatches(matches, "Channel"),
  ];

  const threadFiles = declaredThreadFiles(dataset?.entry);
  const threadRows = rows.filter((row) => isThreadDeviceRow(row, dataset?.entry, threadFiles));
  const roleClasses = threadRows.map(classifyThreadDevice);
  const hasUnclassified = roleClasses.some((roleClass) => roleClass === null);
  const derivedDeviceCounts = {
    total: threadRows.length ? threadRows.length : "n/a",
    borderRouters: threadRows.length && !hasUnclassified
      ? roleClasses.filter((roleClass) => roleClass === "borderRouters").length : "n/a",
    routers: threadRows.length && !hasUnclassified
      ? roleClasses.filter((roleClass) => roleClass === "routers").length : "n/a",
    reed: threadRows.length && !hasUnclassified
      ? roleClasses.filter((roleClass) => roleClass === "reed").length : "n/a",
    endDevices: threadRows.length && !hasUnclassified
      ? roleClasses.filter((roleClass) => roleClass === "endDevices").length : "n/a",
  };
  const deviceCounts = summarizeDeviceCounts(threadRows, summaryCounts) ?? derivedDeviceCounts;
  const links = summarizeStatusLinks(summaryCounts) ?? summarizeLinks(rows, adaptorResult);
  const roleHolders = {
    leaders: rows.filter((row) => row?.isLeader === true).map(roleHolder),
    primaryBbrs: rows.filter((row) => row?.isPrimaryBBR === true).map(roleHolder),
  };

  return {
    loaded,
    datasetLabel: loaded ? toText(dataset.entry.label) : "",
    networkFacts,
    deviceCounts,
    links,
    roleHolders,
  };
}