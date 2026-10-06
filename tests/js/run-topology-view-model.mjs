import assert from "node:assert/strict";

import {
  buildTopologyDetails,
  buildTopologyStatus,
  computeSearchHighlight,
  computeTopologyVisibility,
  createTopologyEventBindings,
  createTopologyFilterState,
  createTopologySearchState,
  createTopologyViewModel,
  resolveTopologyNodeId,
} from "../../src/js/tdash-topology-view-model.js";
import { HA_MATTER_ROLE_POLICY } from "../../src/js/tdash-ha-matter-ws-roles.js";

const router = {
  id: "router-a",
  extAddress: "aaaaaaaaaaaaaaaa",
  rloc16: "0x1000",
  isRouter: true,
  hasChildren: true,
  color: { background: "#111111", border: "#222222" },
  borderWidth: 2,
  font: { color: "#333333" },
  isFtdRouter: true,
  router_child_max_err_rate_frame_pct: 30,
};
const child = {
  id: "child-a",
  extAddress: "bbbbbbbbbbbbbbbb",
  rloc16: "0x1001",
  color: { background: "#444444", border: "#555555" },
  borderWidth: 2,
  font: { color: "#666666" },
};
const rawRouter = {
  extAddress: router.extAddress,
  name: "Office Router",
  isFtdRouter: false,
  childTable: [{ extAddress: child.extAddress, frameErrorRate: 30 }],
};
const rawChild = { extAddress: child.extAddress, name: "Desk Sensor" };
const viewModel = createTopologyViewModel({
  nodeData: [router, child],
  edgeData: [{
    id: "child-edge",
    from: router.id,
    to: child.id,
    isParentChild: true,
    linkCategories: ["default_children", "otbr_child"],
  }],
  nodeMap: new Map([[router.id, router], [child.id, child]]),
  rawByIdForDetails: new Map([[router.id, rawRouter], [child.id, rawChild]]),
  routerNeighborByRloc16: new Map(),
  routerChildByRloc16: new Map([["0x1000", {
    childTable: [
      { extAddress: child.extAddress, frameErrorRate: 30 },
      { extAddress: child.extAddress, frameErrorRate: 30 },
    ],
  }]]),
  sourceNames: ["fixture.json"],
});

assert.notEqual(viewModel.nodes[0], router);
router.color.background = "mutated";
rawRouter.childTable[0].frameErrorRate = 0;
assert.equal(viewModel.originalNodeStyling.get(router.id).color.background, "#111111");
assert.equal(viewModel.rawByIdForDetails.get(router.id).childTable[0].frameErrorRate, 30);
assert.equal(resolveTopologyNodeId(viewModel, { extaddr: child.extAddress.toUpperCase() }), child.id);

const restDeviceId = "0011223344556677";
const restNode = { id: restDeviceId, extAddress: restDeviceId, rloc16: "0x1002" };
const restViewModel = createTopologyViewModel({
  nodeData: [restNode],
  edgeData: [],
  nodeMap: new Map([[restNode.id, restNode]]),
  rawByIdForDetails: new Map([[restNode.id, restNode]]),
});
assert.equal(
  resolveTopologyNodeId(restViewModel, { extAddress: restDeviceId, rloc16: "0x1002" }),
  restDeviceId,
);

const visibility = computeTopologyVisibility(
  viewModel,
  createTopologyFilterState("all", "all", "router-child-err-rate-frame-high"),
);
assert.deepEqual([...visibility.visibleNodeIds].sort(), [child.id, router.id]);
assert.deepEqual([...visibility.forcedVisibleEdgeIds], ["child-edge"]);
assert.equal(visibility.matchedTargetNodeCount, 1);

const searchState = createTopologySearchState("desk", false, viewModel);
const highlight = computeSearchHighlight(viewModel, searchState);
assert.equal(highlight.focusTarget, child.id);
assert.equal(highlight.nodeUpdates.find((update) => update.id === child.id).borderWidth, 4);

const details = buildTopologyDetails(viewModel, router.id);
assert.equal(details.isFtdRouter, true);
assert.equal(details.graph.graphLinkCount, 1);
assert.equal(details.graph.hasChildren, true);

const status = buildTopologyStatus(viewModel, visibility, searchState, 1.234, {
  diagnosticMode: "router-child-err-rate-frame-high",
  physicsProfileLabel: "Fixture",
  stabilizationMs: 1250,
});
assert.equal(status.scale, "1.23x");
assert.match(status.text, /Showing: 2 nodes, 1 links/);
assert.match(status.text, /Search: "desk" — 1 of 2 rows match/);

const haNode = {
  id: "ha-reed",
  role: "Router",
  rloc16: "0x1000",
  isRouter: false,
  isLeader: false,
  isReed: true,
};
const haViewModel = createTopologyViewModel({
  nodeData: [haNode],
  edgeData: [],
  nodeMap: new Map([[haNode.id, haNode]]),
  rawByIdForDetails: new Map([[haNode.id, haNode]]),
  routerNeighborByRloc16: new Map(),
  routerChildByRloc16: new Map(),
  sourceNames: ["ha-matter-ws"],
}, new Map(), { rolePolicy: HA_MATTER_ROLE_POLICY });
const haRouterVisibility = computeTopologyVisibility(
  haViewModel,
  createTopologyFilterState("main-routers", "all", "all"),
);
const haReedVisibility = computeTopologyVisibility(
  haViewModel,
  createTopologyFilterState("reed-devices", "all", "all"),
);
assert.equal(haRouterVisibility.visibleNodeCount, 0);
assert.equal(haReedVisibility.visibleNodeCount, 1);
assert.equal(buildTopologyDetails(haViewModel, haNode.id).graph.isRouter, false);

const legacyHaLookalike = createTopologyViewModel({
  nodeData: [haNode],
  edgeData: [],
  nodeMap: new Map([[haNode.id, haNode]]),
  rawByIdForDetails: new Map([[haNode.id, haNode]]),
  routerNeighborByRloc16: new Map(),
  routerChildByRloc16: new Map(),
  sourceNames: ["fixture.json"],
});
assert.equal(buildTopologyDetails(legacyHaLookalike, haNode.id).graph.isRouter, true);

class FakeTarget {
  constructor() {
    this.listeners = new Map();
  }
  on(name, listener) {
    const listeners = this.listeners.get(name) || new Set();
    listeners.add(listener);
    this.listeners.set(name, listeners);
  }
  off(name, listener) {
    this.listeners.get(name)?.delete(listener);
  }
}
const target = new FakeTarget();
const bindings = createTopologyEventBindings();
bindings.on(target, "click", () => {});
assert.equal(target.listeners.get("click").size, 1);
bindings.dispose();
bindings.dispose();
assert.equal(target.listeners.get("click").size, 0);

console.log(JSON.stringify({
  nodeCount: viewModel.nodes.length,
  visibleNodeIds: [...visibility.visibleNodeIds].sort(),
  forcedVisibleEdgeIds: [...visibility.forcedVisibleEdgeIds],
  searchFocus: highlight.focusTarget,
  listenerCountAfterDispose: target.listeners.get("click").size,
}));