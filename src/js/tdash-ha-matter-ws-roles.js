import { FIELD_DEFINITIONS } from "./tdash-device-fields.js";

export const HA_MATTER_ROLE_POLICY = "ha-matter-ws";
export const HA_MATTER_ROLE_FIELDS = Object.freeze([
  "isBorderRouter",
  "isRouter",
  "isLeader",
  "isReed",
]);

const ROLE_ALIASES = new Map(
  FIELD_DEFINITIONS
    .filter(({ path }) => HA_MATTER_ROLE_FIELDS.includes(path))
    .map(({ path, aliases }) => [path, aliases]),
);
const HA_MATTER_ADAPTORS = new Set([
  "ha-matter-ws",
  "ha-matter-ws-native-thread",
  "ha-matter-ws-network-topology",
  "ha-matter-ws-merge-topology",
]);
const HA_MATTER_FILES = Object.freeze({
  "td-ha-matter-ws-devices-fetch-all.json": "commissioned-device",
  "td-ha-matter-ws-diagnostics-fetch-all.json": "commissioned-diagnostic",
  "td-ha-matter-ws-mesh-diagnostics-fetch-all.json": "commissioned-diagnostic",
  "td-ha-matter-ws-topology.json": "commissioned-topology",
  "td-ha-matter-ws-dashboard.json": "dashboard",
  "td-ha-matter-ws-network-topology.json": "native-topology",
  "td-ha-matter-ws-thread-border-routers.json": "border-router-inventory",
});
const DASHBOARD_EXTRACTOR_CONTEXTS = Object.freeze({
  "ha-matter-ws-diagnostics": "commissioned-diagnostic",
  "ha-matter-ws-mesh-diagnostics": "commissioned-diagnostic",
  "ha-matter-ws-topology": "commissioned-topology",
});
const THREAD_ROLE_FACTS = Object.freeze({
  leader: { isRouter: true, isLeader: true, isReed: false },
  router: { isRouter: true, isLeader: false, isReed: false },
  reed: { isRouter: false, isLeader: false, isReed: true },
  end_device: { isRouter: false, isLeader: false, isReed: false },
  sleepy_end_device: { isRouter: false, isLeader: false, isReed: false },
  Leader: { isRouter: true, isLeader: true, isReed: false },
  Router: { isRouter: true, isLeader: false, isReed: false },
  Reed: { isRouter: false, isLeader: false, isReed: true },
  EndDevice: { isRouter: false, isLeader: false, isReed: false },
  SleepyEndDevice: { isRouter: false, isLeader: false, isReed: false },
});

function contextForFile(filename, extractorId) {
  const context = HA_MATTER_FILES[filename];
  if (context === "dashboard") {
    return DASHBOARD_EXTRACTOR_CONTEXTS[extractorId] ?? null;
  }
  if (context === "native-topology" && extractorId !== "ha-matter-ws-network-topology")
    return null;
  if (context === "border-router-inventory" && extractorId !== "ha-matter-ws-border-routers")
    return null;
  return context ?? null;
}

export function isHaMatterRolePolicyEligible(entry) {
  if (
    entry?.source !== "ha-matter-ws"
    || !HA_MATTER_ADAPTORS.has(entry.adaptor)
    || !Array.isArray(entry.files)
    || entry.files.length === 0
  ) return false;

  return entry.files.every((filename, index) => {
    const extractorId = entry.mergeStrategy === "none"
      ? entry.rowExtractor
      : entry.mergeRowExtractors?.[index];
    return contextForFile(filename, extractorId) !== null;
  });
}

export function getHaMatterRoleContext(entry, index = 0) {
  if (!isHaMatterRolePolicyEligible(entry)) return null;
  const extractorId = entry.mergeStrategy === "none"
    ? entry.rowExtractor
    : entry.mergeRowExtractors?.[index];
  return contextForFile(entry.files[index], extractorId);
}

export function isHaMatterRoleContextAllowed(filename, context) {
  if (filename === "td-ha-matter-ws-dashboard.json") {
    return Object.values(DASHBOARD_EXTRACTOR_CONTEXTS).includes(context);
  }
  return HA_MATTER_FILES[filename] === context;
}

function appendRawConflict(record, path, current, incoming) {
  const conflicts = Array.isArray(record._merge_conflicts)
    ? record._merge_conflicts
    : [];
  const duplicate = conflicts.some((entry) =>
    entry?.path === path
    && entry.current === current
    && entry.incoming === incoming
    && typeof entry.current === "boolean"
    && typeof entry.incoming === "boolean");
  if (!duplicate && conflicts.length < 20) {
    record._merge_conflicts = [
      ...conflicts,
      { path, current, incoming },
    ];
  } else if (!Array.isArray(record._merge_conflicts)) {
    record._merge_conflicts = conflicts;
  }
}

function roleEvidence(row, context) {
  if (context === "canonical-only") return { isThread: false };
  if (context === "commissioned-device") {
    const thread = row.thread;
    return {
      isThread: thread !== null && typeof thread === "object" && !Array.isArray(thread),
      role: thread?.routingRole,
    };
  }
  if (context === "native-topology") {
    return {
      isThread: row.network_type === "thread",
      role: row.network_type === "thread" ? row.role : undefined,
      borderRouter: row.kind === "border_router",
    };
  }
  if (context === "border-router-inventory") {
    return { isThread: false, inventoryRouter: true };
  }
  if (context === "commissioned-topology" && row.relationshipOnly === true) {
    return { isThread: false };
  }
  return {
    isThread: true,
    role: row.role ?? row.thread?.routingRole,
  };
}

export function normalizeHaMatterRoleRecord(row, context) {
  if (!row || typeof row !== "object" || Array.isArray(row)) return row;
  const result = { ...row };
  const thread = context === "commissioned-device"
    && result.thread !== null
    && typeof result.thread === "object"
    && !Array.isArray(result.thread)
    ? { ...result.thread }
    : null;
  if (thread) {
    HA_MATTER_ROLE_FIELDS.forEach((field) => {
      [field, ...(ROLE_ALIASES.get(field) ?? [])].forEach((key) => {
        if (Object.hasOwn(thread, key) && typeof thread[key] !== "boolean")
          delete thread[key];
      });
    });
    result.thread = thread;
  }
  const explicitRecord = thread ? { ...thread, ...result } : result;
  const explicit = new Map();
  const conflicts = new Map(HA_MATTER_ROLE_FIELDS.map((field) => [field, []]));
  if (result.leaderEvidence === "leader-router-id-match") {
    delete result.isLeader;
    delete result.leaderEvidence;
    delete explicitRecord.isLeader;
    delete explicitRecord.leaderEvidence;
  }
  HA_MATTER_ROLE_FIELDS.forEach((field) => {
    const keys = [field, ...(ROLE_ALIASES.get(field) ?? [])];
    const values = keys
      .filter((key) => typeof explicitRecord[key] === "boolean")
      .map((key) => explicitRecord[key]);
    if (values.length) {
      explicit.set(field, values[0]);
      conflicts.get(field).push(
        ...values.slice(1).filter((value) => value !== values[0])
          .map((value) => [values[0], value]),
      );
    }
    keys.forEach((key) => {
      if (Object.hasOwn(result, key) && typeof result[key] !== "boolean")
        delete result[key];
    });
  });

  const evidence = roleEvidence(result, context);
  const normalizedRole = typeof evidence.role === "string"
    ? evidence.role.trim()
    : "";
  const roleFacts = evidence.isThread ? THREAD_ROLE_FACTS[normalizedRole] : undefined;
  const derived = {};
  if (evidence.borderRouter === true || evidence.inventoryRouter === true) {
    derived.isBorderRouter = true;
    derived.isRouter = true;
  }
  if (evidence.inventoryRouter !== true && roleFacts) {
    if (typeof derived.isRouter === "boolean" && derived.isRouter !== roleFacts.isRouter) {
      conflicts.get("isRouter").push([derived.isRouter, roleFacts.isRouter]);
    } else {
      derived.isRouter = roleFacts.isRouter;
    }
    derived.isLeader = roleFacts.isLeader;
    derived.isReed = roleFacts.isReed;
  }

  HA_MATTER_ROLE_FIELDS.forEach((field) => {
    const explicitValue = explicit.get(field);
    const derivedValue = derived[field];
    if (
      typeof explicitValue === "boolean"
      && typeof derivedValue === "boolean"
      && explicitValue !== derivedValue
    ) conflicts.get(field).push([explicitValue, derivedValue]);
    const value = typeof explicitValue === "boolean" ? explicitValue : derivedValue;
    if (typeof value === "boolean") result[field] = value;
    else delete result[field];
  });

  HA_MATTER_ROLE_FIELDS.forEach((field) => {
    conflicts.get(field).forEach(([current, incoming]) => {
      appendRawConflict(result, field, current, incoming);
    });
  });
  return result;
}

function mapRoleRows(value, context) {
  return Array.isArray(value)
    ? value.map((row) => normalizeHaMatterRoleRecord(row, context))
    : value;
}

function mapRoleRowsProperty(payload, property, context) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  return Array.isArray(payload[property])
    ? { ...payload, [property]: mapRoleRows(payload[property], context) }
    : payload;
}

export function normalizeHaMatterRolePayload(payload, filename) {
  const context = HA_MATTER_FILES[filename];
  if (!context) return payload;
  if (Array.isArray(payload)) {
    return mapRoleRows(payload, context);
  }

  if (context === "dashboard") {
    let result = mapRoleRowsProperty(payload, "diagnostics", "commissioned-diagnostic");
    result = mapRoleRowsProperty(result, "meshDiagnostics", "commissioned-diagnostic");
    return mapRoleRowsProperty(result, "topology", "commissioned-topology");
  }
  if (context === "commissioned-diagnostic") {
    const property = filename.includes("mesh-diagnostics")
      ? "meshDiagnostics"
      : "diagnostics";
    return mapRoleRowsProperty(payload, property, context);
  }
  if (context === "commissioned-topology") {
    return mapRoleRowsProperty(payload, "topology", context);
  }
  if (context === "native-topology") {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
    const topology = payload.topology;
    if (!topology || typeof topology !== "object" || Array.isArray(topology)) return payload;
    return {
      ...payload,
      topology: mapRoleRowsProperty(topology, "nodes", context),
    };
  }
  if (context === "border-router-inventory")
    return mapRoleRowsProperty(payload, "borderRouters", context);
  return payload;
}
