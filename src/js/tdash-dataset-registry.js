
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
//   defaultLinkFilter — value pre-selected in #link-filter when this dataset loads

export const DATASET_REGISTRY = [

  // otbr-cli
  // ── Single-file simple datasets (otbr-cli) ───  
  {
    source: "otbr-cli",
    value: "meshdiag_only",
    label: "Mesh topology [meshdiag md]",
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
    label: "Device topology [network multicast FTD ndmc]",
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
    label: "Device & Mesh topology [FTD ndmc,md]",
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
    label: "Device & Mesh topology w/mdns [md,FTD ndmc,mdns] ",
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
    label: "Device & Mesh topology neighbors, children w/mdns [md,FTD ndmc,mdn,mdc,mdns] ⏱️",
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
    label: "Meshdiag neighbors (mdn)⏱️",
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
    label: "Meshdiag children (mdc)⏱️",
    group: "Versatile: more time",
    files: ["td-otbr-cli-meshdiag-router-childtables.json"],
    mergeStrategy: "none",
    topologyMode: "merged-detailed",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 90
  },


  // ── Single-file simple datasets (otbr-cli) ───
  {
    source: "otbr-cli",
    value: "networkdiag_only",
    label: "Device topology all [network fetch all (ndfa)]⏱️",
    group: "Detailed: most time",
    files: ["td-otbr-cli-networkdiag-fetch-all.json"],
    mergeStrategy: "none",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 600
  }, 

  // ── Multi-file merged (otbr-cli) ──
  {
    source: "otbr-cli",
    value: "merged_otbr_cli_meshdiag_networkdiag_fetch_all_mdns",
    label: "Device topology all w/mdns [md, ndfa, mdns] ⏱️",
    group: "Detailed: most time",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-fetch-all.json",
      "td-mdns-scopes-thread.json"
    ],
    mergeStrategy: "by-identity",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 720
  },

  {
    source: "otbr-cli",
    value: "merged_otbr_cli_poll_all_mdns",
    label: "Device topology all neighbors, children w/mdns [md, ndfa, mdn, mdc, mdns] ⏱️",
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
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 900
  },

  // ── Single-file simple datasets (otbr-cli) ───
  {
    source: "otbr-cli",
    value: "router_table",
    label: "Router table (rt)",
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
    label: "Diag & Device topology list [dial,devl]",
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
    label: "Diag topology [diagnostics list dial]",
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
    label: "Devices list (devl)",
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
    label: "Devices fetch (devf)",
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
    label: "Devices & Diag Topology fetch: [devf,diagfa]⏱️",
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
    label: "Devices, Diag & Mesh Topology: [devf,diagfa,mdfa]⏱️",
    group: "Detailed: most time",
    files: [
      "td-otbr-restapi-devices-fetch.json", 
      "td-otbr-restapi-diagnostics-fetch-all.json",
      "td-otbr-restapi-mesh-diagnostics-fetch-all.json"
    ],
    mergeStrategy: "none",
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1206
  },

  // ── Single-file simple datasets ───
  {
    source: "otbr-restapi",
    value: "restapi_diagnostics_fetch_all",
    label: "Diag Topology: diagnostics fetch all [diagfa]⏱️",
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
    label: "Mesh Topology: mesh diagnostics fetch all (mdfa)⏱️",
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
    label: "actions list (al)",
    group: "System",
    files: ["td-otbr-restapi-actions-list.json"],
    mergeStrategy: "none",
    topologyMode: "raw-array",
    defaultView: "table",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1
  },

  // ── Single-file simple datasets ───
  {
    source: "otbr-restapi",
    value: "restapi_dataset_active",
    label: "dataset active",
    group: "System",
    files: ["td-otbr-restapi-dataset-active.json"],
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
    label: "Eve Thread Network Layout",
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
    label: "Eve Thread Network Layout",
    group: "Processed",
    files: ["td-eve-topology.json"],
    mergeStrategy: "none",
    topologyMode: "eve_enhanced",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1
  },

  // mDNS
  {
    source: "mdns",
    value: "mdns_scopes_br",
    label: "BR scope",
    group: null,
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
    label: "HAP scope",
    group: null,
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
    label: "Matter scope",
    group: null,
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
    label: "Thread scopes (BR, HAP, Matter)",
    group: "Versatile: more time",
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
    label: "premerged: topology [otbr-cli, otbr-restapi, mdns ...] deep & wide. may be stale",
    group: null,
    files: [
      "td-merged-topology-all.json"
    ],
    mergeStrategy: "none",
    topologyMode: "merged-detailed",
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 1
  },

  // ── Multi-file topology datasets (otbr-cli, otbr-restapi) ────────────
  {
    source: "merged",
    value: "merged_otbr_cli_otbr_restapi",
    label: "dynamic merge:otbr-cli, otbr-restapi, mdns ⏱️",
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
    defaultView: "topology",
    defaultLinkFilter: "all_links",
    estimateActionCostSecs: 720
  },

  // ── Single-file simple datasets (system) ───
  {
    source: "system",
    value: "static_extaddr_device_label",
    label: "Extended MAC to Device Label map",
    group: null,
    files: ["td-static-extaddr-device-label.json"],
    mergeStrategy: "none",
    topologyMode: "raw-array",
    defaultLinkFilter: "all_links",
    defaultView: "table",
    estimateActionCostSecs: 1
  }
];
