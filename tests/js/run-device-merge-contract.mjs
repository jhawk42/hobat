import fs from "node:fs";

import { mergeRowsByStrategy, normalizeRows } from "../../src/js/tdash-merge.js";
import { normalizeInputRecord } from "../../src/js/tdash-device-fields.js";


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