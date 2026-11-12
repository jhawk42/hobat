import assert from "node:assert/strict";
import {
  parseSearchQuery, rowMatchesSearch, filterRowsBySearch,
} from "../../src/js/tdash-search.js";
import {
  populateFilterSelects, populateDiagnosticFilterBySource,
  populateDiagnosticFilterBySourceWithCapabilities, updateFilterOptionVisibility,
} from "../../src/js/tdash-filters.js";

const rows = [
  {name: "Desk", privateNote: "custom needle", mode: {device: "MTD"}, isRouter: false},
  {name: "Router", privateNote: {nested: "needle"}, isRouter: true},
  {name: "Other"},
];
assert.equal(parseSearchQuery("  DeSK "), "desk");
assert.equal(parseSearchQuery(null), "");
assert.equal(rowMatchesSearch(rows[0], "needle"), false);
assert.equal(rowMatchesSearch(rows[0], "needle", true), true);
assert.equal(rowMatchesSearch(rows[1], "needle", true), true);
assert.equal(rowMatchesSearch(rows[0], "mtd"), true);
assert.equal(rowMatchesSearch(rows[0], "false"), true);
assert.equal(rowMatchesSearch(rows[1], "true"), true);
assert.equal(rowMatchesSearch(null, "desk"), false);
assert.equal(rowMatchesSearch([], "desk"), false);
const cycle = {}; cycle.self = cycle;
assert.equal(rowMatchesSearch({privateNote: cycle}, "needle", true), false);
assert.deepEqual([...filterRowsBySearch(rows, "needle", true).matchingIndices], [0, 1]);
assert.deepEqual(filterRowsBySearch(rows, "needle", true).matchingRows, rows.slice(0, 2));
assert.deepEqual([...filterRowsBySearch(rows, "").matchingIndices], [0, 1, 2]);
assert.notEqual(filterRowsBySearch(rows, "").matchingRows, rows);
assert.deepEqual(filterRowsBySearch(null, "needle").matchingRows, []);
assert.equal(filterRowsBySearch(rows, "missing").matchingIndices.size, 0);

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this._value = null; }
  set innerHTML(value) { assert.equal(value, ""); this.children = []; this._value = null; }
  appendChild(child) { this.children.push(child); return child; }
  get options() { return this.children.flatMap(child => child.tag === "optgroup" ? child.options : [child]); }
  get value() { return this._value ?? this.options.find(option => option.selected)?.value ?? this.options[0]?.value; }
  set value(value) { this._value = value; }
  get selectedIndex() { return this.options.findIndex(option => option.value === this.value); }
}
const elements = new Map(["node-filter", "link-filter", "diagnostic-filter"]
  .map(id => [id, new Element("select")]));
const originalDocument = globalThis.document;
globalThis.document = {getElementById: id => elements.get(id), createElement: tag => new Element(tag)};
try {
  populateFilterSelects();
  const node = elements.get("node-filter"), link = elements.get("link-filter");
  assert.equal(node.options[0].value, "all");
  assert.ok(node.options.slice(1).every(option => option.hidden && option.disabled));
  const capabilities = {hasRouters: true, hasBorderRouters: true,
    hasFieldMacTotalErrorsRatio: true, hasFieldPartitionChanges: true,
    edgeCategories: new Set(["router_neighbor"])};
  updateFilterOptionVisibility(capabilities, "topology");
  assert.equal(node.options.find(option => option.value === "border-routers")?.disabled, false);
  assert.equal(node.options.find(option => option.value === "mtd-devices").disabled, true);
  assert.equal(link.options.find(option => option.value === "lq_otbr_neighbor").hidden, false);
  node.value = "border-routers"; link.value = "lq_otbr_neighbor";
  updateFilterOptionVisibility({edgeCategories: new Set()}, "table");
  assert.equal(node.value, "all");
  assert.equal(link.value, "lq_otbr_neighbor", "table does not reset topology link options");
  updateFilterOptionVisibility({edgeCategories: new Set()}, "topology");
  assert.equal(link.value, "all_links");
  const diagnostic = elements.get("diagnostic-filter");
  const values = () => diagnostic.options.map(option => option.value);
  populateDiagnosticFilterBySource("mac_counters");
  assert.deepEqual(values(), ["all", "mac-total-errors-ratio-medium", "mac-total-errors-ratio-high",
    "mac-total-discards-ratio-medium", "mac-total-discards-ratio-high"]);
  populateDiagnosticFilterBySourceWithCapabilities("mac_counters", capabilities,
    [{macCounters: {ifTotalErrorsTotalPktsRatio: 8}}], "table");
  assert.deepEqual(values(), ["all", "mac-total-errors-ratio-medium", "mac-total-errors-ratio-high"]);
  diagnostic.value = "mac-total-errors-ratio-high";
  updateFilterOptionVisibility({edgeCategories: new Set()}, "table");
  assert.equal(diagnostic.value, "all");
  populateDiagnosticFilterBySourceWithCapabilities("macCounters", capabilities, [], "table");
  assert.deepEqual(values(), ["all"]);
  populateDiagnosticFilterBySourceWithCapabilities("mle_counters", capabilities,
    [{partIdChangesCount: 6}], "topology");
  assert.deepEqual(values(), ["all", "medium-partition-changes", "high-partition-changes"]);
  populateDiagnosticFilterBySourceWithCapabilities("unknown", capabilities, null);
  assert.deepEqual(values(), ["all"]);
} finally {
  globalThis.document = originalDocument;
}
console.log(JSON.stringify({matchedIndices: [0, 1], restoredNodeFilter: "all"}));
