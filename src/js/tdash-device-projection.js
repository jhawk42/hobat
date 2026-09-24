import { getDeviceIdentityKeys, normalizeInputRecord } from "./tdash-device-fields.js";
import { computeTopologyCapabilities } from "./tdash-filters.js";
import { getColumnValue, toFiniteNumber, toText } from "./tdash-utils.js";

const relationshipPaths = ["children", "childTable", "routerNeighbors"];
const metricPaths = [
  "frameErrorRate", "messageErrorRate", "averageRssi", "linkMargin",
  "queuedMessageCount", "linkQuality",
];

function hasNumber(value) {
  return Number.isFinite(toFiniteNumber(value));
}

function metricPresent(metrics, path, field) {
  return metrics[path][field].length > 0;
}

function canonicalMetricPresent(row, path, field) {
  const records = getColumnValue(row, path);
  return Array.isArray(records) && records.some((record) => hasNumber(record?.[field]));
}

function deriveDiagnostics(row, metrics, deviceType, isRouter, isBorderRouter, isReed, relationships) {
  const mac = (field) => hasNumber(getColumnValue(row, `macCounters.${field}`));
  const mle = (field) => hasNumber(getColumnValue(row, `mleCounters.${field}`));
  const time = (field) => hasNumber(getColumnValue(row, `timeStatistics.${field}`));
  const children = Array.isArray(getColumnValue(row, "children")) ? getColumnValue(row, "children") : [];
  return {
    hasFtdNodes: deviceType === "FTD",
    hasMtdNodes: deviceType === "MTD",
    hasReedNodes: isReed,
    hasRouters: isRouter,
    hasBorderRouters: isBorderRouter,
    hasRoutersWithChildren: isRouter && (relationships.children > 0 || relationships.totalChildren > 0),
    hasRoutersWithoutChildren: isRouter && relationships.children === 0 && relationships.totalChildren <= 0,
    hasFieldMacTotalErrorsPct: mac("ifinerrors_pct") || mac("ifouterrors_pct"),
    hasFieldMacDiscardPct: mac("ifindiscards_pct"),
    hasFieldPartitionChanges: mle("partIdChangesCount") || mle("partitionidchanges"),
    hasFieldParentChanges: mle("newParentCount") || mle("parentchanges"),
    hasNeighborFrameErrRate: canonicalMetricPresent(row, "routerNeighbors", "frameErrorRate"),
    hasNeighborMsgErrRate: canonicalMetricPresent(row, "routerNeighbors", "messageErrorRate"),
    hasNeighborRss: metricPresent(metrics, "routerNeighbors", "averageRssi"),
    hasLinkQualityDistribution: hasNumber(getColumnValue(row, "links3")) && hasNumber(getColumnValue(row, "totalLinks")),
    hasChildLinkQuality: children.some((child) => Number.isFinite(Number.parseInt(child?.lq ?? child?.linkQuality, 10))),
    hasChildFrameErrRate: canonicalMetricPresent(row, "childTable", "frameErrorRate"),
    hasChildMsgErrRate: canonicalMetricPresent(row, "childTable", "messageErrorRate"),
    hasChildRss: metricPresent(metrics, "childTable", "averageRssi"),
    hasChildRssMargin: metricPresent(metrics, "childTable", "linkMargin"),
    hasChildQueuedMsgs: metrics.childTable.queuedMessageCount.some((value) => value > 0),
    hasFieldMacTotalErrorsRatio: mac("ifTotalErrorsTotalPktsRatio"),
    hasFieldMacTotalDiscardsRatio: mac("ifTotalDiscardsTotalPktsRatio"),
    hasFieldBetterPartitionAttach: mle("betterPartIdAttachAttemptsCount"),
    hasFieldTotalParentPartitionChanges: mle("totalParentPartitionChangesCount"),
    hasFieldRouterPct: time("routerPct"),
    hasFieldDetachedDisabledPct: time("detachedDisabledPct"),
  };
}

export function buildDeviceProjection(row, index = 0) {
  const deviceId = getDeviceIdentityKeys(row)[0] ?? `row:${index}`;
  const rloc16 = toText(getColumnValue(row, "rloc16")).toLowerCase();
  const role = toText(getColumnValue(row, "role")).toLowerCase();
  const explicitRouter = getColumnValue(row, "isRouter");
  const roleRouter = ["router", "leader", "border router"].includes(role);
  const hasRole = typeof explicitRouter === "boolean" || role.length > 0;
  const derivedRouter = rloc16.startsWith("0x") && rloc16.endsWith("00") && rloc16.length === 6;
  const isRouter = typeof explicitRouter === "boolean" ? explicitRouter : hasRole ? roleRouter : derivedRouter;
  const roleEvidence = typeof explicitRouter === "boolean" || role.length > 0
    ? "explicit" : derivedRouter ? "rloc16-derived" : "none";
  const deviceType = toText(getColumnValue(row, "mode.device")).toUpperCase();
  const relationships = Object.fromEntries(relationshipPaths.map((path) => {
    const value = getColumnValue(row, path);
    return [path, Array.isArray(value) ? value.length : 0];
  }));
  relationships.totalChildren = toFiniteNumber(getColumnValue(row, "totalChildren")) || 0;
  const metrics = Object.fromEntries(relationshipPaths.map((path) => {
    const value = getColumnValue(row, path);
    const items = Array.isArray(value) ? value : [];
    return [path, Object.fromEntries(metricPaths.map((field) => [field,
      items.map((item) => toFiniteNumber(normalizeInputRecord(item, { canonicalMetrics: true })?.[field]))
        .filter(Number.isFinite),
    ]))];
  }));
  const normalizedType = ["FTD", "MTD", "REED"].includes(deviceType) ? deviceType : "unknown";
  const isBorderRouter = getColumnValue(row, "isBorderRouter") === true;
  const isReed = deviceType === "FTD" && (role ? role === "child" : !isRouter && !isBorderRouter);
  const diagnostics = deriveDiagnostics(row, metrics, normalizedType, derivedRouter,
    derivedRouter && isBorderRouter, deviceType === "FTD" && (role ? role === "child" : !derivedRouter && !isBorderRouter), relationships);
  return {
    deviceId,
    extAddress: toText(getColumnValue(row, "extAddress")),
    rloc16,
    omrIpv6Address: toText(getColumnValue(row, "omrIpv6Address")),
    deviceType: normalizedType,
    isRouter,
    isLeader: getColumnValue(row, "isLeader") === true || role === "leader",
    isBorderRouter,
    isReed,
    roleEvidence,
    relationships,
    metrics,
    diagnostics,
  };
}

export function buildDeviceProjections(rows) {
  const projections = new Map();
  rows.forEach((row, index) => {
    const projection = buildDeviceProjection(row, index);
    projections.set(projections.has(projection.deviceId) ? `${projection.deviceId}#${index}` : projection.deviceId, projection);
  });
  return projections;
}

export function projectAdaptorNode(projection, node) {
  const deviceType = toText(node.mode_device).toUpperCase();
  const isRouter = node.isRouter === true;
  const isBorderRouter = node.isBorderRouter === true;
  const role = toText(node.role).trim().toLowerCase();
  const { edgeCategories, ...diagnostics } = computeTopologyCapabilities([node], []);
  return {
    ...projection,
    deviceType: ["FTD", "MTD"].includes(deviceType) ? deviceType : "unknown",
    isRouter,
    isBorderRouter,
    isReed: deviceType === "FTD" && (role ? role === "child" : !isRouter && !isBorderRouter),
    relationships: { ...projection.relationships, children: node.hasChildren === true ? 1 : 0,
      totalChildren: 0 },
    roleEvidence: projection.isRouter === isRouter ? projection.roleEvidence : "adaptor",
    diagnostics,
  };
}