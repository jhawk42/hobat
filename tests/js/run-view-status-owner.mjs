import assert from "node:assert/strict";

import {
  activateViewStatus,
  configureViewStatusPresenter,
  createViewStatusOwner,
  networkInstanceStatus,
  publishViewStatus,
  supersedeViewStatus,
} from "../../src/js/tdash-view-status.js";

const presented = [];
const owner = createViewStatusOwner((status) => presented.push(status));
const firstDataset = {};
const secondDataset = {};
const capabilities = { files: {
  first: { networkInstance: { extPanId: "78b9775b001c1cbe", provenance: "observed" } },
  second: { networkInstance: { extPanId: "1111111111111111", provenance: "operator" } },
} };
assert.equal(networkInstanceStatus(["first"], capabilities), "Network instance: 78b9775b001c1cbe (observed)");
assert.equal(networkInstanceStatus(["second"], capabilities), "Network instance: 1111111111111111 (operator)");
assert.equal(networkInstanceStatus(["first", "second"], capabilities), "Network instance: mixed");
assert.equal(networkInstanceStatus(["missing"], capabilities), "Network instance: unknown");

assert.equal(owner.activate("topology", firstDataset), undefined);
assert.equal(owner.publish("topology", "Showing: 93 nodes, 0 links", firstDataset), true);
assert.equal(presented.at(-1), "Showing: 93 nodes, 0 links");

owner.activate("table", firstDataset);
assert.equal(owner.publish("table", "Total: 93 rows", firstDataset), true);
assert.equal(presented.at(-1), "Total: 93 rows");

assert.equal(owner.publish("topology", "Showing: 93 nodes, stabilized", firstDataset), true);
assert.equal(presented.at(-1), "Total: 93 rows");
assert.equal(owner.activate("topology", firstDataset), "Showing: 93 nodes, stabilized");
assert.equal(presented.at(-1), "Showing: 93 nodes, stabilized");
assert.equal(owner.activate("table", firstDataset), "Total: 93 rows");
assert.equal(presented.at(-1), "Total: 93 rows");

owner.invalidate(secondDataset);
assert.equal(owner.activate("topology", secondDataset), undefined);
assert.equal(owner.publish("topology", "Topology error: invalid data", firstDataset), false);
assert.equal(owner.publish("topology", "Topology error: empty dataset", secondDataset), true);
assert.equal(presented.at(-1), "Topology error: empty dataset");

const singletonPresented = [];
configureViewStatusPresenter((status) => singletonPresented.push(status));
activateViewStatus("table", firstDataset);
publishViewStatus("table", "Total: 93 rows", firstDataset);
supersedeViewStatus("Loading replacement…");
activateViewStatus("table", firstDataset);
assert.deepEqual(singletonPresented, ["Total: 93 rows", "Loading replacement…", "Total: 93 rows"]);

console.log(JSON.stringify({
  presentedCount: presented.length,
  finalStatus: presented.at(-1),
  staleDatasetRejected: true,
  transientOverrideRestored: true,
}));