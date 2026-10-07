import assert from "node:assert/strict";
import { DATASET_REGISTRY } from "../../src/js/tdash-dataset-registry.js";

const REQUIRED = [
  "td-otbr-cli-meshdiag-topology.json",
  "td-otbr-cli-meshdiag-router-childtables.json",
];
const AUXILIARY = "td-otbr-cli-thread-network-info.json";
const CACHE_ONLY_SECONDS = 31536000;
const ENTRY = {
  source: "otbr-cli",
  value: "fetch_characterization",
  label: "Fetch characterization",
  files: REQUIRED,
  mergeStrategy: "by-identity",
  rowExtractor: "raw-array",
  adaptor: "otbr-cli",
  defaultLinkFilter: "all",
  estimateActionCostSecs: 5,
};
const row = (name) => [{ extAddress: "0011223344556677", name }];
const response = (data, headers = {}, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: new Headers(headers),
  json: async () => data,
});
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};

const originalGlobals = Object.fromEntries(
  ["document", "fetch", "setTimeout", "clearTimeout", "setInterval", "clearInterval"]
    .map((key) => [key, globalThis[key]]),
);
const originalNow = Date.now;
let scenarioCount = 0;
let requestCount = 0;
let now = Date.parse("2026-10-01T00:00:00Z");
let timerSequence = 0;
const timers = new Map();
const intervals = new Map();
const elements = new Map();
globalThis.document = {
  getElementById: (id) => {
    assert.ok([
      "fetch-status-line-content", "fetch-timetaken-value",
      "fetch-timetaken-progress", "link-filter",
    ].includes(id), `Unexpected DOM access: ${id}`);
    if (!elements.has(id)) elements.set(id, { textContent: "", value: 0, max: 100 });
    return elements.get(id);
  },
};
Date.now = () => now;
globalThis.setTimeout = (callback, delay) => {
  const id = ++timerSequence;
  timers.set(id, { callback, delay });
  return id;
};
globalThis.clearTimeout = (id) => timers.delete(id);
globalThis.setInterval = (callback, delay) => {
  const id = ++timerSequence;
  intervals.set(id, { callback, delay });
  return id;
};
globalThis.clearInterval = (id) => intervals.delete(id);

async function flush() {
  for (let tick = 0; tick < 40; tick += 1) await Promise.resolve();
}

async function finish(promise) {
  let done = false;
  let result;
  let error;
  promise.then(
    (value) => { done = true; result = value; },
    (reason) => { done = true; error = reason; },
  );
  for (let step = 0; step < 30 && !done; step += 1) {
    await flush();
    if (done) break;
    assert.ok(timers.size > 0, "Fetch stalled without a controlled timer");
    const [id, timer] = timers.entries().next().value;
    timers.delete(id);
    now += timer.delay;
    timer.callback();
  }
  assert.ok(done, "Fetch exceeded controlled timer budget");
  assert.equal(intervals.size, 0, "Elapsed interval leaked");
  assert.equal(timers.size, 0, "Polling timeout leaked");
  if (error) throw error;
  return result;
}

function mockFetch(handler) {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    const call = { url, ...options, headers: { ...options.headers } };
    calls.push(call);
    requestCount += 1;
    return handler(call, calls);
  };
  return calls;
}

function cachedFetch(headersFor = () => ({})) {
  return mockFetch(({ url }) => response(
    url.endsWith(AUXILIARY) ? { networkName: "Characterization" } : row(url),
    headersFor(url),
  ));
}

async function freshModule() {
  elements.clear();
  assert.equal(intervals.size, 0);
  assert.equal(timers.size, 0);
  scenarioCount += 1;
  return import(`../../src/js/tdash-dataset.js?fetch-scenario=${scenarioCount}`);
}

function assertHeaders(calls, expected) {
  assert.deepEqual(calls.map((call) => call.url), [...REQUIRED, AUXILIARY].map(
    (filename) => `/api/data/${filename}`,
  ));
  calls.forEach((call, index) => {
    assert.deepEqual(call.headers, expected[index], call.url);
  });
}

DATASET_REGISTRY.push(ENTRY);
try {
  // Required and auxiliary metadata seed subsequent normal requests independently.
  {
    const dataset = await freshModule();
    const dates = ["Wed, 30 Sep 2026 00:00:00 GMT", "Tue, 29 Sep 2026 00:00:00 GMT",
      "Mon, 28 Sep 2026 00:00:00 GMT"];
    const files = [...REQUIRED, AUXILIARY];
    let calls = cachedFetch((url) => {
      const index = files.indexOf(url.split("/").at(-1));
      return { "Cache-Control": `public, max-age=${[11, 22, 33][index]}`,
        "Last-Modified": dates[index] };
    });
    const sessionId = dataset.startFetchSession();
    const partials = [];
    const loaded = await finish(dataset.loadDataset(ENTRY.value, {
      sessionId, onFileReady: () => partials.push(dataset.currentDataset),
    }));
    dataset.endFetchSession(sessionId);
    assertHeaders(calls, [{}, {}, {}]);
    assert.equal(loaded, dataset.currentDataset);
    assert.equal(loaded.fileLastModifiedAt, Date.parse(dates[2]));
    assert.equal(loaded.isPartial, false);
    assert.deepEqual(loaded.loadedFiles, REQUIRED);
    assert.deepEqual(Object.keys(loaded.auxiliaryFiles), [AUXILIARY]);
    assert.equal(loaded.fetchMetrics.completedFileUpdateCount, 2);
    assert.equal(loaded.fetchMetrics.checkpointUpdateCount, 0);
    assert.deepEqual(partials.map((partial) => partial.fileLastModifiedAt),
      [Date.parse(dates[0]), Date.parse(dates[1])]);
    partials.forEach((partial) => {
      assert.equal(partial.isPartial, true);
      assert.deepEqual(partial.auxiliaryFiles, {});
      assert.equal(Object.hasOwn(partial, "fetchMetrics"), false);
    });
    // Missing metadata retains prior values; zero max-age is a real value.
    calls = cachedFetch((url) => url.endsWith(REQUIRED[0])
      ? { "Cache-Control": "max-age=0" } : {});
    assert.equal((await finish(dataset.loadDataset(ENTRY.value))).fileLastModifiedAt,
      Date.parse(dates[2]));
    assertHeaders(calls, [11, 22, 33].map((age) => ({ "Cache-Control": `max-age=${age}` })));
    calls = cachedFetch();
    await finish(dataset.loadDataset(ENTRY.value));
    assertHeaders(calls, [0, 22, 33].map((age) => ({ "Cache-Control": `max-age=${age}` })));
    dataset.setOnlyCache(true);
    calls = cachedFetch();
    await finish(dataset.loadDataset(ENTRY.value));
    assertHeaders(calls, files.map(() => ({
      "Cache-Control": `only-if-cached, max-age=${CACHE_ONLY_SECONDS}`,
    })));
    calls = cachedFetch();
    await finish(dataset.loadDataset(ENTRY.value, { forceFresh: true }));
    assertHeaders(calls, files.map(() => ({ "Cache-Control": "no-cache" })));
    dataset.setForceFresh(true);
    calls = cachedFetch();
    await finish(dataset.loadDataset(ENTRY.value));
    assertHeaders(calls, files.map(() => ({ "Cache-Control": "no-cache" })));
  }
  // Last-Modified alone defaults max-age to zero; invalid dates remain numeric NaN.
  {
    const dataset = await freshModule();
    cachedFetch((url) => url.endsWith(REQUIRED[0])
      ? { "Last-Modified": "invalid date" }
      : url.endsWith(AUXILIARY) ? { "Last-Modified": "Mon, 28 Sep 2026 00:00:00 GMT" } : {});
    const loaded = await finish(dataset.loadDataset(ENTRY.value));
    assert.ok(Number.isNaN(loaded.fileLastModifiedAt));
    const calls = cachedFetch();
    await finish(dataset.loadDataset(ENTRY.value));
    assertHeaders(calls, [{ "Cache-Control": "max-age=0" }, {}, { "Cache-Control": "max-age=0" }]);
  }
  // A superseded session cannot publish either incremental or final results.
  {
    const dataset = await freshModule();
    cachedFetch();
    const accepted = await finish(dataset.loadDataset(ENTRY.value));
    const pending = deferred();
    mockFetch(() => pending.promise);
    const sessionId = dataset.startFetchSession();
    let publications = 0;
    const loading = dataset.loadDataset(ENTRY.value, {
      sessionId, onFileReady: () => { publications += 1; },
    });
    const rejected = assert.rejects(loading, dataset.isFetchCancelledError);
    const replacement = dataset.startFetchSession();
    dataset.endFetchSession(sessionId);
    assert.equal(dataset.isFetchSessionRunning(), true);
    pending.resolve(response(row("stale")));
    await finish(rejected);
    assert.equal(publications, 0);
    assert.equal(dataset.currentDataset, accepted);
    dataset.endFetchSession(replacement);
  }
  for (const withPartial of [false, true]) {
    const dataset = await freshModule();
    cachedFetch();
    const accepted = await finish(dataset.loadDataset(ENTRY.value));
    const pending = deferred();
    mockFetch(({ url }) => withPartial && url.endsWith(REQUIRED[0])
      ? response(row("partial")) : pending.promise);
    const sessionId = dataset.startFetchSession();
    let publications = 0;
    const loading = dataset.loadDataset(ENTRY.value, {
      sessionId, onFileReady: () => { publications += 1; },
    });
    const rejected = assert.rejects(loading, dataset.isFetchCancelledError);
    await flush();
    const beforeCancel = dataset.currentDataset;
    assert.equal(publications, withPartial ? 1 : 0);
    if (withPartial) {
      assert.equal(beforeCancel.isPartial, true);
      assert.deepEqual(beforeCancel.loadedFiles, [REQUIRED[0]]);
    } else assert.equal(beforeCancel, accepted);
    assert.deepEqual(await dataset.cancelActiveFetchSession(),
      { cancelled: true, cancelledJobIds: [] });
    pending.resolve(response(row("cancelled")));
    await finish(rejected);
    assert.equal(dataset.currentDataset, beforeCancel);
    assert.equal(dataset.restoreLastKnownGoodDataset(), accepted);
    dataset.endFetchSession(sessionId);
  }
  // Both complete failure and an incomplete repeat discard attempted partial publication.
  {
    const dataset = await freshModule();
    cachedFetch();
    const accepted = await finish(dataset.loadDataset(ENTRY.value));
    for (const incomplete of [false, true]) {
      mockFetch(({ url }) => incomplete && url.endsWith(REQUIRED[0])
        ? response(row("unaccepted")) : response({}, {}, 500));
      const sessionId = dataset.startFetchSession();
      assert.equal(await finish(dataset.loadDataset(ENTRY.value, {
        sessionId, onFileReady: () => {},
      })), null);
      assert.equal(dataset.currentDataset, accepted);
      assert.equal(document.getElementById("fetch-status-line-content").textContent,
        incomplete
          ? `Incomplete dataset "${ENTRY.label}": 1 of 2 required files loaded.`
          : `Error: could not load any required file for "${ENTRY.label}".`);
      dataset.endFetchSession(sessionId);
    }
  }
  // Terminal polling uses cache-only max-age, never the original force-fresh intent.
  for (const redispatch of [false, true]) {
    const dataset = await freshModule();
    let primaryReads = 0;
    const calls = mockFetch(({ url }) => {
      if (url === "/api/job/job-1") return response({ status: "done" });
      if (url.endsWith(REQUIRED[0])) {
        primaryReads += 1;
        if (primaryReads === 1 || redispatch) {
          return response({ job_id: "job-1", filename: REQUIRED[0] }, {}, 202);
        }
        return response(row("terminal"), { "Cache-Control": "max-age=7",
          "Last-Modified": "Mon, 28 Sep 2026 00:00:00 GMT" });
      }
      return response(row("other"));
    });
    const sessionId = dataset.startFetchSession();
    const loaded = await finish(dataset.loadDataset(ENTRY.value, { sessionId, forceFresh: true }));
    assert.equal(primaryReads, 2);
    assert.equal(calls.filter((call) => call.url.startsWith("/api/job/")).length, 1);
    const primaryCalls = calls.filter((call) => call.url.endsWith(REQUIRED[0]));
    assert.deepEqual(primaryCalls.map((call) => call.headers), [
      { "Cache-Control": "no-cache" },
      { "Cache-Control": `max-age=${CACHE_ONLY_SECONDS}` },
    ]);
    assert.equal(loaded.isPartial, redispatch);
    assert.deepEqual(loaded.loadedFiles, redispatch ? [REQUIRED[1]] : REQUIRED);
    assert.equal(loaded.fileLastModifiedAt, redispatch ? null
      : Date.parse("Mon, 28 Sep 2026 00:00:00 GMT"));
    assert.equal(calls.every((call) => call.signal === primaryCalls[0].signal), true);
    dataset.endFetchSession(sessionId);
  }
  console.log(JSON.stringify({ scenarioCount, requestCount, controlledTimers: true }));
} finally {
  DATASET_REGISTRY.pop();
  Object.assign(globalThis, originalGlobals);
  Date.now = originalNow;
}
