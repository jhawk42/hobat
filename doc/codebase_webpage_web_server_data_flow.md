# Webpage, Web Server, and Data Flow

This document covers `td_webserver.py`, `tdash.html`, `tdash.css`, and all
browser modules under `src/js/`.

## End-to-End Architecture

```text
tdash.html + tdash.css
        |
        v
tdash-ui.js -> tdash-dataset.js -> /api/data/{filename}
                                      |
                                      v
                              td_webserver.py
                               /           \
                    cached snapshot      td_cli subprocess
                         |                     |
                         +------ data/ <-------+
                                |
                                v
dataset assembly -> merge -> adaptor model -> topology view model
                                |                    |
                                v                    v
                         table renderer      layouts + topology renderer
```

The browser never calls OTBR directly. Live work is owned by Python collectors
started through `td_cli`; the browser consumes files from the configured data
directory through the server allowlist.

## Server Routes

| Method and route | Handler | Behavior |
|---|---|---|
| `GET /` | `handle_root` | Redirect to `/tdash.html` |
| `GET /api/data/{filename}` | `handle_data_api` | Serve, refresh, or start a job for an allowed data file |
| `GET /api/job/{job_id}` | `handle_job_api` | Return job state and final/checkpoint metadata |
| `DELETE /api/job/{job_id}` | `handle_job_cancel_api` | Request cancellation of a running job |
| `GET /api/device/{extAddress}` | `handle_device_get_api` | Read one static device label |
| `PATCH /api/device/{extAddress}` | `handle_device_patch_api` | Atomically insert or update one device label |
| `GET /**` | aiohttp static route | Serve `src/` assets |

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

Data responses include `Cache-Control`, `Last-Modified`, and an ETag based on
mtime and size. `If-None-Match` takes precedence over `If-Modified-Since` and
can produce HTTP 304. Static HTML/CSS/JS uses `Cache-Control: no-cache` so the
browser revalidates it.

### Source Serialization and Deduplication

The server deduplicates simultaneous refreshes of the same filename and uses an
`asyncio.Lock` per source command family. Two OTBR CLI actions therefore do not
run concurrently in one server process, while unrelated source families can
progress independently.

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
| Controls | `tdash.html`, `tdash-ui.js` | Source/dataset selection, Sync/Cancel, views, filters, settings, and insights |
| Fetch and assembly | `tdash-dataset.js`, `tdash-dataset-registry.js` | Registry lookup, cache policy, jobs, checkpoints, extractors, and final/partial datasets |
| Field and merge contract | `tdash-device-fields.js`, `tdash-merge.js`, `tdash-utils.js` | Preferred fields, aliases, identities, normalization, precedence, conflicts, and provenance |
| Adaptation | `tdash-adaptors.js`, `tdash-adaptor-model.js` | Source-specific records to canonical devices, relationships, and details |
| View model | `tdash-topology-view-model.js`, `tdash-filters.js`, `tdash-search.js` | Indexed visibility, capabilities, diagnostic matching, and search state |
| Presentation | `tdash-layouts.js`, `tdash-topology-utils.js`, `tdash-topology-renderer.js`, `tdash-table-renderer.js` | Seed layouts, vis-network lifecycle, topology interaction, and sortable tables |
| Status | `tdash-view-status.js` | Active-view status ownership and suppression of stale publishers |
| Styling | `tdash.css`, `tdash-constants.js` | Responsive layout, controls, palettes, node/edge styles, and vis options |

## Dataset Assembly

`DATASOURCE_REGISTRY` defines seven source groups. `DATASET_REGISTRY` is the
runtime authority for selectable datasets and declares ordered files, merge
strategy, row extractor, adaptor, default view, link filter, physics profile,
and estimated action cost.

On Sync, `loadDataset()` starts per-file requests concurrently and uses
`Promise.allSettled` so successful files can still produce a partial result when
another file fails or is cancelled. `buildDatasetRows()` is the pure assembly
boundary: it applies the selected row extractor, merge strategy, and canonical
output normalization while preserving source indexes.

The three browser merge strategies are:

- `none`: normalize/pass through records without cross-record merging.
- `by-rloc16`: merge records sharing canonical RLOC16.
- `by-identity`: merge through canonical extended address, OMR address, or
  RLOC16 with Matter composite-identity consistency guards.

First non-empty values win after source-priority ordering. Conflicting
non-empty values are retained in `_merge_conflicts` and contributing files in
`_source_files`.

## Topology Pipeline

```text
assembled dataset
      |
      v
source adaptor -> adaptor model -> emitted node/edge/detail maps
      |
      v
topology view model -> capability scan -> filter/search visibility
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

The table renderer discovers columns from current records and orders preferred
fields before additional fields. More Info expands the displayed/searchable
surface. Row and topology-node selection publish the same
`tdash:device-selected` event, keeping details, settings, and diagnostic
insights synchronized.

Filter options are capability-driven. The browser scans the active topology or
table payload and hides or disables unsupported node, link, and diagnostic
options. Link filtering applies only to topology. Diagnostic relationship
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