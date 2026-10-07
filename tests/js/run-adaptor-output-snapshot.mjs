import fs from "node:fs";
import path from "node:path";

import { DATASET_REGISTRY } from "../../src/js/tdash-dataset-registry.js";
import { buildDatasetRows } from "../../src/js/tdash-dataset.js";
import { runAdaptor } from "../../src/js/tdash-adaptors.js";
import { HA_MATTER_ROLE_POLICY } from "../../src/js/tdash-ha-matter-ws-roles.js";

const PINNED_INPUT_DIRECTORY = new URL("../fixtures/adaptor_refactor_inputs/", import.meta.url);
const PINNED_BASELINE = new URL("../fixtures/adaptor_refactor_baseline.json", import.meta.url);

function snapshotReplacer(_key, value) {
  if (value === undefined) return { $undefined: true };
  if (value instanceof Map) return { $map: [...value.entries()] };
  if (value instanceof Set) return { $set: [...value] };
  return value;
}

export function stringifyPinnedAdaptorSnapshot(snapshot) {
  return `${JSON.stringify(snapshot, snapshotReplacer, 2)}\n`;
}

function serializeAdaptorResult(result) {
  return Object.fromEntries(Object.keys(result).map((key) => [key, result[key]]));
}

function readPinnedInput(filename) {
  return JSON.parse(fs.readFileSync(new URL(filename, PINNED_INPUT_DIRECTORY), "utf8"));
}

function runPinnedAdaptor(adaptor, input) {
  const files = Object.keys(input.files);
  const entry = { adaptor, files, ...(input.entry ?? {}) };
  return runAdaptor({
    entry,
    rawFiles: files.map((filename) => input.files[filename]),
    rows: input.rows ?? input.mergedRows ?? [],
    adaptorRows: input.adaptorRows,
    rolePolicy: input.rolePolicy ? HA_MATTER_ROLE_POLICY : undefined,
  });
}

export function createPinnedAdaptorSnapshot() {
  const cases = [
    ["otbrCli", "meshdiag-networkdiag", "otbr-cli.json"],
    ["threadTools", "thread-tools-native", "thread-tools.json"],
    ["mergedDetailed", "merged-detailed", "merged-detailed.json"],
    ["otbrRestApi", "otbr-restapi", "otbr-restapi.json"],
    ["haMatterWs", "ha-matter-ws", "ha-matter-ws.json"],
    ["haMatterWsRolePolicy", "ha-matter-ws", "ha-matter-ws-role-policy.json"],
    ["haMatterWsMeshDiagnostics", "ha-matter-ws", "ha-matter-ws-mesh-diagnostics.json"],
  ];
  return Object.fromEntries(cases.map(([name, adaptor, filename]) => [
    name,
    serializeAdaptorResult(runPinnedAdaptor(adaptor, readPinnedInput(filename))),
  ]));
}

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
      nodeEmphasis: result.nodeData.map((node) => [
        node.id,
        node.borderWidth ?? null,
        node.size ?? null,
      ]),
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

export function writePinnedAdaptorSnapshot() {
  fs.writeFileSync(PINNED_BASELINE, stringifyPinnedAdaptorSnapshot(createPinnedAdaptorSnapshot()));
}
