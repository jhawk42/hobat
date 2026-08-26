import assert from "node:assert/strict";

import {
  buildTopologyEdgeIndexes,
  expandVisibleRelationship,
  topologyEndpointPairKey,
} from "../../src/js/tdash-topology-utils.js";

const edges = [
  { id: "neighbor-a", from: "Router-A", to: "Router-B", linkCategories: ["router-neighbor"] },
  { id: "neighbor-b", from: "router-b", to: "router-a", linkCategories: ["router-neighbor", "route"] },
  { id: "child", from: "router-a", to: "child-1", linkCategories: ["children", "otbr-child"] },
  { id: "hidden", from: "router-a", to: "child-1", linkCategories: ["children"], baseHidden: true },
  { id: "missing-target", from: "router-a", linkCategories: ["children"] },
];

const indexes = buildTopologyEdgeIndexes(edges);
assert.deepEqual(
  indexes.byEndpointPair.get(topologyEndpointPairKey("router-a", "router-b")).map((edge) => edge.id),
  ["neighbor-a", "neighbor-b"],
);
assert.deepEqual(indexes.incidentByNodeId.get("router-a").map((edge) => edge.id), [
  "neighbor-a",
  "neighbor-b",
  "child",
  "hidden",
]);
assert.deepEqual(indexes.byCategory.get("route").map((edge) => edge.id), ["neighbor-b"]);
assert.equal(indexes.byEndpointPair.has(topologyEndpointPairKey("router-a", undefined)), false);

const visibleNodeIds = new Set(["router-a"]);
const forcedEdgeIds = new Set();
const neighborExpansion = expandVisibleRelationship(
  {
    sourceId: "router-a",
    targetId: "router-b",
    category: "router-neighbor",
    directed: false,
    diagnosticRecord: { frameErrorRate: 30 },
    optionValue: "router-neighbor-err-rate-frame-critical",
  },
  indexes,
  visibleNodeIds,
  forcedEdgeIds,
);
const childExpansion = expandVisibleRelationship(
  {
    sourceId: "router-a",
    targetId: "child-1",
    category: "children",
    directed: false,
    diagnosticRecord: { linkQuality: 1 },
    optionValue: "child-lq-poor",
  },
  indexes,
  visibleNodeIds,
  forcedEdgeIds,
);

assert.deepEqual(neighborExpansion, { matchedEdgeCount: 2, expanded: true });
assert.deepEqual(childExpansion, { matchedEdgeCount: 1, expanded: true });
assert.deepEqual([...visibleNodeIds].sort(), ["child-1", "router-a", "router-b"]);
assert.deepEqual([...forcedEdgeIds].sort(), ["child", "neighbor-a", "neighbor-b"]);

console.log(JSON.stringify({
  endpointPairCount: indexes.byEndpointPair.size,
  incidentNodeCount: indexes.incidentByNodeId.size,
  categoryCount: indexes.byCategory.size,
  forcedEdgeIds: [...forcedEdgeIds].sort(),
}));