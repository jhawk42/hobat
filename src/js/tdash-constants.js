// ── Merge strategy identifiers ────────────────────────────────────────────────

export const MERGE_STRATEGIES = Object.freeze({
  none: "none",
  byRloc16: "by-rloc16",
  byIdentity: "by-identity",
});

export const MERGE_IDENTITY_FIELDS = Object.freeze({
  rloc16: "rloc16",
  extaddrAliases: ["extaddr", "extAddress", "Extended MAC"],
  omrIpv6Address: "omrIpv6Address",
});

// ── Link filter constants ─────────────────────────────────────────────────────

export const LINK_FILTER_DEFAULT = "default_links";
export const LINK_FILTER_DEFAULT_PLUS_NEIGHBORS =
  "default_plus_router_neighbors";
export const LINK_FILTER_OTBR_REST_API = "otbr_rest_api";
export const LINK_FILTER_EVE_ENHANCED = "eve_enhanced_routes_children";
export const LINK_FILTER_EVE_NATIVE = "eve_native_routes_children";
export const LINK_FILTER_ALL = "all_links";
export const LINK_FILTER_LQ_HIGH = "lq_high";
export const LINK_FILTER_LQ_MEDIUM = "lq_medium";
export const LINK_FILTER_LQ_LOW = "lq_low";
export const LINK_FILTER_PARENT_CHILD = "lq_parent_child";
export const LINK_FILTER_OTBR_NEIGHBOR = "lq_otbr_neighbor";
export const LINK_FILTER_LQ_NONE = "lq_none";

// ── Edge category constants ───────────────────────────────────────────────────

export const EDGE_CATEGORY_DEFAULT_CHILDREN = "default_children";
export const EDGE_CATEGORY_DEFAULT_1 = "default_1_links";
export const EDGE_CATEGORY_DEFAULT_2 = "default_2_links";
export const EDGE_CATEGORY_DEFAULT_3 = "default_3_links";
export const EDGE_CATEGORY_ROUTER_NEIGHBOR = "router_neighbor";
export const EDGE_CATEGORY_OTBR_ROUTE = "otbr_route";
export const EDGE_CATEGORY_OTBR_CHILD = "otbr_child";
export const EDGE_CATEGORY_EVE_ROUTE = "eve_route";
export const EDGE_CATEGORY_EVE_CHILD = "eve_child";
export const EDGE_CATEGORY_EVE_NATIVE_ROUTE = "eve_native_route";
export const EDGE_CATEGORY_EVE_NATIVE_CHILD = "eve_native_child";

// ── Link Quality edge style constants ─────────────────────────────────────────
export const EDGE_LQ_STYLES = Object.freeze({
  high: { width: 8, color: "#0072B2", dashes: false, lqLevel: 3 }, // LQ3 bold blue  (.lq-high)
  medium: { width: 6, color: "#56B4E9", dashes: false, lqLevel: 2 }, // LQ2 light blue (.lq-medium)
  low: { width: 4, color: "#c62828", dashes: true, lqLevel: 1 }, // LQ1 red dashed (.lq-low)
  none: { width: 4, color: "#8a8a8a", dashes: false, lqLevel: 0 }, // fallback (no LQ data)
  parentChild: { width: 8, color: "#CC79A7", dashes: false, lqLevel: 0 }, // parent–child pink/mauve (.lq-parent-child)
  noLqPurple: { width: 4, color: "#009E73", dashes: false, lqLevel: 0 }, // OTBR / router-neighbor green (.lq-otbr)
});

// ── Filter option metadata registries ────────────────────────────────────────
//
// Each registry is the single source of truth mapping a dropdown <option>
// value to the data fields / edge categories that must be present in the
// active dataset for that option to be meaningful.
//
// Fields:
//   value          — must match the <option value="..."> in the HTML
//   alwaysShow     — when true the option is never hidden regardless of data
//
// NODE_FILTER_OPTIONS
//   topoNodeField  — vis-node property name (topology view)
//   topoNodeValue  — expected value to test for (undefined → truthy-check)
//   tableRowField  — dot-path into the normalised row (table view)
//   tableRowValue  — expected value to test for (undefined → any non-empty)
//
// LINK_FILTER_OPTIONS  (topology-only; always hidden in table view)
//   requiredEdgeCategories — at least one edge must carry one of these
//
// DIAGNOSTIC_FILTER_OPTIONS
//   topoNodeField  — vis-node property name (topology view)
//   tableRowField  — dot-path into the normalised row (table view)
//   tableNeighborField — field inside router_neighbor_table[] rows
//                        (used instead of tableRowField when set)

export const NODE_FILTER_OPTIONS = Object.freeze([
  { value: "all", alwaysShow: true },
  {
    value: "ftd-devices",
    topoNodeField: "mode_device",
    topoNodeValue: "FTD",
    tableRowField: "mode.device",
    tableRowValue: "FTD",
  },
  {
    value: "mtd-devices",
    topoNodeField: "mode_device",
    topoNodeValue: "MTD",
    tableRowField: "mode.device",
    tableRowValue: "MTD",
  },
  {
    value: "main-routers",
    topoNodeField: "isMainRouter",
    tableRowField: "rloc16", // rloc16 ending in '00' → main router
  },
  {
    value: "border-routers",
    topoNodeField: "isBorderRouter",
    tableRowField: "br",
  },
  {
    value: "routers-with-children",
    topoNodeField: "isRouter", // isRouter && hasChildren
    tableRowField: "total_children", // > 0, or children[] length > 0
  },
  {
    value: "routers-without-children",
    topoNodeField: "isRouter", // isRouter && !hasChildren
    tableRowField: "rloc16", // router-shaped, checked by predicate
  },
]);

export const LINK_FILTER_OPTIONS = Object.freeze([
  { value: LINK_FILTER_ALL, alwaysShow: true },
  {
    value: LINK_FILTER_DEFAULT,
    requiredEdgeCategories: [
      EDGE_CATEGORY_DEFAULT_CHILDREN,
      EDGE_CATEGORY_DEFAULT_1,
      EDGE_CATEGORY_DEFAULT_2,
      EDGE_CATEGORY_DEFAULT_3,
      EDGE_CATEGORY_OTBR_CHILD,
    ],
  },
  {
    value: LINK_FILTER_DEFAULT_PLUS_NEIGHBORS,
    requiredEdgeCategories: [
      EDGE_CATEGORY_DEFAULT_CHILDREN,
      EDGE_CATEGORY_DEFAULT_1,
      EDGE_CATEGORY_DEFAULT_2,
      EDGE_CATEGORY_DEFAULT_3,
      EDGE_CATEGORY_OTBR_CHILD,
      EDGE_CATEGORY_ROUTER_NEIGHBOR,
    ],
  },
  {
    value: LINK_FILTER_OTBR_REST_API,
    requiredEdgeCategories: [
      EDGE_CATEGORY_OTBR_ROUTE,
      EDGE_CATEGORY_OTBR_CHILD,
    ],
  },
  {
    value: LINK_FILTER_EVE_ENHANCED,
    requiredEdgeCategories: [EDGE_CATEGORY_EVE_ROUTE, EDGE_CATEGORY_EVE_CHILD],
  },
  {
    value: LINK_FILTER_EVE_NATIVE,
    requiredEdgeCategories: [
      EDGE_CATEGORY_EVE_NATIVE_ROUTE,
      EDGE_CATEGORY_EVE_NATIVE_CHILD,
    ],
  },
  // ── Link Quality filters ──────────────────────────────────────────────
  {
    value: LINK_FILTER_LQ_HIGH,
    requiredEdgeCategories: [
      EDGE_CATEGORY_DEFAULT_3,
      EDGE_CATEGORY_EVE_ROUTE,
      EDGE_CATEGORY_EVE_NATIVE_ROUTE,
    ],
  },
  {
    value: LINK_FILTER_LQ_MEDIUM,
    requiredEdgeCategories: [
      EDGE_CATEGORY_DEFAULT_2,
      EDGE_CATEGORY_EVE_ROUTE,
      EDGE_CATEGORY_EVE_NATIVE_ROUTE,
    ],
  },
  {
    value: LINK_FILTER_LQ_LOW,
    requiredEdgeCategories: [
      EDGE_CATEGORY_DEFAULT_1,
      EDGE_CATEGORY_EVE_ROUTE,
      EDGE_CATEGORY_EVE_NATIVE_ROUTE,
    ],
  },
  {
    value: LINK_FILTER_PARENT_CHILD,
    requiredEdgeCategories: [
      EDGE_CATEGORY_DEFAULT_CHILDREN,
      EDGE_CATEGORY_EVE_CHILD,
      EDGE_CATEGORY_EVE_NATIVE_CHILD,
      EDGE_CATEGORY_OTBR_CHILD,
    ],
  },
  {
    value: LINK_FILTER_OTBR_NEIGHBOR,
    requiredEdgeCategories: [
      EDGE_CATEGORY_OTBR_ROUTE,
      EDGE_CATEGORY_ROUTER_NEIGHBOR,
    ],
  },
  { value: LINK_FILTER_LQ_NONE, alwaysShow: true },
]);

export const DIAGNOSTIC_FILTER_OPTIONS = Object.freeze([
  { value: "all", alwaysShow: true },
  // ── Mac counters ──────────────────────────────────────────────────────
  {
    value: "medium-total-errors-pct",
    topoNodeField: "ifinerrors_pct",
    tableRowField: "mac_counters.ifinerrors_pct",
  },
  {
    value: "medium-total-errors-high",
    topoNodeField: "ifinerrors_pct",
    tableRowField: "mac_counters.ifinerrors_pct",
  },
  {
    value: "medium-discard-pct",
    topoNodeField: "ifindiscards_pct",
    tableRowField: "mac_counters.ifindiscards_pct",
  },
  // ── Mle counters ──────────────────────────────────────────────────────
  {
    value: "medium-partition-changes",
    topoNodeField: "partitionidchanges",
    tableRowField: "mle_counters.partitionidchanges",
  },
  {
    value: "high-partition-changes",
    topoNodeField: "partitionidchanges",
    tableRowField: "mle_counters.partitionidchanges",
  },
  {
    value: "medium-parent-changes",
    topoNodeField: "parentchanges",
    tableRowField: "mle_counters.parentchanges",
  },
  {
    value: "high-parent-changes",
    topoNodeField: "parentchanges",
    tableRowField: "mle_counters.parentchanges",
  },
  // ── Router-neighbor: frame error rate ─────────────────────────────────
  {
    value: "router-neighbor-err-rate-frame-low",
    topoNodeField: "router_neighbor_max_err_rate_frame_pct",
    tableNeighborField: "err_rate_frame_pct",
  },
  {
    value: "router-neighbor-err-rate-frame-medium",
    topoNodeField: "router_neighbor_max_err_rate_frame_pct",
    tableNeighborField: "err_rate_frame_pct",
  },
  {
    value: "router-neighbor-err-rate-frame-high",
    topoNodeField: "router_neighbor_max_err_rate_frame_pct",
    tableNeighborField: "err_rate_frame_pct",
  },
  // ── Router-neighbor: message error rate ───────────────────────────────
  {
    value: "router-neighbor-err-rate-msg-low",
    topoNodeField: "router_neighbor_max_err_rate_msg_pct",
    tableNeighborField: "err_rate_msg_pct",
  },
  {
    value: "router-neighbor-err-rate-msg-medium",
    topoNodeField: "router_neighbor_max_err_rate_msg_pct",
    tableNeighborField: "err_rate_msg_pct",
  },
  {
    value: "router-neighbor-err-rate-msg-high",
    topoNodeField: "router_neighbor_max_err_rate_msg_pct",
    tableNeighborField: "err_rate_msg_pct",
  },
  // ── Router-neighbor: RSS ──────────────────────────────────────────────
  {
    value: "router-neighbor-rss-very-low",
    topoNodeField: "router_neighbor_has_rss_very_low",
    tableNeighborField: "rss_ave",
  },
  {
    value: "router-neighbor-rss-low",
    topoNodeField: "router_neighbor_has_rss_low",
    tableNeighborField: "rss_ave",
  },
  {
    value: "router-neighbor-rss-medium",
    topoNodeField: "router_neighbor_has_rss_medium",
    tableNeighborField: "rss_ave",
  },
  {
    value: "router-neighbor-rss-high",
    topoNodeField: "router_neighbor_has_rss_high",
    tableNeighborField: "rss_ave",
  },
]);

// ── vis.js network options ────────────────────────────────────────────────────

export const VIS_OPTIONS = {
  layout: { improvedLayout: true, randomSeed: 7 },
  nodes: {
    font: { size: 13, face: "monospace", multi: "md" },
    margin: 10,
    widthConstraint: { maximum: 260 },
  },
  groups: { unknown: { color: { background: "#f2f2f2", border: "#808080" } } },
  edges: { color: "#8a8a8a", width: 1.5, smooth: false },
  physics: {
    barnesHut: {
      gravitationalConstant: -9500,
      centralGravity: 0.15,
      springLength: 380,
      springConstant: 0.01,
      damping: 0.22,
      avoidOverlap: 1.5,
    },
    stabilization: { enabled: true, iterations: 1500, updateInterval: 25 },
  },
  interaction: { hover: true, navigationButtons: true },
};

// ── Table column priority order ───────────────────────────────────────────────

export const TABLE_PRIORITY_COLUMNS = [
  "rloc16",
  "extaddr",
  "device_label",
  "name",
  "room",
  "ID",
  "Extended MAC",
  "Next Hop",
  "Path Cost",
  "LQ In",
  "LQ Out",
  "Age",
  "type",
  "br",
  "status",
  "icon",
  "ver",
  "total_children",
  "total_links",
  "total_link_3",
  "total_link_2",
  "total_link_1",
  "router_neighbor_table_count",
  "router_child_table_count",
  "mode.device",
  "omrIpv6Address",
  "scope",
  "thread_stack_version",
  "mac_counters.ifinerrors_pct",
  "mac_counters.ifouterrors_pct",
  "mac_counters.ifindiscards_pct",
  "mac_counters.ifoutdiscards_pct",
  "mle_counters.partitionidchanges",
  "mle_counters.betterpartitionattachattempts",
  "mle_counters.parentchanges",
];
