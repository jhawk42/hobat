# camelCase JSON Migration Plan (Draft)

This document proposes migrating TDash's internal JSON key convention from the current
mixed state (snake_case from CLI collectors, camelCase from REST API collectors) to a
single canonical convention. It is a **draft** — intended for review and comment.

---

## Background

TDash currently merges two independent data sources:

| Source | Module | Key convention |
|--------|--------|----------------|
| CLI (`ot-ctl`) | `otbr_cli_*.py` | `snake_case` (e.g. `route_data`, `ipv6_addrs`) |
| REST API (OTBR) | `otbr_restapi_*.py` | `camelCase` (e.g. `routeData`, `ipv6Addrs`) |

A `FIELD_ALIASES` table in both `src/js/tdash-constants.js` (lines 47–112) and
`src/merge_dataset.py` (lines 489–544) bridges the two conventions today. The merge
layer normalises everything to snake_case before writing the combined record; the browser
layer then re-applies alias resolution at render time.

---

## Problem Statement

1. **Dual normalisation overhead** — aliases are resolved once in the backend merge and
   again in the frontend adaptor, creating two places that must stay in sync.
2. **Inconsistent nested-object keys** — parent object names differ between sources
   (`route_data` vs `route`; `router_neighbor_table` vs `routerNeighbors`;
   `router_child_table` vs `childTable`), requiring special-case handling beyond simple
   field aliasing.
3. **Percentage conversion ambiguity** — REST API error-rate fields arrive as decimals
   (0–1); CLI fields arrive as percentages (0–100). The conversion currently lives only
   in `normalizeNestedArrayFields()` in the browser, so any server-side consumer of the
   merged file receives inconsistent units.
4. **Growing alias table** — every new REST API field requires a matching entry in both
   the Python and JS alias tables to avoid silent data loss.

---

## Proposed Direction

Pick one canonical convention for the **merged** JSON record (the file written to disk
and served via `/api/data/`). camelCase is the natural choice because:

- The OTBR REST API (the authoritative upstream) already uses camelCase.
- The browser/JS ecosystem conventionally uses camelCase.
- New fields added to the REST API require no alias entry if the canonical form is
  already camelCase.

CLI-sourced snake_case fields would be converted to camelCase at ingest time (in
`merge_dataset.py`), eliminating the need for alias resolution in the browser.

---

## Affected Components

### Backend

| File | Change |
|------|--------|
| `src/merge_dataset.py` | Convert snake_case CLI keys to camelCase on ingest; remove post-merge alias resolution pass; keep reverse map for reading legacy on-disk files during transition |
| `src/otbr_cli_*.py` | Optional: convert at write time so individual collector files are also camelCase |
| `src/otbr_restapi_util.py` | No key changes needed; already produces camelCase |

### Frontend

| File | Change |
|------|--------|
| `src/js/tdash-constants.js` | Simplify `FIELD_ALIASES` — only legacy→camelCase entries needed during rollout; remove after cutover |
| `src/js/tdash-utils.js` | Remove `getCanonicalFieldName` / `normalizeFieldNames` once aliases are gone |
| `src/js/tdash-adaptors.js` | Remove `normalizeNestedArrayFields` alias pass; move percentage conversion to backend |
| `src/js/tdash-ui.js` | Audit any hardcoded `snake_case` keys |
| `src/js/tdash-topology.js` | Audit any hardcoded `snake_case` keys |

### Tests

| File | Change |
|------|--------|
| `tests/test_phase1_current_merge_behavior.py` | Update expected keys in assertions |
| `tests/test_phase2_enhanced_merge.py` | Update expected keys in assertions |
| `tests/test_td_merge_identity.py` | Update expected keys in assertions |

---

## Proposed Field Name Mapping

The table below lists every current snake_case key and its target camelCase name.
This is a **draft** — completeness and correctness need verification.

| Current (snake_case) | Target (camelCase) | Notes |
|----------------------|-------------------|-------|
| `router_id` | `routerId` | |
| `ext_addr` / `extaddr` | `extAddress` | consolidate spellings |
| `ipv6_addrs` | `ipv6Addrs` | already camelCase in REST; keep as-is |
| `route_data` | `routeData` | |
| `leader_data` | `leaderData` | already camelCase in REST; keep as-is |
| `router_neighbor_table` | `routerNeighbors` | rename matches REST API |
| `router_child_table` | `childTable` | rename matches REST API |
| `err_rate_frame_pct` | `frameErrorRate` | drop `_pct` suffix; store as 0–100 |
| `err_rate_msg_pct` | `messageErrorRate` | drop `_pct` suffix; store as 0–100 |
| `rss_ave` | `averageRssi` | |
| `rss_margin` | `linkMargin` | |
| `q_msg` | `queuedMessageCount` | |
| `link_quality_in` | `linkQualityIn` | |
| `link_quality_out` | `linkQualityOut` | |
| `link_quality` | `linkQuality` | |
| `full_netdata` | `fullNetdata` | |
| `full_thread_device` | `fullThreadDevice` | |
| `is_border_router` | `isBorderRouter` | |
| `mode` (device mode struct) | `mode` | already consistent |
| `child_id` | `childId` | |
| `child_mac` | `childMac` | |

> **TODO**: Run a grep across `src/` for remaining snake_case keys not listed here.

---

## Migration Phases

### Phase 0 — Audit (no code change)

- Generate a complete list of every JSON key name in use across all collector outputs,
  merged files, and frontend consumers.
- Identify any keys not covered by the current `FIELD_ALIASES` table.
- Confirm the percentage-unit question for each `_pct` field.

### Phase 1 — Backend conversion + dual-write

- `merge_dataset.py`: after normalising to snake_case (existing logic), add a second
  pass that converts snake_case keys to camelCase before writing the merged file.
- The merged file now contains **only camelCase keys**.
- Keep alias resolution in the frontend unchanged so nothing breaks yet.

### Phase 2 — Frontend cutover

- Remove `normalizeFieldNames` and `getCanonicalFieldName` from `tdash-utils.js`.
- Remove alias resolution from `tdash-adaptors.js`; keep only the percentage conversion
  (or move it to the backend in Phase 1).
- Update all hardcoded key references in `tdash-ui.js`, `tdash-topology.js`, etc.

### Phase 3 — Cleanup

- Remove `FIELD_ALIASES` table from `tdash-constants.js` and `merge_dataset.py`.
- Remove the legacy snake_case-reader path from `merge_dataset.py`.
- Update tests.

---

## Backward Compatibility

- **On-disk legacy files**: merged files already written in snake_case will be served
  until they expire. The frontend alias table handles these during Phase 1–2.
- **External consumers**: any script reading merged JSON files directly will need
  updating after Phase 3. Document in release notes.
- **Individual collector files** (`td-otbr-cli-*.json`): these are internal; they can
  be converted in Phase 1 or left as-is until Phase 3.

---

## Open Questions

1. Should collector files (pre-merge) also be converted to camelCase, or only the merged
   output?
2. What is the policy for percentage vs decimal representation of error rates? Storing as
   0–100 in the canonical file seems clearest.
3. Are there any external scripts or integrations that read the merged JSON files
   directly that would break in Phase 3?
4. Should `ipv6Addrs` keep its current mixed-case form or be normalised to `ipv6Addrs`
   (no change needed)?

---

## Testing Strategy

- Add a round-trip test: feed a synthetic CLI record through `merge_dataset.py` and
  assert every key in the output is camelCase.
- Add a round-trip test: feed a synthetic REST API record and assert no keys change.
- Regression tests for the browser: mock `/api/data/` responses with camelCase-only
  payloads and assert correct rendering.

---

## References

- `src/js/tdash-constants.js` — `FIELD_ALIASES` table
- `src/merge_dataset.py` — `get_canonical_field_name`, `normalize_field_names_in_record`
- `src/js/tdash-utils.js` — `getCanonicalFieldName`, `normalizeFieldNames`, `normalizeNestedArrayFields`
- `src/js/tdash-adaptors.js` — data loading and normalisation entry point
- `doc/codebase_webpage_web_server_data_flow.md` — end-to-end data flow overview
