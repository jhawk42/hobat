import { getDatasetCatalog } from "./tdash-dataset-registry.js";

export function sourceDefaults() {
  return getDatasetCatalog().authority.sourceDefaults;
}

export function sourceRank(filename) {
  return sourceDefaults()[filename] ?? 0;
}

export function fieldRank(field, filename) {
  return getDatasetCatalog().authority.fieldOverrides[field]?.[filename] ?? sourceRank(filename);
}