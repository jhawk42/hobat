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
  normalizeFieldNames,
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

function buildEdgeEndpointTitlePart(nodeLike, fallbackId = '') {
  const rloc16 = toText(nodeLike?.rloc16) || toText(fallbackId) || 'n/a';
  const candidateId = toText(nodeLike?.id);
  const canonicalExtaddr = getCanonicalExtaddr(nodeLike);
  const deviceLabel =
    toText(nodeLike?.deviceLabel)
    || toText(nodeLike?.device_label)
    || toText(nodeLike?.name)
    || toText(nodeLike?.hostName)
    || (candidateId && candidateId !== rloc16 ? candidateId : '')
    || toText(nodeLike?.extAddress)
    || canonicalExtaddr
    || toText(nodeLike?.extaddr)
    || '';
  return `${rloc16} ${deviceLabel}`;
}

function buildEdgeEndpointTitles(fromNodeLike, toNodeLike, fromFallbackId = '', toFallbackId = '') {
  return {
    edgeFromTitle: buildEdgeEndpointTitlePart(fromNodeLike, fromFallbackId),
    edgeToTitle: buildEdgeEndpointTitlePart(toNodeLike, toFallbackId),
  };
}

function getOtbrRouteCategory(sourceNode) {
  const role = toText(sourceNode?.role).trim().toLowerCase();
  const modeDevice = toText(
    sourceNode?.['mode.device']
    || sourceNode?.mode?.device
    || sourceNode?.modeDevice
    || sourceNode?.mode_device
    || (sourceNode?.mode?.deviceTypeFTD === true ? 'FTD' : ''),
  ).toUpperCase();
  const hasRouterFlag =
    sourceNode?.isBorderRouter === true || sourceNode?.isRouter === true;

  if (role === 'child') {
    if (hasRouterFlag) return '';
    return modeDevice === 'FTD' ? EDGE_CATEGORY_OTBR_ROUTE_FTD_CHILD : '';
  }
  if (
    hasRouterFlag
    || role === 'border router'
    || role === 'router'
  ) {
    return EDGE_CATEGORY_OTBR_ROUTE_ROUTER;
  }
  return '';
}

function getOtbrRouteCategories(sourceNode) {
  const category = getOtbrRouteCategory(sourceNode);
  return category ? [EDGE_CATEGORY_OTBR_ROUTE, category] : [];
}

function applyMergedRowLabels(nodeMap, mergedRows) {
  if (!Array.isArray(mergedRows) || mergedRows.length === 0) return;

  const nodeIdByRloc16 = new Map();
  const nodeIdByExtaddr = new Map();
  const nodeIdByOmr = new Map();
  nodeMap.forEach((node, nodeId) => {
    const rloc16 = getCanonicalRloc16(node);
    const extaddr = getCanonicalExtaddr(node);
    const omr = getCanonicalOmrIpv6Address(node);
    if (rloc16) nodeIdByRloc16.set(rloc16, nodeId);
    if (extaddr) nodeIdByExtaddr.set(extaddr, nodeId);
    if (omr) nodeIdByOmr.set(omr, nodeId);
  });

  mergedRows.forEach((row) => {
    if (!isPlainObject(row)) return;
    const rloc16 = getCanonicalRloc16(row);
    const extaddr = getCanonicalExtaddr(row);
    const omr = getCanonicalOmrIpv6Address(row);
    const nodeId =
      (extaddr && nodeIdByExtaddr.get(extaddr))
      || (omr && nodeIdByOmr.get(omr))
      || (rloc16 && nodeIdByRloc16.get(rloc16));
    if (!nodeId) return;

    const deviceLabel =
      toText(row.deviceLabel) || toText(row.device_label) || toText(row.name);
    if (!deviceLabel) return;
    const node = nodeMap.get(nodeId);
    if (node) nodeMap.set(nodeId, { ...node, deviceLabel });
  });
}

// ── Adaptor 1: meshdiag + networkdiag + routerNeighbors + restApi ─────────────

export function adaptMeshdiagNetworkdiag(fileMap, mergedRows = []) {
  const meshdiag = asArray(fileMap.get(FILE_MESHDIAG));
  const networkDiag = asArray(
    fileMap.get(FILE_NETWORKDIAG_FETCH_ALL) ?? fileMap.get(FILE_NETWORKDIAG_MULTICAST)
  );
  const routerNeighborTables = asArray(fileMap.get(FILE_ROUTER_NEIGHBORTABLES));
  const routerChildTables = asArray(fileMap.get(FILE_ROUTER_CHILDTABLES));
  const restApiMeshDiagnostics = asArray(fileMap.get(FILE_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL));
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
  const restMeshByRloc16 = new Map();

  function upsertNode(nodeId, rawNode, style) {
    const existing = nodeMap.get(nodeId);
    const rawIpv6 = Array.isArray(rawNode.ipv6_addrs) ? rawNode.ipv6_addrs : [];
    const existingIpv6 = existing && Array.isArray(existing.ipv6_addrs) ? existing.ipv6_addrs : [];
    const mergedIpv6 = rawIpv6.length > 0 ? rawIpv6 : existingIpv6;
    const rawChildren = Array.isArray(rawNode.children) ? rawNode.children : [];
    const getRawMetric = (path) => toFiniteNumber(getColumnValue(rawNode, path));
    const rawPacketErrorDiscardPct = getRawMetric('macCounters.ifInDiscardsPercentage');
    const rawInerrorsPct = getRawMetric('macCounters.ifInErrorsPercentage');
    const rawOuterrorsPct = getRawMetric('macCounters.ifOutErrorsPercentage');
    const rawModeDevice = rawNode.mode && toText(rawNode.mode.device)
      ? toText(rawNode.mode.device)
      : (rawNode.mode?.deviceTypeFTD === true ? 'FTD' : (rawNode.mode?.deviceTypeFTD === false ? 'MTD' : ''));
    const rawPartitionIdChanges = getRawMetric('mleCounters.partIdChangesCount');
    const rawParentChanges = getRawMetric('mleCounters.newParentCount');
    // Phase 1a: new fields
    const mergedTotalLink3 = Number.isFinite(rawNode.totalLink3) ? rawNode.totalLink3
      : (Number.isFinite(rawNode.total_link_3) ? rawNode.total_link_3
        : (Array.isArray(rawNode.links3) ? rawNode.links3.length
          : (Number.isFinite(rawNode.links3) ? rawNode.links3
            : (existing && Number.isFinite(existing.totalLink3 ?? existing.total_link_3)
              ? (existing.totalLink3 ?? existing.total_link_3)
              : undefined))));
    const mergedTotalLink2 = Number.isFinite(rawNode.totalLink2) ? rawNode.totalLink2
      : (Number.isFinite(rawNode.total_link_2) ? rawNode.total_link_2
        : (Array.isArray(rawNode.links2) ? rawNode.links2.length
          : (Number.isFinite(rawNode.links2) ? rawNode.links2
            : (existing && Number.isFinite(existing.totalLink2 ?? existing.total_link_2)
              ? (existing.totalLink2 ?? existing.total_link_2)
              : undefined))));
    const mergedTotalLink1 = Number.isFinite(rawNode.totalLink1) ? rawNode.totalLink1
      : (Number.isFinite(rawNode.total_link_1) ? rawNode.total_link_1
        : (Array.isArray(rawNode.links1) ? rawNode.links1.length
          : (Number.isFinite(rawNode.links1) ? rawNode.links1
            : (existing && Number.isFinite(existing.totalLink1 ?? existing.total_link_1)
              ? (existing.totalLink1 ?? existing.total_link_1)
              : undefined))));
    const mergedTotalLinks = Number.isFinite(rawNode.totalLinks) ? rawNode.totalLinks
      : (Number.isFinite(rawNode.total_links) ? rawNode.total_links
        : (Number.isFinite(mergedTotalLink3) && Number.isFinite(mergedTotalLink2) && Number.isFinite(mergedTotalLink1)
          ? (mergedTotalLink3 + mergedTotalLink2 + mergedTotalLink1)
          : (existing ? (existing.totalLinks ?? existing.total_links ?? 0) : 0)));
    const lq3Ratio = (Number.isFinite(mergedTotalLink3) && mergedTotalLinks > 0)
      ? mergedTotalLink3 / mergedTotalLinks : undefined;
    const lq1Ratio = (Number.isFinite(mergedTotalLink1) && mergedTotalLinks > 0)
      ? mergedTotalLink1 / mergedTotalLinks : undefined;
    let hasChildLqMedium = false;
    let hasChildLqPoor = false;
    rawChildren.forEach((child) => {
      const lqRaw = child.lq !== undefined ? child.lq : child.linkQuality;
      const lqNum = Number.parseInt(lqRaw, 10);
      if (Number.isFinite(lqNum)) {
        if (lqNum <= 2) hasChildLqMedium = true;
        if (lqNum === 1) hasChildLqPoor = true;
      }
    });
    const rawTotalErrorsRatio = getRawMetric('macCounters.ifTotalErrorsTotalPktsRatio');
    const rawTotalDiscardsRatio = getRawMetric('macCounters.ifTotalDiscardsTotalPktsRatio');
    const rawBetterPartition = getRawMetric('mleCounters.betterPartIdAttachAttemptsCount');
    const rawTotalParentPartition = getRawMetric('mleCounters.totalParentPartitionChangesCount');
    const rawRouterPct = getRawMetric('timeStatistics.routerPct');
    const rawDetachedDisabledPct = getRawMetric('timeStatistics.detachedDisabledPct');
    const merged = {
      id: nodeId,
      deviceLabel: toText(rawNode.device_label) || (existing ? existing.deviceLabel || existing.device_label : ''),
      rloc16: toText(rawNode.rloc16) || (existing ? existing.rloc16 : ''),
      sourceId: toText(rawNode.id) || (existing ? existing.sourceId || existing.source_id : ''),
      extAddress: toText(rawNode.extaddr) || (existing ? existing.extAddress || existing.extaddr : ''),
      type: toText(rawNode.type) || (existing ? existing.type : ''),
      role: toText(rawNode.role).trim().toLowerCase() || (existing ? existing.role : ''),
      threadVersion: toText(rawNode.thread_version) || (existing ? existing.threadVersion || existing.thread_version : ''),
      threadStackVersion: toText(rawNode.thread_stack_version) || (existing ? existing.threadStackVersion || existing.thread_stack_version : ''),
      ipv6Addresses: mergedIpv6,
      totalChildren: Number.isFinite(rawNode.total_children)
        ? rawNode.total_children : (rawChildren.length || (existing ? existing.totalChildren || existing.total_children : 0)),
      totalLinks: mergedTotalLinks,
      totalLink3: mergedTotalLink3,
      totalLink2: mergedTotalLink2,
      totalLink1: mergedTotalLink1,
      lq3Ratio: lq3Ratio,
      lq1Ratio: lq1Ratio,
      hasChildLqMedium: hasChildLqMedium || (existing ? (existing.hasChildLqMedium || existing.has_child_lq_medium) === true : false),
      hasChildLqPoor: hasChildLqPoor || (existing ? (existing.hasChildLqPoor || existing.has_child_lq_poor) === true : false),
      ifInDiscardsPct: Number.isFinite(rawPacketErrorDiscardPct) ? rawPacketErrorDiscardPct
        : (existing && Number.isFinite(existing.ifInDiscardsPct || existing.ifindiscards_pct) ? (existing.ifInDiscardsPct || existing.ifindiscards_pct) : undefined),
      ifInErrorsPct: Number.isFinite(rawInerrorsPct) ? rawInerrorsPct
        : (existing && Number.isFinite(existing.ifInErrorsPct || existing.ifinerrors_pct) ? (existing.ifInErrorsPct || existing.ifinerrors_pct) : undefined),
      ifOutErrorsPct: Number.isFinite(rawOuterrorsPct) ? rawOuterrorsPct
        : (existing && Number.isFinite(existing.ifOutErrorsPct || existing.ifouterrors_pct) ? (existing.ifOutErrorsPct || existing.ifouterrors_pct) : undefined),
      ifTotalErrorsTotalPktsRatio: rawTotalErrorsRatio !== undefined ? rawTotalErrorsRatio
        : (existing && Number.isFinite(existing.ifTotalErrorsTotalPktsRatio || existing.iftotalerrors_totalpkts_ratio) ? (existing.ifTotalErrorsTotalPktsRatio || existing.iftotalerrors_totalpkts_ratio) : undefined),
      ifTotalDiscardsTotalPktsRatio: rawTotalDiscardsRatio !== undefined ? rawTotalDiscardsRatio
        : (existing && Number.isFinite(existing.ifTotalDiscardsTotalPktsRatio || existing.iftotaldiscards_totalpkts_ratio) ? (existing.ifTotalDiscardsTotalPktsRatio || existing.iftotaldiscards_totalpkts_ratio) : undefined),
      modeDevice: rawModeDevice || (existing ? existing.modeDevice || existing.mode_device : ''),
      partitionIdChanges: Number.isFinite(rawPartitionIdChanges) ? rawPartitionIdChanges
        : (existing && Number.isFinite(existing.partitionIdChanges || existing.partitionidchanges) ? (existing.partitionIdChanges || existing.partitionidchanges) : undefined),
      parentChanges: Number.isFinite(rawParentChanges) ? rawParentChanges
        : (existing && Number.isFinite(existing.parentChanges || existing.parentchanges) ? (existing.parentChanges || existing.parentchanges) : undefined),
      betterPartitionAttachAttempts: rawBetterPartition !== undefined ? rawBetterPartition
        : (existing && Number.isFinite(existing.betterPartitionAttachAttempts || existing.betterpartitionattachattempts) ? (existing.betterPartitionAttachAttempts || existing.betterpartitionattachattempts) : undefined),
      totalParentPartitionChanges: rawTotalParentPartition !== undefined ? rawTotalParentPartition
        : (existing && Number.isFinite(existing.totalParentPartitionChanges || existing.totalparentpartitionchanges) ? (existing.totalParentPartitionChanges || existing.totalparentpartitionchanges) : undefined),
      routerPct: rawRouterPct !== undefined ? rawRouterPct
        : (existing && Number.isFinite(existing.routerPct || existing.router_pct) ? (existing.routerPct || existing.router_pct) : undefined),
      detachedDisabledPct: rawDetachedDisabledPct !== undefined ? rawDetachedDisabledPct
        : (existing && Number.isFinite(existing.detachedDisabledPct || existing.detached_disabled_pct) ? (existing.detachedDisabledPct || existing.detached_disabled_pct) : undefined),
      br: rawNode.br === true || (existing ? existing.br === true : false),
      fromMeshdiag: (style.source === 'meshdiag') || (existing ? (existing.fromMeshdiag || existing.from_meshdiag) === true : false),
      fromNetworkdiagnostic: (style.source === 'networkdiagnostic') || (existing ? (existing.fromNetworkdiagnostic || existing.from_networkdiagnostic) === true : false),
      shape: (existing && existing.shape === NODE_SHAPES.child) ? NODE_SHAPES.child : (style.shape || (existing ? existing.shape : NODE_SHAPES.router)),
      color: style.color || (existing ? existing.color : NODE_COLORS.router)
    };
    merged.isFtdRouter = merged.modeDevice === 'FTD' && merged.rloc16.toLowerCase().endsWith('00');
    // Apply role-based color overrides
    if (merged.br) {
      merged.color = NODE_COLORS.borderRouter;
    } else if (merged.shape === NODE_SHAPES.child) {
      // Child nodes (ellipse shape) should always use child color, not router default
      merged.color = NODE_COLORS.child;
    }
    nodeMap.set(nodeId, normalizeFieldNames(merged));
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
      source: 'meshdiag', shape: NODE_SHAPES.router,
      color: node.br ? NODE_COLORS.borderRouter : NODE_COLORS.router
    });
  });

  networkDiag.forEach((node, index) => {
    const uid = chooseNodeId(node, 'netdiag-node', index + 1);
    networkDiagById.set(uid, node);
    upsertNode(uid, node, { source: 'networkdiagnostic', shape: NODE_SHAPES.router, color: NODE_COLORS.router });
  });

  restApiDiagnostics.forEach((node, index) => {
    const uid = chooseNodeId(node, 'restapi-node', index + 1);
    restApiById.set(uid, node);
    upsertNode(uid, node, { source: 'networkdiagnostic', shape: NODE_SHAPES.router, color: NODE_COLORS.router });
  });

  routerNeighborTables.forEach((row) => {
    const rloc16 = toText(row.rloc16).toLowerCase();
    if (rloc16) routerNeighborByRloc16.set(rloc16, row);
  });

  routerChildTables.forEach((row) => {
    const rloc16 = toText(row.parent_rloc16 || row.rloc16).toLowerCase();
    if (rloc16) routerChildByRloc16.set(rloc16, row);
  });

  restApiMeshDiagnostics.forEach((row) => {
    const rloc16 = toText(row.rloc16).toLowerCase();
    if (rloc16) restMeshByRloc16.set(rloc16, row);
  });

  function findRouterChildLinkMargin(parentRloc16, childRloc16) {
    const parentKey = toText(parentRloc16).toLowerCase();
    const childKey = toText(childRloc16).toLowerCase();
    if (!parentKey || !childKey) return undefined;
    const parentRow = routerChildByRloc16.get(parentKey);
    const childRows = Array.isArray(parentRow?.router_child_table)
      ? parentRow.router_child_table
      : [];
    const childRow = childRows.find(
      (entry) => toText(entry?.rloc16).toLowerCase() === childKey,
    );
    return toFiniteNumber(childRow?.rss_margin);
  }

  for (const node of meshdiag) {
    const fromId = chooseNodeId(node, 'meshdiag-parent', 0);
    (Array.isArray(node.children) ? node.children : []).forEach((child, ci) => {
      const childId = toText(child.rloc16) || `${fromId}-child-${ci + 1}`;
      const linkMargin = findRouterChildLinkMargin(node.rloc16, child.rloc16);
      const childLq = toFiniteNumber(child.lq) || toFiniteNumber(child.link_quality);
      const lqStyle = Number.isFinite(childLq)
        ? lqStyleFromAvgLqi(childLq, 3)
        : (Number.isFinite(linkMargin) ? lqStyleFromLinkMargin(linkMargin) : {});
      upsertNode(childId, { device_label: toText(child.device_label), rloc16: toText(child.rloc16), id: childId },
        { source: 'meshdiag', shape: NODE_SHAPES.child, color: NODE_COLORS.child });
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...lqStyle,
        linkMargin,
        ...buildEdgeEndpointTitles(node, childNodeEnriched, fromId, childId),
        linkCategories: [EDGE_CATEGORY_DEFAULT_CHILDREN]
      });
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
            { source: 'meshdiag', shape: NODE_SHAPES.router, color: NODE_COLORS.eve });
        }
        const toNodeEnriched = nodeMap.get(toId);
        addEdge(edgeMap, edgeData, fromId, toId, {
          ...lqStyle,
          ...buildEdgeEndpointTitles(node, toNodeEnriched, fromId, toId),
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
        { source: 'meshdiag', shape: NODE_SHAPES.router, color: NODE_COLORS.eve }
      );
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        width: 1.5,
        linkMargin: toFiniteNumber(neighbor.rss_margin),
        ...buildEdgeEndpointTitles(node, toNodeEnriched, fromId, toId),
        linkCategories: [EDGE_CATEGORY_ROUTER_NEIGHBOR],
      });
    });

    const restMeshRow = restMeshByRloc16.get(toText(node.rloc16).toLowerCase());
    (Array.isArray(restMeshRow?.routerNeighbors) ? restMeshRow.routerNeighbors : []).forEach((neighbor) => {
      const toId = ensureNode(
        toText(neighbor.rloc16) || toText(neighbor.extAddress),
        {
          rloc16: toText(neighbor.rloc16),
          extaddr: toText(neighbor.extAddress),
          device_label: toText(neighbor.device_label),
          id: toText(neighbor.rloc16) || toText(neighbor.extAddress)
        },
        { source: 'networkdiagnostic', shape: NODE_SHAPES.router, color: NODE_COLORS.eve }
      );
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        ...lqStyleFromLinkMargin(neighbor.linkMargin),
        linkMargin: toFiniteNumber(neighbor.linkMargin),
        ...buildEdgeEndpointTitles(node, toNodeEnriched, fromId, toId),
        linkCategories: [EDGE_CATEGORY_ROUTER_NEIGHBOR],
      });
    });

    (Array.isArray(restMeshRow?.children) ? restMeshRow.children : []).forEach((child, ci) => {
      const childId = ensureNode(
        toText(child.rloc16) || toText(child.extAddress) || `${fromId}-restmesh-child-${ci + 1}`,
        {
          rloc16: toText(child.rloc16),
          extaddr: toText(child.extAddress),
          device_label: toText(child.device_label),
          id: toText(child.rloc16) || toText(child.extAddress) || `${fromId}-restmesh-child-${ci + 1}`
        },
        { source: 'networkdiagnostic', shape: NODE_SHAPES.child, color: NODE_COLORS.child }
      );
      const linkMargin = toFiniteNumber(child.linkMargin);
      const lqStyle = Number.isFinite(linkMargin) ? lqStyleFromLinkMargin(linkMargin) : {};
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...lqStyle,
        linkMargin,
        ...buildEdgeEndpointTitles(node, childNodeEnriched, fromId, childId),
        linkCategories: [EDGE_CATEGORY_OTBR_CHILD],
      });
      routerIdsWithChildren.add(fromId);
    });
  }

  for (const node of networkDiag) {
    const fromId = chooseNodeId(node, 'netdiag-parent', 0);
    const routeCategories = getOtbrRouteCategories(node);
    (Array.isArray(node.children) ? node.children : []).forEach((child, ci) => {
      const childId = toText(child.rloc16) || `${fromId}-child-${ci + 1}`;
      const linkMargin = findRouterChildLinkMargin(node.rloc16, child.rloc16);
      const childLq = toFiniteNumber(child.lq) || toFiniteNumber(child.link_quality);
      const lqStyle = Number.isFinite(childLq)
        ? lqStyleFromAvgLqi(childLq, 3)
        : (Number.isFinite(linkMargin) ? lqStyleFromLinkMargin(linkMargin) : {});
      upsertNode(childId, { device_label: toText(child.device_label), rloc16: toText(child.rloc16), id: childId },
        { source: 'networkdiagnostic', shape: NODE_SHAPES.child, color: NODE_COLORS.child });
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...lqStyle,
        linkMargin,
        ...buildEdgeEndpointTitles(node, childNodeEnriched, fromId, childId),
        linkCategories: [EDGE_CATEGORY_DEFAULT_CHILDREN]
      });
      routerIdsWithChildren.add(fromId);
    });

    // Process route routes from networkdiag (multicast variant).
    // route.routeData[] contains routing table entries with LQI metrics.
    // Each route has a direct rloc16 target (no ID conversion needed).
    (Array.isArray(node.route?.routeData) ? node.route.routeData : []).forEach((route) => {
      if (routeCategories.length === 0) return;
      const toRloc16 = toText(route.rloc16);
      if (!toRloc16) return;

      // Ensure target node exists
      const toId = ensureNode(
        toRloc16,
        { rloc16: toRloc16, id: toRloc16, device_label: toRloc16 },
        { source: 'networkdiagnostic', shape: NODE_SHAPES.router, color: NODE_COLORS.router }
      );

      // Compute LQI-based edge style
      const lqIn = toFiniteNumber(route.linkQualityIn) || 0;
      const lqOut = toFiniteNumber(route.linkQualityOut) || 0;
      const avgLqi = Math.max(lqIn, lqOut); // Take max for conservative estimate
      const lqStyle = lqStyleFromAvgLqi(avgLqi, 3);

      // Add edge with LQI styling
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        ...lqStyle,
        ...buildEdgeEndpointTitles(node, toNodeEnriched, fromId, toId),
        linkCategories: routeCategories,
      });
    });
  }

  restApiDiagnostics.forEach((node) => {
    const fromId = chooseNodeId(node, 'restapi-parent', 0);
    const routeCategories = getOtbrRouteCategories(node);
    (Array.isArray(node.route?.routeData) ? node.route.routeData : []).forEach((route) => {
      if (routeCategories.length === 0) return;
      const toRloc16 = buildMainRouterRloc16(route.routeId);
      if (!toRloc16) return;
      const toId = ensureNode(toRloc16, { rloc16: toRloc16, id: toRloc16, device_label: toRloc16 },
        { source: 'networkdiagnostic', shape: NODE_SHAPES.router, color: NODE_COLORS.router });
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        width: 1.5,
        ...buildEdgeEndpointTitles(node, toNodeEnriched, fromId, toId),
        linkCategories: routeCategories,
      });
    });
    (Array.isArray(node.childTable) ? node.childTable : []).forEach((child, ci) => {
      const childRloc16 = buildChildRloc16(node.rloc16, child.childId);
      const linkMargin = findRouterChildLinkMargin(node.rloc16, childRloc16);
      const childLq = toFiniteNumber(child.linkQuality);
      const lqStyle = Number.isFinite(childLq)
        ? lqStyleFromAvgLqi(childLq, 3)
        : (Number.isFinite(linkMargin) ? lqStyleFromLinkMargin(linkMargin) : {});
      const childId = ensureNode(
        childRloc16 || `${fromId}-rest-child-${ci + 1}`,
        {
          rloc16: childRloc16, id: childRloc16 || `${fromId}-rest-child-${ci + 1}`,
          device_label: childRloc16 || `${fromId} child ${child.childId}`
        },
        { source: 'networkdiagnostic', shape: NODE_SHAPES.child, color: NODE_COLORS.child }
      );
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...lqStyle,
        linkMargin,
        ...buildEdgeEndpointTitles(node, childNodeEnriched, fromId, childId),
        linkCategories: [EDGE_CATEGORY_OTBR_CHILD]
      });
      routerIdsWithChildren.add(fromId);
    });
  });

  applyMergedRowLabels(nodeMap, mergedRows);
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
        // Supplementary files (e.g. mdns) should enrich missing fields but not
        // clobber canonical values already derived from primary topology files.
        rawByIdForDetails.set(nodeId, mergeForDisplay(record, existing));
    });
  }

  const sourceNames = [];
  if (meshdiag.length > 0) sourceNames.push('meshdiag');
  if (networkDiag.length > 0) sourceNames.push('networkdiagnostic');
  if (routerNeighborTables.length > 0) sourceNames.push('routerneighbortables');
  if (routerChildTables.length > 0) sourceNames.push('routerchildtables');
  if (restApiDiagnostics.length > 0) sourceNames.push('restapi');
  if (restApiMeshDiagnostics.length > 0) sourceNames.push('restapi_mesh_diagnostics');

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
      deviceLabel: toText(rawNode.device_label) || (existing ? existing.deviceLabel || existing.device_label : ''),
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
    nodeMap.set(nodeId, normalizeFieldNames(merged));
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
    nodeMap.set(nodeId, normalizeFieldNames(merged));
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

  return { nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, sourceNames: ['eve_native'] };
}

// ── Adaptor 2c: Thread Tools native diagnostics (diagnostics.json) ───────────

export function adaptThreadToolsNative(fileMap) {
  const raw = fileMap.values().next().value;
  const diagnostics = (raw && Array.isArray(raw.diagnostics)) ? raw.diagnostics
    : (Array.isArray(raw) ? raw : []);

  const nodeMap = new Map();
  const rawByIdForDetails = new Map();
  const rloc16ToNodeId = new Map();
  const edgeMap = new Map();
  const edgeData = [];
  const routerIdsWithChildren = new Set();
  const routerNeighborByRloc16 = new Map();
  const routerChildByRloc16 = new Map();

  function macAddrToRloc16(value) {
    const n = toFiniteNumber(value);
    if (!Number.isFinite(n)) return '';
    return `0x${Math.trunc(n).toString(16).padStart(4, '0')}`;
  }

  function chooseThreadToolsNodeId(node, index = 0) {
    const rloc16 = macAddrToRloc16(node?.macAddr) || toText(node?.rloc16).toLowerCase();
    const extaddr = toText(node?.extMacAddr || node?.extAddress || node?.extaddr).toLowerCase();
    const peerAddress = toText(node?.peerAddress);
    return rloc16 || extaddr || peerAddress || `thread-tools-node-${index + 1}`;
  }

  function upsertThreadToolsNode(nodeId, rawNode, style) {
    const existing = nodeMap.get(nodeId);
    const rloc16Val = macAddrToRloc16(rawNode.macAddr)
      || toText(rawNode.rloc16)
      || (existing ? toText(existing.rloc16) : '');
    const extaddrVal = toText(rawNode.extMacAddr || rawNode.extAddress || rawNode.extaddr).toLowerCase()
      || (existing ? toText(existing.extAddress || existing.extaddr).toLowerCase() : '');
    const modeFtd = rawNode.mode?.ftd;
    const inferredType = modeFtd === true ? 'router' : (modeFtd === false ? 'child' : '');
    const inferredModeDevice = modeFtd === true ? 'FTD' : (modeFtd === false ? 'MTD' : '');
    const connectivity = isPlainObject(rawNode.connectivity) ? rawNode.connectivity : {};
    const totalLink3 = toFiniteNumber(connectivity.linkQuality3)
      ?? (existing ? toFiniteNumber(existing.totalLink3 || existing.total_link_3) : undefined);
    const totalLink2 = toFiniteNumber(connectivity.linkQuality2)
      ?? (existing ? toFiniteNumber(existing.totalLink2 || existing.total_link_2) : undefined);
    const totalLink1 = toFiniteNumber(connectivity.linkQuality1)
      ?? (existing ? toFiniteNumber(existing.totalLink1 || existing.total_link_1) : undefined);
    const totalLinks = (Number.isFinite(totalLink3) && Number.isFinite(totalLink2) && Number.isFinite(totalLink1))
      ? (totalLink3 + totalLink2 + totalLink1)
      : (existing ? toFiniteNumber(existing.totalLinks || existing.total_links) : undefined);
    const lq3Ratio = (Number.isFinite(totalLink3) && Number.isFinite(totalLinks) && totalLinks > 0)
      ? totalLink3 / totalLinks : undefined;
    const lq1Ratio = (Number.isFinite(totalLink1) && Number.isFinite(totalLinks) && totalLinks > 0)
      ? totalLink1 / totalLinks : undefined;
    const childArray = Array.isArray(rawNode.children) ? rawNode.children : [];
    const childTableArray = Array.isArray(rawNode.childTable) ? rawNode.childTable : [];
    const totalChildren = childArray.length > 0 ? childArray.length
      : (childTableArray.length > 0 ? childTableArray.length
        : (existing ? toFiniteNumber(existing.totalChildren || existing.total_children) : 0));

    const merged = {
      id: nodeId,
      deviceLabel: toText(rawNode.device_label)
        || toText(rawNode.name)
        || toText(rawNode.hostName)
        || (existing ? toText(existing.deviceLabel || existing.device_label || existing.name) : ''),
      name: toText(rawNode.name) || toText(rawNode.hostName) || (existing ? toText(existing.name) : ''),
      rloc16: rloc16Val,
      extAddress: extaddrVal,
      peerAddress: toText(rawNode.peerAddress) || (existing ? toText(existing.peerAddress) : ''),
      type: toText(rawNode.type) || inferredType || (existing ? toText(existing.type) : ''),
      role: toText(rawNode.role).trim().toLowerCase() || (existing ? existing.role : ''),
      version: toText(rawNode.version) || (existing ? toText(existing.version) : ''),
      threadStackVersion: toText(rawNode.threadStackVersion)
        || (existing ? toText(existing.threadStackVersion || existing.thread_stack_version) : ''),
      ipv6Addresses: Array.isArray(rawNode.addrs)
        ? rawNode.addrs
        : (existing ? (existing.ipv6Addresses || existing.ipv6_addrs || []) : []),
      route: isPlainObject(rawNode.route64) ? rawNode.route64 : (existing ? (existing.route || existing.route64) : undefined),
      totalChildren,
      totalLinks,
      totalLink3,
      totalLink2,
      totalLink1,
      lq3Ratio,
      lq1Ratio,
      modeDevice: toText(rawNode.mode?.device)
        || inferredModeDevice
        || (existing ? toText(existing.modeDevice || existing.mode_device) : ''),
      partitionIdChanges: toFiniteNumber(rawNode.mleCounters?.partitionIdChangesCounter)
        ?? (existing ? toFiniteNumber(existing.partitionIdChanges || existing.partitionidchanges) : undefined),
      parentChanges: toFiniteNumber(rawNode.mleCounters?.newParentCounter)
        ?? (existing ? toFiniteNumber(existing.parentChanges || existing.parentchanges) : undefined),
      betterPartitionAttachAttempts: toFiniteNumber(rawNode.mleCounters?.betterPartitionAttachAttemptsCounter)
        ?? (existing ? toFiniteNumber(existing.betterPartitionAttachAttempts || existing.betterpartitionattachattempts) : undefined),
      routerPct: toFiniteNumber(rawNode.timeStatistics?.routerPct)
        ?? (existing ? toFiniteNumber(existing.routerPct || existing.router_pct) : undefined),
      detachedDisabledPct: toFiniteNumber(rawNode.timeStatistics?.detachedDisabledPct)
        ?? (existing ? toFiniteNumber(existing.detachedDisabledPct || existing.detached_disabled_pct) : undefined),
      br: rawNode.br === true || (existing ? existing.br === true : false),
      fromThreadToolsNative: true,
      shape: style.shape || (existing ? existing.shape : (modeFtd === false ? NODE_SHAPES.child : NODE_SHAPES.router)),
      color: style.color || (existing ? existing.color : NODE_COLORS.router),
    };
    merged.isFtdRouter = merged.modeDevice === 'FTD' && merged.rloc16.toLowerCase().endsWith('00');
    if (merged.br) {
      merged.color = NODE_COLORS.borderRouter;
    } else if (merged.shape === NODE_SHAPES.child) {
      merged.color = NODE_COLORS.child;
    }

    nodeMap.set(nodeId, normalizeFieldNames(merged));
    if (merged.rloc16) rloc16ToNodeId.set(merged.rloc16.toLowerCase(), nodeId);
  }

  diagnostics.forEach((node, index) => {
    if (!isPlainObject(node)) return;
    const nodeId = chooseThreadToolsNodeId(node, index);
    const modeFtd = node.mode?.ftd;
    const isChildLike = modeFtd === false;
    upsertThreadToolsNode(nodeId, node, {
      shape: isChildLike ? NODE_SHAPES.child : NODE_SHAPES.router,
      color: isChildLike ? NODE_COLORS.child : NODE_COLORS.router,
    });

    const existing = rawByIdForDetails.get(nodeId) || {};
    rawByIdForDetails.set(nodeId, mergeForDisplay(existing, node));
  });

  diagnostics.forEach((node, index) => {
    if (!isPlainObject(node)) return;
    const fromId = chooseThreadToolsNodeId(node, index);
    if (!fromId || !nodeMap.has(fromId)) return;
    const fromNode = nodeMap.get(fromId);

    (Array.isArray(node.route64?.routeData) ? node.route64.routeData : []).forEach((route) => {
      const routeId = route?.routeId ?? route?.routerId;
      const toRloc16 = buildMainRouterRloc16(routeId);
      if (!toRloc16) return;
      const toId = rloc16ToNodeId.get(toRloc16.toLowerCase()) || toRloc16;
      if (!nodeMap.has(toId)) {
        upsertThreadToolsNode(toId, { rloc16: toRloc16, id: toId, mode: { ftd: true } },
          { shape: NODE_SHAPES.router, color: NODE_COLORS.router });
      }

      const lqi = Math.max(
        toFiniteNumber(route.linkQualityOut ?? route.outLinkQuality) || 0,
        toFiniteNumber(route.linkQualityIn ?? route.inLinkQuality) || 0,
      );
      const lqStyle = lqStyleFromAvgLqi(lqi, 3);
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        ...lqStyle,
        ...buildEdgeEndpointTitles(fromNode, toNodeEnriched, fromId, toId),
        linkCategories: [EDGE_CATEGORY_OTBR_ROUTE],
      });
    });

    (Array.isArray(node.childTable) ? node.childTable : []).forEach((child, ci) => {
      const childRloc16 = buildChildRloc16(toText(fromNode.rloc16), child.childId);
      const childLq = toFiniteNumber(child.linkQuality ?? child.incomingLinkQuality);
      const lqStyle = Number.isFinite(childLq) ? lqStyleFromAvgLqi(childLq, 3) : {};
      const childId = (childRloc16 && rloc16ToNodeId.get(childRloc16.toLowerCase()))
        || childRloc16
        || `${fromId}-child-${ci + 1}`;

      if (!nodeMap.has(childId)) {
        upsertThreadToolsNode(childId, {
          rloc16: childRloc16,
          id: childId,
          mode: child.mode,
          type: child.mode?.ftd === false ? 'child' : '',
        }, { shape: NODE_SHAPES.child, color: NODE_COLORS.child });
      }

      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...lqStyle,
        ...buildEdgeEndpointTitles(fromNode, childNodeEnriched, fromId, childId),
        linkCategories: [EDGE_CATEGORY_OTBR_CHILD],
      });
      routerIdsWithChildren.add(fromId);

      const fromRloc16 = toText(fromNode.rloc16).toLowerCase();
      if (fromRloc16) {
        if (!routerChildByRloc16.has(fromRloc16)) {
          routerChildByRloc16.set(fromRloc16, { rloc16: fromRloc16, router_child_table: [] });
        }
        const childRow = routerChildByRloc16.get(fromRloc16);
        if (Array.isArray(childRow.router_child_table)) {
          const childForFilter = {
            ...child,
            linkQuality: toFiniteNumber(child.linkQuality ?? child.incomingLinkQuality),
            rloc16: childRloc16,
          };
          const normalizedChild = normalizeNestedArrayFields([childForFilter])[0];
          childRow.router_child_table.push(normalizedChild);
        }
      }
    });

    (Array.isArray(node.children) ? node.children : []).forEach((child, ci) => {
      const childObj = isPlainObject(child) ? child : {};
      const childRloc16 = toText(childObj.rloc16) || macAddrToRloc16(childObj.macAddr);
      const childExtaddr = toText(childObj.extAddress || childObj.extMacAddr || childObj.extaddr).toLowerCase();
      const childId = (childRloc16 && rloc16ToNodeId.get(childRloc16.toLowerCase()))
        || childExtaddr
        || childRloc16
        || `${fromId}-children-${ci + 1}`;

      if (!nodeMap.has(childId)) {
        upsertThreadToolsNode(childId, {
          id: childId,
          rloc16: childRloc16,
          extAddress: childExtaddr,
          mode: childObj.mode,
          type: childObj.mode?.ftd === false ? 'child' : '',
        }, { shape: NODE_SHAPES.child, color: NODE_COLORS.child });
      }

      const linkMargin = toFiniteNumber(childObj.linkMargin);
      const childLq = toFiniteNumber(childObj.linkQuality ?? childObj.lq ?? childObj.incomingLinkQuality);
      const lqStyle = Number.isFinite(linkMargin)
        ? lqStyleFromLinkMargin(linkMargin)
        : (Number.isFinite(childLq) ? lqStyleFromAvgLqi(childLq, 3) : {});
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...lqStyle,
        linkMargin,
        ...buildEdgeEndpointTitles(fromNode, childNodeEnriched, fromId, childId),
        linkCategories: [EDGE_CATEGORY_OTBR_CHILD],
      });
      routerIdsWithChildren.add(fromId);

      const fromRloc16 = toText(fromNode.rloc16).toLowerCase();
      if (fromRloc16) {
        if (!routerChildByRloc16.has(fromRloc16)) {
          routerChildByRloc16.set(fromRloc16, { rloc16: fromRloc16, router_child_table: [] });
        }
        const childRow = routerChildByRloc16.get(fromRloc16);
        if (Array.isArray(childRow.router_child_table)) {
          const childForFilter = {
            ...childObj,
            linkQuality: toFiniteNumber(childObj.linkQuality ?? childObj.lq ?? childObj.incomingLinkQuality),
            rloc16: childRloc16,
            extAddress: childExtaddr,
          };
          const normalizedChild = normalizeNestedArrayFields([childForFilter])[0];
          childRow.router_child_table.push(normalizedChild);
        }
      }
    });

    (Array.isArray(node.routerNeighbor) ? node.routerNeighbor : []).forEach((neighbor) => {
      const neighborObj = isPlainObject(neighbor) ? neighbor : {};
      const neighborExtaddr = toText(neighborObj.extAddress || neighborObj.extMacAddr || neighborObj.extaddr).toLowerCase();
      const neighborRloc16 = toText(neighborObj.rloc16).toLowerCase() || macAddrToRloc16(neighborObj.macAddr);
      let toId = neighborExtaddr || neighborRloc16;
      if (!toId) return;

      if (neighborExtaddr && nodeMap.has(neighborExtaddr)) {
        toId = neighborExtaddr;
      } else if (neighborRloc16 && rloc16ToNodeId.has(neighborRloc16.toLowerCase())) {
        toId = rloc16ToNodeId.get(neighborRloc16.toLowerCase());
      } else if (!nodeMap.has(toId)) {
        upsertThreadToolsNode(toId, {
          extAddress: neighborExtaddr,
          rloc16: neighborRloc16,
          id: toId,
          mode: { ftd: true },
        }, { shape: NODE_SHAPES.router, color: NODE_COLORS.router });
      }

      const linkMargin = toFiniteNumber(neighborObj.linkMargin);
      const lqi = Math.max(
        toFiniteNumber(neighborObj.linkQualityOut ?? neighborObj.outLinkQuality) || 0,
        toFiniteNumber(neighborObj.linkQualityIn ?? neighborObj.inLinkQuality) || 0,
      );
      const lqStyle = Number.isFinite(linkMargin) ? lqStyleFromLinkMargin(linkMargin) : lqStyleFromAvgLqi(lqi, 3);
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        ...lqStyle,
        linkMargin,
        ...buildEdgeEndpointTitles(fromNode, toNodeEnriched, fromId, toId),
        linkCategories: [EDGE_CATEGORY_ROUTER_NEIGHBOR],
      });

      const fromRloc16 = toText(fromNode.rloc16).toLowerCase();
      if (fromRloc16) {
        if (!routerNeighborByRloc16.has(fromRloc16)) {
          routerNeighborByRloc16.set(fromRloc16, { rloc16: fromRloc16, router_neighbor_table: [] });
        }
        const neighborRow = routerNeighborByRloc16.get(fromRloc16);
        if (Array.isArray(neighborRow.router_neighbor_table)) {
          const normalizedNeighbor = normalizeNestedArrayFields([neighborObj])[0];
          neighborRow.router_neighbor_table.push(normalizedNeighbor);
        }
      }
    });
  });

  const nodeData = buildVisNodeData(nodeMap, routerIdsWithChildren, routerNeighborByRloc16, buildLabel, routerChildByRloc16);

  groupIsolatedUnknownNodes(nodeData, edgeData, edgeMap);

  return {
    nodeData,
    edgeData,
    nodeMap,
    rawByIdForDetails,
    routerNeighborByRloc16,
    routerChildByRloc16,
    sourceNames: ['thread_tools_native'],
  };
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
    return toText(node.rloc16) || toText(node.id) || getCanonicalExtaddr(node) || `merged-node-${index + 1}`;
  }

  function upsertMergedNode(nodeId, rawNode, style) {
    const existing = nodeMap.get(nodeId);
    const rawMergedChildren = Array.isArray(rawNode.children) ? rawNode.children : [];
    const mergedTotalLink3 = Number.isFinite(rawNode.totalLink3) ? rawNode.totalLink3
      : (Number.isFinite(rawNode.total_link_3) ? rawNode.total_link_3
        : (Array.isArray(rawNode.links3) ? rawNode.links3.length
          : (Number.isFinite(rawNode.links3) ? rawNode.links3
            : (existing && Number.isFinite(existing.totalLink3 ?? existing.total_link_3)
              ? (existing.totalLink3 ?? existing.total_link_3)
              : undefined))));
    const mergedTotalLink2 = Number.isFinite(rawNode.totalLink2) ? rawNode.totalLink2
      : (Number.isFinite(rawNode.total_link_2) ? rawNode.total_link_2
        : (Array.isArray(rawNode.links2) ? rawNode.links2.length
          : (Number.isFinite(rawNode.links2) ? rawNode.links2
            : (existing && Number.isFinite(existing.totalLink2 ?? existing.total_link_2)
              ? (existing.totalLink2 ?? existing.total_link_2)
              : undefined))));
    const mergedTotalLink1 = Number.isFinite(rawNode.totalLink1) ? rawNode.totalLink1
      : (Number.isFinite(rawNode.total_link_1) ? rawNode.total_link_1
        : (Array.isArray(rawNode.links1) ? rawNode.links1.length
          : (Number.isFinite(rawNode.links1) ? rawNode.links1
            : (existing && Number.isFinite(existing.totalLink1 ?? existing.total_link_1)
              ? (existing.totalLink1 ?? existing.total_link_1)
              : undefined))));
    const mergedTotalLinks = Number.isFinite(rawNode.totalLinks) ? rawNode.totalLinks
      : (Number.isFinite(rawNode.total_links) ? rawNode.total_links
        : (Number.isFinite(mergedTotalLink3) && Number.isFinite(mergedTotalLink2) && Number.isFinite(mergedTotalLink1)
          ? (mergedTotalLink3 + mergedTotalLink2 + mergedTotalLink1)
          : (existing ? (existing.totalLinks ?? existing.total_links ?? 0) : 0)));
    const lq3Ratio = (Number.isFinite(mergedTotalLink3) && mergedTotalLinks > 0)
      ? mergedTotalLink3 / mergedTotalLinks : undefined;
    const lq1Ratio = (Number.isFinite(mergedTotalLink1) && mergedTotalLinks > 0)
      ? mergedTotalLink1 / mergedTotalLinks : undefined;
    let hasChildLqMedium = false;
    let hasChildLqPoor = false;
    rawMergedChildren.forEach((child) => {
      const lqRaw = child.lq !== undefined ? child.lq : child.linkQuality;
      const lqNum = Number.parseInt(lqRaw, 10);
      if (Number.isFinite(lqNum)) {
        if (lqNum <= 2) hasChildLqMedium = true;
        if (lqNum === 1) hasChildLqPoor = true;
      }
    });
    const merged = {
      id: nodeId,
      name: toText(rawNode.name) || (existing ? existing.name : ''),
      deviceLabel: toText(rawNode.device_label) || (existing ? existing.deviceLabel || existing.device_label : ''),
      rloc16: toText(rawNode.rloc16) || (existing ? existing.rloc16 : ''),
      sourceId: toText(rawNode.id) || (existing ? existing.sourceId || existing.source_id : ''),
      extAddress: toText(rawNode.extaddr) || (existing ? existing.extAddress || existing.extaddr : ''),
      type: toText(rawNode.type) || (existing ? existing.type : ''),
      role: toText(rawNode.role).trim().toLowerCase() || (existing ? existing.role : ''),
      threadVersion: toText(rawNode.thread_version) || (existing ? existing.threadVersion || existing.thread_version : ''),
      threadStackVersion: toText(rawNode.thread_stack_version) || (existing ? existing.threadStackVersion || existing.thread_stack_version : ''),
      totalChildren: Number.isFinite(rawNode.total_children) ? rawNode.total_children : (existing ? existing.totalChildren || existing.total_children : 0),
      totalLinks: mergedTotalLinks,
      totalLink3: mergedTotalLink3,
      totalLink2: mergedTotalLink2,
      totalLink1: mergedTotalLink1,
      lq3Ratio: lq3Ratio,
      lq1Ratio: lq1Ratio,
      hasChildLqMedium: hasChildLqMedium || (existing ? (existing.hasChildLqMedium || existing.has_child_lq_medium) === true : false),
      hasChildLqPoor: hasChildLqPoor || (existing ? (existing.hasChildLqPoor || existing.has_child_lq_poor) === true : false),
      ifInDiscardsPct: Number.isFinite(rawNode.macCounters?.ifInDiscardsPercentage)
        ? rawNode.macCounters.ifInDiscardsPercentage : (existing?.ifInDiscardsPct || existing?.ifindiscards_pct),
      ifTotalErrorsPct: Number.isFinite(rawNode.macCounters?.ifTotalErrorsPercentage)
        ? rawNode.macCounters.ifTotalErrorsPercentage : (existing?.ifTotalErrorsPct || existing?.iftotalerrors_pct),
      ifTotalErrorsTotalPktsRatio: Number.isFinite(rawNode.macCounters?.ifTotalErrorsTotalPktsRatio)
        ? rawNode.macCounters.ifTotalErrorsTotalPktsRatio : (existing?.ifTotalErrorsTotalPktsRatio || existing?.iftotalerrors_totalpkts_ratio),
      ifTotalDiscardsTotalPktsRatio: Number.isFinite(rawNode.macCounters?.ifTotalDiscardsTotalPktsRatio)
        ? rawNode.macCounters.ifTotalDiscardsTotalPktsRatio : (existing?.ifTotalDiscardsTotalPktsRatio || existing?.iftotaldiscards_totalpkts_ratio),
      modeDevice: toText(rawNode['mode.device']) || toText(rawNode.mode?.device) || (existing ? existing.modeDevice || existing.mode_device : ''),
      partitionIdChanges: Number.isFinite(rawNode.mleCounters?.partIdChangesCount)
        ? rawNode.mleCounters.partIdChangesCount : (existing?.partitionIdChanges || existing?.partitionidchanges),
      parentChanges: Number.isFinite(rawNode.mleCounters?.newParentCount)
        ? rawNode.mleCounters.newParentCount : (existing?.parentChanges || existing?.parentchanges),
      betterPartitionAttachAttempts: Number.isFinite(rawNode.mleCounters?.betterPartIdAttachAttemptsCount)
        ? rawNode.mleCounters.betterPartIdAttachAttemptsCount : (existing?.betterPartitionAttachAttempts || existing?.betterpartitionattachattempts),
      totalParentPartitionChanges: Number.isFinite(rawNode.mleCounters?.totalParentPartitionChangesCount)
        ? rawNode.mleCounters.totalParentPartitionChangesCount : (existing?.totalParentPartitionChanges || existing?.totalparentpartitionchanges),
      routerPct: Number.isFinite(rawNode.timeStatistics?.routerPct)
        ? rawNode.timeStatistics.routerPct : (existing?.routerPct || existing?.router_pct),
      detachedDisabledPct: Number.isFinite(rawNode.timeStatistics?.detachedDisabledPct)
        ? rawNode.timeStatistics.detachedDisabledPct : (existing?.detachedDisabledPct || existing?.detached_disabled_pct),
      br: rawNode.br === true || (existing ? existing.br === true : false),
      fromMergedDetailed: true,
      shape: style.shape || (existing ? existing.shape : NODE_SHAPES.router),
      color: style.color || (existing ? existing.color : NODE_COLORS.eve)
    };
    merged.isFtdRouter = merged.modeDevice === 'FTD' && merged.rloc16.toLowerCase().endsWith('00');
    if (merged.br) merged.color = NODE_COLORS.borderRouter;
    nodeMap.set(nodeId, normalizeFieldNames(merged));
  }

  function ensureNodeForLink(linkNode, fallbackId) {
    const candidateId = toText(linkNode.rloc16) || toText(linkNode.id) || toText(fallbackId);
    if (!candidateId) return '';
    if (!nodeMap.has(candidateId)) {
      upsertMergedNode(candidateId, {
        rloc16: toText(linkNode.rloc16), id: toText(linkNode.id) || candidateId,
        device_label: toText(linkNode.device_label), name: toText(linkNode.name)
      }, { source: 'merged-detailed', shape: NODE_SHAPES.router, color: NODE_COLORS.eve });
    }
    return candidateId;
  }

  rows.forEach((node, index) => {
    if (isMergedRowEveOnly(node)) return;
    const nodeId = chooseMergedId(node, index);
    rawNodeById.set(nodeId, node);
    const rloc16Text = toText(node.rloc16).toLowerCase();
    const modeDevice = toText(node['mode.device'] || node.mode?.device).toUpperCase();
    const isRouterLike = rloc16Text.endsWith('00') || modeDevice === 'FTD' || toText(node.role).toLowerCase() === 'router';
    const isChildLike = modeDevice === 'MTD' || toText(node.role).toLowerCase().includes('child');
    upsertMergedNode(nodeId, node, {
      source: 'merged-detailed',
      shape: isChildLike && !isRouterLike ? NODE_SHAPES.child : NODE_SHAPES.router,
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
    const routeCategories = getOtbrRouteCategories(node);
    ['3_links', '2_links', '1_links'].forEach((key) => {
      const lqStyle = lqStyleFromField(key);
      (Array.isArray(node[key]) ? node[key] : []).forEach((link) => {
        const toId = ensureNodeForLink(link, link.rloc16 || link.id);
        if (!toId) return;
        const toNodeEnriched = nodeMap.get(toId);
        addEdge(edgeMap, edgeData, fromId, toId, {
          ...lqStyle,
          ...buildEdgeEndpointTitles(node, toNodeEnriched, fromId, toId),
          linkCategories: [key === '3_links' ? EDGE_CATEGORY_DEFAULT_3 : key === '2_links' ? EDGE_CATEGORY_DEFAULT_2 : EDGE_CATEGORY_DEFAULT_1],
          edgeKeySuffix: `merged-${key}`
        });
      });
    });
    (Array.isArray(node.router_neighbor_table) ? node.router_neighbor_table : []).forEach((neighbor) => {
      const toId = ensureNodeForLink(neighbor, neighbor.rloc16 || neighbor.extAddress || neighbor.id);
      if (!toId) return;
      const linkMargin = toFiniteNumber(neighbor.rss_margin ?? neighbor.linkMargin);
      const lqStyle = Number.isFinite(linkMargin) ? lqStyleFromLinkMargin(linkMargin) : {};
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        width: 1.5,
        ...lqStyle,
        linkMargin,
        ...buildEdgeEndpointTitles(node, toNodeEnriched, fromId, toId),
        linkCategories: [EDGE_CATEGORY_ROUTER_NEIGHBOR],
        edgeKeySuffix: 'merged-router-neighbor'
      });
    });
    (Array.isArray(node.route?.routeData) ? node.route.routeData : []).forEach((route) => {
      if (routeCategories.length === 0) return;
      const toRloc16 = buildMainRouterRloc16(route.routeId);
      const toId = ensureNodeForLink({ rloc16: toRloc16, id: toRloc16, device_label: toRloc16 }, toRloc16);
      if (!toId) return;
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        width: 1.5,
        ...buildEdgeEndpointTitles(node, toNodeEnriched, fromId, toId),
        linkCategories: routeCategories,
        edgeKeySuffix: 'merged-otbr-route'
      });
    });
    (Array.isArray(node.childTable) ? node.childTable : []).forEach((child, ci) => {
      const childRloc16 = buildChildRloc16(node.rloc16, child.childId);
      const childId = ensureNodeForLink(
        { rloc16: childRloc16, id: childRloc16 || `${fromId}-rest-child-${ci + 1}`, device_label: childRloc16 || `${fromId} child ${child.childId}` },
        childRloc16 || `${fromId}-rest-child-${ci + 1}`
      );
      if (!childId) return;
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...buildEdgeEndpointTitles(node, childNodeEnriched, fromId, childId),
        linkCategories: [EDGE_CATEGORY_OTBR_CHILD],
        edgeKeySuffix: 'merged-otbr-child'
      });
      routerIdsWithChildren.add(fromId);
    });
    (Array.isArray(node.children) ? node.children : []).forEach((child, ci) => {
      const childNode = typeof child === 'string' ? { id: child } : (child || {});
      if (typeof child === 'string') return; // skip eve-only string children
      if (!toText(childNode.rloc16) && !toText(childNode.extaddr)) return; // skip object refs without Thread identity
      const childId = ensureNodeForLink(childNode, `${fromId}-child-${ci + 1}`);
      if (!childId) return;
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...buildEdgeEndpointTitles(node, childNodeEnriched, fromId, childId),
        linkCategories: [EDGE_CATEGORY_DEFAULT_CHILDREN],
        edgeKeySuffix: 'merged-default-child'
      });
      routerIdsWithChildren.add(fromId);
    });
    (Array.isArray(node.router_child_table) ? node.router_child_table : []).forEach((child, ci) => {
      const childId = toText(child.rloc16) || `${fromId}-rct-child-${ci + 1}`;
      const linkMargin = toFiniteNumber(child.rss_margin);
      const lqStyle = Number.isFinite(linkMargin) ? lqStyleFromLinkMargin(linkMargin) : {};
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
        shape: isChildLikeNode && !isRouterLikeNode ? NODE_SHAPES.child : NODE_SHAPES.router,
        color: isChildLikeNode && !isRouterLikeNode ? NODE_COLORS.child : NODE_COLORS.eve
      });
      if (!rawNodeById.has(childId)) rawNodeById.set(childId, child);
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false, isParentChild: true,
        ...lqStyle,
        linkMargin,
        ...buildEdgeEndpointTitles(node, childNodeEnriched, fromId, childId),
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
      shape: NODE_SHAPES.router,
      color: isBr ? NODE_COLORS.borderRouter : NODE_COLORS.router
    });
    rawByIdForDetails.set(nodeId, row);
  });

  // Build edges: row.rloc16 → rloc16 of Next Hop router ID
  rows.forEach((row) => {
    const fromId = toText(row.rloc16);
    if (!fromId) return;

    // "Next Hop" is a router ID integer → convert to rloc16
    const nextHopId = toFiniteNumber(row['nextHop']);
    if (Number.isFinite(nextHopId)) {
      const toRloc16 = buildMainRouterRloc16(nextHopId);
      const toRow = byRloc16.get(toRloc16.toLowerCase());
      if (toRow && toRloc16 && toRloc16 !== fromId) {
        const lqOut = toFiniteNumber(row['linkQualityOut']);
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
      role: toText(row.role).trim().toLowerCase(),
      mode_device: toText(row.mode?.device) || (row.type === 'router' ? 'FTD' : (isChildLike ? 'MTD' : '')),
      ifindiscards_pct: row.mac_counters?.ifindiscards_pct,
      iftotalerrors_pct: row.mac_counters?.iftotalerrors_pct,
      iftotalerrors_totalpkts_ratio: row.mac_counters?.iftotalerrors_totalpkts_ratio,
      iftotaldiscards_totalpkts_ratio: row.mac_counters?.iftotaldiscards_totalpkts_ratio,
      partitionidchanges: row.mle_counters?.partitionidchanges,
      parentchanges: row.mle_counters?.parentchanges,
      br: row.br === true,
      shape: isChildLike ? NODE_SHAPES.child : NODE_SHAPES.router,
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
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...buildEdgeEndpointTitles(row, childNodeEnriched, fromId, childId),
        linkCategories: [EDGE_CATEGORY_DEFAULT_CHILDREN]
      });
      routerIdsWithChildren.add(fromId);
    });
    // routes[] → solid edges
    (Array.isArray(row.routes) ? row.routes : []).forEach((route) => {
      const toId = toText(route.to);
      if (!toId || !nodeMap.has(toId)) return;
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        ...buildEdgeEndpointTitles(row, toNodeEnriched, fromId, toId),
        linkCategories: [EDGE_CATEGORY_EVE_ROUTE]
      });
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
  
  // Load both basic diagnostics AND mesh diagnostics (which has link quality data)
  // Prioritize mesh-diagnostics-fetch-all over diagnostics-fetch-all when both are present
  const diagRaw = fileMap.get(FILE_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_LIST) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_FETCH) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_FETCH_ALL);
  
  // If we have BOTH mesh-diagnostics AND regular diagnostics, load the basic one too for additional fields
  const basicDiagRaw = fileMap.has(FILE_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL) 
    ? (fileMap.get(FILE_RESTAPI_DIAGNOSTICS) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_LIST) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_FETCH) ?? fileMap.get(FILE_RESTAPI_DIAGNOSTICS_FETCH_ALL))
    : null;
  
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
  const basicDiagData = extractItems(basicDiagRaw);

  // Flatten each item: merge top-level fields + attributes sub-object
  function flattenRestApiItem(item) {
    if (!isPlainObject(item)) return item;
    const attrs = isPlainObject(item.attributes) ? item.attributes : {};
    return { ...item, ...attrs };
  }

  const devices = devicesData.map(flattenRestApiItem);
  const diagnostics = diagData.map(flattenRestApiItem);
  const basicDiagnostics = basicDiagData.map(flattenRestApiItem);
  
  // Merge basic diagnostics with mesh diagnostics (mesh diagnostics take precedence)
  // If we have both, combine them by extAddress so we get both basic fields AND link quality data
  if (basicDiagnostics.length > 0) {
    const basicByExtaddr = new Map();
    basicDiagnostics.forEach(item => {
      const extaddr = toText(item.extAddress).toLowerCase();
      if (extaddr) basicByExtaddr.set(extaddr, item);
    });
    
    // Merge basic data into diagnostics for matching extAddresses
    diagnostics.forEach((item, index) => {
      const extaddr = toText(item.extAddress).toLowerCase();
      const basic = basicByExtaddr.get(extaddr);
      if (basic) {
        // Merge basic fields into item (mesh fields take precedence)
        diagnostics[index] = { ...basic, ...item };
      }
    });
  }

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
      omrIpv6Addr: toText(rawNode.omr_ipv6_addr) || (existing ? existing.omrIpv6Addr || existing.omr_ipv6_addr : ''),
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
      fromOtbrRestapi: true,
      shape: style.shape || (existing ? existing.shape : (isChildLike ? NODE_SHAPES.child : NODE_SHAPES.router)),
      color: style.color || (existing ? existing.color : NODE_COLORS.router)
    };
    merged.isFtdRouter = merged.modeDevice === 'FTD' && merged.rloc16.toLowerCase().endsWith('00');
    if (merged.br) merged.color = NODE_COLORS.borderRouter;
    nodeMap.set(nodeId, normalizeFieldNames(merged));
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
  if (diagnostics.length > 0) sourceNames.push('otbr_restapi_diagnostics');

  return { nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, routerChildByRloc16, sourceNames };
}

// ── Dispatch: pick adaptor based on topologyMode ──────────────────────────────

export function runAdaptor(dataset) {
  const { entry, rawFiles, rows } = dataset;
  const fileMap = buildFileMap(entry.files || [], rawFiles);
  switch (entry.topologyMode) {
    case 'meshdiag-networkdiag': return adaptMeshdiagNetworkdiag(fileMap, rows);
    case 'merged-detailed': return adaptMergedDetailed(fileMap);
    case 'eve_enhanced': return adaptEve(fileMap);
    case 'eve_native': return adaptEveNative(fileMap);
    case 'thread_tools_native': return adaptThreadToolsNative(fileMap);
    case 'router-table': return adaptRouterTable(fileMap);
    case 'otbr_restapi': return adaptOtbrRestApi(fileMap);
    case 'raw-array':
    default: return adaptRawArray(fileMap);
  }
}
