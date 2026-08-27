import assert from "node:assert/strict";

import {
  createTopologyEventBindings,
  createTopologyRenderOwner,
} from "../../src/js/tdash-topology-view-model.js";

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