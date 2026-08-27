import assert from "node:assert/strict";

import {
  applyRingStarSeedLayout,
  assignRingMembership,
  calculateRingRadii,
  classifyRingGraph,
  placeRingNodes,
} from "../../src/js/tdash-layouts.js";

const clone = (value) => JSON.parse(JSON.stringify(value));
const nodes = [
  { id: "br", isRouter: true, isBorderRouter: true },
  { id: "r-a", isRouter: true },
  { id: "r-b", isRouter: true },
  { id: "ftd", mode_device: "FTD" },
  { id: "tie", mode_device: "MTD" },
  { id: "isolated" },
];
const edges = [
  { from: "br", to: "r-a", lqLevel: 3, linkCategories: ["router_neighbor"] },
  { from: "r-a", to: "r-b", lqLevel: 3, linkCategories: ["router_neighbor"] },
  { from: "br", to: "ftd", isParentChild: true, linkCategories: ["default_children"] },
  { from: "r-a", to: "tie", isParentChild: true, linkCategories: ["otbr_child"] },
  { from: "r-b", to: "tie", isParentChild: true, linkCategories: ["otbr_child"] },
];

const classification = classifyRingGraph(clone(nodes), clone(edges));
const membership = assignRingMembership(classification);
assert.deepEqual([...membership.childrenByParent.get("r-a")], ["tie"]);
assert.deepEqual([...membership.childrenByParent.get("r-b")], ["tie"]);
const radii = calculateRingRadii(classification.routers.length);
assert.deepEqual(radii, { router: 380, ftd: 600, mtd: 740, isolated: 950, fallback: 1060 });
placeRingNodes(classification, membership, radii);

const first = clone(nodes);
const second = clone(nodes).reverse();
const report = applyRingStarSeedLayout(first, clone(edges));
applyRingStarSeedLayout(second, clone(edges).reverse());
const positions = (values) => values.map(({ id, x, y, fixed, physics }) => ({ id, x, y, fixed, physics })).sort((left, right) => left.id.localeCompare(right.id));
assert.deepEqual(positions(first), positions(second));
first.forEach((node) => {
  assert.equal(Number.isFinite(node.x) && Number.isFinite(node.y), true);
  assert.deepEqual(node.fixed, { x: true, y: true });
  assert.equal(node.physics, false);
});
assert.equal(report.collisionIterations <= 120, true);
assert.equal(report.coupledCollisionIterations <= 120, true);

const denseNodes = [{ id: "router", isRouter: true }];
const denseEdges = [];
for (let index = 0; index < 24; index += 1) {
  denseNodes.push({ id: `child-${String(index).padStart(2, "0")}`, mode_device: "MTD" });
  denseEdges.push({ from: "router", to: `child-${String(index).padStart(2, "0")}`, isParentChild: true, linkCategories: ["otbr_child"] });
}
const denseReport = applyRingStarSeedLayout(denseNodes, denseEdges);
assert.equal(denseReport.collisionIterations <= 120, true);
assert.equal(denseReport.coupledCollisionIterations <= 120, true);
assert.equal(denseNodes.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y)), true);

console.log(JSON.stringify({ nodes: first.length, denseNodes: denseNodes.length, bounded: true }));