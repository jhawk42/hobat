import assert from "node:assert/strict";

import { computeRowCounts, evaluateDiagnosticOption, getRowRoleProjection, isRowVisibleByNodeFilter } from "../../src/js/tdash-filters.js";
import { buildDatasetRows } from "../../src/js/tdash-dataset.js";
import {
  createHealthComparisonDetailController,
  formatAge,
  isComparisonPageForAssessment,
} from "../../src/js/tdash-health.js";
import {
  collectColumns,
  getTableColumnCategories,
  getTableColumnsForCategory,
  getTableFilterLabel,
  setTableHealthColumnsEnabled,
  setTableHealthFindings,
} from "../../src/js/tdash-table-renderer.js";
import { DEVICE_DETAILS_SECTIONS, NODE_FILTER_OPTIONS, NODE_SHAPES, TABLE_PRIORITY_COLUMNS } from "../../src/js/tdash-constants.js";
import { getColumnValue } from "../../src/js/tdash-utils.js";
import { projectObservedTopologyLinkCounts } from "../../src/js/tdash-adaptor-model.js";
import { buildVisNodeData } from "../../src/js/tdash-topology-utils.js";
import { SEARCH_TARGET_FIELDS, parseSearchQuery, rowMatchesSearch } from "../../src/js/tdash-search.js";

const explicitRouter = { isRouter: true, role: "Router", children: [{}] };
const leader = { role: "leader" };
const reedChild = { rloc16: "0x1001", role: "REED", mode: { device: "FTD" } };
const borderRouter = { isBorderRouter: true };
assert.equal(isRowVisibleByNodeFilter(explicitRouter, "main-routers"), true);
assert.equal(isRowVisibleByNodeFilter(leader, "main-routers"), true);
assert.equal(isRowVisibleByNodeFilter(borderRouter, "border-routers"), true);
assert.equal(isRowVisibleByNodeFilter({ br: true }, "border-routers"), true);
assert.equal(isRowVisibleByNodeFilter({ isBorderRouter: false }, "border-routers"), false);
assert.equal(isRowVisibleByNodeFilter({}, "border-routers"), false);
assert.equal(getRowRoleProjection({ role: "border router", type: "router" }).isBorderRouter, false);
assert.equal(getRowRoleProjection({ isBorderRouter: false, role: "border router", type: "router" }).isBorderRouter, false);
const topologyProjection = buildVisNodeData(
  new Map([
    ["canonical-br", { id: "canonical-br", isRouter: true, isBorderRouter: true }],
    ["explicit-false", { id: "explicit-false", isRouter: true, isBorderRouter: false }],
    ["role-only", { id: "role-only", isRouter: true, role: "border router" }],
  ]),
  new Set(),
  new Map(),
  (node) => node.id,
);
const topologyById = new Map(topologyProjection.map((node) => [node.id, node]));
assert.equal(topologyById.get("canonical-br").isBorderRouter, true);
assert.equal(topologyById.get("canonical-br").shape, NODE_SHAPES.borderRouter);
assert.equal(topologyById.get("explicit-false").isBorderRouter, false);
assert.equal(topologyById.get("explicit-false").shape, NODE_SHAPES.router);
assert.equal(topologyById.get("role-only").isBorderRouter, false);
assert.equal(topologyById.get("role-only").shape, NODE_SHAPES.router);
assert.equal(isRowVisibleByNodeFilter(explicitRouter, "routers-with-children"), true);
assert.equal(getRowRoleProjection(reedChild).isChild, true);
assert.equal(isRowVisibleByNodeFilter(reedChild, "main-routers"), false);

const rangeOption = {
  conditionKind: "collection", collectionPath: "routerNeighbors", collectionMetricField: "averageRssi",
  evaluatorId: "range", threshold: [-80, -70], rangeUpperInclusive: true, aggregation: "min", unit: "dBm",
};
const rangeEvaluation = evaluateDiagnosticOption({
  routerNeighbors: [{ averageRssi: -90 }, { averageRssi: -75 }, { averageRssi: -65 }],
}, "table", rangeOption);
assert.equal(rangeEvaluation.triggered, true);
assert.equal(rangeEvaluation.metric, -75);
assert.deepEqual(rangeEvaluation.matchedRecords, [{ averageRssi: -75 }]);

assert.deepEqual(collectColumns([{ rloc16: "0x1000", room: "Lab" }]).filter((column) => column === "room"), ["room"]);
assert.deepEqual(
  collectColumns([{ br: true, threadVersion: "1.2" }, { isBorderRouter: true, version: 7 }])
    .filter((column) => ["br", "isBorderRouter", "ver", "version", "threadVersion"].includes(column)),
  ["isBorderRouter", "version", "threadVersion"],
);
const healthTableRows = [{ extAddress: "0011223344556677", room: "Lab" }];
setTableHealthFindings([
  { deviceIds: ["extaddr:0011223344556677"], status: "moderate", title: "Health finding" },
], "2026-09-29T00:00:00Z", true);
assert.deepEqual(collectColumns(healthTableRows).filter((column) => column.startsWith("Health ")), []);
setTableHealthColumnsEnabled(true);
assert.deepEqual(
  collectColumns(healthTableRows).filter((column) => column.startsWith("Health ")),
  ["Health Status", "Health Reason", "Health Observed"],
);
setTableHealthFindings([], "2026-09-29T00:00:00Z", true);
assert.deepEqual(
  collectColumns(healthTableRows).filter((column) => column.startsWith("Health ")),
  ["Health Status", "Health Reason", "Health Observed"],
);
setTableHealthFindings([], "", false);
assert.deepEqual(collectColumns(healthTableRows).filter((column) => column.startsWith("Health ")), []);
setTableHealthColumnsEnabled(false);
assert.equal(getTableFilterLabel(null, "All nodes"), "All nodes");
assert.equal(getTableFilterLabel({ selectedOptions: [] }, "All diagnostics"), "All diagnostics");
assert.equal(getTableFilterLabel({ selectedOptions: [{ text: "Routers" }] }, "All nodes"), "Routers");
const identityDetails = DEVICE_DETAILS_SECTIONS.find((section) => section.sectionId === "identity-list").fields;
const highlightDetails = DEVICE_DETAILS_SECTIONS.find((section) => section.sectionId === "highlights-list").fields;
const borderRouterFilter = NODE_FILTER_OPTIONS.find((option) => option.value === "border-routers");
assert.ok(identityDetails.includes("eui"));
assert.ok(!identityDetails.includes("eui64"));
assert.ok(highlightDetails.includes("threadVersion"));
assert.ok(highlightDetails.includes("threadVersionDecimal"));
assert.ok(highlightDetails.includes("threadStackVersion"));
assert.ok(!highlightDetails.includes("ver"));
assert.ok(highlightDetails.includes("isBorderRouter"));
assert.ok(!highlightDetails.includes("br"));
assert.equal(borderRouterFilter.topoNodeField, "isBorderRouter");
assert.equal(borderRouterFilter.tableRowField, "isBorderRouter");
assert.ok(TABLE_PRIORITY_COLUMNS.includes("eui"));
assert.ok(TABLE_PRIORITY_COLUMNS.includes("isBorderRouter"));
assert.ok(!TABLE_PRIORITY_COLUMNS.includes("br"));
assert.ok(TABLE_PRIORITY_COLUMNS.includes("threadVersion"));
assert.ok(!TABLE_PRIORITY_COLUMNS.includes("eui64"));
assert.ok(!TABLE_PRIORITY_COLUMNS.includes("ver"));
assert.ok(!TABLE_PRIORITY_COLUMNS.includes("threadVersionDecimal"));
assert.ok(SEARCH_TARGET_FIELDS.includes("eui"));
assert.ok(SEARCH_TARGET_FIELDS.includes("threadVersion"));
assert.ok(SEARCH_TARGET_FIELDS.includes("version"));
assert.ok(SEARCH_TARGET_FIELDS.includes("isBorderRouter"));
assert.ok(!SEARCH_TARGET_FIELDS.includes("br"));
assert.ok(!SEARCH_TARGET_FIELDS.includes("eui64"));
assert.ok(!SEARCH_TARGET_FIELDS.includes("ver"));
const canonicalThreadRow = { eui: "8899aabbccddeeff", threadVersion: "1.3", threadVersionDecimal: 4 };
assert.equal(getColumnValue(canonicalThreadRow, "threadVersion"), "1.3");
assert.equal(rowMatchesSearch(canonicalThreadRow, parseSearchQuery("1.3")), true);
assert.equal(rowMatchesSearch({ threadVersionDecimal: 4 }, parseSearchQuery("4")), false);
assert.equal(rowMatchesSearch({ eui: "8899aabbccddeeff" }, parseSearchQuery("8899")), true);
assert.deepEqual(
  getTableColumnCategories([
    { extAddress: "0011223344556677", hostname: "Border Router", modelName: "BorderRouter" },
  ]).map(({ value }) => value),
  ["identity-list", "thread-list"],
);
assert.deepEqual(
  getTableColumnCategories([{ matter: { nodeId: 123 } }]).map(({ value }) => value),
  ["matter-list"],
);
assert.deepEqual(getTableColumnCategories([]), []);
const supportedEmptyTableProjection = projectObservedTopologyLinkCounts(
  [{ extAddress: "aa00112233445566" }],
  {
    edgeData: [],
    nodeData: [{ id: "device-a" }],
    nodeMap: new Map([["device-a", { extAddress: "aa00112233445566" }]]),
    relationshipCapabilities: {
      datasetWide: new Set(["children"]),
      byDeviceId: new Map(),
    },
  },
);
assert.deepEqual(
  getTableColumnCategories(supportedEmptyTableProjection.rows).map(({ value }) => value),
  ["identity-list", "connections-list"],
);
assert.deepEqual(
  getTableColumnsForCategory(supportedEmptyTableProjection.rows, "connections-list"),
  [
    "extAddress",
    "observedTopologyLinks",
    "observedTopologyLinksLq3",
    "observedTopologyLinksLq2",
    "observedTopologyLinksLq1",
  ],
);
const unsupportedLinkProjection = projectObservedTopologyLinkCounts(
  [{ extAddress: "aa00112233445566", observedTopologyLinks: 4 }],
  {
    edgeData: [{ id: "unqualified-edge", from: "device-a", to: "device-b" }],
    nodeData: [{ id: "device-a" }, { id: "device-b" }],
    nodeMap: new Map([
      ["device-a", { extAddress: "aa00112233445566" }],
      ["device-b", { extAddress: "bb00112233445566" }],
    ]),
  },
);
assert.deepEqual(
  getTableColumnCategories(unsupportedLinkProjection.rows).map(({ value }) => value),
  ["identity-list"],
);
assert.deepEqual(
  getTableColumnsForCategory(
    [{ rloc16: "0x1234", extAddress: "0011223344556677", deviceLabel: "Desk Light", matter: { nodeId: 123, serialNumber: "SN-1", matterVersion: "1.4.1", lastInterview: "2026-08-02T10:30:00Z" }, deviceTypes: ["0x0302"], room: "Lab" }],
    "matter-list",
  ),
  ["rloc16", "extAddress", "deviceLabel", "matter.nodeId", "matter.serialNumber", "matter.matterVersion", "matter.lastInterview", "deviceTypes"],
);
assert.deepEqual(
  getTableColumnsForCategory([{ rloc16: "0x1234" }], "identity-list"),
  ["rloc16"],
);
assert.deepEqual(
  getTableColumnsForCategory(
    [{ rloc16: "0x1234", modelName: "BorderRouter", networkName: "Test Thread" }],
    "thread-list",
  ),
  ["rloc16", "modelName", "networkName"],
);

const haMatterRows = buildDatasetRows({
  source: "ha-matter-ws",
  adaptor: "ha-matter-ws",
  mergeStrategy: "none",
  rowExtractor: "raw-array",
  files: ["ha-matter.json"],
}, [[{ deviceLabel: "Desk Light", nodeId: 123, vendorName: "Example", networkInterfaces: [] }]]).rows;
assert.deepEqual(haMatterRows[0].matter, {
  deviceLabel: "Desk Light", nodeId: 123, vendorName: "Example",
});

const counts = computeRowCounts([{ role: "Router", isRouter: true }, { role: "SleepyEndDevice" }, { isBorderRouter: true }]);
assert.deepEqual([counts.borderRouters, counts.routers, counts.children], [1, 1, 1]);
const explicitBorderRouterCount = computeRowCounts([{ isBorderRouter: true, rloc16: "0x1001" }]);
assert.equal(explicitBorderRouterCount.borderRouters, 1);
assert.equal(formatAge(null), "unknown");
assert.equal(formatAge("not-a-date"), "unknown");
assert.equal(formatAge(new Date(Date.now() - 30_000).toISOString()), "just now");
const assessment = { networkId: "extpan:78b9775b001c1cbe", datasetId: "otbr_cli_networkdiag_fetch_all" };
const page = { schemaVersion: 1, total: 1, limit: 25, offset: 0, items: [{
  comparisonId: "comparison:one", networkId: assessment.networkId, datasetId: assessment.datasetId,
}] };
assert.equal(isComparisonPageForAssessment(page, assessment, 0), true);
assert.equal(isComparisonPageForAssessment({ ...page, items: [] }, assessment, 0), true);
assert.equal(isComparisonPageForAssessment({ ...page, offset: 25 }, assessment, 0), false);
assert.equal(isComparisonPageForAssessment({ ...page, total: 0 }, assessment, 0), false);
assert.equal(isComparisonPageForAssessment({ ...page, items: [{ ...page.items[0], networkId: "extpan:0000000000000000" }] }, assessment, 0), false);
assert.equal(isComparisonPageForAssessment({ ...page, items: [{ ...page.items[0], datasetId: "other" }] }, assessment, 0), false);

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function comparisonHeader(overrides = {}) {
  return {
    comparisonId: "comparison:one",
    comparisonVersion: 1,
    beforeAssessmentId: "assessment:before",
    afterAssessmentId: "assessment:after",
    beforeObservationId: "observation:before",
    afterObservationId: "observation:after",
    baselineState: "available",
    comparable: true,
    itemCount: 1,
    ...overrides,
  };
}

function comparisonDetail(header, query, items = [{}]) {
  return {
    schemaVersion: 1,
    ...header,
    networkId: assessment.networkId,
    datasetId: assessment.datasetId,
    filteredItemCount: header.filteredItemCount ?? header.itemCount,
    limit: 25,
    offset: query.offset,
    items,
  };
}

function comparisonControllerFixture(fetchDetail) {
  const state = {
    comparison: null,
    comparisonQueryIdentity: null,
    comparisonDetailLoading: false,
    comparisonDetailError: "",
    comparisonDetailRequestVersion: 0,
    comparisonDetailRequestIdentity: null,
    comparisonDetailRequestHeader: null,
  };
  const selection = {
    comparisonId: "comparison:one",
    scope: "all",
    result: "changed",
  };
  let offset = 0;
  let summary = comparisonHeader();
  const controller = createHealthComparisonDetailController({
    state,
    getAssessment: () => assessment,
    getSelection: () => ({ ...selection }),
    getSummary: () => summary,
    getOffset: () => offset,
    setOffset: (value) => { offset = value; },
    updateSelection: (filter, value) => { selection[filter] = value; },
    fetchDetail,
  });
  return {
    state,
    selection,
    controller,
    setSummary: (value) => { summary = value; },
    getOffset: () => offset,
  };
}

{
  const requests = [];
  const fixture = comparisonControllerFixture((id, requestedOffset, _signal, filters) => {
    const response = deferred();
    requests.push({ id, offset: requestedOffset, filters, response });
    return response.promise;
  });
  const first = fixture.controller.select("comparison:one", 0);
  const second = fixture.controller.changeFilter("result", "unchanged");
  assert.equal(fixture.getOffset(), 0);
  assert.deepEqual(requests.map(({ filters }) => filters.result), ["changed", "unchanged"]);
  requests[0].response.resolve(comparisonDetail(comparisonHeader(), { offset: 0 }));
  await first;
  assert.equal(fixture.state.comparison, null);
  requests[1].response.resolve(comparisonDetail(comparisonHeader(), { offset: 0 }));
  await second;
  assert.equal(fixture.state.comparison?.items.length, 1);
  assert.equal(fixture.state.comparisonQueryIdentity.result, "unchanged");
}

{
  const requests = [];
  const fixture = comparisonControllerFixture((id, requestedOffset, _signal, filters) => {
    const response = deferred();
    requests.push({ id, offset: requestedOffset, filters, response });
    return response.promise;
  });
  const first = fixture.controller.select("comparison:one", 0);
  fixture.selection.comparisonId = "comparison:two";
  fixture.setSummary(comparisonHeader({ comparisonId: "comparison:two" }));
  const second = fixture.controller.select("comparison:two", 0);
  requests[0].response.resolve(comparisonDetail(comparisonHeader(), { offset: 0 }));
  await first;
  assert.equal(fixture.state.comparison, null);
  requests[1].response.resolve(comparisonDetail(
    comparisonHeader({ comparisonId: "comparison:two" }),
    { offset: 0 },
  ));
  await second;
  assert.equal(fixture.state.comparison?.comparisonId, "comparison:two");
}

{
  const requests = [];
  const fixture = comparisonControllerFixture((id, requestedOffset, _signal, filters) => {
    const response = deferred();
    requests.push({ id, offset: requestedOffset, filters, response });
    return response.promise;
  });
  const initial = fixture.controller.select("comparison:one", 0);
  requests[0].response.resolve(comparisonDetail(comparisonHeader(), { offset: 0 }));
  await initial;
  fixture.setSummary(comparisonHeader({ baselineState: "pruned", comparable: false }));
  const refreshed = fixture.controller.reconcileSummary();
  assert.equal(requests.length, 2);
  requests[1].response.resolve(comparisonDetail(
    comparisonHeader({ baselineState: "pruned", comparable: false }),
    { offset: 0 },
    [{ change: "unknown" }],
  ));
  await refreshed;
  assert.equal(fixture.state.comparison?.baselineState, "pruned");
  assert.equal(fixture.state.comparison.items[0].change, "unknown");
}

{
  const requests = [];
  const fixture = comparisonControllerFixture((id, requestedOffset, _signal, filters) => {
    const response = deferred();
    requests.push({ id, offset: requestedOffset, filters, response });
    return response.promise;
  });
  const staleRequest = fixture.controller.select("comparison:one", 0);
  const refreshedHeader = comparisonHeader({ baselineState: "pruned", comparable: false });
  fixture.setSummary(refreshedHeader);
  const currentRequest = fixture.controller.reconcileSummary();
  assert.equal(requests.length, 2);
  requests[0].response.resolve(comparisonDetail(comparisonHeader(), { offset: 0 }));
  await staleRequest;
  assert.equal(fixture.state.comparison, null);
  requests[1].response.resolve(comparisonDetail(refreshedHeader, { offset: 0 }));
  await currentRequest;
  assert.equal(fixture.state.comparison?.baselineState, "pruned");
}

{
  const requests = [];
  const fixture = comparisonControllerFixture((id, requestedOffset, _signal, filters) => {
    const response = deferred();
    requests.push({ id, offset: requestedOffset, filters, response });
    return response.promise;
  });
  const initial = fixture.controller.select("comparison:one", 0);
  requests[0].response.resolve(comparisonDetail(comparisonHeader(), { offset: 0 }));
  await initial;
  fixture.setSummary(null);
  const filtered = fixture.controller.changeFilter("scope", "device");
  assert.equal(requests.length, 2);
  requests[1].response.resolve(comparisonDetail(comparisonHeader(), { offset: 0 }));
  await filtered;
  assert.equal(fixture.state.comparison?.comparisonId, "comparison:one");
  assert.equal(fixture.state.comparisonQueryIdentity.scope, "device");
}

{
  const requests = [];
  const fixture = comparisonControllerFixture((id, requestedOffset, _signal, filters) => {
    const response = deferred();
    requests.push({ id, offset: requestedOffset, filters, response });
    return response.promise;
  });
  fixture.setSummary(comparisonHeader({ itemCount: 30 }));
  const pageRequest = fixture.controller.select("comparison:one", 25);
  requests[0].response.resolve(comparisonDetail(
    comparisonHeader({ itemCount: 30 }),
    { offset: 25 },
    [],
  ));
  await Promise.resolve();
  assert.deepEqual(requests.map(({ offset }) => offset), [25, 0]);
  assert.equal(fixture.getOffset(), 0);
  requests[1].response.resolve(comparisonDetail(
    comparisonHeader({ itemCount: 30 }),
    { offset: 0 },
    Array.from({ length: 5 }, () => ({})),
  ));
  await pageRequest;
  assert.equal(fixture.state.comparison?.offset, 0);
  assert.equal(fixture.state.comparison.items.length, 5);
}

{
  let fetchCount = 0;
  const header = comparisonHeader();
  const fixture = comparisonControllerFixture(async (_id, requestedOffset, _signal, filters) => {
    fetchCount += 1;
    return comparisonDetail(header, { offset: requestedOffset }, [{}]);
  });
  await fixture.controller.select("comparison:one", 0);
  fixture.controller.cancelPending();
  await fixture.controller.select("comparison:one", 0);
  assert.equal(fetchCount, 1);
  assert.equal(fixture.state.comparisonQueryIdentity.result, "changed");
}

process.stdout.write("phase3 regressions passed\n");