import assert from "node:assert/strict";

import { runAdaptor } from "../../src/js/tdash-adaptors.js";


const rows = [{
  rloc16: "0x8c00",
  role: "router",
  mode: { device: "FTD" },
  childTable: [{
    rloc16: "0x8c31",
    extAddress: "9e829c2b32bc4050",
    deviceLabel: "Wine Cellar Ikea Leak Sensor",
    type: "mtd",
    linkMargin: 19,
  }],
}, {
  rloc16: "0x8c31",
}];

const result = runAdaptor({
  entry: { adaptor: "merged-detailed", files: ["td-merged-topology-all.json"] },
  rawFiles: [rows],
  rows: [],
});

assert.deepEqual(result.nodeData.map((node) => node.id), ["0x8c00", "0x8c31"]);
assert.equal(result.nodeMap.get("0x8c31")?.extAddress, "9e829c2b32bc4050");
assert.equal(result.nodeMap.get("0x8c31")?.deviceLabel, "Wine Cellar Ikea Leak Sensor");
assert.equal(result.nodeData.some((node) => String(node.id).includes("rest-child")), false);

process.stdout.write(`${JSON.stringify({ syntheticRestChildren: 0 })}\n`);