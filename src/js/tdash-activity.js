const ACTIVITY_LIMIT = 200;
const METADATA_MAX_DEPTH = 4;
const METADATA_MAX_KEYS = 20;
const METADATA_MAX_ARRAY = 20;
const STRING_MAX_LENGTH = 256;
const SAFE_QUERY_NAMES = new Set([
  "assessment",
  "dataset",
  "grouped",
  "limit",
  "network",
  "offset",
  "scope",
  "status",
]);
const TRACKING_MODES = new Set(["full", "terminal-only", "silent"]);

const activityEntries = [];
const activitySubscribers = new Set();
let activitySequence = 0;

function boundedString(value) {
  const text = String(value);
  return text.length <= STRING_MAX_LENGTH
    ? text
    : `${text.slice(0, STRING_MAX_LENGTH - 1)}\u2026`;
}

export function sanitizeActivityMetadata(value, depth = 0) {
  if (value == null || typeof value === "boolean" || typeof value === "number") {
    return value;
  }
  if (typeof value === "string") return boundedString(value);
  if (depth >= METADATA_MAX_DEPTH) return "[truncated]";
  if (Array.isArray(value)) {
    return value.slice(0, METADATA_MAX_ARRAY)
      .map((item) => sanitizeActivityMetadata(item, depth + 1));
  }
  if (typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).slice(0, METADATA_MAX_KEYS).map(([key, item]) => [
        boundedString(key),
        sanitizeActivityMetadata(item, depth + 1),
      ]),
    );
  }
  return boundedString(value);
}

function routeTemplate(pathname) {
  const templates = [
    [/^\/api\/job\/[^/]+$/, "/api/job/{job_id}"],
    [/^\/api\/device-action-jobs\/[^/]+$/, "/api/device-action-jobs/{job_id}"],
    [/^\/api\/device\/[^/]+$/, "/api/device/{extAddress}"],
    [/^\/api\/health\/devices\/[^/]+$/, "/api/health/devices/{device_id}"],
  ];
  return templates.find(([pattern]) => pattern.test(pathname))?.[1] ?? pathname;
}

export function normalizeActivityRoute(input) {
  let url;
  try {
    url = new URL(String(input), "http://hobat.local/");
  } catch {
    return "invalid-url";
  }
  const query = new URLSearchParams();
  [...url.searchParams.entries()]
    .filter(([name]) => SAFE_QUERY_NAMES.has(name))
    .slice(0, METADATA_MAX_KEYS)
    .forEach(([name, value]) => query.append(name, boundedString(value)));
  const suffix = query.toString();
  return boundedString(`${routeTemplate(url.pathname)}${suffix ? `?${suffix}` : ""}`);
}

function failureCategory(error) {
  if (error?.name === "AbortError") return "aborted";
  if (error instanceof TypeError) return "network";
  return "request-failed";
}

export function recordActivity(entry) {
  const normalized = Object.freeze({
    id: entry.id ?? `activity-${++activitySequence}`,
    timestamp: entry.timestamp ?? Date.now(),
    category: boundedString(entry.category ?? "ui"),
    phase: boundedString(entry.phase ?? "changed"),
    message: boundedString(entry.message ?? "Activity changed"),
    ...(entry.method ? { method: boundedString(entry.method).toUpperCase() } : {}),
    ...(entry.route ? { route: normalizeActivityRoute(entry.route) } : {}),
    ...(Number.isInteger(entry.status) ? { status: entry.status } : {}),
    ...(Number.isFinite(entry.durationMs)
      ? { durationMs: Math.max(0, Math.round(entry.durationMs)) }
      : {}),
    ...(entry.requestId ? { requestId: boundedString(entry.requestId) } : {}),
    ...(entry.jobId ? { jobId: boundedString(entry.jobId) } : {}),
    ...(entry.metadata ? { metadata: sanitizeActivityMetadata(entry.metadata) } : {}),
  });
  activityEntries.push(normalized);
  if (activityEntries.length > ACTIVITY_LIMIT) {
    activityEntries.splice(0, activityEntries.length - ACTIVITY_LIMIT);
  }
  activitySubscribers.forEach((subscriber) => subscriber(normalized));
  return normalized;
}

export function getActivityEntries() {
  return [...activityEntries];
}

export function clearActivityEntries() {
  activityEntries.length = 0;
  activitySubscribers.forEach((subscriber) => subscriber(null));
}

export function subscribeActivity(subscriber) {
  activitySubscribers.add(subscriber);
  return () => activitySubscribers.delete(subscriber);
}

export async function trackedFetch(input, options = {}, activityMode = "full") {
  if (!TRACKING_MODES.has(activityMode)) {
    throw new TypeError(`Unknown activity mode: ${activityMode}`);
  }
  const method = String(options.method ?? "GET").toUpperCase();
  const route = normalizeActivityRoute(input);
  const requestId = globalThis.crypto?.randomUUID?.()
    ?? `request-${Date.now()}-${++activitySequence}`;
  const startedAt = Date.now();
  if (activityMode === "full") {
    recordActivity({
      category: "http",
      phase: "started",
      message: "HTTP request started",
      method,
      route,
      requestId,
    });
  }
  try {
    const response = await fetch(input, options);
    if (activityMode !== "silent") {
      recordActivity({
        category: "http",
        phase: response.ok ? "completed" : "failed",
        message: response.ok ? "HTTP request completed" : "HTTP request failed",
        method,
        route,
        status: response.status,
        durationMs: Date.now() - startedAt,
        requestId,
        metadata: response.ok ? undefined : { failureCategory: "http" },
      });
    }
    return response;
  } catch (error) {
    if (activityMode !== "silent") {
      recordActivity({
        category: "http",
        phase: error?.name === "AbortError" ? "cancelled" : "failed",
        message: error?.name === "AbortError" ? "HTTP request cancelled" : "HTTP request failed",
        method,
        route,
        durationMs: Date.now() - startedAt,
        requestId,
        metadata: { failureCategory: failureCategory(error) },
      });
    }
    throw error;
  }
}
