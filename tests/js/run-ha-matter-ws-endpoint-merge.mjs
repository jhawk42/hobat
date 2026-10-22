import fs from "node:fs";

import { mergeRowFields } from "../../src/js/tdash-merge.js";

const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const merged = structuredClone(input.base);
mergeRowFields(merged, input.incoming);
process.stdout.write(`${JSON.stringify(merged)}\n`);
