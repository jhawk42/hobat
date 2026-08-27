import {
  EDGE_CATEGORY_DEFAULT_CHILDREN,
  EDGE_CATEGORY_OTBR_CHILD,
  EDGE_CATEGORY_ROUTER_NEIGHBOR,
  DIAGNOSTIC_FILTER_OPTIONS,
} from "./tdash-constants.js";
import { getDeviceIdentityKeys } from "./tdash-device-fields.js";
import {
  edgeMatchesLinkFilter,
  isChildLinkQualityDiagnosticMode,
  isNodeVisibleByDiagnosticFilter,
  isNodeVisibleByFilter,
  isRouterChildDiagnosticMode,
  isRouterNeighborDiagnosticMode,
  childMatchesLinkQualityFilter,
  routerChildRowMatchesDiagnosticFilter,
  routerNeighborRowMatchesDiagnosticFilter,
} from "./tdash-filters.js";
import { rowMatchesSearch } from "./tdash-search.js";
import {
  buildTopologyEdgeIndexes,
  computeDatasetCounts,
  expandVisibleRelationship,
} from "./tdash-topology-utils.js";
import { getColumnValue, mergeForDisplay, toText } from "./tdash-utils.js";

const TOPOLOGY_DIAGNOSTIC_FIELDS = Object.freeze([
  ...new Set([
    ...DIAGNOSTIC_FILTER_OPTIONS.map((option) => option.topoNodeField),
    "isFtdRouter",
  ].filter(Boolean)),
]);

function cloneValue(value) {
  if (Array.isArray(value)) return value.map(cloneValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, nestedValue]) => [key, cloneValue(nestedValue)]),
    );
  }
  return value;
}

function cloneNodeStyle(node) {
  return Object.freeze({
    color: node?.color && typeof node.color === "object" ? { ...node.color } : node?.color,
    borderWidth: node?.borderWidth,
    font: node?.font && typeof node.font === "object" ? { ...node.font } : node?.font,
  });
}

function identityKeysForRecord(record) {
  const keys = getDeviceIdentityKeys(record);
  const explicitId = toText(record?.id).toLowerCase();
  return explicitId ? [...keys, `id:${explicitId}`] : keys;
}

function indexIdentity(identityToNodeId, record, nodeId) {
  identityKeysForRecord(record).forEach((key) => {
    if (!identityToNodeId.has(key)) identityToNodeId.set(key, nodeId);
  });
}

function getRouterChildRows(viewModel, parentNodeId) {
  const parentRaw = viewModel.rawByIdForDetails.get(parentNodeId) || {};
  const rawChildTable = getColumnValue(parentRaw, "childTable")
    ?? getColumnValue(parentRaw, "router_child_table");
  const rowsFromRaw = Array.isArray(rawChildTable) ? rawChildTable : [];
  const parentRloc16 = toText(viewModel.nodeMap.get(parentNodeId)?.rloc16).toLowerCase();
  const indexedRecord = viewModel.routerChildByRloc16.get(parentRloc16) || {};
  const indexedChildTable = getColumnValue(indexedRecord, "childTable")
    ?? getColumnValue(indexedRecord, "router_child_table");
  const rowsFromIndex = Array.isArray(indexedChildTable) ? indexedChildTable : [];
  const mergedRows = [];
  const seen = new Set();

  [...rowsFromIndex, ...rowsFromRaw].forEach((row) => {
    const keys = identityKeysForRecord(row);
    const fallback = toText(row?.child_id || row?.childId).toLowerCase();
    const dedupeKey = keys[0] || (fallback ? `child:${fallback}` : `anonymous:${mergedRows.length}`);
    if (seen.has(dedupeKey)) return;
    seen.add(dedupeKey);
    mergedRows.push(row);
  });
  return mergedRows;
}

export function createTopologyViewModel(adaptorResult) {
  const nodes = (adaptorResult.nodeData || []).map(cloneValue);
  const edges = (adaptorResult.edgeData || []).map(cloneValue);
  const nodeMap = new Map(
    [...(adaptorResult.nodeMap || nodes.map((node) => [node.id, node]))]
      .map(([nodeId, node]) => [nodeId, cloneValue(node)]),
  );
  const rawByIdForDetails = new Map(
    [...(adaptorResult.rawByIdForDetails || [])]
      .map(([nodeId, record]) => [nodeId, cloneValue(record)]),
  );
  const identityToNodeId = new Map();

  nodeMap.forEach((node, nodeId) => indexIdentity(identityToNodeId, node, nodeId));
  rawByIdForDetails.forEach((row, nodeId) => indexIdentity(identityToNodeId, row, nodeId));

  return Object.freeze({
    nodes,
    edges,
    nodeMap,
    rawByIdForDetails,
    routerNeighborByRloc16: new Map(
      [...(adaptorResult.routerNeighborByRloc16 || [])]
        .map(([rloc16, record]) => [rloc16, cloneValue(record)]),
    ),
    routerChildByRloc16: new Map(
      [...(adaptorResult.routerChildByRloc16 || [])]
        .map(([rloc16, record]) => [rloc16, cloneValue(record)]),
    ),
    sourceNames: [...(adaptorResult.sourceNames || [])],
    identityToNodeId,
    originalNodeStyling: new Map(nodes.map((node) => [node.id, cloneNodeStyle(node)])),
    edgeIndexes: buildTopologyEdgeIndexes(edges),
    datasetCounts: computeDatasetCounts(nodes, edges),
  });
}

export function resolveTopologyNodeId(viewModel, record) {
  for (const key of identityKeysForRecord(record)) {
    if (viewModel.identityToNodeId.has(key)) return viewModel.identityToNodeId.get(key);
  }
  const fallback = toText(record?.id).toLowerCase();
  return viewModel.nodeMap.has(fallback) ? fallback : null;
}

export function createTopologyFilterState(nodeMode, linkMode, diagnosticMode) {
  return Object.freeze({ nodeMode, linkMode, diagnosticMode });
}

export function computeTopologyVisibility(viewModel, filterState) {
  const visibleNodeIds = new Set();
  const forcedVisibleEdgeIds = new Set();
  const matchedTargetNodeIds = new Set();

  const expandDiagnosticMatch = (sourceId, targetId, categories, diagnosticRecord) => {
    categories.forEach((category) => {
      expandVisibleRelationship({
        sourceId,
        targetId,
        category,
        directed: false,
        diagnosticRecord,
        optionValue: filterState.diagnosticMode,
      }, viewModel.edgeIndexes, visibleNodeIds, forcedVisibleEdgeIds);
    });
  };

  viewModel.nodes.forEach((node) => {
    if (
      isNodeVisibleByFilter(node, filterState.nodeMode)
      && isNodeVisibleByDiagnosticFilter(node, filterState.diagnosticMode)
    ) visibleNodeIds.add(node.id);
  });

  if (filterState.nodeMode === "routers-with-children") {
    viewModel.edges.forEach((edge) => {
      if (
        edge.isParentChild === true
        && edgeMatchesLinkFilter(edge, filterState.linkMode)
        && visibleNodeIds.has(edge.from)
      ) visibleNodeIds.add(edge.to);
    });
  }

  if (isRouterNeighborDiagnosticMode(filterState.diagnosticMode)) {
    [...visibleNodeIds].forEach((sourceNodeId) => {
      const sourceRloc16 = toText(viewModel.nodeMap.get(sourceNodeId)?.rloc16).toLowerCase();
      const neighborRecord = viewModel.routerNeighborByRloc16.get(sourceRloc16) || {};
      const neighbors = getColumnValue(neighborRecord, "routerNeighbors")
        ?? getColumnValue(neighborRecord, "router_neighbor_table");
      (Array.isArray(neighbors) ? neighbors : [])
        .filter((neighbor) => routerNeighborRowMatchesDiagnosticFilter(neighbor, filterState.diagnosticMode))
        .forEach((neighbor) => {
          const targetId = resolveTopologyNodeId(viewModel, neighbor);
          if (!targetId) return;
          matchedTargetNodeIds.add(targetId);
          expandDiagnosticMatch(sourceNodeId, targetId, [EDGE_CATEGORY_ROUTER_NEIGHBOR], neighbor);
        });
    });
  }

  if (isChildLinkQualityDiagnosticMode(filterState.diagnosticMode)) {
    [...visibleNodeIds].forEach((parentNodeId) => {
      const children = viewModel.rawByIdForDetails.get(parentNodeId)?.children;
      (Array.isArray(children) ? children : [])
        .filter((child) => childMatchesLinkQualityFilter(child, filterState.diagnosticMode))
        .forEach((child) => {
          const childId = resolveTopologyNodeId(viewModel, child);
          if (!childId) return;
          matchedTargetNodeIds.add(childId);
          expandDiagnosticMatch(
            parentNodeId,
            childId,
            [EDGE_CATEGORY_DEFAULT_CHILDREN, EDGE_CATEGORY_OTBR_CHILD],
            child,
          );
        });
    });
  }

  if (isRouterChildDiagnosticMode(filterState.diagnosticMode)) {
    [...visibleNodeIds].forEach((parentNodeId) => {
      getRouterChildRows(viewModel, parentNodeId)
        .filter((child) => routerChildRowMatchesDiagnosticFilter(child, filterState.diagnosticMode))
        .forEach((child) => {
          const childId = resolveTopologyNodeId(viewModel, child);
          if (!childId) return;
          matchedTargetNodeIds.add(childId);
          expandDiagnosticMatch(
            parentNodeId,
            childId,
            [EDGE_CATEGORY_DEFAULT_CHILDREN, EDGE_CATEGORY_OTBR_CHILD],
            child,
          );
        });
    });
  }

  const visibleEdgeIds = new Set();
  viewModel.edges.forEach((edge) => {
    if (
      edge.baseHidden !== true
      && visibleNodeIds.has(edge.from)
      && visibleNodeIds.has(edge.to)
      && (edgeMatchesLinkFilter(edge, filterState.linkMode) || forcedVisibleEdgeIds.has(edge.id))
    ) visibleEdgeIds.add(edge.id);
  });

  return Object.freeze({
    visibleNodeIds,
    visibleEdgeIds,
    forcedVisibleEdgeIds,
    matchedTargetNodeIds,
    visibleNodeCount: visibleNodeIds.size,
    visibleEdgeCount: visibleEdgeIds.size,
    matchedTargetNodeCount: matchedTargetNodeIds.size,
    forcedVisibleLinkCount: forcedVisibleEdgeIds.size,
  });
}

export function createTopologySearchState(query, advancedMode, viewModel) {
  const matchingNodeIds = new Set();
  if (query) {
    viewModel.rawByIdForDetails.forEach((row, nodeId) => {
      if (rowMatchesSearch(row, query, advancedMode)) matchingNodeIds.add(nodeId);
    });
  }
  return Object.freeze({ query, advancedMode, matchingNodeIds });
}

export function computeSearchHighlight(viewModel, searchState) {
  const nodeUpdates = [...viewModel.originalNodeStyling.entries()].map(([nodeId, originalStyle]) => {
    if (!searchState.query) return { id: nodeId, ...cloneNodeStyle(originalStyle) };
    if (searchState.matchingNodeIds.has(nodeId)) {
      return {
        id: nodeId,
        color: { background: originalStyle.color?.background, border: "#d97706" },
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
  });
  const focusTarget = searchState.matchingNodeIds.size === 1
    ? [...searchState.matchingNodeIds][0]
    : null;
  return Object.freeze({ nodeUpdates, focusTarget });
}

export function buildTopologyDetails(viewModel, selectedId) {
  const node = viewModel.nodeMap.get(selectedId);
  if (!node) return null;
  const graphLinkCount = viewModel.edges.filter(
    (edge) => edge.from === selectedId || edge.to === selectedId,
  ).length;
  const graphDetails = {
    graph: {
      unifiedId: selectedId,
      graphLinkCount,
      isRouter: node.isRouter || node.is_router || (
        typeof node.rloc16 === "string"
        && node.rloc16.toLowerCase().startsWith("0x")
        && node.rloc16.toLowerCase().endsWith("00")
        && node.rloc16.length === 6
      ) || toText(node.role).toLowerCase() === "router",
      hasChildren: viewModel.nodes.some((candidate) => candidate.id === selectedId && candidate.hasChildren),
    },
  };
  const diagnosticDetails = Object.fromEntries(
    TOPOLOGY_DIAGNOSTIC_FIELDS.map((field) => [field, node[field]]),
  );
  return mergeForDisplay(
    mergeForDisplay(viewModel.rawByIdForDetails.get(selectedId) || {}, diagnosticDetails),
    graphDetails,
  );
}

export function buildTopologyStatus(viewModel, visibility, searchState, scale, options = {}) {
  const neighborSuffix = isRouterNeighborDiagnosticMode(options.diagnosticMode)
    ? ` Neighbor Match: targets ${visibility.matchedTargetNodeCount}, links ${visibility.forcedVisibleLinkCount}.`
    : "";
  const searchSuffix = searchState?.query
    ? ` Search: "${searchState.query}" — ${searchState.matchingNodeIds.size} of ${viewModel.rawByIdForDetails.size} rows match.`
    : "";
  const stabilizationSuffix = Number.isFinite(options.stabilizationMs)
    ? ` Stabilized: ${(options.stabilizationMs / 1000).toFixed(2)}s.`
    : "";
  const scaleText = Number.isFinite(scale) ? `${scale.toFixed(2)}x` : "";
  return Object.freeze({
    visibleNodeCount: visibility.visibleNodeCount,
    visibleEdgeCount: visibility.visibleEdgeCount,
    scale: scaleText,
    text: `Showing: ${visibility.visibleNodeCount} nodes, ${visibility.visibleEdgeCount} links. Physics profile: ${options.physicsProfileLabel || ""}.${stabilizationSuffix}${neighborSuffix}${searchSuffix}`,
  });
}

export function createTopologyEventBindings() {
  const disposers = [];
  let disposed = false;
  return Object.freeze({
    on(target, eventName, listener) {
      if (disposed) return listener;
      target.on(eventName, listener);
      disposers.push(() => target.off(eventName, listener));
      return listener;
    },
    once(target, eventName, listener) {
      if (disposed) return listener;
      const wrapped = (...args) => {
        if (typeof target.off === "function") target.off(eventName, wrapped);
        else target.removeEventListener(eventName, wrapped);
        listener(...args);
      };
      if (typeof target.on === "function") target.on(eventName, wrapped);
      else target.addEventListener(eventName, wrapped);
      disposers.push(() => {
        if (typeof target.off === "function") target.off(eventName, wrapped);
        else target.removeEventListener(eventName, wrapped);
      });
      return listener;
    },
    listen(target, eventName, listener, options) {
      if (disposed) return listener;
      target.addEventListener(eventName, listener, options);
      disposers.push(() => target.removeEventListener(eventName, listener, options));
      return listener;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      disposers.splice(0).reverse().forEach((dispose) => dispose());
    },
  });
}

export function createTopologyRenderOwner(network, bindings) {
  let active = true;
  return Object.freeze({
    isActive() {
      return active;
    },
    dispose() {
      if (!active) return;
      active = false;
      bindings.dispose();
      network.destroy();
    },
  });
}

export function applyTopologyTransition(nodesDataset, edgesDataset, transition) {
  nodesDataset.update([...transition.visibility.visibleNodeIds].map((id) => ({ id, hidden: false })));
  nodesDataset.update(
    transition.viewModel.nodes
      .filter((node) => !transition.visibility.visibleNodeIds.has(node.id))
      .map((node) => ({ id: node.id, hidden: true })),
  );
  edgesDataset.update(transition.viewModel.edges.map((edge) => ({
    id: edge.id,
    hidden: !transition.visibility.visibleEdgeIds.has(edge.id),
  })));
  if (transition.nodeUpdates) nodesDataset.update(transition.nodeUpdates);
}