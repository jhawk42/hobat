import assert from "node:assert/strict";

import { buildThreadNetworkModel } from "../../src/js/tdash-thread-network.js";
import { DATASET_REGISTRY } from "../../src/js/tdash-dataset-registry.js";

const filename = "network.json";
const dataset = {
  entry: { label: "Thread snapshot", files: [filename] },
  loadedFiles: [filename],
  rawFiles: [{
    networkName: "house-thread",
    prefixOmrIpv6AddrPrefix: "fd00:abcd::/64",
    meshLocalPrefix: "fd00:1234::/64",
    channel: 15,
  }],
  rows: [
    { isBorderRouter: true, isRouter: true, isLeader: true, extAddress: "0011223344556677", rloc16: "0x0400", role: "router", deviceLabel: "Leader", threadVersion: "1.3", threadStackVersion: "OPENTHREAD/2024-01-01" },
    { isRouter: true, isPrimaryBBR: true, rloc16: "0x0800", role: "router", extAddress: "8899aabbccddeeff", deviceLabel: "Backbone", threadVersion: "1.3" },
    { isRouterEligible: true, role: "child", mode: { device: "FTD" }, rloc16: "0x0801" },
    { role: "child", mode: { device: "MTD" }, rloc16: "0x0802" },
    { extAddress: "aaaaaaaaaaaaaaaa" },
  ],
};
const capabilities = { files: {
  [filename]: { networkInstance: { extPanId: "78b9775b001c1cbe", provenance: "observed" } },
} };
const adaptorResult = {
  edgeData: [
    { from: "a", to: "b", lqLevel: 3 },
    { from: "b", to: "a", lqLevel: 3 },
    { from: "b", to: "c", lqLevel: 2 },
    { from: "c", to: "b", lqLevel: 1 },
  ],
  relationshipCapabilities: { datasetWide: new Set(["children"]), byDeviceId: new Map() },
};

const model = buildThreadNetworkModel(dataset, capabilities, adaptorResult);
assert.equal(model.loaded, true);
assert.equal(model.datasetLabel, "Thread snapshot");
assert.deepEqual(model.networkFacts.map(({ value }) => value), [
  "house-thread", "78b9775b001c1cbe", "fd00:abcd::/64", "fd00:1234::/64", "15",
]);
assert.deepEqual(model.deviceCounts, {
  total: 4, borderRouters: 1, routers: 1, reed: 1, endDevices: 1,
});
assert.equal(model.roleHolders.leaders.length, 1);
assert.equal(model.roleHolders.primaryBbrs.length, 1);
assert.equal(model.roleHolders.leaders[0].threadStackVersion, "OPENTHREAD/2024-01-01");
assert.equal(model.links.total, 2);
assert.equal(model.links.lqi[3].count, 1);
assert.equal(model.links.lqi[3].percent, 50);
assert.equal(model.links.lqi[2].count, 0);
assert.equal(model.links.lqi[1].count, 0);

const sidebarCounts = buildThreadNetworkModel(dataset, capabilities, adaptorResult, {
  devices: 64, borderRouters: 6, routers: 13, children: 45,
  links: 408, lq3: 163, lq2: 36, lq1: 175,
});
assert.deepEqual(sidebarCounts.deviceCounts, {
  total: 64, borderRouters: 6, routers: 13, reed: 1, endDevices: 45,
});
assert.equal(sidebarCounts.links.total, 408);
assert.equal(sidebarCounts.links.lqi[3].percent, 40);

const auxiliaryNetworkInfo = buildThreadNetworkModel({
  ...dataset,
  auxiliaryFiles: {
    "td-otbr-cli-thread-network-info.json": {
      networkName: "house-thread",
      extPanId: "78b9775b001c1cbe",
      prefixOmrIpv6AddrPrefix: "fd00:abcd::/64",
      prefixMeshLocalIpv6AddrPrefix: "fd00:1234::/64",
      channel: 15,
    },
  },
}, {
  files: {
    ...capabilities.files,
    "td-otbr-cli-thread-network-info.json": {
      networkInstance: { extPanId: "78b9775b001c1cbe", provenance: "observed" },
    },
  },
}, adaptorResult, {
  devices: 64, borderRouters: 6, routers: 13, children: 45,
  links: 408, lq3: 163, lq2: 36, lq1: 175,
});
assert.deepEqual(auxiliaryNetworkInfo.networkFacts.map(({ value }) => value), [
  "house-thread", "78b9775b001c1cbe", "fd00:abcd::/64", "fd00:1234::/64", "15",
]);

const restDataset = {
  entry: { label: "OTBR REST devices", files: ["td-otbr-restapi-devices-list.json"] },
  loadedFiles: ["td-otbr-restapi-devices-list.json"],
  rawFiles: [[]],
  auxiliaryFiles: {
    "td-otbr-restapi-dataset-active.json": {
      networkName: "rest-thread",
      extPanId: "78b9775b001c1cbe",
      meshLocalPrefix: "fd3b:a255:4aa6:5483::/64",
      channel: 25,
    },
  },
  rows: dataset.rows,
};
const restNetworkInfo = buildThreadNetworkModel(restDataset, {
  files: {
    "td-otbr-restapi-dataset-active.json": {
      networkInstance: { extPanId: "78b9775b001c1cbe", provenance: "observed" },
    },
  },
}, adaptorResult, {
  devices: 64, borderRouters: 6, routers: 13, children: 45,
  links: 408, lq3: 163, lq2: 36, lq1: 175,
});
assert.deepEqual(restNetworkInfo.networkFacts.map(({ value }) => value), [
  "rest-thread", "78b9775b001c1cbe", "n/a", "fd3b:a255:4aa6:5483::/64", "25",
]);

const unavailable = buildThreadNetworkModel({
  entry: { label: "Partial", files: [filename] },
  loadedFiles: [filename],
  rawFiles: [{}],
  rows: [{ threadVersion: "1.3", role: "child", mode: { device: "FTD" } }],
}, { files: {} }, { edgeData: [], relationshipCapabilities: { datasetWide: new Set(), byDeviceId: new Map() } });
assert.equal(unavailable.networkFacts[1].value, "n/a");
assert.equal(unavailable.deviceCounts.total, 1);
assert.equal(unavailable.deviceCounts.reed, 1);
assert.equal(unavailable.links.total, "n/a");
const missingSidebarCounts = buildThreadNetworkModel(dataset, capabilities, adaptorResult, {
  devices: null, borderRouters: null, routers: null, children: null,
  links: null, lq3: null, lq2: null, lq1: null,
});
assert.equal(missingSidebarCounts.deviceCounts.total, "n/a");
assert.equal(missingSidebarCounts.links.total, "n/a");
assert.equal(unavailable.roleHolders.leaders.length, 0);

const declaredThreadCollection = buildThreadNetworkModel({
  entry: { label: "Thread tools", source: "thread-tools", files: ["diagnostics.json"] },
  loadedFiles: ["diagnostics.json"],
  rawFiles: [[]],
  rows: [{ extAddress: "0011223344556677" }],
}, { files: {} }, null);
assert.equal(declaredThreadCollection.deviceCounts.total, 1);

const mixedSource = buildThreadNetworkModel({
  entry: {
    label: "Mixed Thread and mDNS",
    source: "merged",
    files: ["td-otbr-cli-meshdiag-topology.json", "td-mdns-scopes-thread.json"],
  },
  loadedFiles: ["td-otbr-cli-meshdiag-topology.json", "td-mdns-scopes-thread.json"],
  rawFiles: [[], []],
  rows: [{ extAddress: "0011223344556677", _source_files: ["td-mdns-scopes-thread.json"] }],
}, { files: {} }, null);
assert.equal(mixedSource.deviceCounts.total, "n/a");

const explicitRouterFalse = buildThreadNetworkModel({
  entry: { label: "Explicit role", source: "otbr-cli", files: [filename] },
  loadedFiles: [filename],
  rawFiles: [[]],
  rows: [{ isRouter: false, role: "router", rloc16: "0x0400" }],
}, { files: {} }, null);
assert.equal(explicitRouterFalse.deviceCounts.total, 1);
assert.equal(explicitRouterFalse.deviceCounts.routers, "n/a");

const partitionDataset = {
  entry: { label: "Partition snapshot", source: "otbr-cli", files: [filename] },
  loadedFiles: [filename],
  rawFiles: [[]],
  rows: [
    { extAddress: "0011223344556677", role: "router", leaderData: { partitionId: 0x20 }, _source_files: [filename] },
    { extAddress: "0011223344556677", role: "router", leaderData: { partitionId: "0x00000020" }, _source_files: [filename] },
    { extAddress: "8899aabbccddeeff", role: "child", leaderData: { partitionId: 5 }, _source_files: [filename] },
    { extAddress: "aaaaaaaaaaaaaaaa", role: "child", leaderData: { partitionId: 5 }, _source_files: [filename] },
    { extAddress: "bbbbbbbbbbbbbbbb", role: "child" },
    { role: "child", leaderData: { partitionId: 9 } },
  ],
};
const partitionCapabilities = {
  files: { [filename]: { networkInstance: { extPanId: "78b9775b001c1cbe", provenance: "observed" } } },
};
const partitions = buildThreadNetworkModel(
  partitionDataset, partitionCapabilities, adaptorResult,
);
assert.equal(partitions.partitions.state, "partial");
assert.deepEqual(partitions.partitions.partitions, [
  { partitionId: "0x00000005", count: 2, sourceFiles: [filename] },
  { partitionId: "0x00000020", count: 1, sourceFiles: [filename] },
]);
assert.equal(partitions.partitions.totalDeviceCount, 4);
assert.equal(partitions.partitions.assignedDeviceCount, 3);
assert.equal(partitions.partitions.missingDeviceCount, 1);
assert.equal(partitions.partitions.unidentifiedClaimCount, 1);
assert.equal(partitions.deviceCounts.total, 6);

const conflictingPartitions = buildThreadNetworkModel({
  ...partitionDataset,
  rows: [
    { extAddress: "0011223344556677", role: "router", leaderData: { partitionId: 2 } },
    { extAddress: "0011223344556677", role: "router", leaderData: { partitionId: 3 } },
    { extAddress: "8899aabbccddeeff", role: "child", leaderData: { partitionId: -1 } },
  ],
}, partitionCapabilities, adaptorResult);
assert.equal(conflictingPartitions.partitions.state, "conflicting");
assert.deepEqual(conflictingPartitions.partitions.partitions, []);
assert.equal(conflictingPartitions.partitions.conflictingDeviceCount, 1);
assert.equal(conflictingPartitions.partitions.invalidDeviceCount, 1);

const onePartition = buildThreadNetworkModel({
  ...partitionDataset,
  rows: [
    { extAddress: "0011223344556677", role: "router", leaderData: { partitionId: 7 } },
    { extAddress: "8899aabbccddeeff", role: "child", leaderData: { partitionId: 7 } },
  ],
}, partitionCapabilities, adaptorResult);
assert.equal(onePartition.partitions.state, "supported");
assert.deepEqual(onePartition.partitions.partitions, [
  { partitionId: "0x00000007", count: 2, sourceFiles: [] },
]);

const partialPartitions = buildThreadNetworkModel({
  ...partitionDataset,
  isPartial: true,
  rows: [{ extAddress: "0011223344556677", role: "router", leaderData: { partitionId: 7 } }],
}, partitionCapabilities, adaptorResult);
assert.equal(partialPartitions.partitions.state, "partial");

const unresolvedPartitionScope = buildThreadNetworkModel({
  ...partitionDataset,
  rows: [{ extAddress: "0011223344556677", role: "router", leaderData: { partitionId: 7 } }],
}, { files: {} }, adaptorResult);
assert.equal(unresolvedPartitionScope.partitions.state, "unresolved-scope");
assert.deepEqual(unresolvedPartitionScope.partitions.partitions, []);

const notLoaded = buildThreadNetworkModel(null, {}, null);
assert.equal(notLoaded.loaded, false);
assert.ok(notLoaded.networkFacts.every(({ value }) => value === "n/a"));
assert.equal(notLoaded.partitions.state, "unresolved-scope");

const otbrCliEntry = DATASET_REGISTRY.find(
  (entry) => entry.value === "otbr_cli_networkdiag_fetch_all",
);
const otbrRoleRows = [
  { extAddress: "0011223344556677", role: "child", mode: { device: "FTD" }, isReed: true },
  { extAddress: "8899aabbccddeeff", role: "child", mode: { device: "FTD" }, isReed: false },
];
const otbrThreadDataset = {
  entry: otbrCliEntry,
  loadedFiles: [...otbrCliEntry.files],
  rawFiles: [[]],
  rows: otbrRoleRows,
};
const otbrThreadCounts = buildThreadNetworkModel(
  otbrThreadDataset,
  { files: {} },
  adaptorResult,
  { devices: 2, borderRouters: 0, routers: 0, children: 2 },
);
assert.deepEqual(otbrThreadCounts.deviceCounts, {
  total: 2, borderRouters: 0, routers: 0, reed: 1, endDevices: 2,
});
const otbrLegacyCache = buildThreadNetworkModel(
  {
    ...otbrThreadDataset,
    rows: otbrRoleRows.map(({ isReed, ...row }) => row),
  },
  { files: {} },
  adaptorResult,
  { devices: 2, borderRouters: 0, routers: 0, children: 2 },
);
assert.equal(otbrLegacyCache.deviceCounts.reed, 2);
const legacyReedHeuristic = buildThreadNetworkModel({
  entry: { label: "Legacy OTBR", source: "otbr-cli", files: [filename] },
  loadedFiles: [filename],
  rawFiles: [[]],
  rows: [{ role: "child", mode: { device: "FTD" }, isRouterEligible: true }],
}, { files: {} }, adaptorResult);
assert.equal(legacyReedHeuristic.deviceCounts.reed, 1);
const routerEligibilityOnly = buildThreadNetworkModel({
  entry: { label: "Legacy eligibility only", source: "otbr-cli", files: [filename] },
  loadedFiles: [filename],
  rawFiles: [[]],
  rows: [{ role: "router", mode: { device: "FTD" }, isRouterEligible: true }],
}, { files: {} }, adaptorResult);
assert.equal(routerEligibilityOnly.deviceCounts.reed, 0);

console.log(JSON.stringify({ uniqueLinks: model.links.total, threadDevices: model.deviceCounts.total }));