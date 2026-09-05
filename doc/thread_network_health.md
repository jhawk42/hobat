# Thread Network Health

The health subsystem provides a cache-only `health process-dataset` command. It reads approved JSON
snapshots from the effective data directory, derives a deterministic assessment,
and optionally stores immutable history in the Hobat-wide `hobat_v1.db`. It never starts live
collection, probes devices, or rewrites collector files.

## Quick Start

Preview an assessment without creating the database:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset otbr_cli_networkdiag_fetch_all --dry-run
```

Store it atomically and emit one JSON document:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset otbr_cli_networkdiag_fetch_all --json
```

Write a non-authoritative support export after the database commit:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset otbr_cli_networkdiag_fetch_all --export-latest
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

## Eligible Datasets

The shared manifest currently permits these dataset IDs:

| Source | Dataset ID | Health profile |
|---|---|---|
| OTBR CLI | `otbr_cli_networkdiag_fetch_all` | `otbr-cli-networkdiag-v1` |
| OTBR CLI | `otbr_cli_topology_health` | `otbr-cli-topology-diagnostics-v1` |
| OTBR CLI | `otbr_cli_topology_mdns_health` | `otbr-cli-topology-diagnostics-mdns-v1` |
| OTBR REST | `otbr_restapi_devices_fetch_diagnostics_fetch_all` | `otbr-restapi-devices-diagnostics-v1` |
| OTBR REST | `otbr_restapi_devices_fetch_diagnostics_fetch_all_mesh_diagnostics_fetch_all` | `otbr-restapi-topology-diagnostics-v1` |
| OTBR REST | `otbr_restapi_topology_mdns_health` | `otbr-restapi-topology-diagnostics-mdns-v1` |
| Merged | `merged_otbr_topology_mdns_health` | `merged-otbr-topology-diagnostics-mdns-v1` |

OTBR CLI profiles and the merged OTBR profile use
`td-otbr-cli-thread-network-info.json` for source-wide network identity. OTBR REST
profiles use `td-otbr-restapi-dataset-active.json`. Both identity files provide
`extPanId` and `networkName` independently of the selected evidence recipe.

Arbitrary dataset IDs and file paths are rejected. Required final, identity,
and outcome filenames are versioned in `src/td-dataset-manifest.json`.

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

Expected devices are never enrolled automatically. Import valid `extAddress`
entries from the static label map explicitly:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset otbr_cli_networkdiag_fetch_all --init-roster-from-label-map
```

An expected device absent from one complete observation remains missing with
Unknown status. A device becomes Offline after absence from two distinct
eligible complete observations, independent of other roster devices. Offline is
a device-level Poor finding and does not by itself make the network Poor. The
separate `network.offline-impact` rule makes the network Poor when more than 15%
of the expected roster is Offline. Partial and degraded observations do not
increment absence history. Stage 1 reports observation counts, not wall-clock
offline duration.

List or update one network's roster through the CLI-only administration boundary:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset otbr_cli_networkdiag_fetch_all --roster-list
PYTHONPATH=src python3 -m td_cli --datadir ./data health process-dataset \
  --dataset otbr_cli_networkdiag_fetch_all --roster-device 0011223344556677 \
  --roster-label "Office Router" --roster-state expected
```

Supported states are `expected`, `retired`, `intentionally-offline`, and
`intermittent`. There are no roster mutation HTTP routes.

## Policy and Findings

Python owns all verdicts. Built-in `snapshot-v1` thresholds cover current MAC
delivery ratios, router-neighbor and child error rates, directional link quality,
RSS, link margin, multiple-reporter correlation, attachment, and Router/Border
Router resilience. Child and router-neighbor delivery policies have explicit
critical bands. Border Router redundancy is emitted only for profiles whose
evidence can identify Border Routers; incomplete observations keep that finding
provisional. RSS alone is supporting evidence and cannot produce Poor. Critical
delivery evidence escalates only when direct current evidence also identifies
an observed sole path.

An optional `config/td-health-policy.json` replaces the defaults after strict
validation. It must include the complete `snapshot-v1` threshold contract and
an Offline requirement of at least two complete observations. The applied
policy version and digest, evaluator version, and health profile ID are stored
with every assessment. Policy, evaluator, and profile capability digests
participate in assessment identity, so any semantic change creates a new
assessment over the same observation.

Every finding has a stable ID, scope, status, confidence, affected device or
relationship IDs, structured evidence, source files, action, and verification
text. The rule catalog declares and the evaluator enforces role, relationship,
capability, source, denominator, evidence-kind, materiality, and threshold-owner
contracts. Device-only findings do not automatically determine aggregate
network status; network and relationship materiality do. Missing evidence
remains Unknown.

## Coverage Pillars

Each health profile in `td-dataset-manifest.json` declares static capability for
five fixed pillars, checked against `ALLOWED_COVERAGE_STATES` in
`td_health_manifest.py`. Every assessment also records `observedPillars`, which
applies the same states to evidence actually present in that observation:

| Pillar | Covers |
|---|---|
| `availability` | Observed device presence and expected-device coverage. |
| `connectivity` | Attachment and relationship evidence showing how devices connect to the mesh. |
| `delivery` | Packet delivery and error-counter evidence from observed devices and relationships. |
| `resilience` | Router, Border Router, and alternate-path evidence for avoiding single points of failure. |
| `externalRouting` | Border Router and OMR configuration evidence; it does not imply tested backbone or Internet reachability. |

Each pillar is assigned one of three coverage states:

- `sufficient`: the assessment has the evidence required for this pillar.
- `limited`: some useful evidence is available, but coverage is incomplete.
- `missing`: the assessment does not have the evidence required for this pillar.

A `limited` or `missing` observed pillar can still contribute findings, but with
reduced confidence. Observed coverage cannot exceed static capability, and a
partial or degraded observation cannot have `sufficient` observed coverage.
The dashboard renders observed state with static capability as context.

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
| `observation.duplicate-source-entry` | Duplicate Relationships in Source Data | Reports duplicate source relationships as a collection artifact. |
| `device.observed` | Observed Devices | Records device presence in the current cached observation. |
| `device.missing` | Expected Device Missing | Reports an expected device absent without enough eligible history to establish Offline. |
| `device.offline` | Offline Devices | Reports an expected device absent for the configured consecutive complete observations. |
| `device.diagnostic-timeout` | Mesh Diagnostic Query Timed Out | Reports attributed missing diagnostic evidence for a device. |
| `device.multiple-reporters-high-error` | High Link Errors Reported by Multiple Neighbors | Correlates elevated delivery errors reported by multiple observed relationships. |
| `device.parentChanges` | Parent Changes Since Counter Reset | Reports a cumulative parent-change counter that requires a later delta to establish current churn. |
| `device.partitionIdChanges` | Partition ID Changes Since Counter Reset | Reports a cumulative partition-change counter that requires a later delta to establish current instability. |
| `device.betterPartitionAttachAttempts` | Better-Partition Attach Attempts Since Counter Reset | Reports cumulative attempts to attach to a better partition. |
| `device.totalParentPartitionChanges` | Parent and Partition Changes Since Counter Reset | Reports a cumulative combined parent and partition change counter. |
| `device.routerRolePercent` | Low Router-Role Time Since Reset | Reports low cumulative Router-role time for an observed Router or Leader. |
| `device.detachedDisabledPercent` | Detached or Disabled Time Since Reset | Reports cumulative detached or disabled uptime without claiming current detachment. |
| `device.totalMacErrorRatio` | High Device MAC Error Ratio | Reports a current device-wide MAC error ratio with a valid packet denominator. |
| `device.totalMacDiscardRatio` | High Device MAC Discard Ratio | Reports a current device-wide MAC discard ratio with a valid packet denominator. |
| `device.attachment-failure` | Device Not Attached to Mesh | Reports a current detached, disabled, or orphaned attachment state. |
| `relationship.bidirectional-lq3` | Strong Bidirectional Link (LQ3) | Reports a relationship where both observed directions have LQ3. |
| `relationship.directional-quality` | Link Quality or Delivery Degradation | Reports current directional LQ, delivery, RSS, or margin degradation using relationship-specific policy and path evidence. |
| `relationship.queued-messages` | Indirect Messages Queued for Child | Reports current indirect messages queued on a parent-child relationship as trend evidence. |

## Storage Safety

`hobat_v1.db` uses SQLite WAL mode, foreign keys, a five-second busy timeout,
and explicit transactions. Observation sources, normalized device and
relationship samples, assessment, findings, and current pointer commit together.
Any failure rolls back the whole operation. Reprocessing unchanged inputs and
policy is idempotent.

Schema version 3 stores evaluator version and health profile ID as explicit
assessment provenance. Older assessments migrate with `legacy-unknown` values;
their immutable finding and evidence rows are not rewritten.

The `snapshot-v10` read projection resolves known-rule titles, descriptions,
actions, verification text, evidence kinds, materiality, and template keys from
the catalog. Legacy findings receive version-aware metadata defaults at read
time; unknown legacy rules retain their stored operator copy and deterministic
fallback keys without rewriting history.

The filename promotes SQLite to a shared Hobat persistence boundary. The
existing health tables and their contents are retained unchanged.

After a successful non-dry-run `health process --dataset all`, current
assessment pointers for dataset IDs no longer present in the manifest are
removed transactionally. Their immutable observations and assessments remain
available as history.

The store retains at most 2,000 observations. Pruning occurs in the same write
transaction and never deletes collector snapshots. Automatic byte retention,
redaction, scheduling, probes, duration, rates, trends, and firmware compliance
are not implemented.

## Purge and Backup

Preview or apply age-based health retention; the default is 180 days:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data health purge --dry-run
PYTHONPATH=src python3 -m td_cli --datadir ./data health purge --keep-days 180 --yes
```

`observedAt` values strictly older than the UTC cutoff are removed. Cascading
health rows and stale current pointers are removed in the same transaction;
roster records are preserved. `purge-all` removes all health-domain records,
including roster records, while preserving `hobat_v1.db`, schema migrations,
and non-health tables. `purge-by-device --device EXTADDR` removes that identity's
health samples, relationships, and roster entry and deletes assessments derived
from affected observations. Shared observation/source records remain. None of
these commands removes data from collector snapshots, exports, or backups.

All purge commands support `--dry-run` and `--json`. Mutation requires an
interactive confirmation or `--yes`.

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