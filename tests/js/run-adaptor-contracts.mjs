import assert from "node:assert/strict";
import fs from "node:fs";

import {
  extractOtbrRestApiItems,
  extractOtbrRestApiSources,
  runAdaptor,
} from "../../src/js/tdash-adaptors.js";
import { mergeRowsByStrategy, normalizeRows } from "../../src/js/tdash-merge.js";
import {
  createAdaptorModelFromResult,
  emitAdaptorResult,
  projectObservedTopologyLinkCounts,
} from "../../src/js/tdash-adaptor-model.js";
import { emitThroughAdaptorModel } from "../../src/js/tdash-adaptor-shared.js";
import { getPreferredFieldPath } from "../../src/js/tdash-device-fields.js";
import { HA_MATTER_ROLE_POLICY } from "../../src/js/tdash-ha-matter-ws-roles.js";
import { buildRoleNodeEmphasis } from "../../src/js/tdash-topology-utils.js";

assert.deepEqual(buildRoleNodeEmphasis({ isBorderRouter: true, isRouter: true }), {
  borderWidth: 5,
  size: 45,
});
assert.deepEqual(buildRoleNodeEmphasis({ isBorderRouter: false, isRouter: true }), {
  borderWidth: 3,
  size: 45,
});
assert.deepEqual(buildRoleNodeEmphasis({ isBorderRouter: false, isRouter: false }), {
  borderWidth: 1,
  size: 27,
});

if (process.argv.includes("--snapshot") && !process.argv.includes("--write-baseline")) {
  const { createCachedAdaptorSnapshot } = await import("./run-adaptor-output-snapshot.mjs");
  const output = `${JSON.stringify(createCachedAdaptorSnapshot())}\n`;
  await new Promise((resolve) => process.stdout.write(output, resolve));
  process.exit(0);
}

function run(adaptor, files, rawFiles, rows = []) {
  return runAdaptor({ entry: { adaptor, files }, rawFiles, rows });
}

function runHaMatterRolePolicy(adaptor, files, rawFiles, rows, entryOptions = {}) {
  return runAdaptor({
    entry: {
      source: "ha-matter-ws",
      adaptor,
      files,
      mergeStrategy: "none",
      ...entryOptions,
    },
    rawFiles,
    rows,
    rolePolicy: HA_MATTER_ROLE_POLICY,
  });
}

function assertRoleEmphasis(result, expectedById) {
  for (const [id, expected] of Object.entries(expectedById)) {
    const node = result.nodeData.find((candidate) => candidate.id === id);
    assert.ok(node, `missing node ${id}`);
    assert.deepEqual({ borderWidth: node.borderWidth, size: node.size }, expected, id);
  }
}

function assertResult(result, expected) {
  for (const record of [...result.nodeData, ...result.nodeMap.values()]) {
    const seen = new Set();
    for (const field of Object.keys(record)) {
      const preferred = getPreferredFieldPath(field);
      assert.ok(!seen.has(preferred), `duplicate preferred field ${preferred} on ${record.id}`);
      seen.add(preferred);
    }
  }
  assert.deepEqual(result.nodeData.map((node) => node.id), expected.nodeIds);
  assert.deepEqual(
    result.edgeData.map((edge) => [edge.from, edge.to, edge.linkCategories]),
    expected.edges,
  );
  assert.deepEqual(result.sourceNames, expected.sourceNames);
  assert.ok(result.nodeMap instanceof Map);
  assert.ok(result.rawByIdForDetails instanceof Map);
  assert.ok(result.routerNeighborByRloc16 instanceof Map);
  assert.equal("routerChildByRloc16" in result, expected.hasChildIndex);
}

const networkdiag = run(
  "meshdiag-networkdiag",
  ["td-otbr-cli-networkdiag-fetch-all.json"],
  [[
    {
      rloc16: "0x1000",
      role: "router",
      route: { routeData: [{ rloc16: "0x2000", linkQualityIn: 2, linkQualityOut: 3 }] },
    },
    { rloc16: "0x2000", role: "router" },
  ]],
);
assertResult(networkdiag, {
  nodeIds: ["0x1000", "0x2000"],
  edges: [["0x1000", "0x2000", ["otbr_route", "otbr_route_router"]]],
  sourceNames: ["networkdiagnostic"],
  hasChildIndex: true,
});
assert.equal(networkdiag.edgeData[0].width, 12);

const meshdiagRoutes = run(
  "meshdiag-networkdiag",
  ["td-otbr-cli-meshdiag-topology.json"],
  [[
    {
      rloc16: "0x1000",
      role: "router",
      route: { routeData: [{ rloc16: "0x2000", linkQualityIn: 2, linkQualityOut: 3 }] },
      links3: [{ rloc16: "0x2000" }],
    },
    { rloc16: "0x2000", role: "router" },
  ]],
);
assertResult(meshdiagRoutes, {
  nodeIds: ["0x1000", "0x2000"],
  edges: [["0x1000", "0x2000", ["otbr_route", "otbr_route_router"]]],
  sourceNames: ["meshdiag"],
  hasChildIndex: true,
});

const meshdiagLinkFallback = run(
  "meshdiag-networkdiag",
  ["td-otbr-cli-meshdiag-topology.json"],
  [[
    { rloc16: "0x1000", role: "router", links3: [{ rloc16: "0x2000" }] },
    { rloc16: "0x2000", role: "router" },
  ]],
);
assertResult(meshdiagLinkFallback, {
  nodeIds: ["0x1000", "0x2000"],
  edges: [["0x1000", "0x2000", ["default_3_links"]]],
  sourceNames: ["meshdiag"],
  hasChildIndex: true,
});

const eveRows = {
  "0x1000": { id: "eve-a", name: "A", type: "router", routes: [{ to: "eve-b", in: 3, out: 3 }] },
  "0x2000": { id: "eve-b", name: "B", type: "router" },
};
const eve = run("eve-enhanced", ["eve.json"], [eveRows]);
assertResult(eve, {
  nodeIds: ["eve-a", "eve-b"],
  edges: [["eve-a", "eve-b", ["eve_route"]]],
  sourceNames: ["eve"],
  hasChildIndex: false,
});
assert.deepEqual(eve.rawByIdForDetails.get("eve-a"), eveRows["0x1000"]);

const borderRouterEvidence = run("eve-enhanced", ["eve.json"], [[
  { id: "legacy-border-router", type: "router", role: "border router", br: "yes" },
  { id: "explicit-non-border-router", type: "router", role: "border router", isBorderRouter: false },
  { id: "missing-border-router-evidence", type: "router", role: "border router", deviceLabel: "Border Router" },
]]);
const legacyBorderRouter = borderRouterEvidence.nodeMap.get("legacy-border-router");
const explicitNonBorderRouter = borderRouterEvidence.nodeMap.get("explicit-non-border-router");
const missingBorderRouterEvidence = borderRouterEvidence.nodeMap.get("missing-border-router-evidence");
assert.equal(legacyBorderRouter.isBorderRouter, true);
assert.equal("br" in legacyBorderRouter, false);
assert.equal(explicitNonBorderRouter.isBorderRouter, false);
assert.equal("isBorderRouter" in missingBorderRouterEvidence, false);
assert.equal("br" in missingBorderRouterEvidence, false);
for (const record of borderRouterEvidence.rawByIdForDetails.values()) {
  assert.equal("br" in record, false);
  assert.equal("is_border_router" in record, false);
}

for (const observations of [
  [false, true],
  [true, false],
]) {
  const duplicateEvidence = run("eve-enhanced", ["eve.json"], [[
    {
      id: "conflicting-border-router",
      extaddr: "cc00112233445566",
      type: "router",
      isBorderRouter: observations[0],
    },
    {
      id: "conflicting-border-router",
      extaddr: "cc00112233445566",
      type: "router",
      isBorderRouter: observations[1],
    },
  ]]);
  const expectedConflict = [
    { path: "isBorderRouter", current: true, incoming: false },
  ];
  for (const record of [
    duplicateEvidence.nodeData[0],
    duplicateEvidence.nodeMap.get("conflicting-border-router"),
    duplicateEvidence.rawByIdForDetails.get("conflicting-border-router"),
  ]) {
    assert.equal(record.isBorderRouter, true);
    assert.deepEqual(record._merge_conflicts, expectedConflict);
    assert.equal("br" in record, false);
  }
}

const cachedEveRows = JSON.parse(fs.readFileSync("data/td-eve-topology.json", "utf8"));
const cachedEve = run(
  "eve-enhanced",
  ["td-eve-topology.json"],
  [cachedEveRows],
);
assert.equal(cachedEve.nodeData.length, 79);
assert.equal(cachedEve.edgeData.length, 207);
assert.deepEqual(
  cachedEve.nodeData.map((node) => node.id),
  Object.values(cachedEveRows).map((row) => row.id),
);
assert.equal(cachedEve.rawByIdForDetails.size, 79);
assert.deepEqual(cachedEve.sourceNames, ["eve"]);

const eveNativeRows = Object.values(eveRows);
const eveNative = run("eve-native", ["eve-native.json"], [{ nodes: eveNativeRows }]);
assertResult(eveNative, {
  nodeIds: ["eve-a", "eve-b"],
  edges: [["eve-a", "eve-b", ["eve_native_route"]]],
  sourceNames: ["eve_native"],
  hasChildIndex: false,
});

const threadTools = run("thread-tools-native", ["diagnostics.json"], [{ diagnostics: [
  {
    macAddr: 0x1000,
    extMacAddr: "aa00112233445566",
    mode: { ftd: true },
    children: [{ macAddr: 0x1001, extAddress: "bb00112233445566", isDeviceTypeMtd: false }],
  },
  { macAddr: 0x1001, extMacAddr: "bb00112233445566", mode: { ftd: false } },
] }]);
assertResult(threadTools, {
  nodeIds: ["0x1000", "0x1001"],
  edges: [["0x1000", "0x1001", ["otbr_child"]]],
  sourceNames: ["thread_tools_native"],
  hasChildIndex: true,
});
assert.equal(
  threadTools.routerChildByRloc16.get("0x1000").router_child_table.length,
  1,
);

const merged = run("merged-detailed", ["merged.json"], [[
  { rloc16: "0x1000", role: "router", route: { routeData: [{ routeId: 8 }] } },
  { rloc16: "0x2000", role: "router" },
]]);
assertResult(merged, {
  nodeIds: ["0x1000", "0x2000"],
  edges: [["0x1000", "0x2000", ["otbr_route", "otbr_route_router"]]],
  sourceNames: ["merged-detailed"],
  hasChildIndex: true,
});

const mergedRouterNeighbors = run("merged-detailed", ["neighbors.json"], [[
  {
    rloc16: "0x1000",
    role: "router",
    routerNeighbors: [{ rloc16: "0x2000", extAddress: "bb00112233445566", linkMargin: 30 }],
  },
  { rloc16: "0x2000", role: "router" },
]]);
assertResult(mergedRouterNeighbors, {
  nodeIds: ["0x1000", "0x2000"],
  edges: [["0x1000", "0x2000", ["router_neighbor"]]],
  sourceNames: ["merged-detailed"],
  hasChildIndex: true,
});
assert.equal(
  mergedRouterNeighbors.routerNeighborByRloc16.get("0x1000").routerNeighbors.length,
  1,
);

const routerTable = run("router-table", ["router-table.json"], [[
  { rloc16: "0x0400", nextHop: 2, linkQualityOut: 3 },
  { rloc16: "0x0800", nextHop: 2 },
]]);
assertResult(routerTable, {
  nodeIds: ["0x0400", "0x0800"],
  edges: [["0x0400", "0x0800", ["default_1_links"]]],
  sourceNames: ["router-table"],
  hasChildIndex: false,
});

const raw = run("raw-array", ["raw.json"], [[
  { id: "raw-a", rloc16: "0x1000", type: "router", children: ["0x1001"] },
  { id: "raw-b", rloc16: "0x1001", type: "child" },
]]);
assertResult(raw, {
  nodeIds: ["0x1000", "0x1001"],
  edges: [["0x1000", "0x1001", ["default_children"]]],
  sourceNames: ["raw-array"],
  hasChildIndex: false,
});

const haMatter = run("ha-matter-ws", ["td-ha-matter-ws-topology.json"], [[
  {
    topologyId: "matter:a",
    extAddress: "aa00112233445566",
    rloc16: "0x1000",
    role: "Router",
    routerNeighbors: [{
      sourceId: "matter:a",
      targetId: "matter:b",
      lqi: 3,
      averageRssi: -61,
      lastRssi: -63,
      frameErrorRate: 4,
      messageErrorRate: 1,
    }],
    children: [{ sourceId: "matter:a", targetId: "matter:b", lqi: 3 }],
    route: { routeData: [{ sourceId: "matter:a", targetId: "matter:b", routeCost: 1 }] },
  },
  {
    topologyId: "matter:b",
    extAddress: "bb00112233445566",
    rloc16: "0x1001",
    role: "Child",
    routerNeighbors: [],
    children: [],
    route: { routeData: [] },
  },
]]);
assertResult(haMatter, {
  nodeIds: ["matter:a", "matter:b"],
  edges: [[
    "matter:a",
    "matter:b",
    ["default_children", "otbr_route", "otbr_route_router"],
  ]],
  sourceNames: ["ha-matter-ws"],
  hasChildIndex: true,
});
assert.equal(haMatter.edgeData[0].arrows, "to");
assert.equal(haMatter.edgeData[0].isParentChild, true);
assert.equal(haMatter.rawByIdForDetails.get("matter:a").role, "Router");
assert.match(haMatter.edgeData[0].title, /type: Parent-child, Route, Route: Router/);
assert.match(haMatter.edgeData[0].title, /from: 0x1000/);
assert.match(haMatter.edgeData[0].title, /to: 0x1001/);
assert.match(haMatter.edgeData[0].title, /LQI: 3/);
assert.match(haMatter.edgeData[0].title, /Average RSSI: -61 dBm/);
assert.match(haMatter.edgeData[0].title, /Last RSSI: -63 dBm/);
assert.match(haMatter.edgeData[0].title, /Frame error rate: 4%/);
assert.match(haMatter.edgeData[0].title, /Message error rate: 1%/);
assert.match(haMatter.edgeData[0].title, /Route cost: 1/);
assert.equal(haMatter.nodeData[0].font.background, "rgba(7, 18, 40, 0.62)");
assert.equal(haMatter.nodeData[0].font.size, 19.5);
assert.equal(haMatter.nodeData[0].font.vadjust, -8);
assert.equal(haMatter.nodeData[1].font.background, "rgba(7, 18, 40, 0.62)");
assert.equal(haMatter.nodeData[1].font.size, 13);
assert.equal(haMatter.nodeData[1].font.vadjust, undefined);
assert.equal(haMatter.nodeData[0].title, "Unknown node\nRLOC16: 0x1000");
assert.equal(haMatter.nodeData[0].borderWidth, 3);
assert.equal(haMatter.nodeData[0].size, 45);
assert.equal(haMatter.nodeData[1].borderWidth, 1);
assert.equal(haMatter.nodeData[1].size, 27);

const haLegacyBorderFlag = run("ha-matter-ws", ["td-ha-matter-ws-topology.json"], [[{
  topologyId: "legacy-border-flag",
  role: "Router",
  isBorderRouter: true,
}]]);
assert.equal(haLegacyBorderFlag.nodeData[0].shape, "hexagon");
assert.equal(haLegacyBorderFlag.nodeData[0].color.background, "#e8f5e9");
assert.equal(haLegacyBorderFlag.nodeData[0].borderWidth, 3);
assert.equal(haLegacyBorderFlag.nodeData[0].size, 45);

const haRoleRows = [
  { topologyId: "role:br", extAddress: "aa00000000000001", isBorderRouter: true, isRouter: true },
  { topologyId: "role:router", extAddress: "aa00000000000002", isBorderRouter: false, isRouter: true },
  { topologyId: "role:child", extAddress: "aa00000000000003", isBorderRouter: false, isRouter: false, role: "Child" },
  {
    topologyId: "role:unknown",
    extAddress: "aa00000000000004",
    isBorderRouter: false,
    isRouter: false,
    role: "unknown",
    neighborTable: [{ rloc16: "0x3000" }],
  },
];
const haRoleEmphasis = {
  "role:br": { borderWidth: 5, size: 45 },
  "role:router": { borderWidth: 3, size: 45 },
  "role:child": { borderWidth: 1, size: 27 },
  "role:unknown": { borderWidth: 1, size: 27 },
};
const haRoleTopology = runHaMatterRolePolicy(
  "ha-matter-ws",
  ["td-ha-matter-ws-topology.json"],
  [{ topology: haRoleRows }],
  haRoleRows,
  { rowExtractor: "ha-matter-ws-topology" },
);
assertRoleEmphasis(haRoleTopology, {
  ...haRoleEmphasis,
  "ha-matter-ws:rloc:0x3000": { borderWidth: 1, size: 27 },
});

const haNativeRolePayload = {
  topology: {
    nodes: [
      { id: "native:br", kind: "border_router", network_type: "thread", role: "router", ext_address: "aa00000000000001" },
      { id: "native:router", kind: "matter", network_type: "thread", role: "router", ext_address: "aa00000000000012" },
      { id: "native:child", kind: "matter", network_type: "thread", role: "end_device", ext_address: "aa00000000000013" },
      { id: "native:unknown", kind: "wifi_ap", network_type: "wifi", role: "ap", ext_address: "aa00000000000014" },
    ],
    connections: [],
  },
};
const haNativeRoleEmphasis = {
  "native:br": { borderWidth: 5, size: 45 },
  "native:router": { borderWidth: 3, size: 45 },
  "native:child": { borderWidth: 1, size: 27 },
  "native:unknown": { borderWidth: 1, size: 27 },
};
const haNativeRoleTopology = runHaMatterRolePolicy(
  "ha-matter-ws-network-topology",
  ["td-ha-matter-ws-network-topology.json"],
  [haNativeRolePayload],
  [],
  { rowExtractor: "ha-matter-ws-network-topology" },
);
assertRoleEmphasis(haNativeRoleTopology, haNativeRoleEmphasis);

const haMergedRoleTopology = runHaMatterRolePolicy(
  "ha-matter-ws-merge-topology",
  ["td-ha-matter-ws-topology.json", "td-ha-matter-ws-network-topology.json"],
  [{ topology: haRoleRows }, haNativeRolePayload],
  haRoleRows,
  {
    mergeStrategy: "by-identity",
    mergeRowExtractors: ["ha-matter-ws-topology", "ha-matter-ws-network-topology"],
  },
);
const haMergedRoleEmphasis = {
  ...haRoleEmphasis,
  "role:br": { borderWidth: 5, size: 45 },
  "native:router": { borderWidth: 3, size: 45 },
  "native:child": { borderWidth: 1, size: 27 },
  "native:unknown": { borderWidth: 1, size: 27 },
  "ha-matter-ws:rloc:0x3000": { borderWidth: 1, size: 27 },
};
assert.deepEqual(
  haMergedRoleTopology.nodeData.map((node) => node.id).sort(),
  Object.keys(haMergedRoleEmphasis).sort(),
);
assertRoleEmphasis(haMergedRoleTopology, haMergedRoleEmphasis);

const haNativeThreadRole = runHaMatterRolePolicy(
  "ha-matter-ws-native-thread",
  ["td-ha-matter-ws-thread-border-routers.json"],
  [{ borderRouters: [] }],
  [{ extAddress: "aa00000000000021", isBorderRouter: true, isRouter: true }],
  { rowExtractor: "ha-matter-ws-border-routers" },
);
assertRoleEmphasis(haNativeThreadRole, {
  "ha-matter-ws-border-router:aa00000000000021": { borderWidth: 5, size: 45 },
});

const haMatterDashboard = run(
  "ha-matter-ws",
  ["td-ha-matter-ws-dashboard.json"],
  [{
    diagnostics: [{ nodeId: 1 }],
    meshDiagnostics: [{ nodeId: 1 }],
    topology: [
      {
        topologyId: "matter:a",
        rloc16: "0x1000",
        role: "Router",
        routerNeighbors: [{ sourceId: "matter:a", targetId: "matter:b", lqi: 3 }],
        children: [],
        route: { routeData: [] },
      },
      {
        topologyId: "matter:b",
        rloc16: "0x2000",
        role: "Router",
        routerNeighbors: [],
        children: [],
        route: { routeData: [] },
      },
    ],
  }],
);
assertResult(haMatterDashboard, {
  nodeIds: ["matter:a", "matter:b"],
  edges: [["matter:a", "matter:b", ["router_neighbor"]]],
  sourceNames: ["ha-matter-ws"],
  hasChildIndex: true,
});
assert.equal(haMatterDashboard.edgeData[0].isParentChild, false);

const haMatterRawThreadTables = run(
  "ha-matter-ws",
  ["td-ha-matter-ws-diagnostics-fetch-all.json"],
  [[
    {
      matterId: "matter:source",
      thread: {
        extAddress: "aa00112233445566",
        rloc16: "0x1000",
        routingRole: "Router",
        neighborTable: [{
          extAddress: "bb00112233445566",
          rloc16: "0x2000",
          lqi: 3,
        }],
        routeTable: [{
          extAddress: "bb00112233445566",
          rloc16: "0x2000",
          pathCost: 1,
          allocated: true,
        }],
      },
    },
  ]],
);
assertResult(haMatterRawThreadTables, {
  nodeIds: ["matter:source", "ha-matter-ws:ext:bb00112233445566"],
  edges: [[
    "matter:source",
    "ha-matter-ws:ext:bb00112233445566",
    ["router_neighbor", "otbr_route", "otbr_route_router"],
  ]],
  sourceNames: ["ha-matter-ws"],
  hasChildIndex: true,
});
assert.equal(haMatterRawThreadTables.edgeData[0].routeCost, 1);

const haMatterDiagnostics = runAdaptor({
  entry: {
    adaptor: "ha-matter-ws",
    files: ["td-ha-matter-ws-dashboard.json"],
    rowExtractor: "ha-matter-ws-diagnostics",
  },
  rawFiles: [{
    diagnostics: [{ topologyId: "matter:diagnostic", rloc16: "0x1001" }],
    topology: [{ topologyId: "matter:topology", rloc16: "0x1000" }],
  }],
  rows: [{ topologyId: "matter:diagnostic", rloc16: "0x1001" }],
});
assert.deepEqual(
  haMatterDiagnostics.nodeData.map((node) => node.id),
  ["matter:diagnostic"],
);

const haMatterMeshDiagnostics = runAdaptor({
  entry: {
    adaptor: "ha-matter-ws",
    files: ["td-ha-matter-ws-dashboard.json"],
    rowExtractor: "ha-matter-ws-mesh-diagnostics",
  },
  rawFiles: [{
    meshDiagnostics: [{
      topologyId: "matter:child",
      rloc16: "0x1001",
      routerNeighbors: [{
        sourceId: "matter:child",
        targetId: "thread:router",
        lqi: 3,
      }],
    }],
    topology: [{
      topologyId: "thread:router",
      rloc16: "0x1000",
      relationshipOnly: true,
    }],
  }],
  rows: [{
    topologyId: "matter:child",
    rloc16: "0x1001",
    routerNeighbors: [{
      sourceId: "matter:child",
      targetId: "thread:router",
      lqi: 3,
    }],
  }],
});
assert.deepEqual(
  haMatterMeshDiagnostics.nodeData.map((node) => node.id),
  ["matter:child", "thread:router"],
);
assert.deepEqual(
  haMatterMeshDiagnostics.edgeData.map((edge) => [edge.from, edge.to]),
  [["matter:child", "thread:router"]],
);

const haMatterDevices = run(
  "ha-matter-ws",
  ["td-ha-matter-ws-devices-fetch-all.json"],
  [[{
    matter: {
      matterId: "0000000000001234-0000000000000001",
      nodeId: 1,
      deviceLabel: "Hall Sensor",
    },
    thread: { extAddress: "aa00112233445566", routingRole: "Child" },
  }]],
);
assert.equal(haMatterDevices.nodeData[0].id, "0000000000001234-0000000000000001");
assert.match(haMatterDevices.nodeData[0].label, /Hall Sensor/);
assert.equal(
  haMatterDevices.nodeMap.get("0000000000001234-0000000000000001").extAddress,
  "aa00112233445566",
);

const cachedHaMatterRows = JSON.parse(
  fs.readFileSync("data/td-ha-matter-ws-topology.json", "utf8"),
);
const cachedHaMatter = run(
  "ha-matter-ws",
  ["td-ha-matter-ws-topology.json"],
  [cachedHaMatterRows],
);
assert.equal(cachedHaMatter.nodeData.length, 31);
assert.equal(cachedHaMatter.edgeData.length, 38);
assert.equal(cachedHaMatter.edgeData[0].arrows, "to");
assert.equal(cachedHaMatter.nodeData.filter((node) => node.isRouter === true).length, 20);
assert.equal(cachedHaMatter.nodeData.filter((node) => node.isRouter !== true).length, 11);
assert.equal(
  cachedHaMatter.nodeData.find(
    (node) => cachedHaMatter.nodeMap.get(node.id)?.role === "Reed",
  )?.isRouter,
  false,
);

  const cachedHaMatterDashboard = JSON.parse(
    fs.readFileSync("data/td-ha-matter-ws-dashboard.json", "utf8"),
  );
  const cachedHaMatterDashboardDiagnostics = runAdaptor({
    entry: {
      adaptor: "ha-matter-ws",
      files: ["td-ha-matter-ws-dashboard.json"],
      rowExtractor: "ha-matter-ws-diagnostics",
    },
    rawFiles: [cachedHaMatterDashboard],
    rows: cachedHaMatterDashboard.diagnostics,
  });
  assert.equal(cachedHaMatterDashboardDiagnostics.nodeData.length, 31);
  assert.equal(cachedHaMatterDashboardDiagnostics.edgeData.length, 29);

const nativeBorderRouters = runAdaptor({
  entry: {
    adaptor: "ha-matter-ws-native-thread",
    files: ["td-ha-matter-ws-thread-border-routers.json"],
    rowExtractor: "ha-matter-ws-border-routers",
  },
  rawFiles: [{ borderRouters: [] }],
  rows: [{
    extAddressHex: "AABBCCDDEEFF0011",
    networkName: "Test Thread",
    hostname: "border-router.local.",
  }],
});
assertResult(nativeBorderRouters, {
  nodeIds: ["ha-matter-ws-border-router:aabbccddeeff0011"],
  edges: [],
  sourceNames: ["ha-matter-ws-thread-border-routers"],
  hasChildIndex: false,
});
assert.equal(nativeBorderRouters.nodeMap.values().next().value.isBorderRouter, true);

const nativeTopologyPayload = {
  topology: {
    collected_at: 1767888000000,
    nodes: [
      { id: "1", ext_address: "aabbccddeeff0011", kind: "matter", network_type: "thread", role: "leader", rloc16: 1024 },
      { id: "br_AABB", kind: "border_router", network_type: "thread", role: "router" },
      { id: "ap_1122", kind: "wifi_ap", network_type: "wifi", role: "ap" },
    ],
    connections: [{
      source: "1",
      target: "br_AABB",
      network: "thread",
      strength: "unknown",
      source_to_target: { strength: "medium", lqi: 2, rssi: -70 },
      target_to_source: { strength: "unknown" },
      via_route_table: true,
      path_cost: 1,
    }, {
      source: "1",
      target: "ap_1122",
      network: "wifi",
      strength: "strong",
      source_to_target: { strength: "strong", rssi: -55 },
    }],
  },
};
const nativeTopology = run(
  "ha-matter-ws-network-topology",
  ["td-ha-matter-ws-network-topology.json"],
  [nativeTopologyPayload],
);
assertResult(nativeTopology, {
  nodeIds: ["1", "br_AABB", "ap_1122"],
  edges: [
    ["1", "br_AABB", ["otbr_route"]],
    ["br_AABB", "1", ["otbr_route"]],
    ["1", "ap_1122", ["router_neighbor"]],
  ],
  sourceNames: ["ha-matter-ws-network-topology"],
  hasChildIndex: false,
});
assert.deepEqual(
  nativeTopology.edgeData.map((edge) => edge.nativeDirection),
  ["source_to_target", "target_to_source", "source_to_target"],
);
assert.equal(nativeTopology.edgeData[0].nativeConnection.path_cost, 1);
assert.deepEqual(nativeTopology.edgeData[0].nativeObservation, {
  strength: "medium",
  lqi: 2,
  rssi: -70,
});
const nativeTopologyProjection = projectObservedTopologyLinkCounts(
  nativeTopologyPayload.topology.nodes,
  nativeTopology,
);
assert.ok(nativeTopology.relationshipCapabilities.datasetWide.has("nativeTopologyConnections"));
assert.deepEqual(
  [
    nativeTopologyProjection.rows[0].observedTopologyLinks,
    nativeTopologyProjection.rows[0].observedTopologyLinksLq3,
    nativeTopologyProjection.rows[0].observedTopologyLinksLq2,
    nativeTopologyProjection.rows[0].observedTopologyLinksLq1,
  ],
  [3, 1, 1, 0],
);

const mergedHaMatterTopology = run(
  "ha-matter-ws-merge-topology",
  ["td-ha-matter-ws-network-topology.json"],
  [nativeTopologyPayload],
  [{
    topologyId: "matter-a",
    extAddress: "aabbccddeeff0011",
    role: "router",
  }],
);
assertResult(mergedHaMatterTopology, {
  nodeIds: ["matter-a", "br_AABB", "ap_1122"],
  edges: [
    ["matter-a", "br_AABB", ["otbr_route"]],
    ["br_AABB", "matter-a", ["otbr_route"]],
    ["matter-a", "ap_1122", ["router_neighbor"]],
  ],
  sourceNames: ["ha-matter-ws", "ha-matter-ws-network-topology"],
  hasChildIndex: true,
});
const mergedHaMatterProjection = projectObservedTopologyLinkCounts(
  [{ topologyId: "matter-a", extAddress: "aabbccddeeff0011" }],
  mergedHaMatterTopology,
);
assert.equal(mergedHaMatterProjection.rows[0].observedTopologyLinks, 3);
assert.ok(mergedHaMatterTopology.relationshipCapabilities.datasetWide.has("nativeTopologyConnections"));

const nativeTopologyModelRoundTrip = emitAdaptorResult(
  createAdaptorModelFromResult(nativeTopology),
);
assert.ok(nativeTopologyModelRoundTrip.relationshipCapabilities.datasetWide.has("nativeTopologyConnections"));
const nativeTopologyWrapperRoundTrip = emitThroughAdaptorModel({
  ...nativeTopology,
  nodeData: nativeTopology.nodeData.map((node) => ({ ...node })),
  nodeMap: new Map(nativeTopology.nodeMap),
  rawByIdForDetails: new Map(nativeTopology.rawByIdForDetails),
});
assert.ok(nativeTopologyWrapperRoundTrip.relationshipCapabilities.datasetWide.has("nativeTopologyConnections"));

const devicesEnvelope = { data: [
  { id: "device-a", attributes: { extAddress: "aa00112233445566", hostName: "Device A", role: "router" } },
  { id: "device-b", attributes: { extAddress: "bb00112233445566", hostName: "Device B", role: "router" } },
] };
const basicDiagnostics = { data: [{ attributes: {
  extAddress: "aa00112233445566",
  rloc16: "0x1000",
  basicOnly: true,
  shared: "basic",
} }] };
const meshDiagnostics = [{
  extAddress: "aa00112233445566",
  rloc16: "0x1000",
  role: "router",
  shared: "mesh",
  route: { routeData: [{ routeId: 8, linkQualityIn: 2, linkQualityOut: 3 }] },
  children: [{ extAddress: "cc00112233445566", rloc16: "0x1001", linkMargin: 20 }],
  routerNeighbors: [{ extAddress: "bb00112233445566", rloc16: "0x2000", linkMargin: 30 }],
}, {
  extAddress: "bb00112233445566",
  rloc16: "0x2000",
  role: "router",
}];
const restFiles = [
  "td-otbr-restapi-devices.json",
  "td-otbr-restapi-diagnostics.json",
  "td-otbr-restapi-mesh-diagnostics-fetch-all.json",
];
const restRawFiles = [devicesEnvelope, basicDiagnostics, meshDiagnostics];
const rest = run("otbr-restapi", restFiles, restRawFiles);
assertResult(rest, {
  nodeIds: ["aa00112233445566", "bb00112233445566", "cc00112233445566"],
  edges: [
    ["aa00112233445566", "bb00112233445566", ["otbr_route", "otbr_route_router", "router_neighbor"]],
    ["aa00112233445566", "cc00112233445566", ["otbr_child"]],
  ],
  sourceNames: ["otbr_restapi_devices", "otbr_restapi_diagnostics", "restapi_mesh_diagnostics"],
  hasChildIndex: true,
});
assert.equal(rest.rawByIdForDetails.get("aa00112233445566").shared, "mesh");
assert.equal(rest.rawByIdForDetails.get("aa00112233445566").basicOnly, true);
assert.equal(rest.routerNeighborByRloc16.get("0x1000").router_neighbor_table.length, 1);
assert.equal(rest.routerChildByRloc16.get("0x1000").router_child_table.length, 1);

const projectedCounts = projectObservedTopologyLinkCounts([
  { extAddress: "aa00112233445566", totalLinks: 99 },
  { extAddress: "bb00112233445566" },
  { extAddress: "cc00112233445566" },
  { extAddress: "dd00112233445566" },
], {
  nodeData: [{ id: "a" }, { id: "b" }, { id: "c" }],
  nodeMap: new Map([
    ["a", { extAddress: "aa00112233445566" }],
    ["b", { extAddress: "bb00112233445566" }],
    ["c", { extAddress: "cc00112233445566" }],
  ]),
  rawByIdForDetails: new Map(),
  edgeData: [
    { id: "route-a-b", from: "a", to: "b", lqLevel: 3, linkCategories: ["router_neighbor"] },
    { id: "parallel-a-b", from: "a", to: "b", lqLevel: 1, linkCategories: ["router_neighbor"] },
    { id: "reverse-b-a", from: "b", to: "a", lqLevel: 2, linkCategories: ["router_neighbor"] },
    { id: "route-a-b", from: "a", to: "b", lqLevel: 3, linkCategories: ["router_neighbor"] },
  ],
  relationshipCapabilities: {
    datasetWide: new Set(["routerNeighbors"]),
    byDeviceId: new Map(),
  },
});
assert.equal(projectedCounts.hasRelationshipEvidence, true);
assert.equal(projectedCounts.rows[0].totalLinks, 99);
assert.deepEqual(
  projectedCounts.rows.slice(0, 2).map((row) => [
    row.observedTopologyLinks,
    row.observedTopologyLinksLq3,
    row.observedTopologyLinksLq2,
    row.observedTopologyLinksLq1,
  ]),
  [[3, 1, 1, 1], [3, 1, 1, 1]],
);
assert.deepEqual(
  [
    projectedCounts.rows[2].observedTopologyLinks,
    projectedCounts.rows[2].observedTopologyLinksLq3,
  ],
  [0, 0],
);
assert.equal("observedTopologyLinks" in projectedCounts.rows[3], false);

const s1Contract = JSON.parse(fs.readFileSync(
  "tests/fixtures/device_merge_contract.json",
  "utf8",
)).cases.find((item) => item.id === "s1-03-relationship-reconciliation");
assert.ok(s1Contract, "S1-03 shared relationship fixture exists");
const s1MergedRows = mergeRowsByStrategy(
  s1Contract.inputs.sources.map((source) => normalizeRows(source.records, source.name)),
  s1Contract.inputs.strategy,
);
const s1Adapted = run(
  "merged-detailed",
  ["td-merged-topology-all.json"],
  [s1MergedRows],
  s1MergedRows,
);
assert.deepEqual(
  s1Adapted.nodeData.map((node) => node.id),
  ["0x1000", "0x3000", "0x2000", "0x1001", "0x3001"],
);
assert.deepEqual(
  s1Adapted.edgeData.map((edge) => [edge.from, edge.to, edge.linkCategories]),
  [
    ["0x1000", "0x2000", ["router_neighbor"]],
    ["0x1000", "0x1001", ["default_children"]],
    ["0x3000", "0x3001", ["default_children"]],
  ],
);
assert.equal(new Set(s1Adapted.edgeData.map((edge) => edge.id)).size, 3);
const s1LinkProjection = projectObservedTopologyLinkCounts(s1MergedRows, s1Adapted);
assert.deepEqual(
  s1LinkProjection.rows.map((row) => [row.extAddress, row.observedTopologyLinks]),
  [["aa00112233445566", 2], ["bb00112233445566", 1]],
);

const noEvidenceProjection = projectObservedTopologyLinkCounts(
  [{
    extAddress: "aa00112233445566",
    observedTopologyLinks: 7,
    observedTopologyLinksLq3: 3,
    observedTopologyLinksLq2: 2,
    observedTopologyLinksLq1: 2,
  }],
  {
    edgeData: [],
    nodeData: [{ id: "a" }],
    nodeMap: new Map([["a", { extAddress: "aa00112233445566" }]]),
  },
);
assert.equal(noEvidenceProjection.hasRelationshipEvidence, false);
assert.equal(noEvidenceProjection.hasRelationshipCapability, false);
assert.equal("observedTopologyLinks" in noEvidenceProjection.rows[0], false);
assert.equal("observedTopologyLinksLq3" in noEvidenceProjection.rows[0], false);
assert.equal("observedTopologyLinksLq2" in noEvidenceProjection.rows[0], false);
assert.equal("observedTopologyLinksLq1" in noEvidenceProjection.rows[0], false);

const layoutAnchorProjection = projectObservedTopologyLinkCounts([
  { extAddress: "aa00112233445566" },
  { extAddress: "bb00112233445566" },
], {
  nodeData: [{ id: "a" }, { id: "b" }],
  nodeMap: new Map([
    ["a", { extAddress: "aa00112233445566" }],
    ["b", { extAddress: "bb00112233445566" }],
  ]),
  edgeData: [{ id: "layout-anchor", from: "a", to: "b", hidden: true, linkCategories: [] }],
  relationshipCapabilities: {
    datasetWide: new Set(["children"]),
    byDeviceId: new Map(),
  },
});
assert.equal(layoutAnchorProjection.hasRelationshipEvidence, false);
assert.deepEqual(
  layoutAnchorProjection.rows.map((row) => row.observedTopologyLinks),
  [0, 0],
);

const routerTableWithNextHop = run("router-table", ["td-otbr-cli-router-table.json"], [[
  { rloc16: "0x0400", extAddress: "aa00112233445566", nextHop: "2" },
  { rloc16: "0x0800", extAddress: "bb00112233445566", nextHop: "1" },
]]);
assert.equal(routerTableWithNextHop.edgeData.length, 1);
const routerTableProjection = projectObservedTopologyLinkCounts(
  [
    { rloc16: "0x0400", extAddress: "aa00112233445566" },
    { rloc16: "0x0800", extAddress: "bb00112233445566" },
  ],
  routerTableWithNextHop,
);
assert.equal(routerTableProjection.hasRelationshipCapability, false);
assert.equal(routerTableProjection.rows.some((row) => "observedTopologyLinks" in row), false);

const mdnsScopeRows = run("raw-array", ["td-mdns-scopes-thread.json"], [[
  { recordKey: "_meshcop._udp.local.|Border Router", scope: "_meshcop._udp.local.", name: "Border Router" },
]]);
const mdnsScopeProjection = projectObservedTopologyLinkCounts(mdnsScopeRows.rawByIdForDetails.values(), mdnsScopeRows);
assert.equal(mdnsScopeProjection.hasRelationshipCapability, false);

const rawArrayEmptyChildren = run("raw-array", ["relationship-rows.json"], [[
  { extAddress: "cc00112233445566", children: [] },
]]);
const rawArrayEmptyProjection = projectObservedTopologyLinkCounts(
  [{ extAddress: "cc00112233445566" }],
  rawArrayEmptyChildren,
);
assert.equal(rawArrayEmptyProjection.hasRelationshipCapability, true);
assert.equal(rawArrayEmptyProjection.rows[0].observedTopologyLinks, 0);
assert.equal(rawArrayEmptyProjection.rows[0].observedTopologyLinksLq3, 0);
const rawArrayRoundTrip = emitAdaptorResult(createAdaptorModelFromResult(rawArrayEmptyChildren));
assert.equal(rawArrayRoundTrip.relationshipCapabilities.byDeviceId.size, 1);

const failedEmptyRelationships = run("raw-array", ["failed-relationships.json"], [[
  { extAddress: "dd00112233445566", children: [], tableAttempt: { status: "timeout" } },
  { extAddress: "ee00112233445566", routes: [], error: { type: "CollectionFailed" } },
]]);
const failedEmptyProjection = projectObservedTopologyLinkCounts(
  [
    { extAddress: "dd00112233445566" },
    { extAddress: "ee00112233445566" },
  ],
  failedEmptyRelationships,
);
assert.equal(failedEmptyProjection.hasRelationshipCapability, false);
assert.equal(failedEmptyProjection.rows.some((row) => "observedTopologyLinks" in row), false);

const missingRawArray = run("raw-array", ["missing.json"], [null]);
const loadedEmptyRawArray = run("raw-array", ["empty.json"], [[]]);
assert.equal(missingRawArray.relationshipCapabilities.byDeviceId.size, 0);
assert.equal(loadedEmptyRawArray.relationshipCapabilities.byDeviceId.size, 0);

function projectPerRouterNeighborTable(tableAttempt) {
  const result = run(
    "meshdiag-networkdiag",
    ["td-otbr-cli-meshdiag-topology.json", "td-otbr-cli-meshdiag-router-neighbortables.json"],
    [[{ rloc16: "0x1000", extAddress: "dd00112233445566", role: "router" }], [{
      rloc16: "0x1000",
      router_neighbor_table: [],
      tableAttempt,
    }]],
  );
  return projectObservedTopologyLinkCounts(
    [{ rloc16: "0x1000", extAddress: "dd00112233445566" }],
    result,
  );
}

const successfulEmptyNeighborTable = projectPerRouterNeighborTable({ status: "success" });
assert.equal(successfulEmptyNeighborTable.hasRelationshipCapability, true);
assert.equal(successfulEmptyNeighborTable.rows[0].observedTopologyLinks, 0);
for (const status of ["timeout", "error", "protocol-error"]) {
  const failedEmptyNeighborTable = projectPerRouterNeighborTable({ status });
  assert.equal(failedEmptyNeighborTable.hasRelationshipCapability, false);
  assert.equal("observedTopologyLinks" in failedEmptyNeighborTable.rows[0], false);
}

assert.deepEqual(extractOtbrRestApiItems({ extAddress: "AA", attributes: { role: "router" } }), [
  { extAddress: "AA", attributes: { role: "router" }, role: "router" },
]);
const extracted = extractOtbrRestApiSources(new Map(restFiles.map((name, index) => [name, restRawFiles[index]])));
assert.equal(extracted.diagnostics[0].shared, "mesh");
assert.equal(extracted.diagnostics[0].basicOnly, true);

if (process.argv.includes("--write-baseline")) {
  const { writeCachedAdaptorSnapshot } = await import("./run-adaptor-output-snapshot.mjs");
  writeCachedAdaptorSnapshot();
} else {
  process.stdout.write(`${JSON.stringify({ adaptorCount: 12 })}\n`);
}