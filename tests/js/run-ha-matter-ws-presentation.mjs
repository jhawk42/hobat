import assert from "node:assert/strict";

import {
  createDetailValueNode,
  flattenObjectEntries,
  formatMatterDisplayValue,
 matterFieldDisplayLabel,
 matterEndpointArraySummary,
 populateNodeDetailsLists,
} from "../../src/js/tdash-utils.js";

class Element {
 constructor(tagName) {
   Object.assign(this, {
     tagName,
     children: [],
     attributes: {},
     className: "",
     textContent: "",
   });
   this.classList = {
     add: (...names) => {
       this.className = [...new Set([...this.className.split(/\s+/), ...names].filter(Boolean))].join(" ");
     },
     remove: (...names) => {
       this.className = this.className.split(/\s+/).filter((name) => !names.includes(name)).join(" ");
     },
   };
 }
 appendChild(child) { this.children.push(child); return child; }
 set innerHTML(value) { this.children = []; this.textContent = String(value); }
 setAttribute(name, value) { this.attributes[name] = value; }
 getAttribute(name) { return this.attributes[name] ?? null; }
}

const matterDetailsList = new Element("ul");
matterDetailsList.setAttribute(
 "data-fields",
 "matter.endpoints,generalDiagnostics.upTime,generalDiagnostics.bootReason,"
   + "generalDiagnostics.activeRadioFaults,powerSources",
);
globalThis.document = {
 createElement: (tagName) => new Element(tagName),
 getElementById: (id) => id === "matter-list" ? matterDetailsList : null,
};
const allText = (node) => [
 node.textContent,
 ...node.children.flatMap(allText),
].filter(Boolean).join(" ");

assert.equal(
  formatMatterDisplayValue("generalDiagnostics.upTime", "90061"),
  "90061 s (1d 1h 1m 1s)",
);
assert.equal(
  formatMatterDisplayValue("generalDiagnostics.totalOperationalHours", 0),
  "0 h",
);
assert.equal(
  formatMatterDisplayValue("generalDiagnostics.bootReason", 2),
  "Brown-out reset (2)",
);
assert.equal(
  formatMatterDisplayValue("generalDiagnostics.activeRadioFaults", [3, 99]),
  "Thread fault (3), Unknown (99)",
);
assert.equal(
  formatMatterDisplayValue("generalDiagnostics.activeHardwareFaults", []),
  "None reported",
);
assert.equal(
  formatMatterDisplayValue("powerSources.0.attributes.description", null),
  "n/a",
);
assert.equal(
  formatMatterDisplayValue("powerSources.0.attributes.status", 99),
  "Unknown (99)",
);
assert.equal(
  formatMatterDisplayValue("powerSources.0.attributes.endpointList", []),
  "All endpoints (node-wide)",
);
assert.equal(
  matterEndpointArraySummary("matter.endpoints", [{
    endpointId: 2,
    bridgedBasicInformation: {productName: "<sensor>"},
  }]),
  "Endpoint 2 — <sensor>",
);

const detail = createDetailValueNode("powerSources", [
  {
    endpointId: 2,
    attributes: {
      description: "Sensor battery",
      status: 1,
      batPercentRemaining: 151,
      endpointList: [],
      batReplacementNeeded: false,
    },
    batteryPercent: 75.5,
  },
  {
    endpointId: 3,
    attributes: {batVoltage: 0},
  },
  {
    endpointId: 4,
    attributes: {endpointList: null},
  },
  {
    endpointId: 5,
  },
], "powerSources");
const detailText = allText(detail);
assert.match(detailText, /Power source · Endpoint 2 — Sensor battery — 75\.5%/);
assert.match(detailText, /Active \(1\)/);
assert.match(detailText, /151 \(0\.5% units\)/);
assert.match(detailText, /All endpoints \(node-wide\)/);
assert.match(detailText, /false/);
assert.match(detailText, /Powered endpoint scope.*scope unknown/);
assert.match(detailText, /Not reported \(scope unknown\)/);
assert.match(detailText, /0 mV/);
assert.doesNotMatch(detailText, /\[object Object\]/);
assert.match(
  allText(createDetailValueNode("powerSources", [], "powerSources")),
  /No power sources reported/,
);

const endpointDetail = createDetailValueNode("endpoints", [
  {
    endpointId: 4,
    bridgedBasicInformation: {
      vendorName: "<Vendor>",
      productName: "Temperature sensor",
      reachable: false,
    },
  },
], "matter.endpoints");
const endpointText = allText(endpointDetail);
assert.match(endpointText, /Endpoint 4 — Temperature sensor/);
assert.match(endpointText, /<Vendor>/);
assert.match(endpointText, /false/);
assert.doesNotMatch(endpointText, /&lt;Vendor&gt;/);
const nestedMatterDetails = [];
const visit = (node) => {
  if (node.tagName === "details" && node.className.includes("matter-endpoint-detail")) {
    nestedMatterDetails.push(node);
  }
  node.children.forEach(visit);
};
visit(endpointDetail);
assert.equal(nestedMatterDetails[0].open, false);
assert.equal(matterFieldDisplayLabel("matter.isBridge", "isBridge"), "Node is a bridge");
assert.equal(
  formatMatterDisplayValue("powerSources.0.attributes.endpointList", null),
  "Not reported (scope unknown)",
);

const panelDetails = flattenObjectEntries({
  matter: {
    endpoints: [{
      endpointId: 4,
      bridgedBasicInformation: {productName: "Temperature sensor"},
    }],
  },
  generalDiagnostics: {
    upTime: "90061",
    bootReason: 2,
    activeRadioFaults: [3],
  },
  powerSources: [{
    endpointId: 2,
    attributes: {description: "Sensor battery", batPercentRemaining: 151},
    batteryPercent: 75.5,
  }],
});
populateNodeDetailsLists(panelDetails);
const panelText = allText(matterDetailsList);
assert.match(panelText, /90061 s \(1d 1h 1m 1s\)/);
assert.match(panelText, /Brown-out reset \(2\)/);
assert.match(panelText, /Thread fault \(3\)/);
assert.match(panelText, /Endpoint 4 — Temperature sensor/);
assert.match(panelText, /Power source · Endpoint 2 — Sensor battery — 75\.5%/);
assert.match(
  panelText,
  /Matter values reflect the server's last-known cache; they are not live reads\./,
);
assert.doesNotMatch(panelText, /\[0\]/);

const coverage = flattenObjectEntries({
  diagnosticCoverage: {
    threadNetworkDiagnostics: {cluster: "populated"},
    powerSources: {
      "2": {cluster: "populated", attributes: {batPercentRemaining: "populated"}},
    },
  },
});
assert.ok(coverage.some(([path]) => path === "diagnosticCoverage.powerSources"));
assert.ok(coverage.some(([path]) => path === "diagnosticCoverage.threadNetworkDiagnostics.cluster"));

process.stdout.write(`${JSON.stringify({checks: 9})}\n`);
