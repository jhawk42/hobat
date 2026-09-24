import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { DATASET_REGISTRY } from "../../src/js/tdash-dataset-registry.js";
import { buildDatasetRows } from "../../src/js/tdash-dataset.js";
import { buildDeviceProjection, buildDeviceProjections } from "../../src/js/tdash-device-projection.js";
import { computeTableCapabilities } from "../../src/js/tdash-filters.js";

let checked = 0;
for (const entry of DATASET_REGISTRY) {
  const files = entry.files.map((filename) => {
    const file = path.join("data", filename);
    return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : null;
  });
  const { rows, loadedFiles } = buildDatasetRows(entry, files);
  if (!loadedFiles.length) continue;
  const projections = rows.map((row, index) => buildDeviceProjection(row, index));
  const { edgeCategories, ...expected } = computeTableCapabilities(rows);
  const actual = Object.fromEntries(Object.keys(expected).map((key) => [
    key, projections.some((projection) => projection.diagnostics[key]),
  ]));
  assert.deepEqual(actual, expected, entry.value);
  assert.doesNotThrow(() => JSON.stringify([...buildDeviceProjections(rows).values()]));
  checked += 1;
}
assert.ok(checked > 0);
const explicit = buildDeviceProjection({
  extAddress: "aaaaaaaaaaaaaaaa", rloc16: "0x1001", isRouter: true, role: "leader",
  routerNeighbors: [{ err_rate_frame_pct: 12, err_rate_msg_pct: 3, rss_ave: -75,
    rss_margin: 19, q_msg: 2, lq: 3 }],
});
assert.equal(explicit.isRouter, true);
assert.equal(explicit.isLeader, true);
assert.equal(explicit.roleEvidence, "explicit");
assert.equal(explicit.relationships.routerNeighbors, 1);
assert.deepEqual(explicit.metrics.routerNeighbors, {
  frameErrorRate: [12], messageErrorRate: [3], averageRssi: [-75],
  linkMargin: [19], queuedMessageCount: [2], linkQuality: [3],
});
assert.equal(buildDeviceProjection({ rloc16: "0x1000" }).roleEvidence, "rloc16-derived");
assert.equal(buildDeviceProjection({ rloc16: "0x1001", isRouter: false }).isRouter, false);
assert.equal(buildDeviceProjections([{ rloc16: "0x1000" }, { rloc16: "0x1000" }]).size, 2);
console.log(JSON.stringify({ checked }));