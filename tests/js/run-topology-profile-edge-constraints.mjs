import assert from "node:assert/strict";
import { applyProfileEdgeConstraints } from "../../src/js/tdash-topology-renderer.js";

const nodes = [
  { id: "br", isRouter: true, isBorderRouter: true },
  { id: "br2", isRouter: true, isBorderRouter: true },
  { id: "r", isRouter: true },
  { id: "r2", isRouter: true },
  { id: "ftd", mode_device: "ftd" },
  { id: "mtd", mode_device: "MTD" },
  { id: "ftd2", mode_device: "FTD" },
  { id: "unknown" },
  { id: "unknown2" },
];
const secondary = ["otbr_route", "otbr_route_router"];
const makeEdge = (id, from, to, extras = {}) => ({
  id, from, to, length: 12, physics: true,
  smooth: { enabled: true, type: "curvedCCW", roundness: 0.26 },
  color: "#abcdef", width: 2, dashes: false, linkCategories: [],
  ...extras,
});
const edges = [
  makeEdge("parent-ftd", "br", "ftd", { isParentChild: true, physics: false }),
  makeEdge("parent-mtd-reversed", "mtd", "r", { isParentChild: true, physics: false }),
  makeEdge("parent-ftd2", "r", "ftd2", { isParentChild: true }),
  makeEdge("secondary", "r", "ftd", { linkCategories: secondary }),
  makeEdge("secondary-object", "ftd", "r", {
    linkCategories: secondary, color: { color: "#123456", opacity: 0.9 }, width: 0.2,
  }),
  makeEdge("secondary-zero", "br", "mtd", { linkCategories: secondary, width: 0 }),
  makeEdge("secondary-string", "br", "mtd", { linkCategories: secondary, width: "0.3" }),
  makeEdge("neighbor-route", "r", "ftd", { linkCategories: [...secondary, "router_neighbor"] }),
  makeEdge("ftd-route", "r", "ftd", { linkCategories: [...secondary, "otbr_route_ftd_child"] }),
  makeEdge("bare-route", "r", "ftd", { linkCategories: ["otbr_route"] }),
  makeEdge("router-child", "br", "unknown"),
  makeEdge("missing-child", "r", "missing"),
  makeEdge("router-router", "r", "r2"),
  makeEdge("border-router", "br", "r"),
  makeEdge("both-border", "br", "br2"),
  makeEdge("router-secondary", "r", "r2", { linkCategories: secondary }),
  makeEdge("cross-zone", "ftd", "ftd2"),
  makeEdge("same-zone", "unknown", "unknown2"),
  makeEdge("missing-both", "missing", "absent"),
  makeEdge("non-router-parent", "ftd2", "mtd", { isParentChild: true }),
  makeEdge("router-parent", "r", "r2", { isParentChild: true }),
  makeEdge("hidden-parent", "br", "mtd", { isParentChild: true, baseHidden: true }),
  makeEdge("hidden-secondary", "r", "ftd", { linkCategories: secondary, baseHidden: true }),
  makeEdge("hidden-router", "br", "br2", { baseHidden: true }),
  makeEdge("not-strictly-hidden", "br", "br2", { baseHidden: 1 }),
];
const profiles = [
  "mesh-compact", "mesh-ring", "mesh-tree-horizontal", "mesh-tree-vertical",
  "mesh-balanced", "mesh-baseline", "unknown-profile",
];
const curve = (edge, tree) => ({
  enabled: true,
  type: `${edge.from}|${edge.to}`.length % 2 === 0 ? "curvedCW" : "curvedCCW",
  roundness: tree ? 0.34 : 0.3,
});
const faded = (edge) => ({
  color: { color: typeof edge.color === "string" ? edge.color : undefined, opacity: 0.16 },
  width: Math.min(Number(edge.width) || 1.5, 0.45),
  dashes: [2, 8],
});
let exactEdgeComparisons = 0;
for (const profile of profiles) {
  const tree = profile.startsWith("mesh-tree-");
  const hub = profile === "mesh-balanced";
  const compact = profile === "mesh-compact";
  const ring = profile === "mesh-ring";
  const expected = structuredClone(edges);
  const update = (id, changes) => Object.assign(expected.find((edge) => edge.id === id), changes);
  if (tree || compact || ring || hub) {
    const ftdLength = tree ? 170 : compact ? 280 : ring ? 200 : 300;
    const mtdLength = tree ? 250 : compact ? 450 : ring ? 430 : 460;
    for (const id of ["parent-ftd", "parent-ftd2", "parent-mtd-reversed"]) {
      const edge = expected.find((item) => item.id === id);
      update(id, {
        length: id === "parent-mtd-reversed" ? mtdLength : ftdLength,
        physics: true,
        ...(hub ? {} : { smooth: curve(edge, tree) }),
      });
    }
    for (const id of ["secondary", "secondary-object", "secondary-zero", "secondary-string"]) {
      const edge = expected.find((item) => item.id === id);
      update(id, {
        ...(ring || hub ? faded(edge) : {}),
        ...(hub || compact || tree ? { physics: false } : {}),
      });
    }
    if (hub || compact || tree) {
      for (const id of ["neighbor-route", "ftd-route", "bare-route", "router-child", "missing-child"]) {
        update(id, { physics: false });
      }
    }
    const routerLength = hub ? 680 : tree ? 620 : 430;
    for (const id of ["router-router", "router-secondary"]) update(id, { length: routerLength });
    update("border-router", { length: hub ? 1097 : routerLength });
    for (const id of ["both-border", "not-strictly-hidden"]) {
      update(id, { length: hub ? 1345 : routerLength });
    }
    if (tree) update("cross-zone", { length: 520 });
    if (hub) {
      update("router-parent", { length: 680 });
    } else {
      for (const id of ["non-router-parent", "router-parent"]) {
        const edge = expected.find((item) => item.id === id);
        update(id, { length: id === "non-router-parent" ? ftdLength : mtdLength, physics: true, smooth: curve(edge, tree) });
      }
    }
  }
  const actualNodes = structuredClone(nodes);
  const actualEdges = structuredClone(edges);
  const nodeRefs = [...actualNodes];
  const edgeRefs = [...actualEdges];
  assert.equal(applyProfileEdgeConstraints(actualNodes, actualEdges, profile), undefined);
  assert.deepEqual(actualNodes, nodes, `${profile}: nodes are untouched`);
  assert.deepEqual(actualEdges, expected, `${profile}: exact ordered edge output`);
  actualNodes.forEach((node, index) => assert.equal(node, nodeRefs[index]));
  actualEdges.forEach((edge, index) => assert.equal(edge, edgeRefs[index]));
  exactEdgeComparisons += actualEdges.length;
}

let lengthComparisons = 0;
const lengths = [undefined, null, "9999", NaN, Infinity, -Infinity, -5, 0, 12, 170, 9999];
for (const profile of profiles.slice(0, 5)) {
  const tree = profile.startsWith("mesh-tree-");
  const hub = profile === "mesh-balanced";
  const compact = profile === "mesh-compact";
  const cases = [
    ["br", "ftd", true, tree ? 170 : hub ? 300 : compact ? 280 : 200],
    ["mtd", "r", true, tree ? 250 : hub ? 460 : compact ? 450 : 430],
    ["r", "r2", false, tree ? 620 : hub ? 680 : 430],
    ["br", "r", false, hub ? 1097 : tree ? 620 : 430],
    ["br", "br2", false, hub ? 1345 : tree ? 620 : 430],
    ...(tree ? [["ftd", "ftd2", false, 520]] : []),
  ];
  for (const [from, to, isParentChild, minimum] of cases) {
    for (const length of lengths) {
      const edge = makeEdge("length-case", from, to, { isParentChild, length });
      applyProfileEdgeConstraints(nodes, [...structuredClone(edges), edge], profile);
      assert.equal(edge.length, Number.isFinite(length) ? Math.max(length, minimum) : minimum,
        `${profile}: ${from}/${to} length ${String(length)}`);
      lengthComparisons += 1;
    }
  }
}

console.log(JSON.stringify({ profiles: profiles.length, exactEdgeComparisons, lengthComparisons }));
