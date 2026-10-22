import { MERGE_STRATEGIES } from "./tdash-constants.js";
import { sourceDefaults } from "./tdash-source-authority.js";
import { getDeviceIdentityKeys, isPlaceholderExtAddress, isPlaceholderDeviceLabel } from "./tdash-device-fields.js";
import {
  toText,
  isPlainObject,
  canonicalIdText,
  getCanonicalRloc16,
  getCanonicalExtaddr,
  getCanonicalOmrIpv6Address,
  normalizeRowMergeAliases,
  normalizeNestedArrayFields,
} from "./tdash-utils.js";

const TLV_SUMMARY_PRIORITY_FIELD = "_tlv_summary_source_priority";

// ── Row normalisation (used by table renderer + merge strategies) ────────────

export function normalizeRows(rawData, sourceName = "") {
  const fieldSource = fieldSourceForFile(sourceName);
  const normalizeRelationships = (row) =>
    normalizeSourceRelationships(row, sourceName, fieldSource);
  if (Array.isArray(rawData)) {
    return rawData.map((row, index) => {
      if (isPlainObject(row)) {
        const normalized = normalizeRelationships(row);
        delete normalized[TLV_SUMMARY_PRIORITY_FIELD];
        return withRowProvenance(normalized, sourceName);
      }
      return withRowProvenance({ row_index: index, value: row }, sourceName);
    });
  }
  if (isPlainObject(rawData)) {
    return Object.keys(rawData).map((key) => {
      const row = rawData[key];
      if (isPlainObject(row)) {
        const normalized = normalizeRowMergeAliases(
          { _row_key: key, ...row },
          { source: fieldSource },
        );
        delete normalized[TLV_SUMMARY_PRIORITY_FIELD];
        return withRowProvenance(
          normalized,
          sourceName,
        );
      }
      return withRowProvenance({ _row_key: key, value: row }, sourceName);
    });
  }
  return [withRowProvenance({ value: rawData }, sourceName)];
}

function fieldSourceForFile(filename) {
  if (filename.startsWith("td-otbr-cli-")) return "cli";
  if (filename.startsWith("td-otbr-restapi-")) return "rest";
  if (filename.startsWith("td-ha-matter-ws-")) return "ha-matter-ws";
  if (filename === "diagnostics.json") return "thread-tools";
  return undefined;
}

function normalizeSourceRelationships(row, sourceName, fieldSource) {
  const normalized = normalizeRowMergeAliases(row, { source: fieldSource });
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

function getMatterFabricNodeIdentity(row) {
  const directKeys = getDeviceIdentityKeys(row, "by-identity")
    .find((key) => key.startsWith("matterFabricNode:"));
  if (directKeys) return directKeys.slice("matterFabricNode:".length);
  return "";
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
  if (Array.isArray(left) && Array.isArray(right)) {
    return left.length === right.length
      && left.every((value, index) => areMergeValuesEquivalent(value, right[index]));
  }
  if (isPlainObject(left) && isPlainObject(right)) {
    return Object.keys(left).length === Object.keys(right).length
      && Object.keys(left).every((key) => Object.hasOwn(right, key)
        && areMergeValuesEquivalent(left[key], right[key]));
  }
  return false;
}

function mergeArrays(existing, incoming) {
  const result = [];
  [...existing, ...incoming].forEach((value) => {
    if (!result.some((item) => areMergeValuesEquivalent(item, value))) result.push(structuredClone(value));
  });
  return result;
}

function fillMissingFields(target, source) {
  Object.entries(source).forEach(([key, value]) => {
    if (isEmptyMergeValue(target[key])) target[key] = structuredClone(value);
    else if (isPlainObject(target[key]) && isPlainObject(value)) fillMissingFields(target[key], value);
  });
}

export function mergeStringArrays(existingValues, incomingValues) {
  const merged = [];
  [...existingValues, ...incomingValues].forEach((value) => {
    const text = typeof value === "string" ? value.trim() : "";
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
  const conflicts = mergeArrays(
    Array.isArray(target._merge_conflicts) ? target._merge_conflicts : [], [],
  ).slice(0, limit);
  if (conflicts.length >= limit) {
    target._merge_conflicts = conflicts;
    return;
  }

  const entry = { path, current: currentValue, incoming: incomingValue };
  const duplicate = conflicts.some(
    (existing) => areMergeValuesEquivalent(existing, entry),
  );
  if (!duplicate) {
    conflicts.push(structuredClone(entry));
  }
  target._merge_conflicts = conflicts;
}

function appendTlvSummaryConflict(target, path, currentValue, incomingValue, limit = 20) {
  appendRowConflict(target, path, currentValue, incomingValue, limit);
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
  if (isPlainObject(source._mdns_aliases)) {
    const aliases = isPlainObject(target._mdns_aliases) ? target._mdns_aliases : {};
    Object.entries(source._mdns_aliases).forEach(([key, values]) => {
      if (Array.isArray(values)) aliases[key] = mergeStringArrays(
        Array.isArray(aliases[key]) ? aliases[key] : [], values,
      );
    });
    target._mdns_aliases = aliases;
  }
  const existingConflicts = Array.isArray(target._merge_conflicts)
    ? target._merge_conflicts
    : [];
  const incomingConflicts = Array.isArray(source._merge_conflicts)
    ? source._merge_conflicts
    : [];
  if (incomingConflicts.length > 0) {
    target._merge_conflicts = mergeArrays(existingConflicts, incomingConflicts).slice(0, 20);
  } else if (existingConflicts.length > 0) {
    target._merge_conflicts = mergeArrays(existingConflicts, []).slice(0, 20);
  }
}

function isMdnsRecord(row) {
  if (!isPlainObject(row)) return false;
  if (typeof (row.recordKey ?? row.record_key) === "string"
    && (row.recordKey ?? row.record_key).includes("|")) return true;
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
  const baseTs = base?.capturedAtEpoch ?? base?.captured_at_epoch;
  const incomingTs = incoming?.capturedAtEpoch ?? incoming?.captured_at_epoch;
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
  const priorities = options.sourcePriorities ?? sourceDefaults();
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
  if (!isPlainObject(existing)) existing = {};
  if (!isPlainObject(incoming)) return { ...existing };
  if (
    context.partitionId !== undefined
    && context.incomingPartitionId !== undefined
    && context.partitionId !== context.incomingPartitionId
  ) return { ...existing };
  const parseSequence = (value) => isEmptyMergeValue(value) ? undefined
    : (Number.isInteger(Number(value)) ? Number(value) : undefined);
  const existingSequence = parseSequence(existing.idSequence ?? existing.id_sequence);
  const incomingSequence = parseSequence(incoming.idSequence ?? incoming.id_sequence);
  const filterContainer = (container) => {
    const result = structuredClone(container);
    if (Array.isArray(result.routeData)) {
      result.routeData = result.routeData.filter((route) => {
        const partition = getPartitionId(route);
        return isPlainObject(route) && (context.partitionId === undefined
          || partition === undefined || partition === context.partitionId);
      });
    }
    return result;
  };
  existing = filterContainer(existing);
  incoming = filterContainer(incoming);
  if (existingSequence === undefined && incomingSequence !== undefined) return incoming;
  if (existingSequence !== undefined && incomingSequence === undefined) return existing;
  if (existingSequence !== undefined && incomingSequence !== undefined) {
    if (isSequenceNewer(incomingSequence, existingSequence)) {
      return incoming;
    }
    if (isSequenceNewer(existingSequence, incomingSequence)) return { ...existing };
  }
  const merged = structuredClone(existing);
  const ambiguous = existingSequence !== undefined && incomingSequence !== undefined
    && ((incomingSequence - existingSequence + 256) % 256) === 128;
  const fields = Object.fromEntries(Object.entries(incoming)
    .filter(([key]) => !["routeData", "idSequence", "id_sequence"].includes(key)));
  fillMissingFields(merged, fields);
  merged.routeData = mergeRouteData(context.ownerRloc16,
    Array.isArray(existing.routeData) ? existing.routeData : [],
    Array.isArray(incoming.routeData) ? incoming.routeData : [],
    { ...context, ambiguousSequence: ambiguous });
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
  powerSources: (existing, incoming, context) => mergePowerSources(existing, incoming, context),
});

export function mergeRowFields(target, source, context = {}) {
  const mergeContext = { ...context, ...matterIdentityMergeState(target, source) };
  mergeMdnsRowIntoTarget(target, source);
  mergeRowMetadata(target, source);
  const tlvSummaryFields = ["tlvRequestValues", "tlvResponseValues"];
  const sourceHasTlvSummaries = tlvSummaryFields.some((key) =>
    Object.prototype.hasOwnProperty.call(source, key));
  const targetHasTlvSummaries = tlvSummaryFields.some((key) =>
    Object.prototype.hasOwnProperty.call(target, key));
  if (sourceHasTlvSummaries) {
    const existingTlvPriority = Number.isInteger(target[TLV_SUMMARY_PRIORITY_FIELD])
      ? target[TLV_SUMMARY_PRIORITY_FIELD]
      : (context.existingPriority ?? 0);
    const incomingTlvPriority = Number.isInteger(source[TLV_SUMMARY_PRIORITY_FIELD])
      ? source[TLV_SUMMARY_PRIORITY_FIELD]
      : (context.incomingPriority ?? 0);
    tlvSummaryFields.forEach((key) => {
      if (
        Object.prototype.hasOwnProperty.call(target, key)
        && Object.prototype.hasOwnProperty.call(source, key)
        && !areMergeValuesEquivalent(target[key], source[key])
      ) {
        appendTlvSummaryConflict(target, key, target[key], source[key], context.conflictLimit ?? 20);
      }
    });
    if (!targetHasTlvSummaries || incomingTlvPriority > existingTlvPriority) {
      tlvSummaryFields.forEach((key) => {
        if (Object.prototype.hasOwnProperty.call(source, key)) target[key] = source[key];
        else delete target[key];
      });
      target[TLV_SUMMARY_PRIORITY_FIELD] = incomingTlvPriority;
    } else if (!Number.isInteger(target[TLV_SUMMARY_PRIORITY_FIELD])) {
      target[TLV_SUMMARY_PRIORITY_FIELD] = existingTlvPriority;
    }
  }
  Object.keys(source).forEach((key) => {
    if (key.startsWith("_")) return;
    // Guard against prototype-pollution keys
    if (key === "__proto__" || key === "constructor" || key === "prototype") return;
    if (tlvSummaryFields.includes(key)) return;
    const sv = source[key];
    const tv = target[key];
    if (key === "matter" && mergeContext.matterIdentityStatus === "mismatch") {
      if (!isEmptyMergeValue(sv) && !areMergeValuesEquivalent(tv, sv)) {
        appendRowConflict(target, key, tv, sv, mergeContext.conflictLimit ?? 20);
      }
      return;
    }
    const handler = MERGE_FIELD_HANDLERS[key];
    if (handler && !isEmptyMergeValue(sv)) {
      target[key] = handler(tv, sv, {
        ...mergeContext,
        conflictTarget: target,
        sourceRecord: source,
        ownerRloc16: context.ownerRloc16 || getCanonicalRloc16(target),
        fieldPath: key,
      });
      return;
    }
    if (key === "ipv6Addresses" && Array.isArray(sv)) {
      target[key] = mergeStringArrays(Array.isArray(tv) ? tv : [], sv);
    } else if (key === "extAddress" && isPlaceholderExtAddress(tv)
      && !isPlaceholderExtAddress(sv) && !isEmptyMergeValue(sv)) {
      target[key] = sv;
    } else if (key === "deviceLabel" && isPlaceholderDeviceLabel(tv)
      && !isPlaceholderDeviceLabel(sv) && !isEmptyMergeValue(sv)) {
      target[key] = sv;
    } else if (isEmptyMergeValue(tv) && !isEmptyMergeValue(sv)) {
      target[key] = sv;
    } else if (isPlainObject(tv) && isPlainObject(sv)) {
      deepMergeObjects(tv, sv, key, target, mergeContext);
    } else if (Array.isArray(tv) && Array.isArray(sv)) {
      target[key] = mergeArrays(tv, sv);
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
  if ((a - b + 256) % 256 === 128) return 0;
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
  const matterIdentityState = ctx.matterIdentityStatus
    ? {}
    : pathPrefix
      ? { matterIdentityStatus: "absent", matterIdentityEnrichmentAllowed: false }
      : matterIdentityMergeState(target, source);
  const mergeContext = {
    ...ctx,
    ...matterIdentityState,
  };
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

    if (
      pathPrefix === "matter"
      && ["matterId", "compressedFabricId", "nodeId"].includes(key)
      && mergeContext.matterIdentityStatus === "mismatch"
    ) {
      return;
    }

    if (fieldPath === "matter.endpoints" && Array.isArray(sv)) {
      if (
        mergeContext.matterIdentityStatus !== "match"
        && !mergeContext.matterIdentityEnrichmentAllowed
      ) {
        appendRowConflict(conflictTarget, fieldPath, tv, sv, ctx.conflictLimit ?? 20);
        return;
      }
      target[key] = mergeMatterEndpointArrays(tv, sv, {
        ...mergeContext,
        conflictTarget,
        fieldPath,
      });
      return;
    }

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
      deepMergeObjects(tv, sv, fieldPath, conflictTarget, mergeContext);
    } else if (Array.isArray(tv) && Array.isArray(sv)) {
      target[key] = mergeArrays(tv, sv);
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
  const routeKey = (route) => {
    const routeId = route.routeId ?? route.id;
    if ((typeof routeId === "number" && Number.isInteger(routeId) && routeId >= 0)
      || (typeof routeId === "string" && /^(?:0x[0-9a-f]+|\d+)$/i.test(routeId.trim()))) return `id:${Number(routeId)}`;
    const sourceId = canonicalIdText(route.sourceId);
    const targetId = canonicalIdText(route.targetId);
    if (sourceId && targetId) return `endpoints:${sourceId}|${targetId}`;
    const extAddress = getCanonicalExtaddr(route);
    const rloc16 = getCanonicalRloc16(route);
    return extAddress && !isPlaceholderExtAddress(extAddress)
      ? `extaddr:${extAddress}` : (rloc16 ? `rloc16:${rloc16}` : '');
  };
  baseRoutes.forEach((route) => {
    if (!isPlainObject(route)) return;
    const key = routeKey(route);
    if (key) index.set(key, structuredClone(route));
  });

  incomingRoutes.forEach((route) => {
    if (!isPlainObject(route)) return;
    const key = routeKey(route);
    if (!key) return;

    // Partition gate: skip when partition IDs are known and differ
    if (ctx.partitionId !== undefined) {
      const routePartition = getPartitionId(route);
      if (routePartition !== undefined && routePartition !== ctx.partitionId) return;
    }

    const existing = index.get(key);
    if (!existing) {
      if (!ctx.ambiguousSequence) index.set(key, structuredClone(route));
      return;
    }

    // Keep whichever entry has the newer id_sequence (RFC 1982)
    const existingSeq = existing.idSequence ?? existing.id_sequence;
    const incomingSeq = route.idSequence ?? route.id_sequence;
    if (incomingSeq !== undefined && (existingSeq === undefined || isSequenceNewer(incomingSeq, existingSeq))) {
      index.set(key, structuredClone(route));
    } else if (existingSeq === incomingSeq || (existingSeq !== undefined
      && incomingSeq !== undefined && compareSequences(existingSeq, incomingSeq) === 0)) {
      fillMissingFields(existing, route);
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
    const ext = getCanonicalExtaddr(source);
    const identity = ext && !isPlaceholderExtAddress(ext)
      ? `extAddress:${ext}` : `rloc16:${getCanonicalRloc16(source)}`;
    const path = `${context.fieldPath || "relationship"}[${identity}]`;
    Object.keys(source).forEach((field) => {
      const replacesPlaceholderExtAddress =
        (field === "extAddress" || field === "extaddr")
        && isPlaceholderExtAddress(target[field])
        && !isPlaceholderExtAddress(source[field]);
      if ((isEmptyMergeValue(target[field]) || replacesPlaceholderExtAddress) && !isEmptyMergeValue(source[field])) {
        target[field] = source[field];
      } else if (isPlainObject(target[field]) && isPlainObject(source[field])) {
        deepMergeObjects(target[field], source[field], `${path}.${field}`,
          context.conflictTarget ?? target, context);
      } else if (Array.isArray(target[field]) && Array.isArray(source[field])) {
        target[field] = mergeArrays(target[field], source[field]);
      } else if (!isEmptyMergeValue(source[field])
        && !areMergeValuesEquivalent(target[field], source[field])) {
        appendRowConflict(context.conflictTarget ?? target, `${path}.${field}`,
          target[field], source[field], context.conflictLimit ?? 20);
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

function matterEndpointId(record) {
  return isPlainObject(record)
    && Number.isInteger(record.endpointId)
    && record.endpointId >= 0
    && record.endpointId < 0xffff
    ? record.endpointId
    : undefined;
}

function matterIdentityMergeState(left, right) {
  const leftIdentity = getMatterFabricNodeIdentity(left);
  const rightIdentity = getMatterFabricNodeIdentity(right);
  if (leftIdentity && rightIdentity) {
    return {
      matterIdentityStatus: leftIdentity === rightIdentity ? "match" : "mismatch",
      matterIdentityEnrichmentAllowed: false,
    };
  }
  return {
    matterIdentityStatus: "absent",
    matterIdentityEnrichmentAllowed: !leftIdentity && Boolean(rightIdentity),
  };
}

function mergeMatterEndpointRecord(target, source, path, context) {
  const setMergeArrays = new Set(["deviceTypes", "serverClusters", "partsList"]);
  Object.keys(source).forEach((key) => {
    if (key === "__proto__" || key === "constructor" || key === "prototype") return;
    const value = source[key];
    const fieldPath = `${path}.${key}`;
    if (!Object.prototype.hasOwnProperty.call(target, key)) {
      target[key] = structuredClone(value);
    } else if (isPlainObject(target[key]) && isPlainObject(value)) {
      mergeMatterEndpointRecord(target[key], value, fieldPath, context);
    } else if (Array.isArray(target[key]) && Array.isArray(value)) {
      if (setMergeArrays.has(key)) {
        target[key] = mergeArrays(target[key], value);
      } else if (!areMergeValuesEquivalent(target[key], value)) {
        appendRowConflict(
          context.conflictTarget ?? target,
          fieldPath,
          target[key],
          value,
          context.conflictLimit ?? 20,
        );
      }
    } else if (!areMergeValuesEquivalent(target[key], value)) {
      appendRowConflict(
        context.conflictTarget ?? target,
        fieldPath,
        target[key],
        value,
        context.conflictLimit ?? 20,
      );
    }
  });
}

function mergeMatterEndpointArrays(existing, incoming, context = {}) {
  const keyed = new Map();
  const unkeyed = [];
  [...(Array.isArray(existing) ? existing : []), ...(Array.isArray(incoming) ? incoming : [])]
    .forEach((record) => {
      const endpointId = matterEndpointId(record);
      if (endpointId === undefined) {
        unkeyed.push(structuredClone(record));
        return;
      }
      const target = keyed.get(endpointId);
      if (!target) {
        keyed.set(endpointId, structuredClone(record));
        return;
      }
      mergeMatterEndpointRecord(
        target,
        record,
        `${context.fieldPath ?? "matterArray"}[endpointId=${endpointId}]`,
        context,
      );
    });
  return [...[...keyed.keys()].sort((a, b) => a - b).map((id) => keyed.get(id)), ...unkeyed];
}

function mergePowerSources(existing, incoming, context) {
  if (!Array.isArray(incoming)) return structuredClone(existing);
  if (
    context.matterIdentityStatus !== "match"
    && !context.matterIdentityEnrichmentAllowed
  ) {
    appendRowConflict(
      context.conflictTarget,
      "powerSources",
      existing,
      incoming,
      context.conflictLimit ?? 20,
    );
    return Array.isArray(existing) ? structuredClone(existing) : [];
  }
  return mergeMatterEndpointArrays(existing, incoming, context);
}

// ── Source precedence sorting (#1) ────────────────────────────────────────────

/**
 * Returns rowGroups sorted highest-priority-first, preserving ties.
 *
 * Each element of `rowGroups` is expected to have at least one row with
 * `_source_files[0]` set by `normalizeRows()`.  The priority map defaults to
 * catalog source defaults but can be overridden via `priorityMap`.
 */
export function sortRowGroupsByPriority(rowGroups, priorityMap) {
  const map = priorityMap ?? sourceDefaults();
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
  const compatible = (left, right) => {
    const values = (row, prefix) => [...new Set([
      ...getDeviceIdentityKeys(row, "by-identity"), ...(row._merge_identity_keys ?? []),
    ])]
      .filter((key) => key.startsWith(prefix));
    const leftExt = values(left, "extAddress:");
    const rightExt = values(right, "extAddress:");
    if (leftExt.length && rightExt.length) {
      return leftExt.some((key) => rightExt.includes(key));
    }
    if (getMatterIdentityMode(options) === "composite-guard") {
      const leftMatter = values(left, "matterFabricNode:");
      const rightMatter = values(right, "matterFabricNode:");
      if (leftMatter.length && rightMatter.length
        && !leftMatter.some((key) => rightMatter.includes(key))) return false;
    }
    return true;
  };

  sortedGroups.forEach((rows) => {
    rows.forEach((rawRow) => {
      const row = structuredClone(rawRow);
      delete row._merge_identity_keys;
      if (Array.isArray(row._merge_conflicts)) {
        row._merge_conflicts = mergeArrays(row._merge_conflicts, []).slice(0, 20);
      }
      const identityKeys = getRowMergeIdentityKeys(row, strategy);
      row._merge_identity_keys = identityKeys;
      const candidatesFor = (keys) => [...new Set(
        keys.flatMap((key) => [...(identifierToNodeId.get(key) ?? [])]),
      )].filter((id) => compatible(mergedRows.get(id), row)).sort((a, b) => a - b);
      let filteredCandidateIds = candidatesFor(
        identityKeys.filter((key) => !key.startsWith("rloc16:")),
      );
      if (!filteredCandidateIds.length) {
        filteredCandidateIds = candidatesFor(identityKeys.filter((key) => key.startsWith("rloc16:")));
      }
      const ambiguous = filteredCandidateIds.some((left, index) =>
        filteredCandidateIds.slice(index + 1).some((right) =>
          !compatible(mergedRows.get(left), mergedRows.get(right))));
      if (ambiguous) {
        console.warn("[tdash-merge] identity ambiguity: retaining incoming row separately",
          { identityKeys, candidateIds: filteredCandidateIds });
        appendRowConflict(row, "_merge_identity_ambiguity",
          filteredCandidateIds.map((id) => mergedRows.get(id)._merge_identity_keys), identityKeys);
        filteredCandidateIds = [];
      }

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
          identifierToNodeId.forEach((owners) => {
            if (owners.delete(sourceId)) owners.add(targetId);
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
        const owners = identifierToNodeId.get(identityKey) ?? new Set();
        owners.add(targetId);
        identifierToNodeId.set(identityKey, owners);
      });
    });
  });

  return Array.from(mergedRows.values()).map((row) => {
    delete row[TLV_SUMMARY_PRIORITY_FIELD];
    return row;
  });
}

export function mergeRowsByRloc16(rowGroups, options = {}) {
  return mergeRowsByStrategy(rowGroups, MERGE_STRATEGIES.byRloc16, options);
}

export function mergeRowsByIdentity(rowGroups, options = {}) {
  return mergeRowsByStrategy(rowGroups, MERGE_STRATEGIES.byIdentity, options);
}
