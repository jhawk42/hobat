# Dashboard UI Fields

The dashboard accepts source-specific records from OTBR CLI, OTBR REST, mDNS,
Eve, Thread Tools, and merged snapshots. Field availability depends on the
selected dataset.

## Field Authority

`src/js/tdash-device-fields.js` owns the browser's maintained field definitions,
preferred names, aliases, transforms, identity fields, and placeholders.
`src/js/tdash-constants.js` owns table priority and details-section metadata.
The Python counterpart is `src/td_device_fields.py`; tests enforce parity for
the shared contract.

Preferred output names are camelCase. Legacy and source-specific aliases remain
accepted during normalization. Important examples are:

| Preferred field | Accepted aliases |
|---|---|
| `extAddress` | `extaddr`, `extMacAddr`, `Extended MAC` |
| `omrIpv6Address` | `omrIpv6Addr`, `omr_ipv6_addr` |
| `rloc16` | `RLOC16` |
| `deviceLabel` | `device_label` |
| `threadVersion` | `thread_version` |
| `threadStackVersion` | `thread_stack_version` |
| `route` | `route64`, `route_data` |
| `childTable` | `router_child_table` |
| `routerNeighbors` | `router_neighbor_table` |

Transport envelope fields such as `data`, `attributes`, `relationships`,
`links`, `included`, and collection `meta` are not device fields.

## Field Groups

The maintained model covers these groups:

- Identity: `rloc16`, `extAddress`, `omrIpv6Address`, `eui`, `id`, `routerId`,
  `mlEidIid`, `deviceLabel`, and network identity fields.
- Role and mode: `role`, `type`, `mode.*`, `isLeader`, `isBorderRouter`,
  `isRouter`, and `isPrimaryBBR`.
- Network state: IPv6 addresses, `leaderData`, `connectivity`, routes, children,
  child tables, child IPv6 addresses, and router neighbors.
- Diagnostics: `macCounters`, `mleCounters`, `timeStatistics`, and derived
  totals/ratios.
- Source details: version, vendor, mDNS, Eve, state, and collection fields.
- Merge metadata: `_source_files` and `_merge_conflicts`.

Missing fields are omitted from details and capability-dependent controls.
Fields are not synthesized merely to fill every table column; defined
placeholders are used only where the normalization contract requires them.

## Table and Details

The table renderer discovers fields from the loaded rows, places priority
columns first, and formats nested values for inspection. **More Info** expands
the displayed column set.

Selecting a topology node or table row publishes `tdash:device-selected`.
Details, Device Settings, and Device Insights consume that shared selection.
Details sections and field bindings come from `DEVICE_DETAILS_SECTIONS`; section
containers are declared in `tdash.html`.

## Search

Normal search is case-insensitive and checks the curated
`SEARCH_TARGET_FIELDS` list, including identities, addresses, labels, roles,
versions, network state, status, and vendor name. Dot paths such as
`mode.device` are resolved normally.

Advanced search checks every top-level field and one level of nested object
values. Object and array values are stringified for substring matching.

## Filters and Insights

Node, link, and diagnostic options are capability-driven. The application scans
the current topology or rows and offers only filters supported by available
fields or relationship categories. Link filters are topology-only.

Diagnostic insights evaluate the selected normalized record. They are
informational and use the same diagnostic predicates as filtering where the
field shapes overlap.

See [Webpage, Web Server, and Data Flow](codebase_webpage_web_server_data_flow.md) and [Merge Thread Device Information](merge_thread_device_info.md).