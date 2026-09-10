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
the displayed column set. The **Categories** selector immediately before it is
derived from `DEVICE_DETAILS_SECTIONS`: **All** restores the default table
column set exactly, while another category shows the available `identity-list`
fields followed by its own available registry fields. Fields use registry
order, canonical preferred names, and appear only once. Changing category
preserves rows, search, sorting, and the selected device and its detail panel.

Selecting a topology node or table row publishes `tdash:device-selected`.
Details, Device Settings, and Device Insights consume that shared selection.
Details sections and field bindings come from `DEVICE_DETAILS_SECTIONS`; section
containers are declared in `tdash.html`.

### Matter Device Details

The **Matter** section is immediately before **MDNS**. It is populated from the
selected HA Matter WebSocket record and does not trigger collection. A field is
shown only when its source value is present; `null`, missing, and unsupported
attributes do not create placeholder rows. Selecting another topology node or
table row replaces the section with that record's available values; clearing the
selection clears the section.

| Source field | Display label | Selection behavior |
|---|---|---|
| `matter.deviceLabel` | `matter.deviceLabel` | Controller-provided Matter node label; separate from the operator-overridable `deviceLabel` in Keys. |
| `matter.nodeId` | `matter.nodeId` | Decimal Matter node ID for the selected record. |
| `matter.matterId` | `matter.matterId` | Uppercase hexadecimal compressed-fabric/node identifier for the selected record. |
| `matter.fabricId`, `matter.compressedFabricId`, `matter.fabricIndex` | Corresponding field name | Matter fabric context for the selected record. |
| `matter.vendorName`, `matter.vendorId`, `matter.vendorModel`, `matter.productId`, `matter.productLabel` | Corresponding field name | Basic Information manufacturer and product attributes for the selected record. |
| `matter.vendorSwVersion`, `matter.vendorSwVersionNumber` | Corresponding field name | Matter software version string and numeric version for the selected record. |
| `matter.vendorHwVersion`, `matter.vendorHwVersionNumber` | Corresponding field name | Matter hardware version string and numeric version for the selected record. |
| `matter.available`, `matter.isBridge`, `matter.dateCommissioned` | Corresponding field name | HA Matter controller availability, bridge state, and commissioning timestamp for the selected record. No interview timestamp is currently collected. |
| `deviceTypes` | `deviceTypes` | Endpoint device types and revisions observed for the selected record. |
| `networkInterfaces` | `networkInterfaces` | Matter General Diagnostics interfaces, including reported IP addresses and MAC addresses. |
| `generalDiagnostics` | `generalDiagnostics` | Reported Matter General Diagnostics values for the selected record. |

Thread network name, Thread IPv6 addresses, and neighbor RSSI/LQI remain in
Network and Neighbors because they are Thread Network Diagnostics observations,
not Matter Basic Information fields.

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