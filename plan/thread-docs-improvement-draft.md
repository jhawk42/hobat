# Thread Mesh Documentation Improvement Plan (Draft)

Status: Draft for review only. Do not execute until approved.

## Plan Structure (Phased)

1. Phase 1 — Audience, onboarding path, and information architecture
2. Phase 2 — Quickstart and first-success workflows
3. Phase 3 — Thread concepts and data model docs
4. Phase 4 — Task-oriented guides (CLI, REST API, dashboard)
5. Phase 5 — Troubleshooting and diagnostics playbooks
6. Phase 6 — Reference quality, consistency, and navigation improvements
7. Phase 7 — Validation, feedback loop, and maintenance process

## Top 10 Documentation Improvements

1. Add role-based **Start Here** guide for Thread users vs. engineers.
2. Add a 10-minute **Quickstart** that gets from zero to first topology view.
3. Add a **Prerequisites and environment matrix** (Docker/manual, OTBR, network assumptions, required ports, permissions).
4. Add a clear **Data source decision guide** (otbr-cli vs otbr-restapi vs mDNS vs Eve) with tradeoffs and expected latency.
5. Add a **Thread concepts primer** tied to tdash fields (RLOC16, extaddr, OMR, FTD/MTD, BR, TLVs) and where each appears.
6. Add **end-to-end workflow guides** for common goals (health check, full topology sweep, merged dataset creation, label mapping).
7. Add a consolidated **Troubleshooting section** for setup failures, stale/missing files, empty datasets, permission errors, API errors, and mDNS discovery issues.
8. Add a **Diagnostics interpretation guide** (how to read MAC/MLE counters, link quality, neighbor metrics, and when to investigate).
9. Add a **Known limitations and performance expectations** section (sync vs async jobs, action durations, large network behavior, timeouts).
10. Add a **Documentation IA cleanup** with cross-links, reduced duplication, a central command index, and versioned change notes for breaking CLI behavior.

## Implementation Findings (No Code Changes)

This pass implemented the plan as a documentation audit and gap analysis only.

### Current Coverage Snapshot

- **Strong coverage exists** for deep technical reference:
  - `doc/help_td_restapi_cli.md` provides detailed command reference depth.
  - `doc/codebase_overview.md` covers architecture, data flow, and testing entry points.
  - `doc/help_td_cli.md` and `doc/datadir_model.md` document CLI behavior and data-dir precedence.
- **Partial coverage exists** in `README.md` for setup and command examples.
- **Major gaps remain** for beginner onboarding and operational guidance:
  - No role-based "Start Here" path.
  - No explicit 10-minute quickstart to first topology visualization.
  - No consolidated troubleshooting playbook.
  - No "known limitations/performance expectations" section.
  - No centralized docs index mapping user goals to files.

### Findings Mapped to Top 10 Items

1. **Start Here guide**: Not present (gap).
2. **10-minute Quickstart**: Not present as a focused flow (gap).
3. **Prerequisites/environment matrix**: Partially present, fragmented across docs (partial).
4. **Data-source decision guide**: Not present as decision matrix/tradeoff doc (gap).
5. **Thread concepts primer mapped to tdash fields**: Partially present in overview, not user-oriented (partial).
6. **End-to-end workflows**: Partially present as command examples, not goal-driven guides (partial).
7. **Troubleshooting section**: Not present in consolidated form (gap).
8. **Diagnostics interpretation guide**: Not present as interpretation-focused guidance (gap).
9. **Known limitations/performance expectations**: Not present as dedicated section (gap).
10. **IA cleanup with command index/cross-links/change notes**: Partial; significant consolidation opportunity remains (partial).

## Feedback and Recommendations

1. **Prioritize onboarding before adding more reference depth.** Existing docs are strong for experienced operators but high-friction for first-time users.
2. **Create a single navigation hub** (README "Docs Index") that points to setup, quickstart, operations, troubleshooting, and reference.
3. **Split documentation by audience and intent**:
   - "Operator quick wins" (run, fetch, view topology).
   - "Engineer deep dive" (architecture, merge strategy, diagnostic semantics).
4. **Standardize command examples** around one canonical invocation style and datadir handling to reduce ambiguity.
5. **Add troubleshooting + limits early** to reduce repeated support/debug loops.

## Validation Notes

- No source code changes were made in this pass.
- Updates are limited to this plan markdown file.
- Baseline test run in this environment identified pre-existing test/module issues unrelated to this documentation-only update.
