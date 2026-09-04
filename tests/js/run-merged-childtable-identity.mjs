import assert from "node:assert/strict";

import { runAdaptor } from "../../src/js/tdash-adaptors.js";


const rows = [{
  rloc16: "0x8c00",
  role: "router",
  mode: { device: "FTD" },
  route: { routeData: [{ routeId: 1, linkQualityIn: 2, linkQualityOut: 3, routeCost: 1 }] },
  childTable: [{
    rloc16: "0x8c31",
    extAddress: "9e829c2b32bc4050",
    deviceLabel: "Wine Cellar Ikea Leak Sensor",
    type: "mtd",
    linkQuality: 2,
    linkMargin: 19,
  }],
  children: [{
    rloc16: "0x8c32",
    extAddress: "aa829c2b32bc4050",
    deviceLabel: "Kitchen Button",
    linkMargin: 31,
    averageRssi: -69,
  }],
}, {
  rloc16: "0x8c31",
}, {
  rloc16: "0x0400",
}];

const result = runAdaptor({
  entry: { adaptor: "merged-detailed", files: ["td-merged-topology-all.json"] },
  rawFiles: [rows],
  rows: [],
});

assert.deepEqual(result.nodeData.map((node) => node.id), ["0x8c00", "0x8c31", "0x0400", "0x8c32"]);
assert.equal(result.nodeMap.get("0x8c31")?.extAddress, "9e829c2b32bc4050");
assert.equal(result.nodeMap.get("0x8c31")?.deviceLabel, "Wine Cellar Ikea Leak Sensor");
assert.equal(result.nodeData.some((node) => String(node.id).includes("rest-child")), false);

const routeEdge = result.edgeData.find((edge) => edge.linkCategories.includes("otbr_route"));
assert.equal(routeEdge?.color, "#008080");
assert.equal(routeEdge?.lqLevel, 3);
assert.equal(routeEdge?.lqiIn, 2);
assert.equal(routeEdge?.lqiOut, 3);

const childTableEdge = result.edgeData.find((edge) => edge.linkCategories.includes("otbr_child"));
assert.equal(childTableEdge?.color, "#D55E00");
assert.equal(childTableEdge?.lqLevel, 2);
assert.equal(childTableEdge?.linkMargin, 19);

const childrenEdge = result.edgeData.find((edge) => edge.linkCategories.includes("default_children"));
assert.equal(childrenEdge?.color, "#D55E00");
assert.equal(childrenEdge?.lqLevel, 2);
assert.equal(childrenEdge?.linkMargin, 31);

process.stdout.write(`${JSON.stringify({ syntheticRestChildren: 0 })}\n`);