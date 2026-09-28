import fs from "node:fs";
import path from "node:path";

import { DATASET_REGISTRY } from "../../src/js/tdash-dataset-registry.js";
import { buildDatasetRows } from "../../src/js/tdash-dataset.js";
import { runAdaptor } from "../../src/js/tdash-adaptors.js";

export function createCachedAdaptorSnapshot() {
  const snapshot = {};
  for (const entry of DATASET_REGISTRY) {
    const rawFiles = entry.files.map((filename) => {
      const file = path.join("data", filename);
      return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : null;
    });
    const { rows, loadedFiles } = buildDatasetRows(entry, rawFiles);
    if (!loadedFiles.length) continue;
    const result = runAdaptor({ entry, rawFiles, rows });
    const keys = (index) => [...index.keys()].map(String).sort();
    snapshot[entry.value] = {
      nodeIds: result.nodeData.map((node) => node.id),
      edges: result.edgeData.map((edge) => [edge.id ?? null, edge.from, edge.to, edge.linkCategories ?? null]),
      details: [...result.rawByIdForDetails].map(([id, record]) => [String(id), Object.keys(record).sort()]),
      nodeMapKeys: keys(result.nodeMap),
      neighborKeys: keys(result.routerNeighborByRloc16),
      childKeys: result.routerChildByRloc16 ? keys(result.routerChildByRloc16) : null,
      sourceNames: result.sourceNames,
    };
  }
  return snapshot;
}

export function writeCachedAdaptorSnapshot() {
  const output = `${JSON.stringify(createCachedAdaptorSnapshot())}\n`;
  fs.writeFileSync(new URL("../fixtures/adaptor_output_baseline.json", import.meta.url), output);
}
