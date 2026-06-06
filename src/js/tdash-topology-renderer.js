import {
  VIS_OPTIONS,
  EDGE_CATEGORY_ROUTER_NEIGHBOR,
} from "./tdash-constants.js";
import {
  toText,
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
}

// ── Main renderer ─────────────────────────────────────────────────────────────

export function renderTopologyForDataset(dataset, physicsEnabled) {
  const container = document.getElementById("topology-view");
  const statusEl = document.getElementById("view-status-line-content");
  const nodeFilterEl = document.getElementById("node-filter");
  const linkFilterEl = document.getElementById("link-filter");
  const diagnosticFilterEl = document.getElementById("diagnostic-filter");
  let lastStatusCounts = null;

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
    sourceNames,
  } = adaptorResult;

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
  
  // Store original styling for each node so we can restore it when search is cleared
  _originalNodeStyling = new Map();
  nodeData.forEach((node) => {
    _originalNodeStyling.set(node.id, {
      color: node.color,
      borderWidth: node.borderWidth,
      font: node.font,
    });
  });
  
  const effectiveOptions = physicsEnabled
    ? VIS_OPTIONS
    : Object.assign({}, VIS_OPTIONS, {
      physics: Object.assign({}, VIS_OPTIONS.physics, { enabled: false }),
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
        const neighborEntries = Array.isArray(
          neighborRow?.router_neighbor_table,
        )
          ? neighborRow.router_neighbor_table
          : [];
        neighborEntries
          .filter((neighbor) =>
            routerNeighborRowMatchesDiagnosticFilter(
              neighbor,
              diagnosticFilterMode,
            ),
          )
          .forEach((neighbor) => {
            const targetId =
              toText(neighbor.rloc16) || toText(neighbor.extaddr);
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

  // ── Search highlight ─────────────────────────────────────────────────────

  function applySearchHighlight(searchQuery, advancedMode) {
    if (!_topologyNodeData || !_topologyRawRows) return;

    if (!searchQuery) {
      // Restore all nodes to their original appearance using stored original styling
      nodesDataset.update(
        Array.from(_originalNodeStyling.entries()).map(([nodeId, originalStyle]) => ({
          id: nodeId,
          color: originalStyle.color,
          borderWidth: originalStyle.borderWidth,
          font: originalStyle.font,
        })),
      );
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
            font: originalStyle.font,
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
      nodeFilterEl.options[nodeFilterEl.selectedIndex].text;
    const linkFilterLabel =
      linkFilterEl.options[linkFilterEl.selectedIndex].text;
    const diagFilterLabel =
      diagnosticFilterEl.options[diagnosticFilterEl.selectedIndex].text;
    const neighborSuffix = isRouterNeighborDiagnosticMode(
      diagnosticFilterEl.value,
    )
      ? ` Neighbor Match: targets ${matchedTargetNodeCount}, links ${forcedVisibleLinkCount}.`
      : "";
    const searchSuffix = searchQuery
      ? ` Search: "${searchQuery}" — ${matchCount} of ${totalCount} rows match.`
      : "";
    const fetchStatusEl = document.getElementById("fetch-status-line-content");
    if (fetchStatusEl) fetchStatusEl.textContent = `Loaded: ${sourceNames.join(", ")}`;
    statusEl.textContent =
      `Showing: ${visibleNodeCount} nodes, ${visibleEdgeCount} links.${neighborSuffix}${searchSuffix}`;
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
        unified_id: selectedId,
        graph_link_count: (function () {
          let deg = 0;
          edgesDataset.forEach((e) => {
            if (e.from === selectedId || e.to === selectedId) deg += 1;
          });
          return deg;
        })(),
        is_router: node.shape !== "ellipse",
        has_children: routerIdsWithChildrenRef
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

  // ── Store filter handlers so the toggle/filter wiring can call them ──
  _topologyFilterHandlers = {
    applyFilters,
    applySearchHighlight,
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
  nodesDataset.update(
    Array.from(_originalNodeStyling.entries()).map(([nodeId, originalStyle]) => ({
      id: nodeId,
      color: originalStyle.color,
      borderWidth: originalStyle.borderWidth,
      font: originalStyle.font,
    })),
  );
  
  _topologyFilterHandlers.fitIfEnabled();
}
