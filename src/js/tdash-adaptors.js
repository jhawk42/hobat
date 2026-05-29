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
  getCanonicalOmrIpv6Address,
  mergeForDisplay
} from './tdash-utils.js';
import {
  chooseNodeId, buildLabel,
  buildMainRouterRloc16, buildChildRloc16,
  addEdge, groupIsolatedUnknownNodes, buildVisNodeData,
  lqStyleFromField, lqStyleFromAvgLqi, lqStyleFromLinkMargin
} from './tdash-topology-utils.js';

// ── File name constants ───────────────────────────────────────────────────────

const FILE_MESHDIAG              = 'td-otbr-cli-meshdiag-topology.json';
const FILE_NETWORKDIAG_FETCH_ALL      = 'td-otbr-cli-networkdiag-fetch-all.json';
const FILE_NETWORKDIAG_MULTICAST = 'td-otbr-cli-networkdiag-multicast-network.json';
const FILE_ROUTER_NEIGHBORTABLES = 'td-otbr-cli-meshdiag-router-neighbortables.json';
const FILE_ROUTER_CHILDTABLES    = 'td-otbr-cli-meshdiag-router-childtables.json';
const FILE_RESTAPI_DEVICES       = 'td-otbr-restapi-devices.json';
const FILE_RESTAPI_DIAGNOSTICS   = 'td-otbr-restapi-diagnostics.json';
const FILE_RESTAPI_DEVICES_LIST      = 'td-otbr-restapi-devices-list.json';
const FILE_RESTAPI_DEVICES_FETCH     = 'td-otbr-restapi-devices-fetch.json';
const FILE_RESTAPI_DIAGNOSTICS_LIST      = 'td-otbr-restapi-diagnostics-list.json';
const FILE_RESTAPI_DIAGNOSTICS_FETCH     = 'td-otbr-restapi-diagnostics-fetch.json';
const FILE_RESTAPI_DIAGNOSTICS_FETCH_ALL = 'td-otbr-restapi-diagnostics-fetch-all.json';
const FILE_ROUTER_CHILDIP6               = 'td-otbr-cli-meshdiag-router-childip6.json';
const FILE_NETWORKDIAG_MULTICAST_NEIGHBORS = 'td-otbr-cli-networkdiag-multicast-neighbors.json';
const FILE_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL = 'td-otbr-restapi-mesh-diagnostics-fetch-all.json';

// Files consumed as named primary slots in adaptMeshdiagNetworkdiag;
// anything not in this set is treated as supplementary (e.g. mdns, eve).
const MESHDIAG_PRIMARY_FILES = new Set([
  FILE_MESHDIAG, FILE_NETWORKDIAG_FETCH_ALL, FILE_NETWORKDIAG_MULTICAST,
  FILE_ROUTER_NEIGHBORTABLES, FILE_ROUTER_CHILDTABLES,
  FILE_RESTAPI_DIAGNOSTICS,
]);

// ── Shared helpers ────────────────────────────────────────────────────────────

/** Coerce a value to an array; returns [] if value is not already an array. */
function asArray(value) { return Array.isArray(value) ? value : []; }

/**
 * Build a Map<filename, loadedData> from the registry entry's files list and
 * the parallel array of loaded file contents.
 */
function buildFileMap(fileNames, rawFiles) {
  const map = new Map();
  fileNames.forEach((name, i) => { if (name) map.set(name, rawFiles[i]); });
  return map;
}

// ── Adaptor 1: meshdiag + networkdiag + routerNeighbors + restApi ─────────────

export function adaptMeshdiagNetworkdiag(fileMap) {
  const meshdiag = asArray(fileMap.get(FILE_MESHDIAG));
  const networkDiag = asArray(
    fileMap.get(FILE_NETWORKDIAG_FETCH_ALL) ?? fileMap.get(FILE_NETWORKDIAG_MULTICAST)
  );
  const routerNeighborTables = asArray(fileMap.get(FILE_ROUTER_NEIGHBORTABLES));
  const routerChildTables = asArray(fileMap.get(FILE_ROUTER_CHILDTABLES));
  const restApiRaw = fileMap.get(FILE_RESTAPI_DIAGNOSTICS);
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
  const routerChildByRloc16 = new Map();

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
    // Phase 1a: new fields
    const mergedTotalLink3 = Number.isFinite(rawNode.total_link_3) ? rawNode.total_link_3
      : (existing && Number.isFinite(existing.total_link_3) ? existing.total_link_3 : undefined);
    const mergedTotalLink2 = Number.isFinite(rawNode.total_link_2) ? rawNode.total_link_2
      : (existing && Number.isFinite(existing.total_link_2) ? existing.total_link_2 : undefined);
    const mergedTotalLink1 = Number.isFinite(rawNode.total_link_1) ? rawNode.total_link_1
      : (existing && Number.isFinite(existing.total_link_1) ? existing.total_link_1 : undefined);
    const mergedTotalLinks = Number.isFinite(rawNode.total_links) ? rawNode.total_links
      : (existing ? existing.total_links : 0);
    const lq3Ratio = (Number.isFinite(mergedTotalLink3) && mergedTotalLinks > 0)
      ? mergedTotalLink3 / mergedTotalLinks : undefined;
    const lq1Ratio = (Number.isFinite(mergedTotalLink1) && mergedTotalLinks > 0)
      ? mergedTotalLink1 / mergedTotalLinks : undefined;
    let hasChildLqMedium = false;
    let hasChildLqPoor = false;
    rawChildren.forEach((child) => {
      const lqRaw = child.lq !== undefined ? child.lq : child.link_quality;
      const lqNum = Number.parseInt(lqRaw, 10);
      if (Number.isFinite(lqNum)) {
        if (lqNum <= 2) hasChildLqMedium = true;
        if (lqNum === 1) hasChildLqPoor = true;
      }
    });
    const rawTotalErrorsRatio = rawNode.mac_counters && Number.isFinite(rawNode.mac_counters.iftotalerrors_totalpkts_ratio)
      ? rawNode.mac_counters.iftotalerrors_totalpkts_ratio : undefined;
    const rawTotalDiscardsRatio = rawNode.mac_counters && Number.isFinite(rawNode.mac_counters.iftotaldiscards_totalpkts_ratio)
      ? rawNode.mac_counters.iftotaldiscards_totalpkts_ratio : undefined;
    const rawBetterPartition = rawNode.mle_counters && Number.isFinite(rawNode.mle_counters.betterpartitionattachattempts)
      ? rawNode.mle_counters.betterpartitionattachattempts : undefined;
    const rawTotalParentPartition = rawNode.mle_counters && Number.isFinite(rawNode.mle_counters.totalparentpartitionchanges)
      ? rawNode.mle_counters.totalparentpartitionchanges : undefined;
    const rawRouterPct = rawNode.time_statistics && Number.isFinite(rawNode.time_statistics.router_pct)
      ? rawNode.time_statistics.router_pct : undefined;
    const rawDetachedDisabledPct = rawNode.time_statistics && Number.isFinite(rawNode.time_statistics.detached_disabled_pct)
      ? rawNode.time_statistics.detached_disabled_pct : undefined;
    const merged = {
      id: nodeId,
      device_label: toText(rawNode.device_label) || (existing ? existing.device_label : ''),
      rloc16: toText(rawNode.rloc16) || (existing ? existing.rloc16 : ''),
      source_id: toText(rawNode.id) || (existing ? existing.source_id : ''),
      extaddr: toText(rawNode.extaddr) || (existing ? existing.extaddr : ''),
      type: toText(rawNode.type) || (existing ? existing.type : ''),
      thread_version: toText(rawNode.thread_version) || (existing ? existing.thread_version : ''),
      thread_stack_version: toText(rawNode.thread_stack_version) || (existing ? existing.thread_stack_version : ''),
      ipv6_addrs: mergedIpv6,
      total_children: Number.isFinite(rawNode.total_children)
        ? rawNode.total_children : (rawChildren.length || (existing ? existing.total_children : 0)),
      total_links: mergedTotalLinks,
      total_link_3: mergedTotalLink3,
      total_link_2: mergedTotalLink2,
      total_link_1: mergedTotalLink1,
      lq3_ratio: lq3Ratio,
      lq1_ratio: lq1Ratio,
      has_child_lq_medium: hasChildLqMedium || (existing ? existing.has_child_lq_medium === true : false),
      has_child_lq_poor: hasChildLqPoor || (existing ? existing.has_child_lq_poor === true : false),
      ifindiscards_pct: Number.isFinite(rawPacketErrorDiscardPct) ? rawPacketErrorDiscardPct
        : (existing && Number.isFinite(existing.ifindiscards_pct) ? existing.ifindiscards_pct : undefined),
      ifinerrors_pct: Number.isFinite(rawInerrorsPct) ? rawInerrorsPct
        : (existing && Number.isFinite(existing.ifinerrors_pct) ? existing.ifinerrors_pct : undefined),
      ifouterrors_pct: Number.isFinite(rawOuterrorsPct) ? rawOuterrorsPct
        : (existing && Number.isFinite(existing.ifouterrors_pct) ? existing.ifouterrors_pct : undefined),
      iftotalerrors_totalpkts_ratio: rawTotalErrorsRatio !== undefined ? rawTotalErrorsRatio
        : (existing && Number.isFinite(existing.iftotalerrors_totalpkts_ratio) ? existing.iftotalerrors_totalpkts_ratio : undefined),
      iftotaldiscards_totalpkts_ratio: rawTotalDiscardsRatio !== undefined ? rawTotalDiscardsRatio
        : (existing && Number.isFinite(existing.iftotaldiscards_totalpkts_ratio) ? existing.iftotaldiscards_totalpkts_ratio : undefined),
      mode_device: rawModeDevice || (existing ? existing.mode_device : ''),
      partitionidchanges: Number.isFinite(rawPartitionIdChanges) ? rawPartitionIdChanges
        : (existing && Number.isFinite(existing.partitionidchanges) ? existing.partitionidchanges : undefined),
      parentchanges: Number.isFinite(rawParentChanges) ? rawParentChanges
        : (existing && Number.isFinite(existing.parentchanges) ? existing.parentchanges : undefined),
      betterpartitionattachattempts: rawBetterPartition !== undefined ? rawBetterPartition
        : (existing && Number.isFinite(existing.betterpartitionattachattempts) ? existing.betterpartitionattachattempts : undefined),
      totalparentpartitionchanges: rawTotalParentPartition !== undefined ? rawTotalParentPartition
        : (existing && Number.isFinite(existing.totalparentpartitionchanges) ? existing.totalparentpartitionchanges : undefined),
      router_pct: rawRouterPct !== undefined ? rawRouterPct
        : (existing && Number.isFinite(existing.router_pct) ? existing.router_pct : undefined),
      detached_disabled_pct: rawDetachedDisabledPct !== undefined ? rawDetachedDisabledPct
        : (existing && Number.isFinite(existing.detached_disabled_pct) ? existing.detached_disabled_pct : undefined),
      br: rawNode.br === true || (existing ? existing.br === true : false),
      from_meshdiag: (style.source === 'meshdiag') || (existing ? existing.from_meshdiag === true : false),
      from_networkdiagnostic: (style.source === 'networkdiagnostic') || (existing ? existing.from_networkdiagnostic === true : false),
      shape: (existing && existing.shape === 'ellipse') ? 'ellipse' : (style.shape || (existing ? existing.shape : 'box')),
      color: style.color || (existing ? existing.color : NODE_COLORS.router)
    };
    merged.is_ftd_router = merged.mode_device === 'FTD' && merged.rloc16.toLowerCase().endsWith('00');
    // Apply role-based color overrides
    if (merged.br) {
      merged.color = NODE_COLORS.borderRouter;
    } else if (merged.shape === 'ellipse') {
      // Child nodes (ellipse shape) should always use child color, not router default
      merged.color = NODE_COLORS.child;
    }
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

  routerChildTables.forEach((row) => {
    const rloc16 = toText(row.parent_rloc16 || row.rloc16).toLowerCase();
    if (rloc16) routerChildByRloc16.set(rloc16, row);
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

    // Process route_data routes from networkdiag (multicast variant).
    // route_data.route_data[] contains routing table entries with LQI metrics.
    // Each route has a direct rloc16 target (no ID conversion needed).
    (Array.isArray(node.route_data?.route_data) ? node.route_data.route_data : []).forEach((route) => {
      const toRloc16 = toText(route.rloc16);
      if (!toRloc16) return;

      // Ensure target node exists
      const toId = ensureNode(
        toRloc16,
        { rloc16: toRloc16, id: toRloc16, device_label: toRloc16 },
        { source: 'networkdiagnostic', shape: 'box', color: NODE_COLORS.router }
      );

      // Compute LQI-based edge style
      const lqIn = toFiniteNumber(route.link_quality_in) || 0;
      const lqOut = toFiniteNumber(route.link_quality_out) || 0;
      const avgLqi = Math.max(lqIn, lqOut); // Take max for conservative estimate
      const lqStyle = lqStyleFromAvgLqi(avgLqi, 3);

      // Add edge with LQI styling
      addEdge(edgeMap, edgeData, fromId, toId, {
        ...lqStyle,
        linkCategories: [EDGE_CATEGORY_OTBR_ROUTE]
      });
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

  const nodeData = buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, buildLabel, routerChildByRloc16);

  const rawByIdForDetails = new Map();
  nodeMap.forEach((_, id) => {
    const m = meshdiagById.get(id) || {};
    const n = networkDiagById.get(id) || {};
    const r = restApiById.get(id) || {};
    rawByIdForDetails.set(id, mergeForDisplay(mergeForDisplay(m, n), r));
  });

  // Merge supplementary files (non-primary fileMap entries, e.g. mdns) into rawByIdForDetails.
  // MTD/FTD mdns records match by omr_ipv6_addr; BR mdns records match by extaddr.
  const omrToNodeId = new Map();
  const extaddrToNodeId = new Map();
  rawByIdForDetails.forEach((raw, id) => {
    const omr = getCanonicalOmrIpv6Address(raw);
    if (omr) omrToNodeId.set(omr, id);
    const ea = getCanonicalExtaddr(raw);
    if (ea) extaddrToNodeId.set(ea, id);
  });
  nodeMap.forEach((node, id) => {
    const omr = getCanonicalOmrIpv6Address(node);
    if (omr && !omrToNodeId.has(omr)) omrToNodeId.set(omr, id);
    const ea = getCanonicalExtaddr(node);
    if (ea && !extaddrToNodeId.has(ea)) extaddrToNodeId.set(ea, id);
  });
  for (const [supplementaryFileName, extraFile] of fileMap) {
    if (MESHDIAG_PRIMARY_FILES.has(supplementaryFileName)) continue;
    if (!Array.isArray(extraFile)) continue;
    extraFile.forEach((record) => {
      if (!isPlainObject(record)) return;
      const omr = getCanonicalOmrIpv6Address(record);
      const ea = getCanonicalExtaddr(record);
      const nodeId = (omr && omrToNodeId.get(omr)) || (ea && extaddrToNodeId.get(ea));
      if (!nodeId) return;
      const existing = rawByIdForDetails.get(nodeId) || {};
      rawByIdForDetails.set(nodeId, mergeForDisplay(existing, record));
    });
  }

  const sourceNames = [];
  if (meshdiag.length > 0) sourceNames.push('meshdiag');
  if (networkDiag.length > 0) sourceNames.push('networkdiagnostic');
  if (routerNeighborTables.length > 0) sourceNames.push('routerneighbortables');
  if (routerChildTables.length > 0) sourceNames.push('routerchildtables');
  if (restApiDiagnostics.length > 0) sourceNames.push('restapi');

  groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap);

  return { nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, routerChildByRloc16, sourceNames };
}

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
      device_label: toText(rawNode.device_label) || (existing ? existing.device_label : ''),
      rloc16: toText(rawNode.rloc16) || (existing ? existing.rloc16 : ''),
      source_id: toText(rawNode.id) || (existing ? existing.source_id : ''),
      extaddr: toText(rawNode.extaddr) || (existing ? existing.extaddr : ''),
      type: toText(rawNode.type) || (existing ? existing.type : ''),
      thread_version: toText(rawNode.thread_version) || (existing ? existing.thread_version : ''),
      thread_stack_version: toText(rawNode.thread_stack_version) || (existing ? existing.thread_stack_version : ''),
      total_children: Number.isFinite(rawNode.total_children) ? rawNode.total_children : (existing ? existing.total_children : 0),
      total_links: Number.isFinite(rawNode.total_links) ? rawNode.total_links : (existing ? existing.total_links : 0),
      ifindiscards_pct: Number.isFinite(rawNode.mac_counters?.ifindiscards_pct)
        ? rawNode.mac_counters.ifindiscards_pct : (existing?.ifindiscards_pct),
      iftotalerrors_pct: Number.isFinite(rawNode.mac_counters?.iftotalerrors_pct)
        ? rawNode.mac_counters.iftotalerrors_pct : (existing?.iftotalerrors_pct),
      iftotalerrors_totalpkts_ratio: Number.isFinite(rawNode.mac_counters?.iftotalerrors_totalpkts_ratio)
        ? rawNode.mac_counters.iftotalerrors_totalpkts_ratio : (existing?.iftotalerrors_totalpkts_ratio),
      iftotaldiscards_totalpkts_ratio: Number.isFinite(rawNode.mac_counters?.iftotaldiscards_totalpkts_ratio)
        ? rawNode.mac_counters.iftotaldiscards_totalpkts_ratio : (existing?.iftotaldiscards_totalpkts_ratio),
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
    // Apply role-based color overrides
    if (merged.br) {
      merged.color = NODE_COLORS.borderRouter;
    } else if (merged.shape === 'ellipse') {
      // Child nodes (ellipse shape) should always use child color
      if (['0x4c00', '0xa800'].includes(nodeId)) {
        console.log(`[upsertEveNativeNode] Setting ellipse color for ${nodeId}: from`, existing?.color, 'to', NODE_COLORS.child);
      }
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
    // Apply role-based color overrides
    if (merged.br) {
      merged.color = NODE_COLORS.borderRouter;
    } else if (merged.shape === 'ellipse') {
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

export function adaptMergedDetailed(fileMap) {
  const rows = asArray(fileMap.values().next().value);
  const nodeMap = new Map();
  const rawNodeById = new Map();
  const edgeMap = new Map();
  const edgeData = [];
  const routerIdsWithChildren = new Set();
  const routerNeighborByRloc16 = new Map();
  const routerChildByRloc16 = new Map();

  function isMergedRowEveOnly(node) {
    const sources = Array.isArray(node?._sources) ? node._sources : [];
    if (!sources.includes('td-eve-topology.json')) return false;
    return !sources.some((s) => s === 'td-otbr-cli-router-table.json'
      || s === 'td-otbr-cli-meshdiag-topology.json'
      || s === 'td-otbr-cli-networkdiag-fetch-all.json'
      || s === 'td-otbr-cli-meshdiag-router-neighbortables.json'
      || s === 'td-otbr-restapi-devices.json'
      || s === 'td-otbr-restapi-diagnostics.json');
  }

  function chooseMergedId(node, index) {
    return toText(node.rloc16) || toText(node.id) || toText(node.extaddr) || `merged-node-${index + 1}`;
  }

  function upsertMergedNode(nodeId, rawNode, style) {
    const existing = nodeMap.get(nodeId);
    const rawMergedChildren = Array.isArray(rawNode.children) ? rawNode.children : [];
    const mergedTotalLink3 = Number.isFinite(rawNode.total_link_3) ? rawNode.total_link_3
      : (existing && Number.isFinite(existing.total_link_3) ? existing.total_link_3 : undefined);
    const mergedTotalLink2 = Number.isFinite(rawNode.total_link_2) ? rawNode.total_link_2
      : (existing && Number.isFinite(existing.total_link_2) ? existing.total_link_2 : undefined);
    const mergedTotalLink1 = Number.isFinite(rawNode.total_link_1) ? rawNode.total_link_1
      : (existing && Number.isFinite(existing.total_link_1) ? existing.total_link_1 : undefined);
    const mergedTotalLinks = Number.isFinite(rawNode.total_links) ? rawNode.total_links
      : (existing ? existing.total_links : 0);
    const lq3Ratio = (Number.isFinite(mergedTotalLink3) && mergedTotalLinks > 0)
      ? mergedTotalLink3 / mergedTotalLinks : undefined;
    const lq1Ratio = (Number.isFinite(mergedTotalLink1) && mergedTotalLinks > 0)
      ? mergedTotalLink1 / mergedTotalLinks : undefined;
    let hasChildLqMedium = false;
    let hasChildLqPoor = false;
    rawMergedChildren.forEach((child) => {
      const lqRaw = child.lq !== undefined ? child.lq : child.link_quality;
      const lqNum = Number.parseInt(lqRaw, 10);
      if (Number.isFinite(lqNum)) {
        if (lqNum <= 2) hasChildLqMedium = true;
        if (lqNum === 1) hasChildLqPoor = true;
      }
    });
    const merged = {
      id: nodeId,
      name: toText(rawNode.name) || (existing ? existing.name : ''),
      device_label: toText(rawNode.device_label) || (existing ? existing.device_label : ''),
      rloc16: toText(rawNode.rloc16) || (existing ? existing.rloc16 : ''),
      source_id: toText(rawNode.id) || (existing ? existing.source_id : ''),
      extaddr: toText(rawNode.extaddr) || (existing ? existing.extaddr : ''),
      type: toText(rawNode.type) || (existing ? existing.type : ''),
      thread_version: toText(rawNode.thread_version) || (existing ? existing.thread_version : ''),
      thread_stack_version: toText(rawNode.thread_stack_version) || (existing ? existing.thread_stack_version : ''),
      total_children: Number.isFinite(rawNode.total_children) ? rawNode.total_children : (existing ? existing.total_children : 0),
      total_links: mergedTotalLinks,
      total_link_3: mergedTotalLink3,
      total_link_2: mergedTotalLink2,
      total_link_1: mergedTotalLink1,
      lq3_ratio: lq3Ratio,
      lq1_ratio: lq1Ratio,
      has_child_lq_medium: hasChildLqMedium || (existing ? existing.has_child_lq_medium === true : false),
      has_child_lq_poor: hasChildLqPoor || (existing ? existing.has_child_lq_poor === true : false),
      ifindiscards_pct: Number.isFinite(rawNode.mac_counters?.ifindiscards_pct)
        ? rawNode.mac_counters.ifindiscards_pct : (existing?.ifindiscards_pct),
      iftotalerrors_pct: Number.isFinite(rawNode.mac_counters?.iftotalerrors_pct)
        ? rawNode.mac_counters.iftotalerrors_pct : (existing?.iftotalerrors_pct),
      iftotalerrors_totalpkts_ratio: Number.isFinite(rawNode.mac_counters?.iftotalerrors_totalpkts_ratio)
        ? rawNode.mac_counters.iftotalerrors_totalpkts_ratio : (existing?.iftotalerrors_totalpkts_ratio),
      iftotaldiscards_totalpkts_ratio: Number.isFinite(rawNode.mac_counters?.iftotaldiscards_totalpkts_ratio)
        ? rawNode.mac_counters.iftotaldiscards_totalpkts_ratio : (existing?.iftotaldiscards_totalpkts_ratio),
      mode_device: toText(rawNode['mode.device']) || toText(rawNode.mode?.device) || (existing ? existing.mode_device : ''),
      partitionidchanges: Number.isFinite(rawNode.mle_counters?.partitionidchanges)
        ? rawNode.mle_counters.partitionidchanges : (existing?.partitionidchanges),
      parentchanges: Number.isFinite(rawNode.mle_counters?.parentchanges)
        ? rawNode.mle_counters.parentchanges : (existing?.parentchanges),
      betterpartitionattachattempts: Number.isFinite(rawNode.mle_counters?.betterpartitionattachattempts)
        ? rawNode.mle_counters.betterpartitionattachattempts : (existing?.betterpartitionattachattempts),
      totalparentpartitionchanges: Number.isFinite(rawNode.mle_counters?.totalparentpartitionchanges)
        ? rawNode.mle_counters.totalparentpartitionchanges : (existing?.totalparentpartitionchanges),
      router_pct: Number.isFinite(rawNode.time_statistics?.router_pct)
        ? rawNode.time_statistics.router_pct : (existing?.router_pct),
      detached_disabled_pct: Number.isFinite(rawNode.time_statistics?.detached_disabled_pct)
        ? rawNode.time_statistics.detached_disabled_pct : (existing?.detached_disabled_pct),
      br: rawNode.br === true || (existing ? existing.br === true : false),
      from_merged_detailed: true,
      shape: style.shape || (existing ? existing.shape : 'box'),
      color: style.color || (existing ? existing.color : NODE_COLORS.eve)
    };
    merged.is_ftd_router = merged.mode_device === 'FTD' && merged.rloc16.toLowerCase().endsWith('00');
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
    // populate routerChildByRloc16 for filter support
    const rloc16ForChild = toText(node.parent_rloc16 || node.rloc16).toLowerCase();
    if (Array.isArray(node.router_child_table) && rloc16ForChild) {
      routerChildByRloc16.set(rloc16ForChild, node);
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
      if (typeof child === 'string') return; // skip eve-only string children
      if (!toText(childNode.rloc16) && !toText(childNode.extaddr)) return; // skip object refs without Thread identity
      const childId = ensureNodeForLink(childNode, `${fromId}-child-${ci + 1}`);
      if (!childId) return;
      addEdge(edgeMap, edgeData, fromId, childId, { dashes: false, isParentChild: true, linkCategories: [EDGE_CATEGORY_DEFAULT_CHILDREN], edgeKeySuffix: 'merged-default-child' });
      routerIdsWithChildren.add(fromId);
    });
    (Array.isArray(node.router_child_table) ? node.router_child_table : []).forEach((child, ci) => {
      const childId = toText(child.rloc16) || `${fromId}-rct-child-${ci + 1}`;
      const childType = toText(child.type).toLowerCase();
      const isChildLikeNode = childType === 'mtd' || child.rx_on === false;
      const isRouterLikeNode = childType === 'ftd' && childId.toLowerCase().endsWith('00');
      upsertMergedNode(childId, {
        rloc16: toText(child.rloc16),
        extaddr: toText(child.extaddr),
        device_label: toText(child.device_label),
        type: childType,
        thread_version: toText(child.thread_version)
      }, {
        source: 'merged-detailed',
        shape: isChildLikeNode && !isRouterLikeNode ? 'ellipse' : 'box',
        color: isChildLikeNode && !isRouterLikeNode ? NODE_COLORS.child : NODE_COLORS.eve
      });
      if (!rawNodeById.has(childId)) rawNodeById.set(childId, child);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false, isParentChild: true,
        linkCategories: [EDGE_CATEGORY_DEFAULT_CHILDREN],
        edgeKeySuffix: 'merged-rct-child'
      });
      routerIdsWithChildren.add(fromId);
    });
  });

  const nodeData = buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, buildLabel, routerChildByRloc16);

  const rawByIdForDetails = new Map(rawNodeById);

  groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap);

  return { nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, routerChildByRloc16, sourceNames: ['merged-detailed'] };
}

// ── Adaptor 4: Router table (Nodes from ID/rloc16, edges from Next Hop) ───────

export function adaptRouterTable(fileMap) {
  const rows = asArray(fileMap.values().next().value);
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

export function adaptRawArray(fileMap) {
  const raw = [...fileMap.values()].find((f) => f !== null);
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
      iftotalerrors_totalpkts_ratio: row.mac_counters?.iftotalerrors_totalpkts_ratio,
      iftotaldiscards_totalpkts_ratio: row.mac_counters?.iftotaldiscards_totalpkts_ratio,
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
// Devices provide: extAddress, mlEidIid, omr_ipv6_addr, hostName, role, mode.
// Diagnostics provide: extAddress, rloc16, route.routeData[], childTable[].
// Primary node ID = extAddress (lowercase). Merged by extAddress identity.

export function adaptOtbrRestApi(fileMap) {
  const devicesRaw = fileMap.get(FILE_RESTAPI_DEVICES) ?? fileMap.get(FILE_RESTAPI_DEVICES_LIST) ?? fileMap.get(FILE_RESTAPI_DEVICES_FETCH);
  const diagRaw = fileMap.get(FILE_RESTAPI_DIAGNOSTICS) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_LIST) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_FETCH) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_FETCH_ALL) ?? fileMap.get(FILE_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL);
  // Accept JSON:API envelope ({data:[...]}), pre-flattened array, or a single diagnostic object
  function extractItems(raw) {
    if (!raw) return [];
    if (Array.isArray(raw)) return raw;
    if (Array.isArray(raw.data)) return raw.data;
    if (isPlainObject(raw) && raw.extAddress) return [raw]; // single diagnostic record
    return [];
  }
  const devicesData = extractItems(devicesRaw);
  const diagData = extractItems(diagRaw);

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
      omr_ipv6_addr: toText(rawNode.omr_ipv6_addr) || (existing ? existing.omr_ipv6_addr : ''),
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
        }, { shape: 'box', color: NODE_COLORS.router });
        if (neighborRloc16) rloc16ToNodeId.set(neighborRloc16, toId);
      }

      // Style link based on linkMargin (dB)
      const lqStyle = lqStyleFromLinkMargin(neighbor.linkMargin);
      addEdge(edgeMap, edgeData, fromId, toId, {
        ...lqStyle,
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
          neighborRow.router_neighbor_table.push(neighbor);
        }
      }
    });
  });

  // Pass 4: group isolated unknown nodes
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
  const fileMap = buildFileMap(entry.files || [], rawFiles);
  switch (entry.topologyMode) {
    case 'meshdiag-networkdiag': return adaptMeshdiagNetworkdiag(fileMap);
    case 'merged-detailed': return adaptMergedDetailed(fileMap);
    case 'eve_enhanced': return adaptEve(fileMap);
    case 'eve_native': return adaptEveNative(fileMap);
    case 'router-table': return adaptRouterTable(fileMap);
    case 'otbr_restapi': return adaptOtbrRestApi(fileMap);
    case 'raw-array':
    default: return adaptRawArray(fileMap);
  }
}
