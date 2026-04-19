import { VIS_OPTIONS, EDGE_CATEGORY_ROUTER_NEIGHBOR } from './tdash-constants.js';
import {
  toText, mergeForDisplay, flattenObjectEntries,
  shouldExcludeDetailPath, sortDetailsWithPriority,
  formatValue, areNodeIdsEquivalent
} from './tdash-utils.js';
import {
  computeTopologyCapabilities, updateFilterOptionVisibility,
  isNodeVisibleByFilter, isNodeVisibleByDiagnosticFilter,
  edgeMatchesLinkFilter, isRouterNeighborDiagnosticMode,
  routerNeighborRowMatchesDiagnosticFilter, normalizeLinkCategories
} from './tdash-filters.js';
import { runAdaptor } from './tdash-adaptors.js';

// ── Module-level state ────────────────────────────────────────────────────────

let _visNetwork = null;
let _topologyFilterHandlers = null;
let _autoZoomEnabled = true;
let _animationEnabled = true;

// ── Exported accessors / setters ──────────────────────────────────────────────

export function getVisNetwork() { return _visNetwork; }
export function getTopologyFilterHandlers() { return _topologyFilterHandlers; }
export function setAutoZoomEnabled(val) { _autoZoomEnabled = val; }
export function setAnimationEnabled(val) { _animationEnabled = val; }
export function isAutoZoomEnabled() { return _autoZoomEnabled; }
export function isAnimationEnabled() { return _animationEnabled; }

// ── Main renderer ─────────────────────────────────────────────────────────────

export function renderTopologyForDataset(dataset, physicsEnabled) {
  const container = document.getElementById('topology-view');
  const statusEl = document.getElementById('status');
  const detailsList = document.getElementById('details-list');
  const nodeFilterEl = document.getElementById('node-filter');
  const linkFilterEl = document.getElementById('link-filter');
  const diagnosticFilterEl = document.getElementById('diagnostic-filter');
  let lastStatusCounts = null;

  // Destroy previous network instance to free memory
  if (_visNetwork) {
    _visNetwork.destroy();
    _visNetwork = null;
    _topologyFilterHandlers = null;
  }
  container.innerHTML = '';
  detailsList.innerHTML = '<li>Click a node to view its properties.</li>';

  let adaptorResult;
  try {
    adaptorResult = runAdaptor(dataset);
  } catch (err) {
    statusEl.textContent = `Topology error: ${err.message}`;
    return;
  }

  const { nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, sourceNames } = adaptorResult;

  // ── Phase 5.1: compute and apply dynamic filter option visibility ────────
  const capabilities = computeTopologyCapabilities(nodeData, edgeData);
  dataset.capabilities = capabilities;
  updateFilterOptionVisibility(capabilities, 'topology');

  const nodesDataset = new vis.DataSet(nodeData);
  const edgesDataset = new vis.DataSet(edgeData);
  const effectiveOptions = physicsEnabled
    ? VIS_OPTIONS
    : Object.assign({}, VIS_OPTIONS, { physics: Object.assign({}, VIS_OPTIONS.physics, { enabled: false }) });
  _visNetwork = new vis.Network(container, { nodes: nodesDataset, edges: edgesDataset }, effectiveOptions);

  // ── applyFilters ───────────────────────────────────────────────────────

  function applyFilters(nodeFilterMode, linkFilterMode, diagnosticFilterMode) {
    const visibleNodeIds = new Set();
    const forcedVisibleEdgeIds = new Set();
    const matchedTargetNodeIds = new Set();
    let visibleEdgeCount = 0;

    nodesDataset.forEach((node) => {
      if (isNodeVisibleByFilter(node, nodeFilterMode) && isNodeVisibleByDiagnosticFilter(node, diagnosticFilterMode)) {
        visibleNodeIds.add(node.id);
      }
    });

    // Pull in child nodes when routers-with-children filter is active
    if (nodeFilterMode === 'routers-with-children') {
      edgesDataset.forEach((edge) => {
        if (edge.isParentChild === true && edgeMatchesLinkFilter(edge, linkFilterMode) && visibleNodeIds.has(edge.from)) {
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
        const neighborEntries = Array.isArray(neighborRow?.router_neighbor_table) ? neighborRow.router_neighbor_table : [];
        neighborEntries
          .filter((neighbor) => routerNeighborRowMatchesDiagnosticFilter(neighbor, diagnosticFilterMode))
          .forEach((neighbor) => {
            const targetId = toText(neighbor.rloc16) || toText(neighbor.extaddr);
            if (!targetId) return;
            matchedTargetNodeIds.add(targetId);
            visibleNodeIds.add(targetId);
            edgesDataset.forEach((edge) => {
              const cats = normalizeLinkCategories(edge.linkCategories);
              if (!cats.includes(EDGE_CATEGORY_ROUTER_NEIGHBOR)) return;
              if ((areNodeIdsEquivalent(edge.from, sourceNodeId) && areNodeIdsEquivalent(edge.to, targetId))
                || (areNodeIdsEquivalent(edge.to, sourceNodeId) && areNodeIdsEquivalent(edge.from, targetId))) {
                forcedVisibleEdgeIds.add(edge.id);
              }
            });
          });
      });
    }

    nodesDataset.forEach((node) => {
      nodesDataset.update({ id: node.id, hidden: !visibleNodeIds.has(node.id) });
    });

    edgesDataset.forEach((edge) => {
      const endpointsVisible = visibleNodeIds.has(edge.from) && visibleNodeIds.has(edge.to);
      const shouldShow = edge.baseHidden !== true
        && endpointsVisible
        && (edgeMatchesLinkFilter(edge, linkFilterMode) || forcedVisibleEdgeIds.has(edge.id));
      edgesDataset.update({ id: edge.id, hidden: !shouldShow });
      if (shouldShow) visibleEdgeCount += 1;
    });

    return {
      visibleNodeCount: visibleNodeIds.size,
      visibleEdgeCount,
      matchedTargetNodeCount: matchedTargetNodeIds.size,
      forcedVisibleLinkCount: forcedVisibleEdgeIds.size
    };
  }

  // ── Status line ────────────────────────────────────────────────────────

  function formatTopologyScale() {
    if (!_visNetwork || typeof _visNetwork.getScale !== 'function') return '';
    const scale = _visNetwork.getScale();
    if (!Number.isFinite(scale)) return '';
    return ` Scale: ${scale.toFixed(2)}x.`;
  }

  function updateStatus(counts) {
    lastStatusCounts = counts;
    const { visibleNodeCount, visibleEdgeCount, matchedTargetNodeCount = 0, forcedVisibleLinkCount = 0 } = counts;
    const nodeFilterLabel = nodeFilterEl.options[nodeFilterEl.selectedIndex].text;
    const linkFilterLabel = linkFilterEl.options[linkFilterEl.selectedIndex].text;
    const diagFilterLabel = diagnosticFilterEl.options[diagnosticFilterEl.selectedIndex].text;
    const neighborSuffix = isRouterNeighborDiagnosticMode(diagnosticFilterEl.value)
      ? ` Neighbor Match: targets ${matchedTargetNodeCount}, links ${forcedVisibleLinkCount}.` : '';
    statusEl.textContent = `Loaded ${sourceNames.join(', ')}. Total: ${nodeData.length} nodes, ${edgeData.length} links. `
      + `Showing: ${visibleNodeCount} nodes, ${visibleEdgeCount} links. `
      + `Node Filter: ${nodeFilterLabel}. Link Filter: ${linkFilterLabel}. Diagnostic Filter: ${diagFilterLabel}.${neighborSuffix}${formatTopologyScale()}`;
  }

  // ── Node detail click handler ──────────────────────────────────────────

  _visNetwork.on('click', (params) => {
    if (params.nodes.length === 0) {
      detailsList.innerHTML = '<li>Click a node to view its properties.</li>';
      return;
    }
    const selectedId = params.nodes[0];
    const node = nodeMap.get(selectedId);
    detailsList.innerHTML = '';
    if (!node) {
      detailsList.innerHTML = '<li>No details available for selected node.</li>';
      return;
    }

    const rawSource = rawByIdForDetails.get(selectedId) || {};
    const graphDetails = {
      graph: {
        unified_id: selectedId,
        graph_link_count: (function () {
          let deg = 0;
          edgesDataset.forEach((e) => { if (e.from === selectedId || e.to === selectedId) deg += 1; });
          return deg;
        })(),
        is_router: node.shape !== 'ellipse',
        has_children: routerIdsWithChildrenRef ? routerIdsWithChildrenRef.has(selectedId) : undefined
      }
    };

    // Router-neighbor table gets its own top-level li for readability
    if (Array.isArray(rawSource.router_neighbor_table)) {
      const li = document.createElement('li');
      li.textContent = `router_neighbor_table: ${formatValue(rawSource.router_neighbor_table)}`;
      detailsList.appendChild(li);
    }

    const mergedDetails = mergeForDisplay(rawSource, graphDetails);
    const details = sortDetailsWithPriority(
      flattenObjectEntries(mergedDetails).filter(([key]) => !shouldExcludeDetailPath(key))
    );

    if (details.length === 0) {
      detailsList.innerHTML = '<li>No details available for selected node.</li>';
      return;
    }
    details.forEach(([key, value]) => {
      const li = document.createElement('li');
      li.textContent = `${key}: ${formatValue(value)}`;
      detailsList.appendChild(li);
    });
  });

  // Capture routerIdsWithChildren for detail panel
  const routerIdsWithChildrenRef = new Set(
    nodeData.filter((n) => n.hasChildren).map((n) => n.id)
  );

  function refreshStatusScale() {
    if (lastStatusCounts) updateStatus(lastStatusCounts);
  }

  _visNetwork.on('zoom', refreshStatusScale);
  _visNetwork.on('animationFinished', refreshStatusScale);
  _visNetwork.once('stabilized', refreshStatusScale);

  // ── Store filter handlers so the toggle/filter wiring can call them ──
  _topologyFilterHandlers = {
    applyFilters,
    updateStatus,
    fitIfEnabled: () => {
      if (_autoZoomEnabled && _visNetwork) {
        requestAnimationFrame(() => {
          if (_visNetwork) {
            _visNetwork.fit({ animation: _animationEnabled });
          }
        });
      }
    }
  };

  // ── Initial filter pass ────────────────────────────────────────────────
  const initial = applyFilters(nodeFilterEl.value, linkFilterEl.value, diagnosticFilterEl.value);
  updateStatus(initial);
  _topologyFilterHandlers.fitIfEnabled();
}
