import {
  EDGE_CATEGORY_DEFAULT_CHILDREN,
  EDGE_CATEGORY_EVE_CHILD,
  EDGE_CATEGORY_EVE_NATIVE_CHILD,
  EDGE_CATEGORY_OTBR_CHILD,
  EDGE_CATEGORY_ROUTER_NEIGHBOR,
} from "./tdash-constants.js";
import { normalizeLinkCategories } from "./tdash-filters.js";

export const TREE_ZONE = Object.freeze({
  borderRouterChildren: 40,
  borderRouterFtds: 30,
  borderRouters: 10,
  buffer: 0,
  nonBorderRouters: -20,
  nonBorderRouterFtds: -30,
  nonBorderRouterChildren: -40,
  fallback: -50,
});

const ZONE_ORDER = Object.freeze([40, 30, 10, 0, -20, -30, -40, -50]);
const ZONE_ANCHORS = Object.freeze({ 40: -1125, 30: -900, 10: -450, 0: 0, "-20": 150, "-30": 600, "-40": 825, "-50": 1750 });
const ZONE_SPACING = Object.freeze({ 40: 82, 30: 72, 10: 120, "-20": 154, "-30": 72, "-40": 82, "-50": 110 });
const ZONE_MIN_GAP = Object.freeze({ 40: 28, 30: 24, 10: 108, "-20": 132, "-30": 24, "-40": 28, "-50": 88 });
const CHILD_ZONES = new Set([40, 30, -30, -40]);

const RING_CONFIG = Object.freeze({
  ftdBandOffset: 220,
  mtdBandOffset: 360,
  ftdParentDistance: 240,
  mtdParentDistance: 330,
  childLayerDistance: 82,
  childClearance: 172,
  ftdParentClearance: 220,
  mtdParentClearance: 290,
  collisionIterations: 120,
});

const COMPACT_CONFIG = Object.freeze({
  ftdBandOffset: 130,
  mtdBandOffset: 360,
  ftdParentDistance: 230,
  mtdParentDistance: 400,
  ftdSpreadScale: 0.3,
  mtdSpreadScale: 0.22,
  childLayerDistance: 82,
  childClearance: 172,
  routerClearance: 220,
  ftdMaxParentDistance: 450,
  mtdMaxParentDistance: 720,
  collisionIterations: 90,
  finalCollisionIterations: 120,
});

export function stableLayoutHash(text) {
  let hash = 2166136261;
  for (const character of String(text || "")) {
    hash ^= character.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function layoutJitter(id, amplitude = 1) {
  return ((stableLayoutHash(id) / 0xffffffff) - 0.5) * 2 * amplitude;
}

function sortedIds(values) {
  return [...new Set(values)].sort((left, right) => String(left).localeCompare(String(right)));
}

function upperText(value) {
  return typeof value === "string" ? value.trim().toUpperCase() : "";
}

function edgeCategories(edge) {
  return normalizeLinkCategories(edge.linkCategories || edge.linkCategory || edge.category);
}

function isFtd(node) {
  return node?.isRouter !== true && (
    upperText(node?.mode_device) === "FTD" || /\bFTD\b/i.test(String(node?.label || ""))
  );
}

function isExplicitChildEdge(edge) {
  const categories = edgeCategories(edge);
  return edge.isParentChild === true
    || categories.includes(EDGE_CATEGORY_DEFAULT_CHILDREN)
    || categories.includes(EDGE_CATEGORY_OTBR_CHILD)
    || categories.includes(EDGE_CATEGORY_EVE_CHILD)
    || categories.includes(EDGE_CATEGORY_EVE_NATIVE_CHILD);
}

export function buildGraphAnalysis(nodes, edges) {
  const visibleNodes = nodes
    .filter((node) => node?.hidden !== true)
    .sort((left, right) => String(left.id).localeCompare(String(right.id)));
  const nodeById = new Map(visibleNodes.map((node) => [node.id, node]));
  const visibleEdges = edges
    .filter((edge) => (
      edge?.baseHidden !== true
      && edge?.hidden !== true
      && nodeById.has(edge.from)
      && nodeById.has(edge.to)
    ))
    .sort((left, right) => (
      String(left.from).localeCompare(String(right.from))
      || String(left.to).localeCompare(String(right.to))
      || String(left.id || "").localeCompare(String(right.id || ""))
      || JSON.stringify(edgeCategories(left)).localeCompare(JSON.stringify(edgeCategories(right)))
    ));
  const adjacency = new Map([...nodeById.keys()].map((nodeId) => [nodeId, new Set()]));
  const degreeById = new Map([...nodeById.keys()].map((nodeId) => [nodeId, 0]));
  visibleEdges.forEach((edge) => {
    adjacency.get(edge.from).add(edge.to);
    adjacency.get(edge.to).add(edge.from);
    degreeById.set(edge.from, degreeById.get(edge.from) + 1);
    degreeById.set(edge.to, degreeById.get(edge.to) + 1);
  });

  const components = [];
  const roots = [];
  const parentById = new Map();
  const depthById = new Map();
  const unvisited = new Set(sortedIds(nodeById.keys()));
  while (unvisited.size > 0) {
    const root = sortedIds(unvisited)[0];
    const component = [];
    const queue = [root];
    unvisited.delete(root);
    roots.push(root);
    parentById.set(root, null);
    depthById.set(root, 0);
    while (queue.length > 0) {
      const nodeId = queue.shift();
      component.push(nodeId);
      sortedIds(adjacency.get(nodeId)).forEach((neighborId) => {
        if (!unvisited.has(neighborId)) return;
        unvisited.delete(neighborId);
        parentById.set(neighborId, nodeId);
        depthById.set(neighborId, depthById.get(nodeId) + 1);
        queue.push(neighborId);
      });
    }
    components.push(component);
  }

  return Object.freeze({ nodeById, visibleEdges, adjacency, degreeById, components, roots, parentById, depthById });
}

export function classifyParentRelationships(analysis) {
  const routerIds = new Set(
    [...analysis.nodeById.values()].filter((node) => node.isRouter === true).map((node) => node.id),
  );
  const explicitParents = new Map();
  const scoresByChild = new Map();
  const explicitChildren = new Set();
  const bump = (childId, routerId, weight, explicit) => {
    if (!scoresByChild.has(childId)) scoresByChild.set(childId, new Map());
    const scores = scoresByChild.get(childId);
    scores.set(routerId, (scores.get(routerId) || 0) + weight);
    if (!explicit) return;
    explicitChildren.add(childId);
    if (!explicitParents.has(childId)) explicitParents.set(childId, new Set());
    explicitParents.get(childId).add(routerId);
  };

  analysis.visibleEdges.forEach((edge) => {
    const fromRouter = routerIds.has(edge.from);
    const toRouter = routerIds.has(edge.to);
    if (fromRouter === toRouter) return;
    const routerId = fromRouter ? edge.from : edge.to;
    const childId = fromRouter ? edge.to : edge.from;
    const categories = edgeCategories(edge);
    const explicit = isExplicitChildEdge(edge);
    if (!explicit && categories.length > 0 && categories.every((category) => category === EDGE_CATEGORY_ROUTER_NEIGHBOR)) return;
    bump(childId, routerId, explicit ? 14 : (edge.lqLevel === 3 ? 4 : 1), explicit);
  });

  const parentByChild = new Map();
  scoresByChild.forEach((scores, childId) => {
    const candidates = explicitParents.get(childId) || new Set(scores.keys());
    const selected = [...candidates].sort((left, right) => (
      (scores.get(right) || 0) - (scores.get(left) || 0)
      || String(left).localeCompare(String(right))
    ))[0];
    if (selected !== undefined) parentByChild.set(childId, selected);
  });
  const childrenByParent = new Map();
  parentByChild.forEach((parentId, childId) => {
    if (!childrenByParent.has(parentId)) childrenByParent.set(parentId, []);
    childrenByParent.get(parentId).push(childId);
  });
  childrenByParent.forEach((childIds, parentId) => childrenByParent.set(parentId, sortedIds(childIds)));
  return Object.freeze({ routerIds, scoresByChild, parentByChild, childrenByParent, explicitChildren });
}

export function assignMeshTreeZones(analysis, relationships) {
  const zoneByNodeId = new Map();
  const zoneNodeIds = new Map(ZONE_ORDER.map((zone) => [zone, []]));
  analysis.nodeById.forEach((node, nodeId) => {
    const parent = analysis.nodeById.get(relationships.parentByChild.get(nodeId));
    let zone = TREE_ZONE.fallback;
    if (node.isBorderRouter === true) zone = TREE_ZONE.borderRouters;
    else if (node.isRouter === true) zone = TREE_ZONE.nonBorderRouters;
    else if (isFtd(node) && parent) zone = parent.isBorderRouter ? TREE_ZONE.borderRouterFtds : TREE_ZONE.nonBorderRouterFtds;
    else if (relationships.explicitChildren.has(nodeId) && parent) {
      zone = parent.isBorderRouter ? TREE_ZONE.borderRouterChildren : TREE_ZONE.nonBorderRouterChildren;
    }
    zoneByNodeId.set(nodeId, zone);
    zoneNodeIds.get(zone).push(nodeId);
  });
  zoneNodeIds.forEach((ids, zone) => zoneNodeIds.set(zone, sortedIds(ids)));
  return Object.freeze({ zoneByNodeId, zoneNodeIds });
}

export function buildMeshTreeZoningContext(nodes, edges) {
  const analysis = buildGraphAnalysis(nodes, edges);
  const relationships = classifyParentRelationships(analysis);
  const zoning = assignMeshTreeZones(analysis, relationships);
  const zones = Object.freeze({
    zone40: zoning.zoneNodeIds.get(40), zone30: zoning.zoneNodeIds.get(30),
    zone10: zoning.zoneNodeIds.get(10), zone0: zoning.zoneNodeIds.get(0),
    zoneMinus20: zoning.zoneNodeIds.get(-20), zoneMinus30: zoning.zoneNodeIds.get(-30),
    zoneMinus40: zoning.zoneNodeIds.get(-40), zoneMinus50: zoning.zoneNodeIds.get(-50),
  });
  return Object.freeze({
    ...analysis,
    nodeDegreeById: analysis.degreeById,
    routerIdSet: relationships.routerIds,
    routerScoresByChild: relationships.scoresByChild,
    parentByChild: relationships.parentByChild,
    childrenByParent: relationships.childrenByParent,
    childHasParentChildLink: relationships.explicitChildren,
    zoneByNodeId: zoning.zoneByNodeId,
    zoneNodeIds: zoning.zoneNodeIds,
    zones,
    zoneJitterByNodeId: new Map([...analysis.nodeById.keys()].map((id) => [id, layoutJitter(id)])),
    totalNodesClassified: zoning.zoneByNodeId.size,
  });
}

const AXES = Object.freeze({
  horizontal: Object.freeze({ primary: "x", cross: "y", fixPrimary: "x", fixCross: "y" }),
  vertical: Object.freeze({ primary: "y", cross: "x", fixPrimary: "y", fixCross: "x" }),
});

function setAxes(node, axes, primary, cross, child) {
  node[axes.primary] = Math.round(primary);
  node[axes.cross] = Math.round(cross);
  node.fixed = axes.primary === "x"
    ? { x: true, y: !child }
    : { x: !child, y: true };
  node.physics = child;
}

function relaxAxis(nodes, axis, clamp, minimumGap) {
  const ordered = nodes.filter(Boolean).sort((left, right) => (Number(left[axis]) || 0) - (Number(right[axis]) || 0));
  for (let index = 1; index < ordered.length; index += 1) {
    const previous = Number(ordered[index - 1][axis]) || 0;
    if ((Number(ordered[index][axis]) || 0) - previous < minimumGap) ordered[index][axis] = clamp(previous + minimumGap);
  }
  for (let index = ordered.length - 2; index >= 0; index -= 1) {
    const next = Number(ordered[index + 1][axis]) || 0;
    if (next - (Number(ordered[index][axis]) || 0) < minimumGap) ordered[index][axis] = clamp(next - minimumGap);
  }
  ordered.forEach((node) => { node[axis] = Math.round(Number(node[axis]) || 0); });
}

export function applyMeshTreeSeedLayout(nodes, edges, config = {}) {
  const axes = AXES[config.orientation || "horizontal"];
  if (!axes) throw new Error(`Unknown mesh-tree orientation: ${config.orientation}`);
  const context = buildMeshTreeZoningContext(nodes, edges);
  if (context.totalNodesClassified === 0) return context;
  const maxCount = Math.max(1, ...ZONE_ORDER.map((zone) => context.zoneNodeIds.get(zone).length));
  const halfSpan = Math.max(780, Math.round(maxCount * 86));
  const clamp = (value) => Math.max(-halfSpan - 140, Math.min(halfSpan + 140, value));

  const distribute = (zone) => {
    const ids = context.zoneNodeIds.get(zone);
    const center = (ids.length - 1) / 2;
    ids.forEach((nodeId, index) => {
      const jitter = layoutJitter(nodeId);
      const crossJitter = zone === 10 || zone === -20 ? 10 : 14;
      setAxes(
        context.nodeById.get(nodeId), axes,
        ZONE_ANCHORS[zone] + jitter * 18,
        clamp((index - center) * ZONE_SPACING[zone] + jitter * crossJitter),
        CHILD_ZONES.has(zone),
      );
    });
  };
  [10, -20, -50].forEach(distribute);

  const borderRouters = context.zoneNodeIds.get(10).map((id) => context.nodeById.get(id));
  relaxAxis(borderRouters, axes.cross, clamp, 560);
  if (borderRouters.length > 1) {
    const values = borderRouters.map((node) => Number(node[axes.cross]) || 0);
    const delta = -(Math.min(...values) + Math.max(...values)) / 2;
    borderRouters.forEach((node) => { node[axes.cross] = Math.round(clamp((Number(node[axes.cross]) || 0) + delta)); });
  }
  const parentRouters = sortedIds(context.childrenByParent.keys())
    .filter((id) => context.zoneByNodeId.get(id) === -20)
    .map((id) => context.nodeById.get(id));
  relaxAxis(parentRouters, axes.cross, clamp, 158);

  CHILD_ZONES.forEach((zone) => {
    const ids = context.zoneNodeIds.get(zone);
    const byParent = new Map();
    const remaining = [];
    ids.forEach((childId) => {
      const parentId = context.parentByChild.get(childId);
      if (!parentId || !context.nodeById.has(parentId)) remaining.push(childId);
      else {
        if (!byParent.has(parentId)) byParent.set(parentId, []);
        byParent.get(parentId).push(childId);
      }
    });
    const used = new Set();
    [...byParent.keys()].sort((left, right) => (
      (Number(context.nodeById.get(left)?.[axes.cross]) || 0)
      - (Number(context.nodeById.get(right)?.[axes.cross]) || 0)
      || String(left).localeCompare(String(right))
    )).forEach((parentId) => {
      const childIds = sortedIds(byParent.get(parentId));
      const center = (childIds.length - 1) / 2;
      childIds.forEach((childId, index) => {
        const jitter = layoutJitter(`${parentId}|${childId}`);
        setAxes(
          context.nodeById.get(childId), axes,
          ZONE_ANCHORS[zone] + jitter * 14,
          clamp((Number(context.nodeById.get(parentId)?.[axes.cross]) || 0) + (index - center) * ([30, -30].includes(zone) ? 66 : 76) + jitter * 10),
          true,
        );
        used.add(childId);
      });
    });
    const leftovers = sortedIds([...remaining, ...ids.filter((id) => !used.has(id))]);
    const center = (leftovers.length - 1) / 2;
    leftovers.forEach((childId, index) => {
      const jitter = layoutJitter(childId);
      setAxes(context.nodeById.get(childId), axes, ZONE_ANCHORS[zone] + jitter * 16, clamp((index - center) * ZONE_SPACING[zone] + jitter * 12), true);
    });
  });

  ZONE_ORDER.filter((zone) => zone !== 0).forEach((zone) => {
    relaxAxis(context.zoneNodeIds.get(zone).map((id) => context.nodeById.get(id)), axes.cross, clamp, ZONE_MIN_GAP[zone]);
  });
  return context;
}

export function applyMeshTreeHorizontalSeedLayout(nodes, edges) {
  return applyMeshTreeSeedLayout(nodes, edges, { orientation: "horizontal" });
}

export function applyMeshTreeVerticalSeedLayout(nodes, edges) {
  return applyMeshTreeSeedLayout(nodes, edges, { orientation: "vertical" });
}

export function applyLayoutPinning(nodes, fixed = true) {
  nodes.forEach((node) => {
    node.fixed = { x: fixed, y: fixed };
    node.physics = !fixed;
  });
}

export function resolveLayoutCollisions(nodes, options = {}) {
  const maxIterations = options.maxIterations ?? 120;
  const damping = options.damping ?? 0.55;
  const separation = options.separation ?? (() => 172);
  const afterIteration = options.afterIteration;
  let iterations = 0;
  let converged = false;
  for (; iterations < maxIterations; iterations += 1) {
    let moved = false;
    for (let leftIndex = 0; leftIndex < nodes.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < nodes.length; rightIndex += 1) {
        const left = nodes[leftIndex];
        const right = nodes[rightIndex];
        const deltaX = (right.x || 0) - (left.x || 0);
        const deltaY = (right.y || 0) - (left.y || 0);
        const distance = Math.hypot(deltaX, deltaY) || 0.01;
        const minimum = separation(left, right);
        if (distance >= minimum) continue;
        const overlap = (minimum - distance) * damping;
        const unitX = deltaX / distance;
        const unitY = deltaY / distance;
        left.x = Math.round((left.x || 0) - unitX * overlap * 0.5);
        left.y = Math.round((left.y || 0) - unitY * overlap * 0.5);
        right.x = Math.round((right.x || 0) + unitX * overlap * 0.5);
        right.y = Math.round((right.y || 0) + unitY * overlap * 0.5);
        moved = true;
      }
    }
    if (afterIteration?.() === true) moved = true;
    if (!moved) {
      converged = true;
      break;
    }
  }
  return Object.freeze({ iterations, converged, maxIterations });
}

export function classifyRingGraph(nodes, edges) {
  const analysis = buildGraphAnalysis(nodes, edges.filter((edge) => edge.baseHidden !== true));
  const relationships = classifyParentRelationships(analysis);
  const routers = [...analysis.nodeById.values()].filter((node) => node.isRouter === true).sort((a, b) => String(a.id).localeCompare(String(b.id)));
  const connectedIds = new Set(analysis.visibleEdges.flatMap((edge) => [edge.from, edge.to]));
  return Object.freeze({ analysis, relationships, routers, connectedIds });
}

export function assignRingMembership(classification) {
  const explicitByParent = new Map();
  const explicitlyAssigned = new Set();
  classification.analysis.visibleEdges.forEach((edge) => {
    if (!isExplicitChildEdge(edge)) return;
    const fromRouter = classification.relationships.routerIds.has(edge.from);
    const toRouter = classification.relationships.routerIds.has(edge.to);
    if (fromRouter === toRouter) return;
    const parentId = fromRouter ? edge.from : edge.to;
    const childId = fromRouter ? edge.to : edge.from;
    if (!explicitByParent.has(parentId)) explicitByParent.set(parentId, new Set());
    explicitByParent.get(parentId).add(childId);
    explicitlyAssigned.add(childId);
  });
  classification.relationships.parentByChild.forEach((parentId, childId) => {
    if (explicitlyAssigned.has(childId)) return;
    if (!explicitByParent.has(parentId)) explicitByParent.set(parentId, new Set());
    explicitByParent.get(parentId).add(childId);
  });
  const childrenByParent = new Map(
    sortedIds(explicitByParent.keys()).map((parentId) => [parentId, new Set(sortedIds(explicitByParent.get(parentId)))]),
  );
  const childCounts = new Map(classification.routers.map((router) => [router.id, childrenByParent.get(router.id)?.size || 0]));
  const routerIds = classification.routers.map((router) => router.id).sort((left, right) => childCounts.get(right) - childCounts.get(left) || String(left).localeCompare(String(right)));
  const interleaved = [];
  for (let low = 0, high = routerIds.length - 1; low <= high; low += 1, high -= 1) {
    interleaved.push(routerIds[low]);
    if (low < high) interleaved.push(routerIds[high]);
  }
  const ftdChildren = [];
  const otherChildren = [];
  childrenByParent.forEach((childIds, parentId) => {
    childIds.forEach((childId) => {
      (isFtd(classification.analysis.nodeById.get(childId)) ? ftdChildren : otherChildren).push({ parentId, childId });
    });
  });
  const isolated = [...classification.analysis.nodeById.values()].filter((node) => !classification.connectedIds.has(node.id));
  return Object.freeze({ routerIds: interleaved, ftdChildren, otherChildren, isolated, childrenByParent });
}

export function calculateRingRadii(routerCount, config = RING_CONFIG) {
  const router = Math.max(380, routerCount * 38);
  return Object.freeze({ router, ftd: router + config.ftdBandOffset, mtd: router + config.mtdBandOffset, isolated: router + 570, fallback: router + 680 });
}

function placeOnRing(nodesById, ids, radius, angleById = null) {
  ids.forEach((id, index) => {
    const angle = angleById?.get(id) ?? (-Math.PI / 2 + (2 * Math.PI * index) / Math.max(1, ids.length));
    const node = nodesById.get(id);
    node.x = Math.round(radius * Math.cos(angle));
    node.y = Math.round(radius * Math.sin(angle));
  });
}

function routerAngles(classification, routerIds) {
  const neighbors = new Map(routerIds.map((id) => [id, new Set()]));
  classification.analysis.visibleEdges.forEach((edge) => {
    if (edge.lqLevel !== 3 || !neighbors.has(edge.from) || !neighbors.has(edge.to)) return;
    neighbors.get(edge.from).add(edge.to);
    neighbors.get(edge.to).add(edge.from);
  });
  const weights = routerIds.map((id, index) => neighbors.get(id).has(routerIds[(index + 1) % routerIds.length]) ? 0.95 : 1.05);
  const total = weights.reduce((sum, weight) => sum + weight, 0) || routerIds.length;
  const angles = new Map();
  let angle = -Math.PI / 2;
  routerIds.forEach((id, index) => { angles.set(id, angle); angle += 2 * Math.PI * weights[index] / total; });
  return angles;
}

export function placeRingNodes(classification, membership, radii, config = RING_CONFIG) {
  const nodeById = classification.analysis.nodeById;
  const angles = routerAngles(classification, membership.routerIds);
  placeOnRing(nodeById, membership.routerIds, radii.router, angles);
  const placed = new Set(membership.routerIds);
  const placeChildren = (entries, minimumRadius, parentDistance, spreadScale) => {
    const byParent = new Map();
    entries.forEach(({ parentId, childId }) => { if (!byParent.has(parentId)) byParent.set(parentId, []); byParent.get(parentId).push(childId); });
    byParent.forEach((childIds, parentId) => {
      const parent = nodeById.get(parentId);
      const ids = sortedIds(childIds);
      const spread = Math.min(Math.PI * 1.65, Math.max(Math.PI / 3, ids.length * spreadScale));
      ids.forEach((childId, index) => {
        const child = nodeById.get(childId);
        const offset = ids.length === 1 ? 0 : -spread / 2 + spread * index / (ids.length - 1);
        const layer = Math.floor(index / 3);
        const theta = (angles.get(parentId) || 0) + offset + layoutJitter(`${parentId}|${childId}|theta`, Math.PI / 9);
        const distance = parentDistance + layer * config.childLayerDistance + layoutJitter(`${parentId}|${childId}|radius`, 34);
        child.x = Math.round((parent.x || 0) + distance * Math.cos(theta));
        child.y = Math.round((parent.y || 0) + distance * Math.sin(theta));
        const radius = Math.hypot(child.x, child.y);
        if (radius < minimumRadius + layer * 34) {
          const scale = (minimumRadius + layer * 34) / Math.max(1, radius);
          child.x = Math.round(child.x * scale);
          child.y = Math.round(child.y * scale);
        }
        placed.add(childId);
      });
    });
  };
  placeChildren(membership.ftdChildren, radii.ftd, config.ftdParentDistance, 0.28);
  placeChildren(membership.otherChildren, radii.mtd, config.mtdParentDistance, 0.34);
  placeOnRing(nodeById, sortedIds(membership.isolated.map((node) => node.id)), radii.isolated);
  membership.isolated.forEach((node) => placed.add(node.id));
  placeOnRing(nodeById, sortedIds([...nodeById.keys()].filter((id) => !placed.has(id))), radii.fallback);
  return { placed, angles };
}

export function applyRingStarSeedLayout(nodes, edges) {
  const classification = classifyRingGraph(nodes, edges);
  if (classification.routers.length === 0) return Object.freeze({ collisionIterations: 0, converged: true });
  const membership = assignRingMembership(classification);
  const radii = calculateRingRadii(classification.routers.length);
  placeRingNodes(classification, membership, radii);
  const childIds = new Set([...membership.ftdChildren, ...membership.otherChildren].map(({ childId }) => childId));
  const children = nodes.filter((node) => childIds.has(node.id));
  const collision = resolveLayoutCollisions(children, { maxIterations: RING_CONFIG.collisionIterations, separation: () => RING_CONFIG.childClearance });
  const parentByChild = new Map();
  [...membership.ftdChildren, ...membership.otherChildren].forEach(({ parentId, childId }) => {
    if (!parentByChild.has(childId)) parentByChild.set(childId, parentId);
  });
  const coupledCollision = resolveLayoutCollisions(children, {
    maxIterations: RING_CONFIG.collisionIterations,
    separation: () => RING_CONFIG.childClearance,
    afterIteration: () => {
      let moved = false;
      parentByChild.forEach((parentId, childId) => {
        const parent = classification.analysis.nodeById.get(parentId);
        const child = classification.analysis.nodeById.get(childId);
        const deltaX = (child.x || 0) - (parent.x || 0);
        const deltaY = (child.y || 0) - (parent.y || 0);
        const distance = Math.hypot(deltaX, deltaY) || 0.01;
        const minimum = isFtd(child) ? RING_CONFIG.ftdParentClearance : RING_CONFIG.mtdParentClearance;
        if (distance >= minimum) return;
        const outwardTheta = Math.atan2(parent.y || 0, parent.x || 0);
        const unitX = distance > 0.01 ? deltaX / distance : Math.cos(outwardTheta);
        const unitY = distance > 0.01 ? deltaY / distance : Math.sin(outwardTheta);
        child.x = Math.round((parent.x || 0) + unitX * minimum);
        child.y = Math.round((parent.y || 0) + unitY * minimum);
        moved = true;
      });
      return moved;
    },
  });
  applyLayoutPinning(nodes);
  return Object.freeze({ classification, membership, radii, collisionIterations: collision.iterations, coupledCollisionIterations: coupledCollision.iterations, converged: collision.converged && coupledCollision.converged });
}

export function classifyMeshLabGraph(nodes, edges) {
  const ring = classifyRingGraph(nodes, edges);
  const membership = assignRingMembership(ring);
  const routersWithChildren = ring.routers.filter((router) => (membership.childrenByParent.get(router.id)?.size || 0) > 0 || router.hasChildren === true);
  const outerRouters = routersWithChildren.length > 0 ? routersWithChildren : ring.routers;
  const outerIds = new Set(outerRouters.map((router) => router.id));
  const innerRouters = ring.routers.filter((router) => !outerIds.has(router.id));
  return Object.freeze({ ...ring, membership, outerRouters, innerRouters });
}

export function placeMeshLabRouters(classification) {
  const byCount = classification.outerRouters.slice().sort((left, right) => (
    (classification.membership.childrenByParent.get(right.id)?.size || 0)
    - (classification.membership.childrenByParent.get(left.id)?.size || 0)
    || String(left.id).localeCompare(String(right.id))
  ));
  const outerIds = [];
  for (let low = 0, high = byCount.length - 1; low <= high; low += 1, high -= 1) {
    outerIds.push(byCount[low].id);
    if (low < high) outerIds.push(byCount[high].id);
  }
  const outerRadius = Math.max(560, outerIds.length * 68);
  const innerRadius = Math.max(335, Math.floor(outerRadius * 0.68));
  const neighbors = new Map(outerIds.map((id) => [id, new Set()]));
  classification.analysis.visibleEdges.forEach((edge) => {
    if (edge.lqLevel !== 3 || !neighbors.has(edge.from) || !neighbors.has(edge.to)) return;
    neighbors.get(edge.from).add(edge.to);
    neighbors.get(edge.to).add(edge.from);
  });
  const weights = outerIds.map((id, index) => neighbors.get(id).has(outerIds[(index + 1) % outerIds.length]) ? 0.92 : 1.08);
  const totalWeight = weights.reduce((sum, weight) => sum + weight, 0) || outerIds.length;
  const angles = new Map();
  let angle = -Math.PI / 2;
  outerIds.forEach((id, index) => { angles.set(id, angle); angle += 2 * Math.PI * weights[index] / totalWeight; });
  placeOnRing(classification.analysis.nodeById, outerIds, outerRadius, angles);
  classification.innerRouters.sort((a, b) => String(a.id).localeCompare(String(b.id))).forEach((router, index, values) => {
    const anchor = -Math.PI / 2 + 2 * Math.PI * index / Math.max(1, values.length);
    const radius = innerRadius + (index % 2 === 0 ? -34 : 34) + layoutJitter(`${router.id}|innerR`, 30);
    const theta = anchor + layoutJitter(`${router.id}|innerTheta`, Math.PI / 10);
    router.x = Math.round(radius * Math.cos(theta));
    router.y = Math.round(radius * Math.sin(theta));
  });
  return Object.freeze({ outerIds, outerRadius, innerRadius, angles });
}

export function placeMeshLabChildren(classification, routerPlacement, config = COMPACT_CONFIG) {
  const childTypeById = new Map();
  const childrenByParent = classification.membership.childrenByParent;
  childrenByParent.forEach((childIdSet, parentId) => {
    const childIds = sortedIds(childIdSet);
    childIds.forEach((childId) => childTypeById.set(childId, isFtd(classification.analysis.nodeById.get(childId)) ? "ftd" : "mtd"));
    const parent = classification.analysis.nodeById.get(parentId);
    ["mtd", "ftd"].forEach((type) => {
      const ids = sortedIds(childIds.filter((id) => childTypeById.get(id) === type));
      const spreadScale = type === "ftd" ? config.ftdSpreadScale : config.mtdSpreadScale;
      const spread = Math.min(Math.PI * 1.82, Math.max(Math.PI / 3, ids.length * spreadScale));
      ids.forEach((childId, index) => {
        const child = classification.analysis.nodeById.get(childId);
        const layer = Math.floor(index / 3);
        const offset = ids.length === 1 ? 0 : -spread / 2 + spread * index / (ids.length - 1);
        const theta = Math.atan2(parent.y || 0, parent.x || 0) + offset + layoutJitter(`${parentId}|${childId}|theta`, type === "ftd" ? Math.PI / 10 : Math.PI / 11);
        const base = type === "ftd" ? config.ftdParentDistance : config.mtdParentDistance;
        const distance = base + layer * config.childLayerDistance + layoutJitter(`${parentId}|${childId}|r`, type === "ftd" ? 26 : 20);
        child.x = Math.round((parent.x || 0) + distance * Math.cos(theta));
        child.y = Math.round((parent.y || 0) + distance * Math.sin(theta));
        const minimum = Math.max(
          Math.hypot(parent.x || 0, parent.y || 0) + 70,
          routerPlacement.outerRadius + (type === "ftd" ? config.ftdBandOffset : config.mtdBandOffset) + layer * 36,
        );
        const radius = Math.hypot(child.x, child.y);
        if (radius < minimum) {
          const scale = minimum / Math.max(1, radius);
          child.x = Math.round(child.x * scale);
          child.y = Math.round(child.y * scale);
        }
      });
    });
  });
  return childTypeById;
}

export function placeIsolatedMeshLabNodes(classification, outerRadius, childTypeById) {
  const maximumMtdRadius = [...classification.analysis.nodeById.values()].reduce((maximum, node) => (
    childTypeById.get(node.id) === "mtd" && Number.isFinite(node.x)
      ? Math.max(maximum, Math.hypot(node.x, node.y))
      : maximum
  ), 0);
  const radius = Math.max(outerRadius + 700, maximumMtdRadius + 140);
  const isolated = [...classification.analysis.nodeById.values()].filter((node) => (
    !classification.connectedIds.has(node.id)
    && node.isRouter !== true
    && node.isBorderRouter !== true
    && !childTypeById.has(node.id)
    && !isFtd(node)
  )).sort((a, b) => String(a.id).localeCompare(String(b.id)));
  placeOnRing(classification.analysis.nodeById, isolated.map((node) => node.id), radius);
  return Object.freeze({ isolated, radius });
}

export function applyMeshLabHybridSeedLayout(nodes, edges) {
  const classification = classifyMeshLabGraph(nodes, edges);
  if (classification.routers.length === 0) return Object.freeze({ collisionIterations: 0, finalCollisionIterations: 0, converged: true });
  const routerPlacement = placeMeshLabRouters(classification);
  const childTypeById = placeMeshLabChildren(classification, routerPlacement);
  const parentByChild = new Map();
  classification.membership.childrenByParent.forEach((childIds, parentId) => {
    sortedIds(childIds).forEach((childId) => { if (!parentByChild.has(childId)) parentByChild.set(childId, parentId); });
  });
  const outerIds = new Set(routerPlacement.outerIds);
  const movable = nodes.filter((node) => !outerIds.has(node.id) && Number.isFinite(node.x) && (node.isRouter === true || parentByChild.has(node.id)));
  const collision = resolveLayoutCollisions(movable, {
    maxIterations: COMPACT_CONFIG.collisionIterations,
    damping: 0.57,
    separation: (left, right) => left.isRouter === true || right.isRouter === true ? COMPACT_CONFIG.routerClearance : COMPACT_CONFIG.childClearance,
    afterIteration: () => {
      let moved = false;
      parentByChild.forEach((parentId, childId) => {
        const parent = classification.analysis.nodeById.get(parentId);
        const child = classification.analysis.nodeById.get(childId);
        let deltaX = (child.x || 0) - (parent.x || 0);
        let deltaY = (child.y || 0) - (parent.y || 0);
        const distance = Math.hypot(deltaX, deltaY) || 0.01;
        const maximum = childTypeById.get(childId) === "ftd" ? COMPACT_CONFIG.ftdMaxParentDistance : COMPACT_CONFIG.mtdMaxParentDistance;
        if (distance > maximum) {
          const scale = maximum / distance;
          child.x = Math.round((parent.x || 0) + deltaX * scale);
          child.y = Math.round((parent.y || 0) + deltaY * scale);
          moved = true;
        }
        const minimum = routerPlacement.outerRadius + (childTypeById.get(childId) === "ftd" ? COMPACT_CONFIG.ftdBandOffset : COMPACT_CONFIG.mtdBandOffset);
        const radius = Math.hypot(child.x || 0, child.y || 0);
        if (radius < minimum) {
          const scale = minimum / Math.max(1, radius);
          child.x = Math.round((child.x || 0) * scale);
          child.y = Math.round((child.y || 0) * scale);
          moved = true;
        }
      });
      return moved;
    },
  });
  const children = movable.filter((node) => node.isRouter !== true);
  const finalCollision = resolveLayoutCollisions(children, {
    maxIterations: COMPACT_CONFIG.finalCollisionIterations,
    damping: 0.62,
    separation: () => COMPACT_CONFIG.childClearance,
  });
  const isolated = placeIsolatedMeshLabNodes(classification, routerPlacement.outerRadius, childTypeById);
  applyLayoutPinning(nodes.filter((node) => Number.isFinite(node.x) && Number.isFinite(node.y)));
  return Object.freeze({ classification, routerPlacement, childTypeById, isolated, collisionIterations: collision.iterations, finalCollisionIterations: finalCollision.iterations, converged: collision.converged && finalCollision.converged });
}