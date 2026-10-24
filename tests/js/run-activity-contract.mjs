import assert from "node:assert/strict";

import {
  clearActivityEntries,
  getActivityEntries,
  normalizeActivityRoute,
  recordActivity,
  sanitizeActivityMetadata,
  subscribeActivity,
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

const originalWarn = console.warn;
const warnings = [];
const notices = [];
let fetchCount = 0;
const unsubscribers = [
  subscribeActivity(() => { throw new Error("private subscriber details"); }),
  subscribeActivity((entry) => notices.push(entry)),
  subscribeActivity(() => { throw new Error("more private details"); }),
  subscribeActivity((entry) => notices.push(entry)),
];
console.warn = (...args) => warnings.push(args);
try {
  for (const mode of ["full", "terminal-only", "silent"]) {
    for (const outcome of ["success", "failure", "abort"]) {
      clearActivityEntries();
      notices.length = 0;
      const response = new Response("{}", {status: 200});
      const error = outcome === "abort" ? new DOMException("cancelled", "AbortError")
        : new TypeError("private network detail");
      globalThis.fetch = async () => {
        fetchCount += 1;
        if (outcome !== "success") throw error;
        return response;
      };
      const before = fetchCount;
      if (outcome === "success") assert.equal(await trackedFetch("/api/jobs", {}, mode), response);
      else await assert.rejects(trackedFetch("/api/jobs", {}, mode), (actual) => actual === error);
      assert.equal(fetchCount, before + 1);
      const entries = mode === "full" ? 2 : mode === "terminal-only" ? 1 : 0;
      assert.equal(getActivityEntries().length, entries);
      assert.equal(notices.length, entries * 2);
    }
  }
  clearActivityEntries();
  assert.deepEqual(notices.slice(-2), [null, null]);
  assert.ok(warnings.length > 0);
  assert.equal(JSON.stringify(warnings).includes("private"), false);
} finally {
  unsubscribers.forEach((unsubscribe) => unsubscribe());
  console.warn = originalWarn;
  globalThis.fetch = originalFetch;
}

console.log("activity contracts passed");
