import { DATASET_REGISTRY } from './tdash-dataset-registry.js';
import { MERGE_STRATEGIES } from './tdash-constants.js';
import {
  toText, isPlainObject, canonicalIdText,
  getCanonicalExtaddr, normalizeDatasetPayload
} from './tdash-utils.js';
import {
  normalizeRows, mergeRowsByRloc16, mergeRowsByIdentity
} from './tdash-merge.js';

// ── Module-level state ────────────────────────────────────────────────────────

// export let — live binding: reassigning currentDataset inside this module
// is immediately visible to all importers (ES module semantics, not a copy).
export let currentDataset = null;

// Map<lowercased-extaddr-string, device_label-string> — loaded at startup
let staticExtaddrLabelMap = new Map();

// ── Enrichment helpers (used by Enhance toggle) ───────────────────────────────

// Returns an enriched copy of a single node/row; original is not mutated.
// Eligible when: no device_label AND no name AND extaddr is present in map.
function enrichNodeWithStaticLabel(node) {
  if (!isPlainObject(node)) return node;
  if (toText(node.device_label) || toText(node.name)) return node;
  // Restapi rows have shape { id, type, attributes: { extAddress, ... } };
  // extAddress lives in attributes, not at the top level.
  let extaddr = getCanonicalExtaddr(node);
  if (!extaddr && isPlainObject(node.attributes)) extaddr = getCanonicalExtaddr(node.attributes);
  if (!extaddr) return node;
  const label = staticExtaddrLabelMap.get(extaddr);
  if (!label) return node;
  return { ...node, device_label: label };
}

// Enriches a flat array of normalised rows (used by table renderer path).
export function enrichRows(rows) {
  return rows.map(enrichNodeWithStaticLabel);
}

// Recursively enriches a raw JSON value, targeting node-like objects.
// Handles plain arrays, objects with .nodes[] (eve_native), .data[] (otbr_restapi),
// and plain node objects directly.
function enrichRawValue(value) {
  if (Array.isArray(value)) {
    return value.map((item) => enrichRawValue(item));
  }
  if (isPlainObject(value)) {
    const enriched = enrichNodeWithStaticLabel(value);
    const result = {};
    Object.keys(enriched).forEach((key) => {
      const child = enriched[key];
      if (Array.isArray(child) || isPlainObject(child)) {
        result[key] = enrichRawValue(child);
      } else {
        result[key] = child;
      }
    });
    return result;
  }
  return value;
}

// Returns a new rawFiles array with enrichment applied to each file's data.
export function enrichRawFiles(rawFiles) {
  return rawFiles.map((file) => (file === null ? null : enrichRawValue(file)));
}

// ── Core fetch helper ─────────────────────────────────────────────────────────

async function fetchJson(path) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
  return response.json();
}

// ── Static label map loader ───────────────────────────────────────────────────

export async function loadStaticLabelMap() {
  try {
    const data = await fetchJson('td-static-extaddr-device-label.json');
    if (Array.isArray(data)) {
      data.forEach((entry) => {
        const key = canonicalIdText(entry?.extaddr);
        const label = toText(entry?.device_label);
        if (key && label) staticExtaddrLabelMap.set(key, label);
      });
    }
  } catch (err) {
    console.warn('td-static-extaddr-device-label.json could not be loaded:', err);
  }
}

// ── Dataset load entry-point ──────────────────────────────────────────────────
//
// Pure data function: fetches files, runs merge strategy, updates currentDataset.
// Does NOT call renderCurrentView — the caller (tdash-ui.js) is responsible for
// rendering after awaiting this function.  This avoids a circular import:
//   tdash-ui.js → loadDataset → renderCurrentView → tdash-ui.js (currentView etc.)

export async function loadDataset(entryValue) {
  const entry = DATASET_REGISTRY.find((e) => e.value === entryValue);
  if (!entry) {
    document.getElementById('status').textContent = `Unknown dataset: ${entryValue}`;
    document.getElementById('device_stats').textContent = 'Devices: 0';
    return;
  }

  const statusEl = document.getElementById('status');
  const deviceStatsEl = document.getElementById('device_stats');
  statusEl.textContent = `Loading ${entry.label}…`;
  deviceStatsEl.textContent = 'Devices: 0';

  // Apply default link-filter for this dataset
  const linkFilterEl = document.getElementById('link-filter');
  if (entry.defaultLinkFilter) {
    linkFilterEl.value = entry.defaultLinkFilter;
  }

  // Fetch all files in parallel (settle so a missing optional file doesn't abort)
  const settled = await Promise.allSettled(entry.files.map((f) => fetchJson(f)));

  const rawFiles = [];
  const loadedFiles = [];
  const failedFiles = [];

  settled.forEach((result, i) => {
    if (result.status === 'fulfilled') {
      rawFiles.push(normalizeDatasetPayload(result.value));
      loadedFiles.push(entry.files[i]);
    } else {
      rawFiles.push(null);
      failedFiles.push(entry.files[i]);
    }
  });

  if (loadedFiles.length === 0) {
    statusEl.textContent = `Error: could not load any file for "${entry.label}". Failed: ${failedFiles.join(', ')}`;
    deviceStatsEl.textContent = 'Devices: 0';
    return;
  }

  // Apply merge strategy to produce a flat rows array for the table renderer
  let rows;
  if (entry.mergeStrategy === MERGE_STRATEGIES.byRloc16) {
    const groups = rawFiles
      .map((d, index) => (d !== null ? normalizeRows(d, entry.files[index]) : null))
      .filter((group) => group !== null);
    rows = mergeRowsByRloc16(groups);
  } else if (entry.mergeStrategy === MERGE_STRATEGIES.byIdentity) {
    const groups = rawFiles
      .map((d, index) => (d !== null ? normalizeRows(d, entry.files[index]) : null))
      .filter((group) => group !== null);
    rows = mergeRowsByIdentity(groups);
  } else {
    // 'none' — for single-file datasets just normalise the first loaded file;
    // multi-file 'none' datasets hand the full rawFiles array to the adaptor
    const firstLoaded = rawFiles.find((d) => d !== null);
    const firstLoadedIndex = rawFiles.findIndex((d) => d !== null);
    // For eve_native files the top-level shape is { version, nodes: [...] };
    // For otbr_restapi files the top-level shape is { data: [...] };
    // extract the inner array so the table renderer shows one row per node.
    const rowSource = (entry.topologyMode === 'eve_native' && firstLoaded && Array.isArray(firstLoaded.nodes))
      ? firstLoaded.nodes
      : (entry.topologyMode === 'otbr_restapi' && firstLoaded && Array.isArray(firstLoaded.data))
      ? firstLoaded.data
      : firstLoaded;
    rows = rowSource !== null ? normalizeRows(rowSource, entry.files[firstLoadedIndex]) : [];
  }

  currentDataset = { entry, rawFiles, rows, loadedFiles };

  // Warn about any files that failed to load but don't hard-fail
  if (failedFiles.length > 0) {
    console.warn('Some dataset files could not be loaded:', failedFiles);
  }
}
