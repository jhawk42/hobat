import fs from "node:fs";
import path from "node:path";
import { DATASET_REGISTRY } from "../../src/js/tdash-dataset-registry.js";
import { buildDatasetRows } from "../../src/js/tdash-dataset.js";
import { runAdaptor } from "../../src/js/tdash-adaptors.js";
import {
  computeTableCapabilities, computeTopologyCapabilities, scanTableCapabilities,
  isNodeVisibleByDiagnosticFilter, isRowVisibleByDiagnosticFilter,
} from "../../src/js/tdash-filters.js";
import {
  createTopologyFilterState, createTopologyViewModel, computeTopologyVisibility,
} from "../../src/js/tdash-topology-view-model.js";
import { NODE_FILTER_OPTIONS, LINK_FILTER_OPTIONS, DIAGNOSTIC_FILTER_OPTIONS } from "../../src/js/tdash-constants.js";
import { getDeviceIdentityKeys } from "../../src/js/tdash-device-fields.js";
import { buildDeviceProjections } from "../../src/js/tdash-device-projection.js";

const sorted = (items) => [...items].sort();
const nodeCapabilityKeys = {
  "ftd-devices": "hasFtdNodes", "mtd-devices": "hasMtdNodes", "reed-devices": "hasReedNodes",
  "main-routers": "hasRouters", "border-routers": "hasBorderRouters",
  "routers-with-children": "hasRoutersWithChildren", "routers-without-children": "hasRoutersWithoutChildren",
};

const dataDir = process.argv[2] ?? "data";
const selected = process.argv[3]?.startsWith("--") ? null : process.argv[3];
const useProjection = process.argv.includes("--projection");
const results = {};
for (const entry of DATASET_REGISTRY.filter((item) => !selected || item.value === selected)) {
  const rawFiles = entry.files.map((file) => {
    const filename = path.join(dataDir, file);
    return fs.existsSync(filename) ? JSON.parse(fs.readFileSync(filename, "utf8")) : null;
  });
  const { rows, loadedFiles } = buildDatasetRows(entry, rawFiles);
  if (loadedFiles.length === 0) continue;
  const adapted = runAdaptor({ entry, rawFiles, rows });
  const projections = useProjection ? buildDeviceProjections(rows) : undefined;
  const { edgeCategories, ...flags } = useProjection
    ? computeTableCapabilities(rows, projections) : scanTableCapabilities(rows);
  const topologyCapabilities = computeTopologyCapabilities(adapted.nodeData, adapted.edgeData);
  const viewModel = createTopologyViewModel(adapted, projections);
  const projectionsByRow = projections ? [...projections.values()] : [];
  const rowId = (row, index) => getDeviceIdentityKeys(row)[0] ?? `row:${index}`;
  const diagnosticMatches = Object.fromEntries(DIAGNOSTIC_FILTER_OPTIONS.map((option) => [
    option.value,
    {
      table: sorted(rows.flatMap((row, index) => isRowVisibleByDiagnosticFilter(row, option.value, projectionsByRow[index])
        ? [rowId(row, index)] : [])),
      topology: sorted(adapted.nodeData.filter((node) => isNodeVisibleByDiagnosticFilter(node, option.value,
        viewModel.projectionByNodeId.get(node.id)))
        .map((node) => String(node.id))),
    },
  ]));
  const nodeModes = NODE_FILTER_OPTIONS.filter((option) => option.alwaysShow || topologyCapabilities[nodeCapabilityKeys[option.value]]).map((option) => option.value);
  const linkModes = LINK_FILTER_OPTIONS.filter((option) => option.alwaysShow || option.requiredEdgeCategories?.some((category) => topologyCapabilities.edgeCategories.has(category))).map((option) => option.value);
  const diagnosticModes = DIAGNOSTIC_FILTER_OPTIONS.filter((option) => option.alwaysShow ||
    (topologyCapabilities[option.capabilityKey] && diagnosticMatches[option.value].topology.length > 0))
    .map((option) => option.value);
  const visibility = {};
  for (const nodeMode of nodeModes) for (const linkMode of linkModes) for (const diagnosticMode of diagnosticModes) {
    const visible = computeTopologyVisibility(viewModel, createTopologyFilterState(nodeMode, linkMode, diagnosticMode));
    visibility[`${nodeMode}|${linkMode}|${diagnosticMode}`] = {
      nodes: sorted(visible.visibleNodeIds), edges: sorted(visible.visibleEdgeIds),
    };
  }
  results[entry.value] = {
    loadedFiles,
    rowCount: rows.length,
    nodeCount: adapted.nodeData.length,
    flags,
    edgeCategories: [...edgeCategories].sort(),
    diagnosticMatches,
    offered: { nodeModes, linkModes, diagnosticModes },
    visibility,
  };
}
const snapshot = JSON.stringify(results);
if (process.argv.includes("--write")) {
  fs.writeFileSync(new URL("../fixtures/view_capability_baseline.json", import.meta.url), `${snapshot}\n`);
} else {
  console.log(snapshot);
}