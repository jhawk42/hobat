import { MERGE_IDENTITY_FIELDS } from './tdash-constants.js';

// ── Primitive type helpers ────────────────────────────────────────────────────

export function toText(value) {
  return value === undefined || value === null ? '' : String(value).trim();
}

export function toFiniteNumber(value) {
  if (Number.isFinite(value)) return value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

// ── Canonical identity helpers ────────────────────────────────────────────────

export function canonicalIdText(value) {
  const text = toText(value);
  return text ? text.toLowerCase() : '';
}

export function getCanonicalRloc16(row) {
  return canonicalIdText(row?.[MERGE_IDENTITY_FIELDS.rloc16]);
}

export function getCanonicalExtaddr(row) {
  for (const key of MERGE_IDENTITY_FIELDS.extaddrAliases) {
    const value = canonicalIdText(row?.[key]);
    if (value) return value;
  }
  return '';
}

export function getCanonicalOmrIpv6Address(row) {
  return canonicalIdText(row?.[MERGE_IDENTITY_FIELDS.omrIpv6Address]);
}

// ── Row normalisation helpers ─────────────────────────────────────────────────

export function normalizeRowMergeAliases(row) {
  if (!isPlainObject(row)) return row;
  const normalized = { ...row };
  const extaddr = getCanonicalExtaddr(row);
  const omrIpv6Address = getCanonicalOmrIpv6Address(row);

  if (extaddr) normalized.extaddr = extaddr;
  if (omrIpv6Address) normalized.omrIpv6Address = omrIpv6Address;

  return normalized;
}

export function normalizeDatasetPayload(value) {
  if (Array.isArray(value)) {
    return value.map((item) => normalizeDatasetPayload(item));
  }
  if (isPlainObject(value)) {
    const normalized = normalizeRowMergeAliases(value);
    Object.keys(normalized).forEach((key) => {
      const child = normalized[key];
      if (Array.isArray(child) || isPlainObject(child)) {
        normalized[key] = normalizeDatasetPayload(child);
      }
    });
    return normalized;
  }
  return value;
}

// ── Display formatting helpers ────────────────────────────────────────────────

export function formatValue(value) {
  if (Array.isArray(value)) return value.length === 0 ? '[]' : value.join(', ');
  if (value && typeof value === 'object') {
    try { return JSON.stringify(value); } catch (_e) { return '[object]'; }
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return toText(value) || 'n/a';
}

export function mergeForDisplay(primary, secondary) {
  if (primary === undefined || primary === null) return secondary;
  if (secondary === undefined || secondary === null) return primary;
  if (Array.isArray(primary) && Array.isArray(secondary)) {
    return secondary.length > 0 ? secondary : primary;
  }
  if (isPlainObject(primary) && isPlainObject(secondary)) {
    const merged = {};
    const keys = new Set([...Object.keys(primary), ...Object.keys(secondary)]);
    keys.forEach((key) => { merged[key] = mergeForDisplay(primary[key], secondary[key]); });
    return merged;
  }
  return secondary;
}

export function flattenObjectEntries(value, path = '', entries = []) {
  if (isPlainObject(value)) {
    const keys = Object.keys(value).sort((a, b) => a.localeCompare(b));
    if (keys.length === 0 && path) { entries.push([path, {}]); return entries; }
    keys.forEach((key) => {
      flattenObjectEntries(value[key], path ? `${path}.${key}` : key, entries);
    });
    return entries;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) { entries.push([path, []]); return entries; }
    if (value.every((item) => isPlainObject(item))) {
      value.forEach((item, i) => flattenObjectEntries(item, `${path}[${i}]`, entries));
      return entries;
    }
    entries.push([path, value]);
    return entries;
  }
  entries.push([path || 'value', value]);
  return entries;
}

export function shouldExcludeDetailPath(_path, _context) {
  return false;
}

export function sortDetailsWithPriority(details) {
  const priorityKeys = [
    'rloc16', 'extaddr', 'device_label', 'name', 'type', 'br', 'status', 'icon', 'ver',
    'total_links', 'total_children', 'total_link_3', 'total_link_2', 'total_link_1',
    'router_neighbor_table_count', 'router_child_table_count',
    'mode', 'mode.device', 'omrIpv6Address', 'thread_stack_version',
    'mac_counters.ifinerrors_pct', 'mac_counters.ifouterrors_pct', 'mac_counters.ifindiscards_pct', 'mac_counters.ifoutdiscards_pct',
    'mle_counters.partitionidchanges', 'mle_counters.betterpartitionattachattempts',
    'mle_counters.parentchanges'
  ];
  const priorityIndex = new Map(priorityKeys.map((k, i) => [k, i]));
  return [...details].sort((a, b) => {
    const ap = priorityIndex.has(a[0]) ? priorityIndex.get(a[0]) : Infinity;
    const bp = priorityIndex.has(b[0]) ? priorityIndex.get(b[0]) : Infinity;
    if (ap !== bp) return ap - bp;
    return a[0].localeCompare(b[0]);
  });
}

// ── Node identity comparison ──────────────────────────────────────────────────

export function areNodeIdsEquivalent(a, b) {
  return toText(a).toLowerCase() === toText(b).toLowerCase();
}

// ── Row/column path helpers ───────────────────────────────────────────────────

// Returns true if `row` contains a value at the given dot-separated `path`.
export function hasNestedPath(row, path) {
  if (!path.includes('.')) return Object.prototype.hasOwnProperty.call(row, path);
  let current = row;
  for (const part of path.split('.')) {
    if (!isPlainObject(current) || !Object.prototype.hasOwnProperty.call(current, part)) return false;
    current = current[part];
  }
  return true;
}

// Returns the value at a dot-separated `columnName` path within `row`, or
// `undefined` if any segment is missing.
export function getColumnValue(row, columnName) {
  if (Object.prototype.hasOwnProperty.call(row, columnName)) return row[columnName];
  if (!columnName.includes('.')) return undefined;
  let current = row;
  for (const part of columnName.split('.')) {
    if (!isPlainObject(current) || !Object.prototype.hasOwnProperty.call(current, part)) return undefined;
    current = current[part];
  }
  return current;
}
