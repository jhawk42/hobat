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

  // ── Single-file simple datasets (eve, table; topology ) ───
  {
    value: 'example_small_eve_native_threadlayout',
    label: 'example: small: eve native: Eve Thread Network Layout.evethreadlayout',
    files: [
      'example-small-Eve Thread Network Layout.evethreadlayout'
    ],
    mergeStrategy: 'none',
    topologyMode: 'eve_native',
    defaultLinkFilter: 'eve_native_routes_children'
  },
  // ── Single-file simple datasets (eve, table; topology ) ───
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
  // ── Single-file simple datasets (eve, table; topology ) ───
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

  // ── Multi-file topology datasets (otbr rest api) ────────────
  {
    value: 'restapi_devices_diagnostics',
    label: 'otbr rest api: devices, diagnostics',
    files: [
      'td-otbr-restapi-devices.json',
      'td-otbr-restapi-diagnostics.json'
    ],
    mergeStrategy: 'none',
    topologyMode: 'otbr_restapi',
    defaultLinkFilter: 'otbr_rest_api'
  },

  // ── Multi-file merged (medium depth — matches td_web_tables.html __merged__) ──
  {
    value: 'merged_otbr_cli_all',
    label: 'merged: otbr cli: meshdiag, networkdiag, neighbortables, childtables',
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

  // ── Multi-file topology datasets (match td_web_topology.html) ────────────
  {
    value: 'merged_otbr_cli_otbr_restapi',
    label: 'merged: otbr cli: meshdiag, networkdiag, restapi: devices, diagnostics',
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

  // ── Multi-file merged (medium depth — matches td_web_tables.html __merged__) ──
  {
    value: 'merged_otbr_cli_meshdiag_networkdiag_neighbortables_eve',
    label: 'merged: otbr cli: meshdiag, networkdiag, neighbortables, eve',
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

  // ── Multi-file merged (medium depth — matches td_web_tables.html __merged__) ──
  {
    value: 'merged_otbr_cli_meshdiag_networkdiag_neighbortables_restapi_eve',
    label: 'merged: otbr cli: meshdiag, networkdiag, neighbortables, otbr restapi, eve',
    files: [
      'td-otbr-cli-meshdiag-topology.json',
      'td-otbr-cli-networkdiag-topology.json',
      'td-otbr-cli-meshdiag-router-neighbortables.json',
      'td-otbr-restapi-devices.json',
      'td-otbr-restapi-diagnostics.json',
      'td-eve-topology.json'
    ],
    mergeStrategy: 'by-identity',
    topologyMode: 'meshdiag-networkdiag',
    defaultLinkFilter: 'default_links'
  },

  // ── Deep merged (matches td_web_tables.html td-merged-topology-all.json) ─
  {
    value: 'merged_all_deep_wide_otbr_cli_restapi_eve',
    label: 'merged: all: otbr cli, restapi, eve - td-merged-topology-all.json',
    files: [
      'td-merged-topology-all.json'
    ],
    mergeStrategy: 'none',
    topologyMode: 'merged-detailed',
    defaultLinkFilter: 'all_links'
  },

  // ── Single-file simple datasets (table-first; topology via raw-array) ───
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
