import {
  getDeviceIdentityKeys,
  normalizeInputRecord,
} from "./tdash-device-fields.js";


function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
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
    includeRouterChildIndex: false,
  };
}

export function registerDevice(model, record, options = {}) {
  if (!isPlainObject(record)) throw new Error("Adaptor device record must be an object.");
  const canonicalRecord = normalizeInputRecord(record, { source: options.sourceName });
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
  const existing = model.detailsByDeviceId.get(deviceId) ?? {};
  if (ownership === "replace") {
    model.detailsByDeviceId.set(deviceId, { ...rawRecord });
  } else if (ownership === "merge") {
    model.detailsByDeviceId.set(deviceId, { ...existing, ...rawRecord });
  } else if (ownership === "preserve") {
    model.detailsByDeviceId.set(deviceId, mergeMissing(existing, rawRecord));
  } else {
    throw new Error(`Unknown details ownership policy: ${ownership}`);
  }
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
    nodeData.push({ ...device.presentation, id: deviceId });
    nodeMap.set(deviceId, device.nodeRecord);
  });
  const edgeData = model.relationships.map((relationship) => ({
    ...relationship.presentation,
    ...relationship.metrics,
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
  };
  if (model.includeRouterChildIndex) {
    result.routerChildByRloc16 = new Map(model.routerChildrenByRloc16);
  }
  return result;
}

export function createAdaptorModelFromResult(result) {
  const model = createAdaptorModel(result.sourceNames ?? []);
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
  }
  if (result.routerChildByRloc16 instanceof Map) {
    model.routerChildrenByRloc16 = new Map(result.routerChildByRloc16);
    model.includeRouterChildIndex = true;
  }
  return model;
}