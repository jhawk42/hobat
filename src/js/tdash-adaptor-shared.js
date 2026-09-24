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


export function asArray(value) { return Array.isArray(value) ? value : []; }

export function emitThroughAdaptorModel(result) {
  return emitAdaptorResult(createAdaptorModelFromResult(result));
}

/**
 * Build a Map<filename, loadedData> from the registry entry's files list and
 * the parallel array of loaded file contents.
 */

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

export function buildEdgeEndpointTitles(fromNodeLike, toNodeLike, fromFallbackId = '', toFallbackId = '') {
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

export function getOtbrRouteCategories(sourceNode) {
  const category = getOtbrRouteCategory(sourceNode);
  return category ? [EDGE_CATEGORY_OTBR_ROUTE, category] : [];
}
