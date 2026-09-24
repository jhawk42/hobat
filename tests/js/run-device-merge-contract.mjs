import assert from "node:assert/strict";
import fs from "node:fs";

import { mergeRowsByStrategy, normalizeRows } from "../../src/js/tdash-merge.js";
import { canonicalExtPanId, normalizeInputRecord } from "../../src/js/tdash-device-fields.js";

assert.throws(() => canonicalExtPanId(8699115387970395326), /represented exactly/);


function projectResult(value) {
  if (Array.isArray(value)) return value.map(projectResult);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => key !== "_row_key" && key !== "_merge_identity_keys")
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
  return projectResult(
    mergeRowsByStrategy(rowGroups, inputs.strategy, inputs.options ?? {}),
  );
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