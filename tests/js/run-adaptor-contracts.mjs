import assert from "node:assert/strict";
import fs from "node:fs";

import {
  extractOtbrRestApiItems,
  extractOtbrRestApiSources,
  runAdaptor,
} from "../../src/js/tdash-adaptors.js";


function run(adaptor, files, rawFiles, rows = []) {
  return runAdaptor({ entry: { adaptor, files }, rawFiles, rows });
}

function assertResult(result, expected) {
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
    routerNeighbors: [{ sourceId: "matter:a", targetId: "matter:b", lqi: 3 }],
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
assert.equal(haMatter.rawByIdForDetails.get("matter:a").role, "Router");

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
assert.equal(cachedHaMatter.nodeData.length, 2);
assert.equal(cachedHaMatter.edgeData.length, 1);
assert.equal(cachedHaMatter.edgeData[0].arrows, "to");

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

assert.deepEqual(extractOtbrRestApiItems({ extAddress: "AA", attributes: { role: "router" } }), [
  { extAddress: "AA", attributes: { role: "router" }, role: "router" },
]);
const extracted = extractOtbrRestApiSources(new Map(restFiles.map((name, index) => [name, restRawFiles[index]])));
assert.equal(extracted.diagnostics[0].shared, "mesh");
assert.equal(extracted.diagnostics[0].basicOnly, true);

process.stdout.write(`${JSON.stringify({ adaptorCount: 9 })}\n`);