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

const crossFabricAddressMatched = mergeRowsByIdentity(
  [
    [{
      matter: {
        compressedFabricId: 0x1234,
        nodeId: 1,
        endpoints: [{
          endpointId: 2,
          bridgedBasicInformation: { serialNumber: "FABRIC-A" },
        }],
      },
      extAddress: "aa00112233445566",
      powerSources: [{ endpointId: 2, attributes: { batPercentRemaining: 151 } }],
    }],
    [{
      matter: {
        matterId: "0000000000005678-0000000000000001",
        nodeId: 1,
        endpoints: [{
          endpointId: 2,
          bridgedBasicInformation: { serialNumber: "FABRIC-B" },
        }],
      },
      extAddress: "aa00112233445566",
      powerSources: [{ endpointId: 2, attributes: { batPercentRemaining: 149 } }],
    }],
  ],
  { matterIdentityMode: "composite-guard" },
);
assert.equal(crossFabricAddressMatched.length, 1);
assert.equal(crossFabricAddressMatched[0].matter.compressedFabricId, 0x1234);
assert.equal(Object.hasOwn(crossFabricAddressMatched[0].matter, "matterId"), false);
assert.equal(
  crossFabricAddressMatched[0].matter.endpoints[0].bridgedBasicInformation.serialNumber,
  "FABRIC-A",
);
assert.equal(
  crossFabricAddressMatched[0].powerSources[0].attributes.batPercentRemaining,
  151,
);

const matterEnrichment = mergeRowsByIdentity(
  [
    [{ extAddress: "aa00112233445566", deviceLabel: "Sensor" }],
    [{
      matter: {
        compressedFabricId: 0x1234,
        nodeId: 1,
        endpoints: [{ endpointId: 2, basicInformation: {} }],
      },
      extAddress: "aa00112233445566",
      powerSources: [{ endpointId: 2, attributes: { batPercentRemaining: 151 } }],
    }],
  ],
  { matterIdentityMode: "composite-guard" },
);
assert.equal(matterEnrichment.length, 1);
assert.equal(matterEnrichment[0].matter.compressedFabricId, 0x1234);
assert.deepEqual(matterEnrichment[0].matter.endpoints, [
  { endpointId: 2, basicInformation: {} },
]);
assert.equal(matterEnrichment[0].powerSources[0].attributes.batPercentRemaining, 151);

const legacyMatterIdentity = mergeRowsByIdentity(
  [
    [{
      matterId: "0000000000001234-0000000000000001",
      compressedFabricId: 0x1234,
      nodeId: 1,
      extAddress: "aa00112233445566",
      powerSources: [{ endpointId: 2, attributes: { batPercentRemaining: 151 } }],
    }],
    [{
      matter: {
        matterId: "0000000000005678-0000000000000001",
        compressedFabricId: 0x5678,
        nodeId: 1,
        endpoints: [{
          endpointId: 2,
          bridgedBasicInformation: { serialNumber: "FABRIC-B" },
        }],
      },
      extAddress: "aa00112233445566",
      powerSources: [{ endpointId: 2, attributes: { batPercentRemaining: 149 } }],
    }],
  ],
  { matterIdentityMode: "composite-guard" },
);
assert.equal(legacyMatterIdentity.length, 1);
assert.equal(
  legacyMatterIdentity[0].matterId,
  "0000000000001234-0000000000000001",
);
assert.equal(Object.hasOwn(legacyMatterIdentity[0], "matter"), false);
assert.equal(
  legacyMatterIdentity[0].powerSources[0].attributes.batPercentRemaining,
  151,
);

process.stdout.write(`${JSON.stringify({ scenarios: 7 })}\n`);
