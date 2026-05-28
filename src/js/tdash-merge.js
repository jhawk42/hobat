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
  }

  const rloc16 = getCanonicalRloc16(row);
  if (rloc16) keys.push(`rloc16:${rloc16}`);

  return [...new Set(keys)];
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

export function mergeRowFields(target, source) {
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
  Object.keys(source).forEach((key) => {
    if (key.startsWith("_")) return;
    // Guard against prototype-pollution keys
    if (key === "__proto__" || key === "constructor" || key === "prototype") return;
    const sv = source[key];
    const tv = target[key];
    const fieldPath = pathPrefix ? `${pathPrefix}.${key}` : key;

    // Special-case known nested arrays with composite-identity merge
    if (key === "route_data" && Array.isArray(sv)) {
      const ownerRloc16 = ctx.ownerRloc16 ?? getCanonicalRloc16(conflictTarget);
      target[key] = mergeRouteData(ownerRloc16, Array.isArray(tv) ? tv : [], sv, ctx);
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
 * Identity key: child.extaddr (lowercased) or child.rloc16.
 *
 * @param {string} parentRloc16
 * @param {Array}  baseChildren
 * @param {Array}  incomingChildren
 * @returns {Array}
 */
export function mergeChildrenArray(parentRloc16, baseChildren, incomingChildren) {
  const index = new Map();
  const childKey = (child) => {
    const ext = canonicalIdText(child.extaddr ?? child.extAddress);
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
 * Identity key: neighbor.extaddr or neighbor.rloc16.
 *
 * @param {Array} baseNeighbors
 * @param {Array} incomingNeighbors
 * @returns {Array}
 */
export function mergeRouterNeighbors(baseNeighbors, incomingNeighbors) {
  const index = new Map();
  const neighborKey = (n) => {
    const ext = canonicalIdText(n.extaddr ?? n.extAddress);
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
    return prioA - prioB; // ascending: lowest priority first
  });
}

export function mergeRowsByStrategy(rowGroups, strategy, options = {}) {
  const mergedRows = new Map();
  const identifierToNodeId = new Map();
  let nextNodeId = 1;

  // Sort rowGroups so that higher-priority sources are processed last (they
  // win on conflicts because mergeRowFields keeps the existing value unless
  // it is empty — so we flip order: lowest priority first as base, highest
  // priority merges on top and wins).
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

      let targetId;
      if (candidateIds.length === 0) {
        targetId = nextNodeId;
        nextNodeId += 1;
        mergedRows.set(targetId, {
          ...row,
          _merge_identity_keys: [...identityKeys],
        });
      } else {
        targetId = candidateIds[0];
        const target = mergedRows.get(targetId) || { ...row };
        mergedRows.set(targetId, target);

        if (candidateIds.length > 1) {
          // Multiple existing nodes resolve to this incoming record — log collision.
          console.warn(
            `[tdash-merge] identity collision: incoming row matches ${candidateIds.length} existing nodes`,
            { identityKeys, candidateIds },
          );
        }

        candidateIds.slice(1).forEach((sourceId) => {
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
