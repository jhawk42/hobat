import assert from "node:assert/strict";

import {
  datasetIsAvailable,
  isFileCached,
  sourceIsAvailable,
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

console.log("source capability contracts passed");