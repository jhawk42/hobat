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
| OTBR CLI | `otbr_cli_meshdiag_topology_networkdiag_fetch_all_mdns_scopes_thread` | `otbr-cli-topology-networkdiag-mdns-v1` |
| OTBR CLI | `otbr_cli_topology_mdns_health` | `otbr-cli-topology-diagnostics-mdns-v1` |
| OTBR REST | `otbr_restapi_diagnostics_fetch_all` | `otbr-restapi-diagnostics-v1` |
| OTBR REST | `otbr_restapi_devices_fetch_diagnostics_fetch_all` | `otbr-restapi-devices-diagnostics-v1` |
| OTBR REST | `otbr_restapi_mesh_diagnostics_fetch_all` | `otbr-restapi-mesh-diagnostics-v1` |
| OTBR REST | `otbr_restapi_devices_fetch_diagnostics_fetch_all_mesh_diagnostics_fetch_all` | `otbr-restapi-topology-diagnostics-v1` |
| OTBR REST | `otbr_restapi_topology_mdns_health` | `otbr-restapi-topology-diagnostics-mdns-v1` |

All OTBR CLI profiles use `td-otbr-cli-thread-network-info.json` for source-wide
network identity. All OTBR REST profiles use
`td-otbr-restapi-dataset-active.json`. Both identity files provide `extPanId`
and `networkName` independently of the selected evidence recipe.

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
Their findings remain provisional and confidence is reduced.

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
RSS, link margin, attachment, and Router/Border Router resilience. RSS alone is
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

## Storage Safety

`hobat_v1.db` uses SQLite WAL mode, foreign keys, a five-second busy timeout,
and explicit transactions. Observation sources, normalized device and
relationship samples, assessment, findings, and current pointer commit together.
Any failure rolls back the whole operation. Reprocessing unchanged inputs and
policy is idempotent.

The filename promotes SQLite to a shared Hobat persistence boundary. The
existing health tables and their contents are retained unchanged.

The store retains at most 2,000 observations. Pruning occurs in the same write
transaction and never deletes collector snapshots. Age/byte retention, backup,
purge, redaction, scheduling, probes, duration, rates, trends, and firmware
compliance are not implemented.

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