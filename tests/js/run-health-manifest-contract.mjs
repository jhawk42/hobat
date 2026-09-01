import fs from "node:fs";
import { DATASET_REGISTRY } from "../../src/js/tdash-dataset-registry.js";

const manifest = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const eligible = DATASET_REGISTRY.filter((entry) => entry.healthEligible === true);
const fields = [
  "source",
  "value",
  "files",
  "mergeStrategy",
  "rowExtractor",
  "adaptor",
  "healthEligible",
  "healthProfile",
];

const selected = (entry) => Object.fromEntries(fields.map((field) => [field, entry[field]]));
const actual = eligible.map(selected).sort((left, right) => left.value.localeCompare(right.value));
const expected = manifest.datasets.map(selected).sort((left, right) => left.value.localeCompare(right.value));

if (JSON.stringify(actual) !== JSON.stringify(expected)) {
  console.error(JSON.stringify({ actual, expected }, null, 2));
  process.exit(1);
}