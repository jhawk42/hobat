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
  lqStyleFromField, lqStyleFromAvgLqi, lqStyleFromLinkMargin
} from './tdash-topology-utils.js';
import { isPlaceholderOmrAddress } from './tdash-device-fields.js';
import {
  createAdaptorModel,
  createAdaptorModelFromResult,
  emitAdaptorResult,
  registerDetails,
  registerDevice,
  registerRelationship,
  registerRouterChildRows,
  registerRouterNeighborRows,
} from './tdash-adaptor-model.js';

import { asArray, emitThroughAdaptorModel, buildEdgeEndpointTitles, getOtbrRouteCategories } from './tdash-adaptor-shared.js';

const FILE_RESTAPI_DEVICES       = 'td-otbr-restapi-devices.json';

const FILE_RESTAPI_DIAGNOSTICS   = 'td-otbr-restapi-diagnostics.json';

const FILE_RESTAPI_DEVICES_LIST      = 'td-otbr-restapi-devices-list.json';

const FILE_RESTAPI_DEVICES_FETCH     = 'td-otbr-restapi-devices-fetch.json';

const FILE_RESTAPI_DIAGNOSTICS_LIST      = 'td-otbr-restapi-diagnostics-list.json';

const FILE_RESTAPI_DIAGNOSTICS_FETCH     = 'td-otbr-restapi-diagnostics-fetch.json';

const FILE_RESTAPI_DIAGNOSTICS_FETCH_ALL = 'td-otbr-restapi-diagnostics-fetch-all.json';
const FILE_ROUTER_CHILDIP6               = 'td-otbr-cli-meshdiag-router-childip6.json';

const FILE_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL = 'td-otbr-restapi-mesh-diagnostics-fetch-all.json';

// ── Adaptor 6: OTBR REST API (devices + diagnostics) ─────────────────────────
//
// Both files use { "data": [ { "id", "type", "attributes": {...} } ] } shape.
// Devices provide: extAddress, mlEidIid, omr_ipv6_addr, hostName, role, mode.
// Diagnostics provide: extAddress, rloc16, route.routeData[], childTable[].
// Primary node ID = extAddress (lowercase). Merged by extAddress identity.

export function extractOtbrRestApiItems(raw) {
  if (!raw) return [];
  const items = Array.isArray(raw)
    ? raw
    : (Array.isArray(raw.data) ? raw.data : (isPlainObject(raw) && raw.extAddress ? [raw] : []));
  return items
    .filter(isPlainObject)
    .map((item) => ({
      ...item,
      ...(isPlainObject(item.attributes) ? item.attributes : {}),
    }));
}

export function extractOtbrRestApiSources(fileMap) {
  const devicesRaw = fileMap.get(FILE_RESTAPI_DEVICES) ?? fileMap.get(FILE_RESTAPI_DEVICES_LIST) ?? fileMap.get(FILE_RESTAPI_DEVICES_FETCH);
  const meshDiagnosticsRaw = fileMap.get(FILE_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL);
  const diagRaw = meshDiagnosticsRaw ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_LIST) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_FETCH) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_FETCH_ALL);
  const basicDiagRaw = fileMap.has(FILE_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL)
    ? (fileMap.get(FILE_RESTAPI_DIAGNOSTICS) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_LIST) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_FETCH) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_FETCH_ALL))
    : null;
  const devices = extractOtbrRestApiItems(devicesRaw);
  const diagnostics = extractOtbrRestApiItems(diagRaw);
  const basicDiagnostics = extractOtbrRestApiItems(basicDiagRaw);
  const hasMeshDiagnostics = extractOtbrRestApiItems(meshDiagnosticsRaw).length > 0;
  const hasBasicDiagnostics = hasMeshDiagnostics
    ? basicDiagnostics.length > 0
    : diagnostics.length > 0;

  if (basicDiagnostics.length > 0) {
    const basicByExtaddr = new Map();
    basicDiagnostics.forEach(item => {
      const extaddr = toText(item.extAddress).toLowerCase();
      if (extaddr) basicByExtaddr.set(extaddr, item);
    });
    
    diagnostics.forEach((item, index) => {
      const extaddr = toText(item.extAddress).toLowerCase();
      const basic = basicByExtaddr.get(extaddr);
      if (basic) {
        diagnostics[index] = { ...basic, ...item };
      }
    });
  }

  return { devices, diagnostics, hasBasicDiagnostics, hasMeshDiagnostics };
}

export function adaptOtbrRestApi(fileMap, mergedRows = []) {
  const sources = extractOtbrRestApiSources(fileMap);
  return emitAdaptorResult(buildOtbrRestApiModel(sources, mergedRows));
}

export function buildOtbrRestApiModel({ devices, diagnostics, hasBasicDiagnostics = diagnostics.length > 0, hasMeshDiagnostics = false }, mergedRows = []) {

  const nodeMap = new Map();
  const rawByIdForDetails = new Map();
  const rloc16ToNodeId = new Map();
  const edgeMap = new Map();
  const edgeData = [];
  const routerIdsWithChildren = new Set();
  const routerNeighborByRloc16 = new Map();
  const routerChildByRloc16 = new Map();

  function upsertOtbrRestApiNode(nodeId, rawNode, style) {
    const existing = nodeMap.get(nodeId);
    const getRawMetric = (path) => toFiniteNumber(getColumnValue(rawNode, path));
    const roleText = toText(rawNode.role).toLowerCase();
    const isChildLike = roleText === 'child' || roleText.includes('sleepy');
    const modeDevice = rawNode.mode?.deviceTypeFTD === true ? 'FTD'
      : (rawNode.mode?.deviceTypeFTD === false ? 'MTD' : (existing ? existing.mode_device : ''));
    const rloc16Val = toText(rawNode.rloc16) || (existing ? existing.rloc16 : '');
    const extaddrVal = toText(rawNode.extAddress || rawNode.extaddr).toLowerCase() || (existing ? existing.extAddress : '');
    const merged = {
      id: nodeId,
      deviceLabel: toText(rawNode.hostName) || toText(rawNode.device_label) || (existing ? existing.deviceLabel || existing.device_label : ''),
      name: toText(rawNode.hostName) || toText(rawNode.device_label) || (existing ? existing.name : ''),
      rloc16: rloc16Val,
      extAddress: extaddrVal,
      type: roleText || toText(rawNode.type) || (existing ? existing.type : ''),
      role: roleText || (existing ? existing.role : ''),
      modeDevice: modeDevice || (existing ? existing.modeDevice || existing.mode_device : ''),
      omrIpv6Address: getCanonicalOmrIpv6Address(rawNode) || (existing ? existing.omrIpv6Address : ''),
      ifTotalErrorsTotalPktsRatio: getRawMetric('macCounters.ifTotalErrorsTotalPktsRatio')
        ?? (existing ? existing.ifTotalErrorsTotalPktsRatio || existing.iftotalerrors_totalpkts_ratio : undefined),
      ifTotalDiscardsTotalPktsRatio: getRawMetric('macCounters.ifTotalDiscardsTotalPktsRatio')
        ?? (existing ? existing.ifTotalDiscardsTotalPktsRatio || existing.iftotaldiscards_totalpkts_ratio : undefined),
      partitionIdChanges: getRawMetric('mleCounters.partIdChangesCount')
        ?? (existing ? existing.partitionIdChanges || existing.partitionidchanges : undefined),
      parentChanges: getRawMetric('mleCounters.newParentCount')
        ?? (existing ? existing.parentChanges || existing.parentchanges : undefined),
      betterPartitionAttachAttempts: getRawMetric('mleCounters.betterPartIdAttachAttemptsCount')
        ?? (existing ? existing.betterPartitionAttachAttempts || existing.betterpartitionattachattempts : undefined),
      totalParentPartitionChanges: getRawMetric('mleCounters.totalParentPartitionChangesCount')
        ?? (existing ? existing.totalParentPartitionChanges || existing.totalparentpartitionchanges : undefined),
      routerPct: getRawMetric('timeStatistics.routerPct')
        ?? (existing ? existing.routerPct || existing.router_pct : undefined),
      detachedDisabledPct: getRawMetric('timeStatistics.detachedDisabledPct')
        ?? (existing ? existing.detachedDisabledPct || existing.detached_disabled_pct : undefined),
      br: rawNode.br === true || (existing ? existing.br === true : false),
      isLeader: rawNode.isLeader === true || (existing ? existing.isLeader === true : false),
      isPrimaryBBR: rawNode.isPrimaryBBR === true || (existing ? existing.isPrimaryBBR === true : false),
      fromOtbrRestapi: true,
      shape: style.shape || (existing ? existing.shape : (isChildLike ? NODE_SHAPES.child : NODE_SHAPES.router)),
      color: style.color || (existing ? existing.color : NODE_COLORS.router)
    };
    merged.isFtdRouter = merged.modeDevice === 'FTD' && merged.rloc16.toLowerCase().endsWith('00');
    if (merged.br) merged.color = NODE_COLORS.borderRouter;
    nodeMap.set(nodeId, merged);
  }

  // Pass 1: register nodes from devices (extAddress as node ID)
  devices.forEach((node) => {
    const nodeId = toText(node.extAddress || node.extaddr).toLowerCase() || toText(node.id);
    if (!nodeId) return;
    const roleText = toText(node.role).toLowerCase();
    const isChildLike = roleText === 'child' || roleText.includes('sleepy');
    upsertOtbrRestApiNode(nodeId, node, {
      shape: isChildLike ? NODE_SHAPES.child : NODE_SHAPES.router,
      color: isChildLike ? NODE_COLORS.child : NODE_COLORS.router
    });
    rawByIdForDetails.set(nodeId, node);
  });

  // Pass 2: augment from diagnostics — adds rloc16, route, childTable
  diagnostics.forEach((node) => {
    const nodeId = toText(node.extAddress || node.extaddr).toLowerCase() || toText(node.id);
    if (!nodeId) return;
    upsertOtbrRestApiNode(nodeId, node, {
      shape: NODE_SHAPES.router,
      color: NODE_COLORS.router
    });
    const rloc16Val = toText(node.rloc16).toLowerCase();
    if (rloc16Val) rloc16ToNodeId.set(rloc16Val, nodeId);
    const existing = rawByIdForDetails.get(nodeId) || {};
    rawByIdForDetails.set(nodeId, mergeForDisplay(existing, node));
  });

  mergedRows.forEach((row) => {
    if (!isPlainObject(row)) return;
    const nodeId = getCanonicalExtaddr(row);
    if (!nodeId || !rawByIdForDetails.has(nodeId)) return;
    rawByIdForDetails.set(
      nodeId,
      mergeForDisplay(rawByIdForDetails.get(nodeId), row),
    );
  });

  // Pass 3: edges from diagnostics route.routeData (router routes) + childTable
  diagnostics.forEach((node) => {
    const fromId = toText(node.extAddress || node.extaddr).toLowerCase() || toText(node.id);
    if (!fromId || !nodeMap.has(fromId)) return;
    const fromNode = nodeMap.get(fromId);
    const routeCategories = getOtbrRouteCategories(node);

    (Array.isArray(node.route?.routeData) ? node.route.routeData : []).forEach((route) => {
      if (routeCategories.length === 0) return;
      const toRloc16 = buildMainRouterRloc16(route.routeId);
      if (!toRloc16) return;
      let toId = rloc16ToNodeId.get(toRloc16.toLowerCase()) || toRloc16;
      if (!nodeMap.has(toId)) {
        upsertOtbrRestApiNode(toId, { rloc16: toRloc16, id: toId },
          { shape: NODE_SHAPES.router, color: NODE_COLORS.router });
      }
      const lqiIn = toFiniteNumber(route.linkQualityIn);
      const lqiOut = toFiniteNumber(route.linkQualityOut);
      const lqi = Math.max(lqiOut || 0, lqiIn || 0);
      const lqStyle = lqStyleFromAvgLqi(lqi, 3);
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        ...lqStyle,
        lqiIn,
        lqiOut,
        ...buildEdgeEndpointTitles(fromNode, toNodeEnriched, fromId, toId),
        linkCategories: routeCategories
      });
    });

    (Array.isArray(node.childTable) ? node.childTable : []).forEach((child, ci) => {
      const childRloc16 = buildChildRloc16(toText(fromNode.rloc16), child.childId);
      const childLq = toFiniteNumber(child.linkQuality);
      const lqStyle = Number.isFinite(childLq) ? lqStyleFromAvgLqi(childLq, 3) : {};
      const childId = (childRloc16 && rloc16ToNodeId.get(childRloc16.toLowerCase()))
        || childRloc16
        || `${fromId}-child-${ci + 1}`;
      if (!nodeMap.has(childId)) {
        upsertOtbrRestApiNode(childId, { rloc16: childRloc16, id: childId, mode: child.mode },
          { shape: NODE_SHAPES.child, color: NODE_COLORS.child });
      }
      if (childRloc16) rloc16ToNodeId.set(childRloc16.toLowerCase(), childId);
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...lqStyle,
        ...buildEdgeEndpointTitles(
          fromNode,
          childNodeEnriched,
          fromId,
          childId,
        ),
        linkCategories: [EDGE_CATEGORY_OTBR_CHILD]
      });
      routerIdsWithChildren.add(fromId);
    });

    // Pass 3a: edges from children[] (mesh-diagnostics-fetch-all)
    (Array.isArray(node.children) ? node.children : []).forEach((child, ci) => {
      const childRloc16 = toText(child.rloc16);
      const childExtaddr = toText(child.extAddress).toLowerCase();
      const childId = (childRloc16 && rloc16ToNodeId.get(childRloc16.toLowerCase()))
        || childExtaddr
        || childRloc16
        || `${fromId}-children-${ci + 1}`;
      if (!nodeMap.has(childId)) {
        upsertOtbrRestApiNode(childId, {
          id: childId,
          rloc16: childRloc16,
          extAddress: childExtaddr,
          mode: { deviceTypeFTD: child.deviceTypeFTD },
        }, { shape: NODE_SHAPES.child, color: NODE_COLORS.child });
      } else if (childExtaddr || childRloc16) {
        upsertOtbrRestApiNode(childId, {
          id: childId,
          rloc16: childRloc16,
          extAddress: childExtaddr,
          mode: { deviceTypeFTD: child.deviceTypeFTD },
        }, { shape: NODE_SHAPES.child, color: NODE_COLORS.child });
      }
      if (childRloc16) rloc16ToNodeId.set(childRloc16.toLowerCase(), childId);
      const linkMargin = toFiniteNumber(child.linkMargin);
      const lqStyle = Number.isFinite(linkMargin) ? lqStyleFromLinkMargin(linkMargin) : {};
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...lqStyle,
        linkMargin,
        ...buildEdgeEndpointTitles(
          fromNode,
          childNodeEnriched,
          fromId,
          childId,
        ),
        linkCategories: [EDGE_CATEGORY_OTBR_CHILD]
      });
      routerIdsWithChildren.add(fromId);
      
      // Store child data for diagnostic filter support
      const fromRloc16 = toText(fromNode.rloc16).toLowerCase();
      if (fromRloc16) {
        if (!routerChildByRloc16.has(fromRloc16)) {
          routerChildByRloc16.set(fromRloc16, { rloc16: fromRloc16, router_child_table: [] });
        }
        const childRow = routerChildByRloc16.get(fromRloc16);
        if (Array.isArray(childRow.router_child_table)) {
          // Normalize field names (frameErrorRate → err_rate_frame_pct, etc.) and convert decimals to percentages
          const normalizedChild = normalizeNestedArrayFields([child])[0];
          childRow.router_child_table.push(normalizedChild);
        }
      }
    });

    // Pass 3b: edges from routerNeighbors (mesh-diagnostics-fetch-all)
    (Array.isArray(node.routerNeighbors) ? node.routerNeighbors : []).forEach((neighbor) => {
      const neighborExtaddr = toText(neighbor.extAddress).toLowerCase();
      const neighborRloc16 = toText(neighbor.rloc16).toLowerCase();
      let toId = neighborExtaddr || neighborRloc16;
      if (!toId) return;

      // Prefer extAddress-based lookup, fallback to rloc16
      if (neighborExtaddr && nodeMap.has(neighborExtaddr)) {
        toId = neighborExtaddr;
      } else if (neighborRloc16 && rloc16ToNodeId.has(neighborRloc16)) {
        toId = rloc16ToNodeId.get(neighborRloc16);
      } else if (!nodeMap.has(toId)) {
        // Create placeholder node for neighbor
        upsertOtbrRestApiNode(toId, {
          extAddress: neighborExtaddr,
          rloc16: neighborRloc16,
          id: toId
        }, { shape: NODE_SHAPES.router, color: NODE_COLORS.router });
        if (neighborRloc16) rloc16ToNodeId.set(neighborRloc16, toId);
      }

      // Style link based on linkMargin (dB)
      const lqStyle = lqStyleFromLinkMargin(neighbor.linkMargin);
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        ...lqStyle,
        linkMargin: neighbor.linkMargin,
        ...buildEdgeEndpointTitles(
          fromNode,
          toNodeEnriched,
          fromId,
          toId,
        ),
        linkCategories: [EDGE_CATEGORY_ROUTER_NEIGHBOR]
      });

      // Store neighbor data for potential detail display
      const fromRloc16 = toText(fromNode.rloc16).toLowerCase();
      if (fromRloc16) {
        if (!routerNeighborByRloc16.has(fromRloc16)) {
          routerNeighborByRloc16.set(fromRloc16, { rloc16: fromRloc16, router_neighbor_table: [] });
        }
        const neighborRow = routerNeighborByRloc16.get(fromRloc16);
        if (Array.isArray(neighborRow.router_neighbor_table)) {
          // Normalize field names (frameErrorRate → err_rate_frame_pct, etc.) and convert decimals to percentages
          const normalizedNeighbor = normalizeNestedArrayFields([neighbor])[0];
          neighborRow.router_neighbor_table.push(normalizedNeighbor);
        }
      }
    });
  });

  // Pass 4: group isolated unknown nodes
  const nodeData = buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, buildLabel, routerChildByRloc16);
  groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap);

  const sourceNames = [];
  if (devices.length > 0) sourceNames.push('otbr_restapi_devices');
  if (hasBasicDiagnostics) sourceNames.push('otbr_restapi_diagnostics');
  if (hasMeshDiagnostics) sourceNames.push('restapi_mesh_diagnostics');

  return createAdaptorModelFromResult({ nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, routerChildByRloc16, sourceNames });
}
