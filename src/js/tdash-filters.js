import {
  LINK_FILTER_DEFAULT, LINK_FILTER_DEFAULT_PLUS_NEIGHBORS,
  LINK_FILTER_OTBR_REST_API, LINK_FILTER_EVE_ENHANCED,
  LINK_FILTER_EVE_NATIVE, LINK_FILTER_ALL,
  LINK_FILTER_LQ_HIGH, LINK_FILTER_LQ_MEDIUM, LINK_FILTER_LQ_LOW,
  LINK_FILTER_PARENT_CHILD, LINK_FILTER_OTBR_NEIGHBOR, LINK_FILTER_LQ_NONE,
  EDGE_CATEGORY_DEFAULT_CHILDREN, EDGE_CATEGORY_DEFAULT_1,
  EDGE_CATEGORY_DEFAULT_2, EDGE_CATEGORY_DEFAULT_3,
  EDGE_CATEGORY_ROUTER_NEIGHBOR, EDGE_CATEGORY_OTBR_ROUTE,
  EDGE_CATEGORY_OTBR_CHILD, EDGE_CATEGORY_EVE_ROUTE,
  EDGE_CATEGORY_EVE_CHILD, EDGE_CATEGORY_EVE_NATIVE_ROUTE,
  EDGE_CATEGORY_EVE_NATIVE_CHILD,
  NODE_FILTER_OPTIONS, LINK_FILTER_OPTIONS, DIAGNOSTIC_FILTER_OPTIONS
} from './tdash-constants.js';
import {
  toText, toFiniteNumber, isPlainObject,
  getColumnValue
} from './tdash-utils.js';

// ── Link-category normalisation ───────────────────────────────────────────────

export function normalizeLinkCategories(value) {
  if (Array.isArray(value)) return value.filter((item) => toText(item));
  const text = toText(value);
  return text ? [text] : [];
}

// ── Edge visibility predicate ─────────────────────────────────────────────────

export function edgeMatchesLinkFilter(edge, mode) {
  const cats = normalizeLinkCategories(edge.linkCategories);
  if (cats.length === 0) return mode === LINK_FILTER_ALL;
  const hasAny = (...wanted) => wanted.some((c) => cats.includes(c));
  if (mode === LINK_FILTER_DEFAULT) {
    return hasAny(EDGE_CATEGORY_DEFAULT_CHILDREN, EDGE_CATEGORY_DEFAULT_1,
      EDGE_CATEGORY_DEFAULT_2, EDGE_CATEGORY_DEFAULT_3, EDGE_CATEGORY_OTBR_CHILD);
  }
  if (mode === LINK_FILTER_DEFAULT_PLUS_NEIGHBORS) {
    return hasAny(EDGE_CATEGORY_DEFAULT_CHILDREN, EDGE_CATEGORY_DEFAULT_1,
      EDGE_CATEGORY_DEFAULT_2, EDGE_CATEGORY_DEFAULT_3, EDGE_CATEGORY_OTBR_CHILD,
      EDGE_CATEGORY_ROUTER_NEIGHBOR);
  }
  if (mode === LINK_FILTER_OTBR_REST_API) return hasAny(EDGE_CATEGORY_OTBR_ROUTE, EDGE_CATEGORY_OTBR_CHILD);
  if (mode === LINK_FILTER_EVE_ENHANCED) return hasAny(EDGE_CATEGORY_EVE_ROUTE, EDGE_CATEGORY_EVE_CHILD);
  if (mode === LINK_FILTER_EVE_NATIVE) return hasAny(EDGE_CATEGORY_EVE_NATIVE_ROUTE, EDGE_CATEGORY_EVE_NATIVE_CHILD);
  if (mode === LINK_FILTER_ALL) return true;
  if (mode === LINK_FILTER_LQ_HIGH)       return (edge.lqLevel ?? 0) === 3;
  if (mode === LINK_FILTER_LQ_MEDIUM)     return (edge.lqLevel ?? 0) === 2;
  if (mode === LINK_FILTER_LQ_LOW)        return (edge.lqLevel ?? 0) === 1;
  if (mode === LINK_FILTER_PARENT_CHILD)  return edge.isParentChild === true;
  if (mode === LINK_FILTER_OTBR_NEIGHBOR) return hasAny(EDGE_CATEGORY_OTBR_ROUTE, EDGE_CATEGORY_OTBR_CHILD, EDGE_CATEGORY_ROUTER_NEIGHBOR);
  if (mode === LINK_FILTER_LQ_NONE)       return !edge.lqLevel || edge.lqLevel === 0;
  return false;
}

// ── Dataset capabilities ──────────────────────────────────────────────────────
//
// Both functions return the same DatasetCapabilities shape:
//   {
//     hasFtdNodes, hasMtdNodes, hasMainRouters, hasBorderRouters,
//     hasRoutersWithChildren, hasRoutersWithoutChildren,
//     edgeCategories : Set<string>,   (empty in table view)
//     hasFieldMacTotalErrorsPct, hasFieldMacDiscardPct,
//     hasFieldPartitionChanges, hasFieldParentChanges,
//     hasNeighborFrameErrRate, hasNeighborMsgErrRate, hasNeighborRss
//   }

// Called after runAdaptor() in renderTopologyForDataset.
// Scans vis-node objects and edge linkCategories.
export function computeTopologyCapabilities(nodeData, edgeData) {
  let hasFtdNodes = false;
  let hasMtdNodes = false;
  let hasMainRouters = false;
  let hasBorderRouters = false;
  let hasRoutersWithChildren = false;
  let hasRoutersWithoutChildren = false;
  let hasFieldMacTotalErrorsPct = false;
  let hasFieldMacDiscardPct = false;
  let hasFieldPartitionChanges = false;
  let hasFieldParentChanges = false;
  let hasNeighborFrameErrRate = false;
  let hasNeighborMsgErrRate = false;
  let hasNeighborRss = false;

  for (const node of nodeData) {
    const md = toText(node.mode_device).toUpperCase();
    if (md === 'FTD') hasFtdNodes = true;
    if (md === 'MTD') hasMtdNodes = true;
    if (node.isMainRouter === true) hasMainRouters = true;
    if (node.isBorderRouter === true) hasBorderRouters = true;
    if (node.isRouter === true && node.hasChildren === true) hasRoutersWithChildren = true;
    if (node.isRouter === true && node.hasChildren !== true) hasRoutersWithoutChildren = true;
    if (Number.isFinite(node.ifinerrors_pct) || Number.isFinite(node.ifouterrors_pct)) hasFieldMacTotalErrorsPct = true;
    if (Number.isFinite(node.iftotalpktserrorsdiscards_pct)) hasFieldMacDiscardPct = true;
    if (Number.isFinite(node.partitionidchanges)) hasFieldPartitionChanges = true;
    if (Number.isFinite(node.parentchanges)) hasFieldParentChanges = true;
    if (Number.isFinite(node.router_neighbor_max_err_rate_frame_pct)) hasNeighborFrameErrRate = true;
    if (Number.isFinite(node.router_neighbor_max_err_rate_msg_pct)) hasNeighborMsgErrRate = true;
    if (Number.isFinite(node.router_neighbor_min_rss_ave)
        || Number.isFinite(node.router_neighbor_max_rss_ave)) hasNeighborRss = true;
  }

  const edgeCategories = new Set();
  for (const edge of edgeData) {
    for (const cat of normalizeLinkCategories(edge.linkCategories)) {
      edgeCategories.add(cat);
    }
  }

  return {
    hasFtdNodes, hasMtdNodes,
    hasMainRouters, hasBorderRouters,
    hasRoutersWithChildren, hasRoutersWithoutChildren,
    edgeCategories,
    hasFieldMacTotalErrorsPct, hasFieldMacDiscardPct,
    hasFieldPartitionChanges, hasFieldParentChanges,
    hasNeighborFrameErrRate, hasNeighborMsgErrRate, hasNeighborRss
  };
}

// Called at the top of renderTableForDataset.
// Scans normalised row objects (including router_neighbor_table sub-arrays).
// edgeCategories is always an empty Set (table view has no topology edges).
export function computeTableCapabilities(rows) {
  let hasFtdNodes = false;
  let hasMtdNodes = false;
  let hasMainRouters = false;
  let hasBorderRouters = false;
  let hasRoutersWithChildren = false;
  let hasRoutersWithoutChildren = false;
  let hasFieldMacTotalErrorsPct = false;
  let hasFieldMacDiscardPct = false;
  let hasFieldPartitionChanges = false;
  let hasFieldParentChanges = false;
  let hasNeighborFrameErrRate = false;
  let hasNeighborMsgErrRate = false;
  let hasNeighborRss = false;

  for (const row of rows) {
    const md = toText(getColumnValue(row, 'mode.device')).toUpperCase();
    if (md === 'FTD') hasFtdNodes = true;
    if (md === 'MTD') hasMtdNodes = true;

    const rloc16Text = toText(getColumnValue(row, 'rloc16')).toLowerCase();
    const isMainRouter = rloc16Text.endsWith('00') && rloc16Text.length > 0;
    if (isMainRouter) hasMainRouters = true;

    const brValue = getColumnValue(row, 'br');
    if (isMainRouter && (brValue === true || toText(brValue).toLowerCase() === 'true')) {
      hasBorderRouters = true;
    }

    const totalChildren = toFiniteNumber(getColumnValue(row, 'total_children'));
    const childrenValue = getColumnValue(row, 'children');
    const childrenCount = Array.isArray(childrenValue) ? childrenValue.length : undefined;
    const hasChildren = (Number.isFinite(totalChildren) && totalChildren > 0)
      || (Number.isFinite(childrenCount) && childrenCount > 0);
    const isRouter = isMainRouter
      || Number.isFinite(totalChildren)
      || Array.isArray(childrenValue);
    if (isRouter && hasChildren) hasRoutersWithChildren = true;
    if (isRouter && !hasChildren) hasRoutersWithoutChildren = true;

    const macInerrors = getColumnValue(row, 'mac_counters.ifinerrors_pct');
    const macOuterrors = getColumnValue(row, 'mac_counters.ifouterrors_pct');
    if (Number.isFinite(toFiniteNumber(macInerrors)) || Number.isFinite(toFiniteNumber(macOuterrors))) hasFieldMacTotalErrorsPct = true;

    const macDiscard = getColumnValue(row, 'mac_counters.iftotalpktserrorsdiscards_pct');
    if (Number.isFinite(toFiniteNumber(macDiscard))) hasFieldMacDiscardPct = true;

    const partChanges = getColumnValue(row, 'mle_counters.partitionidchanges');
    if (Number.isFinite(toFiniteNumber(partChanges))) hasFieldPartitionChanges = true;

    const parentChanges = getColumnValue(row, 'mle_counters.parentchanges');
    if (Number.isFinite(toFiniteNumber(parentChanges))) hasFieldParentChanges = true;

    const neighborRows = Array.isArray(getColumnValue(row, 'router_neighbor_table'))
      ? getColumnValue(row, 'router_neighbor_table') : [];
    for (const neighbor of neighborRows) {
      if (Number.isFinite(toFiniteNumber(neighbor?.err_rate_frame_pct))) hasNeighborFrameErrRate = true;
      if (Number.isFinite(toFiniteNumber(neighbor?.err_rate_msg_pct))) hasNeighborMsgErrRate = true;
      if (Number.isFinite(toFiniteNumber(neighbor?.rss_ave))) hasNeighborRss = true;
    }
  }

  return {
    hasFtdNodes, hasMtdNodes,
    hasMainRouters, hasBorderRouters,
    hasRoutersWithChildren, hasRoutersWithoutChildren,
    edgeCategories: new Set(),
    hasFieldMacTotalErrorsPct, hasFieldMacDiscardPct,
    hasFieldPartitionChanges, hasFieldParentChanges,
    hasNeighborFrameErrRate, hasNeighborMsgErrRate, hasNeighborRss
  };
}

// ── Filter option visibility (DOM) ────────────────────────────────────────────
//
// Hides/disables filter <option> elements whose required fields are absent from
// the active dataset.  If the currently-selected option becomes unavailable it
// is reset to the safe default for that dropdown.

export function updateFilterOptionVisibility(capabilities, view) {
  // ── Node filter ─────────────────────────────────────────────────────────
  const nodeCapabilityByValue = {
    'ftd-devices':              capabilities.hasFtdNodes,
    'mtd-devices':              capabilities.hasMtdNodes,
    'main-routers':             capabilities.hasMainRouters,
    'border-routers':           capabilities.hasBorderRouters,
    'routers-with-children':    capabilities.hasRoutersWithChildren,
    'routers-without-children': capabilities.hasRoutersWithoutChildren
  };

  const nodeFilterEl = document.getElementById('node-filter');
  Array.from(nodeFilterEl.options).forEach((opt) => {
    const meta = NODE_FILTER_OPTIONS.find((m) => m.value === opt.value);
    if (!meta || meta.alwaysShow) {
      opt.hidden = false;
      opt.disabled = false;
      return;
    }
    const available = nodeCapabilityByValue[opt.value] === true;
    opt.hidden = !available;
    opt.disabled = !available;
  });
  // Reset to 'all' if currently-selected option is now unavailable
  if (nodeFilterEl.options[nodeFilterEl.selectedIndex]?.disabled) {
    nodeFilterEl.value = 'all';
  }

  // ── Link filter ─────────────────────────────────────────────────────────
  // Link filter visibility only applies in topology view; in table view the
  // whole control is styled as disabled via CSS (filter-disabled class).
  const linkFilterEl = document.getElementById('link-filter');
  if (view === 'topology') {
    Array.from(linkFilterEl.options).forEach((opt) => {
      const meta = LINK_FILTER_OPTIONS.find((m) => m.value === opt.value);
      if (!meta || meta.alwaysShow) {
        opt.hidden = false;
        opt.disabled = false;
        return;
      }
      const available = meta.requiredEdgeCategories.some(
        (cat) => capabilities.edgeCategories.has(cat)
      );
      opt.hidden = !available;
      opt.disabled = !available;
    });
    if (linkFilterEl.options[linkFilterEl.selectedIndex]?.disabled) {
      linkFilterEl.value = LINK_FILTER_ALL;
    }
  }

  // ── Diagnostic filter ───────────────────────────────────────────────────
  const diagCapabilityByValue = {
    'medium-total-errors-pct':               capabilities.hasFieldMacTotalErrorsPct,
    'medium-total-errors-high':              capabilities.hasFieldMacTotalErrorsPct,
    'medium-discard-pct':                    capabilities.hasFieldMacDiscardPct,
    'medium-partition-changes':              capabilities.hasFieldPartitionChanges,
    'high-partition-changes':                capabilities.hasFieldPartitionChanges,
    'medium-parent-changes':                 capabilities.hasFieldParentChanges,
    'high-parent-changes':                   capabilities.hasFieldParentChanges,
    'router-neighbor-err-rate-frame-low':    capabilities.hasNeighborFrameErrRate,
    'router-neighbor-err-rate-frame-medium': capabilities.hasNeighborFrameErrRate,
    'router-neighbor-err-rate-frame-high':   capabilities.hasNeighborFrameErrRate,
    'router-neighbor-err-rate-msg-low':      capabilities.hasNeighborMsgErrRate,
    'router-neighbor-err-rate-msg-medium':   capabilities.hasNeighborMsgErrRate,
    'router-neighbor-err-rate-msg-high':     capabilities.hasNeighborMsgErrRate,
    'router-neighbor-rss-very-low':          capabilities.hasNeighborRss,
    'router-neighbor-rss-low':               capabilities.hasNeighborRss,
    'router-neighbor-rss-medium':            capabilities.hasNeighborRss,
    'router-neighbor-rss-high':              capabilities.hasNeighborRss
  };

  const diagFilterEl = document.getElementById('diagnostic-filter');
  Array.from(diagFilterEl.options).forEach((opt) => {
    const meta = DIAGNOSTIC_FILTER_OPTIONS.find((m) => m.value === opt.value);
    if (!meta || meta.alwaysShow) {
      opt.hidden = false;
      opt.disabled = false;
      return;
    }
    const available = diagCapabilityByValue[opt.value] === true;
    opt.hidden = !available;
    opt.disabled = !available;
  });
  if (diagFilterEl.options[diagFilterEl.selectedIndex]?.disabled) {
    diagFilterEl.value = 'all';
  }
}

// ── Node visibility predicates (topology) ─────────────────────────────────────

export function isNodeVisibleByFilter(node, filterMode) {
  if (filterMode === 'ftd-devices') return toText(node.mode_device).toUpperCase() === 'FTD';
  if (filterMode === 'mtd-devices') return toText(node.mode_device).toUpperCase() === 'MTD';
  if (filterMode === 'main-routers') return node.isMainRouter === true;
  if (filterMode === 'border-routers') return node.isBorderRouter === true;
  if (filterMode === 'routers-with-children') return node.isRouter === true && node.hasChildren === true;
  if (filterMode === 'routers-without-children') return node.isRouter === true && node.hasChildren !== true;
  return true;
}

export function isNodeVisibleByDiagnosticFilter(node, filterMode) {
  if (filterMode === 'medium-discard-pct') return Number.isFinite(node.iftotalpktserrorsdiscards_pct) && node.iftotalpktserrorsdiscards_pct >= 15;
  if (filterMode === 'medium-total-errors-pct') return (Number.isFinite(node.ifinerrors_pct) && node.ifinerrors_pct >= 5) || (Number.isFinite(node.ifouterrors_pct) && node.ifouterrors_pct >= 5);
  if (filterMode === 'medium-total-errors-high') return (Number.isFinite(node.ifinerrors_pct) && node.ifinerrors_pct > 10) || (Number.isFinite(node.ifouterrors_pct) && node.ifouterrors_pct > 10);
  if (filterMode === 'medium-partition-changes') return Number.isFinite(node.partitionidchanges) && node.partitionidchanges >= 2;
  if (filterMode === 'high-partition-changes') return Number.isFinite(node.partitionidchanges) && node.partitionidchanges >= 5;
  if (filterMode === 'medium-parent-changes') return Number.isFinite(node.parentchanges) && node.parentchanges >= 2;
  if (filterMode === 'high-parent-changes') return Number.isFinite(node.parentchanges) && node.parentchanges >= 5;
  if (filterMode === 'router-neighbor-err-rate-frame-low') return Number.isFinite(node.router_neighbor_max_err_rate_frame_pct) && node.router_neighbor_max_err_rate_frame_pct >= 2;
  if (filterMode === 'router-neighbor-err-rate-frame-medium') return Number.isFinite(node.router_neighbor_max_err_rate_frame_pct) && node.router_neighbor_max_err_rate_frame_pct >= 5;
  if (filterMode === 'router-neighbor-err-rate-frame-high') return Number.isFinite(node.router_neighbor_max_err_rate_frame_pct) && node.router_neighbor_max_err_rate_frame_pct >= 10;
  if (filterMode === 'router-neighbor-err-rate-msg-low') return Number.isFinite(node.router_neighbor_max_err_rate_msg_pct) && node.router_neighbor_max_err_rate_msg_pct >= 2;
  if (filterMode === 'router-neighbor-err-rate-msg-medium') return Number.isFinite(node.router_neighbor_max_err_rate_msg_pct) && node.router_neighbor_max_err_rate_msg_pct >= 5;
  if (filterMode === 'router-neighbor-err-rate-msg-high') return Number.isFinite(node.router_neighbor_max_err_rate_msg_pct) && node.router_neighbor_max_err_rate_msg_pct >= 10;
  if (filterMode === 'router-neighbor-rss-very-low') return node.router_neighbor_has_rss_very_low === true;
  if (filterMode === 'router-neighbor-rss-low') return node.router_neighbor_has_rss_low === true;
  if (filterMode === 'router-neighbor-rss-medium') return node.router_neighbor_has_rss_medium === true;
  if (filterMode === 'router-neighbor-rss-high') return node.router_neighbor_has_rss_high === true;
  return true;
}

// ── Router-neighbor diagnostic mode helpers ───────────────────────────────────

export function isRouterNeighborDiagnosticMode(mode) {
  return mode === 'router-neighbor-err-rate-frame-low'
    || mode === 'router-neighbor-err-rate-frame-medium'
    || mode === 'router-neighbor-err-rate-frame-high'
    || mode === 'router-neighbor-err-rate-msg-low'
    || mode === 'router-neighbor-err-rate-msg-medium'
    || mode === 'router-neighbor-err-rate-msg-high'
    || mode === 'router-neighbor-rss-very-low'
    || mode === 'router-neighbor-rss-low'
    || mode === 'router-neighbor-rss-medium'
    || mode === 'router-neighbor-rss-high';
}

export function routerNeighborRowMatchesDiagnosticFilter(row, mode) {
  const fp = toFiniteNumber(row?.err_rate_frame_pct);
  const mp = toFiniteNumber(row?.err_rate_msg_pct);
  const rss = toFiniteNumber(row?.rss_ave);
  if (mode === 'router-neighbor-err-rate-frame-low') return Number.isFinite(fp) && fp >= 2;
  if (mode === 'router-neighbor-err-rate-frame-medium') return Number.isFinite(fp) && fp >= 5;
  if (mode === 'router-neighbor-err-rate-frame-high') return Number.isFinite(fp) && fp >= 10;
  if (mode === 'router-neighbor-err-rate-msg-low') return Number.isFinite(mp) && mp >= 2;
  if (mode === 'router-neighbor-err-rate-msg-medium') return Number.isFinite(mp) && mp >= 5;
  if (mode === 'router-neighbor-err-rate-msg-high') return Number.isFinite(mp) && mp >= 10;
  if (mode === 'router-neighbor-rss-very-low') return Number.isFinite(rss) && rss < -80;
  if (mode === 'router-neighbor-rss-low') return Number.isFinite(rss) && rss >= -80 && rss < -70;
  if (mode === 'router-neighbor-rss-medium') return Number.isFinite(rss) && rss >= -70 && rss <= -60;
  if (mode === 'router-neighbor-rss-high') return Number.isFinite(rss) && rss > -60;
  return false;
}

// ── Row visibility predicates (table) ─────────────────────────────────────────

export function isRowVisibleByNodeFilter(row, filterMode) {
  if (filterMode === 'all') return true;
  const modeDevice = toText(getColumnValue(row, 'mode.device')).toUpperCase();
  const rloc16Text = toText(getColumnValue(row, 'rloc16')).toLowerCase();
  const isMainRouter = rloc16Text.endsWith('00');
  const brValue = getColumnValue(row, 'br');
  const isBorderRouter = isMainRouter && (brValue === true || toText(brValue).toLowerCase() === 'true');
  const totalChildren = toFiniteNumber(getColumnValue(row, 'total_children'));
  const childrenValue = getColumnValue(row, 'children');
  const childrenCount = Array.isArray(childrenValue) ? childrenValue.length : undefined;
  const hasChildren = (Number.isFinite(totalChildren) && totalChildren > 0)
    || (Number.isFinite(childrenCount) && childrenCount > 0);
  const isRouter = isMainRouter || Number.isFinite(totalChildren) || Array.isArray(childrenValue);
  if (filterMode === 'ftd-devices') return modeDevice === 'FTD';
  if (filterMode === 'mtd-devices') return modeDevice === 'MTD';
  if (filterMode === 'main-routers') return isMainRouter;
  if (filterMode === 'border-routers') return isBorderRouter;
  if (filterMode === 'routers-with-children') return isRouter && hasChildren;
  if (filterMode === 'routers-without-children') return isRouter && !hasChildren;
  return true;
}

export function isRowVisibleByDiagnosticFilter(row, filterMode) {
  if (filterMode === 'all') return true;
  const getMetric = (path) => {
    const v = getColumnValue(row, path);
    return Number.isFinite(v) ? v : undefined;
  };
  if (filterMode === 'medium-total-errors-pct') { const vi = getMetric('mac_counters.ifinerrors_pct'); const vo = getMetric('mac_counters.ifouterrors_pct'); return (Number.isFinite(vi) && vi >= 5) || (Number.isFinite(vo) && vo >= 5); }
  if (filterMode === 'medium-total-errors-high') { const vi = getMetric('mac_counters.ifinerrors_pct'); const vo = getMetric('mac_counters.ifouterrors_pct'); return (Number.isFinite(vi) && vi > 10) || (Number.isFinite(vo) && vo > 10); }
  if (filterMode === 'medium-discard-pct') { const vi = getMetric('mac_counters.ifindiscards_pct'); const vo = getMetric('mac_counters.ifoutdiscards_pct'); return (Number.isFinite(vi) && vi >= 15) || (Number.isFinite(vo) && vo >= 15); }
  if (filterMode === 'medium-partition-changes') { const v = getMetric('mle_counters.partitionidchanges'); return Number.isFinite(v) && v >= 2; }
  if (filterMode === 'high-partition-changes') { const v = getMetric('mle_counters.partitionidchanges'); return Number.isFinite(v) && v >= 5; }
  if (filterMode === 'medium-parent-changes') { const v = getMetric('mle_counters.parentchanges'); return Number.isFinite(v) && v >= 2; }
  if (filterMode === 'high-parent-changes') { const v = getMetric('mle_counters.parentchanges'); return Number.isFinite(v) && v >= 5; }

  const neighborRows = Array.isArray(getColumnValue(row, 'router_neighbor_table'))
    ? getColumnValue(row, 'router_neighbor_table') : [];
  const hasMatchingNeighbor = (pred) => neighborRows.some(pred);

  if (filterMode === 'router-neighbor-err-rate-frame-low') return hasMatchingNeighbor((n) => { const v = toFiniteNumber(n?.err_rate_frame_pct); return Number.isFinite(v) && v >= 2; });
  if (filterMode === 'router-neighbor-err-rate-frame-medium') return hasMatchingNeighbor((n) => { const v = toFiniteNumber(n?.err_rate_frame_pct); return Number.isFinite(v) && v >= 5; });
  if (filterMode === 'router-neighbor-err-rate-frame-high') return hasMatchingNeighbor((n) => { const v = toFiniteNumber(n?.err_rate_frame_pct); return Number.isFinite(v) && v >= 10; });
  if (filterMode === 'router-neighbor-err-rate-msg-low') return hasMatchingNeighbor((n) => { const v = toFiniteNumber(n?.err_rate_msg_pct); return Number.isFinite(v) && v >= 2; });
  if (filterMode === 'router-neighbor-err-rate-msg-medium') return hasMatchingNeighbor((n) => { const v = toFiniteNumber(n?.err_rate_msg_pct); return Number.isFinite(v) && v >= 5; });
  if (filterMode === 'router-neighbor-err-rate-msg-high') return hasMatchingNeighbor((n) => { const v = toFiniteNumber(n?.err_rate_msg_pct); return Number.isFinite(v) && v >= 10; });
  if (filterMode === 'router-neighbor-rss-very-low') return hasMatchingNeighbor((n) => { const v = toFiniteNumber(n?.rss_ave); return Number.isFinite(v) && v < -80; });
  if (filterMode === 'router-neighbor-rss-low') return hasMatchingNeighbor((n) => { const v = toFiniteNumber(n?.rss_ave); return Number.isFinite(v) && v >= -80 && v < -70; });
  if (filterMode === 'router-neighbor-rss-medium') return hasMatchingNeighbor((n) => { const v = toFiniteNumber(n?.rss_ave); return Number.isFinite(v) && v >= -70 && v <= -60; });
  if (filterMode === 'router-neighbor-rss-high') return hasMatchingNeighbor((n) => { const v = toFiniteNumber(n?.rss_ave); return Number.isFinite(v) && v > -60; });
  return true;
}
