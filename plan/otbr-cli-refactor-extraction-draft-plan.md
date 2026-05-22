# Draft Plan: OTBR CLI Refactor and Utility Extraction (Phases Executed for Discovery)

## Structure (Phased)
1. Phase 1 — Baseline and Refactor Catalog
2. Phase 2 — `networkdiag` Extraction Review
3. Phase 3 — `meshdiag` Extraction Review
4. Phase 4 — Remaining `otbr_cli_*` Review
5. Phase 5 — Consolidated Refactor Proposal and Sequencing

> Discovery executed in sequence to collect refactoring information only.  
> No production code changes performed.

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
