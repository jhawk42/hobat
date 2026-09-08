import { MERGE_STRATEGIES, SOURCE_PRECEDENCE } from "./tdash-constants.js";
import { getDeviceIdentityKeys, isPlaceholderExtAddress } from "./tdash-device-fields.js";
import {
  toText,
  isPlainObject,
  canonicalIdText,
  getCanonicalRloc16,
  getCanonicalExtaddr,
  getCanonicalOmrIpv6Address,
  normalizeRowMergeAliases,
  normalizeNestedArrayFields,
  formatValue,
} from "./tdash-utils.js";

// ── Row normalisation (used by table renderer + merge strategies) ────────────

export function normalizeRows(rawData, sourceName = "") {
  if (Array.isArray(rawData)) {
    return rawData.map((row, index) => {
      if (isPlainObject(row))
        return withRowProvenance(normalizeSourceRelationships(row, sourceName), sourceName);
      return withRowProvenance({ row_index: index, value: row }, sourceName);
    });
  }
  if (isPlainObject(rawData)) {
    return Object.keys(rawData).map((key) => {
      const row = rawData[key];
      if (isPlainObject(row))
        return withRowProvenance(
          normalizeRowMergeAliases({ _row_key: key, ...row }),
          sourceName,
        );
      return withRowProvenance({ _row_key: key, value: row }, sourceName);
    });
  }
  return [withRowProvenance({ value: rawData }, sourceName)];
}

function normalizeSourceRelationships(row, sourceName) {
  const normalized = normalizeRowMergeAliases(row);
  if (sourceName !== "td-otbr-restapi-mesh-diagnostics-fetch-all.json")
    return normalized;

  const result = { ...normalized };
  if (Array.isArray(result.routerNeighbors))
    result.routerNeighbors = normalizeNestedArrayFields(result.routerNeighbors);
  if (Array.isArray(result.children)) {
    result.children = normalizeNestedArrayFields(result.children);
    result.childTable = result.children;
  }
  return result;
}

// ── Merge strategy helpers ────────────────────────────────────────────────────

export function normalizeRloc16(value) {
  return canonicalIdText(value);
}

export function getRowMergeIdentityKeys(row, strategy) {
  return getDeviceIdentityKeys(row, strategy);
}

function isMatterOperationalMdnsRow(row) {
  if (!isPlainObject(row)) return false;
  const scope = toText(row.scope).toLowerCase();
  return scope === "_matter._tcp.local.";
}

function getServiceInfoPropDecodedText(row, key) {
  const props = row?.serviceInfo?.properties ?? row?.service_info?.properties;
  if (!isPlainObject(props)) return "";
  const preferredKey = key === "FabricID_compressed"
    ? "fabricIdCompressed"
    : (key === "NodeID" ? "nodeId" : key);
  const obj = props[key] ?? props[preferredKey];
  if (!isPlainObject(obj)) return "";
  const decoded = toText(obj.decoded);
  return decoded ? decoded.toLowerCase() : "";
}

function getMatterFabricNodeIdentity(row) {
  const directKeys = getDeviceIdentityKeys(row, "by-identity")
    .find((key) => key.startsWith("matterFabricNode:"));
  if (directKeys) return directKeys.slice("matterFabricNode:".length);
  if (!isMatterOperationalMdnsRow(row)) return "";
  const fabricId = getServiceInfoPropDecodedText(row, "FabricID_compressed");
  const nodeId = getServiceInfoPropDecodedText(row, "NodeID");
  if (!fabricId || !nodeId) return "";
  return `${fabricId}|${nodeId}`;
}

function filterCandidateIdsForMatterIdentityConsistency(candidateIds, incomingRow, mergedRows) {
  const incomingMatterId = getMatterFabricNodeIdentity(incomingRow);
  if (!incomingMatterId) return candidateIds;

  const incomingExtaddr = getCanonicalExtaddr(incomingRow);
  const incomingRloc16 = getCanonicalRloc16(incomingRow);

  const filtered = [];
  candidateIds.forEach((nodeId) => {
    const node = mergedRows.get(nodeId);
    if (!isPlainObject(node)) return;

    const nodeExtaddr = getCanonicalExtaddr(node);
    if (incomingExtaddr && nodeExtaddr && incomingExtaddr === nodeExtaddr) {
      filtered.push(nodeId);
      return;
    }

    const nodeMatterId = getMatterFabricNodeIdentity(node);
    if (nodeMatterId) {
      if (nodeMatterId === incomingMatterId) filtered.push(nodeId);
      return;
    }

    const nodeRloc16 = getCanonicalRloc16(node);
    if (incomingRloc16 && nodeRloc16 && incomingRloc16 === nodeRloc16) {
      filtered.push(nodeId);
    }
  });

  return filtered;
}

function getMatterIdentityMode(options = {}) {
  const mode = toText(options.matterIdentityMode).toLowerCase();
  return mode === "composite-guard" ? "composite-guard" : "strict-omr";
}

export function isEmptyMergeValue(value) {
  if (value === undefined || value === null || value === "") return true;
  if (Array.isArray(value) && value.length === 0) return true;
  if (isPlainObject(value) && Object.keys(value).length === 0) return true;
  return false;
}

export function areMergeValuesEquivalent(left, right) {
  if (left === right) return true;
  if (
    Array.isArray(left) ||
    Array.isArray(right) ||
    isPlainObject(left) ||
    isPlainObject(right)
  ) {
    try {
      return JSON.stringify(left) === JSON.stringify(right);
    } catch (_error) {
      return false;
    }
  }
  return false;
}

export function mergeStringArrays(existingValues, incomingValues) {
  const merged = [];
  [...existingValues, ...incomingValues].forEach((value) => {
    const text = toText(value);
    if (text && !merged.includes(text)) merged.push(text);
  });
  return merged;
}

export function withRowProvenance(row, sourceName) {
  if (!isPlainObject(row)) return row;
  const normalized = { ...row };
  const existingSources = Array.isArray(normalized._source_files)
    ? normalized._source_files
    : [];
  normalized._source_files = sourceName
    ? mergeStringArrays(existingSources, [sourceName])
    : mergeStringArrays(existingSources, []);
  return normalized;
}

export function appendRowConflict(target, path, currentValue, incomingValue, limit = 20) {
  const conflicts = Array.isArray(target._merge_conflicts)
    ? [...target._merge_conflicts]
    : [];
  if (conflicts.length >= limit) {
    target._merge_conflicts = conflicts;
    return;
  }

  const currentText = formatValue(currentValue);
  const incomingText = formatValue(incomingValue);
  const duplicate = conflicts.some(
    (entry) =>
      entry &&
      entry.path === path &&
      entry.current === currentText &&
      entry.incoming === incomingText,
  );
  if (!duplicate) {
    conflicts.push({ path, current: currentText, incoming: incomingText });
  }
  target._merge_conflicts = conflicts;
}

export function mergeRowMetadata(target, source) {
  target._source_files = mergeStringArrays(
    Array.isArray(target._source_files) ? target._source_files : [],
    Array.isArray(source._source_files) ? source._source_files : [],
  );
  target._merge_identity_keys = mergeStringArrays(
    Array.isArray(target._merge_identity_keys)
      ? target._merge_identity_keys
      : [],
    Array.isArray(source._merge_identity_keys)
      ? source._merge_identity_keys
      : [],
  );
  const existingConflicts = Array.isArray(target._merge_conflicts)
    ? target._merge_conflicts
    : [];
  const incomingConflicts = Array.isArray(source._merge_conflicts)
    ? source._merge_conflicts
    : [];
  if (incomingConflicts.length > 0) {
    target._merge_conflicts = [
      ...existingConflicts,
      ...incomingConflicts,
    ].slice(0, 20);
  } else if (existingConflicts.length > 0) {
    target._merge_conflicts = existingConflicts;
  }
}

function isMdnsRecord(row) {
  if (!isPlainObject(row)) return false;
  if (typeof row.record_key === "string" && row.record_key.includes("|")) return true;
  return (
    typeof row.scope === "string" &&
    row.scope.startsWith("_") &&
    row.scope.endsWith(".local.")
  );
}

function getMdnsEventPriority(event) {
  const priorities = { add: 3, update: 2, remove: 1 };
  return priorities[toText(event).toLowerCase()] ?? 0;
}

function mergeMdnsServiceInfo(baseServiceInfo, incomingServiceInfo, baseTs, incomingTs) {
  if (!isPlainObject(baseServiceInfo)) return { ...incomingServiceInfo };
  if (!isPlainObject(incomingServiceInfo)) return { ...baseServiceInfo };

  const mergeMissing = (primary, secondary) => {
    const out = { ...primary };
    Object.keys(secondary).forEach((k) => {
      const pv = out[k];
      const sv = secondary[k];
      if (isEmptyMergeValue(pv) && !isEmptyMergeValue(sv)) {
        out[k] = sv;
      } else if (isPlainObject(pv) && isPlainObject(sv)) {
        out[k] = mergeMdnsServiceInfo(pv, sv, undefined, undefined);
      }
    });
    return out;
  };

  if (Number.isFinite(baseTs) && Number.isFinite(incomingTs)) {
    return incomingTs > baseTs
      ? mergeMissing(incomingServiceInfo, baseServiceInfo)
      : mergeMissing(baseServiceInfo, incomingServiceInfo);
  }

  return mergeMissing(baseServiceInfo, incomingServiceInfo);
}

function mergeMdnsRecords(base, incoming) {
  const baseTs = Number(base?.capturedAtEpoch ?? base?.captured_at_epoch);
  const incomingTs = Number(incoming?.capturedAtEpoch ?? incoming?.captured_at_epoch);
  const hasBaseTs = Number.isFinite(baseTs);
  const hasIncomingTs = Number.isFinite(incomingTs);

  const mergeMissingFields = (primary, secondary) => {
    const out = { ...primary };
    Object.keys(secondary).forEach((k) => {
      if (k === "service_info" || k === "serviceInfo") return;
      const pv = out[k];
      const sv = secondary[k];
      if (isEmptyMergeValue(pv) && !isEmptyMergeValue(sv)) {
        out[k] = sv;
      }
    });
    const primaryService = primary.serviceInfo ?? primary.service_info;
    const secondaryService = secondary.serviceInfo ?? secondary.service_info;
    if (isPlainObject(primaryService) || isPlainObject(secondaryService)) {
      const serviceKey = Object.hasOwn(primary, "serviceInfo") || Object.hasOwn(secondary, "serviceInfo")
        ? "serviceInfo"
        : "service_info";
      out[serviceKey] = mergeMdnsServiceInfo(
        isPlainObject(primaryService) ? primaryService : {},
        isPlainObject(secondaryService) ? secondaryService : {},
        undefined,
        undefined,
      );
    }
    return out;
  };

  if (hasBaseTs && hasIncomingTs) {
    if (incomingTs > baseTs) return mergeMissingFields(incoming, base);
    if (incomingTs < baseTs) return mergeMissingFields(base, incoming);

    const basePrio = getMdnsEventPriority(base?.event);
    const incomingPrio = getMdnsEventPriority(incoming?.event);
    return incomingPrio > basePrio
      ? mergeMissingFields(incoming, base)
      : mergeMissingFields(base, incoming);
  }

  return mergeMissingFields(base, incoming);
}

function appendUniqueAlias(aliasMap, key, value) {
  const text = toText(value);
  if (!text) return;
  const arr = Array.isArray(aliasMap[key]) ? aliasMap[key] : [];
  if (!arr.includes(text)) arr.push(text);
  aliasMap[key] = arr;
}

function getServiceInfoPropDecoded(row, key) {
  const props = row?.serviceInfo?.properties ?? row?.service_info?.properties;
  if (!isPlainObject(props)) return "";
  const preferredKey = key === "FabricID_compressed"
    ? "fabricIdCompressed"
    : (key === "NodeID" ? "nodeId" : key);
  const node = props[key] ?? props[preferredKey];
  if (!isPlainObject(node)) return "";
  return toText(node.decoded);
}

function updateMdnsAliases(target, row) {
  if (!isPlainObject(target) || !isPlainObject(row)) return;
  const aliasMap = isPlainObject(target._mdns_aliases) ? target._mdns_aliases : {};

  appendUniqueAlias(aliasMap, "nameAliases", row.name);
  appendUniqueAlias(aliasMap, "serverAliases", row.server ?? row?.serviceInfo?.server ?? row?.service_info?.server);
  appendUniqueAlias(
    aliasMap,
    "serverKeyAliases",
    toText(row.serverKey ?? row.server_key ?? row?.serviceInfo?.key ?? row?.service_info?.key).toLowerCase(),
  );
  appendUniqueAlias(
    aliasMap,
    "fabricIdCompressedAliases",
    getServiceInfoPropDecoded(row, "FabricID_compressed"),
  );
  appendUniqueAlias(aliasMap, "nodeIdAliases", getServiceInfoPropDecoded(row, "NodeID"));
  appendUniqueAlias(
    aliasMap,
    "matterFabricNodeAliases",
    getMatterFabricNodeIdentity(row),
  );

  target._mdns_aliases = aliasMap;
}

function extractMdnsMergeView(row) {
  if (!isPlainObject(row)) return {};
  const fields = [
    "recordKey",
    "event",
    "capturedAtEpoch",
    "capturedAtIso",
    "scope",
    "name",
    "extAddress",
    "omrIpv6Address",
    "isBorderRouter",
    "role",
    "serviceInfo",
    "server",
    "serverKey",
  ];
  const out = {};
  fields.forEach((k) => {
    if (Object.prototype.hasOwnProperty.call(row, k)) out[k] = row[k];
  });
  if (!out.server && typeof out?.serviceInfo?.server === "string") {
    out.server = out.serviceInfo.server;
  }
  if (!out.server && typeof out?.service_info?.server === "string") {
    out.server = out.service_info.server;
  }
  if (!out.serverKey && !out.server_key && typeof out?.serviceInfo?.key === "string") {
    out.serverKey = out.serviceInfo.key;
  }
  if (!out.serverKey && !out.server_key && typeof out?.service_info?.key === "string") {
    out.server_key = out.service_info.key;
  }
  return out;
}

function applyMdnsMergeView(target, merged) {
  [
    "recordKey",
    "event",
    "capturedAtEpoch",
    "capturedAtIso",
    "scope",
    "name",
    "extAddress",
    "omrIpv6Address",
    "isBorderRouter",
    "role",
    "serviceInfo",
    "server",
    "serverKey",
  ].forEach((k) => {
    if (Object.prototype.hasOwnProperty.call(merged, k)) target[k] = merged[k];
  });
}

function mergeMdnsRowIntoTarget(target, source) {
  if (!isMdnsRecord(source)) return;

  updateMdnsAliases(target, target);
  updateMdnsAliases(target, source);

  const baseView = extractMdnsMergeView(target);
  const incomingView = extractMdnsMergeView(source);
  if (!isPlainObject(incomingView) || Object.keys(incomingView).length === 0) return;

  const merged =
    isPlainObject(baseView) && Object.keys(baseView).length > 0
      ? mergeMdnsRecords(baseView, incomingView)
      : { ...incomingView };
  applyMdnsMergeView(target, merged);
}

export function createMergeContext(existingSource, incomingSource, options = {}) {
  const priorities = options.sourcePriorities ?? SOURCE_PRECEDENCE;
  return Object.freeze({
    existingSource: existingSource ?? "",
    incomingSource: incomingSource ?? "",
    existingPriority: priorities[existingSource] ?? 0,
    incomingPriority: priorities[incomingSource] ?? 0,
    ownerRloc16: options.ownerRloc16 ?? "",
    partitionId: options.partitionId,
    incomingPartitionId: options.incomingPartitionId,
    conflictLimit: options.conflictLimit ?? 20,
    matterIdentityMode: getMatterIdentityMode(options),
    fieldPath: options.fieldPath ?? "",
  });
}

function mergeRouteObjects(existing, incoming, context) {
  if (!isPlainObject(existing)) return { ...incoming };
  if (!isPlainObject(incoming)) return { ...existing };
  if (
    context.partitionId !== undefined
    && context.incomingPartitionId !== undefined
    && context.partitionId !== context.incomingPartitionId
  ) return { ...existing };
  const existingSequence = Number(existing.idSequence ?? existing.id_sequence);
  const incomingSequence = Number(incoming.idSequence ?? incoming.id_sequence);
  if (Number.isFinite(existingSequence) && Number.isFinite(incomingSequence)) {
    if (isSequenceNewer(incomingSequence, existingSequence)) return { ...incoming };
    if (isSequenceNewer(existingSequence, incomingSequence)) return { ...existing };
  }
  const merged = { ...existing };
  deepMergeObjects(merged, incoming, "route", context.conflictTarget, context);
  return merged;
}

export const MERGE_FIELD_HANDLERS = Object.freeze({
  route: (existing, incoming, context) => mergeRouteObjects(existing, incoming, context),
  children: (existing, incoming, context) =>
    mergeChildrenArray(context.ownerRloc16, Array.isArray(existing) ? existing : [], incoming, context),
  childTable: (existing, incoming, context) =>
    mergeChildrenArray(context.ownerRloc16, Array.isArray(existing) ? existing : [], incoming, context),
  childIpv6Addresses: (existing, incoming) =>
    mergeStringArrays(Array.isArray(existing) ? existing : [], incoming),
  routerNeighbors: (existing, incoming, context) =>
    mergeRouterNeighbors(Array.isArray(existing) ? existing : [], incoming, context),
});

export function mergeRowFields(target, source, context = {}) {
  mergeMdnsRowIntoTarget(target, source);
  mergeRowMetadata(target, source);
  Object.keys(source).forEach((key) => {
    if (key.startsWith("_")) return;
    // Guard against prototype-pollution keys
    if (key === "__proto__" || key === "constructor" || key === "prototype") return;
    const sv = source[key];
    const tv = target[key];
    const handler = MERGE_FIELD_HANDLERS[key];
    if (handler && !isEmptyMergeValue(sv)) {
      target[key] = handler(tv, sv, {
        ...context,
        conflictTarget: target,
        ownerRloc16: context.ownerRloc16 || getCanonicalRloc16(target),
        fieldPath: key,
      });
      return;
    }
    if (isEmptyMergeValue(tv) && !isEmptyMergeValue(sv)) {
      target[key] = sv;
    } else if (isPlainObject(tv) && isPlainObject(sv)) {
      deepMergeObjects(tv, sv, key, target);
    } else if (
      !isEmptyMergeValue(tv) &&
      !isEmptyMergeValue(sv) &&
      !areMergeValuesEquivalent(tv, sv)
    ) {
      appendRowConflict(target, key, tv, sv, context.conflictLimit ?? 20);
    }
  });
}

// ── RFC 1982 serial number arithmetic (#5) ────────────────────────────────────

/**
 * Returns true when sequence number `seqA` is strictly newer than `seqB`
 * using RFC 1982 8-bit serial arithmetic (handles 0→255 wraparound).
 */
export function isSequenceNewer(seqA, seqB) {
  const a = ((seqA % 256) + 256) % 256;
  const b = ((seqB % 256) + 256) % 256;
  if (a === b) return false;
  return ((a - b + 256) % 256) < 128;
}

/**
 * Compares two 8-bit sequence numbers with RFC 1982 wraparound.
 * Returns: positive if seqA is newer, negative if seqB is newer, 0 if equal.
 */
export function compareSequences(seqA, seqB) {
  const a = ((seqA % 256) + 256) % 256;
  const b = ((seqB % 256) + 256) % 256;
  if (a === b) return 0;
  return isSequenceNewer(a, b) ? 1 : -1;
}

// ── Partition awareness (#6) ──────────────────────────────────────────────────

/**
 * Returns the numeric partition_id from a row (checks both snake_case and
 * camelCase keys).  Returns undefined when not present.
 */
export function getPartitionId(row) {
  const v = row?.leaderData?.partitionId
    ?? row?.leader_data?.partition_id
    ?? row?.partition_id
    ?? row?.partitionId;
  if (v === undefined || v === null) return undefined;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : undefined;
}

// ── Deep merge for nested objects (#2) ───────────────────────────────────────

/**
 * Merges plain-object `source` into plain-object `target` recursively.
 * Special-cased sub-arrays (route_data, children, router_neighbors) use
 * composite-identity deduplication.  Conflicts are recorded on `conflictTarget`
 * using dotted `pathPrefix.fieldName` paths.
 *
 * @param {object} target         - Object to merge into (mutated in place)
 * @param {object} source         - Object providing new values
 * @param {string} pathPrefix     - Dotted-path context for conflict recording
 * @param {object} conflictTarget - Row that owns _merge_conflicts
 * @param {object} [ctx]          - Optional context: { ownerRloc16, partitionId }
 */
export function deepMergeObjects(target, source, pathPrefix, conflictTarget, ctx = {}) {
  const isRouteContainerPath = pathPrefix === "route" || pathPrefix === "route_data";
  const parseSeqValue = (value) => {
    if (value === undefined || value === null || value === "") return undefined;
    const n = typeof value === "number" ? value : parseInt(value, 10);
    return Number.isFinite(n) ? n : undefined;
  };

  Object.keys(source).forEach((key) => {
    if (key.startsWith("_")) return;
    // Guard against prototype-pollution keys
    if (key === "__proto__" || key === "constructor" || key === "prototype") return;
    const sv = source[key];
    const tv = target[key];
    const fieldPath = pathPrefix ? `${pathPrefix}.${key}` : key;

    // Special-case known nested arrays with composite-identity merge
    if ((key === "route_data" || key === "routeData") && Array.isArray(sv)) {
      const ownerRloc16 = ctx.ownerRloc16 ?? getCanonicalRloc16(conflictTarget);
      target[key] = mergeRouteData(ownerRloc16, Array.isArray(tv) ? tv : [], sv, ctx);
      return;
    }

    if (isRouteContainerPath && (key === "id_sequence" || key === "idSequence")) {
      const existingSeq = parseSeqValue(tv);
      const incomingSeq = parseSeqValue(sv);

      if (existingSeq === undefined && incomingSeq !== undefined) {
        target[key] = incomingSeq;
      } else if (existingSeq !== undefined && incomingSeq !== undefined) {
        if (isSequenceNewer(incomingSeq, existingSeq)) {
          target[key] = incomingSeq;
        }
      } else if (isEmptyMergeValue(tv) && !isEmptyMergeValue(sv)) {
        target[key] = sv;
      } else if (
        !isEmptyMergeValue(tv) &&
        !isEmptyMergeValue(sv) &&
        !areMergeValuesEquivalent(tv, sv)
      ) {
        appendRowConflict(conflictTarget, fieldPath, tv, sv);
      }

      // Keep both sequence aliases aligned when both exist on the route container.
      const resolvedSeq = target[key];
      if (key === "idSequence" && Object.prototype.hasOwnProperty.call(target, "id_sequence")) {
        target.id_sequence = resolvedSeq;
      }
      if (key === "id_sequence" && Object.prototype.hasOwnProperty.call(target, "idSequence")) {
        target.idSequence = resolvedSeq;
      }
      return;
    }
    if ((key === "children" || key === "childTable") && Array.isArray(sv)) {
      const parentRloc16 = ctx.ownerRloc16 ?? getCanonicalRloc16(conflictTarget);
      target[key] = mergeChildrenArray(parentRloc16, Array.isArray(tv) ? tv : [], sv);
      return;
    }
    if ((key === "router_neighbors" || key === "neighborTable") && Array.isArray(sv)) {
      target[key] = mergeRouterNeighbors(Array.isArray(tv) ? tv : [], sv);
      return;
    }

    if (isEmptyMergeValue(tv) && !isEmptyMergeValue(sv)) {
      target[key] = sv;
    } else if (isPlainObject(tv) && isPlainObject(sv)) {
      deepMergeObjects(tv, sv, fieldPath, conflictTarget, ctx);
    } else if (
      !isEmptyMergeValue(tv) &&
      !isEmptyMergeValue(sv) &&
      !areMergeValuesEquivalent(tv, sv)
    ) {
      appendRowConflict(conflictTarget, fieldPath, tv, sv);
    }
  });
}

// ── Composite-identity array merges (#3) ─────────────────────────────────────

/**
 * Merges two route_data arrays for a given ownerRloc16.
 * Identity key: route.id (or route.routeId).
 * When both sides have the same route, the side with the newer id_sequence
 * (RFC 1982) wins.  Cross-partition routes are skipped when partition_id
 * differs from ctx.partitionId.
 *
 * @param {string} ownerRloc16
 * @param {Array}  baseRoutes
 * @param {Array}  incomingRoutes
 * @param {object} [ctx]  - { partitionId }
 * @returns {Array}
 */
export function mergeRouteData(ownerRloc16, baseRoutes, incomingRoutes, ctx = {}) {
  const index = new Map();
  baseRoutes.forEach((route) => {
    if (!isPlainObject(route)) return;
    const routeId = route.id ?? route.routeId;
    if (routeId !== undefined) index.set(String(routeId), route);
  });

  incomingRoutes.forEach((route) => {
    if (!isPlainObject(route)) return;
    const routeId = route.id ?? route.routeId;
    if (routeId === undefined) return;

    // Partition gate: skip when partition IDs are known and differ
    if (ctx.partitionId !== undefined) {
      const routePartition = getPartitionId(route);
      if (routePartition !== undefined && routePartition !== ctx.partitionId) return;
    }

    const key = String(routeId);
    const existing = index.get(key);
    if (!existing) {
      index.set(key, { ...route });
      return;
    }

    // Keep whichever entry has the newer id_sequence (RFC 1982)
    const existingSeq = existing.id_sequence ?? existing.idSequence ?? 0;
    const incomingSeq = route.id_sequence ?? route.idSequence ?? 0;
    if (isSequenceNewer(incomingSeq, existingSeq)) {
      index.set(key, { ...route });
    }
  });

  return Array.from(index.values());
}

/**
 * Merges two children arrays for a given parentRloc16.
 * Identity key: child.extAddress (lowercased) or child.rloc16.
 *
 * @param {string} parentRloc16
 * @param {Array}  baseChildren
 * @param {Array}  incomingChildren
 * @returns {Array}
 */
function mergeRelationshipArrays(baseRecords, incomingRecords, context = {}) {
  const records = [];
  const byExtAddress = new Map();
  const byRloc16 = new Map();

  const mergeRecord = (target, source) => {
    Object.keys(source).forEach((field) => {
      const replacesPlaceholderExtAddress =
        (field === "extAddress" || field === "extaddr")
        && isPlaceholderExtAddress(target[field])
        && !isPlaceholderExtAddress(source[field]);
      if ((isEmptyMergeValue(target[field]) || replacesPlaceholderExtAddress) && !isEmptyMergeValue(source[field])) {
        target[field] = source[field];
      }
    });
  };
  const indexRecord = (record, extAddress, rloc16) => {
    if (extAddress) byExtAddress.set(extAddress, record);
    if (rloc16) {
      const matches = byRloc16.get(rloc16) ?? new Set();
      matches.add(record);
      byRloc16.set(rloc16, matches);
    }
  };
  const addRecord = (source) => {
    if (!isPlainObject(source)) return;
    const extAddress = canonicalIdText(source.extAddress ?? source.extaddr);
    const concreteExtAddress = extAddress && !isPlaceholderExtAddress(extAddress) ? extAddress : "";
    const rloc16 = canonicalIdText(source.rloc16);
    const extMatch = concreteExtAddress ? byExtAddress.get(concreteExtAddress) : undefined;
    const rlocMatches = rloc16 ? byRloc16.get(rloc16) : undefined;
    const rlocMatch = rlocMatches?.size === 1 ? [...rlocMatches][0] : undefined;

    if (extMatch) {
      mergeRecord(extMatch, source);
      indexRecord(extMatch, concreteExtAddress, rloc16);
      return;
    }
    if (rlocMatch) {
      const matchedExtAddress = canonicalIdText(rlocMatch.extAddress ?? rlocMatch.extaddr);
      const matchedConcreteExtAddress = matchedExtAddress && !isPlaceholderExtAddress(matchedExtAddress)
        ? matchedExtAddress
        : "";
      if (!concreteExtAddress || !matchedConcreteExtAddress) {
        mergeRecord(rlocMatch, source);
        indexRecord(rlocMatch, concreteExtAddress, rloc16);
        return;
      }
      appendRowConflict(
        context.conflictTarget ?? rlocMatch,
        `${context.fieldPath || "relationship"}[rloc16:${rloc16}].extAddress`,
        matchedConcreteExtAddress,
        concreteExtAddress,
        context.conflictLimit ?? 20,
      );
    }

    const record = { ...source };
    records.push(record);
    indexRecord(record, concreteExtAddress, rloc16);
  };

  [...(Array.isArray(baseRecords) ? baseRecords : []), ...(Array.isArray(incomingRecords) ? incomingRecords : [])]
    .forEach(addRecord);
  return records;
}

export function mergeChildrenArray(parentRloc16, baseChildren, incomingChildren, context = {}) {
  return mergeRelationshipArrays(baseChildren, incomingChildren, context);
}

/**
 * Merges two router_neighbors arrays.
 * Identity key: neighbor.extAddress (lowercased) or neighbor.rloc16.
 *
 * @param {Array} baseNeighbors
 * @param {Array} incomingNeighbors
 * @returns {Array}
 */
export function mergeRouterNeighbors(baseNeighbors, incomingNeighbors, context = {}) {
  return mergeRelationshipArrays(baseNeighbors, incomingNeighbors, context);
}

// ── Source precedence sorting (#1) ────────────────────────────────────────────

/**
 * Returns a new array of rowGroups sorted lowest-priority-first so that
 * higher-priority sources are merged last and their values win on conflicts.
 *
 * Each element of `rowGroups` is expected to have at least one row with
 * `_source_files[0]` set by `normalizeRows()`.  The priority map defaults to
 * `SOURCE_PRECEDENCE` but can be overridden via `priorityMap`.
 */
export function sortRowGroupsByPriority(rowGroups, priorityMap) {
  const map = priorityMap ?? SOURCE_PRECEDENCE;
  return [...rowGroups].sort((groupA, groupB) => {
    const srcA = groupA[0]?._source_files?.[0] ?? "";
    const srcB = groupB[0]?._source_files?.[0] ?? "";
    const prioA = map[srcA] ?? 0;
    const prioB = map[srcB] ?? 0;
    return prioB - prioA; // descending: highest priority first
  });
}

export function mergeRowsByStrategy(rowGroups, strategy, options = {}) {
  const mergedRows = new Map();
  const identifierToNodeId = new Map();
  let nextNodeId = 1;

  // Sort rowGroups so higher-priority sources are processed first. Since
  // mergeRowFields preserves existing non-empty values, this ensures the
  // highest-authority source keeps conflicting scalar fields.
  const sortedGroups = sortRowGroupsByPriority(rowGroups, options.sourcePriorities);

  sortedGroups.forEach((rows) => {
    rows.forEach((row) => {
      const identityKeys = getRowMergeIdentityKeys(row, strategy);
      if (identityKeys.length === 0) {
        const standaloneId = nextNodeId;
        nextNodeId += 1;
        mergedRows.set(standaloneId, {
          ...row,
          _merge_identity_keys: [],
        });
        return;
      }

      const candidateIds = [
        ...new Set(
          identityKeys
            .map((identityKey) => identifierToNodeId.get(identityKey))
            .filter((nodeId) => nodeId !== undefined),
        ),
      ].sort((a, b) => a - b);

      const filteredCandidateIds =
        getMatterIdentityMode(options) === "composite-guard"
          ? filterCandidateIdsForMatterIdentityConsistency(candidateIds, row, mergedRows)
          : candidateIds;

      let targetId;
      if (filteredCandidateIds.length === 0) {
        targetId = nextNodeId;
        nextNodeId += 1;
        const created = {
          ...row,
          _merge_identity_keys: [...identityKeys],
        };
        if (isMdnsRecord(created)) updateMdnsAliases(created, created);
        mergedRows.set(targetId, created);
      } else {
        targetId = filteredCandidateIds[0];
        const target = mergedRows.get(targetId) || { ...row };
        mergedRows.set(targetId, target);

        if (filteredCandidateIds.length > 1) {
          // Multiple existing nodes resolve to this incoming record — log collision.
          console.warn(
            `[tdash-merge] identity collision: incoming row matches ${filteredCandidateIds.length} existing nodes`,
            { identityKeys, candidateIds: filteredCandidateIds },
          );
        }

        filteredCandidateIds.slice(1).forEach((sourceId) => {
          const source = mergedRows.get(sourceId);
          if (!source) return;
          const existingSource = target._source_files?.[0] ?? "";
          const incomingSource = source._source_files?.[0] ?? "";
          mergeRowFields(
            target,
            source,
            createMergeContext(existingSource, incomingSource, {
              ...options,
              ownerRloc16: getCanonicalRloc16(target),
              partitionId: getPartitionId(target),
              incomingPartitionId: getPartitionId(source),
            }),
          );
          mergedRows.delete(sourceId);
          identifierToNodeId.forEach((mappedId, identityKey) => {
            if (mappedId === sourceId)
              identifierToNodeId.set(identityKey, targetId);
          });
        });

        const existingSource = target._source_files?.[0] ?? "";
        const incomingSource = row._source_files?.[0] ?? "";
        mergeRowFields(
          target,
          row,
          createMergeContext(existingSource, incomingSource, {
            ...options,
            ownerRloc16: getCanonicalRloc16(target),
            partitionId: getPartitionId(target),
            incomingPartitionId: getPartitionId(row),
          }),
        );
        target._merge_identity_keys = mergeStringArrays(
          Array.isArray(target._merge_identity_keys)
            ? target._merge_identity_keys
            : [],
          identityKeys,
        );
      }

      identityKeys.forEach((identityKey) => {
        identifierToNodeId.set(identityKey, targetId);
      });
    });
  });

  return Array.from(mergedRows.values());
}

export function mergeRowsByRloc16(rowGroups, options = {}) {
  return mergeRowsByStrategy(rowGroups, MERGE_STRATEGIES.byRloc16, options);
}

export function mergeRowsByIdentity(rowGroups, options = {}) {
  return mergeRowsByStrategy(rowGroups, MERGE_STRATEGIES.byIdentity, options);
}
