import {
  VIS_OPTIONS,
  getPhysicsProfile,
  getPhysicsProfileLabel,
  PHYSICS_PROFILE_MESH_RING,
  PHYSICS_PROFILE_MESH_COMPACT,
  PHYSICS_PROFILE_MESH_TREE_HORIZONTAL,
  PHYSICS_PROFILE_MESH_TREE_VERTICAL,
  EDGE_CATEGORY_ROUTER_NEIGHBOR,
  EDGE_CATEGORY_DEFAULT_CHILDREN,
  EDGE_CATEGORY_OTBR_CHILD,
  EDGE_CATEGORY_EVE_CHILD,
  EDGE_CATEGORY_EVE_NATIVE_CHILD,
} from "./tdash-constants.js";
import {
  toText,
  getColumnValue,
  mergeForDisplay,
  flattenObjectEntries,
  shouldExcludeDetailPath,
  sortDetailsWithPriority,
  formatValue,
  areNodeIdsEquivalent,
  populateNodeDetailsLists,
} from "./tdash-utils.js";
import {
  computeTopologyCapabilities,
  updateFilterOptionVisibility,
  isNodeVisibleByFilter,
  isNodeVisibleByDiagnosticFilter,
  edgeMatchesLinkFilter,
  isRouterNeighborDiagnosticMode,
  routerNeighborRowMatchesDiagnosticFilter,
  isChildLinkQualityDiagnosticMode,
  childMatchesLinkQualityFilter,
  isRouterChildDiagnosticMode,
  routerChildRowMatchesDiagnosticFilter,
  normalizeLinkCategories,
} from "./tdash-filters.js";
import { rowMatchesSearch, parseSearchQuery } from "./tdash-search.js";
import { runAdaptor } from "./tdash-adaptors.js";
import { computeDatasetCounts } from "./tdash-topology-utils.js";

// ── Module-level state ────────────────────────────────────────────────────────

let _visNetwork = null;
let _topologyFilterHandlers = null;
let _autoZoomEnabled = true;
let _animationEnabled = false;
let _topologyNodeData = null;  // Store nodeData from last render for filter validation
let _topologyRawRows = null;   // Map<nodeId, rawRow> from last render, used for search
let _topologyDatasetCounts = null;  // Counts derived from last topology render
let _originalNodeStyling = null;  // Map<nodeId, {color, borderWidth, font}> — original styling for search restore
let _onPhysicsDisabledCallback = null;  // Callback invoked when physics is auto-disabled after stabilization

// ── Exported accessors / setters ──────────────────────────────────────────────

export function getVisNetwork() {
  return _visNetwork;
}
export function getTopologyFilterHandlers() {
  return _topologyFilterHandlers;
}
export function getTopologyNodeData() {
  return _topologyNodeData;
}
export function getTopologyDatasetCounts() {
  return _topologyDatasetCounts;
}
export function setAutoZoomEnabled(val) {
  _autoZoomEnabled = val;
}
export function setAnimationEnabled(val) {
  _animationEnabled = val;
}
export function isAutoZoomEnabled() {
  return _autoZoomEnabled;
}
export function isAnimationEnabled() {
  return _animationEnabled;
}
export function setOnPhysicsDisabledCallback(callback) {
  _onPhysicsDisabledCallback = callback;
}

// ── Debug accessors (for development/troubleshooting) ────────────────────────

/**
 * DEBUG: Expose the vis Network instance for browser console inspection.
 * Usage in browser console: window.tdashDebug.getVisNetwork()
 */
if (typeof window !== 'undefined') {
  window.tdashDebug = window.tdashDebug || {};
  window.tdashDebug.getVisNetwork = function() { return _visNetwork; };
  window.tdashDebug.getTopologyNodeData = function() { return _topologyNodeData; };
  window.tdashDebug.getOriginalNodeStyling = function() { return _originalNodeStyling; };
  window.tdashDebug.getMeshTreeZoningContext = function(nodeData, edgeData) {
    return _buildMeshTreeZoningContext(nodeData || [], edgeData || []);
  };
}

function _meshTreeUpperText(value) {
  return typeof value === "string" ? value.trim().toUpperCase() : "";
}

function _meshTreeStableHash(text) {
  const s = String(text || "");
  let h = 2166136261;
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function _meshTreeSortedIds(ids) {
  return Array.from(ids).sort((a, b) => String(a).localeCompare(String(b)));
}

function _meshTreeJitterById(nodeId, amplitude = 1) {
  const u = _meshTreeStableHash(nodeId) / 0xffffffff;
  return (u - 0.5) * 2 * amplitude;
}

function _meshTreeEdgeCategories(edge) {
  return normalizeLinkCategories(
    edge.linkCategories || edge.linkCategory || edge.category,
  );
}

function _buildMeshTreeZoningContext(nodeData, edgeData) {
  const nonHiddenNodes = nodeData.filter((n) => n?.hidden !== true);
  const nodeById = new Map(nonHiddenNodes.map((node) => [node.id, node]));
  const visibleEdges = edgeData.filter((edge) => {
    if (edge?.baseHidden === true || edge?.hidden === true) return false;
    return nodeById.has(edge.from) && nodeById.has(edge.to);
  });

  const visibleEdgeSet = new Set(
    visibleEdges.map((edge) => {
      const a = String(edge.from);
      const b = String(edge.to);
      return a <= b ? `${a}|${b}` : `${b}|${a}`;
    }),
  );

  const nodeDegreeById = new Map();
  nodeById.forEach((_, nodeId) => nodeDegreeById.set(nodeId, 0));
  visibleEdges.forEach((edge) => {
    nodeDegreeById.set(edge.from, (nodeDegreeById.get(edge.from) || 0) + 1);
    nodeDegreeById.set(edge.to, (nodeDegreeById.get(edge.to) || 0) + 1);
  });

  const routerIdSet = new Set(
    nonHiddenNodes.filter((node) => node.isRouter === true).map((node) => node.id),
  );

  const explicitParentsByChild = new Map();
  const routerScoresByChild = new Map();
  function addExplicitParent(childId, routerId) {
    if (!explicitParentsByChild.has(childId)) {
      explicitParentsByChild.set(childId, new Set());
    }
    explicitParentsByChild.get(childId).add(routerId);
  }
  function bumpRouterScore(childId, routerId, weight) {
    if (!routerScoresByChild.has(childId)) {
      routerScoresByChild.set(childId, new Map());
    }
    const scoreByRouter = routerScoresByChild.get(childId);
    scoreByRouter.set(routerId, (scoreByRouter.get(routerId) || 0) + weight);
  }

  visibleEdges.forEach((edge) => {
    const fromNode = nodeById.get(edge.from);
    const toNode = nodeById.get(edge.to);
    if (!fromNode || !toNode) return;

    const fromIsRouter = routerIdSet.has(fromNode.id);
    const toIsRouter = routerIdSet.has(toNode.id);
    if (fromIsRouter === toIsRouter) return;

    const routerNode = fromIsRouter ? fromNode : toNode;
    const childNode = fromIsRouter ? toNode : fromNode;
    const categories = _meshTreeEdgeCategories(edge);

    const isExplicitParentChild =
      edge.isParentChild === true ||
      categories.includes(EDGE_CATEGORY_DEFAULT_CHILDREN) ||
      categories.includes(EDGE_CATEGORY_OTBR_CHILD) ||
      categories.includes(EDGE_CATEGORY_EVE_CHILD) ||
      categories.includes(EDGE_CATEGORY_EVE_NATIVE_CHILD);

    const isRouterNeighborOnly = categories.length > 0 && categories.every(
      (cat) => cat === EDGE_CATEGORY_ROUTER_NEIGHBOR,
    );
    const isImplicitChildLike = isExplicitParentChild || !isRouterNeighborOnly;
    if (!isImplicitChildLike) return;

    const weight = isExplicitParentChild ? 14 : (edge.lqLevel === 3 ? 4 : 1);
    bumpRouterScore(childNode.id, routerNode.id, weight);

    if (isExplicitParentChild) {
      addExplicitParent(childNode.id, routerNode.id);
    }
  });

  const parentByChild = new Map();
  const childHasParentChildLink = new Set();

  explicitParentsByChild.forEach((parentSet, childId) => {
    childHasParentChildLink.add(childId);
    const scoreByRouter = routerScoresByChild.get(childId) || new Map();
    let selectedParentId = null;
    let selectedScore = -1;
    Array.from(parentSet).forEach((routerId) => {
      const score = scoreByRouter.get(routerId) || 0;
      if (score > selectedScore) {
        selectedScore = score;
        selectedParentId = routerId;
      } else if (score === selectedScore && selectedParentId != null) {
        if (String(routerId).localeCompare(String(selectedParentId)) < 0) {
          selectedParentId = routerId;
        }
      }
    });
    if (selectedParentId != null) {
      parentByChild.set(childId, selectedParentId);
    }
  });

  routerScoresByChild.forEach((scoreByRouter, childId) => {
    if (parentByChild.has(childId)) return;
    let selectedParentId = null;
    let selectedScore = -1;
    scoreByRouter.forEach((score, routerId) => {
      if (score > selectedScore) {
        selectedScore = score;
        selectedParentId = routerId;
      } else if (score === selectedScore && selectedParentId != null) {
        if (String(routerId).localeCompare(String(selectedParentId)) < 0) {
          selectedParentId = routerId;
        }
      }
    });
    if (selectedParentId != null) {
      parentByChild.set(childId, selectedParentId);
    }
  });

  const childrenByParent = new Map();
  parentByChild.forEach((parentId, childId) => {
    if (!childrenByParent.has(parentId)) childrenByParent.set(parentId, []);
    childrenByParent.get(parentId).push(childId);
  });
  childrenByParent.forEach((childIds, parentId) => {
    childrenByParent.set(parentId, _meshTreeSortedIds(new Set(childIds)));
  });

  function isFtdChildNode(node) {
    if (!node || node.isRouter === true) return false;
    if (_meshTreeUpperText(node.mode_device) === "FTD") return true;
    return /\bFTD\b/i.test(String(node.label || ""));
  }

  function isChildRoleCandidate(node, nodeId) {
    if (!node) return false;
    if (node.isBorderRouter === true || node.isRouter === true) return false;
    if (isFtdChildNode(node)) return true;
    if (_meshTreeUpperText(node.mode_device) === "MTD") return true;
    if (routerScoresByChild.has(nodeId) || parentByChild.has(nodeId)) return true;
    if ((nodeDegreeById.get(nodeId) || 0) > 0) return true;
    return true;
  }

  const zoneByNodeId = new Map();
  const zoneNodeIds = new Map([
    [1, []],
    [2, []],
    [3, []],
    [4, []],
    [5, []],
  ]);

  nodeById.forEach((node, nodeId) => {
    const isBorderRouter = node.isBorderRouter === true;
    const isRouter = node.isRouter === true;
    const isFtd = isFtdChildNode(node);
    const childCandidate = isChildRoleCandidate(node, nodeId);
    const hasParentChildLink = childHasParentChildLink.has(nodeId);

    let zone = 5;
    if (isBorderRouter) {
      zone = 1;
    } else if (isRouter) {
      zone = 2;
    } else if (isFtd && childCandidate) {
      zone = 3;
    } else if (childCandidate && !isBorderRouter && !isRouter && !isFtd && hasParentChildLink) {
      zone = 4;
    } else if (childCandidate && !isBorderRouter && !isRouter && !isFtd && !hasParentChildLink) {
      zone = 5;
    }

    zoneByNodeId.set(nodeId, zone);
    zoneNodeIds.get(zone).push(nodeId);
  });

  const zoneJitterByNodeId = new Map();
  const zones = Object.freeze({
    zone1: _meshTreeSortedIds(zoneNodeIds.get(1)),
    zone2: _meshTreeSortedIds(zoneNodeIds.get(2)),
    zone3: _meshTreeSortedIds(zoneNodeIds.get(3)),
    zone4: _meshTreeSortedIds(zoneNodeIds.get(4)),
    zone5: _meshTreeSortedIds(zoneNodeIds.get(5)),
  });

  Object.values(zones).forEach((zoneIds) => {
    zoneIds.forEach((nodeId) => {
      zoneJitterByNodeId.set(nodeId, _meshTreeJitterById(nodeId, 1));
    });
  });

  return {
    nodeById,
    visibleEdges,
    visibleEdgeSet,
    nodeDegreeById,
    routerIdSet,
    parentByChild,
    childrenByParent,
    childHasParentChildLink,
    routerScoresByChild,
    zoneByNodeId,
    zones,
    zoneJitterByNodeId,
    totalNodesClassified: zoneByNodeId.size,
  };
}

function applyMeshTreeHorizontalSeedLayout(nodeData, edgeData) {
  const zoning = _buildMeshTreeZoningContext(nodeData, edgeData);
  if (!zoning || zoning.totalNodesClassified === 0) return;

  const { nodeById, zones, parentByChild, childrenByParent, zoneByNodeId } = zoning;
  const zoneOrder = [1, 2, 3, 4, 5];
  const zoneIdsByIndex = {
    1: zones.zone1,
    2: zones.zone2,
    3: zones.zone3,
    4: zones.zone4,
    5: zones.zone5,
  };

  const allZoneIds = zoneOrder.flatMap((z) => zoneIdsByIndex[z]);
  const maxZoneCount = Math.max(1, ...zoneOrder.map((z) => zoneIdsByIndex[z].length));
  const baseHalfSpanY = Math.max(780, Math.round(maxZoneCount * 86));

  const zoneXAnchors = {
    1: -2400,
    2: -1200,
    3: 0,
    4: 600,
    5: 2400,
  };
  const zoneYSpacing = {
    1: 120,
    2: 140,
    3: 72,
    4: 82,
    5: 110,
  };

  function placeNode(node, x, y, policy) {
    if (!node) return;
    node.x = Math.round(x);
    node.y = Math.round(y);
    node.fixed = { x: Boolean(policy.fixX), y: Boolean(policy.fixY) };
    node.physics = Boolean(policy.physics);
  }

  function clampY(y) {
    const hardPad = 140;
    const minY = -baseHalfSpanY - hardPad;
    const maxY = baseHalfSpanY + hardPad;
    return Math.max(minY, Math.min(maxY, y));
  }

  function distributeByIndex(sortedIds, zoneNum) {
    const count = sortedIds.length;
    if (count === 0) return;
    const xAnchor = zoneXAnchors[zoneNum];
    const ySpacing = zoneYSpacing[zoneNum];
    const center = (count - 1) / 2;
    sortedIds.forEach((nodeId, idx) => {
      const node = nodeById.get(nodeId);
      const jitter = _meshTreeJitterById(nodeId, 1);
      const yJitter = zoneNum === 1 || zoneNum === 2 ? 10 : 14;
      const y = clampY((idx - center) * ySpacing + jitter * yJitter);
      const x = xAnchor + jitter * 18;
      const isZone3or4 = zoneNum === 3 || zoneNum === 4;
      placeNode(node, x, y, {
        fixX: true,
        fixY: !isZone3or4,
        physics: isZone3or4,
      });
    });
  }

  // 1) Strict band placement for zones 1, 2, 5.
  distributeByIndex(zoneIdsByIndex[1], 1);
  distributeByIndex(zoneIdsByIndex[2], 2);
  distributeByIndex(zoneIdsByIndex[5], 5);

  // Enforce extra spacing for border routers and parent routers so child clusters
  // inherit cleaner separation around their anchors.
  const borderRouterIds = _meshTreeSortedIds(new Set(zoneIdsByIndex[1]));
  const parentRouterIds = _meshTreeSortedIds(
    new Set(
      Array.from(childrenByParent.keys()).filter(
        (nodeId) => zoneByNodeId.get(nodeId) === 2,
      ),
    ),
  );

  function relaxSpecificNodeY(nodeIds, minGap) {
    const nodes = nodeIds
      .map((nodeId) => nodeById.get(nodeId))
      .filter(Boolean)
      .sort((a, b) => (Number(a.y) || 0) - (Number(b.y) || 0));
    if (nodes.length <= 1) return;
    for (let i = 1; i < nodes.length; i += 1) {
      const prev = nodes[i - 1];
      const curr = nodes[i];
      const py = Number(prev.y) || 0;
      let cy = Number(curr.y) || 0;
      if (cy - py < minGap) {
        cy = py + minGap;
        curr.y = clampY(cy);
      }
    }
    nodes.forEach((node) => {
      node.y = Math.round(Number(node.y) || 0);
    });
  }

  relaxSpecificNodeY(borderRouterIds, 280);
  relaxSpecificNodeY(parentRouterIds, 158);

  // 2) Parent-affinity placement for zones 3 and 4 around the parent Y-axis.
  function placeChildZoneWithParentAffinity(zoneNum) {
    const zoneIds = zoneIdsByIndex[zoneNum];
    const xAnchor = zoneXAnchors[zoneNum];
    const parentToChildren = new Map();
    const orphans = [];

    zoneIds.forEach((childId) => {
      const parentId = parentByChild.get(childId);
      if (!parentId || !nodeById.has(parentId)) {
        orphans.push(childId);
        return;
      }
      if (!parentToChildren.has(parentId)) parentToChildren.set(parentId, []);
      parentToChildren.get(parentId).push(childId);
    });

    const orderedParents = Array.from(parentToChildren.keys()).sort((a, b) => {
      const ay = Number(nodeById.get(a)?.y) || 0;
      const by = Number(nodeById.get(b)?.y) || 0;
      if (ay !== by) return ay - by;
      return String(a).localeCompare(String(b));
    });

    const used = new Set();
    orderedParents.forEach((parentId) => {
      const parentNode = nodeById.get(parentId);
      const parentY = Number(parentNode?.y) || 0;
      const childIds = _meshTreeSortedIds(parentToChildren.get(parentId) || []);
      const center = (childIds.length - 1) / 2;
      const localSpacing = zoneNum === 3 ? 66 : 76;
      childIds.forEach((childId, idx) => {
        const childNode = nodeById.get(childId);
        const jitter = _meshTreeJitterById(`${parentId}|${childId}`, 1);
        const y = clampY(parentY + (idx - center) * localSpacing + jitter * 10);
        const x = xAnchor + jitter * 14;
        placeNode(childNode, x, y, { fixX: true, fixY: false, physics: true });
        used.add(childId);
      });
    });

    const remaining = _meshTreeSortedIds(new Set([...orphans, ...zoneIds.filter((id) => !used.has(id))]));
    const fallbackCenter = (remaining.length - 1) / 2;
    remaining.forEach((childId, idx) => {
      const childNode = nodeById.get(childId);
      const jitter = _meshTreeJitterById(childId, 1);
      const y = clampY((idx - fallbackCenter) * zoneYSpacing[zoneNum] + jitter * 12);
      const x = xAnchor + jitter * 16;
      placeNode(childNode, x, y, { fixX: true, fixY: false, physics: true });
    });
  }

  placeChildZoneWithParentAffinity(3);
  placeChildZoneWithParentAffinity(4);

  // 3) Per-zone monotonic spacing pass to reduce immediate overlaps while
  // preserving clear x-band separation and parent-relative ordering.
  function relaxZoneYSpacing(zoneNum, minGap) {
    const ids = _meshTreeSortedIds(
      new Set(
        allZoneIds.filter((nodeId) => zoneByNodeId.get(nodeId) === zoneNum),
      ),
    );
    if (ids.length <= 1) return;
    const nodes = ids
      .map((nodeId) => nodeById.get(nodeId))
      .filter(Boolean)
      .sort((a, b) => (Number(a.y) || 0) - (Number(b.y) || 0));
    for (let i = 1; i < nodes.length; i += 1) {
      const prev = nodes[i - 1];
      const curr = nodes[i];
      const py = Number(prev.y) || 0;
      let cy = Number(curr.y) || 0;
      if (cy - py < minGap) {
        cy = py + minGap;
        curr.y = clampY(cy);
      }
    }
    for (let i = nodes.length - 2; i >= 0; i -= 1) {
      const next = nodes[i + 1];
      const curr = nodes[i];
      const ny = Number(next.y) || 0;
      let cy = Number(curr.y) || 0;
      if (ny - cy < minGap) {
        cy = ny - minGap;
        curr.y = clampY(cy);
      }
    }

    // Prevent single child-node tails in zones 3/4 from drifting too far.
    if (zoneNum === 3 || zoneNum === 4) {
      const sortedY = nodes
        .map((node) => Number(node.y) || 0)
        .sort((a, b) => a - b);
      const medianY = sortedY[Math.floor((sortedY.length - 1) / 2)] || 0;
      const maxTail = Math.max(560, Math.round(nodes.length * 12));
      const minAllowed = medianY - maxTail;
      const maxAllowed = medianY + maxTail;
      nodes.forEach((node) => {
        const y = Number(node.y) || 0;
        node.y = clampY(Math.max(minAllowed, Math.min(maxAllowed, y)));
      });
    }

    nodes.forEach((node) => {
      node.y = Math.round(Number(node.y) || 0);
      node.x = Math.round(Number(node.x) || 0);
    });
  }

  relaxZoneYSpacing(1, 108);
  relaxZoneYSpacing(2, 120);
  // Keep child clusters compact in zones 3/4; larger global gaps can create tails.
  relaxZoneYSpacing(3, 24);
  relaxZoneYSpacing(4, 28);
  relaxZoneYSpacing(5, 88);
}

function applyMeshTreeVerticalSeedLayout(nodeData, edgeData) {
  const zoning = _buildMeshTreeZoningContext(nodeData, edgeData);
  if (!zoning || zoning.totalNodesClassified === 0) return;

  const { nodeById, zones, parentByChild, childrenByParent, zoneByNodeId } = zoning;
  const zoneOrder = [1, 2, 3, 4, 5];
  const zoneIdsByIndex = {
    1: zones.zone1,
    2: zones.zone2,
    3: zones.zone3,
    4: zones.zone4,
    5: zones.zone5,
  };

  const allZoneIds = zoneOrder.flatMap((z) => zoneIdsByIndex[z]);
  const maxZoneCount = Math.max(1, ...zoneOrder.map((z) => zoneIdsByIndex[z].length));
  const baseHalfSpanX = Math.max(780, Math.round(maxZoneCount * 86));

  const zoneYAnchors = {
    1: -2400,
    2: -1200,
    3: 0,
    4: 600,
    5: 2400,
  };
  const zoneXSpacing = {
    1: 120,
    2: 140,
    3: 72,
    4: 82,
    5: 110,
  };

  function placeNode(node, x, y, policy) {
    if (!node) return;
    node.x = Math.round(x);
    node.y = Math.round(y);
    node.fixed = { x: Boolean(policy.fixX), y: Boolean(policy.fixY) };
    node.physics = Boolean(policy.physics);
  }

  function clampX(x) {
    const hardPad = 140;
    const minX = -baseHalfSpanX - hardPad;
    const maxX = baseHalfSpanX + hardPad;
    return Math.max(minX, Math.min(maxX, x));
  }

  function distributeByIndex(sortedIds, zoneNum) {
    const count = sortedIds.length;
    if (count === 0) return;
    const yAnchor = zoneYAnchors[zoneNum];
    const xSpacing = zoneXSpacing[zoneNum];
    const center = (count - 1) / 2;
    sortedIds.forEach((nodeId, idx) => {
      const node = nodeById.get(nodeId);
      const jitter = _meshTreeJitterById(nodeId, 1);
      const xJitter = zoneNum === 1 || zoneNum === 2 ? 10 : 14;
      const x = clampX((idx - center) * xSpacing + jitter * xJitter);
      const y = yAnchor + jitter * 18;
      const isZone3or4 = zoneNum === 3 || zoneNum === 4;
      placeNode(node, x, y, {
        fixX: !isZone3or4,
        fixY: true,
        physics: isZone3or4,
      });
    });
  }

  // 1) Strict band placement for zones 1, 2, 5.
  distributeByIndex(zoneIdsByIndex[1], 1);
  distributeByIndex(zoneIdsByIndex[2], 2);
  distributeByIndex(zoneIdsByIndex[5], 5);

  const borderRouterIds = _meshTreeSortedIds(new Set(zoneIdsByIndex[1]));
  const parentRouterIds = _meshTreeSortedIds(
    new Set(
      Array.from(childrenByParent.keys()).filter(
        (nodeId) => zoneByNodeId.get(nodeId) === 2,
      ),
    ),
  );

  function relaxSpecificNodeX(nodeIds, minGap) {
    const nodes = nodeIds
      .map((nodeId) => nodeById.get(nodeId))
      .filter(Boolean)
      .sort((a, b) => (Number(a.x) || 0) - (Number(b.x) || 0));
    if (nodes.length <= 1) return;
    for (let i = 1; i < nodes.length; i += 1) {
      const prev = nodes[i - 1];
      const curr = nodes[i];
      const px = Number(prev.x) || 0;
      let cx = Number(curr.x) || 0;
      if (cx - px < minGap) {
        cx = px + minGap;
        curr.x = clampX(cx);
      }
    }
    nodes.forEach((node) => {
      node.x = Math.round(Number(node.x) || 0);
    });
  }

  relaxSpecificNodeX(borderRouterIds, 280);
  relaxSpecificNodeX(parentRouterIds, 158);

  // 2) Parent-affinity placement for zones 3 and 4 around the parent X-axis.
  function placeChildZoneWithParentAffinity(zoneNum) {
    const zoneIds = zoneIdsByIndex[zoneNum];
    const yAnchor = zoneYAnchors[zoneNum];
    const parentToChildren = new Map();
    const orphans = [];

    zoneIds.forEach((childId) => {
      const parentId = parentByChild.get(childId);
      if (!parentId || !nodeById.has(parentId)) {
        orphans.push(childId);
        return;
      }
      if (!parentToChildren.has(parentId)) parentToChildren.set(parentId, []);
      parentToChildren.get(parentId).push(childId);
    });

    const orderedParents = Array.from(parentToChildren.keys()).sort((a, b) => {
      const ax = Number(nodeById.get(a)?.x) || 0;
      const bx = Number(nodeById.get(b)?.x) || 0;
      if (ax !== bx) return ax - bx;
      return String(a).localeCompare(String(b));
    });

    const used = new Set();
    orderedParents.forEach((parentId) => {
      const parentNode = nodeById.get(parentId);
      const parentX = Number(parentNode?.x) || 0;
      const childIds = _meshTreeSortedIds(parentToChildren.get(parentId) || []);
      const center = (childIds.length - 1) / 2;
      const localSpacing = zoneNum === 3 ? 66 : 76;
      childIds.forEach((childId, idx) => {
        const childNode = nodeById.get(childId);
        const jitter = _meshTreeJitterById(`${parentId}|${childId}`, 1);
        const x = clampX(parentX + (idx - center) * localSpacing + jitter * 10);
        const y = yAnchor + jitter * 14;
        placeNode(childNode, x, y, { fixX: false, fixY: true, physics: true });
        used.add(childId);
      });
    });

    const remaining = _meshTreeSortedIds(new Set([...orphans, ...zoneIds.filter((id) => !used.has(id))]));
    const fallbackCenter = (remaining.length - 1) / 2;
    remaining.forEach((childId, idx) => {
      const childNode = nodeById.get(childId);
      const jitter = _meshTreeJitterById(childId, 1);
      const x = clampX((idx - fallbackCenter) * zoneXSpacing[zoneNum] + jitter * 12);
      const y = yAnchor + jitter * 16;
      placeNode(childNode, x, y, { fixX: false, fixY: true, physics: true });
    });
  }

  placeChildZoneWithParentAffinity(3);
  placeChildZoneWithParentAffinity(4);

  // 3) Per-zone monotonic spacing pass to reduce immediate overlaps while
  // preserving clear y-band separation and parent-relative ordering.
  function relaxZoneXSpacing(zoneNum, minGap) {
    const ids = _meshTreeSortedIds(
      new Set(
        allZoneIds.filter((nodeId) => zoneByNodeId.get(nodeId) === zoneNum),
      ),
    );
    if (ids.length <= 1) return;
    const nodes = ids
      .map((nodeId) => nodeById.get(nodeId))
      .filter(Boolean)
      .sort((a, b) => (Number(a.x) || 0) - (Number(b.x) || 0));
    for (let i = 1; i < nodes.length; i += 1) {
      const prev = nodes[i - 1];
      const curr = nodes[i];
      const px = Number(prev.x) || 0;
      let cx = Number(curr.x) || 0;
      if (cx - px < minGap) {
        cx = px + minGap;
        curr.x = clampX(cx);
      }
    }
    for (let i = nodes.length - 2; i >= 0; i -= 1) {
      const next = nodes[i + 1];
      const curr = nodes[i];
      const nx = Number(next.x) || 0;
      let cx = Number(curr.x) || 0;
      if (nx - cx < minGap) {
        cx = nx - minGap;
        curr.x = clampX(cx);
      }
    }

    // Prevent single child-node tails in zones 3/4 from drifting too far.
    if (zoneNum === 3 || zoneNum === 4) {
      const sortedX = nodes
        .map((node) => Number(node.x) || 0)
        .sort((a, b) => a - b);
      const medianX = sortedX[Math.floor((sortedX.length - 1) / 2)] || 0;
      const maxTail = Math.max(560, Math.round(nodes.length * 12));
      const minAllowed = medianX - maxTail;
      const maxAllowed = medianX + maxTail;
      nodes.forEach((node) => {
        const x = Number(node.x) || 0;
        node.x = clampX(Math.max(minAllowed, Math.min(maxAllowed, x)));
      });
    }

    nodes.forEach((node) => {
      node.y = Math.round(Number(node.y) || 0);
      node.x = Math.round(Number(node.x) || 0);
    });
  }

  relaxZoneXSpacing(1, 108);
  relaxZoneXSpacing(2, 120);
  // Keep child clusters compact in zones 3/4; larger global gaps can create tails.
  relaxZoneXSpacing(3, 24);
  relaxZoneXSpacing(4, 28);
  relaxZoneXSpacing(5, 88);
}

function applyRingStarSeedLayout(nodeData, edgeData) {
  const nodeById = new Map(nodeData.map((n) => [n.id, n]));
  const visibleEdges = edgeData.filter((e) => e.baseHidden !== true);
  const routers = nodeData
    .filter((n) => n.isRouter === true)
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));

  if (routers.length === 0) return;

  function toUpperText(value) {
    return typeof value === "string" ? value.trim().toUpperCase() : "";
  }

  function stableHash(text) {
    const s = String(text || "");
    let h = 2166136261;
    for (let i = 0; i < s.length; i += 1) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return (h >>> 0);
  }

  function jitterFromId(id, amplitude) {
    const u = stableHash(id) / 0xffffffff;
    return (u - 0.5) * 2 * amplitude;
  }

  function isFtdChildNode(node) {
    if (!node || node.isRouter === true) return false;
    if (toUpperText(node.mode_device) === "FTD") return true;
    // Fallback for sparse datasets where mode_device is empty.
    return /\bFTD\b/i.test(String(node.label || ""));
  }

  function getEdgeCategories(edge) {
    return normalizeLinkCategories(edge.linkCategories || edge.linkCategory || edge.category);
  }

  const routerCount = routers.length;
  const routerRingRadius = Math.max(380, routerCount * 38);
  const routerIdSet = new Set(routers.map((r) => r.id));
  const routerById = new Map(routers.map((r) => [r.id, r]));

  // Four explicit rings from center.
  const ring2MinRadius = routerRingRadius + 170;  // FTD children (pushed farther from parents)
  const ring3MinRadius = routerRingRadius + 300;  // non-FTD children linked to routers
  const ring4Radius = routerRingRadius + 570;     // unconnected nodes (pushed farther out)

  // Build LQ3 router affinity graph.
  const lq3NeighborByRouter = new Map();
  routers.forEach((r) => lq3NeighborByRouter.set(r.id, new Set()));
  visibleEdges.forEach((edge) => {
    const a = nodeById.get(edge.from);
    const b = nodeById.get(edge.to);
    if (!a || !b) return;
    if (!routerIdSet.has(a.id) || !routerIdSet.has(b.id)) return;
    if (edge.lqLevel !== 3) return;
    lq3NeighborByRouter.get(a.id).add(b.id);
    lq3NeighborByRouter.get(b.id).add(a.id);
  });

  // Ring 1 order: greedy walk favoring LQ3-connected routers.
  const unvisited = new Set(routers.map((r) => r.id));
  const orderedRouterIds = [];
  function degreeOf(routerId) {
    return lq3NeighborByRouter.get(routerId)?.size || 0;
  }
  while (unvisited.size > 0) {
    const candidates = Array.from(unvisited).sort((a, b) => {
      const degreeDiff = degreeOf(b) - degreeOf(a);
      if (degreeDiff !== 0) return degreeDiff;
      return String(a).localeCompare(String(b));
    });
    let current = candidates[0];
    orderedRouterIds.push(current);
    unvisited.delete(current);

    while (unvisited.size > 0) {
      const lq3Candidates = Array.from(unvisited)
        .filter((id) => lq3NeighborByRouter.get(current)?.has(id))
        .sort((a, b) => {
          const degreeDiff = degreeOf(b) - degreeOf(a);
          if (degreeDiff !== 0) return degreeDiff;
          return String(a).localeCompare(String(b));
        });
      const next = lq3Candidates[0];
      if (!next) break;
      orderedRouterIds.push(next);
      unvisited.delete(next);
      current = next;
    }
  }

  // Use variable angular gaps: LQ3-adjacent routers get tighter spacing,
  // but keep a modest minimum gap so dense clusters stay readable.
  const LQ3_ADJACENT_GAP_WEIGHT = 0.95;
  const NON_LQ3_GAP_WEIGHT = 1.05;
  const gapWeights = [];
  const ringCount = orderedRouterIds.length;
  for (let i = 0; i < ringCount; i += 1) {
    const aId = orderedRouterIds[i];
    const bId = orderedRouterIds[(i + 1) % ringCount];
    const areLq3Neighbors = lq3NeighborByRouter.get(aId)?.has(bId) === true;
    gapWeights.push(areLq3Neighbors ? LQ3_ADJACENT_GAP_WEIGHT : NON_LQ3_GAP_WEIGHT);
  }
  const totalWeight = gapWeights.reduce((sum, w) => sum + w, 0) || ringCount;

  const routerAngleById = new Map();
  let cumulative = -Math.PI / 2;
  for (let i = 0; i < ringCount; i += 1) {
    const routerId = orderedRouterIds[i];
    routerAngleById.set(routerId, cumulative);
    cumulative += ((2 * Math.PI) * gapWeights[i]) / totalWeight;
  }

  const placed = new Set();

  // 1) Ring 1: pin routers on the ring. LQ3 neighbors are positioned with tighter arc spacing.
  orderedRouterIds.forEach((routerId) => {
    const router = routerById.get(routerId);
    const angle = routerAngleById.get(routerId) || 0;
    router.x = Math.round(routerRingRadius * Math.cos(angle));
    router.y = Math.round(routerRingRadius * Math.sin(angle));
    router.fixed = { x: true, y: true };
    router.physics = false;
    placed.add(router.id);
  });

  const parentToChildren = new Map();
  const nodeRouterScores = new Map();
  function pushChild(parentId, childId) {
    if (!parentToChildren.has(parentId)) parentToChildren.set(parentId, []);
    parentToChildren.get(parentId).push(childId);
  }

  function bumpRouterScoreWeighted(nodeId, routerId, weight) {
    if (!nodeRouterScores.has(nodeId)) nodeRouterScores.set(nodeId, new Map());
    const scoreByRouter = nodeRouterScores.get(nodeId);
    scoreByRouter.set(routerId, (scoreByRouter.get(routerId) || 0) + weight);
  }

  // 2) Build parent-child relation from parent-child and child-category edges.
  visibleEdges.forEach((edge) => {
    const a = nodeById.get(edge.from);
    const b = nodeById.get(edge.to);
    if (!a || !b) return;
    const cats = getEdgeCategories(edge);
    const aIsRouter = routerIdSet.has(a.id);
    const bIsRouter = routerIdSet.has(b.id);
    if (aIsRouter === bIsRouter) return;

    const routerNode = aIsRouter ? a : b;
    const nonRouterNode = aIsRouter ? b : a;

    const isExplicitChild =
      edge.isParentChild === true ||
      cats.includes(EDGE_CATEGORY_DEFAULT_CHILDREN) ||
      cats.includes(EDGE_CATEGORY_OTBR_CHILD) ||
      cats.includes(EDGE_CATEGORY_EVE_CHILD) ||
      cats.includes(EDGE_CATEGORY_EVE_NATIVE_CHILD);

    const isChildLike = isExplicitChild || !cats.includes(EDGE_CATEGORY_ROUTER_NEIGHBOR);

    // Prefer explicit parent-child semantics, then high-LQ links, then weak fallback.
    const weight = isExplicitChild ? 12 : (edge.lqLevel === 3 ? 3 : 1);
    bumpRouterScoreWeighted(nonRouterNode.id, routerNode.id, weight);

    // Only register an explicit parent-child edge here; implicit relationships
    // (e.g. OTBR_ROUTE edges from child nodes to every router in their routing
    // table) are handled via nodeRouterScores below.  Calling pushChild for all
    // isChildLike edges would add each child to parentToChildren for *every*
    // router it has a route entry to, and the last placeBandChildren call would
    // win — placing children far from their real parent.
    if (isExplicitChild) {
      pushChild(routerNode.id, nonRouterNode.id);
    }
  });

  // Assign any remaining router-connected non-router node to its strongest router.
  // Skip nodes that were already explicitly pushed via a parent-child edge above,
  // since their explicit parent always scores highest (weight 12 vs max 3 for routes).
  const explicitlyAssignedChildren = new Set();
  for (const [, childIds] of parentToChildren.entries()) {
    childIds.forEach((id) => explicitlyAssignedChildren.add(id));
  }
  for (const [nodeId, scoreByRouter] of nodeRouterScores.entries()) {
    const node = nodeById.get(nodeId);
    if (!node || node.isRouter === true) continue;
    if (explicitlyAssignedChildren.has(nodeId)) continue;
    let bestRouterId = null;
    let bestScore = -1;
    for (const [routerId, score] of scoreByRouter.entries()) {
      if (score > bestScore) {
        bestScore = score;
        bestRouterId = routerId;
      }
    }
    if (bestRouterId != null) pushChild(bestRouterId, nodeId);
  }

  // Helper for ring 2/3 placement around each parent router angle.
  function placeBandChildren(parent, parentAngle, childIds, bandMinRadius, distanceFromParentBase, spreadScale) {
    const sortedIds = Array.from(new Set(childIds)).sort((a, b) => String(a).localeCompare(String(b)));
    const childCount = sortedIds.length;
    if (childCount === 0) return;

    const spread = Math.min(Math.PI * 1.65, Math.max(Math.PI / 3, childCount * spreadScale));
    sortedIds.forEach((childId, idx) => {
      const child = nodeById.get(childId);
      if (!child) return;

      const localOffset = childCount === 1
        ? 0
        : (-spread / 2) + (spread * (idx / (childCount - 1)));
      const layer = Math.floor(idx / 3);
      const theta = parentAngle + localOffset + jitterFromId(`${parent.id}|${childId}|theta`, Math.PI / 9);
      const parentDist = distanceFromParentBase + (layer * 56) + jitterFromId(`${parent.id}|${childId}|radius`, 34);

      let x = parent.x + (parentDist * Math.cos(theta));
      let y = parent.y + (parentDist * Math.sin(theta));

      // Enforce the band's minimum radial distance from center.
      const r = Math.hypot(x, y);
      const minBandR = bandMinRadius + (layer * 34);
      if (r < minBandR) {
        const scale = minBandR / Math.max(1, r);
        x *= scale;
        y *= scale;
      }

      child.x = Math.round(x);
      child.y = Math.round(y);
      child.fixed = { x: true, y: true };
      child.physics = false;
      placed.add(child.id);
    });
  }

  // 2 & 3) Ring 2 = FTD children, Ring 3 = other router-linked children.
  for (const [parentId, childIdsRaw] of parentToChildren.entries()) {
    const parent = nodeById.get(parentId);
    if (!parent) continue;
    const parentAngle = routerAngleById.get(parentId) ?? 0;

    const childIds = Array.from(new Set(childIdsRaw));
    const ftdChildren = childIds.filter((childId) => {
      const child = nodeById.get(childId);
      return isFtdChildNode(child);
    });
    const otherChildren = childIds.filter((childId) => !ftdChildren.includes(childId));

    placeBandChildren(parent, parentAngle, ftdChildren, ring2MinRadius, 180, 0.24);
    placeBandChildren(parent, parentAngle, otherChildren, ring3MinRadius, 255, 0.30);
  }

  // After all children are placed, push overlapping non-router nodes apart.
  // Node shape sizes (from buildVisNodeData): routers ~187×77, children ~109×41.
  // We use a conservative bounding circle radius per type to drive separation.
  const MIN_CHILD_SEP = 130; // px — desired minimum centre-to-centre gap for child nodes
  const MAX_ITERS = 80;
  const DAMPING = 0.55;
  const childNodes = nodeData.filter((n) => n.isRouter !== true && placed.has(n.id));
  for (let iter = 0; iter < MAX_ITERS; iter += 1) {
    let moved = false;
    for (let i = 0; i < childNodes.length; i += 1) {
      const a = childNodes[i];
      for (let j = i + 1; j < childNodes.length; j += 1) {
        const b = childNodes[j];
        const dx = (b.x || 0) - (a.x || 0);
        const dy = (b.y || 0) - (a.y || 0);
        const dist = Math.hypot(dx, dy) || 0.01;
        if (dist >= MIN_CHILD_SEP) continue;
        const overlap = (MIN_CHILD_SEP - dist) * DAMPING;
        const nx = dx / dist;
        const ny = dy / dist;
        // Push each node equally away from the other.
        a.x = Math.round((a.x || 0) - nx * overlap * 0.5);
        a.y = Math.round((a.y || 0) - ny * overlap * 0.5);
        b.x = Math.round((b.x || 0) + nx * overlap * 0.5);
        b.y = Math.round((b.y || 0) + ny * overlap * 0.5);
        moved = true;
      }
    }
    if (!moved) break;
  }

  // 4) Ring 4: nodes with no links at all.
  const connectedNodeIds = new Set();
  visibleEdges.forEach((edge) => {
    connectedNodeIds.add(edge.from);
    connectedNodeIds.add(edge.to);
  });
  const unconnectedNodes = nodeData
    .filter((n) => !connectedNodeIds.has(n.id))
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));
  const unconnectedCount = unconnectedNodes.length;
  unconnectedNodes.forEach((node, idx) => {
    const angle = -Math.PI / 2 + ((2 * Math.PI * idx) / Math.max(1, unconnectedCount));
    node.x = Math.round(ring4Radius * Math.cos(angle));
    node.y = Math.round(ring4Radius * Math.sin(angle));
    node.fixed = { x: true, y: true };
    node.physics = false;
    placed.add(node.id);
  });

  // Fallback: place any remaining non-router nodes outside ring 4.
  const remaining = nodeData
    .filter((n) => !placed.has(n.id))
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));
  const fallbackRadius = ring4Radius + 110;
  const remCount = remaining.length;
  remaining.forEach((node, idx) => {
    const angle = -Math.PI / 2 + ((2 * Math.PI * idx) / Math.max(1, remCount));
    node.x = Math.round(fallbackRadius * Math.cos(angle));
    node.y = Math.round(fallbackRadius * Math.sin(angle));
    node.fixed = { x: true, y: true };
    node.physics = false;
  });
}

function applyMeshLabHybridSeedLayout(nodeData, edgeData) {
  const nodeById = new Map(nodeData.map((n) => [n.id, n]));
  const visibleEdges = edgeData.filter((e) => e.baseHidden !== true);
  const routers = nodeData
    .filter((n) => n.isRouter === true)
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));
  if (routers.length === 0) return;

  function toUpperText(value) {
    return typeof value === "string" ? value.trim().toUpperCase() : "";
  }

  function stableHash(text) {
    const s = String(text || "");
    let h = 2166136261;
    for (let i = 0; i < s.length; i += 1) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return (h >>> 0);
  }

  function jitterFromId(id, amplitude) {
    const u = stableHash(id) / 0xffffffff;
    return (u - 0.5) * 2 * amplitude;
  }

  function getEdgeCategories(edge) {
    return normalizeLinkCategories(edge.linkCategories || edge.linkCategory || edge.category);
  }

  function isChildMtdNode(node) {
    if (!node || node.isRouter === true) return false;
    return toUpperText(node.mode_device) === "MTD";
  }

  function isChildFtdNode(node) {
    if (!node || node.isRouter === true) return false;
    return toUpperText(node.mode_device) === "FTD";
  }

  const routerIdSet = new Set(routers.map((r) => r.id));
  const routerById = new Map(routers.map((r) => [r.id, r]));

  const parentToChildren = new Map();
  const childTypeById = new Map();
  const nodeRouterScores = new Map();
  function pushChild(parentId, childId) {
    if (!parentToChildren.has(parentId)) parentToChildren.set(parentId, []);
    parentToChildren.get(parentId).push(childId);
  }
  function bumpRouterScoreWeighted(nodeId, routerId, weight) {
    if (!nodeRouterScores.has(nodeId)) nodeRouterScores.set(nodeId, new Map());
    const scoreByRouter = nodeRouterScores.get(nodeId);
    scoreByRouter.set(routerId, (scoreByRouter.get(routerId) || 0) + weight);
  }

  visibleEdges.forEach((edge) => {
    const a = nodeById.get(edge.from);
    const b = nodeById.get(edge.to);
    if (!a || !b) return;
    const cats = getEdgeCategories(edge);
    const aIsRouter = routerIdSet.has(a.id);
    const bIsRouter = routerIdSet.has(b.id);
    if (aIsRouter === bIsRouter) return;

    const routerNode = aIsRouter ? a : b;
    const nonRouterNode = aIsRouter ? b : a;
    const isExplicitChild =
      edge.isParentChild === true ||
      cats.includes(EDGE_CATEGORY_DEFAULT_CHILDREN) ||
      cats.includes(EDGE_CATEGORY_OTBR_CHILD) ||
      cats.includes(EDGE_CATEGORY_EVE_CHILD) ||
      cats.includes(EDGE_CATEGORY_EVE_NATIVE_CHILD);

    const weight = isExplicitChild ? 14 : (edge.lqLevel === 3 ? 4 : 1);
    bumpRouterScoreWeighted(nonRouterNode.id, routerNode.id, weight);
    if (isExplicitChild) {
      pushChild(routerNode.id, nonRouterNode.id);
      childTypeById.set(
        nonRouterNode.id,
        isChildFtdNode(nonRouterNode) ? "ftd" : "mtd",
      );
    }
  });

  const explicitlyAssignedChildren = new Set();
  for (const [, childIds] of parentToChildren.entries()) {
    childIds.forEach((id) => explicitlyAssignedChildren.add(id));
  }
  for (const [nodeId, scoreByRouter] of nodeRouterScores.entries()) {
    const node = nodeById.get(nodeId);
    if (!node || node.isRouter === true) continue;
    if (explicitlyAssignedChildren.has(nodeId)) continue;
    let bestRouterId = null;
    let bestScore = -1;
    for (const [routerId, score] of scoreByRouter.entries()) {
      if (score > bestScore) {
        bestScore = score;
        bestRouterId = routerId;
      }
    }
    if (bestRouterId != null) {
      pushChild(bestRouterId, nodeId);
      childTypeById.set(nodeId, isChildFtdNode(node) ? "ftd" : "mtd");
    }
  }

  const routersWithChildren = routers
    .filter((r) => r.hasChildren === true || (parentToChildren.get(r.id)?.length || 0) > 0)
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));
  const routersWithoutChildren = routers
    .filter((r) => !routersWithChildren.some((rc) => rc.id === r.id))
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));

  const lq3NeighborByRouter = new Map();
  routers.forEach((r) => lq3NeighborByRouter.set(r.id, new Set()));
  visibleEdges.forEach((edge) => {
    const a = nodeById.get(edge.from);
    const b = nodeById.get(edge.to);
    if (!a || !b) return;
    if (!routerIdSet.has(a.id) || !routerIdSet.has(b.id)) return;
    if (edge.lqLevel !== 3) return;
    lq3NeighborByRouter.get(a.id).add(b.id);
    lq3NeighborByRouter.get(b.id).add(a.id);
  });

  function degreeOf(routerId) {
    return lq3NeighborByRouter.get(routerId)?.size || 0;
  }

  function orderRoutersByGreedyAffinity(routerSubset) {
    const subsetIds = new Set(routerSubset.map((r) => r.id));
    const unvisited = new Set(routerSubset.map((r) => r.id));
    const ordered = [];
    while (unvisited.size > 0) {
      const candidates = Array.from(unvisited).sort((a, b) => {
        const degreeDiff = degreeOf(b) - degreeOf(a);
        if (degreeDiff !== 0) return degreeDiff;
        return String(a).localeCompare(String(b));
      });
      let current = candidates[0];
      ordered.push(current);
      unvisited.delete(current);
      while (unvisited.size > 0) {
        const nextCandidates = Array.from(unvisited)
          .filter((id) => subsetIds.has(id) && lq3NeighborByRouter.get(current)?.has(id))
          .sort((a, b) => {
            const degreeDiff = degreeOf(b) - degreeOf(a);
            if (degreeDiff !== 0) return degreeDiff;
            return String(a).localeCompare(String(b));
          });
        const next = nextCandidates[0];
        if (!next) break;
        ordered.push(next);
        unvisited.delete(next);
        current = next;
      }
    }
    return ordered;
  }

  const orderedOuterRouterIds = orderRoutersByGreedyAffinity(routersWithChildren.length > 0 ? routersWithChildren : routers);
  const outerCount = orderedOuterRouterIds.length;
  const innerCount = routersWithoutChildren.length;
  const outerRadius = Math.max(560, outerCount * 68);
  const innerRadius = Math.max(335, Math.floor(outerRadius * 0.68));

  const routerAngleById = new Map();
  const gapWeights = [];
  for (let i = 0; i < outerCount; i += 1) {
    const aId = orderedOuterRouterIds[i];
    const bId = orderedOuterRouterIds[(i + 1) % Math.max(1, outerCount)];
    const areLq3Neighbors = lq3NeighborByRouter.get(aId)?.has(bId) === true;
    gapWeights.push(areLq3Neighbors ? 0.92 : 1.08);
  }
  const totalWeight = gapWeights.reduce((sum, w) => sum + w, 0) || Math.max(1, outerCount);
  let cumulative = -Math.PI / 2;
  for (let i = 0; i < outerCount; i += 1) {
    const routerId = orderedOuterRouterIds[i];
    routerAngleById.set(routerId, cumulative);
    cumulative += ((2 * Math.PI) * gapWeights[i]) / totalWeight;
  }

  orderedOuterRouterIds.forEach((routerId) => {
    const router = routerById.get(routerId);
    const angle = routerAngleById.get(routerId) || 0;
    router.x = Math.round(outerRadius * Math.cos(angle));
    router.y = Math.round(outerRadius * Math.sin(angle));
    router.fixed = { x: true, y: true };
    router.physics = false;
  });

  const sortedInnerRouters = routersWithoutChildren
    .slice()
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));
  sortedInnerRouters.forEach((router, idx) => {
    const anchorAngle =
      -Math.PI / 2 + ((2 * Math.PI * idx) / Math.max(1, sortedInnerRouters.length));

    const ringLayer = idx % 2;
    const ringOffset = ringLayer === 0 ? -34 : 34;
    const r = innerRadius + ringOffset + jitterFromId(`${router.id}|innerR`, 30);
    const theta = anchorAngle + jitterFromId(`${router.id}|innerTheta`, Math.PI / 10);
    router.x = Math.round(r * Math.cos(theta));
    router.y = Math.round(r * Math.sin(theta));
    router.fixed = { x: true, y: true };
    router.physics = false;
  });

  function placeChildrenAroundParent(parent, childIds, bandConfig) {
    const {
      bandMinRadius,
      distanceFromParentBase,
      spreadScale,
      jitterAngle,
      jitterRadius,
      pinChildren,
    } = bandConfig;
    const uniqueChildren = Array.from(new Set(childIds)).sort((a, b) => String(a).localeCompare(String(b)));
    const childCount = uniqueChildren.length;
    if (childCount === 0) return;

    const parentR = Math.hypot(parent.x || 0, parent.y || 0) || 1;
    const outwardTheta = Math.atan2(parent.y || 0, parent.x || 0);
    const spread = Math.min(Math.PI * 1.82, Math.max(Math.PI / 3, childCount * spreadScale));

    uniqueChildren.forEach((childId, idx) => {
      const child = nodeById.get(childId);
      if (!child) return;
      const layer = Math.floor(idx / 3);
      const offset = childCount === 1
        ? 0
        : (-spread / 2) + (spread * (idx / (childCount - 1)));
      const theta = outwardTheta + offset + jitterFromId(`${parent.id}|${child.id}|theta`, jitterAngle);
      const distFromParent = distanceFromParentBase + (layer * 66) + jitterFromId(`${parent.id}|${child.id}|r`, jitterRadius);
      let x = (parent.x || 0) + (distFromParent * Math.cos(theta));
      let y = (parent.y || 0) + (distFromParent * Math.sin(theta));

      // Keep children near parent while still biasing outside the parent router ring.
      const r = Math.hypot(x, y) || 1;
      const minR = Math.max(parentR + 70, bandMinRadius + (layer * 36));
      if (r < minR) {
        const scale = minR / r;
        x *= scale;
        y *= scale;
      }

      child.x = Math.round(x);
      child.y = Math.round(y);
      child.fixed = pinChildren ? { x: true, y: true } : { x: false, y: false };
      child.physics = !pinChildren;
    });
  }

  for (const [parentId, childIds] of parentToChildren.entries()) {
    const parent = nodeById.get(parentId);
    if (!parent) continue;
    const mtdChildren = childIds.filter((childId) => {
      const child = nodeById.get(childId);
      return isChildMtdNode(child) || childTypeById.get(childId) === "mtd";
    });
    const ftdChildren = childIds.filter((childId) => {
      const child = nodeById.get(childId);
      return isChildFtdNode(child) || childTypeById.get(childId) === "ftd";
    });

    placeChildrenAroundParent(parent, mtdChildren, {
      bandMinRadius: outerRadius + 360,
      distanceFromParentBase: 400,
      spreadScale: 0.22,
      jitterAngle: Math.PI / 11,
      jitterRadius: 20,
      pinChildren: true,
    });
    placeChildrenAroundParent(parent, ftdChildren, {
      bandMinRadius: outerRadius + 70,
      distanceFromParentBase: 150,
      spreadScale: 0.28,
      jitterAngle: Math.PI / 10,
      jitterRadius: 26,
      pinChildren: true,
    });
  }

  // Relax overlap on seeded inner routers and children while preserving outer router anchors.
  const outerRouterSet = new Set(orderedOuterRouterIds);
  const parentByChild = new Map();
  for (const [parentId, childIds] of parentToChildren.entries()) {
    childIds.forEach((childId) => {
      if (!parentByChild.has(childId)) parentByChild.set(childId, parentId);
    });
  }
  const seededMovable = nodeData.filter((n) => {
    if (outerRouterSet.has(n.id)) return false;
    if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) return false;
    return n.isRouter === true || parentByChild.has(n.id);
  });

  const MAX_ITERS = 90;
  for (let iter = 0; iter < MAX_ITERS; iter += 1) {
    let moved = false;
    for (let i = 0; i < seededMovable.length; i += 1) {
      const a = seededMovable[i];
      for (let j = i + 1; j < seededMovable.length; j += 1) {
        const b = seededMovable[j];
        const aIsRouter = a.isRouter === true;
        const bIsRouter = b.isRouter === true;
        const minSep = aIsRouter || bIsRouter ? 205 : 138;
        const dx = (b.x || 0) - (a.x || 0);
        const dy = (b.y || 0) - (a.y || 0);
        const dist = Math.hypot(dx, dy) || 0.01;
        if (dist >= minSep) continue;
        const overlap = (minSep - dist) * 0.57;
        const nx = dx / dist;
        const ny = dy / dist;
        a.x = Math.round((a.x || 0) - nx * overlap * 0.5);
        a.y = Math.round((a.y || 0) - ny * overlap * 0.5);
        b.x = Math.round((b.x || 0) + nx * overlap * 0.5);
        b.y = Math.round((b.y || 0) + ny * overlap * 0.5);
        moved = true;
      }
    }

    // Keep children parent-local after repulsion.
    parentByChild.forEach((parentId, childId) => {
      const parent = nodeById.get(parentId);
      const child = nodeById.get(childId);
      if (!parent || !child) return;
      const dx = (child.x || 0) - (parent.x || 0);
      const dy = (child.y || 0) - (parent.y || 0);
      const dist = Math.hypot(dx, dy) || 0.01;
      const maxParentDist = 380;
      if (dist > maxParentDist) {
        const scale = maxParentDist / dist;
        child.x = Math.round((parent.x || 0) + dx * scale);
        child.y = Math.round((parent.y || 0) + dy * scale);
        moved = true;
      }

      const childType = childTypeById.get(childId);
      const minBandRadius = childType === "ftd" ? outerRadius + 60 : outerRadius + 340;
      const childRadius = Math.hypot(child.x || 0, child.y || 0) || 0;
      if (childRadius < minBandRadius) {
        const scale = minBandRadius / Math.max(1, childRadius);
        child.x = Math.round((child.x || 0) * scale);
        child.y = Math.round((child.y || 0) * scale);
        moved = true;
      }
    });

    if (!moved) break;
  }

  // Place uncategorized, unlinked nodes on a dedicated outer ring.
  // Mirrors mesh-ring's explicit ring placement for degree-zero nodes.
  const connectedNodeIds = new Set();
  visibleEdges.forEach((edge) => {
    connectedNodeIds.add(edge.from);
    connectedNodeIds.add(edge.to);
  });

  const maxMtdRadius = nodeData.reduce((maxRadius, node) => {
    if (childTypeById.get(node.id) !== "mtd") return maxRadius;
    if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) return maxRadius;
    return Math.max(maxRadius, Math.hypot(node.x, node.y));
  }, 0);

  const uncategorizedOuterRadius = Math.max(outerRadius + 700, maxMtdRadius + 140);
  const uncategorizedUnlinkedNodes = nodeData
    .filter((node) => {
      if (connectedNodeIds.has(node.id)) return false;
      if (node.isBorderRouter === true) return false;
      if (node.isRouter === true) return false;
      if (childTypeById.has(node.id)) return false;
      if (isChildFtdNode(node)) return false;
      if (isChildMtdNode(node)) return false;
      return true;
    })
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));

  const uncategorizedCount = uncategorizedUnlinkedNodes.length;
  uncategorizedUnlinkedNodes.forEach((node, idx) => {
    const angle = -Math.PI / 2 + ((2 * Math.PI * idx) / Math.max(1, uncategorizedCount));
    node.x = Math.round(uncategorizedOuterRadius * Math.cos(angle));
    node.y = Math.round(uncategorizedOuterRadius * Math.sin(angle));
    node.fixed = { x: true, y: true };
    node.physics = false;
  });
}

// ── Main renderer ─────────────────────────────────────────────────────────────

export function renderTopologyForDataset(dataset, physicsEnabled, physicsProfileName = "mesh-baseline") {
  const container = document.getElementById("topology-view");
  const statusEl = document.getElementById("view-status-line-content");
  const nodeFilterEl = document.getElementById("node-filter");
  const linkFilterEl = document.getElementById("link-filter");
  const diagnosticFilterEl = document.getElementById("diagnostic-filter");
  let lastStatusCounts = null;
  let lastStabilizationMs = null;
  const renderStartedAt = (typeof performance !== "undefined" && typeof performance.now === "function")
    ? performance.now()
    : Date.now();
  const physicsProfile = getPhysicsProfile(physicsProfileName);
  const physicsProfileLabel = getPhysicsProfileLabel(physicsProfileName);

  // Destroy previous network instance to free memory
  if (_visNetwork) {
    _visNetwork.destroy();
    _visNetwork = null;
    _topologyFilterHandlers = null;
    _topologyRawRows = null;
  }
  container.innerHTML = "";

  // Reset all details lists
  document.getElementById("summary-list").innerHTML =
    "<li>Click a node or row to view its properties.</li>";
  document
    .querySelectorAll(
      "#identity-list, #highlights-list, #network-list, #connections-list, #mdns-list, #routes-links-list, #neighbors-list, #children-list, #counters-list, #details-list",
    )
    .forEach((list) => {
      list.innerHTML = "";
      list.classList.add("hidden");
    });

  let adaptorResult;
  try {
    adaptorResult = runAdaptor(dataset);
  } catch (err) {
    statusEl.textContent = `Topology error: ${err.message}`;
    return;
  }

  const {
    nodeData,
    edgeData,
    nodeMap,
    rawByIdForDetails,
    routerNeighborByRloc16,
    routerChildByRloc16 = new Map(),
    sourceNames,
  } = adaptorResult;

  if (physicsProfileName === PHYSICS_PROFILE_MESH_RING) {
    applyRingStarSeedLayout(nodeData, edgeData);
  } else if (physicsProfileName === PHYSICS_PROFILE_MESH_COMPACT) {
    applyMeshLabHybridSeedLayout(nodeData, edgeData);
  } else if (physicsProfileName === PHYSICS_PROFILE_MESH_TREE_HORIZONTAL) {
    applyMeshTreeHorizontalSeedLayout(nodeData, edgeData);
  } else if (physicsProfileName === PHYSICS_PROFILE_MESH_TREE_VERTICAL) {
    applyMeshTreeVerticalSeedLayout(nodeData, edgeData);
  }

  // Apply curved parent-child edges across all profiles to reduce overlap.
  // Profile-specific branches below can still override roundness/length/physics.
  edgeData.forEach((edge) => {
    if (edge.baseHidden === true) return;
    if (edge.isParentChild !== true) return;
    const hashSeed = `${edge.from}|${edge.to}`;
    const curveType = (hashSeed.length % 2 === 0) ? "curvedCW" : "curvedCCW";
    edge.smooth = { enabled: true, type: curveType, roundness: 0.2 };
  });

  // Curve router-to-router edges so overlapping links become individually visible.
  {
    const nodeByIdForCurves = new Map(nodeData.map((n) => [n.id, n]));
    edgeData.forEach((edge) => {
      if (edge.baseHidden === true) return;
      if (edge.isParentChild === true) return;
      const fromNode = nodeByIdForCurves.get(edge.from);
      const toNode = nodeByIdForCurves.get(edge.to);
      if (fromNode?.isRouter !== true || toNode?.isRouter !== true) return;
      const hashSeed = `${edge.from}|${edge.to}`;
      const curveType = (hashSeed.length % 2 === 0) ? "curvedCW" : "curvedCCW";
      edge.smooth = { enabled: true, type: curveType, roundness: 0.26 };
    });
  }

  const isMeshTreeProfile =
    physicsProfileName === PHYSICS_PROFILE_MESH_TREE_HORIZONTAL ||
    physicsProfileName === PHYSICS_PROFILE_MESH_TREE_VERTICAL;
  if (
    physicsProfileName === PHYSICS_PROFILE_MESH_COMPACT ||
    physicsProfileName === PHYSICS_PROFILE_MESH_RING ||
    isMeshTreeProfile
  ) {
    const nodeById = new Map(nodeData.map((n) => [n.id, n]));
    const isFtdChildNode = (node) => toText(node?.mode_device).toUpperCase() === "FTD";
    const meshTreeZoneByNodeId = isMeshTreeProfile
      ? _buildMeshTreeZoningContext(nodeData, edgeData).zoneByNodeId
      : null;
    const applyMinEdgeLength = (edge, minLength) => {
      edge.length = Number.isFinite(edge.length)
        ? Math.max(edge.length, minLength)
        : minLength;
    };

    edgeData.forEach((edge) => {
      if (edge.baseHidden === true) return;
      const fromNode = nodeById.get(edge.from);
      const toNode = nodeById.get(edge.to);
      const fromIsRouter = fromNode?.isRouter === true;
      const toIsRouter = toNode?.isRouter === true;
      const routerToChildLike = (fromIsRouter && !toIsRouter) || (!fromIsRouter && toIsRouter);
      const fromZone = meshTreeZoneByNodeId?.get(edge.from);
      const toZone = meshTreeZoneByNodeId?.get(edge.to);
      const isCrossZoneLink =
        Number.isInteger(fromZone) &&
        Number.isInteger(toZone) &&
        fromZone !== toZone;

      if (edge.isParentChild === true) {
        const childNode = fromIsRouter ? toNode : fromNode;
        const childBandLength = isMeshTreeProfile
          ? (isFtdChildNode(childNode) ? 170 : 250)
          : (isFtdChildNode(childNode) ? 200 : 430);
        applyMinEdgeLength(edge, childBandLength);
        edge.physics = true;
        // Alternate curve direction to separate sibling parent-child edges.
        const hashSeed = `${edge.from}|${edge.to}`;
        const curveType = (hashSeed.length % 2 === 0) ? "curvedCW" : "curvedCCW";
        edge.smooth = {
          enabled: true,
          type: curveType,
          roundness: isMeshTreeProfile ? 0.34 : 0.3,
        };
      } else if (
        (physicsProfileName === PHYSICS_PROFILE_MESH_COMPACT || isMeshTreeProfile) &&
        routerToChildLike
      ) {
        // Keep non-parent router-to-child links visual, but remove spring force to
        // avoid pulling children into dense central clusters.
        edge.physics = false;
      } else if (fromIsRouter && toIsRouter) {
        applyMinEdgeLength(edge, isMeshTreeProfile ? 620 : 430);
      } else if (isMeshTreeProfile && isCrossZoneLink) {
        // Increase spring length for non-parent links crossing zone bands
        // to preserve explicit mesh-tree separation.
        applyMinEdgeLength(edge, 520);
      }
    });
  }

  // Store nodeData and raw rows for filter validation and search
  _topologyNodeData = nodeData;
  _topologyRawRows = rawByIdForDetails;
  // Compute and store dataset counts for the status bar
  _topologyDatasetCounts = computeDatasetCounts(nodeData, edgeData);

  // ── compute and apply dynamic filter option visibility ────────
  const capabilities = computeTopologyCapabilities(nodeData, edgeData);
  dataset.capabilities = capabilities;
  updateFilterOptionVisibility(capabilities, "topology");

  const nodesDataset = new vis.DataSet(nodeData);
  const edgesDataset = new vis.DataSet(edgeData);

  const nodeIdByRloc16 = new Map();
  const nodeIdByExtaddr = new Map();
  nodeMap.forEach((node, nodeId) => {
    const rloc16 = toText(node?.rloc16).toLowerCase();
    if (rloc16) nodeIdByRloc16.set(rloc16, nodeId);
    const extaddr = toText(node?.extAddress || node?.extaddr).toLowerCase();
    if (extaddr) nodeIdByExtaddr.set(extaddr, nodeId);
  });

  function resolveDiagnosticTargetNodeId(row) {
    const extaddr = toText(row?.extAddress || row?.extaddr).toLowerCase();
    const rloc16 = toText(row?.rloc16).toLowerCase();
    const rowId = toText(row?.id);

    if (extaddr && nodeIdByExtaddr.has(extaddr)) {
      return nodeIdByExtaddr.get(extaddr);
    }
    if (rloc16 && nodeIdByRloc16.has(rloc16)) {
      return nodeIdByRloc16.get(rloc16);
    }
    if (rowId && nodeMap.has(rowId)) {
      return rowId;
    }
    if (rowId && nodeMap.has(rowId.toLowerCase())) {
      return rowId.toLowerCase();
    }

    return extaddr || rloc16 || rowId;
  }

  function getRouterChildRowsForParent(parentNodeId, parentRaw) {
    const rawChildTable = getColumnValue(parentRaw || {}, "childTable")
      ?? getColumnValue(parentRaw || {}, "router_child_table");
    const rowsFromRaw = Array.isArray(rawChildTable)
      ? rawChildTable
      : [];
    const parentRloc16 = toText(nodeMap.get(parentNodeId)?.rloc16).toLowerCase();
    const indexedChildTable = getColumnValue(
      routerChildByRloc16.get(parentRloc16) || {},
      "childTable",
    ) ?? getColumnValue(routerChildByRloc16.get(parentRloc16) || {}, "router_child_table");
    const rowsFromIndex = Array.isArray(indexedChildTable)
      ? indexedChildTable
      : [];

    if (rowsFromIndex.length === 0) return rowsFromRaw;
    if (rowsFromRaw.length === 0) return rowsFromIndex;

    const mergedRows = [];
    const seen = new Set();
    [...rowsFromIndex, ...rowsFromRaw].forEach((row) => {
      const key = [
        toText(row?.rloc16).toLowerCase(),
        toText(row?.extAddress || row?.extaddr).toLowerCase(),
        toText(row?.child_id || row?.childId).toLowerCase(),
      ].join("|");
      const dedupeKey = key === "||" ? `anon:${mergedRows.length}` : key;
      if (seen.has(dedupeKey)) return;
      seen.add(dedupeKey);
      mergedRows.push(row);
    });
    return mergedRows;
  }

  function cloneNodeStyle(style) {
    return {
      color: style?.color ? { ...style.color } : style?.color,
      borderWidth: style?.borderWidth,
      font: style?.font ? { ...style.font } : style?.font,
    };
  }
  
  // Store original styling for each node so we can restore it when search is cleared
  _originalNodeStyling = new Map();
  nodeData.forEach((node) => {
    _originalNodeStyling.set(node.id, cloneNodeStyle(node));
  });
  
  const optionsWithProfile = Object.assign({}, VIS_OPTIONS, {
    physics: Object.assign({}, VIS_OPTIONS.physics, {
      barnesHut: Object.assign({}, VIS_OPTIONS.physics?.barnesHut, physicsProfile.barnesHut),
      stabilization: Object.assign({}, VIS_OPTIONS.physics?.stabilization, physicsProfile.stabilization),
    }),
  });

  const effectiveOptions = physicsEnabled
    ? optionsWithProfile
    : Object.assign({}, VIS_OPTIONS, {
      physics: Object.assign({}, optionsWithProfile.physics, { enabled: false }),
    });
  _visNetwork = new vis.Network(
    container,
    { nodes: nodesDataset, edges: edgesDataset },
    effectiveOptions,
  );

  // ── applyFilters ───────────────────────────────────────────────────────

  function applyFilters(nodeFilterMode, linkFilterMode, diagnosticFilterMode) {
    const visibleNodeIds = new Set();
    const forcedVisibleEdgeIds = new Set();
    const matchedTargetNodeIds = new Set();
    let visibleEdgeCount = 0;

    nodesDataset.forEach((node) => {
      if (
        isNodeVisibleByFilter(node, nodeFilterMode) &&
        isNodeVisibleByDiagnosticFilter(node, diagnosticFilterMode)
      ) {
        visibleNodeIds.add(node.id);
      }
    });

    // Pull in child nodes when routers-with-children filter is active
    if (nodeFilterMode === "routers-with-children") {
      edgesDataset.forEach((edge) => {
        if (
          edge.isParentChild === true &&
          edgeMatchesLinkFilter(edge, linkFilterMode) &&
          visibleNodeIds.has(edge.from)
        ) {
          visibleNodeIds.add(edge.to);
        }
      });
    }

    // For router-neighbor diagnostic modes: expose matched neighbor nodes + force their edges visible
    if (isRouterNeighborDiagnosticMode(diagnosticFilterMode)) {
      Array.from(visibleNodeIds).forEach((sourceNodeId) => {
        const sourceNode = nodeMap.get(sourceNodeId);
        if (!sourceNode) return;
        const sourceRloc16 = toText(sourceNode.rloc16).toLowerCase();
        const neighborRow = routerNeighborByRloc16.get(sourceRloc16);
        const neighborTable = getColumnValue(neighborRow || {}, "routerNeighbors")
          ?? getColumnValue(neighborRow || {}, "router_neighbor_table");
        const neighborEntries = Array.isArray(neighborTable)
          ? neighborTable
          : [];
        neighborEntries
          .filter((neighbor) =>
            routerNeighborRowMatchesDiagnosticFilter(
              neighbor,
              diagnosticFilterMode,
            ),
          )
          .forEach((neighbor) => {
            const targetId = resolveDiagnosticTargetNodeId(neighbor);
            if (!targetId) return;
            matchedTargetNodeIds.add(targetId);
            visibleNodeIds.add(targetId);
            edgesDataset.forEach((edge) => {
              const cats = normalizeLinkCategories(edge.linkCategories);
              if (!cats.includes(EDGE_CATEGORY_ROUTER_NEIGHBOR)) return;
              if (
                (areNodeIdsEquivalent(edge.from, sourceNodeId) &&
                  areNodeIdsEquivalent(edge.to, targetId)) ||
                (areNodeIdsEquivalent(edge.to, sourceNodeId) &&
                  areNodeIdsEquivalent(edge.from, targetId))
              ) {
                forcedVisibleEdgeIds.add(edge.id);
              }
            });
          });
      });
    }

    // For child link quality diagnostic modes: expose matched child nodes + force their edges visible
    if (isChildLinkQualityDiagnosticMode(diagnosticFilterMode)) {
      Array.from(visibleNodeIds).forEach((parentNodeId) => {
        const parentRaw = rawByIdForDetails.get(parentNodeId);
        if (!parentRaw) return;
        const childrenArray = Array.isArray(parentRaw.children)
          ? parentRaw.children
          : [];
        childrenArray
          .filter((child) =>
            childMatchesLinkQualityFilter(child, diagnosticFilterMode),
          )
          .forEach((child) => {
            const childId = resolveDiagnosticTargetNodeId(child);
            if (!childId) return;
            matchedTargetNodeIds.add(childId);
            visibleNodeIds.add(childId);
            edgesDataset.forEach((edge) => {
              const cats = normalizeLinkCategories(edge.linkCategories);
              if (
                !cats.includes(EDGE_CATEGORY_DEFAULT_CHILDREN) &&
                !cats.includes(EDGE_CATEGORY_OTBR_CHILD)
              )
                return;
              if (
                (areNodeIdsEquivalent(edge.from, parentNodeId) &&
                  areNodeIdsEquivalent(edge.to, childId)) ||
                (areNodeIdsEquivalent(edge.to, parentNodeId) &&
                  areNodeIdsEquivalent(edge.from, childId))
              ) {
                forcedVisibleEdgeIds.add(edge.id);
              }
            });
          });
      });
    }

    // For router-child diagnostic modes: expose matched child nodes + force their edges visible
    if (isRouterChildDiagnosticMode(diagnosticFilterMode)) {
      Array.from(visibleNodeIds).forEach((parentNodeId) => {
        const parentRaw = rawByIdForDetails.get(parentNodeId);
        if (!parentRaw) return;
        const childTableRows = getRouterChildRowsForParent(parentNodeId, parentRaw);
        childTableRows
          .filter((child) =>
            routerChildRowMatchesDiagnosticFilter(child, diagnosticFilterMode),
          )
          .forEach((child) => {
            const childId = resolveDiagnosticTargetNodeId(child);
            if (!childId) return;
            matchedTargetNodeIds.add(childId);
            visibleNodeIds.add(childId);
            edgesDataset.forEach((edge) => {
              const cats = normalizeLinkCategories(edge.linkCategories);
              if (
                !cats.includes(EDGE_CATEGORY_DEFAULT_CHILDREN) &&
                !cats.includes(EDGE_CATEGORY_OTBR_CHILD)
              )
                return;
              if (
                (areNodeIdsEquivalent(edge.from, parentNodeId) &&
                  areNodeIdsEquivalent(edge.to, childId)) ||
                (areNodeIdsEquivalent(edge.to, parentNodeId) &&
                  areNodeIdsEquivalent(edge.from, childId))
              ) {
                forcedVisibleEdgeIds.add(edge.id);
              }
            });
          });
      });
    }

    nodesDataset.forEach((node) => {
      nodesDataset.update({
        id: node.id,
        hidden: !visibleNodeIds.has(node.id),
      });
    });

    edgesDataset.forEach((edge) => {
      const endpointsVisible =
        visibleNodeIds.has(edge.from) && visibleNodeIds.has(edge.to);
      const shouldShow =
        edge.baseHidden !== true &&
        endpointsVisible &&
        (edgeMatchesLinkFilter(edge, linkFilterMode) ||
          forcedVisibleEdgeIds.has(edge.id));
      edgesDataset.update({ id: edge.id, hidden: !shouldShow });
      if (shouldShow) visibleEdgeCount += 1;
    });

    return {
      visibleNodeCount: visibleNodeIds.size,
      visibleEdgeCount,
      matchedTargetNodeCount: matchedTargetNodeIds.size,
      forcedVisibleLinkCount: forcedVisibleEdgeIds.size,
    };
  }

  // Shared canonical restore path for node visual styles.
  function restoreOriginalNodeStyling() {
    if (!_originalNodeStyling) return;
    nodesDataset.update(
      Array.from(_originalNodeStyling.entries()).map(([nodeId, originalStyle]) => ({
        id: nodeId,
        ...cloneNodeStyle(originalStyle),
      })),
    );
  }

  // ── Search highlight ─────────────────────────────────────────────────────

  function applySearchHighlight(searchQuery, advancedMode) {
    if (!_topologyNodeData || !_topologyRawRows) return;

    if (!searchQuery) {
      // Restore all nodes to their original appearance using stored original styling
      restoreOriginalNodeStyling();
      // Clear search from status line
      updateStatus(lastStatusCounts);
      return;
    }

    // Identify node IDs whose source row matches the query
    const matchingNodeIds = new Set();
    _topologyRawRows.forEach((row, nodeId) => {
      if (rowMatchesSearch(row, searchQuery, advancedMode)) {
        matchingNodeIds.add(nodeId);
      }
    });

    // Update status line with search counts
    updateStatus(lastStatusCounts, searchQuery, matchingNodeIds.size, _topologyRawRows.size);

    // Update each node: highlight matches, dim non-matches
    // Use stored original styling to preserve current node state
    nodesDataset.update(
      Array.from(_originalNodeStyling.entries()).map(([nodeId, originalStyle]) => {
        if (matchingNodeIds.has(nodeId)) {
          return {
            id: nodeId,
            color: { background: originalStyle.color.background, border: "#d97706" },
            borderWidth: Math.max(originalStyle.borderWidth ?? 2, 4),
            font: originalStyle.font ? { ...originalStyle.font } : originalStyle.font,
          };
        }
        return {
          id: nodeId,
          color: { background: "#e8e8e8", border: "#c0c0c0" },
          borderWidth: 1,
          font: { ...originalStyle.font, color: "#aaaaaa" },
        };
      }),
    );

    // When exactly one node matches: select it visually, populate the details
    // panel, and zoom to it in the upper-center of the canvas.
    if (matchingNodeIds.size === 1 && _visNetwork) {
      const [singleId] = matchingNodeIds;
      _visNetwork.selectNodes([singleId]);
      showNodeDetails(singleId);
      const viewEl = document.getElementById("view-topology");
      const canvasHeight = viewEl ? viewEl.clientHeight : 400;
      // Negative y shifts focal point upward; cap at 100px to avoid clipping on short canvases
      const yOffset = -Math.min(Math.round(canvasHeight * 0.22), 100);
      _visNetwork.focus(singleId, {
        scale: 1.10,
        animation: { duration: 600, easingFunction: "easeInOutQuad" },
        offset: { x: 0, y: yOffset },
      });
    }
  }

  // ── Status line ────────────────────────────────────────────────────────

  function formatTopologyScale() {
    if (!_visNetwork || typeof _visNetwork.getScale !== "function") return "";
    const scale = _visNetwork.getScale();
    if (!Number.isFinite(scale)) return "";
    return ` Scale: ${scale.toFixed(2)}x.`;
  }

  function updateStatus(counts, searchQuery = null, matchCount = 0, totalCount = 0) {
    lastStatusCounts = counts;
    const {
      visibleNodeCount,
      visibleEdgeCount,
      matchedTargetNodeCount = 0,
      forcedVisibleLinkCount = 0,
    } = counts;
    const nodeFilterLabel =
      nodeFilterEl?.options[nodeFilterEl.selectedIndex]?.text || "All";
    const linkFilterLabel =
      linkFilterEl?.options[linkFilterEl.selectedIndex]?.text || "All";
    const diagFilterLabel =
      diagnosticFilterEl?.options[diagnosticFilterEl.selectedIndex]?.text || "None";
    const neighborSuffix = isRouterNeighborDiagnosticMode(
      diagnosticFilterEl.value,
    )
      ? ` Neighbor Match: targets ${matchedTargetNodeCount}, links ${forcedVisibleLinkCount}.`
      : "";
    const searchSuffix = searchQuery
      ? ` Search: "${searchQuery}" — ${matchCount} of ${totalCount} rows match.`
      : "";
    const stabilizationSuffix = Number.isFinite(lastStabilizationMs)
      ? ` Stabilized: ${(lastStabilizationMs / 1000).toFixed(2)}s.`
      : "";
    const fetchStatusEl = document.getElementById("fetch-status-line-content");
    const fetchStatusPinnedUntil = window.tdashDebug?.fetchStatusPinnedUntil ?? 0;
    const isFetchStatusPinned = Date.now() < fetchStatusPinnedUntil;
    if (fetchStatusEl && !isFetchStatusPinned) {
      fetchStatusEl.textContent = `Loaded: ${sourceNames.join(", ")}`;
    }
    statusEl.textContent =
      `Showing: ${visibleNodeCount} nodes, ${visibleEdgeCount} links. Physics profile: ${physicsProfileLabel}.${stabilizationSuffix}${neighborSuffix}${searchSuffix}`;
  }

  // ── Node detail click handler ──────────────────────────────────────────

  _visNetwork.on("click", (params) => {
    if (params.nodes.length === 0) {
      document.getElementById("summary-list").innerHTML =
        "<li>Click a node or row to view its properties.</li>";
      document
        .querySelectorAll(
          "#identity-list, #highlights-list, #network-list, #connections-list, #mdns-list, #routes-links-list, #neighbors-list, #children-list, #counters-list, #details-list",
        )
        .forEach((list) => {
          list.classList.add("hidden");
        });
      return;
    }
    showNodeDetails(params.nodes[0]);
  });

  // Capture routerIdsWithChildren for detail panel
  const routerIdsWithChildrenRef = new Set(
    nodeData.filter((n) => n.hasChildren).map((n) => n.id),
  );

  // Shared helper: populate the device-details side panel for a given node ID.
  // Called from the vis.js click handler and programmatically (e.g. single-match search).
  function showNodeDetails(selectedId) {
    const _QL =
      "#identity-list, #highlights-list, #network-list, #connections-list, " +
      "#mdns-list, #routes-links-list, #neighbors-list, #children-list, " +
      "#counters-list, #details-list";
    const _hide = () => document.querySelectorAll(_QL).forEach((l) => l.classList.add("hidden"));
    const node = nodeMap.get(selectedId);
    if (!node) {
      document.getElementById("summary-list").innerHTML =
        "<li>No details available for selected node.</li>";
      _hide();
      return;
    }
    const rawSource = rawByIdForDetails.get(selectedId) || {};
    const graphDetails = {
      graph: {
        unifiedId: selectedId,
        graphLinkCount: (function () {
          let deg = 0;
          edgesDataset.forEach((e) => {
            if (e.from === selectedId || e.to === selectedId) deg += 1;
          });
          return deg;
        })(),
        // check both is_router field and shape to determine router status for details panel, since some adaptors may not set is_router but use shape to indicate router status
        // also is node.selectedId is an rloc16 that starts with '0x'. and ends with '00', which conventionally indicates a router in Thread networks, treat it as a router as well
        // Additionally, check if the type or role fields indicate "router" to cover more cases where router status might be implied
        // check if rloc16 is 6 characters long to avoid misclassifying non-rloc16 IDs that coincidentally start with '0x' and end with '00'
        isRouter: node.isRouter || node.is_router || 
          (typeof node.rloc16 === "string" &&
            node.rloc16.toLowerCase().startsWith("0x") &&
            node.rloc16.toLowerCase().endsWith("00") &&
            node.rloc16.length === 6) ||
          toText(node.role).toLowerCase() === "router",
        hasChildren: routerIdsWithChildrenRef
          ? routerIdsWithChildrenRef.has(selectedId)
          : undefined,
      },
    };
    const mergedDetails = mergeForDisplay(rawSource, graphDetails);
    const details = sortDetailsWithPriority(
      flattenObjectEntries(mergedDetails).filter(
        ([key]) => !shouldExcludeDetailPath(key),
      ),
    );
    if (details.length === 0) {
      document.getElementById("summary-list").innerHTML =
        "<li>No details available for selected node.</li>";
      _hide();
      return;
    }
    populateNodeDetailsLists(details);
  }

  function refreshStatusScale() {
    if (lastStatusCounts) updateStatus(lastStatusCounts);
  }

  _visNetwork.on("zoom", refreshStatusScale);
  _visNetwork.on("animationFinished", refreshStatusScale);
  _visNetwork.once("stabilized", refreshStatusScale);

  // Turn off physics when stabilization is complete to stop graph movement
  _visNetwork.on("stabilizationIterationsDone", function () {
    const stabilizedAt = (typeof performance !== "undefined" && typeof performance.now === "function")
      ? performance.now()
      : Date.now();
    lastStabilizationMs = Math.max(0, stabilizedAt - renderStartedAt);

    if (typeof window !== "undefined") {
      window.tdashDebug = window.tdashDebug || {};
      window.tdashDebug.phase1Runs = Array.isArray(window.tdashDebug.phase1Runs)
        ? window.tdashDebug.phase1Runs
        : [];
      window.tdashDebug.phase1Runs.push({
        timestampIso: new Date().toISOString(),
        profile: physicsProfileName,
        profileLabel: physicsProfileLabel,
        stabilizationMs: Math.round(lastStabilizationMs),
        nodeCount: nodeData.length,
        edgeCount: edgeData.filter((e) => e.baseHidden !== true).length,
      });
    }

    _visNetwork.setOptions({ physics: false });
    if (physicsProfileName === PHYSICS_PROFILE_MESH_RING && _autoZoomEnabled) {
      requestAnimationFrame(() => {
        if (_visNetwork) {
          _visNetwork.fit({ animation: _animationEnabled });
        }
      });
    }
    // Notify UI layer that physics has been disabled
    if (_onPhysicsDisabledCallback) {
      _onPhysicsDisabledCallback();
    }

    if (lastStatusCounts) updateStatus(lastStatusCounts);
  });

  // ── Store filter handlers so the toggle/filter wiring can call them ──
  _topologyFilterHandlers = {
    applyFilters,
    applySearchHighlight,
    restoreOriginalNodeStyling,
    updateStatus,
    fitIfEnabled: () => {
      if (_autoZoomEnabled && _visNetwork) {
        requestAnimationFrame(() => {
          if (_visNetwork) {
            _visNetwork.fit({ animation: _animationEnabled });
          }
        });
      }
    },
  };

  // ── Initial filter pass ────────────────────────────────────────────────
  const initial = applyFilters(
    nodeFilterEl.value,
    linkFilterEl.value,
    diagnosticFilterEl.value,
  );
  updateStatus(initial);
  
  // Apply visual styling after filters to ensure correct colors are displayed
  restoreOriginalNodeStyling();
  
  _topologyFilterHandlers.fitIfEnabled();
}
