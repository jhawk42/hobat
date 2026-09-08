# Merge Thread Device Information

Hobat merges complementary OTBR CLI, OTBR REST, mDNS, Eve, label-map, and other
records into preferred camelCase device records. Python owns offline merged
snapshots; equivalent browser contracts support multi-file dashboard datasets.

## Owners

| Runtime | Owners |
|---|---|
| Shared Python field model | `td_device_fields.py`, `td_json_key_normalizer.py` |
| Python merge policy | `td_device_merge.py`, `td_record_merge.py`, `merge_dataset.py` |
| Browser field model | `tdash-device-fields.js`, `tdash-utils.js` |
| Browser merge policy | `tdash-merge.js`, `tdash-dataset.js` |

Tests enforce shared preferred fields, aliases, identity keys, placeholders,
source precedence, conflicts, and idempotence across the two runtimes.

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

## Merge Strategies

The offline command accepts:

- `merge`: source-priority sort followed by identity-aware record merge.
- `none`: normalize and concatenate selected records without identity matching.

Browser datasets use `none`, `by-rloc16`, or `by-identity`, selected by
`DATASET_REGISTRY`.

## Source Precedence

Higher priority sources are processed first. Generic fields retain the first
non-empty value; later incompatible values become conflicts.

| Priority | Source |
|---:|---|
| 101 | Static device label map |
| 100-95 | OTBR CLI fetch-all, multicast, meshdiag, neighbor/child tables, router table |
| 90-84 | OTBR REST diagnostic, mesh-diagnostic, and device snapshots |
| 60 | Processed Eve topology |
| 50-47 | mDNS thread, border-router, HAP, and Matter snapshots |

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

The default selected inputs are the configured OTBR CLI, OTBR REST, and mDNS
groups in `merge_dataset.py`. Missing candidate files are skipped. The network
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