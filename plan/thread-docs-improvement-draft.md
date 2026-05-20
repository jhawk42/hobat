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

