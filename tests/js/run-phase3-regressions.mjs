import assert from "node:assert/strict";

import { computeRowCounts, evaluateDiagnosticOption, getRowRoleProjection, isRowVisibleByNodeFilter } from "../../src/js/tdash-filters.js";
import { formatAge } from "../../src/js/tdash-health.js";
import { collectColumns, getTableFilterLabel } from "../../src/js/tdash-table-renderer.js";

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

const counts = computeRowCounts([{ role: "Router", isRouter: true }, { role: "SleepyEndDevice" }, { isBorderRouter: true }]);
assert.deepEqual([counts.borderRouters, counts.routers, counts.children], [1, 1, 1]);
assert.equal(formatAge(null), "unknown");
assert.equal(formatAge("not-a-date"), "unknown");
assert.equal(formatAge(new Date(Date.now() - 30_000).toISOString()), "just now");

process.stdout.write("phase3 regressions passed\n");