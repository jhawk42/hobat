# Merge plan for Thread Node identity value information

The dashboard and Python merge pipeline support canonical identity matching across these fields:

- `rloc16`
- `extaddr`, `extAddress`, and `Extended MAC` as one canonical `extaddr` identity
- `omr_ipv6_addr`

## Supported dashboard merge strategies:

- `none`: pass loaded JSON through without dashboard row merging
- `by-rloc16`: merge rows only when `rloc16` matches
- `by-identity`: merge rows when any canonical identity matches in this order of use: canonical `extaddr`, `omr_ipv6_addr`, `rloc16`

## How `by-identity` merge works:

1. **Collect identity values** — for each incoming record, extract up to three canonical identifiers:
   - `extaddr`: first non-empty value found among the aliases `extaddr`, `extAddress`, `Extended MAC`, lowercased and trimmed
   - `omr_ipv6_addr`: lowercased and trimmed
   - `rloc16`: lowercased and trimmed
2. **Find candidate nodes** — look up each identity value in the existing index (`by_extaddr`, `by_omr`, `by_rloc16`). All matching node IDs are collected as candidates.
3. **Merge or create**:
   - If no candidates match, a new node is created for the record.
   - If one or more candidates match, they are merged into the lowest-ID node. Any identity collisions (multiple existing nodes matched) are recorded.
4. **Index update** — after merge, all three identity values of the active node are (re-)indexed so future records can match on any of them.
5. **Field merge rules** — non-empty existing values are preserved; a conflicting non-empty incoming value is appended to `_merge_conflicts` rather than overwriting.

## Merge normalization rules:

- identity values are trimmed and compared case-insensitively
- empty identifiers are ignored
- non-empty existing values are preserved during merge; conflicting incoming non-empty values are recorded as merge conflicts instead of overwriting the existing value
- merged rows and merged Python records retain source provenance in `_source_files`
