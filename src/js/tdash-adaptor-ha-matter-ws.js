import {
  EDGE_CATEGORY_DEFAULT_CHILDREN, EDGE_CATEGORY_DEFAULT_1,
  EDGE_CATEGORY_DEFAULT_2, EDGE_CATEGORY_DEFAULT_3,
  EDGE_CATEGORY_ROUTER_NEIGHBOR, EDGE_CATEGORY_OTBR_ROUTE,
  EDGE_CATEGORY_OTBR_ROUTE_ROUTER, EDGE_CATEGORY_OTBR_ROUTE_FTD_CHILD,
  EDGE_CATEGORY_OTBR_CHILD, EDGE_CATEGORY_EVE_ROUTE,
  EDGE_CATEGORY_EVE_CHILD, EDGE_CATEGORY_EVE_NATIVE_ROUTE,
  EDGE_CATEGORY_EVE_NATIVE_CHILD, NODE_COLORS, NODE_SHAPES, PALETTE
} from './tdash-constants.js';
import {
  toText, toFiniteNumber, isPlainObject,
  getCanonicalRloc16, getCanonicalExtaddr,
  getCanonicalOmrIpv6Address,
  mergeForDisplay,
  getColumnValue,
  normalizeNestedArrayFields,
} from './tdash-utils.js';
import {
  chooseNodeId, buildLabel,
  buildMainRouterRloc16, buildChildRloc16,
  addEdge, buildEdgeTitle, buildNodeHoverLabel, groupIsolatedUnknownNodes, buildVisNodeData, buildNodeLabelFont,
  buildRoleNodeEmphasis,
  lqStyleFromField, lqStyleFromAvgLqi, lqStyleFromLinkMargin
} from './tdash-topology-utils.js';
import { isPlaceholderOmrAddress } from './tdash-device-fields.js';
import {
  createAdaptorModel,
  createAdaptorModelFromResult,
  emitAdaptorResult,
  registerDetails,
  registerDevice,
  registerRelationshipCapability,
  registerRelationship,
  registerRouterChildRows,
  registerRouterNeighborRows,
} from './tdash-adaptor-model.js';

import { asArray, emitThroughAdaptorModel, buildEdgeEndpointTitles, getOtbrRouteCategories } from './tdash-adaptor-shared.js';

const MATTER_FIELDS = Object.freeze([
  'deviceLabel', 'nodeId', 'matterId', 'fabricId', 'compressedFabricId',
  'fabricIndex', 'vendorName', 'vendorId', 'vendorModel', 'productId',
  'productLabel', 'vendorSwVersion', 'vendorSwVersionNumber',
  'vendorHwVersion', 'vendorHwVersionNumber', 'available', 'isBridge',
  'dateCommissioned',
]);
const ROLE_FACT_FIELDS = Object.freeze([
  'isBorderRouter', 'isRouter', 'isLeader', 'isReed',
]);

function explicitRoleFacts(record) {
  return Object.fromEntries(
    ROLE_FACT_FIELDS.flatMap((field) =>
      typeof record?.[field] === 'boolean' ? [[field, record[field]]] : []),
  );
}

// Files consumed as named primary slots in adaptMeshdiagNetworkdiag;
// anything not in this set is treated as supplementary (e.g. mdns, eve).

// ── Adaptor 7: Home Assistant Matter WebSocket canonical snapshots ──────────

function registerHaMatterRow(row, index, {
  model, topologyIdToDeviceId, extAddressToDeviceId,
  rloc16ToDeviceId, canonicalRowsByDeviceId,
}) {
  if (!isPlainObject(row)) return;
  const matter = isPlainObject(row.matter)
    ? row.matter
    : Object.fromEntries(
      MATTER_FIELDS.flatMap((field) => (
        row[field] === undefined ? [] : [[field, row[field]]]
      )),
    );
  const thread = isPlainObject(row.thread) ? row.thread : {};
  const canonicalRow = {
    ...row,
    ...matter,
    ...thread,
    ...(row.deviceLabel != null ? { deviceLabel: row.deviceLabel } : {}),
    matter,
  };
  ROLE_FACT_FIELDS.forEach((field) => {
    if (typeof row[field] === 'boolean') canonicalRow[field] = row[field];
    else if (typeof thread[field] === 'boolean') canonicalRow[field] = thread[field];
    else if (typeof matter[field] === 'boolean') canonicalRow[field] = matter[field];
  });
  const explicitId = toText(canonicalRow.topologyId)
    || toText(canonicalRow.id)
    || toText(canonicalRow.matterId)
    || `ha-matter-ws-${index + 1}`;
  const role = toText(canonicalRow.role || canonicalRow.routingRole).toLowerCase();
  const rloc16 = toText(canonicalRow.rloc16).toLowerCase();
  const isChild = role.includes('child') || role.includes('enddevice');
  const isRouter = typeof canonicalRow.isRouter === 'boolean'
    ? canonicalRow.isRouter
    : role === 'router'
      || role === 'leader'
      || (canonicalRow.relationshipOnly === true && rloc16.endsWith('00'));
  const isBorderRouter = canonicalRow.isBorderRouter === true;
  const isLeader = typeof canonicalRow.isLeader === 'boolean'
    ? canonicalRow.isLeader
    : role === 'leader';
  const shape = isBorderRouter
    ? NODE_SHAPES.borderRouter
    : isChild
      ? NODE_SHAPES.child
      : isRouter
        ? NODE_SHAPES.router
        : NODE_SHAPES.unknown;
  const color = isBorderRouter
    ? NODE_COLORS.borderRouter
    : isChild
      ? NODE_COLORS.child
      : isRouter
        ? NODE_COLORS.router
        : NODE_COLORS.unknown;
  const deviceId = registerDevice(model, canonicalRow, {
    id: explicitId,
    preserveId: true,
    sourceName: 'ha-matter-ws',
    nodeRecord: canonicalRow,
    presentation: {
      label: buildLabel(canonicalRow),
      title: buildNodeHoverLabel(canonicalRow),
      shape,
      color,
      font: buildNodeLabelFont({ fontSize: isRouter ? 19.5 : 13, isRouter }),
      ...buildRoleNodeEmphasis({ isBorderRouter, isRouter }),
      isRouter,
      isLeader,
      ...explicitRoleFacts(canonicalRow),
      relationshipOnly: canonicalRow.relationshipOnly === true,
    },
  });
  topologyIdToDeviceId.set(explicitId, deviceId);
  const extAddress = getCanonicalExtaddr(canonicalRow);
  if (extAddress) extAddressToDeviceId.set(extAddress, deviceId);
  if (rloc16) rloc16ToDeviceId.set(rloc16, deviceId);
  canonicalRowsByDeviceId.set(deviceId, canonicalRow);
  registerDetails(model, deviceId, canonicalRow, 'replace');
  registerRouterNeighborRows(
    model,
    canonicalRow.rloc16,
    canonicalRow.routerNeighbors ?? canonicalRow.neighborTable,
  );
  registerRouterChildRows(model, row.rloc16, row.children);
}

function resolveRawRelationshipTarget(ownerId, entry, {
  model, extAddressToDeviceId, rloc16ToDeviceId, canonicalRowsByDeviceId,
}) {
  const extAddress = getCanonicalExtaddr(entry);
  const rloc16 = getCanonicalRloc16(entry);
  const knownTarget = (extAddress && extAddressToDeviceId.get(extAddress))
    || (rloc16 && rloc16ToDeviceId.get(rloc16));
  if (knownTarget) return knownTarget;

  const owner = canonicalRowsByDeviceId.get(ownerId) || {};
  const fallbackId = extAddress
    ? `ha-matter-ws:ext:${extAddress}`
    : `ha-matter-ws:rloc:${rloc16}`;
  const target = {
    relationshipOnly: true,
    extAddress,
    rloc16,
    networkName: owner.networkName,
    extPanId: owner.extPanId,
    role: 'unknown',
  };
  const targetId = registerDevice(model, target, {
    id: fallbackId,
    preserveId: true,
    sourceName: 'ha-matter-ws',
    nodeRecord: target,
    presentation: {
      label: buildLabel(target),
      title: buildNodeHoverLabel(target),
      shape: NODE_SHAPES.router,
      color: NODE_COLORS.eve,
      font: buildNodeLabelFont({ fontSize: 13, isRouter: false }),
      ...buildRoleNodeEmphasis({ isBorderRouter: false, isRouter: false }),
      isRouter: false,
      isLeader: false,
      relationshipOnly: true,
    },
  });
  if (extAddress) extAddressToDeviceId.set(extAddress, targetId);
  if (rloc16) rloc16ToDeviceId.set(rloc16, targetId);
  canonicalRowsByDeviceId.set(targetId, target);
  registerDetails(model, targetId, target, 'replace');
  return targetId;
}

function collectRelationship(ownerId, relationship, categories, {
  topologyIdToDeviceId, model, relationships,
}) {
  if (!isPlainObject(relationship)) return;
  const sourceId = topologyIdToDeviceId.get(toText(relationship.sourceId)) || ownerId;
  const targetId = topologyIdToDeviceId.get(toText(relationship.targetId))
    || (model.devicesById.has(toText(relationship.targetId))
      ? toText(relationship.targetId)
      : undefined);
  if (!sourceId || !targetId) return;
  const key = `${sourceId}|${targetId}`;
  const aggregate = relationships.get(key) || {
    sourceId,
    targetId,
    categories: [],
    records: [],
    metrics: {},
  };
  categories.forEach((category) => {
    if (!aggregate.categories.includes(category)) aggregate.categories.push(category);
  });
  aggregate.records.push(relationship);
  [
    'lqi', 'averageRssi', 'lastRssi', 'frameErrorRate',
    'messageErrorRate', 'routeCost',
  ].forEach((field) => {
    const value = field === 'routeCost'
      ? relationship.routeCost ?? relationship.pathCost
      : relationship[field];
    if (aggregate.metrics[field] === undefined && value !== undefined) {
      aggregate.metrics[field] = value;
    }
  });
  relationships.set(key, aggregate);
}

function collectHaMatterNeighbor(ownerId, relationship, childTargets, context) {
  collectRelationship(
    ownerId,
    relationship,
    [childTargets.has(toText(relationship?.targetId))
      ? EDGE_CATEGORY_DEFAULT_CHILDREN
      : EDGE_CATEGORY_ROUTER_NEIGHBOR],
    context,
  );
}

function collectHaMatterChild(ownerId, relationship, row, context) {
  if (!asArray(row.routerNeighbors).some(
    (neighbor) => toText(neighbor?.targetId) === toText(relationship?.targetId),
  )) {
    collectRelationship(ownerId, relationship, [EDGE_CATEGORY_DEFAULT_CHILDREN], context);
  }
}

function collectHaMatterRoute(ownerId, relationship, row, context) {
  const routeCategories = getOtbrRouteCategories(row);
  collectRelationship(
    ownerId,
    relationship,
    routeCategories.length > 0 ? routeCategories : [EDGE_CATEGORY_OTBR_ROUTE],
    context,
  );
}

function collectHaMatterRawNeighbor(ownerId, entry, context) {
  const targetId = resolveRawRelationshipTarget(ownerId, entry, context);
  collectRelationship(ownerId, { ...entry, sourceId: ownerId, targetId }, [
    entry.isChild === true
      ? EDGE_CATEGORY_DEFAULT_CHILDREN
      : EDGE_CATEGORY_ROUTER_NEIGHBOR,
  ], context);
}

function collectHaMatterRawRoute(ownerId, entry, canonicalRow, context) {
  if (entry.allocated === false) return;
  const targetId = resolveRawRelationshipTarget(ownerId, entry, context);
  const routeCategories = getOtbrRouteCategories({
    ...canonicalRow,
    role: canonicalRow.role || canonicalRow.routingRole,
  });
  collectRelationship(
    ownerId,
    { ...entry, sourceId: ownerId, targetId },
    routeCategories.length > 0 ? routeCategories : [EDGE_CATEGORY_OTBR_ROUTE],
    context,
  );
}

function registerHaMatterRelationship(relationship, model) {
  const lqi = toFiniteNumber(relationship.metrics.lqi);
  const sourceNode = model.devicesById.get(relationship.sourceId)?.nodeRecord;
  const targetNode = model.devicesById.get(relationship.targetId)?.nodeRecord;
  const presentation = {
    ...lqStyleFromAvgLqi(lqi, 3),
    ...buildEdgeEndpointTitles(
      sourceNode,
      targetNode,
      relationship.sourceId,
      relationship.targetId,
    ),
    arrows: 'to',
    isParentChild: relationship.categories.includes(EDGE_CATEGORY_DEFAULT_CHILDREN),
    linkCategories: relationship.categories,
  };
  presentation.title = buildEdgeTitle({
    ...relationship.metrics,
    ...presentation,
  });
  registerRelationship(model, {
    sourceId: relationship.sourceId,
    targetId: relationship.targetId,
    category: relationship.categories.join('+'),
    directed: true,
    sourceName: 'ha-matter-ws',
    metrics: relationship.metrics,
    presentation,
    rawRecord: { observations: relationship.records },
  });
}

export function adaptHaMatterWs(
  fileMap,
  extractedRows,
  rowExtractor = '',
) {
  const payload = fileMap.values().next().value;
  const rows = rowExtractor
    ? [
      ...asArray(extractedRows),
      ...(rowExtractor === 'ha-matter-ws-mesh-diagnostics'
        ? asArray(payload?.topology).filter((row) => row?.relationshipOnly === true)
        : []),
    ]
    : (Array.isArray(payload) ? payload : asArray(payload?.topology));
  const model = createAdaptorModel(['ha-matter-ws']);
  const topologyIdToDeviceId = new Map();
  const extAddressToDeviceId = new Map();
  const rloc16ToDeviceId = new Map();
  const canonicalRowsByDeviceId = new Map();
  const relationships = new Map();
  const context = {
    model, topologyIdToDeviceId, extAddressToDeviceId,
    rloc16ToDeviceId, canonicalRowsByDeviceId, relationships,
  };

  rows.forEach((row, index) => {
    registerHaMatterRow(row, index, context);
  });

  rows.forEach((row, index) => {
    if (!isPlainObject(row)) return;
    const explicitId = toText(row.topologyId)
      || toText(row.id)
      || toText(row.matterId)
      || `ha-matter-ws-${index + 1}`;
    const ownerId = topologyIdToDeviceId.get(explicitId);
    if (!ownerId) return;
    const childTargets = new Set(
      asArray(row.children).map((relationship) => toText(relationship?.targetId)),
    );
    asArray(row.routerNeighbors).forEach((relationship) => {
      collectHaMatterNeighbor(ownerId, relationship, childTargets, context);
    });
    asArray(row.children).forEach((relationship) => {
      collectHaMatterChild(ownerId, relationship, row, context);
    });
    asArray(row.route?.routeData).forEach((relationship) => {
      collectHaMatterRoute(ownerId, relationship, row, context);
    });
    const canonicalRow = canonicalRowsByDeviceId.get(ownerId) || row;
    asArray(canonicalRow.neighborTable).forEach((entry) => {
      collectHaMatterRawNeighbor(ownerId, entry, context);
    });
    asArray(canonicalRow.routeTable).forEach((entry) => {
      collectHaMatterRawRoute(ownerId, entry, canonicalRow, context);
    });
  });

  relationships.forEach((relationship) => {
    registerHaMatterRelationship(relationship, model);
  });

  return emitAdaptorResult(model);
}

// ── Adaptor 8: Home Assistant Matter Server native Thread products ─────────

function nativeStrengthStyle(strength) {
  switch (toText(strength).toLowerCase()) {
    case 'strong': return { width: 12, color: PALETTE.lqHigh, dashes: false, lqLevel: 3 };
    case 'medium': return { width: 8, color: PALETTE.lqMedium, dashes: true, lqLevel: 2 };
    case 'weak': return { width: 4, color: PALETTE.lqLow, dashes: true, lqLevel: 1 };
    default: return { width: 4, color: PALETTE.lqNone, dashes: strength === 'unknown', lqLevel: 0 };
  }
}

function nativeRloc16(value) {
  const number = toFiniteNumber(value);
  return number === undefined ? toText(value).toLowerCase() : `0x${number.toString(16).padStart(4, '0')}`;
}

function nativeTopologyNodeRecord(node) {
  const deviceId = toText(node.id);
  const role = toText(node.role).trim().toLowerCase();
  const isBorderRouter = typeof node.isBorderRouter === 'boolean'
    ? node.isBorderRouter
    : node.kind === 'border_router';
  const isChild = role === 'end_device' || role === 'sleepy_end_device';
  const isRouter = typeof node.isRouter === 'boolean'
    ? node.isRouter
    : isBorderRouter || ['leader', 'router'].includes(role);
  const isLeader = typeof node.isLeader === 'boolean' ? node.isLeader : role === 'leader';
  const result = {
    ...node,
    id: deviceId,
    extAddress: toText(node.extAddress || node.ext_address).toLowerCase(),
    rloc16: nativeRloc16(node.rloc16),
    deviceLabel: node.deviceLabel || node.device_label || node.networkName || node.network_name || node.hostName || node.host_name || node.vendorName || node.vendor_name || deviceId,
    nodeId: node.nodeId || node.node_id,
    isChild,
    isBorderRouter,
    isRouter,
    isLeader,
  };
  return result;
}

function nativeTopologyNodePresentation(node) {
  return {
    label: buildLabel(node),
    title: buildNodeHoverLabel(node),
    shape: node.isBorderRouter ? NODE_SHAPES.borderRouter : (node.isChild ? NODE_SHAPES.child : (node.isRouter ? NODE_SHAPES.router : NODE_SHAPES.unknown)),
    color: node.isBorderRouter ? NODE_COLORS.borderRouter : (node.isChild ? NODE_COLORS.child : (node.isRouter ? NODE_COLORS.router : NODE_COLORS.unknown)),
    ...buildRoleNodeEmphasis({
      isBorderRouter: node.isBorderRouter === true,
      isRouter: node.isRouter === true,
    }),
    isRouter: node.isRouter,
    isLeader: node.isLeader,
    ...explicitRoleFacts(node),
  };
}

export function adaptHaMatterWsNativeThread(
  fileMap,
  extractedRows,
) {
  const rows = asArray(extractedRows);
  const sourceName = 'ha-matter-ws-thread-border-routers';
  const model = createAdaptorModel([sourceName]);

  rows.forEach((row, index) => {
    if (!isPlainObject(row)) return;
    const extAddress = toText(row.extAddress || row.extAddressHex || row.extMacAddress).toLowerCase();
    const rloc16 = nativeRloc16(row.rloc16);
    const fallbackId = `ha-matter-ws-border-router:${extAddress || index}`;
    const canonicalRow = {
      ...row,
      extAddress,
      rloc16,
      networkName: row.networkName,
      deviceLabel: row.deviceLabel
        || row.device_label
        || row.networkName
        || row.hostname
        || row.vendorName
        || row.vendorModel
        || fallbackId,
      role: row.role ?? 'Border Router',
      isBorderRouter: typeof row.isBorderRouter === 'boolean' ? row.isBorderRouter : true,
      isRouter: typeof row.isRouter === 'boolean' ? row.isRouter : true,
    };
    const isBorderRouter = canonicalRow.isBorderRouter === true;
    const isRouter = canonicalRow.isRouter === true;
    const deviceId = registerDevice(model, canonicalRow, {
      id: fallbackId,
      preserveId: true,
      sourceName,
      nodeRecord: canonicalRow,
      presentation: {
        label: buildLabel(canonicalRow),
        title: buildNodeHoverLabel(canonicalRow),
        shape: isBorderRouter
          ? NODE_SHAPES.borderRouter
          : isRouter ? NODE_SHAPES.router : NODE_SHAPES.unknown,
        color: isBorderRouter
          ? NODE_COLORS.borderRouter
          : isRouter ? NODE_COLORS.router : NODE_COLORS.unknown,
        ...buildRoleNodeEmphasis({ isBorderRouter, isRouter }),
        isRouter,
        isBorderRouter,
        ...explicitRoleFacts(canonicalRow),
      },
    });
    registerDetails(model, deviceId, canonicalRow, 'replace');
  });

  return emitAdaptorResult(model);
}

// ── Adaptor 9: Home Assistant Matter Server native schema-13 topology ──────

export function adaptHaMatterWsNetworkTopology(
  fileMap,
  extractedRows = [],
) {
  const wrapper = fileMap.values().next().value;
  const topology = isPlainObject(wrapper?.topology) ? wrapper.topology : {};
  const model = createAdaptorModel(['ha-matter-ws-network-topology']);
  if (Array.isArray(topology.connections)) {
    registerRelationshipCapability(model, "nativeTopologyConnections");
  }

  const normalizedRowsByNativeId = new Map(
    asArray(extractedRows)
      .filter(isPlainObject)
      .map((row) => [toText(row.id), row]),
  );
  asArray(topology.nodes).forEach((rawNode) => {
    if (!isPlainObject(rawNode)) return;
    const node = normalizedRowsByNativeId.get(toText(rawNode.id)) ?? rawNode;
    const canonicalNode = nativeTopologyNodeRecord(node);
    if (!canonicalNode.id) return;
    registerDevice(model, canonicalNode, {
      id: canonicalNode.id,
      preserveId: true,
      sourceName: 'ha-matter-ws-network-topology',
      nodeRecord: canonicalNode,
      presentation: nativeTopologyNodePresentation(canonicalNode),
    });
    registerDetails(
      model,
      canonicalNode.id,
      node,
      'replace',
    );
  });

  asArray(topology.connections).forEach((connection, index) => {
    if (!isPlainObject(connection)) return;
    const sourceId = toText(connection.source);
    const targetId = toText(connection.target);
    if (!model.devicesById.has(sourceId) || !model.devicesById.has(targetId)) return;
    const category = connection.via_route_table === true
      ? EDGE_CATEGORY_OTBR_ROUTE
      : EDGE_CATEGORY_ROUTER_NEIGHBOR;
    const directions = [];
    if (isPlainObject(connection.source_to_target)) {
      directions.push(['source_to_target', sourceId, targetId, connection.source_to_target]);
    }
    if (isPlainObject(connection.target_to_source)) {
      directions.push(['target_to_source', targetId, sourceId, connection.target_to_source]);
    }
    if (directions.length === 0) {
      directions.push(['summary', sourceId, targetId, { strength: connection.strength }]);
    }

    directions.forEach(([directionName, fromId, toId, observation]) => {
      const directed = directionName !== 'summary';
      const metrics = {
        strength: observation.strength,
        lqi: observation.lqi,
        rssi: observation.rssi,
        pathCost: connection.path_cost,
        viaRouteTable: connection.via_route_table,
        network: connection.network,
        nativeDirection: directionName,
        nativeConnection: connection,
        nativeObservation: observation,
      };
      const presentation = {
        ...nativeStrengthStyle(observation.strength),
        ...(directed ? { arrows: 'to' } : {}),
        ...buildEdgeEndpointTitles(
          model.devicesById.get(fromId)?.nodeRecord,
          model.devicesById.get(toId)?.nodeRecord,
          fromId,
          toId,
        ),
        linkCategories: [category],
      };
      presentation.title = buildEdgeTitle({ ...metrics, ...presentation });
      registerRelationship(model, {
        id: `ha-matter-ws-native:${index}:${directionName}`,
        sourceId: fromId,
        targetId: toId,
        category,
        directed,
        sourceName: 'ha-matter-ws-network-topology',
        metrics,
        presentation,
        rawRecord: { connection, direction: directionName, observation },
      });
    });
  });

  return emitAdaptorResult(model);
}

function findMergedNativeTopologyRow(node, rows) {
  const nativeId = toText(node.id);
  const extAddress = getCanonicalExtaddr(node);
  const rloc16 = getCanonicalRloc16(node);
  return asArray(rows).find((row) =>
    toText(row?.id) === nativeId
    || (extAddress && getCanonicalExtaddr(row) === extAddress)
    || (rloc16 && getCanonicalRloc16(row) === rloc16));
}

function resolveNativeTopologyDevice(model, node, rows) {
  const roleRecord = findMergedNativeTopologyRow(node, rows) ?? node;
  const canonicalNode = nativeTopologyNodeRecord({
    ...node,
    ...roleRecord,
    id: node.id,
  });
  const extAddress = getCanonicalExtaddr(canonicalNode);
  const existingId = extAddress
    ? model.identityToDeviceId.get(`extAddress:${extAddress}`)
    : undefined;
  if (!canonicalNode.id) return '';
  const registeredId = existingId
    || (model.devicesById.has(canonicalNode.id) ? canonicalNode.id : undefined);
  if (registeredId) {
    registerDevice(model, canonicalNode, {
      id: registeredId,
      preserveId: true,
      sourceName: 'ha-matter-ws-network-topology',
      nodeRecord: canonicalNode,
      presentation: nativeTopologyNodePresentation(canonicalNode),
    });
    registerDetails(model, registeredId, roleRecord, 'preserve');
    return registeredId;
  }
  const deviceId = registerDevice(model, canonicalNode, {
    id: canonicalNode.id,
    preserveId: true,
    sourceName: 'ha-matter-ws-network-topology',
    nodeRecord: canonicalNode,
    presentation: nativeTopologyNodePresentation(canonicalNode),
  });
  registerDetails(
    model,
    deviceId,
    roleRecord,
    'preserve',
  );
  return deviceId;
}

export function adaptHaMatterWsMergeTopology(
  fileMap,
  extractedRows,
) {
  const baseResult = adaptHaMatterWs(
    fileMap,
    extractedRows,
    'merged-ha-matter-ws',
  );
  const model = createAdaptorModelFromResult(baseResult);
  const topology = fileMap.get('td-ha-matter-ws-network-topology.json')?.topology;
  if (!isPlainObject(topology)) return emitAdaptorResult(model);
  if (Array.isArray(topology.connections)) {
    registerRelationshipCapability(model, "nativeTopologyConnections");
  }

  const nativeIds = new Map();
  asArray(topology.nodes).forEach((node) => {
    if (!isPlainObject(node)) return;
    const deviceId = resolveNativeTopologyDevice(
      model,
      node,
      extractedRows,
    );
    if (deviceId) nativeIds.set(toText(node.id), deviceId);
  });

  asArray(topology.connections).forEach((connection, index) => {
    if (!isPlainObject(connection)) return;
    const sourceId = nativeIds.get(toText(connection.source));
    const targetId = nativeIds.get(toText(connection.target));
    if (!sourceId || !targetId) return;
    const category = connection.via_route_table === true
      ? EDGE_CATEGORY_OTBR_ROUTE
      : EDGE_CATEGORY_ROUTER_NEIGHBOR;
    const directions = [];
    if (isPlainObject(connection.source_to_target)) {
      directions.push(['source_to_target', sourceId, targetId, connection.source_to_target]);
    }
    if (isPlainObject(connection.target_to_source)) {
      directions.push(['target_to_source', targetId, sourceId, connection.target_to_source]);
    }
    if (directions.length === 0) {
      directions.push(['summary', sourceId, targetId, { strength: connection.strength }]);
    }
    directions.forEach(([directionName, fromId, toId, observation]) => {
      const directed = directionName !== 'summary';
      const metrics = {
        strength: observation.strength,
        lqi: observation.lqi,
        rssi: observation.rssi,
        pathCost: connection.path_cost,
        viaRouteTable: connection.via_route_table,
        network: connection.network,
        nativeDirection: directionName,
        nativeConnection: connection,
        nativeObservation: observation,
      };
      const presentation = {
        ...nativeStrengthStyle(observation.strength),
        ...(directed ? { arrows: 'to' } : {}),
        ...buildEdgeEndpointTitles(
          model.devicesById.get(fromId)?.nodeRecord,
          model.devicesById.get(toId)?.nodeRecord,
          fromId,
          toId,
        ),
        linkCategories: [category],
      };
      presentation.title = buildEdgeTitle({ ...metrics, ...presentation });
      registerRelationship(model, {
        id: `ha-matter-ws-merge-native:${index}:${directionName}`,
        sourceId: fromId,
        targetId: toId,
        category,
        directed,
        sourceName: 'ha-matter-ws-network-topology',
        metrics,
        presentation,
        rawRecord: { connection, direction: directionName, observation },
      });
    });
  });
  return emitAdaptorResult(model);
}
