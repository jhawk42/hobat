import assert from "node:assert/strict";

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