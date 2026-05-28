import { DATASET_REGISTRY } from "./tdash-dataset-registry.js";
import { MERGE_STRATEGIES } from "./tdash-constants.js";
import {
  toText,
  isPlainObject,
  canonicalIdText,
  getCanonicalExtaddr,
  normalizeDatasetPayload,
} from "./tdash-utils.js";
import {
  normalizeRows,
  mergeRowsByRloc16,
  mergeRowsByIdentity,
} from "./tdash-merge.js";

// ── Module-level state ────────────────────────────────────────────────────────

// export let — live binding: reassigning currentDataset inside this module
// is immediately visible to all importers (ES module semantics, not a copy).
export let currentDataset = null;

// Map<lowercased-extaddr-string, device_label-string> — loaded at startup
let staticExtaddrLabelMap = new Map();

// per-file cache-header store (task 3.3)
// Map<filename, { maxAge: number, fetchedAt: number }>
const fileMaxAgeCache = new Map();

// force-fresh flag (DD-1 / task 3.6)
let _forceFresh = false;
// Only cache mode — send max-age = 365 days to use only cached files
let _onlyCache = false;
// delay after job completion before fetching file (for filesystem sync)
const _JOB_COMPLETION_WAIT_MS = 1000; // 1 second
/** When true, all subsequent fetchJson calls send Cache-Control: no-cache. */
export function setForceFresh(enabled) {
  _forceFresh = enabled;
}
/** When true, all subsequent fetchJson calls send Cache-Control: max-age=31536000 (365 days). */
export function setOnlyCache(enabled) {
  _onlyCache = enabled;
}

// ── Enrichment helpers (used by Enhance toggle) ───────────────────────────────

// Returns an enriched copy of a single node/row; original is not mutated.
// Eligible when: no device_label AND no name AND extaddr is present in map.
function enrichNodeWithStaticLabel(node) {
  if (!isPlainObject(node)) return node;
  if (toText(node.device_label) || toText(node.name)) return node;
  // Restapi rows have shape { id, type, attributes: { extAddress, ... } };
  // extAddress lives in attributes, not at the top level.
  let extaddr = getCanonicalExtaddr(node);
  if (!extaddr && isPlainObject(node.attributes))
    extaddr = getCanonicalExtaddr(node.attributes);
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

// accepts optional request headers; returns { data, responseMaxAge }.
// handles HTTP 202 by delegating to pollJobUntilDone.
async function fetchJson(url, requestHeaders = {}) {
  const response = await fetch(url, { headers: requestHeaders });
  if (response.status === 202) {
    const job = await response.json();
    const data = await pollJobUntilDone(job.job_id, job.filename, url, requestHeaders);
    return { data, responseMaxAge: null };
  }
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
  const data = await response.json();
  const ccHeader = response.headers.get("Cache-Control") || "";
  const maxAgeMatch = ccHeader.match(/max-age=(\d+)/);
  const responseMaxAge = maxAgeMatch ? parseInt(maxAgeMatch[1], 10) : null;
  const lastModifiedHeader = response.headers.get("Last-Modified");
  const lastModifiedAt = lastModifiedHeader ? Date.parse(lastModifiedHeader) : null;
  return { data, responseMaxAge, lastModifiedAt };
}

// Polls /api/job/{jobId} every 5 s until done or error.
// On done, fetches /api/data/{filename} (without the original cache-miss headers)
// and returns the JSON payload.
const _JOB_POLL_INTERVAL_MS = 5000;
const _JOB_TIMEOUT_MS = 900_000; // 15 minutes

async function pollJobUntilDone(jobId, filename, originalUrl, originalHeaders) {
  const statusEl = document.getElementById("fetch-status-line-content");
  const startedAt = Date.now();

  while (true) {
    const elapsed = Math.round((Date.now() - startedAt) / 1000);

    if (elapsed * 1000 > _JOB_TIMEOUT_MS) {
      throw new Error(
        `Timed out waiting for ${filename} after ${elapsed}s (job ${jobId})`,
      );
    }

    if (statusEl) {
      statusEl.textContent = `Fetching ${filename}… (${elapsed}s)`;
    }

    await new Promise((resolve) => setTimeout(resolve, _JOB_POLL_INTERVAL_MS));

    const pollResponse = await fetch(`/api/job/${jobId}`);
    if (!pollResponse.ok) {
      throw new Error(
        `/api/job/${jobId} returned HTTP ${pollResponse.status}`,
      );
    }
    const pollBody = await pollResponse.json();

    if (pollBody.status === "done") {
      // Wait briefly for file to be fully written and synced before fetching.
      // This prevents race conditions where the job is marked done but the file
      // hasn't been completely written to disk yet (especially on slower I/O).
      await new Promise((resolve) => setTimeout(resolve, _JOB_COMPLETION_WAIT_MS));

      // Fetch the completed file directly (no force headers — it's now cached).
      const finalResponse = await fetch(`/api/data/${filename}`);
      if (!finalResponse.ok) {
        throw new Error(
          `/api/data/${filename} returned HTTP ${finalResponse.status} after job done`,
        );
      }
      return finalResponse.json();
    }

    if (pollBody.status === "error") {
      throw new Error(
        `Server error generating ${filename}: ${pollBody.detail || "unknown"}`,
      );
    }
    // status === "running" — continue polling
  }
}

// ── Static label map loader ───────────────────────────────────────────────────

export async function loadStaticLabelMap() {
  try {
    const { data } = await fetchJson("/api/data/td-static-extaddr-device-label.json");
    if (Array.isArray(data)) {
      data.forEach((entry) => {
        const key = canonicalIdText(entry?.extaddr);
        const label = toText(entry?.device_label);
        if (key && label) staticExtaddrLabelMap.set(key, label);
      });
    }
  } catch (err) {
    console.warn(
      "td-static-extaddr-device-label.json could not be loaded:",
      err,
    );
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
    document.getElementById("fetch-status-line-content").textContent =
      `Unknown dataset: ${entryValue}`;
    return;
  }

  const statusEl = document.getElementById("fetch-status-line-content");
  const timerEl = document.getElementById("fetch-timetaken-value");
  const progressEl = document.getElementById("fetch-timetaken-progress");
  const estimateActionCostSecs = entry.estimateActionCostSecs ?? "?";
  const initialLabel = entry.label;
  const loadStartTime = Date.now();
  statusEl.textContent = `Loading ${initialLabel}…`;
  if (progressEl) progressEl.value = 0;

  // Set up an interval to update status bar with elapsed time while loading
  const elapsedUpdateInterval = setInterval(() => {
    const elapsed = Math.round((Date.now() - loadStartTime) / 1000);
    statusEl.textContent = `Loading ${initialLabel}…`;
    if (timerEl) timerEl.textContent = `${elapsed} / ${estimateActionCostSecs}s`;
    // Update progress bar with animated progress (cycles 10-90)
    if (progressEl) {
      const progress = 10 + ((elapsed % 8) * 10);
      progressEl.value = Math.min(progress, 90);
    }
  }, 500); // Update every 500ms for smooth counter

  // Apply default link-filter for this dataset
  const linkFilterEl = document.getElementById("link-filter");
  if (entry.defaultLinkFilter) {
    linkFilterEl.value = entry.defaultLinkFilter;
  }

  // fetch via /api/data/{filename} with per-file cache headers.
  const settled = await Promise.allSettled(
    entry.files.map((f) => {
      const reqHeaders = {};
      if (_forceFresh) {
        reqHeaders["Cache-Control"] = "no-cache";
      } else if (_onlyCache) {
        // 365 days in seconds: 365 * 24 * 60 * 60 = 31536000
        reqHeaders["Cache-Control"] = "max-age=31536000";
      } else {
        const cached = fileMaxAgeCache.get(f);
        if (cached) reqHeaders["Cache-Control"] = `max-age=${cached.maxAge}`;
      }
      return fetchJson(`/api/data/${f}`, reqHeaders).then(
        ({ data, responseMaxAge, lastModifiedAt }) => {
          if (responseMaxAge !== null) {
            fileMaxAgeCache.set(f, { maxAge: responseMaxAge, fetchedAt: Date.now(), lastModifiedAt });
          }
          return data;
        },
      );
    }),
  );

  // Clear the elapsed time update interval
  clearInterval(elapsedUpdateInterval);
  const finalElapsed = Math.round((Date.now() - loadStartTime) / 1000);
  if (timerEl) timerEl.textContent = `${finalElapsed}s`;

  const rawFiles = [];
  const loadedFiles = [];
  const failedFiles = [];

  settled.forEach((result, i) => {
    if (result.status === "fulfilled") {
      rawFiles.push(normalizeDatasetPayload(result.value));
      loadedFiles.push(entry.files[i]);
    } else {
      rawFiles.push(null);
      failedFiles.push(entry.files[i]);
    }
  });

  if (loadedFiles.length === 0) {
    statusEl.textContent = `Error: could not load any file for "${entry.label}". Failed: ${failedFiles.join(", ")}`;
    if (progressEl) progressEl.value = 0;
    return;
  }

  // Apply merge strategy to produce a flat rows array for the table renderer
  let rows;
  if (entry.mergeStrategy === MERGE_STRATEGIES.byRloc16) {
    const groups = rawFiles
      .map((d, index) =>
        d !== null ? normalizeRows(d, entry.files[index]) : null,
      )
      .filter((group) => group !== null);
    rows = mergeRowsByRloc16(groups);
  } else if (entry.mergeStrategy === MERGE_STRATEGIES.byIdentity) {
    const groups = rawFiles
      .map((d, index) =>
        d !== null ? normalizeRows(d, entry.files[index]) : null,
      )
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
    const rowSource =
      entry.topologyMode === "eve_native" &&
      firstLoaded &&
      Array.isArray(firstLoaded.nodes)
        ? firstLoaded.nodes
        : entry.topologyMode === "otbr_restapi" &&
            firstLoaded &&
            Array.isArray(firstLoaded.data)
          ? firstLoaded.data
          : firstLoaded;
    rows =
      rowSource !== null
        ? normalizeRows(rowSource, entry.files[firstLoadedIndex])
        : [];
  }

  const fetchDurationMs = Date.now() - loadStartTime;
  // Use the oldest lastModifiedAt across all loaded files (most stale piece of the dataset)
  let oldestLastModifiedAt = null;
  for (const f of loadedFiles) {
    const cached = fileMaxAgeCache.get(f);
    if (cached?.lastModifiedAt != null) {
      if (oldestLastModifiedAt === null || cached.lastModifiedAt < oldestLastModifiedAt) {
        oldestLastModifiedAt = cached.lastModifiedAt;
      }
    }
  }

  currentDataset = { entry, rawFiles, rows, loadedFiles, fetchDurationMs, fileLastModifiedAt: oldestLastModifiedAt };

  // Set progress bar to 100% when fetch completes
  if (progressEl) {
    progressEl.value = progressEl.max;
  }

  // Warn about any files that failed to load but don't hard-fail
  if (failedFiles.length > 0) {
    console.warn("Some dataset files could not be loaded:", failedFiles);
  }
}
