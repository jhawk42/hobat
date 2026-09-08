// Canonical Thread device fields, normalization, and identity helpers.

export const FIELD_DEFINITIONS = Object.freeze([
  { path: "extAddress", aliases: ["extaddr", "extMacAddr", "Extended MAC"], transform: "identifier" },
  { path: "omrIpv6Address", aliases: ["omrIpv6Addr", "omr_ipv6_addr"], transform: "identifier" },
  { path: "rloc16", aliases: ["RLOC16"], transform: "identifier" },
  { path: "eui", aliases: ["eui64", "EUI64"], transform: "identifier" },
  { path: "mode.fullThreadDevice", aliases: ["mode.deviceType", "mode.deviceTypeFTD"], transform: "boolean" },
  { path: "mode.fullNetworkData", aliases: ["mode.networkData"], transform: "boolean" },
  { path: "mode.rxOnWhenIdle", aliases: ["mode.rxOn", "mode.rx_on_when_idle"], transform: "boolean" },
  { path: "mode.device", aliases: [], transform: "identity" },
  { path: "isLeader", aliases: ["leader"], transform: "boolean" },
  { path: "isBorderRouter", aliases: ["br", "is_border_router"], transform: "boolean" },
  { path: "isRouter", aliases: ["is_router"], transform: "boolean" },
  { path: "isPrimaryBBR", aliases: [], transform: "boolean" },
  { path: "mleCounters.partIdChangesCount", aliases: ["mleCounters.partitionIdChanges"], transform: "number" },
  { path: "mleCounters.newParentCount", aliases: ["mleCounters.parentChanges"], transform: "number" },
  { path: "mleCounters.betterPartIdAttachAttemptsCount", aliases: ["mleCounters.betterPartitionAttachAttempts"], transform: "number" },
  { path: "id", aliases: [], transform: "identity" },
  { path: "routerId", aliases: ["router_id"], transform: "identity" },
  { path: "ipv6Addresses", aliases: ["ipv6_addrs"], transform: "stringArray" },
  { path: "role", aliases: [], transform: "identity" },
  { path: "type", aliases: [], transform: "identity" },
  { path: "threadVersion", aliases: ["thread_version"], transform: "identity" },
  { path: "threadStackVersion", aliases: ["thread_stack_version"], transform: "identity" },
  { path: "version", aliases: ["ver"], transform: "identity" },
  { path: "vendorName", aliases: ["vendor_name"], transform: "identity" },
  { path: "vendorModel", aliases: ["vendor_model"], transform: "identity" },
  { path: "vendorSwVersion", aliases: ["vendor_sw_version"], transform: "identity" },
  { path: "leaderData", aliases: ["leader_data"], transform: "identity" },
  { path: "connectivity", aliases: [], transform: "identity" },
  { path: "macCounters", aliases: ["mac_counters"], transform: "identity" },
  { path: "mleCounters", aliases: ["mle_counters"], transform: "identity" },
  { path: "timeStatistics", aliases: ["time_statistics"], transform: "identity" },
  { path: "route", aliases: ["route64", "route_data"], transform: "route" },
  { path: "children", aliases: [], transform: "relationship" },
  { path: "childTable", aliases: ["router_child_table"], transform: "relationship" },
  { path: "childIpv6Addresses", aliases: ["child_ipv6_addresses"], transform: "stringArray" },
  { path: "routerNeighbors", aliases: ["router_neighbor_table"], transform: "relationship" },
  { path: "rlocAddress", aliases: [], transform: "identifier" },
  { path: "mlEidIid", aliases: [], transform: "identity" },
  { path: "state", aliases: [], transform: "identity" },
  { path: "updated", aliases: [], transform: "identity" },
  { path: "created", aliases: [], transform: "identity" },
  { path: "hostname", aliases: [], transform: "identity" },
  { path: "routerCount", aliases: [], transform: "number" },
  { path: "hostsService", aliases: [], transform: "boolean" },
  { path: "baId", aliases: [], transform: "identity" },
  { path: "baState", aliases: [], transform: "identity" },
  { path: "brCounters", aliases: [], transform: "identity" },
  { path: "extPanId", aliases: ["ext_pan_id"], transform: "identifier" },
  { path: "networkName", aliases: ["network_name"], transform: "identity" },
  { path: "deviceLabel", aliases: ["device_label"], transform: "identity" },
  { path: "tlvValues", aliases: ["tlv_values"], transform: "identity" },
  { path: "lastAttemptResponded", aliases: ["last_attempt_responded"], transform: "number" },
  { path: "lastAttemptTlvDetailLevel", aliases: ["last_attempt_tlv_detail_level"], transform: "number" },
  { path: "networkDiagnosticStatus", aliases: ["network_diagnostic_status"], transform: "identity" },
  { path: "reachability", aliases: [], transform: "identity" },
  { path: "ping", aliases: [], transform: "identity" },
  { path: "totalChildren", aliases: ["total_children"], transform: "number" },
  { path: "totalLinks", aliases: ["total_links"], transform: "number" },
  { path: "totalLink1", aliases: ["total_link_1"], transform: "number" },
  { path: "totalLink2", aliases: ["total_link_2"], transform: "number" },
  { path: "totalLink3", aliases: ["total_link_3"], transform: "number" },
  { path: "links1", aliases: ["1_links"], transform: "identity" },
  { path: "links2", aliases: ["2_links"], transform: "identity" },
  { path: "links3", aliases: ["3_links"], transform: "identity" },
  { path: "error", aliases: ["_error"], transform: "identity" },
  { path: "_source_files", aliases: [], transform: "identity" },
  { path: "_merge_conflicts", aliases: [], transform: "identity" },
]);

export const EXT_ADDRESS_ALIASES = Object.freeze(["extAddress", "extaddr", "extMacAddr", "Extended MAC"]);
export const OMR_ADDRESS_ALIASES = Object.freeze(["omrIpv6Address", "omrIpv6Addr", "omr_ipv6_addr"]);
export const RLOC16_ALIASES = Object.freeze(["rloc16", "RLOC16"]);
export const TRANSPORT_FIELDS = Object.freeze(["data", "attributes", "relationships", "meta", "links", "included"]);

const PLACEHOLDER_EXT_ADDRESSES = new Set(["0000000000000000"]);
const ROUTE_ALIASES = Object.freeze({
  id_sequence: "idSequence",
  route_data: "routeData",
  route_id: "routeId",
  route_cost: "routeCost",
  link_quality_in: "linkQualityIn",
  link_quality_out: "linkQualityOut",
});

export const PREFERRED_FIELD_NAMES = Object.freeze(
  Object.fromEntries(
    FIELD_DEFINITIONS.flatMap((definition) => [
      [definition.path, definition.path],
      ...definition.aliases.map((alias) => [alias, definition.path]),
    ]),
  ),
);

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function cloneValue(value) {
  if (Array.isArray(value)) return value.map(cloneValue);
  if (isPlainObject(value)) {
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, cloneValue(child)]));
  }
  return value;
}

export function normalizeIdentifierText(value) {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

function firstIdentifier(record, aliases) {
  if (!isPlainObject(record)) return "";
  for (const alias of aliases) {
    const value = normalizeIdentifierText(record[alias]);
    if (value) return value;
  }
  return "";
}

export function getCanonicalExtAddress(record) {
  return firstIdentifier(record, EXT_ADDRESS_ALIASES);
}

export function getCanonicalOmrAddress(record) {
  return firstIdentifier(record, OMR_ADDRESS_ALIASES);
}

export function isPlaceholderOmrAddress(value) {
  const normalized = normalizeIdentifierText(value);
  const halves = normalized.split("::");
  if (halves.length > 2 || !normalized.includes(":")) return false;
  const groups = halves.flatMap((half) => half ? half.split(":") : []);
  if (!groups.every((group) => /^0{1,4}$/.test(group))) return false;
  return halves.length === 2 ? groups.length < 8 : groups.length === 8;
}

export function getCanonicalRloc16(record) {
  return firstIdentifier(record, RLOC16_ALIASES);
}

export function isPlaceholderExtAddress(value) {
  const normalized = normalizeIdentifierText(value);
  if (!normalized || /^(found|offline|unknown)-/.test(normalized)) return true;
  return PLACEHOLDER_EXT_ADDRESSES.has(normalized.replace(/[:.-]/g, ""));
}

export function canonicalizeExtAddress(value) {
  const normalized = normalizeIdentifierText(value);
  if (/^[0-9a-f]{16}$/.test(normalized)) return normalized;
  const separator = normalized.match(/[:.-]/)?.[0];
  const octets = separator ? normalized.split(separator) : [];
  if (octets.length === 8 && octets.every((octet) => /^[0-9a-f]{2}$/.test(octet))) return octets.join("");
  return "";
}

function getPath(record, path) {
  let current = record;
  for (const part of path.split(".")) {
    if (!isPlainObject(current) || !Object.prototype.hasOwnProperty.call(current, part)) {
      return { found: false, value: undefined };
    }
    current = current[part];
  }
  return { found: true, value: current };
}

function setPath(record, path, value) {
  const parts = path.split(".");
  let current = record;
  parts.slice(0, -1).forEach((part) => {
    if (!isPlainObject(current[part])) current[part] = {};
    current = current[part];
  });
  current[parts.at(-1)] = value;
}

function deletePath(record, path) {
  const parts = path.split(".");
  let current = record;
  const parents = [];
  for (const part of parts.slice(0, -1)) {
    if (!isPlainObject(current[part])) return;
    parents.push([current, part]);
    current = current[part];
  }
  delete current[parts.at(-1)];
  parents.reverse().forEach(([parent, part]) => {
    if (isPlainObject(parent[part]) && Object.keys(parent[part]).length === 0) delete parent[part];
  });
}

function toBoolean(value) {
  if (typeof value === "boolean") return value;
  if (value === 0 || value === 1) return Boolean(value);
  if (typeof value === "string") {
    const text = value.trim().toLowerCase();
    if (["1", "true", "yes", "on"].includes(text)) return true;
    if (["0", "false", "no", "off"].includes(text)) return false;
  }
  return value;
}

function toNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return value;
}

function normalizeRoute(value) {
  if (!isPlainObject(value)) return cloneValue(value);
  return Object.fromEntries(
    Object.entries(value).map(([key, child]) => {
      const preferred = ROUTE_ALIASES[key] ?? key;
      if (preferred === "routeData" && Array.isArray(child)) {
        return [preferred, child.map(normalizeRoute)];
      }
      return [preferred, isPlainObject(child) ? normalizeRoute(child) : cloneValue(child)];
    }),
  );
}

function transformValue(transform, value, source) {
  if (transform === "identifier") {
    const normalized = normalizeIdentifierText(value);
    return normalized || cloneValue(value);
  }
  if (transform === "boolean") return toBoolean(value);
  if (transform === "number") return toNumber(value);
  if (transform === "route") return normalizeRoute(value);
  if (transform === "relationship" && Array.isArray(value)) {
    return value.map((item) => isPlainObject(item) ? normalizeInputRecord(item, { source }) : cloneValue(item));
  }
  if (transform === "stringArray" && Array.isArray(value)) {
    return value.map((item) => typeof item === "string" ? normalizeIdentifierText(item) : cloneValue(item));
  }
  return cloneValue(value);
}

export function normalizeInputRecord(record, options = {}) {
  if (!isPlainObject(record)) return record;
  const result = cloneValue(record);
  TRANSPORT_FIELDS.forEach((field) => delete result[field]);

  FIELD_DEFINITIONS.forEach((definition) => {
    const candidates = [definition.path, ...definition.aliases];
    let selected;
    for (const candidate of candidates) {
      const found = getPath(result, candidate);
      if (found.found) {
        selected = { path: candidate, value: found.value };
        break;
      }
    }
    if (!selected) return;
    setPath(result, definition.path, transformValue(definition.transform, selected.value, options.source));
    candidates.forEach((candidate) => {
      if (candidate !== definition.path) deletePath(result, candidate);
    });
  });

  if (isPlainObject(result.mode) && !("device" in result.mode) && typeof result.mode.fullThreadDevice === "boolean") {
    result.mode.device = result.mode.fullThreadDevice ? "FTD" : "MTD";
  }
  return result;
}

function matterCompositeIdentity(record) {
  const matter = isPlainObject(record?.matter) ? record.matter : record;
  const explicitMatterId = normalizeIdentifierText(matter?.matterId);
  const explicitMatch = explicitMatterId.match(
    /^([0-9a-f]{16})-([0-9a-f]{16})$/,
  );
  if (explicitMatch) return `${explicitMatch[1]}|${explicitMatch[2]}`;
  const fabricValue = matter?.compressedFabricId ?? matter?.fabricId;
  const nodeValue = matter?.nodeId;
  const normalizeMatterComponent = (value) => {
    if (typeof value === "number" && Number.isSafeInteger(value) && value >= 0) {
      return value.toString(16).padStart(16, "0");
    }
    const text = normalizeIdentifierText(value).replace(/^0x/, "");
    return /^[0-9a-f]{1,16}$/.test(text) ? text.padStart(16, "0") : "";
  };
  const directFabric = normalizeMatterComponent(fabricValue);
  const directNode = normalizeMatterComponent(nodeValue);
  if (directFabric && directNode) return `${directFabric}|${directNode}`;

  const scope = String(record?.scope ?? "").trim().toLowerCase();
  if (scope !== "_matter._tcp.local.") return "";
  const properties = record?.serviceInfo?.properties ?? record?.service_info?.properties;
  if (!isPlainObject(properties)) return "";
  const fabric = normalizeIdentifierText(properties.FabricID_compressed?.decoded);
  const node = normalizeIdentifierText(properties.NodeID?.decoded);
  return fabric && node ? `${fabric}|${node}` : "";
}

export function getDeviceIdentityKeys(record, strategy = "by-identity", options = {}) {
  void options;
  const keys = [];
  if (strategy === "by-identity") {
    const extAddress = getCanonicalExtAddress(record);
    if (extAddress && !isPlaceholderExtAddress(extAddress)) keys.push(`extAddress:${extAddress}`);
    const omrAddress = getCanonicalOmrAddress(record);
    if (omrAddress && !isPlaceholderOmrAddress(omrAddress)) keys.push(`omrIpv6Address:${omrAddress}`);
    const matterIdentity = matterCompositeIdentity(record);
    if (matterIdentity) keys.push(`matterFabricNode:${matterIdentity}`);
  }
  const rloc16 = getCanonicalRloc16(record);
  if (rloc16) keys.push(`rloc16:${rloc16}`);
  return [...new Set(keys)];
}
