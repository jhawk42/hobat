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
import { getDeviceIdentityKeys } from './tdash-device-fields.js';
import { adaptUnified } from './tdash-adaptor-unified.js';
export { adaptThreadToolsNative };
function buildFileMap(fileNames, rawFiles) {
  const map = new Map();
  fileNames.forEach((name, i) => { if (name) map.set(name, rawFiles[i]); });
  return map;
}

// ── Dispatch: pick adaptor from the dataset registry identifier ───────────────

export const ADAPTOR_HANDLERS = Object.freeze({
  'unified': adaptUnified,
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
  'ha-matter-ws-native-thread': (fileMap, rows) => adaptHaMatterWsNativeThread(fileMap, rows),
  'ha-matter-ws-network-topology': (fileMap, rows) => adaptHaMatterWsNetworkTopology(fileMap, rows),
  'ha-matter-ws-merge-topology': (fileMap, rows) => adaptHaMatterWsMergeTopology(fileMap, rows),
  'raw-array': (fileMap) => adaptRawArray(fileMap),
});

function canonicalReedRowsByIdentity(rows) {
  const byIdentity = new Map();
  rows.forEach((row) => {
    if (typeof row?.isReed !== 'boolean') return;
    canonicalReedIdentityKeys(row).forEach((key) => {
      if (!byIdentity.has(key)) byIdentity.set(key, row);
    });
  });
  return byIdentity;
}

function canonicalReedIdentityKeys(record) {
  const keys = getDeviceIdentityKeys(record);
  const id = typeof record?.id === 'string' ? record.id.trim().toLowerCase() : '';
  if (/^[0-9a-f]{16}$/.test(id)) keys.push(`extAddress:${id}`);
  else if (/^0x[0-9a-f]{4}$/.test(id)) keys.push(`rloc16:${id}`);
  return [...new Set(keys)];
}

function applyCanonicalReedFacts(result, rows) {
  const byIdentity = canonicalReedRowsByIdentity(rows);
  const apply = (record) => {
    if (!record || typeof record !== 'object') return;
    const row = canonicalReedIdentityKeys(record)
      .map((key) => byIdentity.get(key))
      .find(Boolean);
    if (row) record.isReed = row.isReed;
  };
  result.nodeData?.forEach(apply);
  result.nodeMap?.forEach(apply);
  result.rawByIdForDetails?.forEach(apply);
}

export function runAdaptor(dataset) {
  const { entry, rawFiles, rows } = dataset;
  const fileMap = buildFileMap(entry.files || [], rawFiles);
  const handler = ADAPTOR_HANDLERS[entry.adaptor];
  if (!handler) throw new Error(`Unknown adaptor: ${entry.adaptor}`);
  const adaptorRows = dataset.adaptorRows ?? rows;
  const handlerRows = entry.adaptor === "ha-matter-ws" ? adaptorRows : rows;
  const result = handler(fileMap, handlerRows, entry);
  applyCanonicalReedFacts(result, adaptorRows);
  return result;
}
