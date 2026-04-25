import { MERGE_STRATEGIES, MERGE_IDENTITY_FIELDS } from "./tdash-constants.js";
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
  const rloc16 = getCanonicalRloc16(row);
  if (rloc16) keys.push(`rloc16:${rloc16}`);

  if (strategy === MERGE_STRATEGIES.byIdentity) {
    const extaddr = getCanonicalExtaddr(row);
    const omrIpv6Address = getCanonicalOmrIpv6Address(row);
    if (extaddr) keys.push(`extaddr:${extaddr}`);
    if (omrIpv6Address) keys.push(`omrIpv6Address:${omrIpv6Address}`);
  }

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

export function appendRowConflict(target, key, currentValue, incomingValue) {
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
      entry.key === key &&
      entry.current === currentText &&
      entry.incoming === incomingText,
  );
  if (!duplicate) {
    conflicts.push({ key, current: currentText, incoming: incomingText });
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
    const sv = source[key];
    const tv = target[key];
    if (isEmptyMergeValue(tv) && !isEmptyMergeValue(sv)) {
      target[key] = sv;
    } else if (
      !isEmptyMergeValue(tv) &&
      !isEmptyMergeValue(sv) &&
      !areMergeValuesEquivalent(tv, sv)
    ) {
      appendRowConflict(target, key, tv, sv);
    }
  });
}

export function mergeRowsByStrategy(rowGroups, strategy) {
  const mergedRows = new Map();
  const identifierToNodeId = new Map();
  let nextNodeId = 1;

  rowGroups.forEach((rows) => {
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

export function mergeRowsByRloc16(rowGroups) {
  return mergeRowsByStrategy(rowGroups, MERGE_STRATEGIES.byRloc16);
}

export function mergeRowsByIdentity(rowGroups) {
  return mergeRowsByStrategy(rowGroups, MERGE_STRATEGIES.byIdentity);
}
