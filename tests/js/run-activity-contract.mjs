import assert from "node:assert/strict";

import {
  clearActivityEntries,
  getActivityEntries,
  normalizeActivityRoute,
  recordActivity,
  sanitizeActivityMetadata,
  trackedFetch,
} from "../../src/js/tdash-activity.js";

clearActivityEntries();
for (let index = 0; index < 205; index += 1) {
  recordActivity({ category: "ui", message: `event ${index}` });
}
assert.equal(getActivityEntries().length, 200);
assert.equal(getActivityEntries()[0].message, "event 5");

assert.equal(
  normalizeActivityRoute("/api/job/private-id?token=secret&limit=5"),
  "/api/job/{job_id}?limit=5",
);
assert.equal(
  normalizeActivityRoute("/api/device/aabbccddeeff0011"),
  "/api/device/{extAddress}",
);
assert.equal(
  normalizeActivityRoute("/api/data/td-otbr-cli-meshdiag-topology.json"),
  "/api/data/td-otbr-cli-meshdiag-topology.json",
);
const sanitized = sanitizeActivityMetadata({
  text: "x".repeat(300),
  nested: { one: { two: { three: { secret: "hidden" } } } },
  array: Array.from({ length: 30 }, (_, index) => index),
});
assert.equal(sanitized.text.length, 256);
assert.equal(sanitized.array.length, 20);
assert.equal(sanitized.nested.one.two.three, "[truncated]");

const originalFetch = globalThis.fetch;
globalThis.fetch = async () => new Response("{}", { status: 200 });
try {
  clearActivityEntries();
  await trackedFetch("/api/capabilities");
  assert.deepEqual(
    getActivityEntries().map(({ phase }) => phase),
    ["started", "completed"],
  );

  clearActivityEntries();
  await trackedFetch("/api/jobs", {}, "terminal-only");
  assert.deepEqual(getActivityEntries().map(({ phase }) => phase), ["completed"]);

  clearActivityEntries();
  await trackedFetch("/api/jobs", {}, "silent");
  assert.equal(getActivityEntries().length, 0);

  globalThis.fetch = async () => {
    throw new TypeError("https://example.invalid/?token=secret");
  };
  await assert.rejects(() => trackedFetch("/api/capabilities"));
  const failure = getActivityEntries().at(-1);
  assert.equal(failure.metadata.failureCategory, "network");
  assert.equal(JSON.stringify(failure).includes("secret"), false);
} finally {
  globalThis.fetch = originalFetch;
}

console.log("activity contracts passed");
