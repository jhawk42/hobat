import assert from "node:assert/strict";
import {
  applyTableFilters,
  collectColumns,
  renderTableForDataset,
  setMoreInfoEnabled,
  setTableColumnCategory,
  setTableHealthColumnsEnabled,
} from "../../src/js/tdash-table-renderer.js";
import {
  activateViewStatus,
  configureViewStatusPresenter,
} from "../../src/js/tdash-view-status.js";

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this.listeners = {};
    this.parentNode = null;
    this._textContent = "";
    this._innerHTML = "";
    this.className = "";
    this.classList = {
      add: (...names) => {
        this.className = [...new Set([...this.className.split(/\s+/), ...names].filter(Boolean))].join(" ");
      },
      remove: (...names) => {
        this.className = this.className.split(/\s+/).filter((name) => !names.includes(name)).join(" ");
      },
      contains: (name) => this.className.split(/\s+/).includes(name),
      toggle: (name, force) => {
        const enabled = force ?? !this.classList.contains(name);
        this.classList[enabled ? "add" : "remove"](name);
        return enabled;
      },
    };
  }
  get textContent() {
    return this._textContent + this.children.map((child) => child.textContent).join("");
  }
  set textContent(value) {
    this.replaceChildren();
    this._textContent = String(value);
  }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(value) {
    this.replaceChildren();
    this._innerHTML = String(value);
    this._textContent = "";
  }
  appendChild(child) {
    if (child.tagName === "#DOCUMENT-FRAGMENT") {
      child.children.slice().forEach((fragmentChild) => this.appendChild(fragmentChild));
      child.replaceChildren();
      return child;
    }
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  replaceChildren(...children) {
    this.children.forEach((child) => { child.parentNode = null; });
    this.children = [];
    this._textContent = "";
    children.forEach((child) => this.appendChild(child));
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  focus() { document.activeElement = this; }
  click() {
    document.activeElement = this;
    this.listeners.click?.({ stopPropagation() {} });
  }
  querySelector(selector) {
    if (selector === "tr.selected-row") {
      return this.querySelectorAll("tr").find((item) => item.classList.contains("selected-row")) ?? null;
    }
    return this.querySelectorAll(selector)[0] ?? null;
  }
  querySelectorAll(selector) {
    const matches = (element) => {
      if (selector === "tr") return element.tagName === "TR";
      if (selector === "button.table-sort-button") {
        return element.tagName === "BUTTON" && element.classList.contains("table-sort-button");
      }
      if (selector === "button[data-roster-sort-column]") {
        return element.tagName === "BUTTON" && element.dataset.rosterSortColumn !== undefined;
      }
      if (selector === "button[data-health-sort-column]") {
        return element.tagName === "BUTTON" && element.dataset.healthSortColumn !== undefined;
      }
      return false;
    };
    const found = [];
    const visit = (element) => {
      element.children.forEach((child) => {
        if (matches(child)) found.push(child);
        visit(child);
      });
    };
    visit(this);
    return found;
  }
}

class FakeSelect extends FakeElement {
  constructor(value, optionValues) {
    super("select");
    this.options = optionValues.map((optionValue) => ({value: optionValue, disabled: false}));
    this._value = value;
    this.selectedIndex = 0;
  }
  get value() { return this._value; }
  set value(value) { this._value = value; }
  get selectedOptions() { return [{text: this._value}]; }
}

const thead = new FakeElement("thead");
const tbody = new FakeElement("tbody");
const table = new FakeElement("table");
const selects = {
  "node-filter": new FakeSelect("all", ["all"]),
  "link-filter": new FakeSelect("default_links", ["default_links"]),
  "diagnostic-filter": new FakeSelect("all", ["all"]),
  "search-input": new FakeSelect("", []),
};
const elements = new Map([
  ...Object.entries(selects),
  ["details-list", new FakeElement("ul")],
  ["summary-list", new FakeElement("ul")],
  ["fetch-status-line-content", new FakeElement("div")],
]);
const publishedTableStatuses = [];
configureViewStatusPresenter((status) => publishedTableStatuses.push(status));
globalThis.document = {
  activeElement: null,
  createElement: (tagName) => new FakeElement(tagName),
  createDocumentFragment: () => new FakeElement("#document-fragment"),
  getElementById: (id) => elements.get(id) ?? null,
  querySelector(selector) {
    if (selector === "#data-table") return table;
    if (selector === "#data-table thead") return thead;
    if (selector === "#data-table tbody") return tbody;
    return null;
  },
  querySelectorAll(selector) {
    if (selector === "#data-table thead button.table-sort-button") {
      return thead.querySelectorAll("button.table-sort-button");
    }
    return [];
  },
  dispatchEvent() {},
};
globalThis.window = {tdashDebug: {}};
globalThis.CustomEvent = class {
  constructor(type, options) { this.type = type; this.detail = options?.detail; }
};

const records = [
  {name: "Alpha", extAddress: "0000000000000003", rloc16: "0003",
    metric: "10", omrIpv6Address: "fd00::10", observedAt: "2026-10-03T00:00:00Z",
    threadVersion: "1.10"},
  {name: "Beta", extAddress: "0000000000000002", rloc16: "0002",
    metric: "2", omrIpv6Address: "fd00::2", observedAt: "2026-10-02T00:00:00Z",
    threadVersion: "1.2"},
  {name: "Gamma", extAddress: "0000000000000001", rloc16: "0001",
    metric: "Unknown", omrIpv6Address: "fd00::1", observedAt: "2026-10-01T00:00:00Z",
    threadVersion: "1.1"},
  {name: "Delta", extAddress: "0000000000000004", rloc16: "0004",
    metric: "", omrIpv6Address: "fd00::3", observedAt: "2026-10-04T00:00:00Z",
    threadVersion: "1.11"},
];
setMoreInfoEnabled(true);
renderTableForDataset({rows: records, loadedFiles: ["fixture.json"]});

function headerButton(column) {
  return thead.querySelectorAll("button.table-sort-button")
    .find((button) => button.dataset.sortColumn === column);
}
function rowOrder(column) {
  const nameIndex = thead.children[0].children.findIndex(
    (heading) => ["name", "deviceLabel"].includes(heading.children[0].dataset.sortColumn),
  );
  if (nameIndex < 0) throw new Error("name identity column is missing");
  return tbody.children.map((row) => row.children[nameIndex].textContent);
}

headerButton("metric").click();
const ascendingMetrics = rowOrder("metric");
const ascendingSortState = thead.children[0].children.find(
  (heading) => heading.children[0].dataset.sortColumn === "metric",
);
const selectedIdentityAction = tbody.children[0].children.find(
  (cell) => cell.children[0]?.classList.contains("table-identity-action"),
).children[0];
selectedIdentityAction.click();
const selectedIdentityValue = tbody.children.find((row) => row.classList.contains("selected-row"))
  .children.find((cell) => cell.children[0]?.classList.contains("table-identity-action"))
  .textContent;
const selectedName = rowOrder("metric")[0];
headerButton("metric").click();
const descendingMetrics = rowOrder("metric");
const metricFocusColumn = document.activeElement?.dataset?.sortColumn;
const descendingSortState = thead.children[0].children.find(
  (heading) => heading.children[0].dataset.sortColumn === "metric",
);
const selectedRowPreserved = tbody.children.some((row) => row.classList.contains("selected-row")
  && row.children.find((cell) => cell.children[0]?.classList.contains("table-identity-action"))
    ?.textContent === selectedIdentityValue);

headerButton("omrIpv6Address").click();
const ascendingAddresses = rowOrder("omrIpv6Address");
headerButton("observedAt").click();
const ascendingTimestamps = rowOrder("observedAt");
headerButton("threadVersion").click();
const ascendingVersions = rowOrder("threadVersion");
setTableHealthColumnsEnabled(true);
renderTableForDataset({
  entry: {healthEligible: true, value: "fixture-dataset"},
  rows: records,
  loadedFiles: ["fixture.json"],
  healthAssessment: {
    datasetId: "fixture-dataset",
    findingGroups: [
      {findings: [{status: "strong", deviceIds: ["extaddr:0000000000000003"]}]},
      {findings: [{status: "poor", deviceIds: ["extaddr:0000000000000002"]}]},
      {findings: [{status: "unknown", deviceIds: ["extaddr:0000000000000001"]}]},
    ],
  },
});
headerButton("Health Status").click();
const ascendingHealthStatus = rowOrder("Health Status");
headerButton("Health Status").click();
const descendingHealthStatus = rowOrder("Health Status");
const identityActionButtons = tbody.children.filter((row) => row.children.some(
  (cell) => cell.children[0]?.classList.contains("table-identity-action"),
)).length;
const healthColumns = ["Health Status", "Health Reason", "Health Observed"];
const orderingCases = [];
for (const moreInfo of [false, true]) {
  for (const category of ["all", "identity-list"]) {
    for (const fields of [
      {deviceLabel: "Label", eui: "0011223344556677"},
      {eui: "0011223344556677"},
      {deviceLabel: "Label"},
      {},
    ]) {
      setMoreInfoEnabled(moreInfo);
      setTableHealthColumnsEnabled(false);
      renderTableForDataset({
        entry: {healthEligible: true, value: "fixture-dataset"},
        rows: [{...records[0], ...fields}],
        loadedFiles: ["fixture.json"],
        healthAssessment: {datasetId: "fixture-dataset", findingGroups: []},
      });
      setTableColumnCategory(category);
      applyTableFilters();
      const headings = () => thead.querySelectorAll("button.table-sort-button")
        .map((button) => button.dataset.sortColumn);
      const baseline = headings();
      setTableHealthColumnsEnabled(true);
      applyTableFilters();
      const expected = [...baseline];
      const labelIndex = expected.indexOf("deviceLabel");
      const euiIndex = expected.indexOf("eui");
      expected.splice(labelIndex >= 0 ? labelIndex + 1 : euiIndex >= 0 ? euiIndex : expected.length,
        0, ...healthColumns);
      assert.deepEqual(headings(), expected);
      assert.equal(table.dataset.identityColumn, baseline[0]);
      const collected = collectColumns([{...records[0], ...fields}]);
      const collectedLabelIndex = collected.indexOf("deviceLabel");
      if (collectedLabelIndex >= 0) {
        assert.deepEqual(collected.slice(collectedLabelIndex + 1, collectedLabelIndex + 4), healthColumns);
      }
      setTableHealthColumnsEnabled(false);
      applyTableFilters();
      assert.deepEqual(headings(), baseline);
      orderingCases.push({moreInfo, category, fields: Object.keys(fields)});
    }
  }
}

const matterRecord = {
  deviceLabel: "Matter sensor",
  extAddress: "0000000000000005",
  matter: {
    endpoints: [{
      endpointId: 4,
      bridgedBasicInformation: {productName: "Temperature sensor"},
    }],
  },
  generalDiagnostics: {upTime: "90061", rebootCount: 0},
  powerSources: [{
    endpointId: 2,
    attributes: {
      description: "Sensor battery",
      status: 1,
      batPercentRemaining: 151,
      endpointList: [],
    },
    batteryPercent: 75.5,
  }, {
    endpointId: 4,
  }, {
    endpointId: 5,
    attributes: null,
  }, {
    endpointId: 6,
    attributes: {endpointList: null},
  }],
};
const matterDataset = {rows: [matterRecord], loadedFiles: ["fixture.json"]};
activateViewStatus("table", matterDataset);
setMoreInfoEnabled(false);
setTableHealthColumnsEnabled(false);
renderTableForDataset(matterDataset);
setTableColumnCategory("matter-list");
applyTableFilters();
const matterTableStatus = publishedTableStatuses.at(-1);
const matterTableStatusMatch = matterTableStatus?.match(
  /Total: \d+ rows, (\d+) columns\. Showing: \d+ rows, (\d+) columns/,
);
assert.ok(matterTableStatusMatch);
const matterTableStatusColumns = matterTableStatusMatch.slice(1).map(Number);
assert.ok(matterTableStatusColumns[0] >= matterTableStatusColumns[1]);
const matterColumnNames = thead.querySelectorAll("button.table-sort-button")
  .map((button) => button.dataset.sortColumn);
const matterCellText = (column) => {
  const index = matterColumnNames.indexOf(column);
  return index < 0 ? "" : tbody.children[0].children[index].textContent;
};
assert.match(matterCellText("powerSources"), /Power source · Endpoint 2 — Sensor battery — 75\.5%/);
assert.match(matterCellText("powerSources"), /151 \(0\.5% units\)/);
assert.match(matterCellText("powerSources"), /All endpoints \(node-wide\)/);
assert.match(
  matterCellText("powerSources"),
  /Powered endpoint scope: Not reported \(scope unknown\)/,
);
assert.match(matterCellText("matter.endpoints"), /Endpoint 4 — Temperature sensor/);
assert.match(matterCellText("generalDiagnostics.upTime"), /90061 s \(1d 1h 1m 1s\)/);

const uptimeRecords = [
  {
    deviceLabel: "Uptime 99",
    extAddress: "0000000000000006",
    generalDiagnostics: {upTime: "99"},
  },
  {
    deviceLabel: "Uptime 100",
    extAddress: "0000000000000007",
    generalDiagnostics: {upTime: "100"},
  },
  {
    deviceLabel: "Uptime uint64",
    extAddress: "0000000000000008",
    generalDiagnostics: {upTime: "18446744073709551615"},
  },
];
renderTableForDataset({rows: uptimeRecords, loadedFiles: ["fixture.json"]});
setTableColumnCategory("matter-list");
applyTableFilters();
headerButton("generalDiagnostics.upTime").click();
const ascendingUptime = rowOrder("generalDiagnostics.upTime");
headerButton("generalDiagnostics.upTime").click();
const descendingUptime = rowOrder("generalDiagnostics.upTime");

console.log(JSON.stringify({
  healthColumnOrderingCases: orderingCases.length,
  ascendingMetrics,
  descendingMetrics,
  ascendingAddresses,
  ascendingTimestamps,
  ascendingVersions,
  ascendingHealthStatus,
  descendingHealthStatus,
  ascendingUptime,
  descendingUptime,
  matterTableStatusColumns,
  ascendingAriaSort: ascendingSortState.getAttribute("aria-sort"),
  descendingAriaSort: descendingSortState.getAttribute("aria-sort"),
  metricFocusColumn,
  selectedName,
  selectedRowPreserved,
  identityActionButtons,
}));
