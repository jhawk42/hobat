import assert from "node:assert/strict";
import fs from "node:fs";
import { buildDatasetRows } from "../../src/js/tdash-dataset.js";
import { runAdaptor } from "../../src/js/tdash-adaptors.js";
import { buildDeviceProjections } from "../../src/js/tdash-device-projection.js";
import { computeTopologyCapabilities } from "../../src/js/tdash-filters.js";
import {
  createTopologyViewModel, createTopologyFilterState, computeTopologyVisibility,
  resolveTopologyNodeId,
} from "../../src/js/tdash-topology-view-model.js";

const fixture = JSON.parse(fs.readFileSync(
  process.argv[2] ?? new URL("../fixtures/js_view_semantics.json", import.meta.url), "utf8",
));
const sorted = (values) => [...values].sort();
const section = process.argv[3] ?? "all";
const {rows, loadedFiles} = buildDatasetRows(fixture.entry, [fixture.rows]);
assert.equal(rows.length, fixture.expected.rowCount);
assert.deepEqual(loadedFiles, ["fixture.json"]);
const adapted = runAdaptor({entry: fixture.entry, rows, rawFiles: [fixture.rows]});
const model = createTopologyViewModel(adapted, buildDeviceProjections(rows));
assert.deepEqual(sorted(model.nodes.map(node => node.id)), fixture.expected.nodeIds);
assert.deepEqual(sorted(model.edges.map(edge => edge.id)), fixture.expected.edgeIds);
const flags = computeTopologyCapabilities(adapted.nodeData, adapted.edgeData);
if (["all", "capabilities"].includes(section)) {
  assert.deepEqual(Object.fromEntries(Object.keys(fixture.expected.flags)
    .map(key => [key, flags[key]])), fixture.expected.flags);
}
if (["all", "visibility"].includes(section)) {
  const actual = fixture.expected.visibility.map(test => {
    const result = computeTopologyVisibility(model,
      createTopologyFilterState(test.node, test.link, test.diagnostic));
    return {...test, nodes: sorted(result.visibleNodeIds), edges: sorted(result.visibleEdgeIds)};
  });
  assert.deepEqual(actual, fixture.expected.visibility);
}
const baseline = () => computeTopologyVisibility(model,
  createTopologyFilterState("all", "all_links", "all"));
assert.deepEqual(sorted(baseline().visibleNodeIds), fixture.expected.nodeIds);
assert.deepEqual(sorted(baseline().visibleEdgeIds), fixture.expected.edgeIds);
assert.equal(baseline().visibleNodeCount, fixture.expected.rowCount);
assert.equal(baseline().visibleEdgeCount, fixture.expected.edgeIds.length);

const collisionRows = ["scope-a", "scope-b"].map(_unifiedRecordId => ({
  _unifiedRecordId, _networkInstance: _unifiedRecordId,
  extAddress: "1111111111111111", role: "router", isRouter: true,
}));
const collision = createTopologyViewModel(runAdaptor({
  entry: fixture.entry, rows: collisionRows, rawFiles: [collisionRows],
}), buildDeviceProjections(collisionRows));
assert.deepEqual(sorted(collision.nodes.map(node => node.id)), ["scope-a", "scope-b"]);
assert.equal(resolveTopologyNodeId(collision, {extAddress: "1111111111111111"}), null);
for (const row of collisionRows) assert.equal(resolveTopologyNodeId(collision, row), row._unifiedRecordId);
const empty = createTopologyViewModel(runAdaptor({entry: fixture.entry, rows: [], rawFiles: [[]]}));
assert.equal(computeTopologyVisibility(empty, createTopologyFilterState()).visibleNodeCount, 0);
console.log(JSON.stringify({nodes: fixture.expected.nodeIds, scopedIdentities: collision.nodes.length}));
