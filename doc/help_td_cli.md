# td_cli — Command Reference

Thread Network Topology Dashboard CLI.

Run from the project root with:

```bash
PYTHONPATH=src python3 -m td_cli [global-options] <command> ...
```

---

## Global Options

| Option | Description |
|---|---|
| `-h`, `--help` | Show help message and exit |
| `--verbose`, `-v` | Select INFO logging, overriding `TD_DEBUG_LEVEL` |
| `--debug`, `-d` | Select DEBUG logging; takes precedence over `--verbose` and `TD_DEBUG_LEVEL` |
| `--log-thread-secrets` | Opt in to unredacted Thread Network Key and PSKc in OTBR REST DEBUG response-body logs only |
| `--output FILE`, `-o FILE` | Write command output to file |
| `--datadir DIR` | Data directory for JSON reads/writes (takes precedence over `TD_DATA_DIR`). If omitted and `TD_DATA_DIR` is unset: use `/data` when present; otherwise create/use `./data` under the current run directory. |

---

## Logging and Secret Redaction

`TD_DEBUG_LEVEL` accepts `DEBUG`, `INFO`, `WARNING`, or `ERROR`, ignoring case
and surrounding whitespace. The effective level is `--debug`/`-d`, then
`--verbose`/`-v`, then `TD_DEBUG_LEVEL`, then INFO. If both CLI switches are
present, `--debug` wins. An invalid environment value exits with usage status
2 only when neither CLI level switch overrides it; help-only invocations do
not validate it.

For example:

```bash
TD_DEBUG_LEVEL=' debug ' PYTHONPATH=src python3 -m td_cli --datadir ./data otbr-restapi devices list
```

DEBUG can include HTTP traffic, response details, and `ot-ctl` diagnostics.
Thread Network Key and PSKc values are redacted by default, including REST
success/error bodies, captured child output, and active-dataset stdout. The
explicit `--log-thread-secrets` option disables redaction only for OTBR REST
DEBUG response-body logs; it never changes stdout or saved snapshots. Use it
only when the process log destination, access, and retention are controlled.

## Command Summary

| Command | Description |
|---|---|
| `otbr-cli` | Scan OTBR CLI commands |
| `otbr-restapi` | Query OTBR REST API commands |
| `ha-matter-ws` | Collect commissioned-node and native Thread snapshots or run an explicit Matter-node diagnostic |
| `mdns` | Scan Thread-related mDNS scopes |
| `process-eve` | Parse and enhance an Eve Thread layout file |
| `health` | Process, inspect, or purge health history |
| `system` | Create or restore data-directory backups or run a bounded host ping |
| `source-probe` | Run a fresh live readiness probe for one supported collector source |
| `unify-dataset` | Materialize a declared source-primary product using cached inputs only |
| `merge-dataset` (`merge-data`) | Merge Thread (otbr-cli, otbr-restapi, eve, mdns) sources into one cache file; `merge-data` is a compatibility alias |
| `merge-extaddr` | Read or upsert one device label, or bulk-merge missing extaddr entries into the static map |

---

## Commands Usage

### `source-probe`

```bash
PYTHONPATH=src python3 -m td_cli source-probe --source otbr-cli --json
```

Supported sources are `otbr-cli`, `otbr-restapi`, and `ha-matter-ws`. This
explicit live-only command reuses the bounded source capability probes, but
does not inspect cached files, reuse earlier probe results, or read/write the
data directory. The dashboard capabilities endpoint remains cache-first:
its `cached` state does not establish live reachability.

| Exit status | Meaning | JSON state |
|---|---|---|
| 0 | Probe succeeded; attempt collection | `live` |
| 1 | Source unavailable or response unusable; skip collection | `probe-failed` |
| 2 | Invalid configuration, usage, or probe execution error | `probe-error` for completed error reports; usage errors print help to stderr |

`--json` writes one result to stdout without CLI banners; logging stays on
stderr. Usage errors and unexpected dispatcher failures may emit only stderr
and status 2. For example:

```json
{"source":"otbr-cli","state":"probe-failed","probe":{"state":"failed","reason":"docker-unavailable"}}
```

Branch on the exit status rather than grepping output. The scripts log the
JSON directly for diagnostics; consumers can extract a failed probe's reason
with `jq -er '.probe.reason'`. Stable failure reasons include `unreachable`,
`docker-unavailable`, `executable-unavailable`, `command-failed`, and
`invalid-response`; errors use `invalid-configuration` or
`probe-execution-error`. Preflights reject invalid configured ports instead
of silently falling back to defaults. `TD_OTBR_CONTAINER_USE` must be `0` or
`1`, and a configured container name must not be blank when container use
is enabled. Configuration/probe error logs omit endpoint and exception values
that might contain credentials.

These are readiness checks, not mesh-health checks or guarantees that every
collection command will succeed. CLI checks `ot-ctl state` (including
`disabled`/`detached`); REST reads node state; HA Matter opens a WebSocket and
validates its server-info handshake. They do not run diagnostics or mDNS
discovery. mDNS and system have no equivalent endpoint preflight and are not
accepted sources.

The local full and quick collection scripts probe each supported source once,
immediately before its collection block. Unavailable sources are skipped;
configuration/execution errors are reported separately. Both retain cached
snapshots, continue with later sources, and always attempt mDNS normally.
REST still verifies the active dataset's Extended PAN ID before collecting
other REST snapshots. A collector failure is logged and recorded even after
a successful preflight; a later successful command cannot erase it.
Final per-source summaries distinguish `collected`, `skipped`, and `failed`.

Skipped/failed collection does not prevent the existing cache-only Unified
and health stages from using retained evidence under their `--allow-partial`
policy. Their success does not mean skipped sources were refreshed. The final
script status is 1 for unavailable/skipped sources, collection failures, or
Unified/health failures, and 2 for preflight errors (which take precedence).
Final elapsed-time output and the full script's tabular exports are retained.

#### Collection script modes

The [full collection script](../script/td-fetch.sh) owns both collection modes:

```bash
script/td-fetch.sh          # Full collection (default)
script/td-fetch.sh --quick  # Reduced collection
script/td-fetch.sh --help   # Help only; no activation, probes, or collection
```

The [quick compatibility script](../script/td-fetch-quick.sh) delegates to
`td-fetch.sh --quick` using `exec`, forwarding any arguments and preserving
the exit status. Existing quick-script cron jobs can continue unchanged.
Unknown arguments exit with status 2 before environment activation or probes.

| Operation | Full mode | Quick mode |
|---|---|---|
| CLI meshdiag neighbor, child-table, and child-IP tables | Collect | Skip |
| CLI `networkdiag fetch-all` | Existing full options | Add `-cno` / `--children-no` |
| REST diagnostics and mesh-diagnostics `fetch-all` | Collect | Skip |
| Final tabular exports | Produce | Skip |
| HA Matter, mDNS, source preflights, merge, Unified, and health | Shared pipeline | Shared pipeline |

Both modes use the full script's existing repository-local data-directory
setup, network-identity guard, failure reporting, and retained-cache policy.

### `unify-dataset`

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data unify-dataset \
  --dataset otbr_cli_unified --allow-partial --json
```

Implemented targets: `otbr_cli_unified`, `otbr_restapi_unified`,
`ha_matter_ws_unified`, `mdns_unified`, and `multi_source_unified`.
Use `--dataset all` to build all five, in the order listed above. The
Multi-source build reuses the already prepared source primaries when unchanged.
`--allow-partial` applies to every target. In `all` mode, `--network` applies
to the Thread source primaries and Multi-source, not the standalone mDNS service
inventory, matching Multi-source's dependency handling. `--json` returns an
array of normal per-dataset summaries for `all`, retaining the single-object
result for an individual target. Human-readable output has one line per target.
The first failure stops the command with exit status 1 and no summary output;
earlier successful builds remain committed rather than being rolled back.
All five are selectable source primaries; fast defaults remain unchanged.
Retirement of overlapping selectors is coverage-gated; see the
[current rollout limits](../README.md#cache-only-unified-materialization).
CLI, REST, HA Matter and Multi-source have dedicated qualified health profiles;
mDNS remains enrichment-only and health-ineligible. Building does not process
health: request `health process-dataset --dataset DATASET_ID` explicitly after building.
Health verifies the bound original cached inputs; stale/missing originals need
an explicit cache-only rebuild, not a live refresh. Partial/degraded originals
do not become fresh complete collections. See
[Unified qualification and retained evidence](thread_network_health.md#unified-health-qualification).
This does not change legacy collector or merge
commands, fast defaults, or existing health profiles.

The local full and quick collection scripts build the four source primaries,
then build Multi-source once only if all four commands succeed. Health runs
only after successful Unified materialization. A failed Unified or health
command makes the script exit nonzero, while final elapsed-time output and
the full script's tabular exports are still produced.

Multi-source prepares/reuses the four catalog-owned source-primary generations
once under the outer build lock. It verifies reports, companions and original
raw inputs, then replays only their admitted raw observations through the same
normalizers/merge policies so an aggregate filename never supplies a rank.
It preserves scoped Thread devices, distinct Matter fabrics, non-Thread members
and uncorrelated services. Native links are rebound to final committed row IDs.
An operational Matter or HAP UDP (`_hap._udp.local.`) mDNS advertisement with
one matching Thread-device OMR address is embedded in the device's `mdnsRecords`
array. Without an explicit service OMR field, usable IPv6 addresses from
`serviceInfo.addressesParsed` and `serviceInfo.ipv6Addresses` are compared against
observed device OMRs. Exactly one device must match across all advertised
addresses; explicit OMR evidence takes precedence. The array preserves
individual fabric/node identities, capture data, original scope and lineage;
it never overwrites the device's identity or Matter fields. Invalid/unspecified,
multicast, link-local or loopback addresses cannot correlate services. Conflicting
addresses/scopes or multiple device candidates retain standalone service rows.
Genuine relationship-only placeholders cannot receive advertisements. Accepted
device observations clear that marker without modifying the original evidence.
Assembly-v8 applies these corrections on an explicit build, including when raw
inputs are unchanged; coherent v2-v7 generations remain readable.
Other source-primary recipes are unchanged; mDNS Unified has no Thread inventory
and groups services sharing a normalized usable OMR address within exactly the
same observed network scope. Every complete advertisement, fabric/node identity,
capture time and source lineage remains in `mdnsRecords`, without flattening
service-specific fields into the summary. Conflicting extended addresses,
unknown versus known scopes and invalid/unspecified/multicast/link-local/loopback
addresses remain separate. Multi-source still consumes the original services
independently. See the [merge contract](merge_thread_device_info.md).
Known mismatched sources are excluded with reasons; without four complete
sources, publication needs `--allow-partial`. No usable source is an error,
including when an older output remains on disk.

The opt-in catalog group can also be requested with
`merge-dataset --include-groups unified [--allow-partial]`. It dispatches the same
safe composer and fixed Unified artifacts, never the legacy merged output.
It cannot be combined with other groups, arbitrary files/output overrides or
legacy merge-policy options. Use `unify-dataset` for observed network selection.
The legacy default `full` group is unchanged.

HA requires its commissioned-device inventory, derived topology, native Border
Routers and native network topology. Optional diagnostics/dashboard projections
enrich these inputs; they never make a missing inventory complete. Original HA
outcomes are checked for status, counts, capture association and observed scope;
their gaps degrade evidence without hiding usable rows. A malformed present
outcome still aborts publication. Native graph collection/discovery time stays
distinct from wrapper read/build time, and raw-file mtime fallback is explicitly
degraded evidence. Safe identity is emitted only for one unambiguous observed
network (or an explicit observed selection). Non-Thread rows remain unscoped.
Native link endpoints bind to committed row IDs; unresolved/ambiguous endpoints
remain explicit coverage/conflicts, never arbitrary connections.

| Option | Meaning |
| --- | --- |
| `--dataset ID` | One canonical Unified target; no aliases or arbitrary recipes |
| `--network extpan:0123456789abcdef` | Select an observed, nonzero, lowercase Extended PAN ID; never assigns scope to unknown rows |
| `--allow-partial` | Permit usable inspection data with missing required source/network coverage |
| `--json` | Emit one summary object, including materialization/health state, generation, artifacts, row/relationship-entry counts, coverage, and no-op state |

No live, refresh, host, retry, arbitrary-input, output-override, or
Thread-secret flags are accepted. Logs go to stderr. Exit status is 0 for
published/unchanged complete or explicitly permitted partial results, 2 for
invalid arguments, and 1 for input/identity/publication failures. A successful
partial build is not a completeness or health-eligibility claim.
`healthState` describes evidence readiness, not a network-health assessment
or catalog health eligibility.

Rows remain arrays. Reports bind every row, network, identity and outcome
artifact; original source names/times and per-record/field lineage remain in
the report. Raw-file mtime fallback is explicit. Missing optional inputs are
reported; malformed present optional inputs fail. Unchanged evidence preserves
all output bytes and mtimes. A directory-wide advisory lock serializes separate
CLI/server builds. Report-last publication retains recovery copies; only an
explicit subsequent build recovers an interrupted generation. Cache Only and
normal reads never repair it.
`linkCount` counts canonical relationship entries (including Route64 and
child/neighbor tables), not deduplicated rendered canvas edges.

### `otbr-cli`

```text
td_cli otbr-cli {thread-network-info,router-table,bbr,meshdiag,networkdiag,device,topology} ...
```

`otbr-cli topology` runs seven steps in order: thread network info, router
table, meshdiag topology, networkdiag multicast-network, networkdiag fetch-all,
meshdiag router-neighbor tables, and meshdiag child tables. It attempts every
step and returns the first non-zero step result.

### `otbr-cli device`

```text
td_cli otbr-cli device ping IPV6 [--source IPV6] [--size BYTES] [--count COUNT]
                           [--interval SECONDS] [--hop-limit HOPS] [--timeout SECONDS]
                           [--allow-sed] [--json]
td_cli otbr-cli device reset-counters IPV6 --counters {mac,mle,both} --confirm [--json]
```

These are explicit active operations and never run during collection, Sync, or
`health process-dataset`. Both accept only unicast IPv6 addresses without zone
identifiers. Ping is blocking and bounded below the 30-second OTBR command
ceiling; omitted values use documented positional defaults. `--allow-sed`
acknowledges active traffic to a sleepy end device.

Counter reset is destructive. It maps `mac`, `mle`, and `both` exactly to TLVs
`9`, `34`, and `9 34`. Terminal `Done` means OTBR accepted the request for
transmission; it does not prove the remote device applied the reset. A response
that reports unsupported TLVs fails without fallback.

### `otbr-restapi`

```text
td_cli otbr-restapi [global-forwarded-options] {download,node,devices,diagnostics,actions,mesh-diagnostics,topology} ...
```

### `ha-matter-ws`

```text
td_cli ha-matter-ws [source-options] {server-info,device,devices,thread,network-topology,diagnostics,mesh-diagnostics,topology,dashboard,all} ...
```

Source options include `--host`, `--port`, `--uri`, `--connect-timeout`,
`--request-timeout`, `--settle-timeout`, `--output`, and `--no-progress`.
Host and port default to `TD_HA_MATTER_WS_HOST` and `TD_HA_MATTER_WS_PORT`, then
`localhost` and `5580`; `--host`/`--port` override those values, and `--uri`
overrides the complete endpoint. `devices`, `diagnostics`, and `mesh-diagnostics`
provide `get` and `fetch-all` commands; `devices` also provides `list`.
`topology` writes the canonical topology snapshot, while `all` performs one
inventory transaction and writes every fixed snapshot plus the collection
outcome. `dashboard` writes the dashboard data bundle. `--output` applies only
to leaf commands.

`device ping` is a separate active diagnostic against one commissioned Matter
node; it is not run as part of snapshot collection:

```text
td_cli ha-matter-ws device ping --node-id NODE_ID [--attempts N]
```

The node ID is required and attempts default to one. See the
[web-server data-flow guide](codebase_webpage_web_server_data_flow.md#device-diagnostics)
for the dashboard's separately gated device-action API.

Native Thread network products are explicit, schema-gated commands and are not
included in `all`:

```text
td_cli ha-matter-ws thread border-routers
td_cli ha-matter-ws thread diagnostics list
td_cli ha-matter-ws thread diagnostics get --ext-pan-id HEX [--force]
  [--collection-timeout SECONDS]
td_cli ha-matter-ws network-topology [--refresh]
  [--refresh-timeout SECONDS]
```

`thread border-routers` saves the passive mDNS-discovered Border Router
inventory to `td-ha-matter-ws-thread-border-routers.json`, with its outcome in
`td-ha-matter-ws-thread-border-routers.outcome.json`. `thread diagnostics list`
saves Matter Server's immediately returned diagnostic cache to
`td-ha-matter-ws-thread-diagnostics.json`, with its outcome in
`td-ha-matter-ws-thread-diagnostics.outcome.json`, and then closes the one-shot
connection. Issuing the list command also starts Matter Server's background
refresh; the saved wrapper and outcome therefore report
`backgroundRefreshStarted=true`, and batch freshness comes from each upstream
`collectedAt` value rather than the file write time. Use the saved JSON file for
a side-effect-free cache read.

`thread diagnostics get` collects one Extended PAN ID, normalized to lowercase,
and follows matching `thread_diagnostics_updated` events until the batch is
complete, terminal-partial, or the total deadline expires. The default
`--collection-timeout` is 45 seconds and includes the request, progressive
events, validation, and connection close. Transient and terminal partials are
saved to `td-ha-matter-ws-thread-diagnostics.partial.json`; only a complete
batch replaces `td-ha-matter-ws-thread-diagnostics.json`. A complete result
removes the partial checkpoint. `--force` asks Matter Server to replace its
current per-network collection and can create additional Thread network load;
avoid concurrent forced invocations for the same network.

`network-topology` saves Matter Server's native schema-13 graph to
`td-ha-matter-ws-network-topology.json`, with its outcome in
`td-ha-matter-ws-network-topology.outcome.json`. It is separate from Hobat's
canonical `topology` command and is not included in `all`. By default it sends
`refresh=false` and uses Matter Server's current attribute cache. `--refresh`
explicitly re-reads diagnostics from online Matter nodes before rebuilding the
graph and can create radio and device load; its default `--refresh-timeout` is
60 seconds. The one-shot command uses the correlated response and does not wait
for `network_topology_updated` events.

Normal output excludes Matter credentials. Collection is read-only and limited
to nodes commissioned to the connected controller. Missing diagnostics on an
unavailable or non-Thread Matter node are not treated as zero values.

### `mdns`

```text
td_cli mdns [--browse-timeout SECONDS] [--ext-pan-id ID] [--haptcp] [--write-scope-snapshots] [--mattertcpsupported] [SCOPE]
```

The owning mDNS parser uses a 3-second idle timeout unless
`TD_MDNS_BROWSE_TIMEOUT` or `--browse-timeout` overrides it. `--haptcp` adds
`_hap._tcp.local.` for `thread` or `hap`; `--mattertcpsupported` includes
`_matter._tcp` records whose `T=1` TXT value reports TCP support.
`--ext-pan-id` supplies an operator identity only when the selected scope has no
observed MeshCoP Extended PAN ID. It also works on
`td_cli otbr-cli thread-network-info --ext-pan-id ID`; an observed value wins
and a disagreement is logged. The `TD_EXT_PAN_ID` environment fallback applies
only when writing collector scopes; operator values never select the merge
output network. IDs accept 16 hex digits,
`0x`-prefixed or byte-separated hex, or exact decimal text. Use strings for
large IDs in JavaScript; unsafe numeric values lose precision.

`--write-scope-snapshots` writes the `br`, `hap`, and `matter` snapshots from
the same records collected by a `thread` browse.

Final collector snapshots have sibling `.network.json` files containing
provenance and the snapshot SHA-256. Merge excludes known cross-instance and
digest-mismatched inputs, treats missing sidecars as unknown instance, and
reports exclusions in the merge report. The merged record file remains an array.

### `process-eve`

```text
td_cli process-eve ...
```

### `health`

```text
td_cli health process-dataset --dataset DATASET [--allow-partial] [--dry-run] [--json]
                              [--export-latest [FILE]]
td_cli health compare --before-assessment ID --after-assessment ID [--dry-run] [--json]
td_cli health migrate (--check | --apply) [--json]
td_cli health migrate-history --dataset all|DATASET [--network NETWORK_ID]
                              [--policy-config-dir DIR] [--allow-policy-change]
                              [--dry-run] [--backup-output DIRECTORY] [--yes] [--json]
td_cli health purge [--keep-days DAYS] [--dry-run] [--yes] [--json]
td_cli health purge-all [--dry-run] [--yes] [--json]
td_cli health purge-by-device --device EXTADDR [--network NETWORK_ID]
                              [--dry-run] [--yes] [--json]
```

`process-dataset` assesses approved cached snapshots without starting
collection. `compare` compares two stored assessments. `migrate-history`
replays validated retained evidence after an operator-managed backup; run it
only in a health-writer maintenance window. The processing command also
supports roster administration and policy options; see
[Thread Network Health](thread_network_health.md) for its full contract and
examples.

`health migrate --check` reports the schema-only migration plan without
writing. `--apply` applies supported schema operations using a verified
SQLite-only recovery copy under `<datadir>/.migration-backups/`; writable store
startup can apply the same online migrations automatically. Schema migration
does not replay history. Recovery copies are excluded from directory backups
and preserved by restore.

Roster writes are network-scoped. `--roster-label` without `--roster-state`
preserves the existing designation and monitoring epoch. Setting
`--roster-state expected` explicitly reactivates a non-Expected device and
starts a fresh absence-monitoring epoch; equal label/state updates are no-ops.
Importing the static label map is additive: it does not clear
Intentionally Offline or Retired designations. Retired remains retained until
explicitly returned to Expected. The dashboard exposes the same confirmed
per-device lifecycle transitions through `PATCH /api/health/roster/{device_id}`;
that mutation route is not authenticated, so protect it with the same trusted
network or authenticated reverse-proxy boundary as other API mutations.

Age purge defaults to 30 retained days and uses an exclusive UTC cutoff.
`purge-all` removes health-domain records and roster entries but preserves the
shared database, migrations, and non-health tables. Per-device purge preserves
shared observations but invalidates assessments derived from affected
observations. Purge does not remove identities from collector snapshots,
exports, or existing backups.

### `system database repack`

```text
td_cli [--datadir DIRECTORY] system database repack
```

Rebuilds `hobat_v1.db` in the effective data directory with SQLite `VACUUM;`,
reclaiming unused pages without changing stored records or the schema. The
database must already exist. Repacking requires exclusive database access; if
another process is using it, stop that process and retry.

### `system backups`

```text
td_cli system backups create --output DIRECTORY [--json]
td_cli system backups restore --input BACKUP [--yes] [--json]
```

Create writes a versioned, checksummed copy of the complete effective data
directory and snapshots `hobat_v1.db` through SQLite's backup API. The output
must not already exist or be inside the active data directory. Restore requires
confirmation, validates checksums and database integrity, stages the complete
replacement, and refuses an active database writer. Stop the web server and all
writers before restore. Backups are unredacted and can contain credentials.

### `system device ping`

```text
td_cli system device ping --address IP [--family {auto,ipv4,ipv6}]
                           [--attempts N] [--timeout SECONDS]
                           [--deadline SECONDS]
```

This runs a bounded host ping to a literal IP address. It is separate from
OTBR or Matter device actions.

### `merge-dataset`

```text
td_cli {merge-dataset,merge-data} ...
```

### `merge-extaddr`

```text
td_cli merge-extaddr [--read-extaddr EXTADDR | --update-extaddr EXTADDR]
                        [--device-label DEVICE_LABEL] [bulk-merge-options]
```

Single-record operations use the configured data directory's
`td-static-extaddr-device-label.json`:

```bash
# Read one mapping without writing.
PYTHONPATH=src python3 -m td_cli --datadir ./data \
  merge-extaddr --read-extaddr 4e866ce96501b9ed

# Update an existing mapping or insert it when absent.
PYTHONPATH=src python3 -m td_cli --datadir ./data \
  merge-extaddr --update-extaddr 4e866ce96501b9ed \
  --device-label "Office Sensor"
```

Read success writes one JSON object to stdout:

```json
{"deviceLabel": "Office Sensor", "extAddress": "4e866ce96501b9ed"}
```

Upsert success adds an `operation` field:

```json
{"deviceLabel": "Office Sensor", "extAddress": "4e866ce96501b9ed", "operation": "updated"}
```

`operation` is `inserted` for a new mapping and `updated` for an existing one.
It is response metadata and is not persisted. ExtAddresses are normalized to
lowercase. Upsert preserves unrelated records and fields, sorts the map, and
atomically replaces the file. If the map is missing, upsert creates it;
single-record read returns exit code `4` instead.

Single-record exit codes:

| Code | Meaning |
|---|---|
| `0` | Read or upsert succeeded |
| `2` | Invalid option combination or missing required option |
| `3` | File access or atomic-write failure |
| `4` | Static map is missing during read |
| `5` | Invalid extAddress, label, JSON shape, map record, or duplicate normalized extAddress |
| `6` | Valid extAddress is not present during read |

Labels allow Unicode, are trimmed, must contain 1–128 characters, and cannot
contain control characters. ExtAddress must contain exactly 16 hexadecimal
characters. Blank labels do not delete mappings.

---

## `otbr-restapi` Summary

`td_cli otbr-restapi` forwards to OTBR REST API tooling:

- `download` routes to `otbr_restapi_download.py`
- `node`, `devices`, `diagnostics`, `actions`, `mesh-diagnostics`, `topology` route to `otbr_restapi_cli.py`

### Forwarded Global Options

These options must be placed after `otbr-restapi` and before its subcommand.

| Option | Description |
|---|---|
| `--host HOST` | OTBR REST API host |
| `--port PORT` | OTBR REST API port |
| `--base-url URL` | Full base URL override |
| `--timeout SECS` | HTTP request timeout |
| `--accept MIME` | Default Accept header |
| `--raw` | Return raw API envelopes |
| `--poll-interval FLOAT` | Seconds between action polls |
| `--poll-timeout FLOAT` | Max seconds to wait for action completion |
| `--no-progress` | Suppress per-device progress output |
| `--no-auto-output` | Disable automatic output file naming |
| `--lab` | Allow experimental `otbr-restapi` mutating commands (`node state set`, `node dataset active set`, `actions enqueue add-thread-device`, `actions enqueue reset-network-diag-counter`) |

### Commands and Subcommands

| Command | Subcommands | Purpose |
|---|---|---|
| `download` | *(none)* | Download OTBR REST API endpoint snapshots to JSON files |
| `node` | `get`, `state get`, `state set`, `dataset active get`, `dataset active set` | Read/mutate local OTBR node and active dataset |
| `devices` | `list`, `get`, `fetch` | List, read, or refresh device collection |
| `diagnostics` | `list`, `get`, `fetch`, `fetch-all` | Read or fetch network diagnostics |
| `actions` | `list`, `get`, `enqueue add-thread-device`, `enqueue get-network-diagnostic`, `enqueue reset-network-diag-counter`, `enqueue get-energy-scan`, `enqueue update-device-collection` | Inspect and enqueue OTBR action tasks |
| `mesh-diagnostics` | `children`, `child-ipv6`, `router-neighbors`, `fetch`, `fetch-all` | Fetch mesh-diagnostic TLV datasets |
| `topology` | *(none)* | Run full sweep: devices fetch + diagnostics fetch-all + mesh-diagnostics fetch-all |

`otbr-restapi node dataset active get` saves JSON to `td-otbr-restapi-dataset-active.json`
in the data directory by default, along with its network identity sidecar. Use
`--no-auto-output` to print it without saving; `get --text` does not auto-save.

---

## Data Directory Behavior

Data directory resolution precedence:

1. `--datadir` CLI argument
2. `TD_DATA_DIR` environment variable
3. Defaults (`/data` when present, otherwise `./data` under the current run directory)

When `TD_DATA_DIR` points at an empty or partially populated directory, command families now behave consistently:

| Family | Required local inputs | Optional local inputs | Missing-file behavior |
|---|---|---|---|
| `otbr-cli` | none | `td-static-extaddr-device-label.json` | Continue with no enrichment and log a warning |
| `mdns` | none | none | Continue unless the runtime browse/discovery itself fails |
| `process-eve` | `Eve Thread Network Layout.evethreadlayout` | none | Return `4` when the file is missing |
| `merge-extaddr` | Bulk merge: static map and merge input. Single read: static map. Single upsert: none. | none | Bulk/read return `4` for a missing required map; upsert creates a missing map atomically. |
| `merge-dataset` | `td-otbr-cli-thread-network-info.json` | `td-static-extaddr-device-label.json` and the merge source files listed in the plan | Return `4` when the seed is missing or no viable optional source loads |
| `otbr-restapi` | none, unless an explicit file argument is used by a mutating set command | command-dependent | Preserve OTBR REST API exit-code semantics |

Troubleshooting empty-data-dir runs:

- If `merge-dataset` returns `4`, confirm `td-otbr-cli-thread-network-info.json` exists and contains `prefix_omr_ipv6addr_prefix`.
- If an OTBR CLI command emits a warning about `td-static-extaddr-device-label.json`, the command still completed and wrote output without label enrichment.
- If `otbr-restapi` returns `4`, that still indicates an HTTP/action failure, not a local missing-file error.

### Final, checkpoint, and outcome files

Collectors atomically write mandatory final snapshots before reporting command
success. Long-running collectors may also replace a sibling `.partial.json`
checkpoint as records arrive. Checkpoints are transient progress data used by
the dashboard and never substitute for the final snapshot.

REST topology writes compatibility array snapshots plus
`td-otbr-restapi-diagnostics-fetch-all.outcome.json` and
`td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json`. Outcome sidecars
retain per-device status and partial-completion metadata without changing the
array shape consumed by the dashboard.

---

## Command Group Help Behavior

If you invoke a command group without the required deeper subcommand, `td_cli` prints contextual help for that group and exits successfully.

Examples:

- `td_cli otbr-cli meshdiag` prints `otbr-cli meshdiag` subcommand help
- `td_cli otbr-cli networkdiag` prints `otbr-cli networkdiag` subcommand help
- `td_cli otbr-restapi actions` prints `otbr-restapi actions` subcommand help
- `td_cli ha-matter-ws devices` prints `ha-matter-ws devices` subcommand help

---

## Subcommand Help Snapshots

### `otbr-cli`

```
usage: td_cli otbr-cli [-h]
                       {thread-network-info,router-table,bbr,meshdiag,networkdiag,device,topology}
                       ...

positional arguments:
  {thread-network-info,router-table,bbr,meshdiag,networkdiag,device,topology}
    thread-network-info         Scan and save thread network info
    router-table                Scan and save router table
    bbr                         Explicitly collect Primary Backbone Router
                                state
    meshdiag                    Scan and save mesh diagnostic data
    networkdiag                 Scan and save network diagnostic data
    device                      Run explicit active Thread device commands
    topology                    Run full otbr-cli topology sweep: thread-
                                network-info, router-table, meshdiag topology,
                                networkdiag multicast-network, networkdiag
                                fetch-all, meshdiag routerneighbortable,
                                meshdiag childtable

options:
  -h, --help                    show this help message and exit
```

### `otbr-cli topology`

```
usage: td_cli otbr-cli topology [-h]

options:
  -h, --help  show this help message and exit
```

### `otbr-cli meshdiag`

```
usage: td_cli otbr-cli meshdiag [-h]
                                {topology,routerneighbortable,childtable,childip6}
                                ...

positional arguments:
  {topology,routerneighbortable,childtable,childip6}
    topology            Scan meshdiag topology
    routerneighbortable
                        Scan meshdiag router-neighbour table
    childtable          Scan meshdiag child table
    childip6            Scan meshdiag child IPv6 addresses
```

### `otbr-cli networkdiag`

```
usage: td_cli otbr-cli networkdiag [-h] {fetch-all,multicast-network,multicast-neighbors} ...

positional arguments:
  {fetch-all,multicast-network,multicast-neighbors}
    fetch-all       Scan and poll networkdiag topology (unicast, router-by-router)
    multicast-network
                        Scan networkdiag topology via multicast to all Thread devices (ff03::1)
    multicast-neighbors
                        Scan networkdiag topology via multicast to one-hop neighbors (ff02::1)
```

### `otbr-cli networkdiag fetch-all`

```
usage: td_cli otbr-cli networkdiag fetch-all [-h] [-c | -cno]

options:
  -h, --help           show this help message and exit
  -c, --children       Expand and include child nodes in the topology map (default)
  -cno, --children-no  Do not expand child nodes in the topology map
```

### `mdns`

```
usage: td_cli mdns [-h] [--browse-timeout BROWSE_TIMEOUT]
                   [--ext-pan-id EXT_PAN_ID] [--haptcp]
                   [--write-scope-snapshots] [--mattertcpsupported]
                   [{thread,br,hap,matter}]

positional arguments:
  {thread,br,hap,matter}
                        mDNS scope to query; provide one to run a scan

options:
  -h, --help            show this help message and exit
  --browse-timeout BROWSE_TIMEOUT
                        Browse timeout in seconds forwarded to
                        mdns_thread_scopes
  --ext-pan-id EXT_PAN_ID
                        Extended PAN ID to use when mDNS cannot observe it
  --haptcp              Include _hap._tcp service scope
  --write-scope-snapshots
                        Write br, hap, and matter snapshots from one thread
                        browse
  --mattertcpsupported  Include _matterc._udp scope
```

### `otbr-restapi`

```
usage: td_cli otbr-restapi [-h] [--host HOST] [--port PORT] [--base-url URL]
                           [--timeout SECS] [--accept MIME] [--raw]
                           [--poll-interval FLOAT] [--poll-timeout FLOAT]
                           [--no-progress] [--no-auto-output]
                           [--log-thread-secrets] [--lab]
                           {download,node,devices,diagnostics,actions,mesh-diagnostics,topology}
                           ...

positional arguments:
  {download,node,devices,diagnostics,actions,mesh-diagnostics,topology}
    download            Download OTBR REST API endpoints to JSON files
    node                Read or mutate local OTBR node data
    devices             Read OTBR devices
    diagnostics         Read OTBR network diagnostics
    actions             Read or enqueue OTBR task actions
    mesh-diagnostics    Fetch mesh-diagnostic TLVs (children, childIpv6,
                        routerNeighbors)
    topology            Full topology sweep: devices fetch + diagnostics
                        fetch-all + mesh-diagnostics fetch-all

options:
  -h, --help            show this help message and exit
  --host HOST           OTBR REST API host (forwarded to otbr_restapi_cli)
  --port PORT           OTBR REST API port (forwarded to otbr_restapi_cli)
  --base-url URL        Override host/port with a full base URL (forwarded)
  --timeout SECS        HTTP request timeout in seconds (forwarded)
  --accept MIME         Default Accept header (forwarded)
  --raw                 Return raw API envelopes instead of flattened output
                        (forwarded)
  --poll-interval FLOAT
                        Seconds between action status polls (forwarded)
  --poll-timeout FLOAT  Max seconds to wait for an action to complete
                        (forwarded)
  --no-progress         Suppress per-device progress output (forwarded)
  --no-auto-output      Disable automatic output file naming (forwarded)
  --log-thread-secrets  Show Thread Network Key and PSKc in REST DEBUG
                        response-body logs
  --lab                 Allow experimental otbr-restapi mutating commands
                        (node state set, node dataset active set, actions
                        enqueue add-thread-device, actions enqueue reset-
                        network-diag-counter)
```

### `otbr-restapi node`

```
usage: python3 -m td_cli node [-h] {get,state,dataset} ...

positional arguments:
  {get,state,dataset}
    get                Get the OTBR node record from /api/node
    state              Get or set Thread state
    dataset            Operate on node datasets

options:
  -h, --help           show this help message and exit
```

### `otbr-restapi devices`

```
usage: python3 -m td_cli devices [-h] {list,get,fetch} ...

positional arguments:
  {list,get,fetch}
    list            List devices
    get             Get a device by device ID
    fetch           Trigger updateDeviceCollectionTask, wait for it, and
                    return the populated device list

options:
  -h, --help        show this help message and exit
```

### `otbr-restapi diagnostics`

```
usage: python3 -m td_cli diagnostics [-h] {list,get,fetch,fetch-all} ...

positional arguments:
  {list,get,fetch,fetch-all}
    list                List diagnostics
    get                 Get a diagnostic by diagnostics ID
    fetch               Enqueue getNetworkDiagnosticTask for a device, wait
                        for completion, and return the diagnostic result
    fetch-all           Fetch diagnostics for all known devices (or a given
                        list), one device at a time

options:
  -h, --help            show this help message and exit
```

### `otbr-restapi actions`

```
usage: python3 -m td_cli actions [-h] {list,get,enqueue} ...

positional arguments:
  {list,get,enqueue}
    list              List actions
    get               Get an action by action ID
    enqueue           Enqueue a new OTBR task

options:
  -h, --help          show this help message and exit
```

### `otbr-restapi mesh-diagnostics`

```
usage: python3 -m td_cli mesh-diagnostics [-h]
                                          {children,child-ipv6,router-neighbors,fetch,fetch-all} ...

positional arguments:
  {children,child-ipv6,router-neighbors,fetch,fetch-all}
    children            Fetch the child table for a device via otMeshDiag (TLV
                        29). Higher latency than standard diagnostic TLVs.
    child-ipv6          Fetch child IPv6 addresses for a device via otMeshDiag
                        (TLV 30). Higher latency than standard diagnostic
                        TLVs.
    router-neighbors    Fetch router neighbor table for a device via
                        otMeshDiag (TLV 31). Higher latency than standard
                        diagnostic TLVs.
    fetch               Fetch a caller-specified subset of mesh-diagnostic
                        TLVs for a single device. Allowed types: children,
                        childIpv6Addresses, routerNeighbors.
    fetch-all           Fetch mesh diagnostics for all known devices (or a
                        given list), one device at a time.

options:
  -h, --help            show this help message and exit
```

### `otbr-restapi topology`

```
usage: python3 -m td_cli topology [-h]
                                  [--preset {recommended,full,minimal,basic}]
                                  [--skip-devices] [--skip-diagnostics]
                                  [--skip-mesh-diagnostics]
                                  [--no-update-devices]
                                  [--no-enrich-mac-counters] [--no-fallback]
                                  [--fallback-preset {medium,minimal,basic}]

options:
  -h, --help            show this help message and exit
  --preset {recommended,full,minimal,basic}
                        TLV preset for the diagnostics step (default:
                        recommended)
  --skip-devices        Skip Step 1 (device refresh via
                        updateDeviceCollectionTask)
  --skip-diagnostics    Skip Step 2 (network diagnostics fetch-all)
  --skip-mesh-diagnostics
                        Skip Step 3 (mesh diagnostics fetch-all)
  --no-update-devices   Skip updateDeviceCollectionTask before
                        diagnostics/mesh steps
  --no-enrich-mac-counters
                        Disable MAC counter enrichment on the diagnostics
                        result
  --no-fallback         Disable per-device TLV fallback retry on failure
  --fallback-preset {medium,minimal,basic}
                        TLV preset to retry with on per-device failure
                        (default: minimal)
```

### `process-eve`

```
usage: td_cli process-eve [-h]
```

### `merge-dataset`

```
usage: td_cli merge-dataset [-h]
```

### `merge-extaddr`

```
usage: td_cli merge-extaddr [-h] [--merge-mdns-br | --merge-topology-all]
                             [--read-extaddr EXTADDR | --update-extaddr EXTADDR]
                             [--device-label DEVICE_LABEL]
                             [--merge-input-file MERGE_INPUT_FILE]
                             [--merge_name_override] [--datadir DATADIR]

options:
  -h, --help            show this help message and exit
  --merge-mdns-br       Use td-mdns-scopes-br.json instead of the default
                        merge input file
  --merge-topology-all  Use td-merged-topology-all.json instead of the
                        default merge input file
  --read-extaddr EXTADDR
                        Read one deviceLabel by 16-digit extAddress as JSON
  --update-extaddr EXTADDR
                        Update or insert one deviceLabel by 16-digit
                        extAddress
  --device-label DEVICE_LABEL
                        Device label for --update-extaddr
  --merge-input-file MERGE_INPUT_FILE
                        Merge input file name (default:
                        td-otbr-cli-networkdiag-fetch-all.json)
  --merge_name_override
                        If set, replace static Unknown device_label values
                        with merge input name for matching extaddr entries
  --datadir DATADIR     Data directory for JSON reads/writes (takes precedence
                        over TD_DATA_DIR)
```
