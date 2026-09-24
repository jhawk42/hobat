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
      deviceLabel: toText(rawNode.deviceLabel) || toText(rawNode.device_label)
        || (existing ? existing.deviceLabel || existing.device_label : ''),
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
    nodeMap.set(nodeId, merged);
  }

  function ensureNodeForLink(linkNode, fallbackId) {
    const candidateId = toText(linkNode.rloc16) || toText(linkNode.id) || toText(fallbackId);
    if (!candidateId) return '';
    if (!nodeMap.has(candidateId)) {
      upsertMergedNode(candidateId, {
        ...linkNode,
        rloc16: toText(linkNode.rloc16),
        id: toText(linkNode.id) || candidateId,
        extaddr: getCanonicalExtaddr(linkNode),
        device_label: toText(linkNode.device_label) || toText(linkNode.deviceLabel),
        name: toText(linkNode.name),
      }, { source: 'merged-detailed', shape: NODE_SHAPES.router, color: NODE_COLORS.eve });
    }
    return candidateId;
  }

  rows.forEach((node, index) => {
    if (isMergedRowEveOnly(node)) return;
    const nodeId = chooseMergedId(node, index);
    rawNodeById.set(nodeId, node);
    const rloc16Text = toText(node.rloc16).toLowerCase();
    const routerNeighbors = Array.isArray(node.routerNeighbors)
      ? node.routerNeighbors
      : (Array.isArray(node.router_neighbor_table) ? node.router_neighbor_table : []);
    const childTable = Array.isArray(node.childTable)
      ? node.childTable
      : (Array.isArray(node.router_child_table) ? node.router_child_table : []);
    const modeDevice = toText(node['mode.device'] || node.mode?.device).toUpperCase();
    const isRouterLike = rloc16Text.endsWith('00') || modeDevice === 'FTD' || toText(node.role).toLowerCase() === 'router';
    const isChildLike = modeDevice === 'MTD' || toText(node.role).toLowerCase().includes('child');
    upsertMergedNode(nodeId, node, {
      source: 'merged-detailed',
      shape: isChildLike && !isRouterLike ? NODE_SHAPES.child : NODE_SHAPES.router,
      color: isChildLike && !isRouterLike ? NODE_COLORS.child : NODE_COLORS.eve
    });
    // populate routerNeighborByRloc16 for filter support
    if (routerNeighbors.length > 0 && rloc16Text) {
      routerNeighborByRloc16.set(rloc16Text, node);
    }
    // populate routerChildByRloc16 for filter support
    const rloc16ForChild = toText(node.parentRloc16 || node.parent_rloc16 || node.rloc16).toLowerCase();
    if (childTable.length > 0 && rloc16ForChild) {
      routerChildByRloc16.set(rloc16ForChild, node);
    }
  });

  rows.forEach((node, index) => {
    if (isMergedRowEveOnly(node)) return;
    const fromId = chooseMergedId(node, index);
    const routeCategories = getOtbrRouteCategories(node);
    [
      { canonical: 'links3', legacy: '3_links' },
      { canonical: 'links2', legacy: '2_links' },
      { canonical: 'links1', legacy: '1_links' },
    ].forEach(({ canonical, legacy }) => {
      const lqStyle = lqStyleFromField(legacy);
      const links = Array.isArray(node[canonical]) ? node[canonical] : node[legacy];
      (Array.isArray(links) ? links : []).forEach((link) => {
        const toId = ensureNodeForLink(link, link.rloc16 || link.id);
        if (!toId) return;
        const toNodeEnriched = nodeMap.get(toId);
        addEdge(edgeMap, edgeData, fromId, toId, {
          ...lqStyle,
          ...buildEdgeEndpointTitles(node, toNodeEnriched, fromId, toId),
          linkCategories: [legacy === '3_links' ? EDGE_CATEGORY_DEFAULT_3 : legacy === '2_links' ? EDGE_CATEGORY_DEFAULT_2 : EDGE_CATEGORY_DEFAULT_1],
          edgeKeySuffix: `merged-${legacy}`
        });
      });
    });
    const routerNeighbors = Array.isArray(node.routerNeighbors)
      ? node.routerNeighbors
      : (Array.isArray(node.router_neighbor_table) ? node.router_neighbor_table : []);
    routerNeighbors.forEach((neighbor) => {
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
      const lqiIn = toFiniteNumber(route.linkQualityIn ?? route.inLinkQuality);
      const lqiOut = toFiniteNumber(route.linkQualityOut ?? route.outLinkQuality);
      const lqi = Math.max(lqiOut || 0, lqiIn || 0);
      const lqStyle = lqStyleFromAvgLqi(lqi, 3);
      const toNodeEnriched = nodeMap.get(toId);
      addEdge(edgeMap, edgeData, fromId, toId, {
        ...lqStyle,
        lqiIn,
        lqiOut,
        routeCost: toFiniteNumber(route.routeCost),
        ...buildEdgeEndpointTitles(node, toNodeEnriched, fromId, toId),
        linkCategories: routeCategories,
        edgeKeySuffix: 'merged-otbr-route'
      });
    });
    (Array.isArray(node.childTable) ? node.childTable : []).forEach((child, ci) => {
      const childRloc16 = toText(child.rloc16) || buildChildRloc16(node.rloc16, child.childId);
      const childExtaddr = getCanonicalExtaddr(child);
      const childFallbackId = `${fromId}-rest-child-${ci + 1}`;
      const childLabel = toText(child.device_label) || toText(child.deviceLabel);
      const childRecord = {
        ...child,
        rloc16: childRloc16,
        extaddr: childExtaddr,
        id: toText(child.id) || childRloc16 || childExtaddr || childFallbackId,
        device_label: childLabel
          || (!childRloc16 && child.childId !== undefined ? `${fromId} child ${child.childId}` : ''),
      };
      const childId = ensureNodeForLink(
        childRecord,
        childRloc16 || childExtaddr || childFallbackId
      );
      if (!childId) return;
      upsertMergedNode(childId, childRecord, {
        source: 'merged-detailed',
        shape: NODE_SHAPES.child,
        color: NODE_COLORS.child,
      });
      const childLq = toFiniteNumber(child.linkQuality ?? child.incomingLinkQuality ?? child.lq);
      const linkMargin = toFiniteNumber(child.rss_margin ?? child.linkMargin);
      const lqStyle = Number.isFinite(childLq)
        ? lqStyleFromAvgLqi(childLq, 3)
        : (Number.isFinite(linkMargin) ? lqStyleFromLinkMargin(linkMargin) : {});
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...lqStyle,
        linkMargin,
        averageRssi: toFiniteNumber(child.rss_ave ?? child.averageRssi),
        lastRssi: toFiniteNumber(child.rss_last ?? child.lastRssi),
        frameErrorRate: toFiniteNumber(child.err_rate_frame_pct ?? child.frameErrorRate),
        messageErrorRate: toFiniteNumber(child.err_rate_msg_pct ?? child.messageErrorRate),
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
      const childLq = toFiniteNumber(childNode.linkQuality ?? childNode.incomingLinkQuality ?? childNode.lq);
      const linkMargin = toFiniteNumber(childNode.rss_margin ?? childNode.linkMargin);
      const lqStyle = Number.isFinite(linkMargin)
        ? lqStyleFromLinkMargin(linkMargin)
        : (Number.isFinite(childLq) ? lqStyleFromAvgLqi(childLq, 3) : {});
      const childNodeEnriched = nodeMap.get(childId);
      addEdge(edgeMap, edgeData, fromId, childId, {
        dashes: false,
        isParentChild: true,
        ...lqStyle,
        linkMargin,
        averageRssi: toFiniteNumber(childNode.rss_ave ?? childNode.averageRssi),
        lastRssi: toFiniteNumber(childNode.rss_last ?? childNode.lastRssi),
        frameErrorRate: toFiniteNumber(childNode.err_rate_frame_pct ?? childNode.frameErrorRate),
        messageErrorRate: toFiniteNumber(childNode.err_rate_msg_pct ?? childNode.messageErrorRate),
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

  return emitThroughAdaptorModel({ nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, routerChildByRloc16, sourceNames: ['merged-detailed'] });
}


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

  return emitThroughAdaptorModel({ nodeData, edgeData, nodeMap, rawByIdForDetails, routerNeighborByRloc16, sourceNames: ['raw-array'] });
}
