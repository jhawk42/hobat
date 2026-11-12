# Hobat Codebase Overview

## Architecture

Hobat is a cache-first system. Collectors write atomic snapshots into one data
directory; cache-only processing builds Unified products and health assessments;
the web server serves cached data or invokes the CLI for an explicit processing
or collection action. Browser modules assemble dataset rows, derive device
projections, adapt topology models, filter, lay out, and render the returned data.

```text
OTBR CLI / OTBR REST / HA Matter WS / mDNS / Eve exports
                 |
                 v
        Python collectors and parsers
                 |
                 v
       data/*.json snapshots and scope companions
                 |
                 v
       cache-only Unified / health processing
                 |
                 v
       committed Unified files / hobat_v1.db
                 ^
                 |
Browser <---- aiohttp web server ----> td_cli subprocess
```

Eve and Thread Tools also provide operator-managed export inputs; Thread Tools
conversion belongs to the browser adaptor rather than a live Python collector.
The snapshot path is not the only browser/server flow. The dashboard also reads
health assessments from `hobat_v1.db`, can request cache-only health processing,
and can start transient device diagnostics. Source capabilities report cached
files and source availability; when needed, the server performs bounded
reachability probes. Device labels use a separate static-map read/update API.

| Layer | Owners | Responsibility |
|---|---|---|
| Browser | `src/tdash.html`, `src/tdash.css`, `src/js/*.js` | Dataset selection, fetch sessions, merge/adaptation, filters, layouts, topology/table and Thread Network views, health views, appearance, and device actions |
| HTTP server | `td_webserver.py` | Static assets, catalog and source capabilities, data allowlist, cache policy, jobs, health APIs, device actions, and device labels |
| CLI dispatcher | `td_cli.py` | Top-level command tree and command-family dispatch |
| Collectors | `otbr_cli_*.py`, `otbr_restapi_*.py`, `ha_matter_ws_*.py`, `mdns_*.py`, `eve_process.py` | Live collection, parsing, normalization, checkpoints, final snapshots |
| Processing | `td_unified_dataset.py`, `merge_dataset.py`, `merge_extaddr_device_label_map.py`, `td_health_*.py`, `td_system_*.py` | Cache-only Unified materialization, cross-source merge, label-map administration, health assessment/history, and system administration |
| Shared contracts | `td_const.py`, `td_dataset_catalog.py`, `td_network_identity.py`, `td_source_authority.py`, `td_source_capabilities.py`, `td_device_fields.py`, `td_device_merge.py`, `td_record_merge.py`, `td_json_key_normalizer.py`, `util_*.py` | Catalog validation, source availability, filenames, identities, fields, merge policies, data paths, network and subprocess helpers |
| Persistence | Effective data directory | Operator inputs, generated snapshots, and the Hobat-wide `hobat_v1.db` SQLite store |

Runtime dependencies include `aiohttp`, `websockets`, and `zeroconf`. The browser
uses vendored vis-network; dashboard table sorting is application-owned.

## Python Modules

### Entry Points and Shared Contracts

| File | Responsibility |
|---|---|
| `td_cli.py` | Dispatcher for `otbr-cli`, `otbr-restapi`, `ha-matter-ws`, `mdns`, `process-eve`, `unify-dataset`, `source-probe`, `health`, `system`, `merge-dataset`/`merge-data`, and `merge-extaddr` |
| `td_unified_dataset.py` | Cache-only Unified source-primary assembly and catalog-owned four-primary composition with original raw authority/lineage, one outer lock, report-last publication/recovery, verified generation reads, and CLI |
| `td_webserver.py` | aiohttp application, dataset catalog, source capabilities, file action registry, HTTP caching, background jobs, health APIs, device actions, and device-label API |
| `td_logging.py` | Shared logging configuration, structured collector events, and redaction of Thread secrets in sensitive output |
| [td_collection_outcomes.py](../src/td_collection_outcomes.py) | Immutable, versioned collection facts, explicit attempt histories, bounded reason vocabulary, and shared outcome summaries; no evidence qualification or inferred attempts |
| `td_dataset_catalog.py` | Dataset manifest validation and runtime catalog loading, including health roster policy projections |
| `td_source_capabilities.py` | Cached source/file inventory and deduplicated, bounded dashboard availability probes; fresh live-only collection preflights through `td_cli source-probe` |
| `td_source_authority.py` | Source-priority and per-field authority resolution from the catalog |
| `td_network_identity.py` | Canonical Extended PAN IDs, network instance IDs, and observed/operator/unknown scope provenance |
| `td_device_actions.py` | Validation and allowlisted command construction for transient device diagnostics |
| `td_const.py` | Authoritative Python cache filenames, data-directory constants, and Thread multicast addresses |
| `td_device_fields.py` | Python field definitions, preferred names, aliases, identities, and placeholders |
| `td_device_merge.py` | Shared merge context, source ordering, and domain merge policy |
| `td_record_merge.py` | Record/object/array merge primitives, conflict and provenance handling |
| `td_json_key_normalizer.py` | Recursive conversion to preferred field names |
| `otbr_role_evidence.py` | Positive OTBR child/FTD evidence normalization for REED state |

### OTBR CLI

| Files | Responsibility |
|---|---|
| `otbr_cli_thread_network_info.py` | Active dataset, mesh-local prefix, and favored OMR prefix |
| `otbr_cli_bbr.py` | Border Router information collection |
| `otbr_cli_device.py` | Explicit active device ping and counter-reset operations |
| `otbr_cli_router_table.py` | Router table collection and parsing |
| `otbr_cli_meshdiag_topology.py` | Mesh topology, addresses, links, and children |
| `otbr_cli_meshdiag_childip6.py` | Per-router child IPv6 tables |
| `otbr_cli_meshdiag_childtable.py` | Per-router child diagnostic tables |
| `otbr_cli_meshdiag_routerneighbortable.py` | Per-router neighbor diagnostic tables |
| `otbr_cli_networkdiag_topology.py` | Multicast and fetch-all network diagnostics, retries, reconciliation, and checkpoints |
| `otbr_cli_networkdiag_parsers.py`, `otbr_cli_networkdiag_util.py` | Network Diagnostic TLV parsing and collection helpers |
| `otbr_cli_util.py`, `util_ot_ctl.py` | Shared data loading and Docker/local `ot-ctl` execution |

Command collectors own mandatory final snapshots. The success order is:

```text
collect -> normalize -> atomic save -> return
```

Reusable collectors remain side-effect free when no output path is supplied.
Progressive `.partial.json` files are separate checkpoints and never replace the
mandatory final snapshot.

The per-router `meshdiag routerneighbortable`, `childtable`, and `childip6`
collectors record an explicit table attempt for every queried router. On a
timeout or explicit OTBR error, they may issue one bounded, two-attempt ping to
that router's validated mesh-local RLOC IPv6 address. Ping evidence is distinct
from table evidence: a reply does not turn a failed table collection into a
success, and an all-failed run retains its prior final snapshot. Some router
implementations (for example Apple HomePods) never return these tables. A
router whose attempt failed, whose tables are empty, and which replied to the
ping is classified `not-provided` by `classify_meshdiag_router_table` in
`otbr_cli_util.py`: it is expected and contributes zero table entries. A run
is complete when every router either answered or is `not-provided` and at least
one router answered.

### OTBR REST API

| File | Responsibility |
|---|---|
| `otbr_restapi_util.py` | Filesystem-free HTTP client, JSON:API flattening, retries, polling, and shared errors |
| `otbr_restapi_cli.py` | REST command parser, dispatch, stdout rendering, output resolution, and exit mapping |
| `otbr_restapi_node.py` | Node, state, and active-dataset commands |
| `otbr_restapi_devices.py` | Device list/get/fetch commands and device checkpoints |
| `otbr_restapi_diagnostics.py` | Diagnostic list/get/fetch/fetch-all, TLV fallback, child expansion, progress, checkpoints, and outcome publication |
| `otbr_restapi_mesh_diagnostics.py` | Children, child IPv6, router-neighbor, and batch mesh diagnostics with optional bounded diagnostic-response checks |
| [otbr_restapi_outcomes.py](../src/otbr_restapi_outcomes.py) | Read-only collection-fact views over reconciled REST diagnostics and mesh evidence, retaining initial/effective status and verified attempts |
| [td_restapi_diagnostic_recovery.py](../src/td_restapi_diagnostic_recovery.py) | Pure reconciliation of same-run child/router recovery, per-field availability, scope/digest bindings, and retained recovery provenance |
| [td_restapi_mesh_evidence.py](../src/td_restapi_mesh_evidence.py) | Pure eligibility, identity/time/scope checks, child-table witnesses, and REST mesh responsiveness qualification |
| `otbr_restapi_actions.py` | Action list/get/enqueue commands |
| `otbr_restapi_topology.py` | Composite devices, diagnostics, and mesh-diagnostics sweep |
| `otbr_restapi_download.py` | Fixed endpoint snapshot download |

Batch REST diagnostics retain device mode from the selected roster. The default
mode-aware policy uses an MTD fast pass, an optional MTD detail pass, and one
FTD medium pass; it does not affect single-device diagnostics or mesh
diagnostics. Same-set retries and pass outcomes belong to the diagnostic client,
while the dispatchers own the canonical output and atomic provisional
checkpoints. Missing or contradictory child mode remains an explicit legacy
fallback rather than a guessed classification.

For standard extended-address batches, the shared client skips any selected
record with the explicit canonical-zero `mlEidIid` sentinel, independent of
role or mode. Missing or noncanonical IID evidence keeps the existing request
path. Guard skips are unresolved addressability, not offline evidence;
dispatchers retain an all-guarded empty diagnostic snapshot and persist the
current skip outcome separately. `queriedCount` includes normalized skips,
while `attemptedCount` counts only devices with a diagnostic attempt.

Standalone `diagnostics fetch-all` enables child RLOC expansion by default;
`--no-children-expand-by-rloc` disables it and is required for alternate
destination types. This second, one-level phase derives six-character child RLOC
destinations from this run's parent `rloc16` and `childTable`, reuses the child
pass policies, and validates the returned identity before publishing or
checkpointing. Results are kept in a separate `childrenExpansion` outcome
object, so base counters keep their meaning. The dispatcher only labels
expansion checkpoints and preserves the prior snapshot when an incomplete
expansion yields no items. Shared client calls, topology, mesh diagnostics, and
single-device commands retain their existing defaults.

Standalone diagnostic and mesh-diagnostic batches persist full outcome
companions even with `--items-only`; that flag changes the returned item shape,
not the retained evidence. Recovery qualification uses original snapshot and
scope bindings, not a pre-existing claim of recovery. Initial failure,
effective status, field availability, responsiveness, and table coverage remain
separate facts.

`mesh-diagnostics fetch-all --diagnostic-response-fallback` opts into one bounded
Network Diagnostics check per eligible failed router at its extended address.
It requires router-only selection and validates a fresh matching response,
network scope, and child-table witnesses before qualifying `not-provided`
coverage. It does not use ping or turn a response into a successful mesh table.

Transport methods do not write files. Resource dispatchers or composite
workflows own command output because they know the command and resolved path.
Mutating action POSTs are not retried after an ambiguous response because the
OTBR action API has no idempotency key; idempotent reads use bounded retries.
Truncated, timed-out, or reset response reads use that same attempt/deadline
budget and discard incomplete bytes. Broken HTTP error bodies retain their
known status. An interrupted action POST remains indeterminate: no replay or
polling is started without an acknowledged action ID.

### Home Assistant Matter WebSocket

| File | Responsibility |
|---|---|
| `ha_matter_ws_client.py`, `ha_matter_ws_contract.py` | Correlated WebSocket transport, handshake compatibility, and pinned Matter paths |
| `ha_matter_ws_extractor.py`, `ha_matter_ws_snapshots.py` | Matter node decoding, canonical records, coverage, and credential exclusion |
| [ha_matter_ws_roles.py](../src/ha_matter_ws_roles.py) | Source-owned Thread role normalization, explicit boolean precedence, and conflict retention |
| `ha_matter_ws_topology.py` | Directional neighbor, child, route, and placeholder topology derivation |
| `ha_matter_ws_thread.py` | Native Thread Border Router and selected-network diagnostics validation and collection |
| `ha_matter_ws_native_topology.py` | Native schema-13 network-topology validation |
| `ha_matter_ws_unified.py` | Pure cached inventory/native/projection conversion, native link binding, original times/outcome checks; no client or collection imports |
| `ha_matter_ws_fetch_all.py`, `ha_matter_ws_cli.py` | One-snapshot orchestration, checkpoints, atomic files, outcome, and source CLI |

The source is read-only and controller-scoped. Its fallback URI is
`ws://localhost:5580/ws`; environment variables and CLI endpoint options can
override it. Missing or unavailable node telemetry remains
explicitly absent. It does not replace OTBR network-wide collection.
Failed handshake entry attempts one close within the existing connection
timeout, preserving the original error or cancellation. A close failure/timeout
is reported as incomplete cleanup, not guaranteed peer acknowledgement.

HA Unified admission requires positive cached Thread diagnostic, interface,
native topology, or Border Router evidence. Thread/Wi-Fi and Thread/Ethernet
hybrids remain eligible; unknown or conflicting observations are excluded
without declaring them non-Thread. Native node IDs stay separate from Matter
fabric/node IDs. Typed native links retain their directions and measured
metrics, not fabricated OTBR tables or signal measurements. Original controller
snapshot times and artifact bindings remain distinct from native collection
times and do not establish network-wide absence authority.

### Other Sources and Processing

mDNS checkpoint failures are handed back to the main waiter before discovery
shutdown and monitor join; a collection or cleanup failure retains prior finals.
OMR enrichment in mDNS, topology collectors, and Eve uses explicit full CIDR
evidence. Shortened legacy display prefixes are retained but never assigned a
guessed mask; missing/conflicting evidence skips optional enrichment.

| Files | Responsibility |
|---|---|
| `mdns_thread_scopes.py`, `mdns_hap.py`, `mdns_matter.py`, `mdns_meshcop.py`, `mdns_thread_util.py` | Zeroconf discovery and source-specific service normalization |
| `eve_process.py` | Eve export parsing, identifier conversion, and topology enrichment |
| `merge_dataset.py` | Input selection, normalization, identity-aware merge, validation report, and merged snapshot |
| [merge_report.py](../src/merge_report.py) | Merge command input/result contracts, viable seed-identity checks, and atomic dataset/report publication with network context |
| `merge_policy_identity.py`, `merge_policy_mdns.py`, `merge_policy_relationship.py` | Domain-specific identity matching, mDNS record handling, and relationship/route merge policy used by dataset merging |
| `merge_extaddr_device_label_map.py` | Bulk merge plus single-record read/upsert for the static label map |
| `extaddr_device_label_map.py` | Static label-map loading |
| `td_health_manifest.py`, `td-dataset-manifest.json` | Approved health dataset/profile contracts shared with browser registry metadata |
| `td_health_rules.py`, `td-health-rules.json` | Health finding catalog validation and stable rule metadata |
| `td_health_cli.py` | Health processing, comparison, bounded history preparation, roster, schema/history migration, and retention command dispatch |
| `td_health_processor.py`, `td_health_evaluator.py` | Stable cached-file reads, safe normalization, completeness, tagged evaluation context, and Python-owned verdicts |
| `td_health_unified.py` | Immutable original-evidence closure, retained Unified reproduction contracts, source times, and domain-qualified absence witness identity; no collector or schema changes |
| `td_health_observation_model.py`, `td_health_policy.py` | Frozen domain contracts and validated health policy |
| `td_health_observation_store.py`, `td_health_sqlite.py`, `td_health_history.py` | Observation persistence boundary, SQLite transactions, current assessment, and bounded retention |
| [td_health_preparation.py](../src/td_health_preparation.py) | Versioned, digest-checked compressed observation/pair preparation with bounded storage; native retained samples remain authoritative |
| `td_health_migration.py` | Read-only retained-history inventory, replay adapters, backup-first transactional migration, and report generation |
| `td_health_manifest_history.py`, `td-dataset-manifest-history.json` | Immutable reviewed historical contracts and history-only source/target resolution; no Git or database I/O |
| `td_health_graph.py`, `td_health_roster.py`, `td_health_roster_mutation.py`, `td_health_comparison.py` | Topology evidence graph, roster projections and lifecycle mutations, and stored-assessment comparisons |
| `td_health_read.py`, `td_webserver.py` health routes | Query-only SQLite projections, assessment pinning, grouped findings, bounded history, and no-store HTTP responses |
| `td_system_backups.py`, `td_system_cli.py`, `td_system_database.py`, `td_system_ping.py` | Data-directory backup/restore, SQLite database repacking, and bounded host ping |
| `util_data.py` | Data-directory resolution and atomic JSON/text writes |
| `util_network.py`, `util_convert.py`, `util_mac_counters.py` | Network, address conversion, and counter helpers |
| `profile_wrapper_td_cli.py`, `profile_wrapper_td_webserver.py` | Development profiling wrappers |

### Cache-only Unified and Health Processing

[td_unified_dataset.py](../src/td_unified_dataset.py) materializes four source
primaries (OTBR CLI, OTBR REST, HA Matter, and mDNS) and their Multi-source
composition from catalog-declared cached finals. `unify-dataset --dataset all`
builds the source primaries before Multi-source and stops on the first failure;
earlier committed products remain intact. Missing required inputs need explicit
`--allow-partial`; invalid present evidence is not silently repaired.

One data-directory lock covers dependency preparation, recovery, and publication.
The report is replaced last as the commit marker; generation reads validate
artifact bindings, and evidence consumers additionally verify original inputs.
Unchanged inputs preserve output bytes and mtimes. Reads never recover or
rebuild a generation; only an explicit build does. Original source authority,
observation times, network/fabric boundaries, and raw lineage survive composition.
Unambiguous mDNS advertisements can enrich a device's `mdnsRecords`; ambiguous
services remain separate, and enrichment does not grant health authority.

All five Unified products are selectable source primaries. Multi-source defaults
to Unified; other source defaults are unchanged. Superseded composite recipes
remain explicitly resolvable even where hidden from menus. Menu visibility,
canonical lookup, and health eligibility are separate catalog contracts.

CLI, REST, HA Matter, and Multi-source Unified have dedicated health profiles;
mDNS remains enrichment-only and health-ineligible. Health processing verifies
original cached evidence without collecting or rebuilding Unified data.
Assessments, roster state, comparisons, and retained reproduction context live
in SQLite; optional latest JSON reports are non-authoritative.
`health prepare-history` prepares bounded, resumable retained observation and
comparison evidence without collection. Prepared payloads are derivative,
validated against immutable native inputs, and never replace those inputs.
See [Thread Network Health](thread_network_health.md) and the
[Unified command reference](help_td_cli.md#unify-dataset).

## Browser Modules

Files under `src/js/` are browser-only JavaScript. All are ES modules except
[tdash-theme.js](../src/js/tdash-theme.js), a blocking classic bootstrap loaded
before styles to apply System/Light/Dark appearance without a first-paint flash.
`tdash-health.js` fetches and renders stored Python verdicts for health-eligible
datasets. It does not contain health thresholds or reclassify evidence.

| File | Responsibility |
|---|---|
| `tdash-ui.js` | DOM event wiring, source/dataset controls, view dispatch, settings/appearance, Operations logs/jobs, device details/labels, and insights |
| [tdash-theme.js](../src/js/tdash-theme.js) | Guarded local preference storage, System resolution, root theme attributes, cross-tab updates, and frozen global theme controller |
| `tdash-activity.js` | Bounded browser activity log, metadata sanitization, and tracked HTTP requests |
| `tdash-dataset-registry.js` | Catalog-backed source groups and selectable dataset definitions |
| `tdash-catalog-fallback.js` | Generated bundled fallback catalog used when `/api/catalog` is unavailable or invalid |
| `tdash-capabilities.js` | Source and file capability loading and availability checks |
| `tdash-dataset.js` | Fetch sessions, cache controls, jobs, cancellation, checkpoints, row assembly, and required Unified materialization-state validation |
| `tdash-device-fields.js` | Browser field definitions, aliases, identities, the shared REED resolver, and placeholders |
| `tdash-merge.js` | Browser merge strategies, source precedence, conflicts, and provenance |
| `tdash-utils.js` | Canonical identifiers, field normalization, payload normalization, and formatting |
| `tdash-adaptors.js` | Dispatch from dataset recipes to source adaptors |
| `tdash-adaptor-*.js`, `tdash-adaptor-shared.js` | Source-specific record conversion and shared adaptor helpers |
| `tdash-adaptor-model.js` | Canonical device/relationship/detail model and validated emission |
| `tdash-adaptor-unified.js` | Committed Unified row/model projection, scoped relationship resolution, and typed native links without raw-file dispatch |
| `tdash-source-authority.js` | Browser projection of catalog source authority for merge ordering |
| `tdash-device-diagnostics.js` | Eligible device targets and supported transient diagnostic actions |
| `tdash-health.js` | Health API requests and rendering of server-owned assessments, roster, and comparisons |
| `tdash-thread-network.js` | Thread Network facts, device/link counts, role holders, observation-scoped partition summaries, and source evidence derived from the active dataset |
| `tdash-device-projection.js`, `tdash-topology-view-model.js` | Derived per-device capabilities and diagnostic evidence; indexed topology state and pure filter/search visibility calculations |
| `tdash-topology-utils.js` | Node/edge helpers, indexes, styles, labels, and isolated-node anchors |
| `tdash-topology-renderer.js` | vis-network lifecycle, rendering, interaction, search/health styling, layout selection, and in-place CSS-palette theme projection |
| `tdash-layouts.js` | Deterministic tree, ring/star, compact, hub-spoke, and hybrid seed layouts |
| `tdash-table-renderer.js` | Accessible typed table sorting, column selection, formatting, and row selection |
| `tdash-filters.js` | Capability discovery and node/link/diagnostic predicates |
| `tdash-search.js` | Query parsing and record matching |
| `tdash-view-status.js` | Active-view status ownership and stale-status suppression |
| `tdash-constants.js` | Shared merge, filter, field, palette, details, table, and vis options |

The selectable source and dataset inventory comes from the shared catalog,
validated/projected by `tdash-dataset-registry.js`; documentation does not
duplicate the complete list. The generated fallback retains the same contracts.
Unified uses committed row IDs and scoped native relationships directly rather
than redispatching raw inputs through legacy source adaptors.

Appearance is browser-only: `tdash-ui.js` binds the theme controller to controls,
and the active topology renderer updates existing DataSets without rebuilding
the view or changing camera/physics. Theme metadata does not enter cached rows,
exports, or Python health verdicts. Thread Network summaries likewise derive
from the loaded dataset, without a separate live collection.

## Data and Identity Contracts

The data directory contains final snapshots, transient `.partial.json`
checkpoints, `.outcome.json` evidence, `.network.json` scope companions,
Unified `.report.json` commit markers, and operator-managed inputs.
Python-owned fixed filenames are defined in `td_const.py`; browser filename
literals are tested against the server registry.

Canonical merge identities are:

1. `extAddress`
2. `omrIpv6Address`
3. `rloc16`

Matter mDNS records additionally use fabric/node composite identity to guard or
preserve distinctions according to the selected Matter identity mode. Preferred
output field names are camelCase. Source aliases remain accepted and provenance
is retained in `_source_files`; incompatible non-empty values are recorded in
`_merge_conflicts`.

Network identity is `extpan:<canonical Extended PAN ID>`. Scope companions
retain observed/operator/unknown provenance and snapshot bindings where
required. Unified `_unifiedRecordId` and `_networkInstance` metadata preserve
same-address records across distinct scopes/fabrics; unknown scope is not
silently promoted to a known network.

See [Merge Thread Device Information](merge_thread_device_info.md) and
[Dashboard UI Fields](dashboard_ui_fields.md).

## Server and Cache Contract

`td_webserver.py` serves only filenames present in `FILE_ACTION_MAP`, plus
derived checkpoint filenames for dynamic entries. A `FileAction` contains the
freshness limit, CLI action or `STATIC`, estimated cost, and an optional forced
background flag.

Browser API access is same-origin. API routes do not emit CORS authorization
headers or handle cross-origin preflights. Changing the bind host or placing
Hobat behind a reverse proxy does not create an origin allowlist; the proxy must
serve the dashboard and API from the same browser origin.

- Fresh dynamic files are served from disk.
- Missing or stale dynamic files invoke `td_cli` unless Cache Only is requested.
- Short actions are awaited and return the file.
- Forced-background and long actions return HTTP 202 and a job ID.
- Data responses support ETag and Last-Modified revalidation.
- Static assets use `Cache-Control: no-cache`.
- Health and device-label API responses use `Cache-Control: no-store`.

Unified row actions are always background cache-only builds, not collector
refreshes. Companions are static, generation-validated reads; Unified
checkpoints are not exposed. Cache Only never starts a build. Mixed or invalid
generations return HTTP 409 rather than partial bytes. Data/revalidation
responses carry `X-TD-Materialization-State`; the browser requires a valid
`complete`/`partial` value and preserves the incomplete-data notice across views.

Capabilities distinguish valid committed `cached` state from
`buildableFromCache`, so Unified can remain available while its collector is
offline. Shared off-event-loop inspection is reused only while catalog and
relevant filesystem signatures remain unchanged; it does not replace validation
on data or health reads. Explicit `source-probe` preflights remain live-only.

See [Webpage, Web Server, and Data Flow](codebase_webpage_web_server_data_flow.md).

## Data Directory

Resolution precedence is `--datadir`, `TD_DATA_DIR`, `/data` when present, then
`./data`. User paths are resolved to absolute paths; the local default is
created when selected. See [Data Directory Model](codebase_datadirectory.md).

## Validation

The default suite is offline:

```bash
python3 -m pytest -q
```

Frontend behavior is exercised through Node-backed tests and cache-only browser
acceptance. Live tests require `TD_LIVE_TESTS=1`. Checked-in data is treated as
immutable test input.