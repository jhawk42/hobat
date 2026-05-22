# Draft Plan: OTBR CLI Refactor and Utility Extraction (Phases Executed for Discovery)

## Structure (Phased)
1. Phase 1 — Baseline and Refactor Catalog
2. Phase 2 — `networkdiag` Extraction Review
3. Phase 3 — `meshdiag` Extraction Review
4. Phase 4 — Remaining `otbr_cli_*` Review
5. Phase 5 — Consolidated Refactor Proposal and Sequencing
6. Phase 6 — Utility/Core Module Expansion
7. Phase 7 — OTBR REST API Module Expansion
8. Phase 8 — mDNS / Eve / Merge Module Expansion
9. Phase 9 — Expanded Consolidated Extraction Matrix

> Discovery executed in sequence to collect refactoring information only.  
> No production code changes performed.

## Expanded Scope (Requested)
This plan now explicitly includes the following files for refactor discovery:

- `src/util_convert.py`
- `src/util_data.py`
- `src/util_network.py`
- `src/util_ot_ctl.py`
- `src/td_cli.py`
- `src/td_const.py`
- `src/td_webserver.py`
- `src/extaddr_device_label_map.py`
- `src/otbr_cli_meshdiag_childip6.py`
- `src/otbr_cli_meshdiag_childtable.py`
- `src/otbr_cli_meshdiag_routerneighbortable.py`
- `src/otbr_cli_meshdiag_topology.py`
- `src/otbr_cli_networkdiag_topology.py`
- `src/otbr_cli_router_table.py`
- `src/otbr_cli_thread_network_info.py`
- `src/otbr_restapi_cli.py`
- `src/otbr_restapi_download.py`
- `src/otbr_restapi_topology.py`
- `src/otbr_restapi_util.py`
- `src/mdns_thread_scopes.py`
- `src/dataset_merge.py`
- `src/merge_extaddr_file_into_static_map.py`
- `src/eve_parse.py`

---

## Phase 1 — Baseline and Refactor Catalog (Executed)

### Extraction Buckets
- **A. Common processing functions** (domain flow logic shared by collectors)
- **B. OTBR CLI utility functions** (`src/otbr_cli_util.py` target)
- **C. Cross-dataset utility functions** (`src/util_*.py` target)

### Inventory Format Used
- Source function/file
- Duplicate pattern
- Proposed destination
- Priority: High / Medium / Low
- Risk: Low / Medium / High

---

## Phase 2 — `networkdiag` Extraction Review (Executed)
Target: `src/otbr_cli_networkdiag_topology.py`

Reviewed functions:
- `fetch_network_diag_topology`
- `fetch_network_diag_multicast`
- `fetch_network_diag_topology_multicast_network`
- `fetch_network_diag_topology_multicast_neighbors`

### Findings
1. **Retry + TLV fallback orchestration duplicated across router/child/multicast paths**
   - Similar retry loops and detail-level downgrades appear in multicast, router polling, and child polling.
   - Candidate destination: `src/otbr_cli_util.py`
   - Priority: High, Risk: Medium

2. **Node default/fallback record construction repeated**
   - Repeated “Unknown-*” record assembly for router and child failure paths.
   - Candidate destination: internal helper in `src/otbr_cli_networkdiag_topology.py` first; later promote if reused.
   - Priority: High, Risk: Low

3. **Node enrichment/classification repeated**
   - OMR detection and border-router/type classification logic repeated in multiple branches.
   - Candidate destination: shared network utility helper(s) in `src/util_network.py`
   - Priority: High, Risk: Low

4. **Record merge paths are centralized but invocation is repeated**
   - `merge_device_record` exists, but call-site patterns can be wrapped in single merge/upsert helper.
   - Candidate destination: `src/otbr_cli_networkdiag_topology.py` (internal)
   - Priority: Medium, Risk: Low

5. **Multicast wrapper functions are thin and appropriate**
   - `fetch_network_diag_topology_multicast_network/neighbors` are clean wrappers and can remain as-is.
   - Candidate destination: keep local
   - Priority: Low, Risk: Low

---

## Phase 3 — `meshdiag` Extraction Review (Executed)
Targets:
- `src/otbr_cli_meshdiag_topology.py`
- `src/otbr_cli_meshdiag_childip6.py`
- `src/otbr_cli_meshdiag_childtable.py`
- `src/otbr_cli_meshdiag_routerneighbortable.py`

### Findings
1. **Per-router orchestration duplicated in 3 collectors**
   - Pattern: fetch router table → build `router_rlocs` → iterate routers → lookup router metadata → call per-router collector.
   - Candidate destination: `src/otbr_cli_util.py`
   - Priority: High, Risk: Low

2. **ResponseTimeout detection and `_error` payload duplicated**
   - Same timeout regex and similar error envelope shape in childtable/childip6/routerneighbortable.
   - Candidate destination: `src/otbr_cli_util.py`
   - Priority: High, Risk: Low

3. **Telemetry line parser fragments duplicated**
   - `conn-time` parsing duplicated in childtable and routerneighbortable.
   - RSS/error-rate parsing structure also strongly similar.
   - Candidate destination: `src/otbr_cli_util.py` parser helpers, and/or `src/util_*.py` if reused beyond OTBR CLI.
   - Priority: Medium, Risk: Medium

4. **Device label / extaddr enrichment repeated**
   - Repeated safe lookup patterns for `device_label` from `extaddr_map`.
   - Candidate destination: `src/otbr_cli_util.py`
   - Priority: Medium, Risk: Low

5. **Main flow boilerplate repeated**
   - Logging setup, datadir resolution, extaddr map loading, output save pattern repeated.
   - Candidate destination: `src/otbr_cli_util.py` for OTBR collector runtime helpers.
   - Priority: High, Risk: Low

---

## Phase 4 — Remaining `otbr_cli_*` Review (Executed)
Targets:
- `src/otbr_cli_router_table.py`
- `src/otbr_cli_thread_network_info.py`

### Findings
1. **CLI startup/save scaffolding aligns with meshdiag duplication**
   - Datadir resolution and JSON-save wiring is repeated and can be standardized.
   - Candidate destination: `src/otbr_cli_util.py`
   - Priority: Medium, Risk: Low

2. **Extaddr-map loading behavior is repeated and inconsistent in logging details**
   - Some modules warn on missing map, others silently default to `{}`.
   - Candidate destination: `src/otbr_cli_util.py` shared loader
   - Priority: Medium, Risk: Low

3. **Cross-dataset utility opportunities are limited but present**
   - Generic list/record parser helpers could move to `util_*.py` only if reused by non-OTBR collectors.
   - Priority: Low, Risk: Medium

---

## Phase 5 — Consolidated Refactor Proposal and Sequencing (Prepared)

## Consolidated Extraction Matrix

### Keep in `src/otbr_cli_networkdiag_topology.py` (networkdiag-specific)
- TLV-specific parsing composition and networkdiag domain assembly.
- Multicast mode wrappers (`ff03::1`, `ff02::1`) as explicit entry points.
- `merge_device_record` (unless reused by other OTBR modules later).

### Move to `src/otbr_cli_util.py` (shared OTBR CLI collectors)
- Retry policy runner with pluggable TLV/detail strategy.
- Router-iteration orchestrator (`fetch routers + iterate + metadata callback`).
- Standard ResponseTimeout detection and error-envelope builder.
- Shared extaddr/device-label helpers.
- Shared OTBR collector main-flow helpers (datadir/extaddr/output lifecycle).
- Shared parser atoms for repeated telemetry rows (conn-time, RSS, err-rate).

### Move to `src/util_*.py` (cross-dataset generic utilities)
- Generic dict merge/upsert utilities only if reused outside OTBR CLI.
- Generic record-normalization helpers only when demonstrably shared by non-OTBR sources.
- Keep domain-specific Thread parsing out of generic util modules.

## Recommended Implementation Order (for later execution)
1. Introduce `src/otbr_cli_util.py` with non-breaking shared helpers.
2. Refactor `meshdiag` modules first (highest duplicate density, lower risk).
3. Refactor `networkdiag` retry/enrichment helpers second.
4. Unify CLI module startup/extaddr loading/save flows last.
5. Evaluate which helpers are truly cross-dataset before promoting to `util_*.py`.

## Review Gates Before Any Code Refactor
- Confirm function ownership boundaries (`networkdiag` internal vs shared utility).
- Approve error-envelope schema standardization.
- Approve parser helper contracts and return shapes.
- Ensure behavior parity requirements are defined for each migration step.

---

## Phase 6 — Utility/Core Module Expansion (Executed)
Targets:
- `src/util_convert.py`
- `src/util_data.py`
- `src/util_network.py`
- `src/util_ot_ctl.py`
- `src/td_cli.py`
- `src/td_const.py`
- `src/td_webserver.py`
- `src/extaddr_device_label_map.py`

### Findings
1. **Data-dir and output lifecycle patterns are now broadly standardized but still repeated in caller modules**
   - `resolve_data_dir`, `data_file_path`/`resolve_data_file_path`, and `save_json_atomic` are used across CLI/REST/mDNS/merge modules.
   - Candidate destination: keep in `util_data.py`; reduce call-site boilerplate via thin collector/runtime helpers.
   - Priority: High, Risk: Low

2. **Extaddr label-map loading exists in multiple forms**
   - `extaddr_device_label_map.load_extaddr_device_label_map(...)` and a separate `dataset_merge.load_extaddr_device_label_map(...)` overlap behavior.
   - Candidate destination: unify parser/validation in `extaddr_device_label_map.py`; keep dataset-specific adapter only if schema differs.
   - Priority: High, Risk: Medium

3. **Network enrichment utilities are concentrated but call-site classification remains duplicated**
   - `util_network` already centralizes prefix and classifier helpers; repeated call-site record assembly persists in collectors.
   - Candidate destination: new `util_network` composite helper(s) for node enrichment bundles.
   - Priority: Medium, Risk: Low

4. **`td_cli.py` dispatch chains can be table-driven**
   - Repetitive branch dispatch for nested commands can be represented with command maps.
   - Candidate destination: `td_cli.py` internal refactor (no new module required initially).
   - Priority: Medium, Risk: Medium

5. **`td_const.py` remains a good single source for shared constants**
   - Refactor opportunity is mostly governance: expand consistent constant usage for filenames and defaults across modules.
   - Candidate destination: keep in `td_const.py`.
   - Priority: Low, Risk: Low

6. **`td_webserver.py` has reusable cache/response patterns that should remain local for now**
   - Helper density is already high; extraction outside module not yet justified unless reused by another HTTP surface.
   - Candidate destination: keep internal to `td_webserver.py`.
   - Priority: Low, Risk: Low

---

## Phase 7 — OTBR REST API Module Expansion (Executed)
Targets:
- `src/otbr_restapi_cli.py`
- `src/otbr_restapi_download.py`
- `src/otbr_restapi_topology.py`
- `src/otbr_restapi_util.py`

### Findings
1. **Parser and client-bootstrapping patterns overlap between CLI/download/topology drivers**
   - Shared arguments (`host`, `port`, `timeout`, `datadir`, headers/base-url) and repeated client construction logic exist.
   - Candidate destination: `otbr_restapi_util.py` helper builders for parser fragments and client setup.
   - Priority: High, Risk: Medium

2. **JSON output/save + logging patterns repeat across restapi entry points**
   - Common “save payload to path and debug log JSON” shape appears in multiple modules.
   - Candidate destination: restapi-specific output helper module/function set.
   - Priority: Medium, Risk: Low

3. **Error normalization is centralized in `error_to_dict` but exit-code mapping is repeated**
   - `otbr_restapi_cli` and `otbr_restapi_topology` both maintain exception→exit-code mapping logic.
   - Candidate destination: `otbr_restapi_util.py` shared exit-code policy helper.
   - Priority: Medium, Risk: Low

4. **Fallback/retry orchestration exists in both CLI command handlers and client utility layer**
   - Candidate destination: keep network-call retries in `otbr_restapi_util.py`; keep command intent logic in `otbr_restapi_cli.py`.
   - Priority: Medium, Risk: Medium

---

## Phase 8 — mDNS / Eve / Merge Module Expansion (Executed)
Targets:
- `src/mdns_thread_scopes.py`
- `src/dataset_merge.py`
- `src/merge_extaddr_file_into_static_map.py`
- `src/eve_parse.py`

### Findings
1. **`mdns_thread_scopes.py` contains many field-specific enrichers with repeated shape**
   - Repeated “decode + format + structured field payload” functions suggest a table-driven decoder registry.
   - Candidate destination: internal registry in `mdns_thread_scopes.py` first; only promote generic bits if reused elsewhere.
   - Priority: Medium, Risk: Medium

2. **`dataset_merge.py` includes robust generic merge primitives reusable by other sources**
   - `deep_merge`, list merge, conflict tracking, identifier normalization are strong cross-source utility candidates.
   - Candidate destination: promote carefully selected generic functions to `util_data.py`/new `util_merge.py` only if needed by other modules.
   - Priority: Medium, Risk: Medium

3. **Extaddr label-map parsing duplication with dataset merge path**
   - `dataset_merge.load_extaddr_device_label_map` overlaps with `extaddr_device_label_map.py`.
   - Candidate destination: shared parser in `extaddr_device_label_map.py` plus optional dataset_merge wrapper.
   - Priority: High, Risk: Medium

4. **`eve_parse.py` and `merge_extaddr_file_into_static_map.py` share normalization/save scaffolding**
   - Similar “load-transform-save with datadir resolution” flow can use shared runtime helpers.
   - Candidate destination: shared lightweight collector runtime helper(s) in `util_data.py` or dedicated helper module.
   - Priority: Medium, Risk: Low

---

## Phase 9 — Expanded Consolidated Extraction Matrix (Prepared)

### Keep Local (module-specific)
- `td_webserver.py` cache, conditional-GET, and job-registry internals.
- `mdns_thread_scopes.py` protocol-specific decoders until reuse is proven.
- `otbr_cli_networkdiag_topology.py` TLV parser composition and multicast wrappers.

### Promote to `src/otbr_cli_util.py`
- Per-router collection orchestration (`router table → iterate → fetch`).
- ResponseTimeout detection/envelope helpers.
- Device label/extaddr enrichment helpers.
- Collector main-flow helpers (datadir/extaddr/output wiring).
- Shared retry policy helpers for OTBR CLI collectors.

### Promote to `src/otbr_restapi_util.py` (or restapi helper layer)
- Shared parser fragments for host/port/timeout/datadir/base-url/header options.
- Shared REST client bootstrap from normalized options.
- Shared exit-code/error policy helpers for REST API entry points.
- Shared save-and-log output helper for REST payload files.

### Promote to `src/util_*.py` only when cross-source reuse is confirmed
- Generic merge/conflict primitives from `dataset_merge.py`.
- Generic normalization helpers not tied to Thread protocol specifics.
- Shared JSON/file lifecycle utilities (if they reduce real duplication at call sites).
