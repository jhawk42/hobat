import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

import {
  activateViewStatus,
  configureViewStatusPresenter,
  createViewStatusOwner,
  networkInstanceMatchesId,
  networkInstanceStatus,
  publishViewStatus,
  supersedeViewStatus,
} from "../../src/js/tdash-view-status.js";

const presented = [];
const owner = createViewStatusOwner((status) => presented.push(status));
const firstDataset = {};
const secondDataset = {};
const capabilities = { files: {
  first: { networkInstance: { extPanId: "78b9775b001c1cbe", provenance: "observed" } },
  second: { networkInstance: { extPanId: "1111111111111111", provenance: "operator" } },
} };
assert.equal(networkInstanceStatus(["first"], capabilities), "Network instance: 78b9775b001c1cbe (observed)");
assert.equal(networkInstanceStatus(["second"], capabilities), "Network instance: 1111111111111111 (operator)");
assert.equal(networkInstanceStatus(["first", "second"], capabilities), "Network instance: mixed");
assert.equal(networkInstanceStatus(["missing"], capabilities), "Network instance: unknown");
assert.equal(networkInstanceMatchesId(["first"], capabilities, "extpan:78b9775b001c1cbe"), true);
assert.equal(networkInstanceMatchesId(["first"], capabilities, "extpan:1111111111111111"), false);
assert.equal(networkInstanceMatchesId(["first", "second"], capabilities, "extpan:78b9775b001c1cbe"), false);
assert.equal(networkInstanceMatchesId(["missing"], capabilities, "extpan:78b9775b001c1cbe"), false);
assert.equal(networkInstanceMatchesId(["first"], capabilities, "unknown"), false);

const status = (summary, state = "ready") => ({ summary, details: [], state });
assert.equal(owner.activate("topology", firstDataset), undefined);
assert.equal(presented.at(-1), undefined);
assert.equal(owner.publish("topology", status("93 nodes | 0 links"), firstDataset), true);
assert.equal(presented.at(-1).summary, "93 nodes | 0 links");

owner.activate("table", firstDataset);
assert.equal(presented.at(-1), undefined);
assert.equal(owner.publish("table", status("93/93 rows"), firstDataset), true);
assert.equal(presented.at(-1).summary, "93/93 rows");

assert.equal(owner.publish("topology", status("93 nodes | 0 links, stabilized"), firstDataset), true);
assert.equal(presented.at(-1).summary, "93/93 rows");
assert.equal(owner.activate("topology", firstDataset).summary, "93 nodes | 0 links, stabilized");
assert.equal(owner.activate("table", firstDataset).summary, "93/93 rows");

owner.invalidate(secondDataset);
assert.equal(owner.activate("topology", secondDataset), undefined);
assert.equal(presented.at(-1), undefined);
assert.equal(owner.publish("topology", status("Topology error: invalid data", "error"), firstDataset), false);
assert.equal(owner.publish("topology", status("Topology error: empty dataset", "error"), secondDataset), true);
assert.equal(presented.at(-1).summary, "Topology error: empty dataset");

const singletonPresented = [];
configureViewStatusPresenter((status) => singletonPresented.push(status));
activateViewStatus("table", firstDataset);
publishViewStatus("table", status("93/93 rows"), firstDataset);
supersedeViewStatus(status("Loading replacement…", "loading"));
activateViewStatus("table", firstDataset);
assert.deepEqual(singletonPresented.map((item) => item?.summary),
  [undefined, "93/93 rows", "Loading replacement…", "93/93 rows"]);

const source = fs.readFileSync("src/js/tdash-ui.js", "utf8");
const controllerSource = source.slice(source.indexOf("function createStatusDisclosure()"),
  source.indexOf("\nconst statusDisclosure ="));
const documentListeners = {};
const nodes = {};
const document = {
  activeElement: null,
  getElementById: (id) => nodes[id],
  addEventListener: (name, callback) => { documentListeners[name] = callback; },
  querySelectorAll: () => [nodes.next],
  createElement: () => ({textContent: ""}),
};
function element() {
  return {
    listeners: {}, attributes: {}, hidden: false, children: [], style: {}, scrollTop: 0,
    addEventListener(name, callback) { this.listeners[name] = callback; },
    setAttribute(name, value) { this.attributes[name] = value; },
    contains(target) { return target === this || this.children.includes(target); },
    matches() { return false; },
    replaceChildren() { this.children = []; },
    append(...items) { this.children.push(...items); },
    getClientRects() { return [{}]; },
    getBoundingClientRect() { return {left: 100, top: 50, bottom: 80, height: 100}; },
    querySelectorAll() { return [nodes.close]; },
    focus() { document.activeElement = this; this.listeners.focus?.(); },
  };
}
nodes.trigger = element();
nodes.region = element();
nodes.close = element();
nodes.list = element();
nodes.next = element();
nodes.region.scrollHeight = 100;
nodes.region.offsetWidth = 200;
nodes.region.children.push(nodes.close);
nodes["btn-view-status-details"] = nodes.trigger;
nodes["view-status-details-popover"] = nodes.region;
nodes["btn-view-status-details-close"] = nodes.close;
nodes["view-status-details-list"] = nodes.list;
const context = vm.createContext({document, window: {innerHeight: 600, innerWidth: 800, addEventListener() {}},
  setTimeout() { return 1; }, clearTimeout() {}, requestAnimationFrame() { return 1; },
  cancelAnimationFrame() {}});
vm.runInContext(`${controllerSource}; globalThis.controller = createStatusDisclosure();`, context);
nodes.trigger.listeners.focus();
assert.equal(nodes.region.hidden, false);
assert.equal(nodes.trigger.attributes["aria-expanded"], "true");
assert.equal(nodes.region.style.top, "88px");
assert.equal(nodes.region.style.left, "100px");
nodes.trigger.listeners.click();
nodes.trigger.focus();
let prevented = false;
documentListeners.keydown({key: "Tab", shiftKey: false, preventDefault() { prevented = true; }});
assert.equal(prevented, true);
assert.equal(document.activeElement, nodes.close);
documentListeners.keydown({key: "Tab", shiftKey: true, preventDefault() {}});
assert.equal(document.activeElement, nodes.trigger);
documentListeners.keydown({key: "Escape", preventDefault() {}});
assert.equal(nodes.region.hidden, true);
nodes.trigger.listeners.focus();
assert.equal(nodes.region.hidden, true);
nodes.trigger.listeners.click();
assert.equal(nodes.region.hidden, false);
context.controller.update([{label: "<filter>", value: "<unsafe>"}]);
assert.equal(nodes.list.children[0].textContent, "<filter>");
assert.equal(nodes.list.children[1].textContent, "<unsafe>");
documentListeners.pointerdown({target: nodes.next});
assert.equal(nodes.region.hidden, true);

console.log(JSON.stringify({
  presentedCount: presented.length,
  finalStatus: presented.at(-1).summary,
  staleDatasetRejected: true,
  transientOverrideRestored: true,
}));