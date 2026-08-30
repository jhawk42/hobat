import assert from "node:assert/strict";

import { getDeviceIdentityKeys } from "../../src/js/tdash-device-fields.js";
import { mergeRowsByIdentity } from "../../src/js/tdash-merge.js";


const matterA = {
  matter: {
    matterId: "0000000000001234-0000000000000001",
    compressedFabricId: 0x1234,
    nodeId: 1,
  },
};
const matterB = {
  matter: {
    matterId: "0000000000005678-0000000000000002",
    compressedFabricId: 0x5678,
    nodeId: 2,
  },
};

assert.ok(
  getDeviceIdentityKeys(matterA).includes(
    "matterFabricNode:0000000000001234|0000000000000001",
  ),
);

const correlated = mergeRowsByIdentity(
  [[{ ...matterA, deviceLabel: "Sensor" }], [{ ...matterA, channel: 15 }]],
  { matterIdentityMode: "composite-guard" },
);
assert.equal(correlated.length, 1);
assert.equal(correlated[0].deviceLabel, "Sensor");
assert.equal(correlated[0].channel, 15);

const separated = mergeRowsByIdentity(
  [
    [{ ...matterA, omrIpv6Address: "fd00::1" }],
    [{ ...matterB, omrIpv6Address: "fd00::1" }],
  ],
  { matterIdentityMode: "composite-guard" },
);
assert.equal(separated.length, 2);

const extaddrMatched = mergeRowsByIdentity(
  [
    [{ ...matterA, extAddress: "aa00112233445566" }],
    [{ ...matterB, extAddress: "aa00112233445566" }],
  ],
  { matterIdentityMode: "composite-guard" },
);
assert.equal(extaddrMatched.length, 1);

process.stdout.write(`${JSON.stringify({ scenarios: 4 })}\n`);
