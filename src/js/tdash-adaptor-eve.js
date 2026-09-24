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



// ── Adaptor 2: Eve topology ───────────────────────────────────────────────────

export function adaptEve(fileMap) {
  const eveRaw = fileMap.values().next().value;
  const eveArray = Array.isArray(eveRaw) ? eveRaw
    : (eveRaw && typeof eveRaw === 'object' ? Object.values(eveRaw) : []);

  const nodeMap = new Map();
  const eveNodeById = new Map();
  const edgeMap = new Map();
  const edgeData = [];
  const routerIdsWithChildren = new Set();
  const routerNeighborByRloc16 = new Map();

  function upsertEveNode(nodeId, rawNode, style) {
    const existing = nodeMap.get(nodeId);
    const merged = {
      id: nodeId,
      name: toText(rawNode.name) || (existing ? existing.name : ''),
      deviceLabel: toText(rawNode.deviceLabel) || toText(rawNode.device_label)
        || (existing ? existing.deviceLabel || existing.device_label : ''),
      rloc16: toText(rawNode.rloc16) || (existing ? existing.rloc16 : ''),
      sourceId: toText(rawNode.id) || (existing ? existing.sourceId || existing.source_id : ''),
      extAddress: toText(rawNode.extaddr) || (existing ? existing.extAddress || existing.extaddr : ''),
      type: toText(rawNode.type) || (existing ? existing.type : ''),
      role: toText(rawNode.role).trim().toLowerCase() || (existing ? existing.role : ''),
      threadVersion: toText(rawNode.thread_version) || (existing ? existing.threadVersion || existing.thread_version : ''),
      threadStackVersion: toText(rawNode.thread_stack_version) || (existing ? existing.threadStackVersion || existing.thread_stack_version : ''),
      totalChildren: Number.isFinite(rawNode.totalChildren) ? rawNode.totalChildren : (existing ? existing.totalChildren || existing.total_children : 0),
      totalLinks: Number.isFinite(rawNode.totalLinks) ? rawNode.totalLinks : (existing ? existing.totalLinks || existing.total_links : 0),
      ifInDiscardsPct: Number.isFinite(rawNode.macCounters?.ifInDiscardsPercentage)
        ? rawNode.macCounters.ifInDiscardsPercentage : (existing?.ifInDiscardsPct || existing?.ifindiscards_pct),
      ifTotalErrorsPct: Number.isFinite(rawNode.macCounters?.ifTotalErrorsPercentage)
        ? rawNode.macCounters.ifTotalErrorsPercentage : (existing?.ifTotalErrorsPct || existing?.iftotalerrors_pct),
      ifTotalErrorsTotalPktsRatio: Number.isFinite(rawNode.macCounters?.ifTotalErrorsTotalPktsRatio)
        ? rawNode.macCounters.ifTotalErrorsTotalPktsRatio : (existing?.ifTotalErrorsTotalPktsRatio || existing?.iftotalerrors_totalpkts_ratio),
      ifTotalDiscardsTotalPktsRatio: Number.isFinite(rawNode.macCounters?.ifTotalDiscardsTotalPktsRatio)
        ? rawNode.macCounters.ifTotalDiscardsTotalPktsRatio : (existing?.ifTotalDiscardsTotalPktsRatio || existing?.iftotaldiscards_totalpkts_ratio),
      modeDevice: toText(rawNode.mode?.device)
        || (rawNode.type === 'router' ? 'FTD' : (rawNode.type === 'child' || rawNode.type === 'sleepy-child' ? 'MTD' : ''))
        || (existing ? existing.modeDevice || existing.mode_device : ''),
      partitionIdChanges: Number.isFinite(rawNode.mleCounters?.partIdChangesCount)
        ? rawNode.mleCounters.partIdChangesCount : (existing?.partitionIdChanges || existing?.partitionidchanges),
      parentChanges: Number.isFinite(rawNode.mleCounters?.newParentCount)
        ? rawNode.mleCounters.newParentCount : (existing?.parentChanges || existing?.parentchanges),
      br: rawNode.br === true || (existing ? existing.br === true : false),
      fromEve: true,
      shape: style.shape || (existing ? existing.shape : NODE_SHAPES.router),
      color: style.color || (existing ? existing.color : NODE_COLORS.eve)
    };
    // Apply role-based color overrides
    if (merged.br) {
      merged.color = NODE_COLORS.borderRouter;
    } else if (merged.shape === NODE_SHAPES.child) {
      // Child nodes (ellipse shape) should always use child color
      merged.color = NODE_COLORS.child;
    }
    nodeMap.set(nodeId, merged);
  }

  eveArray.forEach((node) => {
    const eveNodeId = toText(node.id);
    if (!eveNodeId) return;
    eveNodeById.set(eveNodeId, node);
    const isChildType = node.type === 'child' || node.type === 'sleepy-child';
    upsertEveNode(eveNodeId, node, {
      source: 'eve',
      shape: isChildType ? NODE_SHAPES.child : NODE_SHAPES.router,
      color: node.br ? NODE_COLORS.borderRouter
        : (isChildType ? NODE_COLORS.child : NODE_COLORS.eve)
    });
  });

  for (const node of eveArray) {
    const fromId = toText(node.id);
    if (!fromId) continue;
    (Array.isArray(node.routes) ? node.routes : []).forEach((route) => {
      const toId = toText(route.to);
      if (!toId) return;
      if (!nodeMap.has(toId)) {
        upsertEveNode(toId, { id: toId }, { source: 'eve', shape: NODE_SHAPES.router, color: NODE_COLORS.eve });
      }
      const lqiIn = toFiniteNumber(route.in);
      const lqiOut = toFiniteNumber(route.out);
      const avgLqi = (Number.isFinite(lqiIn) && Number.isFinite(lqiOut)) ? (lqiIn + lqiOut) / 2 : (lqiIn || lqiOut);
      const lqStyle = lqStyleFromAvgLqi(avgLqi, 3);
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        ...lqStyle,
        lqiIn,
        lqiOut,
        ...buildEdgeEndpointTitles(node, toNodeEnriched, fromId, toId),
        linkCategories: [EDGE_CATEGORY_EVE_ROUTE],
      });
    });
    (Array.isArray(node.children) ? node.children : []).forEach((child) => {
      const childObj = typeof child === 'string' ? {} : (child || {});
      const childId = toText(typeof child === 'string' ? child : child.id);
      if (!childId) return;
      if (!nodeMap.has(childId)) {
        upsertEveNode(childId, { id: childId }, { source: 'eve', shape: NODE_SHAPES.child, color: NODE_COLORS.child });
      }
      const childLq = toFiniteNumber(childObj.lq) || toFiniteNumber(childObj.link_quality);
      const lqStyle = Number.isFinite(childLq) ? lqStyleFromAvgLqi(childLq, 255) : {};
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...lqStyle,
        ...buildEdgeEndpointTitles(node, childNodeEnriched, fromId, childId),
        linkCategories: [EDGE_CATEGORY_EVE_CHILD]
      });
      routerIdsWithChildren.add(fromId);
    });
  }

  const nodeData = buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, buildLabel);

  const rawByIdForDetails = new Map();
  eveNodeById.forEach((raw, id) => rawByIdForDetails.set(id, raw));

  groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap);

  return emitThroughAdaptorModel({ nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, sourceNames: ['eve'] });
}

// ── Adaptor 2b: Eve native topology (Eve Thread Network Layout.evethreadlayout) ──

export function adaptEveNative(fileMap) {
  const raw = fileMap.values().next().value;
  // Native file shape: { version, nodes: [...] }
  // Fall back gracefully if the loader already normalised it to a plain array.
  const eveArray = (raw && Array.isArray(raw.nodes)) ? raw.nodes
    : (Array.isArray(raw) ? raw
      : (raw && typeof raw === 'object' ? Object.values(raw) : []));

  const nodeMap = new Map();
  const eveNodeById = new Map();
  const edgeMap = new Map();
  const edgeData = [];
  const routerIdsWithChildren = new Set();
  const routerNeighborByRloc16 = new Map();

  // Native rloc16 is a decimal integer; convert to canonical hex string '0xNNNN'.
  function nativeRloc16ToHex(value) {
    const n = toFiniteNumber(value);
    if (!Number.isFinite(n)) return '';
    return `0x${n.toString(16).padStart(4, '0')}`;
  }

  function upsertEveNativeNode(nodeId, rawNode, style) {
    const existing = nodeMap.get(nodeId);
    const rloc16Hex = nativeRloc16ToHex(rawNode.rloc16) || (existing ? existing.rloc16 : '');
    const merged = {
      id: nodeId,
      name: toText(rawNode.name) || (existing ? existing.name : ''),
      deviceLabel: toText(rawNode.deviceLabel || rawNode.device_label) || toText(rawNode.name) || (existing ? existing.deviceLabel : ''),
      rloc16: rloc16Hex,
      source_id: toText(rawNode.id) || (existing ? existing.source_id : ''),
      extAddress: toText(rawNode.extAddress || rawNode.extaddr) || (existing ? existing.extAddress : ''),
      type: toText(rawNode.type) || (existing ? existing.type : ''),
      role: toText(rawNode.role).trim().toLowerCase() || (existing ? existing.role : ''),
      room: toText(rawNode.room) || (existing ? existing.room : ''),
      ip_addresses: Array.isArray(rawNode.ip_addresses) ? rawNode.ip_addresses
        : (existing ? existing.ip_addresses : []),
      threadNetworks: Array.isArray(rawNode.threadNetworks) ? rawNode.threadNetworks
        : (existing ? existing.threadNetworks : []),
      mode_device: rawNode.type === 'router' ? 'FTD'
        : (rawNode.type === 'child' || rawNode.type === 'sleepy-child' ? 'MTD' : '')
        || (existing ? existing.mode_device : ''),
      br: rawNode.br === true || (existing ? existing.br === true : false),
      from_eve_native: true,
      shape: style.shape || (existing ? existing.shape : NODE_SHAPES.router),
      color: style.color || (existing ? existing.color : NODE_COLORS.eve)
    };
    // Apply role-based color overrides
    if (merged.br) {
      merged.color = NODE_COLORS.borderRouter;
    } else if (merged.shape === NODE_SHAPES.child) {
      // Child nodes (ellipse shape) should always use child color
      merged.color = NODE_COLORS.child;
    }
    nodeMap.set(nodeId, merged);
  }

  // Pass 1: register all nodes
  eveArray.forEach((node) => {
    const eveNodeId = toText(node.id);
    if (!eveNodeId) return;
    eveNodeById.set(eveNodeId, node);
    const isChildType = node.type === 'child' || node.type === 'sleepy-child';
    upsertEveNativeNode(eveNodeId, node, {
      source: 'eve_native',
      shape: isChildType ? NODE_SHAPES.child : NODE_SHAPES.router,
      color: node.br ? NODE_COLORS.borderRouter
        : (isChildType ? NODE_COLORS.child : NODE_COLORS.eve)
    });
  });

  // Pass 2: build edges from routes[] and children[]
  for (const node of eveArray) {
    const fromId = toText(node.id);
    if (!fromId) continue;

    (Array.isArray(node.routes) ? node.routes : []).forEach((route) => {
      const toId = toText(route.to);
      if (!toId) return;
      if (!nodeMap.has(toId)) {
        upsertEveNativeNode(toId, { id: toId }, { source: 'eve_native', shape: NODE_SHAPES.router, color: NODE_COLORS.eve });
      }
      const lqiIn = toFiniteNumber(route.in);
      const lqiOut = toFiniteNumber(route.out);
      const avgLqi = (Number.isFinite(lqiIn) && Number.isFinite(lqiOut)) ? (lqiIn + lqiOut) / 2 : (lqiIn || lqiOut);
      const lqStyle = lqStyleFromAvgLqi(avgLqi, 3);
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        ...lqStyle,
        lqiIn,
        lqiOut,
        ...buildEdgeEndpointTitles(node, toNodeEnriched, fromId, toId),
        linkCategories: [EDGE_CATEGORY_EVE_NATIVE_ROUTE],
      });
    });

    (Array.isArray(node.children) ? node.children : []).forEach((child) => {
      const childObj = typeof child === 'string' ? {} : (child || {});
      const childId = toText(typeof child === 'string' ? child : child.id);
      if (!childId) return;
      if (!nodeMap.has(childId)) {
        upsertEveNativeNode(childId, { id: childId }, { source: 'eve_native', shape: NODE_SHAPES.child, color: NODE_COLORS.child });
      }
      const childLq = toFiniteNumber(childObj.lq);
      const lqStyle = Number.isFinite(childLq) ? lqStyleFromAvgLqi(childLq, 3) : {};
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...lqStyle,
        ...buildEdgeEndpointTitles(node, childNodeEnriched, fromId, childId),
        linkCategories: [EDGE_CATEGORY_EVE_NATIVE_CHILD]
      });
      routerIdsWithChildren.add(fromId);
    });
  }

  const nodeData = buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, buildLabel);

  const rawByIdForDetails = new Map();
  eveNodeById.forEach((raw, id) => rawByIdForDetails.set(id, raw));

  groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap);

  return emitThroughAdaptorModel({ nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, sourceNames: ['eve_native'] });
}
