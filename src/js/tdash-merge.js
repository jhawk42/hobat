import { MERGE_STRATEGIES, MERGE_IDENTITY_FIELDS, SOURCE_PRECEDENCE } from "./tdash-constants.js";
import {
  toText,
  isPlainObject,
  canonicalIdText,
  getCanonicalRloc16,
  getCanonicalExtaddr,
  getCanonicalOmrIpv6Address,
  normalizeRowMergeAliases,
  formatValue,
} from "./tdash-utils.js";

// ── Row normalisation (used by table renderer + merge strategies) ────────────

export function normalizeRows(rawData, sourceName = "") {
  if (Array.isArray(rawData)) {
    return rawData.map((row, index) => {
      if (isPlainObject(row))
        return withRowProvenance(normalizeRowMergeAliases(row), sourceName);
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

// ── Merge strategy helpers ────────────────────────────────────────────────────

export function normalizeRloc16(value) {
  return canonicalIdText(value);
}

export function getRowMergeIdentityKeys(row, strategy) {
  const keys = [];

  if (strategy === MERGE_STRATEGIES.byIdentity) {
    const extaddr = getCanonicalExtaddr(row);
    const omr_ipv6_addr = getCanonicalOmrIpv6Address(row);
    if (extaddr) keys.push(`extaddr:${extaddr}`);
    if (omr_ipv6_addr) keys.push(`omr_ipv6_addr:${omr_ipv6_addr}`);

    const matterComposite = getMatterFabricNodeIdentity(row);
    if (matterComposite) keys.push(`matter_fabric_node:${matterComposite}`);
  }

  const rloc16 = getCanonicalRloc16(row);
  if (rloc16) keys.push(`rloc16:${rloc16}`);

  return [...new Set(keys)];
}

function isMatterOperationalMdnsRow(row) {
  if (!isPlainObject(row)) return false;
  const scope = toText(row.scope).toLowerCase();
  return scope === "_matter._tcp.local.";
}

function getServiceInfoPropDecodedText(row, key) {
  const props = row?.service_info?.properties;
  if (!isPlainObject(props)) return "";
  const obj = props[key];
  if (!isPlainObject(obj)) return "";
  const decoded = toText(obj.decoded);
  return decoded ? decoded.toLowerCase() : "";
}

function getMatterFabricNodeIdentity(row) {
  if (!isMatterOperationalMdnsRow(row)) return "";
  const fabricId = getServiceInfoPropDecodedText(row, "FabricID_compressed");
  const nodeId = getServiceInfoPropDecodedText(row, "NodeID");
  if (!fabricId || !nodeId) return "";
  return `${fabricId}|${nodeId}`;
}

function filterCandidateIdsForMatterIdentityConsistency(candidateIds, incomingRow, mergedRows) {
  if (!isMatterOperationalMdnsRow(incomingRow)) return candidateIds;

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

export function appendRowConflict(target, path, currentValue, incomingValue) {
  const conflicts = Array.isArray(target._merge_conflicts)
    ? [...target._merge_conflicts]
    : [];
  if (conflicts.length >= 20) {
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
  const baseTs = Number(base?.captured_at_epoch);
  const incomingTs = Number(incoming?.captured_at_epoch);
  const hasBaseTs = Number.isFinite(baseTs);
  const hasIncomingTs = Number.isFinite(incomingTs);

  const mergeMissingFields = (primary, secondary) => {
    const out = { ...primary };
    Object.keys(secondary).forEach((k) => {
      if (k === "service_info") return;
      const pv = out[k];
      const sv = secondary[k];
      if (isEmptyMergeValue(pv) && !isEmptyMergeValue(sv)) {
        out[k] = sv;
      }
    });
    if (isPlainObject(primary.service_info) || isPlainObject(secondary.service_info)) {
      out.service_info = mergeMdnsServiceInfo(
        isPlainObject(primary.service_info) ? primary.service_info : {},
        isPlainObject(secondary.service_info) ? secondary.service_info : {},
        hasBaseTs ? baseTs : undefined,
        hasIncomingTs ? incomingTs : undefined,
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
  const props = row?.service_info?.properties;
  if (!isPlainObject(props)) return "";
  const node = props[key];
  if (!isPlainObject(node)) return "";
  return toText(node.decoded);
}

function updateMdnsAliases(target, row) {
  if (!isPlainObject(target) || !isPlainObject(row)) return;
  const aliasMap = isPlainObject(target._mdns_aliases) ? target._mdns_aliases : {};

  appendUniqueAlias(aliasMap, "name_aliases", row.name);
  appendUniqueAlias(aliasMap, "server_aliases", row.server ?? row?.service_info?.server);
  appendUniqueAlias(
    aliasMap,
    "server_key_aliases",
    toText(row.server_key ?? row?.service_info?.key).toLowerCase(),
  );
  appendUniqueAlias(
    aliasMap,
    "fabric_id_compressed_aliases",
    getServiceInfoPropDecoded(row, "FabricID_compressed"),
  );
  appendUniqueAlias(aliasMap, "node_id_aliases", getServiceInfoPropDecoded(row, "NodeID"));

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

export function mergeRowFields(target, source) {
  mergeMdnsRowIntoTarget(target, source);
  mergeRowMetadata(target, source);
  Object.keys(source).forEach((key) => {
    if (key.startsWith("_")) return;
    // Guard against prototype-pollution keys
    if (key === "__proto__" || key === "constructor" || key === "prototype") return;
    const sv = source[key];
    const tv = target[key];
    if (isEmptyMergeValue(tv) && !isEmptyMergeValue(sv)) {
      target[key] = sv;
    } else if (isPlainObject(tv) && isPlainObject(sv)) {
      deepMergeObjects(tv, sv, key, target);
    } else if (
      !isEmptyMergeValue(tv) &&
      !isEmptyMergeValue(sv) &&
      !areMergeValuesEquivalent(tv, sv)
    ) {
      appendRowConflict(target, key, tv, sv);
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
  const v = row?.partition_id ?? row?.partitionId;
  if (v === undefined || v === null) return undefined;
  const n = typeof v === "number" ? v : parseInt(v, 10);
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
export function mergeChildrenArray(parentRloc16, baseChildren, incomingChildren) {
  const index = new Map();
  const childKey = (child) => {
    const ext = canonicalIdText(child.extAddress ?? child.extaddr);
    if (ext) return `ext:${ext}`;
    const r = canonicalIdText(child.rloc16);
    if (r) return `rloc16:${r}`;
    return null;
  };
  baseChildren.forEach((child) => {
    if (!isPlainObject(child)) return;
    const k = childKey(child);
    if (k) index.set(k, { ...child });
  });
  incomingChildren.forEach((child) => {
    if (!isPlainObject(child)) return;
    const k = childKey(child);
    if (!k) return;
    const existing = index.get(k);
    if (!existing) {
      index.set(k, { ...child });
    } else {
      Object.keys(child).forEach((f) => {
        if (isEmptyMergeValue(existing[f]) && !isEmptyMergeValue(child[f])) {
          existing[f] = child[f];
        }
      });
    }
  });
  return Array.from(index.values());
}

/**
 * Merges two router_neighbors arrays.
 * Identity key: neighbor.extAddress (lowercased) or neighbor.rloc16.
 *
 * @param {Array} baseNeighbors
 * @param {Array} incomingNeighbors
 * @returns {Array}
 */
export function mergeRouterNeighbors(baseNeighbors, incomingNeighbors) {
  const index = new Map();
  const neighborKey = (n) => {
    const ext = canonicalIdText(n.extAddress ?? n.extaddr);
    if (ext) return `ext:${ext}`;
    const r = canonicalIdText(n.rloc16);
    if (r) return `rloc16:${r}`;
    return null;
  };
  baseNeighbors.forEach((n) => {
    if (!isPlainObject(n)) return;
    const k = neighborKey(n);
    if (k) index.set(k, { ...n });
  });
  incomingNeighbors.forEach((n) => {
    if (!isPlainObject(n)) return;
    const k = neighborKey(n);
    if (!k) return;
    const existing = index.get(k);
    if (!existing) {
      index.set(k, { ...n });
    } else {
      Object.keys(n).forEach((f) => {
        if (isEmptyMergeValue(existing[f]) && !isEmptyMergeValue(n[f])) {
          existing[f] = n[f];
        }
      });
    }
  });
  return Array.from(index.values());
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
      if (identityKeys.length === 0) return;

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
        mergedRows.set(targetId, {
          ...row,
          _merge_identity_keys: [...identityKeys],
        });
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
          mergeRowFields(target, source);
          mergedRows.delete(sourceId);
          identifierToNodeId.forEach((mappedId, identityKey) => {
            if (mappedId === sourceId)
              identifierToNodeId.set(identityKey, targetId);
          });
        });

        mergeRowFields(target, row);
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
