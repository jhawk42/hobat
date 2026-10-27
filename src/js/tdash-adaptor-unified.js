import {
  EDGE_CATEGORY_DEFAULT_CHILDREN, EDGE_CATEGORY_ROUTER_NEIGHBOR,
  EDGE_CATEGORY_DEFAULT_1, EDGE_CATEGORY_DEFAULT_2, EDGE_CATEGORY_DEFAULT_3,
  EDGE_CATEGORY_OTBR_ROUTE, NODE_COLORS, NODE_SHAPES,
} from "./tdash-constants.js";
import {
  createAdaptorModel, emitAdaptorResult, registerDevice, registerDetails,
  registerRelationshipCapability,
} from "./tdash-adaptor-model.js";
import {
  asArray, getOtbrRouteCategories, getRelationshipLinkQuality, projectRelationshipMetrics,
  registerCanonicalRelationship,
} from "./tdash-adaptor-shared.js";
import { getDeviceIdentityKeys } from "./tdash-device-fields.js";
import { buildDeviceProjection } from "./tdash-device-projection.js";
import {
  buildLabel, buildNodeHoverLabel, buildNodeLabelFont, buildRoleNodeEmphasis,
  buildMainRouterRloc16, buildChildRloc16,
} from "./tdash-topology-utils.js";
import { toText, toFiniteNumber, isPlainObject } from "./tdash-utils.js";

function scopeKey(row, key) {
  return JSON.stringify([row._networkInstance ?? null, key]);
}

function recordKeys(row) {
  return [...getDeviceIdentityKeys(row), ...["id", "topologyId"].flatMap((key) =>
    row[key] == null ? [] : [`id:${toText(row[key])}`])];
}

export function adaptUnified(fileMap, rows, entry) {
  const model = createAdaptorModel([entry.source]);
  const index = new Map();
  rows.forEach((row) => {
    if (!isPlainObject(row) || typeof row._unifiedRecordId !== "string" || !row._unifiedRecordId
      || model.devicesById.has(row._unifiedRecordId)) {
      throw new Error("Unified rows require unique committed record IDs.");
    }
    const projection = buildDeviceProjection(row);
    const role = toText(row.role).toLowerCase();
    const child = ["child", "reed", "enddevice", "sleepyenddevice", "sleepychild"].includes(role);
    const themeRole = projection.isBorderRouter ? "borderRouter"
      : projection.isRouter ? "router" : child ? "child" : "unknown";
    const id = registerDevice(model, row, {
      id: row._unifiedRecordId,
      preserveId: true,
      sourceName: entry.source,
      nodeRecord: row,
      presentation: {
        _unifiedRecordId: row._unifiedRecordId,
        label: buildLabel(row),
        title: buildNodeHoverLabel(row),
        shape: NODE_SHAPES[themeRole],
        color: NODE_COLORS[themeRole],
        themeRole,
        font: buildNodeLabelFont({ fontSize: projection.isRouter ? 19.5 : 13, isRouter: projection.isRouter }),
        ...buildRoleNodeEmphasis(projection),
        ...projection,
        type: row.type,
        relationshipOnly: row.relationshipOnly === true,
      },
    });
    registerDetails(model, id, row);
    recordKeys(row).forEach((key) => {
      const scoped = scopeKey(row, key);
      const matches = index.get(scoped) ?? new Set();
      matches.add(id);
      index.set(scoped, matches);
    });
  });
  const resolve = (owner, record) => {
    if (typeof record.targetId === "string" && model.devicesById.has(record.targetId)) {
      const target = model.devicesById.get(record.targetId).record;
      return target._networkInstance === owner._networkInstance ? record.targetId : null;
    }
    const keys = [...(record.targetId ? [`id:${record.targetId}`] : []), ...recordKeys(record)];
    let candidates = null;
    for (const key of keys) {
      const matches = index.get(scopeKey(owner, key));
      if (!matches) continue;
      candidates = candidates === null ? new Set(matches)
        : new Set([...candidates].filter((id) => matches.has(id)));
    }
    return candidates?.size === 1 ? candidates.values().next().value : null;
  };
  const relationships = new Map();
  const collect = (owner, record, categories, supplemental = {}) => {
    if (typeof record === "string") {
      record = /^0x[0-9a-f]{4}$/i.test(record) ? { rloc16: record } : { id: record };
    }
    if (!isPlainObject(record) || record.allocated === false) return;
    const targetId = resolve(owner, { ...record, ...supplemental });
    if (!targetId || targetId === owner._unifiedRecordId) return;
    if (categories.includes(EDGE_CATEGORY_ROUTER_NEIGHBOR)
      && model.devicesById.get(targetId).presentation.themeRole === "child") {
      categories = [EDGE_CATEGORY_DEFAULT_CHILDREN];
    }
    const key = JSON.stringify([owner._unifiedRecordId, targetId]);
    const existing = relationships.get(key);
    const lqiIn = toFiniteNumber(record.linkQualityIn ?? record.inLinkQuality);
    const lqiOut = toFiniteNumber(record.linkQualityOut ?? record.outLinkQuality);
    const directionalLqi = [lqiIn, lqiOut].filter(Number.isFinite);
    const observedMetrics = {
      lqiIn, lqiOut,
      lqi: toFiniteNumber(record.lqi) ?? getRelationshipLinkQuality(record)
        ?? toFiniteNumber(record.incomingLinkQuality)
        ?? (directionalLqi.length ? Math.max(...directionalLqi) : undefined),
      routeCost: toFiniteNumber(record.routeCost ?? record.pathCost),
    };
    const metrics = {
      ...projectRelationshipMetrics(record),
      ...Object.fromEntries(Object.entries(observedMetrics).filter(([, value]) => Number.isFinite(value))),
    };
    if (existing) {
      existing.records.push(record);
      existing.categories = [...new Set([...existing.categories, ...categories])];
      Object.entries(metrics).forEach(([name, value]) => {
        if (existing.metrics[name] === undefined) existing.metrics[name] = value;
      });
    } else {
      relationships.set(key, {
        sourceId: owner._unifiedRecordId, targetId, categories, metrics,
        records: [record], sourceName: entry.source,
      });
    }
  };
  rows.forEach((row) => {
    const ownerId = row._unifiedRecordId;
    for (const [family, categories] of [
      ["children", [EDGE_CATEGORY_DEFAULT_CHILDREN]],
      ["childTable", [EDGE_CATEGORY_DEFAULT_CHILDREN]],
      ["routerNeighbors", [EDGE_CATEGORY_ROUTER_NEIGHBOR]],
      ["neighborTable", [EDGE_CATEGORY_ROUTER_NEIGHBOR]],
      ["links1", [EDGE_CATEGORY_DEFAULT_1]],
      ["links2", [EDGE_CATEGORY_DEFAULT_2]],
      ["links3", [EDGE_CATEGORY_DEFAULT_3]],
    ]) {
      if (!Array.isArray(row[family])) continue;
      registerRelationshipCapability(model, family, ownerId);
      row[family].forEach((record) => collect(row, record, categories,
        record?.childId != null && !record.rloc16
          ? { rloc16: buildChildRloc16(row.rloc16, record.childId) } : {}));
    }
    const routeCategories = getOtbrRouteCategories(row);
    for (const routes of [row.route?.routeData, row.routes, row.routeTable]) {
      if (!Array.isArray(routes)) continue;
      registerRelationshipCapability(model, "routes", ownerId);
      routes.forEach((record) => collect(row, record,
        routeCategories.length ? routeCategories : [EDGE_CATEGORY_OTBR_ROUTE],
        record?.routeId != null ? { rloc16: buildMainRouterRloc16(record.routeId) } : {}));
    }
    if (Array.isArray(row.nativeRelationships)) {
      registerRelationshipCapability(model, "nativeRelationships", ownerId);
    }
    asArray(row.nativeRelationships).forEach((link) => {
      if (asArray(link.unresolvedEndpoints).length
        || !model.devicesById.has(link.sourceId) || !model.devicesById.has(link.targetId)) return;
      const directions = [];
      if (isPlainObject(link.sourceToTarget)) directions.push([link.sourceId, link.targetId, link.sourceToTarget]);
      if (isPlainObject(link.targetToSource)) directions.push([link.targetId, link.sourceId, link.targetToSource]);
      if (!directions.length) directions.push([link.sourceId, link.targetId, null]);
      directions.forEach(([sourceId, targetId, observation]) => {
        const category = `native:${link.networkType}`;
        const metrics = {
          ...(observation ?? {}), networkType: link.networkType,
          strength: observation?.strength ?? link.strength,
          ...(link.pathCost !== undefined ? { pathCost: link.pathCost } : {}),
          ...(link.viaRouteTable !== undefined ? { viaRouteTable: link.viaRouteTable } : {}),
        };
        const id = JSON.stringify(["native", sourceId, targetId, link.networkType, observation !== null]);
        if (!relationships.has(id)) relationships.set(id, {
          id, sourceId, targetId, categories: [category], metrics,
          directed: observation !== null, records: [link], sourceName: entry.source,
        });
      });
    });
  });
  relationships.forEach((relationship) => registerCanonicalRelationship(relationship, model));
  return emitAdaptorResult(model);
}
