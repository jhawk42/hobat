import assert from "node:assert/strict";
import fs from "node:fs";

import {
  DATASOURCE_REGISTRY,
  DATASET_REGISTRY,
  DATASET_CATALOG_FALLBACK,
  setDatasetCatalog,
  validateDatasetCatalog,
  validateDatasetRegistry,
} from "../../src/js/tdash-dataset-registry.js";
import {
  ROW_EXTRACTORS,
  buildDatasetRows,
  getDatasetAuxiliaryFiles,
  normalizeDatasetFilePayload,
} from "../../src/js/tdash-dataset.js";
import { normalizeRows } from "../../src/js/tdash-merge.js";
import { normalizeDatasetPayload } from "../../src/js/tdash-utils.js";
import { buildDeviceProjection } from "../../src/js/tdash-device-projection.js";
import { ADAPTOR_HANDLERS, runAdaptor } from "../../src/js/tdash-adaptors.js";
import {
  computeTopologyCapabilities,
  isNodeVisibleByFilter,
  isRowVisibleByNodeFilter,
} from "../../src/js/tdash-filters.js";


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
  if (extractor === "ha-matter-ws-border-routers") return { borderRouters: rows };
  if (extractor === "ha-matter-ws-network-topology") return { topology: { nodes: rows } };
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
const otbrCliEntry = DATASET_REGISTRY.find((entry) => entry.source === "otbr-cli");
assert.deepEqual(getDatasetAuxiliaryFiles(otbrCliEntry), ["td-otbr-cli-thread-network-info.json"]);
const otbrRestEntry = DATASET_REGISTRY.find((entry) => entry.source === "otbr-restapi");
assert.deepEqual(getDatasetAuxiliaryFiles(otbrRestEntry), ["td-otbr-restapi-dataset-active.json"]);
assert.deepEqual(getDatasetAuxiliaryFiles(entry({ source: "system" })), []);
assert.equal(otbrCliEntry.files.includes("td-otbr-cli-thread-network-info.json"), false);
assert.equal(otbrRestEntry.files.includes("td-otbr-restapi-dataset-active.json"), false);
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
assert.equal(detailedRestRows.find((row) => row.extAddress === "aa").deviceLabel, "Router A");
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
const noneBoth = buildDatasetRows(entry(), [rawFirst, rawSecond]);
assert.deepEqual(noneBoth.rows.map((row) => row.name), ["first"]);
assert.deepEqual(noneBoth.loadedFileIndexes, [0, 1]);
assert.deepEqual(noneBoth.rows[0]._source_files, ["td-static-extaddr-device-label.json"]);
const changedRloc = [
  [{ extAddress: "aa11", rloc16: "0x1000" }],
  [{ extAddress: "aa11", rloc16: "0x2000" }],
];
assert.equal(buildDatasetRows(entry({ mergeStrategy: "by-rloc16" }), changedRloc).rows.length, 2);
assert.equal(buildDatasetRows(entry({ mergeStrategy: "by-identity" }), changedRloc).rows.length, 1);
const collidingRloc = [
  [{ extAddress: "aa11", rloc16: "0x1000" }],
  [{ extAddress: "bb22", rloc16: "0x1000" }],
];
assert.deepEqual(
  buildDatasetRows(entry({ mergeStrategy: "by-rloc16" }), collidingRloc).rows
    .map((row) => [row.extAddress, row._source_files]),
  [["aa11", ["td-static-extaddr-device-label.json"]], ["bb22", ["td-mdns-scopes-thread.json"]]],
);

const canonicalResult = buildDatasetRows(entry(), [[{
  extAddress: "AA",
  route: { route_data: [{ route_id: 1 }] },
}], null]);
assert.ok(Array.isArray(canonicalResult.rows[0].route.routeData));
assert.equal(Object.hasOwn(canonicalResult.rows[0].route, "route_data"), false);

const cliVersionResult = buildDatasetRows(entry({
  source: "otbr-cli",
  value: "cli_version_fields",
  files: ["td-otbr-cli-networkdiag-fetch-all.json"],
}), [[{
  extAddress: "0011223344556677",
  rloc16: "0x0400",
  eui64: "8899aabbccddeeff",
  ver: 4,
  thread_version: "1.3",
}]]);
assert.equal(cliVersionResult.rows[0].eui, "8899aabbccddeeff");
assert.equal(cliVersionResult.rows[0].threadVersionDecimal, 4);
assert.equal(cliVersionResult.rows[0].threadVersion, "1.3");
assert.equal(Object.hasOwn(cliVersionResult.rows[0], "ver"), false);
assert.equal(Object.hasOwn(cliVersionResult.rows[0], "eui64"), false);

const restVersionResult = buildDatasetRows(entry({
  source: "otbr-restapi",
  value: "rest_version_fields",
  files: ["td-otbr-restapi-diagnostics-fetch-all.json"],
}), [[{
  type: "threadNetworkDiagnostic",
  eui: "8899aabbccddeeff",
  threadVersion: 4,
}]]);
assert.equal(restVersionResult.rows[0].threadVersionDecimal, 4);
assert.equal(restVersionResult.rows[0].threadVersion, "1.3");
assert.equal(Object.hasOwn(restVersionResult.rows[0], "version"), false);

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
const servedCatalog = JSON.parse(fs.readFileSync(new URL("../../src/td-dataset-manifest.json", import.meta.url)));
assert.deepEqual(DATASET_CATALOG_FALLBACK, servedCatalog);
assert.doesNotThrow(() => setDatasetCatalog(servedCatalog));
for (const [patch, message] of [
  [{ mergeStrategy: "invalid" }, /unknown merge strategy/],
  [{ adaptor: "invalid" }, /unknown adaptor/],
  [{ mergeRowExtractors: [] }, /one merge row extractor per file/],
]) {
  const invalid = { ...servedCatalog, datasets: [{ ...servedCatalog.datasets[0], ...patch }] };
  assert.throws(() => validateDatasetCatalog(invalid), message);
}
assert.throws(() => validateDatasetCatalog({ ...servedCatalog, vocabulary: {} }), /vocabulary/);
setDatasetCatalog(DATASET_CATALOG_FALLBACK);

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
const nativeBorderRouterWrapper = {
  borderRouters: [{ extAddressHex: "AABBCCDDEEFF0011", networkName: "Test Thread" }],
};
assert.deepEqual(
  ROW_EXTRACTORS["ha-matter-ws-border-routers"](nativeBorderRouterWrapper),
  nativeBorderRouterWrapper.borderRouters,
);
const nativeTopologyWrapper = { topology: { nodes: [{ id: "native-a" }], connections: [] } };
assert.deepEqual(
  ROW_EXTRACTORS["ha-matter-ws-network-topology"](nativeTopologyWrapper),
  nativeTopologyWrapper.topology.nodes,
);
assert.deepEqual(
  DATASET_REGISTRY
    .filter((entry) => entry.source === "ha-matter-ws")
    .map((entry) => entry.value),
  [
    "ha_matter_ws_devices_fetch_all",
    "ha_matter_ws_thread_border_routers",
    "ha_matter_ws_dashboard_diagnostics",
    "ha_matter_ws_dashboard_mesh_diagnostics",
    "ha_matter_ws_topology",
    "ha_matter_ws_network_topology",
    "ha_matter_ws_merge_topology",
  ],
);
const haMatterMergeEntry = DATASET_REGISTRY.find(
  (dataset) => dataset.value === "ha_matter_ws_merge_topology",
);
const haMatterMergeRows = buildDatasetRows(
  haMatterMergeEntry,
  haMatterMergeEntry.files.map((file) => JSON.parse(fs.readFileSync(`data/${file}`, "utf8"))),
).rows;
assert.ok(haMatterMergeRows.every((row) => row._row_key === undefined));
const haMatterRouteRows = [
  {
    extAddress: "0011223344556677",
    route: { routeData: [
      { sourceId: "router-a", targetId: "router-b", pathCost: 1 },
      { sourceId: "router-a", targetId: "router-c", pathCost: 2 },
    ] },
  },
  {
    extAddress: "8899aabbccddeeff",
    route: { routeData: [
      { sourceId: "router-b", targetId: "router-c", pathCost: 1 },
    ] },
  },
];
const haMatterRouteFiles = haMatterMergeEntry.files.map((filename) => {
  if ([
    "td-ha-matter-ws-mesh-diagnostics-fetch-all.json",
    "td-ha-matter-ws-topology.json",
  ].includes(filename)) return structuredClone(haMatterRouteRows);
  if (filename === "td-ha-matter-ws-dashboard.json") {
    return { topology: structuredClone(haMatterRouteRows) };
  }
  return null;
});
const haMatterRouteAssembly = buildDatasetRows(haMatterMergeEntry, haMatterRouteFiles);
assert.deepEqual(
  haMatterRouteAssembly.rows.map(({ extAddress, route }) => ({ extAddress, route })),
  haMatterRouteRows,
);
assert.ok(haMatterRouteAssembly.rows.every((row) => row._row_key === undefined));

const haDeviceEntry = DATASET_REGISTRY.find(
  (dataset) => dataset.value === "ha_matter_ws_devices_fetch_all",
);
const oldReedRows = buildDatasetRows(haDeviceEntry, [[
  {
    matter: { nodeId: 1, matterId: "FABRIC-1" },
    thread: { routingRole: "Reed", rloc16: "0x1001" },
  },
]]);
assert.equal(Object.hasOwn(oldReedRows.rows[0], "isRouter"), false);
assert.equal(Object.hasOwn(oldReedRows.rows[0], "isLeader"), false);
assert.equal(Object.hasOwn(oldReedRows.rows[0], "isReed"), false);
assert.equal(Object.hasOwn(oldReedRows.rows[0], "isBorderRouter"), false);
const enrichedReedRows = buildDatasetRows(haDeviceEntry, [[
  {
    matter: { nodeId: 1, matterId: "FABRIC-1" },
    thread: {
      routingRole: "Reed",
      rloc16: "0x1001",
      isRouter: true,
      isLeader: true,
      isReed: true,
      isBorderRouter: true,
    },
    isRouter: false,
    isLeader: false,
    isReed: false,
    isBorderRouter: false,
  },
]]);
assert.deepEqual(
  [enrichedReedRows.rows[0].isBorderRouter, enrichedReedRows.rows[0].isRouter,
    enrichedReedRows.rows[0].isLeader, enrichedReedRows.rows[0].isReed],
  [false, false, false, false],
);

const invalidFetchedDevice = normalizeDatasetFilePayload(
  haDeviceEntry,
  0,
  [{
    matter: { nodeId: 2 },
    thread: { routingRole: "Reed" },
    isRouter: "true",
  }],
);
assert.equal(invalidFetchedDevice[0].isRouter, true);
assert.equal(Object.hasOwn(invalidFetchedDevice[0], "isReed"), false);
assert.notEqual(invalidFetchedDevice[0].leaderEvidence, "leader-router-id-match");

const nestedExplicitDevice = normalizeDatasetFilePayload(
  haDeviceEntry,
  0,
  [{
    matter: { nodeId: 3 },
    thread: { routingRole: "Reed", isRouter: true },
  }],
);
assert.equal(Object.hasOwn(nestedExplicitDevice[0], "isRouter"), false);
assert.equal(nestedExplicitDevice[0].thread.isRouter, true);
assert.equal(Object.hasOwn(nestedExplicitDevice[0], "isReed"), false);
const nestedFactAssembly = buildDatasetRows(haDeviceEntry, [[{
  matter: { nodeId: 3 },
  thread: { isRouter: true, isLeader: false, isReed: true, isBorderRouter: false },
}]]);
assert.deepEqual(
  ["isBorderRouter", "isRouter", "isLeader", "isReed"].map((field) =>
    nestedFactAssembly.rows[0][field]),
  [false, true, false, true],
);

const oldOtbrCliEntry = DATASET_REGISTRY.find(
  (item) => item.value === "otbr_cli_networkdiag_fetch_all",
);
const oldOtbrCliRecord = {
  extAddress: "0011223344556677",
  role: "router",
  type: "child",
  mode: { device: "FTD" },
};
const oldOtbrCliSource = structuredClone(oldOtbrCliRecord);
const oldOtbrPayload = normalizeDatasetFilePayload(
  oldOtbrCliEntry,
  0,
  [oldOtbrCliRecord],
);
assert.equal(Object.hasOwn(oldOtbrPayload[0], "isReed"), false);
assert.deepEqual(oldOtbrCliRecord, oldOtbrCliSource);
assert.equal(
  Object.hasOwn(normalizeDatasetFilePayload(oldOtbrCliEntry, 0, oldOtbrPayload)[0], "isReed"),
  false,
);
const oldOtbrAssembly = buildDatasetRows(oldOtbrCliEntry, [[oldOtbrCliRecord]]);
assert.equal(Object.hasOwn(oldOtbrAssembly.rows[0], "isReed"), false);
assert.equal(buildDeviceProjection(oldOtbrAssembly.rows[0]).isReed, false);
const fallbackFtd = { role: "child", mode: { device: "FTD" }, isRouter: false, isBorderRouter: false };
assert.equal(buildDeviceProjection(fallbackFtd).isReed, true);
const explicitFalseOtbrPayload = normalizeDatasetFilePayload(
  oldOtbrCliEntry,
  0,
  [{
    ...oldOtbrCliRecord,
    isReed: false,
  }],
);
assert.equal(explicitFalseOtbrPayload[0].isReed, false);
assert.deepEqual(explicitFalseOtbrPayload[0]._merge_conflicts, undefined);
const explicitFalseOtbrRaw = [{
  ...oldOtbrCliRecord,
  isReed: false,
}];
const explicitFalseOtbrAssembly = buildDatasetRows(
  oldOtbrCliEntry,
  [explicitFalseOtbrRaw],
);
const explicitFalseOtbrAdapted = runAdaptor({
  entry: oldOtbrCliEntry,
  rawFiles: [explicitFalseOtbrRaw],
  rows: explicitFalseOtbrAssembly.rows,
  adaptorRows: explicitFalseOtbrAssembly.adaptorRows,
});
const explicitFalseOtbrNode = [...explicitFalseOtbrAdapted.nodeMap.values()][0];
assert.equal(explicitFalseOtbrNode.isReed, false);
assert.equal(
  [...explicitFalseOtbrAdapted.rawByIdForDetails.values()][0].isReed,
  false,
);

const legacyOtbrLookingEntry = {
  ...oldOtbrCliEntry,
  value: "otbr_cli_networkdiag_other_product",
};
const legacyOtbrLookingRows = buildDatasetRows(legacyOtbrLookingEntry, [[
  { role: "child", mode: { device: "FTD" } },
]]);
assert.equal(Object.hasOwn(legacyOtbrLookingRows.rows[0], "isReed"), false);

const otbrMdnsRecipes = [
  {
    value: "otbr_cli_topology_mdns_health",
    eligiblePrefix: "td-otbr-cli-networkdiag-fetch-all.json",
  },
  {
    value: "otbr_restapi_topology_mdns_health",
    eligiblePrefix: "td-otbr-restapi-devices-fetch.json",
  },
  {
    value: "otbr_cli_meshdiag_topology_networkdiag_multicast_network_router_neighbortables_router_childtables_mdns_scopes_thread",
    eligiblePrefix: "td-otbr-cli-networkdiag-multicast-network.json",
  },
];
for (const { value, eligiblePrefix } of otbrMdnsRecipes) {
  const dataset = DATASET_REGISTRY.find((item) => item.value === value);
  const sourceIndexes = dataset.files
    .map((filename, index) => filename.startsWith("td-otbr-") ? index : -1)
    .filter((index) => index >= 0);
  const eligibleIndex = dataset.files.indexOf(eligiblePrefix);
  const mdnsIndex = dataset.files.indexOf("td-mdns-scopes-thread.json");
  const complementaryIndex = dataset.files.findIndex((filename, index) =>
    filename.startsWith("td-otbr-")
    && filename !== eligiblePrefix
    && index !== eligibleIndex
    && filename !== "td-mdns-scopes-thread.json"
  );
  assert.ok(eligibleIndex >= 0, `${value} lacks eligible input`);
  assert.ok(sourceIndexes.length > 0, `${value} has no OTBR input`);
  assert.ok(mdnsIndex >= 0, `${value} lacks mDNS input`);
  assert.ok(complementaryIndex >= 0, `${value} lacks complementary OTBR input`);
  const inputRows = new Array(dataset.files.length).fill(null);
  sourceIndexes.forEach((index, eligibleOrdinal) => {
    inputRows[index] = [{
      extAddress: eligibleOrdinal === 0
        ? "0011223344556677"
        : "3011223344556677",
      role: "child",
      mode: { device: "FTD" },
    }];
  });
  inputRows[complementaryIndex].push({
    extAddress: "1011223344556677",
    type: "child",
    mode: { device: "FTD" },
  });
  inputRows[mdnsIndex] = [{
    extAddress: "0011223344556677",
    serviceInfo: { name: "matched mDNS enrichment" },
  }, {
    extAddress: "2011223344556677",
    role: "child",
    mode: { device: "FTD" },
    serviceInfo: { name: "mDNS enrichment" },
  }];
  const untouchedInputs = structuredClone(inputRows);
  const normalizedInputs = inputRows.map((payload, index) =>
    payload === null
      ? null
      : normalizeDatasetFilePayload(dataset, index, payload),
  );
  assert.deepEqual(inputRows, untouchedInputs);
  sourceIndexes.forEach((index) => {
    assert.equal(Object.hasOwn(normalizedInputs[index][0], "isReed"), false, value);
  });
  assert.equal(
    Object.hasOwn(normalizedInputs[complementaryIndex][0], "isReed"),
    false,
    value,
  );
  assert.equal(Object.hasOwn(normalizedInputs[mdnsIndex][0], "isReed"), false, value);
  const assembled = buildDatasetRows(dataset, normalizedInputs);
  assert.equal(Object.hasOwn(
    assembled.rows.find((row) => row.extAddress === "0011223344556677"),
    "isReed",
  ), false, value);
  assert.ok(
    assembled.rows.find((row) => row.extAddress === "0011223344556677")
      ._source_files.includes("td-mdns-scopes-thread.json"),
    value,
  );
  assert.equal(
    assembled.rows.find((row) => row.extAddress === "0011223344556677")
      .serviceInfo?.name,
    "matched mDNS enrichment",
    value,
  );
  assert.equal(
    Object.hasOwn(
      assembled.rows.find((row) => row.extAddress === "1011223344556677"),
      "isReed",
    ),
    false,
    value,
  );
  assert.equal(
    Object.hasOwn(
      assembled.rows.find((row) => row.extAddress === "2011223344556677"),
      "isReed",
    ),
    false,
    value,
  );
  for (const order of representativeArrivalOrders(
    dataset.files.map((_, index) => index),
  )) {
    const arriving = new Array(dataset.files.length).fill(null);
    for (const index of order) {
      arriving[index] = normalizedInputs[index];
      const partial = buildDatasetRows(dataset, arriving);
      if (sourceIndexes.includes(index)) {
        const reed = partial.rows.find((row) => row.extAddress === "0011223344556677");
        if (reed) assert.equal(Object.hasOwn(reed, "isReed"), false, value);
      }
      if (index === mdnsIndex) {
        const mdnsOnly = partial.rows.find((row) =>
          row.extAddress === "2011223344556677");
        assert.equal(Object.hasOwn(mdnsOnly ?? {}, "isReed"), false, value);
      }
    }
  }

  const conflictRawFiles = structuredClone(normalizedInputs);
  sourceIndexes.forEach((index) => {
    const row = conflictRawFiles[index].find(
      (item) => item.extAddress === "0011223344556677",
    );
    if (row) row.isReed = false;
  });
  const conflictAssembly = buildDatasetRows(dataset, conflictRawFiles);
  const conflictRow = conflictAssembly.rows.find(
    (row) => row.extAddress === "0011223344556677",
  );
  assert.equal(conflictRow.isReed, false, value);
  assert.equal(conflictRow._merge_conflicts?.some((conflict) =>
    conflict.path === "isReed") ?? false, false, value);
  const mergeWinnerInputs = structuredClone(normalizedInputs);
  mergeWinnerInputs[complementaryIndex].push({
    extAddress: "0011223344556677",
    role: "child",
    mode: { device: "FTD" },
    isReed: false,
  });
  const mergeWinnerAssembly = buildDatasetRows(dataset, mergeWinnerInputs);
  const mergeWinnerRow = mergeWinnerAssembly.rows.find(
    (row) => row.extAddress === "0011223344556677",
  );
  assert.equal(mergeWinnerRow.isReed, false, value);
  assert.equal(typeof mergeWinnerRow.isReed, "boolean", value);
  const missingInputs = buildDatasetRows(
    dataset,
    new Array(dataset.files.length).fill(null),
  );
  assert.deepEqual(missingInputs.loadedFiles, [], value);
  assert.deepEqual(missingInputs.rows, [], value);
}

const dashboardDiagnosticsEntry = DATASET_REGISTRY.find(
  (dataset) => dataset.value === "ha_matter_ws_dashboard_diagnostics",
);
const fetchedRoleConflicts = normalizeDatasetFilePayload(
  dashboardDiagnosticsEntry,
  0,
  {
    diagnostics: [
      {
        role: "Unknown",
        isRouter: false,
        is_router: true,
      },
      {
        role: "Unknown",
        routerId: 4,
        leaderData: { leaderRouterId: 4 },
      },
    ],
  },
);
assert.equal(fetchedRoleConflicts.diagnostics[0].isRouter, false);
assert.equal(fetchedRoleConflicts.diagnostics[0]._merge_conflicts, undefined);
assert.equal(Object.hasOwn(fetchedRoleConflicts.diagnostics[1], "isLeader"), false);
assert.equal(Object.hasOwn(fetchedRoleConflicts.diagnostics[1], "leaderEvidence"), false);
const inferredLeaderAssembly = buildDatasetRows(dashboardDiagnosticsEntry, [{
  diagnostics: [{
    matterId: "unknown-role",
    role: "Unknown",
    routerId: 4,
    leaderData: { leaderRouterId: 4 },
  }],
}]);
assert.equal(Object.hasOwn(inferredLeaderAssembly.rows[0], "isLeader"), false);
const inferredLeaderAdapted = runAdaptor({
  entry: dashboardDiagnosticsEntry,
  rawFiles: [{
    diagnostics: [{
      matterId: "unknown-role",
      role: "Unknown",
      routerId: 4,
      leaderData: { leaderRouterId: 4 },
    }],
  }],
  rows: inferredLeaderAssembly.rows,
  adaptorRows: inferredLeaderAssembly.adaptorRows,
});
const inferredLeaderNode = [...inferredLeaderAdapted.nodeMap.values()][0];
assert.equal(Object.hasOwn(inferredLeaderNode, "isLeader"), false);
assert.equal(
  Object.hasOwn(inferredLeaderAdapted.rawByIdForDetails.values().next().value, "isLeader"),
  false,
);
assert.equal(
  normalizeDatasetPayload([{ isRouter: "true" }])[0].isRouter,
  true,
  "generic payload normalization remains unchanged",
);

const roleSource = [{
  role: "Leader",
  isRouter: false,
  is_router: true,
  isBorderRouter: "true",
  br: true,
}];
const normalizedRoleRows = normalizeRows(
  roleSource,
  "td-ha-matter-ws-diagnostics-fetch-all.json",
);
assert.equal(normalizedRoleRows[0].isRouter, false);
assert.equal(Object.hasOwn(normalizedRoleRows[0], "isLeader"), false);
assert.equal(Object.hasOwn(normalizedRoleRows[0], "isReed"), false);
assert.equal(normalizedRoleRows[0].isBorderRouter, true);
assert.equal(Object.hasOwn(normalizedRoleRows[0], "br"), false);
assert.deepEqual(normalizedRoleRows[0]._merge_conflicts, undefined);
const normalizedRoleRowsAgain = normalizeRows(
  normalizedRoleRows,
  "td-ha-matter-ws-diagnostics-fetch-all.json",
);
assert.equal(normalizedRoleRowsAgain[0].isRouter, false);

const oldNativeTopology = buildDatasetRows(
  DATASET_REGISTRY.find((dataset) => dataset.value === "ha_matter_ws_network_topology"),
  [{
    topology: {
      nodes: [
        { id: "reed", kind: "matter", network_type: "thread", role: "reed" },
        { id: "ap", kind: "wifi_ap", network_type: "wifi", role: "ap" },
        { id: "br", kind: "border_router", network_type: "thread", role: "router" },
      ],
      connections: [],
    },
  }],
);
assert.deepEqual(
  oldNativeTopology.rows.map((row) => [
    row.isBorderRouter,
    row.isRouter,
    row.isLeader,
    row.isReed,
  ]),
  [
    [undefined, undefined, undefined, undefined],
    [undefined, undefined, undefined, undefined],
    [undefined, undefined, undefined, undefined],
  ],
);
const nativeTopologyEntry = DATASET_REGISTRY.find(
  (dataset) => dataset.value === "ha_matter_ws_network_topology",
);
const nativeTopologyRaw = [{
  topology: {
    nodes: [
      {
        id: "reed",
        kind: "matter",
        network_type: "thread",
        role: "reed",
        rloc16: 4096,
      },
      {
        id: "ap",
        kind: "wifi_ap",
        network_type: "wifi",
        role: "ap",
        rloc16: 4096,
      },
      {
        id: "br",
        kind: "border_router",
        network_type: "thread",
        role: "reed",
        isRouter: false,
      },
    ],
    connections: [{
      source: "reed",
      target: "br",
      network: "thread",
      strength: "strong",
    }],
  },
}];
const nativeTopologyAssembly = buildDatasetRows(nativeTopologyEntry, nativeTopologyRaw);
const nativeTopologyAdapted = runAdaptor({
  entry: nativeTopologyEntry,
  rawFiles: nativeTopologyRaw,
  rows: nativeTopologyAssembly.rows,
  adaptorRows: nativeTopologyAssembly.adaptorRows,
});
assert.equal(nativeTopologyAdapted.nodeMap.get("reed").isRouter, false);
assert.equal(Object.hasOwn(nativeTopologyAdapted.nodeMap.get("reed"), "isReed"), false);
assert.equal(nativeTopologyAdapted.nodeMap.get("ap").isRouter, false);
assert.equal(nativeTopologyAdapted.nodeMap.get("br").isBorderRouter, true);
assert.equal(nativeTopologyAdapted.nodeMap.get("br").isRouter, false);
assert.equal(nativeTopologyAdapted.edgeData.length, 1);
assert.equal(nativeTopologyAdapted.rawByIdForDetails.get("br").isRouter, false);
const nativeBorderNode = nativeTopologyAdapted.nodeData.find((node) => node.id === "br");
const nativeReedNode = nativeTopologyAdapted.nodeData.find((node) => node.id === "reed");
assert.equal(nativeBorderNode.isBorderRouter, true);
assert.equal(Object.hasOwn(nativeReedNode, "isReed"), false);
assert.equal(isRowVisibleByNodeFilter(
  nativeTopologyAssembly.rows.find((row) => row.id === "reed"),
  "reed-devices",
), false);
assert.equal(isRowVisibleByNodeFilter(
  nativeTopologyAssembly.rows.find((row) => row.id === "reed"),
  "main-routers",
), false);
assert.equal(
  computeTopologyCapabilities(nativeTopologyAdapted.nodeData, []).hasBorderRouters,
  true,
);
assert.equal(
  isNodeVisibleByFilter(
    nativeReedNode,
    "reed-devices",
    undefined,
  ),
  false,
);

const mergeTopologyEntry = DATASET_REGISTRY.find(
  (dataset) => dataset.value === "ha_matter_ws_merge_topology",
);
const mergedNativeTopology = {
  topology: {
    nodes: [
      {
        id: "merged-reed",
        kind: "matter",
        network_type: "thread",
        role: "reed",
        extAddress: "0011223344556677",
      },
      {
        id: "merged-br",
        kind: "border_router",
        network_type: "thread",
        role: "router",
        extAddress: "8899aabbccddeeff",
      },
    ],
    connections: [{
      source: "merged-reed",
      target: "merged-br",
      network: "thread",
      strength: "strong",
    }],
  },
};
const mergeTopologyRawFiles = mergeTopologyEntry.files.map((filename) =>
  filename === "td-ha-matter-ws-network-topology.json"
    ? mergedNativeTopology
    : null);
const mergeTopologyAssembly = buildDatasetRows(
  mergeTopologyEntry,
  mergeTopologyRawFiles,
);
const mergeTopologyAdapted = runAdaptor({
  entry: mergeTopologyEntry,
  rawFiles: mergeTopologyRawFiles,
  rows: mergeTopologyAssembly.rows,
  adaptorRows: mergeTopologyAssembly.adaptorRows,
});
assert.notEqual(mergeTopologyAdapted.nodeMap.get("merged-reed").isRouter, true);
assert.equal(Object.hasOwn(mergeTopologyAdapted.nodeMap.get("merged-reed"), "isReed"), false);
assert.equal(mergeTopologyAdapted.nodeMap.get("merged-br").isBorderRouter, true);
assert.equal(mergeTopologyAdapted.nodeMap.get("merged-br").isRouter, true);
assert.equal(mergeTopologyAdapted.edgeData.length, 1);
const enrichedMergeTopology = structuredClone(mergedNativeTopology);
enrichedMergeTopology.topology.nodes[0] = {
  ...enrichedMergeTopology.topology.nodes[0],
  isRouter: false,
  isLeader: false,
  isReed: true,
};
enrichedMergeTopology.topology.nodes[1] = {
  ...enrichedMergeTopology.topology.nodes[1],
  isBorderRouter: true,
  isRouter: true,
  isLeader: false,
  isReed: false,
};
const enrichedMergeTopologyFiles = mergeTopologyEntry.files.map((filename) =>
  filename === "td-ha-matter-ws-network-topology.json"
    ? enrichedMergeTopology
    : null);
const enrichedMergeTopologyAssembly = buildDatasetRows(
  mergeTopologyEntry,
  enrichedMergeTopologyFiles,
);
assert.deepEqual(
  enrichedMergeTopologyAssembly.rows.map((row) => [
    row.id,
    row.isBorderRouter,
    row.isRouter,
    row.isLeader,
    row.isReed,
  ]),
  [
    ["merged-reed", undefined, false, false, true],
    ["merged-br", true, true, false, false],
  ],
);

const oldInventory = buildDatasetRows(
  DATASET_REGISTRY.find((dataset) => dataset.value === "ha_matter_ws_thread_border_routers"),
  [{ borderRouters: [{ extAddressHex: "AABBCCDDEEFF0011" }] }],
);
assert.deepEqual(
  [oldInventory.rows[0].isBorderRouter, oldInventory.rows[0].isRouter],
  [undefined, undefined],
);
const inventoryEntry = DATASET_REGISTRY.find(
  (dataset) => dataset.value === "ha_matter_ws_thread_border_routers",
);
const inventoryRaw = [{
  borderRouters: [{ extAddressHex: "AABBCCDDEEFF0011", isReed: true }],
}];
const inventoryAssembly = buildDatasetRows(inventoryEntry, inventoryRaw);
const inventoryAdapted = runAdaptor({
  entry: inventoryEntry,
  rawFiles: inventoryRaw,
  rows: inventoryAssembly.rows,
  adaptorRows: inventoryAssembly.adaptorRows,
});
const inventoryRecord = [...inventoryAdapted.nodeMap.values()][0];
assert.equal(inventoryRecord.isBorderRouter, true);
assert.equal(inventoryRecord.isRouter, true);
assert.equal(inventoryAdapted.nodeData[0].isBorderRouter, true);
assert.equal(inventoryAdapted.nodeData[0].isReed, true);
assert.equal(isRowVisibleByNodeFilter(
  inventoryAssembly.rows[0],
  "reed-devices",
), true);
assert.equal(
  isNodeVisibleByFilter(
    inventoryAdapted.nodeData[0],
    "reed-devices",
    undefined,
  ),
  true,
);
assert.equal(Object.hasOwn(inventoryRecord, "isLeader"), false);
assert.equal(inventoryRecord.isReed, true);

const dashboardMeshEntry = DATASET_REGISTRY.find(
  (dataset) => dataset.value === "ha_matter_ws_dashboard_mesh_diagnostics",
);
const dashboardMeshRaw = [{
  meshDiagnostics: [{
    matter: { nodeId: 1 },
    thread: { routingRole: "Router", rloc16: "0x1000" },
  }],
  topology: [{
    id: "mesh-placeholder",
    relationshipOnly: true,
    rloc16: "0x1001",
    isRouter: true,
    isLeader: false,
  }],
}];
const dashboardMeshAssembly = buildDatasetRows(dashboardMeshEntry, dashboardMeshRaw);
assert.equal(dashboardMeshAssembly.rows.length, 1);
assert.equal(dashboardMeshAssembly.adaptorRows.length, 2);
const dashboardMeshAdapted = runAdaptor({
  entry: dashboardMeshEntry,
  rawFiles: dashboardMeshRaw,
  rows: dashboardMeshAssembly.rows,
  adaptorRows: dashboardMeshAssembly.adaptorRows,
});
assert.equal(dashboardMeshAdapted.nodeMap.get("mesh-placeholder").relationshipOnly, true);
assert.equal(dashboardMeshAdapted.nodeMap.get("mesh-placeholder").isRouter, true);
assert.equal(dashboardMeshAdapted.nodeMap.get("mesh-placeholder").isLeader, false);

const nonHaLookingRow = buildDatasetRows(entry({
  source: "eve",
  files: ["td-ha-matter-ws-devices-fetch-all.json"],
}), [[{ role: "Router", isReed: true }]]);
assert.equal(Object.hasOwn(nonHaLookingRow.rows[0], "isRouter"), false);
assert.equal(nonHaLookingRow.rows[0].isReed, true);
assert.deepEqual(
  DATASET_REGISTRY
    .filter((entry) => [
      "ha_matter_ws_thread_border_routers",
      "ha_matter_ws_network_topology",
    ].includes(entry.value))
    .map((entry) => [entry.files[0], entry.defaultView, entry.estimateActionCostSecs]),
  [
    ["td-ha-matter-ws-thread-border-routers.json", "table", 10],
    ["td-ha-matter-ws-network-topology.json", "topology", 10],
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