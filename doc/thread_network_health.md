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
Unknown status. Offline requires absence from two distinct eligible complete
observations and more than 15% of the expected roster meeting that absence
threshold. This keeps occasional sleepy-device misses from making the network
Poor. Partial and degraded observations do not increment that count. Stage 1
reports observation counts, not wall-clock offline duration.

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
RSS, link margin, attachment, and Router/Border Router resilience. Border Router
redundancy is emitted only for profiles whose evidence can identify Border
Routers; incomplete observations keep that finding provisional. RSS alone is
supporting evidence and cannot produce Poor. Critical delivery evidence
escalates only when direct current evidence also identifies an observed sole
path.

An optional `config/td-health-policy.json` replaces the defaults after strict
validation. It must include the complete `snapshot-v1` threshold contract and
an Offline requirement of at least two complete observations. The applied
policy version and digest are stored with every assessment. Policy and profile
capability digests participate in assessment identity, so either kind of change
creates a new assessment over the same observation.

Every finding has a stable ID, scope, status, confidence, affected device or
relationship IDs, structured evidence, source files, action, and verification
text. Missing evidence remains Unknown.

## Coverage Pillars

Each health profile in `td-dataset-manifest.json` declares a coverage state for
five fixed pillars, checked against `ALLOWED_COVERAGE_STATES` in
`td_health_manifest.py`:

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

A `limited` or `missing` pillar can still contribute findings, but with reduced
confidence, consistent with the `complete`/`degraded`/`partial` completeness
levels above. The dashboard renders these states in the Insights five-pillar
coverage grid.

## Finding Catalog

Finding titles below are the grouped display titles from
`FINDING_GROUP_PRESENTATION` in `td_health_read.py`, in dashboard presentation
order. Descriptions summarize the implemented finding logic in
`td_health_evaluator.py`.

| ruleId | title | description |
|---|---|---|
| `network.border-router-redundancy` | Border Router Redundancy | Counts observed Border Routers. One means there is no Border Router failover; an incomplete observation or no authoritative count remains Unknown. |
| `network.router-redundancy` | Router Redundancy | Counts observed routing devices, including the Leader. One leaves mesh routing dependent on a single active Router; no observed Routers remains Unknown. |
| `network.external-routing` | Border Router OMR Addressing | Checks whether an identified Border Router has an address in the current OMR prefix. This supports OMR configuration but does not verify backbone, default-route, or Internet reachability. |
| `network.current-path-redundancy` | Router Path Redundancy | Identifies Routers with only one observed router-neighbor relationship versus multiple router-neighbor relationships. Child relationships do not establish alternate router paths. |
| `network.observed-link-quality-ratios` | Network Link Quality Distribution | Shows the proportion of observed link-quality reports at LQ3, LQ2, and LQ1. Missing and unknown quality reports are excluded rather than treated as healthy. |
| `observation.duplicate-source-entry` | Duplicate Relationships in Source Data | The same relationship appeared more than once in one source snapshot. It is treated as a collection artifact, not as multiple links. |
| `device.observed` | Observed Devices | Device is present in this cached observation. Presence does not prove application reachability or continued availability. |
| `device.missing` | Expected Device Missing | An expected device is absent from the latest observation but has not met the history and completeness requirements for Offline status. |
| `device.offline` | Offline Devices | An expected device has been absent for the required consecutive complete observations, and the policy's missing-roster threshold has also been exceeded. |
| `device.diagnostic-timeout` | Mesh Diagnostic Query Timed Out | The device did not answer a mesh diagnostic query in this observation. This reduces evidence coverage and may reflect sleep behavior, congestion, overload, or loss of connectivity. |
| `device.multiple-reporters-high-error` | High Link Errors Reported by Multiple Neighbors | Two or more observed relationships report elevated frame or message error rates toward this device, providing stronger evidence than one reporter alone. |
| `device.parentChanges` | Parent Changes Since Counter Reset | The cumulative parent-change count crossed its threshold. It may indicate earlier attachment instability, but a later comparable observation is required to establish current churn. |
| `device.partitionIdChanges` | Partition ID Changes Since Counter Reset | The cumulative partition-ID-change count crossed its threshold. Compare its change over time before concluding that partition instability is current. |
| `device.betterPartitionAttachAttempts` | Better-Partition Attach Attempts Since Counter Reset | The cumulative number of attempts to attach to a better partition crossed its threshold. A future delta is needed to determine whether attempts are continuing. |
| `device.totalParentPartitionChanges` | Parent and Partition Changes Since Counter Reset | The cumulative combined parent and partition change count crossed its threshold. It is historical evidence, not proof of current instability. |
| `device.routerRolePercent` | Low Router-Role Time Since Reset | The device has spent less than the configured proportion of its recorded uptime in the Router role. Interpret this against its intended role and compare future observations. |
| `device.detachedDisabledPercent` | Detached or Disabled Time Since Reset | The proportion of recorded uptime spent detached or disabled crossed its threshold. It does not establish that the device is currently detached. |
| `device.totalMacErrorRatio` | High Device MAC Error Ratio | The current device-wide MAC error ratio crossed a policy threshold using a valid packet denominator, indicating degraded delivery in this observation. |
| `device.totalMacDiscardRatio` | High Device MAC Discard Ratio | The current device-wide MAC discard ratio crossed a policy threshold using a valid packet denominator, indicating packet loss before successful delivery. |
| `device.attachment-failure` | Device Not Attached to Mesh | The device currently reports a detached, disabled, or orphaned state and is therefore not attached to the Thread mesh. |
| `relationship.bidirectional-lq3` | Strong Bidirectional Link (LQ3) | Both observed directions report LQ3, providing current evidence of a strong usable relationship. |
| `relationship.directional-quality` | Link Quality or Delivery Degradation | Directional LQ, asymmetry, delivery errors, RSS, or link margin crossed a current-snapshot threshold. Critical delivery errors become Poor only when an endpoint has no observed alternate relationship. An attributed finding uses **High Delivery Errors Despite Acceptable Signal** when errors are elevated despite acceptable RSS or link margin. |
| `relationship.queued-messages` | Indirect Messages Queued for Child | One or more indirect messages were waiting at the parent for this child in the current observation. This can be normal for a sleepy child; persistence or growth across observations is more significant. |

## Storage Safety

`hobat_v1.db` uses SQLite WAL mode, foreign keys, a five-second busy timeout,
and explicit transactions. Observation sources, normalized device and
relationship samples, assessment, findings, and current pointer commit together.
Any failure rolls back the whole operation. Reprocessing unchanged inputs and
policy is idempotent.

The filename promotes SQLite to a shared Hobat persistence boundary. The
existing health tables and their contents are retained unchanged.

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
completeness, and evidence age. Insights show five-pillar coverage, grouped
findings with lossless expansion, status/scope filters, recent observation and
expected-roster counts, and JSON export. Unsupported datasets show health as
unavailable and retain the existing diagnostic insights view.