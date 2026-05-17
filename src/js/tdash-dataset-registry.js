// ── Dataset Registry ──────────────────────────────────────────────────────────
//
// Each entry describes one selectable dataset.
//
// Fields:
//   value            — unique key used as <option value=>
//   label            — display text in the dropdown
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
  // ── Single-file simple datasets (otbr-cli) ───  
  {
    source: "otbr-cli",
    value: "meshdiag_only",
    label: "meshdiag topo",
    files: ["td-otbr-cli-meshdiag-topology.json"],
    mergeStrategy: "none",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "default_links"
  },

  // ── Single-file simple datasets (otbr-cli) ───
  {
    source: "otbr-cli",
    value: "networkdiag_multicast_network_only",
    label: "networkdiag topo (multicast)",
    files: ["td-otbr-cli-networkdiag-topology-multicast-network.json"],
    mergeStrategy: "none",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "default_links"
  },

  {
    source: "otbr-cli",
    value: "networkdiag_only",
    label: "networkdiag topo (poll devices)",
    files: ["td-otbr-cli-networkdiag-topology-poll.json"],
    mergeStrategy: "none",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "default_links"
  },

  // ── Multi-file merged (otbr-cli) ──
  {
    source: "otbr-cli",
    value: "merged_otbr_cli_meshdiag_networkdiag_multicast",
    label: "meshdiag, networkdiag (multicast)",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-topology-multicast-network.json"
    ],
    mergeStrategy: "by-identity",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "all_links"
  },

  {
    source: "otbr-cli",
    value: "merged_otbr_cli_all_multicast",
    label: "mesh, network (multicast), neighbors, children",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-topology-multicast-network.json",
      "td-otbr-cli-meshdiag-router-neighbortables.json",
      "td-otbr-cli-meshdiag-router-childtables.json",
    ],
    mergeStrategy: "by-identity",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "all_links"
  },

  {
    source: "otbr-cli",
    value: "merged_otbr_cli_all",
    label: "mesh, network (poll), neighbors, children",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-topology-poll.json",
      "td-otbr-cli-meshdiag-router-neighbortables.json",
      "td-otbr-cli-meshdiag-router-childtables.json",
    ],
    mergeStrategy: "by-identity",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "all_links"
  },

  {
    source: "otbr-cli",
    value: "router_neighbortables",
    label: "mesh neighbors",
    files: ["td-otbr-cli-meshdiag-router-neighbortables.json"],
    mergeStrategy: "none",
    topologyMode: "merged-detailed",
    defaultView: "topology",
    defaultLinkFilter: "all_links"
  },
  {
    source: "otbr-cli",
    value: "router_childtables",
    label: "mesh children",
    files: ["td-otbr-cli-meshdiag-router-childtables.json"],
    mergeStrategy: "none",
    topologyMode: "merged-detailed",
    defaultView: "topology",
    defaultLinkFilter: "all_links"
  },

  // ── Single-file simple datasets (otbr-cli) ───
  {
    source: "otbr-cli",
    value: "router_table",
    label: "router table",
    files: ["td-otbr-cli-router-table.json"],
    mergeStrategy: "none",
    topologyMode: "router-table",
    defaultView: "table",
    defaultLinkFilter: "all_links"
  },

  // ── Merged (all nodes) ─
  {
    source: "merged",
    value: "merged_all_deep_wide_otbr_cli_restapi_eve",
    label: "premerged: otbr-cli, otbr-restapi, eve",
    files: ["td-merged-topology-all.json"],
    mergeStrategy: "none",
    topologyMode: "merged-detailed",
    defaultView: "topology",
    defaultLinkFilter: "all_links"
  },

  {
    source: "merged",
    value: "merged_otbr_cli_all_mdns",
    label: "otbr-cli, mdns",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-topology-poll.json",
      "td-otbr-cli-meshdiag-router-neighbortables.json",
      "td-otbr-cli-meshdiag-router-childtables.json",
      "td-mdns-scopes-thread.json"
    ],
    mergeStrategy: "by-identity",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "all_links"
  },

  // ── Single-file simple datasets (mdns) ───
  {
    source: "mdns",
    value: "mdns_scopes_thread",
    label: "Thread scopes (BR, HAP, Matter)",
    files: ["td-mdns-scopes-thread.json"],
    mergeStrategy: "none",
    topologyMode: "raw-array",
    defaultLinkFilter: "all_links",
    defaultView: "table"
  },

  {
    source: "mdns",
    value: "mdns_scopes_br",
    label: "BR scope",
    files: ["td-mdns-scopes-br.json"],
    mergeStrategy: "none",
    topologyMode: "raw-array",
    defaultLinkFilter: "all_links",
    defaultView: "table"
  },

   {
    source: "mdns",
    value: "mdns_scopes_hap",
    label: "HAP scope",
    files: ["td-mdns-scopes-hap.json"],
    mergeStrategy: "none",
    topologyMode: "raw-array",
    defaultLinkFilter: "all_links",
    defaultView: "table"
  },
  
  {
    source: "mdns",
    value: "mdns_scopes_matter",
    label: "Matter scope",
    files: ["td-mdns-scopes-matter.json"],
    mergeStrategy: "none",
    topologyMode: "raw-array",
    defaultLinkFilter: "all_links",
    defaultView: "table"
  },

  // ── Single-file simple dataset ───
  {
    source: "eve",
    value: "eve_native_threadlayout",
    label: "native: Eve Thread Network Layout",
    files: ["Eve Thread Network Layout.evethreadlayout"],
    mergeStrategy: "none",
    topologyMode: "eve_native",
    defaultView: "topology",
    defaultLinkFilter: "eve_native_routes_children"
  },
  // ── Single-file simple dataset ───
  {
    source: "eve",
    value: "eve_enhanced_topology",
    label: "enhanced: td-eve-topology.json",
    files: ["td-eve-topology.json"],
    mergeStrategy: "none",
    topologyMode: "eve_enhanced",
    defaultView: "topology",
    defaultLinkFilter: "eve_enhanced_routes_children"
  },

  // ── Multi-file topology datasets (otbr-cli, otbr-restapi) ────────────
  {
    source: "lab",
    value: "merged_otbr_cli_otbr_restapi",
    label: "otbr-cli, otbr-restapi",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-topology-poll.json",
      "td-otbr-cli-meshdiag-router-neighbortables.json",
      "td-otbr-cli-meshdiag-router-childtables.json",
      "td-otbr-restapi-devices.json",
      "td-otbr-restapi-diagnostics.json",
    ],
    mergeStrategy: "by-identity",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "default_links"
  },

  // ── Multi-file merge (otbr-cli, eve) ──
  {
    source: "lab",
    value: "merged_otbr_cli_meshdiag_networkdiag_neighbortables_eve",
    label: "otbr-cli, eve",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-topology-poll.json",
      "td-otbr-cli-meshdiag-router-neighbortables.json",
      "td-otbr-cli-meshdiag-router-childtables.json",
      "td-eve-topology.json",
    ],
    mergeStrategy: "by-identity",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "default_links"
  },

  // ── Multi-file merge [otbr-cli, otbr-restapi, eve] ──
  {
    source: "lab",
    value: "merged_otbr_cli_meshdiag_networkdiag_neighbortables_restapi_eve",
    label: "otbr-cli, otbr-restapi, eve",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-topology-poll.json",
      "td-otbr-cli-meshdiag-router-neighbortables.json",
      "td-otbr-cli-meshdiag-router-childtables.json",
      "td-otbr-restapi-devices.json",
      "td-otbr-restapi-diagnostics.json",
      "td-eve-topology.json",
    ],
    mergeStrategy: "by-identity",
    topologyMode: "meshdiag-networkdiag",
    defaultView: "topology",
    defaultLinkFilter: "default_links"
  },

  // ── Multi-file topology datasets (otbr-restapi) ────────────
  {
    source: "otbr-restapi",
    value: "restapi_devices_diagnostics",
    label: "devices, diagnostics",
    files: ["td-otbr-restapi-devices.json", "td-otbr-restapi-diagnostics.json"],
    mergeStrategy: "none",
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "otbr_rest_api",
  },
  {
    source: "otbr-restapi",
    value: "restapi_devices",
    label: "devices",
    files: ["td-otbr-restapi-devices.json"],
    mergeStrategy: "none",
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "all_links"
  },

  // ── Single-file simple datasets ───
  {
    source: "otbr-restapi",
    value: "restapi_diagnostics",
    label: "diagnostics",
    files: ["td-otbr-restapi-diagnostics.json"],
    mergeStrategy: "none",
    topologyMode: "otbr_restapi",
    defaultView: "topology",
    defaultLinkFilter: "all_links"
  },

  // ── Single-file simple datasets (system) ───
  {
    source: "system",
    value: "static_extaddr_device_label",
    label: "Extended MAC to Device Label map",
    files: ["td-static-extaddr-device-label.json"],
    mergeStrategy: "none",
    topologyMode: "raw-array",
    defaultLinkFilter: "all_links",
    defaultView: "table"
  }
];
