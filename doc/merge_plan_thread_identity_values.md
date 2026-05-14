# Merge plan for Thread Node identity value information

The dashboard and Python merge pipeline support canonical identity matching across these fields:

- `rloc16`
- `extaddr`, `extAddress`, and `Extended MAC` as one canonical `extaddr` identity
- `omr_ipv6_addr`

## Supported dashboard merge strategies:

- `none`: pass loaded JSON through without dashboard row merging
- `by-rloc16`: merge rows only when `rloc16` matches
- `by-identity`: merge rows when any canonical identity matches in this order of use: `rloc16`, canonical `extaddr`, `omr_ipv6_addr`

## Merge normalization rules:

- identity values are trimmed and compared case-insensitively
- empty identifiers are ignored
- non-empty existing values are preserved during merge; conflicting incoming non-empty values are recorded as merge conflicts instead of overwriting the existing value
- merged rows and merged Python records retain source provenance in `_source_files`
