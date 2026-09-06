import {
  toText,
  toFiniteNumber,
  getColumnValue,
  getCanonicalExtaddr,
  getCanonicalOmrIpv6Address,
  areNodeIdsEquivalent,
} from "./tdash-utils.js";
import { normalizeLinkCategories } from "./tdash-filters.js";
import {
  EDGE_LQ_STYLES,
  NODE_COLORS,
  NODE_SHAPES,
  ISOLATED_ANCHOR_PRESET_A,
  getIsolatedAnchorPreset,
  getIsolatedAnchorPresetLabel,
} from "./tdash-constants.js";
import { EDGE_CATEGORY_LABELS } from "./tdash-constants.js";

let _isolatedAnchorPresetName = ISOLATED_ANCHOR_PRESET_A;

function normalizedTopologyNodeId(value) {
  return toText(value).toLowerCase();
}

export function topologyEndpointPairKey(sourceId, targetId, directed = false) {
  const source = normalizedTopologyNodeId(sourceId);
  const target = normalizedTopologyNodeId(targetId);
  if (!source || !target) return "";
  return directed ? `${source}\u0000${target}` : [source, target].sort().join("\u0000");
}

export function buildTopologyEdgeIndexes(edgeData) {
  const byEndpointPair = new Map();
  const incidentByNodeId = new Map();
  const byCategory = new Map();

  const append = (index, key, edge) => {
    if (!index.has(key)) index.set(key, []);
    index.get(key).push(edge);
  };

  for (const edge of Array.isArray(edgeData) ? edgeData : []) {
    const sourceId = normalizedTopologyNodeId(edge?.from);
    const targetId = normalizedTopologyNodeId(edge?.to);
    if (!sourceId || !targetId) continue;
    const pairKey = topologyEndpointPairKey(sourceId, targetId, edge.directed === true);
    append(byEndpointPair, pairKey, edge);
    append(incidentByNodeId, sourceId, edge);
    if (targetId !== sourceId) append(incidentByNodeId, targetId, edge);
    for (const category of new Set(normalizeLinkCategories(edge.linkCategories))) {
      append(byCategory, category, edge);
    }
  }

  return { byEndpointPair, incidentByNodeId, byCategory };
}

export function expandVisibleRelationship(
  match,
  indexes,
  visibleNodeIds,
  forcedEdgeIds,
) {
  const pairKey = topologyEndpointPairKey(match?.sourceId, match?.targetId, match?.directed === true);
  if (!pairKey) return { matchedEdgeCount: 0, expanded: false };
  const candidates = indexes?.byEndpointPair?.get(pairKey) ?? [];
  let matchedEdgeCount = 0;

  for (const edge of candidates) {
    if (edge.baseHidden === true) continue;
    if (!normalizeLinkCategories(edge.linkCategories).includes(match.category)) continue;
    const forward = areNodeIdsEquivalent(edge.from, match.sourceId)
      && areNodeIdsEquivalent(edge.to, match.targetId);
    const reverse = match.directed !== true
      && areNodeIdsEquivalent(edge.to, match.sourceId)
      && areNodeIdsEquivalent(edge.from, match.targetId);
    if (!forward && !reverse) continue;
    visibleNodeIds.add(match.sourceId);
    visibleNodeIds.add(match.targetId);
    if (edge.id !== undefined && edge.id !== null) forcedEdgeIds.add(edge.id);
    matchedEdgeCount += 1;
  }

  return { matchedEdgeCount, expanded: matchedEdgeCount > 0 };
}

export function setIsolatedAnchorPreset(name) {
  const key = typeof name === "string" ? name.toLowerCase() : "";
  _isolatedAnchorPresetName = key || ISOLATED_ANCHOR_PRESET_A;
}

export function getIsolatedAnchorPresetName() {
  return _isolatedAnchorPresetName;
}

export function getIsolatedAnchorPresetStatusLabel() {
  return getIsolatedAnchorPresetLabel(_isolatedAnchorPresetName);
}

// ── Node-id selection ─────────────────────────────────────────────────────────

export function chooseNodeId(node, fallbackPrefix, index) {
  const rloc16 = toText(node.rloc16);
  if (rloc16) return rloc16;
  const idField = toText(node.id);
  if (idField) return idField;
  const extAddr = getCanonicalExtaddr(node);
  if (extAddr) return extAddr;
  const omrIpv6Addr = getCanonicalOmrIpv6Address(node);
  if (omrIpv6Addr) return omrIpv6Addr;
  return `${fallbackPrefix}-${index}`;
}

// ── Node label builder ────────────────────────────────────────────────────────

export function buildLabel(node) {
  const nodeName =
    toText(node.deviceLabel) || toText(node.device_label) || toText(node.name) || "found node";
  const rloc16 = toText(node.rloc16) || "rloc16:not_found";
  return `${nodeName}\n${rloc16}`;
}

export function isUnknownNodeName(nodeName) {
  const normalizedName = toText(nodeName).toLowerCase();
  return normalizedName.startsWith("unknown") || normalizedName.startsWith("found-");
}

// ── Link Quality style helpers ───────────────────────────────────────────────

export function lqStyleFromField(field) {
  if (field === "3_links") return EDGE_LQ_STYLES.high;
  if (field === "2_links") return EDGE_LQ_STYLES.medium;
  if (field === "1_links") return EDGE_LQ_STYLES.low;
  return EDGE_LQ_STYLES.none;
}

// scale = 255  → Eve-enhanced (0–255 range)
// scale = 3    → Eve-native / Thread route quality (0–3 range)
export function lqStyleFromAvgLqi(avgLqi, scale) {
  if (!Number.isFinite(avgLqi)) return EDGE_LQ_STYLES.none;
  if (scale === 3) {
    if (avgLqi >= 3) return EDGE_LQ_STYLES.high;
    if (avgLqi >= 2) return EDGE_LQ_STYLES.medium;
    return EDGE_LQ_STYLES.low;
  }
  // default: 0–255 scale
  if (avgLqi >= 200) return EDGE_LQ_STYLES.high;
  if (avgLqi >= 128) return EDGE_LQ_STYLES.medium;
  return EDGE_LQ_STYLES.low;
}

// linkMargin in dB: higher = better link quality
// Typical values: 0–80 dB; >20 dB is good, >40 dB is excellent
export function lqStyleFromLinkMargin(linkMargin) {
  const margin = toFiniteNumber(linkMargin);
  if (!Number.isFinite(margin)) return EDGE_LQ_STYLES.noLqPurple;
  if (margin >= 40) return EDGE_LQ_STYLES.high;
  if (margin >= 20) return EDGE_LQ_STYLES.medium;
  if (margin >= 10) return EDGE_LQ_STYLES.low;
  return EDGE_LQ_STYLES.noLqPurple;
}

// ── Edge builder ──────────────────────────────────────────────────────────────
//
// Inserts or merges a directed edge into edgeMap/edgeData.
// - Duplicate undirected edges (same {from,to} pair regardless of order) are
//   merged: widths are max'd, linkCategories are unioned.
// - edgeKeySuffix in style creates a distinct key so multiple edge types
//   between the same pair can co-exist.

function lqiBarSuffix(lqiValue) {
  const level = toFiniteNumber(lqiValue);
  if (!Number.isFinite(level)) return "";
  if (level >= 3) return " ▂▄▆";
  if (level >= 2) return " ▂▄";
  if (level >= 1) return "  ▂";
  return "  _";
}

function linkMarginBarSuffix(linkMarginValue) {
  const margin = toFiniteNumber(linkMarginValue);
  if (!Number.isFinite(margin)) return "";
  if (margin > 30) return " ▂▄▆█";
  if (margin >= 20) return " ▂▄▆";
  if (margin >= 10) return " ▂▄";
  return " ▂";
}

export function buildEdgeTitle(edgeStyle) {
  const edgeType =
    Array.isArray(edgeStyle.linkCategories) && edgeStyle.linkCategories.length > 0
      ? `${edgeStyle.linkCategories.join(", ")}`
      : null;

  const edgeTypeReadable = edgeType
    ? `type: ${edgeType
        .split(", ")
        .map((category) => EDGE_CATEGORY_LABELS[category] ?? category)
        .join(", ")}`
    : null;

  const lqi = toFiniteNumber(edgeStyle.lqLevel ?? edgeStyle.lqi);
  const lqiIn = toFiniteNumber(edgeStyle.lqiIn);
  const lqiOut = toFiniteNumber(edgeStyle.lqiOut);
  const linkMargin = toFiniteNumber(edgeStyle.linkMargin);
  const averageRssi = toFiniteNumber(edgeStyle.averageRssi);
  const lastRssi = toFiniteNumber(edgeStyle.lastRssi);
  const frameErrorRate = toFiniteNumber(edgeStyle.frameErrorRate);
  const messageErrorRate = toFiniteNumber(edgeStyle.messageErrorRate);
  const routeCost = toFiniteNumber(edgeStyle.routeCost);
  const edgeFrom = toText(edgeStyle.edgeFromTitle)
    ? `from: ${toText(edgeStyle.edgeFromTitle)}`
    : null;
  const edgeTo = toText(edgeStyle.edgeToTitle)
    ? `to: ${toText(edgeStyle.edgeToTitle)}`
    : null;
  const titleParts = [
    edgeTypeReadable,
    edgeFrom,
    edgeTo,
    Number.isFinite(lqiOut)
      ? `LQI out: ${lqiOut}${lqiBarSuffix(lqiOut)}`
      : null,
    Number.isFinite(lqiIn)
      ? `LQI in: ${lqiIn}${lqiBarSuffix(lqiIn)}`
      : null,
    Number.isFinite(lqi) ? `LQI: ${lqi}${lqiBarSuffix(lqi)}` : null,
    Number.isFinite(linkMargin)
      ? `Link margin: ${linkMargin} dB${linkMarginBarSuffix(linkMargin)}`
      : null,
    Number.isFinite(averageRssi) ? `Average RSSI: ${averageRssi} dBm` : null,
    Number.isFinite(lastRssi) ? `Last RSSI: ${lastRssi} dBm` : null,
    Number.isFinite(frameErrorRate) ? `Frame error rate: ${frameErrorRate}%` : null,
    Number.isFinite(messageErrorRate) ? `Message error rate: ${messageErrorRate}%` : null,
    Number.isFinite(routeCost) ? `Route cost: ${routeCost}` : null,
  ].filter(Boolean);
  return titleParts.join("\n");
}

export function addEdge(edgeMap, edgeData, from, to, style) {
  if (!from || !to || from === to) return;

  const suffix = toText(style.edgeKeySuffix);
  const keyBase = [from, to].sort().join("|");
  const key = suffix ? `${keyBase}|${suffix}` : keyBase;
  const existing = edgeMap.get(key);
  if (existing) {
    if (Number.isFinite(style.width))
      existing.width = Math.max(existing.width || 0, style.width);
    const merged = new Set([
      ...normalizeLinkCategories(existing.linkCategories),
      ...normalizeLinkCategories(style.linkCategories),
    ]);
    existing.linkCategories = Array.from(merged);
    if (style.isParentChild === true) existing.isParentChild = true;
    if (Number.isFinite(style.lqiIn)) existing.lqiIn = style.lqiIn;
    if (Number.isFinite(style.lqiOut)) existing.lqiOut = style.lqiOut;
    if (toText(style.edgeFromTitle)) existing.edgeFromTitle = toText(style.edgeFromTitle);
    if (toText(style.edgeToTitle)) existing.edgeToTitle = toText(style.edgeToTitle);
    if (
      Number.isFinite(style.linkMargin) &&
      !Number.isFinite(existing.linkMargin)
    ) {
      existing.linkMargin = style.linkMargin;
    }
    if (
      style.lqLevel !== undefined &&
      (existing.lqLevel === undefined || style.lqLevel > existing.lqLevel)
    ) {
      existing.lqLevel = style.lqLevel;
      existing.color = style.color;
      existing.dashes = style.dashes;
    }
    existing.title = buildEdgeTitle(existing);
    return;
  }

  // Build title to include edgeType and LQI level if present
  // Include lqi in and out if present, as well as link margin if present
  // Include lqLevel even if it's 0, to distinguish from undefined
  // Include edge type if present in style.linkCategories
  const title = buildEdgeTitle(style);

  const { edgeKeySuffix: _s, ...edgeStyle } = style;
  const edge = { from, to, title, ...edgeStyle };
  edge.id = key;
  edge.baseHidden = style.hidden === true;
  edge.linkCategories = normalizeLinkCategories(style.linkCategories);
  edgeMap.set(key, edge);
  edgeData.push(edge);
}

// ── RLOC16 arithmetic ─────────────────────────────────────────────────────────

export function buildMainRouterRloc16(routeId) {
  const n = toFiniteNumber(routeId);
  if (!Number.isFinite(n)) return "";
  return `0x${(n << 10).toString(16).padStart(4, "0")}`;
}

export function buildChildRloc16(parentRloc16, childId) {
  const parentText = toText(parentRloc16).toLowerCase();
  const childNum = toFiniteNumber(childId);
  if (!parentText.startsWith("0x") || !Number.isFinite(childNum)) return "";
  const parentNum = Number.parseInt(parentText, 16);
  if (!Number.isFinite(parentNum)) return "";
  return `0x${(parentNum + childNum).toString(16).padStart(4, "0")}`;
}

// ── Router-neighbor statistics ────────────────────────────────────────────────

export function computeRouterNeighborStats(routerNeighborTable) {
  const rows = Array.isArray(routerNeighborTable) ? routerNeighborTable : [];
  let maxFrame, maxMsg, minRss, maxRss;
  let hasVeryLow = false,
    hasLow = false,
    hasMedium = false,
    hasHigh = false;
  rows.forEach((row) => {
    const fp = toFiniteNumber(row?.err_rate_frame_pct);
    if (Number.isFinite(fp))
      maxFrame = Number.isFinite(maxFrame) ? Math.max(maxFrame, fp) : fp;
    const mp = toFiniteNumber(row?.err_rate_msg_pct);
    if (Number.isFinite(mp))
      maxMsg = Number.isFinite(maxMsg) ? Math.max(maxMsg, mp) : mp;
    const rss = toFiniteNumber(row?.rss_ave);
    if (Number.isFinite(rss)) {
      minRss = Number.isFinite(minRss) ? Math.min(minRss, rss) : rss;
      maxRss = Number.isFinite(maxRss) ? Math.max(maxRss, rss) : rss;
      if (rss < -80) hasVeryLow = true;
      else if (rss >= -80 && rss < -70) hasLow = true;
      else if (rss >= -70 && rss <= -60) hasMedium = true;
      else if (rss > -60) hasHigh = true;
    }
  });
  return {
    router_neighbor_max_err_rate_frame_pct: maxFrame,
    router_neighbor_max_err_rate_msg_pct: maxMsg,
    router_neighbor_min_rss_ave: minRss,
    router_neighbor_max_rss_ave: maxRss,
    router_neighbor_has_rss_very_low: hasVeryLow,
    router_neighbor_has_rss_low: hasLow,
    router_neighbor_has_rss_medium: hasMedium,
    router_neighbor_has_rss_high: hasHigh,
  };
}

// ── Router-child statistics ───────────────────────────────────────────────────

export function computeRouterChildStats(routerChildTable) {
  const rows = Array.isArray(routerChildTable) ? routerChildTable : [];
  let maxFrame, maxMsg;
  let hasRssVeryLow = false,
    hasRssLow = false,
    hasRssMarginLow = false,
    hasQueuedMsgs = false;
  rows.forEach((row) => {
    const fp = toFiniteNumber(row?.err_rate_frame_pct);
    if (Number.isFinite(fp))
      maxFrame = Number.isFinite(maxFrame) ? Math.max(maxFrame, fp) : fp;
    const mp = toFiniteNumber(row?.err_rate_msg_pct);
    if (Number.isFinite(mp))
      maxMsg = Number.isFinite(maxMsg) ? Math.max(maxMsg, mp) : mp;
    const rss = toFiniteNumber(row?.rss_ave);
    if (Number.isFinite(rss)) {
      if (rss < -80) hasRssVeryLow = true;
      else if (rss >= -80 && rss < -70) hasRssLow = true;
    }
    const margin = toFiniteNumber(row?.rss_margin);
    if (Number.isFinite(margin) && margin < 20) hasRssMarginLow = true;
    const qMsg = toFiniteNumber(row?.q_msg);
    if (Number.isFinite(qMsg) && qMsg > 0) hasQueuedMsgs = true;
  });
  return {
    router_child_max_err_rate_frame_pct: maxFrame,
    router_child_max_err_rate_msg_pct: maxMsg,
    router_child_has_rss_very_low: hasRssVeryLow,
    router_child_has_rss_low: hasRssLow,
    router_child_has_rss_margin_low: hasRssMarginLow,
    router_child_has_queued_msgs: hasQueuedMsgs,
  };
}

// ── Isolated-node clustering ──────────────────────────────────────────────────
//
// Groups isolated (degree-0) nodes with phantom hidden edges to keep the
// layout tidy.  Returns a nodeDegree Map for optional use by callers.

export function groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap, presetName = _isolatedAnchorPresetName) {
  const preset = getIsolatedAnchorPreset(presetName);
  const nodeDegree = new Map();
  for (const edge of edgeData) {
    nodeDegree.set(edge.from, (nodeDegree.get(edge.from) || 0) + 1);
    nodeDegree.set(edge.to, (nodeDegree.get(edge.to) || 0) + 1);
  }
  const connectedAnchorId = (function chooseConnectedAnchorId() {
    const knownCandidates = nodeData
      .filter((n) => n.group !== "unknown" && (nodeDegree.get(n.id) || 0) > 0)
      .sort(
        (a, b) => (nodeDegree.get(b.id) || 0) - (nodeDegree.get(a.id) || 0),
      );
    return knownCandidates.length > 0 ? knownCandidates[0].id : "";
  })();

  function clusterIsolatedNodeIds(nodeIds, options = {}) {
    if (nodeIds.length === 0) return;
    const { clusterLength = 80, anchorLength = 180, anchorId = "" } = options;

    if (nodeIds.length > 1) {
      const anchorNodeId = nodeIds[0];
      for (let i = 1; i < nodeIds.length; i += 1) {
        addEdge(edgeMap, edgeData, anchorNodeId, nodeIds[i], {
          hidden: true,
          physics: true,
          length: clusterLength,
          color: { opacity: 0 },
        });
      }
    }

    if (anchorId) {
      addEdge(edgeMap, edgeData, nodeIds[0], anchorId, {
        hidden: true,
        physics: true,
        length: anchorLength,
        color: { opacity: 0 },
      });
    }
  }

  const unknownIds = nodeData
    .filter((n) => n.group === "unknown" && (nodeDegree.get(n.id) || 0) === 0)
    .map((n) => n.id);
  clusterIsolatedNodeIds(unknownIds, {
    clusterLength: preset.unknown.clusterLength,
    anchorLength: preset.unknown.anchorLength,
    anchorId: connectedAnchorId,
  });

  const knownIsolatedIds = nodeData
    .filter((n) => n.group !== "unknown" && (nodeDegree.get(n.id) || 0) === 0)
    .map((n) => n.id);
  clusterIsolatedNodeIds(knownIsolatedIds, {
    clusterLength: preset.known.clusterLength,
    anchorLength: preset.known.anchorLength,
    anchorId: connectedAnchorId,
  });

  return nodeDegree;
}

// ── Vis-node data builder ─────────────────────────────────────────────────────

export function buildVisNodeData(
  nodeMap,
  routerIdsWithChildren,
  routerNeighborByRloc16,
  labelFn,
  routerChildByRloc16 = new Map(),
) {
  return Array.from(nodeMap.values()).map((node) => {
    const displayName = toText(node.deviceLabel) || toText(node.device_label) || toText(node.name);
    const rloc16Text = toText(node.rloc16).toLowerCase();
    const modeDevice = toText(node.modeDevice || node.mode_device).toUpperCase();
    const neighborStats = computeRouterNeighborStats(
      getColumnValue(routerNeighborByRloc16.get(rloc16Text) || {}, "routerNeighbors")
      ?? getColumnValue(routerNeighborByRloc16.get(rloc16Text) || {}, "router_neighbor_table"),
    );
    const childTableRow = routerChildByRloc16.get(rloc16Text);
    const childStats = computeRouterChildStats(
      getColumnValue(childTableRow || {}, "childTable")
      ?? getColumnValue(childTableRow || {}, "router_child_table"),
    );
    const hasChildren = routerIdsWithChildren.has(node.id);
    const isRouter =
      node.isRouter === true ||
      node.is_router === true ||
      rloc16Text.endsWith("00") ||
      toText(node.type).toLowerCase() === "router" ||
      toText(node.role).toLowerCase() === "router";
    const isBorderRouter =
      (isRouter && (node.br === true || node.isBorderRouter === true || node.is_border_router === true)) ||
      toText(node.role).toLowerCase() === "border router";
    const unknown = isUnknownNodeName(displayName) && !isRouter && !isBorderRouter;
    const isChildFtd = !isRouter && modeDevice === "FTD";
    const isChildMtd = !isRouter && modeDevice === "MTD";
    const effectiveShape = unknown
      ? NODE_SHAPES.unknown
      : (isBorderRouter
        ? NODE_SHAPES.borderRouter
        : (isRouter
          ? NODE_SHAPES.router
          : (isChildFtd
            ? NODE_SHAPES.childFtd
            : (isChildMtd ? NODE_SHAPES.childMtd : NODE_SHAPES.child))));
    
    let borderWidth = 1;
    let fontSize = 13;
    let size = 27;
    let widthConstraint = { minimum: 70, maximum: 200 };
    let heightConstraint = { minimum: 26, maximum: 26 };
    if (isBorderRouter) {
      borderWidth = 5;
      fontSize = 19.5;
      size = 45;
    } else if (isRouter) {
      borderWidth = 3;
      fontSize = 19.5;
      size = 45;
    }
    const font = buildNodeLabelFont({ fontSize, isRouter });
    // Enforce role-based color independently from shape strings.
    const effectiveColor = unknown
      ? (node.color || NODE_COLORS.unknown)
      : ((!isRouter && !isBorderRouter)
        ? NODE_COLORS.child
        : node.color);
    return {
      id: node.id,
      label: labelFn(node),
      shape: effectiveShape,
      size,
      color: effectiveColor ? { ...effectiveColor } : effectiveColor,
      font,
      heightConstraint,
      widthConstraint,
      group: unknown ? "unknown" : "known",
      isRouter,
      hasChildren,
      isBorderRouter,
      role: toText(node.role).trim().toLowerCase(),
      borderWidth,
      ifInDiscardsPct: node.ifInDiscardsPct ?? node.ifindiscards_pct,
      ifInErrorsPct: node.ifInErrorsPct ?? node.ifinerrors_pct,
      ifOutErrorsPct: node.ifOutErrorsPct ?? node.ifouterrors_pct,
      ifindiscards_pct: node.ifindiscards_pct ?? node.ifInDiscardsPct,
      ifinerrors_pct: node.ifinerrors_pct ?? node.ifInErrorsPct,
      ifouterrors_pct: node.ifouterrors_pct ?? node.ifOutErrorsPct,
      ifTotalErrorsTotalPktsRatio:
        node.ifTotalErrorsTotalPktsRatio ?? node.iftotalerrors_totalpkts_ratio,
      ifTotalDiscardsTotalPktsRatio:
        node.ifTotalDiscardsTotalPktsRatio ?? node.iftotaldiscards_totalpkts_ratio,
      iftotalerrors_totalpkts_ratio:
        node.iftotalerrors_totalpkts_ratio ?? node.ifTotalErrorsTotalPktsRatio,
      iftotaldiscards_totalpkts_ratio:
        node.iftotaldiscards_totalpkts_ratio ?? node.ifTotalDiscardsTotalPktsRatio,
      modeDevice: node.modeDevice ?? node.mode_device,
      mode_device: node.mode_device ?? node.modeDevice,
      totalLink3: node.totalLink3 ?? node.total_link_3,
      total_link_3: node.total_link_3,
      totalLink2: node.totalLink2 ?? node.total_link_2,
      total_link_2: node.total_link_2,
      totalLink1: node.totalLink1 ?? node.total_link_1,
      total_link_1: node.total_link_1,
      lq3Ratio: node.lq3Ratio ?? node.lq3_ratio,
      lq3_ratio: node.lq3_ratio,
      lq1Ratio: node.lq1Ratio ?? node.lq1_ratio,
      lq1_ratio: node.lq1_ratio,
      hasChildLqMedium: node.hasChildLqMedium ?? node.has_child_lq_medium,
      hasChildLqPoor: node.hasChildLqPoor ?? node.has_child_lq_poor,
      has_child_lq_medium: node.has_child_lq_medium ?? node.hasChildLqMedium,
      has_child_lq_poor: node.has_child_lq_poor ?? node.hasChildLqPoor,
      partIdChangesCount:
        node.partIdChangesCount ?? node.partitionIdChanges ?? node.partitionidchanges,
      newParentCount: node.newParentCount ?? node.parentChanges ?? node.parentchanges,
      betterPartIdAttachAttemptsCount:
        node.betterPartIdAttachAttemptsCount
        ?? node.betterPartitionAttachAttempts
        ?? node.betterpartitionattachattempts,
      totalParentPartitionChangesCount:
        node.totalParentPartitionChangesCount
        ?? node.totalParentPartitionChanges
        ?? node.totalparentpartitionchanges,
      partitionidchanges:
        node.partitionidchanges ?? node.partIdChangesCount ?? node.partitionIdChanges,
      parentchanges: node.parentchanges ?? node.newParentCount ?? node.parentChanges,
      betterpartitionattachattempts:
        node.betterpartitionattachattempts
        ?? node.betterPartIdAttachAttemptsCount
        ?? node.betterPartitionAttachAttempts,
      totalparentpartitionchanges:
        node.totalparentpartitionchanges
        ?? node.totalParentPartitionChangesCount
        ?? node.totalParentPartitionChanges,
      routerPct: node.routerPct ?? node.router_pct,
      detachedDisabledPct: node.detachedDisabledPct ?? node.detached_disabled_pct,
      router_pct: node.router_pct ?? node.routerPct,
      detached_disabled_pct:
        node.detached_disabled_pct ?? node.detachedDisabledPct,
      isFtdRouter: node.isFtdRouter ?? node.is_ftd_router,
      is_ftd_router: node.is_ftd_router ?? node.isFtdRouter,
      router_neighbor_max_err_rate_frame_pct:
        neighborStats.router_neighbor_max_err_rate_frame_pct,
      router_neighbor_max_err_rate_msg_pct:
        neighborStats.router_neighbor_max_err_rate_msg_pct,
      router_neighbor_min_rss_ave: neighborStats.router_neighbor_min_rss_ave,
      router_neighbor_max_rss_ave: neighborStats.router_neighbor_max_rss_ave,
      router_neighbor_has_rss_very_low:
        neighborStats.router_neighbor_has_rss_very_low,
      router_neighbor_has_rss_low: neighborStats.router_neighbor_has_rss_low,
      router_neighbor_has_rss_medium:
        neighborStats.router_neighbor_has_rss_medium,
      router_neighbor_has_rss_high: neighborStats.router_neighbor_has_rss_high,
      router_child_max_err_rate_frame_pct:
        childStats.router_child_max_err_rate_frame_pct,
      router_child_max_err_rate_msg_pct:
        childStats.router_child_max_err_rate_msg_pct,
      router_child_has_rss_very_low: childStats.router_child_has_rss_very_low,
      router_child_has_rss_low: childStats.router_child_has_rss_low,
      router_child_has_rss_margin_low:
        childStats.router_child_has_rss_margin_low,
      router_child_has_queued_msgs: childStats.router_child_has_queued_msgs,
    };
  });
}

export function buildNodeLabelFont({ fontSize = 13, isRouter = false } = {}) {
  return {
    size: fontSize,
    face: "monospace",
    multi: "md",
    color: "#e8f1ff",
    strokeWidth: 0,
    background: "rgba(7, 18, 40, 0.62)",
    ...(isRouter ? { vadjust: -8 } : {}),
  };
}

// ── Dataset counts helper ─────────────────────────────────────────────────────

/**
 * Derives device and link counts from topology nodeData and edgeData arrays.
 * Uses the semantic vis-node fields (`isRouter`, `isBorderRouter`) that are
 * set by buildVisNodeData — these are authoritative and consistent with the
 * filter/capabilities system.
 *
 * @param {Array} nodeData - Array of vis.js node objects
 * @param {Array} edgeData - Array of vis.js edge objects
 * @returns {{ devices, borderRouters, routers, children, links, lq3, lq2, lq1 }}
 */
export function computeDatasetCounts(nodeData, edgeData) {
  const borderRouters = nodeData.filter((n) => n.isBorderRouter === true).length;
  const routers       = nodeData.filter((n) => n.isRouter === true && !n.isBorderRouter).length;
  const children      = nodeData.filter((n) => n.isRouter !== true).length;
  const visibleEdges  = edgeData.filter((e) => !e.baseHidden);
  return {
    devices:       nodeData.length,
    borderRouters,
    routers,
    children,
    links:         visibleEdges.length,
    lq3:           visibleEdges.filter((e) => e.lqLevel === 3).length,
    lq2:           visibleEdges.filter((e) => e.lqLevel === 2).length,
    lq1:           visibleEdges.filter((e) => e.lqLevel === 1).length,
  };
}
