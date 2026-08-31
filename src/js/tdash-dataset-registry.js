
// ── Datasource Registry ──────────────────────────────────────────────────────────

// Keep this list in sync with DATASET_REGISTRY source values.
export const DATASOURCE_REGISTRY = [
  { value: "otbr-cli", label: "otbr-cli", default_dataset_value: "merged_otbr_cli_meshdiag_networkdiag_multicast" },
  { value: "otbr-restapi", label: "otbr-restapi", default_dataset_value: "restapi_devices_diagnostics_list" },
  { value: "ha-matter-ws", label: "ha matter ws", default_dataset_value: "ha_matter_ws_topology" },
  { value: "eve", label: "eve app" },
  { value: "thread-tools", label: "thread tools app" },
  { value: "mdns", label: "mdns" },
  { value: "merged", label: "multi-source", default_dataset_value: "merged_otbr_cli_meshdiag_networkdiag_multicast" },
  { value: "system", label: "system" },
];


// ── Dataset Registry ──────────────────────────────────────────────────────────
//
// Each entry describes one selectable dataset.
//
// Fields:
//   value            — unique key used as <option value=>
//   label            — display text in the dropdown
//   group          — <optgroup> label string; null means no group.
//                    Consecutive entries sharing the same group string are
//                    placed inside one <optgroup>. Group labels must be
//                    unique within each registry.
//   files[]          — ordered list of JSON filenames to fetch
//   mergeStrategy    — 'none' | 'by-rloc16' | 'by-identity'
//                       'none'        → pass raw arrays straight to the adaptor
//                       'by-rloc16'   → merge all fetched arrays by rloc16 key
//                       'by-identity' → merge by rloc16, canonical extaddr, or omr_ipv6_addr
//   topologyMode     — which topology adaptor to call:
//                       'meshdiag-networkdiag' | 'merged-detailed' | 'eve'
//                       'router-table' | 'raw-array'
//   physicsProfile   — (legacy optional) physics engine profile override:
//                       'mesh-baseline' | 'mesh-dense' | 'mesh-balanced' | 'mesh-compact' | 'mesh-sparse' | 'mesh-ring'
//                       'mesh-tree-horizontal' | 'mesh-tree-vertical' (manual selector only in Phase 1 rollout)
//                       Precedence: manual user selection > dataset defaultPhysicsProfile
//   defaultLinkFilter — value pre-selected in #link-filter when this dataset loads
//   rowExtractor     — named payload extractor used for non-merged table rows
//   adaptor          — named topology adaptor
//   defaultPhysicsProfile — resolved automatic physics profile

export const DATASET_REGISTRY = [

  // otbr-cli
  // ── Single-file simple datasets (otbr-cli) ───  
  {
    source: "otbr-cli",
    value: "meshdiag_only",
    label: "Mesh Topology (meshdiag)",
    group: "Fast",
    files: ["td-otbr-cli-meshdiag-topology.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "meshdiag-networkdiag",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 6
  },

  // ── Single-file simple datasets (otbr-cli) ───
  {
    source: "otbr-cli",
    value: "networkdiag_multicast_network_only",
    label: "Network Diagnostics (multicast FTD)",
    group: "Fast",
    files: ["td-otbr-cli-networkdiag-multicast-network.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "meshdiag-networkdiag",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 15
  },

  // ── Multi-file merged (otbr-cli) ──
  {
    source: "otbr-cli",
    value: "merged_otbr_cli_meshdiag_networkdiag_multicast",
    label: "Mesh + FTD Diagnostics",
    group: "Versatile: more time",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-multicast-network.json"
    ],
    mergeStrategy: "by-identity",
    rowExtractor: "raw-array",
    adaptor: "meshdiag-networkdiag",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 30
  },

  // ── Multi-file merged (otbr-cli, mdns) ──
  {
    source: "otbr-cli",
    value: "merged_otbr_cli_meshdiag_networkdiag_multicast_mdns",
    label: "Mesh + FTD Diagnostics + mDNS",
    group: "Versatile: more time",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-multicast-network.json",
      "td-mdns-scopes-thread.json",
    ],
    mergeStrategy: "by-identity",
    rowExtractor: "raw-array",
    adaptor: "meshdiag-networkdiag",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 80
  },

  {
    source: "otbr-cli",
    value: "merged_otbr_cli_all_multicast_mdns",
    label: "Mesh + FTD + Neighbor/Child + mDNS",
    group: "Versatile: more time",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-multicast-network.json",
      "td-otbr-cli-meshdiag-router-neighbortables.json",
      "td-otbr-cli-meshdiag-router-childtables.json",
      "td-mdns-scopes-thread.json"
    ],
    mergeStrategy: "by-identity",
    rowExtractor: "raw-array",
    adaptor: "meshdiag-networkdiag",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 270
  },  

  {
    source: "otbr-cli",
    value: "router_neighbortables",
    label: "Router Neighbor Table",
    group: "Versatile: more time",
    files: ["td-otbr-cli-meshdiag-router-neighbortables.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "merged-detailed",
    defaultPhysicsProfile: "mesh-ring",
    topologyMode: "merged-detailed",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 90
  },
  {
    source: "otbr-cli",
    value: "router_childtables",
    label: "Router Child Table",
    group: "Versatile: more time",
    files: ["td-otbr-cli-meshdiag-router-childtables.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "merged-detailed",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "merged-detailed",
    physicsProfile: "mesh-compact",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 90
  },


  // ── Single-file simple datasets (otbr-cli) ───
  {
    source: "otbr-cli",
    value: "networkdiag_only",
    label: "Network Diagnostics (fetch-all)⏱️",
    group: "Detailed: most time",
    files: ["td-otbr-cli-networkdiag-fetch-all.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "meshdiag-networkdiag",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "meshdiag-networkdiag",
    physicsProfile: "mesh-compact",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 600
  }, 

  // ── Multi-file merged (otbr-cli) ──
  {
    source: "otbr-cli",
    value: "merged_otbr_cli_meshdiag_networkdiag_fetch_all_mdns",
    label: "Mesh + Diagnostics All + mDNS⏱️",
    group: "Detailed: most time",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-fetch-all.json",
      "td-mdns-scopes-thread.json"
    ],
    mergeStrategy: "by-identity",
    rowExtractor: "raw-array",
    adaptor: "meshdiag-networkdiag",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "meshdiag-networkdiag",
    physicsProfile: "mesh-compact",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 720
  },

  {
    source: "otbr-cli",
    value: "merged_otbr_cli_poll_all_mdns",
    label: "Mesh + Diag All + Neighbor/Child + mDNS⏱️",
    group: "Detailed: most time",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-fetch-all.json",
      "td-otbr-cli-meshdiag-router-neighbortables.json",
      "td-otbr-cli-meshdiag-router-childtables.json",
      "td-mdns-scopes-thread.json"
    ],
    mergeStrategy: "by-identity",
    rowExtractor: "raw-array",
    adaptor: "meshdiag-networkdiag",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "meshdiag-networkdiag",
    physicsProfile: "mesh-compact",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 900
  },

  {
    source: "otbr-cli",
    value: "merged_otbr_cli_topology_mdns",
    label: "Topology + mDNS⏱️",
    group: "Detailed: most time",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-fetch-all.json",
      "td-otbr-cli-meshdiag-router-neighbortables.json",
      "td-otbr-cli-meshdiag-router-childtables.json",
      "td-mdns-scopes-thread.json"
    ],
    mergeStrategy: "by-identity",
    rowExtractor: "raw-array",
    adaptor: "meshdiag-networkdiag",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "meshdiag-networkdiag",
    physicsProfile: "mesh-compact",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 900
  },

  // ── Single-file simple datasets (otbr-cli) ───
  {
    source: "otbr-cli",
    value: "router_table",
    label: "Router Table",
    group: "System",
    files: ["td-otbr-cli-router-table.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "router-table",
    defaultPhysicsProfile: "mesh-ring",
    topologyMode: "router-table",
    defaultView: "table",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1
  },

  // otbr-restapi
   // ── Multi-file topology datasets (otbr-restapi) ────────────
  {
    source: "otbr-restapi",
    value: "restapi_devices_diagnostics_list",
    label: "Devices + Diagnostics (list)",
    group: "Fast",
    files: [
      "td-otbr-restapi-devices-list.json", 
      "td-otbr-restapi-diagnostics-list.json"
    ],
    mergeStrategy: "by-identity",
    rowExtractor: "otbr-restapi",
    adaptor: "otbr-restapi",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 2
  },  
  // ── Single-file simple datasets ───
  {
    source: "otbr-restapi",
    value: "restapi_diagnostics_list",
    label: "Diagnostics (list)",
    group: "Fast",
    files: ["td-otbr-restapi-diagnostics-list.json"],
    mergeStrategy: "none",
    rowExtractor: "otbr-restapi",
    adaptor: "otbr-restapi",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1
  },

  // ── Single-file simple datasets ───
  {
    source: "otbr-restapi",
    value: "restapi_devices_list",
    label: "Devices (list)",
    group: "Fast",
    files: ["td-otbr-restapi-devices-list.json"],
    mergeStrategy: "none",
    rowExtractor: "otbr-restapi",
    adaptor: "otbr-restapi",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 1
  },
  
  // ── Single-file simple datasets ───
  {
    source: "otbr-restapi",
    value: "restapi_devices_fetch",
    label: "Devices (fetch)",
    group: "Versatile: more time",
    files: ["td-otbr-restapi-devices-fetch.json"],
    mergeStrategy: "none",
    rowExtractor: "otbr-restapi",
    adaptor: "otbr-restapi",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 30
  },

  // ── Multi-file topology datasets (otbr-restapi) ────────────
  {
    source: "otbr-restapi",
    value: "restapi_devices_fetch_diagnostics_fetch_all",
    label: "Devices Fetch + Diagnostics Fetch-All⏱️",
    group: "Versatile: more time",
    files: [
      "td-otbr-restapi-devices-fetch.json", 
      "td-otbr-restapi-diagnostics-fetch-all.json"
    ],
    mergeStrategy: "none",
    rowExtractor: "otbr-restapi",
    adaptor: "otbr-restapi",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1260
  },
  
  // ── Single-file simple datasets ───
  {
    source: "otbr-restapi",
    value: "restapi_diagnostics_fetch_all",
    label: "Diagnostics (fetch-all)⏱️",
    group: "Detailed: most time",
    files: ["td-otbr-restapi-diagnostics-fetch-all.json"],
    mergeStrategy: "by-identity",
    rowExtractor: "otbr-restapi",
    adaptor: "otbr-restapi",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1200
  },

  // ── Multi-file topology datasets (otbr-restapi) ────────────
  {
    source: "otbr-restapi",
    value: "restapi_mesh_diagnostics_fetch_all",
    label: "Mesh Diagnostics (fetch-all)⏱️",
    group: "Detailed: most time",
    files: ["td-otbr-restapi-mesh-diagnostics-fetch-all.json"],
    mergeStrategy: "by-identity",
    rowExtractor: "otbr-restapi",
    adaptor: "otbr-restapi",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 600
  },
  
  // ── Multi-file topology datasets (otbr-restapi) ────────────
  {
    source: "otbr-restapi",
    value: "restapi_devices_fetch_diagnostics_fetch_mesh-diagnostics-fetch_all",
    label: "Devices + Diagnostics + Mesh Diagnostics⏱️",
    group: "Detailed: most time",
    files: [
      "td-otbr-restapi-devices-fetch.json", 
      "td-otbr-restapi-diagnostics-fetch-all.json",
      "td-otbr-restapi-mesh-diagnostics-fetch-all.json"
    ],
    mergeStrategy: "by-identity",
    rowExtractor: "otbr-restapi",
    adaptor: "otbr-restapi",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "otbr_restapi",
    physicsProfile: "mesh-compact",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 2450
  },

  // ── Multi-file topology datasets (otbr-restapi) ────────────
  {
    source: "otbr-restapi",
    value: "restapi_devices_fetch_diagnostics_fetch_mesh-diagnostics-fetch_all_mdns_scopes_thread",
    label: "Devices + Diagnostics + Mesh Diagnostics + mDNS⏱️",
    group: "Detailed: most time",
    files: [
      "td-otbr-restapi-devices-fetch.json", 
      "td-otbr-restapi-diagnostics-fetch-all.json",
      "td-otbr-restapi-mesh-diagnostics-fetch-all.json",
      "td-mdns-scopes-thread.json"
    ],
    mergeStrategy: "by-identity",
    rowExtractor: "otbr-restapi",
    adaptor: "otbr-restapi",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "otbr_restapi",
    physicsProfile: "mesh-compact",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 2450
  },

 // ── Multi-file topology datasets (otbr-restapi) ────────────
  {
    source: "otbr-restapi",
    value: "restapi_topology_mdns_scopes_thread",
    label: "Topology + mDNS⏱️",
    group: "Detailed: most time",
    files: [
      "td-otbr-restapi-devices-fetch.json", 
      "td-otbr-restapi-diagnostics-fetch-all.json",
      "td-otbr-restapi-mesh-diagnostics-fetch-all.json",
      "td-mdns-scopes-thread.json"
    ],
    mergeStrategy: "by-identity",
    rowExtractor: "otbr-restapi",
    adaptor: "otbr-restapi",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "otbr_restapi",
    physicsProfile: "mesh-compact",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 2450
  },

  // ── Single-file simple datasets ───
  {
    source: "otbr-restapi",
    value: "restapi_actions_list",
    label: "Actions (list)",
    group: "System",
    files: ["td-otbr-restapi-actions-list.json"],
    mergeStrategy: "none",
    rowExtractor: "otbr-restapi",
    adaptor: "raw-array",
    defaultPhysicsProfile: "mesh-balanced",
    topologyMode: "raw-array",
    defaultView: "table",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 1
  },  

  // Home Assistant Matter Server
  {
    source: "ha-matter-ws",
    value: "ha_matter_ws_devices",
    label: "Devices",
    group: "Inventory",
    files: ["td-ha-matter-ws-devices-fetch-all.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "ha-matter-ws",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "ha-matter-ws",
    defaultView: "table",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 60
  },
  {
    source: "ha-matter-ws",
    value: "ha_matter_ws_diagnostics",
    label: "Diagnostics",
    group: "Diagnostics",
    files: ["td-ha-matter-ws-diagnostics-fetch-all.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "ha-matter-ws",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "ha-matter-ws",
    defaultView: "table",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 60
  },
  {
    source: "ha-matter-ws",
    value: "ha_matter_ws_mesh_diagnostics",
    label: "Mesh Diagnostics",
    group: "Topology",
    files: ["td-ha-matter-ws-mesh-diagnostics-fetch-all.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "ha-matter-ws",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "ha-matter-ws",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 60
  },
  {
    source: "ha-matter-ws",
    value: "ha_matter_ws_topology",
    label: "Topology",
    group: "Topology",
    files: ["td-ha-matter-ws-topology.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "ha-matter-ws",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "ha-matter-ws",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 60
  },

  // ── Single-file simple dataset ───
  {
    source: "eve",
    value: "eve_native_threadlayout",
    label: "Eve Layout (native)",
    group: "Native",
    files: ["Eve Thread Network Layout.evethreadlayout"],
    mergeStrategy: "none",
    rowExtractor: "eve-native",
    adaptor: "eve-native",
    defaultPhysicsProfile: "mesh-ring",
    topologyMode: "eve_native",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1
  },
  // ── Single-file simple dataset ───
  {
    source: "eve",
    value: "eve_processed_topology",
    label: "Eve Topology (processed)",
    group: "Processed",
    files: ["td-eve-topology.json"],
    mergeStrategy: "none",
    rowExtractor: "eve-processed",
    adaptor: "eve-enhanced",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "eve_enhanced",
    physicsProfile: "mesh-compact",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1
  },

  // ── Single-file simple datasets (thread group - thread tools app) ───
  {
    source: "thread-tools",
    value: "thread_tools_native",
    label: "Thread Tools (native)",
    group: "Native",
    files: ["diagnostics.json"],
    mergeStrategy: "none",
    rowExtractor: "thread-tools-native",
    adaptor: "thread-tools-native",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "thread_tools_native",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1
  },

  // mDNS
  {
    source: "mdns",
    value: "mdns_scopes_br",
    label: "mDNS Border Router Scope",
    group: "Versatile: more time",
    files: ["td-mdns-scopes-br.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "raw-array",
    defaultPhysicsProfile: "mesh-balanced",
    topologyMode: "raw-array",
    defaultLinkFilter: "default_links",
    defaultView: "table",
    estimateActionCostSecs: 60
  },
  {
    source: "mdns",
    value: "mdns_scopes_hap",
    label: "mDNS HomeKit (HAP) Scope",
    group: "Versatile: more time",
    files: ["td-mdns-scopes-hap.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "raw-array",
    defaultPhysicsProfile: "mesh-balanced",
    topologyMode: "raw-array",
    defaultLinkFilter: "default_links",
    defaultView: "table",
    estimateActionCostSecs: 60
  },
  {
    source: "mdns",
    value: "mdns_scopes_matter",
    label: "mDNS Matter Scope",
    group: "Versatile: more time",
    files: ["td-mdns-scopes-matter.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "raw-array",
    defaultPhysicsProfile: "mesh-balanced",
    topologyMode: "raw-array",
    defaultLinkFilter: "default_links",
    defaultView: "table",
    estimateActionCostSecs: 60
  },
  // ── Single-file simple datasets (mdns) ───
  {
    source: "mdns",
    value: "mdns_scopes_thread",
    label: "mDNS Thread Scopes (all)",
    group: "Detailed: most time",
    files: ["td-mdns-scopes-thread.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "raw-array",
    defaultPhysicsProfile: "mesh-balanced",
    topologyMode: "raw-array",
    defaultLinkFilter: "default_links",
    defaultView: "table",
    estimateActionCostSecs: 60
  },

  // ── Multi-file topology datasets (otbr-cli, otbr-restapi) ────────────
  {
    source: "merged",
    value: "merged_otbr_cli_otbr_restapi",
    label: "Topology Dynamic Merge: CLI + REST + mDNS",
    group: null,
    files: [
      "td-static-extaddr-device-label.json",
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-fetch-all.json",
      "td-otbr-restapi-devices-list.json",
      "td-otbr-restapi-diagnostics-list.json",
      "td-mdns-scopes-thread.json"
    ],
    mergeStrategy: "by-identity",
    rowExtractor: "raw-array",
    adaptor: "meshdiag-networkdiag",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "meshdiag-networkdiag",
    physicsProfile: "mesh-compact",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 720
  },

  // ── Merged (all nodes) ─
  {
    source: "merged",
    value: "merged_all_deep_wide_otbr_cli_restapi_eve",
    label: "Topology Premerged Multi-Source",
    group: null,
    files: [
      "td-merged-topology-all.json"
    ],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "merged-detailed",
    defaultPhysicsProfile: "mesh-compact",
    topologyMode: "merged-detailed",
    physicsProfile: "mesh-compact",
    defaultView: "topology",
    defaultLinkFilter: "default_links",
    estimateActionCostSecs: 1
  },

  // ── Single-file simple datasets (system) ───
  {
    source: "system",
    value: "static_extaddr_device_label",
    label: "ExtAddr to Device Label Map",
    group: null,
    files: ["td-static-extaddr-device-label.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "raw-array",
    defaultPhysicsProfile: "mesh-balanced",
    topologyMode: "raw-array",
    defaultLinkFilter: "default_links",
    defaultView: "table",
    estimateActionCostSecs: 1
  }
];

const KNOWN_DATASET_FILES = new Set([
  "Eve Thread Network Layout.evethreadlayout",
  "diagnostics.json",
  "td-eve-topology.json",
  "td-ha-matter-ws-devices-fetch-all.json",
  "td-ha-matter-ws-diagnostics-fetch-all.json",
  "td-ha-matter-ws-mesh-diagnostics-fetch-all.json",
  "td-ha-matter-ws-topology.json",
  "td-mdns-scopes-br.json",
  "td-mdns-scopes-hap.json",
  "td-mdns-scopes-matter.json",
  "td-mdns-scopes-thread.json",
  "td-merged-topology-all.json",
  "td-otbr-cli-meshdiag-router-childtables.json",
  "td-otbr-cli-meshdiag-router-neighbortables.json",
  "td-otbr-cli-meshdiag-topology.json",
  "td-otbr-cli-networkdiag-fetch-all.json",
  "td-otbr-cli-networkdiag-multicast-network.json",
  "td-otbr-cli-router-table.json",
  "td-otbr-restapi-actions-list.json",
  "td-otbr-restapi-devices-fetch.json",
  "td-otbr-restapi-devices-list.json",
  "td-otbr-restapi-diagnostics-fetch-all.json",
  "td-otbr-restapi-diagnostics-list.json",
  "td-otbr-restapi-mesh-diagnostics-fetch-all.json",
  "td-static-extaddr-device-label.json",
]);

const MERGE_STRATEGY_IDS = new Set(["none", "by-rloc16", "by-identity"]);
const ROW_EXTRACTOR_IDS = new Set([
  "raw-array",
  "eve-native",
  "eve-processed",
  "thread-tools-native",
  "otbr-restapi",
]);
const ADAPTOR_IDS = new Set([
  "meshdiag-networkdiag",
  "merged-detailed",
  "eve-enhanced",
  "eve-native",
  "thread-tools-native",
  "otbr-restapi",
  "ha-matter-ws",
  "router-table",
  "raw-array",
]);
const PHYSICS_PROFILE_IDS = new Set([
  "mesh-baseline",
  "mesh-dense",
  "mesh-balanced",
  "mesh-compact",
  "mesh-sparse",
  "mesh-ring",
  "mesh-tree-horizontal",
  "mesh-tree-vertical",
]);

const REQUIRED_EXTRACTOR_BY_ADAPTOR = Object.freeze({
  "eve-enhanced": "eve-processed",
  "eve-native": "eve-native",
  "thread-tools-native": "thread-tools-native",
  "otbr-restapi": "otbr-restapi",
});

export function validateDatasetRegistry(registry) {
  if (!Array.isArray(registry)) throw new Error("Dataset registry must be an array.");

  const values = new Set();
  registry.forEach((entry, index) => {
    const label = entry?.value || `entry ${index}`;
    if (!entry?.value || values.has(entry.value)) {
      throw new Error(`Duplicate dataset value: ${label}`);
    }
    values.add(entry.value);

    if (!Array.isArray(entry.files) || entry.files.length === 0) {
      throw new Error(`Dataset ${label} must define a non-empty files array.`);
    }
    entry.files.forEach((file) => {
      if (!KNOWN_DATASET_FILES.has(file)) {
        throw new Error(`Dataset ${label} references unknown file: ${file}`);
      }
    });
    if (!MERGE_STRATEGY_IDS.has(entry.mergeStrategy)) {
      throw new Error(`Dataset ${label} has unknown merge strategy: ${entry.mergeStrategy}`);
    }
    if (!ROW_EXTRACTOR_IDS.has(entry.rowExtractor)) {
      throw new Error(`Dataset ${label} has unknown row extractor: ${entry.rowExtractor}`);
    }
    if (!ADAPTOR_IDS.has(entry.adaptor)) {
      throw new Error(`Dataset ${label} has unknown adaptor: ${entry.adaptor}`);
    }
    if (!PHYSICS_PROFILE_IDS.has(entry.defaultPhysicsProfile)) {
      throw new Error(`Dataset ${label} has unknown default physics profile: ${entry.defaultPhysicsProfile}`);
    }
    const requiredExtractor = REQUIRED_EXTRACTOR_BY_ADAPTOR[entry.adaptor];
    if (requiredExtractor && entry.rowExtractor !== requiredExtractor) {
      throw new Error(
        `Dataset ${label} has unsupported adaptor/row extractor combination: `
        + `${entry.adaptor}/${entry.rowExtractor}`,
      );
    }
    if (entry.physicsProfile && entry.physicsProfile !== entry.defaultPhysicsProfile) {
      throw new Error(`Dataset ${label} has conflicting physics profile identifiers.`);
    }
  });

  return registry;
}

validateDatasetRegistry(DATASET_REGISTRY);
