import assert from "node:assert/strict";

import {
  DEVICE_ACTIONS,
  buildDeviceDiagnosticsModel,
  deviceActionStatusLabel,
  getEligibleDeviceAddresses,
} from "../../src/js/tdash-device-diagnostics.js";

const capabilities = {
  enabled: true,
  resetEnabled: true,
  actions: Object.values(DEVICE_ACTIONS),
};

const otbr = buildDeviceDiagnosticsModel({
  extAddress: "aabbccddeeff0011",
  ipv6Addresses: ["fd00:0::10", "fd00::10", "fe80::1", "ff03::1"],
  mode: { rxOnWhenIdle: false },
}, {
  source: "otbr-cli",
  files: ["td-otbr-cli-networkdiag-fetch-all.json"],
}, capabilities);
assert.equal(otbr.pingAction, DEVICE_ACTIONS.OTBR_PING);
assert.equal(otbr.targets.length, 1);
assert.equal(otbr.targets[0].address, "fd00::10");
assert.equal(otbr.sleepy, true);
assert.equal(otbr.resetSupported, true);

const matter = buildDeviceDiagnosticsModel({
  matter: { nodeId: "4660" },
  networkInterfaces: [{ ipv6Addresses: ["fd00::20"] }],
}, {
  source: "ha-matter-ws",
  files: ["td-ha-matter-ws-dashboard.json"],
}, capabilities);
assert.equal(matter.pingAction, DEVICE_ACTIONS.MATTER_PING);
assert.equal(matter.nodeId, "4660");
assert.deepEqual(matter.targets, []);

const mdns = buildDeviceDiagnosticsModel({
  id: "service-1",
  serviceInfo: { addressesParsed: ["192.0.2.5", "2001:db8::5"] },
}, {
  source: "mdns",
  files: ["td-mdns-scopes-thread.json"],
}, capabilities);
assert.equal(mdns.pingAction, DEVICE_ACTIONS.SYSTEM_PING);
assert.equal(mdns.targets.length, 2);
assert.equal(deviceActionStatusLabel("no-response"), "No response");

assert.deepEqual(getEligibleDeviceAddresses({ addresses: ["127.0.0.1", "ff03::1"] }), []);

console.log("device diagnostics model tests passed");