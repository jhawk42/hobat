import { TABLE_PRIORITY_COLUMNS } from "./tdash-constants.js";
import { toText, getColumnValue, isPlainObject } from "./tdash-utils.js";

// ── Search target fields (normal mode) ────────────────────────────────────────

/**
 * Device record fields that are searchable in normal (non-advanced) search mode.
 * 
 * This is a curated subset of TABLE_PRIORITY_COLUMNS containing fields that are
 * most meaningful for user-initiated searches: identity fields, addresses, device
 * roles, and version information.
 * 
 * **Field Categories:**
 * - **Identity & Addresses** - Core identifiers like rloc16, extaddr, device_label, routerId
 * - **Device Type & Role** - Role, type, br, leader, isBorderRouter
 * - **Versions** - Thread stack version, software version
 * - **Other** - mode.device, scope, status
 * 
 * **Usage:**
 * - Normal mode search (`advancedMode === false`) checks only these fields
 * - Advanced mode search (`advancedMode === true`) checks all fields in the record
 * - Search is case-insensitive and supports partial matches
 * 
 * **Field Naming:**
 * - Includes both snake_case (CLI) and camelCase (REST API) variants
 * - Examples: extaddr/extAddress, omr_ipv6_addr/omrIpv6Address, thread_stack_version/threadStackVersion
 * - Both variants are searchable to support all dataset types
 * 
 * @type {Readonly<string[]>}
 * @constant
 * @see {@link TABLE_PRIORITY_COLUMNS} for complete field list
 */
export const SEARCH_TARGET_FIELDS = Object.freeze([
  // === Identity & Addresses ===
  "rloc16",
  "extaddr",
  "extAddress",
  "eui64",
  "device_label",
  "name",
  "room",
  "ID",
  "Extended MAC",
  "routerId",
  "router_id",
  "omr_ipv6_addr",
  "omrIpv6Address",
  "mlEidIid",
  
  // === Device Type & Role ===
  "type",
  "Role",
  "br",
  "isBorderRouter",
  "leader",
  "isLeader",
  
  // === Versions ===
  "ver",
  "version",
  "thread_version",
  "thread_stack_version",
  "threadStackVersion",
  
  // === Other ===
  "mode.device",
  "scope",
  "status",
  "vendor_name",
  "vendorName"  
]);

// ── Query normalisation ────────────────────────────────────────────────────────

/**
 * Normalises raw query text: trims whitespace and lowercases.
 * Returns an empty string when the input is blank.
 *
 * @param {string} queryText
 * @returns {string}
 */
export function parseSearchQuery(queryText) {
  if (typeof queryText !== "string") return "";
  return queryText.trim().toLowerCase();
}

// ── Row matching ───────────────────────────────────────────────────────────────

/**
 * Returns a stringified representation of a field value suitable for
 * case-insensitive substring matching.
 *
 * @param {*} value
 * @returns {string}
 */
function _fieldToSearchText(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value).toLowerCase();
    } catch (_e) {
      return "";
    }
  }
  return toText(value).toLowerCase();
}

/**
 * Tests whether a single row matches the normalised query string.
 *
 * In normal mode (`advancedMode === false`) only `SEARCH_TARGET_FIELDS` are
 * checked. In advanced mode all own keys present on the row object are checked.
 *
 * Dot-path fields (e.g. `"mode.device"`) are resolved via `getColumnValue`.
 *
 * @param {object} row           - Plain JS row object from `currentDataset.rows`.
 * @param {string} query         - Normalised (lowercase, trimmed) query string.
 * @param {boolean} advancedMode - When true, scan all row keys.
 * @returns {boolean}
 */
export function rowMatchesSearch(row, query, advancedMode = false) {
  if (!query) return true;
  if (!isPlainObject(row)) return false;

  if (advancedMode) {
    // Scan every own key, including nested objects
    for (const key of Object.keys(row)) {
      const value = row[key];
      if (_fieldToSearchText(value).includes(query)) return true;
      // One level of dot-path isn't needed here since we traverse all keys,
      // but for nested plain objects check one level down as well.
      if (isPlainObject(value)) {
        for (const subKey of Object.keys(value)) {
          if (_fieldToSearchText(value[subKey]).includes(query)) return true;
        }
      }
    }
    return false;
  }

  // Normal mode: check only SEARCH_TARGET_FIELDS
  for (const field of SEARCH_TARGET_FIELDS) {
    const value = getColumnValue(row, field);
    if (_fieldToSearchText(value).includes(query)) return true;
  }
  return false;
}

// ── Bulk filtering ────────────────────────────────────────────────────────────

/**
 * Filters an array of rows by the normalised query string.
 *
 * When the query is empty/blank all rows are returned (no filtering applied).
 *
 * @param {object[]} rows         - Flat array of row objects.
 * @param {string}   query        - Normalised query from `parseSearchQuery()`.
 * @param {boolean}  advancedMode - Passed through to `rowMatchesSearch()`.
 * @returns {{ matchingRows: object[], matchingIndices: Set<number> }}
 */
export function filterRowsBySearch(rows, query, advancedMode = false) {
  if (!Array.isArray(rows)) return { matchingRows: [], matchingIndices: new Set() };
  if (!query) {
    return {
      matchingRows: rows.slice(),
      matchingIndices: new Set(rows.map((_, i) => i)),
    };
  }

  const matchingRows = [];
  const matchingIndices = new Set();

  for (let i = 0; i < rows.length; i++) {
    if (rowMatchesSearch(rows[i], query, advancedMode)) {
      matchingRows.push(rows[i]);
      matchingIndices.add(i);
    }
  }

  return { matchingRows, matchingIndices };
}
