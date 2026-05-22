# Draft Plan: OTBR CLI Refactor and Utility Extraction

## Structure (Phased)
1. Phase 1 — Baseline and Refactor Catalog
2. Phase 2 — `networkdiag` Extraction Review
3. Phase 3 — `meshdiag` Extraction Review
4. Phase 4 — Remaining `otbr_cli_*` Review
5. Phase 5 — Consolidated Refactor Proposal and Sequencing

> Draft-only plan. Do not execute until reviewed and approved.

## Phase 1 — Baseline and Refactor Catalog
- Confirm current collector boundaries using `doc/codebase_overview.md`.
- Define extraction buckets to use consistently across all reviews:
  - Common processing functions (domain logic used in multiple collectors)
  - OTBR CLI utility functions (command execution, retries, shared collector orchestration)
  - Cross-dataset utility functions (general parsing/normalization reusable in `util_*.py`)
- Create an inventory table template capturing:
  - Source file/function
  - Duplicate pattern
  - Proposed destination (`otbr_cli_networkdiag_topology.py`, `otbr_cli_util.py`, `util_*.py`)
  - Priority and migration risk

## Phase 2 — `networkdiag` Extraction Review
Target file: `src/otbr_cli_networkdiag_topology.py`

- Review these required functions and child functions:
  - `fetch_network_diag_topology`
  - `fetch_network_diag_multicast`
  - `fetch_network_diag_topology_multicast_network`
  - `fetch_network_diag_topology_multicast_neighbors`
- Identify reusable common processing candidates inside `networkdiag` flow, including:
  - Retry + TLV downgrade orchestration
  - Node record defaults and fallback construction
  - Node enrichment/classification (`type`, border-router detection, OMR matching)
  - Merge and dedupe flows for multicast/unicast consolidation
  - Child expansion traversal and polling loop patterns
- Mark which helpers should stay internal to `otbr_cli_networkdiag_topology.py` versus moved to shared modules.

## Phase 3 — `meshdiag` Extraction Review
Target files:
- `src/otbr_cli_meshdiag_topology.py`
- `src/otbr_cli_meshdiag_childip6.py`
- `src/otbr_cli_meshdiag_childtable.py`
- `src/otbr_cli_meshdiag_routerneighbortable.py`

- Apply the same extraction categories from Phase 2.
- Focus on duplicated meshdiag patterns:
  - Per-router iteration pattern (`fetch_and_parse_router_table` + per-router collector call)
  - Repeated timeout handling with standardized `_error` payload
  - Repeated metadata enrichment (`device_label`, `thread_version`)
  - Repeated line-parser fragments (RSS, error-rate, conn-time blocks)
  - Repeated `main()` setup flow (datadir resolution + extaddr map loading + JSON save)
- Map candidates to `otbr_cli_util.py` (new shared OTBR CLI helpers) and to `util_*.py` where domain-agnostic.

## Phase 4 — Remaining `otbr_cli_*` Review
Target files:
- `src/otbr_cli_router_table.py`
- `src/otbr_cli_thread_network_info.py`

- Evaluate remaining reusable patterns and confirm compatibility with prior extraction candidates.
- Identify opportunities to standardize:
  - Common CLI module startup wiring
  - Shared extaddr-map loading behavior
  - Common save/log patterns for JSON outputs
- Validate no duplication category was missed across all `src/otbr_cli_*.py` modules.

## Phase 5 — Consolidated Refactor Proposal and Sequencing
- Produce a consolidated extraction matrix grouped by destination:
  - Keep in `src/otbr_cli_networkdiag_topology.py` (networkdiag-specific helpers)
  - Move to `src/otbr_cli_util.py` (shared OTBR CLI collector helpers)
  - Move to `src/util_*.py` (cross-dataset generic utilities)
- Define recommended implementation order:
  1. Introduce shared helpers
  2. Migrate one collector at a time
  3. Verify behavior after each migration batch
- Define review gates for approval before execution:
  - Function ownership and naming approval
  - Backward compatibility constraints
  - Risk and rollback strategy

## Initial Candidate Hotspots (from current review)
- Shared per-router collection orchestration across meshdiag files.
- Shared timeout/error envelope creation across meshdiag and networkdiag.
- Shared extaddr/device-label/thread-version enrichment helpers.
- Shared record finalization for OMR/border-router/type classification.
- Shared parser fragments for repeated telemetry lines (RSS, err-rate, conn-time).
- Shared module `main()` setup pipeline (datadir, extaddr map, save_json).
