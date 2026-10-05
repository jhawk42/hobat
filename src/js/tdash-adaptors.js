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
import {
  HA_MATTER_ROLE_POLICY,
  isHaMatterRolePolicyEligible,
} from './tdash-ha-matter-ws-roles.js';
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
    entry?.rolePolicy,
  ),
  'ha-matter-ws-native-thread': (fileMap, rows, entry) => adaptHaMatterWsNativeThread(fileMap, rows, entry?.rolePolicy),
  'ha-matter-ws-network-topology': (fileMap, rows, entry) => adaptHaMatterWsNetworkTopology(fileMap, rows, entry?.rolePolicy),
  'ha-matter-ws-merge-topology': (fileMap, rows, entry) => adaptHaMatterWsMergeTopology(fileMap, rows, entry?.rolePolicy),
  'raw-array': (fileMap) => adaptRawArray(fileMap),
});

export function runAdaptor(dataset) {
  const { entry, rawFiles, rows } = dataset;
  const fileMap = buildFileMap(entry.files || [], rawFiles);
  const handler = ADAPTOR_HANDLERS[entry.adaptor];
  if (!handler) throw new Error(`Unknown adaptor: ${entry.adaptor}`);
  const rolePolicy = dataset.rolePolicy === HA_MATTER_ROLE_POLICY
    && isHaMatterRolePolicyEligible(entry)
    ? HA_MATTER_ROLE_POLICY
    : undefined;
  if (rolePolicy) {
    const roleEntry = { ...entry, rolePolicy };
    return handler(
      fileMap,
      dataset.adaptorRows ?? rows,
      roleEntry,
    );
  }
  return handler(fileMap, rows, entry);
}
