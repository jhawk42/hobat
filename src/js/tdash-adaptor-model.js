import {
  getDeviceIdentityKeys,
  getPreferredFieldPath,
  normalizeInputRecord,
} from "./tdash-device-fields.js";
import {
  HA_MATTER_ROLE_POLICY,
  normalizeHaMatterRoleRecord,
} from "./tdash-ha-matter-ws-roles.js";


function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function normalizeAdaptorRecord(model, record, sourceName) {
  const normalized = normalizeInputRecord(record, { source: sourceName });
  return model.rolePolicy === HA_MATTER_ROLE_POLICY
    ? normalizeHaMatterRoleRecord(normalized, "canonical-only")
    : normalized;
}

const OBSERVED_TOPOLOGY_LINK_FIELDS = [
  "observedTopologyLinks",
  "observedTopologyLinksLq3",
  "observedTopologyLinksLq2",
  "observedTopologyLinksLq1",
];

const RELATIONSHIP_COLLECTIONS = [
  { family: "routes", path: ["route", "routeData"] },
  { family: "routes", path: ["routes"] },
  { family: "routes", path: ["routeTable"] },
  { family: "routerNeighbors", path: ["routerNeighbors"], tableSource: "routerneighbortables" },
  { family: "routerNeighbors", path: ["neighborTable"] },
  { family: "children", path: ["children"] },
  { family: "childTable", path: ["childTable"], tableSource: "routerchildtables" },
  { family: "linkTables", path: ["links1"] },
  { family: "linkTables", path: ["links2"] },
  { family: "linkTables", path: ["links3"] },
];

function getNestedValue(record, path) {
  return path.reduce(
    (value, key) => isPlainObject(value) ? value[key] : undefined,
    record,
  );
}

function hasErrorEnvelope(record) {
  return isPlainObject(record.error) || isPlainObject(record._error);
}

function relationshipCollectionIsSupported(model, record, definition, value) {
  if (!Array.isArray(value)) return false;
  if (!definition.tableSource) {
    if (isPlainObject(record.tableAttempt)) {
      return record.tableAttempt.status === "success";
    }
    return !hasErrorEnvelope(record);
  }

  if (isPlainObject(record.tableAttempt)) {
    return record.tableAttempt.status === "success";
  }
  if (hasErrorEnvelope(record)) return false;
  if (value.length > 0) return true;

  return !model.sourceNames.includes(definition.tableSource);
}

function relationshipFamiliesForRecord(model, record) {
  const families = new Set();
  RELATIONSHIP_COLLECTIONS.forEach((definition) => {
    const value = getNestedValue(record, definition.path);
    if (relationshipCollectionIsSupported(model, record, definition, value)) {
      families.add(definition.family);
    }
  });
  return families;
}

function cloneRelationshipCapabilities(capabilities) {
  return {
    datasetWide: new Set(capabilities?.datasetWide ?? []),
    byDeviceId: new Map(
      [...(capabilities?.byDeviceId ?? new Map())]
        .map(([deviceId, families]) => [deviceId, new Set(families)]),
    ),
  };
}

function registerIndexedTableCapabilities(model, tableIndex, family) {
  if (!(tableIndex instanceof Map)) return;
  tableIndex.forEach((record, ownerRloc16) => {
    if (!isPlainObject(record)) return;
    const canonicalRecord = normalizeInputRecord(record);
    const definition = RELATIONSHIP_COLLECTIONS.find((candidate) => candidate.family === family
      && candidate.tableSource);
    if (!definition || !relationshipCollectionIsSupported(
      model,
      canonicalRecord,
      definition,
      getNestedValue(canonicalRecord, definition.path),
    )) return;
    const rlocRecord = { rloc16: record.rloc16 ?? ownerRloc16 };
    const identityKey = getDeviceIdentityKeys(rlocRecord)
      .find((key) => key.startsWith("rloc16:"));
    const deviceId = identityKey ? model.identityToDeviceId.get(identityKey) : undefined;
    if (deviceId) registerRelationshipCapability(model, family, deviceId);
  });
}

function mergeMissing(existing, incoming) {
  const merged = { ...existing };
  Object.entries(incoming).forEach(([key, value]) => {
    if (!(key in merged) || merged[key] === null || merged[key] === "") {
      merged[key] = value;
    }
  });
  return merged;
}

function removeDuplicateAliases(record) {
  const result = { ...record };
  const preferredKeys = new Map();
  for (const key of Object.keys(result)) {
    const preferred = getPreferredFieldPath(key);
    const retained = preferredKeys.get(preferred);
    if (retained === undefined) {
      preferredKeys.set(preferred, key);
    } else if (key === preferred) {
      delete result[retained];
      preferredKeys.set(preferred, key);
    } else {
      delete result[key];
    }
  }
  return result;
}

function addSourceName(model, sourceName) {
  if (typeof sourceName !== "string" || !sourceName.trim()) return;
  if (!model.sourceNames.includes(sourceName)) model.sourceNames.push(sourceName);
}

function preferredDeviceId(identityKeys, fallbackId = "") {
  const preferred = ["extAddress:", "omrIpv6Address:", "matterFabricNode:", "rloc16:"];
  for (const prefix of preferred) {
    const key = identityKeys.find((candidate) => candidate.startsWith(prefix));
    if (key) return key.slice(prefix.length);
  }
  return typeof fallbackId === "string" ? fallbackId.trim().toLowerCase() : "";
}

function relationshipId(relationship) {
  if (relationship.id) return String(relationship.id);
  const sourceId = String(relationship.sourceId);
  const targetId = String(relationship.targetId);
  const endpoints = relationship.directed || sourceId <= targetId
    ? [sourceId, targetId]
    : [targetId, sourceId];
  return [
    relationship.category,
    relationship.directed ? "directed" : "undirected",
    ...endpoints,
  ].join("|");
}

export function createAdaptorModel(sourceNames = []) {
  return {
    devicesById: new Map(),
    identityToDeviceId: new Map(),
    relationships: [],
    detailsByDeviceId: new Map(),
    routerNeighborsByRloc16: new Map(),
    routerChildrenByRloc16: new Map(),
    sourceNames: [...new Set(sourceNames.filter((name) => typeof name === "string" && name))],
    relationshipIds: new Set(),
    relationshipCapabilities: {
      datasetWide: new Set(),
      byDeviceId: new Map(),
    },
    includeRouterChildIndex: false,
  };
}

export function registerRelationshipCapability(model, family, deviceId = null) {
  if (typeof family !== "string" || !family) return;
  if (!model.relationshipCapabilities) {
    model.relationshipCapabilities = { datasetWide: new Set(), byDeviceId: new Map() };
  }
  if (deviceId === null || deviceId === undefined) {
    model.relationshipCapabilities.datasetWide.add(family);
    return;
  }
  const key = String(deviceId);
  const families = model.relationshipCapabilities.byDeviceId.get(key) ?? new Set();
  families.add(family);
  model.relationshipCapabilities.byDeviceId.set(key, families);
}

export function registerDevice(model, record, options = {}) {
  if (!isPlainObject(record)) throw new Error("Adaptor device record must be an object.");
  const canonicalRecord = normalizeAdaptorRecord(model, record, options.sourceName);
  const identityKeys = getDeviceIdentityKeys(canonicalRecord);
  const indexedId = identityKeys
    .map((key) => model.identityToDeviceId.get(key))
    .find(Boolean);
  const explicitId = typeof options.id === "string" ? options.id : "";
  const deviceId = options.preserveId === true && explicitId
    ? explicitId
    : (indexedId || preferredDeviceId(identityKeys, explicitId));
  if (!deviceId) throw new Error("Adaptor device requires a canonical identity or fallback id.");

  const existing = model.devicesById.get(deviceId);
  const sourceNames = existing ? [...existing.sourceNames] : [];
  if (options.sourceName && !sourceNames.includes(options.sourceName)) {
    sourceNames.push(options.sourceName);
  }
  addSourceName(model, options.sourceName);

  const presentation = {
    ...(existing?.presentation ?? {}),
    ...(options.presentation ?? {}),
    id: deviceId,
  };
  const device = {
    id: deviceId,
    record: existing ? mergeMissing(existing.record, canonicalRecord) : canonicalRecord,
    nodeRecord: options.nodeRecord
      ?? existing?.nodeRecord
      ?? canonicalRecord,
    presentation,
    diagnosticSummary: {
      ...(existing?.diagnosticSummary ?? {}),
      ...(options.diagnosticSummary ?? {}),
    },
    sourceNames,
  };
  model.devicesById.set(deviceId, device);
  getDeviceIdentityKeys(device.record).forEach((key) => {
    if (!model.identityToDeviceId.has(key)) model.identityToDeviceId.set(key, deviceId);
  });
  return deviceId;
}

export function registerDetails(model, deviceId, rawRecord, ownership = "replace") {
  if (!model.devicesById.has(deviceId)) {
    throw new Error(`Cannot register details for unknown device: ${deviceId}`);
  }
  if (!isPlainObject(rawRecord)) return;
  const canonicalRecord = normalizeAdaptorRecord(model, rawRecord);
  const existing = model.detailsByDeviceId.get(deviceId) ?? {};
  if (ownership === "replace") {
    model.detailsByDeviceId.set(deviceId, canonicalRecord);
  } else if (ownership === "merge") {
    model.detailsByDeviceId.set(deviceId, { ...existing, ...canonicalRecord });
  } else if (ownership === "preserve") {
    model.detailsByDeviceId.set(deviceId, mergeMissing(existing, canonicalRecord));
  } else {
    throw new Error(`Unknown details ownership policy: ${ownership}`);
  }
  relationshipFamiliesForRecord(model, canonicalRecord).forEach((family) => {
    registerRelationshipCapability(model, family, deviceId);
  });
}

export function registerRelationship(model, relationship) {
  if (!relationship?.sourceId || !relationship?.targetId) {
    throw new Error("Adaptor relationship requires source and target endpoints.");
  }
  if (!relationship.category) {
    throw new Error("Adaptor relationship requires a category.");
  }
  const id = relationshipId(relationship);
  if (model.relationshipIds.has(id)) return id;
  model.relationshipIds.add(id);
  model.relationships.push({
    id,
    sourceId: String(relationship.sourceId),
    targetId: String(relationship.targetId),
    category: String(relationship.category),
    directed: relationship.directed === true,
    metrics: isPlainObject(relationship.metrics) ? { ...relationship.metrics } : {},
    presentation: isPlainObject(relationship.presentation) ? { ...relationship.presentation } : {},
    sourceName: relationship.sourceName || "",
    rawRecord: isPlainObject(relationship.rawRecord) ? { ...relationship.rawRecord } : {},
  });
  addSourceName(model, relationship.sourceName);
  return id;
}

function registerRouterRows(index, ownerRloc16, property, rows) {
  const key = String(ownerRloc16 ?? "").trim().toLowerCase();
  if (!key || !Array.isArray(rows)) return;
  const existing = index.get(key) ?? { rloc16: key, [property]: [] };
  existing[property].push(...rows);
  index.set(key, existing);
}

export function registerRouterNeighborRows(model, ownerRloc16, rows) {
  registerRouterRows(
    model.routerNeighborsByRloc16,
    ownerRloc16,
    "router_neighbor_table",
    rows,
  );
}

export function registerRouterChildRows(model, ownerRloc16, rows) {
  model.includeRouterChildIndex = true;
  registerRouterRows(
    model.routerChildrenByRloc16,
    ownerRloc16,
    "router_child_table",
    rows,
  );
}

export function validateAdaptorModel(model) {
  if (!(model?.devicesById instanceof Map)) throw new Error("Invalid devicesById map.");
  if (!(model.identityToDeviceId instanceof Map)) throw new Error("Invalid identity index.");
  if (!Array.isArray(model.relationships)) throw new Error("Invalid relationships array.");
  model.identityToDeviceId.forEach((deviceId) => {
    if (!model.devicesById.has(deviceId)) {
      throw new Error(`Identity index references unknown device: ${deviceId}`);
    }
  });
  model.relationships.forEach((relationship) => {
    if (!relationship.sourceId || !relationship.targetId) {
      throw new Error(`Relationship ${relationship.id} has an invalid endpoint.`);
    }
    if (!model.devicesById.has(relationship.sourceId) || !model.devicesById.has(relationship.targetId)) {
      throw new Error(`Relationship ${relationship.id} references an unknown device.`);
    }
  });
  return model;
}

export function emitAdaptorResult(model) {
  validateAdaptorModel(model);
  const nodeData = [];
  const nodeMap = new Map();
  model.devicesById.forEach((device, deviceId) => {
    nodeData.push(removeDuplicateAliases(
      normalizeAdaptorRecord(model, { ...device.presentation, id: deviceId }),
    ));
    nodeMap.set(deviceId, removeDuplicateAliases(
      normalizeAdaptorRecord(model, device.nodeRecord),
    ));
  });
  const edgeData = model.relationships.map((relationship) => ({
    ...relationship.presentation,
    ...relationship.metrics,
    id: relationship.id,
    from: relationship.sourceId,
    to: relationship.targetId,
    linkCategories: Array.isArray(relationship.presentation.linkCategories)
      ? relationship.presentation.linkCategories
      : [relationship.category],
  }));
  const result = {
    nodeData,
    edgeData,
    nodeMap,
    rawByIdForDetails: new Map(model.detailsByDeviceId),
    routerNeighborByRloc16: new Map(model.routerNeighborsByRloc16),
    sourceNames: [...model.sourceNames],
    relationshipCapabilities: cloneRelationshipCapabilities(model.relationshipCapabilities),
  };
  if (model.rolePolicy === HA_MATTER_ROLE_POLICY) result.rolePolicy = model.rolePolicy;
  if (model.includeRouterChildIndex) {
    result.routerChildByRloc16 = new Map(model.routerChildrenByRloc16);
  }
  return result;
}

function normalizedRecordId(record) {
  const value = record?.topologyId ?? record?.matterId ?? record?.id;
  return typeof value === "string" || typeof value === "number"
    ? String(value).trim().toLowerCase()
    : "";
}

function addRecordIdentityMappings(index, record, deviceId) {
  if (!isPlainObject(record)) return;
  getDeviceIdentityKeys(record).forEach((key) => {
    if (!index.has(key)) index.set(key, deviceId);
  });
  const recordId = normalizedRecordId(record);
  if (recordId && !index.has(`id:${recordId}`)) index.set(`id:${recordId}`, deviceId);
}

function resolveProjectedDeviceId(index, record) {
  const identityKey = getDeviceIdentityKeys(record).find((key) => index.has(key));
  if (identityKey) return index.get(identityKey);
  const recordId = normalizedRecordId(record);
  return recordId ? index.get(`id:${recordId}`) : undefined;
}

/**
 * Returns cloned table rows annotated with counts from observed adaptor edges.
 * Rows without a canonical topology identity or relationship evidence are left unchanged.
 */
export function projectObservedTopologyLinkCounts(rows, adaptorResult) {
  if (!Array.isArray(rows)) {
    return {
      rows,
      hasRelationshipCapability: false,
      hasRelationshipEvidence: false,
    };
  }
  const edgeData = Array.isArray(adaptorResult?.edgeData) ? adaptorResult.edgeData : [];
  const relationshipCapabilities = adaptorResult?.relationshipCapabilities;
  const datasetWideCapabilities = relationshipCapabilities?.datasetWide instanceof Set
    ? relationshipCapabilities.datasetWide
    : new Set();
  const capabilitiesByDeviceId = relationshipCapabilities?.byDeviceId instanceof Map
    ? relationshipCapabilities.byDeviceId
    : new Map();
  const hasRelationshipCapability = datasetWideCapabilities.size > 0
    || capabilitiesByDeviceId.size > 0;

  const identityToDeviceId = new Map();
  const deviceIds = new Set([
    ...(adaptorResult.nodeData ?? []).map((node) => String(node.id)),
    ...(adaptorResult.nodeMap instanceof Map ? adaptorResult.nodeMap.keys() : []),
    ...(adaptorResult.rawByIdForDetails instanceof Map ? adaptorResult.rawByIdForDetails.keys() : []),
  ]);
  deviceIds.forEach((deviceId) => {
    const normalizedDeviceId = String(deviceId);
    identityToDeviceId.set(`id:${normalizedDeviceId.toLowerCase()}`, normalizedDeviceId);
    addRecordIdentityMappings(identityToDeviceId, adaptorResult.nodeMap?.get(deviceId), normalizedDeviceId);
    addRecordIdentityMappings(identityToDeviceId, adaptorResult.rawByIdForDetails?.get(deviceId), normalizedDeviceId);
    addRecordIdentityMappings(
      identityToDeviceId,
      (adaptorResult.nodeData ?? []).find((node) => String(node.id) === normalizedDeviceId),
      normalizedDeviceId,
    );
  });

  const coveredDeviceIds = new Set(capabilitiesByDeviceId.keys());
  if (datasetWideCapabilities.size > 0) {
    deviceIds.forEach((deviceId) => coveredDeviceIds.add(String(deviceId)));
  }

  const countsByDeviceId = new Map();
  const seenEdgeIds = new Set();
  if (hasRelationshipCapability) edgeData.forEach((edge, index) => {
    if (!Array.isArray(edge.linkCategories) || edge.linkCategories.length === 0) return;
    const edgeId = String(edge.id ?? `${edge.from}|${edge.to}|${index}`);
    if (seenEdgeIds.has(edgeId)) return;
    seenEdgeIds.add(edgeId);
    new Set([String(edge.from), String(edge.to)]).forEach((deviceId) => {
      const counts = countsByDeviceId.get(deviceId) ?? {
        observedTopologyLinks: 0,
        observedTopologyLinksLq3: 0,
        observedTopologyLinksLq2: 0,
        observedTopologyLinksLq1: 0,
      };
      counts.observedTopologyLinks += 1;
      if (edge.lqLevel === 3) counts.observedTopologyLinksLq3 += 1;
      if (edge.lqLevel === 2) counts.observedTopologyLinksLq2 += 1;
      if (edge.lqLevel === 1) counts.observedTopologyLinksLq1 += 1;
      countsByDeviceId.set(deviceId, counts);
    });
  });

  const withoutExistingProjection = (row) => {
    if (!isPlainObject(row)
      || !OBSERVED_TOPOLOGY_LINK_FIELDS.some((field) => Object.hasOwn(row, field))) return row;
    const copy = { ...row };
    OBSERVED_TOPOLOGY_LINK_FIELDS.forEach((field) => delete copy[field]);
    return copy;
  };

  return {
    rows: rows.map((row) => {
      const cleanRow = withoutExistingProjection(row);
      if (!isPlainObject(cleanRow) || !hasRelationshipCapability) return cleanRow;
      const deviceId = resolveProjectedDeviceId(identityToDeviceId, cleanRow);
      if (!deviceId) return cleanRow;
      const counts = countsByDeviceId.get(deviceId);
      if (!counts && !coveredDeviceIds.has(deviceId)) return cleanRow;
      return {
        ...cleanRow,
        ...(counts ?? {
          observedTopologyLinks: 0,
          observedTopologyLinksLq3: 0,
          observedTopologyLinksLq2: 0,
          observedTopologyLinksLq1: 0,
        }),
      };
    }),
    hasRelationshipCapability,
    hasRelationshipEvidence: hasRelationshipCapability && seenEdgeIds.size > 0,
  };
}

export function createAdaptorModelFromResult(result) {
  const model = createAdaptorModel(result.sourceNames ?? []);
  if (result.rolePolicy === HA_MATTER_ROLE_POLICY) model.rolePolicy = result.rolePolicy;
  const nodeDataById = new Map(
    (result.nodeData ?? []).map((node) => [String(node.id), node]),
  );
  const deviceIds = new Set([
    ...nodeDataById.keys(),
    ...(result.nodeMap instanceof Map ? result.nodeMap.keys() : []),
  ]);
  deviceIds.forEach((rawDeviceId) => {
    const deviceId = String(rawDeviceId);
    const nodeRecord = result.nodeMap?.get(rawDeviceId)
      ?? result.nodeMap?.get(deviceId)
      ?? nodeDataById.get(deviceId)
      ?? { id: deviceId };
    const details = result.rawByIdForDetails?.get(rawDeviceId)
      ?? result.rawByIdForDetails?.get(deviceId)
      ?? nodeRecord;
    registerDevice(model, isPlainObject(details) ? details : nodeRecord, {
      id: deviceId,
      preserveId: true,
      nodeRecord,
      presentation: nodeDataById.get(deviceId) ?? { id: deviceId },
    });
    if (isPlainObject(details)) registerDetails(model, deviceId, details, "replace");
  });

  (result.edgeData ?? []).forEach((edge, index) => {
    const categories = Array.isArray(edge.linkCategories) && edge.linkCategories.length > 0
      ? edge.linkCategories
      : ["uncategorized"];
    registerRelationship(model, {
      id: edge.id || [
        "adaptor-edge",
        categories.join("+"),
        edge.from,
        edge.to,
        edge.edgeKeySuffix || "",
        index,
      ].join("|"),
      sourceId: edge.from,
      targetId: edge.to,
      category: categories.join("+"),
      directed: edge.arrows === "to" || edge.arrows?.to === true,
      presentation: edge,
    });
  });

  if (result.routerNeighborByRloc16 instanceof Map) {
    model.routerNeighborsByRloc16 = new Map(result.routerNeighborByRloc16);
    registerIndexedTableCapabilities(model, model.routerNeighborsByRloc16, "routerNeighbors");
  }
  if (result.routerChildByRloc16 instanceof Map) {
    model.routerChildrenByRloc16 = new Map(result.routerChildByRloc16);
    model.includeRouterChildIndex = true;
    registerIndexedTableCapabilities(model, model.routerChildrenByRloc16, "childTable");
  }
  if (result.relationshipCapabilities) {
    const capabilities = cloneRelationshipCapabilities(result.relationshipCapabilities);
    capabilities.datasetWide.forEach((family) => registerRelationshipCapability(model, family));
    capabilities.byDeviceId.forEach((families, deviceId) => {
      families.forEach((family) => registerRelationshipCapability(model, family, deviceId));
    });
  }
  return model;
}