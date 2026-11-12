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
                      raw finals / Unified generations
                      hobat_v1.db health assessments
                                  |
                                  v
                            JSON response
                                  |
                                  v
buildDatasetRows -> buildDeviceProjections -> runAdaptor
                              |                    |
                              v                    v
                   table + diagnostic filters   topology view model
```

The browser never calls OTBR directly. Live work is owned by Python collectors
started through `td_cli`; the browser consumes files from the configured data
directory through the server allowlist. Not every CLI action collects live
data: Unified materialization and health processing consume cached evidence.
Eve and Thread Tools also support operator-managed exports, with Thread Tools
conversion owned by its browser adaptor. Source-availability discovery is a
separate bounded probe path in the Python web server, not a collector refresh.
See the [data-flow ownership table](merge_thread_device_info.md#ownership) for
the field, identity, authority, and projection owners in both runtimes.

The catalog owns direct non-health dataset aliases and validates source/dataset
pairs. Only canonical IDs appear in menus; `multi-source` replaces the synthetic
`merged` source without renaming cache files or commands. Health IDs use an
intentional cutover, not aliases; see the
[operator cutover notes](thread_network_health.md#dataset-identifier-cutover-2026-10-27).
Canonical recipe lookup remains separate from the optional `selectable` menu
flag, and source defaults must reference visible recipes in the same source.

### Unified processing

The catalog declares selectable CLI/REST/HA Matter/mDNS and
Multi-source Unified primaries. Multi-source defaults to Unified; other source
defaults are unchanged. All five products are available in normal selectors;
menu visibility does not imply live-source availability or health eligibility.
[td_unified_dataset.py](../src/td_unified_dataset.py) reads only those declared
cached finals and their scope companions. Source records reuse the merge
engine's in-memory path; BBR envelope conversion stays in its CLI owner.
No collector, checkpoint, action-list, or network refresh is implicit.
`unify-dataset --dataset all` builds the four source primaries before
Multi-source. JSON output is an array of the five per-dataset summaries; a
single-dataset command returns one object. Failure stops the command with a
nonzero exit status without rolling back earlier committed products.
Missing required evidence needs explicit `--allow-partial`; invalid present
inputs or stale scope bindings fail rather than repairing raw caches.
HA cached inventory/native converters are implemented in the source-owned
[ha_matter_ws_unified.py](../src/ha_matter_ws_unified.py). HA primary assembly
includes its four required inputs, optional projections, original outcome
checks and conservative observed identity/coverage. Four-primary composition
prepares/reuses the catalog dependencies once inside the same directory lock,
verifies their committed reports/current raw evidence and retains per-source
completion, missing/excluded reasons and original times. Only admitted original
observations are replayed through the owning normalizers and merge policies;
no aggregate file rank is used. Network/fabric boundaries and uncorrelated
services remain separate, and native links rebind to final row IDs.
Operational Matter and HAP UDP (`_hap._udp.local.`) services with one unambiguous
Thread-device OMR match instead remain complete records in the device's
`mdnsRecords` array. If the optional promoted OMR field is absent, usable IPv6
addresses in `serviceInfo.addressesParsed` and `serviceInfo.ipv6Addresses` can
establish that match against device OMR evidence. Multiple matching devices
remain ambiguous; an explicit service OMR takes precedence. The builder does
not add an inferred OMR or network scope to the original service. They retain their
own service IDs, original scope, times, properties and per-field source lineage;
no device field or fabric identity is overwritten. MeshCoP
(`_meshcop._udp.local.`) records use the same embedding path when exactly one
Thread device matches their concrete extended address within the observed
network scope; no OMR address is required. Other service types, unmatched,
scope-conflicting and ambiguous services remain top-level rows. Standalone mDNS
Unified groups advertisements with the same normalized usable OMR address and
identical observed scope into one service-summary row, retaining all complete
advertisements in `mdnsRecords`. It does not choose one fabric's identity for
the summary or merge conflicting extended addresses. Unknown and known scopes
remain separate; Multi-source continues to replay original advertisements
independently. The shared device-details mDNS section renders the array.
The in-memory device merge derives `relationshipOnly` from accepted original
contributors: a genuine device observation clears the flag, while placeholders
and mDNS-only enrichment cannot. The current builder contract is
`unified-assembly-v14`; an explicit build upgrades older generations even when
their raw inputs are unchanged. Coherent assembly-v2 through assembly-v13
generations remain readable under their retained contracts without rebuilding.
CLI/REST/HA Matter/Multi-source health profiles now consume verified original
evidence with dedicated retained contracts; mDNS is enrichment-only and remains
health-ineligible. Qualification never processes health on selection.
CLI and REST topology, the HA seven-file composite, and the Multi-source dynamic
merge are menu-hidden but explicitly resolvable; legacy precomputed Multi-source
remains visible. The CLI and REST OTBR + mDNS alternatives stay in their
original source groups.

The HA converters preserve commissioned membership, full safe
device/endpoint/power/operational fields and explicit roles. Assembly-v14
applies a separate source-owned admission step requiring positive Thread
diagnostic, Thread interface, native Thread topology or Border Router evidence,
including validated diagnostic topology relationships. Hybrids remain; unknown
and conflicting observations are excluded without claiming they are non-Thread.
Missing evidence can hide a real Thread device. Original raw caches remain untouched, and original-evidence
replay uses the same admission policy for current generations. Older generations
keep their original reads and retained health semantics. Native IDs stay in
`nativeNodeIds`, never Matter fabric/node IDs. Safe native details and original
graph collection time remain under `diagnosticsDetail.nativeBorderRouter` or
`diagnosticsDetail.nativeTopology`. Only validated IPv6 addresses are promoted
from the mixed-address Border Router inventory.

`nativeRelationships` are supplementary typed links with stable `sourceId`,
`targetId`, `networkType`, original `nativeSourceId`/`nativeTargetId`, qualitative
`strength`, observations, and only present directional `sourceToTarget`/
`targetToSource` metrics and route metadata. They are not copied into OTBR
neighbor/child/Route64 tables. Exact duplicate native observations are removed.
Wi-Fi/Ethernet links and confirmed non-Thread nodes are filtered from new
Unified products with separate `coverage.haTransportFiltering` reasons, never
manufactured replacement endpoints. Valid admitted Thread links remain intact.
Dangling endpoints stay explicit in `unresolvedEndpoints` and merge conflicts;
when neither endpoint exists, a relationship-only row retains the evidence
without inventing a device. Native identity collisions retain separate
source-local IDs with conflicts instead of arbitrarily connecting endpoints.
After identity-aware assembly, links bind to committed `_unifiedRecordId`
values via native IDs, not possibly colliding addresses. Different commissioned
Matter fabrics remain separate. A missing inventory stays partial even with a
dashboard projection. Native upstream time and outcome capture/count/scope
association are checked independently; mtime-only evidence is explicitly
degraded, not proof of one complete observation.
New commissioned-node collections capture one typed `controller-snapshot`
observation after bounded event reconciliation, before normalization. Records,
dashboard and checkpoints retain that time; `all` publishes exact-byte
`artifactObservations` bindings in its outcome after its finals. Assembly-v11
resolves these original HA times without file-mtime dependence and retains
their kind through Multi-source raw lineage. Native graph/discovery time is
never refreshed from the wrapper or controller receipt. Legacy caches are not
backfilled, and empty leaf arrays without a matching binding remain explicit.
Controller receipt is not a measurement interval or mesh absence authority;
health keeps these semantics in retained reproduction context.
Live native collection keeps strict endpoint validation. These are processing
contracts; selecting a Unified product does not initiate native collection.

The `unified` browser adaptor registers the committed canonical rows directly
through the shared adaptor model and relationship emitter. Committed record IDs
keep same-address devices from different scopes/fabrics distinct in topology,
table selection, details and device projections. Native transport links keep
their categories, directions and measured metrics; qualitative strength alone
does not become measured LQI. Unresolved native endpoints remain in details,
not invented nodes. Retained focused source adaptors keep their existing paths.

Generation IDs bind ordered original content/scope digests, original times,
recipe/authority digests and selected observed network, excluding build time.
Rows carry internal `_unifiedRecordId` and `_networkInstance` metadata so report
lineage does not depend on array ordering. Unknown-scope records are not relabelled
as known networks, including embedded service evidence. Same-file identity collisions remain visible, while mDNS
uses service/event deduplication rather than fabricated Thread device identity.

One per-directory `flock` covers building and recovery. Named artifacts stage
in the data directory, with durable recovery copies and the report replaced
last as the commit marker. Reads validate the report, generation fingerprint,
and artifact bindings; mixed generations produce explicit HTTP 409 errors.
Only an explicit build performs recovery or rebuilds invalid output. Display
reads may inspect a coherent generation after raw caches change; evidence
consumers additionally verify current original digests/times. A build with
unchanged evidence and the current builder contract is a byte/mtime-preserving
no-op rather than a new observation.
For Multi-source, `read_generation(..., verify_inputs=True)` verifies dependency
report/artifact bindings and the catalog-allowlisted transitive `rawInputs`
closure. The report's generation-bound `rawInputsDigest` includes original
roles, content/scope digests, times and selected/missing/excluded states without
copying raw snapshots. `read_original_evidence` rechecks the committed report and stable original
reads, applies source-owned normalizers and selected-network/Thread-kind filters,
then verifies the closure again. This is the health sample boundary; aggregate
rows never supply authority or observation time. See
[Unified health qualification](thread_network_health.md#unified-health-qualification)
for retained recipe, absence witness and replay guarantees.

Unified HTTP row actions run `unify-dataset --allow-partial --json`, asynchronously
with a 60-second subprocess budget. Companions are static, validated reads;
Unified checkpoint filenames are not exposed. Successful jobs carry coverage
and materialization state, and data/revalidation responses carry
`X-TD-Materialization-State`. Cache Only never starts a build. Capabilities report
valid committed `cached` state, `buildableFromCache`, and local validation
reasons, without collecting data. Unified browser availability uses only valid
cached/buildable state, including when a collector is offline. Capabilities
requests share one off-event-loop inspection per data directory. Each product
is inspected once per scan, including Multi-source dependencies. Unchanged
results are reused only while catalog contracts and filesystem signatures
(device/inode, mode, size, nanosecond mtime/ctime) of advertised files, Unified
artifacts, original inputs and scope companions remain unchanged. Changes
trigger full digest/lineage/snapshot validation, not a TTL-based assumption;
unstable scans and inspection errors are not cached as successful results.
This cache does not replace generation validation on data or health reads.
Unified loads
never fetch the legacy raw identity auxiliaries. The response materialization
header is mandatory for a Unified row response, including the final response
after a processing job: `partial` stays a persistent incomplete-data notice
across view changes; missing/invalid state cannot replace the last good view.

### REST Collection Evidence and Cached Qualification

The REST collectors own live requests, provisional checkpoints, final snapshots,
and outcome companions; Unified and health processing only read that evidence.
Standalone `diagnostics fetch-all` enables one-level child RLOC expansion by
default. `--no-children-expand-by-rloc` disables it and is required for alternate
destination types. Expansion uses this run's parent identity and child tables,
validates returned identities, and retains separate `childrenExpansion` counters.
Shared client calls, topology, mesh diagnostics, and single-device commands do
not acquire that default. An unresolved-IID or incomplete-expansion run with no
diagnostic items retains the previous final snapshot.

Both standalone REST diagnostic and mesh-diagnostic batches retain full outcome
companions even with `--items-only`; the flag changes the returned payload, not
the recorded attempt evidence. The server's existing diagnostic action uses
`--items-only --no-basic-fallback` and inherits the standalone child-expansion
default. Its router-only mesh action uses
`--items-only --preserve-diagnostics`; it does not enable
`--diagnostic-response-fallback`.

That optional mesh flag allows one bounded extended-address Network Diagnostics
check per eligible failed router. It does not ping or manufacture mesh-table
entries. Fresh matching action/result identities, stable observed network scope,
and qualified child-table witnesses are required before failed tables can be
classified as `not-provided` coverage.
[td_restapi_mesh_evidence.py](../src/td_restapi_mesh_evidence.py) owns those pure
checks; [td_restapi_diagnostic_recovery.py](../src/td_restapi_diagnostic_recovery.py)
reconciles same-run router/child recovery and field availability from original
snapshot/scope bindings. Unified and health reuse these source-owned rules,
not cached claims of recovery or aggregate row timestamps.

[otbr_restapi_outcomes.py](../src/otbr_restapi_outcomes.py) projects reconciled
facts into the immutable vocabulary in
[td_collection_outcomes.py](../src/td_collection_outcomes.py). Initial/effective
status, explicit ordered attempts, responsiveness, recovery, and table coverage
remain independent. Structured logs report these facts without inferring
attempts or turning a response into successful table collection. See the
[REST command reference](help_td_restapi_cli.md#diagnostics-fetch-all) and
[REST mesh coverage rules](thread_network_health.md#rest-mesh-diagnostic-responsiveness).

### Browser-only Appearance

[tdash-theme.js](../src/js/tdash-theme.js) is a blocking classic script loaded
before styles and vis-network. It resolves `tdash.themePreference` to root
`data-theme`/`data-theme-preference` attributes and native `color-scheme` before
paint. It owns guarded storage, System resolution and cross-tab events, not
controls or computed CSS. A frozen `globalThis.tdashTheme` controller exposes
`getState()`/`setPreference()` and publishes immutable `tdash:theme-changed`
snapshots. Bootstrap failure leaves system-driven CSS as the fallback.

[tdash-ui.js](../src/js/tdash-ui.js) binds both appearance cycle buttons and one
document listener, including when Topology is hidden. The renderer's
`readThemePalette()` validates/caches CSS colors per resolved theme;
`projectTopologyTheme()` builds frozen replacement style maps and presentation
patches. The active render owner's `applyTheme()` updates existing DataSets
without publishing selection, rebuilding views, or touching camera/physics.
Adaptor `themeRole`/`themeColorKey` metadata is browser presentation only;
it does not enter normalized rows, details, cache files or exports.
The topology view model refines child presentation roles from canonical node
and identity-matched child-table evidence before theme projection. Confirmed
REED, MED, and SED styles remain separate from unconfirmed child and unknown
fallbacks; filter classifications and counts do not change. Canvas-matched
SED fills and unknown-role border dashes participate in theme/search/health
restoration. The collapsible topology legend uses the same CSS role tokens.
There is no appearance API, server flag, collector or database setting.

The header home link uses a decorative inline SVG with `currentColor`, so its
solid home symbol follows the link's light/dark text and hover colors. The
visible `hobat` label, navigation target, and keyboard focus style are retained.

Workspace and device Insights share a monochrome outline-bulb SVG. The cache
options and grouped filter disclosures use down/up chevrons with `aria-controls`,
visibility-derived `aria-expanded`, and Show/Hide accessible names. Their state
also follows the individual section headers; activating a disclosure with any
controlled section hidden or collapsed opens all its sections.

Device properties use an outline properties-sheet SVG; Operations uses a
distinct two-stage workflow SVG for its Logs and Jobs workspace. Thread Network
uses a network-dossier SVG: a small network branch beside fact lines inside
an outline card. It is a decorative summary marker, not network health or a
live device count.
All inherit the existing tab text and selected-state colors, without changing
navigation, accessible names, or keyboard behavior.

Topology uses a six-node hexagonal mesh SVG with three opposite-node cross-links,
including the top-to-bottom link. Its non-directional links and round nodes
distinguish it from Operations; it is a decorative symbol, not a live node count.

The Insights: Health heading ends with a decorative Activity Pulse SVG in the
heading text color; it is a static section marker, not a live status indicator.

The Links status label uses a fixed, decorative signal-bars SVG in the current
text color. It still reports a link count, not a measured signal-strength
reading; the separate LQ3/LQ2/LQ1 counts are unchanged.

The dashboard also uses API paths and views outside snapshot assembly. Health
processing consumes approved cached files and writes assessments to
`hobat_v1.db`; health GET routes read stored projections from that database.
Device diagnostics run as transient actions and do not update snapshots or
health history. Device labels use their own static-map API. The Thread Network
workspace summarizes network facts and device/link evidence from the loaded
dataset and capabilities, including observation-scoped partition membership;
it does not trigger a separate live collection.

## Server Routes

| Method and route | Handler | Behavior |
|---|---|---|
| `GET /` | `handle_root` | Redirect to `/tdash.html` |
| `GET /api/catalog` | `handle_catalog_api` | Return the validated dataset catalog without caching |
| `GET /api/capabilities` | `handle_capabilities_api` | Report source availability, cached files, and validated Unified cached/buildable state |
| `GET /api/data/{filename}` | `handle_data_api` | Serve an allowed file, refresh a raw snapshot, or start a cache-only Unified build |
| `GET /api/job/{job_id}` | `handle_job_api` | Return job state and final/checkpoint metadata |
| `DELETE /api/job/{job_id}` | `handle_job_cancel_api` | Request cancellation of a running job |
| `GET /api/jobs` | `handle_jobs_api` | Return a no-store projection of all active generic, health, and device-action jobs |
| `DELETE /api/jobs` | `handle_jobs_cancel_api` | Request deterministic, idempotent cancellation of all active jobs |
| `GET /api/health/summary` | `handle_health_summary_api` | Read a pinned or latest grouped assessment |
| `GET /api/health/findings` | `handle_health_findings_api` | Read filtered or paginated findings for an assessment |
| `GET /api/health/devices/{device_id}` | `handle_health_device_api` | Read one device's findings and approved health evidence |
| `GET /api/health/observations` | `handle_health_observations_api` | Read bounded observation history |
| `GET /api/health/comparison-endpoints` | `handle_health_comparison_endpoints_api` | Page retained Before/After candidates, resolve defaults/shortcuts, and expose optional adjacent-run metadata |
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

Collection automation instead calls
[`td_cli source-probe`](help_td_cli.md#source-probe) once before each supported
source block. It reuses the bounded probes without consulting cached evidence,
probe TTLs, or inflight dashboard results, and does not change this API's
cache-first behavior.

### Health and Device-Action Flows

```text
Dashboard -> POST /api/health/process-dataset -> web server
                 -> td_cli health process-dataset -> hobat_v1.db
Operator maintenance -> td_cli health migrate-history -> verified backup + retained assessment revisions
Operator maintenance -> td_cli health migrate --check/--apply -> schema registry + .migration-backups/
Operator maintenance -> td_cli health prepare-history -> derived SQLite evidence
Dashboard -> GET /api/health/* -> web server -> query-only hobat_v1.db read
Dashboard -> PATCH /api/health/roster/{device_id} -> validate revision/receipt
                 -> atomic roster + lifecycle audit + receipt + reassessment transaction
Dashboard -> POST /api/device-actions -> validate -> source action
                                                           -> transient job/result (memory)
```

Health processing is cache-only: the server starts a background `td_cli` job
with `--allow-partial`, which writes health history to `hobat_v1.db` without
starting a collector, changing a snapshot, rebuilding a Unified generation, or
probing a device. Health GET
routes never load the historical manifest archive. Explicit `health migrate-history`
preflight alone loads the bundled current/archive resolver, discovers retained
dataset IDs, and validates historical source contracts separately from current
targets. Only identical retained replay contracts are adapted; original samples
and historical roster policies are not reprocessed. Locked replay checks the
same file snapshot and database inventory before backup and cohort writes.
New audit JSON retains source-resolution provenance without changing native
assessment identity or the database schema. See
[historical contract limits](thread_network_health.md#bundled-historical-contracts).
Health GET
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

Roster reassessment shares validated retained evidence only within that
network's transaction, including nested automatic comparisons. Newly inserted
assessments become visible to each source/mode-specific history group before
comparison work. Each dataset still derives its own endpoint/monitoring-epoch
absence counts, with per-assessment contract validation. CLI and browser writes
retain the same atomic boundary. Invocation-local admissions never survive it.
Roster revisions evaluate only the four retained roster/context rule IDs and
reuse previous non-roster findings. Shared sample-derived coverage and final
aggregation rebuild pillar states, status/confidence and assessment identities;
the previous coverage object is not used as a shortcut. Ordinary dataset
processing still evaluates all rules, and automatic interval comparisons and
their writes remain inside the existing transaction. Schema 10 adds separate
derived observation bodies and sample-derived comparison fragments, published
by shared normal processing or bounded explicit `prepare-history`.
Later transactions verify current native SQL signatures and full contracts
before reuse, then still admit each assessment individually. Roster/absence
context, compatibility, headers and final writes remain fresh. PATCH misses
reconstruct without publishing; GET and dry-run remain query-only. See
[preparation maintenance and limits](thread_network_health.md#preparing-retained-evidence).
[td_health_preparation.py](../src/td_health_preparation.py) owns versioned,
compressed payloads and checksum/input validation; native samples remain
authoritative. Preparation has per-network record/byte budgets and does not
cache roster/absence decisions. Explicit maintenance uses bounded observation
and pair limits plus an inventory-bound continuation cursor; changed history
requires restarting rather than resuming a stale cursor. Invalid prepared
payloads or changed native bindings are corruption errors, not successful
fallbacks. No browser route starts preparation maintenance.
The dialog announces the pending save until commit, then reconciles the views.
Post-save reconciliation owns its roster-page reads: one for the current
filters and, only when needed to keep the selected device visible, one after
expanding an excluding designation/presence filter to All. Its assessment
refresh suppresses the ordinary automatic roster read; other refresh callers
retain it.
A failed post-commit refresh offers a refresh-only retry, distinct from an
uncertain PATCH outcome's same-request retry.

Newly processed relationship evidence preserves incoming link quality and
queued-message counts of zero. Preferred fields fall back to aliases only
when absent or null, not when zero or invalid. A positive queue followed by
zero can therefore be reported as cleared; missing evidence remains unknown.
This correction does not rewrite retained observations or change the schema,
health thresholds, or historical evidence.

The Device Roster list projection combines presence from the pinned assessment
with network-scoped last-known fields from SQLite; list reads do not fetch
individual device details. See [Thread Network Health](thread_network_health.md#read-api-and-dashboard)
for the additive field and sorting contract.

The endpoint inventory GET pages retained assessment metadata and resolves
defaults and interval candidates over the full history. The arbitrary pair GET
uses an exact stored pair or derives one from retained evidence in a query-only
transaction; neither GET invokes health processing. Comparison reads accept
optional Result and scope filters and return the matching-row count alongside
the unfiltered comparison count. The health read service and SQLite store apply
both filters before `LIMIT`/`OFFSET` in one read transaction, including the
effective Unknown classification for non-comparable or baseline-pruned items.
The dashboard explicitly requests its Changed default; callers that omit the
filters retain the unfiltered API behavior. Subject search and supported
ordering operate across effective matches before paging. The table pager
offers 25, 50, and 100 rows, defaulting to 100; endpoint-history pages remain
separate. See
[Thread Network Health](thread_network_health.md#read-api-and-dashboard) for
route parameters, latest-After preset selection, Custom endpoint selection,
filter/count semantics, and lifecycle. For `side=after`, the endpoint inventory
also returns optional page-independent `selectedAssessmentId`, `older`, and
`newer` navigation metadata. Adjacent runs use one preferred assessment per
observation, skip sibling revisions, and remain query-only; this metadata does
not alter Comparison endpoint state. Findings, Comparison, and Device Roster
are browser-owned peer tabs; the selected tab, preset intent, disclosure
state, visible row ranges, selected table page sizes, and pagination remain in
the browser.
Findings, Comparison, and Roster each have a local reset that preserves the
other tabs' state. These navigation choices do not
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

The browser owns each submission independently of the selected device. A
selection change or Cancel during submission retains cancellation intent and
disposes of a later accepted job without attaching it to the new selection.
It validates job/result identities and states, bounds each POST/GET/DELETE
including body consumption to 15 seconds, and polls every 500 ms for at most
the submitted deadline plus 30 seconds after validated acceptance. That local
budget includes source-lock queue wait; the server subprocess deadline starts
only after acquiring the lock. Local timeout, transport failure, or invalid
protocol means the result is unavailable and server state uncertain, not
proven action failure or cancellation. Known job references remain available
for Cancel/Pending Jobs; POST is never automatically replayed.

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
        |                           (Unified: validate generation or 409)
        |
        v
normalize request max-age (invalid --> 400), then evaluate freshness
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
estimated cost, and `force_async`. Checkpoint filenames are derived from eligible dynamic entries with the
`.partial.json` suffix and are served as non-regenerating, zero-max-age files.
Unified actions are explicitly excluded: their publication boundary is the
committed report, not a progressive checkpoint.

For dynamic files, request `Cache-Control: max-age=N` overrides the configured
age, including when the request permits an older snapshot. Nonnegative integers
and quoted ASCII decimal values such as `max-age="60"` are supported.
`max-age=0` or `no-cache` requests regeneration; `only-if-cached` forbids it and
returns 404 if the snapshot is missing or stale under the requested policy.
Invalid ages, including negative, empty, bare, or nonnumeric values, return
HTTP 400 before dispatch rather than falling back to another age policy.
Static files and checkpoints bypass regeneration-age validation.

After a dataset job reports `done`, the browser reads its final snapshot with
`only-if-cached, max-age=31536000`, independently of the initial refresh intent.
A missing final reports a failed read without dispatching another collector.
The browser retains its accepted snapshot when one is available.

A catalog recipe can reuse an already registered filename by changing only the
[manifest](../src/td-dataset-manifest.json). A new snapshot filename also needs
an entry in `td_webserver.py` `FILE_ACTION_MAP` (static or with a collector
action) and a producer or operator-supplied file. Listing it in the catalog
alone does not make `/api/data/{filename}` serve it: unknown filenames return
404. Unified is the catalog-derived exception: `_build_file_action_map()`
registers each validated Unified row action and its declared report, outcome,
identity, and network companions. This does not expose arbitrary raw filenames.

Data responses include `Cache-Control`, `Last-Modified`, and an ETag. Ordinary
files use mtime and size; Unified rows and companions use the verified artifact
content digest and serve the same bytes that generation validation admitted.
Validation precedes conditional response handling, so an invalid generation
cannot bypass its HTTP 409 failure through revalidation. Both HTTP 200 and 304
Unified responses retain `X-TD-Materialization-State`. `If-None-Match` takes
precedence over `If-Modified-Since`. Static HTML/CSS/JS uses
`Cache-Control: no-cache` so the browser revalidates it.

Browser Cache Only sends `only-if-cached, max-age=31536000`; Direct-Refresh
sends `no-cache`; Auto uses the remembered response max-age when available,
otherwise the server policy. These controls affect raw-file regeneration or
Unified processing, not the independent query-only health and transient
device-action APIs.

### Source Serialization and Deduplication

The server deduplicates simultaneous refreshes of the same filename and uses an
`asyncio.Lock` per source command family. Two OTBR CLI actions therefore do not
run concurrently in one server process, while unrelated source families can
progress independently. Devices, diagnostics, mesh diagnostics, canonical and
native topology, and native Thread inventory refreshes from `ha-matter-ws`
share one source lock so concurrent dashboard requests do not load the Matter
controller in parallel. Native dashboard actions never add diagnostics
`--force` or topology `--refresh`.

All Unified HTTP builds share the `unify-dataset` command-family lock. Their
subprocesses additionally use the data-directory `flock`, which also coordinates
explicit CLI materialization across processes. Health processing is separate
from collector refreshes and never implicitly builds a Unified prerequisite.

Short actions repeat the same request-aware freshness decision after acquiring
their source lock. A snapshot refreshed while the request waited can be reused
only if it meets that request's bound. Joining an already-running collection
does not start a second refresh or retry a successful `max-age=0` request.

## Background Jobs and Cancellation

Jobs use five states:

- `running`
- `cancelling`
- `cancelled`
- `done`
- `error`

Only `running` jobs begin a new cancellation. `cancelled`, `done`, and `error`
are terminal. A successful DELETE transitions a running job to `cancelling`,
cancels its task, terminates the tracked subprocess, and uses a force-kill
fallback if graceful termination does not finish in time. Unknown jobs return
404; terminal or otherwise non-cancellable jobs return 409. Repeated DELETE
while cancellation is still active returns 202 without cancelling the task
again.

Task completion callbacks finalize `cancelled` status even when a worker was
cancelled before its coroutine started. The same finalization is used for
generic data jobs, health processing, and device actions; device actions retain
their cancelled result and invocation metadata.

Completed job records are retained temporarily so clients can poll the result.
Each minute, cleanup removes terminal records older than 15 minutes measured
from job creation. Shutdown cancels cleanup and remaining background tasks.

Health-processing requests reuse the active job for their dataset. Completion,
cancellation, and expiry release a dataset's deduplication index only when it
still belongs to that job, so an older job cannot remove a newer job's entry.

The unified `/api/jobs` resource projects only `running` and `cancelling`
records from the generic and device-action registries. Stable kind and source
metadata lives on status records rather than transient runtime handles. The
projection excludes command arguments, action request payloads, subprocess
output, and credentials. Bulk cancellation snapshots jobs in creation-time and
job-ID order and delegates to the same request-independent helpers used by the
individual DELETE routes. A missing runtime handle or completed task transitions
a `running` or stale `cancelling` record to `cancelled` instead of leaving it
indefinitely pending. Terminal cancelled jobs disappear from this projection
but remain individually pollable until TTL cleanup.

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

After all files settle, the browser rebuilds from final payloads. Loading every
required final accepts that snapshot for later rollback, including a Unified
response with a validated `partial` materialization state. That state retains
its incomplete-coverage warning; a failed retry restores the accepted snapshot
without changing its freshness. A later successful partial load clears the
retry failure, not the incomplete warning. Progressive checkpoints and
bootstrap results missing required files never become the rollback baseline.
Auxiliary files remain optional.

Cancellation applies to all active jobs in the current fetch session. If usable
partial data exists, the browser keeps it and reports that the result is
partial, without promoting that preview to the rollback baseline.

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

The browser checks request generation and selected address after both response
headers and the JSON body arrive. A stale label read cannot overwrite a newer
selection's label, status, loading state, or controls.

Atomic replacement prevents partial JSON. The in-process lock does not
coordinate a separate writer process, so cross-process writes are
last-write-wins.

## Browser Application Layers

| Layer | Owners | Responsibility |
|---|---|---|
| Controls | `tdash.html`, `tdash-ui.js` | Source/dataset selection, Sync/Cancel, topology/table and Thread Network views, filters, settings/appearance, insights, device actions, activity logs, and pending jobs |
| Appearance bootstrap | [tdash-theme.js](../src/js/tdash-theme.js) | Classic pre-paint script for local preference, System resolution, root attributes, cross-tab updates, and theme events |
| Browser activity | `tdash-activity.js` | Bounded in-memory activity, route/metadata sanitization, subscriptions, and tracked HTTP requests |
| Source and catalog capabilities | `tdash-capabilities.js`, `tdash-catalog-fallback.js` | Source/file availability and bundled fallback for catalog loading |
| Fetch and assembly | `tdash-dataset.js`, `tdash-dataset-registry.js` | Catalog/menu lookup, cache policy, jobs, checkpoints, extractors, Unified materialization-state checks, and final/partial datasets |
| Field and merge contract | `tdash-device-fields.js`, `tdash-source-authority.js`, `tdash-merge.js`, `tdash-utils.js` | Preferred fields, aliases, identities, the shared REED resolver, normalization, precedence, conflicts, and provenance |
| Adaptation | `tdash-adaptors.js`, `tdash-adaptor-*.js`, `tdash-adaptor-model.js` | Source-specific records to canonical devices, relationships, and details |
| View model | `tdash-device-projection.js`, `tdash-topology-view-model.js`, `tdash-filters.js`, `tdash-search.js` | Derived device state, indexed visibility, diagnostic matching, and search state |
| Thread Network view model | `tdash-thread-network.js`, `tdash-ui.js` | Network facts with source attribution, network-instance context, observation-scoped partitions, and available device/link/role summaries |
| Presentation | `tdash-layouts.js`, `tdash-topology-utils.js`, `tdash-topology-renderer.js`, `tdash-table-renderer.js` | Seed layouts, vis-network lifecycle, theme projection, topology interaction, and sortable tables |
| Device diagnostics | `tdash-device-diagnostics.js` | Device-action eligibility, target selection, and result presentation inputs |
| Health | `tdash-health.js` | Assessment, findings, roster, comparison, and health-job API/rendering workflows |
| Status | `tdash-view-status.js` | Active-view status ownership and suppression of stale publishers |
| Styling | `tdash.css`, `tdash-constants.js` | Responsive layout, controls, palettes, node/edge styles, and vis options |

## Browser Activity and Jobs

Most browser API requests use `trackedFetch()`. Ordinary tracked calls record
a start and one terminal event; polling calls can be silent and their owning
workflow records only job-state transitions. The catalog bootstrap and device
action capability/action/cancellation requests use direct `fetch()` instead;
device-action job state is recorded explicitly in the activity log. Dynamic URL
components in tracked requests are replaced with route templates, query values
are retained only for an explicit allowlist, metadata is recursively bounded,
and failures use HTTP, network, or abort classifications rather than arbitrary
exception text.

The activity ring stores at most 200 entries in browser memory and is cleared
only by the operator or page lifecycle. The Jobs tab polls `/api/jobs` only
while visible: it waits 10 seconds when no jobs are active, otherwise uses an
elapsed-time-based delay bounded between 2 and 60 seconds. An abort controller
and monotonic request version prevent hidden or stale responses from replacing
the current table. Neither activity entries nor transient server job records
are written to `data/`.

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
`selectableDatasets()` excludes menu-hidden entries without removing them from
explicit canonical recipe lookup. Unified availability uses validated
`cached`/`buildableFromCache` flags, so a source can still offer its Unified
product while live collection is unavailable.
Startup populates these controls but does not load a dataset until Sync.

After editing the manifest, run `python3 script/build_dataset_catalog.py` to
regenerate the bundled fallback and restart the server. The manifest is the
single recipe source of truth, but the generated fallback must be refreshed
with it; recipes that introduce new snapshot filenames also need the server
registration and producer described under [Data Request Flow](#data-request-flow).

Legacy browser multi-file assembly does not enforce network-instance separation:
it can combine files from different instances. `tdash-view-status.js` compares known instance
IDs from `/api/capabilities` for loaded files and displays `Network instance:
mixed` when they disagree; unknown scopes do not block rendering. The offline
merge has a separate exclusion rule described in the
[Network Instance section](merge_thread_device_info.md#network-instance).
Unified is different: Python has already admitted scoped records into a
committed generation, and its browser adaptor retains `_unifiedRecordId` and
network-scoped relationship resolution rather than merging raw files again.

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
The shared Assessment toolbar starts in Latest mode; choosing or stepping
selects an exact retained assessment for Findings, Device Roster, and health
coloring. Latest resumes follow mode. Same-context refresh preserves a pin or
advances follow mode, while Comparison endpoints and each panel's reset state
remain independent. Historical reads and retries do not invoke the
`process-dataset` task.

Collector-derived role booleans remain source facts. OTBR collectors add
positive `isReed` evidence when a record identifies a child running in FTD
mode; the shared Python field layer normalizes role evidence. HA Matter uses
[ha_matter_ws_roles.py](../src/ha_matter_ws_roles.py) to preserve explicit role
booleans ahead of derived Thread/Border Router facts and retain contradictions
as merge conflicts. Browser
presentation uses explicit `isReed` booleans when present, otherwise a shared
FTD/child-or-nonrouter fallback independent of source, dataset, adaptor, or
filename. The browser resolver does not rewrite payloads or cache files; see
[Merge Thread Device Information](merge_thread_device_info.md#ftd-and-reed-capability)
for the decision contract and exclusions.

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

Primary navigation offers Topology, Table, Thread Network, Insights, Operations,
and Settings, in that order. The Thread Network tab targets the
`thread-network-summary` peer panel under the shared workspace. Operations
contains only Logs and Jobs. The summary keeps Dataset/Sync controls available
but hides Topology/Table filters without resetting their values. The existing
dataset-default Topology/Table switch after Sync is unchanged.

The Thread Network view is a browser-only projection of the currently loaded
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

Partition membership uses canonical `leaderData.partitionId` claims only when
the active network instance is known. Identity-deduplicated devices contribute
to one validated 32-bit partition ID; missing, invalid, conflicting, or
unidentified claims remain separate coverage counts. Mixed or unknown network
scope is unresolved, not a zero-partition result. Partial datasets retain an
observed-membership warning; multiple observed partitions are not independently
classified as a network fault or a complete live mesh census.

Activation and cached dataset updates reuse that same model; opening the view
does not initiate collection, auxiliary reads, a Unified build, or health
processing. Role-holder actions open Device details without leaving the
summary. Returning to the same loaded dataset preserves workspace/table scroll;
a replacement dataset starts at the top.

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

`projectTopologySelection()` derives presentation-only edge patches from
theme-resolved, profile-constrained base styles, visible relationships, and
current selection intent. Ordinary single-node inspection retains incident LQ
styles and dims fully opaque context edges to 0.42; already-translucent edges
retain their base opacity. Search and explicit health-target navigation
suppress this effect. No source/adaptor records, visibility, or geometry change.
The render owner recomposes after native select/deselect/click, filter,
search, health-color, and theme transitions. Programmatic search selection
refreshes explicitly; `selectTopologyHealthTargets()` signals health intent
after `setSelection`, preserving its existing target fit and explicit edges.
Disposable, owner-guarded handlers cannot patch a replacement network.

Relationship metric projection belongs to the browser adaptor/presentation
boundary, not dataset assembly or row-merge policy. CLI, merged, OTBR REST, and
Thread Tools adaptors normalize local copies of child and neighbor observations
with canonical metric aliases enabled, then project finite relationship
measurements into existing edges and tooltips. Composite child enrichment
requires the same parent and child RLOC16; when both records have concrete
extended addresses, they must agree. It does not create unmatched child edges.
Explicit neighbor-table observations retain the router-neighbor category, and
duplicate edge calls fill only missing finite metrics from the same endpoint
direction. Missing measurements remain unavailable; source rows and
detail/index records are not mutated.

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

Browser acceptance uses port 9178 and `--datadir ./data`. Refresh the linked
browser after frontend edits. Before the first Sync, enable the hidden Cache
Only control by setting `#chk-only-cache.checked = true` and dispatching a
bubbling `change` event. Enumerate offered source/dataset/filter options from
the rendered DOM rather than assuming an inventory.

Attach console, page-error, failed-request, and HTTP-status instrumentation
before reload; track the active source, dataset, view, and filter. Validate the
visible topology node/link status, positive canvas dimensions and nonblank
pixels after stabilization; zero links are valid. Validate table rows/headers,
`.table-wrap` scrolling, and no document-level mobile overflow. Accept HTTP
200/304, require exact baseline restoration after resets, and classify explicit
error states rather than diagnostic labels containing the word Error.

Hash `data/` before and after to prove fixtures were not modified. Stop the test
server and confirm port 9178 is free after acceptance. Documentation-only
updates do not require starting the server or running browser acceptance.