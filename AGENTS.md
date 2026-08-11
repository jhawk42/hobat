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
- For frontend changes, use the linked browser when available to confirm layout, scrolling, filtering, and dataset-specific behavior did not regress.
- Preserve existing regression coverage patterns in `tests/`; extend nearby tests instead of adding broad new harnesses when a focused test will do.

## Conventions

- Keep comments concise. Prefer one short line stating the non-obvious constraint, or no comment at all.
- Preserve the established file naming style and source prefixes rather than introducing new naming schemes.
- Favor minimal, local changes over broad refactors unless the task explicitly asks for structural cleanup.