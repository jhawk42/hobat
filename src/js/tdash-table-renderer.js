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
import { publishViewStatus } from "./tdash-view-status.js";
import { getDeviceIdentityKeys } from "./tdash-device-fields.js";

// ── Module-level table state ──────────────────────────────────────────────────

let _tableRows = [];
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
const MORE_INFO_CELL_MAX_LINES = 6;
const MORE_INFO_CELL_MAX_CHARACTERS = 60;
const HEALTH_COLUMNS = ["Health Status", "Health Reason", "Health Observed"];

export function setMoreInfoEnabled(val) {
  _moreInfoEnabled = val;
}
export function isMoreInfoEnabled() {
  return _moreInfoEnabled;
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

export function getTableColumnCategories() {
  return DEVICE_DETAILS_SECTIONS
    .filter((section) => !section.fields.includes("*"))
    .map((section) => ({ value: section.sectionId, label: categoryLabel(section.sectionId) }));
}

export function setTableColumnCategory(category) {
  _tableColumnCategory = getTableColumnCategories().some(({ value }) => value === category)
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

export function setTableHealthFindings(findings = [], observedAt = "") {
  _tableHealthByDeviceId = new Map();
  _tableHealthObservedAt = observedAt;
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
  if (columnName === "routes") {
    td.textContent = formatCellValue(value, columnName);
    return;
  }
  if (_isTdScalar(value)) {
    td.textContent =
      value === null || value === undefined
        ? ""
        : typeof value === "boolean"
          ? value ? "true" : "false"
          : String(value);
    return;
  }
  const node = _createTdValueNode(value, 0);
  if (node) td.appendChild(node);
}

// ── Column collection ─────────────────────────────────────────────────────────

export function collectColumns(rows) {
  const columns = [];
  const seen = new Set();
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => {
      if (!seen.has(key)) {
        seen.add(key);
        columns.push(key);
      }
    });
  });
  const healthColumns = _tableHealthByDeviceId.size > 0 ? HEALTH_COLUMNS : [];
  const pinned = [...new Set(TABLE_PRIORITY_COLUMNS)].filter(
    (col) => seen.has(col) || rows.some((row) => hasNestedPath(row, col)),
  );
  const remaining = columns.filter((col) => !pinned.includes(col));
  return [...healthColumns, ...pinned, ...remaining];
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

function sortedTableRows(rows) {
  if (!_tableSort) return rows;
  const { column, direction } = _tableSort;
  const multiplier = direction === "ascending" ? 1 : -1;
  return [...rows].sort((left, right) => {
    const leftText = formatCellValue(tableCellValue(left, column), column);
    const rightText = formatCellValue(tableCellValue(right, column), column);
    const numericDifference = Number(leftText) - Number(rightText);
    const comparison = Number.isNaN(numericDifference)
      ? leftText.localeCompare(rightText)
      : numericDifference;
    return comparison * multiplier;
  });
}

// ── DOM table builder ─────────────────────────────────────────────────────────

function renderTableRows(rows, columns, isSearchActive = false, selectedRow = null) {
  const theadEl = document.querySelector("#data-table thead");
  const tbodyEl = document.querySelector("#data-table tbody");
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
    th.textContent = col;
    if (_tableSort?.column === col) th.setAttribute("aria-sort", _tableSort.direction);
    th.addEventListener("click", (event) => {
      event.stopPropagation();
      const direction = _tableSort?.column === col && _tableSort.direction === "ascending"
        ? "descending"
        : "ascending";
      _tableSort = { column: col, direction };
      applyTableFilters({ preserveSelection: true });
    });
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
    columns.forEach((col) => {
      const td = document.createElement("td");
      renderTdContent(td, tableCellValue(row, col), col);
      if (col === "Health Status") {
        const statusClass = String(tableCellValue(row, col)).toLowerCase().replaceAll(" ", "-");
        td.className = `table-health-status state-${statusClass}`;
      }
      Object.assign(td.style, columnWidths.get(col));
      tr.appendChild(td);
    });
    tr.addEventListener("click", () => {
      const prev = tbodyEl.querySelector("tr.selected-row");
      if (prev) prev.classList.remove("selected-row");
      tr.classList.add("selected-row");
      const summaryListEl = document.getElementById("summary-list");
      const rawRow = _lastFilteredRows[idx] ?? row;
      _selectedTableRow = rawRow;
      publishDeviceSelection(rawRow);
      const details = sortDetailsWithPriority(
        flattenObjectEntries(rawRow).filter(
          ([key]) => !shouldExcludeDetailPath(key, "table"),
        ),
      );
      if (details.length === 0) {
        if (summaryListEl)
          summaryListEl.innerHTML =
            "<li>No details available for selected row.</li>";
        return;
      }
      if (summaryListEl) summaryListEl.innerHTML = "";
      populateNodeDetailsLists(details);
    });
    fragment.appendChild(tr);
  });
  tbodyEl.appendChild(fragment);

  // Re-initialise SortableJS after replacing table content
  if (window.Sortable && typeof window.Sortable.init === "function") {
    window.Sortable.init();
  }
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
  statusText += " Click a header to sort.";
  publishViewStatus("table", statusText, _tableDatasetToken);
}

export function applyTableFilters({ preserveSelection = false } = {}) {
  const nodeMode = document.getElementById("node-filter").value;
  const diagMode = document.getElementById("diagnostic-filter").value;
  const searchQuery = parseSearchQuery(
    document.getElementById("search-input")?.value ?? "",
  );
  const filtered = _tableRows.filter(
    (row) =>
      isRowVisibleByNodeFilter(row, nodeMode) &&
      isRowVisibleByDiagnosticFilter(row, diagMode),
  );
  const { matchingRows } = filterRowsBySearch(filtered, searchQuery, _moreInfoEnabled);
  const sortedRows = sortedTableRows(matchingRows);
  _lastFilteredRows = sortedRows;
  const selectedRow = preserveSelection ? _selectedTableRow : null;
  if (!preserveSelection) _selectedTableRow = null;
  const activeColumns = _tableColumnCategory === "all"
    ? (_moreInfoEnabled
      ? _tableColumns
      : [...HEALTH_COLUMNS, ...TABLE_PRIORITY_COLUMNS]
        .filter((col) => _tableColumns.includes(col)))
    : getTableColumnsForCategory(_tableRows, _tableColumnCategory);
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

export function renderTableForDataset(dataset, statusDatasetToken = dataset) {
  if (dataset.healthAssessment) {
    setTableHealthFindings(
      (dataset.healthAssessment.findingGroups || []).flatMap(
        (group) => group.findings || [],
      ),
      dataset.healthAssessment.observedAt,
    );
  }
  const rows = dataset.rows;
  const columns = collectColumns(rows);

  _tableRows = rows;
  _tableColumns = columns;
  _selectedTableRow = null;
  _tableSort = null;
  _tableDatasetLabel = dataset.loadedFiles.join(", ");
  _tableDatasetToken = statusDatasetToken;

  // ── compute and apply dynamic filter option visibility ────────
  const capabilities = computeTableCapabilities(rows);
  dataset.capabilities = capabilities;
  updateFilterOptionVisibility(capabilities, "table");

  applyTableFilters();
}
