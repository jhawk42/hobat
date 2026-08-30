# Merge Troubleshooting

Use the unified CLI from the repository root:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data merge-dataset
```

Add `--debug` before `merge-dataset` for dispatcher logging and use
`--report-file` to retain merge statistics.

## Confirm Effective Inputs

```bash
find data -maxdepth 1 -type f -name '*.json' -printf '%f\n' | sort

PYTHONPATH=src python3 -m td_cli --datadir ./data merge-dataset \
  --base-dir ./data \
  --report-file td-merge-report.json
```

`--datadir` selects the cache/output directory. `--base-dir` selects the
directory used to resolve relative input filenames. In normal use both point to
the same directory.

Missing default candidate files are skipped. A filename explicitly selected
through `--include-files` is required and returns exit code 4 when absent.

## No Viable Output (Exit 3)

The merge can write an output and still return 3 when no resulting record has a
usable `extAddress`, `omrIpv6Address`, or `rloc16`.

```bash
jq '[.[] | select((.extAddress // "") != "" or (.omrIpv6Address // "") != "" or (.rloc16 // "") != "")] | length' \
  data/td-merged-topology-all.json
```

Check that at least one selected source contains device records rather than only
transport metadata or an empty collection.

## Invalid Payload (Exit 5)

Validate source JSON and top-level shapes:

```bash
for file in data/*.json; do
  jq empty "$file" || echo "invalid: $file"
done
```

Use `--exclude-files NAME` to isolate a suspect default source. Field aliases
are normalized automatically; an invalid structural type can still fail a
domain merge handler.

## Missing Explicit Input (Exit 4)

Confirm spelling and resolution:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data merge-dataset \
  --base-dir ./data --include-files custom-snapshot.json
```

Absolute paths remain absolute. Relative include/exclude names are source
filenames under `--base-dir`.

## Unexpected Device Coalescing

Inspect canonical identities and provenance:

```bash
jq '.[] | {extAddress, omrIpv6Address, rloc16, sources: ._source_files}' \
  data/td-merged-topology-all.json
```

RLOC16 is not globally stable. Prefer extended address when diagnosing an
identity collision. For Matter records that share an OMR address but have
different fabric/node identities, compare both supported modes:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data merge-dataset \
  --matter-identity-mode composite-guard \
  --output td-merged-topology-composite-guard.json
```

The default `strict-omr` mode records distinct Matter observations in
`_mdns_aliases`; `composite-guard` keeps incompatible fabric/node identities in
separate records.

## Unexpected Field Value

Source precedence keeps the first useful value after priority ordering. Inspect
the record's provenance and conflict list:

```bash
jq '.[] | select(._merge_conflicts) |
  {extAddress, rloc16, sources: ._source_files, conflicts: ._merge_conflicts}' \
  data/td-merged-topology-all.json
```

The preferred camelCase field name does not imply that the value came from the
REST source. Field-name authority and value-source precedence are separate.

## Missing Labels

The static label map is an optional reference. Validate its shape and address
spelling:

```bash
jq empty data/td-static-extaddr-device-label.json

PYTHONPATH=src python3 -m td_cli --datadir ./data merge-extaddr \
  --read-extaddr eeeaffeaffeaffe1
```

Add or update one label:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data merge-extaddr \
  --update-extaddr eeeaffeaffeaffe1 \
  --device-label "Office Sensor"
```

## Compare Merge and Pass-Through

Pass-through mode is useful for separating input-selection problems from
identity merge behavior:

```bash
PYTHONPATH=src python3 -m td_cli --datadir ./data merge-dataset \
  --merge-strategy none \
  --output td-merged-topology-unmerged.json
```

If records appear in pass-through output but not as expected in merged output,
inspect canonical identities, source priority, `_merge_conflicts`, and the
optional report.

## Tests

Run the merge and field-contract tests through pytest rather than invoking
historical phase scripts directly:

```bash
python3 -m pytest -q tests/test_merge_dataset*.py tests/test_td_device*.py tests/test_td_record_merge.py
```

The full offline suite is:

```bash
python3 -m pytest -q
```

See [Merge Thread Device Information](merge_thread_device_info.md) and [Data Directory Model](codebase_datadirectory.md).