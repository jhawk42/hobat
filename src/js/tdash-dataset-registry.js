import { DATASET_CATALOG_FALLBACK } from "./tdash-catalog-fallback.js";

export { DATASET_CATALOG_FALLBACK };

const RETIRED_HEALTH_DATASET_IDS = new Set([
  "otbr_cli_networkdiag_fetch_all", "otbr_cli_topology_health", "otbr_cli_topology_mdns_health",
  "otbr_restapi_devices_fetch_diagnostics_fetch_all",
  "otbr_restapi_devices_fetch_diagnostics_fetch_all_mesh_diagnostics_fetch_all",
  "otbr_restapi_topology_mdns_health", "merged_otbr_topology_mdns_health",
]);

function requiredSet(vocabulary, name) {
  if (!Array.isArray(vocabulary?.[name]) || vocabulary[name].length === 0) {
    throw new Error(`Dataset catalog requires vocabulary.${name}.`);
  }
  return new Set(vocabulary[name]);
}

function validateUnifiedRecipes(catalog) {
  const known = new Set(catalog.vocabulary.knownFiles);
  const outputs = new Map([
    ["otbr_cli_unified", "td-otbr-cli-unified.json"],
    ["otbr_restapi_unified", "td-otbr-restapi-unified.json"],
    ["ha_matter_ws_unified", "td-ha-matter-ws-unified.json"],
    ["mdns_unified", "td-mdns-unified.json"],
    ["multi_source_unified", "td-merged-unified.json"],
  ]);
  const extractors = new Set(["raw-array", "json-api", "identity", "outcome",
    "ha-inventory", "ha-border-routers", "ha-native-topology", "ha-projection", "unified"]);
  const dependencies = new Map();
  for (const entry of catalog.datasets) {
    const recipe = entry.unified;
    if (recipe === undefined) {
      if (outputs.has(entry.value)) throw new Error(`Missing Unified recipe: ${entry.value}`);
      continue;
    }
    const row = outputs.get(entry.value);
    if (!row || entry.files.length !== 1 || entry.files[0] !== row
      || entry.mergeStrategy !== "none" || entry.rowExtractor !== "raw-array"
      || entry.adaptor !== "unified" || !recipe || typeof recipe !== "object"
      || Array.isArray(recipe)
      || Object.keys(recipe).sort().join() !== "identityFile,inputs,outcomeFile,reportFile,version"
      || recipe.version !== "unified-v1") throw new Error(`Invalid Unified recipe: ${entry.value}`);
    const stem = row.slice(0, -5);
    const expected = {
      reportFile: `${stem}.report.json`,
      outcomeFile: entry.value === "mdns_unified" ? null : `${stem}.outcome.json`,
      identityFile: entry.value === "mdns_unified" ? null
        : entry.value === "ha_matter_ws_unified" ? "td-ha-matter-ws-thread-network-info.json"
          : `${stem}-thread-network-info.json`,
    };
    for (const [key, file] of Object.entries(expected)) {
      if (recipe[key] !== file || (file !== null && !known.has(file))) {
        throw new Error(`Invalid Unified ${key}: ${entry.value}`);
      }
    }
    if (!Array.isArray(recipe.inputs) || recipe.inputs.length === 0) {
      throw new Error(`Missing Unified inputs: ${entry.value}`);
    }
    const ownOutputs = new Set([row, `${stem}.network.json`, ...Object.values(expected)]);
    const seen = new Set();
    const prefix = { "otbr-cli": "td-otbr-cli-", "otbr-restapi": "td-otbr-restapi-",
      "ha-matter-ws": "td-ha-matter-ws-", mdns: "td-mdns-scopes-" }[entry.source];
    for (const item of recipe.inputs) {
      if (!item || typeof item !== "object" || Array.isArray(item)
        || Object.keys(item).sort().join() !== "extractor,file,required,role"
        || typeof item.file !== "string" || !known.has(item.file)
        || /[/\\]/.test(item.file) || seen.has(item.file) || ownOutputs.has(item.file)
        || !["records", "identity", "outcome", "projection"].includes(item.role)
        || typeof item.required !== "boolean" || !extractors.has(item.extractor)
        || (["identity", "outcome"].includes(item.role) && item.extractor !== item.role)
        || (["records", "projection"].includes(item.role) && ["identity", "outcome"].includes(item.extractor))) {
        throw new Error(`Invalid Unified input: ${entry.value}`);
      }
      if (["td-otbr-restapi-actions-list.json", "td-ha-matter-ws-server-info.json",
        "td-ha-matter-ws-thread-diagnostics.json"].includes(item.file)
        || item.file.includes(".partial.") || (prefix && !item.file.startsWith(prefix))
        || (entry.source !== "multi-source" && ["records", "projection"].includes(item.role)
          && (/\.(outcome|report|network)\.json$/.test(item.file) || [...outputs.values()].includes(item.file)))
        || (entry.source === "multi-source"
          && ![...outputs.values(), "td-static-extaddr-device-label.json"].includes(item.file))) {
        throw new Error(`Excluded Unified input: ${item.file}`);
      }
      seen.add(item.file);
    }
    if (!recipe.inputs.some((item) => item.role === "records" && item.required)) {
      throw new Error(`Unified recipe needs required records: ${entry.value}`);
    }
    dependencies.set(row, [...seen]);
  }
  function visit(file, visiting) {
    if (visiting.has(file)) throw new Error("Cyclic Unified inputs");
    for (const dependency of dependencies.get(file) ?? []) {
      visit(dependency, new Set([...visiting, file]));
    }
  }
  for (const file of dependencies.keys()) visit(file, new Set());
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
    if (typeof entry?.value !== "string" || !/^[a-z][a-z0-9_]{0,39}$/.test(entry.value)) {
      throw new Error(`Invalid dataset identifier: ${label}`);
    }
    if (RETIRED_HEALTH_DATASET_IDS.has(entry.value)) {
      throw new Error(`Unsupported retired health dataset: ${label}`);
    }
    if (values.has(entry.value)) {
      throw new Error(`Duplicate dataset value: ${label}`);
    }
    values.add(entry.value);
    if (entry.selectable !== undefined && typeof entry.selectable !== "boolean") {
      throw new Error(`Invalid selectable for ${label}`);
    }
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
  validateUnifiedRecipes(catalog);
  const sources = new Set(catalog.datasources.map((source) => source.value));
  if (sources.size !== catalog.datasources.length ||
      catalog.datasets.some((dataset) => !sources.has(dataset.source))) {
    throw new Error("Dataset catalog has missing or duplicate datasources.");
  }
  const datasets = new Map(catalog.datasets.map((entry) => [entry.value, entry]));
  const aliases = catalog.datasetAliases ?? {};
  if (!aliases || typeof aliases !== "object" || Array.isArray(aliases)) {
    throw new Error("Invalid datasetAliases.");
  }
  for (const [alias, target] of Object.entries(aliases)) {
    if (!alias || datasets.has(alias) || RETIRED_HEALTH_DATASET_IDS.has(alias)
      || typeof target !== "string" || !datasets.has(target) || Object.hasOwn(aliases, target)
      || datasets.get(target).healthEligible === true) {
      throw new Error(`Invalid dataset alias: ${alias}`);
    }
  }
  const sourceAliases = catalog.sourceAliases ?? {};
  if (!sourceAliases || typeof sourceAliases !== "object" || Array.isArray(sourceAliases)
    || Object.entries(sourceAliases).some(([alias, target]) =>
      alias !== "merged" || target !== "multi-source" || sources.has(alias) || !sources.has(target))) {
    throw new Error("Invalid sourceAliases.");
  }
  for (const source of catalog.datasources) {
    for (const key of ["default_dataset_value", "primary_dataset_value"]) {
      if (source[key] === undefined) continue;
      const dataset = datasets.get(source[key]);
      if (!dataset || dataset.source !== source.value || dataset.selectable === false) {
        throw new Error(`Invalid ${key} for ${source.value}`);
      }
    }
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

export function resolveDataset(datasetId, source = null, catalog = currentCatalog) {
  const canonical = catalog.datasetAliases?.[datasetId] ?? datasetId;
  const entry = catalog.datasets.find((dataset) => dataset.value === canonical);
  if (!entry) throw new Error(`Unsupported dataset: ${datasetId}`);
  if (source !== null) {
    const sourceAlias = catalog.sourceAliases?.[source];
    if (sourceAlias && (!Object.hasOwn(catalog.datasetAliases ?? {}, datasetId) || entry.healthEligible === true)) {
      throw new Error(`Unsupported source/dataset pair: ${source}/${datasetId}`);
    }
    if ((sourceAlias ?? source) !== entry.source) {
      throw new Error(`Mismatched source/dataset pair: ${source}/${datasetId}`);
    }
  }
  return entry;
}

export function selectableDatasets(source = null) {
  return DATASET_REGISTRY.filter((entry) => entry.selectable !== false && (!source || entry.source === source));
}