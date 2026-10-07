# Webpage, Web Server, and Data Flow

This document covers `td_webserver.py`, `tdash.html`, `tdash.css`, and all
browser modules under `src/js/`.

## End-to-End Architecture

```text
tdash.html + tdash.css
        |
        v
tdash-ui.js -> /api/catalog -> /api/capabilities
        |
        v
tdash-dataset.js -> /api/data/{filename}
                                      |
                                      v
                              td_webserver.py
                               /           \
                    cached snapshot      td_cli subprocess
                         |                     |
                         +------ data/ <-------+
                                |
                                v
buildDatasetRows -> buildDeviceProjections -> runAdaptor
                              |                    |
                              v                    v
                   table + diagnostic filters   topology view model
```

The browser never calls OTBR directly. Live work is owned by Python collectors
started through `td_cli`; the browser consumes files from the configured data
directory through the server allowlist. Source-availability discovery is a
separate bounded probe path in the Python web server, not a collector refresh.
See the [data-flow ownership table](merge_thread_device_info.md#ownership) for
the field, identity, authority, and projection owners in both runtimes.

The dashboard also uses API paths and views outside snapshot assembly. Health
processing consumes approved cached files and writes assessments to
`hobat_v1.db`; health GET routes read stored projections from that database.
Device diagnostics run as transient actions and do not update snapshots or
health history. Device labels use their own static-map API. The Thread Network
workspace summarizes network facts and device/link evidence from the loaded
dataset and capabilities; it does not trigger a separate live collection.

## Server Routes

| Method and route | Handler | Behavior |
|---|---|---|
| `GET /` | `handle_root` | Redirect to `/tdash.html` |
| `GET /api/catalog` | `handle_catalog_api` | Return the validated dataset catalog without caching |
| `GET /api/capabilities` | `handle_capabilities_api` | Report cached files and source availability |
| `GET /api/data/{filename}` | `handle_data_api` | Serve, refresh, or start a job for an allowed data file |
| `GET /api/job/{job_id}` | `handle_job_api` | Return job state and final/checkpoint metadata |
| `DELETE /api/job/{job_id}` | `handle_job_cancel_api` | Request cancellation of a running job |
| `GET /api/jobs` | `handle_jobs_api` | Return a no-store projection of all active generic, health, and device-action jobs |
| `DELETE /api/jobs` | `handle_jobs_cancel_api` | Request deterministic, idempotent cancellation of all active jobs |
| `GET /api/health/summary` | `handle_health_summary_api` | Read a pinned or latest grouped assessment |
| `GET /api/health/findings` | `handle_health_findings_api` | Read filtered or paginated findings for an assessment |
| `GET /api/health/devices/{device_id}` | `handle_health_device_api` | Read one device's findings and approved health evidence |
| `GET /api/health/observations` | `handle_health_observations_api` | Read bounded observation history |
| `GET /api/health/comparison-endpoints` | `handle_health_comparison_endpoints_api` | Page retained Before/After candidates and resolve defaults/shortcuts |
| `GET /api/health/comparison` | `handle_health_comparison_pair_api` | Read or derive one arbitrary endpoint pair without writing |
| `GET /api/health/comparisons` | `handle_health_comparisons_api` | List stored assessment comparisons |
| `GET /api/health/comparisons/{comparison_id}` | `handle_health_comparison_api` | Read a pinned comparison; apply effective Result/scope filters and counts before paging |
| `GET /api/health/roster` | `handle_health_roster_api` | Read a paginated network device roster projection |
| `GET /api/health/roster/{device_id}` | `handle_health_roster_device_api` | Read one device's approved roster fields |
| `PATCH /api/health/roster/{device_id}` | `handle_health_roster_device_patch_api` | Apply one revision-guarded, idempotent network-scoped lifecycle action and reassess retained evidence |
| `GET /api/health/latest` | `handle_health_latest_api` | Read the latest eligible assessment |
| `GET /api/health/capabilities` | `handle_health_capabilities_api` | Report health-store read capabilities |
| `POST /api/health/process-dataset` | `handle_health_process_dataset_api` | Process one approved cached dataset into a health assessment |
| `GET /api/device-actions` | `handle_device_actions_capabilities_api` | Return the effective global device-action policy and enabled action names |
| `POST /api/device-actions` | `handle_device_actions_api` | Validate and start one allowed transient device diagnostic action |
| `GET /api/device-action-jobs/{job_id}` | `handle_device_action_job_api` | Return one transient device-action job state/result |
| `DELETE /api/device-action-jobs/{job_id}` | `handle_device_action_job_cancel_api` | Request cancellation of one transient device-action job |
| `GET /api/device/{extAddress}` | `handle_device_get_api` | Read one static device label |
| `PATCH /api/device/{extAddress}` | `handle_device_patch_api` | Atomically insert or update one device label |
| `GET /**` | aiohttp static route | Serve `src/` assets |

All browser API requests are same-origin. The server does not emit
`Access-Control-Allow-*` headers and does not authorize CORS preflights. Health
requests use document-relative URLs so a reverse proxy can mount the dashboard
and API beneath one path prefix. The proxy must route that prefix to Hobat and
preserve the dashboard/API origin.

This removes cross-origin browser authorization; it is not authentication or a
network-access boundary. Direct HTTP clients such as `curl` and `wget` can still
call reachable API routes, including mutation routes. Use firewall or
authenticated reverse-proxy controls when access must be restricted.

`GET /api/capabilities` inspects cached files and source availability. When no
file is cached for OTBR CLI, OTBR REST, or Home Assistant Matter, the server
performs a bounded reachability probe through its Python source clients; these
probes are coalesced and cached for 60 seconds. They do not collect snapshots or
invoke `td_cli`. `GET /api/device-actions` is separate and reports the effective
policy for active Ping and Reset Counters operations.

### Health and Device-Action Flows

```text
Dashboard -> POST /api/health/process-dataset -> web server
                 -> td_cli health process-dataset -> hobat_v1.db
Operator maintenance -> td_cli health migrate-history -> verified backup + schema-8 revisions
Dashboard -> GET /api/health/* -> web server -> query-only hobat_v1.db read
Dashboard -> PATCH /api/health/roster/{device_id} -> validate revision/receipt
                 -> atomic roster + lifecycle audit + receipt + reassessment transaction
Dashboard -> POST /api/device-actions -> validate -> source action
                                                           -> transient job/result (memory)
```

Health processing is cache-only: the server starts a background `td_cli` job
with `--allow-partial`, which writes health history to `hobat_v1.db` without
starting a collector, changing a snapshot, or probing a device. Health GET
routes are query-only and return no-store responses. Device-action results and
jobs are transient; they are not persisted in snapshots, checkpoints, labels,
or health data. Roster PATCH is the exception to query-only health reads: it
requires a preexisting supported health schema, checks network/device identity,
the request receipt and expected device revision in one write transaction,
applies only an allowed transition, stores the lifecycle event and replay
receipt, and reassesses from retained evidence before committing. It never
starts a collector or changes source snapshots, static labels, or observed
facts. Same-request retries replay the committed response; stale revisions
require a fresh detail read and confirmation. Historical assessments and
comparisons remain immutable, while the selected current assessment may gain a
new roster-aware revision. On eligible complete observations, the shared
processing path stores the adjacent comparison and unique complete-only
1/3/7/30-day interval pairs in the same SQLite transaction, subject to the
existing 2,000-pair cap.

The endpoint inventory GET pages retained assessment metadata and resolves
defaults and interval candidates over the full history. The arbitrary pair GET
uses an exact stored pair or derives one from retained evidence in a query-only
transaction; neither GET invokes health processing. Comparison reads accept
optional Result and scope filters and return the matching-row count alongside
the unfiltered comparison count. The health read service and SQLite store apply
both filters before `LIMIT`/`OFFSET` in one read transaction, including the
effective Unknown classification for non-comparable or baseline-pruned items.
The dashboard explicitly requests its Changed default; callers that omit the
filters retain the unfiltered API behavior. See
[Thread Network Health](thread_network_health.md#read-api-and-dashboard) for
route parameters, latest-After preset selection, Custom endpoint selection,
filter/count semantics, and lifecycle. Findings, Comparison, and Device Roster
are browser-owned peer tabs; the selected tab, preset intent, disclosure
state, visible row ranges, and direct 25-row pagination remain in the browser.
Reset comparison only resets Comparison state. These navigation choices do not
change the query-only server contract or comparison policy.

## Device Diagnostics

Device diagnostics are enabled by default. `GET /api/device-actions` reports
the effective policy: all Ping actions and OTBR Reset Counters are available
unless the server starts with `--disable-device-actions` or
`--disable-device-reset`, or the corresponding `TD_DEVICE_*_ENABLED`
environment override is false. The parent disable removes Reset Counters as
well. Each POST revalidates the cached record, selected target, source, and
action capability before dispatch; action results and jobs remain transient and
are never written to snapshots, checkpoints, labels, or health data.

Same-origin routing does not authenticate these mutation routes. Default-on
operation requires a trusted network or authenticated reverse proxy/firewall
before deployment outside a trusted environment.

### Data Request Flow

```text
GET /api/data/{filename}
        |
        v
validate safe filename and FILE_ACTION_MAP/checkpoint membership
        |
        +-- checkpoint or STATIC --> serve existing file or 404
        |
        v
evaluate request cache controls and file freshness
        |
        +-- Cache Only and missing/stale --> explicit cache-only failure
        +-- fresh -----------------------> 200 or conditional 304
        |
        v
short action? -- yes --> await source lock + td_cli --> 200/304 or 502
        |
        no
        v
deduplicate by filename -> create background job -> 202 + Location
```

`FILE_ACTION_MAP` is the authoritative filename-to-action registry. Each
`FileAction` specifies `max_age_s`, an action argument list or `STATIC`, an
estimated cost, and `force_async`. Checkpoint filenames are derived from dynamic
entries with the `.partial.json` suffix and are served as non-regenerating,
zero-max-age files.

A catalog recipe can reuse an already registered filename by changing only the
[manifest](../src/td-dataset-manifest.json). A new snapshot filename also needs
an entry in `td_webserver.py` `FILE_ACTION_MAP` (static or with a collector
action) and a producer or operator-supplied file. Listing it in the catalog
alone does not make `/api/data/{filename}` serve it: unknown filenames return
404.

Data responses include `Cache-Control`, `Last-Modified`, and an ETag based on
mtime and size. `If-None-Match` takes precedence over `If-Modified-Since` and
can produce HTTP 304. Static HTML/CSS/JS uses `Cache-Control: no-cache` so the
browser revalidates it.

### Source Serialization and Deduplication

The server deduplicates simultaneous refreshes of the same filename and uses an
`asyncio.Lock` per source command family. Two OTBR CLI actions therefore do not
run concurrently in one server process, while unrelated source families can
progress independently. Devices, diagnostics, mesh diagnostics, canonical and
native topology, and native Thread inventory refreshes from `ha-matter-ws`
share one source lock so concurrent dashboard requests do not load the Matter
controller in parallel. Native dashboard actions never add diagnostics
`--force` or topology `--refresh`.

## Background Jobs and Cancellation

Jobs use five states:

- `running`
- `cancelling`
- `cancelled`
- `done`
- `error`

Only `running` jobs are cancellable. `cancelled`, `done`, and `error` are
terminal. A successful DELETE transitions a running job to `cancelling`,
cancels its task, terminates the tracked subprocess, and uses a force-kill
fallback if graceful termination does not finish in time. Unknown jobs return
404; terminal or otherwise non-cancellable jobs return 409.

Completed job records are retained temporarily so clients can poll the result.
The cleanup loop removes terminal jobs after 15 minutes and shutdown cancels
cleanup and remaining background tasks.

The unified `/api/jobs` resource projects only `running` and `cancelling`
records from the generic and device-action registries. Stable kind and source
metadata lives on status records rather than transient runtime handles. The
projection excludes command arguments, action request payloads, subprocess
output, and credentials. Bulk cancellation snapshots jobs in creation-time and
job-ID order and delegates to the same request-independent helpers used by the
individual DELETE routes. A missing runtime handle transitions a running job to
`cancelled` instead of leaving it indefinitely in `cancelling`.

Listing and bulk cancellation are server-wide administrative operations. The
same-origin browser model is not authentication; deployments outside a trusted
network require an authenticated reverse proxy or equivalent access control.

## Progressive Checkpoints

Long collectors can atomically replace a sibling `.partial.json` file while
the final snapshot is still being built. Job polling returns checkpoint
metadata when a checkpoint exists.

`tdash-dataset.js` tracks the active fetch session and each job ID. When a newer
checkpoint is reported it:

1. fetches the checkpoint through `/api/data/`;
2. rejects stale or out-of-order checkpoint versions;
3. replaces that file's in-progress payload;
4. rebuilds rows through the same pure dataset assembly path used for finals;
5. marks the dataset partial and publishes a throttled redraw.

After all files settle, the browser rebuilds from final payloads and clears the
partial state. Cancellation applies to all active jobs in the current fetch
session. If usable partial data exists, the browser keeps it and reports that
the result is partial.

## Device Labels

`GET /api/device/{extAddress}` reads the authoritative
`td-static-extaddr-device-label.json` record. Missing maps or addresses return
404.

`PATCH /api/device/{extAddress}` accepts exactly:

```json
{"deviceLabel": "Office Sensor"}
```

The server validates the 16-hex-digit address and label, acquires the
`merge-extaddr` source lock, invokes the CLI upsert, and reads the persisted
record back before responding. Updating returns 200; inserting returns 201.
Invalid input returns 400, CLI failure or timeout returns 502, and invalid or
unreadable persisted state returns 500. Device API responses use
`Cache-Control: no-store`.

Atomic replacement prevents partial JSON. The in-process lock does not
coordinate a separate writer process, so cross-process writes are
last-write-wins.

## Browser Application Layers

| Layer | Owners | Responsibility |
|---|---|---|
| Controls | `tdash.html`, `tdash-ui.js` | Source/dataset selection, Sync/Cancel, topology/table and Thread Network views, filters, settings, insights, device actions, activity logs, and pending jobs |
| Browser activity | `tdash-activity.js` | Bounded in-memory activity, route/metadata sanitization, subscriptions, and tracked HTTP requests |
| Source and catalog capabilities | `tdash-capabilities.js`, `tdash-catalog-fallback.js` | Source/file availability and bundled fallback for catalog loading |
| Fetch and assembly | `tdash-dataset.js`, `tdash-dataset-registry.js` | Catalog lookup, cache policy, jobs, checkpoints, extractors, and final/partial datasets |
| Field and merge contract | `tdash-device-fields.js`, `tdash-source-authority.js`, `tdash-merge.js`, `tdash-utils.js` | Preferred fields, aliases, identities, normalization, precedence, conflicts, and provenance |
| Home Assistant Matter roles | `tdash-ha-matter-ws-roles.js` | Validates supported file/extractor contexts and normalizes role evidence without treating unrelated records as Matter role data |
| Adaptation | `tdash-adaptors.js`, `tdash-adaptor-*.js`, `tdash-adaptor-model.js` | Source-specific records to canonical devices, relationships, and details |
| View model | `tdash-device-projection.js`, `tdash-topology-view-model.js`, `tdash-filters.js`, `tdash-search.js` | Derived device state, indexed visibility, diagnostic matching, and search state |
| Thread Network view model | `tdash-thread-network.js`, `tdash-ui.js` | Network facts with source attribution, network-instance context, and available device/link/role summaries for the Thread Network workspace |
| Presentation | `tdash-layouts.js`, `tdash-topology-utils.js`, `tdash-topology-renderer.js`, `tdash-table-renderer.js` | Seed layouts, vis-network lifecycle, topology interaction, and sortable tables |
| Device diagnostics | `tdash-device-diagnostics.js` | Device-action eligibility, target selection, and result presentation inputs |
| Health | `tdash-health.js` | Assessment, findings, roster, comparison, and health-job API/rendering workflows |
| Status | `tdash-view-status.js` | Active-view status ownership and suppression of stale publishers |
| Styling | `tdash.css`, `tdash-constants.js` | Responsive layout, controls, palettes, node/edge styles, and vis options |

## Browser Activity and Jobs

All browser HTTP calls pass through `trackedFetch()`. Ordinary calls record a
start and one terminal event; polling calls are silent and their owning
workflow records only job-state transitions. Dynamic URL components are
replaced with route templates, query values are retained only for an explicit
allowlist, metadata is recursively bounded, and failures use HTTP, network, or
abort classifications rather than arbitrary exception text.

The activity ring stores at most 200 entries in browser memory and is cleared
only by the operator or page lifecycle. The Jobs tab polls `/api/jobs` every
two seconds only while visible. An abort controller and monotonic request
version prevent hidden or stale responses from replacing the current table.
Neither activity entries nor transient server job records are written to
`data/`.

## Dataset Assembly

At startup, `tdash-ui.js` fetches `/api/catalog` first, then
`/api/capabilities`, before populating source and dataset controls. If the
catalog request fails or validation rejects it, `tdash-dataset-registry.js`
uses the bundled `tdash-catalog-fallback.js`; a capabilities failure leaves
the catalog available but without source availability hints. The single
[manifest](../src/td-dataset-manifest.json) defines ordered files, merge
strategy, row extractor, adaptor, defaults, and `mergeGroups`; update it to
add a dataset. `DATASOURCE_REGISTRY` and `DATASET_REGISTRY` are runtime views
of the selected catalog, not independent declarations.

After editing the manifest, run `python3 script/build_dataset_catalog.py` to
regenerate the bundled fallback and restart the server. The manifest is the
single recipe source of truth, but the generated fallback must be refreshed
with it; recipes that introduce new snapshot filenames also need the server
registration and producer described under [Data Request Flow](#data-request-flow).

Browser assembly does not enforce network-instance separation: it can combine
files from different instances. `tdash-view-status.js` compares known instance
IDs from `/api/capabilities` for loaded files and displays `Network instance:
mixed` when they disagree; unknown scopes do not block rendering. The offline
merge has a separate exclusion rule described in the
[Network Instance section](merge_thread_device_info.md#network-instance).

Health datasets declare `healthEligible` and `healthProfile`. A cross-language
contract test keeps active browser entries marked `healthEligible: true` aligned
with `td-dataset-manifest.json`, including their source, files, merge strategy,
extractor, adaptor, and profile. For eligible datasets, `tdash-health.js` reads a
pinned assessment from `/api/health/*` and can start a same-origin
`POST /api/health/process-dataset` task. The server always passes
`--allow-partial`; this task consumes only the current cached files and writes
health history in `hobat_v1.db`, without starting a collector, modifying a
snapshot, or probing devices. The browser renders status, five-pillar coverage,
grouped findings, bounded history metadata, and device-attributed findings.
Python remains the only verdict owner. The finding view defaults to All for
each dataset and is held only in browser memory; reloads, dataset changes, and
Reset restore All.

Home Assistant Matter role normalization is restricted to catalog entries and
file/extractor combinations recognized by `tdash-ha-matter-ws-roles.js`.
`tdash-dataset.js` applies the allowed context while normalizing payloads;
adaptors use the same policy when interpreting topology roles. This keeps
commissioned-device, diagnostic, native-topology, and border-router-inventory
role evidence tied to its declared source shape.

On Sync, `tdash-dataset.js` `loadDataset()` starts per-file requests concurrently and uses
`Promise.allSettled` so successful files can still produce a partial result when
another file fails or is cancelled. `buildDatasetRows()` is the pure assembly
boundary: it applies the selected row extractor, merge strategy, and canonical
output normalization while preserving source indexes. It then calls
`buildDeviceProjections()` in `tdash-device-projection.js` once per assembled
dataset. `tdash-adaptors.js` `runAdaptor()` dispatches the selected recipe to
the source adaptor, which emits through `tdash-adaptor-model.js`.

The three browser merge strategies are:

- `none`: normalize/pass through records without cross-record merging.
- `by-rloc16`: merge records sharing canonical RLOC16.
- `by-identity`: merge through canonical extended address, OMR address, or
  RLOC16 with Matter composite-identity consistency guards.

First non-empty values win after source-priority ordering. Conflicting
non-empty values are retained in `_merge_conflicts` and contributing files in
`_source_files`.

## Thread Network Workspace

The Thread Network tab is a browser-only projection of the currently loaded
dataset. `tdash-thread-network.js` gathers network facts from loaded and
auxiliary payloads, associates each fact with its source files, and uses
`/api/capabilities` metadata to report network-instance context. Conflicting
equally preferred payload facts are shown as Mixed rather than silently
selecting one. For Ext PAN ID, a known capabilities instance ID takes
precedence over payload facts; payload evidence is used when no instance ID is
available, and a mixed instance is reported as Mixed. It derives device role
and link-quality summaries from assembled rows and the adaptor relationship
model when available, using cached status counts when provided. Leader and
primary-BBR entries retain their source-file evidence and can link back to a
selectable device when an identity is available. Missing or ambiguous evidence
is shown as unavailable rather than initiating a live refresh.

## Topology Pipeline

```text
assembled dataset
      |
      v
source adaptor -> adaptor model -> emitted node/edge/detail maps
      |
      v
topology view model + device projections -> filter/search visibility
      |
      v
layout seed -> vis.DataSet -> vis.Network -> status + details events
```

The adaptor model centralizes canonical device registration, relationship
categories, details ownership, and result validation. The topology view model
indexes nodes and relationships and computes visibility without directly
mutating vis-network objects. The renderer applies the result, manages network
lifecycle, restores search styling, and publishes device selections.

Layout selection supports automatic and manual profiles. Extracted layout
helpers provide deterministic mesh tree, ring/star, compact, hub-spoke, and
hybrid seed positions; vis-network physics can then refine the result according
to the active profile.

## Tables, Search, Filters, and Details

The table renderer displays canonical row fields and orders preferred fields
before additional fields. `tdash-device-projection.js` computes device
capabilities once from assembled rows; `tdash-filters.js` derives dataset
capabilities from those projections and decides which diagnostic options to
offer, also checking for matching records in the active view. The table
renderer does not decide availability by scanning raw column names. More Info
expands the displayed/searchable surface. Row and topology-node selection publish the same
`tdash:device-selected` event, keeping details, settings, and diagnostic
insights synchronized.

Filter options are capability-driven. `tdash-filters.js` uses the dataset's
device projections to offer supported node and diagnostic options; the topology
view model also uses projections for node and link visibility. Link filtering
applies only to topology. Diagnostic relationship
matches can expand both endpoints and force the matching relationship visible.

Normal search targets the maintained identity, role, version, network, and
status field list. Advanced search also traverses the broader record surface.
Search highlighting preserves original node styling and restores it when the
query is cleared.

## Responsive Layout

`tdash.css` owns the application grid, wrapped control bars, scroll containment,
details panels, loading/error states, and mobile breakpoints. Topology canvases
and tables are constrained by their workspace containers. Wide tables scroll
inside `.table-wrap`; document-level horizontal overflow is not expected.

## Validation

Browser acceptance uses port 9178 and `--datadir ./data`. Enable Cache Only
before the first Sync, enumerate offered options from the rendered DOM, and
instrument console errors, page errors, failed requests, and HTTP failures.
Validate topology status and nonblank canvas pixels, validate table rows and
scroll containment, and hash `data/` before and after to prove fixtures were not
modified.