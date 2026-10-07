import assert from "node:assert/strict";
import {renderHealthFindingDetails, renderHealthComparison} from "../../src/js/tdash-health.js";

class Element {
  constructor(tagName) {
    Object.assign(this, {tagName, children: [], dataset: {}, attributes: {}, listeners: {}});
  }
  get childNodes() { return this.children; }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  replaceChildren() { this.children = []; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
}
globalThis.document = {createElement: (tag) => new Element(tag)};
const nodes = (root) => [root, ...root.children.flatMap(nodes)];
const texts = (root) => nodes(root).map((node) => node.textContent).filter(Boolean);
const container = new Element("section");
renderHealthFindingDetails(container, null);
assert.deepEqual(texts(container), ["Select a finding group to inspect its evidence."]);
assert.equal(container.children[0].className, "network-insights-empty");

const deviceId = "extaddr:a/b";
const findingId = "finding:one/two";
const calls = [];
const model = {
  groupId: "group", summary: "Summary", status: "Poor!", affected: {label: "2 devices"},
  scope: "device", confidence: "high", evidenceLabel: "Snapshot", materialityLabel: "Material",
  shared: {sourceFiles: ["one.json", "two.json"]},
  items: [{
    findingId, endpointId: deviceId, endpointIds: [deviceId], label: "Node",
    identityLabel: "a/b", findingContext: "Offline", highlightSummary: "No response",
    isExpanded: true, evidenceRows: [["sampleCount", 3]],
    finding: {scope: "device", ruleId: "device.offline", whyItMatters: "Impact",
      action: "Act", verify: "Check"},
  }],
  relatedDevices: Array.from({length: 10}, (_,index) => ({
    deviceId: `extaddr:${index}`, displayName: `Related ${index}`, findingId: "related",
    association: "Router path evidence", summary: "Path summary",
  })),
};
const callbacks = Object.fromEntries(
  ["showTopology", "showTable", "compareEndpoints", "applyFilter", "selectFinding",
    "inspectDevice", "inspectRelatedDevice", "rosterAction"].map(
    (name) => [name, (...args) => calls.push([name, ...args])],
  ),
);
renderHealthFindingDetails(container, model, {
  ...callbacks, groupDeviceCount: 2, availableTargets: 2, availableTopologyTargets: 2,
  inspectableDeviceIds: new Set([deviceId, "extaddr:0"]), mutationAvailable: true,
  rosterActionsByDevice: new Map([[deviceId, ["enroll", "mark-offline"]]]),
  rosterActionErrors: new Map([[deviceId, "not retained"]]),
});
assert.deepEqual(container.children.map((node) => node.className), [
  "health-finding-detail-summary", "health-finding-detail-priority", "health-finding-detail-meta",
  ...Array(3).fill("health-finding-detail-section"),
  "health-finding-detail-section health-finding-investigation",
  ...Array(3).fill("health-finding-detail-section"),
]);
assert.equal(nodes(container).find((node) => node.textContent === "Poor!").className,
  "health-finding-detail-status state-poor");
const select = nodes(container).find((node) => node.className === "health-affected-select");
const details = nodes(container).find((node) => node.className === "health-affected-details");
assert.deepEqual(select.dataset, {findingId, deviceId});
assert.deepEqual(select.attributes, {
  "aria-expanded": "true", "aria-controls": "health-affected-details-finding%3Aone%2Ftwo-extaddr%3Aa%2Fb",
  "aria-label": "Node Device ID a/b. Finding: Offline. No response",
});
assert.equal(details.id, select.attributes["aria-controls"]);
assert.equal(details.hidden, false);
assert.equal(nodes(select).find((node) => node.className === "health-affected-chevron")
  .attributes["aria-hidden"], "true");
assert.deepEqual(texts(details), [
  "Sample Count", "3", "Why it matters: Impact", "Action: Act", "Verify: Check",
  "Inspect device", "Add to Roster", "Mark Offline",
  "Stored device actions unavailable: not retained",
]);
assert.equal(nodes(container).find((node) => node.className === "health-related-devices")
  .children.length, 8);
assert.ok(texts(container).includes("2 more related devices not shown."));
assert.ok(texts(container).includes("one.json, two.json"));
assert.equal(texts(container).filter((text) => text === "Varies by affected item.").length, 3);
nodes(container).filter((node) => node.tagName === "button").forEach(
  (button) => button.listeners.click(),
);
assert.deepEqual(calls, [
  ["showTopology", "group"], ["showTable", "group"], ["compareEndpoints", "group"],
  ["applyFilter", "group"], ["selectFinding", findingId, deviceId],
  ["inspectDevice", deviceId, findingId, deviceId, `finding-inspect:${findingId}:${deviceId}`],
  ["rosterAction", "enroll", deviceId, findingId],
  ["rosterAction", "mark-offline", deviceId, findingId],
  ["inspectRelatedDevice", "group", "related", "extaddr:0", "related-inspect:group:related:extaddr:0"],
]);

for (const [state, expected, role] of [
  [{supportLoading: true}, "Loading comparison availability…", "status"],
  [{capabilityKnown: false}, "Comparison availability could not be determined.", "alert"],
  [{detailLoading: true}, "Loading comparison rows…", "status"],
  [{detailError: "failed"}, "Comparison rows could not be loaded: failed", "alert"],
]) {
  renderHealthComparison(container, {total: 1, offset: 0, limit: 25, items: []}, null, state);
  const message = nodes(container).find((node) => node.textContent === expected);
  assert.ok(message, expected);
  assert.equal(message.attributes.role, role);
}
console.log("Health detail contracts passed");
