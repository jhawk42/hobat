import assert from "node:assert/strict";

import {
  applyMeshLabHybridSeedLayout,
  classifyMeshLabGraph,
  placeIsolatedMeshLabNodes,
  placeMeshLabChildren,
  placeMeshLabRouters,
} from "../../src/js/tdash-layouts.js";

const clone = (value) => JSON.parse(JSON.stringify(value));
const nodes = [
  { id: "r-a", isRouter: true },
  { id: "r-b", isRouter: true },
  { id: "mtd", mode_device: "MTD" },
  { id: "tie", mode_device: "MTD" },
  { id: "isolated" },
];
const edges = [
  { from: "r-a", to: "r-b", lqLevel: 3, linkCategories: ["router_neighbor"] },
  { from: "r-a", to: "mtd", isParentChild: true, linkCategories: ["otbr_child"] },
  { from: "r-a", to: "tie", isParentChild: true, linkCategories: ["otbr_child"] },
  { from: "r-b", to: "tie", isParentChild: true, linkCategories: ["otbr_child"] },
];

const stagedNodes = clone(nodes);
const classification = classifyMeshLabGraph(stagedNodes, clone(edges));
assert.deepEqual(classification.outerRouters.map((node) => node.id), ["r-a", "r-b"]);
const routerPlacement = placeMeshLabRouters(classification);
const childTypes = placeMeshLabChildren(classification, routerPlacement);
const isolated = placeIsolatedMeshLabNodes(classification, routerPlacement.outerRadius, childTypes);
assert.equal(childTypes.get("mtd"), "mtd");
assert.equal(isolated.isolated[0].id, "isolated");
assert.equal(isolated.radius >= 1260, true);

const first = clone(nodes);
const second = clone(nodes).reverse();
const report = applyMeshLabHybridSeedLayout(first, clone(edges));
applyMeshLabHybridSeedLayout(second, clone(edges).reverse());
const positions = (values) => values.map(({ id, x, y, fixed, physics }) => ({ id, x, y, fixed, physics })).sort((left, right) => left.id.localeCompare(right.id));
assert.deepEqual(positions(first), positions(second));
first.forEach((node) => {
  assert.equal(Number.isFinite(node.x) && Number.isFinite(node.y), true);
  assert.deepEqual(node.fixed, { x: true, y: true });
  assert.equal(node.physics, false);
});
assert.equal(report.collisionIterations <= 90, true);
assert.equal(report.finalCollisionIterations <= 120, true);

const denseNodes = [{ id: "router", isRouter: true }];
const denseEdges = [];
for (let index = 0; index < 24; index += 1) {
  denseNodes.push({ id: `child-${String(index).padStart(2, "0")}`, mode_device: index % 3 === 0 ? "FTD" : "MTD" });
  denseEdges.push({ from: "router", to: `child-${String(index).padStart(2, "0")}`, isParentChild: true, linkCategories: ["otbr_child"] });
}
const denseReport = applyMeshLabHybridSeedLayout(denseNodes, denseEdges);
assert.equal(denseReport.collisionIterations <= 90, true);
assert.equal(denseReport.finalCollisionIterations <= 120, true);
assert.equal(denseNodes.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y)), true);

console.log(JSON.stringify({ nodes: first.length, denseNodes: denseNodes.length, bounded: true }));