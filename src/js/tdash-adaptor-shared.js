import {
  EDGE_CATEGORY_DEFAULT_CHILDREN, EDGE_CATEGORY_DEFAULT_1,
  EDGE_CATEGORY_DEFAULT_2, EDGE_CATEGORY_DEFAULT_3,
  EDGE_CATEGORY_ROUTER_NEIGHBOR, EDGE_CATEGORY_OTBR_ROUTE,
  EDGE_CATEGORY_OTBR_ROUTE_ROUTER, EDGE_CATEGORY_OTBR_ROUTE_FTD_CHILD,
  EDGE_CATEGORY_OTBR_CHILD, EDGE_CATEGORY_EVE_ROUTE,
  EDGE_CATEGORY_EVE_CHILD, EDGE_CATEGORY_EVE_NATIVE_ROUTE,
  EDGE_CATEGORY_EVE_NATIVE_CHILD, NODE_COLORS, NODE_SHAPES, PALETTE
} from './tdash-constants.js';
import {
  toText, toFiniteNumber, isPlainObject,
  getCanonicalRloc16, getCanonicalExtaddr,
  getCanonicalOmrIpv6Address,
  mergeForDisplay,
  getColumnValue,
  normalizeNestedArrayFields,
} from './tdash-utils.js';
import {
  chooseNodeId, buildLabel,
  buildMainRouterRloc16, buildChildRloc16,
  addEdge, buildEdgeTitle, buildNodeHoverLabel, groupIsolatedUnknownNodes, buildVisNodeData, buildNodeLabelFont,
  lqStyleFromField, lqStyleFromAvgLqi, lqStyleFromLinkMargin
} from './tdash-topology-utils.js';
import {
  getFieldNameCandidates,
  isPlaceholderOmrAddress,
  normalizeInputRecord,
} from './tdash-device-fields.js';
import { compareFieldAuthority } from './tdash-source-authority.js';
import {
  createAdaptorModel,
  createAdaptorModelFromResult,
  emitAdaptorResult,
  registerDetails,
  registerDevice,
  registerRelationship,
  registerRouterChildRows,
  registerRouterNeighborRows,
} from './tdash-adaptor-model.js';


export function asArray(value) { return Array.isArray(value) ? value : []; }

const BORDER_ROUTER_CONFLICT_LIMIT = 20;

function borderRouterObservation(record) {
  if (!isPlainObject(record)) return { value: undefined, conflicts: [] };
  const candidateRecord = {};
  getFieldNameCandidates("isBorderRouter").forEach((field) => {
    if (Object.prototype.hasOwnProperty.call(record, field)) {
      candidateRecord[field] = record[field];
    }
  });
  if (Array.isArray(record._merge_conflicts)) {
    candidateRecord._merge_conflicts = record._merge_conflicts;
  }
  const normalized = normalizeInputRecord(candidateRecord);
  return {
    value: typeof normalized.isBorderRouter === "boolean"
      ? normalized.isBorderRouter : undefined,
    conflicts: Array.isArray(normalized._merge_conflicts)
      ? normalized._merge_conflicts : [],
  };
}

function borderRouterSourceFiles(record) {
  if (!isPlainObject(record) || !Array.isArray(record._source_files)) return [];
  return [...new Set(record._source_files.filter((filename) => (
    typeof filename === "string" && filename.length > 0
  )))];
}

function compareBorderRouterAuthority(record, existing) {
  const incomingFiles = borderRouterSourceFiles(record);
  const existingFiles = borderRouterSourceFiles(existing);
  if (incomingFiles.length === 0 || existingFiles.length === 0) return 0;

  let incomingPreferred = false;
  let existingPreferred = false;
  incomingFiles.forEach((incomingFile) => {
    existingFiles.forEach((existingFile) => {
      const comparison = compareFieldAuthority(
        "isBorderRouter", incomingFile, existingFile,
      );
      if (comparison > 0) incomingPreferred = true;
      if (comparison < 0) existingPreferred = true;
    });
  });
  if (incomingPreferred === existingPreferred) return 0;
  return incomingPreferred ? 1 : -1;
}

function mergeSourceFiles(...records) {
  return [...new Set(records.flatMap(borderRouterSourceFiles))];
}

function mergeConflictLists(...records) {
  const conflicts = [];
  records.forEach((record) => {
    if (!Array.isArray(record?._merge_conflicts)) return;
    record._merge_conflicts.forEach((conflict) => {
      if (!isPlainObject(conflict) || typeof conflict.path !== "string"
          || !Object.prototype.hasOwnProperty.call(conflict, "current")
          || !Object.prototype.hasOwnProperty.call(conflict, "incoming")) return;
      const entry = {
        path: conflict.path,
        current: conflict.current,
        incoming: conflict.incoming,
      };
      const serialized = JSON.stringify(entry);
      if (conflicts.length < BORDER_ROUTER_CONFLICT_LIMIT
          && !conflicts.some((item) => JSON.stringify(item) === serialized)) {
        conflicts.push(entry);
      }
    });
  });
  return conflicts;
}

export function resolveBorderRouterEvidence(record, existing) {
  const incoming = borderRouterObservation(record);
  const previous = borderRouterObservation(existing);
  let value = incoming.value ?? previous.value;
  let disagreement;

  if (incoming.value !== undefined && previous.value !== undefined
      && incoming.value !== previous.value) {
    const authority = compareBorderRouterAuthority(record, existing);
    value = authority > 0 ? incoming.value
      : authority < 0 ? previous.value
        : true;
    disagreement = {
      path: "isBorderRouter",
      current: value,
      incoming: !value,
    };
  }

  const conflictRecord = disagreement ? { _merge_conflicts: [disagreement] } : null;
  const sourceFiles = mergeSourceFiles(existing, record);
  const sourceRecord = sourceFiles.length > 0 ? { _source_files: sourceFiles } : null;
  return {
    value,
    sourceFiles,
    conflicts: mergeConflictLists(
      existing,
      { _merge_conflicts: previous.conflicts },
      record,
      { _merge_conflicts: incoming.conflicts },
      conflictRecord,
    ),
  };
}

export function borderRouterEvidenceFields(resolution) {
  return {
    ...(typeof resolution?.value === "boolean"
      ? { isBorderRouter: resolution.value } : {}),
    ...(resolution?.sourceFiles?.length > 0
      ? { _source_files: resolution.sourceFiles } : {}),
    ...(resolution?.conflicts?.length > 0
      ? { _merge_conflicts: resolution.conflicts } : {}),
  };
}

export function mergeBorderRouterEvidence(record, existing) {
  return resolveBorderRouterEvidence(record, existing).value;
}

function mergeBorderRouterOutputRecord(record, nodeRecord) {
  if (!isPlainObject(record) || !isPlainObject(nodeRecord)) return record;
  const merged = { ...record };
  if (typeof nodeRecord.isBorderRouter === "boolean") {
    merged.isBorderRouter = nodeRecord.isBorderRouter;
    delete merged.br;
    delete merged.is_border_router;
  }
  const conflicts = mergeConflictLists(record, nodeRecord);
  if (conflicts.length > 0) merged._merge_conflicts = conflicts;
  const sourceFiles = mergeSourceFiles(record, nodeRecord);
  if (sourceFiles.length > 0) merged._source_files = sourceFiles;
  return merged;
}

export function emitThroughAdaptorModel(result) {
  if (result?.nodeMap instanceof Map) {
    if (Array.isArray(result.nodeData)) {
      result.nodeData = result.nodeData.map((record) => (
        mergeBorderRouterOutputRecord(
          record,
          result.nodeMap.get(String(record?.id)) ?? result.nodeMap.get(record?.id),
        )
      ));
    }
    if (result.rawByIdForDetails instanceof Map) {
      result.rawByIdForDetails = new Map(
        [...result.rawByIdForDetails.entries()].map(([id, record]) => [
          id,
          mergeBorderRouterOutputRecord(record, result.nodeMap.get(String(id)) ?? result.nodeMap.get(id)),
        ]),
      );
    }
  }
  return emitAdaptorResult(createAdaptorModelFromResult(result));
}

/**
 * Build a Map<filename, loadedData> from the registry entry's files list and
 * the parallel array of loaded file contents.
 */

function buildEdgeEndpointTitlePart(nodeLike, fallbackId = '') {
  const rloc16 = toText(nodeLike?.rloc16) || toText(fallbackId) || 'n/a';
  const candidateId = toText(nodeLike?.id);
  const canonicalExtaddr = getCanonicalExtaddr(nodeLike);
  const deviceLabel =
    toText(nodeLike?.deviceLabel)
    || toText(nodeLike?.device_label)
    || toText(nodeLike?.name)
    || toText(nodeLike?.hostName)
    || (candidateId && candidateId !== rloc16 ? candidateId : '')
    || toText(nodeLike?.extAddress)
    || canonicalExtaddr
    || toText(nodeLike?.extaddr)
    || '';
  return `${rloc16} ${deviceLabel}`;
}

export function buildEdgeEndpointTitles(fromNodeLike, toNodeLike, fromFallbackId = '', toFallbackId = '') {
  return {
    edgeFromTitle: buildEdgeEndpointTitlePart(fromNodeLike, fromFallbackId),
    edgeToTitle: buildEdgeEndpointTitlePart(toNodeLike, toFallbackId),
  };
}

function getOtbrRouteCategory(sourceNode) {
  const role = toText(sourceNode?.role).trim().toLowerCase();
  const modeDevice = toText(
    sourceNode?.['mode.device']
    || sourceNode?.mode?.device
    || sourceNode?.modeDevice
    || sourceNode?.mode_device
    || (sourceNode?.mode?.deviceTypeFTD === true ? 'FTD' : ''),
  ).toUpperCase();
  const hasRouterFlag =
    sourceNode?.isBorderRouter === true || sourceNode?.isRouter === true;

  if (role === 'child') {
    if (hasRouterFlag) return '';
    return modeDevice === 'FTD' ? EDGE_CATEGORY_OTBR_ROUTE_FTD_CHILD : '';
  }
  if (
    hasRouterFlag
    || role === 'border router'
    || role === 'router'
  ) {
    return EDGE_CATEGORY_OTBR_ROUTE_ROUTER;
  }
  return '';
}

export function getOtbrRouteCategories(sourceNode) {
  const category = getOtbrRouteCategory(sourceNode);
  return category ? [EDGE_CATEGORY_OTBR_ROUTE, category] : [];
}
