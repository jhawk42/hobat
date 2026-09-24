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

const FILE_MESHDIAG              = 'td-otbr-cli-meshdiag-topology.json';

const FILE_NETWORKDIAG_FETCH_ALL      = 'td-otbr-cli-networkdiag-fetch-all.json';

const FILE_NETWORKDIAG_MULTICAST = 'td-otbr-cli-networkdiag-multicast-network.json';

const FILE_ROUTER_NEIGHBORTABLES = 'td-otbr-cli-meshdiag-router-neighbortables.json';

const FILE_ROUTER_CHILDTABLES    = 'td-otbr-cli-meshdiag-router-childtables.json';

const FILE_RESTAPI_DIAGNOSTICS   = 'td-otbr-restapi-diagnostics.json';

const FILE_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL = 'td-otbr-restapi-mesh-diagnostics-fetch-all.json';

const MESHDIAG_PRIMARY_FILES = new Set([
  FILE_MESHDIAG, FILE_NETWORKDIAG_FETCH_ALL, FILE_NETWORKDIAG_MULTICAST,
  FILE_ROUTER_NEIGHBORTABLES, FILE_ROUTER_CHILDTABLES,
  FILE_RESTAPI_DIAGNOSTICS,
]);

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
    if (omr && !isPlaceholderOmrAddress(omr)) nodeIdByOmr.set(omr, nodeId);
  });

  mergedRows.forEach((row) => {
    if (!isPlainObject(row)) return;
    const rloc16 = getCanonicalRloc16(row);
    const extaddr = getCanonicalExtaddr(row);
    const omr = getCanonicalOmrIpv6Address(row);
    const nodeId =
      (extaddr && nodeIdByExtaddr.get(extaddr))
      || (omr && !isPlaceholderOmrAddress(omr) && nodeIdByOmr.get(omr))
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
      isLeader: rawNode.isLeader === true || (existing ? existing.isLeader === true : false),
      isPrimaryBBR: rawNode.isPrimaryBBR === true || (existing ? existing.isPrimaryBBR === true : false),
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

  function addOtbrRouteDataEdges(node, fromId, source) {
    const routeData = Array.isArray(node.route?.routeData) ? node.route.routeData : [];
    const routeCategories = getOtbrRouteCategories(node);
    if (routeCategories.length === 0) return routeData.length > 0;

    routeData.forEach((route) => {
      const toRloc16 = toText(route.rloc16);
      if (!toRloc16) return;
      const toId = ensureNode(
        toRloc16,
        { rloc16: toRloc16, id: toRloc16, device_label: toRloc16 },
        { source, shape: NODE_SHAPES.router, color: NODE_COLORS.router }
      );
      const lqIn = toFiniteNumber(route.linkQualityIn) || 0;
      const lqOut = toFiniteNumber(route.linkQualityOut) || 0;
      const lqStyle = lqStyleFromAvgLqi(Math.max(lqIn, lqOut), 3);
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        ...lqStyle,
        ...buildEdgeEndpointTitles(node, toNodeEnriched, fromId, toId),
        linkCategories: routeCategories,
      });
    });
    return routeData.length > 0;
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

    const hasRouteData = addOtbrRouteDataEdges(node, fromId, 'meshdiag');
    if (!hasRouteData) [
      ['links3', '3_links', EDGE_CATEGORY_DEFAULT_3],
      ['links2', '2_links', EDGE_CATEGORY_DEFAULT_2],
      ['links1', '1_links', EDGE_CATEGORY_DEFAULT_1],
    ].forEach(([field, legacyField, category]) => {
      const links = Array.isArray(node[field])
        ? node[field]
        : (Array.isArray(node[legacyField]) ? node[legacyField] : []);
      const lqStyle = lqStyleFromField(legacyField);
      links.forEach((link) => {
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
          linkCategories: [category]
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
    addOtbrRouteDataEdges(node, fromId, 'networkdiagnostic');
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
    if (omr && !isPlaceholderOmrAddress(omr)) omrToNodeId.set(omr, id);
    const ea = getCanonicalExtaddr(raw);
    if (ea) extaddrToNodeId.set(ea, id);
  });
  nodeMap.forEach((node, id) => {
    const omr = getCanonicalOmrIpv6Address(node);
    if (omr && !isPlaceholderOmrAddress(omr) && !omrToNodeId.has(omr)) omrToNodeId.set(omr, id);
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
      const nodeId = (omr && !isPlaceholderOmrAddress(omr) && omrToNodeId.get(omr))
        || (ea && extaddrToNodeId.get(ea));
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

  return emitThroughAdaptorModel({ nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, routerChildByRloc16, sourceNames });
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

  return emitThroughAdaptorModel({ nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, sourceNames: ['router-table'] });
}

// ── Adaptor 5: Raw array generic fallback ─────────────────────────────────────
