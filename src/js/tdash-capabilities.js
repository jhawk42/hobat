import { trackedFetch } from "./tdash-activity.js";

const AVAILABLE_SOURCE_STATES = new Set(["available", "cached", "live"]);

export const EMPTY_CAPABILITIES = Object.freeze({
  sources: Object.freeze({}),
  files: Object.freeze({}),
});

export async function loadSourceCapabilities() {
  const response = await trackedFetch("/api/capabilities");
  if (!response.ok) {
    throw new Error(`Capability request failed (${response.status})`);
  }
  const payload = await response.json();
  if (!payload || typeof payload !== "object"
    || !payload.sources || typeof payload.sources !== "object"
    || !payload.files || typeof payload.files !== "object") {
    throw new Error("Capability response is invalid");
  }
  return payload;
}

export function sourceIsAvailable(source, capabilities) {
  return AVAILABLE_SOURCE_STATES.has(capabilities?.sources?.[source]?.state);
}

export function isFileCached(filename, capabilities) {
  return capabilities?.files?.[filename]?.cached === true;
}

export function datasetIsAvailable(entry, capabilities) {
  if (entry.unified) {
    return entry.files.every((filename) => {
      const file = capabilities?.files?.[filename];
      return file?.cached === true || file?.buildableFromCache === true;
    });
  }
  if (!sourceIsAvailable(entry.source, capabilities)) return false;
  return entry.files.every((filename) => {
    const file = capabilities?.files?.[filename];
    return file?.cached === true || file?.source
      && sourceIsAvailable(file.source, capabilities);
  });
}

export function sourceHasAvailableDatasets(source, capabilities, entries) {
  return sourceIsAvailable(source, capabilities) || entries.some((entry) =>
    entry.source === source && entry.selectable !== false && entry.unified
    && datasetIsAvailable(entry, capabilities));
}