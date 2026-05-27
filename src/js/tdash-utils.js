import { MERGE_IDENTITY_FIELDS } from "./tdash-constants.js";

// ── Primitive type helpers ────────────────────────────────────────────────────

export function toText(value) {
  return value === undefined || value === null ? "" : String(value).trim();
}

export function toFiniteNumber(value) {
  if (Number.isFinite(value)) return value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

// ── Canonical identity helpers ────────────────────────────────────────────────

export function canonicalIdText(value) {
  const text = toText(value);
  return text ? text.toLowerCase() : "";
}

export function getCanonicalRloc16(row) {
  return canonicalIdText(row?.[MERGE_IDENTITY_FIELDS.rloc16]);
}

export function getCanonicalExtaddr(row) {
  for (const key of MERGE_IDENTITY_FIELDS.extaddrAliases) {
    const value = canonicalIdText(row?.[key]);
    if (value) return value;
  }
  return "";
}

export function getCanonicalOmrIpv6Address(row) {
  return canonicalIdText(row?.[MERGE_IDENTITY_FIELDS.omr_ipv6_addr]);
}

// ── Row normalisation helpers ─────────────────────────────────────────────────

export function normalizeRowMergeAliases(row) {
  if (!isPlainObject(row)) return row;
  const normalized = { ...row };
  const extaddr = getCanonicalExtaddr(row);
  const omr_ipv6_addr = getCanonicalOmrIpv6Address(row);

  if (extaddr) normalized.extaddr = extaddr;
  if (omr_ipv6_addr) normalized.omr_ipv6_addr = omr_ipv6_addr;

  return normalized;
}

export function normalizeDatasetPayload(value) {
  if (Array.isArray(value)) {
    return value.map((item) => normalizeDatasetPayload(item));
  }
  if (isPlainObject(value)) {
    const normalized = normalizeRowMergeAliases(value);
    Object.keys(normalized).forEach((key) => {
      const child = normalized[key];
      if (Array.isArray(child) || isPlainObject(child)) {
        normalized[key] = normalizeDatasetPayload(child);
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

function _renderObjectEntries(obj) {
  return Object.entries(obj).map(([k, v]) => createDetailValueNode(k, v));
}

export function createDetailValueNode(key, value) {
  // Scalar (string, number, boolean, null, undefined)
  if (value === null || value === undefined) {
    return _createKvRow(key, "n/a");
  }
  if (typeof value !== "object") {
    const text =
      typeof value === "boolean" ? (value ? "true" : "false") : String(value);
    return _createKvRow(key, text);
  }

  // Empty array
  if (Array.isArray(value) && value.length === 0) {
    return _createKvRow(key, "empty []", true);
  }

  // Empty object
  if (!Array.isArray(value) && Object.keys(value).length === 0) {
    return _createKvRow(key, "empty {}", true);
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
    summary.textContent = `${key}:`;
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
    summary.textContent = `${key}:`;
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
      subLi.appendChild(_createSubList(_renderObjectEntries(item)));
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
  summary.textContent = `${key}:`;
  details.appendChild(summary);
  details.appendChild(_createSubList(_renderObjectEntries(value)));
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
    createDetailValueNode(subkey, value)
  );
  details.appendChild(_createSubList(subItems));
  li.appendChild(details);
  return li;
}

function _appendGrouped(entries, listEl) {
  _groupEntriesByPrefix(entries).forEach((item) => {
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
export function initDetailPanelToggles(panelEl) {
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
      const allBtn = document.createElement("button");
      allBtn.className = "detail-toggle-all";
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

      h2.appendChild(allBtn);
    }
  });
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
      flattenObjectEntries(value[key], path ? `${path}.${key}` : key, entries);
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
 * - **TIER 1: Primary Identity** - Core identifiers (rloc16, extaddr, routerId, device_label)
 * - **TIER 2: Secondary Identity** - Additional identifiers (omr_ipv6_addr, mlEidIid, room)
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
    "rloc16",
    "extaddr",
    "extAddress",
    "device_label",
    "name",
    "routerId",
    "router_id",
    "eui64",
    "id",
    "ID",
    
    // === TIER 2: Secondary Identity ===
    "omr_ipv6_addr",
    "omrIpv6Address",
    "mlEidIid",
    "room",
    "Extended MAC",
    
    // === TIER 3: Device Role & Status ===
    "type",
    "Role",
    "br",
    "isBorderRouter",
    "leader",
    "isLeader",
    "is_router",
    "isPrimaryBBR",
    "status",
    "icon",
    "mode",
    "mode.device",
    "mode.deviceTypeFTD",
    "ver",
    "version",
    "thread_version",
    "thread_stack_version",
    "threadStackVersion",
    "vendor_name",
    "vendorName",
    "vendor_model",
    "vendorModel",
    "vendor_sw_version",
    "vendorSwVersion",    
    "room",
    "icon",
    
    // === TIER 4: Topology & Connectivity ===
    "total_children",
    "has_children",
    "total_links",
    "total_link_3",
    "total_link_2",
    "total_link_1",
    "router_neighbor_table_count",
    "router_child_table_count",
    "connectivity.activeRouters",
    "connectivity.active_routers",
    "connectivity.linkQuality3",
    "connectivity.link_quality_3",
    "connectivity.linkQuality2",
    "connectivity.link_quality_2",
    "connectivity.linkQuality1",
    "connectivity.link_quality_1",
    "leaderData.partitionId",
    "leader_data.partition_id",
    "leaderData.leaderRouterId",
    "leader_data.leader_router_id",
    
    // === TIER 5: Advanced/Diagnostic ===
    "tlv_values",
    "mac_counters.ifinerrors_pct",
    "mac_counters.ifouterrors_pct",
    "mac_counters.ifindiscards_pct",
    "mac_counters.ifoutdiscards_pct",
    "mle_counters.partitionidchanges",
    "mle_counters.betterpartitionattachattempts",
    "mle_counters.parentchanges",
    "mle_counters.totalparentpartitionchanges",
    "mle_counters.attachattempts",
    "mle_counters.detachedrole",
    "mle_counters.disabledrole",
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
    return Object.prototype.hasOwnProperty.call(row, path);
  let current = row;
  for (const part of path.split(".")) {
    if (
      !isPlainObject(current) ||
      !Object.prototype.hasOwnProperty.call(current, part)
    )
      return false;
    current = current[part];
  }
  return true;
}

// Returns the value at a dot-separated `columnName` path within `row`, or
// `undefined` if any segment is missing.
export function getColumnValue(row, columnName) {
  if (Object.prototype.hasOwnProperty.call(row, columnName))
    return row[columnName];
  if (!columnName.includes(".")) return undefined;
  let current = row;
  for (const part of columnName.split(".")) {
    if (
      !isPlainObject(current) ||
      !Object.prototype.hasOwnProperty.call(current, part)
    )
      return undefined;
    current = current[part];
  }
  return current;
}

// ── Shared details-panel renderer ─────────────────────────────────────────────

// Populates the categorised node/row details lists in the given panel.
// `listIdPrefix` distinguishes panels: "" for topology, "table-" for the table.
// Each list element must carry a `data-fields` attribute (comma-separated field
// paths, or "*" for the catch-all remainder list).
export function populateNodeDetailsLists(details, listIdPrefix = "") {
  const listIds = [
    `${listIdPrefix}identity-list`,
    `${listIdPrefix}highlights-list`,
    `${listIdPrefix}network-list`,
    `${listIdPrefix}connections-list`,
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
