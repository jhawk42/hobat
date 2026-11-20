import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { trackedJsonRequest } from "../../src/js/tdash-activity.js";
import { startHealthProcessing, fetchHealthJob } from "../../src/js/tdash-health.js";

const source = readFileSync("src/js/tdash-ui.js", "utf8");
const jobsCode = source.slice(source.indexOf("async function refreshWorkspaceJobs()"),
  source.indexOf("async function cancelWorkspaceJob("));
const response = (body) => ({ ok: true, status: 200, json: async () => body });
const never = () => new Promise(() => {});

for (const fetcher of [never, async () => response(never())]) {
  const state = { jobs: [{jobId: "known", status: "running"}], loading: false,
    error: "", requestVersion: 0, abortController: null, pollTimer: null,
    cancellingJobIds: new Set(["known"]) };
  const timers = [];
  const context = vm.createContext({
    jobsViewState: state, jobsPanelIsVisible: () => true,
    JOBS_POLL_MIN_DELAY_MS: 2000, AbortController,
    renderWorkspaceJobs() {}, recordJobsSnapshotTransitions() {},
    getJobsPollDelayMs: () => 2000,
    trackedJsonRequest: (url, options, mode) => trackedJsonRequest(url, options, mode, 5, fetcher),
    setTimeout(fn) { timers.push(fn); return timers.length; }, clearTimeout() {},
  });
  vm.runInContext(jobsCode, context);
  await context.refreshWorkspaceJobs();
  assert.match(state.error, /timed out locally.*unconfirmed/);
  assert.equal(state.loading, false);
  assert.equal(state.jobs[0].jobId, "known");
  assert.equal(state.cancellingJobIds.has("known"), true);
  assert.equal(timers.length, 1);
}

const controller = new AbortController();
controller.abort();
let called = false;
await assert.rejects(trackedJsonRequest("/test", {signal: controller.signal}, "silent", 5,
  async () => { called = true; return response({}); }), {name: "AbortError"});
assert.equal(called, false);

for (const fetcher of [never, async () => response(never())]) {
  let signal;
  await assert.rejects(trackedJsonRequest("/test", {}, "silent", 5, (url, options) => {
    signal = options.signal;
    return fetcher();
  }), {name: "TimeoutError"});
  assert.equal(signal.aborted, true);
}

const healthStart = source.indexOf("function invalidateHealthRefresh()");
const healthCode = source.slice(healthStart,
  source.indexOf('document.getElementById("health-view-filter")', healthStart));
const originalFetch = globalThis.fetch;
const originalSetTimeout = globalThis.setTimeout;
try {
  globalThis.setTimeout = (fn, delay, ...args) =>
    originalSetTimeout(fn, delay === 15000 ? 5 : delay, ...args);
  for (const phase of ["submission", "poll"]) {
    for (const stall of [never, async () => response(never())]) {
      let count = 0;
      globalThis.fetch = async () => {
        count += 1;
        if (phase === "poll" && count === 1) {
          return response({job_id: "job-1", status: "running"});
        }
        return stall();
      };
      const state = { refreshVersion: 0 };
      const context = vm.createContext({
        healthInsightsState: state,
        currentDataset: {entry: {value: "dataset", healthEligible: true}},
        startHealthProcessing, fetchHealthJob,
        setTimeout: (fn) => originalSetTimeout(fn, 0),
        applyHealthAssessmentPresentation() {}, renderHealthStatusSummary() {},
        renderNetworkInsights() {}, updateHealthRefreshControls() {},
        updateHealthPresentationControls() {}, recordActivity() {},
        getCurrentHealthAssessment() { return null; },
      });
      vm.runInContext(healthCode, context);
      await context.runHealthRefresh();
      assert.equal(state.refreshStatus, "unconfirmed");
      assert.match(state.refreshDetail, /unconfirmed.*deadline/i);
      assert.equal(state.refreshJobId, phase === "poll" ? "job-1" : null);
      assert.equal(count, phase === "poll" ? 2 : 1);
    }
  }
} finally {
  globalThis.fetch = originalFetch;
  globalThis.setTimeout = originalSetTimeout;
}
