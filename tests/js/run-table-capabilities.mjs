import assert from "node:assert/strict";

import { scanTableCapabilities } from "../../src/js/tdash-filters.js";

const keys = [
  "hasFtdNodes",
  "hasMtdNodes",
  "hasReedNodes",
  "hasRouters",
  "hasBorderRouters",
  "hasRoutersWithChildren",
  "hasRoutersWithoutChildren",
  "edgeCategories",
  "hasFieldMacTotalErrorsPct",
  "hasFieldMacDiscardPct",
  "hasFieldPartitionChanges",
  "hasFieldParentChanges",
  "hasNeighborFrameErrRate",
  "hasNeighborMsgErrRate",
  "hasNeighborRss",
  "hasLinkQualityDistribution",
  "hasChildLinkQuality",
  "hasChildFrameErrRate",
  "hasChildMsgErrRate",
  "hasChildRss",
  "hasChildRssMargin",
  "hasChildQueuedMsgs",
  "hasFieldMacTotalErrorsRatio",
  "hasFieldMacTotalDiscardsRatio",
  "hasFieldBetterPartitionAttach",
  "hasFieldTotalParentPartitionChanges",
  "hasFieldRouterPct",
  "hasFieldDetachedDisabledPct",
];
const flagKeys = keys.filter((key) => key !== "edgeCategories");
let checked = 0;

function expectedCapabilities(enabled) {
  return Object.fromEntries(keys.map((key) => [
    key, key === "edgeCategories" ? new Set() : enabled.includes(key),
  ]));
}

function freezeDeep(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freezeDeep);
    Object.freeze(value);
  }
  return value;
}

function check(rows, enabled = []) {
  const before = structuredClone(rows);
  freezeDeep(rows);
  const actual = scanTableCapabilities(rows);
  assert.deepEqual(actual, expectedCapabilities(enabled));
  assert.deepEqual(Object.keys(actual), keys);
  assert.equal(Object.keys(actual)[7], "edgeCategories");
  assert.deepEqual(rows, before);
  checked += 1;
  return actual;
}

function atPath(path, value) {
  return path.split(".").reduceRight((nested, key) => ({ [key]: nested }), value);
}

check([]);
check([{}, { children: [], routerNeighbors: [], childTable: [] }]);
for (const mode of ["FTD", "ftd", " FTD "]) {
  check([{ mode: { device: mode } }], ["hasFtdNodes", "hasReedNodes"]);
}
check([{ "mode.device": "mtd" }], ["hasMtdNodes"]);
check([{ mode: { device: "unknown" } }]);
check([{ mode: { device: "MTD" }, role: "child" }], ["hasMtdNodes"]);
for (const role of [" child ", "CHILD"]) {
  check([{ mode: { device: "FTD" }, role, rloc16: "0x1200", isBorderRouter: true }],
    ["hasFtdNodes", "hasReedNodes", "hasRouters", "hasBorderRouters", "hasRoutersWithoutChildren"]);
}
for (const role of ["router", "leader", "reed", "sleepy-child"]) {
  check([{ mode: { device: "FTD" }, role }], ["hasFtdNodes"]);
}
check([{ mode: { device: "FTD" }, rloc16: "0x1200" }],
  ["hasFtdNodes", "hasRouters", "hasRoutersWithoutChildren"]);
check([{ mode: { device: "FTD" }, isBorderRouter: true }],
  ["hasFtdNodes", "hasBorderRouters"]);
for (const field of ["rloc16", "RLOC16"]) {
  for (const value of ["0x1200", "0XAB00", "0xzz00"]) {
    check([{ [field]: value }], ["hasRouters", "hasRoutersWithoutChildren"]);
  }
}
for (const rloc16 of ["1200", "0x1201", "0x100", "0x12300", "", null]) {
  check([{ rloc16, isRouter: true, role: "router" }]);
}
for (const field of ["isBorderRouter", "is_border_router", "br"]) {
  for (const value of [true, "true", " TRUE "]) {
    check([{ [field]: value }], ["hasBorderRouters"]);
  }
  for (const value of [false, "false", 1, "1", "yes", null]) {
    check([{ [field]: value }]);
  }
}
for (const field of ["totalChildren", "total_children"]) {
  for (const value of [1, "2"]) {
    check([{ rloc16: "0x1200", [field]: value }],
      ["hasRouters", "hasRoutersWithChildren"]);
    check([{ [field]: value }]);
  }
  for (const value of [0, "0", -1, true, "", null, Infinity]) {
    check([{ rloc16: "0x1200", [field]: value }],
      ["hasRouters", "hasRoutersWithoutChildren"]);
  }
}
check([{ rloc16: "0x1200", totalChildren: 0, children: [{}] }],
  ["hasRouters", "hasRoutersWithChildren"]);
check([{ rloc16: "0x1200", children: { length: 1 } }],
  ["hasRouters", "hasRoutersWithoutChildren"]);

const scalarCases = [
  ["hasFieldMacTotalErrorsPct", ["macCounters.ifinerrors_pct", "mac_counters.ifinerrors_pct", "macCounters.ifouterrors_pct", "mac_counters.ifouterrors_pct"]],
  ["hasFieldMacDiscardPct", ["macCounters.ifindiscards_pct", "mac_counters.ifindiscards_pct"]],
  ["hasFieldPartitionChanges", ["mleCounters.partIdChangesCount", "mle_counters.partitionidchanges"]],
  ["hasFieldParentChanges", ["mleCounters.newParentCount", "mle_counters.parentchanges"]],
  ["hasFieldMacTotalErrorsRatio", ["macCounters.ifTotalErrorsTotalPktsRatio", "mac_counters.ifTotalErrorsTotalPktsRatio"]],
  ["hasFieldMacTotalDiscardsRatio", ["macCounters.ifTotalDiscardsTotalPktsRatio", "mac_counters.ifTotalDiscardsTotalPktsRatio"]],
  ["hasFieldBetterPartitionAttach", ["mleCounters.betterPartIdAttachAttemptsCount", "mle_counters.betterPartIdAttachAttemptsCount"]],
  ["hasFieldTotalParentPartitionChanges", ["mleCounters.totalParentPartitionChangesCount", "mle_counters.totalParentPartitionChangesCount"]],
  ["hasFieldRouterPct", ["timeStatistics.routerPct", "time_statistics.routerPct"]],
  ["hasFieldDetachedDisabledPct", ["timeStatistics.detachedDisabledPct", "time_statistics.detachedDisabledPct"]],
];
const invalidNumbers = [undefined, null, "", " ", "bad", "Infinity", Infinity, NaN, true, false, {}, []];
for (const [key, paths] of scalarCases) {
  for (const path of paths) {
    for (const value of [0, "0", -2, " 3.5 "]) {
      check([atPath(path, value)], [key]);
    }
    for (const value of invalidNumbers) check([atPath(path, value)]);
  }
}
for (const [key, path] of [
  ["hasFieldPartitionChanges", "mleCounters.partitionIdChanges"],
  ["hasFieldParentChanges", "mleCounters.parentChanges"],
  ["hasFieldBetterPartitionAttach", "mleCounters.betterPartitionAttachAttempts"],
]) {
  check([{ [path]: "0" }], [key]);
}
for (const [canonical, legacy, key] of [
  ["partIdChangesCount", "partitionidchanges", "hasFieldPartitionChanges"],
  ["newParentCount", "parentchanges", "hasFieldParentChanges"],
]) {
  for (const value of [null, undefined]) {
    check([{ mleCounters: { [canonical]: value, [legacy]: 0 } }], [key]);
  }
  for (const value of ["", "bad", false]) {
    check([{ mleCounters: { [canonical]: value, [legacy]: 0 } }]);
  }
}
for (const linksField of ["links3", "3_links"]) {
  for (const totalField of ["totalLinks", "total_links"]) {
    check([{ [linksField]: "0", [totalField]: 0 }], ["hasLinkQualityDistribution"]);
    for (const value of invalidNumbers) {
      check([{ [linksField]: value, [totalField]: 0 }]);
      check([{ [linksField]: 0, [totalField]: value }]);
    }
  }
}
for (const collection of ["routerNeighbors", "router_neighbor_table", "childTable", "router_child_table"]) {
  const neighbor = collection.startsWith("routerN") || collection === "router_neighbor_table";
  const metrics = neighbor ? [
    ["frameErrorRate", "hasNeighborFrameErrRate"],
    ["messageErrorRate", "hasNeighborMsgErrRate"],
    ["averageRssi", "hasNeighborRss"],
  ] : [
    ["frameErrorRate", "hasChildFrameErrRate"],
    ["messageErrorRate", "hasChildMsgErrRate"],
    ["averageRssi", "hasChildRss"],
    ["linkMargin", "hasChildRssMargin"],
  ];
  for (const [field, key] of metrics) {
    for (const value of [0, "0", -3, " 2.5 "]) {
      check([{ [collection]: [null, {}, { [field]: value }] }], [key]);
    }
    for (const value of invalidNumbers) check([{ [collection]: [{ [field]: value }] }]);
  }
  for (const value of [null, {}, "bad", 1]) check([{ [collection]: value }]);
  // The legacy scan reads nested metrics directly, not through field aliases.
  check([{ [collection]: [{ err_rate_frame_pct: 1, err_rate_msg_pct: 1, rss_ave: -40, rss_margin: 2, q_msg: 1 }] }]);
}
for (const collection of ["childTable", "router_child_table"]) {
  for (const value of [1, "1", 0.1]) {
    check([{ [collection]: [{ queuedMessageCount: value }] }], ["hasChildQueuedMsgs"]);
  }
  for (const value of [0, "0", -1, ...invalidNumbers]) {
    check([{ [collection]: [{ queuedMessageCount: value }] }]);
  }
}
for (const field of ["lq", "linkQuality"]) {
  for (const value of [0, "0", -1, "2junk", 2.9]) {
    check([{ children: [null, {}, { [field]: value }] }], ["hasChildLinkQuality"]);
  }
  for (const value of invalidNumbers) check([{ children: [{ [field]: value }] }]);
}
check([{ children: [{ lq: undefined, linkQuality: "2" }] }], ["hasChildLinkQuality"]);
check([{ children: [{ lq: null, linkQuality: "2" }] }]);
check([{ children: [{ lq: "bad", linkQuality: "2" }] }]);
check([{ childTable: [{ lq: 2 }], children: [{ link_quality: 2 }] }]);

const fullRows = [
  {
    mode: { device: "FTD" }, role: "child", rloc16: "0x1200", isBorderRouter: true,
    totalChildren: 1,
    macCounters: { ifinerrors_pct: 0, ifindiscards_pct: 0, ifTotalErrorsTotalPktsRatio: 0, ifTotalDiscardsTotalPktsRatio: 0 },
    mleCounters: { partIdChangesCount: 0, newParentCount: 0, betterPartIdAttachAttemptsCount: 0, totalParentPartitionChangesCount: 0 },
    routerNeighbors: [{ frameErrorRate: 0, messageErrorRate: 0, averageRssi: -40 }],
    children: [{ lq: 0 }],
    childTable: [{ frameErrorRate: 0, messageErrorRate: 0, averageRssi: -40, linkMargin: 0, queuedMessageCount: 1 }],
    links3: 0, totalLinks: 0, timeStatistics: { routerPct: 0, detachedDisabledPct: 0 },
  },
  { mode: { device: "MTD" }, rloc16: "0x3400" },
];
const full = check(fullRows, flagKeys);
check([...fullRows, {}], flagKeys);
const emptyA = check([]);
const emptyB = check([]);
assert.notEqual(emptyA.edgeCategories, emptyB.edgeCategories);
assert.notEqual(full.edgeCategories, emptyA.edgeCategories);
full.edgeCategories.add("test-only");
emptyA.edgeCategories.add("also-test-only");
assert.deepEqual(emptyB.edgeCategories, new Set());
check(fullRows, flagKeys);
check([]);

const visits = [];
function watchedRecord(label, fields) {
  return Object.defineProperties({}, Object.fromEntries(fields.map((field) => [
    field, { enumerable: true, get() { visits.push(`${label}.${field}`); return 0; } },
  ])));
}
const laterRow = {
  get mode() { visits.push("row.mode"); return { device: "MTD" }; },
  routerNeighbors: [watchedRecord("neighbor-1", ["frameErrorRate", "messageErrorRate", "averageRssi"]),
    watchedRecord("neighbor-2", ["frameErrorRate", "messageErrorRate", "averageRssi"])],
  children: [watchedRecord("child-1", ["lq"]), watchedRecord("child-2", ["lq"])],
  childTable: [watchedRecord("table-1", ["frameErrorRate", "messageErrorRate", "averageRssi", "linkMargin", "queuedMessageCount"]),
    watchedRecord("table-2", ["frameErrorRate", "messageErrorRate", "averageRssi", "linkMargin", "queuedMessageCount"])],
};
assert.deepEqual(scanTableCapabilities([...fullRows, laterRow]), expectedCapabilities(flagKeys));
assert.deepEqual(visits, [
  "row.mode",
  "neighbor-1.frameErrorRate", "neighbor-1.messageErrorRate", "neighbor-1.averageRssi",
  "neighbor-2.frameErrorRate", "neighbor-2.messageErrorRate", "neighbor-2.averageRssi",
  "child-1.lq", "child-1.lq", "child-2.lq", "child-2.lq",
  "table-1.frameErrorRate", "table-1.messageErrorRate", "table-1.averageRssi", "table-1.linkMargin", "table-1.queuedMessageCount",
  "table-2.frameErrorRate", "table-2.messageErrorRate", "table-2.averageRssi", "table-2.linkMargin", "table-2.queuedMessageCount",
]);

console.log(JSON.stringify({ checked, flagCount: flagKeys.length, traversalReads: visits.length }));
