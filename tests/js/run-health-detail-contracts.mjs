import assert from "node:assert/strict";
import {
  renderHealthFindingDetails, renderHealthComparison, renderHealthRoster,
} from "../../src/js/tdash-health.js";

class Element {
  constructor(tagName) {
    Object.assign(this, {tagName, children: [], dataset: {}, attributes: {}, listeners: {},
      classList: {toggle: () => {}}});
  }
  get childNodes() { return this.children; }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  replaceChildren() { this.children = []; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  createTHead() { return this.appendChild(new Element("thead")); }
  createTBody() { return this.appendChild(new Element("tbody")); }
  insertRow() { return this.appendChild(new Element("tr")); }
  insertCell() { return this.appendChild(new Element("td")); }
  click() {
    for (let element = this; element; element = element.parentNode) {
      element.listeners.click?.({target: this, currentTarget: element});
    }
  }
}
globalThis.document = {createElement: (tag) => new Element(tag)};
const nodes = (root) => [root, ...root.children.flatMap(nodes)];
const texts = (root) => nodes(root).map((node) => node.textContent).filter(Boolean);
const container = new Element("section");
renderHealthFindingDetails(container, null);
assert.deepEqual(texts(container), ["Select a finding group to inspect its evidence."]);
assert.equal(container.children[0].className, "network-insights-empty");

const rosterContainer = new Element("section");
const selectedDevices = [];
const rosterSorts = [];
const rosterColumns = [
  "extAddress", "rloc16", "eui", "label", "presence", "rosterState",
  "lastObserved", "quality", "omrIpv6Address", "isBorderRouter", "isRouter",
  "isLeader", "leaderData.partitionId", "threadVersion", "threadStackVersion",
  "vendorName", "vendorModel", "vendorSwVersion",
];
renderHealthRoster(rosterContainer, {
  filteredTotal: 1, total: 1, offset: 0, limit: 25, activeExpectedTotal: 1,
  devices: [{
    deviceId: "extaddr:roster", displayLabel: "Roster device", presenceState: "observed",
    rosterState: "active", lastEndpointPresenceAt: null,
    fieldCounts: {fresh: 1, stale: 0, conflicted: 0},
    fields: {
      extAddress: {value: "0011223344556677"},
      rloc16: {value: "0x1234"},
      omrIpv6Address: {value: "2001:db8::1"},
      isBorderRouter: {value: false},
      isRouter: {value: true},
      isLeader: {value: false},
      "leaderData.partitionId": {value: 0},
      threadVersion: {value: "1.4"},
      threadStackVersion: {value: "1.4.0"},
      vendorName: {value: "Vendor"},
      vendorModel: {value: "Model"},
      vendorSwVersion: {value: "Version"},
    },
  }],
}, {selectedDeviceId: null, loading: false, search: "", presence: "all", rosterState: "all",
  sort: {column: "label", direction: "ascending"}}, {
  select: (deviceId) => selectedDevices.push(deviceId),
  sort: (column) => rosterSorts.push(column),
});
const rosterRow = nodes(rosterContainer).find((node) => node.tagName === "tr" && node.listeners.click);
const rosterCells = rosterRow.children;
const rosterHeader = nodes(rosterContainer).find(
  (node) => node.tagName === "tr" && node.children.length === 18
    && node.children[0].tagName === "th",
);
assert.deepEqual(rosterHeader.children.map((cell) => cell.dataset.column), rosterColumns);
assert.deepEqual(rosterHeader.children.map((cell) => cell.children[0].textContent), [
  "extAddress", "rloc16", "eui", "Device", "Presence", "Roster designation",
  "Last observed", "Data quality", "omrIpv6Address", "isBorderRouter", "isRouter",
  "isLeader", "leaderData.partitionId", "threadVersion", "threadStackVersion",
  "vendorName", "vendorModel", "vendorSwVersion",
]);
assert.equal(rosterHeader.children[3].attributes["aria-sort"], "ascending");
rosterHeader.children.filter((cell) => cell.dataset.column !== "label"
  && cell.dataset.column !== "presence" && cell.dataset.column !== "rosterState"
  && cell.dataset.column !== "lastObserved" && cell.dataset.column !== "quality")
  .forEach((cell) => cell.children[0].click());
assert.deepEqual(rosterSorts, rosterColumns.filter((column) => ![
  "label", "presence", "rosterState", "lastObserved", "quality",
].includes(column)));
assert.equal(rosterCells.length, 18);
assert.deepEqual(rosterCells.map((cell) => cell.dataset.column), rosterColumns);
assert.equal(rosterCells[0].children[0].textContent, "0011223344556677");
assert.equal(rosterCells[1].children[0].textContent, "0x1234");
assert.equal(rosterCells[2].children[0].textContent, "Absent");
assert.equal(rosterCells[9].children[0].textContent, "false");
assert.equal(rosterCells[12].children[0].textContent, "0");
assert.equal(rosterCells[3].children[0].className, "health-roster-device-button");
rosterCells.find((cell) => cell.dataset.column === "presence").click();
rosterCells.find((cell) => cell.dataset.column === "eui").click();
rosterCells.find((cell) => cell.dataset.column === "label").children[0].click();
assert.deepEqual(selectedDevices, Array(3).fill("extaddr:roster"));

const oldPayloadContainer = new Element("section");
renderHealthRoster(oldPayloadContainer, {
  filteredTotal: 1, total: 1, offset: 0, limit: 25, activeExpectedTotal: 0,
  devices: [{
    deviceId: "extaddr:old", displayLabel: "Older server", presenceState: "observed",
    rosterState: "untracked", lastEndpointPresenceAt: null,
    fieldCounts: {fresh: 0, stale: 0, conflicted: 0},
  }],
}, {selectedDeviceId: null, loading: false, search: "", presence: "all", rosterState: "all",
  sort: {column: "label", direction: "ascending"}});
const oldRow = nodes(oldPayloadContainer).find(
  (node) => node.tagName === "tr" && node.listeners.click,
);
assert.equal(oldRow.children[0].children[0].textContent, "Absent");

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
