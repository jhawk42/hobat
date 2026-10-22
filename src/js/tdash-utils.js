import {
  DEVICE_DETAILS_SECTIONS,
} from "./tdash-constants.js";
import {
  getFieldNameCandidates,
  getPreferredFieldPath,
  normalizeNestedMetricFields,
  getCanonicalExtAddress,
  getCanonicalOmrAddress,
  getCanonicalRloc16 as getDeviceCanonicalRloc16,
  normalizeIdentifierText,
  normalizeInputRecord,
} from "./tdash-device-fields.js";

// ── Primitive type helpers ────────────────────────────────────────────────────

export function toText(value) {
  return value === undefined || value === null ? "" : String(value).trim();
}

export function toFiniteNumber(value) {
  if (Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value.trim()) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

// ── Canonical identity helpers ────────────────────────────────────────────────

export function canonicalIdText(value) {
  return normalizeIdentifierText(value);
}

export function getCanonicalRloc16(row) {
  return getDeviceCanonicalRloc16(row);
}

export function getCanonicalExtaddr(row) {
  return getCanonicalExtAddress(row);
}

export function getCanonicalOmrIpv6Address(row) {
  return getCanonicalOmrAddress(row);
}

// ── Field-name normalisation helpers ─────────────────────────────────────────

function _getOwnPropertyValueByAlias(obj, fieldName) {
  for (const candidate of getFieldNameCandidates(fieldName)) {
    if (Object.prototype.hasOwnProperty.call(obj, candidate)) {
      return obj[candidate];
    }
  }
  return undefined;
}

export function getPreferredFieldName(fieldName) {
  return getPreferredFieldPath(fieldName);
}

/**
 * Canonicalizes route containers to row.route.routeData shape.
 *
 * Supported input shapes:
 * - row.route_data = { id_sequence, route_data: [...] }
 * - row.route = { idSequence, routeData: [...] }
 * - mixed snake_case / camelCase route entry fields
 *
 * @param {object} row
 * @param {object} [options]
 * @param {boolean} [options.canonicalizeRouteContainer=false]
 * @param {boolean} [options.dropLegacyRouteData=false]
 * @returns {object}
 */
export function normalizeRouteContainer(row, options = {}) {
  if (!isPlainObject(row)) return row;

  const canonicalizeRouteContainer =
    options.canonicalizeRouteContainer === true;
  const dropLegacyRouteData = options.dropLegacyRouteData === true;

  if (!canonicalizeRouteContainer && !dropLegacyRouteData) return row;

  const hasLegacyRouteContainer = isPlainObject(row.route_data);
  const hasRouteContainer = isPlainObject(row.route);

  if (!hasLegacyRouteContainer && !hasRouteContainer) {
    if (!dropLegacyRouteData) return row;
    if (!Object.prototype.hasOwnProperty.call(row, "route_data")) return row;
    const cloned = { ...row };
    delete cloned.route_data;
    return cloned;
  }

  let result = { ...row };

  if (canonicalizeRouteContainer) {
    const routeSource = hasRouteContainer ? { ...row.route } : {};

    if (hasLegacyRouteContainer) {
      Object.entries(row.route_data).forEach(([key, value]) => {
        if (!(key in routeSource)) routeSource[key] = value;
      });
    }

    const normalizedRoute = normalizeInputRecord({ route: routeSource }).route;
    if (routeSource.routeData !== undefined && routeSource.route_data !== undefined) {
      normalizedRoute.routeData = normalizeInputRecord({ route: { routeData: routeSource.routeData } }).route.routeData;
    }
    if (routeSource.idSequence !== undefined && routeSource.id_sequence !== undefined) {
      normalizedRoute.idSequence = routeSource.idSequence;
    }

    result.route = normalizedRoute;
  }

  if (dropLegacyRouteData) {
    delete result.route_data;
  }

  return result;
}

/**
 * Normalizes field names for objects within an array (e.g., neighbor/child tables).
 * Normalizes each object and handles percentage field conversion.
 * 
 * For fields ending with "_pct", if the source value is a decimal (0-1), it's
 * converted to percentage (0-100). This ensures REST API decimal error rates
 * (e.g., 0.061) are converted to percentages (6.1) to match filter thresholds.
 * 
 * @param {Array} arr - Array of objects to normalize
 * @returns {Array} New array with normalized objects
 */
export function normalizeNestedArrayFields(arr) {
  if (!Array.isArray(arr)) return arr;
  return arr.map(item => {
    if (!isPlainObject(item)) return item;
    const normalized = normalizeNestedMetricFields(normalizeInputRecord(item));
    
    // Handle percentage field conversion for link quality metrics
    // If a canonical field ends with _pct and its value is decimal (0-1), multiply by 100
    Object.keys(normalized).forEach(key => {
      if (key.endsWith('_pct') && typeof normalized[key] === 'number') {
        const val = normalized[key];
        // If value is between 0 and 1 (decimal), convert to percentage
        if (val >= 0 && val <= 1) {
          normalized[key] = val * 100;
        }
      }
    });
    
    return normalized;
  });
}

// ── Mode/device-type derivation ───────────────────────────────────────────────

/**
 * Derives the canonical mode.device value ("FTD" or "MTD") from whichever
 * representation is present in `row`, trying five sources in priority order.
 * Returns "" when the device type cannot be determined.
 * Mirrors derive_mode_device() in merge_dataset.py.
 */
export function deriveModeDevice(row) {
  // 1. Explicit "mode.device" flat key
  const modeDeviceFlat = row?.["mode.device"];
  if (typeof modeDeviceFlat === "string" && modeDeviceFlat.trim()) {
    const v = modeDeviceFlat.trim().toUpperCase();
    if (v === "FTD" || v === "MTD") return v;
  }

  const mode = row?.mode;
  if (isPlainObject(mode)) {
    // 2. mode.device string
    const modeDevice = mode.device;
    if (typeof modeDevice === "string" && modeDevice.trim()) {
      const v = modeDevice.trim().toUpperCase();
      if (v === "FTD" || v === "MTD") return v;
    }
    // 3. mode.deviceTypeFTD boolean (REST API)
    if (typeof mode.deviceTypeFTD === "boolean") {
      return mode.deviceTypeFTD ? "FTD" : "MTD";
    }
    // 4. mode.device_type numeric
    if (typeof mode.device_type === "number") {
      return mode.device_type !== 0 ? "FTD" : "MTD";
    }
  }

  // 5. Role string
  const role = row?.role ?? row?.Role;
  if (typeof role === "string") {
    const r = role.trim().toLowerCase();
    if (r === "router" || r === "border router") return "FTD";
    if (r === "child") return "MTD";
  }

  // 6. Type string
  const nodeType = row?.type;
  if (typeof nodeType === "string") {
    const t = nodeType.trim().toLowerCase();
    if (t === "router" || t === "border router") return "FTD";
    if (t.includes("child")) return "MTD";
  }

  return "";
}

// ── OMR IPv6 auto-discovery ───────────────────────────────────────────────────

/**
 * Attempts to derive `omr_ipv6_addr` by prefix-matching entries in
 * `row.ipv6_addrs` against `omrPrefix`.  Returns the matching address
 * (lowercased) or "" when not found or `omrPrefix` is empty.
 * Mirrors the ipv6_addrs loop in normalize_identifiers() in merge_dataset.py.
 */
export function getOmrIpv6FromIpv6Addrs(row, omrPrefix) {
  if (!omrPrefix || typeof omrPrefix !== "string") return "";
  const prefix = omrPrefix.toLowerCase();
  const addrs = row?.ipv6_addrs;
  if (!Array.isArray(addrs)) return "";
  for (const addr of addrs) {
    if (typeof addr === "string" && addr.toLowerCase().startsWith(prefix)) {
      return addr.toLowerCase();
    }
  }
  return "";
}

function getCanonicalRloc16FromMacAddr(row) {
  const macAddr = row?.macAddr;
  const macAddrNumber = toFiniteNumber(macAddr);
  if (!Number.isFinite(macAddrNumber)) return "";
  return `0x${Math.trunc(macAddrNumber).toString(16).padStart(4, "0")}`;
}

const THREAD_RLOC16_ADDRESS_PREFIX = ":0:ff:fe00:";
const THREAD_BORDER_ROUTER_SERVICE_ANYCAST_SUFFIX_START = "fc10";
const THREAD_BORDER_ROUTER_SERVICE_ANYCAST_SUFFIX_END = "fc1f";

function isThreadBorderRouterServiceAnycastSuffix(suffix) {
  return (
    typeof suffix === "string" &&
    suffix >= THREAD_BORDER_ROUTER_SERVICE_ANYCAST_SUFFIX_START &&
    suffix <= THREAD_BORDER_ROUTER_SERVICE_ANYCAST_SUFFIX_END
  );
}

/**
 * Mirrors util_network.is_border_router_from_ipv6_addrs() in Python.
 *
 * Thread Border Routers advertise mesh-local Service Anycast addresses whose
 * last hextet falls in the fc10-fc1f range. In the existing Python path, the
 * BR heuristic also requires a mesh-local/RLOC16-style address pattern. For
 * the browser path we mirror that existing heuristic using the same RLOC16
 * address infix check that appears in current dataset snapshots.
 */
function isBorderRouterFromIpv6Addresses(ipv6Addresses) {
  if (!Array.isArray(ipv6Addresses)) return false;
  return ipv6Addresses.some((addr) => {
    if (typeof addr !== "string") return false;
    const lowered = addr.toLowerCase();
    if (!lowered.includes(THREAD_RLOC16_ADDRESS_PREFIX)) return false;
    const suffix = lowered.split(":").at(-1) || "";
    return isThreadBorderRouterServiceAnycastSuffix(suffix);
  });
}

function enrichRouterIdentityHints(row) {
  if (!isPlainObject(row)) return row;

  const rloc16 = toText(row.rloc16) || getCanonicalRloc16FromMacAddr(row);
  if (rloc16 && !row.rloc16) row.rloc16 = rloc16;

  const rloc16Text = toText(row.rloc16).toLowerCase();
  const isRouter = rloc16Text.endsWith("00");
  if (isRouter) {
    row.isRouter = true;
    if (!toText(row.role)) row.role = "router";
    if (!toText(row.type)) row.type = "router";
  }

  const ipv6Addresses = Array.isArray(row.ipv6Addresses)
    ? row.ipv6Addresses
    : (Array.isArray(row.ipv6_addrs) ? row.ipv6_addrs : []);
  const isBorderRouter = isBorderRouterFromIpv6Addresses(ipv6Addresses);
  if (isBorderRouter) {
    row.isBorderRouter = true;
    row.isRouter = true;
    row.role = "border router";
    if (!toText(row.type)) row.type = "border router";
  }

  return row;
}

// ── Row normalisation helpers ─────────────────────────────────────────────────

export function normalizeRowMergeAliases(row, options = {}) {
  if (!isPlainObject(row)) return row;
  let normalized = normalizeInputRecord(row, options);
  const serviceInfo = normalized.serviceInfo ?? normalized.service_info;
  if (isPlainObject(serviceInfo)) {
    const properties = isPlainObject(serviceInfo.properties)
      ? Object.fromEntries(
        Object.entries(serviceInfo.properties).map(([key, value]) => [
          key === "FabricID_compressed" ? "fabricIdCompressed" : (key === "NodeID" ? "nodeId" : key),
          value,
        ]),
      )
      : serviceInfo.properties;
    normalized = {
      ...normalized,
      serviceInfo: { ...serviceInfo, properties },
    };
    delete normalized.service_info;
  }
  // Step 2: canonical identity fields
  const extaddr = getCanonicalExtaddr(normalized);
  let omrIpv6Addr = getCanonicalOmrIpv6Address(normalized);
  if (extaddr) {
    if (!normalized.extAddress) normalized.extAddress = extaddr;
  }
  if (!omrIpv6Addr && options.omrPrefix) {
    omrIpv6Addr = getOmrIpv6FromIpv6Addrs(normalized, options.omrPrefix);
  }
  if (omrIpv6Addr) {
    if (!normalized.omrIpv6Address) normalized.omrIpv6Address = omrIpv6Addr;
  }
  // Step 3: derive mode.device (FTD/MTD) when not already set
  const existingModeDevice = normalized?.mode?.device ?? normalized?.["mode.device"];
  if (!existingModeDevice) {
    const derived = deriveModeDevice(normalized);
    if (derived) {
      if (isPlainObject(normalized.mode)) {
        normalized = { ...normalized, mode: { ...normalized.mode, device: derived } };
      } else {
        normalized["mode.device"] = derived;
      }
    }
  }
  // Step 4: optional route container canonicalization (route_data -> route.routeData)
  normalized = normalizeRouteContainer(normalized, options);
  return normalized;
}

export function normalizeDatasetPayload(value, options = {}) {
  if (Array.isArray(value)) {
    return value.map((item) => normalizeDatasetPayload(item, options));
  }
  if (isPlainObject(value)) {
    const normalized = normalizeRowMergeAliases(value, options);
    Object.keys(normalized).forEach((key) => {
      const child = normalized[key];
      if (Array.isArray(child) || isPlainObject(child)) {
        normalized[key] = normalizeDatasetPayload(child, options);
      }
    });
    return normalized;
  }
  return value;
}

// ── Display formatting helpers ────────────────────────────────────────────────

export function formatValue(value) {
  if (Array.isArray(value)) return value.length === 0 ? "[]" : value.join(", ");
  if (value && typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch (_e) {
      return "[object]";
    }
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  return toText(value) || "n/a";
}

/**
 * Returns a human-readable string describing how long ago `timestampMs` was.
 * @param {number|null|undefined} timestampMs - Unix timestamp in milliseconds.
 * @returns {string}
 */
export function formatAgo(timestampMs) {
  if (timestampMs == null || !Number.isFinite(timestampMs)) return "—";
  const elapsed = Date.now() - timestampMs;
  if (elapsed < 1_000)       return "just now";
  if (elapsed < 5_000)       return `${Math.floor(elapsed / 1_000)} sec ago`; 
  if (elapsed < 60_000)      return `${Math.floor(elapsed / 1_000)} sec ago`;
  if (elapsed < 3_600_000) {
    const m = Math.floor(elapsed / 60_000);
    const s = Math.floor((elapsed % 60_000) / 1_000);
    return s > 0 ? `${m}m ${s}s ago` : `${m} min ago`;
  }
  if (elapsed < 86_400_000) {
    const h = Math.floor(elapsed / 3_600_000);
    const m = Math.floor((elapsed % 3_600_000) / 60_000);
    return m > 0 ? `${h}hr ${m}m ago` : `${h}hr ago`;
  }
  const d = Math.floor(elapsed / 86_400_000);
  const h = Math.floor((elapsed % 86_400_000) / 3_600_000);
  return h > 0 ? `${d}d ${h}hr ago` : `${d}d ago`;
}

/**
 * Returns a human-readable string describing a duration in milliseconds.
 * @param {number|null|undefined} ms - Duration in milliseconds.
 * @returns {string}
 */
export function formatDuration(ms) {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms < 1_000)         return "< 1 sec";
  if (ms < 60_000)        return `${Math.floor(ms / 1_000)} sec`;
  if (ms < 3_600_000) {
    const m = Math.floor(ms / 60_000);
    const s = Math.floor((ms % 60_000) / 1_000);
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
  }
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return m > 0 ? `${h}hr ${m}m` : `${h}hr`;
}

// ── Detail-panel structured value renderer ────────────────────────────────────

function _createKvRow(keyText, valueText, isEmpty = false) {
  const li = document.createElement("li");
  li.className = "detail-kv-row";
  const keySpan = document.createElement("span");
  keySpan.className = "detail-kv-key";
  keySpan.textContent = keyText + ":";
  const valSpan = document.createElement("span");
  valSpan.className = isEmpty
    ? "detail-value-empty detail-kv-value"
    : "detail-kv-value";
  valSpan.textContent = valueText;
  li.appendChild(keySpan);
  li.appendChild(valSpan);
  return li;
}

function _createSubList(items) {
  const ul = document.createElement("ul");
  ul.className = "detail-value-list";
  items.forEach((item) => ul.appendChild(item));
  return ul;
}

const MATTER_ENUM_LABELS = Object.freeze({
  status: { 0: "Unspecified", 1: "Active", 2: "Standby", 3: "Unavailable" },
  batChargeLevel: { 0: "Ok", 1: "Warning", 2: "Critical" },
  batReplaceability: {
    0: "Unspecified",
    1: "Not replaceable",
    2: "User replaceable",
    3: "Factory replaceable",
  },
  batChargeState: {
    0: "Unknown",
    1: "Charging",
    2: "At full charge",
    3: "Not charging",
  },
  bootReason: {
    0: "Unspecified",
    1: "Power-on reboot",
    2: "Brown-out reset",
    3: "Software watchdog reset",
    4: "Hardware watchdog reset",
    5: "Software update completed",
    6: "Software reset",
  },
  activeBatFaults: { 0: "Unspecified", 1: "Over temperature", 2: "Under temperature" },
  activeBatChargeFaults: {
    0: "Unspecified",
    1: "Ambient too hot",
    2: "Ambient too cold",
    3: "Battery too hot",
    4: "Battery too cold",
    5: "Battery absent",
    6: "Battery over voltage",
    7: "Battery under voltage",
    8: "Charger over voltage",
    9: "Charger under voltage",
    10: "Safety timeout",
  },
  activeHardwareFaults: {
    0: "Unspecified",
    1: "Radio",
    2: "Sensor",
    3: "Resettable over temperature",
    4: "Non-resettable over temperature",
    5: "Power source",
    6: "Visual display fault",
    7: "Audio output fault",
    8: "User interface fault",
    9: "Non-volatile memory error",
    10: "Tamper detected",
  },
  activeRadioFaults: {
    0: "Unspecified",
    1: "Wi-Fi fault",
    2: "Cellular fault",
    3: "Thread fault",
    4: "NFC fault",
    5: "BLE fault",
    6: "Ethernet fault",
  },
  activeNetworkFaults: {
    0: "Unspecified",
    1: "Hardware failure",
    2: "Network jammed",
    3: "Connection failed",
  },
});

const GENERAL_DIAGNOSTICS_LABELS = Object.freeze({
  rebootCount: "Reported reboot count",
  upTime: "Reported uptime",
  totalOperationalHours: "Reported operational hours",
  bootReason: "Reported boot reason",
  activeHardwareFaults: "Active hardware faults",
  activeRadioFaults: "Active radio faults",
  activeNetworkFaults: "Active network faults",
});

const POWER_SOURCE_LABELS = Object.freeze({
  batteryPercent: "Battery remaining",
  description: "Power source description",
  status: "Power source status",
  batPercentRemaining: "Battery remaining (raw half-percent units)",
  batVoltage: "Battery voltage",
  batTimeRemaining: "Estimated battery time remaining",
  batTimeToFullCharge: "Estimated time to full charge",
  batReplacementNeeded: "Battery replacement needed",
  batReplacementDescription: "Battery replacement guidance",
  batFunctionalWhileCharging: "Functional while charging",
  endpointList: "Powered endpoint scope",
});

export function matterFieldDisplayLabel(path, fallback) {
  const leaf = path.split(".").at(-1);
  if (path === "matter.isBridge") return "Node is a bridge";
  if (path.startsWith("generalDiagnostics.")) {
    return GENERAL_DIAGNOSTICS_LABELS[leaf] ?? fallback;
  }
  if (path === "powerSources" || path.startsWith("powerSources.")) {
    return POWER_SOURCE_LABELS[leaf] ?? fallback;
  }
  if (path.startsWith("matter.") && leaf === "endpointId") return "Hosting endpoint";
  return fallback;
}

function formatMatterEnum(field, value) {
  const labels = MATTER_ENUM_LABELS[field];
  if (!labels) return undefined;
  const formatOne = (item) => {
    if (item === null) return "null";
    const label = labels[item];
    return label ? `${label} (${item})` : `Unknown (${String(item)})`;
  };
  return Array.isArray(value) ? value.map(formatOne).join(", ") : formatOne(value);
}

function formatMatterDuration(value) {
  if (
    typeof value !== "string" && !(typeof value === "number" && Number.isSafeInteger(value))
  ) return undefined;
  const text = String(value);
  if (!/^\d+$/.test(text)) return undefined;
  let remaining;
  try {
    remaining = BigInt(text);
  } catch {
    return undefined;
  }
  const units = [["d", 86400n], ["h", 3600n], ["m", 60n], ["s", 1n]];
  const parts = [];
  units.forEach(([label, seconds]) => {
    const count = remaining / seconds;
    if (count > 0n) parts.push(`${count}${label}`);
    remaining %= seconds;
  });
  return parts.join(" ") || "0s";
}

export function formatMatterDisplayValue(path, value) {
  const leaf = path.split(".").at(-1);
  if (path.startsWith("powerSources.") && leaf === "endpointList") {
    if (!Array.isArray(value)) return "Not reported (scope unknown)";
    if (value.length === 0) return "All endpoints (node-wide)";
    return `Endpoints ${value.join(", ")}`;
  }
  if (value === null) return "n/a";
  if (path === "generalDiagnostics.upTime") {
    const duration = formatMatterDuration(value);
    return duration ? `${String(value)} s (${duration})` : String(value);
  }
  if (path === "generalDiagnostics.totalOperationalHours") {
    return `${String(value)} h`;
  }
  if (path === "generalDiagnostics.bootReason") {
    return formatMatterEnum("bootReason", value);
  }
  if (path.startsWith("generalDiagnostics.") && Array.isArray(value)) {
    const enumText = formatMatterEnum(leaf, value);
    if (enumText !== undefined) return enumText || "None reported";
  }
  if (path.startsWith("powerSources.") || path === "powerSources") {
    if (leaf === "batteryPercent") return `${String(value)}%`;
    if (leaf === "batPercentRemaining") return `${String(value)} (0.5% units)`;
    if (leaf === "batVoltage") return `${String(value)} mV`;
    if (leaf === "batTimeRemaining" || leaf === "batTimeToFullCharge") {
      return `${String(value)} s`;
    }
    const enumText = formatMatterEnum(leaf, value);
    if (enumText !== undefined) return enumText;
  }
  if (path.startsWith("generalDiagnostics.") && Array.isArray(value)) {
    return value.length === 0 ? "None reported" : value.map(String).join(", ");
  }
  return undefined;
}

export function matterEndpointArraySummary(path, records) {
  if (!Array.isArray(records)) return "";
  return records.map((record, index) => {
    if (!isPlainObject(record)) return `${index + 1}: ${String(record)}`;
    const endpoint = Number.isInteger(record.endpointId)
      ? `Endpoint ${record.endpointId}`
      : `Unkeyed entry ${index + 1}`;
    if (path === "powerSources") {
      const description = record.attributes?.description;
      const battery = record.batteryPercent;
      return [
        `Power source · ${endpoint}`,
        description ? String(description) : "",
        battery === undefined ? "" : `${String(battery)}%`,
      ].filter(Boolean).join(" — ");
    }
    const bridged = record.bridgedBasicInformation;
    const basic = record.basicInformation;
    const name = bridged?.nodeLabel ?? bridged?.productName
      ?? basic?.nodeLabel ?? basic?.productName;
    return name ? `${endpoint} — ${String(name)}` : endpoint;
  }).join("; ");
}

function _appendMatterEndpointRecord(path, record, index, parentList) {
  if (!isPlainObject(record)) {
    const item = document.createElement("li");
    item.textContent = record === null ? "null" : String(record);
    parentList.appendChild(item);
    return;
  }
  const item = document.createElement("li");
  const details = document.createElement("details");
  details.className = "detail-value-collapsible matter-endpoint-detail";
  details.open = path === "powerSources";
  const summary = document.createElement("summary");
  summary.textContent = matterEndpointArraySummary(path, [record])
    || `Unkeyed entry ${index + 1}`;
  details.appendChild(summary);
  const values = [];
  let scopeRendered = false;
  const appendUnknownScope = () => {
    scopeRendered = true;
    values.push(createDetailValueNode(
      "Powered endpoint scope",
      null,
      `powerSources.${index}.attributes.endpointList`,
    ));
  };
  Object.entries(record).forEach(([key, value]) => {
    if (key === "endpointId") return;
    if (path === "powerSources" && key === "attributes") {
      if (!isPlainObject(value)) {
        appendUnknownScope();
        return;
      }
      Object.entries(value).forEach(([attribute, attributeValue]) => {
        const attributePath = `powerSources.${index}.attributes.${attribute}`;
        if (attribute === "endpointList") {
          scopeRendered = true;
          values.push(createDetailValueNode(
            matterFieldDisplayLabel(attributePath, "Powered endpoint scope"),
            attributeValue,
            attributePath,
          ));
        } else {
          values.push(createDetailValueNode(
            matterFieldDisplayLabel(attributePath, attribute),
            attributeValue,
            attributePath,
          ));
        }
      });
      if (!scopeRendered) appendUnknownScope();
      return;
    }
    const fieldPath = `${path}.${index}.${key}`;
    values.push(createDetailValueNode(
      matterFieldDisplayLabel(fieldPath, key),
      value,
      fieldPath,
    ));
  });
  if (path === "powerSources" && !scopeRendered) appendUnknownScope();
  details.appendChild(_createSubList(values));
  item.appendChild(details);
  parentList.appendChild(item);
}

function _createMatterEndpointArrayNode(path, records) {
  const listItem = document.createElement("li");
  const details = document.createElement("details");
  details.className = "detail-value-collapsible matter-endpoint-array";
  details.open = true;
  const summary = document.createElement("summary");
  summary.textContent = `${path === "powerSources" ? "Power sources" : "Matter endpoints"} (${records.length})`;
  details.appendChild(summary);
  const entries = document.createElement("ul");
  entries.className = "detail-value-list";
  if (records.length === 0) {
    const empty = document.createElement("li");
    empty.textContent = path === "powerSources"
      ? "No power sources reported"
      : "No Matter endpoints observed";
    entries.appendChild(empty);
  }
  records.forEach((record, index) => _appendMatterEndpointRecord(path, record, index, entries));
  details.appendChild(entries);
  listItem.appendChild(details);
  return listItem;
}

function _renderObjectEntries(obj, path = "") {
  return Object.entries(obj).map(([key, value]) => {
    const fieldPath = path ? `${path}.${key}` : key;
    return createDetailValueNode(
      matterFieldDisplayLabel(fieldPath, key),
      value,
      fieldPath,
    );
  });
}

export function createDetailValueNode(key, value, fieldPath = key) {
  if (
    Array.isArray(value)
    && (fieldPath === "powerSources" || fieldPath === "matter.endpoints")
  ) {
    return _createMatterEndpointArrayNode(fieldPath, value);
  }
  const displayLabel = matterFieldDisplayLabel(fieldPath, key);
  const formattedValue = formatMatterDisplayValue(fieldPath, value);
  if (formattedValue !== undefined) {
    return _createKvRow(
      displayLabel,
      formattedValue,
      value === null || (Array.isArray(value) && value.length === 0),
    );
  }
  // Scalar (string, number, boolean, null, undefined)
  if (value === null || value === undefined) {
    return _createKvRow(displayLabel, "n/a");
  }
  if (typeof value !== "object") {
    const text = typeof value === "boolean" ? (value ? "true" : "false") : String(value);
    return _createKvRow(displayLabel, text);
  }

  // Empty array
  if (Array.isArray(value) && value.length === 0) {
    return _createKvRow(displayLabel, "empty []", true);
  }

  // Empty object
  if (!Array.isArray(value) && Object.keys(value).length === 0) {
    return _createKvRow(displayLabel, "empty {}", true);
  }

  // Array of primitives (no element is an object/array)
  if (
    Array.isArray(value) &&
    value.every((item) => item === null || typeof item !== "object")
  ) {
    const li = document.createElement("li");
    const details = document.createElement("details");
    details.className = "detail-value-collapsible";
    details.open = true;
    const summary = document.createElement("summary");
    summary.textContent = `${displayLabel}:`;
    details.appendChild(summary);
    const items = value.map((item) => {
      const subLi = document.createElement("li");
      subLi.textContent = item === null ? "null" : String(item);
      return subLi;
    });
    details.appendChild(_createSubList(items));
    li.appendChild(details);
    return li;
  }

  // Array of objects (or mixed array) — flat indexed sections
  if (Array.isArray(value)) {
    const li = document.createElement("li");
    const details = document.createElement("details");
    details.className = "detail-value-collapsible";
    details.open = true;
    const summary = document.createElement("summary");
    summary.textContent = `${displayLabel}:`;
    details.appendChild(summary);
    const items = value.map((item, idx) => {
      const subLi = document.createElement("li");
      if (item === null || typeof item !== "object") {
        subLi.textContent = item === null ? "null" : String(item);
        return subLi;
      }
      const idxSpan = document.createElement("span");
      idxSpan.className = "detail-array-idx";
      idxSpan.textContent = `[${idx}]`;
      subLi.appendChild(idxSpan);
      subLi.appendChild(_createSubList(_renderObjectEntries(item, `${fieldPath}.${idx}`)));
      return subLi;
    });
    details.appendChild(_createSubList(items));
    li.appendChild(details);
    return li;
  }

  // Plain object
  const li = document.createElement("li");
  const details = document.createElement("details");
  details.className = "detail-value-collapsible";
  details.open = true;
  const summary = document.createElement("summary");
  summary.textContent = `${displayLabel}:`;
  details.appendChild(summary);
  details.appendChild(_createSubList(_renderObjectEntries(value, fieldPath)));
  li.appendChild(details);
  return li;
}

// Groups [[key, value], ...] entries by the segment before the first '.'
// Returns an ordered array of { type: "flat", key, value }
//   or { type: "group", prefix, children: [[subkey, value], ...] }
function _groupEntriesByPrefix(entries) {
  const order = [];
  const seen = new Map(); // prefix or "flat:key" → index in order

  entries.forEach(([key, value]) => {
    const dotIdx = key.indexOf(".");
    if (dotIdx === -1) {
      const mapKey = `flat:${key}`;
      if (!seen.has(mapKey)) {
        seen.set(mapKey, order.length);
        order.push({ type: "flat", key, value });
      }
    } else {
      const prefix = key.slice(0, dotIdx);
      const subkey = key.slice(dotIdx + 1);
      if (!seen.has(prefix)) {
        seen.set(prefix, order.length);
        order.push({ type: "group", prefix, children: [] });
      }
      order[seen.get(prefix)].children.push([subkey, value]);
    }
  });

  return order;
}

function _createGroupNode(prefix, children) {
  const li = document.createElement("li");
  const details = document.createElement("details");
  details.className = "detail-value-collapsible";
  details.open = true;
  const summary = document.createElement("summary");
  summary.className = "detail-group-header";
  summary.textContent = `${prefix}:`;
  details.appendChild(summary);
  const subItems = children.map(([subkey, value]) =>
    createDetailValueNode(subkey, value, `${prefix}.${subkey}`)
  );
  details.appendChild(_createSubList(subItems));
  li.appendChild(details);
  return li;
}

function _normalizeMdnsDisplayKey(key) {
  if (typeof key !== "string") return key;
  if (key.startsWith("serviceInfo.properties.")) {
    return key.slice("serviceInfo.properties.".length);
  }
  if (key.startsWith("properties.")) {
    return key.slice("properties.".length);
  }
  return key;
}

function _isMdnsDetailsList(listEl) {
  const listId = listEl?.id;
  return typeof listId === "string" && listId.endsWith("mdns-list");
}

function _appendGrouped(entries, listEl) {
  const displayEntries = _isMdnsDetailsList(listEl)
    ? entries.map(([key, value]) => [_normalizeMdnsDisplayKey(key), value])
    : entries;

  _groupEntriesByPrefix(displayEntries).forEach((item) => {
    if (item.type === "flat") {
      listEl.appendChild(createDetailValueNode(item.key, item.value));
    } else {
      listEl.appendChild(_createGroupNode(item.prefix, item.children));
    }
  });
}

// ── Detail panel section toggles ─────────────────────────────────────────────

// Sets up collapsible section headings and a global collapse/expand-all control
// for the given panel element. Call once after the DOM is ready.
export function initDetailPanelToggles(panelEl, onClose = () => {}) {
  const headings = Array.from(panelEl.querySelectorAll("h2"));
  let isAllCollapsed = false;

  headings.forEach((h2, idx) => {
    const listEl = h2.nextElementSibling;
    if (!listEl || listEl.tagName !== "UL") return;

    const label = h2.textContent.trim();
    h2.textContent = "";

    const toggleBtn = document.createElement("button");
    toggleBtn.className = "detail-section-toggle";
    toggleBtn.setAttribute("aria-expanded", "true");

    const arrow = document.createElement("span");
    arrow.className = "detail-section-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "▼";

    const labelSpan = document.createElement("span");
    labelSpan.textContent = label;

    toggleBtn.appendChild(arrow);
    toggleBtn.appendChild(labelSpan);
    h2.appendChild(toggleBtn);

    toggleBtn.addEventListener("click", () => {
      const nowHidden = !listEl.classList.contains("hidden");
      listEl.classList.toggle("hidden", nowHidden);
      arrow.textContent = nowHidden ? "▶" : "▼";
      toggleBtn.setAttribute("aria-expanded", String(!nowHidden));
    });

    // First heading gets the global "Collapse All / Expand All" button
    if (idx === 0) {
      const headerActions = document.createElement("span");
      headerActions.className = "detail-header-actions";

      const allBtn = document.createElement("button");
      allBtn.className = "detail-toggle-all";
      allBtn.type = "button";
      const allArrow = document.createElement("span");
      allArrow.className = "detail-section-arrow";
      allArrow.setAttribute("aria-hidden", "true");
      allArrow.textContent = "▼";

      allBtn.appendChild(allArrow);
      allBtn.title = "Collapse all sections";

      allBtn.addEventListener("click", () => {
        isAllCollapsed = !isAllCollapsed;
        allArrow.textContent = isAllCollapsed ? "▶" : "▼";
        allBtn.title = isAllCollapsed ? "Expand all sections" : "Collapse all sections";

        panelEl.querySelectorAll("ul.node-details-list").forEach((ul) => {
          ul.classList.toggle("hidden", isAllCollapsed);
          const prevH2 = ul.previousElementSibling;
          if (prevH2 && prevH2.tagName === "H2") {
            const btn = prevH2.querySelector(".detail-section-toggle");
            const a = prevH2.querySelector(".detail-section-arrow");
            if (btn) btn.setAttribute("aria-expanded", String(!isAllCollapsed));
            if (a) a.textContent = isAllCollapsed ? "▶" : "▼";
          }
        });

        panelEl
          .querySelectorAll("details.detail-value-collapsible")
          .forEach((d) => {
            d.open = !isAllCollapsed;
          });
      });

      const closeBtn = document.createElement("button");
      closeBtn.id = "btn-device-details-heading-close";
      closeBtn.className = "detail-header-close";
      closeBtn.type = "button";
      closeBtn.title = "Close device details panel";
      closeBtn.setAttribute("aria-label", "Close device details panel");
      closeBtn.textContent = "✕";
      closeBtn.addEventListener("click", onClose);

      headerActions.appendChild(allBtn);
      headerActions.appendChild(closeBtn);

      h2.appendChild(headerActions);
    }
  });

}

export function initContextDetailsPanel({ host, toggleButton, onVisibilityChanged }) {
  let isCollapsed = false;
  let mode = "device";

  const syncToggleButton = () => {
    if (!toggleButton) return;
    const action = isCollapsed ? "Expand" : "Collapse";
    toggleButton.title = `${action} details panel`;
    toggleButton.setAttribute("aria-label", `${action} details panel`);
    toggleButton.setAttribute("aria-expanded", String(!isCollapsed));
    toggleButton.textContent = isCollapsed ? "◀" : "▶";
  };

  const setCollapsed = (collapsed) => {
    const nextCollapsed = Boolean(collapsed);
    if (isCollapsed === nextCollapsed) {
      syncToggleButton();
      return;
    }
    isCollapsed = nextCollapsed;
    host?.classList.toggle("details-panel-collapsed", isCollapsed);
    syncToggleButton();
    onVisibilityChanged?.(isCollapsed);
  };

  const setMode = (nextMode) => {
    mode = nextMode === "finding" ? "finding" : "device";
    host?.querySelector("#device-details")?.toggleAttribute("hidden", mode !== "device");
    host?.querySelector("#health-finding-details")?.toggleAttribute("hidden", mode !== "finding");
  };

  toggleButton?.addEventListener("click", () => setCollapsed(!isCollapsed));
  syncToggleButton();
  setMode(mode);
  return {
    getMode: () => mode,
    isCollapsed: () => isCollapsed,
    setCollapsed,
    setMode,
  };
}

export function mergeForDisplay(primary, secondary) {
  if (primary === undefined || primary === null) return secondary;
  if (secondary === undefined || secondary === null) return primary;
  if (Array.isArray(primary) && Array.isArray(secondary)) {
    return secondary.length > 0 ? secondary : primary;
  }
  if (isPlainObject(primary) && isPlainObject(secondary)) {
    const merged = {};
    const keys = new Set([...Object.keys(primary), ...Object.keys(secondary)]);
    keys.forEach((key) => {
      merged[key] = mergeForDisplay(primary[key], secondary[key]);
    });
    return merged;
  }
  return secondary;
}

export function flattenObjectEntries(value, path = "", entries = []) {
  if (isPlainObject(value)) {
    const keys = Object.keys(value).sort((a, b) => a.localeCompare(b));
    if (keys.length === 0 && path) {
      entries.push([path, {}]);
      return entries;
    }
    keys.forEach((key) => {
      const fieldPath = path ? `${path}.${key}` : key;
      if (
        fieldPath === "diagnosticCoverage"
        && isPlainObject(value[key])
        && isPlainObject(value[key].powerSources)
      ) {
        Object.entries(value[key]).forEach(([coverageKey, coverageValue]) => {
          const coveragePath = `${fieldPath}.${coverageKey}`;
          if (coverageKey === "powerSources") {
            entries.push([coveragePath, coverageValue]);
          } else {
            flattenObjectEntries(coverageValue, coveragePath, entries);
          }
        });
      } else {
        flattenObjectEntries(value[key], fieldPath, entries);
      }
    });
    return entries;
  }
  if (Array.isArray(value)) {
    entries.push([path, value]);
    return entries;
  }
  entries.push([path || "value", value]);
  return entries;
}

export function shouldExcludeDetailPath(_path, _context) {
  return false;
}

/**
 * Sorts device detail entries by priority order for display in detail panels.
 * 
 * This function orders fields according to a 5-tier priority system that matches
 * TABLE_PRIORITY_COLUMNS. Fields appear in the detail panel sections (Keys,
 * Highlights, Connections, Routes & Links) in this priority order.
 * 
 * **Priority Tiers:**
 * - **TIER 1: Primary Identity** - Core identifiers (rloc16, extAddress, routerId, deviceLabel)
 * - **TIER 2: Secondary Identity** - Additional identifiers (omrIpv6Addr, mlEidIid, room)
 * - **TIER 3: Device Role & Status** - Role, type, mode information
 * - **TIER 4: Topology & Connectivity** - Link quality, connectivity metrics
 * - **TIER 5: Advanced/Diagnostic** - Counters, vendor info, diagnostics
 * 
 * **Behavior:**
 * - Fields in priorityKeys appear first, in the specified order
 * - Fields not in priorityKeys appear after, in alphabetical order
 * - Supports both snake_case and camelCase field naming conventions
 * - Missing fields are gracefully skipped (no errors)
 * 
 * @param {Array<[string, any]>} details - Array of [fieldName, fieldValue] tuples
 * @returns {Array<[string, any]>} Sorted array of [fieldName, fieldValue] tuples
 * 
 * @example
 * const details = [['type', 'router'], ['rloc16', '0x4400'], ['extaddr', 'abc123']];
 * const sorted = sortDetailsWithPriority(details);
 * // Returns: [['rloc16', '0x4400'], ['extaddr', 'abc123'], ['type', 'router']]
 */
export function sortDetailsWithPriority(details) {
  const priorityKeys = [
    // === TIER 1: Primary Identity ===
    "extAddress",
    "rloc16",
    "deviceLabel",
    "name",
    "routerId",
    "eui",
    "id",
    "ID",
    
    // === TIER 2: Secondary Identity ===
    "omrIpv6Address",
    "mlEidIid",
    "room",
    
    // === TIER 3: Device Role & Status ===
    "type",
    "Role",
    "isBorderRouter",
    "isRouter",
    "isLeader",
    "leader",
    "isPrimaryBBR",
    "status",
    "icon",
    "mode",
    "mode.device",
    "mode.deviceTypeFTD",
    "version",
    "threadVersion",
    "threadVersionDecimal",
    "threadStackVersion",
    "vendorName",
    "vendorModel",
    "vendorSwVersion",
    
    // === TIER 4: Topology & Connectivity ===
    "totalChildren",
    "hasChildren",
    "totalLinks",
    "totalLink3",
    "totalLink2",
    "totalLink1",
    "routerNeighborsCount",
    "childTableCount",
    "connectivity.activeRouters",
    "connectivity.linkQuality3",
    "connectivity.linkQuality2",
    "connectivity.linkQuality1",
    "leaderData.partitionId",
    "leaderData.leaderRouterId",
    
    // === TIER 5: Advanced/Diagnostic ===
    "tlvRequestValues",
    "tlvResponseValues",
    "macCounters.ifinerrors_pct",
    "macCounters.ifouterrors_pct",
    "macCounters.ifindiscards_pct",
    "macCounters.ifoutdiscards_pct",
    "mleCounters.partitionIdChanges",
    "mleCounters.betterPartitionAttachAttempts",
    "mleCounters.parentChanges",
    "mleCounters.totalParentPartitionChanges",
    "mleCounters.attachAttempts",
    "mleCounters.detachedRole",
    "mleCounters.disabledRole",
  ];
  const priorityIndex = new Map(priorityKeys.map((k, i) => [k, i]));
  return [...details].sort((a, b) => {
    const ap = priorityIndex.has(a[0]) ? priorityIndex.get(a[0]) : Infinity;
    const bp = priorityIndex.has(b[0]) ? priorityIndex.get(b[0]) : Infinity;
    if (ap !== bp) return ap - bp;
    return a[0].localeCompare(b[0]);
  });
}

// ── Node identity comparison ──────────────────────────────────────────────────

export function areNodeIdsEquivalent(a, b) {
  return toText(a).toLowerCase() === toText(b).toLowerCase();
}

// ── Row/column path helpers ───────────────────────────────────────────────────

// Returns true if `row` contains a value at the given dot-separated `path`.
export function hasNestedPath(row, path) {
  if (!path.includes("."))
    return _getOwnPropertyValueByAlias(row, path) !== undefined;
  let current = row;
  for (const part of path.split(".")) {
    if (!isPlainObject(current)) return false;
    const next = _getOwnPropertyValueByAlias(current, part);
    if (next === undefined) return false;
    current = next;
  }
  return true;
}

// Returns the value at a dot-separated `columnName` path within `row`, or
// `undefined` if any segment is missing.
export function getColumnValue(row, columnName) {
  const direct = _getOwnPropertyValueByAlias(row, columnName);
  if (direct !== undefined) return direct;
  if (!columnName.includes(".")) return undefined;
  let current = row;
  for (const part of columnName.split(".")) {
    if (!isPlainObject(current)) return undefined;
    const next = _getOwnPropertyValueByAlias(current, part);
    if (next === undefined) return undefined;
    current = next;
  }
  return current;
}

// ── Shared details-panel renderer ─────────────────────────────────────────────

// Binds DEVICE_DETAILS_SECTIONS entries to DOM list elements by writing
// each section's ordered field list into a comma-separated data-fields attr.
// Missing section IDs are warned and skipped by design.
export function bindDeviceDetailsSectionFields(listIdPrefix = "") {
  DEVICE_DETAILS_SECTIONS.forEach((section) => {
    const listId = `${listIdPrefix}${section.sectionId}`;
    const listEl = document.getElementById(listId);
    if (!listEl) {
      console.warn(
        `[tdash] DEVICE_DETAILS_SECTIONS skipped missing list element: #${listId}`,
      );
      return;
    }
    if (!Array.isArray(section.fields) || section.fields.length === 0) {
      console.warn(
        `[tdash] DEVICE_DETAILS_SECTIONS skipped empty fields for: #${listId}`,
      );
      return;
    }
    listEl.setAttribute("data-fields", section.fields.join(","));
  });
}

// Populates the categorised node/row details lists in the given panel.
// `listIdPrefix` distinguishes panels: "" for topology, "table-" for the table.
// Each list element must have a runtime `data-fields` attribute (comma-separated
// field paths, or "*" for the catch-all remainder list), bound from
// DEVICE_DETAILS_SECTIONS via bindDeviceDetailsSectionFields().
export function populateNodeDetailsLists(details, listIdPrefix = "") {
  const listIds = [
    `${listIdPrefix}identity-list`,
    `${listIdPrefix}highlights-list`,
    `${listIdPrefix}network-list`,
    `${listIdPrefix}connections-list`,
    `${listIdPrefix}thread-list`,
    `${listIdPrefix}matter-list`,
    `${listIdPrefix}mdns-list`,
    `${listIdPrefix}routes-links-list`,
    `${listIdPrefix}neighbors-list`,
    `${listIdPrefix}children-list`,
    `${listIdPrefix}counters-list`,
    `${listIdPrefix}details-list`,
  ];

  const allUsedFields = new Set();
  const detailsMap = new Map(details);

  listIds.forEach((listId) => {
    const listEl = document.getElementById(listId);
    if (!listEl) return;

    const fieldsAttr = listEl.getAttribute("data-fields");
    if (!fieldsAttr) {
      listEl.classList.add("hidden");
      const prevH2 = listEl.previousElementSibling;
      if (prevH2?.tagName === "H2") prevH2.classList.add("hidden");
      return;
    }

    const isCatchAll = fieldsAttr === "*";
    let fieldNames = [];

    if (!isCatchAll) {
      fieldNames = fieldsAttr.split(",").map((f) => f.trim());
      fieldNames.forEach((f) => allUsedFields.add(f));
    }

    listEl.innerHTML = "";

    if (isCatchAll) {
      const catchAllEntries = [];
      details.forEach(([key, value]) => {
        if (!allUsedFields.has(key)) catchAllEntries.push([key, value]);
      });
      _appendGrouped(catchAllEntries, listEl);
    } else {
      const namedEntries = fieldNames
        .map((f) => [f, detailsMap.get(f)])
        .filter(([, v]) => v !== undefined);
      if (
        listId.endsWith("matter-list")
        && namedEntries.some(([key]) =>
          key.startsWith("matter.") || key.startsWith("generalDiagnostics.") || key === "powerSources",
        )
      ) {
        const cacheNote = document.createElement("li");
        cacheNote.className = "detail-cache-note";
        cacheNote.textContent =
          "Matter values reflect the server's last-known cache; they are not live reads.";
        listEl.appendChild(cacheNote);
      }
      _appendGrouped(namedEntries, listEl);
    }

    if (listEl.children.length === 0) {
      listEl.classList.add("hidden");
      const prevH2 = listEl.previousElementSibling;
      if (prevH2?.tagName === "H2") prevH2.classList.add("hidden");
    } else {
      listEl.classList.remove("hidden");
      const prevH2 = listEl.previousElementSibling;
      if (prevH2?.tagName === "H2") prevH2.classList.remove("hidden");
    }
  });
}

export const DEVICE_SELECTION_EVENT = "tdash:device-selected";

export function publishDeviceSelection(record, { direct = false, resolved = false } = {}) {
  document.dispatchEvent(
    new CustomEvent(DEVICE_SELECTION_EVENT, {
      detail: { record: record ?? null, direct, resolved },
    }),
  );
}
