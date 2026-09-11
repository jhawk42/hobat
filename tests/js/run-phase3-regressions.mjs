import assert from "node:assert/strict";

import { computeRowCounts, evaluateDiagnosticOption, getRowRoleProjection, isRowVisibleByNodeFilter } from "../../src/js/tdash-filters.js";
import { buildDatasetRows } from "../../src/js/tdash-dataset.js";
import { formatAge } from "../../src/js/tdash-health.js";
import {
  collectColumns,
  getTableColumnCategories,
  getTableColumnsForCategory,
  getTableFilterLabel,
} from "../../src/js/tdash-table-renderer.js";

const explicitRouter = { isRouter: true, role: "Router", children: [{}] };
const leader = { role: "leader" };
const reedChild = { rloc16: "0x1001", role: "REED", mode: { device: "FTD" } };
const borderRouter = { isBorderRouter: true };
assert.equal(isRowVisibleByNodeFilter(explicitRouter, "main-routers"), true);
assert.equal(isRowVisibleByNodeFilter(leader, "main-routers"), true);
assert.equal(isRowVisibleByNodeFilter(borderRouter, "border-routers"), true);
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
assert.equal(getTableFilterLabel(null, "All nodes"), "All nodes");
assert.equal(getTableFilterLabel({ selectedOptions: [] }, "All diagnostics"), "All diagnostics");
assert.equal(getTableFilterLabel({ selectedOptions: [{ text: "Routers" }] }, "All nodes"), "Routers");
assert.equal(getTableColumnCategories().some(({ value }) => value === "matter-list"), true);
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

const haMatterRows = buildDatasetRows({
  source: "ha-matter-ws",
  mergeStrategy: "none",
  rowExtractor: "raw-array",
  files: ["ha-matter.json"],
}, [[{ deviceLabel: "Desk Light", nodeId: 123, vendorName: "Example", networkInterfaces: [] }]]).rows;
assert.deepEqual(haMatterRows[0].matter, {
  deviceLabel: "Desk Light", nodeId: 123, vendorName: "Example",
});

const counts = computeRowCounts([{ role: "Router", isRouter: true }, { role: "SleepyEndDevice" }, { isBorderRouter: true }]);
assert.deepEqual([counts.borderRouters, counts.routers, counts.children], [1, 1, 1]);
assert.equal(formatAge(null), "unknown");
assert.equal(formatAge("not-a-date"), "unknown");
assert.equal(formatAge(new Date(Date.now() - 30_000).toISOString()), "just now");

process.stdout.write("phase3 regressions passed\n");