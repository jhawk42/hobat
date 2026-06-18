
// ── Datasource Registry ──────────────────────────────────────────────────────────

// Keep this list in sync with DATASET_REGISTRY source values.
export const DATASOURCE_REGISTRY = [
  { value: "otbr-cli", label: "otbr-cli" },
  { value: "otbr-restapi", label: "otbr-restapi" },
  { value: "eve", label: "eve" },
  { value: "mdns", label: "mdns" },
  { value: "merged", label: "multi-source" },
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
//   physicsProfile   — (optional) physics engine profile override:
//                       'mesh-baseline' | 'mesh-dense' | 'mesh-balanced' | 'mesh-compact' | 'mesh-sparse' | 'mesh-ring'
//                       If omitted, auto-selected based on topologyMode.
//                       Precedence: manual user selection > dataset physicsProfile > topologyMode mapping
//   defaultLinkFilter — value pre-selected in #link-filter when this dataset loads

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
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
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
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 16
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
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
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
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
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
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 270
  },  

  {
    source: "otbr-cli",
    value: "router_neighbortables",
    label: "Router Neighbor Table",
    group: "Versatile: more time",
    files: ["td-otbr-cli-meshdiag-router-neighbortables.json"],
    mergeStrategy: "none",
    topologyMode: "merged-detailed",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 90
  },
  {
    source: "otbr-cli",
    value: "router_childtables",
    label: "Router Child Table",
    group: "Versatile: more time",
    files: ["td-otbr-cli-meshdiag-router-childtables.json"],
    mergeStrategy: "none",
    topologyMode: "merged-detailed",
    physicsProfile: "mesh-compact",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
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
    topologyMode: "meshdiag-networkdiag",
    physicsProfile: "mesh-ring",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
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
    topologyMode: "meshdiag-networkdiag",
    physicsProfile: "mesh-ring",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
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
    topologyMode: "meshdiag-networkdiag",
    physicsProfile: "mesh-ring",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
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
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
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
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 6
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
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 606
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
    mergeStrategy: "none",
    topologyMode: "otbr_restapi",
    physicsProfile: "mesh-ring",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1206
  },

  // ── Single-file simple datasets ───
  {
    source: "otbr-restapi",
    value: "restapi_diagnostics_fetch_all",
    label: "Diagnostics (fetch-all)⏱️",
    group: "Detailed: most time",
    files: ["td-otbr-restapi-diagnostics-fetch-all.json"],
    mergeStrategy: "by-identity",
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 600
  },

  // ── Multi-file topology datasets (otbr-restapi) ────────────
  {
    source: "otbr-restapi",
    value: "restapi_mesh_diagnostics_fetch_all",
    label: "Mesh Diagnostics (fetch-all)⏱️",
    group: "Detailed: most time",
    files: ["td-otbr-restapi-mesh-diagnostics-fetch-all.json"],
    mergeStrategy: "by-identity",
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 600
  },
  // ── Single-file simple datasets ───
  {
    source: "otbr-restapi",
    value: "restapi_actions_list",
    label: "Actions (list)",
    group: "System",
    files: ["td-otbr-restapi-actions-list.json"],
    mergeStrategy: "none",
    topologyMode: "raw-array",
    defaultView: "table",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1
  },

  // ── Single-file simple dataset ───
  {
    source: "eve",
    value: "eve_native_threadlayout",
    label: "Eve Layout (native)",
    group: "Native",
    files: ["Eve Thread Network Layout.evethreadlayout"],
    mergeStrategy: "none",
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
    topologyMode: "eve_enhanced",
    physicsProfile: "mesh-ring",
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
    topologyMode: "raw-array",
    defaultLinkFilter: "all_links",
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
    topologyMode: "raw-array",
    defaultLinkFilter: "all_links",
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
    topologyMode: "raw-array",
    defaultLinkFilter: "all_links",
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
    topologyMode: "raw-array",
    defaultLinkFilter: "all_links",
    defaultView: "table",
    estimateActionCostSecs: 60
  },

  // ── Merged (all nodes) ─
  {
    source: "merged",
    value: "merged_all_deep_wide_otbr_cli_restapi_eve",
    label: "Premerged Multi-Source Topology",
    group: null,
    files: [
      "td-merged-topology-all.json"
    ],
    mergeStrategy: "none",
    topologyMode: "merged-detailed",
    physicsProfile: "mesh-ring",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1
  },

  // ── Multi-file topology datasets (otbr-cli, otbr-restapi) ────────────
  {
    source: "merged",
    value: "merged_otbr_cli_otbr_restapi",
    label: "Dynamic Merge: CLI + REST + mDNS",
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
    topologyMode: "meshdiag-networkdiag",
    physicsProfile: "mesh-ring",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 720
  },

  // ── Single-file simple datasets (system) ───
  {
    source: "system",
    value: "static_extaddr_device_label",
    label: "ExtAddr to Device Label Map",
    group: null,
    files: ["td-static-extaddr-device-label.json"],
    mergeStrategy: "none",
    topologyMode: "raw-array",
    defaultLinkFilter: "all_links",
    defaultView: "table",
    estimateActionCostSecs: 1
  }
];
