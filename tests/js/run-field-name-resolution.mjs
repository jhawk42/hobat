import fs from "node:fs";

import {
  FIELD_DEFINITIONS,
  getFieldNameCandidates,
  getPreferredFieldPath,
  normalizeInputRecord,
} from "../../src/js/tdash-device-fields.js";
import { getPreferredFieldName } from "../../src/js/tdash-utils.js";

const names = [...new Set(FIELD_DEFINITIONS.flatMap(({ path, aliases }) => [path, ...aliases]))];
const rows = names.map((input) => ({
  input,
  preferred: getPreferredFieldPath(input),
  candidates: getFieldNameCandidates(input),
  tablePreferred: getPreferredFieldName(input),
}));
const fixturePath = process.argv[2];
const fixtureResults = fixturePath
  ? JSON.parse(fs.readFileSync(fixturePath, "utf8")).cases.map(({ input }) => normalizeInputRecord(input))
  : undefined;
process.stdout.write(`${JSON.stringify(fixtureResults ? { rows, fixtureResults } : rows)}\n`);