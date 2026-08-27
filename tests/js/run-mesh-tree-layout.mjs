import assert from "node:assert/strict";

import {
  applyMeshTreeHorizontalSeedLayout,
  applyMeshTreeSeedLayout,
  applyMeshTreeVerticalSeedLayout,
  buildGraphAnalysis,
} from "../../src/js/tdash-layouts.js";

const clone = (value) => JSON.parse(JSON.stringify(value));
const nodes = [
  { id: "br", isRouter: true, isBorderRouter: true },
  { id: "r-a", isRouter: true },
  { id: "r-b", isRouter: true },
  { id: "child", mode_device: "MTD" },
  { id: "isolated" },
];
const edges = [
  { from: "br", to: "r-a", lqLevel: 3, linkCategories: ["router_neighbor"] },
  { from: "r-a", to: "r-b", lqLevel: 3, linkCategories: ["router_neighbor"] },
  { from: "r-b", to: "br", lqLevel: 2, linkCategories: ["router_neighbor"] },
  { from: "r-a", to: "child", isParentChild: true, linkCategories: ["otbr_child"] },
];

const summarizeAnalysis = (analysis) => ({
  components: analysis.components,
  roots: analysis.roots,
  parents: [...analysis.parentById.entries()],
  depths: [...analysis.depthById.entries()],
  degrees: [...analysis.degreeById.entries()],
});
const analysis = buildGraphAnalysis(clone(nodes), clone(edges));
const shuffled = buildGraphAnalysis(clone(nodes).reverse(), clone(edges).reverse());
assert.deepEqual(summarizeAnalysis(analysis), summarizeAnalysis(shuffled));
assert.deepEqual(analysis.components, [["br", "r-a", "r-b", "child"], ["isolated"]]);
assert.deepEqual(analysis.roots, ["br", "isolated"]);

const horizontal = clone(nodes);
const vertical = clone(nodes);
applyMeshTreeHorizontalSeedLayout(horizontal, clone(edges));
applyMeshTreeVerticalSeedLayout(vertical, clone(edges));
horizontal.sort((left, right) => left.id.localeCompare(right.id));
vertical.sort((left, right) => left.id.localeCompare(right.id));
horizontal.forEach((node, index) => {
  assert.equal(Number.isFinite(node.x) && Number.isFinite(node.y), true);
  assert.equal(vertical[index].x, node.y);
  assert.equal(vertical[index].y, node.x);
  assert.deepEqual(vertical[index].fixed, { x: node.fixed.y, y: node.fixed.x });
});
const generic = clone(nodes);
applyMeshTreeSeedLayout(generic, clone(edges), { orientation: "horizontal" });
assert.deepEqual(generic, clone(nodes).map((node) => horizontal.find((placed) => placed.id === node.id)));
assert.throws(() => applyMeshTreeSeedLayout(clone(nodes), clone(edges), { orientation: "diagonal" }), /Unknown mesh-tree orientation/);

console.log(JSON.stringify({ components: analysis.components.length, nodes: horizontal.length }));