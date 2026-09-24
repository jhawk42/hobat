import { DATASET_CATALOG_FALLBACK } from "./tdash-catalog-fallback.js";

export { DATASET_CATALOG_FALLBACK };

function requiredSet(vocabulary, name) {
  if (!Array.isArray(vocabulary?.[name]) || vocabulary[name].length === 0) {
    throw new Error(`Dataset catalog requires vocabulary.${name}.`);
  }
  return new Set(vocabulary[name]);
}

export function validateDatasetRegistry(registry, vocabulary = DATASET_CATALOG_FALLBACK.vocabulary) {
  if (!Array.isArray(registry)) throw new Error("Dataset registry must be an array.");
  const knownFiles = requiredSet(vocabulary, "knownFiles");
  const mergeStrategies = requiredSet(vocabulary, "mergeStrategies");
  const rowExtractors = requiredSet(vocabulary, "rowExtractors");
  const adaptors = requiredSet(vocabulary, "adaptors");
  const physicsProfiles = requiredSet(vocabulary, "physicsProfiles");
  if (!vocabulary?.valuePrefixBySource || !vocabulary?.requiredExtractorByAdaptor) {
    throw new Error("Dataset catalog requires prefix and adaptor vocabulary.");
  }
  const values = new Set();
  registry.forEach((entry, index) => {
    const label = entry?.value || `entry ${index}`;
    if (!entry?.value || values.has(entry.value)) {
      throw new Error(`Duplicate dataset value: ${label}`);
    }
    values.add(entry.value);
    const valuePrefix = vocabulary.valuePrefixBySource[entry.source];
    if (!valuePrefix || !entry.value.startsWith(valuePrefix)) {
      throw new Error(`Dataset ${label} must begin with its datasource prefix: ${valuePrefix ?? "unknown"}`);
    }
    if (!Array.isArray(entry.files) || entry.files.length === 0) {
      throw new Error(`Dataset ${label} must define a non-empty files array.`);
    }
    entry.files.forEach((file) => {
      if (!knownFiles.has(file)) throw new Error(`Dataset ${label} references unknown file: ${file}`);
    });
    if (!mergeStrategies.has(entry.mergeStrategy)) {
      throw new Error(`Dataset ${label} has unknown merge strategy: ${entry.mergeStrategy}`);
    }
    if (!rowExtractors.has(entry.rowExtractor)) {
      throw new Error(`Dataset ${label} has unknown row extractor: ${entry.rowExtractor}`);
    }
    if (entry.mergeRowExtractors !== undefined) {
      if (!Array.isArray(entry.mergeRowExtractors) || entry.mergeRowExtractors.length !== entry.files.length) {
        throw new Error(`Dataset ${label} must define one merge row extractor per file.`);
      }
      entry.mergeRowExtractors.forEach((extractor) => {
        if (!rowExtractors.has(extractor)) throw new Error(`Dataset ${label} has unknown merge row extractor: ${extractor}`);
      });
    }
    if (!adaptors.has(entry.adaptor)) throw new Error(`Dataset ${label} has unknown adaptor: ${entry.adaptor}`);
    if (!physicsProfiles.has(entry.defaultPhysicsProfile)) {
      throw new Error(`Dataset ${label} has unknown default physics profile: ${entry.defaultPhysicsProfile}`);
    }
    const requiredExtractor = vocabulary.requiredExtractorByAdaptor[entry.adaptor];
    if (requiredExtractor && entry.rowExtractor !== requiredExtractor) {
      throw new Error(`Dataset ${label} has unsupported adaptor/row extractor combination: `
        + `${entry.adaptor}/${entry.rowExtractor}`);
    }
    if (entry.physicsProfile && entry.physicsProfile !== entry.defaultPhysicsProfile) {
      throw new Error(`Dataset ${label} has conflicting physics profile identifiers.`);
    }
  });
  return registry;
}

export function validateDatasetCatalog(catalog) {
  if (catalog?.schemaVersion !== 2 || !Array.isArray(catalog.datasources)) {
    throw new Error("Unsupported dataset catalog schemaVersion or datasources.");
  }
  validateDatasetRegistry(catalog.datasets, catalog.vocabulary);
  const sources = new Set(catalog.datasources.map((source) => source.value));
  if (sources.size !== catalog.datasources.length ||
      catalog.datasets.some((dataset) => !sources.has(dataset.source))) {
    throw new Error("Dataset catalog has missing or duplicate datasources.");
  }
  if (!catalog.authority?.sourceDefaults || !catalog.mergeGroups) {
    throw new Error("Dataset catalog requires authority and merge groups.");
  }
  if (!catalog.rosterPolicy?.fields) throw new Error("Dataset catalog requires roster policy fields.");
  const fieldOverrides = Object.fromEntries(Object.entries(catalog.rosterPolicy.fields).map(([field, policy]) => [
    field, Object.fromEntries(policy.sources.map(({ filename, rank }) => [filename, rank])),
  ]));
  return {
    ...catalog,
    authority: { ...catalog.authority, fieldOverrides,
      freshnessSeconds: Object.fromEntries(Object.entries(catalog.rosterPolicy.fields)
        .map(([field, policy]) => [field, policy.freshnessSeconds])) },
  };
}

let currentCatalog = validateDatasetCatalog(DATASET_CATALOG_FALLBACK);
export let DATASET_REGISTRY = currentCatalog.datasets;
export let DATASOURCE_REGISTRY = currentCatalog.datasources;

export function setDatasetCatalog(catalog) {
  currentCatalog = validateDatasetCatalog(catalog);
  DATASET_REGISTRY = currentCatalog.datasets;
  DATASOURCE_REGISTRY = currentCatalog.datasources;
}

export function getDatasetCatalog() {
  return currentCatalog;
}