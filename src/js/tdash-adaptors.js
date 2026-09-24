import { adaptHaMatterWs, adaptHaMatterWsNativeThread, adaptHaMatterWsNetworkTopology, adaptHaMatterWsMergeTopology } from './tdash-adaptor-ha-matter-ws.js';
export { adaptHaMatterWs, adaptHaMatterWsNativeThread, adaptHaMatterWsNetworkTopology, adaptHaMatterWsMergeTopology };
import { extractOtbrRestApiItems, extractOtbrRestApiSources, adaptOtbrRestApi, buildOtbrRestApiModel } from './tdash-adaptor-otbr-restapi.js';
export { extractOtbrRestApiItems, extractOtbrRestApiSources, adaptOtbrRestApi, buildOtbrRestApiModel };
import { adaptMeshdiagNetworkdiag, adaptRouterTable } from './tdash-adaptor-otbr-cli.js';
export { adaptMeshdiagNetworkdiag, adaptRouterTable };
import { adaptMergedDetailed, adaptRawArray } from './tdash-adaptor-merged.js';
export { adaptMergedDetailed, adaptRawArray };
import { adaptEve, adaptEveNative } from './tdash-adaptor-eve.js';
export { adaptEve, adaptEveNative };
import { adaptThreadToolsNative } from './tdash-adaptor-thread-tools.js';
export { adaptThreadToolsNative };
function buildFileMap(fileNames, rawFiles) {
  const map = new Map();
  fileNames.forEach((name, i) => { if (name) map.set(name, rawFiles[i]); });
  return map;
}

// ── Dispatch: pick adaptor from the dataset registry identifier ───────────────

export const ADAPTOR_HANDLERS = Object.freeze({
  'meshdiag-networkdiag': (fileMap, rows) => adaptMeshdiagNetworkdiag(fileMap, rows),
  'merged-detailed': (fileMap) => adaptMergedDetailed(fileMap),
  'eve-enhanced': (fileMap) => adaptEve(fileMap),
  'eve-native': (fileMap) => adaptEveNative(fileMap),
  'thread-tools-native': (fileMap) => adaptThreadToolsNative(fileMap),
  'router-table': (fileMap) => adaptRouterTable(fileMap),
  'otbr-restapi': (fileMap, rows) => adaptOtbrRestApi(fileMap, rows),
  'ha-matter-ws': (fileMap, rows, entry) => adaptHaMatterWs(
    fileMap,
    rows,
    entry?.rowExtractor,
  ),
  'ha-matter-ws-native-thread': (fileMap, rows, entry) => adaptHaMatterWsNativeThread(fileMap, rows, entry),
  'ha-matter-ws-network-topology': (fileMap) => adaptHaMatterWsNetworkTopology(fileMap),
  'ha-matter-ws-merge-topology': (fileMap, rows) => adaptHaMatterWsMergeTopology(fileMap, rows),
  'raw-array': (fileMap) => adaptRawArray(fileMap),
});

export function runAdaptor(dataset) {
  const { entry, rawFiles, rows } = dataset;
  const fileMap = buildFileMap(entry.files || [], rawFiles);
  const handler = ADAPTOR_HANDLERS[entry.adaptor];
  if (!handler) throw new Error(`Unknown adaptor: ${entry.adaptor}`);
  return handler(fileMap, rows, entry);
}
