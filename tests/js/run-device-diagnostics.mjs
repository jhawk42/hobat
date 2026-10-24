import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

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

const resetDisabled = buildDeviceDiagnosticsModel({
  extAddress: "aabbccddeeff0011",
  ipv6Addresses: ["fd00::10"],
}, {
  source: "otbr-cli",
  files: ["td-otbr-cli-networkdiag-fetch-all.json"],
}, {
  enabled: true,
  resetEnabled: false,
  actions: [DEVICE_ACTIONS.OTBR_PING],
});
assert.equal(resetDisabled.pingAction, DEVICE_ACTIONS.OTBR_PING);
assert.equal(resetDisabled.resetSupported, false);

assert.equal(buildDeviceDiagnosticsModel({
  extAddress: "aabbccddeeff0011",
  ipv6Addresses: ["fd00::10"],
}, {
  source: "otbr-cli",
  files: ["td-otbr-cli-networkdiag-fetch-all.json"],
}, { enabled: false, resetEnabled: false, actions: [] }), null);

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

if (process.argv.includes("--ui")) {
  const source = readFileSync(new URL("../../src/js/tdash-ui.js", import.meta.url), "utf8");
  const diagnostics = source.slice(source.indexOf("const deviceDiagnosticsState ="),
    source.indexOf("const DIAGNOSTIC_SOURCE_LABELS ="));
  const deferred = () => {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
  };
  const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
  let scenarioCount = 0;
  function harness() {
    scenarioCount++;
    let now = 0, timerId = 0;
    const timers = new Map(), calls = [], writes = [], events = [], elements = new Map();
    let responder;
    const element = (id) => {
      if (!elements.has(id)) elements.set(id, {
        value: id.endsWith("attempts") ? "1" : id.endsWith("timeout") ? "1" : "fd00::1",
        checked: false, hidden: false, disabled: false,
        classList: { toggle() {} }, replaceChildren() {},
        listeners: {}, addEventListener(type, listener) { this.listeners[type] = listener; },
      });
      return elements.get(id);
    };
    const model = { deviceId: "A", source: "otbr-cli", datasetFiles: [],
      pingAction: DEVICE_ACTIONS.OTBR_PING, resetSupported: true,
      targets: [{ address: "fd00::1", family: "ipv6" }] };
    const context = vm.createContext({
      AbortController, DOMException, DEVICE_ACTIONS, console,
      performance: { now: () => now }, Date,
      setTimeout: (fn, delay) => { timers.set(++timerId, { fn, at: now + delay }); return timerId; },
      clearTimeout: (id) => timers.delete(id),
      document: { getElementById: element, querySelectorAll: () => [],
        querySelector: () => ({ value: "both" }), addEventListener() {} },
      currentDataset: { entry: {} }, buildDeviceDiagnosticsModel: (record) => record ? model : null,
      formatDuration: String, deviceActionStatusLabel, DEVICE_SELECTION_EVENT: "selected",
      recordActivity: (event) => events.push(event),
      fetch: (url, options = {}) => {
        const reply = deferred(), call = { url, options, ...reply };
        calls.push(call);
        if (responder) responder(call);
        return reply.promise;
      },
    });
    context.trackedFetch = context.fetch;
    vm.runInContext(`${diagnostics}
      setDeviceDiagnosticsStatus = (message, error) => writes.push({message, error});
      renderDeviceDiagnosticResult = (result) => writes.push({result});
      renderDeviceDiagnosticsSelection = () => setDeviceDiagnosticsPending(false);
      globalThis.api = { state: deviceDiagnosticsState, invokeDeviceDiagnostic,
        selectDeviceDiagnosticsRecord, initDeviceDiagnostics, cancelDeviceDiagnostic };
    `, Object.assign(context, { writes }));
    context.api.state.model = model;
    const reply = (call, payload, status = 200) => call.resolve({
      ok: status >= 200 && status < 300, status, json: async () => payload,
    });
    const envelope = (call, status = "running", extra = {}) => {
      const request = calls.find((item) => item.options.method === "POST");
      return { job_id: call.jobId || "job-A", action: model.pingAction,
        invocationId: JSON.parse(request.options.body).invocationId, status, ...extra };
    };
    const advance = async (ms) => {
      const end = now + ms;
      while (true) {
        const next = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
        if (!next || next[1].at > end) break;
        now = next[1].at; timers.delete(next[0]); next[1].fn(); await flush();
      }
      now = end; await flush();
    };
    return { ...context.api, calls, writes, timers, events, reply, envelope, advance, element,
      respondWith: (fn) => { responder = fn; } };
  }
  {
    const h = harness();
    const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
    h.selectDeviceDiagnosticsRecord(null);
    h.reply(h.calls[0], h.envelope(h.calls[0]), 202);
    await flush();
    assert.equal(h.calls.filter((call) => call.options.method === "DELETE").length, 1,
      "late accepted stale submission must be disposed");
    h.reply(h.calls[1], h.envelope(h.calls[0], "cancelling"), 202);
    await pending;
    assert.equal(h.timers.size, 0);
  }
  {
    const h = harness();
    const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
    h.reply(h.calls[0], {}, 202);
    await flush();
    assert.match(h.writes.at(-1).message, /protocol|invalid/i,
      "malformed mandatory success must be a protocol error");
    await pending;
    assert.equal(h.timers.size, 0);
  }
  // Only API/DOM boundaries are stubbed; the extracted lifecycle and timers execute unchanged.
  {
    const h = harness();
    const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
    await h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
    assert.equal(h.calls.length, 1, "pending submission rejects duplicate action");
    await h.cancelDeviceDiagnostic();
    assert.match(h.writes.at(-1).message, /awaiting submission acceptance/);
    assert.equal(h.calls[0].options.signal.aborted, false, "queueing Cancel retains POST");
    h.reply(h.calls[0], h.envelope(h.calls[0]), 202);
    await flush();
    const deletion = h.calls.find((call) => call.options.method === "DELETE");
    assert.ok(deletion);
    const cancelAgain = h.cancelDeviceDiagnostic();
    assert.equal(h.calls.filter((call) => call.options.method === "DELETE").length, 1);
    h.reply(deletion, h.envelope(deletion, "cancelling"), 202);
    await cancelAgain;
    const poll = h.calls.find((call) => !call.options.method);
    h.reply(poll, h.envelope(poll, "cancelled"));
    await pending;
    assert.match(h.writes.at(-1).message, /server diagnostic cancelled/i);
    assert.equal(h.writes.some((write) => write.result), false, "no invented cancelled result");
    assert.equal(h.timers.size, 0);
  }
  for (const failure of ["network", "http", "404"]) {
    const h = harness();
    const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
    h.reply(h.calls[0], h.envelope(h.calls[0]), 202);
    await flush();
    const cancel = h.cancelDeviceDiagnostic();
    const deletion = h.calls.at(-1);
    if (failure === "network") deletion.reject(new Error("offline"));
    else h.reply(deletion, { error: "unavailable" }, failure === "404" ? 404 : 500);
    await cancel;
    assert.match(h.writes.at(-1).message, /cancellation unconfirmed/i);
    assert.equal(h.state.jobId, "job-A");
    const retry = h.cancelDeviceDiagnostic();
    assert.equal(h.calls.filter((call) => call.options.method === "DELETE").length, 2);
    h.reply(h.calls.at(-1), h.envelope(h.calls[0], "done", {
      result: { action: DEVICE_ACTIONS.OTBR_PING, status: "no-response" },
    }), 409);
    await retry;
    await pending;
    assert.equal(h.writes.at(-1).message, "No response");
    assert.equal(h.timers.size, 0);
  }
  {
    const h = harness();
    const old = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
    h.selectDeviceDiagnosticsRecord({});
    const newer = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
    const firstRequest = JSON.parse(h.calls[0].options.body);
    const secondRequest = JSON.parse(h.calls[1].options.body);
    const newEnvelope = { job_id: "new-job", action: secondRequest.action,
      invocationId: secondRequest.invocationId, status: "running" };
    h.reply(h.calls[1], newEnvelope, 202);
    await flush();
    h.reply(h.calls[0], { job_id: "old-job", action: firstRequest.action,
      invocationId: firstRequest.invocationId, status: "running" }, 202);
    await flush();
    const deletion = h.calls.find((call) => call.options.method === "DELETE");
    assert.equal(deletion.url, "/api/device-action-jobs/old-job");
    const writesBefore = h.writes.length;
    deletion.reject(new Error("private error must not be logged"));
    await old;
    assert.equal(h.writes.length, writesBefore, "stale DELETE failure cannot write current UI");
    assert.equal(h.state.jobId, "new-job");
    assert.equal(JSON.stringify(h.events).includes("private error"), false);
    h.reply(h.calls.find((call) => !call.options.method), {
      ...newEnvelope, status: "error", detail: "command rejected",
    });
    await newer;
    assert.match(h.writes.at(-1).message, /server diagnostic error/i);
    assert.equal(h.timers.size, 0);
  }
  for (const where of ["request", "delay", "target", "capabilities"]) {
    const h = harness();
    const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
    h.reply(h.calls[0], h.envelope(h.calls[0]), 202);
    await flush();
    const poll = h.calls[1];
    if (where === "delay") {
      h.reply(poll, h.envelope(poll));
      await flush();
    }
    if (where === "target" || where === "capabilities") {
      h.initDeviceDiagnostics();
      if (where === "target") h.element("device-diagnostics-target").listeners.change();
      else {
        h.reply(h.calls.at(-1), { enabled: true });
        await flush();
      }
    } else h.selectDeviceDiagnosticsRecord(null);
    const deletion = h.calls.find((call) => call.options.method === "DELETE");
    assert.ok(deletion);
    const writesBefore = h.writes.length;
    h.reply(deletion, h.envelope(deletion, "cancelling"), 202);
    if (where !== "delay") h.reply(poll, h.envelope(poll, "done", {
      result: { action: DEVICE_ACTIONS.OTBR_PING, status: "success" },
    }));
    await pending;
    await flush();
    assert.equal(h.writes.length, writesBefore, "invalidated poll never publishes");
    assert.equal(h.timers.size, 0);
  }
  for (const method of ["POST", "GET", "DELETE"]) {
    for (const stalled of ["headers", "body"]) {
      const h = harness();
      const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
      let call = h.calls[0], cancellation;
      if (method !== "POST") {
        h.reply(call, h.envelope(call), 202);
        await flush();
        call = h.calls[1];
      }
      if (method === "DELETE") {
        cancellation = h.cancelDeviceDiagnostic();
        call = h.calls.at(-1);
        // Finish GET while DELETE remains outstanding to isolate its timer ownership.
        h.reply(h.calls[1], h.envelope(h.calls[1], "cancelled"));
        await pending;
      }
      let body;
      if (stalled === "body") {
        body = deferred();
        call.resolve({ ok: true, status: method === "GET" ? 200 : 202,
          json: () => body.promise });
        await flush();
      }
      await h.advance(14999);
      assert.equal(call.options.signal.aborted, false);
      await h.advance(1);
      assert.equal(call.options.signal.aborted, true, `${method} ${stalled} bounded at 15s`);
      await (cancellation || pending);
      assert.equal(h.timers.size, 0);
      const writesBefore = h.writes.length;
      if (body) body.resolve(h.envelope(call, "done", {
        result: { action: DEVICE_ACTIONS.OTBR_PING, status: "success" },
      }));
      else h.reply(call, h.envelope(call));
      await flush();
      assert.equal(h.writes.length, writesBefore, "late request/body cannot publish after timeout");
      assert.equal(h.calls.filter((item) => item.options.method === "POST").length, 1);
    }
  }
  for (const deadline of [30, 600]) {
    for (const status of ["running", "cancelling"]) {
      const h = harness();
      h.element("device-diagnostics-attempts").value = deadline === 600 ? "10" : "1";
      h.element("device-diagnostics-timeout").value = deadline === 600 ? "60" : "1";
      h.respondWith((call) => {
        h.reply(call, h.envelope(call, status), call.options.method === "POST" ? 202 : 200);
      });
      const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
      await flush();
      assert.equal(JSON.parse(h.calls[0].options.body).deadlineSeconds, deadline);
      const budget = deadline * 1000 + 30000;
      await h.advance(budget - 1);
      assert.equal(h.state.invocation.active, true);
      await h.advance(1);
      await pending;
      assert.match(h.writes.at(-1).message, /local polling timeout.*server state uncertain/i);
      assert.equal(h.state.jobId, "job-A");
      assert.equal(h.timers.size, 0);
      assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 1);
      assert.equal(h.calls.filter((call) => !call.options.method).length, budget / 500);
    }
  }
  for (const malformed of ["json", "object", "missing-job", "action", "invocation", "status"]) {
    const h = harness();
    const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
    const payload = h.envelope(h.calls[0]);
    if (malformed === "json") {
      h.calls[0].resolve({ ok: true, status: 202, json: async () => { throw new SyntaxError(); } });
    } else {
      if (malformed === "missing-job") delete payload.job_id;
      if (malformed === "action") payload.action = "bad-action";
      if (malformed === "invocation") payload.invocationId = "other";
      if (malformed === "status") payload.status = "unknown";
      h.reply(h.calls[0], malformed === "object" ? [] : payload, 202);
    }
    await pending;
    assert.match(h.writes.at(-1).message, /protocol error.*server state uncertain/i);
    assert.equal(h.calls.length, 1);
    assert.equal(h.timers.size, 0);
    assert.equal(h.writes.some((write) => write.result), false);
    if (["action", "invocation", "status"].includes(malformed)) {
      assert.equal(h.state.jobId, "job-A", "parseable uncertain ID retained");
      assert.equal(h.element("btn-device-diagnostics-cancel").hidden, false);
    }
  }
  for (const malformed of ["json", "object", "job", "action", "invocation", "status",
    "done-no-result", "result-action", "result-status", "result-array", "non-json-http"]) {
    const h = harness();
    const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
    h.reply(h.calls[0], h.envelope(h.calls[0]), 202);
    await flush();
    const poll = h.calls[1], payload = h.envelope(poll);
    if (["json", "non-json-http"].includes(malformed)) {
      poll.resolve({ ok: malformed === "json", status: malformed === "json" ? 200 : 503,
        json: async () => { throw new SyntaxError(); } });
    } else {
      if (malformed === "job") payload.job_id = "other";
      if (malformed === "action") payload.action = "other";
      if (malformed === "invocation") payload.invocationId = "other";
      if (malformed === "status") payload.status = "unknown";
      if (malformed.startsWith("result-") || malformed === "done-no-result") {
        payload.status = "done";
        if (malformed !== "done-no-result") payload.result = {
          action: malformed === "result-action" ? "other" : payload.action,
          status: malformed === "result-status" ? "running" : "success",
        };
        if (malformed === "result-array") payload.result = [];
      }
      h.reply(poll, malformed === "object" ? null : payload);
    }
    await pending;
    assert.match(h.writes.at(-1).message,
      malformed === "non-json-http" ? /HTTP 503/ : /protocol error/);
    assert.equal(h.state.jobId, "job-A");
    assert.equal(h.writes.some((write) => write.result), false);
    assert.equal(h.timers.size, 0);
  }
  for (const status of ["success", "partial-success", "no-response", "no-addresses",
    "timed-out", "unsupported", "protocol-error", "transport-failure", "deadline-exceeded",
    "local-dispatch-failure", "accepted-for-transmission", "failed", "cancelled"]) {
    const h = harness();
    const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
    h.reply(h.calls[0], h.envelope(h.calls[0]), 202);
    await flush();
    const result = { action: DEVICE_ACTIONS.OTBR_PING, status };
    h.reply(h.calls[1], h.envelope(h.calls[1], "done", { result }));
    await pending;
    assert.deepEqual(h.writes.find((write) => write.result).result, result);
    assert.equal(h.state.jobId, null);
    assert.equal(h.timers.size, 0);
  }
  for (const terminal of ["done", "error", "cancelled"]) {
    for (const atSubmission of [false, true]) {
      const h = harness();
      const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
      if (!atSubmission) {
        h.reply(h.calls[0], h.envelope(h.calls[0]), 202);
        await flush();
      }
      const result = { action: DEVICE_ACTIONS.OTBR_PING,
        status: terminal === "done" ? "failed" : terminal === "error" ? "deadline-exceeded" : "cancelled" };
      h.reply(h.calls.at(-1), h.envelope(h.calls[0], terminal, { result }), atSubmission ? 202 : 200);
      await pending;
      assert.deepEqual(h.writes.find((write) => write.result).result, result);
      assert.equal(h.calls.length, atSubmission ? 1 : 2);
      assert.equal(h.timers.size, 0);
    }
  }
  {
    const h = harness();
    const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
    h.initDeviceDiagnostics();
    h.element("device-diagnostics-allow-sed").listeners.change();
    assert.equal(h.element("btn-device-diagnostics-ping").disabled, true,
      "consent changes cannot re-enable duplicate submission");
    await h.advance(14000);
    h.reply(h.calls[0], h.envelope(h.calls[0]), 202);
    await flush();
    let polls = 1;
    h.reply(h.calls.at(-1), h.envelope(h.calls[0]));
    h.respondWith((call) => {
      polls++;
      if (polls < 120) h.reply(call, h.envelope(call));
    });
    await flush();
    await h.advance(59999);
    assert.equal(h.state.invocation.active, true,
      "poll budget begins at acceptance, not submission");
    const stalled = h.calls.at(-1);
    assert.equal(stalled.options.signal.aborted, false);
    await h.advance(1);
    await pending;
    assert.equal(stalled.options.signal.aborted, true, "GET uses remaining overall budget");
    assert.equal(h.timers.size, 0);
  }
  for (const method of ["POST", "GET"]) {
    for (const error of ["network", "http", "invalid-json-200"]) {
      const h = harness();
      const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
      if (method === "GET") {
        h.reply(h.calls[0], h.envelope(h.calls[0]), 202);
        await flush();
      }
      const call = h.calls.at(-1);
      if (error === "network") call.reject(new TypeError("network unavailable"));
      else call.resolve({ ok: error !== "http", status: error === "http" ? 502 : 200,
        json: async () => { throw new SyntaxError(); } });
      await pending;
      assert.match(h.writes.at(-1).message, error === "network" ? /network unavailable/
        : error === "http" ? /HTTP 502/ : /protocol error/);
      assert.equal(h.writes.some((write) => write.result), false);
      assert.equal(h.timers.size, 0);
      assert.equal(h.calls.filter((item) => item.options.method === "POST").length, 1);
    }
  }
  {
    const h = harness();
    const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_RESET);
    h.selectDeviceDiagnosticsRecord(null);
    h.reply(h.calls[0], { ...h.envelope(h.calls[0]), action: "wrong" }, 202);
    await flush();
    const disposal = h.calls[1];
    assert.equal(disposal.options.method, "DELETE", "uncertain stale accepted ID disposed");
    disposal.reject(new Error("unreachable"));
    await pending;
    assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 1,
      "counter reset is never replayed");
    assert.equal(h.timers.size, 0);
  }
  {
    const h = harness();
    const pending = h.invokeDeviceDiagnostic(DEVICE_ACTIONS.OTBR_PING);
    h.reply(h.calls[0], h.envelope(h.calls[0]), 202);
    await flush();
    h.calls[1].reject(new TypeError("connection lost"));
    await pending;
    const cancellation = h.cancelDeviceDiagnostic();
    h.reply(h.calls.at(-1), h.envelope(h.calls[0], "cancelling"), 202);
    await flush();
    assert.equal(h.calls.at(-1).options.method, undefined,
      "explicit cancellation of retained job resumes bounded terminal observation");
    assert.equal(h.element("btn-device-diagnostics-ping").disabled, true);
    h.reply(h.calls.at(-1), h.envelope(h.calls[0], "cancelled"));
    await cancellation;
    assert.match(h.writes.at(-1).message, /server diagnostic cancelled/i);
    assert.equal(h.timers.size, 0);
    assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 1);
  }
  console.log(`device diagnostics UI execution tests passed (${scenarioCount} scenarios)`);
}