# Operator Guide

## Troubleshooting Logs

Set `TD_DEBUG_LEVEL` to `DEBUG`, `INFO`, `WARNING`, or `ERROR` (case-insensitive;
surrounding whitespace is ignored) for either entry point. CLI precedence is
`--debug`/`-d` > `--verbose`/`-v` > `TD_DEBUG_LEVEL` > INFO; `--debug` wins if
both switches are supplied. Invalid values exit with status 2 only when no
CLI level switch overrides them.

```bash
TD_DEBUG_LEVEL=' debug ' PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-restapi devices list
```

DEBUG can show HTTP traffic and `ot-ctl` diagnostics, but Thread Network Key
and PSKc values are redacted from REST success/error response-body logs,
captured child output, and active-dataset stdout by default. The explicit
`--log-thread-secrets` switch opts into those values only in OTBR REST DEBUG
response-body logs. It does not change stdout, snapshots, or non-REST logs.
On the webserver it is forwarded only to REST data jobs. Use this opt-in only
with controlled process-log access and retention.

The device summary's **Health:** control opens Network Insights. Its adjacent
health status control optionally colors topology node borders from the current
assessment; coloring is off by default, is not persisted, and resets when the
active dataset changes.

Table View sorting is available from keyboard-operable column buttons. Values
sort by their underlying type, empty/unknown values stay last in either
direction, and selecting a device from its identity cell opens the same details
as selecting its row. Sorting keeps the selected device.

Network Insights opens on **Findings** and offers three peer tabs:
**Findings**, **Comparison**, and **Device Roster**. Each tab keeps its filters,
selection, disclosures, pagination, and table position while switching tabs or
using **Show in table** and **Return**. The assessment summary is labeled
**Selected assessment**; it describes the pinned Findings/Roster assessment,
not an arbitrary comparison pair or necessarily its After endpoint. Its
observation time uses the comparison tab's UTC date-time format and includes
the elapsed age of the observation.

The Insights heading, selected-assessment summary, and tabs share a compact
sticky header. The Findings badge counts currently matching filtered groups;
the Device Roster badge counts currently matching filtered devices. These are
not population totals: zero is shown explicitly, while an unavailable roster
count stays blank. Comparison has no tab badge; its result count stays in that
panel.

Findings can be ordered by priority or a visible table field. **Reset Findings**
resets only its filters, order, and selection; Comparison and Device Roster
remain unchanged.

**Device Roster** shows a searchable, sortable, paginated inventory for the
selected stored assessment. Presence defaults to **Observed** and describes
that assessment, not network health; the separate roster designation reflects
the current operator-managed state. Missing and Offline come from stored
assessment findings, not device age. Selecting a device opens its stored facts
in the details panel. On desktop the roster includes stored address and inventory
facts alongside the existing columns, with sortable headings. On mobile the
table stays compact with Device and Presence; select a device to inspect all
facts and their freshness/conflict metadata in the details panel. Table values
are network-scoped last-known facts and do not necessarily describe the pinned
assessment or certify freshness; use Data quality and device details for
evidence quality. Missing values display as **Absent**.
The Device column and state context lead the horizontally scrollable table;
the identity column remains visible while moving across wider facts. Rows Per
Page offers 25, 50, and 100, defaulting to 100. All column headings remain visible
above scrolling rows, including the frozen Device column.
**Reset Roster** resets only its search, filters, sort, page, and selection;
Findings and Comparison remain unchanged.

From Findings or Device Roster, confirmed per-device actions can enroll an
observed untracked device, mark an expected device intentionally offline, clear
that designation, retire a tracked device, or unretire a retired device. These
actions update the expected roster and reassess retained evidence; they do not
collect data, change snapshots, or rewrite historical assessments. Enrollment
does not update the static label map. The same lifecycle changes are available
through the health CLI; see [Thread Network Health](thread_network_health.md)
for transitions, idempotence, audit, retention, and API details.

The **Comparison** tab offers **1D**, **3D**, and **1W** as the primary choices;
each resolves its baseline against the latest retained **After** assessment.
The default is 1D. **Custom** reveals independent Before/After selectors for
any retained assessment pair and is collapsed until opened. Selecting a preset
after a historical Custom choice returns to the latest After. The 1M control is
not shown; its server candidate resolution and automatic 30-day persistence
remain unchanged. Partial assessments remain manually selectable; partial
assessments or gaps longer than seven days may result in Unknown.

The comparison summary shows the selected UTC endpoints and actual elapsed
time; **Details** expands comparison metadata. **Reset comparison** restores
the default 1D/latest-After intent, **Changed** result, **All scopes**, first
pages, and collapsed Custom/Details without changing Findings or Device Roster.
**All scopes** and **Result**
(default **Changed**) filter the entire comparison before paging. The table
reports the visible row range and matching-row count separately from the
unfiltered total. Subject search matches current device names and canonical
IDs across the full result, including relationship endpoints; current names
remain annotations, not historical evidence. The Order control supports
Subject, Evidence, and effective Result. First, Previous, direct page
selection, Next, and Last controls share a Rows Per Page selector offering
25, 50, and 100, defaulting to 100. The table scrolls independently.
Comparison is available only when the server exposes comparison reads; unavailable
history, insufficient retained history, empty filter results, and failed reads
are reported separately. Processing stores adjacent and complete-only interval
pairs in `hobat_v1.db`; reads can also derive an unstored pair without writing.
See [Thread Network Health](thread_network_health.md) for API, retention,
and comparison details.

The **Logs** workspace contains local **Logs** and **Jobs** tabs. Logs retains
the newest 200 sanitized browser activity entries in memory only. Jobs lists
active dataset, health, and device-action work and supports individual or
confirmed bulk cancellation. Neither browser activity nor transient job state
is persisted in the data directory.

Dashboard API calls are same-origin and do not receive CORS authorization
headers. When using a reverse proxy, serve the dashboard and `/api/*` through
the same browser origin (and the same path prefix when one is used). Changing
the bind host does not create an origin allowlist. This browser restriction is
not authentication: direct clients such as `curl` or `wget` can call any API
route they can reach, so use firewall or authenticated proxy controls when the
API must be restricted. This is especially important for roster lifecycle and
device diagnostic mutations.

The unified pending-job listing and bulk cancellation API are server-wide
administrative operations. Browser confirmation prevents accidental bulk
cancellation but does not authorize it; deployments outside a trusted network
must protect these routes with an authenticated reverse proxy or equivalent
access control.

Device Diagnostics are enabled by default: Ping and OTBR Reset Counters create
active network traffic. Use `--disable-device-actions` or
`TD_DEVICE_ACTIONS_ENABLED=false` to disable all diagnostic actions. Use
`--disable-device-reset` or `TD_DEVICE_RESET_ENABLED=false` to disable only
Reset Counters while retaining Ping. Environment values accept `1`, `true`,
`yes`, or `on` to enable and `0`, `false`, `no`, or `off` to disable; CLI
disable switches take precedence. Same-origin routing is not authentication,
so deployments beyond a trusted network require an authenticated reverse proxy
or equivalent firewall controls before exposing the server. Diagnostic results
are transient and are never written to the data directory.

Device Diagnostics are explicit, transient actions, not Sync or health collection.
Each submission, poll, and cancellation request has a 15-second local limit,
including response-body decoding. Polling waits 500 ms between requests and stops
after the submitted action deadline plus 30 seconds, measured from validated
acceptance. This includes server queue/lock wait, so a local timeout can precede
server completion. “Result unavailable; server state uncertain” does not mean the
action failed or was cancelled: use the retained job's Cancel control or Pending
Jobs to inspect/cancel outstanding work. Cancel while queueing records intent;
accepted jobs from an old selection receive one cancellation attempt. Failed
cancellation can be retried explicitly. Diagnostic submissions, especially counter
resets, are never automatically replayed.

## Collection and Diagnostic Policies

Detailed
`networkdiag fetch-all` and REST diagnostic sweeps are the highest-impact
commands; use cached snapshots for repeated analysis.

Dataset recipes, merge input groups, and source authority defaults are declared
in `src/td-dataset-manifest.json` (schema 2). The server loads it at startup and
serves it at `GET /api/catalog` with `Cache-Control: no-store`; the dashboard
uses a bundled snapshot if the catalog request fails. After editing the manifest,
regenerate the bundled fallback with `python3 script/build_dataset_catalog.py`
and restart the server. Health field ranks remain derived from the unchanged
`rosterPolicy`, so existing health observation policy digests remain valid.

The per-router OTBR CLI meshdiag table collectors automatically send one
bounded two-attempt ICMPv6 probe to the queried router only after a table
timeout or explicit OTBR error. The resulting snapshot records table and ping
evidence separately; a ping reply does not make a failed table collection
successful. The probe is skipped when a unique, valid mesh-local router target
cannot be derived.

Default OTBR REST `diagnostics fetch-all` and `topology` sweeps preserve the
roster's `mode.fullThreadDevice` / `mode.device` evidence. Known MTD children
receive the fast request (TLVs 0, 1, 2, 8); the optional detail pass adds MAC
counters (0, 1, 2, 8, 9) and is disabled by default. Known FTD children receive
one medium request (0, 1, 2, 8, 9), independent of the MTD pass controls.
Each enabled known-child pass may repeat its identical TLV set once after a
terminal/no-result response. A same-set retry is not a smaller-TLV fallback;
the first usable result completes that pass. If detail fails after fast
succeeds, the fast record is retained and the device is reported partial.
Successful fast results are checkpointed before detail is enqueued.

The reduced child profile intentionally differs from the old 7-TLV detailed
request: MTD fast does not request MAC counters, while neither new child profile
requests `threadStackVersion` or `mleCounters`. Missing fields remain unavailable
to health evaluation, not zero or fresh inherited evidence. Enabling both MTD
passes can issue up to four actions per MTD child; detail therefore remains
opt-in. Unknown or contradictory child mode is warned and uses the legacy
detailed-to-medium progression.

`--no-fallback` prevents additional actions but preserves known-child initial
sets (and still permits separately enabled MTD detail, with one attempt per
pass). `--no-basic-fallback` only suppresses the final basic tier for routers
and unknown-mode children; it does not disable MTD fast or its same-set retry.
Use `--children-fetch-fast-no --children-fetch-detail` for detail-only MTD
collection, or disable both paired passes to explicitly skip MTD diagnostics
while leaving FTD medium collection enabled.
The child task timeout remains 30 seconds by default, with a derived poll
budget; neither timeout is shortened by this policy change. Custom `--types`,
non-recommended presets, and `--fallback-preset` retain the legacy/custom
request policy and cannot be combined with explicit MTD pass controls.

Mesh sweeps retain their separate split-TLV and basic responsiveness fallback.
Polling timeouts are never retried because the original action may still be
active. Shorter timeout experiments and live collection trials require separate
authorization; the new TLV policy alone does not promise a runtime reduction.

`networkdiag fetch-all --children-ping-fallback` is disabled by default. When
enabled, it sends one bounded ping to the derived RLOC address of each child
that did not answer any enabled Network Diagnostic policy. The child probe waits
up to 10 seconds to accommodate sleepy-device polling. An Echo Reply records
positive reachability, while no reply remains unknown and does not mark a sleepy
child offline. The same option is available on `otbr-cli topology` and applies
only to its `networkdiag fetch-all` step.

Network Diagnostic snapshots record `tlvRequestValues` as the largest
applicable request actually sent and `tlvResponseValues` as the cumulative
application-TLV coverage observed in complete response envelopes. Both are
numeric-sorted, distinct ID lists that exclude control IDs 32 and 33; `null`
means the evidence is unavailable, while an empty string means coverage is
known to be empty. Legacy cached `tlvValues` remains readable as request
metadata only. Router records without sufficient received coverage continue
through the existing bounded direct-diagnostic retry sequence.

## OTBR REST Zero-IID Diagnostic Guard

For standard batch diagnostics using extended-address destinations,
`diagnostics fetch-all` and the diagnostic step of `topology` skip any selected
device whose roster explicitly contains `mlEidIid: "0000000000000000"`,
regardless of role or mode, including legacy/custom TLV policies. Its outcome
uses `skipReasonCode: "unresolved_mesh_local_iid"` and counts the target in
`queriedCount` but not `attemptedCount`; it is not evidence that the device is
offline, and the roster record is not repaired or removed. Missing or
noncanonical IID evidence, ID-only inputs, and alternate destination types
retain their existing behavior. An all-guarded sweep does not clear diagnostics
or replace an existing diagnostic snapshot/checkpoint with an empty result.
Guard-affected `diagnostics fetch-all` writes its outcome beside the resolved
output as `.outcome.json` (the default file is
`td-otbr-restapi-diagnostics-fetch-all.outcome.json`); `topology` updates that
standard outcome file while retaining the prior diagnostic items. Refreshing
the roster with a nonzero IID makes the device eligible for a later sweep. See
the [zero-IID investigation](../plan/hobat-plan/datasource-otbr-restapi/2026_10_otbr_restapi_child_tlv_response_experiment.md)
for the discovery evidence and repair context.