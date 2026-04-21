import {
  toText, toFiniteNumber,
  getCanonicalExtaddr, getCanonicalOmrIpv6Address
} from './tdash-utils.js';
import { normalizeLinkCategories } from './tdash-filters.js';

// ── Node-id selection ─────────────────────────────────────────────────────────

export function chooseNodeId(node, fallbackPrefix, index) {
  const rloc16 = toText(node.rloc16);
  if (rloc16) return rloc16;
  const idField = toText(node.id);
  if (idField) return idField;
  const extAddr = getCanonicalExtaddr(node);
  if (extAddr) return extAddr;
  const omrIpv6Address = getCanonicalOmrIpv6Address(node);
  if (omrIpv6Address) return omrIpv6Address;
  return `${fallbackPrefix}-${index}`;
}

// ── Node label builder ────────────────────────────────────────────────────────

export function buildLabel(node) {
  const nodeName = toText(node.device_label) || toText(node.name) || 'Unknown node';
  const rloc16 = toText(node.rloc16) || 'rloc16:n/a';
  return `${nodeName}\n${rloc16}`;
}

export function isUnknownNodeName(nodeName) {
  return toText(nodeName).toLowerCase().startsWith('unknown');
}

// ── Edge builder ──────────────────────────────────────────────────────────────
//
// Inserts or merges a directed edge into edgeMap/edgeData.
// - Duplicate undirected edges (same {from,to} pair regardless of order) are
//   merged: widths are max'd, linkCategories are unioned.
// - edgeKeySuffix in style creates a distinct key so multiple edge types
//   between the same pair can co-exist.

export function addEdge(edgeMap, edgeData, from, to, style) {
  if (!from || !to || from === to) return;
  const suffix = toText(style.edgeKeySuffix);
  const keyBase = [from, to].sort().join('|');
  const key = suffix ? `${keyBase}|${suffix}` : keyBase;
  const existing = edgeMap.get(key);
  if (existing) {
    if (Number.isFinite(style.width)) existing.width = Math.max(existing.width || 0, style.width);
    const merged = new Set([
      ...normalizeLinkCategories(existing.linkCategories),
      ...normalizeLinkCategories(style.linkCategories)
    ]);
    existing.linkCategories = Array.from(merged);
    if (style.isParentChild === true) existing.isParentChild = true;
    return;
  }
  const { edgeKeySuffix: _s, ...edgeStyle } = style;
  const edge = { from, to, ...edgeStyle };
  edge.id = key;
  edge.baseHidden = style.hidden === true;
  edge.linkCategories = normalizeLinkCategories(style.linkCategories);
  edgeMap.set(key, edge);
  edgeData.push(edge);
}

// ── RLOC16 arithmetic ─────────────────────────────────────────────────────────

export function buildMainRouterRloc16(routeId) {
  const n = toFiniteNumber(routeId);
  if (!Number.isFinite(n)) return '';
  return `0x${(n << 10).toString(16).padStart(4, '0')}`;
}

export function buildChildRloc16(parentRloc16, childId) {
  const parentText = toText(parentRloc16).toLowerCase();
  const childNum = toFiniteNumber(childId);
  if (!parentText.startsWith('0x') || !Number.isFinite(childNum)) return '';
  const parentNum = Number.parseInt(parentText, 16);
  if (!Number.isFinite(parentNum)) return '';
  return `0x${(parentNum + childNum).toString(16).padStart(4, '0')}`;
}

// ── Router-neighbor statistics ────────────────────────────────────────────────

export function computeRouterNeighborStats(routerNeighborTable) {
  const rows = Array.isArray(routerNeighborTable) ? routerNeighborTable : [];
  let maxFrame, maxMsg, minRss, maxRss;
  let hasVeryLow = false, hasLow = false, hasMedium = false, hasHigh = false;
  rows.forEach((row) => {
    const fp = toFiniteNumber(row?.err_rate_frame_pct);
    if (Number.isFinite(fp)) maxFrame = Number.isFinite(maxFrame) ? Math.max(maxFrame, fp) : fp;
    const mp = toFiniteNumber(row?.err_rate_msg_pct);
    if (Number.isFinite(mp)) maxMsg = Number.isFinite(maxMsg) ? Math.max(maxMsg, mp) : mp;
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
    router_neighbor_has_rss_high: hasHigh
  };
}

// ── Isolated-node clustering ──────────────────────────────────────────────────
//
// Groups isolated (degree-0) nodes with phantom hidden edges to keep the
// layout tidy.  Returns a nodeDegree Map for optional use by callers.

export function groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap) {
  const nodeDegree = new Map();
  for (const edge of edgeData) {
    nodeDegree.set(edge.from, (nodeDegree.get(edge.from) || 0) + 1);
    nodeDegree.set(edge.to, (nodeDegree.get(edge.to) || 0) + 1);
  }
  const connectedAnchorId = (function chooseConnectedAnchorId() {
    const knownCandidates = nodeData
      .filter((n) => n.group !== 'unknown' && (nodeDegree.get(n.id) || 0) > 0)
      .sort((a, b) => (nodeDegree.get(b.id) || 0) - (nodeDegree.get(a.id) || 0));
    return knownCandidates.length > 0 ? knownCandidates[0].id : '';
  })();

  function clusterIsolatedNodeIds(nodeIds, options = {}) {
    if (nodeIds.length === 0) return;
    const {
      clusterLength = 80,
      anchorLength = 180,
      anchorId = ''
    } = options;

    if (nodeIds.length > 1) {
      const anchorNodeId = nodeIds[0];
      for (let i = 1; i < nodeIds.length; i += 1) {
        addEdge(edgeMap, edgeData, anchorNodeId, nodeIds[i], {
          hidden: true, physics: true, length: clusterLength, color: { opacity: 0 }
        });
      }
    }

    if (anchorId) {
      addEdge(edgeMap, edgeData, nodeIds[0], anchorId, {
        hidden: true, physics: true, length: anchorLength, color: { opacity: 0 }
      });
    }
  }

  const unknownIds = nodeData
    .filter((n) => n.group === 'unknown' && (nodeDegree.get(n.id) || 0) === 0)
    .map((n) => n.id);
  clusterIsolatedNodeIds(unknownIds, { clusterLength: 60, anchorLength: 180, anchorId: connectedAnchorId });

  const knownIsolatedIds = nodeData
    .filter((n) => n.group !== 'unknown' && (nodeDegree.get(n.id) || 0) === 0)
    .map((n) => n.id);
  clusterIsolatedNodeIds(knownIsolatedIds, { clusterLength: 110, anchorLength: 240, anchorId: connectedAnchorId });

  return nodeDegree;
}

// ── Vis-node data builder ─────────────────────────────────────────────────────

export function buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, labelFn) {
  return Array.from(nodeMap.values()).map((node) => {
    const displayName = toText(node.device_label) || toText(node.name);
    const unknown = isUnknownNodeName(displayName);
    const effectiveShape = unknown ? 'ellipse' : node.shape;
    const rloc16Text = toText(node.rloc16).toLowerCase();
    const neighborStats = computeRouterNeighborStats(
      routerNeighborByRloc16.get(rloc16Text)?.router_neighbor_table
    );
    const isRouter = effectiveShape !== 'ellipse';
    const hasChildren = routerIdsWithChildren.has(node.id);
    const isMainRouter = rloc16Text.endsWith('00');
    const isBorderRouter = isMainRouter && node.br === true;
    let borderWidth = 1;
    let fontSize = 13;
    let widthConstraint = { minimum: 109, maximum: 109 };
    let heightConstraint = { minimum: 41, maximum: 41 };
    if (isBorderRouter) { borderWidth = 5; fontSize = 19.5; }
    else if (isRouter) { borderWidth = 3; fontSize = 19.5; }
    if (isRouter) {
      widthConstraint = { minimum: 187, maximum: 187 };
      heightConstraint = { minimum: 77, maximum: 77 };
    }
    return {
      id: node.id,
      label: labelFn(node),
      shape: effectiveShape,
      color: node.color,
      font: { size: fontSize, face: 'monospace', multi: 'md' },
      heightConstraint,
      widthConstraint,
      group: unknown ? 'unknown' : 'known',
      isRouter, hasChildren, isMainRouter, isBorderRouter, borderWidth,
      iftotalpktserrorsdiscards_pct: node.iftotalpktserrorsdiscards_pct,
      ifinerrors_pct: node.ifinerrors_pct,
      ifouterrors_pct: node.ifouterrors_pct,
      mode_device: node.mode_device,
      partitionidchanges: node.partitionidchanges,
      parentchanges: node.parentchanges,
      router_neighbor_max_err_rate_frame_pct: neighborStats.router_neighbor_max_err_rate_frame_pct,
      router_neighbor_max_err_rate_msg_pct: neighborStats.router_neighbor_max_err_rate_msg_pct,
      router_neighbor_min_rss_ave: neighborStats.router_neighbor_min_rss_ave,
      router_neighbor_max_rss_ave: neighborStats.router_neighbor_max_rss_ave,
      router_neighbor_has_rss_very_low: neighborStats.router_neighbor_has_rss_very_low,
      router_neighbor_has_rss_low: neighborStats.router_neighbor_has_rss_low,
      router_neighbor_has_rss_medium: neighborStats.router_neighbor_has_rss_medium,
      router_neighbor_has_rss_high: neighborStats.router_neighbor_has_rss_high
    };
  });
}
