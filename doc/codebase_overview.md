# Hobat Codebase Overview

## Architecture

Hobat is a cache-first system. Collectors write atomic snapshots into one data
directory; the web server serves those snapshots or invokes the CLI to refresh
known dynamic files; browser modules normalize, merge, adapt, filter, lay out,
and render the returned data.

```text
OTBR CLI / OTBR REST / HA Matter WS / mDNS / Eve
                 |
                 v
        Python collectors and parsers
                 |
                 v
       data/*.json snapshots and checkpoints
                 ^
                 |
Browser <---- aiohttp web server ----> td_cli subprocess
```

| Layer | Owners | Responsibility |
|---|---|---|
| Browser | `tdash.html`, `tdash.css`, `js/*.js` | Dataset selection, fetch sessions, merge/adaptation, filters, layouts, topology/table rendering |
| HTTP server | `td_webserver.py` | Static assets, data allowlist, cache policy, jobs, cancellation, device labels |
| CLI dispatcher | `td_cli.py` | Top-level command tree and command-family dispatch |
| Collectors | `otbr_cli_*.py`, `otbr_restapi_*.py`, `ha_matter_ws_*.py`, `mdns_*.py`, `eve_process.py` | Live collection, parsing, normalization, checkpoints, final snapshots |
| Processing | `merge_dataset.py`, `merge_extaddr_device_label_map.py`, `td_health_*.py` | Cross-source merge, label-map administration, and cache-only health assessment |
| Shared contracts | `td_const.py`, `td_device_fields.py`, `td_device_merge.py`, `td_record_merge.py`, `td_json_key_normalizer.py`, `util_*.py` | Filenames, fields, merge policies, data paths, network and subprocess helpers |
| Persistence | Effective data directory | Operator inputs, generated snapshots, and `td-health.db` observation history |

Runtime dependencies include `aiohttp`, `websockets`, and `zeroconf`. The browser
uses vendored vis-network and sortable table libraries.

## Python Modules

### Entry Points and Shared Contracts

| File | Responsibility |
|---|---|
| `td_cli.py` | Unified dispatcher for `otbr-cli`, `otbr-restapi`, `ha-matter-ws`, `mdns`, `process-eve`, `health`, `merge-dataset`/`merge-data`, and `merge-extaddr` |
| `td_webserver.py` | aiohttp application, file action registry, HTTP caching, background jobs, cancellation, and device-label API |
| `td_const.py` | Authoritative Python cache filenames, data-directory constants, and Thread multicast addresses |
| `td_device_fields.py` | Python field definitions, preferred names, aliases, identities, and placeholders |
| `td_device_merge.py` | Shared merge context, source ordering, and domain merge policy |
| `td_record_merge.py` | Record/object/array merge primitives, conflict and provenance handling |
| `td_json_key_normalizer.py` | Recursive conversion to preferred field names |

### OTBR CLI

| Files | Responsibility |
|---|---|
| `otbr_cli_thread_network_info.py` | Active dataset, mesh-local prefix, and favored OMR prefix |
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

### OTBR REST API

| File | Responsibility |
|---|---|
| `otbr_restapi_util.py` | Filesystem-free HTTP client, JSON:API flattening, retries, polling, and shared errors |
| `otbr_restapi_cli.py` | REST command parser, dispatch, stdout rendering, output resolution, and exit mapping |
| `otbr_restapi_node.py` | Node, state, and active-dataset commands |
| `otbr_restapi_devices.py` | Device list/get/fetch commands and device checkpoints |
| `otbr_restapi_diagnostics.py` | Diagnostic list/get/fetch/fetch-all, TLV fallback, progress, and checkpoints |
| `otbr_restapi_mesh_diagnostics.py` | Children, child IPv6, router-neighbor, and batch mesh diagnostics |
| `otbr_restapi_actions.py` | Action list/get/enqueue commands |
| `otbr_restapi_topology.py` | Composite devices, diagnostics, and mesh-diagnostics sweep |
| `otbr_restapi_download.py` | Fixed endpoint snapshot download |

Transport methods do not write files. Resource dispatchers or composite
workflows own command output because they know the command and resolved path.
Mutating action POSTs are not retried after an ambiguous response because the
OTBR action API has no idempotency key; idempotent reads use bounded retries.

### Home Assistant Matter WebSocket

| File | Responsibility |
|---|---|
| `ha_matter_ws_client.py`, `ha_matter_ws_contract.py` | Correlated WebSocket transport, handshake compatibility, and pinned Matter paths |
| `ha_matter_ws_extractor.py`, `ha_matter_ws_snapshots.py` | Matter node decoding, canonical records, coverage, and credential exclusion |
| `ha_matter_ws_topology.py` | Directional neighbor, child, route, and placeholder topology derivation |
| `ha_matter_ws_fetch_all.py`, `ha_matter_ws_cli.py` | One-snapshot orchestration, checkpoints, atomic files, outcome, and source CLI |

The source is read-only and controller-scoped. Its default URI is
`ws://localhost:5580/ws`; missing or unavailable node telemetry remains
explicitly absent. It does not replace OTBR network-wide collection.

### Other Sources and Processing

| Files | Responsibility |
|---|---|
| `mdns_thread_scopes.py`, `mdns_hap.py`, `mdns_matter.py`, `mdns_meshcop.py`, `mdns_thread_util.py` | Zeroconf discovery and source-specific service normalization |
| `eve_process.py` | Eve export parsing, identifier conversion, and topology enrichment |
| `merge_dataset.py` | Input selection, normalization, identity-aware merge, validation report, and merged snapshot |
| `merge_extaddr_device_label_map.py` | Bulk merge plus single-record read/upsert for the static label map |
| `extaddr_device_label_map.py` | Static label-map loading |
| `td_health_manifest.py`, `td-dataset-manifest.json` | Approved health dataset/profile contracts shared with browser registry metadata |
| `td_health_processor.py`, `td_health_evaluator.py` | Stable cached-file reads, safe normalization, completeness, and Python-owned verdicts |
| `td_health_observation_model.py`, `td_health_policy.py` | Frozen domain contracts and validated `snapshot-v1` policy |
| `td_health_sqlite.py`, `td_health_history.py` | Atomic observation history, current assessment, bounded retention, and explicit roster operations |
| `td_health_read.py`, `td_webserver.py` health routes | Query-only SQLite projections, assessment pinning, grouped findings, bounded history, and no-store HTTP responses |
| `util_data.py` | Data-directory resolution and atomic JSON/text writes |
| `util_network.py`, `util_convert.py`, `util_mac_counters.py` | Network, address conversion, and counter helpers |
| `profile_wrapper_td_cli.py`, `profile_wrapper_td_webserver.py` | Development profiling wrappers |

## Browser Modules

All files under `src/js/` are browser ES modules.
`tdash-health.js` fetches and renders stored Python verdicts for health-eligible
datasets. It does not contain health thresholds or reclassify evidence.

| File | Responsibility |
|---|---|
| `tdash-ui.js` | DOM event wiring, source/dataset controls, view dispatch, settings, and insights |
| `tdash-dataset-registry.js` | Seven source groups and selectable dataset definitions |
| `tdash-dataset.js` | Fetch sessions, cache controls, jobs, cancellation, checkpoints, and dataset assembly |
| `tdash-device-fields.js` | Browser field definitions, aliases, identities, transforms, and placeholders |
| `tdash-merge.js` | Browser merge strategies, source precedence, conflicts, and provenance |
| `tdash-utils.js` | Canonical identifiers, field normalization, payload normalization, and formatting |
| `tdash-adaptors.js` | Source-specific conversion to the topology adaptor contract |
| `tdash-adaptor-model.js` | Canonical device/relationship/detail model and validated emission |
| `tdash-topology-view-model.js` | Indexed topology state and pure filter/search visibility calculations |
| `tdash-topology-utils.js` | Node/edge helpers, indexes, styles, labels, and isolated-node anchors |
| `tdash-topology-renderer.js` | vis-network lifecycle, rendering, interaction, search highlights, and layout selection |
| `tdash-layouts.js` | Deterministic tree, ring/star, compact, hub-spoke, and hybrid seed layouts |
| `tdash-table-renderer.js` | Sortable table, column selection, formatting, and row selection |
| `tdash-filters.js` | Capability discovery and node/link/diagnostic predicates |
| `tdash-search.js` | Query parsing and record matching |
| `tdash-view-status.js` | Active-view status ownership and stale-status suppression |
| `tdash-constants.js` | Shared merge, filter, field, palette, details, table, and vis options |

The selectable source and dataset inventory is runtime data in
`tdash-dataset-registry.js`; documentation does not duplicate the complete list.

## Data and Identity Contracts

The data directory contains final snapshots, transient `.partial.json`
checkpoints, optional `.outcome.json` summaries, and operator-managed inputs.
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
- Device-label API responses use `Cache-Control: no-store`.

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