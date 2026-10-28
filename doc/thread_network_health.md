# Thread Network Health

The health subsystem provides a cache-only `health process-dataset` command. It reads approved JSON
snapshots from the effective data directory, derives a deterministic assessment,
and optionally stores immutable history in the Hobat-wide `hobat_v1.db`. It never starts live
collection, probes devices, or rewrites collector files.

## Quick Start

Preview an assessment without creating the database:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset otbr_cli_diagnostics_fetch --dry-run
```

Store it atomically and emit one JSON document:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset otbr_cli_diagnostics_fetch --json
```

Write a non-authoritative support export after the database commit:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset otbr_cli_diagnostics_fetch --export-latest
```

`--export-latest FILE` accepts only a leaf filename under the data directory.
It cannot be combined with `--dry-run`.

Process every health-eligible dataset in manifest order:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset all --json
```

For `--dataset all`, JSON output is an array of result documents. Roster
operations and `--export-latest` require one concrete dataset ID.

## Migrating Health Store Schema

Health schema version 9 is the current contract. Inspect an existing database
without creating a store or changing any files:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health migrate --check --json
```

Apply supported online-additive upgrades explicitly with:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health migrate --apply --json
```

Normal writable health-store startup uses the same ordered migration registry.
Before changing a non-empty store it creates and integrity-checks a
SQLite-API database-only recovery copy in `./data/.migration-backups/`, with
JSON metadata recording source/target schema versions and verification. Copies
are retained after success and failure; failed migrations roll back their
schema, rows, and version ledger. Check-only and read-only health paths never
create a recovery copy or repair an existing store.

Full data-directory backups omit `.migration-backups/` to avoid recursively
copying recovery history. Restore preserves the active directory's existing
recovery copies and refuses a same-name collision rather than overwriting one.
Remove recovery copies only after the upgraded database and a separate backup
have been verified and the copies are no longer needed for recovery.

## Migrating Retained Health History

`health migrate-history` replays validated retained observations under the
current evaluator and policy contract. It is cache-only: it does not read
today's snapshots, run collectors, probe devices, or rewrite original
observations and assessments. Schema 8 records immutable upgrade mappings and
preferred revisions; explicit assessment and comparison IDs continue to refer
to the original pinned records.

This history replay is separate from `health migrate --check` and
`health migrate --apply`, which only change database schema and never replay
assessments or process snapshots.

In short, `health migrate` changes the database structure; `health
migrate-history` revisits retained health evidence under the current evaluator
and policy. Neither command collects data or checks current network health.

Run this only during a maintenance window after stopping the dashboard's
write-capable health server, scheduled health processing, roster actions, and
collectors. Use the same absolute policy directory for migration and subsequent
native health jobs:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health migrate-history \
  --dataset all --policy-config-dir /absolute/path/to/server/config \
  --dry-run --json

PYTHONPATH=src python3 -m td_cli --datadir ./data health migrate-history \
  --dataset all --policy-config-dir /absolute/path/to/server/config \
  --backup-output /absolute/path/to/new-backup --yes --json
```

Use `--network extpan:<16 lowercase hex digits>` to limit the scope. A policy
digest different from, or not verifiable against, the native history requires
both an explicit `--policy-config-dir` and `--allow-policy-change`. The
external backup directory must not exist, must be outside the effective data
directory, and its parent must already exist. Dry-run requires an existing
data directory and database but does not initialize or write them.

The JSON report identifies replayable context gaps, unsupported history,
before/after findings and coverage, backup provenance, and committed cohorts.
Unsupported or failed history is reported with a nonzero exit status; it is
never silently treated as migrated. Missing historical roster, absence,
duplicate, OMR, or address inputs remain unavailable rather than being
reconstructed from current state. A context gap can lower confidence or leave
verdicts Unknown; migration does not certify network health.

### Bundled Historical Contracts

History migration loads the current [dataset manifest](../src/td-dataset-manifest.json)
and the reviewed [manifest archive](../src/td-dataset-manifest-history.json)
once during preflight. Runtime lookup requires neither Git nor network access.
Missing or corrupt archive data is a preflight failure, not a current-only
fallback. Native processing, schema-only migration, and health reads do not
depend on the archive.

`--dataset all` includes current eligible datasets and dataset IDs retained in
the selected network. An explicit archived or retained ID is accepted for
inventory, even if it has no current target. Unknown IDs absent from both
declarations and selected history fail preflight. This does not expand
`process-dataset` eligibility or install dataset aliases.

Only identical retained replay contracts use `retained-equivalent-v1`.
Supported evaluators remain snapshot-v10, snapshot-v11, and the current
evaluator; tagged samples must retain their actual per-dataset contract.
Pre-schema-4 producer snapshots are identification-only. `legacy-unknown`,
removed/renamed recipes, and changes to coverage, authority, or source recipes
are not converted. Historical roster policies and source priorities are
preserved as metadata, never applied to today's roster or retained samples.

Report schema 1 adds `contractResolutionVersion: 1` and per-item
`sourceResolution`, `sourceContractDigest`, `sourceRevisionIds`,
`targetContractDigest`, `adapterId`, and `legacyLineageReused`. Equivalent
source revisions are reported together; they do not prove which manifest was
deployed. Unsupported items have no target fingerprint. Explicit reasons
distinguish unsupported evaluator/sample/profile, no current health target,
ambiguity, and unsupported contract transitions from invalid retained evidence.
Exit codes are 0 for successful/current/empty, 1 for unsupported/invalid
history, 2 for preflight/argument failures, and 4 for a missing store.

New cohort audit counters retain additive
`counts_json.contractResolution` provenance. Validated older upgrade edges
keep their original digest, migration ID, and audit metadata; a no-op rerun
does not create a backup merely to enrich provenance. Changing manifest or
archive bytes during an invocation invalidates its preview before writes.
Between invocations, presentation changes and unrelated archive additions do
not change a replay target's identity.

Archive maintenance requires a reviewed inventory and independent fixed
snapshot/projection digests before adding a displaced supported manifest.
Never edit an archived snapshot in place or infer sample/evaluator support
from its date. Update the independent expectations in the
[archive and resolver fixtures](../tests/test_td_health_manifest_history.py)
alongside the reviewed inventory and operator documentation.

The archive also retains the committed manifest from `65fb5c6`
(`c74eca00bf7ba2175c2ae1df84e485e025a2fa27cb1c220a505d4bc484bb6011`).
Its replacement changes only the displayed source label from `Multi-source`
to `multi-source`; the current full-manifest digest is
`8d7fc3316a6859d07bd9ff8e5007001bb0737c248b812042fa8d77d6452bad81`.
Both retain health projection
`1a99aac03615857a4d0c33019c227b9c732a867e473fd1624c4d938e122a8f09`
and identical replay/target contracts. The displaced snapshot's explicitly
reviewed sample support is preserved, not inferred from archive membership.
All thirteen earlier archive entries remain immutable. No sample versions,
coverage, authority, backup/rollback or rerun guarantees change.

After migration, refresh a native assessment from cached snapshots before
normal dashboard use when the report identifies a policy transition or
context-dependent current coverage:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset all --allow-partial \
  --policy-config-dir /absolute/path/to/server/config
```

This follow-up also performs no collection or probing. It cannot repair
evidence that is genuinely absent. Review the migration report and preserve its
verified external backup according to the operator's data-retention policy.

## Eligible Datasets

The shared manifest currently permits these dataset IDs:

| Source | Dataset ID | Health profile |
|---|---|---|
| OTBR CLI | `otbr_cli_diagnostics_fetch` | `otbr-cli-networkdiag-v1` |
| OTBR CLI | `otbr_cli_topology` | `otbr-cli-topology-diagnostics-v1` |
| OTBR CLI | `otbr_cli_topology_mdns` | `otbr-cli-topology-diagnostics-mdns-v1` |
| OTBR REST | `otbr_restapi_devices_diagnostics_fetch` | `otbr-restapi-devices-diagnostics-v1` |
| OTBR REST | `otbr_restapi_topology` | `otbr-restapi-topology-diagnostics-v1` |
| OTBR REST | `otbr_restapi_topology_mdns` | `otbr-restapi-topology-diagnostics-mdns-v1` |
| Multi-source | `multi_source_otbr_topology_mdns` | `merged-otbr-topology-diagnostics-mdns-v1` |

### Dataset identifier cutover (2026-10-27)

The current seven health recipes use the compact IDs above. Their previous IDs
are intentionally unsupported for new processing requests: update scripts and
API clients rather than relying on aliases. The profiles, evidence files, fast
defaults, and collector commands have not changed. The synthetic source is now
`multi-source`; cache filenames and existing health profile names are unchanged.
CLI + mDNS and REST + mDNS remain under their respective OTBR source groups.

The displaced manifest is retained in the immutable
[manifest history](../src/td-dataset-manifest-history.json). Existing observations
keep their original dataset/source IDs, profile, digests, and lineage. There is
no historical-row rewrite, cross-ID history stitching, or replay into the renamed
targets. Archive membership alone does not grant replay support. Supported
non-health dataset aliases resolve directly to their canonical recipes; the
legacy source `merged` is accepted only with a matching non-health dataset alias,
not with a current health request.

The initial hidden Unified processing previews left these seven health
profiles and their health-contract projection unchanged. The preceding
identifier-migration and three-source-preview worktree manifests are retained
exactly for observations made between implementation phases. Those entries record
`captureKind: "worktree"` and an offset-bearing `capturedAt`, with null `commit`
and `committedAt`; it does not invent a Git commit. Exact producer support is
declared only for their existing canonical sample contracts. The additive,
hidden HA recipe does not qualify any Unified health profile. The exact
four-source-primary manifest immediately before adding Multi-source is also
archived with digest
`73e911ff0385d0de5f06bbb870dccb50467e78f64cec906bab18527125046b3e`.
It retains only the same seven canonical sample contracts; archive membership
does not authorize replay into any Unified target. The last pre-qualification
manifest is archived exactly as
`88ac93a9e81380ad7c02542c23e8cfe58f469cb180c589df89acc7f61b19349e`.
Other archived
entries and all historical-ID replay boundaries remain unchanged.

### Unified health qualification

The `otbr_cli_unified`, `otbr_restapi_unified`, `ha_matter_ws_unified`,
and `multi_source_unified` products have dedicated `*-unified-v1` profiles.
`mdns_unified` remains explicitly enrichment-only and health-ineligible.
All five Unified products are now selectable source primaries; fast defaults
and collector commands remain unchanged, and selection never processes health.
CLI topology and the HA seven-file composite are menu-hidden but explicitly
resolvable. REST topology and legacy precomputed Multi-source remain visible
until real-cache workflow parity is proved; see the
[current rollout limits](../README.md#cache-only-unified-materialization).
The exact qualified pre-rollout manifest is archived as
`d369ccc7cca9e30cd2016ac33213039343ef94d9d224ea73d2ffd2dbcb548dd6`.
Its reviewed producer contracts include the four Unified sample contracts;
older producer support is unchanged. The presentation-only rollout preserves
health projection `1a99aac03615857a4d0c33019c227b9c732a867e473fd1624c4d938e122a8f09`
and all existing replay/target golden vectors.
Build and process explicitly, without collecting:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data unify-dataset --dataset otbr_cli_unified
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset --dataset otbr_cli_unified
```

`inputMode: unified` and `evidenceReport` select the verified
original-evidence reader. Health verifies the committed report, row/identity/
outcome/scope bindings and original raw digests/times before normalizing through
source-owned converters. Changed, deleted or invalid originals require an
explicit cache-only rebuild. `--allow-partial` admits provisional evidence,
not unknown/mismatched network identity or a stale generation. Health never
rewrites a Unified generation or runs a collector.

Retained Unified lineage accepts the exact assembly-v2/v3/v4/v5 report
contracts. Assembly-v3 corrects repeated REST diagnostic observations in derived
rows; it does not change original-evidence samples, capability maxima, absence
witness rules, manifest snapshots, or replay eligibility. Assembly-v4 embeds
unambiguously matched Matter service advertisements under `mdnsRecords` in
derived Thread rows. Assembly-v5 corrects merged relationship-only markers and
adds HAP UDP advertisements to the same guarded association; health still
consumes only verified original evidence, not the derived marker or service array.
Existing assembly-v2/v3/v4
assessments remain readable and reopenable; unknown assembly contracts are still
rejected.

Samples and roster facts retain original filenames, field authority and
original observation times. Identity/outcome companions, mDNS services,
non-Thread Matter devices, relationship-only placeholders and derived dashboard
projections cannot manufacture Thread devices or counter measurements.
Native Thread links contribute only measured directional LQI/RSSI with
unambiguous admitted endpoints; qualitative strength is not measured LQI.
MAC ratios still require their original denominators. Missing pillars remain
missing/limited. CLI/REST/Multi-source coverage maxima are sufficient for the
first four pillars and limited for external routing; HA maxima are limited
for all five and have no whole-network topology/BR absence authority.
Original completeness, outcomes and unavailable inputs can only reduce these
maxima.

Unified assessments use `snapshot-v15` and the distinct
`comparison-v1-unified` sample contract. Legacy `snapshot-v14`,
`comparison-v1` and Route64 contracts and golden vectors are unchanged.
Original profiles default to `inputMode: files`. An immutable `unifiedRecipe`
uses the builder's `unified-v1` contract and retains the validated transitive raw closure;
versioned assessment `unifiedHealth` retains recipe/authority contract digests,
the original-evidence fingerprint, effective coverage and absence witness.
Observation identity excludes build/report timestamps. Rebuilding identical
evidence cannot create a fresh collection or advance Offline.

For new Unified absence assessments, a qualified complete CLI domain wins;
otherwise a complete qualified REST domain may supply the witness. The key is
the observed network, original diagnostic digest and original diagnostic time.
Required original topology/identity/outcome coverage must qualify that key.
Original and Unified projections count once, same-key positive device presence
overrides negatives, and the current key is excluded from prior counts.
CLI and REST streaks are never stitched together; unresolved time ties make
ordering unavailable. HA-only collections never supply a negative whole-network
witness. Retained roster reassessment uses the same rules without consulting
today's cache.

Reopening, comparisons, replay and complete-directory backup/restore validate
the retained recipe and original evidence; they do not need current raw files.
Restore the whole backup through the existing system commands, not selected
SQLite tables. Existing backup-first replay/rollback and rerun guarantees remain;
there is no SQLite schema migration, historical-ID alias, cross-ID replay
transition or threshold change. See the independent
[Unified regressions](../tests/test_td_health_unified.py) and
[manifest vectors](../tests/test_td_health_manifest_history.py).

OTBR CLI profiles and the merged OTBR profile use
`td-otbr-cli-thread-network-info.json` for source-wide network identity. OTBR REST
profiles use `td-otbr-restapi-dataset-active.json`. Both identity files provide
`extPanId` and `networkName` independently of the selected evidence recipe.

`ha_matter_ws_topology_merge` is explicitly ineligible. Current Matter snapshots
contain consistent per-record Extended PAN IDs, but do not provide a dedicated
identity context, processor-normalized native topology relationships, or a
single merged-collection outcome. It can be reconsidered when those three
cached contracts are available; see `ineligibleDatasets` in the manifest.

## Identity and Secrets

Network identity is only `extpan:<extPanId>`, where `extPanId` is exactly 16
lowercase hexadecimal digits after canonicalization. `networkName` is mutable
display metadata and is never an identity fallback.

The processor extracts only `extPanId` and `networkName` from identity-context
files. Network keys, PSKc values, and full identity payloads are not persisted,
logged, included in findings, or exported.

## Completeness

- `complete`: all required finals and identity context are valid and stable;
  applicable REST outcomes prove terminal success.
- `degraded`: final evidence is valid, but optional or legacy outcome metadata
  cannot prove full target coverage.
- `partial`: a required final is missing or invalid, a newer checkpoint exists,
  an input changes during reading, or an outcome reports incomplete/failure.

Partial evidence is rejected unless `--allow-partial` is supplied. Degraded and
partial observations cannot become Strong and cannot advance Offline history.
Their findings remain provisional and confidence is reduced. For profiles with
Border Router authority, Border Router redundancy still renders for partial or
degraded observations as Unknown instead of Strong or Moderate.

## Expected Devices and Offline

The evaluator reports these device states and related device findings:

- `observed`: the device identity was present in the current cached
  observation. This is informational evidence, not a claim that the device is
  healthy or reachable; the finding records observation completeness and
  source files. A device can be observed while also having attachment, counter,
  delivery, or relationship findings.
- `attachment-failure`: the current snapshot reports the device as
  `detached`, `disabled`, or `orphaned` (from its normalized `state`, or its
  `role` when no state is available). This is a current snapshot finding with
  network materiality. It does not establish Offline, which requires absence
  from complete observations.
- `missing`: a device explicitly in the active `expected` roster is absent from
  the current observation, but the configured consecutive-complete-observation
  requirement has not been met. The finding is device-scoped, Unknown, and low
  confidence. A complete observation increments the absence count; a degraded
  or partial observation reports the absence without advancing that history.
- `offline`: an active expected-roster device is absent for the configured
  number of consecutive complete observations. The default and minimum policy
  requirement is two complete observations. This is a device-scoped Poor
  finding with high confidence. It is independent of the aggregate network
  result: one Offline device can be Poor without making the network Poor.
- `recovered`: a previously absent expected device is present again in the
  current observation. The evaluator emits `observed` and does not emit
  `missing` or `offline`; prior absence history is not itself reported as a
  current device finding.

Expected devices are never enrolled automatically. Import valid `extAddress`
entries from the static label map explicitly:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset otbr_cli_diagnostics_fetch --init-roster-from-label-map
```

An expected device absent from one complete observation remains missing with
Unknown status. A device becomes Offline after absence from two distinct
eligible complete observations, independent of other roster devices. Offline is
a device-level Poor finding and does not by itself make the network Poor. The
separate `network.offline-impact` rule makes the network Poor when more than 15%
of the expected roster is Offline. Partial and degraded observations do not
increment absence history. Stage 1 reports observation counts, not wall-clock
offline duration.

List or update one network's roster from the CLI:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset otbr_cli_diagnostics_fetch --roster-list
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset otbr_cli_diagnostics_fetch --roster-device 0011223344556677 \
  --roster-label "Office Router" --roster-state expected
```

Supported roster states are:

- `expected`: active for presence and consecutive-complete-absence evaluation.
- `retired`: retained for administration and history, but excluded from the
  active expected roster and therefore not reported as missing or Offline.
- `intentionally-offline`: retained as an operator designation and excluded
  from missing and Offline evaluation.
- `intermittent`: retained as an operator designation and excluded from missing
  and Offline evaluation; the state does not change observation completeness or
  suppress current findings when the device is observed.

The dashboard also offers confirmed, single-device lifecycle actions from
Findings and Device Roster. The action-context
`GET /api/health/roster/{device_id}?network=extpan:...&assessment=assessment:...`
returns the network-scoped device detail, per-device and network roster
revisions, selected-assessment presence when requested, and server-computed
`allowedActions`/`disabledActionReasons`. The assessment parameter pins the
presence context; it does not change current roster designation. For an absent
device, Inspect opens its stored scoped facts rather than selecting a possibly
different current-network record.

`PATCH /api/health/roster/{device_id}?network=extpan:...` accepts one
confirmed action. The JSON object requires `action`, UUID `requestId`, and
non-negative `expectedRevision`. Actions are `enroll`, `mark-offline`,
`clear-offline`, `retire`, and `unretire`; optional `reason` is at most 500
characters. Enrollment additionally requires `contextAssessmentId` for a
retained assessment in that network and may include `deviceLabel`. Only a
device sampled in that assessment can be enrolled. An omitted label uses
`found-<16-hex canonical extAddress>` in the expected roster; neither path
updates the static label map or fabricates observed facts.

Transitions are state-gated by the server: Mark Offline is offered only from
Expected; Clear Offline changes Intentionally Offline to Expected; Retire
changes Expected, Intentionally Offline, or Intermittent to Retired; and
Unretire changes Retired to Expected. Retired and intentionally-offline
designations do not expire and later observations do not clear them. Returning
to Expected through Clear Offline, Unretire, or an explicit CLI expected-state
change starts a fresh absence-monitoring epoch. Partial or degraded
observations do not increment absence history, and an Offline device
contributes to the separate `network.offline-impact` finding only when the
Offline ratio is above the configured threshold (15% by default), not merely
because one device is Offline. Stage 1 reports observation counts rather than
wall-clock duration.

PATCH is revision-guarded and request-ID idempotent. A retry with the same
request ID and exact request body replays the stored response; reusing an ID
with a different body or acting on a stale revision returns a conflict and
requires fresh detail and confirmation. A committed lifecycle change records
its server timestamp, actor/source, reason, prior/next designation, context,
and revisions. The roster update, durable lifecycle event, retry receipt, and
retained-evidence reassessment commit atomically. Reassessment can create a
new current assessment revision without collecting data; previous assessments
and comparisons stay immutable. A no-op records a replayable receipt without
creating a lifecycle event or reassessment.

Health GET routes, including roster context, remain query-only and no-store;
PATCH alone writes. The write path requires the current roster schema and an
available health store. Expectation/lifecycle data is separate from observed
device facts and the static label map. Age-based health purge preserves roster
lifecycle history; explicit `purge-all` removes health-domain and roster
records. The API is same-origin, not authenticated: restrict the dashboard and
mutation route to a trusted network or authenticated reverse proxy/firewall.

## Policy and Findings

Python owns all verdicts. Built-in `snapshot-v2` thresholds cover current MAC
delivery ratios, router-neighbor and child error rates, directional link quality,
RSS, link margin, multiple-reporter correlation, attachment, and Router/Border
Router resilience, plus direct snapshot-count findings for selected MLE counters
and per-relationship child queue depth. Parent changes, partition ID changes,
better-partition attach attempts, and queue depths below 2 produce no threshold
finding; counts from 2 through 4 produce Moderate, and counts of 5 or more carry
a High evidence band while remaining Moderate. MLE findings are device-scoped
and do not change aggregate network status; threshold-crossing child queues are
relationship-material and can make the aggregate at most Moderate. A single
queue count does not establish persistence or message age. Child and router-neighbor delivery policies have explicit
critical bands. Border Router redundancy is emitted only for profiles whose
evidence can identify Border Routers; incomplete observations keep that finding
provisional. RSS alone is supporting evidence and cannot produce Poor. Critical
delivery evidence escalates only when direct current evidence also identifies
an observed sole path.

The network-scoped `network.partition-distribution` finding uses unique,
identified Thread devices with one unambiguous `leaderData.partitionId` claim in
the current observation. Within a complete observation, one reported partition
is Strong. Multiple partitions are Moderate when the largest contains at least
75% of devices reporting valid membership and Poor below 75%. Devices without
partition claims are excluded from this denominator, not assumed to share a
partition; the finding reports coverage and uses medium confidence when
membership is missing for some observed devices. Missing all membership,
invalid or conflicting claims, unresolved scope, and partial or degraded
observations remain Unknown. Evaluator `snapshot-v14` implements this
reporting-device contract; earlier assessments retain their original results.

An optional `config/td-health-policy.json` replaces the defaults after strict
validation. It must include the complete `snapshot-v2` threshold contract and
an Offline requirement of at least two complete observations. The applied
policy version and digest, evaluator version, and health profile ID are stored
with every assessment. Policy, evaluator, and profile capability digests
participate in assessment identity, so any semantic change creates a new
assessment over the same observation. Policies written before the queue-depth
and partition-distribution thresholds were added may omit
`thresholds.queuedMessages` and `thresholds.partitionDistribution`; those
policies inherit defaults of 2 and 5 for queue depth and 0.75 for partition
distribution and are digested with the normalized threshold entries.

Every finding has a stable ID, scope, status, confidence, affected device or
relationship IDs, structured evidence, source files, action, and verification
text. The rule catalog declares and the evaluator enforces role, relationship,
capability, source, denominator, evidence-kind, materiality, and threshold-owner
contracts. Device-only findings do not automatically determine aggregate
network status; network and relationship materiality do. Missing evidence
remains Unknown.

## Coverage Pillars

Each health profile in `td-dataset-manifest.json` declares static capability for
five stored-assessment pillars, checked against `ALLOWED_COVERAGE_STATES` in
`td_health_manifest.py`. Every assessment also records `observedPillars`, which
applies the same states to evidence actually present in that observation:

| Pillar | Covers |
|---|---|
| `availability` | Observed device presence and expected-device coverage. |
| `connectivity` | Attachment and relationship evidence showing how devices connect to the mesh. |
| `delivery` | Packet delivery and error-counter evidence from observed devices and relationships. |
| `resilience` | Router, Border Router, and alternate-path evidence for avoiding single points of failure. |
| `externalRouting` | Border Router and OMR configuration evidence; it does not imply tested backbone or Internet reachability. |

The dashboard currently presents Availability, Connectivity, Delivery, and
Resilience only. It intentionally suppresses the External Routing pillar and
its `network.external-routing` finding while preserving the raw observation
and stored-assessment evidence. Re-enable it only after an approved contract
defines the external-routing conclusion, required source snapshots, and
freshness/completeness requirements; restoring a display label is insufficient.

Each pillar is assigned one of three coverage states:

- `sufficient`: the assessment has the evidence required for this pillar.
- `limited`: some useful evidence is available, but coverage is incomplete.
- `missing`: the assessment does not have the evidence required for this pillar.

A `limited` or `missing` observed pillar can still contribute findings, but with
reduced confidence. Observed coverage cannot exceed static capability, and a
partial or degraded observation cannot have `sufficient` observed coverage.
Historical input availability is recorded separately from source completeness.
An unavailable roster, absence-history, OMR, device-address, or duplicate-
relationship input remains tagged Unknown rather than being treated as an
empty value. The network-scoped
`observation.evaluation-context-unavailable` finding lists the unavailable
domains and reason codes. Roster gaps suppress Missing/Offline conclusions;
absence-history gaps can retain Missing but cannot establish Offline. Gaps that
affect a verdict cap the applicable pillar at Limited and prevent Strong, while
an informational duplicate-context gap alone does not cap a verdict.
The dashboard presents each observed state as a labeled status indicator; its
tooltip includes the static capability and evaluator reasons. Static capability
is also displayed inline when it differs from the observed state.

## Finding Catalog

Finding metadata and dashboard order are owned by the machine-readable
`src/td-health-rules.json` catalog and validated by `td_health_rules.py`.
Descriptions below are validated exactly against the catalog. Public findings
also project catalog-owned `evidenceKind`, `materiality`, `actionKey`, and
`verificationKey` metadata plus an optional `presentationVariant`.

| ruleId | title | description |
|---|---|---|
| `network.border-router-redundancy` | Border Router Redundancy | Assesses whether authoritative current evidence contains enough Border Routers for failover. |
| `network.router-redundancy` | Router Redundancy | Assesses whether current topology evidence contains enough routing devices for redundancy. |
| `network.external-routing` | Border Router OMR Addressing | Reports whether an observed Border Router has an address in the OMR prefix without claiming tested external reachability. |
| `network.current-path-redundancy` | Router Path Redundancy | Identifies router-neighbor bridges and articulation Routers in the currently observed routing graph. |
| `network.observed-link-quality-ratios` | Network Link Quality Distribution | Summarizes the distribution of observed non-missing link-quality reports. |
| `network.offline-impact` | Offline Device Network Impact | Separately assesses whether individually Offline devices are material to network health. |
| `network.partition-distribution` | Thread Partition Distribution | Classifies valid reported Thread partition membership within one complete network observation; devices without claims are excluded and coverage is reported. |
| `observation.duplicate-source-entry` | Duplicate Relationships in Source Data | Reports duplicate source relationships as a collection artifact. |
| `observation.evaluation-context-unavailable` | Historical Evaluation Context Unavailable | Identifies evaluator inputs that were not retained or cannot be verified for this observation. |
| `device.observed` | Observed Devices | Records device presence in the current cached observation. |
| `device.missing` | Expected Device Missing | Reports an expected device absent without enough eligible history to establish Offline. |
| `device.offline` | Offline Devices | Reports an expected device absent for the configured consecutive complete observations. |
| `device.diagnostic-timeout` | Mesh Diagnostic Query Timed Out | Reports attributed missing diagnostic evidence for a device. |
| `device.multiple-reporters-high-error` | High Link Errors Reported by Multiple Neighbors | Correlates elevated delivery errors reported by multiple observed relationships. |
| `device.parentChanges` | Parent Changes Since Counter Reset | Classifies the observed since-reset parent-change count directly; the count alone does not establish current churn. |
| `device.partitionIdChanges` | Partition ID Changes Since Counter Reset | Classifies the observed since-reset partition ID change count directly; the count alone does not establish current instability. |
| `device.betterPartitionAttachAttempts` | Better-Partition Attach Attempts Since Counter Reset | Classifies the observed since-reset better-partition attach attempt count directly; the count alone does not establish current instability. |
| `device.totalParentPartitionChanges` | Parent and Partition Changes Since Counter Reset | Reports a cumulative combined parent and partition change counter. |
| `device.routerRolePercent` | Low Router-Role Time Since Reset | Reports low cumulative Router-role time for an observed Router or Leader. |
| `device.detachedDisabledPercent` | Detached or Disabled Time Since Reset | Reports cumulative detached or disabled uptime without claiming current detachment. |
| `device.totalMacErrorRatio` | High Device MAC Error Ratio | Reports a current device-wide MAC error ratio with a valid packet denominator. |
| `device.totalMacDiscardRatio` | High Device MAC Discard Ratio | Reports a current device-wide MAC discard ratio with a valid packet denominator. |
| `device.attachment-failure` | Device Not Attached to Mesh | Reports a current detached, disabled, or orphaned attachment state. |
| `relationship.bidirectional-lq3` | Strong Bidirectional Link (LQ3) | Reports a relationship where both observed directions have LQ3. |
| `relationship.directional-quality` | Link Quality or Delivery Degradation | Reports current directional LQ, delivery, RSS, or margin degradation using relationship-specific policy and path evidence. |
| `relationship.queued-messages` | Indirect Messages Queued for Child | Classifies the current queued-message count on one parent-child relationship; one snapshot does not establish persistence or message age. |

## Storage Safety

`hobat_v1.db` uses SQLite WAL mode, foreign keys, a five-second busy timeout,
and explicit transactions. Observation sources, normalized device and
relationship samples, assessment, findings, and current pointer commit together.
Any failure rolls back the whole operation. Reprocessing unchanged inputs and
policy is idempotent.

Schema version 4 adds comparison provenance and item tables, per-final-file
source observation times, metric kinds, and observed-roster tables.
Older assessments and metrics retain `legacy-unknown` sample semantics; only
losslessly represented extAddress, role, and state device facts are backfilled
with unknown source provenance. Existing assessments and findings are not
rewritten. A comparison is stored atomically with an eligible new assessment;
late-arriving observations do not move the current pointer backward. For each
complete After observation, processing also resolves the 1-, 3-, 7-, and
30-day targets from retained complete assessments and stores each unique
missing pair alongside the existing adjacent pair. Candidate IDs are
deduplicated, existing immutable pairs are not rebuilt, and all pairs share
the assessment transaction. The interval durations are elapsed days, not
calendar periods; long intervals can be stored as non-comparable Unknown.

New observations also retain source-specific Thread device facts. Only complete
observations advance the last-known projection; a repeated device file with an
unchanged source timestamp does not refresh its facts. The projection is separate
from the operator-managed `expected_devices` roster and does not infer device
identity from labels, EUI-64, RLOC16, or IPv6 addresses. Read-only
`GET /api/health/roster?network=extpan:...&limit=100&offset=0` pages canonical
devices; `GET /api/health/roster/extaddr:...?network=extpan:...` shows each
approved field, including absent and stale fields. Health Insights shows the
same projection under Observed devices.

Pinned roster list rows add a `fields` map for the table facts
`extAddress`, `rloc16`, `eui`, `omrIpv6Address`, `isBorderRouter`, `isRouter`,
`isLeader`, `leaderData.partitionId`, `threadVersion`, `threadStackVersion`,
`vendorName`, `vendorModel`, and `vendorSwVersion`. Each entry uses the same
value and evidence-metadata envelope as the device detail response; the dotted
partition key is literal. Missing or null values display as `Absent`, while
`false` and `0` remain visible values. The dashboard offers page sizes 25, 50, and 100, defaulting to 100. Its table
leads with Device, Presence, Roster designation, and Last observed; the Device
column remains pinned during horizontal scrolling. The roster sort keys include those
thirteen field names as well as `label`, `presence`, `rosterState`,
`lastObserved`, and `quality`. Booleans and partition IDs sort by type, OMR
IPv6 addresses sort numerically, and inventory/version strings sort
case-insensitively. Missing values remain last in either direction, with
device ID as a stable tie-break.

These are network-scoped last-known facts, not values reconstructed for the
pinned historical assessment; they can be stale or have unknown freshness.
Roster cells show values only and do not certify freshness. Use the Data quality
column and device details to inspect freshness, confidence, provenance, and
conflicts. List reads remain query-only and no-store.

Stale observed labels without a higher-priority label display a canonical
address suffix with `stale label` text; their original value and provenance
remain in the field details. Duplicate selected labels across devices show a
canonical suffix and `duplicate label` text, even across roster pages; label
origin and canonical identity remain separate. An older database must be migrated by
a write-capable `health process-dataset` before roster reads are available;
reads alone never migrate it. Reprocessing an unchanged observation upgrades
the schema but does not fabricate a last-known roster: new, complete observations
with valid source timestamps populate the projection. Unattributed migrated
facts retain unknown confidence and cannot replace sourced facts.

The `snapshot-v12` read projection resolves known-rule titles, descriptions,
actions, verification text, evidence kinds, materiality, and template keys from
the catalog. For pre-v11 assessments, valid stored materiality remains
authoritative so the queue rule's new relationship materiality does not rewrite
historical findings. Legacy findings receive version-aware metadata defaults
at read time; unknown legacy rules retain their stored operator copy and
deterministic fallback keys without rewriting history.

The filename promotes SQLite to a shared Hobat persistence boundary. The
existing health tables and their contents are retained unchanged.

After a successful non-dry-run `health process --dataset all`, current
assessment pointers for dataset IDs no longer present in the manifest are
removed transactionally. Their immutable observations and assessments remain
available as history.

The store retains at most 2,000 observations and 2,000 comparison headers.
Up to five unique comparisons may be added for one processed assessment, so
the unchanged comparison cap can shorten the stored-pair time horizon.
Automatic count pruning occurs in the same write transaction and never deletes
collector snapshots. Retained comparisons with pruned endpoints become Unknown
on reads; their original endpoint IDs and timestamps remain unchanged. Explicit
age purge instead deletes expired comparisons and their items, as described
below. The new endpoint selectors list retained assessments only; use a stored
comparison ID to inspect older pair headers whose endpoint was pruned. Automatic byte retention,
redaction, scheduling, probes, duration, rates, trends, and firmware compliance
are not implemented.

## Purge and Backup

Preview or apply age-based health retention; the default is 30 days:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health purge --dry-run
PYTHONPATH=src python3 -m td_cli --datadir ./data health purge --keep-days 30 --yes
```

`observedAt` values strictly older than the UTC cutoff are removed. Comparisons
are removed when either stored endpoint observation time is strictly older than
the same cutoff, along with all their comparison items. This also cleans up
expired comparisons whose original observations were deleted by an earlier
purge. Endpoints exactly at the cutoff are retained unless the other endpoint
is older. Cascading health rows and stale current pointers are removed in the
same transaction; roster records are preserved.

`purge-all` removes all health-domain records, including roster records,
while preserving `hobat_v1.db`, schema migrations,
and non-health tables. `purge-by-device --device EXTADDR` removes that identity's
health samples, relationships, and roster entry and deletes assessments derived
from affected observations. Shared observation/source records remain. None of
these commands removes data from collector snapshots, exports, or backups.
Purge-by-device also removes comparisons that reference an affected endpoint
observation. Automatic count pruning still leaves comparison headers available
with a pruned-baseline read state; explicit age purge removes expired pairs.

All purge commands support `--dry-run` and `--json`. Mutation requires an
interactive confirmation or `--yes`. Preview counts include `comparisons` and
`comparison_items` and match apply counts for the same database state and
cutoff. Active writers or the later cutoff of a subsequent command can change
the counts.

Create and verify a backup before destructive cleanup. For example, to retain
one day of health history and then optionally compact the database:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health purge --keep-days 1 --dry-run --json
PYTHONPATH=src python3 -m td_cli --datadir ./data health purge --keep-days 1 --yes
PYTHONPATH=src python3 -m td_cli --datadir ./data system database repack
```

Purge removes records but does not guarantee an immediate reduction in the
database file size. Repack is a separate, optional `VACUUM` operation; stop the
web server and other database users before repacking to avoid lock contention.
Allow working disk space for the purge's WAL growth and repack's temporary
files. No exact reclaimed size or runtime is guaranteed.

Create and restore a complete data-directory backup:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data system backups create \
  --output ./hobat-backup
PYTHONPATH=src python3 -m td_cli --datadir ./data system backups restore \
  --input ./hobat-backup --yes
```

Creation uses SQLite's backup API, excludes SQLite sidecars and transient lock
files, and writes a versioned manifest with checksums and schema version. The
output must be outside the active data directory. Restore validates all paths,
checksums, schema compatibility, and SQLite integrity before staging and
activating the replacement. Stop the web server and all writers first; restore
also refuses a database with an active writer. If validation or activation
fails, the original data directory is retained or restored.

Backups are unredacted and may contain device identifiers, topology, labels,
network credentials from collector snapshots, and configuration. Restrict
filesystem access and treat Home Assistant backup inclusion as sensitive.

## Read API and Dashboard

### Health Compare Two Assessments

Compare two stored assessments explicitly without reading or refreshing cached
collector files:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health compare \
  --before-assessment ASSESSMENT_ID --after-assessment ASSESSMENT_ID --dry-run --json
```

Omit `--dry-run` to store the deterministic pair. Automatic processing stores
the latest complete assessment strictly earlier than the new observation and
the unique complete assessments selected at or before 1, 3, 7, and 30 elapsed
days before it, for the same network and dataset. Identical observation times
are not paired. The separate `comparison-v1` policy permits gaps of at most
seven days and uses an uptime-continuity tolerance of 300 seconds. The result
is discrete Before/After evidence, not a trend, rate, duration, or availability
estimate. Counter
decreases and missing or conflicting reset witnesses produce Unknown rather
than a spike. A newer outcome file does not refresh an unchanged device file.
Approved cached device sources do not provide an audited reset epoch or uptime
witness, so increasing since-reset counters also remain Unknown; OTBR
`TrackedTime` is not treated as device uptime.
Partition and RLOC16 changes require matching, unambiguous immutable device
facts at both endpoints, with a newer attributed source time; the current
last-known roster does not supply historical endpoint values.
OTBR CLI hex partition IDs are stored as bounded integer facts, not treated
as opaque version strings.

For `otbr_cli_diagnostics_fetch`, a complete Route64 table from one
canonical reporter can contribute directional reporter-to-destination
membership comparisons. A table qualifies only with a bounded ID sequence,
at most 63 distinct entries, and every Router ID resolving unambiguously to
an explicitly reported device in that final snapshot. An explicit empty table
qualifies; a missing, malformed, duplicate, or unresolved table does not.
Both endpoint reporters must have qualified Route64 coverage from the same
final file with advancing source times before an added or removed route can
be reported. Otherwise the route item is Unknown. These are discrete
destination-membership observations, not a measured next hop, route cost
change, continuous route history, or a claim about Internet reachability.
Other datasets do not contribute Route64 comparisons.
Route64-aware OTBR networkdiag assessments use the `comparison-v1-route64`
sample contract and a distinct observation identity. Reprocessing a cached
snapshot preserves legacy immutable samples rather than relabeling them;
comparisons between legacy and Route64-aware assessments are non-comparable.
For snapshot OMR evidence, the identity file's observed OMR and mesh-local
IPv6 CIDRs must be valid, disjoint, and no later than processing time. An
identity refresh does not refresh the device file's source-observed time.
Stored roster addresses are sourced
display values, not verified stable OMR aliases; prefix provenance is not yet
persisted with those facts.

### Health REST API

`GET /api/health/comparison-endpoints?network=...&dataset=...&side=after&limit=25&offset=0`
pages retained assessment endpoints. Use `side=before` with `after=ASSESSMENT_ID`
to page only assessments strictly earlier than the selected After. The response
also resolves defaults and shortcut candidates over the full retained history,
independent of the page; `selected=ASSESSMENT_ID` pins an endpoint outside the
visible page. Limits cannot exceed 100.
The `side=after` response also includes additive `navigation` metadata when
`selected` is supplied: the selected ID and its adjacent older/newer preferred
run, independent of the requested offset. Navigation skips sibling revisions
of the same observation; an explicitly selected superseded revision remains
selected without becoming another stepping stop. This projection is resolved
in the read transaction and does not change Before filtering, list totals, or
Comparison selection.

`GET /api/health/comparison?network=...&dataset=...&before=ASSESSMENT_ID&after=ASSESSMENT_ID&limit=25&offset=0`
reads an arbitrary retained endpoint pair. It uses a matching stored pair when
available or derives the pair from retained evidence without writing. Optional
`scope=all|network|device|relationship` and
`result=all|changed|unchanged|unknown` filters are applied before paging.
Responses identify `origin` as `stored` or `derived`; derived responses have
`createdAt: null`. The older
`GET /api/health/comparisons?network=...&dataset=...&limit=25&offset=0`
and `GET /api/health/comparisons/{comparison_id}?limit=25&offset=0` routes
remain available for stored pair history, including pruned endpoints. All four
GET routes are read-only and no-store. Stored responses distinguish persisted
comparability from a read-time `baseline-pruned` override; no GET creates or
repairs a comparison.

### Health Insights Tabs: Findings, Comparison, and Device Roster

Network Insights offers **Findings**, **Comparison**, and **Device Roster** as
peer tabs, with Findings selected initially. Each tab retains its own
navigation, filters, selection, disclosures, and table position while moving
between tabs or using Show in table/Return. The **Selected assessment** summary
describes the assessment pinned to Findings and Device Roster. It must not be
read as the health of an arbitrary comparison pair or necessarily its After
endpoint.

The Insights heading, selected-assessment summary, and peer tabs share one
compact sticky header. Findings' numeric badge is the current filtered matching
group count; Device Roster's badge is the current filtered matching-device
count. These are not population totals. Zero remains visible, but an unavailable
roster count is blank and its accessible tab name has no count. Comparison has
no tab badge; its result count remains local to its panel. Badge text is hidden
from assistive technology because each counted tab exposes the full count and
unit in its accessible name.

One **Time** toolbar is shared by Findings, Device Roster, and health
coloring. Its label and date-button tooltips explain that the time is the
observation time (UTC), not when the health assessment was processed; the date
button also exposes this explanation to assistive technology.
**Latest** follows the latest stored assessment; choosing a retained
run or using **Older**/**Newer** pins its exact assessment ID until Latest is
selected again. The selected observation date opens the inline chooser below
the navigation row. The dropdown fits its option text, capped at the available
width on narrow screens. Its paging controls appear only for multi-page histories;
paging does not select a run. A compact line identifies Following latest or
Pinned assessment. Details exposes exact timestamps, assessment ID, and the
independent Comparison scope; pinned views retain a short visible reminder
that roster facts and layout are current.
The navigation buttons use `«` (oldest retained run), `‹` (Older), `›` (Newer),
and `»` (follow Latest), with descriptive tooltips and accessible names.
Oldest pins the oldest preferred retained run, using bounded history reads
without including an explicitly selected superseded revision as a separate stop.
Adjacent navigation uses the server's preferred assessment per observation,
skips sibling revisions, and remains independent of the visible chooser page.
An explicitly selected superseded revision remains pinned and is identified as
such. If history metadata is unsupported or a selected run is no longer
available, the dashboard explains the condition and offers recovery rather
than silently switching assessments.

Assessment selection, history paging, and retry are read-only. They do not
collect data, process health, or write history. Same-context Sync or explicit
Refresh Health retains a pin; while following Latest, it advances to the
latest assessment produced by that existing workflow. Tab changes,
Show in table/Return, and panel-local resets preserve the shared selection.
Comparison's Before and After endpoints remain independent of this toolbar;
Reset comparison does not change the selected Findings/Roster assessment.

Historical Device Roster presence and findings use the selected assessment,
but roster fields/designations are current or last-known projections.
Historical health coloring overlays the currently loaded table/topology rather
than reconstructing historical network layout; devices unmatched to current
data remain uncolored.

For health-eligible datasets with comparison-read capability, the Comparison
tab opens with the 1D preset selected and Custom collapsed. The 1D, 3D, and 1W
presets resolve against the latest retained After assessment, at or before
exactly 1, 3, or 7 elapsed days before its observation time. They do not fall
back to a later or nearest assessment. Custom reveals independent Before and
After selectors for any retained pair, including partial assessments; editing
an endpoint loads that pair automatically. Opening or closing Custom does not
change the selection. Missing preset candidates are disabled with an
accessible explanation.

Selector and summary timestamps are displayed in UTC to whole seconds while
retaining full source timestamps in option and heading metadata. The 1M control
alone is removed from the UI; its server-side 30-day candidate resolution and
automatic persistence remain unchanged. Partial or over-seven-day pairs retain
truthful Unknown behavior. The compact summary shows the selected endpoints
and actual elapsed time; expandable Details exposes comparison metadata.

**Reset comparison** resets only Comparison: it restores 1D/latest-After
intent, Changed results, All scopes, first history/result pages, collapsed
Custom and Details, and zero table scroll. It stays on Comparison and preserves
Findings and Device Roster state. Findings can be ordered by priority or a
visible table field; **Reset Findings** resets only Findings filters, order,
and selection. **Reset Roster** resets only its search, filters, sort, page,
and selection. Each reset preserves the other tabs' state.

Comparison remains discoverable while its capability and history are loading
or unavailable. Unsupported comparison reads, insufficient retained history,
no rows matching the current filters, non-comparable pairs, and request errors
are distinct states. Empty matches retain the selected pair and filters;
unavailable history is not presented as a successful empty comparison. Legacy
stored-pair reads remain supported when endpoint selection is not available.
Comparison reads and retries are query-only; they do not collect data, process
health, run diagnostics, or write the database.

Result defaults to Changed and offers Changed, Unchanged, Unknown, and All
results. Changed includes both improved and worsened rows; Unknown includes
non-comparable rows and rows whose baseline endpoint has been pruned. Result
and scope combine across the entire comparison on the server before paging.
Result follows Comparison scope in the filter controls. The UI shows the
visible row range, full combined-filter match count, and unfiltered comparison
count separately; for example, `1–25 of 482 matching rows` and `1,626 total
rows`. Subject search matches current device names and canonical IDs globally,
including relationship endpoints, while names remain annotations rather than
historical evidence. Subject, Evidence, and effective Result ordering apply
before paging. First/Previous/direct page selection/Next/Last navigate the
matching rows; Rows Per Page offers 25, 50, and 100, defaulting to 100. The
footer remains outside the internally scrolling table. Filters and valid
endpoints remain selected when changing pairs, pages,
or drilling down and returning; dataset/network identity changes, Reset
comparison, and reload restore Changed and All scopes. Changing a filter
restarts item paging at the first matching row. This view does not create pairs or infer deltas from roster
values. Old stored-pair APIs remain supported for clients that need to inspect
a pruned pair by its ID.

Relationship-change Evidence labels identify the immutable relationship type
captured at the comparison endpoints (`Parent/child`, `Router/neighbor`,
`Router/route`, or `REED/route`). Legacy comparisons without stored type
metadata display `Unknown relationship type`; the server does not reconstruct
or backfill it from relationship IDs or current roster facts. A relationship
type label is descriptive evidence only and does not qualify a comparison's
Result. Route membership remains a discrete destination-membership comparison,
not next-hop, route-cost, duration, or trend history.

When a current expected, static, or fresh unconflicted observed roster name is
available, Comparison annotates device-scope subjects and parent-transition
extaddrs with that name. The complete canonical extaddr remains visible, and
the original Before/After values remain the comparison evidence. These are
current roster annotations at read time, not names recorded at either
comparison endpoint; labels are not persisted in comparison history.

The aiohttp server exposes query-only, `Cache-Control: no-store` routes for the
latest or pinned assessment, grouped or ungrouped findings, one attributed
device, bounded observations, and store capabilities. Finding and observation
pages accept at most 100 records. Busy and unavailable stores return 503;
invalid or future schema data does not produce a best-effort verdict.

For health-eligible datasets, the dashboard pins one assessment after
Sync and reuses that ID for device drill-down. The status bar shows verdict,
completeness, and evidence age. Insights organize stored findings into Needs
Work, Needs Attention, and Going Well without reclassifying them in the
browser. Status, scope, and evidence-kind filters narrow the grouped findings;
each expanded finding includes structured evidence, materiality, confidence,
impact, action, verification, and source provenance.

Available finding actions can select attributed devices or relationships in
Topology, filter matching rows in Table, inspect one device, compare two
endpoints, or apply the related Insights filters. Return to Insights restores
the prior view, search, filters, and selection; Reset clears the health
workflow. Topology borders project the pinned finding status, and Table adds
`Health Status`, `Health Reason`, and `Health Observed` columns. Actions are not
offered when their target is absent from the loaded dataset. Unsupported
datasets show health as unavailable and retain the existing diagnostic
insights view.