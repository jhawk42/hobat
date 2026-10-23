import assert from "node:assert/strict";

import { runAdaptor } from "../../src/js/tdash-adaptors.js";


const rows = [{
  rloc16: "0x8c00",
  deviceLabel: "Office Router",
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
assert.equal(result.nodeMap.get("0x8c00")?.deviceLabel, "Office Router");
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
assert.equal(childrenEdge?.color, "#008080");
assert.equal(childrenEdge?.lqLevel, 3);
assert.equal(childrenEdge?.linkMargin, 31);
assert.equal(childrenEdge?.averageRssi, -69);

for (const [metrics, color, lqLevel] of [
  [{ linkMargin: 31, linkQuality: 1 }, "#008080", 3],
  [{ linkMargin: 12, linkQuality: 3 }, "#D55E00", 2],
  [{ linkMargin: 5, linkQuality: 3 }, "#c62828", 1],
  [{ linkQuality: 2 }, "#D55E00", 2],
]) {
  const adapted = runAdaptor({
    entry: { adaptor: "merged-detailed", files: ["td-merged-topology-all.json"] },
    rawFiles: [[{
      ...rows[0],
      children: [{
        ...rows[0].children[0],
        ...metrics,
        linkMargin: metrics.linkMargin,
      }],
    }]],
    rows: [],
  });
  const edge = adapted.edgeData.find((edge) => edge.linkCategories.includes("default_children"));
  assert.equal(edge?.color, color, JSON.stringify(metrics));
  assert.equal(edge?.lqLevel, lqLevel, JSON.stringify(metrics));
  assert.equal(edge?.linkMargin, metrics.linkMargin);
  assert.equal(edge?.averageRssi, -69);
}

process.stdout.write(`${JSON.stringify({ syntheticRestChildren: 0 })}\n`);