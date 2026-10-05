import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { DATASET_REGISTRY } from "../../src/js/tdash-dataset-registry.js";
import { buildDatasetRows } from "../../src/js/tdash-dataset.js";
import { buildDeviceProjection, buildDeviceProjections } from "../../src/js/tdash-device-projection.js";
import {
  computeTopologyCapabilities,
  isNodeVisibleByFilter,
  isRowVisibleByNodeFilter,
  scanTableCapabilities,
} from "../../src/js/tdash-filters.js";
import { HA_MATTER_ROLE_POLICY } from "../../src/js/tdash-ha-matter-ws-roles.js";

let checked = 0;
for (const entry of DATASET_REGISTRY) {
  const files = entry.files.map((filename) => {
    const file = path.join("data", filename);
    return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : null;
  });
  const { rows, loadedFiles } = buildDatasetRows(entry, files);
  if (!loadedFiles.length) continue;
  const projections = buildDeviceProjections(rows);
  const projectionValues = [...projections.values()];
  const { edgeCategories, ...expected } = scanTableCapabilities(rows);
  const actual = Object.fromEntries(Object.keys(expected).map((key) => [
    key, projectionValues.some((projection) => projection.diagnostics[key] === true),
  ]));
  assert.deepEqual(actual, expected, entry.value);
  assert.doesNotThrow(() => JSON.stringify(projectionValues));
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
const childFtd = buildDeviceProjection({
  rloc16: "0x1001", role: "child", mode: { device: "FTD", fullThreadDevice: true },
});
const childMtd = buildDeviceProjection({
  rloc16: "0x1002", role: "child", mode: { device: "MTD", fullThreadDevice: false },
});
const routerFtd = buildDeviceProjection({
  rloc16: "0x1000", role: "router", mode: { device: "FTD", fullThreadDevice: true },
});
const unknownChild = buildDeviceProjection({ rloc16: "0x1003", role: "child" });
assert.equal(childFtd.deviceType, "FTD");
assert.equal(childFtd.isReed, true);
assert.equal(childFtd.isRouter, false);
assert.equal(childFtd.isBorderRouter, false);
assert.equal(childMtd.isReed, false);
assert.equal(childMtd.isRouter, false);
assert.equal(routerFtd.isReed, false);
assert.equal(routerFtd.isRouter, true);
assert.equal(unknownChild.isReed, false);
assert.equal(unknownChild.isRouter, false);
const haMatterReed = buildDeviceProjection({
  role: "Router",
  isRouter: false,
  isLeader: false,
  isReed: true,
  rloc16: "0x1000",
}, 0, { rolePolicy: HA_MATTER_ROLE_POLICY });
assert.equal(haMatterReed.isRouter, false);
assert.equal(haMatterReed.isLeader, false);
assert.equal(haMatterReed.isReed, true);
assert.equal(haMatterReed.deviceType, "unknown");
assert.equal(
  isRowVisibleByNodeFilter(
    { role: "Router", isRouter: false, isReed: true, rloc16: "0x1000" },
    "reed-devices",
    HA_MATTER_ROLE_POLICY,
  ),
  true,
);
assert.equal(
  isRowVisibleByNodeFilter(
    { role: "Router", isRouter: false, isReed: true, rloc16: "0x1000" },
    "main-routers",
    HA_MATTER_ROLE_POLICY,
  ),
  false,
);
const haMatterUnknown = buildDeviceProjection({
  role: "Router",
  rloc16: "0x1000",
  mode: { device: "FTD", fullThreadDevice: true },
}, 0, { rolePolicy: HA_MATTER_ROLE_POLICY });
assert.equal(haMatterUnknown.isRouter, false);
assert.equal(haMatterUnknown.isReed, false);
assert.equal(haMatterUnknown.roleEvidence, "none");
assert.equal(
  isNodeVisibleByFilter(
    { mode_device: "FTD", role: "child", isRouter: false },
    "reed-devices",
    undefined,
    HA_MATTER_ROLE_POLICY,
  ),
  false,
);
assert.equal(
  isNodeVisibleByFilter(
    { mode_device: "FTD", role: "Router", isReed: true },
    "reed-devices",
    undefined,
    HA_MATTER_ROLE_POLICY,
  ),
  true,
);
assert.equal(
  computeTopologyCapabilities(
    [{ mode_device: "FTD", role: "child", isRouter: false, isBorderRouter: false }],
    [],
    { rolePolicy: HA_MATTER_ROLE_POLICY },
  ).hasReedNodes,
  false,
);
assert.equal(
  computeTopologyCapabilities(
    [{ mode_device: "FTD", role: "child", isRouter: false, isBorderRouter: false }],
    [],
  ).hasReedNodes,
  true,
);
console.log(JSON.stringify({ checked }));