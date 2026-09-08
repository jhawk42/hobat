import {
  LINK_FILTER_ALL,
  LINK_FILTER_EVE_NATIVE,
  LINK_FILTER_EVE_ENHANCED,
  LINK_FILTER_ROUTES_ROUTERS_PARENT_CHILD,
  LINK_FILTER_DEFAULT_PLUS_NEIGHBORS,
  LINK_FILTER_ROUTES,
  LINK_FILTER_ROUTES_ROUTERS,
  LINK_FILTER_ROUTES_FTD_CHILD,
  LINK_FILTER_PARENT_CHILD,
  LINK_FILTER_ROUTER_NEIGHBOR,
  LINK_FILTER_LQ_HIGH,
  LINK_FILTER_LQ_MEDIUM,
  LINK_FILTER_LQ_LOW,
  LINK_FILTER_LQ_NONE,
  EDGE_CATEGORY_DEFAULT_CHILDREN,
  EDGE_CATEGORY_DEFAULT_1,
  EDGE_CATEGORY_DEFAULT_2,
  EDGE_CATEGORY_DEFAULT_3,
  EDGE_CATEGORY_ROUTER_NEIGHBOR,
  EDGE_CATEGORY_OTBR_ROUTE,
  EDGE_CATEGORY_OTBR_ROUTE_ROUTER,
  EDGE_CATEGORY_OTBR_ROUTE_FTD_CHILD,
  EDGE_CATEGORY_OTBR_CHILD,
  EDGE_CATEGORY_EVE_ROUTE,
  EDGE_CATEGORY_EVE_CHILD,
  EDGE_CATEGORY_EVE_NATIVE_ROUTE,
  EDGE_CATEGORY_EVE_NATIVE_CHILD,
  NODE_FILTER_OPTIONS,
  LINK_FILTER_OPTIONS,
  DIAGNOSTIC_FILTER_OPTIONS,
} from "./tdash-constants.js";
import {
  toText,
  toFiniteNumber,
  isPlainObject,
  getColumnValue,
  getCanonicalRloc16,
  getCanonicalExtaddr,
  getCanonicalOmrIpv6Address,
} from "./tdash-utils.js";

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
  
   if (mode === LINK_FILTER_ALL) return true;
   if (mode === LINK_FILTER_EVE_ENHANCED)
    return hasAny(EDGE_CATEGORY_EVE_ROUTE, EDGE_CATEGORY_EVE_CHILD);
  if (mode === LINK_FILTER_EVE_NATIVE)
    return hasAny(
      EDGE_CATEGORY_EVE_NATIVE_ROUTE,
      EDGE_CATEGORY_EVE_NATIVE_CHILD,
    );
  if (mode === LINK_FILTER_PARENT_CHILD) return edge.isParentChild === true;
  /*
      EDGE_CATEGORY_DEFAULT_CHILDREN,
      EDGE_CATEGORY_OTBR_CHILD,
      EDGE_CATEGORY_EVE_CHILD,
      EDGE_CATEGORY_EVE_NATIVE_CHILD,  
  */  
  if (mode === LINK_FILTER_ROUTES_ROUTERS_PARENT_CHILD) {
    return hasAny(
      EDGE_CATEGORY_DEFAULT_1,
      EDGE_CATEGORY_DEFAULT_2,
      EDGE_CATEGORY_DEFAULT_3,
      EDGE_CATEGORY_OTBR_ROUTE_ROUTER,

      EDGE_CATEGORY_DEFAULT_CHILDREN,
      EDGE_CATEGORY_OTBR_CHILD,
      EDGE_CATEGORY_EVE_CHILD,
      EDGE_CATEGORY_EVE_NATIVE_CHILD,      
    );
  }
  if (mode === LINK_FILTER_DEFAULT_PLUS_NEIGHBORS) {
    return hasAny(
      EDGE_CATEGORY_DEFAULT_CHILDREN,
      EDGE_CATEGORY_DEFAULT_1,
      EDGE_CATEGORY_DEFAULT_2,
      EDGE_CATEGORY_DEFAULT_3,
      EDGE_CATEGORY_OTBR_CHILD,
      EDGE_CATEGORY_ROUTER_NEIGHBOR,
    );
  }
  if (mode === LINK_FILTER_ROUTES)
    return hasAny(
      EDGE_CATEGORY_DEFAULT_1,
      EDGE_CATEGORY_DEFAULT_2,
      EDGE_CATEGORY_DEFAULT_3,
      EDGE_CATEGORY_OTBR_ROUTE,
      EDGE_CATEGORY_OTBR_ROUTE_ROUTER,
      EDGE_CATEGORY_OTBR_ROUTE_FTD_CHILD,
    );

  if (mode === LINK_FILTER_ROUTES_ROUTERS)
    return hasAny(
      EDGE_CATEGORY_DEFAULT_1,
      EDGE_CATEGORY_DEFAULT_2,
      EDGE_CATEGORY_DEFAULT_3,
      EDGE_CATEGORY_OTBR_ROUTE_ROUTER,
    );

  if (mode === LINK_FILTER_ROUTES_FTD_CHILD)
    return hasAny(EDGE_CATEGORY_OTBR_ROUTE_FTD_CHILD);

  if (mode === LINK_FILTER_ROUTER_NEIGHBOR)
    return hasAny(
      EDGE_CATEGORY_OTBR_ROUTE,
      EDGE_CATEGORY_ROUTER_NEIGHBOR,
    );

  if (mode === LINK_FILTER_LQ_HIGH) return (edge.lqLevel ?? 0) === 3;
  if (mode === LINK_FILTER_LQ_MEDIUM) return (edge.lqLevel ?? 0) === 2;
  if (mode === LINK_FILTER_LQ_LOW) return (edge.lqLevel ?? 0) === 1;
 
  if (mode === LINK_FILTER_LQ_NONE) return !edge.lqLevel || edge.lqLevel === 0;
  return false;
}

// ── Dataset capabilities ──────────────────────────────────────────────────────
//
// Both functions return the same DatasetCapabilities shape:
//   {
//     hasFtdNodes, hasMtdNodes, hasReedNodes, hasRouters, hasBorderRouters,
//     hasRoutersWithChildren, hasRoutersWithoutChildren,
//     edgeCategories : Set<string>,   (empty in table view)
//     hasFieldMacTotalErrorsPct, hasFieldMacDiscardPct,
//     hasFieldPartitionChanges, hasFieldParentChanges,
//     hasNeighborFrameErrRate, hasNeighborMsgErrRate, hasNeighborRss,
//     hasLinkQualityDistribution, hasChildLinkQuality,
//     hasChildFrameErrRate, hasChildMsgErrRate,
//     hasChildRss, hasChildRssMargin, hasChildQueuedMsgs,
//     hasFieldMacTotalErrorsRatio, hasFieldMacTotalDiscardsRatio,
//     hasFieldBetterPartitionAttach, hasFieldTotalParentPartitionChanges,
//     hasFieldRouterPct, hasFieldDetachedDisabledPct
//   }

function isReedDevice(modeDevice, role, isRouter, isBorderRouter) {
  if (toText(modeDevice).toUpperCase() !== "FTD") return false;
  const normalizedRole = toText(role).trim().toLowerCase();
  if (normalizedRole) return normalizedRole === "child";
  return isRouter !== true && isBorderRouter !== true;
}

// Called after runAdaptor() in renderTopologyForDataset.
// Scans vis-node objects and edge linkCategories.
export function computeTopologyCapabilities(nodeData, edgeData) {
  let hasFtdNodes = false;
  let hasMtdNodes = false;
  let hasReedNodes = false;
  let hasRouters = false;
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
  let hasLinkQualityDistribution = false;
  let hasChildLinkQuality = false;
  let hasChildFrameErrRate = false;
  let hasChildMsgErrRate = false;
  let hasChildRss = false;
  let hasChildRssMargin = false;
  let hasChildQueuedMsgs = false;
  let hasFieldMacTotalErrorsRatio = false;
  let hasFieldMacTotalDiscardsRatio = false;
  let hasFieldBetterPartitionAttach = false;
  let hasFieldTotalParentPartitionChanges = false;
  let hasFieldRouterPct = false;
  let hasFieldDetachedDisabledPct = false;

  for (const node of nodeData) {
    const md = toText(node.mode_device).toUpperCase();
    if (md === "FTD") hasFtdNodes = true;
    if (md === "MTD") hasMtdNodes = true;
    if (isReedDevice(md, node.role, node.isRouter, node.isBorderRouter))
      hasReedNodes = true;
    if (node.isRouter === true) hasRouters = true;
    if (node.isBorderRouter === true) hasBorderRouters = true;
    if (node.isRouter === true && node.hasChildren === true)
      hasRoutersWithChildren = true;
    if (node.isRouter === true && node.hasChildren !== true)
      hasRoutersWithoutChildren = true;
    if (
      Number.isFinite(node.ifinerrors_pct) ||
      Number.isFinite(node.ifouterrors_pct)
    )
      hasFieldMacTotalErrorsPct = true;
    if (Number.isFinite(node.ifindiscards_pct)) hasFieldMacDiscardPct = true;
    if (Number.isFinite(node.partitionidchanges) || Number.isFinite(node.partIdChangesCount))
      hasFieldPartitionChanges = true;
    if (Number.isFinite(node.parentchanges) || Number.isFinite(node.newParentCount))
      hasFieldParentChanges = true;
    if (Number.isFinite(node.router_neighbor_max_err_rate_frame_pct))
      hasNeighborFrameErrRate = true;
    if (Number.isFinite(node.router_neighbor_max_err_rate_msg_pct))
      hasNeighborMsgErrRate = true;
    if (
      Number.isFinite(node.router_neighbor_min_rss_ave) ||
      Number.isFinite(node.router_neighbor_max_rss_ave)
    )
      hasNeighborRss = true;
    if (Number.isFinite(node.lq3Ratio) || Number.isFinite(node.lq1Ratio))
      hasLinkQualityDistribution = true;
    if (node.hasChildLqMedium === true || node.hasChildLqPoor === true)
      hasChildLinkQuality = true;
    if (Number.isFinite(node.router_child_max_err_rate_frame_pct))
      hasChildFrameErrRate = true;
    if (Number.isFinite(node.router_child_max_err_rate_msg_pct))
      hasChildMsgErrRate = true;
    if (node.router_child_has_rss_very_low === true || node.router_child_has_rss_low === true)
      hasChildRss = true;
    if (node.router_child_has_rss_margin_low === true)
      hasChildRssMargin = true;
    if (node.router_child_has_queued_msgs === true)
      hasChildQueuedMsgs = true;
    if (Number.isFinite(node.ifTotalErrorsTotalPktsRatio))
      hasFieldMacTotalErrorsRatio = true;
    if (Number.isFinite(node.ifTotalDiscardsTotalPktsRatio))
      hasFieldMacTotalDiscardsRatio = true;
    if (Number.isFinite(node.betterPartIdAttachAttemptsCount))
      hasFieldBetterPartitionAttach = true;
    if (Number.isFinite(node.totalParentPartitionChangesCount))
      hasFieldTotalParentPartitionChanges = true;
    if (Number.isFinite(node.routerPct))
      hasFieldRouterPct = true;
    if (Number.isFinite(node.detachedDisabledPct))
      hasFieldDetachedDisabledPct = true;
  }

  const edgeCategories = new Set();
  for (const edge of edgeData) {
    for (const cat of normalizeLinkCategories(edge.linkCategories)) {
      edgeCategories.add(cat);
    }
  }

  return {
    hasFtdNodes,
    hasMtdNodes,
    hasReedNodes,
    hasRouters,
    hasBorderRouters,
    hasRoutersWithChildren,
    hasRoutersWithoutChildren,
    edgeCategories,
    hasFieldMacTotalErrorsPct,
    hasFieldMacDiscardPct,
    hasFieldPartitionChanges,
    hasFieldParentChanges,
    hasNeighborFrameErrRate,
    hasNeighborMsgErrRate,
    hasNeighborRss,
    hasLinkQualityDistribution,
    hasChildLinkQuality,
    hasChildFrameErrRate,
    hasChildMsgErrRate,
    hasChildRss,
    hasChildRssMargin,
    hasChildQueuedMsgs,
    hasFieldMacTotalErrorsRatio,
    hasFieldMacTotalDiscardsRatio,
    hasFieldBetterPartitionAttach,
    hasFieldTotalParentPartitionChanges,
    hasFieldRouterPct,
    hasFieldDetachedDisabledPct,
  };
}

// Called at the top of renderTableForDataset.
// Scans normalised row objects (including router_neighbor_table sub-arrays).
// edgeCategories is always an empty Set (table view has no topology edges).
export function computeTableCapabilities(rows) {
  let hasFtdNodes = false;
  let hasMtdNodes = false;
  let hasReedNodes = false;
  let hasRouters = false;
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
  let hasLinkQualityDistribution = false;
  let hasChildLinkQuality = false;
  let hasChildFrameErrRate = false;
  let hasChildMsgErrRate = false;
  let hasChildRss = false;
  let hasChildRssMargin = false;
  let hasChildQueuedMsgs = false;
  let hasFieldMacTotalErrorsRatio = false;
  let hasFieldMacTotalDiscardsRatio = false;
  let hasFieldBetterPartitionAttach = false;
  let hasFieldTotalParentPartitionChanges = false;
  let hasFieldRouterPct = false;
  let hasFieldDetachedDisabledPct = false;

  for (const row of rows) {
    const md = toText(getColumnValue(row, "mode.device")).toUpperCase();
    if (md === "FTD") hasFtdNodes = true;
    if (md === "MTD") hasMtdNodes = true;

    const rloc16Text = toText(getColumnValue(row, "rloc16")).toLowerCase();
    // rloc16 starts with 0x and ends with 00 and has a length of 6
    const isRouter = rloc16Text.startsWith("0x") && rloc16Text.endsWith("00") && rloc16Text.length === 6;
    if (isRouter) hasRouters = true;

    const brValue = getColumnValue(row, "br");
    const isBorderRouter =
      isRouter &&
      (brValue === true || toText(brValue).toLowerCase() === "true");
    if (isBorderRouter) hasBorderRouters = true;
    if (isReedDevice(md, getColumnValue(row, "role"), isRouter, isBorderRouter))
      hasReedNodes = true;

    const totalChildren = toFiniteNumber(getColumnValue(row, "total_children"));
    const childrenValue = getColumnValue(row, "children");
    const childrenCount = Array.isArray(childrenValue)
      ? childrenValue.length
      : undefined;
    const hasChildren =
      (Number.isFinite(totalChildren) && totalChildren > 0) ||
      (Number.isFinite(childrenCount) && childrenCount > 0);
   
    if (isRouter && hasChildren) hasRoutersWithChildren = true;
    if (isRouter && !hasChildren) hasRoutersWithoutChildren = true;

    const macInerrors = getColumnValue(row, "mac_counters.ifinerrors_pct");
    const macOuterrors = getColumnValue(row, "mac_counters.ifouterrors_pct");
    if (
      Number.isFinite(toFiniteNumber(macInerrors)) ||
      Number.isFinite(toFiniteNumber(macOuterrors))
    )
      hasFieldMacTotalErrorsPct = true;

    const macDiscard = getColumnValue(row, "mac_counters.ifindiscards_pct");
    if (Number.isFinite(toFiniteNumber(macDiscard)))
      hasFieldMacDiscardPct = true;

    const partChanges = getColumnValue(row, "mleCounters.partIdChangesCount")
      ?? getColumnValue(row, "mle_counters.partitionidchanges");
    if (Number.isFinite(toFiniteNumber(partChanges)))
      hasFieldPartitionChanges = true;

    const parentChanges = getColumnValue(row, "mleCounters.newParentCount")
      ?? getColumnValue(row, "mle_counters.parentchanges");
    if (Number.isFinite(toFiniteNumber(parentChanges)))
      hasFieldParentChanges = true;

    const neighborRows = Array.isArray(
      getColumnValue(row, "routerNeighbors"),
    )
      ? getColumnValue(row, "routerNeighbors")
      : [];
    for (const neighbor of neighborRows) {
      if (Number.isFinite(toFiniteNumber(neighbor?.frameErrorRate)))
        hasNeighborFrameErrRate = true;
      if (Number.isFinite(toFiniteNumber(neighbor?.messageErrorRate)))
        hasNeighborMsgErrRate = true;
      if (Number.isFinite(toFiniteNumber(neighbor?.averageRssi)))
        hasNeighborRss = true;
    }

    if (
      Number.isFinite(toFiniteNumber(getColumnValue(row, "links3"))) &&
      Number.isFinite(toFiniteNumber(getColumnValue(row, "totalLinks")))
    )
      hasLinkQualityDistribution = true;

    const childrenForLQ = Array.isArray(getColumnValue(row, "children"))
      ? getColumnValue(row, "children")
      : [];
    for (const child of childrenForLQ) {
      const lqRaw = child?.lq !== undefined ? child.lq : child?.linkQuality;
      if (Number.isFinite(Number.parseInt(lqRaw, 10)))
        hasChildLinkQuality = true;
    }

    const childTableRows = Array.isArray(getColumnValue(row, "childTable"))
      ? getColumnValue(row, "childTable")
      : [];
    for (const child of childTableRows) {
      if (Number.isFinite(toFiniteNumber(child?.frameErrorRate)))
        hasChildFrameErrRate = true;
      if (Number.isFinite(toFiniteNumber(child?.messageErrorRate)))
        hasChildMsgErrRate = true;
      if (Number.isFinite(toFiniteNumber(child?.averageRssi)))
        hasChildRss = true;
      if (Number.isFinite(toFiniteNumber(child?.linkMargin)))
        hasChildRssMargin = true;
      const qMsg = toFiniteNumber(child?.queuedMessageCount);
      if (Number.isFinite(qMsg) && qMsg > 0)
        hasChildQueuedMsgs = true;
    }

    if (Number.isFinite(toFiniteNumber(getColumnValue(row, "macCounters.ifTotalErrorsTotalPktsRatio"))))
      hasFieldMacTotalErrorsRatio = true;
    if (Number.isFinite(toFiniteNumber(getColumnValue(row, "macCounters.ifTotalDiscardsTotalPktsRatio"))))
      hasFieldMacTotalDiscardsRatio = true;
    if (Number.isFinite(toFiniteNumber(getColumnValue(row, "mleCounters.betterPartIdAttachAttemptsCount"))))
      hasFieldBetterPartitionAttach = true;
    if (Number.isFinite(toFiniteNumber(getColumnValue(row, "mleCounters.totalParentPartitionChangesCount"))))
      hasFieldTotalParentPartitionChanges = true;
    if (Number.isFinite(toFiniteNumber(getColumnValue(row, "timeStatistics.routerPct"))))
      hasFieldRouterPct = true;
    if (Number.isFinite(toFiniteNumber(getColumnValue(row, "timeStatistics.detachedDisabledPct"))))
      hasFieldDetachedDisabledPct = true;
  }

  return {
    hasFtdNodes,
    hasMtdNodes,
    hasReedNodes,
    hasRouters,
    hasBorderRouters,
    hasRoutersWithChildren,
    hasRoutersWithoutChildren,
    edgeCategories: new Set(),
    hasFieldMacTotalErrorsPct,
    hasFieldMacDiscardPct,
    hasFieldPartitionChanges,
    hasFieldParentChanges,
    hasNeighborFrameErrRate,
    hasNeighborMsgErrRate,
    hasNeighborRss,
    hasLinkQualityDistribution,
    hasChildLinkQuality,
    hasChildFrameErrRate,
    hasChildMsgErrRate,
    hasChildRss,
    hasChildRssMargin,
    hasChildQueuedMsgs,
    hasFieldMacTotalErrorsRatio,
    hasFieldMacTotalDiscardsRatio,
    hasFieldBetterPartitionAttach,
    hasFieldTotalParentPartitionChanges,
    hasFieldRouterPct,
    hasFieldDetachedDisabledPct,
  };
}

// ── Filter select population (DOM) ───────────────────────────────────────────
//
// Builds <option> / <optgroup> elements from a registry array and appends them
// to the given <select>.  Mirrors populateDatasetSelect() in tdash-ui.js.
//
// Non-alwaysShow options start hidden/disabled; updateFilterOptionVisibility()
// reveals them after a dataset is rendered.
//
// Group constraint: group label strings must be unique within each registry so
// that consecutive entries with the same group string map to one <optgroup>.

function buildFilterSelect(selectId, registry) {
  const el = document.getElementById(selectId);
  el.innerHTML = "";

  let currentGroupLabel = undefined;
  let currentOptgroup = null;

  for (let i = 0; i < registry.length; i++) {
    const entry = registry[i];

    if (entry.group !== currentGroupLabel) {
      currentGroupLabel = entry.group;
      if (entry.group != null) {
        currentOptgroup = document.createElement("optgroup");
        currentOptgroup.label = entry.group;
        el.appendChild(currentOptgroup);
      } else {
        currentOptgroup = null;
      }
    }

    const opt = document.createElement("option");
    opt.value = entry.value;
    opt.textContent = entry.label;
    if (entry.title) opt.title = entry.title;
    // Only the first entry (the "all" reset option) starts visible.
    // updateFilterOptionVisibility() reveals the rest after a dataset loads.
    if (i > 0) {
      opt.hidden = true;
      opt.disabled = true;
    }

    (currentOptgroup ?? el).appendChild(opt);
  }
}

export function populateFilterSelects() {
  buildFilterSelect("node-filter",       NODE_FILTER_OPTIONS);
  buildFilterSelect("link-filter",       LINK_FILTER_OPTIONS);
  buildFilterSelect("diagnostic-filter", DIAGNOSTIC_FILTER_OPTIONS);
}

// ── Check if any nodes match a diagnostic filter option ───────────────────────
//
// This prevents showing filter options that have no matching rows.

function anyNodesMatchDiagnosticFilter(nodeData, filterMode) {
  if (!nodeData || nodeData.length === 0) return false;
  return nodeData.some(node => isNodeVisibleByDiagnosticFilter(node, filterMode));
}

function anyRowsMatchDiagnosticFilter(rows, filterMode) {
  if (!rows || rows.length === 0) return false;
  return rows.some((row) => isRowVisibleByDiagnosticFilter(row, filterMode));
}

function normalizeDiagnosticSourceValue(sourceValue) {
  if (sourceValue === "mac_counters") return "macCounters";
  if (sourceValue === "mle_counters") return "mlecounters";
  return sourceValue;
}

export function isDiagnosticOptionAvailable(option, capabilities) {
  if (!option || option.alwaysShow === true) return true;
  return capabilities?.[option.capabilityKey] === true;
}

// ── Populate diagnostic filter by source with capability checking ──────────────
//
// Populates the diagnostic-filter select based on the selected source and the
// current dataset capabilities. Only shows options that:
// 1. Match the selected source
// 2. Have the required fields in the dataset (capability check)
// 3. Actually have matching rows in the dataset (data validation check)

export function populateDiagnosticFilterBySourceWithCapabilities(sourceValue, capabilities, nodeData, view = "topology") {
  const el = document.getElementById("diagnostic-filter");
  el.innerHTML = "";
  sourceValue = normalizeDiagnosticSourceValue(sourceValue);

  // Always add the "all" option first
  const allOpt = document.createElement("option");
  allOpt.value = "all";
  allOpt.textContent = "All Rows";
  allOpt.selected = true;
  el.appendChild(allOpt);

  // Filter DIAGNOSTIC_FILTER_OPTIONS by source, capability, AND data validation
  const filteredOptions = DIAGNOSTIC_FILTER_OPTIONS.filter(
    (entry) => {
      if (entry.source !== sourceValue) return false;
      if (entry.alwaysShow === true) return true;
      if (!isDiagnosticOptionAvailable(entry, capabilities)) return false;
      // Only show if there are actual matches for this filter in the active view.
      if (!nodeData) return true;
      if (view === "table") {
        return anyRowsMatchDiagnosticFilter(nodeData, entry.value);
      }
      return anyNodesMatchDiagnosticFilter(nodeData, entry.value);
    }
  );

  for (const entry of filteredOptions) {
    const opt = document.createElement("option");
    opt.value = entry.value;
    opt.textContent = entry.label;
    if (entry.title) opt.title = entry.title;
    el.appendChild(opt);
  }
}

// ── Populate diagnostic filter by source (without capability checking) ─────────
//
// Legacy function for when capabilities are not available.
// Used during initialization before a dataset is loaded.

export function populateDiagnosticFilterBySource(sourceValue) {
  const el = document.getElementById("diagnostic-filter");
  el.innerHTML = "";
  sourceValue = normalizeDiagnosticSourceValue(sourceValue);

  // Always add the "all" option first
  const allOpt = document.createElement("option");
  allOpt.value = "all";
  allOpt.textContent = "All Rows";
  allOpt.selected = true;
  el.appendChild(allOpt);

  // Filter DIAGNOSTIC_FILTER_OPTIONS by source and add to select
  const filteredOptions = DIAGNOSTIC_FILTER_OPTIONS.filter(
    (entry) => entry.source === sourceValue
  );

  for (const entry of filteredOptions) {
    const opt = document.createElement("option");
    opt.value = entry.value;
    opt.textContent = entry.label;
    if (entry.title) opt.title = entry.title;
    el.appendChild(opt);
  }
}

// ── Filter option visibility (DOM) ────────────────────────────────────────────
//
// Hides/disables filter <option> elements whose required fields are absent from
// the active dataset.  If the currently-selected option becomes unavailable it
// is reset to the safe default for that dropdown.

export function updateFilterOptionVisibility(capabilities, view) {
  // ── Node filter ─────────────────────────────────────────────────────────
  const nodeCapabilityByValue = {
    "ftd-devices": capabilities.hasFtdNodes,
    "mtd-devices": capabilities.hasMtdNodes,
    "reed-devices": capabilities.hasReedNodes,
    "main-routers": capabilities.hasRouters,
    "border-routers": capabilities.hasBorderRouters,
    "routers-with-children": capabilities.hasRoutersWithChildren,
    "routers-without-children": capabilities.hasRoutersWithoutChildren,
  };

  const nodeFilterEl = document.getElementById("node-filter");
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
    nodeFilterEl.value = "all";
  }

  // ── Link filter ─────────────────────────────────────────────────────────
  // Link filter visibility only applies in topology view; in table view the
  // whole control is styled as disabled via CSS (filter-disabled class).
  const linkFilterEl = document.getElementById("link-filter");
  if (view === "topology") {
    Array.from(linkFilterEl.options).forEach((opt) => {
      const meta = LINK_FILTER_OPTIONS.find((m) => m.value === opt.value);
      if (!meta || meta.alwaysShow) {
        opt.hidden = false;
        opt.disabled = false;
        return;
      }
      const available = meta.requiredEdgeCategories.some((cat) =>
        capabilities.edgeCategories.has(cat),
      );
      opt.hidden = !available;
      opt.disabled = !available;
    });
    if (linkFilterEl.options[linkFilterEl.selectedIndex]?.disabled) {
      linkFilterEl.value = LINK_FILTER_ALL;
    }
  }

  // ── Diagnostic filter ───────────────────────────────────────────────────
  const diagFilterEl = document.getElementById("diagnostic-filter");
  Array.from(diagFilterEl.options).forEach((opt) => {
    const meta = DIAGNOSTIC_FILTER_OPTIONS.find((m) => m.value === opt.value);
    if (!meta || meta.alwaysShow) {
      opt.hidden = false;
      opt.disabled = false;
      return;
    }
    const available = isDiagnosticOptionAvailable(meta, capabilities);
    opt.hidden = !available;
    opt.disabled = !available;
  });
  if (diagFilterEl.options[diagFilterEl.selectedIndex]?.disabled) {
    diagFilterEl.value = "all";
  }
}

// ── Node visibility predicates (topology) ─────────────────────────────────────

export function isNodeVisibleByFilter(node, filterMode) {
  if (filterMode === "ftd-devices")
    return toText(node.mode_device).toUpperCase() === "FTD";
  if (filterMode === "mtd-devices")
    return toText(node.mode_device).toUpperCase() === "MTD";
  if (filterMode === "reed-devices")
    return isReedDevice(
      node.mode_device,
      node.role,
      node.isRouter,
      node.isBorderRouter,
    );
  if (filterMode === "main-routers") return node.isRouter === true;
  if (filterMode === "border-routers") return node.isBorderRouter === true;
  if (filterMode === "routers-with-children")
    return node.isRouter === true && node.hasChildren === true;
  if (filterMode === "routers-without-children")
    return node.isRouter === true && node.hasChildren !== true;
  return true;
}

function getDiagnosticOptionByValue(filterMode) {
  return DIAGNOSTIC_FILTER_OPTIONS.find((entry) => entry.value === filterMode);
}

// ── Router-neighbor diagnostic mode helpers ───────────────────────────────────

export function isRouterNeighborDiagnosticMode(mode) {
  return getDiagnosticOptionByValue(mode)?.relationshipKind === "router-neighbor";
}

export function isChildLinkQualityDiagnosticMode(mode) {
  return getDiagnosticOptionByValue(mode)?.relationshipKind === "child-link-quality";
}

export function childMatchesLinkQualityFilter(child, mode) {
  return diagnosticRelationshipRecordMatches(child, mode);
}

export function routerNeighborRowMatchesDiagnosticFilter(row, mode) {
  return diagnosticRelationshipRecordMatches(row, mode);
}

// ── Router-child diagnostic mode helpers ───────────────────────────────────────

export function isRouterChildDiagnosticMode(mode) {
  return getDiagnosticOptionByValue(mode)?.relationshipKind === "router-child";
}

export function routerChildRowMatchesDiagnosticFilter(row, mode) {
  return diagnosticRelationshipRecordMatches(row, mode);
}

// ── Row visibility predicates (table) ─────────────────────────────────────────

function isExplicitTrue(value) {
  return value === true || toText(value).toLowerCase() === "true";
}

function normalizeRowRole(value) {
  return toText(value).toLowerCase().replace(/[\s_-]+/g, "");
}

export function getRowRoleProjection(row) {
  const modeDevice = toText(getColumnValue(row, "mode.device")).toUpperCase();
  const rloc16 = toText(getColumnValue(row, "rloc16")).toLowerCase();
  const roleValues = [getColumnValue(row, "role"), getColumnValue(row, "type")]
    .map(normalizeRowRole);
  const isBorderRouter = isExplicitTrue(getColumnValue(row, "isBorderRouter"))
    || isExplicitTrue(getColumnValue(row, "br"))
    || roleValues.includes("borderrouter");
  const isRouter = isBorderRouter
    || isExplicitTrue(getColumnValue(row, "isRouter"))
    || roleValues.includes("router")
    || roleValues.includes("leader")
    || (rloc16.startsWith("0x") && rloc16.endsWith("00") && rloc16.length === 6);
  const isChild = roleValues.some((value) =>
    ["child", "sleepychild", "enddevice", "sleepyenddevice", "reed"].includes(value),
  );
  const isReedRouter = rloc16.startsWith("0x") && rloc16.endsWith("00") && rloc16.length === 6;
  const hasThreadClassification = Boolean(
    rloc16 || getColumnValue(row, "br") != null || getColumnValue(row, "isRouter") != null
    || getColumnValue(row, "isBorderRouter") != null || getColumnValue(row, "type") != null
    || getColumnValue(row, "role") != null,
  );
  return { modeDevice, isRouter, isBorderRouter, isChild, isReedRouter, hasThreadClassification };
}

export function computeRowCounts(rows) {
  const hasThreadClassification = rows.some((row) => getRowRoleProjection(row).hasThreadClassification);
  if (!hasThreadClassification) {
    return {
      devices: rows.length,
      borderRouters: null, routers: null, children: null,
      links: null, lq3: null, lq2: null, lq1: null,
    };
  }
  let totalLink3 = 0, totalLink2 = 0, totalLink1 = 0, totalLinks = 0, hasLinkFields = false;
  const routerRows = rows.filter((row) => !getRowRoleProjection(row).isChild);
  routerRows.forEach((row) => {
    const link3 = toFiniteNumber(getColumnValue(row, "totalLink3") ?? getColumnValue(row, "total_link_3"));
    const link2 = toFiniteNumber(getColumnValue(row, "totalLink2") ?? getColumnValue(row, "total_link_2"));
    const link1 = toFiniteNumber(getColumnValue(row, "totalLink1") ?? getColumnValue(row, "total_link_1"));
    const links = toFiniteNumber(getColumnValue(row, "totalLinks") ?? getColumnValue(row, "total_links"));
    if (Number.isFinite(link3)) { totalLink3 += link3; hasLinkFields = true; }
    if (Number.isFinite(link2)) { totalLink2 += link2; hasLinkFields = true; }
    if (Number.isFinite(link1)) { totalLink1 += link1; hasLinkFields = true; }
    if (Number.isFinite(links)) { totalLinks += links; hasLinkFields = true; }
  });
  return {
    devices: rows.length,
    borderRouters: rows.filter((row) => getRowRoleProjection(row).isBorderRouter).length,
    routers: routerRows.filter((row) => {
      const role = getRowRoleProjection(row);
      return !role.isBorderRouter && role.isRouter;
    }).length,
    children: rows.filter((row) => getRowRoleProjection(row).isChild).length,
    links: hasLinkFields ? Math.round(totalLinks / 2) : null,
    lq3: hasLinkFields ? Math.round(totalLink3 / 2) : null,
    lq2: hasLinkFields ? Math.round(totalLink2 / 2) : null,
    lq1: hasLinkFields ? Math.round(totalLink1 / 2) : null,
  };
}

export function isRowVisibleByNodeFilter(row, filterMode) {
  if (filterMode === "all") return true;
  const { modeDevice, isRouter, isReedRouter, isBorderRouter } = getRowRoleProjection(row);
  const totalChildren = toFiniteNumber(getColumnValue(row, "total_children"));
  const childrenValue = getColumnValue(row, "children");
  const childrenCount = Array.isArray(childrenValue)
    ? childrenValue.length
    : undefined;
  const hasChildren =
    (Number.isFinite(totalChildren) && totalChildren > 0) ||
    (Number.isFinite(childrenCount) && childrenCount > 0);
 
  if (filterMode === "ftd-devices") return modeDevice === "FTD";
  if (filterMode === "mtd-devices") return modeDevice === "MTD";
  if (filterMode === "reed-devices")
    return isReedDevice(
      modeDevice,
      getColumnValue(row, "role"),
      isReedRouter,
      isBorderRouter,
    );
  if (filterMode === "main-routers") return isRouter;
  if (filterMode === "border-routers") return isBorderRouter;
  if (filterMode === "routers-with-children") return isRouter && hasChildren;
  if (filterMode === "routers-without-children")
    return isRouter && !hasChildren;
  return true;
}

// ── Per-record diagnostic evaluation ─────────────────────────────────────────

const DIAGNOSTIC_RELATIONSHIP_FIELD_ALIASES = Object.freeze({
  frameErrorRate: ["err_rate_frame_pct", "frameErrorRate"],
  messageErrorRate: ["err_rate_msg_pct", "messageErrorRate"],
  averageRssi: ["averageRssi", "rss_ave"],
  linkMargin: ["linkMargin", "rss_margin"],
  queuedMessageCount: ["queuedMessageCount", "q_msg"],
  linkQuality: ["linkQuality", "lq", "link_quality"],
});

export function compareDiagnosticMetric(metric, comparison, threshold) {
  if (!Number.isFinite(metric) || !Number.isFinite(threshold)) return false;
  if (comparison === ">=") return metric >= threshold;
  if (comparison === ">") return metric > threshold;
  if (comparison === "<=") return metric <= threshold;
  if (comparison === "<") return metric < threshold;
  if (comparison === "==") return metric === threshold;
  if (comparison === "!=") return metric !== threshold;
  return false;
}

function getRelationshipMetric(record, option) {
  const aliases = DIAGNOSTIC_RELATIONSHIP_FIELD_ALIASES[option.collectionMetricField] ?? [];
  for (const field of aliases) {
    const value = toFiniteNumber(record?.[field]);
    if (Number.isFinite(value)) return value;
  }
  return undefined;
}

function metricMatchesOption(metric, option) {
  if (option.evaluatorId === "range") {
    const [lowerBound, upperBound] = option.threshold;
    return Number.isFinite(metric)
      && metric >= lowerBound
      && (option.rangeUpperInclusive ? metric <= upperBound : metric < upperBound);
  }
  return compareDiagnosticMetric(metric, option.comparison, option.threshold);
}

export function diagnosticRelationshipRecordMatches(record, optionValue) {
  const option = getDiagnosticOptionByValue(optionValue);
  if (!option || option.conditionKind !== "collection") return false;
  return metricMatchesOption(getRelationshipMetric(record, option), option);
}

function getScalarDiagnosticMetric(record, view, option) {
  const field = view === "topology" ? option.topoNodeField : option.tableRowField;
  if (!field) return undefined;
  const value = view === "topology" ? record?.[field] : getColumnValue(record, field);
  if (typeof value === "boolean") return undefined;
  const metric = toFiniteNumber(value);
  return Number.isFinite(metric) ? metric : undefined;
}

function getCompoundDiagnosticMetric(record, view, option) {
  if (view === "topology") return getScalarDiagnosticMetric(record, view, option);
  if (option.evaluatorId === "link-ratio") {
    const totalLinks = toFiniteNumber(getColumnValue(record, "totalLinks"));
    const linkField = option.value.startsWith("low-lq3-") ? "links3" : "links1";
    const links = toFiniteNumber(getColumnValue(record, linkField));
    return Number.isFinite(totalLinks) && totalLinks > 0 && Number.isFinite(links)
      ? links / totalLinks
      : undefined;
  }
  return getScalarDiagnosticMetric(record, view, option);
}

function isFtdRouterRecord(record, view) {
  if (view === "topology") return record?.isFtdRouter === true;
  const modeDevice = toText(getColumnValue(record, "mode.device")).toUpperCase();
  const rloc16 = toText(getColumnValue(record, "rloc16")).toLowerCase();
  return modeDevice === "FTD" && rloc16.length > 0 && rloc16.endsWith("00");
}

export function evaluateDiagnosticOption(record, view, option) {
  let metric;
  let matchedRecords = [];
  let triggered = false;

  if (option.conditionKind === "collection" && view === "table") {
    const rows = getColumnValue(record, option.collectionPath);
    const records = Array.isArray(rows) ? rows : [];
    const measured = records
      .map((item) => ({ item, metric: getRelationshipMetric(item, option) }))
      .filter(({ metric: value }) => Number.isFinite(value));
    matchedRecords = measured
      .filter(({ metric: value }) => metricMatchesOption(value, option))
      .map(({ item }) => item);
    const metrics = measured
      .filter(({ metric: value }) => metricMatchesOption(value, option))
      .map(({ metric: value }) => value);
    if (metrics.length > 0) {
      metric = option.aggregation === "min" ? Math.min(...metrics) : Math.max(...metrics);
    }
    triggered = matchedRecords.length > 0;
  } else {
    const summaryValue = view === "topology" ? record?.[option.topoNodeField] : undefined;
    metric = option.conditionKind === "compound"
      ? getCompoundDiagnosticMetric(record, view, option)
      : getScalarDiagnosticMetric(record, view, option);
    triggered = typeof summaryValue === "boolean"
      ? summaryValue
      : metricMatchesOption(metric, option);
    if (option.evaluatorId === "ftd-router" && !isFtdRouterRecord(record, view)) {
      triggered = false;
    }
  }

  return {
    option,
    metric,
    metricText: formatDiagnosticMetric(metric, option.unit),
    thresholdText: formatDiagnosticThreshold(option),
    triggered,
    matchedRecords,
  };
}

function formatDiagnosticMetric(value, unit) {
  if (!Number.isFinite(value)) return undefined;
  if (unit === "percent") return `${value.toFixed(1)}%`;
  if (unit === "ratio") return `${(value * 100).toFixed(1)}%`;
  if (unit === "dBm") return `${value} dBm`;
  if (unit === "dB") return `${value} dB`;
  if (unit === "linkQuality") return `LQ ${value}`;
  return String(value);
}

function formatDiagnosticThreshold(option) {
  if (option.evaluatorId === "range") {
    const [lowerBound, upperBound] = option.threshold;
    return `${lowerBound} to ${upperBound} ${option.unit}`;
  }
  const value = formatDiagnosticMetric(option.threshold, option.unit);
  const comparison = option.comparison === "==" ? "=" : option.comparison;
  return `${comparison} ${value}`;
}

const DIAGNOSTIC_SEVERITY_RANK = Object.freeze({
  info: 0,
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
});

export function selectHighestQualifyingDiagnosticEvaluations(evaluations) {
  const highestRankByGroup = new Map();
  evaluations.forEach((evaluation) => {
    if (!evaluation.triggered) return;
    const groupKey = `${evaluation.option.source}\u0000${evaluation.option.group}`;
    const rank = DIAGNOSTIC_SEVERITY_RANK[evaluation.option.severity] ?? -1;
    const highestRank = highestRankByGroup.get(groupKey) ?? -1;
    if (rank > highestRank) highestRankByGroup.set(groupKey, rank);
  });

  return evaluations.filter((evaluation) => {
    if (!evaluation.triggered) return true;
    const groupKey = `${evaluation.option.source}\u0000${evaluation.option.group}`;
    const rank = DIAGNOSTIC_SEVERITY_RANK[evaluation.option.severity] ?? -1;
    return rank === highestRankByGroup.get(groupKey);
  });
}

/**
 * Returns the diagnostic conditions that the supplied record can evaluate.
 */
export function evaluateDiagnosticsForRecord(record, view = "topology") {
  if (view !== "topology" && view !== "table") {
    throw new Error(`Unsupported diagnostic view: ${view}`);
  }
  if (!record) return [];

  return DIAGNOSTIC_FILTER_OPTIONS
    .filter((option) => option.value !== "all")
    .map((option) => evaluateDiagnosticOption(record, view, option))
    .map((evaluation) => Number.isFinite(evaluation.metric)
      || (evaluation.triggered && evaluation.option.conditionKind === "collection")
      ? evaluation
      : null)
    .filter(Boolean);
}

const THREAD_DEVICE_TYPES = new Set([
  "router",
  "border router",
  "child",
  "sleepy-child",
  "sleepy child",
]);

function getNetworkInsightIdentity(record, rowIndex) {
  const rloc16 = getCanonicalRloc16(record);
  if (rloc16) return `rloc16:${rloc16}`;
  const extAddress = getCanonicalExtaddr(record);
  if (extAddress) return `extAddress:${extAddress}`;
  const omrIpv6Address = getCanonicalOmrIpv6Address(record);
  if (omrIpv6Address) return `omrIpv6Address:${omrIpv6Address}`;
  const rowId = toText(record?.id) || toText(record?.recordKey);
  return rowId ? `row:${rowId.toLowerCase()}` : `row-index:${rowIndex}`;
}

function getNetworkInsightDisplayName(record, identity) {
  return toText(getColumnValue(record, "deviceLabel"))
    || toText(getColumnValue(record, "name"))
    || getCanonicalRloc16(record)
    || getCanonicalExtaddr(record)
    || getCanonicalOmrIpv6Address(record)
    || identity;
}

export function isEligibleThreadDiagnosticRecord(record) {
  if (!isPlainObject(record)) return false;
  if (getCanonicalRloc16(record) || record.br === true) return true;
  const type = toText(getColumnValue(record, "type")).toLowerCase();
  const role = toText(getColumnValue(record, "role")).toLowerCase();
  return THREAD_DEVICE_TYPES.has(type) || THREAD_DEVICE_TYPES.has(role);
}

/**
 * Aggregates table-view diagnostic evaluations for normalized Thread rows.
 * The returned model is independent of DOM and current dataset state.
 */
export function aggregateNetworkDiagnosticsForRows(rows) {
  const devicesByIdentity = new Map();
  (Array.isArray(rows) ? rows : []).forEach((record, rowIndex) => {
    if (!isEligibleThreadDiagnosticRecord(record)) return;
    const identity = getNetworkInsightIdentity(record, rowIndex);
    if (!devicesByIdentity.has(identity)) {
      devicesByIdentity.set(identity, {
        identity,
        displayName: getNetworkInsightDisplayName(record, identity),
        record,
      });
    }
  });

  const conditionsByValue = new Map();
  const evaluableDevices = new Set();
  devicesByIdentity.forEach((device) => {
    const evaluations = selectHighestQualifyingDiagnosticEvaluations(
      evaluateDiagnosticsForRecord(device.record, "table"),
    );
    if (evaluations.length > 0) evaluableDevices.add(device.identity);

    evaluations.forEach((evaluation) => {
      const { option, metric, triggered } = evaluation;
      let condition = conditionsByValue.get(option.value);
      if (!condition) {
        condition = {
          option,
          triggeredDevices: [],
          observedMetrics: [],
        };
        conditionsByValue.set(option.value, condition);
      }
      if (triggered) {
        condition.triggeredDevices.push({
          identity: device.identity,
          displayName: device.displayName,
        });
      }
      if (Number.isFinite(metric)) condition.observedMetrics.push(metric);
    });
  });

  const sourcesByName = new Map();
  DIAGNOSTIC_FILTER_OPTIONS
    .filter((option) => option.value !== "all")
    .forEach((option) => {
      const condition = conditionsByValue.get(option.value);
      if (!condition) return;
      let source = sourcesByName.get(option.source);
      if (!source) {
        source = { source: option.source, conditions: [] };
        sourcesByName.set(option.source, source);
      }
      const observedMetrics = condition.observedMetrics;
      source.conditions.push({
        option,
        triggeredDevices: [...condition.triggeredDevices].sort((left, right) =>
          left.identity.localeCompare(right.identity),
        ),
        triggeredDeviceCount: condition.triggeredDevices.length,
        observedDeviceCount: observedMetrics.length,
        nonTriggeredDeviceCount: observedMetrics.length - condition.triggeredDevices.length,
        minMetric: observedMetrics.length > 0 ? Math.min(...observedMetrics) : undefined,
        maxMetric: observedMetrics.length > 0 ? Math.max(...observedMetrics) : undefined,
        minMetricText: observedMetrics.length > 0
          ? formatDiagnosticMetric(Math.min(...observedMetrics), option.unit)
          : undefined,
        maxMetricText: observedMetrics.length > 0
          ? formatDiagnosticMetric(Math.max(...observedMetrics), option.unit)
          : undefined,
      });
    });

  return {
    eligibleDeviceCount: devicesByIdentity.size,
    evaluableDeviceCount: evaluableDevices.size,
    sources: [...sourcesByName.values()],
  };
}

export function isNodeVisibleByDiagnosticFilter(node, filterMode) {
  if (filterMode === "all") return true;
  const option = getDiagnosticOptionByValue(filterMode);
  if (!option) return true;
  const evaluation = evaluateDiagnosticsForRecord(node, "topology")
    .find((item) => item.option.value === filterMode);
  return evaluation?.triggered === true;
}

export function isRowVisibleByDiagnosticFilter(row, filterMode) {
  if (filterMode === "all") return true;
  const option = getDiagnosticOptionByValue(filterMode);
  if (!option) return true;
  const evaluation = evaluateDiagnosticsForRecord(row, "table")
    .find((item) => item.option.value === filterMode);
  return evaluation?.triggered === true;
}
