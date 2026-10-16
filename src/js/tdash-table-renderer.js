import { DEVICE_DETAILS_SECTIONS, TABLE_PRIORITY_COLUMNS } from "./tdash-constants.js";
import { parseSearchQuery, filterRowsBySearch } from "./tdash-search.js";
import {
  isPlainObject,
  hasNestedPath,
  getColumnValue,
  getPreferredFieldName,
  formatValue,
  flattenObjectEntries,
  shouldExcludeDetailPath,
  sortDetailsWithPriority,
  populateNodeDetailsLists,
  publishDeviceSelection,
} from "./tdash-utils.js";
import {
  computeTableCapabilities,
  updateFilterOptionVisibility,
  isRowVisibleByNodeFilter,
  isRowVisibleByDiagnosticFilter,
} from "./tdash-filters.js";
import { buildDeviceProjections } from "./tdash-device-projection.js";
import { publishViewStatus } from "./tdash-view-status.js";
import { getDeviceIdentityKeys } from "./tdash-device-fields.js";

// ── Module-level table state ──────────────────────────────────────────────────

let _tableRows = [];
let _tableProjectionByRow = new WeakMap();
let _tableRolePolicy;
let _tableColumns = [];
let _tableDatasetLabel = "";
let _tableDatasetToken = null;
let _moreInfoEnabled = false;
let _tableColumnCategory = "all";
let _lastFilteredRows = [];
let _selectedTableRow = null;
let _tableSort = null;
let _tableHealthByDeviceId = new Map();
let _tableHealthObservedAt = "";
let _tableHealthAvailable = false;
let _tableHealthColumnsEnabled = false;
const MORE_INFO_CELL_MAX_LINES = 6;
const MORE_INFO_CELL_MAX_CHARACTERS = 60;
const HEALTH_COLUMNS = ["Health Status", "Health Reason", "Health Observed"];
const TABLE_IDENTITY_COLUMN_PRIORITY = [
  "deviceLabel", 
  "rloc16", 
  "extAddress", 
  "name", 
  "eui", 
  "routerId", 
  "id", 
  "ID",
];
const HEALTH_STATUS_SORT_ORDER = Object.freeze({
  poor: 0,
  moderate: 1,
  strong: 2,
  unknown: 3,
  "not assessed": 4,
});
const TABLE_TEXT_COLLATOR = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

export function setMoreInfoEnabled(val) {
  _moreInfoEnabled = val;
}
export function isMoreInfoEnabled() {
  return _moreInfoEnabled;
}
export function setTableHealthColumnsEnabled(enabled) {
  _tableHealthColumnsEnabled = enabled === true;
  _tableColumns = collectColumns(_tableRows);
}
export function isTableHealthColumnsEnabled() {
  return _tableHealthColumnsEnabled;
}

function categoryLabel(sectionId) {
  const specialLabels = {
    "mdns-list": "mDNS",
    "routes-links-list": "Routes & Links",
  };
  if (specialLabels[sectionId]) return specialLabels[sectionId];
  return sectionId
    .replace(/-list$/, "")
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function getTableColumnCategories(rows = []) {
  return DEVICE_DETAILS_SECTIONS
    .filter((section) => !section.fields.includes("*"))
    .filter((section) => section.fields.some((field) => {
      const preferredField = getPreferredFieldName(field);
      return rows.some((row) => hasNestedPath(row, preferredField));
    }))
    .map((section) => ({ value: section.sectionId, label: categoryLabel(section.sectionId) }));
}

export function setTableColumnCategory(category, rows = _tableRows) {
  _tableColumnCategory = category === "all" || getTableColumnCategories(rows)
    .some(({ value }) => value === category)
    ? category
    : "all";
}

export function getTableColumnsForCategory(rows, category) {
  const section = DEVICE_DETAILS_SECTIONS.find(({ sectionId }) => sectionId === category);
  if (!section || section.fields.includes("*")) return [];
  const identitySection = DEVICE_DETAILS_SECTIONS.find(
    ({ sectionId }) => sectionId === "identity-list",
  );
  const fields = [...(identitySection?.fields ?? []), ...section.fields]
    .map((field) => getPreferredFieldName(field));
  return [...new Set(fields)].filter((field) => rows.some((row) => hasNestedPath(row, field)));
}

export function setTableHealthFindings(findings = [], observedAt = "", available = false) {
  _tableHealthByDeviceId = new Map();
  _tableHealthObservedAt = observedAt;
  _tableHealthAvailable = available === true;
  const severity = { unknown: 0, strong: 1, moderate: 2, poor: 3 };
  findings.forEach((finding) => {
    (finding.deviceIds || []).forEach((deviceId) => {
      const current = _tableHealthByDeviceId.get(deviceId);
      if (!current || severity[finding.status] > severity[current.status]) {
        _tableHealthByDeviceId.set(deviceId, {
          status: finding.status,
          reason: finding.title,
        });
      }
    });
  });
}

function healthForRow(row) {
  const identityKey = getDeviceIdentityKeys(row).find((key) => key.startsWith("extAddress:"));
  const deviceId = identityKey?.replace(/^extAddress:/, "extaddr:");
  return _tableHealthByDeviceId.get(deviceId);
}

function tableCellValue(row, column) {
  const health = healthForRow(row);
  if (column === "Health Status") return health?.status ?? "Not assessed";
  if (column === "Health Reason") return health?.reason ?? "No attributed finding";
  if (column === "Health Observed") return _tableHealthObservedAt || "Not assessed";
  return getColumnValue(row, column);
}

// ── Cell formatting ───────────────────────────────────────────────────────────

function formatCellValue(value, columnName) {
  if (value === null || value === undefined) return "";

  if (columnName === "routes") {
    const routeItems = Array.isArray(value)
      ? value
      : isPlainObject(value)
        ? [value]
        : [];
    if (routeItems.length === 0) return "[]";
    const summaries = routeItems
      .map((route) => {
        if (!isPlainObject(route)) return "";
        const nestedTo = isPlainObject(route.to) ? route.to : null;
        const toName =
          route.to_name ??
          (nestedTo ? (nestedTo.name ?? nestedTo.to_name) : "") ??
          "";
        const toRloc16 =
          route.to_rloc16 ??
          (nestedTo ? (nestedTo.rloc16 ?? nestedTo.to_rloc16) : "") ??
          "";
        if (!toName && !toRloc16) return "";
        return `${toName ? String(toName) : "(no-name)"} (${toRloc16 ? String(toRloc16) : "(no-rloc16)"})`;
      })
      .filter(Boolean);
    return summaries.length > 0 ? summaries.join("\n") : "[]";
  }

  if (Array.isArray(value) || isPlainObject(value)) {
    try {
      return JSON.stringify(value);
    } catch (_e) {
      return String(value);
    }
  }
  return String(value);
}

function truncateMoreInfoCellValue(value, columnName) {
  const text = formatCellValue(value, columnName);
  const visibleLines = text
    .split(/\r?\n/)
    .slice(0, MORE_INFO_CELL_MAX_LINES)
    .join("\n");
  const clipped =
    visibleLines.length > MORE_INFO_CELL_MAX_CHARACTERS
      ? visibleLines.slice(0, MORE_INFO_CELL_MAX_CHARACTERS)
      : visibleLines;
  return clipped === text ? text : `${clipped} ...`;
}

// ── Table cell structured value renderer ────────────────────────────────────

function _isTdScalar(value) {
  return (
    value === null ||
    value === undefined ||
    typeof value !== "object" ||
    (Array.isArray(value) && value.length === 0) ||
    (!Array.isArray(value) && Object.keys(value).length === 0)
  );
}

function _scalarText(value) {
  if (value === null || value === undefined) return "n/a";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

function _createTdKvRow(keyText, value, depth) {
  const li = document.createElement("li");
  // Complex child at depth ≤ 1 gets its own sub-structure
  if (!_isTdScalar(value) && depth <= 1) {
    const keySpan = document.createElement("span");
    keySpan.className = "td-kv-key";
    keySpan.textContent = keyText + ":";
    li.appendChild(keySpan);
    const child = _createTdValueNode(value, depth + 1);
    if (child) li.appendChild(child);
  } else {
    li.className = "td-kv-row";
    const keySpan = document.createElement("span");
    keySpan.className = "td-kv-key";
    keySpan.textContent = keyText + ":";
    const valSpan = document.createElement("span");
    valSpan.className = "td-kv-value";
    if (_isTdScalar(value)) {
      valSpan.textContent =
        value === null || value === undefined
          ? "n/a"
          : Array.isArray(value) && value.length === 0
            ? "[]"
            : typeof value === "object"
              ? "{}"
              : _scalarText(value);
    } else {
      try {
        valSpan.textContent = JSON.stringify(value);
      } catch (_e) {
        valSpan.textContent = "[object]";
      }
    }
    li.appendChild(keySpan);
    li.appendChild(valSpan);
  }
  return li;
}

function _createTdValueNode(value, depth) {
  if (_isTdScalar(value)) return null;

  // Array of primitives
  if (
    Array.isArray(value) &&
    value.every((item) => item === null || typeof item !== "object")
  ) {
    const ul = document.createElement("ul");
    ul.className = "td-value-list";
    value.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item === null ? "null" : String(item);
      ul.appendChild(li);
    });
    return ul;
  }

  // Array of objects/mixed
  if (Array.isArray(value)) {
    const div = document.createElement("div");
    div.className = "td-value-array";
    value.forEach((item, idx) => {
      const idxSpan = document.createElement("span");
      idxSpan.className = "td-array-idx";
      idxSpan.textContent = `[${idx}]`;
      div.appendChild(idxSpan);
      if (item !== null && typeof item === "object" && !Array.isArray(item)) {
        const ul = document.createElement("ul");
        ul.className = "td-value-list";
        Object.entries(item).forEach(([k, v]) => {
          ul.appendChild(_createTdKvRow(k, v, depth));
        });
        div.appendChild(ul);
      } else {
        const span = document.createElement("span");
        span.textContent = item === null ? "null" : String(item);
        div.appendChild(span);
      }
    });
    return div;
  }

  // Plain object
  const ul = document.createElement("ul");
  ul.className = "td-value-list";
  Object.entries(value).forEach(([k, v]) => {
    ul.appendChild(_createTdKvRow(k, v, depth));
  });
  return ul;
}

function renderTdContent(td, value, columnName) {
  if (_moreInfoEnabled) {
    td.textContent = truncateMoreInfoCellValue(value, columnName);
    return;
  }
  const content = document.createElement("div");
  content.className = "td-cell-content";
  if (columnName === "routes") {
    content.textContent = formatCellValue(value, columnName);
    td.appendChild(content);
    return;
  }
  if (_isTdScalar(value)) {
    content.textContent =
      value === null || value === undefined
        ? ""
        : typeof value === "boolean"
          ? value ? "true" : "false"
          : String(value);
    td.appendChild(content);
    return;
  }
  const node = _createTdValueNode(value, 0);
  if (node) content.appendChild(node);
  td.appendChild(content);
}

// ── Column collection ─────────────────────────────────────────────────────────

function insertHealthColumns(columns) {
  const ordered = [...new Set(columns)].filter((column) => !HEALTH_COLUMNS.includes(column));
  if (!_tableHealthColumnsEnabled || !_tableHealthAvailable) return ordered;
  const labelIndex = ordered.indexOf("deviceLabel");
  const euiIndex = ordered.indexOf("eui");
  const insertAt = labelIndex >= 0 ? labelIndex + 1 : euiIndex >= 0 ? euiIndex : ordered.length;
  ordered.splice(insertAt, 0, ...HEALTH_COLUMNS);
  return ordered;
}

export function collectColumns(rows) {
  const columns = [];
  const seen = new Set();
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => {
      const preferred = getPreferredFieldName(key);
      if (!seen.has(preferred)) {
        seen.add(preferred);
        columns.push(preferred);
      }
    });
  });
  const primaryIdentityColumn = TABLE_IDENTITY_COLUMN_PRIORITY.find((column) =>
    columns.includes(column) && rows.some((row) => getDeviceIdentityKeys(row).length > 0
      && tableCellValue(row, column) !== null
      && tableCellValue(row, column) !== undefined
      && String(tableCellValue(row, column)).trim() !== ""));
  const pinned = [...new Set(TABLE_PRIORITY_COLUMNS.map(getPreferredFieldName))].filter(
    (col) => seen.has(col) || rows.some((row) => hasNestedPath(row, col)),
  );
  const remaining = columns.filter((col) => !pinned.includes(col));
  return insertHealthColumns([
    ...(primaryIdentityColumn ? [primaryIdentityColumn] : []),
    ...pinned,
    ...remaining,
  ]);
}

// ── Column width calculation ──────────────────────────────────────────────────

function calculateColumnMaxLength(rows, column) {
  let max = column.length;
  rows.forEach((row) => {
    const val = formatCellValue(tableCellValue(row, column), column);
    if (val) {
      val.split("\n").forEach((line) => {
        max = Math.max(max, line.length);
      });
    }
  });
  return max;
}

function getColumnWidthStyle(maxLen) {
  const charPx = 8.8;
  const paddingH = 20; // 10px left + 10px right padding (box-sizing: border-box)
  const minWidth = 70;
  const maxChars = 28;
  const maxWidth = maxChars * charPx + paddingH;
  const width = maxLen >= maxChars ? maxWidth : Math.max(maxLen * charPx + paddingH, minWidth);
  return { width: `${width}px` };
}

function isMissingSortValue(value, column) {
  if (value === null || value === undefined) return true;
  if (typeof value !== "string") return false;
  const normalized = value.trim().toLowerCase();
  if (column === "Health Status" && Object.hasOwn(HEALTH_STATUS_SORT_ORDER, normalized)) {
    return false;
  }
  return normalized === "" || ["unknown", "absent", "n/a", "not assessed", "—", "-"].includes(normalized);
}

function parseSortableAddress(value, column) {
  if (typeof value !== "string") return null;
  let address = value.trim().toLowerCase().replace(/^(?:extaddr|eui|ipv6):/, "");
  if (!address) return null;
  if (/^(?:rloc16|eui|extaddress|extendedaddress)$/i.test(column)) {
    address = address.replace(/^0x/, "").replaceAll(":", "").replaceAll("-", "");
    if (/^[0-9a-f]{1,32}$/.test(address)) return BigInt(`0x${address}`);
  }
  address = address.replace(/^\[|\]$/g, "").split("%", 1)[0].split("/", 1)[0];
  if (/^\d{1,3}(?:\.\d{1,3}){3}$/.test(address)) {
    const octets = address.split(".").map(Number);
    if (octets.every((octet) => octet <= 255)) {
      return octets.reduce((result, octet) => (result << 8n) | BigInt(octet), 0n);
    }
    return null;
  }
  if (!address.includes(":")) return null;
  const ipv4Match = address.match(/(?:^|:)(\d{1,3}(?:\.\d{1,3}){3})$/);
  if (ipv4Match) {
    const octets = ipv4Match[1].split(".").map(Number);
    if (!octets.every((octet) => octet <= 255)) return null;
    const ipv4Hex = octets.map((octet) => octet.toString(16).padStart(2, "0")).join("");
    address = `${address.slice(0, -ipv4Match[1].length)}${ipv4Hex.slice(0, 4)}:${ipv4Hex.slice(4)}`;
  }
  if ((address.match(/::/g) || []).length > 1) return null;
  const halves = address.split("::");
  const left = halves[0] ? halves[0].split(":") : [];
  const right = halves.length === 2 && halves[1] ? halves[1].split(":") : [];
  const missingGroups = 8 - left.length - right.length;
  if ((halves.length === 1 && missingGroups !== 0) || (halves.length === 2 && missingGroups < 1)) {
    return null;
  }
  const groups = [...left, ...Array(missingGroups).fill("0"), ...right];
  if (groups.length !== 8 || groups.some((group) => !/^[0-9a-f]{1,4}$/.test(group))) {
    return null;
  }
  return groups.reduce((result, group) => (result << 16n) | BigInt(`0x${group}`), 0n);
}

function compareVersionValues(left, right) {
  const leftParts = String(left).match(/\d+|[^\d]+/g) || [];
  const rightParts = String(right).match(/\d+|[^\d]+/g) || [];
  for (let index = 0; index < Math.max(leftParts.length, rightParts.length); index += 1) {
    if (leftParts[index] === undefined) return -1;
    if (rightParts[index] === undefined) return 1;
    const leftNumber = /^\d+$/.test(leftParts[index]);
    const rightNumber = /^\d+$/.test(rightParts[index]);
    const comparison = leftNumber && rightNumber
      ? (BigInt(leftParts[index]) < BigInt(rightParts[index]) ? -1
        : BigInt(leftParts[index]) > BigInt(rightParts[index]) ? 1 : 0)
      : TABLE_TEXT_COLLATOR.compare(leftParts[index], rightParts[index]);
    if (comparison) return comparison;
  }
  return 0;
}

function compareTableValues(left, right, column) {
  if (isMissingSortValue(left, column) || isMissingSortValue(right, column)) {
    return isMissingSortValue(left, column) === isMissingSortValue(right, column)
      ? 0
      : isMissingSortValue(left, column) ? 1 : -1;
  }
  if (column === "Health Status") {
    const leftRank = HEALTH_STATUS_SORT_ORDER[String(left).trim().toLowerCase()];
    const rightRank = HEALTH_STATUS_SORT_ORDER[String(right).trim().toLowerCase()];
    if (leftRank !== undefined && rightRank !== undefined) return leftRank - rightRank;
  }
  if (typeof left === "boolean" && typeof right === "boolean") return Number(left) - Number(right);
  if (column.toLowerCase().includes("version")) return compareVersionValues(left, right);
  const normalizedColumn = column.toLowerCase().replaceAll(/[._\s-]/g, "");
  const addressColumn = /(?:address|ipv6|eui|rloc16|mleid|^ip$)/.test(normalizedColumn);
  if (addressColumn || (String(left).includes(":") && String(right).includes(":"))) {
    const leftAddress = parseSortableAddress(String(left), column);
    const rightAddress = parseSortableAddress(String(right), column);
    if (leftAddress !== null && rightAddress !== null) {
      return leftAddress < rightAddress ? -1 : leftAddress > rightAddress ? 1 : 0;
    }
  }
  const timestampColumn = /(?:time|date|observed|updated|created|timestamp)/i.test(column);
  if (timestampColumn) {
    const leftTimestamp = typeof left === "number" ? left : Date.parse(String(left));
    const rightTimestamp = typeof right === "number" ? right : Date.parse(String(right));
    if (Number.isFinite(leftTimestamp) && Number.isFinite(rightTimestamp)) {
      return leftTimestamp - rightTimestamp;
    }
  }
  const leftNumber = typeof left === "number" ? left
    : typeof left === "string" && /^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(left.trim())
      ? Number(left) : null;
  const rightNumber = typeof right === "number" ? right
    : typeof right === "string" && /^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(right.trim())
      ? Number(right) : null;
  if (leftNumber !== null && rightNumber !== null) return leftNumber - rightNumber;
  const leftText = typeof left === "object" ? JSON.stringify(left) : String(left);
  const rightText = typeof right === "object" ? JSON.stringify(right) : String(right);
  return TABLE_TEXT_COLLATOR.compare(leftText, rightText);
}

function tableIdentitySortKey(row) {
  return getDeviceIdentityKeys(row).sort().join("|").toLowerCase();
}

function sortedTableRows(rows) {
  if (!_tableSort) return rows;
  const { column, direction } = _tableSort;
  const multiplier = direction === "ascending" ? 1 : -1;
  return [...rows].sort((left, right) => {
    const leftValue = tableCellValue(left, column);
    const rightValue = tableCellValue(right, column);
    const leftMissing = isMissingSortValue(leftValue, column);
    const rightMissing = isMissingSortValue(rightValue, column);
    if (leftMissing !== rightMissing) return leftMissing ? 1 : -1;
    const primary = compareTableValues(leftValue, rightValue, column);
    if (primary) return primary * multiplier;
    return TABLE_TEXT_COLLATOR.compare(tableIdentitySortKey(left), tableIdentitySortKey(right));
  });
}

// ── DOM table builder ─────────────────────────────────────────────────────────

function selectTableRow(row, tableRow) {
  const tbodyEl = document.querySelector("#data-table tbody");
  const previous = tbodyEl.querySelector("tr.selected-row");
  if (previous) previous.classList.remove("selected-row");
  tableRow.classList.add("selected-row");
  const summaryListEl = document.getElementById("summary-list");
  const details = sortDetailsWithPriority(
    flattenObjectEntries(row).filter(([key]) => !shouldExcludeDetailPath(key, "table")),
  );
  if (details.length === 0) {
    _selectedTableRow = null;
    publishDeviceSelection(null, { direct: true });
    if (summaryListEl) summaryListEl.innerHTML = "<li>No details available for selected row.</li>";
    return;
  }
  _selectedTableRow = row;
  publishDeviceSelection(row, { direct: true });
  if (summaryListEl) summaryListEl.innerHTML = "";
  populateNodeDetailsLists(details);
}

function identityColumnForRow(row, columns) {
  if (getDeviceIdentityKeys(row).length === 0) return null;
  const firstColumn = columns[0];
  if (TABLE_IDENTITY_COLUMN_PRIORITY.includes(firstColumn)
      && tableCellValue(row, firstColumn) !== null
      && tableCellValue(row, firstColumn) !== undefined
      && String(tableCellValue(row, firstColumn)).trim() !== "") {
    return firstColumn;
  }
  return TABLE_IDENTITY_COLUMN_PRIORITY.find((column) => columns.includes(column)
    && tableCellValue(row, column) !== null && tableCellValue(row, column) !== undefined
    && String(tableCellValue(row, column)).trim() !== "") ?? null;
}

function renderTableRows(rows, columns, isSearchActive = false, selectedRow = null) {
  const theadEl = document.querySelector("#data-table thead");
  const tbodyEl = document.querySelector("#data-table tbody");
  const tableEl = document.querySelector("#data-table");
  const hasIdentityColumn = TABLE_IDENTITY_COLUMN_PRIORITY.includes(columns[0]);
  if (tableEl) {
    if (hasIdentityColumn) tableEl.dataset.identityColumn = columns[0];
    else delete tableEl.dataset.identityColumn;
  }
  theadEl.innerHTML = "";
  tbodyEl.innerHTML = "";

  const columnWidths = new Map();
  columns.forEach((col) =>
    columnWidths.set(
      col,
      getColumnWidthStyle(calculateColumnMaxLength(rows, col)),
    ),
  );

  const headRow = document.createElement("tr");
  columns.forEach((col) => {
    const th = document.createElement("th");
    th.scope = "col";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "table-sort-button";
    button.dataset.sortColumn = col;
    button.textContent = col;
    button.title = `Sort by ${col}`;
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const direction = _tableSort?.column === col && _tableSort.direction === "ascending"
        ? "descending"
        : "ascending";
      _tableSort = { column: col, direction };
      applyTableFilters({ preserveSelection: true });
    });
    if (_tableSort?.column === col) {
      th.setAttribute("aria-sort", _tableSort.direction);
      const icon = document.createElement("span");
      icon.className = "table-sort-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = _tableSort.direction === "ascending" ? "▲" : "▼";
      button.appendChild(icon);
    }
    th.appendChild(button);
    Object.assign(th.style, columnWidths.get(col));
    headRow.appendChild(th);
  });
  theadEl.appendChild(headRow);

  const fragment = document.createDocumentFragment();
  rows.forEach((row, idx) => {
    const tr = document.createElement("tr");
    tr.dataset.rowIndex = idx;
    if (isSearchActive) tr.classList.add("search-match");
    if (row === selectedRow) tr.classList.add("selected-row");
    const identityColumn = identityColumnForRow(row, columns);
    columns.forEach((col) => {
      const td = document.createElement("td");
      const value = tableCellValue(row, col);
      if (col === identityColumn) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "table-identity-action";
        button.title = `View details for ${formatCellValue(value, col)}`;
        button.setAttribute("aria-label", `View details for ${formatCellValue(value, col)}`);
        renderTdContent(button, value, col);
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          selectTableRow(row, tr);
        });
        td.appendChild(button);
      } else {
        renderTdContent(td, value, col);
      }
      if (col === "Health Status") {
        const statusClass = String(value).toLowerCase().replaceAll(" ", "-");
        td.className = `table-health-status state-${statusClass}`;
      }
      Object.assign(td.style, columnWidths.get(col));
      tr.appendChild(td);
    });
    tr.addEventListener("click", () => {
      selectTableRow(_lastFilteredRows[idx] ?? row, tr);
    });
    fragment.appendChild(tr);
  });
  tbodyEl.appendChild(fragment);
}

// ── Filter + render pipeline ──────────────────────────────────────────────────

export function getTableFilterLabel(select, fallback) {
  return select?.selectedOptions?.[0]?.text ?? fallback;
}

function updateTableStatus(visibleRowCount, columnCount, totalFilteredCount, searchQuery) {
  const nodeFilterEl = document.getElementById("node-filter");
  const diagFilterEl = document.getElementById("diagnostic-filter");
  const nodeLabel = getTableFilterLabel(nodeFilterEl, "All nodes");
  const diagLabel = getTableFilterLabel(diagFilterEl, "All diagnostics");
  const fetchStatusEl = document.getElementById("fetch-status-line-content");
  const fetchStatusPinnedUntil = window.tdashDebug?.fetchStatusPinnedUntil ?? 0;
  const isFetchStatusPinned = Date.now() < fetchStatusPinnedUntil;
  if (fetchStatusEl && !isFetchStatusPinned) {
    fetchStatusEl.textContent = `Loaded: ${_tableDatasetLabel}`;
  }
  let statusText =
    `Total: ${_tableRows.length} rows, ${_tableColumns.length} columns. ` +
    `Showing: ${visibleRowCount} rows, ${columnCount} columns. Node Filter: ${nodeLabel}. Diagnostic Filter: ${diagLabel}.`;
  if (searchQuery) {
    statusText += ` Search: "${searchQuery}" — ${visibleRowCount} of ${totalFilteredCount} rows match.`;
  }
  statusText += " Activate a column header button to sort; empty values sort last and health status follows severity order.";
  publishViewStatus("table", statusText, _tableDatasetToken);
}

export function applyTableFilters({ preserveSelection = false } = {}) {
  const focusedSortColumn = document.activeElement?.dataset?.sortColumn;
  const nodeMode = document.getElementById("node-filter").value;
  const diagMode = document.getElementById("diagnostic-filter").value;
  const searchQuery = parseSearchQuery(
    document.getElementById("search-input")?.value ?? "",
  );
  const filtered = _tableRows.filter(
    (row) =>
      isRowVisibleByNodeFilter(row, nodeMode, _tableRolePolicy) &&
      isRowVisibleByDiagnosticFilter(row, diagMode, _tableProjectionByRow.get(row)),
  );
  const { matchingRows } = filterRowsBySearch(filtered, searchQuery, _moreInfoEnabled);
  const sortedRows = sortedTableRows(matchingRows);
  _lastFilteredRows = sortedRows;
  const selectedRow = preserveSelection && sortedRows.includes(_selectedTableRow)
    ? _selectedTableRow
    : null;
  if (preserveSelection && !selectedRow) _selectedTableRow = null;
  if (!preserveSelection) _selectedTableRow = null;
  const selectedColumns = _tableColumnCategory === "all"
    ? (_moreInfoEnabled ? _tableColumns : TABLE_PRIORITY_COLUMNS)
    : getTableColumnsForCategory(_tableRows, _tableColumnCategory);
  const activeColumns = insertHealthColumns(
    selectedColumns.filter((column) => _tableColumns.includes(column)),
  );
  const detailsListEl = document.getElementById("details-list");
  if (detailsListEl) detailsListEl.innerHTML = "";
  const summaryListEl = document.getElementById("summary-list");
  if (summaryListEl)
    summaryListEl.innerHTML = "<li>Click a node or row to view its properties.</li>";
  if (preserveSelection) {
    publishDeviceSelection(selectedRow);
  } else {
    publishDeviceSelection(null);
  }
  renderTableRows(sortedRows, activeColumns, searchQuery !== "", selectedRow);
  if (focusedSortColumn) {
    const activeSortButton = Array.from(
      document.querySelectorAll("#data-table thead button.table-sort-button"),
    ).find((button) => button.dataset.sortColumn === focusedSortColumn);
    activeSortButton?.focus({ preventScroll: true });
  }
  updateTableStatus(sortedRows.length, activeColumns.length, filtered.length, searchQuery);

  if (selectedRow && sortedRows.includes(selectedRow)) {
    const details = sortDetailsWithPriority(
      flattenObjectEntries(selectedRow).filter(
        ([key]) => !shouldExcludeDetailPath(key, "table"),
      ),
    );
    if (details.length > 0) {
      if (summaryListEl) summaryListEl.innerHTML = "";
      populateNodeDetailsLists(details);
    }
  }

  // Auto-select and populate device details when exactly one row matches the search
  if (searchQuery && matchingRows.length === 1) {
    const tbodyEl = document.querySelector("#data-table tbody");
    const firstRow = tbodyEl?.querySelector("tr");
    if (firstRow) {
      firstRow.classList.add("selected-row");
      const rawRow = _lastFilteredRows[0];
      publishDeviceSelection(rawRow);
      const details = sortDetailsWithPriority(
        flattenObjectEntries(rawRow).filter(
          ([key]) => !shouldExcludeDetailPath(key, "table"),
        ),
      );
      if (details.length > 0) {
        if (summaryListEl) summaryListEl.innerHTML = "";
        populateNodeDetailsLists(details);
      }
    }
  }
}

export function findTableRowByDeviceId(rows, deviceId) {
  const targetAddress = deviceId?.replace(/^extaddr:/i, "").toLowerCase();
  if (!targetAddress) return null;
  let matchingRow = null;
  for (const row of rows) {
    const identity = getDeviceIdentityKeys(row).find((key) => key.startsWith("extAddress:"));
    if (identity?.slice("extAddress:".length) !== targetAddress) continue;
    if (matchingRow) return null;
    matchingRow = row;
  }
  return matchingRow;
}

export function selectTableDeviceById(deviceId) {
  const row = findTableRowByDeviceId(_lastFilteredRows, deviceId);
  if (!row) return false;
  const rowIndex = _lastFilteredRows.indexOf(row);
  const tbodyEl = document.querySelector("#data-table tbody");
  const renderedRow = Array.from(tbodyEl?.querySelectorAll("tr") || []).find(
    (candidate) => Number(candidate.dataset.rowIndex) === rowIndex,
  );
  if (!renderedRow) return false;
  const previous = tbodyEl.querySelector("tr.selected-row");
  if (previous) previous.classList.remove("selected-row");
  renderedRow.classList.add("selected-row");
  renderedRow.tabIndex = -1;
  renderedRow.focus({ preventScroll: true });
  _selectedTableRow = row;
  const details = sortDetailsWithPriority(
    flattenObjectEntries(row).filter(([key]) => !shouldExcludeDetailPath(key, "table")),
  );
  if (details.length === 0) {
    _selectedTableRow = null;
    publishDeviceSelection(null, { direct: true });
    const summaryListEl = document.getElementById("summary-list");
    if (summaryListEl) summaryListEl.innerHTML = "<li>No details available for selected row.</li>";
    return false;
  }
  const summaryListEl = document.getElementById("summary-list");
  if (summaryListEl) summaryListEl.innerHTML = "";
  publishDeviceSelection(row, { direct: true });
  populateNodeDetailsLists(details);
  return true;
}

export function renderTableForDataset(dataset, statusDatasetToken = dataset) {
  const healthAssessment = dataset.healthAssessment;
  const hasMatchingHealthAssessment = dataset.entry?.healthEligible === true &&
    healthAssessment?.datasetId === dataset.entry.value;
  setTableHealthFindings(
    hasMatchingHealthAssessment
      ? (healthAssessment.findingGroups || []).flatMap((group) => group.findings || [])
      : [],
    hasMatchingHealthAssessment ? healthAssessment.observedAt : "",
    hasMatchingHealthAssessment,
  );
  const rows = dataset.rows;
  const columns = collectColumns(rows);

  _tableRows = rows;
  _tableRolePolicy = dataset.rolePolicy;
  _tableColumns = columns;
  _selectedTableRow = null;
  _tableSort = null;
  _tableDatasetLabel = dataset.loadedFiles.join(", ");
  _tableDatasetToken = statusDatasetToken;

  // ── compute and apply dynamic filter option visibility ────────
  _tableProjectionByRow = new WeakMap();
  const projections = [...(
    dataset.deviceProjections
      ?? buildDeviceProjections(rows, { rolePolicy: dataset.rolePolicy })
  ).values()];
  rows.forEach((row, index) => {
    const projection = projections[index];
    _tableProjectionByRow.set(row, projection);
  });
  const capabilities = computeTableCapabilities(rows, projections);
  dataset.capabilities = capabilities;
  updateFilterOptionVisibility(capabilities, "table");

  applyTableFilters();
}
