import {
  EDGE_CATEGORY_DEFAULT_CHILDREN,
  EDGE_CATEGORY_OTBR_CHILD,
  EDGE_CATEGORY_EVE_CHILD,
  EDGE_CATEGORY_EVE_NATIVE_CHILD,
  EDGE_CATEGORY_ROUTER_NEIGHBOR,
  DIAGNOSTIC_FILTER_OPTIONS,
} from "./tdash-constants.js";
import {
  getDeviceIdentityKeys,
  getPreferredFieldPath,
  normalizeInputRecord,
  resolveIsReed,
} from "./tdash-device-fields.js";
import { buildDeviceProjection, projectAdaptorNode } from "./tdash-device-projection.js";
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
    shapeProperties: cloneValue(node?.shapeProperties),
  });
}

const CHILD_ROLES = new Set(["child", "reed", "enddevice", "sleepychild", "sleepyenddevice"]);
const CHILD_MODE_FIELDS = new Set(["isReed", "mode.device", "mode.fullThreadDevice", "mode.rxOnWhenIdle"]);

function resolveNodeThemeRole(node, records, isRelationshipChild) {
  if (node.isBorderRouter === true || node.themeRole === "borderRouter") return "borderRouter";
  if (node.isRouter === true || node.themeRole === "router") return "router";
  const evidence = records.filter(Boolean).map((record) => normalizeInputRecord(record));
  const child = isRelationshipChild || evidence.some((record) => (
    CHILD_ROLES.has(toText(record.role || record.type).toLowerCase().replace(/[\s_-]/g, ""))
  ));
  if (!child) return node.themeRole === "eve" ? "eve" : "unknown";

  const types = new Set();
  const receiverModes = new Set();
  const reedModes = new Set();
  for (const record of evidence) {
    if (Array.isArray(record._merge_conflicts)
        && record._merge_conflicts.some((conflict) => CHILD_MODE_FIELDS.has(getPreferredFieldPath(conflict?.path)))) {
      return "child";
    }
    const device = toText(getColumnValue(record, "mode.device")).toUpperCase();
    for (const fullThreadDevice of [
      getColumnValue(record, "mode.fullThreadDevice"), record.fullThreadDevice, record.deviceTypeFTD,
    ]) {
      if (typeof fullThreadDevice === "boolean") types.add(fullThreadDevice ? "FTD" : "MTD");
    }
    if (["FTD", "MTD"].includes(device)) types.add(device);
    for (const receiver of [getColumnValue(record, "mode.rxOnWhenIdle"), record.rxOnWhenIdle]) {
      if (typeof receiver === "boolean") receiverModes.add(receiver);
    }
    if (typeof record.isReed === "boolean") reedModes.add(record.isReed);
    if (toText(record.role).trim().toLowerCase() === "reed" || device === "REED") reedModes.add(true);
  }
  // Contradictory observations must not turn uncertainty into a confirmed subtype.
  if (types.size > 1 || receiverModes.size > 1 || reedModes.size > 1) return "child";
  const [deviceType] = types;
  const [isReed] = reedModes;
  if (isReed === true && deviceType === "MTD") return "child";
  if (resolveIsReed(isReed, deviceType, "child", false, false)) return "reed";
  if (deviceType === "MTD" && receiverModes.size === 1) {
    return receiverModes.has(true) ? "med" : "sed";
  }
  return "child";
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

export function createTopologyViewModel(
  adaptorResult,
  projections = new Map(),
) {
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

  const childNodeIds = new Set(edges.filter((edge) => edge.isParentChild === true
    || edge.linkCategories?.some((category) => [
      EDGE_CATEGORY_DEFAULT_CHILDREN, EDGE_CATEGORY_OTBR_CHILD,
      EDGE_CATEGORY_EVE_CHILD, EDGE_CATEGORY_EVE_NATIVE_CHILD,
    ].includes(category))).map((edge) => edge.to));
  const childEvidenceById = new Map();
  const owners = [
    ...nodeMap.values(), ...rawByIdForDetails.values(),
    ...(adaptorResult.routerChildByRloc16?.values() ?? []),
  ];
  owners.forEach((owner) => {
    for (const field of ["children", "childTable"]) {
      const children = getColumnValue(owner, field);
      if (!Array.isArray(children)) continue;
      children.forEach((record) => {
        const nodeId = identityKeysForRecord(record).map((key) => identityToNodeId.get(key)).find((id) => id !== undefined);
        if (nodeId === undefined) return;
        const address = getDeviceIdentityKeys(record).find((key) => key.startsWith("extAddress:"));
        const nodeAddress = getDeviceIdentityKeys(rawByIdForDetails.get(nodeId))
          .find((key) => key.startsWith("extAddress:"))
          ?? getDeviceIdentityKeys(nodeMap.get(nodeId)).find((key) => key.startsWith("extAddress:"));
        if (address && nodeAddress && address !== nodeAddress) return;
        childNodeIds.add(nodeId);
        const records = childEvidenceById.get(nodeId) ?? [];
        records.push(record);
        childEvidenceById.set(nodeId, records);
      });
    }
  });
  nodes.forEach((node) => {
    node.themeRole = resolveNodeThemeRole(node, [
      rawByIdForDetails.get(node.id), nodeMap.get(node.id),
      ...(childEvidenceById.get(node.id) ?? []),
    ], childNodeIds.has(node.id));
  });

  const projectionByIdentity = new Map();
  projections.forEach((projection) => {
    identityKeysForRecord(projection).forEach((key) => projectionByIdentity.set(key, projection));
  });
  const projectionByNodeId = new Map();
  const displayById = new Map(nodes.map((node) => [node.id, node]));
  nodeMap.forEach((node, nodeId) => {
    for (const record of [rawByIdForDetails.get(nodeId), node]) {
      const projection = identityKeysForRecord(record).map((key) => projectionByIdentity.get(key)).find(Boolean);
      if (projection) {
        projectionByNodeId.set(
          nodeId,
          projectAdaptorNode(
            projection,
            displayById.get(nodeId) ?? node,
          ),
        );
        break;
      }
    }
  });

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
    projectionByNodeId,
    originalNodeStyling: new Map(nodes.map((node) => [node.id, cloneNodeStyle(node)])),
    originalEdgeStyling: new Map(edges.map((edge) => [edge.id, Object.freeze({ color: cloneValue(edge.color) })])),
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
      isNodeVisibleByFilter(
        node,
        filterState.nodeMode,
        viewModel.projectionByNodeId.get(node.id),
      )
      && isNodeVisibleByDiagnosticFilter(node, filterState.diagnosticMode, viewModel.projectionByNodeId.get(node.id))
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

export function computeSearchHighlight(viewModel, searchState, palette = viewModel.themePalette) {
  const nodeUpdates = [...viewModel.originalNodeStyling.entries()].map(([nodeId, originalStyle]) => {
    if (!searchState.query) return { id: nodeId, ...cloneNodeStyle(originalStyle) };
    if (searchState.matchingNodeIds.has(nodeId)) {
      return {
        id: nodeId,
        color: {
          ...originalStyle.color,
          background: originalStyle.color?.background,
          border: palette?.searchMatch ?? "#d97706",
        },
        borderWidth: Math.max(originalStyle.borderWidth ?? 2, 4),
        font: originalStyle.font ? { ...originalStyle.font } : originalStyle.font,
      };
    }
    return {
      id: nodeId,
      color: {
        ...originalStyle.color,
        background: palette?.searchDimBg ?? "#e8e8e8",
        border: palette?.searchDimBorder ?? "#c0c0c0",
      },
      borderWidth: 1,
      font: { ...originalStyle.font, color: palette?.searchDimText ?? "#aaaaaa" },
    };
  });
  const focusTarget = searchState.matchingNodeIds.size === 1
    ? [...searchState.matchingNodeIds][0]
    : null;
  return Object.freeze({ nodeUpdates, focusTarget });
}

export function projectTopologyTheme(viewModel, palette, styleMode, searchState, healthStatuses = new Map()) {
  const originalNodeStyling = new Map(viewModel.nodes.map((node) => {
    const role = node.themeRole ?? (node.isBorderRouter ? "borderRouter" : node.isRouter ? "router" : "unknown");
    const base = viewModel.originalNodeStyling.get(node.id);
    const color = {
      background: palette[`${role}Bg`],
      border: palette[`${role}Border`],
      highlight: { background: palette[`${role}Bg`], border: palette.selectedBorder },
      hover: { background: palette[`${role}Bg`], border: palette.hoverBorder },
    };
    return [node.id, Object.freeze({
      ...base,
      color,
      shapeProperties: { ...base.shapeProperties, borderDashes: role === "unknown" ? [5, 3] : false },
      font: { ...base.font, color: palette.labelText, background: palette.labelBg },
    })];
  }));
  const edgeUpdates = viewModel.edges.filter((edge) => !edge.baseHidden).map((edge) => {
    const parentChild = edge.isParentChild || edge.linkCategories?.some((category) => [
      EDGE_CATEGORY_DEFAULT_CHILDREN, EDGE_CATEGORY_OTBR_CHILD,
      EDGE_CATEGORY_EVE_CHILD, EDGE_CATEGORY_EVE_NATIVE_CHILD,
    ].includes(category));
    const key = edge.themeColorKey ?? (parentChild ? "lqParentChild" : "lqNone");
    return {
      id: edge.id,
      color: {
        ...(typeof edge.color === "object" ? edge.color : {}),
        color: palette[key],
        highlight: palette.selectedBorder,
        hover: palette.hoverBorder,
      },
    };
  });
  const originalEdgeStyling = new Map([
    ...viewModel.originalEdgeStyling,
    ...edgeUpdates.map(({ id, ...style }) => [id, Object.freeze(style)]),
  ]);
  const next = Object.freeze({ ...viewModel, originalNodeStyling, originalEdgeStyling, themePalette: palette });
  const nodeUpdates = computeSearchHighlight(
    next,
    styleMode === "search" ? searchState : { query: "", matchingNodeIds: new Set() },
    palette,
  ).nodeUpdates;
  if (styleMode !== "search") {
    nodeUpdates.forEach((patch) => {
      const record = viewModel.rawByIdForDetails.get(patch.id);
      const identity = getDeviceIdentityKeys(record).find((key) => key.startsWith("extAddress:"));
      const status = healthStatuses.get(identity?.replace(/^extAddress:/, "extaddr:"));
      if (!status) return;
      patch.borderWidth = status === "poor" ? 5 : 4;
      patch.color = {
        ...patch.color,
        background: palette[`health${status[0].toUpperCase()}${status.slice(1)}Bg`],
        border: palette[`health${status[0].toUpperCase()}${status.slice(1)}`],
      };
    });
  }
  return Object.freeze({ viewModel: next, nodeUpdates, edgeUpdates });
}

const NEIGHBORHOOD_CONTEXT_OPACITY = 0.42;
const DEFAULT_EDGE_SELECTION_WIDTH = 1.5;

export function projectTopologySelection(viewModel, {
  selectedNodeIds = [],
  visibility,
  searchQuery = "",
  healthTarget = false,
} = {}) {
  const visibleNodes = visibility?.visibleNodeIds ?? new Set();
  const visibleEdges = visibility?.visibleEdgeIds ?? new Set();
  const selectedId = selectedNodeIds.length === 1 && visibleNodes.has(selectedNodeIds[0])
    ? selectedNodeIds[0] : null;
  const incidentIds = new Set(viewModel.edges.filter((edge) =>
    !edge.baseHidden && visibleEdges.has(edge.id)
    && visibleNodes.has(edge.from) && visibleNodes.has(edge.to)
    && edge.from !== edge.to && (edge.from === selectedId || edge.to === selectedId),
  ).map((edge) => edge.id));
  const active = selectedId !== null && incidentIds.size > 0 && !searchQuery && !healthTarget;
  return viewModel.edges.filter((edge) => !edge.baseHidden).map((edge) => {
    const base = viewModel.originalEdgeStyling.get(edge.id);
    const color = base.color && typeof base.color === "object" ? cloneValue(base.color) : { color: base.color };
    const opacity = color.opacity ?? 1;
    color.opacity = active && opacity === 1 && visibleEdges.has(edge.id) && !incidentIds.has(edge.id)
      ? opacity * NEIGHBORHOOD_CONTEXT_OPACITY : opacity;
    const incident = active && incidentIds.has(edge.id);
    if (incident) color.highlight = color.color;
    return {
      id: edge.id,
      color,
      selectionWidth: incident ? 0 : (edge.selectionWidth ?? DEFAULT_EDGE_SELECTION_WIDTH),
    };
  });
}

export function buildTopologyDetails(viewModel, selectedId) {
  const node = viewModel.nodeMap.get(selectedId);
  if (!node) return null;
  const rawRecord = viewModel.rawByIdForDetails.get(selectedId) ?? {};
  const deviceProjection = viewModel.projectionByNodeId.get(selectedId)
    ?? buildDeviceProjection({
      ...rawRecord,
      ...node,
      isReed: typeof rawRecord.isReed === "boolean" ? rawRecord.isReed : node.isReed,
      isRouter: typeof rawRecord.isRouter === "boolean" ? rawRecord.isRouter : node.isRouter,
      isBorderRouter: typeof rawRecord.isBorderRouter === "boolean"
        ? rawRecord.isBorderRouter : node.isBorderRouter,
      role: getColumnValue(rawRecord, "role") ?? getColumnValue(node, "role"),
      rloc16: getColumnValue(rawRecord, "rloc16") ?? getColumnValue(node, "rloc16"),
      mode: {
        device: getColumnValue(rawRecord, "mode.device")
          ?? getColumnValue(node, "mode.device")
          ?? node.mode_device,
      },
    });
  const graphLinkCount = viewModel.edges.filter(
    (edge) => edge.from === selectedId || edge.to === selectedId,
  ).length;
  const graphDetails = {
    graph: {
      unifiedId: selectedId,
      graphLinkCount,
      isReed: deviceProjection.isReed,
      isRouter: deviceProjection.isRouter,
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