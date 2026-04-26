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
//                       'by-identity' → merge by rloc16, canonical extaddr, or omrIpv6Address
//   topologyMode     — which topology adaptor to call:
//                       'meshdiag-networkdiag' | 'merged-detailed' | 'eve'
//                       'router-table' | 'raw-array'
//   defaultLinkFilter — value pre-selected in #link-filter when this dataset loads

export const DATASET_REGISTRY = [
  // ── Single-file simple datasets (otbr-cli) ───  
  {
    value: "meshdiag_only",
    label: "otbr-cli: meshdiag topology",
    files: ["td-otbr-cli-meshdiag-topology.json"],
    mergeStrategy: "none",
    topologyMode: "meshdiag-networkdiag",
    defaultLinkFilter: "default_links",
  },
  {
    value: "networkdiag_only",
    label: "otbr-cli: networkdiag topology",
    files: ["td-otbr-cli-networkdiag-topology.json"],
    mergeStrategy: "none",
    topologyMode: "meshdiag-networkdiag",
    defaultLinkFilter: "default_links",
  },

  // ── Multi-file merged (otbr-cli) ──
  {
    value: "merged_otbr_cli_all",
    label: "otbr-cli: merged [meshdiag, networkdiag, neighbors, children]",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-topology.json",
      "td-otbr-cli-meshdiag-router-neighbortables.json",
      "td-otbr-cli-meshdiag-router-childtables.json",
    ],
    mergeStrategy: "by-identity",
    topologyMode: "meshdiag-networkdiag",
    defaultLinkFilter: "all_links", //all_links, default_links
  },

  // ── Single-file simple datasets (otbr-cli) ───
  {
    value: "router_table",
    label: "otbr-cli: router table",
    files: ["td-otbr-cli-router-table.json"],
    mergeStrategy: "none",
    topologyMode: "router-table",
    defaultLinkFilter: "all_links",
  },

  {
    value: "router_neighbortables",
    label: "otbr-cli: meshdiag router neighbortables",
    files: ["td-otbr-cli-meshdiag-router-neighbortables.json"],
    mergeStrategy: "none",
    topologyMode: "merged-detailed",
    defaultLinkFilter: "all_links",
  },
  {
    value: "router_childtables",
    label: "otbr-cli: meshdiag router childtables",
    files: ["td-otbr-cli-meshdiag-router-childtables.json"],
    mergeStrategy: "none",
    topologyMode: "merged-detailed",
    defaultLinkFilter: "all_links",
  },

  // ── Merged (all nodes) ─
  {
    value: "merged_all_deep_wide_otbr_cli_restapi_eve",
    label: "lab: premerged: all 1 file: [otbr-cli, otbr-restapi, eve]",
    files: ["td-merged-topology-all.json"],
    mergeStrategy: "none",
    topologyMode: "merged-detailed",
    defaultLinkFilter: "all_links",
  },

  // ── Single-file simple dataset ───
  {
    value: "example_small_eve_native_threadlayout",
    label: "lab: eve native: example: eve layout",
    files: ["example-small-Eve Thread Network Layout"],
    mergeStrategy: "none",
    topologyMode: "eve_native",
    defaultLinkFilter: "eve_native_routes_children",
  },
  // ── Single-file simple dataset ───
  {
    value: "eve_native_threadlayout",
    label: "lab: eve native: Eve Thread Network Layout",
    files: ["Eve Thread Network Layout.evethreadlayout"],
    mergeStrategy: "none",
    topologyMode: "eve_native",
    defaultLinkFilter: "eve_native_routes_children",
  },
  // ── Single-file simple dataset ───
  {
    value: "eve_enhanced_topology",
    label: "lab: eve enhanced: td-eve-topology.json",
    files: ["td-eve-topology.json"],
    mergeStrategy: "none",
    topologyMode: "eve_enhanced",
    defaultLinkFilter: "eve_enhanced_routes_children",
  },

  // ── Multi-file topology datasets (otbr-cli, otbr-restapi) ────────────
  {
    value: "merged_otbr_cli_otbr_restapi",
    label: "lab: merged: [otbr-cli, otbr-restapi]",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-topology.json",
      "td-otbr-cli-meshdiag-router-neighbortables.json",
      "td-otbr-cli-meshdiag-router-childtables.json",
      "td-otbr-restapi-devices.json",
      "td-otbr-restapi-diagnostics.json",
    ],
    mergeStrategy: "by-identity",
    topologyMode: "meshdiag-networkdiag",
    defaultLinkFilter: "default_links",
  },

  // ── Multi-file merge (otbr-cli, eve) ──
  {
    value: "merged_otbr_cli_meshdiag_networkdiag_neighbortables_eve",
    label: "lab: merged: [otbr-cli, eve]",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-topology.json",
      "td-otbr-cli-meshdiag-router-neighbortables.json",
      "td-eve-topology.json",
    ],
    mergeStrategy: "by-identity",
    topologyMode: "meshdiag-networkdiag",
    defaultLinkFilter: "default_links",
  },

  // ── Multi-file merge [otbr-cli, otbr-restapi, eve] ──
  {
    value: "merged_otbr_cli_meshdiag_networkdiag_neighbortables_restapi_eve",
    label: "lab: merged: [otbr-cli, otbr-restapi, eve]",
    files: [
      "td-otbr-cli-meshdiag-topology.json",
      "td-otbr-cli-networkdiag-topology.json",
      "td-otbr-cli-meshdiag-router-neighbortables.json",
      "td-otbr-cli-meshdiag-router-childtables.json",
      "td-otbr-restapi-devices.json",
      "td-otbr-restapi-diagnostics.json",
      "td-eve-topology.json",
    ],
    mergeStrategy: "by-identity",
    topologyMode: "meshdiag-networkdiag",
    defaultLinkFilter: "default_links",
  },

  // ── Multi-file topology datasets (otbr-restapi) ────────────
  {
    value: "restapi_devices_diagnostics",
    label: "lab: otbr-restapi: [devices, diagnostics]",
    files: ["td-otbr-restapi-devices.json", "td-otbr-restapi-diagnostics.json"],
    mergeStrategy: "none",
    topologyMode: "otbr_restapi",
    defaultLinkFilter: "otbr_rest_api",
  },
  {
    value: "restapi_devices",
    label: "lab: otbr-restapi: devices",
    files: ["td-otbr-restapi-devices.json"],
    mergeStrategy: "none",
    topologyMode: "otbr_restapi",
    defaultLinkFilter: "all_links",
  },

  // ── Single-file simple datasets ───
  {
    value: "restapi_diagnostics",
    label: "lab: otbr-restapi: diagnostics",
    files: ["td-otbr-restapi-diagnostics.json"],
    mergeStrategy: "none",
    topologyMode: "otbr_restapi",
    defaultLinkFilter: "all_links",
  },

  // ── Single-file simple datasets (system) ───
  {
    value: "static_extaddr_device_label",
    label: "system: Extended MAC to Device Label Mapping",
    files: ["td-static-extaddr-device-label.json"],
    mergeStrategy: "none",
    topologyMode: "raw-array",
    defaultLinkFilter: "all_links",
  }
];
