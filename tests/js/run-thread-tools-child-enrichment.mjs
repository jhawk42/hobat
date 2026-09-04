import assert from "node:assert/strict";

import { runAdaptor } from "../../src/js/tdash-adaptors.js";


const diagnostics = [{
  macAddr: 0x1000,
  mode: { ftd: true },
  childTable: [{ childId: 1, linkQuality: 3 }],
  children: [{
    extAddress: "cc00112233445566",
    rloc16: "0x1001",
    linkMargin: 20,
    isDeviceTypeFtd: false,
  }],
}];

const result = runAdaptor({
  entry: { adaptor: "thread-tools-native", files: ["diagnostics.json"] },
  rawFiles: [{ diagnostics }],
  rows: [],
});

const matchingChildIds = result.nodeData
  .filter((node) => result.nodeMap.get(node.id)?.rloc16 === "0x1001")
  .map((node) => node.id);

assert.deepEqual(matchingChildIds, ["0x1001"]);
assert.equal(result.nodeMap.get("0x1001")?.extAddress, "cc00112233445566");

process.stdout.write(`${JSON.stringify({ enrichedChildNodes: 1 })}\n`);