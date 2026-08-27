import assert from "node:assert/strict";

import {
  applyMeshLabHybridSeedLayout,
  applyMeshTreeHorizontalSeedLayout,
  applyMeshTreeVerticalSeedLayout,
  applyRingStarSeedLayout,
  buildMeshTreeZoningContext,
} from "../../src/js/tdash-layouts.js";

const clone = (value) => JSON.parse(JSON.stringify(value));
const nodes = [
  { id: "br", isRouter: true, isBorderRouter: true, hasChildren: true },
  { id: "r-a", isRouter: true, hasChildren: true },
  { id: "r-b", isRouter: true, hasChildren: false },
  { id: "ftd", mode_device: "FTD" },
  { id: "mtd", mode_device: "MTD" },
  { id: "tie", mode_device: "MTD" },
  { id: "isolated" },
];
const edges = [
  { id: "router", from: "br", to: "r-a", lqLevel: 3, linkCategories: ["router_neighbor"] },
  { id: "cycle-a", from: "r-a", to: "r-b", lqLevel: 3, linkCategories: ["router_neighbor"] },
  { id: "cycle-b", from: "r-b", to: "br", lqLevel: 2, linkCategories: ["router_neighbor"] },
  { id: "ftd-parent", from: "br", to: "ftd", isParentChild: true, linkCategories: ["default_children"] },
  { id: "mtd-parent", from: "r-a", to: "mtd", isParentChild: true, linkCategories: ["otbr_child"] },
  { id: "tie-b", from: "r-b", to: "tie", isParentChild: true, linkCategories: ["otbr_child"] },
  { id: "tie-a", from: "r-a", to: "tie", isParentChild: true, linkCategories: ["otbr_child"] },
];

function summarizeContext(context) {
  return {
    parents: [...context.parentByChild.entries()].sort(),
    zones: [...context.zoneByNodeId.entries()].sort(),
    degrees: [...context.nodeDegreeById.entries()].sort(),
    total: context.totalNodesClassified,
  };
}

function summarizeLayout(layoutNodes) {
  return layoutNodes.map((node) => ({
    id: node.id,
    x: node.x,
    y: node.y,
    fixed: node.fixed,
    physics: node.physics,
  })).sort((a, b) => a.id.localeCompare(b.id));
}

function summarizeCoordinates(layoutNodes) {
  return Object.fromEntries(summarizeLayout(layoutNodes).map(({ id, x, y }) => [id, [x, y]]));
}

const context = buildMeshTreeZoningContext(clone(nodes), clone(edges));
const shuffledContext = buildMeshTreeZoningContext(
  clone(nodes).reverse(),
  clone(edges).reverse(),
);
assert.deepEqual(summarizeContext(context), summarizeContext(shuffledContext));
assert.equal(context.parentByChild.get("tie"), "r-a");
assert.equal(context.totalNodesClassified, nodes.length);

const horizontalNodes = clone(nodes);
const verticalNodes = clone(nodes);
applyMeshTreeHorizontalSeedLayout(horizontalNodes, clone(edges));
applyMeshTreeVerticalSeedLayout(verticalNodes, clone(edges));
const horizontal = summarizeLayout(horizontalNodes);
const vertical = summarizeLayout(verticalNodes);
horizontal.forEach((node, index) => {
  assert.equal(Number.isFinite(node.x), true);
  assert.equal(Number.isFinite(node.y), true);
  assert.equal(vertical[index].x, node.y);
  assert.equal(vertical[index].y, node.x);
  assert.deepEqual(vertical[index].fixed, { x: node.fixed.y, y: node.fixed.x });
});

const ringNodes = clone(nodes);
applyRingStarSeedLayout(ringNodes, clone(edges));
ringNodes.forEach((node) => {
  assert.equal(Number.isFinite(node.x), true);
  assert.equal(Number.isFinite(node.y), true);
  assert.deepEqual(node.fixed, { x: true, y: true });
  assert.equal(node.physics, false);
});

const compactNodes = clone(nodes);
applyMeshLabHybridSeedLayout(compactNodes, clone(edges));
compactNodes.forEach((node) => {
  assert.equal(Number.isFinite(node.x), true);
  assert.equal(Number.isFinite(node.y), true);
});
assert.equal(Math.hypot(compactNodes.find((node) => node.id === "isolated").x, compactNodes.find((node) => node.id === "isolated").y) > 1000, true);
assert.deepEqual(summarizeCoordinates(horizontalNodes), {
  br: [-457, -4], ftd: [-900, -4], isolated: [1761, 9], mtd: [829, -118],
  "r-a": [138, -83], "r-b": [139, 71], tie: [834, -39],
});
assert.deepEqual(summarizeCoordinates(verticalNodes), {
  br: [-4, -457], ftd: [-4, -900], isolated: [9, 1761], mtd: [-118, 829],
  "r-a": [-83, 138], "r-b": [71, 139], tie: [-39, 834],
});
assert.deepEqual(summarizeCoordinates(ringNodes), {
  br: [-342, 166], ftd: [-559, 287], isolated: [0, -950], mtd: [-117, -731],
  "r-a": [0, -380], "r-b": [342, 166], tie: [700, 240],
});
assert.deepEqual(summarizeCoordinates(compactNodes), {
  br: [-514, 223], ftd: [-705, 318], isolated: [0, -1260], mtd: [-140, -930],
  "r-a": [0, -560], "r-b": [514, 223], tie: [720, -572],
});

console.log(JSON.stringify({
  context: summarizeContext(context),
  horizontal,
  vertical,
  ring: summarizeLayout(ringNodes),
  compact: summarizeLayout(compactNodes),
}));