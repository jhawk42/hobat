import {
  EDGE_CATEGORY_DEFAULT_CHILDREN, EDGE_CATEGORY_DEFAULT_1,
  EDGE_CATEGORY_DEFAULT_2, EDGE_CATEGORY_DEFAULT_3,
  EDGE_CATEGORY_ROUTER_NEIGHBOR, EDGE_CATEGORY_OTBR_ROUTE,
  EDGE_CATEGORY_OTBR_CHILD, EDGE_CATEGORY_EVE_ROUTE,
  EDGE_CATEGORY_EVE_CHILD, EDGE_CATEGORY_EVE_NATIVE_ROUTE,
  EDGE_CATEGORY_EVE_NATIVE_CHILD, NODE_COLORS, PALETTE
} from './tdash-constants.js';
import {
  toText, toFiniteNumber, isPlainObject,
  getCanonicalRloc16, getCanonicalExtaddr,
  mergeForDisplay
} from './tdash-utils.js';
import {
  chooseNodeId, buildLabel,
  buildMainRouterRloc16, buildChildRloc16,
  addEdge, groupIsolatedUnknownNodes, buildVisNodeData,
  lqStyleFromField, lqStyleFromAvgLqi
} from './tdash-topology-utils.js';

// ── Adaptor 1: meshdiag + networkdiag + routerNeighbors + restApi ─────────────

export function adaptMeshdiagNetworkdiag(rawFiles) {
  const meshdiag = Array.isArray(rawFiles[0]) ? rawFiles[0] : [];
  const networkDiag = Array.isArray(rawFiles[1]) ? rawFiles[1] : [];
  const routerNeighborTables = Array.isArray(rawFiles[2]) ? rawFiles[2] : [];
  const restApiRaw = rawFiles[3];
  const restApiDiagnostics = (restApiRaw && Array.isArray(restApiRaw.data))
    ? restApiRaw.data
      .map((item) => ({ id: item.id, type: item.type, ...(item.attributes || {}) }))
      .filter((item) => item && typeof item === 'object')
    : [];

  const nodeMap = new Map();
  const meshdiagById = new Map();
  const networkDiagById = new Map();
  const restApiById = new Map();
  const meshIdToUnifiedId = new Map();
  const edgeMap = new Map();
  const edgeData = [];
  const routerIdsWithChildren = new Set();
  const routerNeighborByRloc16 = new Map();

  function upsertNode(nodeId, rawNode, style) {
    const existing = nodeMap.get(nodeId);
    const rawIpv6 = Array.isArray(rawNode.ipv6_addrs) ? rawNode.ipv6_addrs : [];
    const existingIpv6 = existing && Array.isArray(existing.ipv6_addrs) ? existing.ipv6_addrs : [];
    const mergedIpv6 = rawIpv6.length > 0 ? rawIpv6 : existingIpv6;
    const rawChildren = Array.isArray(rawNode.children) ? rawNode.children : [];
    const rawPacketErrorDiscardPct = rawNode.mac_counters && Number.isFinite(rawNode.mac_counters.ifindiscards_pct)
      ? rawNode.mac_counters.ifindiscards_pct : undefined;
    const rawInerrorsPct = rawNode.mac_counters && Number.isFinite(rawNode.mac_counters.ifinerrors_pct)
      ? rawNode.mac_counters.ifinerrors_pct : undefined;
    const rawOuterrorsPct = rawNode.mac_counters && Number.isFinite(rawNode.mac_counters.ifouterrors_pct)
      ? rawNode.mac_counters.ifouterrors_pct : undefined;
    const rawModeDevice = rawNode.mode && toText(rawNode.mode.device)
      ? toText(rawNode.mode.device)
      : (rawNode.mode?.deviceTypeFTD === true ? 'FTD' : (rawNode.mode?.deviceTypeFTD === false ? 'MTD' : ''));
    const rawPartitionIdChanges = rawNode.mle_counters && Number.isFinite(rawNode.mle_counters.partitionidchanges)
      ? rawNode.mle_counters.partitionidchanges : undefined;
    const rawParentChanges = rawNode.mle_counters && Number.isFinite(rawNode.mle_counters.parentchanges)
      ? rawNode.mle_counters.parentchanges : undefined;
    const merged = {
      id: nodeId,
      device_label: toText(rawNode.device_label) || (existing ? existing.device_label : ''),
      rloc16: toText(rawNode.rloc16) || (existing ? existing.rloc16 : ''),
      source_id: toText(rawNode.id) || (existing ? existing.source_id : ''),
      extaddr: toText(rawNode.extaddr) || (existing ? existing.extaddr : ''),
      type: toText(rawNode.type) || (existing ? existing.type : ''),
      thread_stack_version: toText(rawNode.thread_stack_version) || (existing ? existing.thread_stack_version : ''),
      ipv6_addrs: mergedIpv6,
      total_children: Number.isFinite(rawNode.total_children)
        ? rawNode.total_children : (rawChildren.length || (existing ? existing.total_children : 0)),
      total_links: Number.isFinite(rawNode.total_links) ? rawNode.total_links : (existing ? existing.total_links : 0),
      ifindiscards_pct: Number.isFinite(rawPacketErrorDiscardPct) ? rawPacketErrorDiscardPct
        : (existing && Number.isFinite(existing.ifindiscards_pct) ? existing.ifindiscards_pct : undefined),
      ifinerrors_pct: Number.isFinite(rawInerrorsPct) ? rawInerrorsPct
        : (existing && Number.isFinite(existing.ifinerrors_pct) ? existing.ifinerrors_pct : undefined),
      ifouterrors_pct: Number.isFinite(rawOuterrorsPct) ? rawOuterrorsPct
        : (existing && Number.isFinite(existing.ifouterrors_pct) ? existing.ifouterrors_pct : undefined),
      mode_device: rawModeDevice || (existing ? existing.mode_device : ''),
      partitionidchanges: Number.isFinite(rawPartitionIdChanges) ? rawPartitionIdChanges
        : (existing && Number.isFinite(existing.partitionidchanges) ? existing.partitionidchanges : undefined),
      parentchanges: Number.isFinite(rawParentChanges) ? rawParentChanges
        : (existing && Number.isFinite(existing.parentchanges) ? existing.parentchanges : undefined),
      br: rawNode.br === true || (existing ? existing.br === true : false),
      from_meshdiag: (style.source === 'meshdiag') || (existing ? existing.from_meshdiag === true : false),
      from_networkdiagnostic: (style.source === 'networkdiagnostic') || (existing ? existing.from_networkdiagnostic === true : false),
      shape: style.shape || (existing ? existing.shape : 'box'),
      color: style.color || (existing ? existing.color : NODE_COLORS.router)
    };
    if (merged.br) merged.color = NODE_COLORS.borderRouter;
    nodeMap.set(nodeId, merged);
  }

  function ensureNode(nodeId, rawNode, style) {
    if (!nodeId) return '';
    if (!nodeMap.has(nodeId)) upsertNode(nodeId, rawNode, style);
    return nodeId;
  }

  meshdiag.forEach((node, index) => {
    const uid = chooseNodeId(node, 'meshdiag-node', index + 1);
    meshdiagById.set(uid, node);
    const meshRawId = toText(node.id);
    if (meshRawId) meshIdToUnifiedId.set(meshRawId, uid);
    upsertNode(uid, node, {
      source: 'meshdiag', shape: 'box',
      color: node.br ? NODE_COLORS.borderRouter : NODE_COLORS.router
    });
  });

  networkDiag.forEach((node, index) => {
    const uid = chooseNodeId(node, 'netdiag-node', index + 1);
    networkDiagById.set(uid, node);
    upsertNode(uid, node, { source: 'networkdiagnostic', shape: 'box', color: NODE_COLORS.router });
  });

  restApiDiagnostics.forEach((node, index) => {
    const uid = chooseNodeId(node, 'restapi-node', index + 1);
    restApiById.set(uid, node);
    upsertNode(uid, node, { source: 'networkdiagnostic', shape: 'box', color: NODE_COLORS.router });
  });

  routerNeighborTables.forEach((row) => {
    const rloc16 = toText(row.rloc16).toLowerCase();
    if (rloc16) routerNeighborByRloc16.set(rloc16, row);
  });

  for (const node of meshdiag) {
    const fromId = chooseNodeId(node, 'meshdiag-parent', 0);
    (Array.isArray(node.children) ? node.children : []).forEach((child, ci) => {
      const childId = toText(child.rloc16) || `${fromId}-child-${ci + 1}`;
      upsertNode(childId, { device_label: toText(child.device_label), rloc16: toText(child.rloc16), id: childId },
        { source: 'meshdiag', shape: 'ellipse', color: NODE_COLORS.child });
      addEdge(edgeMap, edgeData, fromId, childId, { dashes: false, isParentChild: true, linkCategories: [EDGE_CATEGORY_DEFAULT_CHILDREN] });
      routerIdsWithChildren.add(fromId);
    });

    ['3_links', '2_links', '1_links'].forEach((field) => {
      const lqStyle = lqStyleFromField(field);
      (Array.isArray(node[field]) ? node[field] : []).forEach((link) => {
        const linkMeshId = toText(link.id);
        const toId = meshIdToUnifiedId.get(linkMeshId) || toText(link.rloc16) || linkMeshId;
        if (!toId) return;
        if (!nodeMap.has(toId)) {
          upsertNode(toId, { device_label: toText(link.device_label), rloc16: toText(link.rloc16), id: linkMeshId || toId },
            { source: 'meshdiag', shape: 'box', color: NODE_COLORS.eve });
        }
        addEdge(edgeMap, edgeData, fromId, toId, {
          ...lqStyle,
          linkCategories: [field === '3_links' ? EDGE_CATEGORY_DEFAULT_3 : field === '2_links' ? EDGE_CATEGORY_DEFAULT_2 : EDGE_CATEGORY_DEFAULT_1]
        });
      });
    });

    const neighborRow = routerNeighborByRloc16.get(toText(node.rloc16).toLowerCase());
    (Array.isArray(neighborRow?.router_neighbor_table) ? neighborRow.router_neighbor_table : []).forEach((neighbor) => {
      const toId = ensureNode(
        toText(neighbor.rloc16) || toText(neighbor.extaddr),
        {
          rloc16: toText(neighbor.rloc16), extaddr: toText(neighbor.extaddr), device_label: toText(neighbor.device_label),
          id: toText(neighbor.rloc16) || toText(neighbor.extaddr)
        },
        { source: 'meshdiag', shape: 'box', color: NODE_COLORS.eve }
      );
      addEdge(edgeMap, edgeData, fromId, toId, { width: 1.5, linkCategories: [EDGE_CATEGORY_ROUTER_NEIGHBOR] });
    });
  }

  for (const node of networkDiag) {
    const fromId = chooseNodeId(node, 'netdiag-parent', 0);
    (Array.isArray(node.children) ? node.children : []).forEach((child, ci) => {
      const childId = toText(child.rloc16) || `${fromId}-child-${ci + 1}`;
      upsertNode(childId, { device_label: toText(child.device_label), rloc16: toText(child.rloc16), id: childId },
        { source: 'networkdiagnostic', shape: 'ellipse', color: NODE_COLORS.child });
      addEdge(edgeMap, edgeData, fromId, childId, { dashes: false, isParentChild: true, linkCategories: [EDGE_CATEGORY_DEFAULT_CHILDREN] });
      routerIdsWithChildren.add(fromId);
    });
  }

  restApiDiagnostics.forEach((node) => {
    const fromId = chooseNodeId(node, 'restapi-parent', 0);
    (Array.isArray(node.route?.routeData) ? node.route.routeData : []).forEach((route) => {
      const toRloc16 = buildMainRouterRloc16(route.routeId);
      const toId = ensureNode(toRloc16, { rloc16: toRloc16, id: toRloc16, device_label: toRloc16 },
        { source: 'networkdiagnostic', shape: 'box', color: NODE_COLORS.router });
      addEdge(edgeMap, edgeData, fromId, toId, { width: 1.5, linkCategories: [EDGE_CATEGORY_OTBR_ROUTE] });
    });
    (Array.isArray(node.childTable) ? node.childTable : []).forEach((child, ci) => {
      const childRloc16 = buildChildRloc16(node.rloc16, child.childId);
      const childId = ensureNode(
        childRloc16 || `${fromId}-rest-child-${ci + 1}`,
        {
          rloc16: childRloc16, id: childRloc16 || `${fromId}-rest-child-${ci + 1}`,
          device_label: childRloc16 || `${fromId} child ${child.childId}`
        },
        { source: 'networkdiagnostic', shape: 'ellipse', color: NODE_COLORS.child }
      );
      addEdge(edgeMap, edgeData, fromId, childId, { dashes: false, isParentChild: true, linkCategories: [EDGE_CATEGORY_OTBR_CHILD] });
      routerIdsWithChildren.add(fromId);
    });
  });

  const nodeData = buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, buildLabel);

  const rawByIdForDetails = new Map();
  nodeMap.forEach((_, id) => {
    const m = meshdiagById.get(id) || {};
    const n = networkDiagById.get(id) || {};
    const r = restApiById.get(id) || {};
    rawByIdForDetails.set(id, mergeForDisplay(mergeForDisplay(m, n), r));
  });

  const sourceNames = [];
  if (meshdiag.length > 0) sourceNames.push('meshdiag');
  if (networkDiag.length > 0) sourceNames.push('networkdiagnostic');
  if (routerNeighborTables.length > 0) sourceNames.push('routerneighbortables');
  if (restApiDiagnostics.length > 0) sourceNames.push('restapi');

  groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap);

  return { nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, sourceNames };
}

// ── Adaptor 2: Eve topology ───────────────────────────────────────────────────

export function adaptEve(rawFiles) {
  const eveRaw = rawFiles[0];
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
      device_label: toText(rawNode.device_label) || (existing ? existing.device_label : ''),
      rloc16: toText(rawNode.rloc16) || (existing ? existing.rloc16 : ''),
      source_id: toText(rawNode.id) || (existing ? existing.source_id : ''),
      extaddr: toText(rawNode.extaddr) || (existing ? existing.extaddr : ''),
      type: toText(rawNode.type) || (existing ? existing.type : ''),
      thread_stack_version: toText(rawNode.thread_stack_version) || (existing ? existing.thread_stack_version : ''),
      total_children: Number.isFinite(rawNode.total_children) ? rawNode.total_children : (existing ? existing.total_children : 0),
      total_links: Number.isFinite(rawNode.total_links) ? rawNode.total_links : (existing ? existing.total_links : 0),
      ifindiscards_pct: Number.isFinite(rawNode.mac_counters?.ifindiscards_pct)
        ? rawNode.mac_counters.ifindiscards_pct : (existing?.ifindiscards_pct),
      iftotalerrors_pct: Number.isFinite(rawNode.mac_counters?.iftotalerrors_pct)
        ? rawNode.mac_counters.iftotalerrors_pct : (existing?.iftotalerrors_pct),
      mode_device: toText(rawNode.mode?.device)
        || (rawNode.type === 'router' ? 'FTD' : (rawNode.type === 'child' || rawNode.type === 'sleepy-child' ? 'MTD' : ''))
        || (existing ? existing.mode_device : ''),
      partitionidchanges: Number.isFinite(rawNode.mle_counters?.partitionidchanges)
        ? rawNode.mle_counters.partitionidchanges : (existing?.partitionidchanges),
      parentchanges: Number.isFinite(rawNode.mle_counters?.parentchanges)
        ? rawNode.mle_counters.parentchanges : (existing?.parentchanges),
      br: rawNode.br === true || (existing ? existing.br === true : false),
      from_eve: true,
      shape: style.shape || (existing ? existing.shape : 'box'),
      color: style.color || (existing ? existing.color : NODE_COLORS.eve)
    };
    if (merged.br) merged.color = NODE_COLORS.borderRouter;
    nodeMap.set(nodeId, merged);
  }

  eveArray.forEach((node) => {
    const eveNodeId = toText(node.id);
    if (!eveNodeId) return;
    eveNodeById.set(eveNodeId, node);
    const isChildType = node.type === 'child' || node.type === 'sleepy-child';
    upsertEveNode(eveNodeId, node, {
      source: 'eve',
      shape: isChildType ? 'ellipse' : 'box',
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
        upsertEveNode(toId, { id: toId }, { source: 'eve', shape: 'box', color: NODE_COLORS.eve });
      }
      const lqiIn = toFiniteNumber(route.in);
      const lqiOut = toFiniteNumber(route.out);
      const avgLqi = (Number.isFinite(lqiIn) && Number.isFinite(lqiOut)) ? (lqiIn + lqiOut) / 2 : (lqiIn || lqiOut);
      const lqStyle = lqStyleFromAvgLqi(avgLqi, 255);
      addEdge(edgeMap, edgeData, fromId, toId, { ...lqStyle, linkCategories: [EDGE_CATEGORY_EVE_ROUTE] });
    });
    (Array.isArray(node.children) ? node.children : []).forEach((child) => {
      const childId = toText(typeof child === 'string' ? child : child.id);
      if (!childId) return;
      if (!nodeMap.has(childId)) {
        upsertEveNode(childId, { id: childId }, { source: 'eve', shape: 'ellipse', color: NODE_COLORS.child });
      }
      addEdge(edgeMap, edgeData, fromId, childId, { dashes: false, isParentChild: true, linkCategories: [EDGE_CATEGORY_EVE_CHILD] });
      routerIdsWithChildren.add(fromId);
    });
  }

  const nodeData = buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, buildLabel);

  const rawByIdForDetails = new Map();
  eveNodeById.forEach((raw, id) => rawByIdForDetails.set(id, raw));

  groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap);

  return { nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, sourceNames: ['eve'] };
}

// ── Adaptor 2b: Eve native topology (Eve Thread Network Layout.evethreadlayout) ──

export function adaptEveNative(rawFiles) {
  const raw = rawFiles[0];
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
      device_label: toText(rawNode.device_label) || toText(rawNode.name) || (existing ? existing.device_label : ''),
      rloc16: rloc16Hex,
      source_id: toText(rawNode.id) || (existing ? existing.source_id : ''),
      extaddr: toText(rawNode.extaddr) || (existing ? existing.extaddr : ''),
      type: toText(rawNode.type) || (existing ? existing.type : ''),
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
      shape: style.shape || (existing ? existing.shape : 'box'),
      color: style.color || (existing ? existing.color : NODE_COLORS.eve)
    };
    if (merged.br) merged.color = NODE_COLORS.borderRouter;
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
      shape: isChildType ? 'ellipse' : 'box',
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
        upsertEveNativeNode(toId, { id: toId }, { source: 'eve_native', shape: 'box', color: NODE_COLORS.eve });
      }
      const lqiIn = toFiniteNumber(route.in);
      const lqiOut = toFiniteNumber(route.out);
      const avgLqi = (Number.isFinite(lqiIn) && Number.isFinite(lqiOut)) ? (lqiIn + lqiOut) / 2 : (lqiIn || lqiOut);
      const lqStyle = lqStyleFromAvgLqi(avgLqi, 3);
      addEdge(edgeMap, edgeData, fromId, toId, { ...lqStyle, linkCategories: [EDGE_CATEGORY_EVE_NATIVE_ROUTE] });
    });

    (Array.isArray(node.children) ? node.children : []).forEach((child) => {
      const childId = toText(typeof child === 'string' ? child : child.id);
      if (!childId) return;
      if (!nodeMap.has(childId)) {
        upsertEveNativeNode(childId, { id: childId }, { source: 'eve_native', shape: 'ellipse', color: NODE_COLORS.child });
      }
      addEdge(edgeMap, edgeData, fromId, childId, { dashes: false, isParentChild: true, linkCategories: [EDGE_CATEGORY_EVE_NATIVE_CHILD] });
      routerIdsWithChildren.add(fromId);
    });
  }

  const nodeData = buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, buildLabel);

  const rawByIdForDetails = new Map();
  eveNodeById.forEach((raw, id) => rawByIdForDetails.set(id, raw));

  groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap);

  return { nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, sourceNames: ['eve_native'] };
}

// ── Adaptor 3: Merged detailed topology ──────────────────────────────────────

export function adaptMergedDetailed(rawFiles) {
  const rows = Array.isArray(rawFiles[0]) ? rawFiles[0] : [];
  const nodeMap = new Map();
  const rawNodeById = new Map();
  const edgeMap = new Map();
  const edgeData = [];
  const routerIdsWithChildren = new Set();
  const routerNeighborByRloc16 = new Map();

  function isMergedRowEveOnly(node) {
    const sources = Array.isArray(node?._sources) ? node._sources : [];
    if (!sources.includes('td-eve-topology.json')) return false;
    return !sources.some((s) => s === 'td-otbr-cli-router-table.json'
      || s === 'td-otbr-cli-meshdiag-topology.json'
      || s === 'td-otbr-cli-networkdiag-topology.json'
      || s === 'td-otbr-cli-meshdiag-router-neighbortables.json'
      || s === 'td-otbr-restapi-devices.json'
      || s === 'td-otbr-restapi-diagnostics.json');
  }

  function chooseMergedId(node, index) {
    return toText(node.rloc16) || toText(node.id) || toText(node.extaddr) || `merged-node-${index + 1}`;
  }

  function upsertMergedNode(nodeId, rawNode, style) {
    const existing = nodeMap.get(nodeId);
    const merged = {
      id: nodeId,
      name: toText(rawNode.name) || (existing ? existing.name : ''),
      device_label: toText(rawNode.device_label) || (existing ? existing.device_label : ''),
      rloc16: toText(rawNode.rloc16) || (existing ? existing.rloc16 : ''),
      source_id: toText(rawNode.id) || (existing ? existing.source_id : ''),
      extaddr: toText(rawNode.extaddr) || (existing ? existing.extaddr : ''),
      type: toText(rawNode.type) || (existing ? existing.type : ''),
      thread_stack_version: toText(rawNode.thread_stack_version) || (existing ? existing.thread_stack_version : ''),
      total_children: Number.isFinite(rawNode.total_children) ? rawNode.total_children : (existing ? existing.total_children : 0),
      total_links: Number.isFinite(rawNode.total_links) ? rawNode.total_links : (existing ? existing.total_links : 0),
      ifindiscards_pct: Number.isFinite(rawNode.mac_counters?.ifindiscards_pct)
        ? rawNode.mac_counters.ifindiscards_pct : (existing?.ifindiscards_pct),
      iftotalerrors_pct: Number.isFinite(rawNode.mac_counters?.iftotalerrors_pct)
        ? rawNode.mac_counters.iftotalerrors_pct : (existing?.iftotalerrors_pct),
      mode_device: toText(rawNode['mode.device']) || toText(rawNode.mode?.device) || (existing ? existing.mode_device : ''),
      partitionidchanges: Number.isFinite(rawNode.mle_counters?.partitionidchanges)
        ? rawNode.mle_counters.partitionidchanges : (existing?.partitionidchanges),
      parentchanges: Number.isFinite(rawNode.mle_counters?.parentchanges)
        ? rawNode.mle_counters.parentchanges : (existing?.parentchanges),
      br: rawNode.br === true || (existing ? existing.br === true : false),
      from_merged_detailed: true,
      shape: style.shape || (existing ? existing.shape : 'box'),
      color: style.color || (existing ? existing.color : NODE_COLORS.eve)
    };
    if (merged.br) merged.color = NODE_COLORS.borderRouter;
    nodeMap.set(nodeId, merged);
  }

  function ensureNodeForLink(linkNode, fallbackId) {
    const candidateId = toText(linkNode.rloc16) || toText(linkNode.id) || toText(fallbackId);
    if (!candidateId) return '';
    if (!nodeMap.has(candidateId)) {
      upsertMergedNode(candidateId, {
        rloc16: toText(linkNode.rloc16), id: toText(linkNode.id) || candidateId,
        device_label: toText(linkNode.device_label), name: toText(linkNode.name)
      }, { source: 'merged-detailed', shape: 'box', color: NODE_COLORS.eve });
    }
    return candidateId;
  }

  rows.forEach((node, index) => {
    if (isMergedRowEveOnly(node)) return;
    const nodeId = chooseMergedId(node, index);
    rawNodeById.set(nodeId, node);
    const rloc16Text = toText(node.rloc16).toLowerCase();
    const modeDevice = toText(node['mode.device'] || node.mode?.device).toUpperCase();
    const isRouterLike = rloc16Text.endsWith('00') || modeDevice === 'FTD' || toText(node.type).toLowerCase() === 'router';
    const isChildLike = modeDevice === 'MTD' || toText(node.type).toLowerCase().includes('child');
    upsertMergedNode(nodeId, node, {
      source: 'merged-detailed',
      shape: isChildLike && !isRouterLike ? 'ellipse' : 'box',
      color: isChildLike && !isRouterLike ? NODE_COLORS.child : NODE_COLORS.eve
    });
    // populate routerNeighborByRloc16 for filter support
    if (Array.isArray(node.router_neighbor_table) && rloc16Text) {
      routerNeighborByRloc16.set(rloc16Text, node);
    }
  });

  rows.forEach((node, index) => {
    if (isMergedRowEveOnly(node)) return;
    const fromId = chooseMergedId(node, index);
    ['3_links', '2_links', '1_links'].forEach((key) => {
      const lqStyle = lqStyleFromField(key);
      (Array.isArray(node[key]) ? node[key] : []).forEach((link) => {
        const toId = ensureNodeForLink(link, link.rloc16 || link.id);
        if (!toId) return;
        addEdge(edgeMap, edgeData, fromId, toId, {
          ...lqStyle,
          linkCategories: [key === '3_links' ? EDGE_CATEGORY_DEFAULT_3 : key === '2_links' ? EDGE_CATEGORY_DEFAULT_2 : EDGE_CATEGORY_DEFAULT_1],
          edgeKeySuffix: `merged-${key}`
        });
      });
    });
    (Array.isArray(node.router_neighbor_table) ? node.router_neighbor_table : []).forEach((neighbor) => {
      const toId = ensureNodeForLink(neighbor, neighbor.rloc16 || neighbor.extaddr || neighbor.id);
      if (!toId) return;
      addEdge(edgeMap, edgeData, fromId, toId, { width: 1.5, linkCategories: [EDGE_CATEGORY_ROUTER_NEIGHBOR], edgeKeySuffix: 'merged-router-neighbor' });
    });
    (Array.isArray(node.route?.routeData) ? node.route.routeData : []).forEach((route) => {
      const toRloc16 = buildMainRouterRloc16(route.routeId);
      const toId = ensureNodeForLink({ rloc16: toRloc16, id: toRloc16, device_label: toRloc16 }, toRloc16);
      if (!toId) return;
      addEdge(edgeMap, edgeData, fromId, toId, { width: 1.5, linkCategories: [EDGE_CATEGORY_OTBR_ROUTE], edgeKeySuffix: 'merged-otbr-route' });
    });
    (Array.isArray(node.childTable) ? node.childTable : []).forEach((child, ci) => {
      const childRloc16 = buildChildRloc16(node.rloc16, child.childId);
      const childId = ensureNodeForLink(
        { rloc16: childRloc16, id: childRloc16 || `${fromId}-rest-child-${ci + 1}`, device_label: childRloc16 || `${fromId} child ${child.childId}` },
        childRloc16 || `${fromId}-rest-child-${ci + 1}`
      );
      if (!childId) return;
      addEdge(edgeMap, edgeData, fromId, childId, { dashes: false, isParentChild: true, linkCategories: [EDGE_CATEGORY_OTBR_CHILD], edgeKeySuffix: 'merged-otbr-child' });
      routerIdsWithChildren.add(fromId);
    });
    (Array.isArray(node.children) ? node.children : []).forEach((child, ci) => {
      const childNode = typeof child === 'string' ? { id: child } : (child || {});
      if (typeof child === 'string' || toText(childNode.id)) return; // skip eve-only string children
      const childId = ensureNodeForLink(childNode, `${fromId}-child-${ci + 1}`);
      if (!childId) return;
      addEdge(edgeMap, edgeData, fromId, childId, { dashes: false, isParentChild: true, linkCategories: [EDGE_CATEGORY_DEFAULT_CHILDREN], edgeKeySuffix: 'merged-default-child' });
      routerIdsWithChildren.add(fromId);
    });
  });

  const nodeData = buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, buildLabel);

  const rawByIdForDetails = new Map(rawNodeById);

  groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap);

  return { nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, sourceNames: ['merged-detailed'] };
}

// ── Adaptor 4: Router table (Nodes from ID/rloc16, edges from Next Hop) ───────

export function adaptRouterTable(rawFiles) {
  const rows = Array.isArray(rawFiles[0]) ? rawFiles[0] : [];
  const nodeMap = new Map();
  const rawByIdForDetails = new Map();
  const edgeMap = new Map();
  const edgeData = [];
  const routerIdsWithChildren = new Set();
  const routerNeighborByRloc16 = new Map();

  // Index rows by rloc16 for next-hop lookup
  const byRloc16 = new Map();
  rows.forEach((row) => {
    const rloc16 = getCanonicalRloc16(row);
    if (rloc16) byRloc16.set(rloc16, row);
  });

  rows.forEach((row) => {
    const nodeId = toText(row.rloc16) || getCanonicalExtaddr(row);
    if (!nodeId) return;
    const isBr = toText(nodeId).toLowerCase().endsWith('00');
    nodeMap.set(nodeId, {
      id: nodeId,
      device_label: toText(row.device_label),
      rloc16: toText(row.rloc16),
      extaddr: getCanonicalExtaddr(row),
      type: 'router',
      mode_device: 'FTD',
      br: isBr,
      shape: 'box',
      color: isBr ? NODE_COLORS.borderRouter : NODE_COLORS.router
    });
    rawByIdForDetails.set(nodeId, row);
  });

  // Build edges: row.rloc16 → rloc16 of Next Hop router ID
  rows.forEach((row) => {
    const fromId = toText(row.rloc16);
    if (!fromId) return;

    // "Next Hop" is a router ID integer → convert to rloc16
    const nextHopId = toFiniteNumber(row['Next Hop']);
    if (Number.isFinite(nextHopId)) {
      const toRloc16 = buildMainRouterRloc16(nextHopId);
      const toRow = byRloc16.get(toRloc16.toLowerCase());
      if (toRow && toRloc16 && toRloc16 !== fromId) {
        const lqOut = toFiniteNumber(row['LQ Out']);
        const edgeWidth = Number.isFinite(lqOut) ? (lqOut >= 3 ? 4 : lqOut >= 2 ? 2 : 1) : 1.5;
        addEdge(edgeMap, edgeData, fromId, toRloc16, {
          width: edgeWidth,
          linkCategories: [EDGE_CATEGORY_DEFAULT_1]
        });
      }
    }
  });

  const nodeData = buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, buildLabel);

  groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap);

  return { nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, sourceNames: ['router-table'] };
}

// ── Adaptor 5: Raw array generic fallback ─────────────────────────────────────

export function adaptRawArray(rawFiles) {
  const raw = rawFiles.find((f) => f !== null);
  const rows = Array.isArray(raw) ? raw : (raw && typeof raw === 'object' ? Object.values(raw) : []);
  const nodeMap = new Map();
  const rawByIdForDetails = new Map();
  const edgeMap = new Map();
  const edgeData = [];
  const routerIdsWithChildren = new Set();
  const routerNeighborByRloc16 = new Map();

  rows.forEach((row, index) => {
    if (!isPlainObject(row)) return;
    const nodeId = chooseNodeId(row, 'raw-node', index + 1);
    const rloc16Text = toText(row.rloc16).toLowerCase();
    const isBr = row.br === true || (rloc16Text.endsWith('00') && row.br === true);
    const isChildLike = toText(row.type).toLowerCase().includes('child');
    nodeMap.set(nodeId, {
      id: nodeId,
      device_label: toText(row.device_label),
      name: toText(row.name),
      rloc16: toText(row.rloc16),
      extaddr: getCanonicalExtaddr(row),
      type: toText(row.type),
      mode_device: toText(row.mode?.device) || (row.type === 'router' ? 'FTD' : (isChildLike ? 'MTD' : '')),
      ifindiscards_pct: row.mac_counters?.ifindiscards_pct,
      iftotalerrors_pct: row.mac_counters?.iftotalerrors_pct,
      partitionidchanges: row.mle_counters?.partitionidchanges,
      parentchanges: row.mle_counters?.parentchanges,
      br: row.br === true,
      shape: isChildLike ? 'ellipse' : 'box',
      color: isBr ? NODE_COLORS.borderRouter
        : (isChildLike ? NODE_COLORS.child : NODE_COLORS.router)
    });
    rawByIdForDetails.set(nodeId, row);
    if (Array.isArray(row.router_neighbor_table) && rloc16Text) {
      routerNeighborByRloc16.set(rloc16Text, row);
    }
  });

  rows.forEach((row, index) => {
    if (!isPlainObject(row)) return;
    const fromId = chooseNodeId(row, 'raw-node', index + 1);
    // children[] → dashed edges
    (Array.isArray(row.children) ? row.children : []).forEach((child) => {
      const childId = typeof child === 'string' ? child
        : (toText(child.rloc16) || toText(child.id));
      if (!childId || !nodeMap.has(childId)) return;
      addEdge(edgeMap, edgeData, fromId, childId, { dashes: false, isParentChild: true, linkCategories: [EDGE_CATEGORY_DEFAULT_CHILDREN] });
      routerIdsWithChildren.add(fromId);
    });
    // routes[] → solid edges
    (Array.isArray(row.routes) ? row.routes : []).forEach((route) => {
      const toId = toText(route.to);
      if (!toId || !nodeMap.has(toId)) return;
      addEdge(edgeMap, edgeData, fromId, toId, { linkCategories: [EDGE_CATEGORY_EVE_ROUTE] });
    });
  });

  const nodeData = buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, buildLabel);

  groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap);

  return { nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, sourceNames: ['raw-array'] };
}

// ── Adaptor 6: OTBR REST API (devices + diagnostics) ─────────────────────────
//
// Both files use { "data": [ { "id", "type", "attributes": {...} } ] } shape.
// Devices provide: extAddress, mlEidIid, omrIpv6Address, hostName, role, mode.
// Diagnostics provide: extAddress, rloc16, route.routeData[], childTable[].
// Primary node ID = extAddress (lowercase). Merged by extAddress identity.

export function adaptOtbrRestApi(rawFiles) {
  const devicesData = (rawFiles[0] && Array.isArray(rawFiles[0].data)) ? rawFiles[0].data : [];
  const diagData = (rawFiles[1] && Array.isArray(rawFiles[1].data)) ? rawFiles[1].data : [];

  // Flatten each item: merge top-level fields + attributes sub-object
  function flattenRestApiItem(item) {
    if (!isPlainObject(item)) return item;
    const attrs = isPlainObject(item.attributes) ? item.attributes : {};
    return { ...item, ...attrs };
  }

  const devices = devicesData.map(flattenRestApiItem);
  const diagnostics = diagData.map(flattenRestApiItem);

  const nodeMap = new Map();
  const rawByIdForDetails = new Map();
  const rloc16ToNodeId = new Map();
  const edgeMap = new Map();
  const edgeData = [];
  const routerIdsWithChildren = new Set();
  const routerNeighborByRloc16 = new Map();

  function upsertOtbrRestApiNode(nodeId, rawNode, style) {
    const existing = nodeMap.get(nodeId);
    const roleText = toText(rawNode.role).toLowerCase();
    const isChildLike = roleText === 'child' || roleText.includes('sleepy');
    const modeDevice = rawNode.mode?.deviceTypeFTD === true ? 'FTD'
      : (rawNode.mode?.deviceTypeFTD === false ? 'MTD' : (existing ? existing.mode_device : ''));
    const rloc16Val = toText(rawNode.rloc16) || (existing ? existing.rloc16 : '');
    const extaddrVal = toText(rawNode.extAddress || rawNode.extaddr).toLowerCase() || (existing ? existing.extaddr : '');
    const merged = {
      id: nodeId,
      device_label: toText(rawNode.hostName) || toText(rawNode.device_label) || (existing ? existing.device_label : ''),
      name: toText(rawNode.hostName) || toText(rawNode.device_label) || (existing ? existing.name : ''),
      rloc16: rloc16Val,
      extaddr: extaddrVal,
      type: roleText || toText(rawNode.type) || (existing ? existing.type : ''),
      mode_device: modeDevice || (existing ? existing.mode_device : ''),
      omrIpv6Address: toText(rawNode.omrIpv6Address) || (existing ? existing.omrIpv6Address : ''),
      br: rawNode.br === true || (existing ? existing.br === true : false),
      from_otbr_restapi: true,
      shape: style.shape || (existing ? existing.shape : (isChildLike ? 'ellipse' : 'box')),
      color: style.color || (existing ? existing.color : NODE_COLORS.router)
    };
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
      shape: isChildLike ? 'ellipse' : 'box',
      color: isChildLike ? NODE_COLORS.child : NODE_COLORS.router
    });
    rawByIdForDetails.set(nodeId, node);
  });

  // Pass 2: augment from diagnostics — adds rloc16, route, childTable
  diagnostics.forEach((node) => {
    const nodeId = toText(node.extAddress || node.extaddr).toLowerCase() || toText(node.id);
    if (!nodeId) return;
    upsertOtbrRestApiNode(nodeId, node, {
      shape: 'box',
      color: NODE_COLORS.router
    });
    const rloc16Val = toText(node.rloc16).toLowerCase();
    if (rloc16Val) rloc16ToNodeId.set(rloc16Val, nodeId);
    const existing = rawByIdForDetails.get(nodeId) || {};
    rawByIdForDetails.set(nodeId, mergeForDisplay(existing, node));
  });

  // Pass 3: edges from diagnostics route.routeData (router routes) + childTable
  diagnostics.forEach((node) => {
    const fromId = toText(node.extAddress || node.extaddr).toLowerCase() || toText(node.id);
    if (!fromId || !nodeMap.has(fromId)) return;
    const fromNode = nodeMap.get(fromId);

    (Array.isArray(node.route?.routeData) ? node.route.routeData : []).forEach((route) => {
      const toRloc16 = buildMainRouterRloc16(route.routeId);
      if (!toRloc16) return;
      let toId = rloc16ToNodeId.get(toRloc16.toLowerCase()) || toRloc16;
      if (!nodeMap.has(toId)) {
        upsertOtbrRestApiNode(toId, { rloc16: toRloc16, id: toId },
          { shape: 'box', color: NODE_COLORS.router });
      }
      const lqi = Math.max(toFiniteNumber(route.linkQualityOut) || 0, toFiniteNumber(route.linkQualityIn) || 0);
      const edgeWidth = lqi >= 3 ? 3 : (lqi >= 2 ? 2 : 1.5);
      addEdge(edgeMap, edgeData, fromId, toId, { width: edgeWidth, linkCategories: [EDGE_CATEGORY_OTBR_ROUTE] });
    });

    (Array.isArray(node.childTable) ? node.childTable : []).forEach((child, ci) => {
      const childRloc16 = buildChildRloc16(toText(fromNode.rloc16), child.childId);
      const childId = (childRloc16 && rloc16ToNodeId.get(childRloc16.toLowerCase()))
        || childRloc16
        || `${fromId}-child-${ci + 1}`;
      if (!nodeMap.has(childId)) {
        upsertOtbrRestApiNode(childId, { rloc16: childRloc16, id: childId },
          { shape: 'ellipse', color: NODE_COLORS.child });
      }
      addEdge(edgeMap, edgeData, fromId, childId, { dashes: false, isParentChild: true, linkCategories: [EDGE_CATEGORY_OTBR_CHILD] });
      routerIdsWithChildren.add(fromId);
    });
  });

  const nodeData = buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, buildLabel);
  groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap);

  const sourceNames = [];
  if (devices.length > 0) sourceNames.push('otbr_restapi_devices');
  if (diagnostics.length > 0) sourceNames.push('otbr_restapi_diagnostics');

  return { nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, sourceNames };
}

// ── Dispatch: pick adaptor based on topologyMode ──────────────────────────────

export function runAdaptor(dataset) {
  const { entry, rawFiles } = dataset;
  switch (entry.topologyMode) {
    case 'meshdiag-networkdiag': return adaptMeshdiagNetworkdiag(rawFiles);
    case 'merged-detailed': return adaptMergedDetailed(rawFiles);
    case 'eve_enhanced': return adaptEve(rawFiles);
    case 'eve_native': return adaptEveNative(rawFiles);
    case 'router-table': return adaptRouterTable(rawFiles);
    case 'otbr_restapi': return adaptOtbrRestApi(rawFiles);
    case 'raw-array':
    default: return adaptRawArray(rawFiles);
  }
}
