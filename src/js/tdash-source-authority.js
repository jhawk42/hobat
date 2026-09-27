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

export function compareFieldAuthority(field, leftFilename, rightFilename) {
  const authority = getDatasetCatalog().authority;
  const fieldOverrides = authority.fieldOverrides[field] ?? {};
  const leftFieldRank = fieldOverrides[leftFilename];
  const rightFieldRank = fieldOverrides[rightFilename];
  if (Number.isFinite(leftFieldRank) && Number.isFinite(rightFieldRank)
      && leftFieldRank !== rightFieldRank) {
    return Math.sign(leftFieldRank - rightFieldRank);
  }
  return Math.sign(sourceRank(leftFilename) - sourceRank(rightFilename));
}