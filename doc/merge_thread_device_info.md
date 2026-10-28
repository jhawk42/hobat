# Merge Thread Device Information

Hobat merges complementary OTBR CLI, OTBR REST, mDNS, Eve, label-map, and other
records into preferred camelCase device records. Python owns offline merged
snapshots; equivalent browser contracts support multi-file dashboard datasets.

## Ownership

| Concept | Python owner | Browser owner |
|---|---|---|
| Canonical field names and aliases | [td_device_fields.FIELD_DEFINITIONS](../src/td_device_fields.py) | [tdash-device-fields.js FIELD_DEFINITIONS](../src/js/tdash-device-fields.js) |
| Collector wire-format conversion | [td_json_key_normalizer.EXPLICIT_KEY_MAP](../src/td_json_key_normalizer.py) | Not applicable; collectors run in Python |
| Device identity keys | [td_device_fields.get_device_identity_keys](../src/td_device_fields.py) | [tdash-device-fields.js getDeviceIdentityKeys](../src/js/tdash-device-fields.js) |
| Network instance identity | [td_network_identity](../src/td_network_identity.py) | [tdash-device-fields.js canonicalExtPanId](../src/js/tdash-device-fields.js) |
| Dataset catalog | [td-dataset-manifest.json](../src/td-dataset-manifest.json) | Served `/api/catalog`, with [tdash-dataset-registry.js](../src/js/tdash-dataset-registry.js) fallback |
| Source and field authority | [td_source_authority](../src/td_source_authority.py) over the catalog | [tdash-source-authority.js](../src/js/tdash-source-authority.js) reads the catalog; [tdash-merge.js](../src/js/tdash-merge.js) uses source defaults |
| Value and conflict merge rules | [td_record_merge](../src/td_record_merge.py), [identity](../src/merge_policy_identity.py), [relationship](../src/merge_policy_relationship.py), [mDNS](../src/merge_policy_mdns.py) policies | [tdash-merge.js](../src/js/tdash-merge.js) |
| Derived device state | Not applicable; this projection is browser-only | [tdash-device-projection.js](../src/js/tdash-device-projection.js) |
| Adaptor intermediate model | Not applicable; adaptors are browser-only | [tdash-adaptor-model.js](../src/js/tdash-adaptor-model.js) |

Tests enforce shared preferred fields, aliases, identity keys, placeholders,
source precedence, conflicts, and idempotence across the two runtimes.

## Cache-only Four-primary Composition

The `multi_source_unified` recipe consumes exactly the four declared
CLI/REST/HA Matter/mDNS primary generations. Its opt-in `unified` merge group
dispatches [the Unified builder](../src/td_unified_dataset.py), not the legacy
aggregate-file merge; `full` retains its existing inputs and output.
Dependencies are prepared/reused once under one outer lock. Malformed present
evidence aborts; missing/excluded/partial sources require explicit partial
permission, and no usable source preserves the prior final with an error.

Authority is evaluated on verified **original observations**. The builder
replays each admitted raw input through its declared converter and the same
scoped canonical merge used for source primaries. Original filenames keep their
established precedence, tie ordering, conflict, partition and endpoint policies.
It does not assign a rank to a primary filename or treat a source-wide rank as
per-field lineage. Stable `recordSources` and `fieldSources` retain raw
filenames/record identities, including identity-keyed relationship item paths.
Conflicting losing evidence remains in merge metadata.

`read_generation(data_dir, entry, verify_inputs=True)` verifies committed
dependencies, their reports/companions and the current transitive raw evidence.
Multi-source reports expose `rawInputs` (the closed catalog allowlist with
roles/digests/scope/times/status) and generation-bound `rawInputsDigest`.
This is the reusable metadata boundary for the later health evidence view;
it embeds no complete raw snapshot and adds no health eligibility.
Display reads verify only the coherent committed product and do not repair
changed original caches. An explicit build alone refreshes derived products.

Mixed known networks stay separate without a selection; an explicit observed
network excludes mismatches without relabelling unknown records. A primary
sidecar never assigns all mDNS services or non-Thread Matter members a network.
Fabric identities remain distinct, service evidence is retained, and native
links resolve again against final committed row IDs. Rebuilding identical
evidence preserves artifact bytes/mtimes and original observation times.

REST diagnostic snapshots can contain several observations of one device with
different diagnostic UUIDs and creation times. Unified merges these observations
when they have a concrete extended address in the same scope, retaining every
original contributor and normal field conflicts. Diagnostic UUIDs are not device
identities. Same-file inventory collisions, diagnostics without an extended
address, conflicting addresses, and different Matter fabrics remain separate.
mDNS advertisements do not join devices merely through an advertised extended
address, except for the guarded MeshCoP association below.

Assembly contract `unified-assembly-v3` corrects diagnostic-observation merging.
An explicit cache-only build upgrades existing generations even when raw inputs
are unchanged; display reads still accept coherent `unified-assembly-v2`
generations without silently rebuilding them.

Assembly contract `unified-assembly-v4` additionally embeds operational Matter
mDNS services in a matching Thread device's `mdnsRecords` array. Matching uses
the current normalized IPv6 OMR address and requires exactly one device candidate
within any observed service scope, with no conflicting concrete extended address.
An unscoped service can enrich one unambiguous scoped device, but its embedded
`_networkInstance` remains unknown. Unspecified, multicast, link-local, loopback
and invalid addresses cannot establish a match. Multiple device/network/fabric
candidates, mismatched known scopes, non-Thread devices and unmatched services
stay separate. Assembly-v4 did not embed non-Matter services.

Assembly contract `unified-assembly-v5` extends the same guarded association to
HAP UDP (`_hap._udp.local.`), not HAP TCP or MeshCoP advertisements. It also
corrects stale `relationshipOnly` markers in the in-memory device merge: an
accepted non-mDNS device observation with a device identity clears the marker,
regardless of contribution order. Original contributor flags remain untouched;
placeholder-only observations and mDNS enrichment alone cannot clear it.
Genuine relationship-only placeholders remain ineligible association targets.
Explicit builds upgrade unchanged v2/v3/v4 generations; coherent older
generations remain readable without an implicit rebuild.

Assembly contract `unified-assembly-v6` also embeds MeshCoP
(`_meshcop._udp.local.`) advertisements by matching a concrete, normalized
16-digit extended address, without requiring an OMR address. Exactly one
non-placeholder Thread device must match within the advertisement's observed
network scope. Unknown service scope remains unknown; conflicting known scopes,
ambiguous network/fabric or same-file device identities, invalid/placeholder
addresses and unmatched services remain separate. The full advertisement is
retained in `mdnsRecords`, not flattened over authoritative device fields.
Standalone mDNS Unified remains a service inventory. Explicit cache-only builds
upgrade unchanged older generations; coherent v2/v3/v4/v5 products remain
readable without rebuilding on display.

Assembly contract `unified-assembly-v7` groups standalone mDNS Unified
advertisements sharing a normalized, usable OMR IPv6 address and exactly the
same observed network scope into one service-summary row. Every complete
deduplicated advertisement remains in `mdnsRecords`, including separate Matter
fabric/node identities, service types, capture times and original field lineage.
The summary exposes only the shared address, not one advertisement's fabric or
service fields as if they applied to all members. Different known networks,
unknown versus known scope, conflicting concrete extended addresses and
invalid/unspecified/multicast/link-local/loopback addresses do not group.
Singletons remain unchanged. This is a service-inventory grouping, not a Thread
device observation or health input. Multi-source still replays the original
advertisements independently, preserving its guarded device associations.
Explicit builds upgrade unchanged older generations; coherent v2-v6 products
remain readable without an implicit rebuild.

Assembly contract `unified-assembly-v8` also associates operational Matter and
HAP UDP advertisements when collection did not promote an OMR field. In the
absence of an explicit `omrIpv6Address`, the builder compares usable IPv6
addresses from `serviceInfo.addressesParsed` and `serviceInfo.ipv6Addresses`
against observed device OMR addresses. The combined set of matching devices
must contain exactly one device within the service scope; it never chooses the first match
from an ambiguous list. Explicit OMR evidence takes precedence, and the same
extended-address, network, non-Thread and relationship-only guards still apply.
IPv4, unspecified, multicast, link-local, loopback and malformed addresses cannot
establish a match. Complete original advertisements and nested address lineage
are retained without adding a guessed OMR or network scope to the service.
Standalone mDNS grouping still requires an observed OMR; a bare advertised
address is not independently promoted to a Thread identity. No collector or
undeclared prefix lookup is needed. Explicit builds upgrade unchanged older
generations; coherent v2-v7 products remain readable.

Each array item is the complete deduplicated service record, with its own
`_unifiedRecordId`, original scope, capture metadata, service properties and
fabric/node advertisement identity. Device fields and identities are unchanged.
`recordSources` includes every contributing original observation;
`fieldSources` binds `mdnsRecords` and each service-ID-keyed nested field to the
original source references, without assigning mDNS authority to device fields.
Device details show the array in the mDNS section, and normal search includes
embedded advertisement names, fabric/node identities and properties. Source-primary CLI/REST/HA
rows are unchanged; standalone mDNS Unified still represents service inventory.
Explicit builds upgrade existing v2/v3 generations; coherent v2/v3 generations
remain readable, and retained health still uses original evidence rather than
the embedded advertisements.

## Network Instance

An Extended PAN ID scopes a layer snapshot to one Thread network. The shared
[canonicalizer](../src/td_network_identity.py) accepts a nonzero 64-bit integer,
exact decimal text, or 16 hex digits (plain, `0x`-prefixed, or byte-separated)
and returns 16 lowercase hex digits. A 16-digit decimal-looking string is
interpreted as hex. Browser status uses the same identity through
`canonicalExtPanId` in the [field model](../src/js/tdash-device-fields.js).

| Layer | Instance evidence |
|---|---|
| OTBR CLI | Snapshot `extPanId`, or cached Thread network info |
| OTBR REST | Snapshot `extPanId`, or cached active dataset |
| HA Matter WS | Snapshot `extendedPanId`, or cached Matter topology |
| Eve | Processed snapshot `extPanId` |
| mDNS `br` / `thread` | MeshCoP border-router `xp.hex`; one instance for the scope file |
| mDNS `matter` / `hap` | No internal evidence; operator value or unknown |

Final collector snapshots have a sibling `.network.json` scope with provenance
`observed`, `operator`, or `unknown`. Observed evidence wins over an operator
`--ext-pan-id` or `TD_EXT_PAN_ID`; a disagreement is logged. Missing both is
not a collection error. The [data-directory guide](codebase_datadirectory.md)
describes the sidecar and digest. Offline merge chooses only the first observed
scope in source-priority order; operator and unknown scopes never select the
merge output network. When an observed output identity exists, snapshots with
a different scoped identity, internally conflicting scopes, and invalid or
digest-mismatched sidecars are excluded with counts and reasons in the merge
report. Operator scopes can be checked against an observed output identity but
cannot select one. A missing sidecar is treated as unknown, not excluded. The
selected instance and provenance appear in the report and dashboard status.

That exclusion applies to offline merge, not to browser dataset assembly. A
browser recipe can display records from different known instances; the view
status reports `Network instance: mixed` rather than rejecting the dataset.

## Identity

Canonical identity values are normalized as trimmed, lowercase text. Empty
values, the all-zero extended-address placeholder, and the IPv6 unspecified
address (`::`, including equivalent expanded forms) are not valid identities.
Unspecified OMR values remain visible in source data but are not indexed for
device correlation.

The principal identities are:

1. `extAddress` (`extaddr`, `extMacAddr`, and `Extended MAC` aliases)
2. `omrIpv6Address` (`omrIpv6Addr` and `omr_ipv6_addr` aliases)
3. `matterFabricNode` (validated fabric/node composite)
4. `rloc16` (`RLOC16` alias)

Automatic merging first collects eligible extended-address, OMR and Matter
matches together. Only when that stage has no compatible match does it consider
RLOC16. A successful stronger match does not absorb an unrelated RLOC-only row.
RLOC16 is partition-scoped and can change; conflicting concrete extended
addresses never merge, including under an explicit browser `by-rloc16` recipe.

Candidate consistency is checked against the incoming row and between existing
candidates. If the remaining candidates are incompatible, all existing rows
and the incoming row remain separate. `_merge_identity_ambiguity` conflicts and
collision diagnostics distinguish this outcome from successful coalescing;
RLOC16 cannot bypass it. Provenance lists only accepted contributions.

Eligible keys are retained in `_merge_identity_keys` in stable first-seen
order, using extended address/OMR/Matter/RLOC16 order for each contribution.
Earlier accepted OMR and RLOC observations remain indexed even when source
authority retains another scalar value. Unidentified merged rows have an
explicit empty key list. Imported key metadata is not correlation evidence.
Generated `found-...` addresses, all-zero addresses and unspecified OMR
addresses remain source data but are not indexed.

Matter identity accepts `matterId` as two 16-digit hex components separated by
`-`, direct `compressedFabricId`/`fabricId` plus `nodeId` (also under `matter`),
and operational mDNS service properties. Components must be valid unsigned
hex values; full-width 64-bit identifiers should be supplied as hex strings,
not unsafe browser numbers. Invalid identifiers remain visible but are not keys.

Matter operational mDNS records can share an OMR address while representing
different fabric/node identities:

- `strict-omr` is the default. It merges the shared OMR record and preserves
  distinct observed identities in `_mdns_aliases`.
- `composite-guard` prevents an OMR-only merge when
  fabric/node composites conflict. A matching concrete extended address remains
  the strong-anchor exception for multi-fabric observations. Different OMR
  observations alone do not make candidates incompatible.

## Merge Stages

1. [merge_dataset.py](../src/merge_dataset.py) loads the catalog-selected layer
  files, validates their network scopes, extracts records, and sorts sources
  using the catalog authority table.
2. [merge_policy_identity.py](../src/merge_policy_identity.py) normalizes and
  indexes identity candidates; [merge_dataset.py](../src/merge_dataset.py)
  dispatches the record merge and handles cross-source orchestration.
3. [merge_policy_relationship.py](../src/merge_policy_relationship.py) handles
  routes, children, neighbors, and addresses;
  [merge_policy_mdns.py](../src/merge_policy_mdns.py) handles mDNS-specific
  precedence and aliases. Shared value and conflict primitives live in
  [td_record_merge.py](../src/td_record_merge.py).
4. [merge_report.py](../src/merge_report.py) builds the output, viability
  assessment, and report; [merge_dataset.py](../src/merge_dataset.py) retains
  the command surface and output sequencing.

## Merge Strategies

The offline command accepts:

- `merge`: source-priority sort followed by identity-aware record merge.
- `none`: normalize and concatenate selected records without identity matching.

Browser datasets use `none`, `by-rloc16`, or `by-identity`, selected by
the catalog's dataset recipe. `by-rloc16` does not acquire automatic stronger
identity matching. Browser `none` uses the first loaded recipe file, whereas
Python `none` concatenates all selected files. Python command viability and
reports still use identity-merged rows even when its output is pass-through.
Source extraction, network-scope exclusions, label-map enrichment, progressive
fetching and adaptor-only relationship rows remain native wrapper policies.
Add or change a recipe only in
[td-dataset-manifest.json](../src/td-dataset-manifest.json); `/api/catalog`
serves it. Regenerate the bundled browser fallback with
`python3 script/build_dataset_catalog.py` and restart the server after editing
the manifest. This single-file source-of-truth change assumes its snapshot
filenames are already registered for `/api/data/`; new filenames also need
server action registration and a data producer, as described in the
[data request flow](codebase_webpage_web_server_data_flow.md#data-request-flow).

## Source Authority

The catalog's `authority.sourceDefaults` maps snapshot filenames to ranks.
`rosterPolicy.fields` supplies per-field `sources` ranks, projected as
`fieldOverrides` without changing the stored roster policy. The
[Python authority resolver](../src/td_source_authority.py) and
[browser merge](../src/js/tdash-merge.js) read the catalog authority. Generic
dataset merges order sources by `sourceDefaults`, then retain the first
non-empty value; later incompatible values become conflicts. For example,
`td-otbr-cli-meshdiag-topology.json` has source rank 98 and
`td-otbr-restapi-devices-fetch.json` has rank 86: for a conflicting non-empty
generic `extAddress`, the CLI meshdiag value remains in the merged record.
Health roster selection instead uses `rosterPolicy.fields` ranks for a field
when provided, falling back to the source default otherwise. For that same
`extAddress` pair the roster ranks are 2 and 3, respectively, so the REST
devices-fetch observation wins in the health roster. The live ranks and
overrides belong to the [catalog](../src/td-dataset-manifest.json), not this
example; canonical field naming does not imply value authority.

Equal-priority and unknown sources retain caller order. Domain handlers can
apply more specific policies for routes, relationships, sequence numbers, and
mDNS observation recency.

Topology metric display is a later browser-only projection, not a change to
these merge rules. Dataset assembly retains the relationship observations;
adaptors canonicalize local copies and carry finite child/neighbor margin, RSSI,
and error-rate measurements into emitted edges and tooltips. Composite child
enrichment is parent- and RLOC16-scoped, guarded by concrete extended-address
agreement, and does not synthesize an unmatched child edge. Explicit neighbor
observations keep their router-neighbor category. The
[adaptor projection helpers](../src/js/tdash-adaptor-shared.js) and
[edge presentation](../src/js/tdash-topology-utils.js) own this boundary; they
do not change Python persistence, source authority, or browser row merging.

## Field and Relationship Merge

- Empty incoming values do not replace useful existing values.
- Empty existing values can be filled by a useful incoming value.
- Different non-empty generic values keep the higher-priority value and append
  a conflict.
- Nested objects merge recursively through field handlers.
- Routes, children, and router neighbors use domain identities instead of
  blindly appending arrays.
- Route sequence comparison handles 8-bit wraparound and partition context.
- mDNS observations use timestamp and event precedence where available.

Preferred names are independent from value precedence: an OTBR REST camelCase
field name can be canonical while a richer OTBR CLI observation supplies the
retained value.

## Thread Version and EUI

`threadVersion` is the decoded Thread protocol version (`1.1`, `1.2`, `1.3`,
or `1.4`). `threadVersionDecimal` preserves the numeric protocol encoding from
CLI `ver:<decimal>` text or TLV 24. The CLI token `ver:` is parser input only;
it is never a record key. OTBR REST uses `eui` and numeric `threadVersion` on
the current wire contract; the collector preserves the number as
`threadVersionDecimal` and emits the decoded `threadVersion`.

Source-specific input adapters may translate legacy TLV spellings such as
`eui64` and diagnostic `version`, but the shared field model does not make
`ver` or generic `version` aliases. The generic device-record `version` field
is reserved for the existing Matter record-version fact. `threadStackVersion`
is a separate Thread stack/build string, and `vendorSwVersion` is firmware or
application software version. A source without an observed decimal does not
receive a fabricated `threadVersionDecimal`; unsupported decimals are retained
and decode to `Unknown`.

`eui` is the canonical EUI field; `eui64` and `EUI64` are input aliases only.
It is identity data distinct from `extAddress` and is not an extended-address
substitute in merge identity.

When canonical and source-alias values coexist, canonical values win. Different
non-empty values are retained as bounded `_merge_conflicts` entries with
`path`, `current`, and `incoming` fields.

## FTD and REED Capability

Collectors remain the owners of persisted role facts. Their source-specific
enrichment and snapshot behavior are unchanged by the browser resolver; cached
files are not migrated. Generic merging retains ordinary source priority,
explicit booleans, provenance, and persisted conflicts.

In the browser, [resolveIsReed](../src/js/tdash-device-fields.js) applies one
source-independent decision to the post-merge record: an explicit boolean
`isReed` wins. Otherwise, the fallback requires `mode.device` to be `FTD` and
either a nonempty `role` equal to `child`, or an empty role with effective
`isRouter` and `isBorderRouter` both false. Missing, null, and non-boolean
`isReed` values do not count as true. `type`, `routingRole`, `role: "reed"`,
`mode.device: "REED"`, router-eligibility aliases, filenames, and dataset
identity do not independently qualify a device.

The fallback is a presentation compatibility heuristic, not a new collector
fact or proof of network-wide capability. It does not synthesize `isReed` into
raw payloads, merged rows, details source records, or cached snapshots. Resolved
values may appear in projections and topology presentation. Neither FTD mode,
child RLOC16, nor Thread-version fields fabricate `isRouter` or
`isBorderRouter`.

## Provenance and Conflicts

### Values and domain authority

- Missing, null, empty strings, objects and arrays are empty; false and zero
  are data. Scalars retain the highest-priority non-empty observation and
  objects recursively fill missing fields. Concrete device labels and
  addresses can replace generated placeholders.
- Generic arrays use stable structural unions. Object-key order is
  insignificant, array order is significant, and booleans do not equal numbers
  at any nesting depth. Address arrays accept only trimmed non-empty strings.
  Atomic TLV request/response pairs are not unioned.
- Children, child tables and neighbors remain separate, owner-scoped
  collections. Concrete extended address wins over unique safe RLOC matching;
  anonymous entries survive. Metrics retain source-priority first-nonempty
  authority, with bounded typed conflicts for disagreements.
- Routes use owner-scoped valid route ID (including zero), endpoints, concrete
  extended address, then RLOC16. Known conflicting owner/entry partitions are
  rejected; unknown partitions are not fabricated mismatches.
- A newer 8-bit route sequence replaces the entire container, even when its
  route list is empty. A known sequence wins over a missing sequence in either
  arrival direction. Equal or both-missing sequences enrich matching entries
  and union identifiable routes. Exactly half-range-separated sequences
  (for example 100/228) are ambiguous in both directions: retain the base
  sequence and route set, enriching only matching entries. No stale route is
  attributed to a newer sequence.
- mDNS fields use timestamp precedence, then add/update/remove event priority
  for equal known timestamps. Without comparable timestamps, existing
  non-empty values remain primary. Service-info completion recurses through
  nested objects; canonical OMR/server fields and stable aliases are preserved
  without replacing unrelated device facts.

These rules intentionally change older merged views: safe correlation can
retain more rows; stronger matches can leave RLOC-only information separate;
newer empty routes can remove older routes; known route sequences reject
unsequenced enrichment; Python child metrics no longer prefer incoming
non-empty values; and generic-array differences alone no longer add conflicts.
Source snapshots remain unchanged.

Merged records retain contributing filenames:

```json
{
  "_source_files": [
    "td-otbr-cli-networkdiag-fetch-all.json",
    "td-otbr-restapi-diagnostics-fetch-all.json"
  ]
}
```

Sources are processed in descending priority, preserving caller order on ties.
Output uses first-created surviving-row order, not a global identity sort.
Relationships, provenance, identity keys and conflicts retain first-seen order.

Conflicts retain the path and both typed JSON-compatible values, including
browser booleans, numbers and nested structures rather than display strings.
Consumers format values only at display boundaries. Conflicts use recursive
type-aware duplicate suppression and are bounded to 20 entries per merged
record, including imported entries:

```json
{
  "_merge_conflicts": [
    {"path": "mode.device", "current": "FTD", "incoming": "MTD"}
  ]
}
```

The [shared fixture](../tests/fixtures/device_merge_contract.json) executes the
actual automatic strategy in Python and Node, compares canonical rows without
sorting away array order or removing identity metadata, and also checks browser
dataset assembly. Explicit recipes and pass-through selection have native
wrapper tests rather than misleading cross-runtime strategy labels.

## Offline Merge Command

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data merge-dataset
```

The default selected inputs are the OTBR CLI, OTBR REST, and mDNS `mergeGroups`
declared in the [catalog](../src/td-dataset-manifest.json); the command reads
those groups through [merge_dataset.py](../src/merge_dataset.py). Missing
candidate files are skipped. The network
dataset and static label map are optional supporting references. A successful
result still requires at least one loaded record with a viable extended
address, OMR address, or RLOC16 identity.

Useful options:

```bash
# Explicit input directory and report
PYTHONPATH=src python3 -m td_cli --datadir ./data merge-dataset \
  --base-dir ./data --report-file td-merge-report.json

# Include optional groups/files or exclude a default file
PYTHONPATH=src python3 -m td_cli --datadir ./data merge-dataset \
  --include-groups eve system \
  --exclude-files td-otbr-restapi-diagnostics.json

# Preserve separate Matter fabric/node identities
PYTHONPATH=src python3 -m td_cli --datadir ./data merge-dataset \
  --matter-identity-mode composite-guard
```

Relative input selections are resolved against `--base-dir`; output, report,
dataset reference, and label-map paths are resolved through the effective data
directory unless an absolute path is supplied.

## Exit Codes

| Code | Meaning |
|---:|---|
| 0 | Merge completed with viable identity-bearing output |
| 3 | Runtime/write failure or no viable identities |
| 4 | Required explicitly selected input is missing |
| 5 | Invalid JSON, option value, or payload shape |

See [Merge Troubleshooting](merge_troubleshooting.md), [Dashboard UI Fields](dashboard_ui_fields.md), and [Data Directory Model](codebase_datadirectory.md).