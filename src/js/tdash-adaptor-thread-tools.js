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
  const childByMacAddr = new Map();

  function normalizeThreadToolsChild(child) {
    if (!isPlainObject(child) || typeof child.isDeviceTypeMtd !== 'boolean') return child;
    // Thread Tools exports FTD status under the misnamed isDeviceTypeMtd field.
    return { ...child, isDeviceTypeFtd: child.isDeviceTypeMtd };
  }

  diagnostics.forEach((node) => {
    (Array.isArray(node?.children) ? node.children : []).forEach((child) => {
      const normalizedChild = normalizeThreadToolsChild(child);
      const childMacAddr = toFiniteNumber(normalizedChild?.macAddr);
      if (Number.isFinite(childMacAddr)) childByMacAddr.set(childMacAddr, normalizedChild);
    });
  });

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
    const isMainRouter = rloc16Val.toLowerCase().endsWith('00');
    const inferredType = isMainRouter ? 'router' : (typeof modeFtd === 'boolean' ? 'child' : '');
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

    nodeMap.set(nodeId, merged);
    if (merged.rloc16) rloc16ToNodeId.set(merged.rloc16.toLowerCase(), nodeId);
  }

  diagnostics.forEach((node, index) => {
    if (!isPlainObject(node)) return;
    const childRecord = childByMacAddr.get(toFiniteNumber(node.macAddr));
    const effectiveNode = node.isSynthesized === true && typeof childRecord?.isDeviceTypeFtd === 'boolean'
      ? { ...node, mode: { ...node.mode, ftd: childRecord.isDeviceTypeFtd } }
      : node;
    const nodeId = chooseThreadToolsNodeId(effectiveNode, index);
    const modeFtd = effectiveNode.mode?.ftd;
    const isChildLike = modeFtd === false;
    upsertThreadToolsNode(nodeId, effectiveNode, {
      shape: isChildLike ? NODE_SHAPES.child : NODE_SHAPES.router,
      color: isChildLike ? NODE_COLORS.child : NODE_COLORS.router,
    });

    const existing = rawByIdForDetails.get(nodeId) || {};
    rawByIdForDetails.set(nodeId, mergeForDisplay(existing, effectiveNode));
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
      const childObj = normalizeThreadToolsChild(child) || {};
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
          mode: { ...childObj.mode, ftd: childObj.isDeviceTypeFtd },
          type: childObj.isDeviceTypeFtd === false ? 'child' : '',
        }, { shape: NODE_SHAPES.child, color: NODE_COLORS.child });
      } else if (childExtaddr || childRloc16) {
        upsertThreadToolsNode(childId, {
          id: childId,
          rloc16: childRloc16,
          extAddress: childExtaddr,
          mode: { ...childObj.mode, ftd: childObj.isDeviceTypeFtd },
          type: childObj.isDeviceTypeFtd === false ? 'child' : '',
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

  return emitThroughAdaptorModel({
    nodeData,
    edgeData,
    nodeMap,
    rawByIdForDetails,
    routerNeighborByRloc16,
    routerChildByRloc16,
    sourceNames: ['thread_tools_native'],
  });
}
