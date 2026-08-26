import fs from "node:fs";

import {
  FIELD_DEFINITIONS,
  getDeviceIdentityKeys,
  isPlaceholderExtAddress,
  normalizeInputRecord,
} from "../../src/js/tdash-device-fields.js";


const [modelPath] = process.argv.slice(2);
if (!modelPath) throw new Error("Usage: run-thread-device-field-model.mjs MODEL_PATH");

const model = JSON.parse(fs.readFileSync(modelPath, "utf8"));
const results = {};
results._fieldDefinitions = FIELD_DEFINITIONS;
for (const modelCase of model.normalizationCases) {
  const inputBefore = JSON.stringify(modelCase.input);
  const normalized = normalizeInputRecord(modelCase.input);
  results[modelCase.id] = {
    normalized,
    idempotent: JSON.stringify(normalizeInputRecord(normalized)) === JSON.stringify(normalized),
    inputUnchanged: JSON.stringify(modelCase.input) === inputBefore,
    identityKeys: Object.fromEntries(
      Object.keys(modelCase.identityKeys ?? {}).map((strategy) => [
        strategy,
        getDeviceIdentityKeys(normalized, strategy),
      ]),
    ),
  };
}
results._placeholderPolicy = {
  empty: isPlaceholderExtAddress(""),
  zero: isPlaceholderExtAddress("0000000000000000"),
  concrete: isPlaceholderExtAddress("0011223344556677"),
};
process.stdout.write(`${JSON.stringify(results)}\n`);
