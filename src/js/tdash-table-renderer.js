import { TABLE_PRIORITY_COLUMNS } from './tdash-constants.js';
import { isPlainObject, hasNestedPath, getColumnValue, formatValue, flattenObjectEntries, shouldExcludeDetailPath, sortDetailsWithPriority } from './tdash-utils.js';
import {
  computeTableCapabilities, updateFilterOptionVisibility,
  isRowVisibleByNodeFilter, isRowVisibleByDiagnosticFilter
} from './tdash-filters.js';

// ── Module-level table state ──────────────────────────────────────────────────

let _tableRows = [];
let _tableColumns = [];
let _tableDatasetLabel = '';
let _moreInfoEnabled = false;
let _lastFilteredRows = [];

export function setMoreInfoEnabled(val) { _moreInfoEnabled = val; }
export function isMoreInfoEnabled() { return _moreInfoEnabled; }

// ── Cell formatting ───────────────────────────────────────────────────────────

function formatCellValue(value, columnName) {
  if (value === null || value === undefined) return '';

  if (columnName === 'routes') {
    const routeItems = Array.isArray(value) ? value : (isPlainObject(value) ? [value] : []);
    if (routeItems.length === 0) return '[]';
    const summaries = routeItems.map((route) => {
      if (!isPlainObject(route)) return '';
      const nestedTo = isPlainObject(route.to) ? route.to : null;
      const toName = route.to_name ?? (nestedTo ? nestedTo.name ?? nestedTo.to_name : '') ?? '';
      const toRloc16 = route.to_rloc16 ?? (nestedTo ? nestedTo.rloc16 ?? nestedTo.to_rloc16 : '') ?? '';
      if (!toName && !toRloc16) return '';
      return `${toName ? String(toName) : '(no-name)'} (${toRloc16 ? String(toRloc16) : '(no-rloc16)'})`;
    }).filter(Boolean);
    return summaries.length > 0 ? summaries.join('\n') : '[]';
  }

  if (Array.isArray(value) || isPlainObject(value)) {
    try { return JSON.stringify(value); } catch (_e) { return String(value); }
  }
  return String(value);
}

// ── Column collection ─────────────────────────────────────────────────────────

function collectColumns(rows) {
  const columns = [];
  const seen = new Set();
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => {
      if (!seen.has(key)) { seen.add(key); columns.push(key); }
    });
  });
  const pinned = TABLE_PRIORITY_COLUMNS.filter(
    (col) => seen.has(col) || rows.some((row) => hasNestedPath(row, col))
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
      val.split('\n').forEach((line) => { max = Math.max(max, line.length); });
    }
  });
  return max;
}

function getColumnWidthStyle(maxLen) {
  const charPx = 8.8;
  const minWidth = 70;
  const maxWidth = 25 * charPx;
  const width = maxLen >= 25 ? maxWidth : Math.max(maxLen * charPx, minWidth);
  return { width: `${width}px` };
}

// ── DOM table builder ─────────────────────────────────────────────────────────

function renderTableRows(rows, columns) {
  const theadEl = document.querySelector('#data-table thead');
  const tbodyEl = document.querySelector('#data-table tbody');
  theadEl.innerHTML = '';
  tbodyEl.innerHTML = '';

  const columnWidths = new Map();
  columns.forEach((col) => columnWidths.set(col, getColumnWidthStyle(calculateColumnMaxLength(rows, col))));

  const headRow = document.createElement('tr');
  columns.forEach((col) => {
    const th = document.createElement('th');
    th.textContent = col;
    Object.assign(th.style, columnWidths.get(col));
    headRow.appendChild(th);
  });
  theadEl.appendChild(headRow);

  const fragment = document.createDocumentFragment();
  rows.forEach((row, idx) => {
    const tr = document.createElement('tr');
    tr.dataset.rowIndex = idx;
    columns.forEach((col) => {
      const td = document.createElement('td');
      td.textContent = formatCellValue(getColumnValue(row, col), col);
      Object.assign(td.style, columnWidths.get(col));
      tr.appendChild(td);
    });
    tr.addEventListener('click', () => {
      const prev = tbodyEl.querySelector('tr.selected-row');
      if (prev) prev.classList.remove('selected-row');
      tr.classList.add('selected-row');
      const detailsListEl = document.getElementById('table-details-list');
      if (!detailsListEl) return;
      detailsListEl.innerHTML = '';
      const rawRow = _lastFilteredRows[idx] ?? row;
      const details = sortDetailsWithPriority(
        flattenObjectEntries(rawRow).filter(([key]) => !shouldExcludeDetailPath(key, 'table'))
      );
      if (details.length === 0) {
        detailsListEl.innerHTML = '<li>No details available for selected row.</li>';
        return;
      }
      details.forEach(([key, value]) => {
        const li = document.createElement('li');
        li.textContent = `${key}: ${formatValue(value)}`;
        detailsListEl.appendChild(li);
      });
    });
    fragment.appendChild(tr);
  });
  tbodyEl.appendChild(fragment);

  // Re-initialise SortableJS after replacing table content
  if (window.Sortable && typeof window.Sortable.init === 'function') {
    window.Sortable.init();
  }
}

// ── Filter + render pipeline ──────────────────────────────────────────────────

function updateTableStatus(visibleRowCount, columnCount) {
  const nodeFilterEl = document.getElementById('node-filter');
  const diagFilterEl = document.getElementById('diagnostic-filter');
  const nodeLabel = nodeFilterEl.options[nodeFilterEl.selectedIndex].text;
  const diagLabel = diagFilterEl.options[diagFilterEl.selectedIndex].text;
  document.getElementById('status').textContent =
    `Loaded ${_tableDatasetLabel}. Total: ${_tableRows.length} rows, ${_tableColumns.length} columns. `
    + `Showing: ${visibleRowCount} rows, ${columnCount} columns. Node Filter: ${nodeLabel}. Diagnostic Filter: ${diagLabel}. `
    + `Click a header to sort.`;
}

export function applyTableFilters() {
  const nodeMode = document.getElementById('node-filter').value;
  const diagMode = document.getElementById('diagnostic-filter').value;
  const filtered = _tableRows.filter(
    (row) => isRowVisibleByNodeFilter(row, nodeMode) && isRowVisibleByDiagnosticFilter(row, diagMode)
  );
  _lastFilteredRows = filtered;
  const activeColumns = _moreInfoEnabled
    ? _tableColumns
    : TABLE_PRIORITY_COLUMNS.filter((col) => _tableColumns.includes(col));
  const detailsListEl = document.getElementById('table-details-list');
  if (detailsListEl) detailsListEl.innerHTML = '<li>Click a row to view its properties.</li>';
  renderTableRows(filtered, activeColumns);
  updateTableStatus(filtered.length, activeColumns.length);
}

export function renderTableForDataset(dataset) {
  const rows = dataset.rows;
  const columns = collectColumns(rows);

  _tableRows = rows;
  _tableColumns = columns;
  _tableDatasetLabel = dataset.loadedFiles.join(', ');

  // ── Phase 5.2: compute and apply dynamic filter option visibility ────────
  const capabilities = computeTableCapabilities(rows);
  dataset.capabilities = capabilities;
  updateFilterOptionVisibility(capabilities, 'table');

  applyTableFilters();
}
