# Project Guidelines

## Codebase Orientation

Read these first before making non-trivial changes so the agent does not rediscover the same context each session:

- [Codebase Overview](doc/codebase_overview.md)
- [Webpage, Web Server, and Data Flow](doc/codebase_webpage_web_server_data_flow.md)

Use [README.md](README.md) for operator-facing behavior, setup, and runtime expectations.

## Architecture

- Treat tdash as a cache-first system: prefer fixes that preserve cached snapshot workflows and avoid adding unnecessary live mesh load.
- Keep the source split explicit: `otbr_cli_*.py` is OTBR `ot-ctl`, `otbr_restapi_*.py` is OTBR REST, `mdns_*.py` is Zeroconf/mDNS, `src/js/*.js` is browser-only dashboard logic.
- Prefer changes in the layer that owns the behavior. Avoid pushing source-specific logic into unrelated shared utilities or UI glue.
- Keep Python server/collector changes aligned with the documented data flow between `td_cli.py`, `td_webserver.py`, the data directory, and the dashboard fetch/render path.

## Workflow

- When asked for a plan, phased rollout, review report, or backlog summary, match the existing markdown style already used under `plan/` and `doc/` instead of inventing a new format.
- For multi-phase work, present the phase structure first when the user asks for planning or approval, then execute phases in order.
- When updating documentation or review artifacts, link related repo files instead of duplicating large blocks of existing content.
- When a task touches both implementation and documentation, update the documentation in the same change if behavior or operator expectations changed.

## Validation

- Prefer the narrowest validation that matches the touched area: targeted `pytest` tests for Python, focused browser/UI checks for `tdash.html`, `tdash.css`, or `src/js/*.js`, and route/data-flow checks for webserver changes.
- For frontend changes, use the linked browser and start `td_webserver.py` on port 9178 with `--datadir ./data`. Enable Cache Only before the first Sync, derive source/dataset/filter inventories from rendered DOM options, and hash `data/` before and after broad acceptance runs so tests cannot silently repair fixtures through live calls.
- In Playwright, attach console, page-error, failed-request, and HTTP-status instrumentation before reload and track the active source, dataset, view, and filter value. For hidden selects, set `value` and dispatch a bubbling `change` event; if actionability waits are flaky, use a native click and poll `#btn-fetch` plus `#view-status-line-content` directly.
- Validate topology from the visible `Showing: N nodes, M links` status, positive canvas dimensions, and nonblank pixels after stabilization; zero links are valid. Validate tables from rendered rows/headers, `.table-wrap` scrolling, and no document-level mobile overflow. Exercise only offered options, require exact baseline restoration after resets, accept HTTP 200/304, and classify explicit error states rather than the bare word `Error` in diagnostic labels.
- Stop the test server, confirm port 9178 is free, and verify cached file hashes are unchanged after browser validation.
- Preserve existing regression coverage patterns in `tests/`; extend nearby tests instead of adding broad new harnesses when a focused test will do.

## Conventions

- Keep comments concise. Prefer one short line stating the non-obvious constraint, or no comment at all.
- Preserve the established file naming style and source prefixes rather than introducing new naming schemes.
- Favor minimal, local changes over broad refactors unless the task explicitly asks for structural cleanup.