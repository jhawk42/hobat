import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { trackedJsonRequest } from "../../src/js/tdash-activity.js";

const source = readFileSync("src/js/tdash-ui.js", "utf8");
const section = source.slice(source.indexOf("function healthPurgeVisible()"),
  source.indexOf("function getCurrentThreadNetworkViewData("));
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    checked: id === "health-purge-repack", hidden: false, disabled: false,
    textContent: "", children: [], listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    replaceChildren() { this.children = []; },
    appendChild(child) { this.children.push(child); },
  });
  return elements.get(id);
}
const timers = new Map(), calls = [], queue = [];
let timerId = 0;
const document = {
  hidden: false, getElementById: element, createElement: () => ({ textContent: "" }),
  addEventListener(type, fn) { this[type] = fn; },
};
const fetcher = async (url, options) => {
  calls.push({ url, options });
  const next = queue.shift();
  assert.ok(next, `unexpected request ${url}`);
  return typeof next === "function" ? next() : next;
};
let requestTimeoutMs = 15000;
const context = vm.createContext({
  document, AbortController, currentView: "operations", operationsSubview: "logs",
  JOBS_POLL_MIN_DELAY_MS: 2000, stopJobsPolling() {}, refreshWorkspaceJobs() {},
  setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; },
  clearTimeout(id) { timers.delete(id); },
  trackedJsonRequest: (url, options, mode) => trackedJsonRequest(url, options, mode, requestTimeoutMs, fetcher),
});
vm.runInContext(`const healthPurgeState = {
  keepDays: null, submitting: false, jobId: null, active: false, uncertain: false,
  cancelling: false, status: "", progress: null, timer: null, controller: null,
  jobStatus: null, version: 0, retentionController: null,
}; ${section}
globalThis.state = healthPurgeState;`, context);
const { state } = context;
const response = (status, body) => ({ status, ok: status >= 200 && status < 300, json: async () => body });
const flush = () => new Promise((resolve) => setImmediate(resolve));
const statusText = () => element("health-purge-status").children.map((child) => child.textContent).join(" ");

queue.push(response(200, { enabled: false, paused: true, keep_days: 14 }));
await context.loadHealthPurgeRetention();
assert.match(element("health-purge-retention").textContent, /14 days/);
assert.equal(element("btn-health-purge").disabled, false);
assert.equal(calls.length, 1);

let accept;
queue.push(() => new Promise((resolve) => { accept = resolve; }));
const submission = context.submitHealthPurge();
await context.submitHealthPurge();
assert.equal(calls.length, 2);
assert.equal(calls[1].options.body, '{"repack":true}');
assert.equal(element("btn-health-purge").disabled, true);
document.hidden = true;
document.visibilitychange();
accept(response(202, { job_id: "job/1", status: "running", mode: "maintenance" }));
await submission;
assert.equal(calls.length, 2);
assert.equal(state.active, true);

queue.push(response(200, { keep_days: 14 }), response(200, {
  status: "running", progress: { step_id: "system:repack", completed_steps: 1, total_steps: 2,
    steps: { "health:purge": { status: "completed", deleted: { assessments: 3 } } } },
}));
document.hidden = false;
document.visibilitychange();
await flush();
assert.equal(calls[3].url, "/api/job/job%2F1");
assert.match(statusText(), /assessments: 3/);
assert.match(statusText(), /system:repack \(1\/2 steps completed\)/);
assert.equal(timers.size, 1);
context.currentView = "table";
context.stopHealthPurgePolling();
assert.equal(timers.size, 0);
assert.equal(state.jobId, "job/1");

context.currentView = "operations";
queue.push(response(200, { status: "error", progress: { steps: {
  "health:purge": { status: "completed", deleted: { assessments: 3 } },
  "system:repack": { status: "failed", reason: "disk full" },
} } }));
await context.pollHealthPurge();
assert.match(statusText(), /Repack: failed.*disk full/);
assert.match(statusText(), /Purge was not rolled back/);
assert.equal(element("health-purge-repack").checked, true);
assert.equal(element("btn-health-purge").disabled, false);

element("health-purge-repack").checked = false;
queue.push(response(202, { job_id: "two" }), response(200, { status: "cancelled", progress: { steps: {
  "health:purge": { status: "cancelled", maintenance_unconfirmed: true },
  "system:repack": { status: "skipped" },
} } }));
await context.submitHealthPurge();
await flush();
assert.equal(calls.at(-2).options.body, '{"repack":false}');
assert.match(statusText(), /interrupted maintenance may have committed/);
assert.match(statusText(), /Repack: skipped/);

queue.push(response(409, { error: "busy" }));
await context.submitHealthPurge();
assert.match(statusText(), /409.*busy/);
assert.equal(element("btn-health-purge").disabled, false);

queue.push(response(202, { job_id: "three", status: "running" }),
  response(200, { status: "running", progress: { steps: {} } }));
await context.submitHealthPurge();
await flush();
queue.push(response(202, { status: "cancelling" }),
  response(200, { status: "cancelling", progress: { steps: {} } }));
await context.cancelHealthPurge();
await flush();
assert.equal(calls.at(-2).options.method, "DELETE");
assert.equal(element("btn-health-purge-cancel").disabled, true);
assert.match(statusText(), /may have committed/);
queue.push(response(200, { status: "error", progress: { steps: {
  "health:purge": { status: "failed", reason: "nonzero-exit" },
  "system:repack": { status: "skipped", reason: "purge-failed" },
} } }));
await context.pollHealthPurge();
assert.match(statusText(), /Purge: failed/);
assert.match(statusText(), /Repack: skipped/);

queue.push(() => { throw new Error("network"); });
await context.submitHealthPurge();
assert.match(statusText(), /unconfirmed/);
assert.equal(element("btn-health-purge").disabled, true);
const before = calls.length;
await context.submitHealthPurge();
assert.equal(calls.length, before);

requestTimeoutMs = 5;
state.uncertain = false;
state.active = true;
state.jobId = "slow-job";
for (const stall of [
  () => new Promise(() => {}),
  () => response(200, new Promise(() => {})),
]) {
  queue.push(stall);
  await context.pollHealthPurge();
  assert.match(state.status, /timed out locally.*unconfirmed/);
  assert.equal(state.jobId, "slow-job");
  assert.equal(state.active, true);
  assert.equal(element("btn-health-purge").disabled, true);
}
state.active = false;
queue.push(() => new Promise(() => {}));
await context.submitHealthPurge();
assert.equal(state.uncertain, true);
assert.match(state.status, /unconfirmed/);
const afterTimeout = calls.length;
await context.submitHealthPurge();
assert.equal(calls.length, afterTimeout);
