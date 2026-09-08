import assert from "node:assert/strict";

import { canonicalizeExtAddress, isPlaceholderExtAddress } from "../../src/js/tdash-device-fields.js";
import { mergeChildrenArray, mergeRouterNeighbors } from "../../src/js/tdash-merge.js";
import { buildChildRloc16, buildMainRouterRloc16 } from "../../src/js/tdash-topology-utils.js";
import { toFiniteNumber } from "../../src/js/tdash-utils.js";

assert.equal(toFiniteNumber(0), 0);
assert.equal(toFiniteNumber(" 42.5 "), 42.5);
assert.equal(toFiniteNumber("0x10"), 16);
[null, "", "  ", false, [], {}, NaN, Infinity, "Infinity"].forEach((value) => {
  assert.equal(toFiniteNumber(value), undefined);
});
assert.equal(buildMainRouterRloc16(null), "");
assert.equal(buildChildRloc16("0x8c00", null), "");
assert.equal(buildMainRouterRloc16("0x23"), "0x8c00");
assert.equal(buildChildRloc16("0x8c00", "0x31"), "0x8c31");

["0000000000000000", "00:00:00:00:00:00:00:00", "00-00-00-00-00-00-00-00", "00.00.00.00.00.00.00.00", "FOUND-1234", "Offline-1234", "unknown-1234", ""].forEach((value) => {
  assert.equal(isPlaceholderExtAddress(value), true);
});
assert.equal(isPlaceholderExtAddress("00:11:22:33:44:55:66:77"), false);
assert.equal(canonicalizeExtAddress("00:11:22:33:44:55:66:77"), "0011223344556677");
assert.equal(canonicalizeExtAddress("00-11-22-33-44-55-66-77"), "0011223344556677");
assert.equal(canonicalizeExtAddress("00.11.22.33.44.55.66.77"), "0011223344556677");
assert.equal(canonicalizeExtAddress("00:11-22:33-44:55-66:77"), "");
assert.equal(canonicalizeExtAddress("found-1234"), "");

const rlocOnly = { rloc16: "0x8c31", linkMargin: 19 };
const enriched = { rloc16: "0x8c31", extAddress: "0011223344556677", averageRssi: -70 };
for (const [first, second] of [[rlocOnly, enriched], [enriched, rlocOnly]]) {
  const merged = mergeChildrenArray("0x8c00", [first], [second]);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].extAddress, "0011223344556677");
}
const placeholderMerged = mergeRouterNeighbors(
  [{ rloc16: "0x8c31", extAddress: "offline-8c31" }],
  [enriched],
);
assert.equal(placeholderMerged.length, 1);
assert.equal(placeholderMerged[0].extAddress, "0011223344556677");
const conflictTarget = {};
const conflicting = mergeRouterNeighbors(
  [{ rloc16: "0x8c31", extAddress: "0011223344556677" }],
  [{ rloc16: "0x8c31", extAddress: "8899aabbccddeeff" }],
  { conflictTarget, fieldPath: "routerNeighbors" },
);
assert.equal(conflicting.length, 2);
assert.equal(conflictTarget._merge_conflicts.length, 1);
assert.equal(mergeChildrenArray("0x8c00", [{ linkMargin: 2 }], [{ averageRssi: -70 }]).length, 2);

process.stdout.write("phase1 regressions passed\n");