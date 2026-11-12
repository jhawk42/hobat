import assert from "node:assert/strict";

import {
  datasetIsAvailable,
  isFileCached,
  sourceIsAvailable,
  sourceHasAvailableDatasets,
  loadSourceCapabilities,
} from "../../src/js/tdash-capabilities.js";

const capabilities = {
  sources: {
    "otbr-cli": { state: "cached" },
    "otbr-restapi": { state: "live" },
    mdns: { state: "available" },
    system: { state: "available" },
  },
  files: {
    "td-otbr-cli-meshdiag-topology.json": { cached: true, source: "otbr-cli" },
    "td-otbr-cli-networkdiag-fetch-all.json": { cached: false, source: "otbr-cli" },
    "td-otbr-restapi-devices-list.json": { cached: false, source: "otbr-restapi" },
    "td-mdns-scopes-thread.json": { cached: false, source: "mdns" },
    "td-static-extaddr-device-label.json": { cached: false, source: "system" },
  },
};

assert.equal(sourceIsAvailable("otbr-cli", capabilities), true);
assert.equal(sourceIsAvailable("otbr-restapi", capabilities), true);
assert.equal(sourceIsAvailable("mdns", capabilities), true);
assert.equal(sourceIsAvailable("system", capabilities), true);
assert.equal(isFileCached("td-otbr-cli-meshdiag-topology.json", capabilities), true);
assert.equal(isFileCached("td-static-extaddr-device-label.json", capabilities), false);
assert.equal(datasetIsAvailable({
  source: "otbr-cli",
  files: ["td-otbr-cli-meshdiag-topology.json"],
}, capabilities), true);
assert.equal(datasetIsAvailable({
  source: "otbr-cli",
  files: ["td-otbr-cli-networkdiag-fetch-all.json"],
}, capabilities), true);
assert.equal(datasetIsAvailable({
  source: "otbr-restapi",
  files: ["td-otbr-restapi-devices-list.json"],
}, capabilities), true);
assert.equal(datasetIsAvailable({
  source: "otbr-cli",
  files: ["td-otbr-cli-meshdiag-topology.json", "td-mdns-scopes-thread.json"],
}, capabilities), true);
assert.equal(datasetIsAvailable({
  source: "mdns",
  files: ["td-mdns-scopes-thread.json"],
}, capabilities), true);
assert.equal(datasetIsAvailable({
  source: "system",
  files: ["td-static-extaddr-device-label.json"],
}, capabilities), true);

assert.equal(sourceIsAvailable("missing", capabilities), false);
assert.equal(sourceIsAvailable("offline", {sources: {offline: {state: "unavailable"}}}), false);
assert.equal(datasetIsAvailable({source: "missing", files: ["absent"]}, capabilities), false);
assert.equal(datasetIsAvailable({source: "otbr-cli", files: ["absent"]}, capabilities), false);
const unified = {source: "offline", unified: {}, files: ["product.json"]};
const buildable = {sources: {}, files: {"product.json": {buildableFromCache: true}}};
assert.equal(datasetIsAvailable(unified, buildable), true);
assert.equal(datasetIsAvailable(unified, {files: {}}), false);
assert.equal(sourceHasAvailableDatasets("offline", buildable, [unified]), true);
assert.equal(sourceHasAvailableDatasets("offline", buildable, [{...unified, selectable: false}]), false);
const originalFetch = globalThis.fetch;
try {
  for (const outcome of ["success", "http", "payload", "network"]) {
    let requests = 0;
    globalThis.fetch = async (url) => {
      requests++;
      assert.equal(url, "/api/capabilities");
      if (outcome === "network") throw new TypeError("disconnected");
      return {ok: outcome !== "http", status: outcome === "http" ? 503 : 200,
        json: async () => outcome === "payload" ? {sources: {}} : capabilities};
    };
    if (outcome === "success") assert.equal(await loadSourceCapabilities(), capabilities);
    else await assert.rejects(loadSourceCapabilities(),
      outcome === "http" ? /503/ : outcome === "payload" ? /invalid/ : /disconnected/);
    assert.equal(requests, 1);
  }
} finally {
  globalThis.fetch = originalFetch;
}
console.log("source capability contracts passed");