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
  projectTopologyTheme,
} from "../../src/js/tdash-topology-view-model.js";
import { buildDeviceProjections } from "../../src/js/tdash-device-projection.js";
import { addEdge } from "../../src/js/tdash-topology-utils.js";
import { EDGE_LQ_STYLES } from "../../src/js/tdash-constants.js";

const mergeEdges = [];
const mergeMap = new Map();
addEdge(mergeMap, mergeEdges, "a", "b", { ...EDGE_LQ_STYLES.low, linkCategories: ["otbr_child"] });
addEdge(mergeMap, mergeEdges, "a", "b", { ...EDGE_LQ_STYLES.high, linkCategories: ["router_neighbor"] });
assert.equal(mergeEdges[0].themeColorKey, "lqHigh");
addEdge(mergeMap, mergeEdges, "a", "b", { ...EDGE_LQ_STYLES.high, themeColorKey: "lqOtbr" });
assert.equal(mergeEdges[0].themeColorKey, "lqHigh");

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

const palette = Object.fromEntries(
  ["router", "borderRouter", "child", "eve", "unknown"].flatMap((role) => [
    [`${role}Bg`, "#ffffff"], [`${role}Border`, "#333333"],
  ]),
);
Object.assign(palette, {
  labelText: "#111111", labelBg: "#eeeeee", selectedBorder: "#800080", hoverBorder: "#000000",
  searchMatch: "#995500", searchDimBg: "#cccccc", searchDimBorder: "#777777", searchDimText: "#444444",
  healthPoor: "#990000", healthPoorBg: "#ffeeee", lqParentChild: "#aa2288", lqNone: "#666666",
});
const health = new Map([["extaddr:bbbbbbbbbbbbbbbb", "poor"]]);
const beforeTheme = JSON.stringify(viewModel.nodes);
const canonicalTheme = projectTopologyTheme(viewModel, palette, "canonical", searchState, health);
assert.ok(Object.isFrozen(canonicalTheme.viewModel));
assert.equal(canonicalTheme.viewModel.nodes, viewModel.nodes);
assert.equal(canonicalTheme.viewModel.edgeIndexes, viewModel.edgeIndexes);
assert.equal(canonicalTheme.viewModel.rawByIdForDetails, viewModel.rawByIdForDetails);
assert.equal(canonicalTheme.nodeUpdates.find((node) => node.id === child.id).color.border, palette.healthPoor);
assert.equal(canonicalTheme.edgeUpdates[0].color.color, palette.lqParentChild);
assert.equal(canonicalTheme.nodeUpdates[0].font.color, palette.labelText);
assert.equal(JSON.stringify(viewModel.nodes), beforeTheme);
const searchTheme = projectTopologyTheme(canonicalTheme.viewModel, palette, "search", searchState, health);
assert.equal(searchTheme.nodeUpdates.find((node) => node.id === child.id).color.border, palette.searchMatch);
assert.equal(searchTheme.nodeUpdates.find((node) => node.id === router.id).color.background, palette.searchDimBg);
const restored = projectTopologyTheme(searchTheme.viewModel, palette, "canonical", searchState, health);
assert.deepEqual(restored.nodeUpdates, canonicalTheme.nodeUpdates);
const alternate = Object.fromEntries(Object.entries(palette).map(([key]) => [key, "#123456"]));
const cycled = projectTopologyTheme(
  projectTopologyTheme(canonicalTheme.viewModel, alternate, "canonical", searchState, health).viewModel,
  palette, "canonical", searchState, health,
);
assert.deepEqual(cycled.nodeUpdates, canonicalTheme.nodeUpdates);
assert.deepEqual(cycled.edgeUpdates, canonicalTheme.edgeUpdates);
assert.equal(Object.keys(canonicalTheme.nodeUpdates[0]).some((key) => ["hidden", "physics", "x", "y", "label"].includes(key)), false);
const profileViewModel = createTopologyViewModel({
  nodeData: [{
    id: "font-metrics", themeRole: "eve",
    font: { size: 19.5, face: "monospace", multi: "md", vadjust: -8 },
  }],
  edgeData: [
    { id: "quality-child", isParentChild: true, themeColorKey: "lqHigh", color: { color: "#000000", opacity: 0.16 }, width: 0.45, physics: false },
    { id: "anchor", baseHidden: true, color: { opacity: 0 }, hidden: true, physics: true },
    { id: "unclassified" },
    { id: "category-child", linkCategories: ["eve_child"] },
  ],
});
const projectedProfile = projectTopologyTheme(profileViewModel, { ...palette, lqHigh: "#008080" }, "canonical", null);
assert.equal(projectedProfile.edgeUpdates.length, 3);
assert.equal(projectedProfile.edgeUpdates[0].color.color, "#008080");
assert.equal(projectedProfile.edgeUpdates[0].color.opacity, 0.16);
assert.equal(projectedProfile.edgeUpdates[1].color.color, palette.lqNone);
assert.equal(projectedProfile.edgeUpdates[2].color.color, palette.lqParentChild);
assert.deepEqual(projectedProfile.viewModel.originalEdgeStyling.get("anchor"), { color: { opacity: 0 } });
assert.equal(projectedProfile.nodeUpdates[0].font.size, 19.5);
assert.equal(projectedProfile.nodeUpdates[0].font.face, "monospace");
assert.equal(projectedProfile.nodeUpdates[0].font.multi, "md");
assert.equal(projectedProfile.nodeUpdates[0].font.vadjust, -8);
assert.deepEqual(Object.keys(projectedProfile.edgeUpdates[0]).sort(), ["color", "id"]);

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
});
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
assert.equal(buildTopologyDetails(legacyHaLookalike, haNode.id).graph.isRouter, false);

const otbrChild = {
  id: "otbr-child",
  extAddress: "cccccccccccccccc",
  rloc16: "0x1001",
  role: "child",
  mode_device: "FTD",
  isReed: false,
};
const otbrProjections = buildDeviceProjections([{
  ...otbrChild,
  mode: { device: "FTD" },
}]);
const otbrViewModel = createTopologyViewModel({
  nodeData: [otbrChild],
  edgeData: [],
  nodeMap: new Map([[otbrChild.id, otbrChild]]),
  rawByIdForDetails: new Map([[otbrChild.id, otbrChild]]),
  routerNeighborByRloc16: new Map(),
  routerChildByRloc16: new Map(),
}, otbrProjections);
const otbrReedVisibility = computeTopologyVisibility(
  otbrViewModel,
  createTopologyFilterState("reed-devices", "all", "all"),
);
assert.equal(otbrReedVisibility.visibleNodeCount, 0);
assert.equal(buildTopologyDetails(otbrViewModel, otbrChild.id).graph.isReed, false);
otbrChild.isReed = true;
const canonicalOtbrChild = { ...otbrChild };
const canonicalOtbrViewModel = createTopologyViewModel({
  nodeData: [canonicalOtbrChild],
  edgeData: [],
  nodeMap: new Map([[canonicalOtbrChild.id, canonicalOtbrChild]]),
  rawByIdForDetails: new Map([[canonicalOtbrChild.id, canonicalOtbrChild]]),
}, buildDeviceProjections([{
  ...canonicalOtbrChild,
  mode: { device: "FTD" },
}]));
assert.equal(
  computeTopologyVisibility(
    canonicalOtbrViewModel,
    createTopologyFilterState("reed-devices", "all", "all"),
  ).visibleNodeCount,
  1,
);
assert.equal(
  buildTopologyDetails(canonicalOtbrViewModel, canonicalOtbrChild.id).graph.isReed,
  true,
);

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