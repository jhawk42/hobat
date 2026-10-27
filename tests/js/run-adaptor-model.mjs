import assert from "node:assert/strict";
import { adaptUnified } from "../../src/js/tdash-adaptor-unified.js";
import { projectObservedTopologyLinkCounts } from "../../src/js/tdash-adaptor-model.js";
import { buildDeviceProjections } from "../../src/js/tdash-device-projection.js";
import { createTopologyViewModel, resolveTopologyNodeId } from "../../src/js/tdash-topology-view-model.js";
import { findTableRowByDeviceId } from "../../src/js/tdash-table-renderer.js";
import { datasetIsAvailable, sourceHasAvailableDatasets } from "../../src/js/tdash-capabilities.js";

import {
  createAdaptorModel,
  emitAdaptorResult,
  registerDetails,
  registerDevice,
  registerRelationship,
  registerRouterChildRows,
  registerRouterNeighborRows,
  validateAdaptorModel,
} from "../../src/js/tdash-adaptor-model.js";
import {
  emitThroughAdaptorModel,
  resolveBorderRouterEvidence,
} from "../../src/js/tdash-adaptor-shared.js";


const model = createAdaptorModel(["fixture"]);
const unifiedEntry = {
  source: "ha-matter-ws", files: ["unified-fixture.json"], unified: {},
};
const scopedRows = [
  { _unifiedRecordId: "a", _networkInstance: "n1", extAddress: "aa11", role: "child",
    matter: { matterId: "1111222233334444-0000000000000001" },
    powerSources: [{ batteryPercent: 0 }], nativeNodeIds: ["native-a"] },
  { _unifiedRecordId: "b", _networkInstance: "n1", extAddress: "aa11", role: "router",
    matter: { matterId: "2222333344445555-0000000000000001" } },
  { _unifiedRecordId: "c", _networkInstance: "n2", extAddress: "aa11", role: "leader",
    nativeRelationships: [{ sourceId: "c", targetId: "wifi", networkType: "wifi", strength: "strong",
      sourceToTarget: { strength: "weak", lqi: 0, rssi: -80 },
      targetToSource: { strength: "strong", lqi: 3, rssi: -40 } }] },
  { _unifiedRecordId: "parent", _networkInstance: "n1", extAddress: "bb11", role: "router",
    children: [{ targetId: "a" }],
    routerNeighbors: [{ extAddress: "aa11", matter: { matterId: "1111222233334444-0000000000000001" }, lqi: 2 }],
    links1: [{ targetId: "a" }],
    route: { routeData: [{ targetId: "a", routeCost: 0, linkQualityIn: 0 }] },
    nativeRelationships: [
      { sourceId: "parent", targetId: "wifi", networkType: "ethernet", strength: "strong" },
      { sourceId: "parent", targetId: "missing", networkType: "thread", unresolvedEndpoints: ["missing"] },
    ] },
  { _unifiedRecordId: "wifi", _networkInstance: null, id: "native-ap", type: "nativeDevice" },
  { _unifiedRecordId: "service", _networkInstance: null, type: "service", deviceLabel: "Service" },
];
const unchangedRows = structuredClone(scopedRows);
const unifiedResult = adaptUnified(new Map(), scopedRows, unifiedEntry);
assert.deepEqual(scopedRows, unchangedRows);
assert.equal(unifiedResult.nodeData.length, scopedRows.length);
assert.equal(unifiedResult.edgeData.length, 4);
const canonicalChild = unifiedResult.edgeData.find((edge) => edge.from === "parent" && edge.to === "a");
assert.ok(canonicalChild.linkCategories.includes("default_children"));
assert.ok(canonicalChild.linkCategories.includes("default_1_links"));
assert.ok(canonicalChild.linkCategories.includes("otbr_route"));
assert.equal(canonicalChild.routeCost, 0);
assert.equal(canonicalChild.lqiIn, 0);
assert.equal(unifiedResult.nodeData.find((node) => node.id === "wifi").isRouter, false);
assert.equal(unifiedResult.nodeData.find((node) => node.id === "service").themeRole, "unknown");
assert.deepEqual(unifiedResult.rawByIdForDetails.get("a").powerSources, [{ batteryPercent: 0 }]);
assert.equal(unifiedResult.edgeData.find((edge) => edge.from === "c").lqi, 0);
assert.equal(unifiedResult.edgeData.find((edge) => edge.from === "wifi").rssi, -40);
const qualitative = unifiedResult.edgeData.find((edge) => edge.from === "parent" && edge.to === "wifi");
assert.equal(qualitative.strength, "strong");
assert.equal(qualitative.lqi, undefined);
assert.equal(qualitative.lqLevel, 0);
assert.equal(qualitative.arrows, undefined);
const observedRows = projectObservedTopologyLinkCounts(scopedRows, unifiedResult).rows;
assert.equal(observedRows.find((row) => row._unifiedRecordId === "a").observedTopologyLinks, 1);
assert.equal(observedRows.find((row) => row._unifiedRecordId === "b").observedTopologyLinks, undefined);
const unifiedView = createTopologyViewModel(unifiedResult, buildDeviceProjections(scopedRows));
assert.equal(unifiedView.projectionByNodeId.get("parent").diagnostics.hasRouters, true);
assert.equal(unifiedView.projectionByNodeId.get("a").diagnostics.hasRouters, false);
for (const row of scopedRows) {
  assert.equal(resolveTopologyNodeId(unifiedView, row), row._unifiedRecordId);
  assert.equal(unifiedView.projectionByNodeId.get(row._unifiedRecordId).deviceId, row._unifiedRecordId);
  assert.equal(findTableRowByDeviceId(scopedRows, row._unifiedRecordId), row);
}
assert.throws(() => adaptUnified(new Map(), [scopedRows[0], scopedRows[0]], unifiedEntry), /unique committed/);
assert.throws(() => adaptUnified(new Map(), [{}], unifiedEntry), /unique committed/);
const offline = { sources: { "ha-matter-ws": { state: "unavailable" } },
  files: { "unified-fixture.json": { cached: false, buildableFromCache: true } } };
assert.equal(datasetIsAvailable(unifiedEntry, offline), true);
assert.equal(sourceHasAvailableDatasets(unifiedEntry.source, offline, [unifiedEntry]), true);
assert.equal(datasetIsAvailable({ ...unifiedEntry, unified: undefined }, offline), false);
assert.equal(sourceHasAvailableDatasets(unifiedEntry.source, offline, [{ ...unifiedEntry, selectable: false }]), false);
assert.equal(datasetIsAvailable(unifiedEntry, { ...offline, files: {} }), false);
const routerId = registerDevice(model, {
  extaddr: "AA00112233445566",
  rloc16: "0x2800",
  device_label: "Router",
  _source_files: ["router.json"],
}, {
  presentation: {
    label: "Router\n0x2800",
    shape: "hexagon",
    isBorderRouter: false,
    is_border_router: true,
    br: false,
  },
  nodeRecord: { isBorderRouter: false, is_border_router: true, br: false },
  sourceName: "router.json",
});
const duplicateId = registerDevice(model, {
  extAddress: "aa00112233445566",
  role: "router",
}, { presentation: { color: "blue" } });
const childId = registerDevice(model, {
  rloc16: "0x2808",
  role: "child",
}, { presentation: { label: "Child", shape: "dot" } });

assert.equal(routerId, "aa00112233445566");
assert.equal(duplicateId, routerId);
assert.equal(childId, "0x2808");
assert.equal(model.devicesById.size, 2);
assert.equal(model.identityToDeviceId.get("rloc16:0x2800"), routerId);

registerDetails(model, routerId, {
  extAddress: "aa00112233445566",
  _merge_conflicts: [{ field: "name" }],
}, "replace");
registerDetails(model, routerId, { diagnostic: true }, "merge");
registerDetails(model, routerId, {
  isBorderRouter: false,
  is_border_router: true,
  br: false,
}, "merge");

const relationship = {
  sourceId: routerId,
  targetId: childId,
  category: "otbr_child",
  directed: true,
  metrics: { linkMargin: 20 },
  presentation: { dashes: false },
  sourceName: "router.json",
  rawRecord: { childId: 1 },
};
registerRelationship(model, relationship);
registerRelationship(model, relationship);
registerRelationship(model, { ...relationship, category: "router_neighbor" });
assert.equal(model.relationships.length, 2);

registerRouterNeighborRows(model, "0x2800", [{ extAddress: "bb" }]);
registerRouterChildRows(model, "0x2800", [{ rloc16: "0x2808" }]);
assert.doesNotThrow(() => validateAdaptorModel(model));

const result = emitAdaptorResult(model);
const routerNodeData = result.nodeData.find((node) => node.id === routerId);
const routerNodeRecord = result.nodeMap.get(routerId);
const routerDetails = result.rawByIdForDetails.get(routerId);
for (const record of [routerNodeData, routerNodeRecord, routerDetails]) {
  assert.equal(record.isBorderRouter, false);
  assert.equal("br" in record, false);
  assert.equal("is_border_router" in record, false);
  assert.deepEqual(record._merge_conflicts, [
    { path: "isBorderRouter", current: false, incoming: true },
  ]);
}
assert.deepEqual(result.sourceNames, ["fixture", "router.json"]);
assert.equal(result.nodeData.length, 2);
assert.equal(result.edgeData.length, 2);
assert.deepEqual(result.edgeData.map((edge) => edge.linkCategories), [
  ["otbr_child"],
  ["router_neighbor"],
]);
assert.equal(result.rawByIdForDetails.get(routerId).diagnostic, true);
assert.equal(
  result.routerNeighborByRloc16.get("0x2800").router_neighbor_table.length,
  1,
);
assert.equal(
  result.routerChildByRloc16.get("0x2800").router_child_table.length,
  1,
);

const trueWinsWhenAuthorityIsUnavailable = resolveBorderRouterEvidence(
  { isBorderRouter: false },
  { isBorderRouter: true },
);
assert.equal(trueWinsWhenAuthorityIsUnavailable.value, true);
assert.deepEqual(trueWinsWhenAuthorityIsUnavailable.conflicts, [
  { path: "isBorderRouter", current: true, incoming: false },
]);
assert.equal(
  resolveBorderRouterEvidence(
    { isBorderRouter: true },
    { isBorderRouter: false },
  ).value,
  true,
);

const higherAuthorityFalseWins = resolveBorderRouterEvidence(
  {
    isBorderRouter: false,
    _source_files: ["td-otbr-restapi-devices-fetch.json"],
  },
  {
    isBorderRouter: true,
    _source_files: ["td-otbr-cli-networkdiag-fetch-all.json"],
  },
);
assert.equal(higherAuthorityFalseWins.value, true);
assert.deepEqual(higherAuthorityFalseWins.conflicts, [
  { path: "isBorderRouter", current: true, incoming: false },
]);

const conflictOutput = emitThroughAdaptorModel({
  sourceNames: ["fixture"],
  edgeData: [],
  nodeData: [{ id: "conflict-device", isBorderRouter: true }],
  nodeMap: new Map([[
    "conflict-device",
    {
      id: "conflict-device",
      isBorderRouter: true,
      _merge_conflicts: trueWinsWhenAuthorityIsUnavailable.conflicts,
    },
  ]]),
  rawByIdForDetails: new Map([[
    "conflict-device",
    { id: "conflict-device", br: false },
  ]]),
});
for (const record of [
  conflictOutput.nodeData[0],
  conflictOutput.nodeMap.get("conflict-device"),
  conflictOutput.rawByIdForDetails.get("conflict-device"),
]) {
  assert.equal(record.isBorderRouter, true);
  assert.equal("br" in record, false);
  assert.deepEqual(record._merge_conflicts, [
    { path: "isBorderRouter", current: true, incoming: false },
  ]);
}

assert.throws(
  () => registerRelationship(model, { ...relationship, targetId: "" }),
  /endpoint/i,
);

const invalidModel = createAdaptorModel();
const invalidSourceId = registerDevice(invalidModel, { rloc16: "0x3000" });
registerRelationship(invalidModel, {
  sourceId: invalidSourceId,
  targetId: "missing-device",
  category: "router_neighbor",
});
assert.throws(() => validateAdaptorModel(invalidModel), /unknown device/i);

process.stdout.write(`${JSON.stringify({
  deviceCount: result.nodeData.length,
  relationshipCount: result.edgeData.length,
})}\n`);