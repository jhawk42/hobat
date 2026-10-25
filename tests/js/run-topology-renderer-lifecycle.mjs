import assert from "node:assert/strict";

import {
  createTopologyEventBindings,
  createTopologyRenderOwner,
} from "../../src/js/tdash-topology-view-model.js";
import { decorateTopologyNavigation, isSecondaryRouterRouteEdge, readThemePalette } from "../../src/js/tdash-topology-renderer.js";

const root = { dataset: { theme: "light" } };
globalThis.document = { documentElement: root };
let paletteReads = 0;
let missingToken = null;
globalThis.getComputedStyle = () => {
  paletteReads += 1;
  return { getPropertyValue: (token) => token === missingToken ? "" : "#123456" };
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