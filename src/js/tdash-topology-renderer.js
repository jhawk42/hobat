import {
  VIS_OPTIONS,
  getPhysicsProfile,
  getPhysicsProfileLabel,
  PHYSICS_PROFILE_MESH_BALANCED,
  PHYSICS_PROFILE_MESH_RING,
  PHYSICS_PROFILE_MESH_COMPACT,
  PHYSICS_PROFILE_MESH_TREE_HORIZONTAL,
  PHYSICS_PROFILE_MESH_TREE_VERTICAL,
  EDGE_CATEGORY_ROUTER_NEIGHBOR,
  EDGE_CATEGORY_OTBR_ROUTE,
  EDGE_CATEGORY_OTBR_ROUTE_FTD_CHILD,
  EDGE_CATEGORY_OTBR_ROUTE_ROUTER,
} from "./tdash-constants.js";
import {
  toText,
  flattenObjectEntries,
  shouldExcludeDetailPath,
  sortDetailsWithPriority,
  formatValue,
  populateNodeDetailsLists,
  publishDeviceSelection,
} from "./tdash-utils.js";
import {
  computeTopologyCapabilities,
  updateFilterOptionVisibility,
  normalizeLinkCategories,
} from "./tdash-filters.js";
import { runAdaptor } from "./tdash-adaptors.js";
import { getDeviceIdentityKeys } from "./tdash-device-fields.js";
import {
  applyTopologyTransition,
  buildTopologyDetails,
  buildTopologyStatus,
  computeSearchHighlight,
  computeTopologyVisibility,
  createTopologyEventBindings,
  createTopologyFilterState,
  createTopologyRenderOwner,
  createTopologySearchState,
  createTopologyViewModel,
} from "./tdash-topology-view-model.js";
import {
  applyMeshLabHybridSeedLayout as applyExtractedMeshLabHybridSeedLayout,
  applyMeshTreeHorizontalSeedLayout as applyExtractedMeshTreeHorizontalSeedLayout,
  applyMeshTreeVerticalSeedLayout as applyExtractedMeshTreeVerticalSeedLayout,
  applyRingStarSeedLayout as applyExtractedRingStarSeedLayout,
  buildMeshTreeZoningContext as buildExtractedMeshTreeZoningContext,
} from "./tdash-layouts.js";
import { publishViewStatus } from "./tdash-view-status.js";

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
let _topologyRenderOwner = null;
let _healthStatusByDeviceId = new Map();

const HEALTH_BORDER_COLORS = Object.freeze({
  poor: "#b42318",
  moderate: "#a15c00",
  strong: "#067647",
  unknown: "#667085",
});

const MESH_COMPACT_LAYOUT = Object.freeze({
  ftdMinEdgeLength: 280,
  mtdMinEdgeLength: 450,
});

const MESH_RING_LAYOUT = Object.freeze({
  routeEdgeWidth: 0.45,
  routeEdgeOpacity: 0.16,
});

const MESH_HUB_SPOKE_LAYOUT = Object.freeze({
  ftdMinEdgeLength: 300,
  mtdMinEdgeLength: 460,
  routerMinEdgeLength: 680,
  routeEdgeWidth: 0.45,
  routeEdgeOpacity: 0.16,
});

export function isSecondaryRouterRouteEdge(linkCategories) {
  const categories = normalizeLinkCategories(linkCategories);
  return categories.includes(EDGE_CATEGORY_OTBR_ROUTE)
    && categories.includes(EDGE_CATEGORY_OTBR_ROUTE_ROUTER)
    && !categories.includes(EDGE_CATEGORY_ROUTER_NEIGHBOR)
    && !categories.includes(EDGE_CATEGORY_OTBR_ROUTE_FTD_CHILD);
}

export function assignParallelEdgeCurves(edgeData, nodeData) {
  const nodeById = new Map(nodeData.map((node) => [node.id, node]));
  const groups = new Map();
  edgeData.forEach((edge) => {
    if (edge.baseHidden === true) return;
    const fromNode = nodeById.get(edge.from);
    const toNode = nodeById.get(edge.to);
    if (edge.isParentChild !== true && (fromNode?.isRouter !== true || toNode?.isRouter !== true)) return;
    const pairKey = [String(edge.from), String(edge.to)].sort().join("|");
    const group = groups.get(pairKey) ?? [];
    group.push(edge);
    groups.set(pairKey, group);
  });
  groups.forEach((group) => {
    group.sort((left, right) => String(left.id).localeCompare(String(right.id)));
    const baseRoundness = group.length === 1 && group[0].isParentChild !== true ? 0.26 : 0.2;
    group.forEach((edge, index) => {
      edge.smooth = {
        enabled: true,
        type: index % 2 === 0 ? "curvedCW" : "curvedCCW",
        roundness: baseRoundness + Math.floor(index / 2) * 0.08,
      };
    });
  });
}

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
export function setTopologyHealthFindings(findings = []) {
  _healthStatusByDeviceId = new Map();
  const severity = { unknown: 0, strong: 1, moderate: 2, poor: 3 };
  findings.forEach((finding) => {
    (finding.deviceIds || []).forEach((deviceId) => {
      const current = _healthStatusByDeviceId.get(deviceId);
      if (!current || severity[finding.status] > severity[current]) {
        _healthStatusByDeviceId.set(deviceId, finding.status);
      }
    });
  });
  _topologyFilterHandlers?.applyHealthOverlay?.();
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
    return buildExtractedMeshTreeZoningContext(nodeData || [], edgeData || []);
  };
  window.tdashDebug.getCompactChildSpacing = function() {
    return getCompactChildSpacingReport();
  };
}

export function getCompactChildSpacingReport() {
  if (!_visNetwork || !_topologyNodeData) return [];

  const nodeById = new Map(_topologyNodeData.map((node) => [node.id, node]));
  const positions = _visNetwork.getPositions();
  const candidatesByChildId = new Map();

  _topologyNodeData.forEach((node) => {
    if (node?.isRouter === true) return;
    candidatesByChildId.set(node.id, new Map());
  });

  _visNetwork.body.data.edges.get().forEach((edge) => {
    const fromNode = nodeById.get(edge.from);
    const toNode = nodeById.get(edge.to);
    const fromIsRouter = fromNode?.isRouter === true;
    const toIsRouter = toNode?.isRouter === true;
    if (fromIsRouter === toIsRouter) return;

    const parentId = fromIsRouter ? fromNode.id : toNode.id;
    const childId = fromIsRouter ? toNode.id : fromNode.id;
    const weight = edge.isParentChild === true ? 2 : 1;
    const candidates = candidatesByChildId.get(childId);
    if (!candidates) return;
    candidates.set(parentId, (candidates.get(parentId) || 0) + weight);
  });

  return Array.from(candidatesByChildId.entries())
    .flatMap(([childId, candidates]) => {
      const childPosition = positions[childId];
      if (!childPosition || candidates.size === 0) return [];
      const [parentId] = Array.from(candidates.entries())
        .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))[0];
      const parentPosition = positions[parentId];
      if (!parentPosition) return [];

      let nearestNonParentDistance = Infinity;
      Object.entries(positions).forEach(([nodeId, position]) => {
        if (nodeId === String(childId) || nodeId === String(parentId)) return;
        nearestNonParentDistance = Math.min(
          nearestNonParentDistance,
          Math.hypot(position.x - childPosition.x, position.y - childPosition.y),
        );
      });

      const childNode = nodeById.get(childId);
      return [{
        parentId,
        childId,
        childType: _meshTreeUpperText(childNode?.mode_device) === "FTD" ? "ftd" : "mtd",
        parentDistance: Math.round(Math.hypot(
          childPosition.x - parentPosition.x,
          childPosition.y - parentPosition.y,
        )),
        nearestNonParentDistance: Number.isFinite(nearestNonParentDistance)
          ? Math.round(nearestNonParentDistance)
          : null,
        x: Math.round(childPosition.x),
        y: Math.round(childPosition.y),
      }];
    })
    .sort((a, b) => a.parentDistance - b.parentDistance || String(a.childId).localeCompare(String(b.childId)));
}

function _meshTreeUpperText(value) {
  return typeof value === "string" ? value.trim().toUpperCase() : "";
}

// ── Main renderer ─────────────────────────────────────────────────────────────

export function renderTopologyForDataset(
  dataset,
  physicsEnabled,
  physicsProfileName = "mesh-baseline",
  statusDatasetToken = dataset,
) {
  const container = document.getElementById("topology-view");
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

  if (_topologyRenderOwner) {
    _topologyRenderOwner.dispose();
    _topologyRenderOwner = null;
  } else if (_visNetwork) {
    _visNetwork.destroy();
  }
  _visNetwork = null;
  _topologyFilterHandlers = null;
  _topologyNodeData = null;
  _topologyRawRows = null;
  _topologyDatasetCounts = null;
  _originalNodeStyling = null;
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
    publishViewStatus("topology", `Topology error: ${err.message}`, statusDatasetToken);
    return;
  }

  const {
    nodeData,
    edgeData,
  } = adaptorResult;

  if (physicsProfileName === PHYSICS_PROFILE_MESH_RING) {
    applyExtractedRingStarSeedLayout(nodeData, edgeData);
  } else if (physicsProfileName === PHYSICS_PROFILE_MESH_COMPACT) {
    applyExtractedMeshLabHybridSeedLayout(nodeData, edgeData);
  } else if (physicsProfileName === PHYSICS_PROFILE_MESH_TREE_HORIZONTAL) {
    applyExtractedMeshTreeHorizontalSeedLayout(nodeData, edgeData);
  } else if (physicsProfileName === PHYSICS_PROFILE_MESH_TREE_VERTICAL) {
    applyExtractedMeshTreeVerticalSeedLayout(nodeData, edgeData);
  }

  assignParallelEdgeCurves(edgeData, nodeData);

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
      ? buildExtractedMeshTreeZoningContext(nodeData, edgeData).zoneByNodeId
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
        let childBandLength;
        if (isMeshTreeProfile) {
          childBandLength = isFtdChildNode(childNode) ? 170 : 250;
        } else if (physicsProfileName === PHYSICS_PROFILE_MESH_COMPACT) {
          childBandLength = isFtdChildNode(childNode)
            ? MESH_COMPACT_LAYOUT.ftdMinEdgeLength
            : MESH_COMPACT_LAYOUT.mtdMinEdgeLength;
        } else {
          childBandLength = isFtdChildNode(childNode) ? 200 : 430;
        }
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
      } else if (physicsProfileName === PHYSICS_PROFILE_MESH_RING && routerToChildLike) {
        if (isSecondaryRouterRouteEdge(edge.linkCategories)) {
          const color = typeof edge.color === "string" ? edge.color : undefined;
          edge.color = { color, opacity: MESH_RING_LAYOUT.routeEdgeOpacity };
          edge.width = Math.min(Number(edge.width) || 1.5, MESH_RING_LAYOUT.routeEdgeWidth);
          edge.dashes = [2, 8];
        }
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

  if (physicsProfileName === PHYSICS_PROFILE_MESH_BALANCED) {
    const nodeById = new Map(nodeData.map((n) => [n.id, n]));
    const isFtdChildNode = (node) => toText(node?.mode_device).toUpperCase() === "FTD";
    edgeData.forEach((edge) => {
      if (edge.baseHidden === true) return;
      const fromNode = nodeById.get(edge.from);
      const toNode = nodeById.get(edge.to);
      const fromIsRouter = fromNode?.isRouter === true;
      const toIsRouter = toNode?.isRouter === true;
      const routerToChildLike = (fromIsRouter && !toIsRouter) || (!fromIsRouter && toIsRouter);
      const applyMinEdgeLength = (minLength) => {
        edge.length = Number.isFinite(edge.length)
          ? Math.max(edge.length, minLength)
          : minLength;
      };

      if (edge.isParentChild === true && routerToChildLike) {
        const childNode = fromIsRouter ? toNode : fromNode;
        applyMinEdgeLength(
          isFtdChildNode(childNode)
            ? MESH_HUB_SPOKE_LAYOUT.ftdMinEdgeLength
            : MESH_HUB_SPOKE_LAYOUT.mtdMinEdgeLength,
        );
        edge.physics = true;
        return;
      }

      if (routerToChildLike) {
        if (isSecondaryRouterRouteEdge(edge.linkCategories)) {
          const color = typeof edge.color === "string" ? edge.color : undefined;
          edge.color = { color, opacity: MESH_HUB_SPOKE_LAYOUT.routeEdgeOpacity };
          edge.width = Math.min(Number(edge.width) || 1.5, MESH_HUB_SPOKE_LAYOUT.routeEdgeWidth);
          edge.dashes = [2, 8];
        }
        edge.physics = false;
        return;
      }

      if (!fromIsRouter || !toIsRouter) return;

      // Hub Spoke: keep border-router links longer so BRs do not collapse into
      // the central router mass during stabilization.
      const touchesBorderRouter =
        fromNode?.isBorderRouter === true || toNode?.isBorderRouter === true;
      if (!touchesBorderRouter) {
        applyMinEdgeLength(MESH_HUB_SPOKE_LAYOUT.routerMinEdgeLength);
        return;
      }

      const bothBorderRouters =
        fromNode?.isBorderRouter === true && toNode?.isBorderRouter === true;

      const minBorderRouterLength = bothBorderRouters ? 1345 : 1097;

      applyMinEdgeLength(minBorderRouterLength);
    });
  }

  const capabilities = computeTopologyCapabilities(nodeData, edgeData);
  dataset.capabilities = capabilities;
  updateFilterOptionVisibility(capabilities, "topology");

  const viewModel = createTopologyViewModel(adaptorResult);
  const nodesDataset = new vis.DataSet(viewModel.nodes);
  const edgesDataset = new vis.DataSet(viewModel.edges);
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
  const network = new vis.Network(
    container,
    { nodes: nodesDataset, edges: edgesDataset },
    effectiveOptions,
  );
  const bindings = createTopologyEventBindings();
  let currentSearchState = createTopologySearchState("", false, viewModel);

  // ── applyFilters ───────────────────────────────────────────────────────

  function applyFilters(nodeFilterMode, linkFilterMode, diagnosticFilterMode) {
    currentSearchState = createTopologySearchState("", false, viewModel);
    const visibility = computeTopologyVisibility(
      viewModel,
      createTopologyFilterState(nodeFilterMode, linkFilterMode, diagnosticFilterMode),
    );
    applyTopologyTransition(nodesDataset, edgesDataset, { viewModel, visibility });
    return visibility;
  }

  // Shared canonical restore path for node visual styles.
  function restoreOriginalNodeStyling() {
    const restore = computeSearchHighlight(
      viewModel,
      createTopologySearchState("", false, viewModel),
    );
    nodesDataset.update(restore.nodeUpdates);
    const healthUpdates = [];
    viewModel.nodeMap.forEach((_node, nodeId) => {
      const record = viewModel.rawByIdForDetails.get(nodeId);
      const identityKey = getDeviceIdentityKeys(record).find((key) => key.startsWith("extAddress:"));
      const deviceId = identityKey?.replace(/^extAddress:/, "extaddr:");
      const status = _healthStatusByDeviceId.get(deviceId);
      if (!status) return;
      healthUpdates.push({
        id: nodeId,
        borderWidth: status === "poor" ? 5 : 4,
        color: { border: HEALTH_BORDER_COLORS[status] },
      });
    });
    if (healthUpdates.length > 0) nodesDataset.update(healthUpdates);
  }

  // ── Search highlight ─────────────────────────────────────────────────────

  function applySearchHighlight(searchQuery, advancedMode) {
    const baseCounts = applyFilters(
      nodeFilterEl.value,
      linkFilterEl.value,
      diagnosticFilterEl.value,
    );
    currentSearchState = createTopologySearchState(searchQuery, advancedMode, viewModel);
    const highlight = computeSearchHighlight(viewModel, currentSearchState);
    nodesDataset.update(highlight.nodeUpdates);
    updateStatus(baseCounts);

    if (highlight.focusTarget) {
      network.selectNodes([highlight.focusTarget]);
      showNodeDetails(highlight.focusTarget);
      const viewEl = document.getElementById("view-topology");
      const canvasHeight = viewEl ? viewEl.clientHeight : 400;
      const yOffset = -Math.min(Math.round(canvasHeight * 0.22), 100);
      network.focus(highlight.focusTarget, {
        scale: 1.10,
        animation: { duration: 600, easingFunction: "easeInOutQuad" },
        offset: { x: 0, y: yOffset },
      });
    }
  }

  // ── Status line ────────────────────────────────────────────────────────

  function updateStatus(counts) {
    lastStatusCounts = counts;
    const status = buildTopologyStatus(viewModel, counts, currentSearchState, network.getScale(), {
      diagnosticMode: diagnosticFilterEl.value,
      physicsProfileLabel,
      stabilizationMs: lastStabilizationMs,
    });
    const fetchStatusEl = document.getElementById("fetch-status-line-content");
    const fetchStatusPinnedUntil = window.tdashDebug?.fetchStatusPinnedUntil ?? 0;
    const isFetchStatusPinned = Date.now() < fetchStatusPinnedUntil;
    if (fetchStatusEl && !isFetchStatusPinned) {
      fetchStatusEl.textContent = `Loaded: ${viewModel.sourceNames.join(", ")}`;
    }
    publishViewStatus("topology", status.text, statusDatasetToken);
  }

  // ── Node detail click handler ──────────────────────────────────────────

  bindings.on(network, "click", (params) => {
    if (params.nodes.length === 0) {
      publishDeviceSelection(null);
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

  function showNodeDetails(selectedId) {
    const _QL =
      "#identity-list, #highlights-list, #network-list, #connections-list, " +
      "#mdns-list, #routes-links-list, #neighbors-list, #children-list, " +
      "#counters-list, #details-list";
    const _hide = () => document.querySelectorAll(_QL).forEach((l) => l.classList.add("hidden"));
    const mergedDetails = buildTopologyDetails(viewModel, selectedId);
    if (!mergedDetails) {
      publishDeviceSelection(null);
      document.getElementById("summary-list").innerHTML =
        "<li>No details available for selected node.</li>";
      _hide();
      return;
    }
    publishDeviceSelection(mergedDetails);
    const details = sortDetailsWithPriority(
      flattenObjectEntries(mergedDetails).filter(
        ([key]) => !shouldExcludeDetailPath(key),
      ),
    );
    if (details.length === 0) {
      publishDeviceSelection(null);
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

  bindings.on(network, "zoom", refreshStatusScale);
  bindings.on(network, "animationFinished", refreshStatusScale);
  bindings.once(network, "stabilized", refreshStatusScale);

  let stabilizationHandled = false;
  bindings.on(network, "stabilizationIterationsDone", function () {
    if (_topologyRenderOwner !== owner || stabilizationHandled) return;
    stabilizationHandled = true;
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

    network.setOptions({ physics: false });
    if (physicsProfileName === PHYSICS_PROFILE_MESH_RING && _autoZoomEnabled) {
      requestAnimationFrame(() => {
        if (_topologyRenderOwner === owner) network.fit({ animation: _animationEnabled });
      });
    }
    // Notify UI layer that physics has been disabled
    if (_onPhysicsDisabledCallback) {
      _onPhysicsDisabledCallback();
    }

    if (lastStatusCounts) updateStatus(lastStatusCounts);
  });

  const handlers = {
    applyFilters: (...args) => owner.isActive() ? applyFilters(...args) : null,
    applySearchHighlight: (...args) => owner.isActive() ? applySearchHighlight(...args) : null,
    restoreOriginalNodeStyling: () => {
      if (owner.isActive()) restoreOriginalNodeStyling();
    },
    applyHealthOverlay: () => {
      if (owner.isActive()) restoreOriginalNodeStyling();
    },
    updateStatus: (...args) => {
      if (owner.isActive()) updateStatus(...args);
    },
    fitIfEnabled: () => {
      if (_autoZoomEnabled && owner.isActive()) {
        requestAnimationFrame(() => {
          if (_topologyRenderOwner === owner) network.fit({ animation: _animationEnabled });
        });
      }
    },
  };
  const owner = createTopologyRenderOwner(network, bindings);

  try {
    const initial = applyFilters(
      nodeFilterEl.value,
      linkFilterEl.value,
      diagnosticFilterEl.value,
    );
    updateStatus(initial);
    restoreOriginalNodeStyling();
  } catch (error) {
    owner.dispose();
    publishViewStatus("topology", `Topology error: ${error.message}`, statusDatasetToken);
    return;
  }

  _topologyRenderOwner = owner;
  _visNetwork = network;
  _topologyFilterHandlers = handlers;
  _topologyNodeData = viewModel.nodes;
  _topologyRawRows = viewModel.rawByIdForDetails;
  _topologyDatasetCounts = viewModel.datasetCounts;
  _originalNodeStyling = viewModel.originalNodeStyling;
  handlers.fitIfEnabled();
}
