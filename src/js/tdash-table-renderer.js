import { TABLE_PRIORITY_COLUMNS } from "./tdash-constants.js";
import { parseSearchQuery, filterRowsBySearch } from "./tdash-search.js";
import {
  isPlainObject,
  hasNestedPath,
  getColumnValue,
  formatValue,
  flattenObjectEntries,
  shouldExcludeDetailPath,
  sortDetailsWithPriority,
  populateNodeDetailsLists,
} from "./tdash-utils.js";
import {
  computeTableCapabilities,
  updateFilterOptionVisibility,
  isRowVisibleByNodeFilter,
  isRowVisibleByDiagnosticFilter,
} from "./tdash-filters.js";

// ── Module-level table state ──────────────────────────────────────────────────

let _tableRows = [];
let _tableColumns = [];
let _tableDatasetLabel = "";
let _moreInfoEnabled = false;
let _lastFilteredRows = [];

export function setMoreInfoEnabled(val) {
  _moreInfoEnabled = val;
}
export function isMoreInfoEnabled() {
  return _moreInfoEnabled;
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

function collectColumns(rows) {
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
  const pinned = TABLE_PRIORITY_COLUMNS.filter(
    (col) => seen.has(col) || rows.some((row) => hasNestedPath(row, col)),
  );
  const remaining = columns.filter((col) => !pinned.includes(col));
  return [...pinned, ...remaining];
}

// ── Column width calculation ──────────────────────────────────────────────────

function calculateColumnMaxLength(rows, column) {
  let max = column.length;
  rows.forEach((row) => {
    const val = formatCellValue(getColumnValue(row, column), column);
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

// ── DOM table builder ─────────────────────────────────────────────────────────

function renderTableRows(rows, columns, isSearchActive = false) {
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
    Object.assign(th.style, columnWidths.get(col));
    headRow.appendChild(th);
  });
  theadEl.appendChild(headRow);

  const fragment = document.createDocumentFragment();
  rows.forEach((row, idx) => {
    const tr = document.createElement("tr");
    tr.dataset.rowIndex = idx;
    if (isSearchActive) tr.classList.add("search-match");
    columns.forEach((col) => {
      const td = document.createElement("td");
      renderTdContent(td, getColumnValue(row, col), col);
      Object.assign(td.style, columnWidths.get(col));
      tr.appendChild(td);
    });
    tr.addEventListener("click", () => {
      const prev = tbodyEl.querySelector("tr.selected-row");
      if (prev) prev.classList.remove("selected-row");
      tr.classList.add("selected-row");
      const summaryListEl = document.getElementById("summary-list");
      const rawRow = _lastFilteredRows[idx] ?? row;
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

function updateTableStatus(visibleRowCount, columnCount, totalFilteredCount, searchQuery) {
  const nodeFilterEl = document.getElementById("node-filter");
  const diagFilterEl = document.getElementById("diagnostic-filter");
  const nodeLabel = nodeFilterEl.options[nodeFilterEl.selectedIndex].text;
  const diagLabel = diagFilterEl.options[diagFilterEl.selectedIndex].text;
  const fetchStatusEl = document.getElementById("fetch-status-line-content");
  if (fetchStatusEl) fetchStatusEl.textContent = `Loaded: ${_tableDatasetLabel}`;
  let statusText =
    `Total: ${_tableRows.length} rows, ${_tableColumns.length} columns. ` +
    `Showing: ${visibleRowCount} rows, ${columnCount} columns. Node Filter: ${nodeLabel}. Diagnostic Filter: ${diagLabel}.`;
  if (searchQuery) {
    statusText += ` Search: "${searchQuery}" — ${visibleRowCount} of ${totalFilteredCount} rows match.`;
  }
  statusText += " Click a header to sort.";
  document.getElementById("view-status-line-content").textContent = statusText;
}

export function applyTableFilters() {
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
  _lastFilteredRows = matchingRows;
  const activeColumns = _moreInfoEnabled
    ? _tableColumns
    : TABLE_PRIORITY_COLUMNS.filter((col) => _tableColumns.includes(col));
  const detailsListEl = document.getElementById("details-list");
  if (detailsListEl) detailsListEl.innerHTML = "";
  const summaryListEl = document.getElementById("summary-list");
  if (summaryListEl)
    summaryListEl.innerHTML = "<li>Click a node or row to view its properties.</li>";
  renderTableRows(matchingRows, activeColumns, searchQuery !== "");
  updateTableStatus(matchingRows.length, activeColumns.length, filtered.length, searchQuery);

  // Auto-select and populate device details when exactly one row matches the search
  if (searchQuery && matchingRows.length === 1) {
    const tbodyEl = document.querySelector("#data-table tbody");
    const firstRow = tbodyEl?.querySelector("tr");
    if (firstRow) {
      firstRow.classList.add("selected-row");
      const rawRow = _lastFilteredRows[0];
      const details = sortDetailsWithPriority(
        flattenObjectEntries(rawRow).filter(
          ([key]) => !shouldExcludeDetailPath(key, "table"),
        ),
      );
      if (details.length > 0) {
        if (summaryListEl) summaryListEl.innerHTML = "";
        populateNodeDetailsLists(details, "table-");
      }
    }
  }
}

export function renderTableForDataset(dataset) {
  const rows = dataset.rows;
  const columns = collectColumns(rows);

  _tableRows = rows;
  _tableColumns = columns;
  _tableDatasetLabel = dataset.loadedFiles.join(", ");

  // ── compute and apply dynamic filter option visibility ────────
  const capabilities = computeTableCapabilities(rows);
  dataset.capabilities = capabilities;
  updateFilterOptionVisibility(capabilities, "table");

  applyTableFilters();
}
