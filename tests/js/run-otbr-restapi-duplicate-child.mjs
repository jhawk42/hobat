import assert from "node:assert/strict";

import { runAdaptor } from "../../src/js/tdash-adaptors.js";


const devicesEnvelope = { data: [
  { id: "device-a", attributes: { extAddress: "aa00112233445566", hostName: "Device A", role: "router" } },
] };
const basicDiagnostics = { data: [{ attributes: {
  extAddress: "aa00112233445566",
  rloc16: "0x1000",
} }] };
const meshDiagnostics = [{
  extAddress: "aa00112233445566",
  rloc16: "0x1000",
  role: "router",
  childTable: [{ childId: 1, linkQuality: 3 }],
  children: [{ extAddress: "cc00112233445566", rloc16: "0x1001", linkMargin: 20 }],
}];

const result = runAdaptor({
  entry: {
    adaptor: "otbr-restapi",
    files: [
      "td-otbr-restapi-devices.json",
      "td-otbr-restapi-diagnostics.json",
      "td-otbr-restapi-mesh-diagnostics-fetch-all.json",
    ],
  },
  rawFiles: [devicesEnvelope, basicDiagnostics, meshDiagnostics],
  rows: [],
});

const matchingChildIds = result.nodeData
  .filter((node) => result.nodeMap.get(node.id)?.rloc16 === "0x1001")
  .map((node) => node.id);

assert.deepEqual(matchingChildIds, ["0x1001"]);
assert.equal(result.nodeMap.get("0x1001")?.extAddress, "cc00112233445566");
assert.deepEqual(
  result.edgeData.map((edge) => [edge.from, edge.to, edge.linkCategories]),
  [["aa00112233445566", "0x1001", ["otbr_child"]]],
);

process.stdout.write(`${JSON.stringify({ duplicateChildNodes: 0 })}\n`);