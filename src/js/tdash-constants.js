// ── Merge strategy identifiers ────────────────────────────────────────────────

export const MERGE_STRATEGIES = Object.freeze({
  none: "none",
  byRloc16: "by-rloc16",
  byIdentity: "by-identity",
});

export const MERGE_IDENTITY_FIELDS = Object.freeze({
  extaddrAliases: ["extAddress", "extaddr", "Extended MAC"],
  omr_ipv6_addr: "omrIpv6Address",
  rloc16: "rloc16",
});

// ── Source precedence (higher number = higher authority) ─────────────────────
//
// When multiple sources provide a value for the same field, the source with the
// higher priority number wins.  Mirrors the Python SOURCE_PRECEDENCE dict in
// merge_dataset.py.  Filenames not listed default to priority 0.
//
export const SOURCE_PRECEDENCE = Object.freeze({
  "td-static-extaddr-device-label.json": 101, // Highest priority

  "td-otbr-cli-networkdiag-fetch-all.json": 100, // Highest priority (most detailed)
  "td-otbr-cli-networkdiag-multicast-network.json": 99,
  "td-otbr-cli-meshdiag-topology.json": 98,
  "td-otbr-cli-meshdiag-router-neighbortables.json": 97,
  "td-otbr-cli-meshdiag-router-childtables.json": 96,
  "td-otbr-cli-router-table.json": 95,

  "td-otbr-restapi-diagnostics-fetch-all.json": 90, 
  "td-otbr-restapi-mesh-diagnostics-fetch-all.json": 89,
  "td-otbr-restapi-diagnostics-list.json": 88,
  "td-otbr-restapi-diagnostics.json": 87,      
  "td-otbr-restapi-devices-fetch.json": 86,
  "td-otbr-restapi-devices-list.json": 85,
  "td-otbr-restapi-devices.json": 84,

  "td-eve-topology.json": 60,

  "td-mdns-scopes-thread.json": 50,
  "td-mdns-scopes-br.json": 49,             // mDNS scopes (service discovery)
  "td-mdns-scopes-hap.json": 48,
  "td-mdns-scopes-matter.json": 47          // Lowest priority
});

// ── Field-name alias mapping (canonical snake_case → [camelCase aliases]) ────
//
// Mirrors FIELD_ALIASES_BIDIRECTIONAL in merge_dataset.py.
// Used by normalizeFieldNames() in tdash-utils.js to ensure rows from different
// sources (CLI snake_case, REST API camelCase) use consistent field names.
//
export const FIELD_ALIASES = Object.freeze({
  extaddr:              ["extAddress", "extMacAddr", "Extended MAC"],
  omr_ipv6_addr:        ["omrIpv6Address", "omrIpv6Addr"],
  router_id:            ["routerId"],
  device_label:         ["deviceLabel", "name", "hostName"],
  thread_version:       ["threadVersion"],
  eui64:                ["EUI64"],
  ipv6_addrs:           ["ipv6Addresses", "addrs"],
  route:                ["route", "route64"],
  leader_data:          ["leaderData"],
  route_id:             ["routeId"],
  route_cost:           ["routeCost"],
  link_quality_in:      ["linkQualityIn", "inLinkQuality"],
  link_quality_out:     ["linkQualityOut", "outLinkQuality"],
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
  is_border_router:     ["isBorderRouter"],
  is_router:            ["isRouter"],
  vendor_name:          ["vendorName"],
  vendor_model:         ["vendorModel"],
  vendor_sw_version:    ["vendorSwVersion", "vendorSWVersion"],
  thread_stack_version: ["threadStackVersion"],
  total_children:       ["totalChildren"],
  total_links:          ["totalLinks"],
  total_link_3:         ["totalLink3"],
  total_link_2:         ["totalLink2"],
  total_link_1:         ["totalLink1"],
  router_neighbor_table: ["routerNeighbors", "routerNeighbor"],
  router_neighbor_table_count: ["routerNeighborsCount"],
  router_child_table:   ["childTable"],
  router_child_table_count: ["childTableCount"],
  conn_time:            ["connectionTime"],
  ver:                  ["version"],
  rx_on_when_idle:      ["rxOnWhenIdle"],
  rx_on:                ["rxOnWhenIdle"],
  device_type:          ["deviceTypeFTD"],
  network_data:         ["fullNetworkData"],
  macCounters:         ["macCounters"],
  mlecounters:         ["mleCounters"],
  time_statistics:      ["timeStatistics"],
  partitionidchanges:   ["partIdChangesCount", "partitionIdChanges", "partitionIdChangesCounter"],
  parentchanges:        ["newParentCount", "parentChanges", "newParentCounter"],
  attachattempts:       ["attachAttemptsCount", "attachAttempts", "attachAttemptsCounter"],
  childrole:            ["childRoleCount", "childRole", "childRoleCounter"],
  detachedrole:         ["detachedRoleCount", "detachedRole", "detachedRoleCounter"],
  leaderrole:           ["leaderRoleCount", "leaderRole", "leaderRoleCounter"],
  routerrole:           ["routerRoleCount", "routerRole", "routerRoleCounter"],
  disabledrole:         ["radioDisabledCount", "disabledRole", "radioDisabledCounter"],
  betterpartitionattachattempts: ["betterPartIdAttachAttemptsCount", "betterPartitionAttachAttempts", "betterPartitionAttachAttemptsCounter"],
  totalparentpartitionchanges: ["totalParentPartitionChangesCount", "totalParentPartitionChanges"],
  iftotalerrors_totalpkts_ratio: ["ifTotalErrorsTotalPktsRatio", "iftotalerrorsTotalpktsRatio"],
  iftotaldiscards_totalpkts_ratio: ["ifTotalDiscardsTotalPktsRatio", "iftotaldiscardsTotalpktsRatio"],
  router_pct:           ["routerPct"],
  detached_disabled_pct: ["detachedDisabledPct"],
  ifinerrors_totalerrors_pct: ["ifInErrorsPercentage"],
  ifouterrors_totalerrors_pct: ["ifOutErrorsPercentage"],
  ifindiscards_totaldiscards_pct: ["ifInDiscardsPercentage"],
  ifoutdiscards_totaldiscards_pct: ["ifOutDiscardsPercentage"],
  // ── Link quality fields (router neighbors & children) ─────────────────────
  err_rate_frame_pct:   ["frameErrorRate"],
  err_rate_msg_pct:     ["messageErrorRate"],
  rss_ave:              ["averageRssi"],
  rss_last:             ["lastRssi"],
  rss_margin:           ["linkMargin"],
  q_msg:                ["queuedMessageCount"],
  "3_links":           ["links3", "link3"],
  "2_links":           ["links2", "link2"],
  "1_links":           ["links1", "link1"],
});

// ── Link filter constants ─────────────────────────────────────────────────────

export const LINK_FILTER_ALL = "all_links";
export const LINK_FILTER_EVE_NATIVE = "eve_native_routes_children";
export const LINK_FILTER_EVE_ENHANCED = "eve_enhanced_routes_children";
export const LINK_FILTER_DEFAULT = "default_links";
export const LINK_FILTER_DEFAULT_PLUS_NEIGHBORS = "default_plus_router_neighbors";
export const LINK_FILTER_ROUTES = "otbr_routes";
export const LINK_FILTER_PARENT_CHILD = "lq_parent_child";
export const LINK_FILTER_ROUTER_NEIGHBOR = "lq_otbr_neighbor";
export const LINK_FILTER_LQ_HIGH = "lq_high";
export const LINK_FILTER_LQ_MEDIUM = "lq_medium";
export const LINK_FILTER_LQ_LOW = "lq_low";
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

// Map Edge categories to common readable labels (used in filter option tooltips and legends)
export const EDGE_CATEGORY_LABELS = Object.freeze({
  default_children: "Parent-child",
  default_1_links: "Route",
  default_2_links: "Route",
  default_3_links: "Route",
  router_neighbor: "Router-Neighbor",
  otbr_route: "Route",
  otbr_child: "Parent-child",
  eve_route: "Route",
  eve_child: "Parent-child",
  eve_native_route: "Route",
  eve_native_child: "Parent-child",
});

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

// ── Topology node shapes by Thread role ─────────────────────────────────────
// Centralized role-shape mapping used across adaptors and final vis-node build.
export const NODE_SHAPES = Object.freeze({
  borderRouter: "square",
  router: "hexagon",
  childFtd: "dot",
  childMtd: "dot",
  child: "dot",
  unknown: "dot",
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
  { 
    value: "all",                      
    label: "All",                         
    alwaysShow: true, 
    group: null 
  },
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
    topoNodeField: "isRouter",
    tableRowField: "rloc16", // rloc16 ending in '00' → main router
  },
  {
    value: "routers-with-children",
    label: "Routers with Child Nodes",
    group: null,
    topoNodeField: "isRouter", // isRouter && hasChildren
    tableRowField: "totalChildren", // > 0, or children[] length > 0
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
    topoNodeField: "modeDevice",
    topoNodeValue: "FTD",
    tableRowField: "mode.device",
    tableRowValue: "FTD",
  },
  {
    value: "mtd-devices",
    label: "Sleepy End Devices",
    group: null,
    topoNodeField: "modeDevice",
    topoNodeValue: "MTD",
    tableRowField: "mode.device",
    tableRowValue: "MTD",
  },
]);

export const LINK_FILTER_OPTIONS = Object.freeze([
  { 
    value: LINK_FILTER_ALL, 
    label: "All", 
    alwaysShow: true, 
    group: null 
  },
  /*
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
    label: "Eve Processed",
    title: "Shows processed network routes with additional metadata",
    group: null,
    requiredEdgeCategories: [EDGE_CATEGORY_EVE_ROUTE, EDGE_CATEGORY_EVE_CHILD],
  },
  {
    value: LINK_FILTER_DEFAULT,
    label: "Routes & Parent\u2013Child",
    title: "Shows parent-child relationships and routes w/link quality indicators",
    group: null,
    requiredEdgeCategories: [
      EDGE_CATEGORY_DEFAULT_CHILDREN,
      EDGE_CATEGORY_OTBR_CHILD,      
      EDGE_CATEGORY_EVE_CHILD,
      EDGE_CATEGORY_EVE_NATIVE_CHILD,
      EDGE_CATEGORY_DEFAULT_1,
      EDGE_CATEGORY_DEFAULT_2,
      EDGE_CATEGORY_DEFAULT_3,
      EDGE_CATEGORY_OTBR_ROUTE,
    ],
  },
  */

  // ── Link Type filters ─────────────────────────────────────────────────
   {
    value: LINK_FILTER_PARENT_CHILD,
    label: "Parent\u2013Child",
    group: "Link Types",
    requiredEdgeCategories: [
      EDGE_CATEGORY_DEFAULT_CHILDREN,
      EDGE_CATEGORY_OTBR_CHILD,
      EDGE_CATEGORY_EVE_CHILD,
      EDGE_CATEGORY_EVE_NATIVE_CHILD,
    ],
  },
  {
    value: LINK_FILTER_ROUTES,
    label: "Routes",
    title: "Shows Routes",
    group: "Link Types",
    requiredEdgeCategories: [
      EDGE_CATEGORY_OTBR_ROUTE,
      EDGE_CATEGORY_DEFAULT_1,
      EDGE_CATEGORY_DEFAULT_2,
      EDGE_CATEGORY_DEFAULT_3,
    ],
  },  
  {
    value: LINK_FILTER_ROUTER_NEIGHBOR,
    label: "Router Neighbors",
    group: "Link Types",
    requiredEdgeCategories: [
      EDGE_CATEGORY_OTBR_ROUTE,
      EDGE_CATEGORY_ROUTER_NEIGHBOR,
    ],
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
  { 
    value: LINK_FILTER_LQ_NONE, 
    label: "No LQ Data / Unknown", 
    alwaysShow: true, 
    group: "Link Quality" 
  },
]);

export const DIAGNOSTIC_FILTER_OPTIONS = Object.freeze([
  { value: "all", label: "All Rows", alwaysShow: true, group: null },
  // ── Mac counters ──────────────────────────────────────────────────────
  // ── Mac total errors ratio ────────────────────────────────────────────
  {
    source: "macCounters",
    value: "mac-total-errors-ratio-medium",
    label: "Mac Total Errors Ratio: Medium (>= 1.0)",
    group: "Mac Total Errors Ratio",
    topoNodeField: "ifTotalErrorsTotalPktsRatio",
    tableRowField: "macCounters.ifTotalErrorsTotalPktsRatio",
  },
  {
    source: "macCounters",
    value: "mac-total-errors-ratio-high",
    label: "Mac Total Errors Ratio: High (>= 5.0)",
    group: "Mac Total Errors Ratio",
    topoNodeField: "ifTotalErrorsTotalPktsRatio",
    tableRowField: "macCounters.ifTotalErrorsTotalPktsRatio",
  },
  // ── Mac total discards ratio ──────────────────────────────────────────
  {
    source: "macCounters",
    value: "mac-total-discards-ratio-medium",
    label: "Mac Total Discards Ratio: Medium (>= 2.0)",
    group: "Mac Total Discards Ratio",
    topoNodeField: "ifTotalDiscardsTotalPktsRatio",
    tableRowField: "macCounters.ifTotalDiscardsTotalPktsRatio",
  },
  {
    source: "macCounters",
    value: "mac-total-discards-ratio-high",
    label: "Mac Total Discards Ratio: High (>= 8.0)",
    group: "Mac Total Discards Ratio",
    topoNodeField: "ifTotalDiscardsTotalPktsRatio",
    tableRowField: "macCounters.ifTotalDiscardsTotalPktsRatio",
  },

  // ── Mle counters ──────────────────────────────────────────────────────
  {
    source: "mlecounters",
    value: "medium-partition-changes",
    label: "Partition Changes: Medium (>= 2)",
    group: "Mle Partition Changes",
    topoNodeField: "partIdChangesCount",
    tableRowField: "mleCounters.partIdChangesCount",
  },
  {
    source: "mlecounters",
    value: "high-partition-changes",
    label: "Partition Changes: High (>= 5)",
    group: "Mle Partition Changes",
    topoNodeField: "partIdChangesCount",
    tableRowField: "mleCounters.partIdChangesCount",
  },
  {
    source: "mlecounters",
    value: "medium-parent-changes",
    label: "Parent Changes: Medium (>= 2)",
    group: "MLE Parent Changes",
    topoNodeField: "newParentCount",
    tableRowField: "mleCounters.newParentCount",
  },
  {
    source: "mlecounters",
    value: "high-parent-changes",
    label: "Parent Changes: High (>= 5)",
    group: "MLE Parent Changes",
    topoNodeField: "newParentCount",
    tableRowField: "mleCounters.newParentCount",
  },
 
  // ── Mle better partition attach ───────────────────────────────────────
  {
    source: "mlecounters",
    value: "mle-better-partition-medium",
    label: "Better Partition Attach: Medium (>= 2)",
    group: "Mle Better Partition Attach",
    topoNodeField: "betterPartIdAttachAttemptsCount",
    tableRowField: "mleCounters.betterPartIdAttachAttemptsCount",
  },
  {
    source: "mlecounters",
    value: "mle-better-partition-high",
    label: "Better Partition Attach: High (>= 5)",
    group: "Mle Better Partition Attach",
    topoNodeField: "betterPartIdAttachAttemptsCount",
    tableRowField: "mleCounters.betterPartIdAttachAttemptsCount",
  },
  // ── Mle total parent partition changes ────────────────────────────────
  {
    source: "mlecounters",
    value: "mle-total-parent-partition-medium",
    label: "Total Parent Partition Changes: Medium (>= 3)",
    group: "Mle Total Parent Partition Changes",
    topoNodeField: "totalParentPartitionChangesCount",
    tableRowField: "mleCounters.totalParentPartitionChangesCount",
  },
  {
    source: "mlecounters",
    value: "mle-total-parent-partition-high",
    label: "Total Parent Partition Changes: High (>= 8)",
    group: "Mle Total Parent Partition Changes",
    topoNodeField: "totalParentPartitionChangesCount",
    tableRowField: "mleCounters.totalParentPartitionChangesCount",
  },

  // ── link_quality ──────────────────────────────────────────────────────
  // ── Router-neighbor: frame error rate ─────────────────────────────────
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-frame-low",
    label: "Router Neighbor Err Rate Frame: Low (>= 2%)",
    group: "Router Neighbor Err Rate Frame",
    topoNodeField: "router_neighbor_max_err_rate_frame_pct",
    tableNeighborField: "frameErrorRate",
  },
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-frame-medium",
    label: "Router Neighbor Err Rate Frame: Medium (>= 5%)",
    group: "Router Neighbor Err Rate Frame",
    topoNodeField: "router_neighbor_max_err_rate_frame_pct",
    tableNeighborField: "frameErrorRate",
  },
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-frame-high",
    label: "Router Neighbor Err Rate Frame: High (>= 10%)",
    group: "Router Neighbor Err Rate Frame",
    topoNodeField: "router_neighbor_max_err_rate_frame_pct",
    tableNeighborField: "frameErrorRate",
  },
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-frame-critical",
    label: "Router Neighbor Err Rate Frame: Critical (>= 30%)",
    group: "Router Neighbor Err Rate Frame",
    topoNodeField: "router_neighbor_max_err_rate_frame_pct",
    tableNeighborField: "frameErrorRate",
  },
  {
    value: "router-neighbor-err-rate-frame-critical",
    label: "Critical (>= 30%)",
    group: "Router Neighbor Err Rate Frame",
    topoNodeField: "router_neighbor_max_err_rate_frame_pct",
    tableNeighborField: "frameErrorRate",
  },
  // ── Router-neighbor: message error rate ───────────────────────────────
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-msg-low",
    label: "Router Neighbor Err Rate Msg: Low (>= 2%)",
    group: "Router Neighbor Err Rate Msg",
    topoNodeField: "router_neighbor_max_err_rate_msg_pct",
    tableNeighborField: "messageErrorRate",
  },
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-msg-medium",
    label: "Router Neighbor Err Rate Msg: Medium (>= 5%)",
    group: "Router Neighbor Err Rate Msg",
    topoNodeField: "router_neighbor_max_err_rate_msg_pct",
    tableNeighborField: "messageErrorRate",
  },
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-msg-high",
    label: "Router Neighbor Err Rate Msg: High (>= 10%)",
    group: "Router Neighbor Err Rate Msg",
    topoNodeField: "router_neighbor_max_err_rate_msg_pct",
    tableNeighborField: "messageErrorRate",
  },
  {
    source: "link_quality",
    value: "router-neighbor-err-rate-msg-critical",
    label: "Router Neighbor Err Rate Msg: Critical (>= 30%)",
    group: "Router Neighbor Err Rate Msg",
    topoNodeField: "router_neighbor_max_err_rate_msg_pct",
    tableNeighborField: "messageErrorRate",
  },
  {
    value: "router-neighbor-err-rate-msg-critical",
    label: "Critical (>= 30%)",
    group: "Router Neighbor Err Rate Msg",
    topoNodeField: "router_neighbor_max_err_rate_msg_pct",
    tableNeighborField: "messageErrorRate",
  },
  // ── Router-neighbor: RSS ──────────────────────────────────────────────
  {
    source: "link_quality",
    value: "router-neighbor-rss-very-low",
    label: "Router Neighbor RSS Ave: Bad (< -80 dBm)",
    group: "Router Neighbor RSS Ave",
    topoNodeField: "router_neighbor_has_rss_very_low",
    tableNeighborField: "averageRssi",
  },
  {
    source: "link_quality",
    value: "router-neighbor-rss-low",
    label: "Router Neighbor RSS Ave: Fair (-70 dBm To -80 dBm)",
    group: "Router Neighbor RSS Ave",
    topoNodeField: "router_neighbor_has_rss_low",
    tableNeighborField: "averageRssi",
  },
  {
    source: "link_quality",
    value: "router-neighbor-rss-medium",
    label: "Router Neighbor RSS Ave: Good (-60 dBm To -70 dBm)",
    group: "Router Neighbor RSS Ave",
    topoNodeField: "router_neighbor_has_rss_medium",
    tableNeighborField: "averageRssi",
  },
  {
    source: "link_quality",
    value: "router-neighbor-rss-high",
    label: "Router Neighbor RSS Ave: Excellent (> -60 dBm)",
    group: "Router Neighbor RSS Ave",
    topoNodeField: "router_neighbor_has_rss_high",
    tableNeighborField: "averageRssi",
  },
  // ── Router link quality distribution ─────────────────────────────────
  {
    source: "link_quality",
    value: "low-lq3-ratio-medium",
    label: "Router Link Quality Ratio: Low LQ3 (< 60%)",
    group: "Router Link Quality Distribution",
    topoNodeField: "lq3Ratio",
  },
  {
    source: "link_quality",
    value: "low-lq3-ratio-high",
    label: "Router Link Quality Ratio: Very Low LQ3 (< 35%)",
    group: "Router Link Quality Distribution",
    topoNodeField: "lq3Ratio",
  },
  {
    source: "link_quality",
    value: "high-lq1-ratio-medium",
    label: "Router Link Quality Ratio: High LQ1 (>= 20%)",
    group: "Router Link Quality Distribution",
    topoNodeField: "lq1Ratio",
  },
  {
    source: "link_quality",
    value: "high-lq1-ratio-high",
    label: "Router Link Quality Ratio: Very High LQ1 (>= 35%)",
    group: "Router Link Quality Distribution",
    topoNodeField: "lq1Ratio",
  },
  // ── Children link quality ─────────────────────────────────────────────
  {
    source: "link_quality",
    value: "child-lq-medium",
    label: "Children Link: Child LQ <= 2",
    group: "Children Link Quality",
    topoNodeField: "hasChildLqMedium",
  },
  {
    source: "link_quality",
    value: "child-lq-poor",
    label: "Children Link: Child LQ = 1",
    group: "Children Link Quality",
    topoNodeField: "hasChildLqPoor",
  },
  // ── Router child err rate frame ───────────────────────────────────────
  {
    source: "link_quality",
    value: "router-child-err-rate-frame-medium",
    label: "Router Child Err Rate Frame: Medium (>= 10%)",
    group: "Router Child Err Rate Frame",
    topoNodeField: "router_child_max_err_rate_frame_pct",
    tableChildField: "frameErrorRate",
  },
  {
    source: "link_quality",
    value: "router-child-err-rate-frame-high",
    label: "Router Child Err Rate Frame: High (>= 25%)",
    group: "Router Child Err Rate Frame",
    topoNodeField: "router_child_max_err_rate_frame_pct",
    tableChildField: "frameErrorRate",
  },
  // ── Router child err rate msg ─────────────────────────────────────────
  {
    source: "link_quality",
    value: "router-child-err-rate-msg-low",
    label: "Router Child Err Rate Msg: Low (>= 1%)",
    group: "Router Child Err Rate Msg",
    topoNodeField: "router_child_max_err_rate_msg_pct",
    tableChildField: "messageErrorRate",
  },
  {
    source: "link_quality",
    value: "router-child-err-rate-msg-high",
    label: "Router Child Err Rate Msg: High (>= 5%)",
    group: "Router Child Err Rate Msg",
    topoNodeField: "router_child_max_err_rate_msg_pct",
    tableChildField: "messageErrorRate",
  },
  // ── Router child RSS ──────────────────────────────────────────────────
  {
    source: "link_quality",
    value: "router-child-rss-very-low",
    label: "Router Child RSS Ave: Bad (< -80 dBm)",
    group: "Router Child RSS Ave",
    topoNodeField: "router_child_has_rss_very_low",
    tableChildField: "averageRssi",
  },
  {
    source: "link_quality",
    value: "router-child-rss-low",
    label: "Router Child RSS Ave: Fair (-80 to -70 dBm)",
    group: "Router Child RSS Ave",
    topoNodeField: "router_child_has_rss_low",
    tableChildField: "averageRssi",
  },
  {
    source: "link_quality",
    value: "router-child-rss-margin-low",
    label: "Router Child RSS: Low Margin (< 20 dB)",
    group: "Router Child RSS Margin",
    topoNodeField: "router_child_has_rss_margin_low",
    tableChildField: "linkMargin",
  },
  // ── Router child queued messages ──────────────────────────────────────
  {
    source: "link_quality",
    value: "router-child-has-queued-msgs",
    label: "Router Child Has Queued Messages",
    group: "Router Child Queued Messages",
    topoNodeField: "router_child_has_queued_msgs",
    tableChildField: "queuedMessageCount",
  },
 
  // ── time_statistics────────────────────────────────────────────────────
  // ── Time: FTD Router uptime % ─────────────────────────────────────────
  {
    source: "time_statistics",
    value: "ftd-router-pct-low",
    label: "FTD Router < 80% Uptime",
    group: "Time FTD Router Uptime",
    topoNodeField: "routerPct",
    tableRowField: "timeStatistics.routerPct",
  },
  {
    source: "time_statistics",
    value: "ftd-router-pct-very-low",
    label: "Router Uptime: FTD Router < 50% Uptime",
    group: "Time FTD Router Uptime",
    topoNodeField: "routerPct",
    tableRowField: "timeStatistics.routerPct",
  },
  // ── Time: Detached/Disabled % ─────────────────────────────────────────
  {
    source: "time_statistics",
    value: "detached-disabled-pct-medium",
    label: "Time Detached/Disabled: Medium (>= 1%)",
    group: "Time Detached Disabled",
    topoNodeField: "detachedDisabledPct",
    tableRowField: "timeStatistics.detachedDisabledPct",
  },
  {
    source: "time_statistics",
    value: "detached-disabled-pct-high",
    label: "Time Detached/Disabled: High (>= 5%)",
    group: "Time Detached Disabled",
    topoNodeField: "detachedDisabledPct",
    tableRowField: "timeStatistics.detachedDisabledPct",
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

// ── Phase 1: physics profile presets for dry-run comparisons ─────────────────

export const PHYSICS_PROFILE_MESH_BASELINE = "mesh-baseline";
export const PHYSICS_PROFILE_MESH_DENSE = "mesh-dense";
export const PHYSICS_PROFILE_MESH_BALANCED = "mesh-balanced";
export const PHYSICS_PROFILE_MESH_SPARSE = "mesh-sparse";
export const PHYSICS_PROFILE_MESH_RING = "mesh-ring";
export const PHYSICS_PROFILE_MESH_COMPACT = "mesh-compact";
export const PHYSICS_PROFILE_MESH_TREE_HORIZONTAL = "mesh-tree-horizontal";
export const PHYSICS_PROFILE_MESH_TREE_VERTICAL = "mesh-tree-vertical";

export const PHYSICS_PROFILES = Object.freeze({
  [PHYSICS_PROFILE_MESH_BASELINE]: Object.freeze({
    label: "Mesh Baseline",
    barnesHut: Object.freeze({
      gravitationalConstant: -9500,
      centralGravity: 0.15,
      springLength: 380,
      springConstant: 0.01,
      damping: 0.22,
      avoidOverlap: 1.5,
    }),
    stabilization: Object.freeze({ enabled: true, iterations: 1500, updateInterval: 25 }),
  }),
  [PHYSICS_PROFILE_MESH_DENSE]: Object.freeze({
    label: "Mesh Dense",
    barnesHut: Object.freeze({
      gravitationalConstant: -12000,
      centralGravity: 0.10,
      springLength: 300,
      springConstant: 0.012,
      damping: 0.30,
      avoidOverlap: 1.8,
    }),
    stabilization: Object.freeze({ enabled: true, iterations: 2200, updateInterval: 25 }),
  }),
  [PHYSICS_PROFILE_MESH_BALANCED]: Object.freeze({
    label: "Hub Spoke",
    barnesHut: Object.freeze({
      gravitationalConstant: -10000,
      centralGravity: 0.14,
      springLength: 360,
      springConstant: 0.011,
      damping: 0.25,
      avoidOverlap: 1.5,
    }),
    stabilization: Object.freeze({ enabled: true, iterations: 1700, updateInterval: 25 }),
  }),
  [PHYSICS_PROFILE_MESH_SPARSE]: Object.freeze({
    label: "Mesh Sparse",
    barnesHut: Object.freeze({
      gravitationalConstant: -8000,
      centralGravity: 0.22,
      springLength: 260,
      springConstant: 0.014,
      damping: 0.20,
      avoidOverlap: 1.1,
    }),
    stabilization: Object.freeze({ enabled: true, iterations: 1100, updateInterval: 25 }),
  }),
  [PHYSICS_PROFILE_MESH_RING]: Object.freeze({
    label: "Mesh Ring",
    barnesHut: Object.freeze({
      gravitationalConstant: -6000,
      centralGravity: 0.01,
      springLength: 180,
      springConstant: 0.04,
      damping: 0.45,
      avoidOverlap: 1.2,
    }),
    stabilization: Object.freeze({ enabled: true, iterations: 600, updateInterval: 25 }),
  }),
  [PHYSICS_PROFILE_MESH_COMPACT]: Object.freeze({
    label: "Mesh Compact",
    // Starts from mesh-balanced and then tuned for stronger separation and
    // parent-local child clustering in hybrid seeded layouts.
    barnesHut: Object.freeze({
      gravitationalConstant: -14500,
      centralGravity: 0.02,
      springLength: 470,
      springConstant: 0.0075,
      damping: 0.36,
      avoidOverlap: 2.5,
    }),
    stabilization: Object.freeze({ enabled: true, iterations: 2800, updateInterval: 25 }),
  }),
  [PHYSICS_PROFILE_MESH_TREE_HORIZONTAL]: Object.freeze({
    label: "Mesh Tree Horizontal",
    // Tuned for banded seeded layouts (left-to-right zone separation).
    barnesHut: Object.freeze({
      gravitationalConstant: -13500,
      centralGravity: 0.04,
      springLength: 420,
      springConstant: 0.008,
      damping: 0.34,
      avoidOverlap: 2.4,
    }),
    stabilization: Object.freeze({ enabled: true, iterations: 2600, updateInterval: 25 }),
  }),
  [PHYSICS_PROFILE_MESH_TREE_VERTICAL]: Object.freeze({
    label: "Mesh Tree Vertical",
    // Tuned for banded seeded layouts (top-to-bottom zone separation).
    barnesHut: Object.freeze({
      gravitationalConstant: -13500,
      centralGravity: 0.04,
      springLength: 420,
      springConstant: 0.008,
      damping: 0.34,
      avoidOverlap: 2.4,
    }),
    stabilization: Object.freeze({ enabled: true, iterations: 2600, updateInterval: 25 }),
  }),
});

export function getPhysicsProfile(profileName) {
  const key = typeof profileName === "string" ? profileName.toLowerCase() : "";
  return PHYSICS_PROFILES[key] || PHYSICS_PROFILES[PHYSICS_PROFILE_MESH_BASELINE];
}

export function getPhysicsProfileLabel(profileName) {
  return getPhysicsProfile(profileName).label;
}

// ── Phase 3: isolated-node anchor A/B presets ───────────────────────────────

export const ISOLATED_ANCHOR_PRESET_A = "a";
export const ISOLATED_ANCHOR_PRESET_B = "b";

export const ISOLATED_ANCHOR_PRESETS = Object.freeze({
  [ISOLATED_ANCHOR_PRESET_A]: Object.freeze({
    label: "A",
    unknown: Object.freeze({ clusterLength: 60, anchorLength: 180 }),
    known: Object.freeze({ clusterLength: 110, anchorLength: 240 }),
  }),
  [ISOLATED_ANCHOR_PRESET_B]: Object.freeze({
    label: "B",
    unknown: Object.freeze({ clusterLength: 75, anchorLength: 150 }),
    known: Object.freeze({ clusterLength: 95, anchorLength: 200 }),
  }),
});

export function getIsolatedAnchorPreset(name) {
  const key = typeof name === "string" ? name.toLowerCase() : "";
  return ISOLATED_ANCHOR_PRESETS[key] || ISOLATED_ANCHOR_PRESETS[ISOLATED_ANCHOR_PRESET_A];
}

export function getIsolatedAnchorPresetLabel(name) {
  return getIsolatedAnchorPreset(name).label;
}

// ── Table column priority order ───────────────────────────────────────────────

/**
 * Ordered list of device record field names for table column priority.
 * 
 * Fields appear in the table view in this order (left to right).
 * The priority system organizes fields into 5 tiers:
 * 
 * - **TIER 1: Primary Identity** - Core device identifiers (rloc16, extAddress, deviceLabel, routerId)
 * - **TIER 2: Secondary Identity** - Additional identifiers (omrIpv6Addr, mlEidIid, room)
 * - **TIER 3: Device Role & Status** - Device type, role, and mode information
 * - **TIER 4: Topology & Connectivity** - Network topology, link quality, connectivity metrics
 * - **TIER 5: Advanced/Diagnostic** - Detailed diagnostics, vendor info, MLE/MAC counters
 * 
 * **Field Naming Conventions:**
 * - Uses camelCase-first ordering while preserving legacy snake_case aliases
 * - Both variants can appear (e.g., extAddress/extaddr, omrIpv6Addr/omr_ipv6_addr)
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
  "extAddress",
  "deviceLabel",
  "name",
  "routerId",
  "eui64",
  "id",
  "ID",
  
  // === TIER 2: Secondary Identity ===
  "omrIpv6Address",
  "mlEidIid",
  "room",
  "nextHop",
  "pathCost",
  "linkQualityIn",
  "linkQualityOut",
  "age",
  
  // === TIER 3: Device Role & Status ===
  "type",
  "Role",
  "br",
  "isRouter",
  "isBorderRouter",
  "isLeader",
  "leader",
  "isPrimaryBBR",
  "status",
  "mode.device",
  "mode.deviceTypeFTD",
  "ver",
  "version",
  "threadVersion",
  "threadStackVersion",
  "room",
  "icon",
  
  // === TIER 4: Topology & Connectivity ===
  "totalChildren",
  "hasChildren",
  "totalLinks",
  "totalLink3",
  "totalLink2",
  "totalLink1",
  "routerNeighborsCount",
  "childTableCount",
  "connectivity.activeRouters",
  "connectivity.linkQuality3",
  "connectivity.linkQuality2",
  "connectivity.linkQuality1",
  "leaderData.partitionId",
  "leaderData.leaderRouterId",
  
  // === TIER 5: Advanced/Diagnostic ===
  "icon",
  "scope",
  "vendorName",
  "vendorModel",
  "vendorSwVersion",
  "tlvValues",
  "macCounters.ifInErrorsPct",
  "macCounters.ifOutErrorsPct",
  "macCounters.ifInDiscardsPct",
  "macCounters.ifOutDiscardsPct",
  "mlecounters.partitionIdChanges",
  "mlecounters.betterPartitionAttachAttempts",
  "mlecounters.totalParentPartitionChanges",
  "mlecounters.parentChanges",
  "macCounters.ifTotalErrorsTotalPktsRatio",
  "macCounters.ifTotalDiscardsTotalPktsRatio",
  "timeStatistics.routerPct",
  "timeStatistics.detachedDisabledPct",
];
