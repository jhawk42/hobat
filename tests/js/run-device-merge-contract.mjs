import assert from "node:assert/strict";
import fs from "node:fs";

import {
  mergeRowsByStrategy, normalizeRows, compareSequences, isSequenceNewer,
  mergeRouteData,
} from "../../src/js/tdash-merge.js";
import { canonicalExtPanId, normalizeInputRecord } from "../../src/js/tdash-device-fields.js";
import { buildDatasetRows } from "../../src/js/tdash-dataset.js";

assert.throws(() => canonicalExtPanId(8699115387970395326), /represented exactly/);
for (const [base, incoming] of [[100, 228], [228, 100]]) {
  assert.equal(isSequenceNewer(base, incoming), false);
  assert.equal(isSequenceNewer(incoming, base), false);
  assert.equal(compareSequences(base, incoming), 0);
}
const routeInput = [{ routeId: 0, routeCost: 0 }];
assert.deepEqual(mergeRouteData("", routeInput, [{ routeId: 0, linkQualityIn: 3 }]),
  [{ routeId: 0, routeCost: 0, linkQualityIn: 3 }]);
assert.deepEqual(routeInput, [{ routeId: 0, routeCost: 0 }]);


function projectResult(value) {
  if (Array.isArray(value)) return value.map(projectResult);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => key !== "_row_key")
        .map(([key, child]) => [key, projectResult(child)]),
    );
  }
  return value;
}


function runCase(contractCase) {
  const { inputs } = contractCase;
  if (contractCase.operation === "network-identity") {
    try {
      const extPanId = canonicalExtPanId(inputs.value);
      return { extPanId, networkId: `extpan:${extPanId}` };
    } catch (_error) {
      return { error: "invalid" };
    }
  }
  if (contractCase.operation === "normalize") {
    let normalized = inputs.record;
    for (let iteration = 0; iteration < (inputs.repeat ?? 1); iteration += 1) {
      normalized = normalizeInputRecord(normalized, { source: inputs.sourceName ?? "" });
    }
    return projectResult(normalized);
  }

  const rowGroups = inputs.sources.map((source) =>
    normalizeRows(source.records, source.name),
  );
  if (contractCase.operation === "collector-reconciliation") {
    const merged = mergeRowsByStrategy(rowGroups, "by-identity", inputs.options ?? {})[0];
    return Object.fromEntries(inputs.fields.filter((field) => field in merged)
      .map((field) => [field, merged[field]]));
  }
  const result = projectResult(
    mergeRowsByStrategy(rowGroups, inputs.strategy, inputs.options ?? {}),
  );
  const assembled = buildDatasetRows({
    files: inputs.sources.map((source) => source.name),
    mergeStrategy: inputs.strategy,
    rowExtractor: "raw-array",
    adaptor: "raw-array",
  }, inputs.sources.map((source) => source.records), inputs.options ?? {}).rows;
  assert.deepEqual(projectResult(assembled), result, `${contractCase.id}: dataset assembly`);
  return result;
}


const [contractPath, ...selectedCaseIds] = process.argv.slice(2);
if (!contractPath) throw new Error("Usage: run-device-merge-contract.mjs CONTRACT [CASE_ID ...]");

const contract = JSON.parse(fs.readFileSync(contractPath, "utf8"));
const selected = new Set(selectedCaseIds);
const results = {};
for (const contractCase of contract.cases) {
  if (selected.size > 0 && !selected.has(contractCase.id)) continue;
  results[contractCase.id] = runCase(contractCase);
}

process.stdout.write(`${JSON.stringify(results)}\n`);