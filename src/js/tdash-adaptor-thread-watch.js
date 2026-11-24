import {
  createAdaptorModel,
  emitAdaptorResult,
  registerDetails,
  registerDevice,
  registerRelationship,
  registerRelationshipCapability,
} from "./tdash-adaptor-model.js";
import {
  EDGE_CATEGORY_DEFAULT_CHILDREN,
  EDGE_LQ_STYLES,
  NODE_COLORS,
  NODE_SHAPES,
} from "./tdash-constants.js";
import {
  buildNodeLabelFont,
  buildRoleNodeEmphasis,
} from "./tdash-topology-utils.js";
import { toText } from "./tdash-utils.js";


function parentRloc16(childRloc16) {
  const text = toText(childRloc16).toLowerCase();
  if (!/^0x[0-9a-f]{4}$/.test(text)) return "";
  const value = Number.parseInt(text.slice(2), 16);
  return Number.isInteger(value) && (value & 0x03ff) !== 0
    ? `0x${(value & 0xfc00).toString(16).padStart(4, "0")}`
    : "";
}


export function adaptThreadWatch(_fileMap, rows = []) {
  const model = createAdaptorModel(["thread-watch"]);
  const routers = new Map();
  const hasPublishedChildren = rows.some((row) => Array.isArray(row?.children));
  const rowIds = rows.map((row, index) => toText(row?._threadWatchRowId) || `tw:standalone:${index}`);
  rows.forEach((row, index) => {
    const rowId = rowIds[index];
    const role = toText(row?.role).toLowerCase();
    const isRouter = row?.isRouter === true || row?.isBorderRouter === true;
    const isChild = role === "child";
    const isBorderRouter = row?.isBorderRouter === true;
    const themeRole = isBorderRouter
      ? "borderRouter"
      : isRouter
        ? "router"
        : isChild
          ? "child"
          : "unknown";
    registerDevice(model, row, {
      id: rowId,
      preserveId: true,
      sourceName: "thread-watch",
      nodeRecord: row,
      presentation: {
        label: row?.deviceLabel || row?.name || row?.extAddress || rowId,
        shape: isBorderRouter
          ? NODE_SHAPES.borderRouter
          : isRouter
            ? NODE_SHAPES.router
            : isChild
              ? NODE_SHAPES.child
              : NODE_SHAPES.unknown,
        color: isBorderRouter
          ? NODE_COLORS.borderRouter
          : isRouter
            ? NODE_COLORS.router
            : isChild
              ? NODE_COLORS.child
              : NODE_COLORS.unknown,
        themeRole,
        font: buildNodeLabelFont({
          fontSize: isRouter ? 19.5 : 13,
          isRouter,
        }),
        ...buildRoleNodeEmphasis({ isBorderRouter, isRouter }),
        isRouter: row?.isRouter === true,
        isBorderRouter,
        isLeader: row?.isLeader === true,
        role: row?.role ?? null,
        threadWatchRoleUnknown: !isRouter && !isChild,
        _threadWatchRowId: rowId,
      },
    });
    registerDetails(model, rowId, row, "replace");
    if (!hasPublishedChildren && row?.role === "router" && row?.isRouter === true) {
      const extAddress = toText(row.extAddress).toLowerCase();
      const rloc16 = toText(row.rloc16).toLowerCase();
      if (!/^[0-9a-f]{16}$/.test(extAddress) || !/^0x[0-9a-f]{4}$/.test(rloc16)) return;
      const matches = routers.get(extAddress) ?? [];
      matches.push(rowId);
      routers.set(extAddress, matches);
    }
  });
  const addChildEdge = (parentId, index) => {
    registerRelationshipCapability(model, "children", parentId);
    registerRelationship(model, {
      sourceId: parentId,
      targetId: rowIds[index],
      category: EDGE_CATEGORY_DEFAULT_CHILDREN,
      directed: true,
      presentation: {
        ...EDGE_LQ_STYLES.parentChild,
        isParentChild: true,
        linkCategories: [EDGE_CATEGORY_DEFAULT_CHILDREN],
      },
      sourceName: "thread-watch",
      rawRecord: rows[index],
    });
    model.devicesById.get(parentId).presentation.hasChildren = true;
  };
  if (hasPublishedChildren) {
    const childKey = (parentAddress, child) => JSON.stringify(
      [parentAddress, child.rloc16, child.extAddress].map((value) => toText(value).toLowerCase()),
    );
    const childrenByKey = new Map();
    // Reverse the indexes so identical published children consume rows in source order.
    for (let index = rows.length - 1; index >= 0; index--) {
      const row = rows[index];
      if (row?.role !== "child" || !row.parentExtAddress) continue;
      const key = childKey(row.parentExtAddress, row);
      if (!childrenByKey.has(key)) childrenByKey.set(key, []);
      childrenByKey.get(key).push(index);
    }
    rows.forEach((row, index) => {
      if (row?.role !== "router" || !row.extAddress || !Array.isArray(row.children)) return;
      for (const child of row.children) {
        if (!child?.rloc16) continue;
        const childIndex = childrenByKey.get(childKey(row.extAddress, child))?.pop();
        if (childIndex !== undefined) addChildEdge(rowIds[index], childIndex);
      }
    });
  } else {
    // Older verified snapshots predate the published children projection.
    rows.forEach((row, index) => {
      if (row?.role !== "child" || !row.parentExtAddress) return;
      const parentRloc = parentRloc16(row.rloc16);
      const parentIds = routers.get(toText(row.parentExtAddress).toLowerCase());
      if (!parentRloc || parentIds?.length !== 1) return;
      const parentId = parentIds[0];
      const parent = model.devicesById.get(parentId);
      if (toText(parent.record.rloc16).toLowerCase() === parentRloc) addChildEdge(parentId, index);
    });
  }
  return emitAdaptorResult(model);
}
