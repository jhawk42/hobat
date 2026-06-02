// ── Merge strategy identifiers ────────────────────────────────────────────────

export const MERGE_STRATEGIES = Object.freeze({
  none: "none",
  byRloc16: "by-rloc16",
  byIdentity: "by-identity",
});

export const MERGE_IDENTITY_FIELDS = Object.freeze({
  extaddrAliases: ["extaddr", "extAddress", "Extended MAC"],
  omr_ipv6_addr: "omr_ipv6_addr",
  rloc16: "rloc16",
});

// ── Source precedence (higher number = higher authority) ─────────────────────
//
// When multiple sources provide a value for the same field, the source with the
// higher priority number wins.  Mirrors the Python SOURCE_PRECEDENCE dict in
// merge_dataset.py.  Filenames not listed default to priority 0.
//
export const SOURCE_PRECEDENCE = Object.freeze({
  "td-static-extaddr-device-label.json": 101, // Highest priority (most detailed)
  "td-otbr-restapi-diagnostics-fetch-all.json": 100, // Highest priority (most detailed)
  "td-otbr-restapi-mesh-diagnostics-fetch-all.json": 99,
  "td-otbr-restapi-diagnostics-list.json": 98,
  "td-otbr-restapi-diagnostics.json": 97,      
  "td-otbr-restapi-devices-fetch.json": 96,
  "td-otbr-restapi-devices-list.json": 95,
  "td-otbr-restapi-devices.json": 94,
  "td-otbr-cli-networkdiag-fetch-all.json": 90,
  "td-otbr-cli-networkdiag-multicast-network.json": 85,
  "td-otbr-cli-meshdiag-topology.json": 80,
  "td-otbr-cli-meshdiag-router-neighbortables.json": 75,
  "td-otbr-cli-meshdiag-router-childtables.json": 74,
  "td-otbr-cli-router-table.json": 70,
  "td-eve-topology.json": 60,                   
  "td-mdns-scopes-thread.json": 55,
  "td-mdns-scopes-br.json": 60,                // mDNS scopes (service discovery)
  "td-mdns-scopes-hap.json": 50,
  "td-mdns-scopes-matter.json": 45,
});

// ── Field-name alias mapping (canonical snake_case → [camelCase aliases]) ────
//
// Mirrors FIELD_ALIASES_BIDIRECTIONAL in merge_dataset.py.
// Used by normalizeFieldNames() in tdash-utils.js to ensure rows from different
// sources (CLI snake_case, REST API camelCase) use consistent field names.
//
export const FIELD_ALIASES = Object.freeze({
  extaddr:              ["extAddress", "Extended MAC"],
  omr_ipv6_addr:        ["omrIpv6Address"],
  router_id:            ["routerId"],
  device_label:         ["name", "hostName"],
  eui64:                ["EUI64"],
  route_data:           ["route"],
  leader_data:          ["leaderData"],
  route_id:             ["routeId"],
  route_cost:           ["routeCost"],
  link_quality_in:      ["linkQualityIn"],
  link_quality_out:     ["linkQualityOut"],
  id_sequence:          ["idSequence"],
  partition_id:         ["partitionId"],
  leader_router_id:     ["leaderRouterId"],
  data_version:         ["dataVersion"],
  stable_data_version:  ["stableDataVersion"],
  active_routers:       ["activeRouters"],
  leader_cost:          ["leaderCost"],
  parent_priority:      ["parentPriority"],
  link_quality_3:       ["linkQuality3"],
  link_quality_2:       ["linkQuality2"],
  link_quality_1:       ["linkQuality1"],
  sed_buffer_size:      ["sedBufferSize"],
  sed_datagram_count:   ["sedDatagramCount"],
  br:                   ["isBorderRouter"],
  leader:               ["isLeader"],
  is_router:            ["isRouter"],
  vendor_name:          ["vendorName"],
  vendor_model:         ["vendorModel"],
  vendor_sw_version:    ["vendorSwVersion"],
  thread_stack_version: ["threadStackVersion"],
  rx_on_when_idle:      ["rxOnWhenIdle"],
  device_type:          ["deviceTypeFTD"],
  network_data:         ["fullNetworkData"],
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

// ── Color palette — unified design system ────────────────────────────────────
//
// Single source of truth for all theme colors. Keeps CSS tokens, JS constants,
// and canvas colors in sync. Updated for dark mode at runtime via theme system.
//
export const PALETTE = Object.freeze({
  // Link Quality colors
  lqHigh: "#0072b2",
  lqMedium: "#1a86c5",
  lqLow: "#c62828",
  lqNone: "#8a8a8a",
  lqParentChild: "#cc79a7",
  lqOtbr: "#009e73",

  // Topology node colors
  routerBg: "#d9ecff",
  routerBorder: "#1565c0",
  borderRouterBg: "#c8e6c9",
  borderRouterBorder: "#4caf50",
  childBg: "#fff4cc",
  childBorder: "#d9a400",
  eveBg: "#e8f5e9",
  eveBorder: "#2e7d32",
  unknownBg: "#f2f2f2",
  unknownBorder: "#808080",
});

// ── Topology node colors — consolidated constants ──────────────────────────
//
// Replaces hard-coded color literals scattered throughout tdash-adaptors.js.
// Each entry maps a node type to background and border colors.
//
export const NODE_COLORS = Object.freeze({
  router: { background: PALETTE.routerBg, border: PALETTE.routerBorder },
  borderRouter: { background: PALETTE.borderRouterBg, border: PALETTE.borderRouterBorder },
  child: { background: PALETTE.childBg, border: PALETTE.childBorder },
  eve: { background: PALETTE.eveBg, border: PALETTE.eveBorder },
  unknown: { background: PALETTE.unknownBg, border: PALETTE.unknownBorder },
});

// ── Link Quality edge style constants ─────────────────────────────────────────
export const EDGE_LQ_STYLES = Object.freeze({
  high: { width: 8, color: PALETTE.lqHigh, dashes: false, lqLevel: 3 }, // LQ3 bold blue  (.lq-high)
  medium: { width: 6, color: PALETTE.lqMedium, dashes: false, lqLevel: 2 }, // LQ2 light blue (.lq-medium)
  low: { width: 4, color: PALETTE.lqLow, dashes: true, lqLevel: 1 }, // LQ1 red dashed (.lq-low)
  none: { width: 4, color: PALETTE.lqNone, dashes: false, lqLevel: 0 }, // fallback (no LQ data)
  parentChild: { width: 8, color: PALETTE.lqParentChild, dashes: false, lqLevel: 0 }, // parent–child pink/mauve (.lq-parent-child)
  noLqPurple: { width: 4, color: PALETTE.lqOtbr, dashes: false, lqLevel: 0 }, // OTBR / router-neighbor green (.lq-otbr)
});

// ── Filter option metadata registries ────────────────────────────────────────
//
// Each registry is the single source of truth mapping a dropdown <option>
// value to the data fields / edge categories that must be present in the
// active dataset for that option to be meaningful.
//
// Fields:
//   value          — must match the <option value="..."> in the HTML
//   label          — display text rendered as the <option> text content
//   group          — <optgroup> label string; null means no group.
//                    Consecutive entries sharing the same group string are
//                    placed inside one <optgroup>. Group labels must be
//                    unique within each registry.
//   title          — optional tooltip rendered as the <option title="">
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
  { value: "all",                      label: "All",                         alwaysShow: true, group: null },
  {
    value: "border-routers",
    label: "Border Routers",
    group: null,
    topoNodeField: "isBorderRouter",
    tableRowField: "br",
  },
  {
    value: "main-routers",
    label: "Routers",
    group: null,
    topoNodeField: "isMainRouter",
    tableRowField: "rloc16", // rloc16 ending in '00' → main router
  },
  {
    value: "routers-with-children",
    label: "Routers with Child Nodes",
    group: null,
    topoNodeField: "isRouter", // isRouter && hasChildren
    tableRowField: "total_children", // > 0, or children[] length > 0
  },
  {
    value: "routers-without-children",
    label: "Routers without Child Nodes",
    group: null,
    topoNodeField: "isRouter", // isRouter && !hasChildren
    tableRowField: "rloc16", // router-shaped, checked by predicate
  },
  {
    value: "ftd-devices",
    label: "Full Thread Devices",
    group: null,
    topoNodeField: "mode_device",
    topoNodeValue: "FTD",
    tableRowField: "mode.device",
    tableRowValue: "FTD",
  },
  {
    value: "mtd-devices",
    label: "Sleepy End Devices",
    group: null,
    topoNodeField: "mode_device",
    topoNodeValue: "MTD",
    tableRowField: "mode.device",
    tableRowValue: "MTD",
  },
]);

export const LINK_FILTER_OPTIONS = Object.freeze([
  { value: LINK_FILTER_ALL,                   label: "All",                    alwaysShow: true, group: null },
  {
    value: LINK_FILTER_DEFAULT,
    label: "Standard",
    title: "Shows parent-child relationships and link quality indicators",
    group: null,
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
    label: "Standard & Neighbors",
    title: "Shows parent-child relationships, link quality, and router neighbors",
    group: null,
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
    label: "Standard (restapi)",
    title: "OTBR REST API: Shows parent-child relationships and link quality",
    group: null,
    requiredEdgeCategories: [
      EDGE_CATEGORY_OTBR_ROUTE,
      EDGE_CATEGORY_OTBR_CHILD,
    ],
  },
  {
    value: LINK_FILTER_EVE_NATIVE,
    label: "Eve Native",
    title: "Shows network routes and child device relationships",
    group: null,
    requiredEdgeCategories: [
      EDGE_CATEGORY_EVE_NATIVE_ROUTE,
      EDGE_CATEGORY_EVE_NATIVE_CHILD,
    ],
  },
  {
    value: LINK_FILTER_EVE_ENHANCED,
    label: "Eve Enhanced",
    title: "Shows enhanced network routes with additional metadata",
    group: null,
    requiredEdgeCategories: [EDGE_CATEGORY_EVE_ROUTE, EDGE_CATEGORY_EVE_CHILD],
  },
  // ── Link Quality filters ──────────────────────────────────────────────
  {
    value: LINK_FILTER_LQ_HIGH,
    label: "High (LQ3)",
    group: "Link Quality",
    requiredEdgeCategories: [
      EDGE_CATEGORY_DEFAULT_3,
      EDGE_CATEGORY_EVE_ROUTE,
      EDGE_CATEGORY_EVE_NATIVE_ROUTE,
      EDGE_CATEGORY_OTBR_ROUTE,
    ],
  },
  {
    value: LINK_FILTER_LQ_MEDIUM,
    label: "Medium (LQ2)",
    group: "Link Quality",
    requiredEdgeCategories: [
      EDGE_CATEGORY_DEFAULT_2,
      EDGE_CATEGORY_EVE_ROUTE,
      EDGE_CATEGORY_EVE_NATIVE_ROUTE,
      EDGE_CATEGORY_OTBR_ROUTE,
    ],
  },
  {
    value: LINK_FILTER_LQ_LOW,
    label: "Low (LQ1)",
    group: "Link Quality",
    requiredEdgeCategories: [
      EDGE_CATEGORY_DEFAULT_1,
      EDGE_CATEGORY_EVE_ROUTE,
      EDGE_CATEGORY_EVE_NATIVE_ROUTE,
      EDGE_CATEGORY_OTBR_ROUTE,
    ],
  },
  { value: LINK_FILTER_LQ_NONE,             label: "No LQ Data / Unknown",   alwaysShow: true, group: "Link Quality" },
  // ── Link Type filters ─────────────────────────────────────────────────
  {
    value: LINK_FILTER_PARENT_CHILD,
    label: "Parent\u2013Child",
    group: "Link Types",
    requiredEdgeCategories: [
      EDGE_CATEGORY_DEFAULT_CHILDREN,
      EDGE_CATEGORY_EVE_CHILD,
      EDGE_CATEGORY_EVE_NATIVE_CHILD,
      EDGE_CATEGORY_OTBR_CHILD,
    ],
  },
  {
    value: LINK_FILTER_OTBR_NEIGHBOR,
    label: "Router Neighbors",
    group: "Link Types",
    requiredEdgeCategories: [
      EDGE_CATEGORY_OTBR_ROUTE,
      EDGE_CATEGORY_ROUTER_NEIGHBOR,
    ],
  },
]);

export const DIAGNOSTIC_FILTER_OPTIONS = Object.freeze([
  { value: "all", label: "All Rows", alwaysShow: true, group: null },
  // ── Mac counters ──────────────────────────────────────────────────────
  // ── Mac total errors ratio ────────────────────────────────────────────
  {
    source: "mac_counters",
    value: "mac-total-errors-ratio-medium",
    label: "Mac Total Errors Ratio: Medium (>= 1.0)",
    group: "Mac Total Errors Ratio",
    topoNodeField: "iftotalerrors_totalpkts_ratio",
    tableRowField: "mac_counters.iftotalerrors_totalpkts_ratio",
  },
  {
    source: "mac_counters",
    value: "mac-total-errors-ratio-high",
    label: "Mac Total Errors Ratio: High (>= 5.0)",
    group: "Mac Total Errors Ratio",
    topoNodeField: "iftotalerrors_totalpkts_ratio",
    tableRowField: "mac_counters.iftotalerrors_totalpkts_ratio",
  },
  // ── Mac total discards ratio ──────────────────────────────────────────
  {
    source: "mac_counters",
    value: "mac-total-discards-ratio-medium",
    label: "Mac Total Discards Ratio: Medium (>= 2.0)",
    group: "Mac Total Discards Ratio",
    topoNodeField: "iftotaldiscards_totalpkts_ratio",
    tableRowField: "mac_counters.iftotaldiscards_totalpkts_ratio",
  },
  {
    source: "mac_counters",
    value: "mac-total-discards-ratio-high",
    label: "Mac Total Discards Ratio: High (>= 8.0)",
    group: "Mac Total Discards Ratio",
    topoNodeField: "iftotaldiscards_totalpkts_ratio",
    tableRowField: "mac_counters.iftotaldiscards_totalpkts_ratio",
  },

  // ── Mle counters ──────────────────────────────────────────────────────
  {
    source: "mle_counters",
    value: "medium-partition-changes",
    label: "Partition Changes: Medium (>= 2)",
    group: "Mle Partition Changes",
    topoNodeField: "partitionidchanges",
    tableRowField: "mle_counters.partitionidchanges",
  },
  {
    source: "mle_counters",
    value: "high-partition-changes",
    label: "Partition Changes: High (>= 5)",
    group: "Mle Partition Changes",
    topoNodeField: "partitionidchanges",
    tableRowField: "mle_counters.partitionidchanges",
  },
  {
    source: "mle_counters",
    value: "medium-parent-changes",
    label: "Parent Changes: Medium (>= 2)",
    group: "MLE Parent Changes",
    topoNodeField: "parentchanges",
    tableRowField: "mle_counters.parentchanges",
  },
  {
    source: "mle_counters",
    value: "high-parent-changes",
    label: "Parent Changes: High (>= 5)",
    group: "MLE Parent Changes",
    topoNodeField: "parentchanges",
    tableRowField: "mle_counters.parentchanges",
  },
 
  // ── Mle better partition attach ───────────────────────────────────────
  {
    source: "mle_counters",
    value: "mle-better-partition-medium",
    label: "Better Partition Attach: Medium (>= 2)",
    group: "Mle Better Partition Attach",
    topoNodeField: "betterpartitionattachattempts",
    tableRowField: "mle_counters.betterpartitionattachattempts",
  },
  {
    source: "mle_counters",
    value: "mle-better-partition-high",
    label: "Better Partition Attach: High (>= 5)",
    group: "Mle Better Partition Attach",
    topoNodeField: "betterpartitionattachattempts",
    tableRowField: "mle_counters.betterpartitionattachattempts",
  },
  // ── Mle total parent partition changes ────────────────────────────────
  {
    source: "mle_counters",
    value: "mle-total-parent-partition-medium",
    label: "Total Parent Partition Changes: Medium (>= 3)",
    group: "Mle Total Parent Partition Changes",
    topoNodeField: "totalparentpartitionchanges",
    tableRowField: "mle_counters.totalparentpartitionchanges",
  },
  {
    source: "mle_counters",
    value: "mle-total-parent-partition-high",
    label: "Total Parent Partition Changes: High (>= 8)",
    group: "Mle Total Parent Partition Changes",
    topoNodeField: "totalparentpartitionchanges",
    tableRowField: "mle_counters.totalparentpartitionchanges",
  },

  // ── link_quality ──────────────────────────────────────────────────────
  // ── Router-neighbor: frame error rate ─────────────────────────────────
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-frame-low",
    label: "Router Neighbor Err Rate Frame: Low (>= 2%)",
    group: "Router Neighbor Err Rate Frame",
    topoNodeField: "router_neighbor_max_err_rate_frame_pct",
    tableNeighborField: "err_rate_frame_pct",
  },
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-frame-medium",
    label: "Router Neighbor Err Rate Frame: Medium (>= 5%)",
    group: "Router Neighbor Err Rate Frame",
    topoNodeField: "router_neighbor_max_err_rate_frame_pct",
    tableNeighborField: "err_rate_frame_pct",
  },
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-frame-high",
    label: "Router Neighbor Err Rate Frame: High (>= 10%)",
    group: "Router Neighbor Err Rate Frame",
    topoNodeField: "router_neighbor_max_err_rate_frame_pct",
    tableNeighborField: "err_rate_frame_pct",
  },
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-frame-critical",
    label: "Router Neighbor Err Rate Frame: Critical (>= 30%)",
    group: "Router Neighbor Err Rate Frame",
    topoNodeField: "router_neighbor_max_err_rate_frame_pct",
    tableNeighborField: "err_rate_frame_pct",
  },
  {
    value: "router-neighbor-err-rate-frame-critical",
    label: "Critical (>= 30%)",
    group: "Router Neighbor Err Rate Frame",
    topoNodeField: "router_neighbor_max_err_rate_frame_pct",
    tableNeighborField: "err_rate_frame_pct",
  },
  // ── Router-neighbor: message error rate ───────────────────────────────
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-msg-low",
    label: "Router Neighbor Err Rate Msg: Low (>= 2%)",
    group: "Router Neighbor Err Rate Msg",
    topoNodeField: "router_neighbor_max_err_rate_msg_pct",
    tableNeighborField: "err_rate_msg_pct",
  },
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-msg-medium",
    label: "Router Neighbor Err Rate Msg: Medium (>= 5%)",
    group: "Router Neighbor Err Rate Msg",
    topoNodeField: "router_neighbor_max_err_rate_msg_pct",
    tableNeighborField: "err_rate_msg_pct",
  },
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-msg-high",
    label: "Router Neighbor Err Rate Msg: High (>= 10%)",
    group: "Router Neighbor Err Rate Msg",
    topoNodeField: "router_neighbor_max_err_rate_msg_pct",
    tableNeighborField: "err_rate_msg_pct",
  },
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-msg-critical",
    label: "Router Neighbor Err Rate Msg: Critical (>= 30%)",
    group: "Router Neighbor Err Rate Msg",
    topoNodeField: "router_neighbor_max_err_rate_msg_pct",
    tableNeighborField: "err_rate_msg_pct",
  },
  {
    value: "router-neighbor-err-rate-msg-critical",
    label: "Critical (>= 30%)",
    group: "Router Neighbor Err Rate Msg",
    topoNodeField: "router_neighbor_max_err_rate_msg_pct",
    tableNeighborField: "err_rate_msg_pct",
  },
  // ── Router-neighbor: RSS ──────────────────────────────────────────────
  {
    source: "link_quality",
    value: "router-neighbor-rss-very-low",
    label: "Router Neighbor RSS Ave: Bad (< -80 dBm)",
    group: "Router Neighbor RSS Ave",
    topoNodeField: "router_neighbor_has_rss_very_low",
    tableNeighborField: "rss_ave",
  },
  {
    source: "link_quality",
    value: "router-neighbor-rss-low",
    label: "Router Neighbor RSS Ave: Fair (-70 dBm To -80 dBm)",
    group: "Router Neighbor RSS Ave",
    topoNodeField: "router_neighbor_has_rss_low",
    tableNeighborField: "rss_ave",
  },
  {
    source: "link_quality",
    value: "router-neighbor-rss-medium",
    label: "Router Neighbor RSS Ave: Good (-60 dBm To -70 dBm)",
    group: "Router Neighbor RSS Ave",
    topoNodeField: "router_neighbor_has_rss_medium",
    tableNeighborField: "rss_ave",
  },
  {
    source: "link_quality",
    value: "router-neighbor-rss-high",
    label: "Router Neighbor RSS Ave: Excellent (> -60 dBm)",
    group: "Router Neighbor RSS Ave",
    topoNodeField: "router_neighbor_has_rss_high",
    tableNeighborField: "rss_ave",
  },
  // ── Router link quality distribution ─────────────────────────────────
  {
    source: "link_quality",
    value: "low-lq3-ratio-medium",
    label: "Router Link Quality Ratio: Low LQ3 (< 60%)",
    group: "Router Link Quality Distribution",
    topoNodeField: "lq3_ratio",
  },
  {
    source: "link_quality",
    value: "low-lq3-ratio-high",
    label: "Router Link Quality Ratio: Very Low LQ3 (< 35%)",
    group: "Router Link Quality Distribution",
    topoNodeField: "lq3_ratio",
  },
  {
    source: "link_quality",
    value: "high-lq1-ratio-medium",
    label: "Router Link Quality Ratio: High LQ1 (>= 20%)",
    group: "Router Link Quality Distribution",
    topoNodeField: "lq1_ratio",
  },
  {
    source: "link_quality",
    value: "high-lq1-ratio-high",
    label: "Router Link Quality Ratio: Very High LQ1 (>= 35%)",
    group: "Router Link Quality Distribution",
    topoNodeField: "lq1_ratio",
  },
  // ── Children link quality ─────────────────────────────────────────────
  {
    source: "link_quality",
    value: "child-lq-medium",
    label: "Children Link: Child LQ <= 2",
    group: "Children Link Quality",
    topoNodeField: "has_child_lq_medium",
  },
  {
    source: "link_quality",
    value: "child-lq-poor",
    label: "Children Link: Child LQ = 1",
    group: "Children Link Quality",
    topoNodeField: "has_child_lq_poor",
  },
  // ── Router child err rate frame ───────────────────────────────────────
  {
    source: "link_quality",
    value: "router-child-err-rate-frame-medium",
    label: "Router Child Err Rate Frame: Medium (>= 10%)",
    group: "Router Child Err Rate Frame",
    topoNodeField: "router_child_max_err_rate_frame_pct",
    tableChildField: "err_rate_frame_pct",
  },
  {
    source: "link_quality",
    value: "router-child-err-rate-frame-high",
    label: "Router Child Err Rate Frame: High (>= 25%)",
    group: "Router Child Err Rate Frame",
    topoNodeField: "router_child_max_err_rate_frame_pct",
    tableChildField: "err_rate_frame_pct",
  },
  // ── Router child err rate msg ─────────────────────────────────────────
  {
    source: "link_quality",
    value: "router-child-err-rate-msg-low",
    label: "Router Child Err Rate Msg: Low (>= 1%)",
    group: "Router Child Err Rate Msg",
    topoNodeField: "router_child_max_err_rate_msg_pct",
    tableChildField: "err_rate_msg_pct",
  },
  {
    source: "link_quality",
    value: "router-child-err-rate-msg-high",
    label: "Router Child Err Rate Msg: High (>= 5%)",
    group: "Router Child Err Rate Msg",
    topoNodeField: "router_child_max_err_rate_msg_pct",
    tableChildField: "err_rate_msg_pct",
  },
  // ── Router child RSS ──────────────────────────────────────────────────
  {
    source: "link_quality",
    value: "router-child-rss-very-low",
    label: "Router Child RSS Ave: Bad (< -80 dBm)",
    group: "Router Child RSS Ave",
    topoNodeField: "router_child_has_rss_very_low",
    tableChildField: "rss_ave",
  },
  {
    source: "link_quality",
    value: "router-child-rss-low",
    label: "Router Child RSS Ave: Fair (-80 to -70 dBm)",
    group: "Router Child RSS Ave",
    topoNodeField: "router_child_has_rss_low",
    tableChildField: "rss_ave",
  },
  {
    source: "link_quality",
    value: "router-child-rss-margin-low",
    label: "Router Child RSS: Low Margin (< 20 dB)",
    group: "Router Child RSS Margin",
    topoNodeField: "router_child_has_rss_margin_low",
    tableChildField: "rss_margin",
  },
  // ── Router child queued messages ──────────────────────────────────────
  {
    source: "link_quality",
    value: "router-child-has-queued-msgs",
    label: "Router Child Has Queued Messages",
    group: "Router Child Queued Messages",
    topoNodeField: "router_child_has_queued_msgs",
    tableChildField: "q_msg",
  },
 
  // ── time_statistics────────────────────────────────────────────────────
  // ── Time: FTD Router uptime % ─────────────────────────────────────────
  {
    source: "time_statistics",
    value: "ftd-router-pct-low",
    label: "FTD Router < 80% Uptime",
    group: "Time FTD Router Uptime",
    topoNodeField: "router_pct",
    tableRowField: "time_statistics.router_pct",
  },
  {
    source: "time_statistics",
    value: "ftd-router-pct-very-low",
    label: "Router Uptime: FTD Router < 50% Uptime",
    group: "Time FTD Router Uptime",
    topoNodeField: "router_pct",
    tableRowField: "time_statistics.router_pct",
  },
  // ── Time: Detached/Disabled % ─────────────────────────────────────────
  {
    source: "time_statistics",
    value: "detached-disabled-pct-medium",
    label: "Time Detached/Disabled: Medium (>= 1%)",
    group: "Time Detached Disabled",
    topoNodeField: "detached_disabled_pct",
    tableRowField: "time_statistics.detached_disabled_pct",
  },
  {
    source: "time_statistics",
    value: "detached-disabled-pct-high",
    label: "Time Detached/Disabled: High (>= 5%)",
    group: "Time Detached Disabled",
    topoNodeField: "detached_disabled_pct",
    tableRowField: "time_statistics.detached_disabled_pct",
  },
]);

// ── vis.js network options ────────────────────────────────────────────────────

export const VIS_OPTIONS = {
  layout: { improvedLayout: true, randomSeed: 7 },
  nodes: {
    font: { size: 13, face: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif", multi: "md" },
    margin: 10,
    widthConstraint: { maximum: 260 },
  },
  groups: { unknown: { color: NODE_COLORS.unknown } },
  edges: { color: PALETTE.lqNone, width: 1.5, smooth: false },
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

/**
 * Ordered list of device record field names for table column priority.
 * 
 * Fields appear in the table view in this order (left to right).
 * The priority system organizes fields into 5 tiers:
 * 
 * - **TIER 1: Primary Identity** - Core device identifiers (rloc16, extaddr, device_label, routerId)
 * - **TIER 2: Secondary Identity** - Additional identifiers (omr_ipv6_addr, mlEidIid, room)
 * - **TIER 3: Device Role & Status** - Device type, role, and mode information
 * - **TIER 4: Topology & Connectivity** - Network topology, link quality, connectivity metrics
 * - **TIER 5: Advanced/Diagnostic** - Detailed diagnostics, vendor info, MLE/MAC counters
 * 
 * **Field Naming Conventions:**
 * - Supports both snake_case (CLI datasets) and camelCase (REST API datasets)
 * - Both variants can appear (e.g., extaddr and extAddress, omr_ipv6_addr and omrIpv6Address)
 * - Missing fields are gracefully hidden (no errors)
 * 
 * **Dataset Compatibility:**
 * - CLI datasets (meshdiag, networkdiag) provide snake_case fields
 * - REST API datasets (devices-list, diagnostics-fetch) provide camelCase fields
 * - Eve topology and MDNS datasets have mixed conventions
 * - Merged datasets may contain both naming conventions
 * 
 * @type {string[]}
 * @constant
 */
export const TABLE_PRIORITY_COLUMNS = [
  // === TIER 1: Primary Identity ===
  "rloc16",
  "extaddr",
  "extAddress",
  "device_label",
  "name",
  "routerId",
  "router_id",
  "eui64",
  "id",
  "ID",
  
  // === TIER 2: Secondary Identity ===
  "omr_ipv6_addr",
  "omrIpv6Address",
  "mlEidIid",
  "room",
  "Extended MAC",
  "Next Hop",
  "Path Cost",
  "LQ In",
  "LQ Out",
  "Age",
  
  // === TIER 3: Device Role & Status ===
  "type",
  "Role",
  "br",
  "isBorderRouter",
  "leader",
  "isLeader",
  "is_router",
  "isPrimaryBBR",
  "status",
  "mode.device",
  "mode.deviceTypeFTD",
  "ver",
  "version",
  "thread_version",
  "thread_stack_version",
  "threadStackVersion",
  "room",
  "icon",
  
  // === TIER 4: Topology & Connectivity ===
  "total_children",
  "has_children",
  "total_links",
  "total_link_3",
  "total_link_2",
  "total_link_1",
  "router_neighbor_table_count",
  "router_child_table_count",
  "connectivity.activeRouters",
  "connectivity.active_routers",
  "connectivity.linkQuality3",
  "connectivity.link_quality_3",
  "connectivity.linkQuality2",
  "connectivity.link_quality_2",
  "connectivity.linkQuality1",
  "connectivity.link_quality_1",
  "leaderData.partitionId",
  "leader_data.partition_id",
  "leaderData.leaderRouterId",
  "leader_data.leader_router_id",
  
  // === TIER 5: Advanced/Diagnostic ===
  "icon",
  "scope",
  "vendor_name",
  "vendorName",
  "vendor_model",
  "vendorModel",
  "vendor_sw_version",
  "vendorSwVersion",
  "tlv_values",
  "mac_counters.ifinerrors_pct",
  "mac_counters.ifouterrors_pct",
  "mac_counters.ifindiscards_pct",
  "mac_counters.ifoutdiscards_pct",
  "mle_counters.partitionidchanges",
  "mle_counters.betterpartitionattachattempts",
  "mle_counters.totalparentpartitionchanges",
  "mle_counters.parentchanges",
  "mac_counters.iftotalerrors_totalpkts_ratio",
  "mac_counters.iftotaldiscards_totalpkts_ratio",
  "time_statistics.router_pct",
  "time_statistics.detached_disabled_pct",
];
