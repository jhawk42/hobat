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
`--ext-pan-id` or `HOBAT_EXT_PAN_ID`; a disagreement is logged. Missing both
is not a collection error. The [data-directory guide](codebase_datadirectory.md)
describes the sidecar and digest. Offline merge chooses the first observed
scope in source-priority order, then an operator scope if none was observed.
Known cross-instance snapshots, internally conflicting scopes, and invalid or
digest-mismatched sidecars are excluded with counts and reasons in the merge
report. A missing sidecar is treated as unknown, not excluded. The selected
instance and provenance appear in the report and dashboard status.

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
3. `rloc16` (`RLOC16` alias)

RLOC16 is partition-scoped and can change. Extended address is the preferred
stable device identity. Merge candidates that connect separate existing
records are coalesced deterministically and the identity collision is reported.

Matter operational mDNS records can share an OMR address while representing
different fabric/node identities:

- `strict-omr` is the default. It merges the shared OMR record and preserves
  distinct observed identities in `_mdns_aliases`.
- `composite-guard` prevents an OMR-only merge when
  `FabricID_compressed` plus `NodeID` differ.

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
the catalog's dataset recipe. Add or change a recipe only in
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

## Provenance and Conflicts

Merged records retain contributing filenames:

```json
{
  "_source_files": [
    "td-otbr-cli-networkdiag-fetch-all.json",
    "td-otbr-restapi-diagnostics-fetch-all.json"
  ]
}
```

Conflicts retain the path and both JSON-compatible values. They are
deduplicated in stable order and bounded to 20 entries per merged record:

```json
{
  "_merge_conflicts": [
    {"path": "mode.device", "current": "FTD", "incoming": "MTD"}
  ]
}
```

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