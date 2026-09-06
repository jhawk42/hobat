import assert from "node:assert/strict";
import fs from "node:fs";

import {
  DATASOURCE_REGISTRY,
  DATASET_REGISTRY,
  validateDatasetRegistry,
} from "../../src/js/tdash-dataset-registry.js";
import {
  ROW_EXTRACTORS,
  buildDatasetRows,
} from "../../src/js/tdash-dataset.js";
import { ADAPTOR_HANDLERS } from "../../src/js/tdash-adaptors.js";


function entry(overrides = {}) {
  return {
    source: "system",
    value: "system_test_dataset",
    files: ["td-static-extaddr-device-label.json", "td-mdns-scopes-thread.json"],
    mergeStrategy: "none",
    rowExtractor: "raw-array",
    adaptor: "raw-array",
    defaultPhysicsProfile: "mesh-balanced",
    ...overrides,
  };
}

function payloadForExtractor(extractor, index) {
  const rows = [{ extAddress: `00000000000000${index}`, index }];
  if (extractor === "eve-native") return { nodes: rows };
  if (extractor === "eve-processed") {
    return { [`0x${String(index).padStart(4, "0")}`]: rows[0] };
  }
  if (extractor === "thread-tools-native") return { diagnostics: rows };
  if (extractor === "otbr-restapi") return { data: rows };
  if (extractor === "ha-matter-ws-diagnostics") return { diagnostics: rows };
  if (extractor === "ha-matter-ws-mesh-diagnostics") return { meshDiagnostics: rows };
  return rows;
}

function representativeArrivalOrders(fileIndexes) {
  const orders = [fileIndexes, [...fileIndexes].reverse()];
  for (const lastFileIndex of fileIndexes) {
    orders.push([
      ...fileIndexes.filter((fileIndex) => fileIndex !== lastFileIndex),
      lastFileIndex,
    ]);
  }
  return [...new Map(orders.map((order) => [order.join(','), order])).values()];
}

assert.deepEqual(ROW_EXTRACTORS["raw-array"]([{ id: 1 }]), [{ id: 1 }]);
assert.deepEqual(ROW_EXTRACTORS["raw-array"]({ metadata: true }), []);
assert.deepEqual(ROW_EXTRACTORS["eve-native"]({ nodes: [{ id: 1 }] }), [{ id: 1 }]);
assert.deepEqual(ROW_EXTRACTORS["eve-native"]([{ id: 1 }]), [{ id: 1 }]);
assert.deepEqual(ROW_EXTRACTORS["eve-native"]({ version: 1 }), []);
const processedEvePayload = {
  "0x1000": { id: "eve-a", name: "A" },
  "0x2000": { id: "eve-b", extAddress: "AA" },
  "EVE-C": { id: "eve-c", name: "C" },
  "0x3000": "malformed",
  metadata: { version: 1 },
};
const processedEveRows = ROW_EXTRACTORS["eve-processed"](processedEvePayload);
assert.deepEqual(processedEveRows, [
  { id: "eve-a", name: "A", rloc16: "0x1000" },
  { id: "eve-b", extAddress: "AA" },
  { id: "eve-c", name: "C" },
]);
assert.notEqual(processedEveRows[0], processedEvePayload["0x1000"]);
assert.equal(Object.hasOwn(processedEvePayload["0x1000"], "rloc16"), false);
const processedEveArray = [{ id: "eve-c", rloc16: "0x4000" }, null, "bad"];
assert.deepEqual(ROW_EXTRACTORS["eve-processed"](processedEveArray), [
  { id: "eve-c", rloc16: "0x4000" },
]);
assert.notEqual(ROW_EXTRACTORS["eve-processed"](processedEveArray)[0], processedEveArray[0]);
assert.deepEqual(ROW_EXTRACTORS["thread-tools-native"]({ diagnostics: [{ id: 1 }] }), [{ id: 1 }]);
assert.deepEqual(ROW_EXTRACTORS["thread-tools-native"]({ metadata: true }), []);
assert.deepEqual(ROW_EXTRACTORS["otbr-restapi"]({ data: [{ id: 1 }] }), [{ id: 1 }]);
assert.deepEqual(ROW_EXTRACTORS["otbr-restapi"]({ meta: { count: 1 } }), []);

const detailedRestEntry = DATASET_REGISTRY.find(
  (dataset) => dataset.value === "otbr_restapi_devices_fetch_diagnostics_fetch_all_mesh_diagnostics_fetch_all",
);
const detailedRestRows = buildDatasetRows(detailedRestEntry, [
  [{ extAddress: "AA", hostName: "Router A" }],
  [{ extAddress: "AA", macCounters: { ifInErrors: 2 } }],
  [
    {
      extAddress: "AA",
      routerNeighbors: [{ extAddress: "BB", frameErrorRate: 0.12 }],
      children: [{ extAddress: "CC", messageErrorRate: 0.02 }],
    },
    { extAddress: "BB", role: "child" },
  ],
]).rows;
assert.equal(detailedRestEntry.mergeStrategy, "by-identity");
assert.equal(detailedRestRows.length, 2);
assert.equal(detailedRestRows.find((row) => row.extAddress === "aa").hostName, "Router A");
assert.equal(detailedRestRows.find((row) => row.extAddress === "aa").macCounters.ifInErrors, 2);
assert.equal(detailedRestRows.find((row) => row.extAddress === "aa").routerNeighbors.length, 1);
assert.equal(detailedRestRows.find((row) => row.extAddress === "aa").routerNeighbors[0].err_rate_frame_pct, 12);
assert.equal(detailedRestRows.find((row) => row.extAddress === "aa").childTable[0].err_rate_msg_pct, 2);
assert.equal(detailedRestRows.find((row) => row.extAddress === "bb").role, "child");

const rawFirst = [{ extAddress: "AA", name: "first" }];
const rawSecond = [{ extAddress: "BB", name: "second" }];
const noneResult = buildDatasetRows(entry(), [null, rawSecond]);
assert.deepEqual(noneResult.loadedFiles, ["td-mdns-scopes-thread.json"]);
assert.deepEqual(noneResult.loadedFileIndexes, [1]);
assert.equal(noneResult.rows.length, 1);
assert.equal(noneResult.rows[0].name, "second");

const canonicalResult = buildDatasetRows(entry(), [[{
  extAddress: "AA",
  route: { route_data: [{ route_id: 1 }] },
}], null]);
assert.ok(Array.isArray(canonicalResult.rows[0].route.routeData));
assert.equal(Object.hasOwn(canonicalResult.rows[0].route, "route_data"), false);

const processedEveEntry = DATASET_REGISTRY.find(
  (dataset) => dataset.value === "eve_topology_processed",
);
const cachedProcessedEve = JSON.parse(
  fs.readFileSync("data/td-eve-topology.json", "utf8"),
);
const cachedProcessedEveBefore = JSON.stringify(cachedProcessedEve);
const cachedProcessedEveResult = buildDatasetRows(processedEveEntry, [cachedProcessedEve]);
assert.equal(processedEveEntry.rowExtractor, "eve-processed");
assert.deepEqual(cachedProcessedEveResult.loadedFiles, ["td-eve-topology.json"]);
assert.equal(cachedProcessedEveResult.rows.length, 79);
assert.deepEqual(
  cachedProcessedEveResult.rows.map((row) => row.id),
  Object.values(cachedProcessedEve).map((row) => row.id),
);
assert.ok(cachedProcessedEveResult.rows.every((row) => row.id));
assert.ok(cachedProcessedEveResult.rows.every(
  (row) => row._source_files.includes("td-eve-topology.json"),
));
assert.equal(JSON.stringify(cachedProcessedEve), cachedProcessedEveBefore);

for (const mergeStrategy of ["by-rloc16", "by-identity"]) {
  const mergeEntry = entry({ mergeStrategy });
  const firstThenSecond = buildDatasetRows(mergeEntry, [rawFirst, rawSecond]);
  const secondThenFirst = buildDatasetRows(mergeEntry, [null, rawSecond]);
  const converged = buildDatasetRows(mergeEntry, [rawFirst, rawSecond]);
  assert.deepEqual(firstThenSecond.rows, converged.rows);
  assert.deepEqual(secondThenFirst.loadedFileIndexes, [1]);
  assert.deepEqual(firstThenSecond.loadedFileIndexes, [0, 1]);
  assert.ok(firstThenSecond.rows.every((row) => Array.isArray(row._source_files)));
}

const inputFiles = [rawFirst, undefined];
const inputEntry = entry();
buildDatasetRows(inputEntry, inputFiles);
assert.deepEqual(inputFiles, [rawFirst, undefined]);
assert.equal(Object.hasOwn(inputEntry, "loadedFiles"), false);

assert.doesNotThrow(() => validateDatasetRegistry(DATASET_REGISTRY));

const haMatterSource = DATASOURCE_REGISTRY.find((source) => source.value === "ha-matter-ws");
assert.equal(haMatterSource?.default_dataset_value, "ha_matter_ws_topology");
const haMatterDashboard = {
  diagnostics: [{ nodeId: 1, branch: "diagnostics" }],
  meshDiagnostics: [{ nodeId: 2, branch: "meshDiagnostics" }],
};
assert.deepEqual(
  ROW_EXTRACTORS["ha-matter-ws-diagnostics"](haMatterDashboard),
  haMatterDashboard.diagnostics,
);
assert.deepEqual(
  ROW_EXTRACTORS["ha-matter-ws-mesh-diagnostics"](haMatterDashboard),
  haMatterDashboard.meshDiagnostics,
);
assert.deepEqual(
  DATASET_REGISTRY
    .filter((entry) => entry.source === "ha-matter-ws")
    .map((entry) => entry.value),
  [
    "ha_matter_ws_devices_fetch_all",
    "ha_matter_ws_dashboard_diagnostics",
    "ha_matter_ws_dashboard_mesh_diagnostics",
    "ha_matter_ws_topology",
  ],
);
assert.ok(
  DATASET_REGISTRY
    .filter((entry) => [
      "ha_matter_ws_dashboard_mesh_diagnostics",
      "ha_matter_ws_topology",
    ].includes(entry.value))
    .every((entry) => entry.defaultLinkFilter === "all_links"),
);
assert.ok(DATASET_REGISTRY.every((dataset) => ADAPTOR_HANDLERS[dataset.adaptor]));
for (const dataset of DATASET_REGISTRY) {
  const finalRawFiles = dataset.files.map((_, index) =>
    payloadForExtractor(dataset.rowExtractor, index),
  );
  const expected = buildDatasetRows(dataset, finalRawFiles);
  const fileIndexes = dataset.files.map((_, index) => index);
  for (const arrivalOrder of representativeArrivalOrders(fileIndexes)) {
    const arrivingRawFiles = dataset.files.map(() => null);
    for (const fileIndex of arrivalOrder) {
      arrivingRawFiles[fileIndex] = finalRawFiles[fileIndex];
      buildDatasetRows(dataset, arrivingRawFiles);
    }
    assert.deepEqual(buildDatasetRows(dataset, arrivingRawFiles), expected);
  }
}
assert.throws(
  () => validateDatasetRegistry([entry(), entry()]),
  /duplicate dataset value/i,
);
assert.throws(
  () => validateDatasetRegistry([entry({ rowExtractor: "missing" })]),
  /row extractor/i,
);
assert.throws(
  () => validateDatasetRegistry([entry({ files: [] })]),
  /files/i,
);
assert.throws(
  () => validateDatasetRegistry([entry({ files: ["unknown.json"] })]),
  /unknown file/i,
);
assert.throws(
  () => validateDatasetRegistry([entry({ mergeStrategy: "missing" })]),
  /merge strategy/i,
);
assert.throws(
  () => validateDatasetRegistry([entry({ adaptor: "missing" })]),
  /unknown adaptor/i,
);
assert.throws(
  () => validateDatasetRegistry([entry({ defaultPhysicsProfile: "missing" })]),
  /physics profile/i,
);
assert.throws(
  () => validateDatasetRegistry([entry({
    adaptor: "eve-native",
    rowExtractor: "raw-array",
  })]),
  /unsupported adaptor\/row extractor combination/i,
);
assert.throws(
  () => validateDatasetRegistry([entry({
    adaptor: "eve-enhanced",
    rowExtractor: "raw-array",
  })]),
  /unsupported adaptor\/row extractor combination/i,
);

process.stdout.write(`${JSON.stringify({
  datasetCount: DATASET_REGISTRY.length,
  extractorCount: Object.keys(ROW_EXTRACTORS).length,
  adaptorCount: Object.keys(ADAPTOR_HANDLERS).length,
})}\n`);