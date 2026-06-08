import {
  LINK_FILTER_DEFAULT,
  LINK_FILTER_DEFAULT_PLUS_NEIGHBORS,
  LINK_FILTER_OTBR_REST_API,
  LINK_FILTER_EVE_ENHANCED,
  LINK_FILTER_EVE_NATIVE,
  LINK_FILTER_ALL,
  LINK_FILTER_LQ_HIGH,
  LINK_FILTER_LQ_MEDIUM,
  LINK_FILTER_LQ_LOW,
  LINK_FILTER_PARENT_CHILD,
  LINK_FILTER_OTBR_NEIGHBOR,
  LINK_FILTER_LQ_NONE,
  EDGE_CATEGORY_DEFAULT_CHILDREN,
  EDGE_CATEGORY_DEFAULT_1,
  EDGE_CATEGORY_DEFAULT_2,
  EDGE_CATEGORY_DEFAULT_3,
  EDGE_CATEGORY_ROUTER_NEIGHBOR,
  EDGE_CATEGORY_OTBR_ROUTE,
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
  if (mode === LINK_FILTER_DEFAULT) {
    return hasAny(
      EDGE_CATEGORY_DEFAULT_CHILDREN,
      EDGE_CATEGORY_DEFAULT_1,
      EDGE_CATEGORY_DEFAULT_2,
      EDGE_CATEGORY_DEFAULT_3,
      EDGE_CATEGORY_OTBR_CHILD,
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
  if (mode === LINK_FILTER_OTBR_REST_API)
    return hasAny(EDGE_CATEGORY_OTBR_ROUTE, EDGE_CATEGORY_OTBR_CHILD);
  if (mode === LINK_FILTER_EVE_ENHANCED)
    return hasAny(EDGE_CATEGORY_EVE_ROUTE, EDGE_CATEGORY_EVE_CHILD);
  if (mode === LINK_FILTER_EVE_NATIVE)
    return hasAny(
      EDGE_CATEGORY_EVE_NATIVE_ROUTE,
      EDGE_CATEGORY_EVE_NATIVE_CHILD,
    );
  if (mode === LINK_FILTER_ALL) return true;
  if (mode === LINK_FILTER_LQ_HIGH) return (edge.lqLevel ?? 0) === 3;
  if (mode === LINK_FILTER_LQ_MEDIUM) return (edge.lqLevel ?? 0) === 2;
  if (mode === LINK_FILTER_LQ_LOW) return (edge.lqLevel ?? 0) === 1;
  if (mode === LINK_FILTER_PARENT_CHILD) return edge.isParentChild === true;
  if (mode === LINK_FILTER_OTBR_NEIGHBOR)
    return hasAny(
      EDGE_CATEGORY_OTBR_ROUTE,
      EDGE_CATEGORY_OTBR_CHILD,
      EDGE_CATEGORY_ROUTER_NEIGHBOR,
    );
  if (mode === LINK_FILTER_LQ_NONE) return !edge.lqLevel || edge.lqLevel === 0;
  return false;
}

// ── Dataset capabilities ──────────────────────────────────────────────────────
//
// Both functions return the same DatasetCapabilities shape:
//   {
//     hasFtdNodes, hasMtdNodes, hasRouters, hasBorderRouters,
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

// Called after runAdaptor() in renderTopologyForDataset.
// Scans vis-node objects and edge linkCategories.
export function computeTopologyCapabilities(nodeData, edgeData) {
  let hasFtdNodes = false;
  let hasMtdNodes = false;
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
    if (Number.isFinite(node.partitionidchanges))
      hasFieldPartitionChanges = true;
    if (Number.isFinite(node.parentchanges)) hasFieldParentChanges = true;
    if (Number.isFinite(node.router_neighbor_max_err_rate_frame_pct))
      hasNeighborFrameErrRate = true;
    if (Number.isFinite(node.router_neighbor_max_err_rate_msg_pct))
      hasNeighborMsgErrRate = true;
    if (
      Number.isFinite(node.router_neighbor_min_rss_ave) ||
      Number.isFinite(node.router_neighbor_max_rss_ave)
    )
      hasNeighborRss = true;
    if (Number.isFinite(node.lq3_ratio) || Number.isFinite(node.lq1_ratio))
      hasLinkQualityDistribution = true;
    if (node.has_child_lq_medium === true || node.has_child_lq_poor === true)
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
    if (Number.isFinite(node.iftotalerrors_totalpkts_ratio))
      hasFieldMacTotalErrorsRatio = true;
    if (Number.isFinite(node.iftotaldiscards_totalpkts_ratio))
      hasFieldMacTotalDiscardsRatio = true;
    if (Number.isFinite(node.betterpartitionattachattempts))
      hasFieldBetterPartitionAttach = true;
    if (Number.isFinite(node.totalparentpartitionchanges))
      hasFieldTotalParentPartitionChanges = true;
    if (Number.isFinite(node.router_pct))
      hasFieldRouterPct = true;
    if (Number.isFinite(node.detached_disabled_pct))
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
    if (
      isRouter &&
      (brValue === true || toText(brValue).toLowerCase() === "true")
    ) {
      hasBorderRouters = true;
    }

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

    const partChanges = getColumnValue(row, "mle_counters.partitionidchanges");
    if (Number.isFinite(toFiniteNumber(partChanges)))
      hasFieldPartitionChanges = true;

    const parentChanges = getColumnValue(row, "mle_counters.parentchanges");
    if (Number.isFinite(toFiniteNumber(parentChanges)))
      hasFieldParentChanges = true;

    const neighborRows = Array.isArray(
      getColumnValue(row, "router_neighbor_table"),
    )
      ? getColumnValue(row, "router_neighbor_table")
      : [];
    for (const neighbor of neighborRows) {
      if (Number.isFinite(toFiniteNumber(neighbor?.err_rate_frame_pct)))
        hasNeighborFrameErrRate = true;
      if (Number.isFinite(toFiniteNumber(neighbor?.err_rate_msg_pct)))
        hasNeighborMsgErrRate = true;
      if (Number.isFinite(toFiniteNumber(neighbor?.rss_ave)))
        hasNeighborRss = true;
    }

    if (
      Number.isFinite(toFiniteNumber(getColumnValue(row, "total_link_3"))) &&
      Number.isFinite(toFiniteNumber(getColumnValue(row, "total_links")))
    )
      hasLinkQualityDistribution = true;

    const childrenForLQ = Array.isArray(getColumnValue(row, "children"))
      ? getColumnValue(row, "children")
      : [];
    for (const child of childrenForLQ) {
      const lqRaw = child?.lq !== undefined ? child.lq : child?.link_quality;
      if (Number.isFinite(Number.parseInt(lqRaw, 10)))
        hasChildLinkQuality = true;
    }

    const childTableRows = Array.isArray(getColumnValue(row, "router_child_table"))
      ? getColumnValue(row, "router_child_table")
      : [];
    for (const child of childTableRows) {
      if (Number.isFinite(toFiniteNumber(child?.err_rate_frame_pct)))
        hasChildFrameErrRate = true;
      if (Number.isFinite(toFiniteNumber(child?.err_rate_msg_pct)))
        hasChildMsgErrRate = true;
      if (Number.isFinite(toFiniteNumber(child?.rss_ave)))
        hasChildRss = true;
      if (Number.isFinite(toFiniteNumber(child?.rss_margin)))
        hasChildRssMargin = true;
      const qMsg = toFiniteNumber(child?.q_msg);
      if (Number.isFinite(qMsg) && qMsg > 0)
        hasChildQueuedMsgs = true;
    }

    if (Number.isFinite(toFiniteNumber(getColumnValue(row, "mac_counters.iftotalerrors_totalpkts_ratio"))))
      hasFieldMacTotalErrorsRatio = true;
    if (Number.isFinite(toFiniteNumber(getColumnValue(row, "mac_counters.iftotaldiscards_totalpkts_ratio"))))
      hasFieldMacTotalDiscardsRatio = true;
    if (Number.isFinite(toFiniteNumber(getColumnValue(row, "mle_counters.betterpartitionattachattempts"))))
      hasFieldBetterPartitionAttach = true;
    if (Number.isFinite(toFiniteNumber(getColumnValue(row, "mle_counters.totalparentpartitionchanges"))))
      hasFieldTotalParentPartitionChanges = true;
    if (Number.isFinite(toFiniteNumber(getColumnValue(row, "time_statistics.router_pct"))))
      hasFieldRouterPct = true;
    if (Number.isFinite(toFiniteNumber(getColumnValue(row, "time_statistics.detached_disabled_pct"))))
      hasFieldDetachedDisabledPct = true;
  }

  return {
    hasFtdNodes,
    hasMtdNodes,
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

  // Build capability mapping for diagnostic filters (same as in updateFilterOptionVisibility)
  const diagCapabilityByValue = {
    "medium-partition-changes": capabilities?.hasFieldPartitionChanges,
    "high-partition-changes": capabilities?.hasFieldPartitionChanges,
    "medium-parent-changes": capabilities?.hasFieldParentChanges,
    "high-parent-changes": capabilities?.hasFieldParentChanges,
    "router-neighbor-err-rate-frame-low": capabilities?.hasNeighborFrameErrRate,
    "router-neighbor-err-rate-frame-medium": capabilities?.hasNeighborFrameErrRate,
    "router-neighbor-err-rate-frame-high": capabilities?.hasNeighborFrameErrRate,
    "router-neighbor-err-rate-frame-critical": capabilities?.hasNeighborFrameErrRate,
    "router-neighbor-err-rate-msg-low": capabilities?.hasNeighborMsgErrRate,
    "router-neighbor-err-rate-msg-medium": capabilities?.hasNeighborMsgErrRate,
    "router-neighbor-err-rate-msg-high": capabilities?.hasNeighborMsgErrRate,
    "router-neighbor-err-rate-msg-critical": capabilities?.hasNeighborMsgErrRate,
    "router-neighbor-rss-very-low": capabilities?.hasNeighborRss,
    "router-neighbor-rss-low": capabilities?.hasNeighborRss,
    "router-neighbor-rss-medium": capabilities?.hasNeighborRss,
    "router-neighbor-rss-high": capabilities?.hasNeighborRss,
    "low-lq3-ratio-medium": capabilities?.hasLinkQualityDistribution,
    "low-lq3-ratio-high": capabilities?.hasLinkQualityDistribution,
    "high-lq1-ratio-medium": capabilities?.hasLinkQualityDistribution,
    "high-lq1-ratio-high": capabilities?.hasLinkQualityDistribution,
    "child-lq-medium": capabilities?.hasChildLinkQuality,
    "child-lq-poor": capabilities?.hasChildLinkQuality,
    "router-child-err-rate-frame-medium": capabilities?.hasChildFrameErrRate,
    "router-child-err-rate-frame-high": capabilities?.hasChildFrameErrRate,
    "router-child-err-rate-msg-low": capabilities?.hasChildMsgErrRate,
    "router-child-err-rate-msg-high": capabilities?.hasChildMsgErrRate,
    "router-child-rss-very-low": capabilities?.hasChildRss,
    "router-child-rss-low": capabilities?.hasChildRss,
    "router-child-rss-margin-low": capabilities?.hasChildRssMargin,
    "router-child-has-queued-msgs": capabilities?.hasChildQueuedMsgs,
    "mac-total-errors-ratio-medium": capabilities?.hasFieldMacTotalErrorsRatio,
    "mac-total-errors-ratio-high": capabilities?.hasFieldMacTotalErrorsRatio,
    "mac-total-discards-ratio-medium": capabilities?.hasFieldMacTotalDiscardsRatio,
    "mac-total-discards-ratio-high": capabilities?.hasFieldMacTotalDiscardsRatio,
    "mle-better-partition-medium": capabilities?.hasFieldBetterPartitionAttach,
    "mle-better-partition-high": capabilities?.hasFieldBetterPartitionAttach,
    "mle-total-parent-partition-medium": capabilities?.hasFieldTotalParentPartitionChanges,
    "mle-total-parent-partition-high": capabilities?.hasFieldTotalParentPartitionChanges,
    "ftd-router-pct-low": capabilities?.hasFieldRouterPct,
    "ftd-router-pct-very-low": capabilities?.hasFieldRouterPct,
    "detached-disabled-pct-medium": capabilities?.hasFieldDetachedDisabledPct,
    "detached-disabled-pct-high": capabilities?.hasFieldDetachedDisabledPct,
  };

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
      if (diagCapabilityByValue[entry.value] !== true) return false;
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
  const diagCapabilityByValue = {
    "medium-partition-changes": capabilities.hasFieldPartitionChanges,
    "high-partition-changes": capabilities.hasFieldPartitionChanges,
    "medium-parent-changes": capabilities.hasFieldParentChanges,
    "high-parent-changes": capabilities.hasFieldParentChanges,
    "router-neighbor-err-rate-frame-low": capabilities.hasNeighborFrameErrRate,
    "router-neighbor-err-rate-frame-medium":
      capabilities.hasNeighborFrameErrRate,
    "router-neighbor-err-rate-frame-high": capabilities.hasNeighborFrameErrRate,
    "router-neighbor-err-rate-frame-critical": capabilities.hasNeighborFrameErrRate,
    "router-neighbor-err-rate-msg-low": capabilities.hasNeighborMsgErrRate,
    "router-neighbor-err-rate-msg-medium": capabilities.hasNeighborMsgErrRate,
    "router-neighbor-err-rate-msg-high": capabilities.hasNeighborMsgErrRate,
    "router-neighbor-err-rate-msg-critical": capabilities.hasNeighborMsgErrRate,
    "router-neighbor-rss-very-low": capabilities.hasNeighborRss,
    "router-neighbor-rss-low": capabilities.hasNeighborRss,
    "router-neighbor-rss-medium": capabilities.hasNeighborRss,
    "router-neighbor-rss-high": capabilities.hasNeighborRss,
    "low-lq3-ratio-medium": capabilities.hasLinkQualityDistribution,
    "low-lq3-ratio-high": capabilities.hasLinkQualityDistribution,
    "high-lq1-ratio-medium": capabilities.hasLinkQualityDistribution,
    "high-lq1-ratio-high": capabilities.hasLinkQualityDistribution,
    "child-lq-medium": capabilities.hasChildLinkQuality,
    "child-lq-poor": capabilities.hasChildLinkQuality,
    "router-child-err-rate-frame-medium": capabilities.hasChildFrameErrRate,
    "router-child-err-rate-frame-high": capabilities.hasChildFrameErrRate,
    "router-child-err-rate-msg-low": capabilities.hasChildMsgErrRate,
    "router-child-err-rate-msg-high": capabilities.hasChildMsgErrRate,
    "router-child-rss-very-low": capabilities.hasChildRss,
    "router-child-rss-low": capabilities.hasChildRss,
    "router-child-rss-margin-low": capabilities.hasChildRssMargin,
    "router-child-has-queued-msgs": capabilities.hasChildQueuedMsgs,
    "mac-total-errors-ratio-medium": capabilities.hasFieldMacTotalErrorsRatio,
    "mac-total-errors-ratio-high": capabilities.hasFieldMacTotalErrorsRatio,
    "mac-total-discards-ratio-medium": capabilities.hasFieldMacTotalDiscardsRatio,
    "mac-total-discards-ratio-high": capabilities.hasFieldMacTotalDiscardsRatio,
    "mle-better-partition-medium": capabilities.hasFieldBetterPartitionAttach,
    "mle-better-partition-high": capabilities.hasFieldBetterPartitionAttach,
    "mle-total-parent-partition-medium": capabilities.hasFieldTotalParentPartitionChanges,
    "mle-total-parent-partition-high": capabilities.hasFieldTotalParentPartitionChanges,
    "ftd-router-pct-low": capabilities.hasFieldRouterPct,
    "ftd-router-pct-very-low": capabilities.hasFieldRouterPct,
    "detached-disabled-pct-medium": capabilities.hasFieldDetachedDisabledPct,
    "detached-disabled-pct-high": capabilities.hasFieldDetachedDisabledPct,
  };

  const diagFilterEl = document.getElementById("diagnostic-filter");
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
    diagFilterEl.value = "all";
  }
}

// ── Node visibility predicates (topology) ─────────────────────────────────────

export function isNodeVisibleByFilter(node, filterMode) {
  if (filterMode === "ftd-devices")
    return toText(node.mode_device).toUpperCase() === "FTD";
  if (filterMode === "mtd-devices")
    return toText(node.mode_device).toUpperCase() === "MTD";
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

function getNodeDiagnosticMetric(node, filterMode) {
  const option = getDiagnosticOptionByValue(filterMode);
  if (!option?.topoNodeField) return undefined;
  return toFiniteNumber(node?.[option.topoNodeField]);
}

function getRowDiagnosticMetric(row, filterMode) {
  const option = getDiagnosticOptionByValue(filterMode);
  if (!option?.tableRowField) return undefined;
  return toFiniteNumber(getColumnValue(row, option.tableRowField));
}

export function isNodeVisibleByDiagnosticFilter(node, filterMode) {
  if (filterMode === "medium-partition-changes")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 2;
  if (filterMode === "high-partition-changes")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 5;
  if (filterMode === "medium-parent-changes")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 2;
  if (filterMode === "high-parent-changes")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 5;
  if (filterMode === "router-neighbor-err-rate-frame-low")
    return (
      Number.isFinite(node.router_neighbor_max_err_rate_frame_pct) &&
      node.router_neighbor_max_err_rate_frame_pct >= 2
    );
  if (filterMode === "router-neighbor-err-rate-frame-medium")
    return (
      Number.isFinite(node.router_neighbor_max_err_rate_frame_pct) &&
      node.router_neighbor_max_err_rate_frame_pct >= 5
    );
  if (filterMode === "router-neighbor-err-rate-frame-high")
    return (
      Number.isFinite(node.router_neighbor_max_err_rate_frame_pct) &&
      node.router_neighbor_max_err_rate_frame_pct >= 10
    );
  if (filterMode === "router-neighbor-err-rate-frame-critical")
    return (
      Number.isFinite(node.router_neighbor_max_err_rate_frame_pct) &&
      node.router_neighbor_max_err_rate_frame_pct >= 30
    );
  if (filterMode === "router-neighbor-err-rate-msg-low")
    return (
      Number.isFinite(node.router_neighbor_max_err_rate_msg_pct) &&
      node.router_neighbor_max_err_rate_msg_pct >= 2
    );
  if (filterMode === "router-neighbor-err-rate-msg-medium")
    return (
      Number.isFinite(node.router_neighbor_max_err_rate_msg_pct) &&
      node.router_neighbor_max_err_rate_msg_pct >= 5
    );
  if (filterMode === "router-neighbor-err-rate-msg-high")
    return (
      Number.isFinite(node.router_neighbor_max_err_rate_msg_pct) &&
      node.router_neighbor_max_err_rate_msg_pct >= 10
    );
  if (filterMode === "router-neighbor-err-rate-msg-critical")
    return (
      Number.isFinite(node.router_neighbor_max_err_rate_msg_pct) &&
      node.router_neighbor_max_err_rate_msg_pct >= 30
    );
  if (filterMode === "router-neighbor-rss-very-low")
    return node.router_neighbor_has_rss_very_low === true;
  if (filterMode === "router-neighbor-rss-low")
    return node.router_neighbor_has_rss_low === true;
  if (filterMode === "router-neighbor-rss-medium")
    return node.router_neighbor_has_rss_medium === true;
  if (filterMode === "router-neighbor-rss-high")
    return node.router_neighbor_has_rss_high === true;
  // Router link quality distribution
  if (filterMode === "low-lq3-ratio-medium")
    return Number.isFinite(node.lq3_ratio) && node.lq3_ratio < 0.60;
  if (filterMode === "low-lq3-ratio-high")
    return Number.isFinite(node.lq3_ratio) && node.lq3_ratio < 0.35;
  if (filterMode === "high-lq1-ratio-medium")
    return Number.isFinite(node.lq1_ratio) && node.lq1_ratio >= 0.20;
  if (filterMode === "high-lq1-ratio-high")
    return Number.isFinite(node.lq1_ratio) && node.lq1_ratio >= 0.35;
  // Children link quality
  if (filterMode === "child-lq-medium") return node.has_child_lq_medium === true;
  if (filterMode === "child-lq-poor")   return node.has_child_lq_poor === true;
  // Router child err rate frame
  if (filterMode === "router-child-err-rate-frame-medium")
    return (
      Number.isFinite(node.router_child_max_err_rate_frame_pct) &&
      node.router_child_max_err_rate_frame_pct >= 10
    );
  if (filterMode === "router-child-err-rate-frame-high")
    return (
      Number.isFinite(node.router_child_max_err_rate_frame_pct) &&
      node.router_child_max_err_rate_frame_pct >= 25
    );
  // Router child err rate msg
  if (filterMode === "router-child-err-rate-msg-low")
    return (
      Number.isFinite(node.router_child_max_err_rate_msg_pct) &&
      node.router_child_max_err_rate_msg_pct >= 1
    );
  if (filterMode === "router-child-err-rate-msg-high")
    return (
      Number.isFinite(node.router_child_max_err_rate_msg_pct) &&
      node.router_child_max_err_rate_msg_pct >= 5
    );
  // Router child RSS / margin / queued msgs
  if (filterMode === "router-child-rss-very-low")
    return node.router_child_has_rss_very_low === true;
  if (filterMode === "router-child-rss-low")
    return node.router_child_has_rss_low === true;
  if (filterMode === "router-child-rss-margin-low")
    return node.router_child_has_rss_margin_low === true;
  if (filterMode === "router-child-has-queued-msgs")
    return node.router_child_has_queued_msgs === true;
  // Mac total errors ratio
  if (filterMode === "mac-total-errors-ratio-medium")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 1.0;
  if (filterMode === "mac-total-errors-ratio-high")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 5.0;
  // Mac total discards ratio
  if (filterMode === "mac-total-discards-ratio-medium")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 2.0;
  if (filterMode === "mac-total-discards-ratio-high")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 8.0;
  // MLE extended counters
  if (filterMode === "mle-better-partition-medium")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 2;
  if (filterMode === "mle-better-partition-high")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 5;
  if (filterMode === "mle-total-parent-partition-medium")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 3;
  if (filterMode === "mle-total-parent-partition-high")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 8;
  // Time statistics
  if (filterMode === "ftd-router-pct-low")
    return (
      node.is_ftd_router === true &&
      Number.isFinite(node.router_pct) && node.router_pct < 80
    );
  if (filterMode === "ftd-router-pct-very-low")
    return (
      node.is_ftd_router === true &&
      Number.isFinite(node.router_pct) && node.router_pct < 50
    );
  if (filterMode === "detached-disabled-pct-medium")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 1.0;
  if (filterMode === "detached-disabled-pct-high")
    return Number.isFinite(getNodeDiagnosticMetric(node, filterMode)) &&
      getNodeDiagnosticMetric(node, filterMode) >= 5.0;
  return true;
}

// ── Router-neighbor diagnostic mode helpers ───────────────────────────────────

export function isRouterNeighborDiagnosticMode(mode) {
  return (
    mode === "router-neighbor-err-rate-frame-low" ||
    mode === "router-neighbor-err-rate-frame-medium" ||
    mode === "router-neighbor-err-rate-frame-high" ||
    mode === "router-neighbor-err-rate-frame-critical" ||
    mode === "router-neighbor-err-rate-msg-low" ||
    mode === "router-neighbor-err-rate-msg-medium" ||
    mode === "router-neighbor-err-rate-msg-high" ||
    mode === "router-neighbor-err-rate-msg-critical" ||
    mode === "router-neighbor-rss-very-low" ||
    mode === "router-neighbor-rss-low" ||
    mode === "router-neighbor-rss-medium" ||
    mode === "router-neighbor-rss-high"
  );
}

export function routerNeighborRowMatchesDiagnosticFilter(row, mode) {
  const fp = toFiniteNumber(row?.err_rate_frame_pct);
  const mp = toFiniteNumber(row?.err_rate_msg_pct);
  const rss = toFiniteNumber(row?.rss_ave);
  if (mode === "router-neighbor-err-rate-frame-low")
    return Number.isFinite(fp) && fp >= 2;
  if (mode === "router-neighbor-err-rate-frame-medium")
    return Number.isFinite(fp) && fp >= 5;
  if (mode === "router-neighbor-err-rate-frame-high")
    return Number.isFinite(fp) && fp >= 10;
  if (mode === "router-neighbor-err-rate-frame-critical")
    return Number.isFinite(fp) && fp >= 30;
  if (mode === "router-neighbor-err-rate-msg-low")
    return Number.isFinite(mp) && mp >= 2;
  if (mode === "router-neighbor-err-rate-msg-medium")
    return Number.isFinite(mp) && mp >= 5;
  if (mode === "router-neighbor-err-rate-msg-high")
    return Number.isFinite(mp) && mp >= 10;
  if (mode === "router-neighbor-err-rate-msg-critical")
    return Number.isFinite(mp) && mp >= 30;
  if (mode === "router-neighbor-rss-very-low")
    return Number.isFinite(rss) && rss < -80;
  if (mode === "router-neighbor-rss-low")
    return Number.isFinite(rss) && rss >= -80 && rss < -70;
  if (mode === "router-neighbor-rss-medium")
    return Number.isFinite(rss) && rss >= -70 && rss <= -60;
  if (mode === "router-neighbor-rss-high")
    return Number.isFinite(rss) && rss > -60;
  return false;
}

// ── Router-child diagnostic mode helpers ───────────────────────────────────────

export function isRouterChildDiagnosticMode(mode) {
  return (
    mode === "router-child-err-rate-frame-medium" ||
    mode === "router-child-err-rate-frame-high" ||
    mode === "router-child-err-rate-msg-low" ||
    mode === "router-child-err-rate-msg-high" ||
    mode === "router-child-rss-very-low" ||
    mode === "router-child-rss-low" ||
    mode === "router-child-rss-margin-low" ||
    mode === "router-child-has-queued-msgs"
  );
}

export function routerChildRowMatchesDiagnosticFilter(row, mode) {
  const fp = toFiniteNumber(row?.err_rate_frame_pct);
  const mp = toFiniteNumber(row?.err_rate_msg_pct);
  const rss = toFiniteNumber(row?.rss_ave);
  const rssMargin = toFiniteNumber(row?.rss_margin);
  const qMsg = toFiniteNumber(row?.q_msg);
  if (mode === "router-child-err-rate-frame-medium")
    return Number.isFinite(fp) && fp >= 10;
  if (mode === "router-child-err-rate-frame-high")
    return Number.isFinite(fp) && fp >= 25;
  if (mode === "router-child-err-rate-msg-low")
    return Number.isFinite(mp) && mp >= 1;
  if (mode === "router-child-err-rate-msg-high")
    return Number.isFinite(mp) && mp >= 5;
  if (mode === "router-child-rss-very-low")
    return Number.isFinite(rss) && rss < -80;
  if (mode === "router-child-rss-low")
    return Number.isFinite(rss) && rss >= -80 && rss < -70;
  if (mode === "router-child-rss-margin-low")
    return Number.isFinite(rssMargin) && rssMargin < 20;
  if (mode === "router-child-has-queued-msgs")
    return Number.isFinite(qMsg) && qMsg > 0;
  return false;
}

// ── Row visibility predicates (table) ─────────────────────────────────────────

export function isRowVisibleByNodeFilter(row, filterMode) {
  if (filterMode === "all") return true;
  const modeDevice = toText(getColumnValue(row, "mode.device")).toUpperCase();
  const rloc16Text = toText(getColumnValue(row, "rloc16")).toLowerCase();
  const isRouter = rloc16Text.endsWith("00");
  const brValue = getColumnValue(row, "br");
  const isBorderRouter =
    isRouter &&
    (brValue === true || toText(brValue).toLowerCase() === "true");
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
  if (filterMode === "main-routers") return isRouter;
  if (filterMode === "border-routers") return isBorderRouter;
  if (filterMode === "routers-with-children") return isRouter && hasChildren;
  if (filterMode === "routers-without-children")
    return isRouter && !hasChildren;
  return true;
}

export function isRowVisibleByDiagnosticFilter(row, filterMode) {
  if (filterMode === "all") return true;
  const getMetric = () => getRowDiagnosticMetric(row, filterMode);
  if (filterMode === "medium-partition-changes") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 2;
  }
  if (filterMode === "high-partition-changes") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 5;
  }
  if (filterMode === "medium-parent-changes") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 2;
  }
  if (filterMode === "high-parent-changes") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 5;
  }

  const neighborRows = Array.isArray(
    getColumnValue(row, "router_neighbor_table"),
  )
    ? getColumnValue(row, "router_neighbor_table")
    : [];
  const hasMatchingNeighbor = (pred) => neighborRows.some(pred);

  if (filterMode === "router-neighbor-err-rate-frame-low")
    return hasMatchingNeighbor((n) => {
      const v = toFiniteNumber(n?.err_rate_frame_pct);
      return Number.isFinite(v) && v >= 2;
    });
  if (filterMode === "router-neighbor-err-rate-frame-medium")
    return hasMatchingNeighbor((n) => {
      const v = toFiniteNumber(n?.err_rate_frame_pct);
      return Number.isFinite(v) && v >= 5;
    });
  if (filterMode === "router-neighbor-err-rate-frame-high")
    return hasMatchingNeighbor((n) => {
      const v = toFiniteNumber(n?.err_rate_frame_pct);
      return Number.isFinite(v) && v >= 10;
    });
  if (filterMode === "router-neighbor-err-rate-frame-critical")
    return hasMatchingNeighbor((n) => {
      const v = toFiniteNumber(n?.err_rate_frame_pct);
      return Number.isFinite(v) && v >= 30;
    });
  if (filterMode === "router-neighbor-err-rate-msg-low")
    return hasMatchingNeighbor((n) => {
      const v = toFiniteNumber(n?.err_rate_msg_pct);
      return Number.isFinite(v) && v >= 2;
    });
  if (filterMode === "router-neighbor-err-rate-msg-medium")
    return hasMatchingNeighbor((n) => {
      const v = toFiniteNumber(n?.err_rate_msg_pct);
      return Number.isFinite(v) && v >= 5;
    });
  if (filterMode === "router-neighbor-err-rate-msg-high")
    return hasMatchingNeighbor((n) => {
      const v = toFiniteNumber(n?.err_rate_msg_pct);
      return Number.isFinite(v) && v >= 10;
    });
  if (filterMode === "router-neighbor-err-rate-msg-critical")
    return hasMatchingNeighbor((n) => {
      const v = toFiniteNumber(n?.err_rate_msg_pct);
      return Number.isFinite(v) && v >= 30;
    });
  if (filterMode === "router-neighbor-rss-very-low")
    return hasMatchingNeighbor((n) => {
      const v = toFiniteNumber(n?.rss_ave);
      return Number.isFinite(v) && v < -80;
    });
  if (filterMode === "router-neighbor-rss-low")
    return hasMatchingNeighbor((n) => {
      const v = toFiniteNumber(n?.rss_ave);
      return Number.isFinite(v) && v >= -80 && v < -70;
    });
  if (filterMode === "router-neighbor-rss-medium")
    return hasMatchingNeighbor((n) => {
      const v = toFiniteNumber(n?.rss_ave);
      return Number.isFinite(v) && v >= -70 && v <= -60;
    });
  if (filterMode === "router-neighbor-rss-high")
    return hasMatchingNeighbor((n) => {
      const v = toFiniteNumber(n?.rss_ave);
      return Number.isFinite(v) && v > -60;
    });

  // Router link quality distribution
  if (filterMode === "low-lq3-ratio-medium" || filterMode === "low-lq3-ratio-high" ||
      filterMode === "high-lq1-ratio-medium" || filterMode === "high-lq1-ratio-high") {
    const tl3 = toFiniteNumber(getColumnValue(row, "total_link_3"));
    const tl1 = toFiniteNumber(getColumnValue(row, "total_link_1"));
    const tl = toFiniteNumber(getColumnValue(row, "total_links"));
    if (!Number.isFinite(tl) || tl <= 0) return false;
    const lq3r = Number.isFinite(tl3) ? tl3 / tl : undefined;
    const lq1r = Number.isFinite(tl1) ? tl1 / tl : undefined;
    if (filterMode === "low-lq3-ratio-medium")  return Number.isFinite(lq3r) && lq3r < 0.60;
    if (filterMode === "low-lq3-ratio-high")    return Number.isFinite(lq3r) && lq3r < 0.35;
    if (filterMode === "high-lq1-ratio-medium") return Number.isFinite(lq1r) && lq1r >= 0.20;
    if (filterMode === "high-lq1-ratio-high")   return Number.isFinite(lq1r) && lq1r >= 0.35;
  }

  // Children link quality
  if (filterMode === "child-lq-medium" || filterMode === "child-lq-poor") {
    const childrenForLQ = Array.isArray(getColumnValue(row, "children"))
      ? getColumnValue(row, "children")
      : [];
    for (const child of childrenForLQ) {
      const lqRaw = child?.lq !== undefined ? child.lq : child?.link_quality;
      const lqNum = Number.parseInt(lqRaw, 10);
      if (!Number.isFinite(lqNum)) continue;
      if (filterMode === "child-lq-medium" && lqNum <= 2) return true;
      if (filterMode === "child-lq-poor"   && lqNum === 1) return true;
    }
    return false;
  }

  // Router child table filters
  const childTableRows = Array.isArray(getColumnValue(row, "router_child_table"))
    ? getColumnValue(row, "router_child_table")
    : [];
  const hasMatchingChild = (pred) => childTableRows.some(pred);

  if (filterMode === "router-child-err-rate-frame-medium")
    return hasMatchingChild((c) => {
      const v = toFiniteNumber(c?.err_rate_frame_pct);
      return Number.isFinite(v) && v >= 10;
    });
  if (filterMode === "router-child-err-rate-frame-high")
    return hasMatchingChild((c) => {
      const v = toFiniteNumber(c?.err_rate_frame_pct);
      return Number.isFinite(v) && v >= 25;
    });
  if (filterMode === "router-child-err-rate-msg-low")
    return hasMatchingChild((c) => {
      const v = toFiniteNumber(c?.err_rate_msg_pct);
      return Number.isFinite(v) && v >= 1;
    });
  if (filterMode === "router-child-err-rate-msg-high")
    return hasMatchingChild((c) => {
      const v = toFiniteNumber(c?.err_rate_msg_pct);
      return Number.isFinite(v) && v >= 5;
    });
  if (filterMode === "router-child-rss-very-low")
    return hasMatchingChild((c) => {
      const v = toFiniteNumber(c?.rss_ave);
      return Number.isFinite(v) && v < -80;
    });
  if (filterMode === "router-child-rss-low")
    return hasMatchingChild((c) => {
      const v = toFiniteNumber(c?.rss_ave);
      return Number.isFinite(v) && v >= -80 && v < -70;
    });
  if (filterMode === "router-child-rss-margin-low")
    return hasMatchingChild((c) => {
      const v = toFiniteNumber(c?.rss_margin);
      return Number.isFinite(v) && v < 20;
    });
  if (filterMode === "router-child-has-queued-msgs")
    return hasMatchingChild((c) => {
      const v = toFiniteNumber(c?.q_msg);
      return Number.isFinite(v) && v > 0;
    });

  // Mac total errors / discards ratio
  if (filterMode === "mac-total-errors-ratio-medium") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 1.0;
  }
  if (filterMode === "mac-total-errors-ratio-high") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 5.0;
  }
  if (filterMode === "mac-total-discards-ratio-medium") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 2.0;
  }
  if (filterMode === "mac-total-discards-ratio-high") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 8.0;
  }

  // MLE extended counters
  if (filterMode === "mle-better-partition-medium") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 2;
  }
  if (filterMode === "mle-better-partition-high") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 5;
  }
  if (filterMode === "mle-total-parent-partition-medium") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 3;
  }
  if (filterMode === "mle-total-parent-partition-high") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 8;
  }

  // Time statistics
  if (filterMode === "ftd-router-pct-low" || filterMode === "ftd-router-pct-very-low") {
    const modeDevice = toText(getColumnValue(row, "mode.device")).toUpperCase();
    const rloc16Text = toText(getColumnValue(row, "rloc16")).toLowerCase();
    const isFtdRouter = modeDevice === "FTD" && rloc16Text.length > 0 && rloc16Text.endsWith("00");
    if (!isFtdRouter) return false;
    const v = getMetric();
    if (!Number.isFinite(v)) return false;
    if (filterMode === "ftd-router-pct-low")      return v < 80;
    if (filterMode === "ftd-router-pct-very-low") return v < 50;
  }
  if (filterMode === "detached-disabled-pct-medium") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 1.0;
  }
  if (filterMode === "detached-disabled-pct-high") {
    const v = getMetric();
    return Number.isFinite(v) && v >= 5.0;
  }

  return true;
}
