# Home Assistant Matter WebSocket Contract

This document records the protocol and Matter model baseline for the
`ha-matter-ws` collector. It is implementation evidence for Phase 0 of the
collector plan, not an operator command guide.

## Supported Protocol Range

The first-release baseline is the checked-in capture from
`matter-server/1.2.3 (matter.js/0.17.5-alpha.0-20260710-82b39217b)`, WebSocket
schema 12 with minimum schema 11. A read-only live check also passed against
`matter-server/1.3.3 (matter.js/0.17.7)` with the same schema range. The collector
accepts a server when these ranges overlap:

```text
server schema >= 11
server minimum supported schema <= 12
```

A newer server remains usable while it supports schema 12. A server whose minimum
has advanced beyond 12 is rejected before collection. The default endpoint is
`ws://localhost:5580/ws`.

The server sends an uncorrelated server-info object immediately after connection.
Commands and replies use:

```json
{"message_id": "request-id", "command": "get_nodes", "args": {}}
{"message_id": "request-id", "result": []}
{"message_id": "request-id", "error_code": 5, "details": "Node does not exist"}
```

Events are independent frames shaped as `{"event": "name", "data": ...}`.
`start_listening` both enables events and returns the initial node array. Response
selection must therefore use `message_id`, not frame order or result type.

## Matter Model Baseline

The immutable tables in `ha_matter_ws_contract.py` were reviewed against the
generated matter.js model on 2026-08-30:

- Descriptor cluster `0x001D`, revision 3.
- Basic Information cluster `0x0028`, revision 6.
- General Diagnostics cluster `0x0033`, revision 3.
- Thread Network Diagnostics cluster `0x0035`, revision 3.

The critical Thread paths are:

| Path | Meaning |
| --- | --- |
| `0/53/7` | NeighborTable |
| `0/53/8` | RouteTable |
| `0/53/9` | PartitionId |
| `0/53/63` | Local ExtAddress, revision 3 provisional field |
| `0/53/64` | Local Rloc16, revision 3 provisional field |

There is no standard ChildTable attribute in this cluster. A parent-child
relationship is derived later only from a NeighborTable entry with `IsChild=true`.
Collectors targeting an older cluster revision must tolerate absent local
ExtAddress and Rloc16 rather than infer them from another node.

General Diagnostics NetworkInterface fields `5` and `6` are separate IPv4 and
IPv6 address lists. Field `7` is the interface type; value `4` identifies Thread.

## Normalized Diagnostics Contract

The diagnostics snapshot contains only nodes that advertise Thread Network
Diagnostics in a Descriptor ServerList or expose a numeric `0/53/*` path. It
selects a Thread interface only when `Type` is `4` and HardwareAddress is a valid,
non-placeholder EUI-64. Wi-Fi/Ethernet addresses and neighbor identities are never
used as the reporting node's `extAddress`.

Matter TX/RX counters retain their standard lower-camel names under `macCounters`.
Role and attachment counters use their standard names under `mleCounters`, except
for these exact Hobat equivalents:

| Matter counter | Hobat field |
| --- | --- |
| `PartitionIdChangeCount` | `partIdChangesCount` |
| `BetterPartitionAttachAttemptCount` | `betterPartIdAttachAttemptsCount` |
| `ParentChangeCount` | `newParentCount` |

These values are cumulative. The collector does not calculate rates or ratios.
`diagnosticsDetail.threadNetworkDiagnostics` retains decoded standard scalar
attributes, `unknownAttributes` retains newer numeric paths, and `readErrors`
retains explicit per-path errors when supplied by the node snapshot.

`diagnosticCoverage.threadNetworkDiagnostics` reports a cluster state plus one
state per standard attribute. States are `clusterUnsupported`,
`attributeUnsupported`, `readError`, `null`, `implementedEmpty`, and `populated`.
An absent attribute is not converted to zero or an empty table. NeighborTable and
RouteTable remain directional raw observations; relationship derivation belongs
to the topology phase.

## Topology Relationship Contract

Each diagnostic record is one reporter. The topology builder resolves reporters
and targets by valid Thread `extAddress` first, then by network-scoped `rloc16`,
while retaining Matter identity. When local RLOC16 is absent, an address under the
reported mesh-local prefix is accepted only when its IID has the Thread RLOC form
`0000:00ff:fe00:XXXX`; `rloc16Provenance` records that source address.

NeighborTable emits one outbound `routerNeighbors` relationship per resolved
target. Entries with `isChild=true` also appear in `children`. RouteTable emits
`route.routeData`; explicitly unallocated entries are excluded, while allocated
entries with `linkEstablished=false` remain. RouterId alone never resolves an
endpoint.

Relationships retain `sourceId`, `targetId`, direction, and an `observations`
array containing the reporting Matter identity and original table entry. Exact
duplicates collapse, but differing directional or quality observations remain.
An extended-address/RLOC disagreement is retained under `identityConflicts`; the
valid extended address controls target selection.

The topology snapshot adds `relationshipOnly=true` placeholders for valid target
identities absent from commissioned inventory. These records have no Matter
identity. The mesh-diagnostics snapshot contains commissioned reporters only.
Per-reporter link, child, route, and link-quality totals are computed after all
relationships resolve, and final validation rejects duplicate node IDs or any
unresolved relationship endpoint. Reciprocal links are never synthesized.

## Evidence and Limits

Sanitized protocol fixtures cover the initial server-info frame, interleaved node
event, out-of-order command results, duplicate node snapshots, unavailable nodes,
command errors, and timeout/no-response behavior. A synthetic revision 3 Matter
fixture covers Thread attribute and structure IDs without pretending it is a live
capture.

The checked-in `data/td-matter-ws-devices-fetch-all.json` reports schema 12,
minimum schema 11, and a matter.js 0.17.5 alpha build, but contains no `0/53/*`
attributes. It validates the protocol baseline and non-Thread payload shape only.

On 2026-08-30, a read-only comparison against an available Thread Matter node on
the user-provided LAN server confirmed that attribute `7` has NeighborTableStruct
fields `0` through `13`, attribute `8` has RouteTableStruct fields `0` through
`9`, attribute `9` is numeric PartitionId, and ClusterRevision is `3`. The node's
cached attributes `63` and `64` were null and a targeted read omitted them. This
confirms that revision 3 defines those fields but does not guarantee usable local
identity values. The sanitized shape is retained in
`tests/fixtures/ha_matter_ws_live_thread_contract_schema12.json`; server address,
node ID, and telemetry values are intentionally excluded.

### Phase 7 Live Acceptance

On 2026-08-30, the read-only command matrix was run against Matter Server schema
12, minimum schema 11, `matter-server/1.3.3`, and `matter.js/0.17.7`. The server
address and device identities are intentionally omitted.

- `devices fetch-all`, `diagnostics fetch-all`, `mesh-diagnostics fetch-all`,
	`topology`, and `all` completed successfully in an isolated temporary data
	directory.
- The inventory retained 13 commissioned nodes: 11 Thread devices and two Wi-Fi
	Matter devices, including one unavailable Wi-Fi node.
- The normalized topology contained 31 nodes, 13 directional neighbor
	observations, and 30 route observations. No child observation was reported.
- All emitted extended addresses passed the 16-hex-digit EUI-64 check, and a scan
	of normalized finals found no credential-shaped keys or certificate material.
- A forced connection failure returned exit code 3 and left every previous valid
	final byte-identical.
- The checked-in `data/` hash was unchanged before and after live collection.

Cache-only browser acceptance exercised all four offered datasets on desktop and
mobile. Tables rendered two sanitized rows, topology rendered two nodes and one
link on a positive nonblank canvas, search reset restored the exact baseline,
document-level mobile overflow remained absent, and all data requests returned
HTTP 200 without console, page, request, or HTTP errors.

## Upstream Sources

- [matterjs-server WebSocket API](https://github.com/matter-js/matterjs-server/blob/main/docs/websockets_api.md)
- [matterjs-server protocol types](https://github.com/matter-js/matterjs-server/blob/main/packages/ws-client/src/models/model.ts)
- [Thread Network Diagnostics model](https://github.com/matter-js/matter.js/blob/main/packages/model/src/standard/elements/thread-network-diagnostics.element.ts)
- [General Diagnostics model](https://github.com/matter-js/matter.js/blob/main/packages/model/src/standard/elements/general-diagnostics.element.ts)
- [Descriptor model](https://github.com/matter-js/matter.js/blob/main/packages/model/src/standard/elements/descriptor.element.ts)
- [Basic Information model](https://github.com/matter-js/matter.js/blob/main/packages/model/src/standard/elements/basic-information.element.ts)