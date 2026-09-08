import assert from "node:assert/strict";

import { runAdaptor } from "../../src/js/tdash-adaptors.js";
import { resolveLayoutCollisions } from "../../src/js/tdash-layouts.js";
import { assignParallelEdgeCurves } from "../../src/js/tdash-topology-renderer.js";
import { buildVisNodeData } from "../../src/js/tdash-topology-utils.js";

function mergedEdges(row) {
  return runAdaptor({
    entry: { adaptor: "merged-detailed", files: ["merged.json"] },
    rawFiles: [[row, { rloc16: "0x2000", role: "router" }, { rloc16: "0x3000", role: "router" }]],
    rows: [],
  }).edgeData;
}

function default3Edges(edges) {
  return edges.filter((edge) => edge.linkCategories.includes("default_3_links"));
}

const canonicalEdges = mergedEdges({ rloc16: "0x1000", role: "router", links3: [{ rloc16: "0x2000" }] });
assert.equal(default3Edges(canonicalEdges).length, 1);
const legacyEdges = mergedEdges({ rloc16: "0x1000", role: "router", "3_links": [{ rloc16: "0x2000" }] });
assert.equal(default3Edges(legacyEdges).length, 1);
const preferredEdges = mergedEdges({
  rloc16: "0x1000", role: "router",
  links3: [{ rloc16: "0x2000" }], "3_links": [{ rloc16: "0x3000" }],
});
assert.deepEqual(default3Edges(preferredEdges).map((edge) => edge.to), ["0x2000"]);

const coincident = [{ id: "alpha", x: 0, y: 0 }, { id: "beta", x: 0, y: 0 }];
const result = resolveLayoutCollisions(coincident, { separation: () => 100 });
assert.equal(Math.hypot(coincident[0].x - coincident[1].x, coincident[0].y - coincident[1].y) > 0, true);
assert.equal(result.converged, true);
const repeat = [{ id: "beta", x: 0, y: 0 }, { id: "alpha", x: 0, y: 0 }];
resolveLayoutCollisions(repeat, { separation: () => 100 });
assert.deepEqual(
  Object.fromEntries(coincident.map((node) => [node.id, [node.x, node.y]])),
  Object.fromEntries(repeat.map((node) => [node.id, [node.x, node.y]])),
);

const curveEdges = ["route", "neighbor", "diagnostic"].map((id) => ({ id, from: "a", to: "b" }));
assignParallelEdgeCurves(curveEdges, [{ id: "a", isRouter: true }, { id: "b", isRouter: true }]);
assert.equal(new Set(curveEdges.map((edge) => `${edge.smooth.type}:${edge.smooth.roundness}`)).size, 3);

const visNodes = buildVisNodeData(
  new Map([["node", { id: "node", totalLink1: 0, totalLink2: 1, totalLink3: 2, lq1Ratio: 0, lq3Ratio: 3 }]]),
  new Set(), new Map(), () => "node", new Map(),
);
assert.deepEqual(
  [visNodes[0].total_link_1, visNodes[0].total_link_2, visNodes[0].total_link_3, visNodes[0].lq1_ratio, visNodes[0].lq3_ratio],
  [0, 1, 2, 0, 3],
);

process.stdout.write("phase2 regressions passed\n");