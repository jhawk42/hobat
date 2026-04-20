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


  // ── Multi-file merged (otbr-cli) ──
  {
    value: 'merged_otbr_cli_all',
    label: 'otbr-cli: [meshdiag, networkdiag, neighbortables, childtables]',
    files: [
      'td-otbr-cli-meshdiag-topology.json',
      'td-otbr-cli-networkdiag-topology.json',
      'td-otbr-cli-meshdiag-router-neighbortables.json',
      'td-otbr-cli-meshdiag-router-childtables.json'
    ],
    mergeStrategy: 'by-identity',
    topologyMode: 'meshdiag-networkdiag',
    defaultLinkFilter: 'default_links'
  },

  // ── Multi-file topology datasets (otbr-restapi) ────────────
  {
    value: 'restapi_devices_diagnostics',
    label: 'otbr-restapi: [devices, diagnostics]',
    files: [
      'td-otbr-restapi-devices.json',
      'td-otbr-restapi-diagnostics.json'
    ],
    mergeStrategy: 'none',
    topologyMode: 'otbr_restapi',
    defaultLinkFilter: 'otbr_rest_api'
  },  

  // ── Deep merged (all nodes) ─
  {
    value: 'merged_all_deep_wide_otbr_cli_restapi_eve',
    label: 'merged: 1 file: [otbr-cli, otbr-restapi, eve]',
    files: [
      'td-merged-topology-all.json'
    ],
    mergeStrategy: 'none',
    topologyMode: 'merged-detailed',
    defaultLinkFilter: 'all_links'
  },


  // ── Single-file simple dataset ───
  {
    value: 'example_small_eve_native_threadlayout',
    label: 'eve native: example: eve layout',
    files: [
      'example-small-Eve Thread Network Layout.evethreadlayout'
    ],
    mergeStrategy: 'none',
    topologyMode: 'eve_native',
    defaultLinkFilter: 'eve_native_routes_children'
  },
  // ── Single-file simple dataset ───
  {
    value: 'eve_native_threadlayout',
    label: 'eve native: Eve Thread Network Layout.evethreadlayout',
    files: [
      'Eve Thread Network Layout.evethreadlayout'
    ],
    mergeStrategy: 'none',
    topologyMode: 'eve_native',
    defaultLinkFilter: 'eve_native_routes_children'
  },
  // ── Single-file simple dataset ───
  {
    value: 'eve_enhanced_topology',
    label: 'eve enhanced: td-eve-topology.json',
    files: [
      'td-eve-topology.json'
    ],
    mergeStrategy: 'none',
    topologyMode: 'eve_enhanced',
    defaultLinkFilter: 'eve_enhanced_routes_children'
  },

  // ── Multi-file topology datasets (otbr-cli, otbr-restapi) ────────────
  {
    value: 'merged_otbr_cli_otbr_restapi',
    label: 'merged: [otbr-cli, otbr-restapi]',
    files: [
      'td-otbr-cli-meshdiag-topology.json',
      'td-otbr-cli-networkdiag-topology.json',
      'td-otbr-cli-meshdiag-router-neighbortables.json',
      'td-otbr-cli-meshdiag-router-childtables.json',
      'td-otbr-restapi-devices.json',
      'td-otbr-restapi-diagnostics.json'
    ],
    mergeStrategy: 'by-identity',
    topologyMode: 'meshdiag-networkdiag',
    defaultLinkFilter: 'default_links'
  },

  // ── Multi-file merge (otbr-cli, eve) ──
  {
    value: 'merged_otbr_cli_meshdiag_networkdiag_neighbortables_eve',
    label: 'merged: [otbr-cli, eve]',
    files: [
      'td-otbr-cli-meshdiag-topology.json',
      'td-otbr-cli-networkdiag-topology.json',
      'td-otbr-cli-meshdiag-router-neighbortables.json',
      'td-eve-topology.json'
    ],
    mergeStrategy: 'by-identity',
    topologyMode: 'meshdiag-networkdiag',
    defaultLinkFilter: 'default_links'
  },

  // ── Multi-file merge [otbr-cli, otbr-restapi, eve] ──
  {
    value: 'merged_otbr_cli_meshdiag_networkdiag_neighbortables_restapi_eve',
    label: 'merged: [otbr-cli, otbr-restapi, eve]',
    files: [
      'td-otbr-cli-meshdiag-topology.json',
      'td-otbr-cli-networkdiag-topology.json',
      'td-otbr-cli-meshdiag-router-neighbortables.json',
      'td-otbr-cli-meshdiag-router-childtables.json',
      'td-otbr-restapi-devices.json',
      'td-otbr-restapi-diagnostics.json',
      'td-eve-topology.json'
    ],
    mergeStrategy: 'by-identity',
    topologyMode: 'meshdiag-networkdiag',
    defaultLinkFilter: 'default_links'
  },

  // ── Single-file simple datasets ───
  {
    value: 'router_table',
    label: 'td-otbr-cli-router-table.json',
    files: [
      'td-otbr-cli-router-table.json'
    ],
    mergeStrategy: 'none',
    topologyMode: 'router-table',
    defaultLinkFilter: 'all_links'
  },
  {
    value: 'meshdiag_only',
    label: 'td-otbr-cli-meshdiag-topology.json',
    files: [
      'td-otbr-cli-meshdiag-topology.json'
    ],
    mergeStrategy: 'none',
    topologyMode: 'meshdiag-networkdiag',
    defaultLinkFilter: 'default_links'
  },
  {
    value: 'networkdiag_only',
    label: 'td-otbr-cli-networkdiag-topology.json',
    files: [
      'td-otbr-cli-networkdiag-topology.json'
    ],
    mergeStrategy: 'none',
    topologyMode: 'meshdiag-networkdiag',
    defaultLinkFilter: 'default_links'
  },
  {
    value: 'router_neighbortables',
    label: 'td-otbr-cli-meshdiag-router-neighbortables.json',
    files: [
      'td-otbr-cli-meshdiag-router-neighbortables.json'
    ],
    mergeStrategy: 'none',
    topologyMode: 'merged-detailed',
    defaultLinkFilter: 'all_links'
  },
  {
    value: 'router_childtables',
    label: 'td-otbr-cli-meshdiag-router-childtables.json',
    files: [
      'td-otbr-cli-meshdiag-router-childtables.json'
    ],
    mergeStrategy: 'none',
    topologyMode: 'merged-detailed',
    defaultLinkFilter: 'all_links'
  },
  {
    value: 'restapi_devices',
    label: 'td-otbr-restapi-devices.json',
    files: [
      'td-otbr-restapi-devices.json'
    ],
    mergeStrategy: 'none',
    topologyMode: 'otbr_restapi',
    defaultLinkFilter: 'all_links'
  },
  {
    value: 'restapi_diagnostics',
    label: 'td-otbr-restapi-diagnostics.json',
    files: [
      'td-otbr-restapi-diagnostics.json'
    ],
    mergeStrategy: 'none',
    topologyMode: 'otbr_restapi',
    defaultLinkFilter: 'all_links'
  }
];
