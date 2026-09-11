import { canonicalizeExtAddress } from "./tdash-device-fields.js";

export const DEVICE_ACTIONS = Object.freeze({
  OTBR_PING: "otbr-cli-ping",
  MATTER_PING: "ha-matter-ws-ping",
  SYSTEM_PING: "system-ping",
  OTBR_RESET: "otbr-cli-reset-counters",
});

function nestedValue(record, path) {
  let value = record;
  for (const part of path.split(".")) {
    if (!value || typeof value !== "object") return undefined;
    value = value[part];
  }
  return value;
}

function normalizedIpAddress(value) {
  if (typeof value !== "string" || !value || value.includes("%")) return null;
  const text = value.trim();
  const ipv4Parts = text.split(".");
  if (ipv4Parts.length === 4 && ipv4Parts.every((part) => /^\d{1,3}$/.test(part))) {
    const octets = ipv4Parts.map(Number);
    if (octets.some((octet) => octet > 255)) return null;
    if (octets[0] === 0 || octets[0] === 127 || octets[0] >= 224) return null;
    return { address: octets.join("."), family: "ipv4" };
  }
  if (!text.includes(":")) return null;
  try {
    const hostname = new URL(`http://[${text}]/`).hostname;
    const address = hostname.slice(1, -1).toLowerCase();
    if (!address || address === "::" || address === "::1" ||
        address.startsWith("fe8") || address.startsWith("fe9") ||
        address.startsWith("fea") || address.startsWith("feb") ||
        address.startsWith("ff")) return null;
    return { address, family: "ipv6" };
  } catch {
    return null;
  }
}

function addressValues(value) {
  if (typeof value === "string") return [value];
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string") return [item];
    if (!item || typeof item !== "object") return [];
    const direct = item.address ?? item.ipAddress ?? item.ip;
    const nested = [item.ipv4Addresses, item.ipv6Addresses].flatMap(addressValues);
    return typeof direct === "string" ? [direct, ...nested] : nested;
  });
}

export function getEligibleDeviceAddresses(record) {
  if (!record || typeof record !== "object") return [];
  const paths = [
    "omrIpv6Address",
    "omrIpv6Addr",
    "omr_ipv6_addr",
    "peerAddress",
    "ipv6Addresses",
    "ipv6_addresses",
    "addresses",
    "serviceInfo.addressesParsed",
    "networkInterfaces",
  ];
  const candidates = new Map();
  paths.forEach((path) => {
    addressValues(nestedValue(record, path)).forEach((raw) => {
      const normalized = normalizedIpAddress(raw);
      if (!normalized || candidates.has(normalized.address)) return;
      candidates.set(normalized.address, { ...normalized, provenance: path });
    });
  });
  return [...candidates.values()];
}

function matterNodeId(record) {
  const value = nestedValue(record, "matter.nodeId") ?? record?.nodeId;
  if (value === undefined || value === null || value === "") return null;
  try {
    const parsed = BigInt(value);
    return parsed >= 0n && parsed <= 0xffffffffffffffffn ? parsed.toString() : null;
  } catch {
    return null;
  }
}

export function getDeviceActionIdentity(record) {
  if (!record || typeof record !== "object") return "";
  const extAddress = canonicalizeExtAddress(
    record.extAddress ?? record.extaddr ?? record.eui64 ?? record.eui ?? "",
  );
  if (/^[0-9a-f]{16}$/.test(extAddress)) return `extAddress:${extAddress}`;
  const nodeId = matterNodeId(record);
  if (nodeId !== null) return `matterNode:${nodeId}`;
  const rloc = record.rloc16 ?? record.RLOC16;
  if (rloc !== undefined && rloc !== null && `${rloc}`) {
    const parsed = Number.parseInt(`${rloc}`.replace(/^0x/i, ""), 16);
    if (Number.isInteger(parsed) && parsed >= 0 && parsed <= 0xffff) {
      return `rloc16:${parsed.toString(16).padStart(4, "0")}`;
    }
  }
  const id = record.id ?? record.ID;
  return typeof id === "string" && id.trim() ? `id:${id.trim()}` : "";
}

function sourceFiles(record) {
  const value = record?._source_files;
  return Array.isArray(value) ? value.map(String) : [];
}

function hasSourceEvidence(record, entry, prefix) {
  if (entry?.source === prefix) return true;
  if (entry?.source !== "merged") return false;
  return sourceFiles(record).some((filename) => filename.startsWith(`td-${prefix}-`));
}

export function isSleepyDevice(record) {
  if (record?.mode?.rxOnWhenIdle === false) return true;
  return [record?.type, record?.role, record?.Role].some((value) =>
    typeof value === "string" && ["sleepychild", "sleepyenddevice", "sed"].includes(
      value.toLowerCase().replaceAll("-", "").replaceAll(" ", ""),
    ));
}

export function buildDeviceDiagnosticsModel(record, entry, capabilities) {
  const deviceId = getDeviceActionIdentity(record);
  if (!deviceId || !entry || capabilities?.enabled !== true) return null;
  const supported = new Set(capabilities.actions || []);
  const addresses = getEligibleDeviceAddresses(record);
  const hasOtbr = hasSourceEvidence(record, entry, "otbr-cli");
  const hasMatter = hasSourceEvidence(record, entry, "ha-matter-ws");
  const nodeId = matterNodeId(record);
  let pingAction = null;
  let targets = [];
  if (hasOtbr && supported.has(DEVICE_ACTIONS.OTBR_PING)) {
    pingAction = DEVICE_ACTIONS.OTBR_PING;
    targets = addresses.filter(({ family }) => family === "ipv6");
  } else if (hasMatter && nodeId !== null && supported.has(DEVICE_ACTIONS.MATTER_PING)) {
    pingAction = DEVICE_ACTIONS.MATTER_PING;
  } else if (!hasOtbr && !hasMatter && supported.has(DEVICE_ACTIONS.SYSTEM_PING)) {
    pingAction = DEVICE_ACTIONS.SYSTEM_PING;
    targets = addresses;
  }
  if (pingAction !== DEVICE_ACTIONS.MATTER_PING && targets.length === 0) {
    pingAction = null;
  }
  const resetSupported = hasOtbr && targets.length > 0 &&
    supported.has(DEVICE_ACTIONS.OTBR_RESET) && capabilities.resetEnabled === true;
  if (!pingAction && !resetSupported) return null;
  return {
    deviceId,
    source: entry.source,
    datasetFiles: [...(entry.files || [])],
    title: record.deviceLabel || record.name || record.rloc16 || deviceId,
    pingAction,
    targets,
    nodeId,
    sleepy: isSleepyDevice(record),
    resetSupported,
  };
}

export function deviceActionStatusLabel(status) {
  return ({
    success: "Success",
    "partial-success": "Partial success",
    "no-response": "No response",
    "no-addresses": "No addresses",
    "timed-out": "Timed out",
    "deadline-exceeded": "Deadline exceeded",
    cancelled: "Cancelled",
    unsupported: "Unsupported",
    "protocol-error": "Protocol error",
    "transport-failure": "Transport failure",
    "local-dispatch-failure": "Local dispatch failure",
    "accepted-for-transmission": "Accepted for transmission",
    failed: "Failed",
  })[status] ?? status ?? "Unknown";
}