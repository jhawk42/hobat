# tdash Architecture, Reliability, and Data-Flow Review

## Phase 0 — Scope Confirmation and Review Gate

### Findings
- Scope is now approved for analysis writeback.
- Current request is documentation-only: record findings and proposals in this file, with no source-code implementation yet.

### Proposals
- Keep this document as the source-of-truth plan for implementation sequencing.
- Gate implementation by priority tiers (P0/P1/P2) defined in Phase 8.

---

## Phase 1 — End-to-End Data-Flow Trace and Loss Audit (OTBR → td_cli → td_webserver → tdash.html)

### Findings
- Server data path is explicit: `/api/data/{filename}` validates filename, maps to `FILE_ACTION_MAP`, conditionally regenerates via `td_cli.py`, then serves bytes with cache headers and ETag.
- Long or forced-async actions return `202` + `/api/job/{id}` polling; browser handles this in `fetchJson()` and `pollJobUntilDone()`.
- Browser dataset loading tolerates partial failures via `Promise.allSettled()`; it proceeds if at least one file loads.
- Identity merge exists in both Python (`dataset_merge.py`) and browser (`tdash-merge.js`) with shared identity concepts (`rloc16`, extaddr aliases, OMR IPv6).
- Potential data-loss/visibility gap: when some files fail but others load, UI status is present but merged output may hide missing source context from users/operators.

### Proposals
- Add a unified dataset-load health summary model (loaded, failed, stale age, source list) and surface it prominently in UI and API.
- Add explicit provenance/coverage indicators in merged views so operators can see which source files contributed to each node.
- Define a regression matrix for key flows: cache-hit, cache-miss, forced no-cache, long-cost async completion, and partial dataset failure.

---

## Phase 2 — Architecture and Module Boundary Review

### Findings
- Layering is mostly clean: collectors/parsers → CLI dispatcher → aiohttp server → browser rendering modules.
- Data-dir resolution is centralized (`util_data.py`) and documented with strict precedence (`TD_DATA_DIR` > `--datadir` > defaults).
- File generation policy is hard-coded in a large `FILE_ACTION_MAP`; this is clear but increases coordination cost across server/UI/docs.
- Browser modules are well-separated by concern (registry, dataset loader, merge, filters, renderers), but rely on shared global DOM IDs and mutable module state.

### Proposals
- Introduce a single schema/config source for dataset/file metadata (name, source, expected cost, merge strategy) consumed by server and UI.
- Define and document stable contracts for each layer:
  - Collector output schema contract
  - Server file/action contract
  - Browser dataset capability contract
- Add a lightweight architectural decision record (ADR) for regeneration semantics, async thresholds, and merge identity precedence.

---

## Phase 3 — Reliability, Error-Handling, and Recovery Review

### Findings
- Atomic JSON writes are implemented (`save_json_atomic`) and reduce partial-write corruption risk.
- Subprocess timeout handling exists in server (`run_td_cli` with kill/reap on timeout).
- Job registry tracks running/done/error and performs periodic TTL cleanup.
- Error details returned by `/api/job/{id}` are currently coarse (`td_cli exit code X`) and may limit operator diagnosis.
- Some exception handling paths intentionally swallow malformed header parsing and continue (safe for availability, but less observable).

### Proposals
- Standardize structured error payloads for failed jobs (source, action args, timeout class, retryability hint, timestamp).
- Add explicit retry/backoff policy guidance for UI polling and failed file generations.
- Add a “degraded mode” indicator when only partial datasets load, including actionable remediation text.

---

## Phase 4 — Locking, Concurrency, and Memory-Leak Review

### Findings
- Concurrency controls are intentional and tested:
  - Same-filename dedupe via `_active_processes`
  - Per-source serialization via `_source_locks`
  - Async job tracking via `_job_registry` and `_background_tasks`
- Job registry has TTL cleanup; source locks are lazily created and currently unbounded in key count (comment already notes potential growth concern).
- Shutdown path cancels cleanup/background tasks, which reduces lingering task risk.

### Proposals
- Add bounded lifecycle management for `_source_locks` (evict idle unlocked entries using last-used timestamps).
- Add observability counters for lock wait time and queue depth by source to detect starvation.
- Add concurrency stress tests for mixed long/short jobs across multiple sources with cancellation and timeout scenarios.

---

## Phase 5 — Observability and Troubleshooting Logging Plan

### Findings
- Logging is present at key boundaries (spawned subprocess, stdout/stderr capture, data-dir resolution, startup info).
- Current logs are mostly unstructured text; correlation between request, background job, and subprocess execution is limited.
- UI status text helps with elapsed fetch timing but is not persisted/exported for diagnostics.

### Proposals
- Introduce structured log fields across server operations:
  - request_id, job_id, filename, source, action_cost_s, force_async, duration_ms, outcome
- Add timing metrics around regenerate/serve decisions (cache hit ratio, regeneration latency, timeout counts).
- Add optional debug endpoint (read-only) for recent job outcomes and source lock state for troubleshooting.

---

## Phase 6 — CI/GitHub Workflow Improvement Plan

### Findings
- Existing workflow (`.github/workflows/docker-build.yml`) builds and pushes Docker images on `main`, `dev`, schedule, and manual dispatch.
- No visible workflow in-repo for mandatory lint/test/security gates before image publish.
- Current pipeline emphasis is delivery (build/push), with limited pre-publish quality gate visibility.

### Proposals
- Add separate CI workflow for PRs and branches:
  - Unit tests (pytest)
  - Static checks/format checks
  - Security checks (dependency and code scanning as available)
- Make Docker publish depend on passing CI gates.
- Add branch protection requirements tied to the CI workflow.

---

## Phase 7 — Dockerfile and Container Runtime Improvement Plan

### Findings
- Docker image uses `python:3.14-slim-bookworm`, installs docker CLI, installs Python deps from `requirements.txt`, and runs `td_webserver.py`.
- Runtime model assumes docker-socket mount for OTBR docker-exec behavior.
- Image currently copies full repository context into `/app`, then runs in `/app/src`.

### Proposals
- Harden image build/runtime:
  - Run as non-root where feasible
  - Add minimal healthcheck for webserver readiness
  - Reduce attack surface and image size (review apt/pip footprint)
- Clarify and document docker-socket risk and least-privilege runtime alternatives.
- Add deterministic dependency management strategy (pinning/constraints policy) for reproducibility.

---

## Phase 8 — Consolidated Prioritized Change Plan and Rollout

### P0 (first implementation wave)
1. Dataset health/provenance visibility across API + UI.
2. Structured job error model and improved operator-facing failure detail.
3. CI workflow with tests/checks/security gating before publish.

### P1 (second wave)
1. `_source_locks` lifecycle management and lock observability metrics.
2. Unified config/schema for dataset/file metadata across server and UI.
3. Container hardening baseline (non-root, healthcheck, runtime guidance).

### P2 (third wave)
1. Extended stress/concurrency test scenarios.
2. Additional diagnostics endpoint(s) for operational introspection.
3. Documentation refinements (runbook/troubleshooting/ADR set).

### Rollout Approach
- Implement P0 changes behind low-risk, incremental PRs with tests per area.
- Validate each phase with targeted regression matrix (cache, async jobs, partial failure handling).
- Proceed to P1/P2 only after P0 telemetry and stability outcomes are confirmed.
