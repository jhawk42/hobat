import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  createTopologyEventBindings,
  createTopologyRenderOwner,
  createTopologyViewModel,
  projectTopologyTheme,
} from "../../src/js/tdash-topology-view-model.js";
import { decorateTopologyNavigation, isSecondaryRouterRouteEdge, readThemePalette } from "../../src/js/tdash-topology-renderer.js";

const root = { dataset: { theme: "light" } };
globalThis.document = { documentElement: root };
const css = readFileSync(new URL("../../src/tdash.css", import.meta.url), "utf8");
function cssTokens(selector) {
  const start = css.indexOf(`${selector} {`);
  assert.ok(start >= 0);
  const block = css.slice(start, css.indexOf("}", start));
  return Object.fromEntries([...block.matchAll(/(--[\w-]+):\s*(#[0-9a-f]{6})/g)]
    .map((match) => [match[1], match[2]]));
}
const tokens = { light: cssTokens(":root"), dark: cssTokens(':root[data-theme="dark"]') };
let paletteReads = 0;
let missingToken = null;
globalThis.getComputedStyle = () => {
  paletteReads += 1;
  return { getPropertyValue: (token) => token === missingToken ? "" : tokens[root.dataset.theme][token] };
};
globalThis.CSS = { supports: (_property, value) => /^#[0-9a-f]{6}$/.test(value) };
const lightPalette = readThemePalette();
assert.ok(Object.isFrozen(lightPalette));
assert.equal(readThemePalette(), lightPalette);
assert.equal(paletteReads, 1);
root.dataset.theme = "dark";
missingToken = "--topology-label-bg";
assert.throws(() => readThemePalette(), /--topology-label-bg/);
missingToken = null;
const darkPalette = readThemePalette();
assert.notEqual(darkPalette, lightPalette);
assert.equal(readThemePalette(), darkPalette);

const roleTokens = {
  router: "--node-router", borderRouter: "--node-border-router", child: "--node-child",
  eve: "--node-eve", unknown: "--node-unknown",
};
const edgeTokens = {
  lqHigh: "--lq-high", lqMedium: "--lq-medium", lqLow: "--lq-low", lqNone: "--lq-none",
  lqParentChild: "--lq-parent-child", lqOtbr: "--lq-otbr",
};
const colorFixture = createTopologyViewModel({
  nodeData: Object.keys(roleTokens).map((role) => ({
    id: role, themeRole: role, shape: role === "router" ? "hexagon" : "dot",
    x: 12, y: 34, size: 27, physics: false, borderWidth: 3,
    font: { size: 13, face: "monospace" },
  })),
  edgeData: Object.keys(edgeTokens).map((key) => ({
    id: key, themeColorKey: key, from: "router", to: "child",
    width: key === "lqHigh" ? 12 : 4, dashes: key === "lqMedium" || key === "lqLow" ? [5, 5] : false,
    color: { opacity: 0.6 }, physics: false,
  })),
});
const originalFixture = JSON.stringify([colorFixture.nodes, colorFixture.edges]);
let currentFixture = colorFixture;
for (const [theme, palette] of [["light", lightPalette], ["dark", darkPalette], ["light", lightPalette]]) {
  const projection = projectTopologyTheme(currentFixture, palette, "canonical", null);
  for (const [role, token] of Object.entries(roleTokens)) {
    const patch = projection.nodeUpdates.find((node) => node.id === role);
    assert.equal(palette[`${role}Bg`], tokens[theme][`${token}-bg`]);
    assert.equal(patch.color.background, tokens[theme][`${token}-bg`]);
    assert.equal(patch.color.border, tokens[theme][`${token}-border`]);
    assert.equal(patch.color.highlight.border, palette.selectedBorder);
    assert.equal(patch.color.hover.border, palette.hoverBorder);
    assert.equal(patch.font.size, 13);
    assert.equal(patch.borderWidth, 3);
    assert.deepEqual(Object.keys(patch).sort(), ["borderWidth", "color", "font", "id"]);
  }
  for (const [key, token] of Object.entries(edgeTokens)) {
    const patch = projection.edgeUpdates.find((edge) => edge.id === key);
    assert.equal(palette[key], tokens[theme][token]);
    assert.equal(patch.color.color, tokens[theme][token]);
    assert.equal(patch.color.opacity, 0.6);
    assert.equal(patch.color.highlight, palette.selectedBorder);
    assert.equal(patch.color.hover, palette.hoverBorder);
    assert.deepEqual(Object.keys(patch).sort(), ["color", "id"]);
  }
  assert.equal(projection.viewModel.nodes, colorFixture.nodes);
  assert.equal(projection.viewModel.edges, colorFixture.edges);
  assert.equal(JSON.stringify([projection.viewModel.nodes, projection.viewModel.edges]), originalFixture);
  currentFixture = projection.viewModel;
}

const navigationControls = new Map();
const navBindings = createTopologyEventBindings();
let navActivations = 0;
const fakeNetwork = {
  getScale: () => 1,
  getViewPosition: () => ({ x: 0, y: 0 }),
  moveTo: () => { navActivations += 1; },
  fit: () => { navActivations += 1; },
};
for (const name of ["up", "down", "left", "right", "zoomIn", "zoomOut", "zoomExtends"]) {
  const handlers = new Map();
  navigationControls.set(`.vis-navigation .vis-${name}`, {
    attrs: {},
    handlers,
    setAttribute(key, value) { this.attrs[key] = value; },
    addEventListener(name, fn) { handlers.set(name, fn); },
    removeEventListener(name) { handlers.delete(name); },
  });
}
decorateTopologyNavigation({ querySelector: (selector) => navigationControls.get(selector) }, fakeNetwork, navBindings);
for (const control of navigationControls.values()) {
  assert.equal(control.attrs.role, "button");
  assert.ok(control.attrs["aria-label"]);
  assert.equal(control.tabIndex, 0);
  for (const key of ["Enter", " "]) {
    const before = navActivations;
    control.handlers.get("keydown")({ key, repeat: false, preventDefault() {} });
    control.handlers.get("keydown")({ key, repeat: true, preventDefault() {} });
    assert.equal(navActivations, before + 1);
  }
}
navBindings.dispose();
assert.equal(navActivations, 14);
assert.ok([...navigationControls.values()].every((control) => control.handlers.size === 0));

assert.equal(isSecondaryRouterRouteEdge(["otbr_route"]), false);
assert.equal(isSecondaryRouterRouteEdge(["router_neighbor", "otbr_route"]), false);
assert.equal(isSecondaryRouterRouteEdge(["otbr_route", "otbr_route_router"]), true);
assert.equal(
  isSecondaryRouterRouteEdge(["router_neighbor", "otbr_route", "otbr_route_router"]),
  false,
);
assert.equal(isSecondaryRouterRouteEdge(["otbr_route", "otbr_route_ftd_child"]), false);

class FakeEventTarget {
  constructor() {
    this.listeners = new Map();
  }
  on(eventName, listener) {
    const listeners = this.listeners.get(eventName) || new Set();
    listeners.add(listener);
    this.listeners.set(eventName, listeners);
  }
  off(eventName, listener) {
    this.listeners.get(eventName)?.delete(listener);
  }
  emit(eventName) {
    [...(this.listeners.get(eventName) || [])].forEach((listener) => listener());
  }
  count(eventName) {
    return this.listeners.get(eventName)?.size || 0;
  }
}

const target = new FakeEventTarget();
const networks = [];
let currentOwner = null;
let responseCount = 0;
const retainedCallbacks = [];

for (let renderIndex = 0; renderIndex < 5; renderIndex += 1) {
  currentOwner?.dispose();
  const network = {
    destroyed: false,
    destroy() {
      this.destroyed = true;
    },
  };
  const bindings = createTopologyEventBindings();
  bindings.on(target, "change", () => {
    responseCount += 1;
  });
  retainedCallbacks.push(() => {
    if (currentOwner.isActive()) responseCount += 100;
  });
  bindings.once(target, "ready", () => {});
  currentOwner = createTopologyRenderOwner(network, bindings);
  networks.push(network);

  assert.equal(target.count("change"), 1);
  assert.equal(target.count("ready"), 1);
  target.emit("change");
  target.emit("ready");
  assert.equal(target.count("ready"), 0);
}

assert.equal(responseCount, 5);
assert.equal(networks.slice(0, -1).every((network) => network.destroyed), true);
assert.equal(networks.at(-1).destroyed, false);
currentOwner.dispose();
currentOwner.dispose();
retainedCallbacks.at(-1)();
assert.equal(target.count("change"), 0);
assert.equal(networks.at(-1).destroyed, true);

console.log(JSON.stringify({
  renderCount: networks.length,
  responseCount,
  remainingListeners: target.count("change") + target.count("ready"),
  destroyedNetworks: networks.filter((network) => network.destroyed).length,
}));